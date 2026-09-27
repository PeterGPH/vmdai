"""
Tests for tool_bridge.py — VmdToolBridge async tool execution.

Covers:
  - Basic push → resolve → return lifecycle
  - Timeout behavior
  - Cancel-event behavior
  - Snapshot file reading and base64 encoding
  - Concurrent tool calls
  - Event queue contents
"""
from __future__ import annotations

import os
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.events import EventQueue  # noqa: E402
from vmd_ai_runtime.tool_bridge import VmdToolBridge  # noqa: E402


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_tga_1x1() -> bytes:
    """Minimal 1×1 uncompressed TGA (blue pixel)."""
    header = bytearray(18)
    header[2] = 2
    struct.pack_into("<H", header, 12, 1)
    struct.pack_into("<H", header, 14, 1)
    header[16] = 24
    return bytes(header) + bytes([255, 0, 0])  # BGR


# ------------------------------------------------------------------
# Tests: basic lifecycle
# ------------------------------------------------------------------

class ToolBridgeResolveTests(unittest.TestCase):

    def test_tool_start_event_uses_message_type(self):
        """The pushed tool_start event must use type='message' (valid EVENT_TYPE)."""
        q = EventQueue()
        bridge = VmdToolBridge()
        cancel = threading.Event()
        out = {}

        def _run():
            out["result"] = bridge.execute_tool(
                session_id="sess_test",
                tool_call_id="tc_1",
                tool_name="run_vmd_command",
                tool_input={"command": "pwd"},
                session_queue=q,
                cancel_event=cancel,
                timeout=3,
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        events = []
        for _ in range(30):
            polled = q.poll(after_seq=0, limit=10)
            events = polled["events"]
            if events:
                break
            time.sleep(0.05)

        self.assertTrue(events, "expected at least one event")
        ev = events[0]
        self.assertEqual(ev["role"], "tool_start")
        self.assertEqual(ev["type"], "message")
        self.assertEqual(ev["metadata"]["tool_name"], "run_vmd_command")

        bridge.resolve("tc_1", {"ok": True, "output": "ok", "error": ""})
        t.join(timeout=2)
        self.assertFalse(t.is_alive())
        self.assertTrue(out["result"]["ok"])

    def test_resolve_unblocks_execute(self):
        """resolve() from another thread unblocks execute_tool()."""
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()
        result_holder = {}

        def run_exec():
            result_holder["r"] = bridge.execute_tool(
                session_id="s1",
                tool_call_id="tc_r1",
                tool_name="run_vmd_command",
                tool_input={"command": "molinfo list"},
                session_queue=q,
                cancel_event=cancel,
                timeout=5.0,
            )

        t = threading.Thread(target=run_exec)
        t.start()
        time.sleep(0.3)

        ok = bridge.resolve("tc_r1", {"ok": True, "output": "0 1 2", "error": ""})
        t.join(timeout=3.0)

        self.assertTrue(ok)
        self.assertIn("r", result_holder)
        self.assertTrue(result_holder["r"]["ok"])
        self.assertEqual(result_holder["r"]["output"], "0 1 2")

    def test_resolve_unknown_id_returns_false(self):
        """resolve() for an ID that was never registered returns False."""
        bridge = VmdToolBridge()
        self.assertFalse(bridge.resolve("tc_no_such_id", {"ok": True}))


# ------------------------------------------------------------------
# Tests: timeout
# ------------------------------------------------------------------

class ToolBridgeTimeoutTests(unittest.TestCase):

    def test_timeout_returns_error(self):
        """If nobody posts a result, execute_tool returns a timeout error."""
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()

        result = bridge.execute_tool(
            session_id="s1",
            tool_call_id="tc_hang",
            tool_name="run_vmd_command",
            tool_input={"command": "hang"},
            session_queue=q,
            cancel_event=cancel,
            timeout=0.4,
        )

        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["error"])

    def test_resolve_after_timeout_returns_false(self):
        """resolve() after timeout returns False — the call already expired."""
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()

        bridge.execute_tool(
            session_id="s1",
            tool_call_id="tc_late",
            tool_name="run_vmd_command",
            tool_input={"command": "mol list"},
            session_queue=q,
            cancel_event=cancel,
            timeout=0.3,
        )

        late = bridge.resolve("tc_late", {"ok": True, "output": "late"})
        self.assertFalse(late)


# ------------------------------------------------------------------
# Tests: cancel
# ------------------------------------------------------------------

class ToolBridgeCancelTests(unittest.TestCase):

    def test_cancel_event_unblocks_execute(self):
        """Setting cancel_event while execute_tool waits returns 'cancelled'."""
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()
        result_holder = {}

        def run_exec():
            result_holder["r"] = bridge.execute_tool(
                session_id="s1",
                tool_call_id="tc_cx",
                tool_name="run_vmd_command",
                tool_input={"command": "mol top"},
                session_queue=q,
                cancel_event=cancel,
                timeout=10.0,
            )

        t = threading.Thread(target=run_exec)
        t.start()
        time.sleep(0.3)
        cancel.set()
        t.join(timeout=3.0)

        self.assertIn("r", result_holder)
        self.assertFalse(result_holder["r"]["ok"])
        self.assertEqual(result_holder["r"]["error"], "cancelled")


# ------------------------------------------------------------------
# Tests: snapshot image handling
# ------------------------------------------------------------------

class ToolBridgeSnapshotTests(unittest.TestCase):

    def test_snapshot_reads_tga_file_and_produces_b64_png(self):
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()

        tga_data = _make_tga_1x1()
        # Tokenless sessions may only use the path the old plugin builds
        # (spec 2d Snapshot): /tmp/vmdai_snap_<tool_call_id>.tga
        tga_path = "/tmp/vmdai_snap_tc_snap.tga"
        with open(tga_path, "wb") as f:
            f.write(tga_data)

        try:
            def resolve_later():
                time.sleep(0.2)
                bridge.resolve("tc_snap", {
                    "ok": True,
                    "output": "Snapshot captured",
                    "error": "",
                    "snapshot_file": tga_path,
                })

            threading.Thread(target=resolve_later, daemon=True).start()

            result = bridge.execute_tool(
                session_id="s1",
                tool_call_id="tc_snap",
                tool_name="capture_vmd_snapshot",
                tool_input={"purpose": "verify scene"},
                session_queue=q,
                cancel_event=cancel,
                timeout=3.0,
            )

            self.assertTrue(result["ok"])
            self.assertIn("image_b64", result)
            self.assertTrue(len(result["image_b64"]) > 10)
            self.assertEqual(result["image_mime"], "image/png")
            # The temp file should have been cleaned up
            self.assertFalse(os.path.exists(tga_path))
        finally:
            if os.path.exists(tga_path):
                os.unlink(tga_path)

    def test_snapshot_missing_file_no_image(self):
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()

        def resolve_later():
            time.sleep(0.2)
            bridge.resolve("tc_snap2", {
                "ok": True,
                "output": "Snapshot",
                "error": "",
                "snapshot_file": "/tmp/vmdai_snap_tc_snap2.tga",
            })

        threading.Thread(target=resolve_later, daemon=True).start()

        result = bridge.execute_tool(
            session_id="s1",
            tool_call_id="tc_snap2",
            tool_name="capture_vmd_snapshot",
            tool_input={"purpose": "test"},
            session_queue=q,
            cancel_event=cancel,
            timeout=3.0,
        )

        self.assertTrue(result["ok"])
        self.assertNotIn("image_b64", result)

    def test_non_snapshot_tool_ignores_file_handling(self):
        """run_vmd_command results never trigger image reading even if snapshot_file set."""
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()

        def resolve_later():
            time.sleep(0.2)
            bridge.resolve("tc_cmd", {
                "ok": True,
                "output": "done",
                "error": "",
                "snapshot_file": "/tmp/fake.tga",
            })

        threading.Thread(target=resolve_later, daemon=True).start()

        result = bridge.execute_tool(
            session_id="s1",
            tool_call_id="tc_cmd",
            tool_name="run_vmd_command",
            tool_input={"command": "mol list"},
            session_queue=q,
            cancel_event=cancel,
            timeout=3.0,
        )

        self.assertTrue(result["ok"])
        self.assertNotIn("image_b64", result)


# ------------------------------------------------------------------
# Tests: concurrency
# ------------------------------------------------------------------

class ToolBridgeConcurrencyTests(unittest.TestCase):

    def test_two_concurrent_tools_resolve_independently(self):
        bridge = VmdToolBridge()
        q = EventQueue()
        cancel = threading.Event()
        results = {}

        def execute(call_id):
            results[call_id] = bridge.execute_tool(
                session_id="s1",
                tool_call_id=call_id,
                tool_name="run_vmd_command",
                tool_input={"command": f"echo {call_id}"},
                session_queue=q,
                cancel_event=cancel,
                timeout=5.0,
            )

        t1 = threading.Thread(target=execute, args=("tc_a",))
        t2 = threading.Thread(target=execute, args=("tc_b",))
        t1.start()
        t2.start()
        time.sleep(0.3)

        # Resolve in reverse order
        bridge.resolve("tc_b", {"ok": True, "output": "b_out", "error": ""})
        bridge.resolve("tc_a", {"ok": True, "output": "a_out", "error": ""})

        t1.join(timeout=3.0)
        t2.join(timeout=3.0)

        self.assertEqual(results["tc_a"]["output"], "a_out")
        self.assertEqual(results["tc_b"]["output"], "b_out")


if __name__ == "__main__":
    unittest.main()
