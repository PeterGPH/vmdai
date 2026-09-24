"""
Tests for claude_loop.py — message format conversion, tool result construction,
and the SSE streaming path.

Does NOT make real API calls.  Tests cover:
  - Anthropic ↔ OpenRouter message format conversion
  - Tool result block construction (text only vs. image)
  - The SSE event iterator handles partial / malformed / [DONE] cases
  - The streaming response parsers consume the right deltas in real time
  - VMD_TOOLS schema validation
  - build_claude_loop factory behavior
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.claude_loop import (
    VMD_TOOLS,
    VMD_SYSTEM_PROMPT,
    _to_openrouter_messages,
    _build_tool_result_block,
    _openrouter_tools,
    _iter_sse_events,
    _stream_anthropic_direct,
    _stream_openrouter,
    _DONE_SENTINEL,
    build_claude_loop,
)


# ----------------------------------------------------------------------
# Helpers: build a stand-in for an SSE HTTP response
# ----------------------------------------------------------------------

class _FakeResponse:
    """File-like object that yields SSE lines, used in place of urlopen()."""

    def __init__(self, lines):
        # Each line should be raw bytes WITHOUT the trailing newline; we
        # add the SSE-correct \n\n delimiter automatically per record so
        # the iterator's readline() loop sees realistic input.
        encoded = b""
        for line in lines:
            if isinstance(line, str):
                line = line.encode("utf-8")
            encoded += line + b"\n"
        self._buf = io.BytesIO(encoded)

    def readline(self):
        return self._buf.readline()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._buf.close()
        return False


def _sse_line(event_type: str, data: dict) -> str:
    return "data: " + json.dumps(data)


# ----------------------------------------------------------------------
# Tests: VMD_TOOLS schema
# ----------------------------------------------------------------------

class VmdToolSchemaTests(unittest.TestCase):

    def test_tool_count(self):
        # 3 tools: run_vmd_command, capture_vmd_snapshot, search_docs.
        self.assertEqual(len(VMD_TOOLS), 3)
        names = {t["name"] for t in VMD_TOOLS}
        self.assertEqual(
            names,
            {"run_vmd_command", "capture_vmd_snapshot", "search_docs"},
        )

    def test_run_vmd_command_has_required_fields(self):
        tool = next(t for t in VMD_TOOLS if t["name"] == "run_vmd_command")
        schema = tool["input_schema"]
        self.assertIn("command", schema["properties"])
        self.assertIn("command", schema["required"])

    def test_capture_snapshot_has_purpose(self):
        tool = next(t for t in VMD_TOOLS if t["name"] == "capture_vmd_snapshot")
        schema = tool["input_schema"]
        self.assertIn("purpose", schema["properties"])

    def test_system_prompt_mentions_vmd_commands(self):
        for keyword in ("mol load", "mol representation", "render snapshot", "rotate"):
            self.assertIn(keyword, VMD_SYSTEM_PROMPT)


# ----------------------------------------------------------------------
# Tests: OpenRouter format conversion
# ----------------------------------------------------------------------

class OpenRouterFormatTests(unittest.TestCase):

    def test_simple_user_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        out = _to_openrouter_messages(msgs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")
        self.assertEqual(out[0]["content"], "hi")

    def test_tool_use_block_becomes_tool_calls(self):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I'll run that."},
                    {
                        "type": "tool_use",
                        "id": "tc_1",
                        "name": "run_vmd_command",
                        "input": {"command": "mol list"},
                    },
                ],
            }
        ]
        out = _to_openrouter_messages(msgs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "assistant")
        self.assertIn("I'll run that.", out[0]["content"])
        self.assertEqual(len(out[0]["tool_calls"]), 1)
        tc = out[0]["tool_calls"][0]
        self.assertEqual(tc["id"], "tc_1")
        self.assertEqual(tc["function"]["name"], "run_vmd_command")
        parsed_args = json.loads(tc["function"]["arguments"])
        self.assertEqual(parsed_args["command"], "mol list")

    def test_tool_result_block_becomes_tool_role(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tc_1",
                        "content": "done",
                    }
                ],
            }
        ]
        out = _to_openrouter_messages(msgs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "tool")
        self.assertEqual(out[0]["tool_call_id"], "tc_1")
        self.assertEqual(out[0]["content"], "done")

    def test_image_blocks_skipped_in_openrouter(self):
        """Image content blocks are dropped in OpenRouter format."""
        msgs = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tc_snap",
                        "content": "Snapshot captured",
                    },
                    {
                        "type": "image",
                        "source": {"type": "base64", "data": "abc123"},
                    },
                ],
            }
        ]
        out = _to_openrouter_messages(msgs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "tool")

    def test_openrouter_tools_format(self):
        converted = _openrouter_tools(VMD_TOOLS)
        # Mirrors VMD_TOOLS — count must match the source list, not be
        # hardcoded, so adding a tool doesn't quietly break this check.
        self.assertEqual(len(converted), len(VMD_TOOLS))
        for item in converted:
            self.assertEqual(item["type"], "function")
            self.assertIn("name", item["function"])
            self.assertIn("parameters", item["function"])


# ----------------------------------------------------------------------
# Tests: SSE event iterator
# ----------------------------------------------------------------------

class IterSseEventsTests(unittest.TestCase):

    def test_skips_keepalive_comments(self):
        resp = _FakeResponse([
            ":keep-alive",
            "data: " + json.dumps({"type": "x"}),
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "x")

    def test_skips_blank_lines(self):
        resp = _FakeResponse([
            "",
            "",
            "data: " + json.dumps({"type": "y"}),
            "",
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(len(events), 1)

    def test_skips_event_lines(self):
        """Anthropic sends both 'event: foo' and 'data: {...}' lines.
        The iterator ignores the event: header and only yields data."""
        resp = _FakeResponse([
            "event: content_block_delta",
            "data: " + json.dumps({"type": "content_block_delta"}),
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "content_block_delta")

    def test_done_sentinel(self):
        resp = _FakeResponse([
            "data: " + json.dumps({"type": "x"}),
            "data: [DONE]",
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(len(events), 2)
        self.assertIs(events[1], _DONE_SENTINEL)

    def test_malformed_json_skipped(self):
        """A bad SSE line shouldn't kill the whole stream."""
        resp = _FakeResponse([
            "data: not-json-at-all",
            "data: " + json.dumps({"type": "ok"}),
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "ok")

    def test_handles_data_with_no_space_after_colon(self):
        """SSE strictly speaking allows 'data:foo' as well as 'data: foo'."""
        resp = _FakeResponse([
            "data:" + json.dumps({"type": "tight"}),
        ])
        events = list(_iter_sse_events(resp))
        self.assertEqual(events[0]["type"], "tight")


# ----------------------------------------------------------------------
# Tests: Anthropic streaming
# ----------------------------------------------------------------------

class AnthropicStreamingTests(unittest.TestCase):

    def _build_text_only_stream(self, text_parts):
        """Build SSE lines for a text-only message."""
        lines = ["data: " + json.dumps({"type": "message_start"})]
        lines.append("data: " + json.dumps({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }))
        for piece in text_parts:
            lines.append("data: " + json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": piece},
            }))
        lines.append("data: " + json.dumps({"type": "content_block_stop", "index": 0}))
        lines.append("data: " + json.dumps({"type": "message_stop"}))
        return lines

    def _build_tool_use_stream(self, tool_id, tool_name, args_partials):
        """Build SSE lines for a tool_use block, with arguments split into
        multiple input_json_delta fragments — the real API often splits
        even small JSON across 2-3 events."""
        lines = ["data: " + json.dumps({"type": "message_start"})]
        lines.append("data: " + json.dumps({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": tool_id, "name": tool_name},
        }))
        for fragment in args_partials:
            lines.append("data: " + json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": fragment},
            }))
        lines.append("data: " + json.dumps({"type": "content_block_stop", "index": 0}))
        lines.append("data: " + json.dumps({"type": "message_stop"}))
        return lines

    def test_text_chunks_arrive_in_order(self):
        """Text deltas should fire on_text in the same order they appeared."""
        chunks_seen = []
        lines = self._build_text_only_stream(["Hel", "lo, ", "world"])

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, tools = _stream_anthropic_direct(
                messages=[{"role": "user", "content": "hi"}],
                model="claude-sonnet-4-5",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=lambda: False,
            )

        self.assertEqual(chunks_seen, ["Hel", "lo, ", "world"])
        self.assertEqual(text, "Hello, world")
        self.assertEqual(tools, [])

    def test_tool_use_block_assembled_from_partials(self):
        """input_json_delta fragments must concatenate into the final args."""
        lines = self._build_tool_use_stream(
            tool_id="tc_abc",
            tool_name="run_vmd_command",
            args_partials=['{"comm', 'and": "mol li', 'st"}'],
        )

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, tools = _stream_anthropic_direct(
                messages=[{"role": "user", "content": "x"}],
                model="claude-sonnet-4-5",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=lambda _t: None,
                should_cancel=lambda: False,
            )

        self.assertEqual(text, "")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "tool_use")
        self.assertEqual(tools[0]["id"], "tc_abc")
        self.assertEqual(tools[0]["name"], "run_vmd_command")
        self.assertEqual(tools[0]["input"], {"command": "mol list"})

    def test_text_then_tool_use_sequence(self):
        """A turn that streams text first and then a tool use."""
        lines = ["data: " + json.dumps({"type": "message_start"})]
        # Text block
        lines.append("data: " + json.dumps({
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }))
        lines.append("data: " + json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Loading..."},
        }))
        lines.append("data: " + json.dumps({"type": "content_block_stop", "index": 0}))
        # Tool block
        lines.append("data: " + json.dumps({
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tc_x", "name": "run_vmd_command"},
        }))
        lines.append("data: " + json.dumps({
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"command":"mol list"}'},
        }))
        lines.append("data: " + json.dumps({"type": "content_block_stop", "index": 1}))
        lines.append("data: " + json.dumps({"type": "message_stop"}))

        chunks_seen = []
        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, tools = _stream_anthropic_direct(
                messages=[{"role": "user", "content": "x"}],
                model="claude-sonnet-4-5",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=lambda: False,
            )

        self.assertEqual(text, "Loading...")
        self.assertEqual(chunks_seen, ["Loading..."])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["input"], {"command": "mol list"})

    def test_should_cancel_breaks_mid_stream(self):
        """If should_cancel goes True between events the iterator stops early."""
        lines = self._build_text_only_stream(["one", "two", "three"])

        chunks_seen = []
        cancel_after = {"n": 0}

        def should_cancel():
            cancel_after["n"] += 1
            return cancel_after["n"] > 4  # cancel after a few events processed

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, tools = _stream_anthropic_direct(
                messages=[{"role": "user", "content": "x"}],
                model="claude-sonnet-4-5",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=should_cancel,
            )

        # Should have stopped early — fewer than the full 3 chunks made it
        # through. (Exact count depends on how many events fired before
        # should_cancel returned True; the contract is "less than full".)
        self.assertLess(len(chunks_seen), 3)

    def test_malformed_input_json_yields_empty_input(self):
        """Tool calls whose JSON args fail to parse get an empty input dict."""
        lines = self._build_tool_use_stream(
            tool_id="tc_bad",
            tool_name="run_vmd_command",
            args_partials=["this is not valid json"],
        )
        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            _text, tools = _stream_anthropic_direct(
                messages=[{"role": "user", "content": "x"}],
                model="claude-sonnet-4-5",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=lambda _t: None,
                should_cancel=lambda: False,
            )
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["input"], {})


# ----------------------------------------------------------------------
# Tests: OpenRouter streaming
# ----------------------------------------------------------------------

class OpenRouterStreamingTests(unittest.TestCase):

    def _delta_chunk(self, content=None, tool_calls=None):
        delta = {}
        if content is not None:
            delta["content"] = content
        if tool_calls is not None:
            delta["tool_calls"] = tool_calls
        return "data: " + json.dumps({"choices": [{"delta": delta}]})

    def test_text_chunks_arrive_in_order(self):
        chunks_seen = []
        lines = [
            self._delta_chunk(content="Run"),
            self._delta_chunk(content="ning"),
            self._delta_chunk(content=" command"),
            "data: [DONE]",
        ]

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, tools = _stream_openrouter(
                messages=[{"role": "user", "content": "hi"}],
                model="anthropic/claude-sonnet-4.6",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=lambda: False,
            )

        self.assertEqual(chunks_seen, ["Run", "ning", " command"])
        self.assertEqual(text, "Running command")
        self.assertEqual(tools, [])

    def test_tool_call_arguments_concatenated_across_deltas(self):
        """OpenAI streams `function.arguments` as small string fragments."""
        lines = [
            self._delta_chunk(tool_calls=[{
                "index": 0,
                "id": "call_abc",
                "type": "function",
                "function": {"name": "run_vmd_command", "arguments": '{"comm'},
            }]),
            self._delta_chunk(tool_calls=[{
                "index": 0,
                "function": {"arguments": 'and":"mol l'},
            }]),
            self._delta_chunk(tool_calls=[{
                "index": 0,
                "function": {"arguments": 'ist"}'},
            }]),
            "data: [DONE]",
        ]

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            _text, tools = _stream_openrouter(
                messages=[{"role": "user", "content": "x"}],
                model="anthropic/claude-sonnet-4.6",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=lambda _t: None,
                should_cancel=lambda: False,
            )

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["type"], "tool_use")
        self.assertEqual(tools[0]["id"], "call_abc")
        self.assertEqual(tools[0]["name"], "run_vmd_command")
        self.assertEqual(tools[0]["input"], {"command": "mol list"})

    def test_tool_call_with_malformed_arguments_yields_empty_input(self):
        lines = [
            self._delta_chunk(tool_calls=[{
                "index": 0,
                "id": "call_bad",
                "type": "function",
                "function": {"name": "run_vmd_command", "arguments": "not-json"},
            }]),
            "data: [DONE]",
        ]
        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            _text, tools = _stream_openrouter(
                messages=[{"role": "user", "content": "x"}],
                model="anthropic/claude-sonnet-4.6",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=lambda _t: None,
                should_cancel=lambda: False,
            )
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["input"], {})

    def test_done_sentinel_terminates_stream(self):
        """A [DONE] line ends iteration even if more lines follow."""
        chunks_seen = []
        lines = [
            self._delta_chunk(content="early"),
            "data: [DONE]",
            self._delta_chunk(content="late"),  # should NOT be processed
        ]

        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, _tools = _stream_openrouter(
                messages=[{"role": "user", "content": "x"}],
                model="anthropic/claude-sonnet-4.6",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=lambda: False,
            )

        self.assertEqual(chunks_seen, ["early"])
        self.assertEqual(text, "early")

    def test_empty_choices_handled_gracefully(self):
        """Some OpenRouter chunks have no choices array — must not crash."""
        lines = [
            "data: " + json.dumps({"id": "x", "choices": []}),
            self._delta_chunk(content="ok"),
            "data: [DONE]",
        ]
        chunks_seen = []
        with patch("vmd_ai_runtime.claude_loop._stream_request",
                   return_value=_FakeResponse(lines)):
            text, _tools = _stream_openrouter(
                messages=[{"role": "user", "content": "x"}],
                model="anthropic/claude-sonnet-4.6",
                system_prompt="",
                api_key="fake",
                timeout=5,
                on_text=chunks_seen.append,
                should_cancel=lambda: False,
            )
        self.assertEqual(text, "ok")


# ----------------------------------------------------------------------
# Tests: tool result block construction
# ----------------------------------------------------------------------

class ToolResultBlockTests(unittest.TestCase):

    def test_success_text_only(self):
        result = {"ok": True, "output": "0 1 2", "error": ""}
        block = _build_tool_result_block("tc_1", result, include_image=False)
        self.assertEqual(block["tool_use_id"], "tc_1")
        self.assertFalse(block["is_error"])
        self.assertEqual(block["content"], "0 1 2")

    def test_error_result(self):
        result = {"ok": False, "output": "", "error": "unknown command: foo"}
        block = _build_tool_result_block("tc_2", result, include_image=False)
        self.assertTrue(block["is_error"])
        self.assertIn("unknown command: foo", block["content"])

    def test_success_with_image_included(self):
        result = {
            "ok": True,
            "output": "Snapshot captured",
            "error": "",
            "image_b64": "iVBORw0KGgoAAAANS",
            "image_mime": "image/png",
        }
        block = _build_tool_result_block("tc_snap", result, include_image=True)
        self.assertFalse(block["is_error"])
        self.assertIsInstance(block["content"], list)
        self.assertEqual(len(block["content"]), 2)
        self.assertEqual(block["content"][0]["type"], "text")
        self.assertEqual(block["content"][1]["type"], "image")
        self.assertEqual(block["content"][1]["source"]["data"], "iVBORw0KGgoAAAANS")

    def test_image_excluded_for_openrouter(self):
        result = {
            "ok": True,
            "output": "Snapshot captured",
            "error": "",
            "image_b64": "iVBORw0KGgoAAAANS",
            "image_mime": "image/png",
        }
        block = _build_tool_result_block("tc_snap", result, include_image=False)
        self.assertIsInstance(block["content"], str)
        self.assertIn("Snapshot captured", block["content"])
        self.assertIn("not shown", block["content"])

    def test_empty_output_gives_default_success(self):
        result = {"ok": True, "output": "", "error": ""}
        block = _build_tool_result_block("tc_x", result, include_image=False)
        self.assertIn("successfully", block["content"])


# ----------------------------------------------------------------------
# Tests: build_claude_loop factory
# ----------------------------------------------------------------------

class BuildClaudeLoopTests(unittest.TestCase):

    def test_mock_returns_none(self):
        self.assertIsNone(build_claude_loop("mock"))

    def test_unknown_returns_none(self):
        self.assertIsNone(build_claude_loop("some_unknown_provider"))

    def test_openrouter_without_key_returns_none(self):
        saved = {
            k: os.environ.pop(k, None)
            for k in ("OPENROUTER_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        }
        try:
            # Also block keyring fallback by patching the resolver to return empty.
            with patch("vmd_ai_runtime.claude_loop.resolve_openrouter_api_key",
                       return_value=("", "")):
                self.assertIsNone(build_claude_loop("openrouter"))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_anthropic_direct_without_key_returns_none(self):
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            with patch("vmd_ai_runtime.claude_loop.resolve_anthropic_api_key",
                       return_value=("", "")):
                self.assertIsNone(build_claude_loop("anthropic-direct"))
        finally:
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved


if __name__ == "__main__":
    unittest.main()
