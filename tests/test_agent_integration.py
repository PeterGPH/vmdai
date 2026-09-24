"""
Integration tests for the full agent loop path through RuntimeApp.

Exercises the full stack WITHOUT real API calls:
  - chat.send → background thread
  - tool_start events emitted to the queue
  - tool.command_result posted to unblock the loop
  - error events, cancellation, and mock fallback

Uses a monkeypatch strategy to replace the real HTTP API call with a
controllable mock that returns pre-scripted responses.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, ClaudeLoopError


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_app(provider_mode="mock"):
    """Create a RuntimeApp with a temp store dir."""
    store = tempfile.mkdtemp(prefix="vmdai_test_")
    return RuntimeApp(store_dir=store, provider_mode=provider_mode)


def _start_session(app: RuntimeApp) -> dict:
    """POST session.start, return the result dict."""
    resp = app.handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "session.start",
            "params": {"cwd": "/tmp"},
        }
    )
    assert "result" in resp, f"session.start failed: {resp}"
    return resp["result"]


def _poll_events(app: RuntimeApp, session_id: str, token: str, after_seq: int = 0, limit: int = 100):
    """POST chat.events.poll, return the result dict."""
    resp = app.handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": "2",
            "method": "chat.events.poll",
            "params": {
                "session_id": session_id,
                "after_seq": after_seq,
                "limit": limit,
            },
        },
        session_token=token,
    )
    assert "result" in resp, f"poll failed: {resp}"
    return resp["result"]


def _send_chat(app: RuntimeApp, session_id: str, token: str, text: str):
    """POST chat.send, return the result dict."""
    resp = app.handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "chat.send",
            "params": {
                "session_id": session_id,
                "text": text,
            },
        },
        session_token=token,
    )
    assert "result" in resp, f"chat.send failed: {resp}"
    return resp["result"]


def _post_tool_result(app: RuntimeApp, session_id: str, token: str, tool_call_id: str, ok: bool, output: str, error: str = "", snapshot_file: str = ""):
    """POST tool.command_result."""
    resp = app.handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": "4",
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
    return resp


def _wait_for_events(app, sid, tok, role_filter=None, max_wait=5.0, after_seq=0):
    """Poll until events matching role_filter appear (or timeout)."""
    deadline = time.time() + max_wait
    all_events = []
    seq = after_seq
    while time.time() < deadline:
        result = _poll_events(app, sid, tok, after_seq=seq)
        for ev in result.get("events", []):
            all_events.append(ev)
            seq = max(seq, ev.get("seq", seq))
        if role_filter:
            matched = [e for e in all_events if e["role"] == role_filter]
            if matched:
                return all_events, seq
        elif all_events:
            return all_events, seq
        time.sleep(0.15)
    return all_events, seq


# ------------------------------------------------------------------
# Tests: mock provider (no API key)
# ------------------------------------------------------------------

class MockProviderIntegrationTests(unittest.TestCase):

    def test_session_lifecycle(self):
        app = _make_app("mock")
        sess = _start_session(app)
        self.assertIn("session_id", sess)
        self.assertIn("session_token", sess)
        self.assertEqual(sess["provider"], "mock")

    def test_mock_chat_streams_response(self):
        """In mock mode, chat.send should produce assistant chunks and a final message."""
        app = _make_app("mock")
        sess = _start_session(app)
        sid, tok = sess["session_id"], sess["session_token"]

        _send_chat(app, sid, tok, "hello")

        # Wait for assistant events
        events, _ = _wait_for_events(app, sid, tok, role_filter="assistant", max_wait=3.0, after_seq=1)
        assistant_events = [e for e in events if e["role"] == "assistant"]
        self.assertTrue(len(assistant_events) > 0, "expected assistant events from mock provider")

        # Should have at least some chunks and a final message
        chunks = [e for e in assistant_events if e["type"] == "chunk"]
        final = [e for e in assistant_events if e["type"] == "message"]
        self.assertTrue(len(chunks) > 0 or len(final) > 0)


# ------------------------------------------------------------------
# Tests: agent loop with mocked API
# ------------------------------------------------------------------

class AgentLoopIntegrationTests(unittest.TestCase):
    """
    Monkeypatch ClaudeToolLoop._call to simulate multi-turn tool use
    without hitting real APIs.
    """

    def _make_app_with_fake_loop(self, responses):
        """
        Create a RuntimeApp with a fake ClaudeToolLoop whose _call method
        returns a scripted sequence of (text, tool_blocks) tuples.
        """
        app = _make_app("mock")

        call_count = {"n": 0}

        class FakeLoop(ClaudeToolLoop):
            def _call(self, messages, system_prompt, on_text, should_cancel):
                idx = call_count["n"]
                call_count["n"] += 1
                if idx < len(responses):
                    text, tool_blocks = responses[idx]
                else:
                    text, tool_blocks = ("Done.", [])
                # Mimic streaming by pushing the full text as one chunk —
                # the real SSE path emits many small chunks but the
                # contract is the same: on_text fires for any text.
                if text:
                    on_text(text)
                return text, tool_blocks

        app.claude_loop = FakeLoop(
            provider_name="openrouter",
            api_key="fake_key",
            model="anthropic/claude-sonnet-4.6",
        )
        return app

    def test_single_tool_call_round_trip(self):
        """
        Simulate: Claude returns a tool_use → Tcl bridge posts result → Claude responds.
        """
        responses = [
            # Turn 1: model calls run_vmd_command
            (
                "Let me check what's loaded.",
                [
                    {
                        "type": "tool_use",
                        "id": "tc_001",
                        "name": "run_vmd_command",
                        "input": {"command": "molinfo list"},
                    }
                ],
            ),
            # Turn 2: model responds with text (no more tools)
            ("There are 3 molecules loaded: 0, 1, 2.", []),
        ]

        app = self._make_app_with_fake_loop(responses)
        sess = _start_session(app)
        sid, tok = sess["session_id"], sess["session_token"]

        # Send the user message — this starts the agent loop on a background thread
        _send_chat(app, sid, tok, "what molecules are loaded?")

        # Wait for tool_start event
        events, seq = _wait_for_events(
            app, sid, tok, role_filter="tool_start", max_wait=3.0, after_seq=1
        )
        tool_starts = [e for e in events if e["role"] == "tool_start"]
        self.assertTrue(len(tool_starts) >= 1, f"expected tool_start, got: {[e['role'] for e in events]}")

        # Extract the tool_call_id
        tool_call_id = tool_starts[0]["metadata"]["tool_call_id"]

        # Simulate the Tcl bridge posting the result
        _post_tool_result(app, sid, tok, tool_call_id, ok=True, output="0 1 2")

        # Wait for the final assistant message
        events, _ = _wait_for_events(
            app, sid, tok, role_filter="assistant", max_wait=5.0, after_seq=seq
        )
        assistant_events = [e for e in events if e["role"] == "assistant"]
        self.assertTrue(len(assistant_events) > 0, "expected assistant response after tool result")

    def test_tool_error_propagated(self):
        """When tool execution fails, the model gets the error and can respond."""
        responses = [
            (
                "",
                [
                    {
                        "type": "tool_use",
                        "id": "tc_err",
                        "name": "run_vmd_command",
                        "input": {"command": "bad_command"},
                    }
                ],
            ),
            ("That command failed. Try 'molinfo list' instead.", []),
        ]

        app = self._make_app_with_fake_loop(responses)
        sess = _start_session(app)
        sid, tok = sess["session_id"], sess["session_token"]

        _send_chat(app, sid, tok, "run bad_command")

        events, seq = _wait_for_events(
            app, sid, tok, role_filter="tool_start", max_wait=3.0, after_seq=1
        )
        tool_starts = [e for e in events if e["role"] == "tool_start"]
        self.assertTrue(tool_starts)

        tool_call_id = tool_starts[0]["metadata"]["tool_call_id"]
        _post_tool_result(
            app, sid, tok, tool_call_id,
            ok=False, output="", error="invalid command: bad_command",
        )

        events, _ = _wait_for_events(
            app, sid, tok, role_filter="assistant", max_wait=5.0, after_seq=seq
        )
        assistant_events = [e for e in events if e["role"] == "assistant"]
        self.assertTrue(assistant_events)

    def test_no_tool_call_just_text(self):
        """When model responds with text only, no tool_start events appear."""
        responses = [
            ("VMD uses Tcl as its scripting language.", []),
        ]

        app = self._make_app_with_fake_loop(responses)
        sess = _start_session(app)
        sid, tok = sess["session_id"], sess["session_token"]

        _send_chat(app, sid, tok, "what language does VMD use?")

        events, _ = _wait_for_events(
            app, sid, tok, role_filter="assistant", max_wait=3.0, after_seq=1
        )
        tool_starts = [e for e in events if e["role"] == "tool_start"]
        assistant_events = [e for e in events if e["role"] == "assistant"]

        self.assertEqual(len(tool_starts), 0)
        self.assertTrue(len(assistant_events) > 0)


# ------------------------------------------------------------------
# Tests: tool.command_result RPC method
# ------------------------------------------------------------------

class ToolCommandResultRpcTests(unittest.TestCase):

    def test_tool_command_result_invalid_session(self):
        """tool.command_result with a bad session_id should fail."""
        app = _make_app("mock")
        resp = app.handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": "5",
                "method": "tool.command_result",
                "params": {
                    "session_id": "sess_nonexistent",
                    "tool_call_id": "tc_xxx",
                    "ok": True,
                    "output": "test",
                },
            }
        )
        self.assertIn("error", resp)

    def test_tool_command_result_unknown_call_id(self):
        """tool.command_result with a valid session but unknown call_id → TOOL_CALL_UNKNOWN.

        Previously returned ``resolved=False`` silently; the silent path let
        any local process write arbitrary text to a session's transcript by
        guessing tool_call_ids. The handler now refuses unknown ids outright.
        """
        app = _make_app("mock")
        sess = _start_session(app)
        sid = sess["session_id"]

        resp = _post_tool_result(app, sid, sess["session_token"], "tc_orphan", True, "test")
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], "TOOL_CALL_UNKNOWN")


# ------------------------------------------------------------------
# Tests: poll response does NOT false-positive on error events
# ------------------------------------------------------------------

class PollErrorRoleTests(unittest.TestCase):
    """
    Regression test for the bridge.tcl bug where _response_error
    falsely detected an RPC error when events contained role='error'.
    """

    def test_poll_with_error_event_is_still_successful_rpc(self):
        """
        Push an error-role event to the queue, then poll.
        The poll RPC should succeed (have 'result', no top-level 'error').
        """
        app = _make_app("mock")
        sess = _start_session(app)
        sid, tok = sess["session_id"], sess["session_token"]

        # Manually push an error event into the session queue
        state = app.sessions.get(sid)
        state.queue.push("error", "message", "API key invalid", {"request_id": "req_x"})

        # Poll
        result = _poll_events(app, sid, tok, after_seq=0)
        events = result.get("events", [])
        error_events = [e for e in events if e["role"] == "error"]
        self.assertTrue(len(error_events) >= 1, "expected at least one error event")

        # The JSON body should have "result" key (success), NOT "error" at top level
        raw_resp = app.handle_rpc(
            {
                "jsonrpc": "2.0",
                "id": "poll_check",
                "method": "chat.events.poll",
                "params": {"session_id": sid, "after_seq": 0, "limit": 50},
            },
            session_token=tok,
        )
        self.assertIn("result", raw_resp)
        self.assertNotIn("error", raw_resp)
        # Serialized JSON body should contain "result":
        body = json.dumps(raw_resp)
        self.assertIn('"result"', body)


if __name__ == "__main__":
    unittest.main()
