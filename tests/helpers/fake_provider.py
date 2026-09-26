"""Fakes for driving ClaudeToolLoop with no network (plan 02).

FakeUrlopen stands in for urllib.request.urlopen. It answers the Ollama
probe paths (/api/version, /api/ps, /api/tags, /api/show) with canned JSON,
so these tests keep passing when plan 04 adds the preflight calls, and it
serves every other request (the model call) from a scripted list whose
items are response bodies (bytes) or exceptions to raise.
"""
from __future__ import annotations

import copy
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

PROBE_PATHS = ("/api/version", "/api/ps", "/api/tags", "/api/show")
DIGEST = "sha256:" + "0" * 64

Scripted = Union[bytes, BaseException]


class FakeResponse:
    """Enough of http.client.HTTPResponse for the three streamers."""

    def __init__(self, body: bytes, status: int = 200):
        self._buf = io.BytesIO(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._buf.close()
        return False

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def readline(self) -> bytes:
        return self._buf.readline()

    def __iter__(self):
        return iter(self._buf.readlines())

    def close(self) -> None:
        self._buf.close()


def _probe_body(path: str, model: str) -> Dict[str, Any]:
    if path == "/api/version":
        return {"version": "0.12.3"}
    if path in ("/api/ps", "/api/tags"):
        return {"models": [{"name": model, "model": model, "digest": DIGEST, "size": 1}]}
    return {
        "capabilities": ["completion", "tools", "vision", "thinking"],
        "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 131072},
    }


class FakeUrlopen:
    """Callable replacement for urllib.request.urlopen that records every request."""

    def __init__(self, chat: Sequence[Scripted], *, model: str = "qwen3.8:27b"):
        self.chat: List[Scripted] = list(chat)
        self.model = model
        self.requests: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def chat_requests(self) -> List[Dict[str, Any]]:
        """The model calls only (probe requests left out)."""
        return [r for r in self.requests if not r["probe"]]

    def __call__(self, req, timeout=None, *args, **kwargs):
        if isinstance(req, urllib.request.Request):
            url, data, method = req.full_url, req.data, req.get_method()
        else:
            url, data, method = str(req), None, "GET"
        path = urllib.parse.urlsplit(url).path
        probe = path in PROBE_PATHS
        record = {
            "url": url,
            "path": path,
            "method": method,
            "timeout": timeout,
            "probe": probe,
            "body": json.loads(data) if data else None,
        }
        with self._lock:
            self.requests.append(record)
            if probe:
                return FakeResponse(json.dumps(_probe_body(path, self.model)).encode("utf-8"))
            if not self.chat:
                raise AssertionError(f"unexpected extra request: {method} {url}")
            item = self.chat.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)


# --- response bodies -------------------------------------------------------

def ndjson(*events: Dict[str, Any]) -> bytes:
    return b"".join(json.dumps(e).encode("utf-8") + b"\n" for e in events)


def ollama_text(text: str, *, done_reason: str = "stop") -> bytes:
    return ndjson(
        {"message": {"role": "assistant", "content": text}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason},
    )


def ollama_tool_call(name: str, arguments: Dict[str, Any], *, text: str = "",
                     done_reason: str = "stop") -> bytes:
    call = {"function": {"name": name, "arguments": arguments}}
    return ndjson(
        {"message": {"role": "assistant", "content": text, "tool_calls": [call]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason},
    )


def sse(*events: Dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)


_MESSAGE_START = {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}}


def anthropic_text(text: str, *, stop_reason: str = "end_turn") -> bytes:
    return sse(
        _MESSAGE_START,
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )


def anthropic_tool_use(tool_id: str, name: str, partial_json: str, *,
                       stop_reason: str = "tool_use") -> bytes:
    return sse(
        _MESSAGE_START,
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": tool_id, "name": name}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": partial_json}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 50}},
        {"type": "message_stop"},
    )


def anthropic_error(error_type: str, message: str) -> bytes:
    return sse(_MESSAGE_START, {"type": "error", "error": {"type": error_type, "message": message}})


def http_error(url: str, code: int, body: Any,
               headers: Optional[Dict[str, str]] = None) -> urllib.error.HTTPError:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(url, code, "error", dict(headers or {}), io.BytesIO(raw))


# --- loop drivers ----------------------------------------------------------

def tool_use(tool_id: str, name: str, **tool_input: Any) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": dict(tool_input)}


def scripted_call(turns: Sequence[Any], seen: Optional[List[Any]] = None) -> Callable[..., Tuple[str, List[Dict[str, Any]]]]:
    """A 4-argument stand-in for ClaudeToolLoop._call, set on an instance.

    Each item of ``turns`` is ``(text, tool_blocks)`` or an exception to
    raise. After the script ends every call returns ``("", [])``. ``seen``
    collects a deep copy of the messages each call received.
    """
    items = iter(list(turns))

    def _call(messages, system_prompt, on_text, should_cancel):
        if seen is not None:
            seen.append(copy.deepcopy(messages))
        item = next(items, ("", []))
        if isinstance(item, BaseException):
            raise item
        text, blocks = item
        if text:
            on_text(text)
        return text, [dict(b) for b in blocks]

    return _call


class SpyBridge:
    """A strict six-keyword bridge (like the benchmark's) that records calls."""

    def __init__(self, results: Optional[Sequence[Dict[str, Any]]] = None):
        self.calls: List[Dict[str, Any]] = []
        self._results = list(results or [])

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event):
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name,
                           "tool_input": tool_input})
        if self._results:
            return self._results.pop(0)
        return {"ok": True, "output": "ok", "error": ""}


class StatusRecorder:
    """Duck-typed RunRecorder that remembers the chat id and end status."""

    runs_root = None

    def __init__(self):
        self.chat_id: Optional[str] = None
        self.status: Optional[str] = None
        self.commands: List[str] = []

    def start_task(self, prompt, *, chat_id="", model="", cwd=None):
        self.chat_id = chat_id
        return "task"

    def record_vmd_command(self, command, **kwargs):
        self.commands.append(command)

    def record_snapshot(self, **kwargs):
        return None

    def end_task(self, status="complete"):
        self.status = status
        return "task"


def run_loop(loop, *, prompt: str = "hello", bridge: Any = None,
             cancel_event: Optional[threading.Event] = None, ctx: Any = None,
             chunks: Optional[List[str]] = None) -> str:
    """Call loop.run with test defaults; ``chunks`` collects on_chunk text."""
    return loop.run(
        prompt=prompt,
        system_prompt="SYS",
        tool_bridge=bridge if bridge is not None else SpyBridge(),
        session_id="sess_test",
        session_queue=None,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
        on_chunk=chunks.append if chunks is not None else (lambda _chunk: None),
        ctx=ctx,
    )


def event_kinds(events: List[Dict[str, Any]]) -> List[Tuple[str, str, Optional[str]]]:
    """(role, type, metadata.kind) for each on_event item."""
    return [(e["role"], e["type"], (e.get("metadata") or {}).get("kind")) for e in events]
