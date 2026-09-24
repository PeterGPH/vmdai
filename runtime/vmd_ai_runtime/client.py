from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict


class RuntimeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.base_url = f"http://{host}:{int(port)}"
        self.session_token = ""

    def rpc(self, method: str, params: Dict[str, Any], request_id: str = "1") -> Dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/rpc",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Session-Token": self.session_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def health(self) -> Dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
