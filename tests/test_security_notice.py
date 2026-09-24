"""
Tests for the one-time security notice surfaced at session start.

The model can call arbitrary Tcl in the live VMD process, which means
shell-equivalent access. Until a real safe-interpreter sandbox lands,
the only mitigation is making sure users *see* this trust boundary
before they send their first prompt.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.app import RuntimeApp  # noqa: E402


def _start_session(app):
    return app.handle_rpc({
        "jsonrpc": "2.0", "id": "1", "method": "session.start",
        "params": {"cwd": "/tmp"},
    })["result"]


def _poll(app, sid, token):
    return app.handle_rpc({
        "jsonrpc": "2.0", "id": "2", "method": "chat.events.poll",
        "params": {"session_id": sid, "after_seq": 0, "limit": 50},
    }, session_token=token)["result"]


class SecurityNoticeTests(unittest.TestCase):

    def _make_app(self):
        return RuntimeApp(store_dir=tempfile.mkdtemp(prefix="vmdai_sec_"),
                          provider_mode="mock")

    def test_session_start_emits_security_notice(self):
        app = self._make_app()
        sess = _start_session(app)
        events = _poll(app, sess["session_id"], sess["session_token"])["events"]

        notices = [
            e for e in events
            if e.get("metadata", {}).get("notice") == "tcl_trust_boundary"
        ]
        self.assertEqual(len(notices), 1, f"expected exactly one Tcl-trust notice, got: {notices}")
        notice = notices[0]
        self.assertEqual(notice["role"], "system")
        self.assertEqual(notice["type"], "message")
        # Sanity-check the warning words are actually in the text — drift
        # in the message body should be deliberate, not silent.
        text = notice["text"].lower()
        self.assertIn("tcl", text)
        self.assertTrue(any(word in text for word in ("shell", "trust", "security")))

    def test_lifecycle_event_still_emitted(self):
        """The new notice doesn't replace the existing session_started lifecycle."""
        app = self._make_app()
        sess = _start_session(app)
        events = _poll(app, sess["session_id"], sess["session_token"])["events"]

        lifecycle = [e for e in events if e.get("type") == "lifecycle"]
        self.assertTrue(any(e["text"] == "session_started" for e in lifecycle))


if __name__ == "__main__":
    unittest.main()
