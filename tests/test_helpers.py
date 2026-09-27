from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime import RuntimeApp, create_server  # noqa: E402


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RuntimeHarness:
    def __init__(self, store_dir: str):
        self.app = RuntimeApp(store_dir=store_dir, provider_mode="mock")
        self.server = None
        self.port = 0
        self.thread = None
        self.inprocess = False
        try:
            self.server = create_server(self.app, host="127.0.0.1", port=get_free_port())
            self.port = int(self.server.server_port)
            # stop() waits for serve_forever to notice shutdown(); the default
            # 0.5 s poll made every stop that slow.
            self.thread = threading.Thread(target=self.server.serve_forever,
                                           kwargs={"poll_interval": 0.05}, daemon=True)
        except OSError:
            # Some CI/sandbox environments deny local socket binds.
            self.inprocess = True

    def start(self) -> None:
        if self.inprocess:
            return
        self.thread.start()
        for _ in range(60):
            if self.health().get("ok"):
                return
            time.sleep(0.05)
        raise RuntimeError("runtime health check timed out")

    def stop(self) -> None:
        if self.inprocess:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def health(self):
        if self.inprocess:
            return {"ok": True, "mode": "inprocess"}
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def rpc(self, method: str, params: dict, token: str = "", request_id: str = "1") -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        if self.inprocess:
            return self.app.handle_rpc(payload, session_token=token)

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/rpc",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Session-Token": token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
