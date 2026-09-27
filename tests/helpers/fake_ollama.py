"""Ollama stand-ins for runtime tests (plan 03).

FakeOllama answers the probe endpoints the runtime may call (/api/version,
/api/tags, /api/show, /api/ps) plus the OpenAI-style GET /v1/models, and
records every request as (monotonic time, method, path, body).
FakeOllamaServer serves one on a real 127.0.0.1 socket; FakeUrlopen serves
several to code that takes an injected ``urlopen``. stale_listener() and
closed_port() give the dead-server cases.

A model spec is a dict with optional keys: capabilities (list), context_length
(int), arch (str, default "qwen3"), size (int), thinking (any; copied into
/api/show as-is).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple


class FakeOllama:
    def __init__(self, models: Optional[Dict[str, Dict[str, Any]]] = None, version: str = "0.12.3",
                 loaded: Optional[List[str]] = None) -> None:
        self.models = dict(models or {})
        self.version = version
        self.loaded = list(loaded or [])
        self.requests: List[Tuple[float, str, str, Dict[str, Any]]] = []
        self._lock = threading.Lock()

    def paths(self) -> List[str]:
        with self._lock:
            return [path for _when, _method, path, _body in self.requests]

    @staticmethod
    def digest(name: str) -> str:
        return hashlib.sha256(name.encode("utf-8")).hexdigest()

    def _tag(self, name: str) -> Dict[str, Any]:
        spec = self.models.get(name, {})
        return {"name": name, "model": name, "size": int(spec.get("size", 1000)), "digest": self.digest(name)}

    def _show(self, name: str) -> Dict[str, Any]:
        spec = self.models[name]
        arch = str(spec.get("arch", "qwen3"))
        info: Dict[str, Any] = {"general.architecture": arch}
        if spec.get("context_length") is not None:
            info["%s.context_length" % arch] = spec["context_length"]
        show: Dict[str, Any] = {"capabilities": list(spec.get("capabilities", ["completion"])),
                                "model_info": info, "details": {"family": arch}}
        if "thinking" in spec:
            show["thinking"] = spec["thinking"]
        return show

    def handle(self, method: str, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        path = urllib.parse.urlsplit(path).path
        with self._lock:
            self.requests.append((time.monotonic(), method, path, body))
        if method == "GET" and path == "/api/version":
            return 200, {"version": self.version}
        if method == "GET" and path == "/api/tags":
            return 200, {"models": [self._tag(name) for name in self.models]}
        if method == "GET" and path == "/api/ps":
            return 200, {"models": [self._tag(name) for name in self.loaded]}
        if method == "POST" and path == "/api/show":
            name = str(body.get("model") or body.get("name") or "")
            if name not in self.models:
                return 404, {"error": "model '%s' not found" % name}
            return 200, self._show(name)
        if method == "GET" and path == "/v1/models":
            return 200, {"object": "list", "data": [{"id": name, "object": "model"} for name in self.models]}
        return 404, {"error": "not found"}


class FakeOllamaServer:
    """Serve a FakeOllama on 127.0.0.1:<ephemeral port>."""

    def __init__(self, fake: FakeOllama) -> None:
        self.fake = fake
        self.port = 0
        self.base_url = ""

    def __enter__(self) -> "FakeOllamaServer":
        fake = self.fake

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, payload: Dict[str, Any]) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                self._reply(*fake.handle("GET", self.path, {}))

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                self._reply(*fake.handle("POST", self.path, body if isinstance(body, dict) else {}))

            def log_message(self, *args: Any) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = int(self._httpd.server_address[1])
        self.base_url = "http://127.0.0.1:%d" % self.port
        # A short poll interval keeps shutdown() fast (the default 0.5 s would
        # add half a second to every test that uses a server; S9).
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


class _Response(io.BytesIO):
    def __init__(self, status: int, raw: bytes) -> None:
        super().__init__(raw)
        self.status = status


class FakeUrlopen:
    """A callable with urlopen's signature that routes by scheme://host:port.

    An unknown address raises URLError(ConnectionRefusedError), like a closed port.
    """

    def __init__(self, servers: Mapping[str, FakeOllama]) -> None:
        self.servers = {base.rstrip("/"): fake for base, fake in servers.items()}
        self.timeouts: List[Optional[float]] = []

    def __call__(self, request: Any, timeout: Optional[float] = None, **_kw: Any) -> _Response:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        parts = urllib.parse.urlsplit(url)
        self.timeouts.append(timeout)
        fake = self.servers.get("%s://%s" % (parts.scheme, parts.netloc))
        if fake is None:
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        data = getattr(request, "data", None)
        body = json.loads(data.decode("utf-8")) if data else {}
        method = request.get_method() if hasattr(request, "get_method") else "GET"
        status, payload = fake.handle(method, parts.path, body)
        raw = json.dumps(payload).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "HTTP %d" % status, {}, io.BytesIO(raw))
        return _Response(status, raw)


@contextlib.contextmanager
def stale_listener() -> Iterator[int]:
    """A port that accepts TCP connections but never answers (a stale tunnel)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    try:
        yield int(sock.getsockname()[1])
    finally:
        sock.close()


def closed_port() -> int:
    """A loopback port with nothing listening (connection refused)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port
