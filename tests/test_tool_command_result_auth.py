"""
Tests for the auth/binding rules on tool.command_result.

Closes a gap where any local process able to guess a tool_call_id could
resolve another session's pending tool with arbitrary content. The handler
now requires:

  1. A valid X-Session-Token for the supplied session_id.
  2. The tool_call_id must correspond to a pending bridge call.
  3. The pending call must belong to the *same* session.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.app import RuntimeApp  # noqa: E402
from vmd_ai_runtime.events import EventQueue  # noqa: E402


def _make_app() -> RuntimeApp:
    return RuntimeApp(store_dir=tempfile.mkdtemp(prefix="vmdai_auth_"), provider_mode="mock")


def _start_session(app: RuntimeApp) -> dict:
    resp = app.handle_rpc(
        {"jsonrpc": "2.0", "id": "1", "method": "session.start",
         "params": {"cwd": "/tmp"}}
    )
    return resp["result"]


def _post_tool_result(app, session_id, token, tool_call_id, *,
                     ok=True, output="ok", error="", snapshot_file=""):
    return app.handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": "result",
            "method": "tool.command_result",
            "params": {
                "session_id": session_id,
                "tool_call_id": tool_call_id,
                "ok": ok,
                "output": output,
                "error": error,
                "snapshot_file": snapshot_file,
            },
        },
        session_token=token,
    )


def _register_pending(app: RuntimeApp, session_id: str, tool_call_id: str,
                      tool_name: str = "run_vmd_command") -> threading.Event:
    """Spawn an execute_tool that registers a pending call with the bridge.

    Returns a threading.Event the test can use to terminate the pending wait
    early (so the test's daemon thread exits cleanly even if no resolve fires).
    """
    cancel = threading.Event()
    state = app.sessions.get(session_id)
    queue: EventQueue = state.queue if state else EventQueue()

    def _wait():
        app.tool_bridge.execute_tool(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input={"command": "test"},
            session_queue=queue,
            cancel_event=cancel,
            timeout=2.0,
        )

    thread = threading.Thread(target=_wait, daemon=True)
    thread.start()
    # Give the bridge a beat to register the pending entry.
    for _ in range(20):
        if app.tool_bridge.get_pending_session(tool_call_id) is not None:
            break
        time.sleep(0.02)
    return cancel


class ToolCommandResultTokenAuth(unittest.TestCase):

    def test_missing_token_is_rejected(self):
        app = _make_app()
        sess = _start_session(app)

        resp = _post_tool_result(app, sess["session_id"], "", "tc_x")
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], "AUTH_FAILED")

    def test_wrong_token_is_rejected(self):
        app = _make_app()
        sess = _start_session(app)

        resp = _post_tool_result(app, sess["session_id"], "not-the-real-token", "tc_x")
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], "AUTH_FAILED")

    def test_unknown_session_id_is_rejected(self):
        app = _make_app()
        # Don't even start a session — supply a bogus session_id.
        resp = _post_tool_result(app, "sess_nope", "any-token", "tc_x")
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], "AUTH_FAILED")


class ToolCommandResultPendingBinding(unittest.TestCase):

    def test_unknown_tool_call_id_is_rejected(self):
        """Even with a perfectly valid session+token, an unregistered
        tool_call_id is refused — closes the transcript-injection gap."""
        app = _make_app()
        sess = _start_session(app)
        resp = _post_tool_result(
            app, sess["session_id"], sess["session_token"],
            "tc_definitely_not_pending",
        )
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], "TOOL_CALL_UNKNOWN")

    def test_pending_owned_by_other_session_is_rejected(self):
        """The killer test: session B cannot resolve session A's pending call.

        Without per-call session binding, B could write whatever output it
        liked into A's tool result and steer A's agent loop.
        """
        app = _make_app()
        sess_a = _start_session(app)
        sess_b = _start_session(app)
        self.assertNotEqual(sess_a["session_id"], sess_b["session_id"])

        cancel = _register_pending(app, sess_a["session_id"], "tc_secret")
        try:
            # Verify the pending entry exists and is bound to A.
            self.assertEqual(
                app.tool_bridge.get_pending_session("tc_secret"),
                sess_a["session_id"],
            )

            # B tries to resolve A's pending call using B's own token.
            resp = _post_tool_result(
                app, sess_b["session_id"], sess_b["session_token"],
                "tc_secret",
                ok=True,
                output="forged-output",
            )
            self.assertIn("error", resp)
            self.assertEqual(resp["error"]["code"], "AUTH_FAILED")

            # The pending entry must still be there, untouched.
            self.assertEqual(
                app.tool_bridge.get_pending_session("tc_secret"),
                sess_a["session_id"],
            )
        finally:
            cancel.set()

    def test_owning_session_can_resolve(self):
        """Positive case: the same session that owns the pending call
        resolves successfully."""
        app = _make_app()
        sess = _start_session(app)

        cancel = _register_pending(app, sess["session_id"], "tc_legit")
        try:
            resp = _post_tool_result(
                app, sess["session_id"], sess["session_token"],
                "tc_legit",
                ok=True,
                output="real-output",
            )
            self.assertIn("result", resp)
            self.assertTrue(resp["result"]["ok"])
            self.assertTrue(resp["result"]["resolved"])
        finally:
            cancel.set()


class ToolBridgePendingLookup(unittest.TestCase):
    """Direct unit tests on VmdToolBridge.get_pending_session()."""

    def test_get_pending_session_returns_none_for_unknown_id(self):
        app = _make_app()
        self.assertIsNone(app.tool_bridge.get_pending_session("nope"))

    def test_get_pending_session_returns_session_id_for_pending(self):
        app = _make_app()
        sess = _start_session(app)
        cancel = _register_pending(app, sess["session_id"], "tc_lookup")
        try:
            self.assertEqual(
                app.tool_bridge.get_pending_session("tc_lookup"),
                sess["session_id"],
            )
        finally:
            cancel.set()

    def test_pending_cleared_after_resolve(self):
        app = _make_app()
        sess = _start_session(app)
        cancel = _register_pending(app, sess["session_id"], "tc_cleared")
        try:
            # Resolve via the bridge directly; after the call returns the
            # pending entry should be gone (execute_tool's finally removes it).
            self.assertEqual(
                app.tool_bridge.get_pending_session("tc_cleared"),
                sess["session_id"],
            )
            app.tool_bridge.resolve(
                "tc_cleared", {"ok": True, "output": "x", "error": ""}
            )
            # Give the waiter thread a moment to wake and clean up.
            for _ in range(50):
                if app.tool_bridge.get_pending_session("tc_cleared") is None:
                    break
                time.sleep(0.02)
            self.assertIsNone(app.tool_bridge.get_pending_session("tc_cleared"))
        finally:
            cancel.set()


if __name__ == "__main__":
    unittest.main()
