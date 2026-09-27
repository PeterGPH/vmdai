"""C4: loop guard in the loop — nudge, stop, and the tool-less wrap-up call."""
from __future__ import annotations

import json
import threading
from unittest import mock

import pytest

from helpers.fake_http import (
    FakeHTTP, anthropic_text, anthropic_tool_call, http_error,
    ollama_text, ollama_tool_call, ollama_tool_calls, openai_text, openai_tool_call,
)
from vmd_ai_runtime.claude_loop import (
    WRAP_UP_INSTRUCTION, ClaudeToolLoop, LoopOptions, RunContext, _apply_tool_mode,
)
from vmd_ai_runtime.events import EventQueue

FAIL = {"ok": False, "output": "", "error": 'invalid command name "mol_color"'}

PROVIDERS = {
    "ollama": dict(api_key="http://ollama.test", base_url="http://ollama.test",
                   tool=ollama_tool_call, text=ollama_text),
    "anthropic-direct": dict(api_key="sk-ant-test", base_url=None,
                             tool=anthropic_tool_call, text=anthropic_text),
    "openrouter": dict(api_key="sk-or-test", base_url="https://openrouter.ai/api/v1",
                       tool=openai_tool_call, text=openai_text),
    "openai-compatible": dict(api_key="EMPTY", base_url="http://vllm.test/v1",
                              tool=openai_tool_call, text=openai_text),
}


class ScriptBridge:
    """Strict six keywords (no supports_call_meta); returns scripted results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        self.calls.append(dict(tool_input))
        return dict(self.results[min(len(self.calls), len(self.results)) - 1])


def make_loop(provider, **opts):
    p = PROVIDERS[provider]
    options = LoopOptions(loop_guard=True, base_url=p["base_url"], **opts)
    return ClaudeToolLoop(provider_name=provider, api_key=p["api_key"],
                          model="qwen3.8:27b", options=options)


def run_loop(loop, fake, bridge, *, cancel=None, events=None, out=None):
    cancel = cancel or threading.Event()
    ctx = RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                     on_event=events.append if events is not None else None, messages_out=out)
    with mock.patch("urllib.request.urlopen", fake):
        return loop.run(prompt="color the protein red", system_prompt="You are ChatVMD.",
                        tool_bridge=bridge, session_id="sess_0123456789ab",
                        session_queue=EventQueue(), cancel_event=cancel,
                        on_chunk=lambda t: None, ctx=ctx)


def stuck_script(provider, wrap):
    p = PROVIDERS[provider]
    return [p["tool"]("mol_color x", "id_%d" % i) for i in range(4)] + [wrap]


def _meta(event):
    return event.get("metadata") or {}


def test_nudge_once_in_next_body():
    fake = FakeHTTP(stuck_script("ollama", ollama_text("Summary: nothing changed.")))
    bridge = ScriptBridge([FAIL])
    text = run_loop(make_loop("ollama"), fake, bridge)
    assert len(fake.bodies) == 5
    assert json.dumps(fake.bodies[2]).count("Loop check:") == 0
    assert json.dumps(fake.bodies[3]).count("Loop check: this exact call has now run 3 times") == 1
    assert len(bridge.calls) == 4
    assert text == "Summary: nothing changed."


def test_wrapup_ollama_no_tools():
    fake = FakeHTTP(stuck_script("ollama", ollama_text("Summary.")))
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]))
    wrap = fake.bodies[4]
    assert "tools" not in wrap
    assert "tools" in fake.bodies[3]
    assert wrap["messages"][-1] == {"role": "user", "content": WRAP_UP_INSTRUCTION}
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


@pytest.mark.parametrize("provider", ["anthropic-direct", "openrouter", "openai-compatible"])
def test_wrapup_tool_choice_none_anthropic_openrouter_openai(provider):
    fake = FakeHTTP(stuck_script(provider, PROVIDERS[provider]["text"]("Summary.")))
    loop = make_loop(provider)
    run_loop(loop, fake, ScriptBridge([FAIL]))
    wrap = fake.bodies[4]
    expected = {"type": "none"} if provider == "anthropic-direct" else "none"
    assert wrap["tool_choice"] == expected
    assert "tools" in wrap
    assert "tool_choice" not in fake.bodies[3]
    assert WRAP_UP_INSTRUCTION in json.dumps(wrap)
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


def test_status_stuck_wrapped_up():
    events, out = [], []
    summary = "Summary: mol_color is not a VMD command."
    loop = make_loop("ollama")
    run_loop(loop, FakeHTTP(stuck_script("ollama", ollama_text(summary))), ScriptBridge([FAIL]),
             events=events, out=out)
    phases = [_meta(e).get("phase") for e in events if _meta(e).get("kind") == "status"]
    assert phases.count("loop_detected") == 2
    assert phases.count("wrapping_up") == 1
    stops = [_meta(e) for e in events if _meta(e).get("phase") == "loop_detected"]
    assert [m.get("stop") for m in stops] == [False, True]
    finals = [e for e in events
              if e["role"] == "assistant" and e["type"] == "message" and _meta(e).get("final")]
    assert finals[-1]["text"] == summary
    assert out[-1] == {"role": "assistant", "content": [{"type": "text", "text": summary}]}
    assert WRAP_UP_INSTRUCTION not in json.dumps(out)
    assert loop.last_status == "stuck"
    assert loop.last_wrapped_up is True
    assert loop.last_turns == 5
    assert loop.last_final_text_empty is False


def test_calls_after_stop_not_run():
    # C4: tool calls left in the turn after the stop are not run; each gets
    # executed "no" and "not executed: loop guard", and still has a row.
    events = []
    script = [ollama_tool_call("mol_color x") for _ in range(3)]
    script += [ollama_tool_calls("mol_color x", "mol new a.pdb"), ollama_text("Summary.")]
    fake = FakeHTTP(script)
    bridge = ScriptBridge([FAIL])
    loop = make_loop("ollama")
    run_loop(loop, fake, bridge, events=events)
    assert [c["command"] for c in bridge.calls] == ["mol_color x"] * 4
    finished = [_meta(e) for e in events if _meta(e).get("kind") == "tool.finished"]
    assert len(finished) == 5
    assert (finished[-1]["executed"], finished[-1]["error"]) == ("no", "not executed: loop guard")
    assert "not executed: loop guard" in json.dumps(fake.bodies[4])
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


def test_max_turns_wrapup():
    fake = FakeHTTP([ollama_tool_call("mol new a.pdb"), ollama_tool_call("mol new b.pdb"),
                     ollama_text("Summary: loaded a and b.")])
    loop = make_loop("ollama", max_turns=2)
    text = run_loop(loop, fake, ScriptBridge([{"ok": True, "output": "0", "error": ""},
                                              {"ok": True, "output": "1", "error": ""}]))
    assert len(fake.bodies) == 3
    assert "tools" not in fake.bodies[2]
    assert loop.last_status == "max_turns"
    assert loop.last_wrapped_up is True
    assert text == "Summary: loaded a and b."
    assert loop.last_turns == 3


def test_stop_during_wrapup_cancelled():
    cancel = threading.Event()

    def on_chat(body):
        if WRAP_UP_INSTRUCTION in json.dumps(body):
            cancel.set()

    fake = FakeHTTP(stuck_script("ollama", ollama_text("half a summ")), on_chat=on_chat)
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]), cancel=cancel)
    assert loop.last_status == "cancelled"
    assert loop.last_wrapped_up is False


def test_wrapup_error_is_notice_not_raise():
    events = []
    fake = FakeHTTP(stuck_script("ollama", http_error("http://ollama.test/api/chat", 400, b'{"error":"boom"}')))
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]), events=events)  # must not raise
    assert loop.last_status == "stuck"
    assert loop.last_wrapped_up is False
    assert "400" in (loop.last_wrap_up_error or "")
    notes = [_meta(e) for e in events if _meta(e).get("phase") == "wrapping_up"]
    assert notes[-1]["message"].startswith("Summary failed:")
    assert not [e for e in events if e["role"] == "error"]


def test_guard_off_without_options():
    fake = FakeHTTP([ollama_tool_call("mol_color x")] * 4 + [ollama_text("gave up")])
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    with mock.patch("urllib.request.urlopen", fake):
        text = loop.run(prompt="p", system_prompt="s", tool_bridge=ScriptBridge([FAIL]),
                        session_id="s", session_queue=EventQueue(),
                        cancel_event=threading.Event(), on_chunk=lambda t: None)
    assert len(fake.bodies) == 5
    assert all("tools" in body for body in fake.bodies)
    assert "Loop check" not in json.dumps(fake.bodies)
    assert text == "gave up"


def test_apply_tool_mode_unit():
    body = {"tools": [1]}
    _apply_tool_mode(body, "ollama", "none")
    assert "tools" not in body
    body = {"tools": [1]}
    _apply_tool_mode(body, "anthropic", "none")
    assert body["tool_choice"] == {"type": "none"}
    body = {"tools": [1]}
    _apply_tool_mode(body, "openai", "none")
    assert body["tool_choice"] == "none"
    for mode in (None, "auto"):
        body = {"tools": [1]}
        _apply_tool_mode(body, "anthropic", mode)
        assert body == {"tools": [1]}


def test_options_none_no_guard_no_wrapup():
    # Carry-forward (controller): with options=None there is no loop guard
    # and no wrap-up call — request count and end status unchanged from
    # today's behaviour even when the model repeats the same failing call
    # past what would trigger a nudge/stop under options.loop_guard.
    fake = FakeHTTP([ollama_tool_call("mol_color x")] * 28)
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    with mock.patch("urllib.request.urlopen", fake):
        text = loop.run(prompt="p", system_prompt="s", tool_bridge=ScriptBridge([FAIL]),
                        session_id="s", session_queue=EventQueue(),
                        cancel_event=threading.Event(), on_chunk=lambda t: None)
    assert len(fake.bodies) == 28
    assert all("tools" in body for body in fake.bodies)
    assert "Loop check" not in json.dumps(fake.bodies)
    assert "tool_choice" not in json.dumps(fake.bodies)
    assert loop.last_status == "max_turns"
    assert loop.last_wrapped_up is False
    assert loop.last_turns == 28
    assert text == ""


def test_wrap_up_attrs_defined_before_run():
    # M8: a caller (plan 07's getattr defaults notwithstanding) must see
    # real values on a fresh loop, not an AttributeError, before any run().
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    assert loop.last_wrapped_up is False
    assert loop.last_wrap_up_error is None
