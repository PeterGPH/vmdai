"""Replay fake for recorded provider streams (spec C9 "Replay fake").

A cassette is tests/cassettes/<provider>/<name>.json:

    {"meta": {"recorded_at", "provider", "server_version", "model",
              "model_digest", "synthetic"},
     "exchanges": [{"method", "path", "request_sha256", "status",
                    "content_type", "body_lines": [...]}]}

``use_cassette(provider, name)`` patches
``vmd_ai_runtime.claude_loop.urllib.request.urlopen`` (that is the global
``urllib.request.urlopen``, which claude_loop, provider.py and
provider_catalog all reach by attribute access) and serves the exchanges in
order. A method/path mismatch or an extra request fails the test even when
product code swallows the exception; an exchange left unconsumed fails it at
teardown. ``request_sha256`` is recorded for diagnosis and never asserted.
The conftest empties provider_catalog's caches before each test, so whether
a cassette's /api/version exchange is consumed never depends on test order.
"""
from __future__ import annotations

import contextlib
import email.message
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest import mock

CASSETTE_DIR = Path(__file__).resolve().parents[1] / "cassettes"
URLOPEN_TARGET = "vmd_ai_runtime.claude_loop.urllib.request.urlopen"
META_KEYS = ("recorded_at", "provider", "server_version", "model", "model_digest", "synthetic")
EXCHANGE_KEYS = ("method", "path", "request_sha256", "status", "content_type", "body_lines")


class CassetteError(AssertionError):
    """A request did not match the cassette, or exchanges were left over."""


def validate_cassette(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict) or set(data) != {"meta", "exchanges"}:
        raise CassetteError("a cassette has exactly the keys 'meta' and 'exchanges'")
    missing = [k for k in META_KEYS if k not in data["meta"]]
    if missing:
        raise CassetteError(f"cassette meta lacks {missing}")
    for i, ex in enumerate(data["exchanges"]):
        missing = [k for k in EXCHANGE_KEYS if k not in ex]
        if missing:
            raise CassetteError(f"exchange {i} lacks {missing}")
        if not isinstance(ex["body_lines"], list):
            raise CassetteError(f"exchange {i}: body_lines must be a list")


def load_cassette(provider: str, name: str) -> Dict[str, Any]:
    path = CASSETTE_DIR / provider / f"{name}.json"
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    validate_cassette(data)
    return data


def _body_bytes(lines: List[str]) -> bytes:
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def _request_parts(req: Any) -> Tuple[str, str, Optional[bytes]]:
    if isinstance(req, str):
        return "GET", req, None
    return req.get_method(), req.full_url, req.data


def _path_of(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return parts.path + ("?" + parts.query if parts.query else "")


class CassetteResponse:
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

    def __enter__(self) -> "CassetteResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


class CassettePlayer:
    def __init__(self, cassette: Dict[str, Any]) -> None:
        validate_cassette(cassette)
        self.cassette = cassette
        self.exchanges: List[Dict[str, Any]] = list(cassette["exchanges"])
        self.position = 0
        self.failures: List[str] = []
        self.requests: List[Dict[str, Any]] = []

    def _fail(self, message: str) -> None:
        self.failures.append(message)
        raise CassetteError(message)

    def urlopen(self, req: Any, timeout: Optional[float] = None, **_kw: Any) -> CassetteResponse:
        method, url, data = _request_parts(req)
        path = _path_of(url)
        body: Any = None
        if data:
            try:
                body = json.loads(data)
            except Exception:
                body = data
        self.requests.append({"method": method, "path": path, "body": body, "timeout": timeout})
        if self.position >= len(self.exchanges):
            self._fail(f"extra request {method} {path}: all {len(self.exchanges)} exchange(s) were already served")
        ex = self.exchanges[self.position]
        if ex["method"] != method or ex["path"] != path:
            self._fail(f"exchange {self.position}: expected {ex['method']} {ex['path']}, got {method} {path}")
        self.position += 1
        payload = _body_bytes(ex["body_lines"])
        status = int(ex["status"])
        if status >= 400:
            hdrs = email.message.Message()
            hdrs["Content-Type"] = ex["content_type"]
            raise urllib.error.HTTPError(url, status, "recorded error", hdrs, io.BytesIO(payload))
        return CassetteResponse(url, status, ex["content_type"], payload)

    def leftover(self) -> int:
        return len(self.exchanges) - self.position

    def assert_finished(self) -> None:
        if self.failures:
            raise CassetteError("; ".join(self.failures))
        if self.leftover():
            nxt = self.exchanges[self.position]
            raise CassetteError(
                f"{self.leftover()} exchange(s) left unconsumed; next is {nxt['method']} {nxt['path']}"
            )


@contextlib.contextmanager
def play(cassette: Dict[str, Any]) -> Iterator[CassettePlayer]:
    """Serve an in-memory cassette (tests of the fake, or edited copies)."""
    player = CassettePlayer(cassette)
    with mock.patch(URLOPEN_TARGET, new=player.urlopen):
        try:
            yield player
        except Exception as exc:
            if player.failures:
                raise CassetteError("; ".join(player.failures)) from exc
            if player.leftover() and not isinstance(exc, CassetteError):
                raise CassetteError(
                    f"{player.leftover()} exchange(s) left unconsumed while {exc!r} propagated"
                ) from exc
            raise
    player.assert_finished()


def use_cassette(provider: str, name: str):
    """Replay tests/cassettes/<provider>/<name>.json."""
    return play(load_cassette(provider, name))
