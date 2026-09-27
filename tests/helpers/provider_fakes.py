"""Scripted provider HTTP and loop doubles for the plan-04 provider tests.

FakeHttp stands in for ``urllib.request.urlopen``: it routes each request by
URL path to a queue of scripted replies (the last reply repeats) and records
every request (method, url, path, headers, JSON body, timeout). claude_loop
and provider_catalog both reach ``urllib.request.urlopen`` by attribute
access, so ``patch_urlopen(fake)`` serves the preflight probes and the chat
stream alike. Unlike plan 02's helpers.fake_provider.FakeUrlopen, every
probe answer is scripted, so a test can make /api/ps report the model as
not loaded or make /api/chat answer 404.
"""
from __future__ import annotations

import email.message
import io
import json
import struct
import threading
import urllib.error
import urllib.parse
import zlib
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from unittest import mock

URLOPEN_TARGET = "vmd_ai_runtime.claude_loop.urllib.request.urlopen"
DIGEST = "8eeb52dfb3bb9aefdf9d1ef24b3bdbcfbe82238798c4b918278320b6fcef18fe"


class FakeResponse:
    """Enough of http.client.HTTPResponse for urllib callers."""

    def __init__(self, url: str, status: int, content_type: str, body: bytes) -> None:
        self.url = url
        self.status = status
        self.code = status
        self.headers = email.message.Message()
        self.headers["Content-Type"] = content_type
        self._buf = io.BytesIO(body)

    def read(self, amt: Optional[int] = None) -> bytes:
        if amt is None or amt < 0:
            return self._buf.read()
        return self._buf.read(amt)

    def readline(self, limit: int = -1) -> bytes:
        return self._buf.readline(limit)

    def __iter__(self):
        return iter(self._buf.readline, b"")

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self.url

    def info(self) -> email.message.Message:
        return self.headers

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def ndjson(events: Iterable[Dict[str, Any]]) -> bytes:
    """Ollama /api/chat stream body: one JSON object per line."""
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


def sse(events: Iterable[Any]) -> bytes:
    """SSE body: each event becomes ``data: <json>`` plus a blank line.
    A str event is written as-is (use "[DONE]" for the OpenAI end marker)."""
    parts: List[str] = []
    for event in events:
        payload = event if isinstance(event, str) else json.dumps(event)
        parts.append("data: " + payload + "\n\n")
    return "".join(parts).encode("utf-8")


Reply = Union[Tuple[int, bytes, str], BaseException]


class FakeHttp:
    """Path-routed urlopen double. Unscripted paths fail loudly."""

    def __init__(self) -> None:
        self.routes: Dict[str, List[Reply]] = {}
        self.requests: List[Dict[str, Any]] = []

    def add(
        self,
        path: str,
        body: Any,
        *,
        status: int = 200,
        content_type: str = "application/json",
    ) -> "FakeHttp":
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.routes.setdefault(path, []).append((int(status), bytes(body), content_type))
        return self

    def fail(self, path: str, exc: BaseException) -> "FakeHttp":
        self.routes.setdefault(path, []).append(exc)
        return self

    def ollama_ok(self, model: str = "qwen3.8:27b", *, loaded: bool = True,
                  digest: str = DIGEST) -> "FakeHttp":
        """Script a healthy preflight: /api/version, and /api/ps with or
        without ``model`` loaded."""
        self.add("/api/version", {"version": "0.12.0"})
        models = [{"name": model, "model": model, "digest": digest}] if loaded else []
        self.add("/api/ps", {"models": models})
        return self

    def urlopen(self, req: Any, timeout: Optional[float] = None, **_kw: Any) -> FakeResponse:
        if isinstance(req, str):
            url, method, data, headers = req, "GET", None, {}
        else:
            url, method, data = req.full_url, req.get_method(), req.data
            headers = dict(req.header_items())
        path = urllib.parse.urlsplit(url).path
        body: Any = None
        if data:
            try:
                body = json.loads(data)
            except Exception:
                body = data
        self.requests.append({
            "method": method, "url": url, "path": path,
            "headers": headers, "body": body, "timeout": timeout,
        })
        queue = self.routes.get(path)
        if not queue:
            raise AssertionError(f"FakeHttp: no reply scripted for {method} {path}")
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, BaseException):
            raise reply
        status, payload, content_type = reply
        if status >= 400:
            hdrs = email.message.Message()
            hdrs["Content-Type"] = content_type
            raise urllib.error.HTTPError(url, status, "scripted error", hdrs, io.BytesIO(payload))
        return FakeResponse(url, status, content_type, payload)

    def bodies(self, path: str) -> List[Any]:
        return [r["body"] for r in self.requests if r["path"] == path]

    def paths(self) -> List[str]:
        return [r["path"] for r in self.requests]


def patch_urlopen(fake: FakeHttp):
    """Context manager that routes every urllib.request.urlopen call to ``fake``."""
    return mock.patch(URLOPEN_TARGET, new=fake.urlopen)


class NullQueue:
    """session_queue stand-in; the loop only hands it to the bridge."""

    def push(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}


class RecordingBridge:
    """execute_tool stand-in with the six legacy keywords. Records each call
    and returns scripted results in order (the last one repeats)."""

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None) -> None:
        self.results = list(results or [{"ok": True, "output": "", "error": ""}])
        self.calls: List[Dict[str, Any]] = []

    def execute_tool(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(dict(kwargs))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return dict(result)


def run_loop(loop: Any, prompt: str = "hi", *, bridge: Any = None, ctx: Any = None,
             system_prompt: str = "sys", cancel_event: Optional[threading.Event] = None,
             prior_messages: Optional[List[Dict[str, Any]]] = None) -> str:
    """Call ClaudeToolLoop.run with test doubles; passes ctx only when given."""
    kwargs: Dict[str, Any] = dict(
        prompt=prompt,
        system_prompt=system_prompt,
        tool_bridge=bridge if bridge is not None else RecordingBridge(),
        session_id="sess_test",
        session_queue=NullQueue(),
        cancel_event=cancel_event or threading.Event(),
        on_chunk=lambda text: None,
        prior_messages=prior_messages,
    )
    if ctx is not None:
        kwargs["ctx"] = ctx
    return loop.run(**kwargs)


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def rgb_png(rows: List[bytes], width: int, height: int) -> bytes:
    """Encode raw RGB rows (no filter byte) as an 8-bit, filter-0 PNG."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw, 6))
        + _png_chunk(b"IEND", b"")
    )


def solid_png(width: int, height: int, rgb: Tuple[int, int, int]) -> bytes:
    row = bytes(rgb) * width
    return rgb_png([row] * height, width, height)
