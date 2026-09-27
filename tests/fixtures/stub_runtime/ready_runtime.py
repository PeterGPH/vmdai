"""Stub runtime for the plugin launch tests (P06-T05).

Takes main.py's flags (--port 0 --announce --watch-stdin), serves GET /health
and the runtime.shutdown RPC on 127.0.0.1:<ephemeral>, and prints the
VMDAI_READY line. Switches (environment variables):

  STUB_NOISE=1        60 warning lines on stderr, then a partial line, then READY
  STUB_NO_READY=1     never print READY
  STUB_PROTOCOL=<n>   protocol in READY and /health (default 2)
  STUB_IGNORE_TERM=1  ignore SIGTERM, stdin EOF and runtime.shutdown
"""
import argparse
import json
import os
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--announce", action="store_true")
    parser.add_argument("--watch-stdin", action="store_true")
    args, _unknown = parser.parse_known_args()
    protocol = int(os.environ.get("STUB_PROTOCOL", "2"))
    stubborn = os.environ.get("STUB_IGNORE_TERM") == "1"
    token = secrets.token_hex(16)
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload, status=200):
            raw = json.dumps(payload).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                self._json({"ok": True, "pid": os.getpid(), "version": "0.3.0-stub",
                            "protocol": protocol})
            else:
                self._json({"ok": False}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            params = body.get("params") or {}
            if body.get("method") == "runtime.shutdown" and params.get("launch_token") == token:
                self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}})
                if not stubborn:
                    done.set()
                return
            self._json({"jsonrpc": "2.0", "id": body.get("id"),
                        "error": {"code": "METHOD_NOT_FOUND", "message": "stub", "data": {}}})

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if stubborn:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, lambda *_: done.set())
        if args.watch_stdin:
            def watch() -> None:
                sys.stdin.read()
                done.set()
            threading.Thread(target=watch, daemon=True).start()
    if os.environ.get("STUB_NOISE") == "1":
        for i in range(60):
            print(f"DeprecationWarning: noise line {i}", file=sys.stderr, flush=True)
        sys.stderr.write("UserWarning: a partial line with no newline ")
        sys.stderr.flush()
    if os.environ.get("STUB_NO_READY") != "1":
        ready = {"port": server.server_port, "pid": os.getpid(), "version": "0.3.0-stub",
                 "protocol": protocol, "launch_token": token}
        print("VMDAI_READY " + json.dumps(ready, separators=(",", ":")), flush=True)
    done.wait()
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
