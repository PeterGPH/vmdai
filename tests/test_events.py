from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.events import EventQueue  # noqa: E402


class EventQueueTests(unittest.TestCase):
    def test_order_and_polling(self):
        q = EventQueue()
        q.push("system", "lifecycle", "session_started")
        q.push("assistant", "chunk", "hello")
        q.push("assistant", "message", "hello world")

        first = q.poll(after_seq=0, limit=2)
        self.assertEqual(len(first["events"]), 2)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["last_seq"], 2)

        second = q.poll(after_seq=2, limit=10)
        self.assertEqual(len(second["events"]), 1)
        self.assertFalse(second["has_more"])
        self.assertEqual(second["events"][0]["seq"], 3)


if __name__ == "__main__":
    unittest.main()
