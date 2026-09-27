from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, List, Tuple

from .constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from .errors import RpcError


class RpcHTTPServer(ThreadingHTTPServer):
    # Request threads never keep the process alive and server_close() never
    # waits for them, so SIGTERM exits within 2 s while a handler is busy (S4).
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass, app):
        super().__init__(server_address, RequestHandlerClass)
        self.app = app


# HTTP 403 body for a bad Host or any Origin header (§2e).
_FORBIDDEN = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {
        "code": "FORBIDDEN",
        "message": "forbidden: requests must use Host 127.0.0.1:<port> or localhost:<port> and carry no Origin header",
        "data": {},
    },
}


class RpcRequestHandler(BaseHTTPRequestHandler):
    server: RpcHTTPServer

    def _send_json(self, payload: Any, status: int = 200) -> None:
        # ASCII-only JSON: every non-ASCII character travels as a \uXXXX
        # escape, so a client that decodes the body with the wrong charset
        # still gets the right text (defence in depth, §2c Wire encoding).
        raw = json.dumps(payload, ensure_ascii=True).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _request_allowed(self) -> bool:
        """Host/Origin check against DNS rebinding and cross-site POSTs (§2e).

        Host must be 127.0.0.1:<port> or localhost:<port> (case-insensitive),
        and there must be no Origin header at all: browsers send Origin on
        POST, while Tcl's http package and urllib never do.
        """
        if self.headers.get("Origin") is not None:
            return False
        host = str(self.headers.get("Host") or "").strip().lower()
        port = int(self.server.server_port)
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self._request_allowed():
            self._send_json(_FORBIDDEN, status=403)
            return
        if self.path == "/health":
            self._send_json({
                "ok": True,
                "pid": os.getpid(),
                "version": RUNTIME_VERSION,
                "protocol": RUNTIME_PROTOCOL,
            })
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def do_POST(self):
        if not self._request_allowed():
            self._send_json(_FORBIDDEN, status=403)
            return
        if self.path != "/rpc":
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": "INVALID_JSON",
                        "message": "invalid JSON request",
                        "data": {},
                    },
                },
                status=400,
            )
            return

        session_token = self.headers.get("X-Session-Token", "")
        after_reply: List[Callable[[], None]] = []
        result = self.server.app.handle_rpc(body, session_token=session_token,
                                            after_reply=after_reply)
        try:
            self._send_json(result, status=200)
            self.wfile.flush()
        finally:
            # Only now may runtime.shutdown start the exit: this thread is a
            # daemon, so an earlier exit could cut the reply off mid-write.
            # It still runs if the client already hung up.
            for action in after_reply:
                action()

    def log_message(self, format, *args):
        return


def create_server(app, host: str = "127.0.0.1", port: int = 8765) -> RpcHTTPServer:
    normalized = str(host or "127.0.0.1").strip().lower()
    if normalized not in ("127.0.0.1", "localhost"):
        raise RpcError("BIND_FORBIDDEN", "Runtime may only bind to loopback addresses", {"host": host})
    bind_host = "127.0.0.1"
    return RpcHTTPServer((bind_host, int(port)), RpcRequestHandler, app)
