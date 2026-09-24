from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.protocol import validate_rpc_payload, validate_method_params  # noqa: E402
from vmd_ai_runtime.errors import RpcError  # noqa: E402


class ProtocolValidationTests(unittest.TestCase):
    def test_session_start_params(self):
        parsed = validate_rpc_payload({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "session.start",
            "params": {"cwd": ".", "ui_mode": "qt", "client_version": "t", "platform": "x"},
        })
        params = validate_method_params(parsed["method"], parsed["params"])
        self.assertEqual(params["ui_mode"], "qt")

    def test_invalid_conversation_mode(self):
        with self.assertRaises(RpcError):
            validate_method_params("chat.send", {
                "session_id": "s",
                "chat_id": "c",
                "text": "hi",
                "model": "m",
                "mode": "work",
                "conversation_mode": "invalid",
            })

    def test_unknown_method(self):
        with self.assertRaises(RpcError):
            validate_method_params("no.such.method", {})


if __name__ == "__main__":
    unittest.main()
