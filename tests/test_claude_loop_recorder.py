"""
Phase 1 — ClaudeToolLoop recorder hook tests.

Validates that when a RunRecorder is wired into ClaudeToolLoop, every
chat.send produces the right per-task disk artifact, and that recorder
errors never break the agent loop.

Covers:
    no_recorder            · loop.run() behaves identically (backward compat)
    start_end_lifecycle    · start_task fires at entry, end_task at exit
    success_recorded       · successful run_vmd_command → record_vmd_command(ok=True)
    failure_recorded       · failed run_vmd_command → record_vmd_command(ok=False),
                             but the failed command does NOT appear in transcript.tcl
    snapshot_decoded       · capture_vmd_snapshot's image_b64 is base64-decoded
                             into image_bytes before reaching the recorder
    cancel_status          · cancel_event mid-turn → end_task(status='cancelled')
    exception_status       · _call raising → end_task(status='error') still fires
    recorder_error_swallowed · recorder.record raising does NOT propagate
"""
from __future__ import annotations

import base64
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeLoopError,
    ClaudeToolLoop,
)
from vmd_ai_runtime.recorder import RunRecorder  # noqa: E402


# ----------------------------------------------------------------------
# Stub bridge — captures tool calls, returns a canned successful result
# ----------------------------------------------------------------------

class _StubBridge:
    def __init__(self, fail_tool_ids=()):
        self.calls: List[Dict] = []
        self.fail_tool_ids = set(fail_tool_ids)

    def execute_tool(self, *, session_id, tool_call_id, tool_name,
                     tool_input, session_queue, cancel_event):
        self.calls.append({
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
        })
        if tool_call_id in self.fail_tool_ids:
            return {"ok": False, "output": "", "error": "stubbed failure"}
        if tool_name == "capture_vmd_snapshot":
            # Real PNG bytes encoded for the recorder path
            png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
            return {
                "ok": True,
                "output": "snapshot ok",
                "error": "",
                "image_b64": base64.b64encode(png).decode("ascii"),
                "image_mime": "image/png",
            }
        return {"ok": True, "output": "ok", "error": ""}


# ----------------------------------------------------------------------
# Helper: build a loop with a stubbed _call sequence
# ----------------------------------------------------------------------

def _drive_call(turns: List[Tuple[str, List[Dict]]]):
    """Closure that yields successive (text, tool_blocks) when _call fires."""
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


def _build_loop(recorder=None):
    return ClaudeToolLoop(
        provider_name="openrouter",
        api_key="sk-or-faked",
        model="anthropic/claude-sonnet-4.6",
        recorder=recorder,
    )


def _run(loop, prompt="hello", session_id="sess_x",
         cancel_event=None, bridge=None):
    return loop.run(
        prompt=prompt,
        system_prompt="be brief",
        tool_bridge=bridge or _StubBridge(),
        session_id=session_id,
        session_queue=None,
        cancel_event=cancel_event or threading.Event(),
        on_chunk=lambda s: None,
    )


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------

class NoRecorderBackwardCompatTests(unittest.TestCase):

    def test_no_recorder_no_disk_io(self):
        # With recorder=None the loop must complete normally and write
        # no files anywhere. Pin to a turn that emits text only.
        turns = [("hello world", [])]
        loop = _build_loop(recorder=None)
        with tempfile.TemporaryDirectory() as tmp:
            # cwd switching not needed; the recorder is the only thing
            # that would write here, and there isn't one.
            with mock.patch.object(
                ClaudeToolLoop, "_call", new=_drive_call(turns),
            ):
                text = _run(loop)
            # Nothing in the tmp dir
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(text, "hello world")


class RecorderLifecycleTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.recorder = RunRecorder.for_cwd(self.tmp.name)
        self.loop = _build_loop(recorder=self.recorder)

    def test_start_and_end_task_fire_around_a_simple_run(self):
        # Single text turn → no tool calls, completes cleanly.
        turns = [("Done.", [])]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            _run(self.loop, prompt="ping")
        # A task directory should exist with a complete manifest.
        tasks = list(self.recorder.runs_root.iterdir())
        self.assertEqual(len(tasks), 1, f"expected 1 task dir, got {tasks}")
        manifest = self.recorder.read_manifest(tasks[0].name)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["prompt"], "ping")
        self.assertEqual(manifest["chat_id"], "sess_x")
        self.assertEqual(manifest["model"],
                         "anthropic/claude-sonnet-4.6")

    def test_successful_run_vmd_command_is_recorded(self):
        turns = [
            ("Loading.", [{
                "type": "tool_use", "id": "tc_1",
                "name": "run_vmd_command",
                "input": {"command": "mol new 1ubq.pdb",
                          "rationale": "load test"},
            }]),
            ("Done.", []),
        ]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            _run(self.loop)
        task_id = list(self.recorder.runs_root.iterdir())[0].name
        transcript = self.recorder.read_transcript(task_id)
        self.assertIn("mol new 1ubq.pdb", transcript)
        # Rationale must surface as a comment line for human readers.
        self.assertIn("load test", transcript)
        manifest = self.recorder.read_manifest(task_id)
        self.assertEqual(manifest["successful_count"], 1)
        self.assertEqual(manifest["failed_count"], 0)

    def test_failed_run_vmd_command_counted_but_not_in_transcript(self):
        turns = [
            ("Try.", [{
                "type": "tool_use", "id": "tc_bad",
                "name": "run_vmd_command",
                "input": {"command": "mol_color ResName",
                          "rationale": "typo"},
            }]),
            ("Done.", []),
        ]
        bridge = _StubBridge(fail_tool_ids=("tc_bad",))
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            _run(self.loop, bridge=bridge)
        task_id = list(self.recorder.runs_root.iterdir())[0].name
        transcript = self.recorder.read_transcript(task_id)
        # Failed Tcl must NOT appear in the runnable artifact.
        self.assertNotIn("mol_color", transcript)
        manifest = self.recorder.read_manifest(task_id)
        self.assertEqual(manifest["successful_count"], 0)
        self.assertEqual(manifest["failed_count"], 1)
        # turn_count still increments so the audit trail is complete.
        self.assertEqual(manifest["turn_count"], 1)

    def test_snapshot_image_bytes_are_base64_decoded(self):
        turns = [
            ("Snap.", [{
                "type": "tool_use", "id": "tc_snap",
                "name": "capture_vmd_snapshot",
                "input": {"purpose": "verify"},
            }]),
            ("Done.", []),
        ]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            _run(self.loop)
        task_id = list(self.recorder.runs_root.iterdir())[0].name
        snap_dir = self.recorder.runs_root / task_id / "snapshots"
        snaps = list(snap_dir.iterdir())
        self.assertEqual(len(snaps), 1)
        # The image bytes on disk must start with the PNG magic — proves
        # base64 decoding actually happened and we didn't just write
        # the b64 string itself.
        first = snaps[0]
        self.assertEqual(first.suffix, ".png")
        self.assertEqual(first.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_cancel_mid_run_ends_with_status_cancelled(self):
        # Set up a cancel that fires on the first tool result.
        cancel = threading.Event()

        turns = [
            ("Working.", [{
                "type": "tool_use", "id": "tc_a",
                "name": "run_vmd_command",
                "input": {"command": "mol new x.pdb"},
            }]),
            ("More.", [{
                "type": "tool_use", "id": "tc_b",
                "name": "run_vmd_command",
                "input": {"command": "mol new y.pdb"},
            }]),
            ("Done.", []),
        ]

        def fake_call(self_loop, messages, system_prompt,
                      on_text, should_cancel):
            # Simulate cancel landing between turns
            if len([m for m in messages if m["role"] == "assistant"]) >= 1:
                cancel.set()
            return fake_call.driver(self_loop, messages, system_prompt,
                                    on_text, should_cancel)
        fake_call.driver = _drive_call(turns)

        with mock.patch.object(
            ClaudeToolLoop, "_call", new=fake_call,
        ):
            _run(self.loop, cancel_event=cancel)

        task_id = list(self.recorder.runs_root.iterdir())[0].name
        manifest = self.recorder.read_manifest(task_id)
        self.assertEqual(manifest["status"], "cancelled")

    def test_exception_in_provider_call_still_closes_task(self):
        def boom(self_loop, messages, system_prompt,
                 on_text, should_cancel):
            raise RuntimeError("network down")

        with mock.patch.object(ClaudeToolLoop, "_call", new=boom):
            with self.assertRaises(ClaudeLoopError):
                _run(self.loop)

        task_id = list(self.recorder.runs_root.iterdir())[0].name
        manifest = self.recorder.read_manifest(task_id)
        self.assertEqual(manifest["status"], "error")


class RecorderErrorIsolationTests(unittest.TestCase):
    """Failures inside the recorder must NOT break the chat loop."""

    def test_recorder_start_failure_does_not_stop_run(self):
        broken = mock.MagicMock(spec=RunRecorder)
        broken.runs_root = Path("/dev/null/nonexistent")
        broken.start_task.side_effect = RuntimeError("disk full")
        broken.record_vmd_command = mock.MagicMock()
        broken.end_task = mock.MagicMock()

        loop = _build_loop(recorder=broken)
        turns = [("ok", [])]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            text = _run(loop)
        # Run completed despite the recorder's start_task crashing.
        self.assertEqual(text, "ok")
        # end_task was still called (best-effort cleanup).
        broken.end_task.assert_called_once()

    def test_recorder_record_failure_does_not_stop_run(self):
        broken = mock.MagicMock(spec=RunRecorder)
        broken.runs_root = Path("/dev/null/nonexistent")
        broken.start_task.return_value = "fake_task_id"
        broken.record_vmd_command.side_effect = RuntimeError("io error")
        broken.end_task = mock.MagicMock()

        loop = _build_loop(recorder=broken)
        turns = [
            ("go", [{
                "type": "tool_use", "id": "tc_x",
                "name": "run_vmd_command",
                "input": {"command": "mol new a.pdb"},
            }]),
            ("done", []),
        ]
        with mock.patch.object(
            ClaudeToolLoop, "_call", new=_drive_call(turns),
        ):
            text = _run(loop)
        self.assertEqual(text, "done")
        broken.end_task.assert_called_once_with(status="complete")


if __name__ == "__main__":
    unittest.main()
