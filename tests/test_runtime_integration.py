from __future__ import annotations

import tempfile
import time
import unittest

from test_helpers import RuntimeHarness


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = RuntimeHarness(store_dir=self.tmp.name)
        self.h.start()

    def tearDown(self):
        self.h.stop()
        self.tmp.cleanup()

    def test_session_start_and_stop(self):
        start = self.h.rpc("session.start", {
            "cwd": ".",
            "ui_mode": "qt",
            "client_version": "test",
            "platform": "local",
        })
        self.assertIn("result", start)
        sid = start["result"]["session_id"]
        token = start["result"]["session_token"]

        stop = self.h.rpc("session.stop", {"session_id": sid}, token=token)
        self.assertTrue(stop["result"]["ok"])

    def test_send_poll_and_cancel(self):
        start = self.h.rpc("session.start", {
            "cwd": ".",
            "ui_mode": "qt",
            "client_version": "test",
            "platform": "local",
        })
        sid = start["result"]["session_id"]
        token = start["result"]["session_token"]
        chat_id = start["result"]["chat_id"]

        sent = self.h.rpc("chat.send", {
            "session_id": sid,
            "chat_id": chat_id,
            "text": "hello",
            "model": "anthropic/claude-sonnet-4.6",
            "mode": "work",
            "conversation_mode": "local_first",
        }, token=token)
        req_id = sent["result"]["request_id"]

        seen_seq = 0
        total = 0
        got_assistant_message = False
        for _ in range(60):
            polled = self.h.rpc("chat.events.poll", {
                "session_id": sid,
                "after_seq": seen_seq,
                "limit": 50,
            }, token=token)
            events = polled["result"]["events"]
            if events:
                total += len(events)
                seen_seq = polled["result"]["last_seq"]
                if any(e.get("role") == "assistant" and e.get("type") == "message" for e in events):
                    got_assistant_message = True
                    break
            time.sleep(0.05)

        self.assertGreater(total, 0)
        self.assertTrue(got_assistant_message)

        # Wait briefly for the first request's background thread to finish and
        # clear active_request, avoiding REQUEST_CONFLICT on the second send.
        for _ in range(20):
            sent2 = self.h.rpc("chat.send", {
                "session_id": sid,
                "chat_id": chat_id,
                "text": "cancel me",
                "model": "anthropic/claude-sonnet-4.6",
                "mode": "work",
                "conversation_mode": "local_first",
            }, token=token)
            if "result" in sent2:
                break
            time.sleep(0.1)
        req2 = sent2["result"]["request_id"]

        cancel = self.h.rpc("chat.cancel", {"session_id": sid, "request_id": req2}, token=token)
        self.assertTrue(cancel["result"]["ok"])

        got_cancel_lifecycle = False
        for _ in range(40):
            polled = self.h.rpc("chat.events.poll", {
                "session_id": sid,
                "after_seq": seen_seq,
                "limit": 50,
            }, token=token)
            events = polled["result"]["events"]
            if events:
                seen_seq = polled["result"]["last_seq"]
                if any(e.get("type") == "lifecycle" and e.get("text") == "cancelled" for e in events):
                    got_cancel_lifecycle = True
                    break
            time.sleep(0.05)

        self.assertTrue(got_cancel_lifecycle)

        stop = self.h.rpc("session.stop", {"session_id": sid}, token=token)
        self.assertTrue(stop["result"]["ok"])


if __name__ == "__main__":
    unittest.main()
