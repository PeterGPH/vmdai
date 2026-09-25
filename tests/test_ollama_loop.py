"""
Ollama Phase 2 — claude_loop.py agentic-streaming tests.

Covers:
    _ollama_tools          · Anthropic input_schema → OpenAI-style function defs
    _to_ollama_messages    · canonical → Ollama format (text, tool_use, tool_result)
    _iter_ndjson_events    · NDJSON parsing, malformed line tolerance
    _stream_ollama         · text-only streaming, tool_call accumulation,
                              cancel, error field, HTTP error, unreachable host
    ClaudeToolLoop dispatch · _is_ollama property, _call routes correctly
    build_claude_loop       · returns None when no model, returns loop when set

No tests hit a real Ollama server. urllib.request.urlopen is mocked.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from pathlib import Path
from typing import Iterable, List
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeLoopError,
    ClaudeToolLoop,
    _iter_ndjson_events,
    _ollama_tools,
    _rescue_json_tool_calls,
    _stream_ollama,
    _to_ollama_messages,
    build_claude_loop,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

class _FakeNdjsonResponse:
    def __init__(self, ndjson_lines: Iterable[dict]):
        self._lines = [
            (json.dumps(obj) + "\n").encode("utf-8") for obj in ndjson_lines
        ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return b"".join(self._lines)


def _mock_urlopen(lines):
    def _fn(req, timeout=None):
        return _FakeNdjsonResponse(lines)
    return _fn


# ----------------------------------------------------------------------
# _ollama_tools
# ----------------------------------------------------------------------

class OllamaToolFormatTests(unittest.TestCase):

    def test_rewraps_input_schema_as_parameters(self):
        tools = [{
            "name": "run_vmd_command",
            "description": "Execute Tcl in VMD",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }]
        out = _ollama_tools(tools)
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["type"], "function")
        self.assertEqual(f["function"]["name"], "run_vmd_command")
        self.assertEqual(f["function"]["description"], "Execute Tcl in VMD")
        self.assertEqual(f["function"]["parameters"]["type"], "object")
        self.assertIn("command", f["function"]["parameters"]["properties"])

    def test_handles_missing_input_schema(self):
        out = _ollama_tools([{"name": "noargs", "description": ""}])
        self.assertEqual(out[0]["function"]["parameters"]["type"], "object")
        self.assertEqual(out[0]["function"]["parameters"]["properties"], {})

    def test_handles_multiple_tools(self):
        tools = [
            {"name": "a", "description": "", "input_schema": {"type": "object"}},
            {"name": "b", "description": "", "input_schema": {"type": "object"}},
        ]
        out = _ollama_tools(tools)
        self.assertEqual([f["function"]["name"] for f in out], ["a", "b"])


# ----------------------------------------------------------------------
# _to_ollama_messages
# ----------------------------------------------------------------------

class OllamaMessageConversionTests(unittest.TestCase):

    def test_plain_string_user_message(self):
        out = _to_ollama_messages([{"role": "user", "content": "hello"}])
        self.assertEqual(out, [{"role": "user", "content": "hello"}])

    def test_assistant_with_text_block(self):
        msgs = [{
            "role": "assistant",
            "content": [{"type": "text", "text": "Hi there"}],
        }]
        out = _to_ollama_messages(msgs)
        self.assertEqual(out, [{"role": "assistant", "content": "Hi there"}])

    def test_assistant_with_tool_use_emits_tool_calls(self):
        msgs = [{
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check"},
                {
                    "type": "tool_use",
                    "id": "toolu_xyz",
                    "name": "run_vmd_command",
                    "input": {"command": "pwd"},
                },
            ],
        }]
        out = _to_ollama_messages(msgs)
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual(m["role"], "assistant")
        self.assertEqual(m["content"], "Let me check")
        self.assertEqual(len(m["tool_calls"]), 1)
        tc = m["tool_calls"][0]
        self.assertEqual(tc["function"]["name"], "run_vmd_command")
        # Arguments is an OBJECT for Ollama, not a JSON string like OpenAI
        self.assertIsInstance(tc["function"]["arguments"], dict)
        self.assertEqual(tc["function"]["arguments"], {"command": "pwd"})
        self.assertEqual(tc["id"], "toolu_xyz")

    def test_user_with_tool_result_emits_tool_role_message(self):
        msgs = [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_xyz",
                "content": "/Users/peter/dock-1ubq",
            }],
        }]
        out = _to_ollama_messages(msgs)
        self.assertEqual(len(out), 1)
        m = out[0]
        self.assertEqual(m["role"], "tool")
        self.assertEqual(m["tool_call_id"], "toolu_xyz")
        self.assertEqual(m["content"], "/Users/peter/dock-1ubq")

    def test_tool_result_with_image_block_replaces_with_text_marker(self):
        msgs = [{
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_snap",
                "content": [
                    {"type": "text", "text": "Snapshot captured"},
                    {"type": "image", "source": {"type": "base64", "data": "..."}},
                ],
            }],
        }]
        out = _to_ollama_messages(msgs)
        self.assertEqual(out[0]["role"], "tool")
        self.assertIn("Snapshot captured", out[0]["content"])
        # Should drop binary image, add a marker — we don't want raw bytes
        # leaking into the prompt of a non-vision model.
        self.assertIn("image not shown", out[0]["content"].lower())


# ----------------------------------------------------------------------
# _iter_ndjson_events
# ----------------------------------------------------------------------

class NdjsonIterTests(unittest.TestCase):

    def test_parses_multiple_lines(self):
        lines = [
            b'{"a": 1}\n',
            b'{"b": 2}\n',
            b'{"c": 3}\n',
        ]
        out = list(_iter_ndjson_events(lines))
        self.assertEqual(out, [{"a": 1}, {"b": 2}, {"c": 3}])

    def test_skips_blank_lines(self):
        lines = [b'{"a":1}\n', b'\n', b'   \n', b'{"b":2}\n']
        out = list(_iter_ndjson_events(lines))
        self.assertEqual(out, [{"a": 1}, {"b": 2}])

    def test_skips_malformed_lines(self):
        lines = [b'{"a":1}\n', b'not json at all\n', b'{"b":2}\n']
        out = list(_iter_ndjson_events(lines))
        self.assertEqual(out, [{"a": 1}, {"b": 2}])


# ----------------------------------------------------------------------
# _stream_ollama — text only
# ----------------------------------------------------------------------

class StreamOllamaTextTests(unittest.TestCase):

    def setUp(self):
        self.text_chunks: List[str] = []
        self.cancelled = False

    def _on_text(self, s):
        self.text_chunks.append(s)

    def _no_cancel(self):
        return self.cancelled

    def test_text_streaming_in_order_no_tools(self):
        ndjson = [
            {"message": {"role": "assistant", "content": "Hello"},  "done": False},
            {"message": {"role": "assistant", "content": ", "},     "done": False},
            {"message": {"role": "assistant", "content": "world!"}, "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            text, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": "hi"}],
                model="llama3.1",
                system_prompt="be brief",
                base_url="http://localhost:11434",
                timeout=10,
                on_text=self._on_text,
                should_cancel=self._no_cancel,
                tools=[],
            )
        self.assertEqual(text, "Hello, world!")
        self.assertEqual(tool_blocks, [])
        self.assertEqual(self.text_chunks, ["Hello", ", ", "world!"])

    def test_cancel_stops_streaming(self):
        ndjson = [
            {"message": {"role": "assistant", "content": "first"},  "done": False},
            {"message": {"role": "assistant", "content": "second"}, "done": False},
            {"message": {"role": "assistant", "content": "third"},  "done": True},
        ]

        def on_text(s):
            self.text_chunks.append(s)
            if len(self.text_chunks) >= 1:
                self.cancelled = True

        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            text, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": "long"}],
                model="llama3.1",
                system_prompt="",
                base_url="http://localhost:11434",
                timeout=10,
                on_text=on_text,
                should_cancel=self._no_cancel,
                tools=[],
            )
        self.assertEqual(self.text_chunks, ["first"])


# ----------------------------------------------------------------------
# _stream_ollama — tool calls
# ----------------------------------------------------------------------

class StreamOllamaToolCallsTests(unittest.TestCase):

    def setUp(self):
        self.text_chunks: List[str] = []

    def _on_text(self, s):
        self.text_chunks.append(s)

    def _no_cancel(self):
        return False

    def test_single_tool_call_with_object_arguments(self):
        ndjson = [
            {"message": {"role": "assistant", "content": "Let me check the cwd."},
             "done": False},
            {"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "run_vmd_command",
                        "arguments": {"command": "pwd"},
                    },
                }],
            }, "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            text, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": "what is pwd"}],
                model="llama3.1",
                system_prompt="",
                base_url="http://localhost:11434",
                timeout=10,
                on_text=self._on_text,
                should_cancel=self._no_cancel,
                tools=[{"name": "run_vmd_command", "description": "",
                        "input_schema": {"type": "object"}}],
            )
        self.assertEqual(text, "Let me check the cwd.")
        self.assertEqual(len(tool_blocks), 1)
        tb = tool_blocks[0]
        self.assertEqual(tb["type"], "tool_use")
        self.assertEqual(tb["name"], "run_vmd_command")
        self.assertEqual(tb["input"], {"command": "pwd"})
        # Synthesized id when Ollama doesn't provide one.
        self.assertTrue(tb["id"].startswith("otc_"))

    def test_string_arguments_get_json_parsed(self):
        # Some Ollama deployments echo arguments as a JSON STRING instead
        # of an object (matching OpenAI's wire format). Should still parse.
        ndjson = [
            {"message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "run_vmd_command",
                        "arguments": '{"command": "mol new x.pdb"}',
                    },
                }],
            }, "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            _, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": ""}],
                model="llama3.1", system_prompt="",
                base_url="http://localhost:11434", timeout=10,
                on_text=self._on_text, should_cancel=self._no_cancel, tools=[],
            )
        self.assertEqual(tool_blocks[0]["input"],
                         {"command": "mol new x.pdb"})

    def test_provided_tool_call_id_is_preserved(self):
        ndjson = [
            {"message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "real_id_abc",
                    "function": {
                        "name": "run_vmd_command",
                        "arguments": {"command": "pwd"},
                    },
                }],
            }, "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            _, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": ""}],
                model="llama3.1", system_prompt="",
                base_url="http://localhost:11434", timeout=10,
                on_text=self._on_text, should_cancel=self._no_cancel, tools=[],
            )
        self.assertEqual(tool_blocks[0]["id"], "real_id_abc")

    def test_multiple_tool_calls_in_one_turn(self):
        ndjson = [
            {"message": {
                "role": "assistant",
                "tool_calls": [
                    {"function": {"name": "run_vmd_command",
                                  "arguments": {"command": "pwd"}}},
                    {"function": {"name": "capture_vmd_snapshot",
                                  "arguments": {"purpose": "x"}}},
                ],
            }, "done": True},
        ]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            _, tool_blocks = _stream_ollama(
                messages=[{"role": "user", "content": ""}],
                model="llama3.1", system_prompt="",
                base_url="http://localhost:11434", timeout=10,
                on_text=self._on_text, should_cancel=self._no_cancel, tools=[],
            )
        self.assertEqual([tb["name"] for tb in tool_blocks],
                         ["run_vmd_command", "capture_vmd_snapshot"])
        # Distinct synthesized ids
        self.assertNotEqual(tool_blocks[0]["id"], tool_blocks[1]["id"])


# ----------------------------------------------------------------------
# _stream_ollama — error paths
# ----------------------------------------------------------------------

class StreamOllamaErrorTests(unittest.TestCase):

    def test_error_field_in_stream_raises_loop_error(self):
        ndjson = [{"error": "model 'badmodel' not found"}]
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=_mock_urlopen(ndjson),
        ):
            with self.assertRaises(ClaudeLoopError) as ctx:
                _stream_ollama(
                    messages=[{"role": "user", "content": ""}],
                    model="badmodel", system_prompt="",
                    base_url="http://localhost:11434", timeout=10,
                    on_text=lambda s: None, should_cancel=lambda: False,
                    tools=[],
                )
        self.assertIn("not found", str(ctx.exception))

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "known Ollama bug (spec §2a 'Unreachable test'): _stream_request retries "
            "URLError and raises a generic 'network error'. P04-T01 passes opts with "
            "connect_retries=0 and removes this mark."
        ),
    )
    def test_unreachable_host_raises_with_hint(self):
        import urllib.error as _ue
        def boom(req, timeout=None):
            raise _ue.URLError("Connection refused")
        with mock.patch(
            "vmd_ai_runtime.claude_loop.urllib.request.urlopen",
            new=boom,
        ):
            with self.assertRaises(ClaudeLoopError) as ctx:
                _stream_ollama(
                    messages=[{"role": "user", "content": ""}],
                    model="llama3.1", system_prompt="",
                    base_url="http://localhost:11434", timeout=10,
                    on_text=lambda s: None, should_cancel=lambda: False,
                    tools=[],
                )
        self.assertIn("unreachable", str(ctx.exception).lower())
        self.assertIn("ollama serve", str(ctx.exception).lower())


# ----------------------------------------------------------------------
# ClaudeToolLoop dispatch
# ----------------------------------------------------------------------

class ClaudeToolLoopDispatchTests(unittest.TestCase):

    def test_is_ollama_property(self):
        loop = ClaudeToolLoop(
            provider_name="ollama",
            api_key="http://localhost:11434",
            model="llama3.1",
        )
        self.assertTrue(loop._is_ollama)
        self.assertFalse(loop._is_anthropic_direct)

    def test_call_dispatches_to_stream_ollama(self):
        loop = ClaudeToolLoop(
            provider_name="ollama",
            api_key="http://localhost:11434",
            model="llama3.1",
        )
        with mock.patch(
            "vmd_ai_runtime.claude_loop._stream_ollama",
            return_value=("hello", []),
        ) as fake_stream:
            text, blocks = loop._call(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="be brief",
                on_text=lambda s: None,
                should_cancel=lambda: False,
            )
        self.assertEqual(text, "hello")
        self.assertEqual(blocks, [])
        # Verify it was actually _stream_ollama that got called with
        # the right base_url
        self.assertEqual(fake_stream.call_count, 1)
        kwargs = fake_stream.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "http://localhost:11434")
        self.assertEqual(kwargs["model"], "llama3.1")


# ----------------------------------------------------------------------
# build_claude_loop("ollama")
# ----------------------------------------------------------------------

class BuildClaudeLoopOllamaTests(unittest.TestCase):

    def test_returns_none_when_no_model(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_MODEL", None)
            env.pop("OLLAMA_MODEL", None)
            loop = build_claude_loop("ollama")
        self.assertIsNone(loop, "build_claude_loop must refuse Ollama without a model")

    def test_returns_loop_when_model_set(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "llama3.1",
            "VMD_AI_OLLAMA_HOST": "http://gpu-box:11434",
        }):
            loop = build_claude_loop("ollama")
        self.assertIsNotNone(loop)
        self.assertTrue(loop._is_ollama)
        self.assertEqual(loop.model, "llama3.1")
        self.assertEqual(loop.api_key, "http://gpu-box:11434")

    def test_aliases_local_ollama_and_local_ollama_underscore(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "qwen2.5-coder",
        }):
            self.assertIsNotNone(build_claude_loop("local-ollama"))
            self.assertIsNotNone(build_claude_loop("local_ollama"))

    def test_explicit_model_overrides_env(self):
        # The UI's provider.set RPC passes the picked model through —
        # it must win over env so the dropdown actually works.
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "llama3.1",
        }):
            loop = build_claude_loop("ollama", model="qwen2.5-coder:7b")
        self.assertIsNotNone(loop)
        self.assertEqual(loop.model, "qwen2.5-coder:7b")

    def test_explicit_model_works_without_env(self):
        # The UI alone should be sufficient — no env required.
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("VMD_AI_OLLAMA_MODEL", None)
            env.pop("OLLAMA_MODEL", None)
            loop = build_claude_loop("ollama", model="qwen2.5-coder:7b")
        self.assertIsNotNone(loop)
        self.assertEqual(loop.model, "qwen2.5-coder:7b")

    def test_blank_explicit_model_falls_back_to_env(self):
        with mock.patch.dict("os.environ", {
            "VMD_AI_OLLAMA_MODEL": "llama3.1",
        }):
            loop = build_claude_loop("ollama", model="   ")
        self.assertIsNotNone(loop)
        self.assertEqual(loop.model, "llama3.1")


# ----------------------------------------------------------------------
# _rescue_json_tool_calls — JSON-in-content rescue
# ----------------------------------------------------------------------

class RescueJsonToolCallsTests(unittest.TestCase):
    """Small Ollama models often paste tool calls into the text body
    instead of emitting structured ``tool_calls``. The rescue helper
    recovers them so the agent loop can still fire the tools."""

    ALLOWED = {"run_vmd_command", "capture_vmd_snapshot"}

    def test_fenced_json_with_arguments(self):
        # The actual shape qwen2.5-coder:7b produced in the repro.
        text = (
            "```json\n"
            "{\n"
            '  "name": "run_vmd_command",\n'
            '  "arguments": {"command": "mol load pdb 1hck.pdb"}\n'
            "}\n"
            "```\n"
            "This will load the structure."
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertEqual(
            blocks[0]["input"], {"command": "mol load pdb 1hck.pdb"}
        )
        self.assertEqual(blocks[0]["type"], "tool_use")

    def test_bare_whole_body_json(self):
        text = '{"name": "capture_vmd_snapshot", "arguments": {"purpose": "check"}}'
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "capture_vmd_snapshot")
        self.assertEqual(blocks[0]["input"], {"purpose": "check"})

    def test_tool_calls_wrapper(self):
        text = json.dumps({
            "tool_calls": [
                {"name": "run_vmd_command", "arguments": {"command": "axes off"}},
                {"name": "capture_vmd_snapshot", "arguments": {"purpose": "verify"}},
            ]
        })
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertEqual(blocks[1]["name"], "capture_vmd_snapshot")

    def test_openai_function_shape_with_string_arguments(self):
        # Some models mimic OpenAI's wire format verbatim.
        text = json.dumps({
            "function": {
                "name": "run_vmd_command",
                "arguments": json.dumps({"command": "rotate x by 90"}),
            }
        })
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["input"], {"command": "rotate x by 90"})

    def test_parameters_field_alias(self):
        # Qwen variants sometimes use "parameters" instead of "arguments".
        text = '{"name": "run_vmd_command", "parameters": {"command": "mol list"}}'
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["input"], {"command": "mol list"})

    def test_unknown_tool_name_rejected(self):
        text = '{"name": "rm_rf_root", "arguments": {"path": "/"}}'
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(blocks, [])

    def test_plain_prose_text_returns_empty(self):
        text = "Sure! I will load 1HCK and render it as cartoon."
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(blocks, [])

    def test_malformed_json_returns_empty(self):
        text = "```json\n{not actually json\n```"
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(blocks, [])

    def test_empty_inputs(self):
        self.assertEqual(_rescue_json_tool_calls("", self.ALLOWED), [])
        self.assertEqual(_rescue_json_tool_calls("anything", set()), [])

    def test_bare_list_of_calls(self):
        text = json.dumps([
            {"name": "run_vmd_command", "arguments": {"command": "axes off"}},
        ])
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)

    # ---- ```tcl / ```vmd block rescue (pass 2) ----

    def test_tcl_fenced_block_wrapped_as_run_vmd_command(self):
        # The actual shape qwen2.5-coder:7b produced in the CDK2 repro.
        text = (
            "Let's execute these steps using VMD Tcl commands.\n\n"
            "```tcl\n"
            "mol load pdb \"CDK2.pdb\"\n"
            "mol representation NewCartoon\n"
            "```\n\n"
            "This will load and render the structure."
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertIn("mol load pdb", blocks[0]["input"]["command"])
        self.assertIn("NewCartoon", blocks[0]["input"]["command"])

    def test_vmd_fenced_block_alias(self):
        # Some models tag with ```vmd instead of ```tcl.
        text = "```vmd\nmol list\n```"
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["input"]["command"], "mol list")

    def test_multiple_tcl_blocks_concatenated(self):
        text = (
            "First load:\n```tcl\nmol load pdb x.pdb\n```\n"
            "Then color:\n```tcl\nmol color Name\n```"
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        cmd = blocks[0]["input"]["command"]
        self.assertIn("mol load pdb x.pdb", cmd)
        self.assertIn("mol color Name", cmd)

    def test_tcl_rescue_skipped_when_run_vmd_command_not_allowed(self):
        # If the agent wasn't offered run_vmd_command, don't fire it.
        text = "```tcl\nmol load pdb x.pdb\n```"
        blocks = _rescue_json_tool_calls(text, {"capture_vmd_snapshot"})
        self.assertEqual(blocks, [])

    def test_bare_unlabeled_fence_does_not_trigger_tcl_rescue(self):
        # No language tag → we don't auto-execute. Avoids firing on
        # Python/shell snippets the model might paste for illustration.
        text = "```\nrm -rf /\n```"
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(blocks, [])

    def test_inline_json_embedded_in_prose(self):
        # The actual shape llama3.1:8b produced after a failed tool
        # call: prose, blank line, then a bare {...} mid-text. No fence.
        text = (
            "It seems that the PDB files I've tried so far are not loading "
            "correctly. Let me try a different approach.\n\n"
            ' {"name": "run_vmd_command", "parameters": '
            '{"command": "mol load pdb \\"1hck.pdb\\""}}\n'
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertIn("1hck.pdb", blocks[0]["input"]["command"])

    def test_inline_json_after_failed_attempt_text(self):
        # Variant: prose with trailing JSON that lacks the parameters
        # alias — uses arguments directly.
        text = (
            "Sorry, let me retry: "
            '{"name": "capture_vmd_snapshot", "arguments": {"purpose": "verify"}}'
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "capture_vmd_snapshot")

    def test_json_pass_beats_tcl_pass(self):
        # If both a JSON tool call AND a tcl block are present, the
        # structured JSON wins (model was at least trying to do it right).
        text = (
            '```json\n'
            '{"name": "run_vmd_command", "arguments": {"command": "axes off"}}\n'
            '```\n'
            '```tcl\nmol load pdb x.pdb\n```'
        )
        blocks = _rescue_json_tool_calls(text, self.ALLOWED)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["input"]["command"], "axes off")


# ----------------------------------------------------------------------
# _stream_ollama — rescue wired into the stream
# ----------------------------------------------------------------------

class StreamOllamaJsonRescueTests(unittest.TestCase):
    """End-to-end: when the stream returns prose+JSON instead of
    structured tool_calls, the rescue path must fire and the function
    must return synthesized tool_use blocks (and drop the JSON text
    from history so the model doesn't learn to repeat the pattern)."""

    def _run(self, ndjson_events):
        on_text_received = []

        def on_text(chunk):
            on_text_received.append(chunk)

        def should_cancel():
            return False

        fake_resp = _FakeNdjsonResponse(ndjson_events)
        with mock.patch(
            "vmd_ai_runtime.claude_loop._stream_request",
            return_value=fake_resp,
        ):
            text, blocks = _stream_ollama(
                messages=[{"role": "user", "content": "load 1HCK"}],
                model="qwen2.5-coder:7b",
                system_prompt="",
                base_url="http://localhost:11434",
                timeout=10,
                on_text=on_text,
                should_cancel=should_cancel,
            )
        return text, blocks, on_text_received

    def test_rescues_when_no_structured_tool_calls(self):
        # Stream a single chunk whose content is a JSON tool call
        # (the qwen2.5-coder:7b symptom).
        json_payload = (
            "```json\n"
            '{"name": "run_vmd_command", '
            '"arguments": {"command": "mol load pdb 1hck.pdb"}}\n'
            "```"
        )
        events = [
            {"message": {"role": "assistant", "content": json_payload}},
            {"done": True},
        ]
        text, blocks, streamed = self._run(events)

        # Rescue fired → one synthesized tool_use block.
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertEqual(
            blocks[0]["input"], {"command": "mol load pdb 1hck.pdb"}
        )
        # Synthesized blocks get an "otc_rescue_" id when the JSON
        # didn't carry one.
        self.assertTrue(blocks[0]["id"].startswith("otc_rescue_"))

        # Text was streamed to the UI live (so the user sees what the
        # model produced) but dropped from history to avoid teaching
        # the model to repeat the JSON-in-text pattern.
        self.assertIn("run_vmd_command", "".join(streamed))
        self.assertEqual(text, "")

    def test_rescues_tcl_fenced_block(self):
        # The CDK2 repro: model emits prose + ```tcl block, no JSON, no
        # structured tool_calls. The Tcl rescue path must wrap it as
        # a run_vmd_command call.
        content = (
            "To visualize ATP binding to CDK2:\n\n"
            "```tcl\n"
            "mol load pdb \"CDK2.pdb\"\n"
            "mol representation NewCartoon\n"
            "mol addrep top\n"
            "```\n\n"
            "This loads the structure and applies a cartoon rep."
        )
        events = [
            {"message": {"role": "assistant", "content": content}},
            {"done": True},
        ]
        text, blocks, _ = self._run(events)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        self.assertIn("mol load pdb", blocks[0]["input"]["command"])
        self.assertIn("NewCartoon", blocks[0]["input"]["command"])
        # History text is cleared so the model doesn't re-learn the pattern.
        self.assertEqual(text, "")

    def test_no_rescue_when_structured_tool_calls_present(self):
        # If the model already emitted real tool_calls, the rescue
        # path is skipped and text is preserved verbatim.
        events = [
            {
                "message": {
                    "role": "assistant",
                    "content": "Loading the structure.",
                    "tool_calls": [{
                        "function": {
                            "name": "run_vmd_command",
                            "arguments": {"command": "mol load pdb 1hck.pdb"},
                        },
                    }],
                }
            },
            {"done": True},
        ]
        text, blocks, _ = self._run(events)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["name"], "run_vmd_command")
        # Real tool_calls path doesn't strip text.
        self.assertEqual(text, "Loading the structure.")
        # And the id is the regular otc_ counter, not otc_rescue_.
        self.assertFalse(blocks[0]["id"].startswith("otc_rescue_"))


if __name__ == "__main__":
    unittest.main()
