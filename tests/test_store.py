from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.store import ChatStore  # noqa: E402


class StoreTests(unittest.TestCase):
    def test_create_append_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ChatStore(root_dir=tmp)
            chat_id = store.create_chat("test")
            count = store.append_events(chat_id, [
                {"seq": 1, "role": "user", "type": "message", "text": "hi", "metadata": {}},
                {"seq": 2, "role": "assistant", "type": "message", "text": "hello", "metadata": {}},
            ])
            self.assertEqual(count, 2)
            rows = store.list_chats(limit=10, offset=0)
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0]["chat_id"], chat_id)


if __name__ == "__main__":
    unittest.main()
