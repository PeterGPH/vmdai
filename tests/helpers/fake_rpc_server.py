"""A small JSON-RPC server for the Tcl transport tests (P06-T03).

``FakeRpcServer(handler)`` serves ``POST /rpc`` and ``GET /health`` on
127.0.0.1:<ephemeral> in a thread and records every request. The handler is
called as ``handler(method, params, headers)`` and returns either a dict with
a ``result`` or an ``error`` key (wrapped in a JSON-RPC envelope) or a
``Reply`` that is sent as-is. ``health`` is a dict, a ``Reply`` or a callable
returning either. ``ensure_ascii=False`` sends raw UTF-8 JSON, like a runtime
without §2c's ASCII-only wire.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Reply:
    body: bytes = b""
    status: int = 200
    content_type: str = "application/json; charset=utf-8"
    delay_s: float = 0.0


@dataclass
class Recorded:
    path: str
    method: str
    params: Dict[str, Any]
    headers: Dict[str, str]
    body: bytes


Handler = Callable[[str, Dict[str, Any], Dict[str, str]], Any]


def default_health() -> Dict[str, Any]:
    return {"ok": True, "pid": os.getpid(), "version": "0.3.0", "protocol": 2}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class FakeRpcServer:
    def __init__(self, handler: Optional[Handler] = None, *, ensure_ascii: bool = True,
                 health: Any = None) -> None:
        self.handler = handler or (lambda method, params, headers: {"result": {}})
        self.ensure_ascii = ensure_ascii
        self.health = health if health is not None else default_health()
        self.requests: List[Recorded] = []
        self._lock = threading.Lock()
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.server_port)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def calls(self, method: str) -> List[Recorded]:
        with self._lock:
            return [r for r in self.requests if r.method == method]

    def _encode(self, payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=self.ensure_ascii).encode("utf-8")

    def _make_handler(self):
        fake = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _send(self, reply: Reply) -> None:
                if reply.delay_s:
                    time.sleep(reply.delay_s)
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", reply.content_type)
                    self.send_header("Content-Length", str(len(reply.body)))
                    self.end_headers()
                    self.wfile.write(reply.body)
                except OSError:
                    pass  # the client gave up (timeout test)

            def _record(self, method: str, params: Dict[str, Any], body: bytes) -> None:
                with fake._lock:
                    fake.requests.append(Recorded(self.path, method, params,
                                                  dict(self.headers.items()), body))

            def do_GET(self):
                self._record("", {}, b"")
                health = fake.health() if callable(fake.health) else fake.health
                if not isinstance(health, Reply):
                    health = Reply(fake._encode(health))
                self._send(health)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except ValueError:
                    payload = {}
                method = str(payload.get("method", ""))
                params = payload.get("params") or {}
                self._record(method, params, body)
                answer = fake.handler(method, params, dict(self.headers.items()))
                if not isinstance(answer, Reply):
                    envelope = {"jsonrpc": "2.0", "id": payload.get("id")}
                    envelope.update(answer)
                    answer = Reply(fake._encode(envelope))
                self._send(answer)

            def log_message(self, format, *args):
                return

        return _Handler

    def __enter__(self) -> "FakeRpcServer":
        self._server = _Server(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
