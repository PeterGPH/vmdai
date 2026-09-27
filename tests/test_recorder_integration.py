"""
Phase 2 — RuntimeApp + RunRecorder integration tests.

These run the live RuntimeApp through a chat.send (with the provider's
_call patched to return deterministic turns) and verify that on-disk
artifacts appear in the right place:

  * Per-task directory under ``<cwd>/.vmdai_runs/`` with manifest +
    transcript + snapshots.
  * Two consecutive chat.sends produce two isolated task directories.
  * ``VMD_AI_RECORDER=off`` disables the recorder cleanly.
  * Empty cwd falls back to ``~/.vmdai/runs/`` (option c in the plan).
  * The shared ClaudeToolLoop does not leak a recorder binding into
    the next chat.send (prev_recorder restoration).
"""
from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import List, Tuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _make_app(store_dir, provider_mode="openrouter", model="x"):
    from vmd_ai_runtime.app import RuntimeApp
    from vmd_ai_runtime.claude_loop import ClaudeToolLoop
    app = RuntimeApp(store_dir=store_dir, provider_mode=provider_mode)
    # Force a real ClaudeToolLoop so we can drive its _call.
    if app.claude_loop is None:
        app.claude_loop = ClaudeToolLoop(
            provider_name="openrouter",
            api_key="sk-or-faked",
            model=model,
        )
    return app


def _drive_call(turns: List[Tuple[str, List[dict]]]):
    """Closure that yields successive (text, tool_blocks) for _call."""
    idx = {"i": 0}

    def fake_call(self_loop, messages, system_prompt,
                  on_text, should_cancel):
        i = idx["i"]
        idx["i"] += 1
        text, tool_blocks = turns[i] if i < len(turns) else ("", [])
        if text:
            on_text(text)
        return text, tool_blocks

    return fake_call


def _stub_bridge_execute(self_bridge, *, session_id, tool_call_id,
                         tool_name, tool_input, session_queue,
                         cancel_event, **kw):
    """Drop-in for VmdToolBridge.execute_tool — canned successful result."""
    if tool_name == "capture_vmd_snapshot":
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        return {
            "ok": True, "output": "snapshot ok", "error": "",
            "image_b64": base64.b64encode(png).decode("ascii"),
            "image_mime": "image/png",
        }
    return {"ok": True, "output": "ok", "error": ""}


def _start_session(app, cwd: str) -> dict:
    """Helper: drive session.start RPC and return the response result."""
    payload = {
        "jsonrpc": "2.0", "id": "req_s",
        "method": "session.start",
        "params": {"cwd": cwd, "ui_mode": "panel",
                   "client_version": "test", "platform": "test"},
    }
    resp = app.handle_rpc(payload)
    return resp["result"]


def _send_chat(app, session_id, session_token, prompt) -> str:
    """Drive chat.send and return its request_id."""
    payload = {
        "jsonrpc": "2.0", "id": "req_c",
        "method": "chat.send",
        "params": {
            "session_id": session_id,
            "chat_id": "",
            "text": prompt,
            "model": "",
            "mode": "work",
            "conversation_mode": "local_first",
        },
    }
    resp = app.handle_rpc(payload, session_token=session_token)
    return resp["result"]["request_id"]


def _wait_for_active_request_to_clear(app, session_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = app.sessions.get(session_id)
        if state and state.active_request is None:
            return
        time.sleep(0.02)
    raise AssertionError("active_request never cleared")


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

class RecorderIntegrationTests(unittest.TestCase):

    def setUp(self):
        # Two tempdirs: one for chat store, one for the workdir/cwd
        self.store_tmp = tempfile.TemporaryDirectory()
        self.cwd_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.store_tmp.cleanup)
        self.addCleanup(self.cwd_tmp.cleanup)

    def _setup_session(self, app):
        result = _start_session(app, self.cwd_tmp.name)
        return result["session_id"], result["session_token"]

    def test_one_chat_send_creates_one_task_directory(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        from vmd_ai_runtime.tool_bridge import VmdToolBridge

        app = _make_app(self.store_tmp.name)
        sid, token = self._setup_session(app)

        turns = [
            ("Loading.", [{
                "type": "tool_use", "id": "tc_1",
                "name": "run_vmd_command",
                "input": {"command": "mol new 1ubq.pdb",
                          "rationale": "load"},
            }]),
            ("Done.", []),
        ]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ), mock.patch.object(
            VmdToolBridge, "execute_tool", new=_stub_bridge_execute,
        ):
            _send_chat(app, sid, token, "load and check")
            _wait_for_active_request_to_clear(app, sid)

        runs_dir = Path(self.cwd_tmp.name) / ".vmdai_runs"
        self.assertTrue(runs_dir.is_dir(),
                        f"runs dir missing: {runs_dir}")
        tasks = list(runs_dir.iterdir())
        self.assertEqual(len(tasks), 1)
        # Transcript carries the model's Tcl
        transcript = (tasks[0] / "transcript.tcl").read_text()
        self.assertIn("mol new 1ubq.pdb", transcript)
        # Manifest reports the right prompt + completion status
        import json
        m = json.loads((tasks[0] / "manifest.json").read_text())
        self.assertEqual(m["prompt"], "load and check")
        self.assertEqual(m["status"], "complete")

    def test_two_consecutive_chat_sends_isolate_tasks(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        from vmd_ai_runtime.tool_bridge import VmdToolBridge

        app = _make_app(self.store_tmp.name)
        sid, token = self._setup_session(app)

        # Drive A then B; each emits one command then ends.
        turn_pairs_a = [
            ("a1", [{"type": "tool_use", "id": "tA",
                     "name": "run_vmd_command",
                     "input": {"command": "mol new a.pdb"}}]),
            ("done", []),
        ]
        turn_pairs_b = [
            ("b1", [{"type": "tool_use", "id": "tB",
                     "name": "run_vmd_command",
                     "input": {"command": "mol new b.pdb"}}]),
            ("done", []),
        ]

        with mock.patch.object(
            VmdToolBridge, "execute_tool", new=_stub_bridge_execute,
        ):
            with mock.patch.object(
                ClaudeToolLoop, "_call", new=_drive_call(turn_pairs_a),
            ):
                _send_chat(app, sid, token, "task A")
                _wait_for_active_request_to_clear(app, sid)
            with mock.patch.object(
                ClaudeToolLoop, "_call", new=_drive_call(turn_pairs_b),
            ):
                _send_chat(app, sid, token, "task B")
                _wait_for_active_request_to_clear(app, sid)

        runs_dir = Path(self.cwd_tmp.name) / ".vmdai_runs"
        tasks = list(runs_dir.iterdir())
        self.assertEqual(len(tasks), 2)
        # Tasks may not sort by creation order (same-second hex suffix
        # is random). Identify each by its manifest's `prompt` field.
        import json
        by_prompt = {}
        for t in tasks:
            m = json.loads((t / "manifest.json").read_text())
            by_prompt[m["prompt"]] = (t / "transcript.tcl").read_text()
        a_text = by_prompt["task A"]
        b_text = by_prompt["task B"]
        # Each task only contains its own command.
        self.assertIn("a.pdb", a_text)
        self.assertNotIn("b.pdb", a_text)
        self.assertIn("b.pdb", b_text)
        self.assertNotIn("a.pdb", b_text)

    def test_opt_out_via_env_var(self):
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        from vmd_ai_runtime.tool_bridge import VmdToolBridge

        app = _make_app(self.store_tmp.name)
        sid, token = self._setup_session(app)

        turns = [("plain", [])]
        with mock.patch.dict(os.environ, {"VMD_AI_RECORDER": "off"}):
            with mock.patch.object(
                ClaudeToolLoop, "_call", new=_drive_call(turns),
            ), mock.patch.object(
                VmdToolBridge, "execute_tool", new=_stub_bridge_execute,
            ):
                _send_chat(app, sid, token, "no recording please")
                _wait_for_active_request_to_clear(app, sid)

        runs_dir = Path(self.cwd_tmp.name) / ".vmdai_runs"
        self.assertFalse(
            runs_dir.exists(),
            f"runs_dir should not exist with opt-out: {runs_dir}",
        )

    def test_recorder_unbound_after_run(self):
        """The shared self.claude_loop should NOT carry a recorder
        between chat.sends."""
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        from vmd_ai_runtime.tool_bridge import VmdToolBridge

        app = _make_app(self.store_tmp.name)
        sid, token = self._setup_session(app)

        turns = [("hi", [])]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ), mock.patch.object(
            VmdToolBridge, "execute_tool", new=_stub_bridge_execute,
        ):
            _send_chat(app, sid, token, "test")
            _wait_for_active_request_to_clear(app, sid)

        # After the run, the shared loop's recorder must be None again
        # (or whatever prev_recorder was — None in this test setup).
        self.assertIsNone(app.claude_loop.recorder)

    def test_empty_cwd_falls_back_to_home_runs(self):
        """Recorder should still write to ~/.vmdai/runs/ if state.cwd
        is empty — option (c) of the plan: never silently lose data."""
        from vmd_ai_runtime.claude_loop import ClaudeToolLoop
        from vmd_ai_runtime.tool_bridge import VmdToolBridge

        app = _make_app(self.store_tmp.name)
        # Manually create a session with an empty cwd.
        state = app.sessions.create_session(cwd="", chat_id="chat_test")
        # We have to populate session_token for verify() to pass,
        # but session.start does this for us above. Reuse that path:
        # easier — drive _build_recorder_for_session directly.
        rec = app._build_recorder_for_session(state)
        self.assertIsNotNone(rec)
        # Must NOT be under cwd (cwd is empty)
        self.assertNotEqual(rec.runs_root.parent, Path(self.cwd_tmp.name))
        # Must end with .vmdai/runs
        self.assertTrue(
            str(rec.runs_root).endswith("runs"),
            f"unexpected runs_root: {rec.runs_root}",
        )


if __name__ == "__main__":
    unittest.main()
