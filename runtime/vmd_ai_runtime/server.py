from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Tuple

from .errors import RpcError


class RpcHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass, app):
        super().__init__(server_address, RequestHandlerClass)
        self.app = app


class RpcRequestHandler(BaseHTTPRequestHandler):
    server: RpcHTTPServer

    def _send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"ok": True})
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def do_POST(self):
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
        result = self.server.app.handle_rpc(body, session_token=session_token)
        self._send_json(result, status=200)

    def log_message(self, format, *args):
        return


def create_server(app, host: str = "127.0.0.1", port: int = 8765) -> RpcHTTPServer:
    normalized = str(host or "127.0.0.1").strip().lower()
    if normalized not in ("127.0.0.1", "localhost"):
        raise RpcError("BIND_FORBIDDEN", "Runtime may only bind to loopback addresses", {"host": host})
    bind_host = "127.0.0.1"
    return RpcHTTPServer((bind_host, int(port)), RpcRequestHandler, app)
