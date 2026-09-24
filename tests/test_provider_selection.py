from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.app import RuntimeApp  # noqa: E402


class ProviderSelectionTests(unittest.TestCase):
    def test_explicit_anthropic_direct_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = RuntimeApp(store_dir=tmp, provider_mode="anthropic-direct")
            self.assertEqual(app.provider_name, "anthropic-direct")

    def test_default_prefers_openrouter_when_present(self):
        old_openrouter = os.getenv("OPENROUTER_API_KEY")
        old_auth = os.getenv("ANTHROPIC_AUTH_TOKEN")
        old_anthropic = os.getenv("ANTHROPIC_API_KEY")
        try:
            os.environ["OPENROUTER_API_KEY"] = "dummy"
            os.environ["ANTHROPIC_API_KEY"] = "dummy2"
            if "ANTHROPIC_AUTH_TOKEN" in os.environ:
                del os.environ["ANTHROPIC_AUTH_TOKEN"]
            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "openrouter")
        finally:
            if old_openrouter is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = old_openrouter
            if old_auth is None:
                os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            else:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = old_auth
            if old_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic

    def test_default_ignores_short_anthropic_auth_token(self):
        old_openrouter = os.getenv("OPENROUTER_API_KEY")
        old_auth = os.getenv("ANTHROPIC_AUTH_TOKEN")
        old_anthropic = os.getenv("ANTHROPIC_API_KEY")
        try:
            os.environ.pop("OPENROUTER_API_KEY", None)
            os.environ["ANTHROPIC_AUTH_TOKEN"] = "short-placeholder"
            os.environ["ANTHROPIC_API_KEY"] = "dummy-anthropic-key"
            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "anthropic-direct")
        finally:
            if old_openrouter is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = old_openrouter
            if old_auth is None:
                os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            else:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = old_auth
            if old_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic

    def test_default_uses_auth_token_when_openrouter_like(self):
        old_openrouter = os.getenv("OPENROUTER_API_KEY")
        old_auth = os.getenv("ANTHROPIC_AUTH_TOKEN")
        old_anthropic = os.getenv("ANTHROPIC_API_KEY")
        try:
            os.environ.pop("OPENROUTER_API_KEY", None)
            os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-or-v1-" + ("a" * 48)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp)
                self.assertEqual(app.provider_name, "openrouter")
        finally:
            if old_openrouter is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = old_openrouter
            if old_auth is None:
                os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            else:
                os.environ["ANTHROPIC_AUTH_TOKEN"] = old_auth
            if old_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic

    def test_anthropic_direct_without_key_emits_provider_error(self):
        old_key = os.getenv("ANTHROPIC_API_KEY")
        try:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with tempfile.TemporaryDirectory() as tmp:
                app = RuntimeApp(store_dir=tmp, provider_mode="anthropic-direct")
                start = app.handle_rpc({
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "session.start",
                    "params": {"cwd": ".", "ui_mode": "qt", "client_version": "t", "platform": "x"},
                })
                sid = start["result"]["session_id"]
                token = start["result"]["session_token"]
                chat_id = start["result"]["chat_id"]

                sent = app.handle_rpc({
                    "jsonrpc": "2.0",
                    "id": "2",
                    "method": "chat.send",
                    "params": {
                        "session_id": sid,
                        "chat_id": chat_id,
                        "text": "hello",
                        "model": "claude-sonnet-4-5",
                        "mode": "work",
                        "conversation_mode": "local_first",
                    },
                }, session_token=token)
                self.assertIn("result", sent)

                # Wait briefly for worker thread to emit error event.
                import time
                time.sleep(0.08)
                polled = app.handle_rpc({
                    "jsonrpc": "2.0",
                    "id": "3",
                    "method": "chat.events.poll",
                    "params": {"session_id": sid, "after_seq": 0, "limit": 50},
                }, session_token=token)
                events = polled["result"]["events"]
                self.assertTrue(any(e.get("role") == "error" for e in events))
        finally:
            if old_key is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
