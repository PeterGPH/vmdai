"""P02-T07: report_cancelled, turn_retry, raise_stream_errors, guard_truncation and max_turns (§2a, §5)."""
from __future__ import annotations

import threading
import urllib.request

import pytest

from helpers.fake_provider import (
    FakeUrlopen,
    SpyBridge,
    StatusRecorder,
    anthropic_error,
    anthropic_text,
    anthropic_tool_use,
    run_loop,
    scripted_call,
    tool_use,
)
from vmd_ai_runtime.claude_loop import (
    TRUNCATED_TOOL_ERROR,
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
)

CHAT_ID = "chat_0123456789ab"


def _loop(opts=None, provider="openrouter"):
    if provider == "anthropic-direct":
        return ClaudeToolLoop("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5", options=opts)
    return ClaudeToolLoop("openrouter", "sk-or-test", "test/model", options=opts)


def _ctx(events):
    return RunContext(request_id="req_flags", chat_id=CHAT_ID, on_event=events.append)


def _of_kind(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def _serve(monkeypatch, *bodies):
    fake = FakeUrlopen(list(bodies))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _stop_while_streaming(cancel, text):
    def _call(messages, system_prompt, on_text, should_cancel):
        on_text(text)
        cancel.set()  # the user pressed Stop while this turn streamed
        return text, []
    return _call


def test_report_cancelled_on():
    cancel = threading.Event()
    loop = _loop(LoopOptions(report_cancelled=True))
    loop._call = _stop_while_streaming(cancel, "partial")
    assert run_loop(loop, cancel_event=cancel) == "partial"
    assert loop.last_status == "cancelled"
    assert loop.last_final_text_empty is False


def test_report_cancelled_off():
    for opts in (None, LoopOptions()):
        cancel = threading.Event()
        loop = _loop(opts)
        loop._call = _stop_while_streaming(cancel, "partial")
        run_loop(loop, cancel_event=cancel)
        assert loop.last_status == "complete"  # today's behaviour


def test_turn_retry_once_after_stream_drop():
    events, seen = [], []
    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call(
        [ConnectionResetError(54, "Connection reset by peer"), ("recovered", [])], seen=seen)
    assert run_loop(loop, ctx=_ctx(events)) == "recovered"
    assert len(seen) == 2 and seen[0] == seen[1]  # the same messages are resent
    assert _of_kind(events, "turn.retry") == [
        {"kind": "turn.retry", "reason": "stream dropped", "request_id": "req_flags", "turn": 1}]
    assert loop.last_status == "complete"
    assert loop.last_turns == 1


def test_turn_retry_not_after_tool_ran():
    """The retry repeats only the model call: a tool that already ran never runs again,
    and one turn gets at most turn_retry retries."""
    bridge = SpyBridge()
    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call([
        ("", [tool_use("tc_0", "run_vmd_command", command="mol new 1hck.pdb")]),
        ConnectionResetError(54, "reset"),
        ("done", []),
    ])
    assert run_loop(loop, bridge=bridge) == "done"
    assert [c["tool_input"]["command"] for c in bridge.calls] == ["mol new 1hck.pdb"]
    assert loop.last_turns == 2

    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call([ConnectionResetError(54, "reset"),
                                ConnectionResetError(54, "reset again")])
    with pytest.raises(ClaudeLoopError, match="API call failed on turn 1"):
        run_loop(loop)
    assert loop.last_status == "error"

    loop = _loop(None)  # options=None: no retry at all
    loop._call = scripted_call([ConnectionResetError(54, "reset"), ("never", [])])
    with pytest.raises(ClaudeLoopError, match="API call failed on turn 1"):
        run_loop(loop)


def test_sse_error_event_raises_when_flag_on(monkeypatch):
    _serve(monkeypatch, anthropic_error("api_error", "Internal server error"))
    recorder = StatusRecorder()
    loop = _loop(LoopOptions(raise_stream_errors=True), provider="anthropic-direct")
    loop.recorder = recorder
    with pytest.raises(ClaudeLoopError, match="API stream error: Internal server error"):
        run_loop(loop)
    assert recorder.status == "error"
    assert loop.last_status == "error"


def test_sse_overloaded_retries_as_529(monkeypatch, sleep_calls):
    fake = _serve(monkeypatch, anthropic_error("overloaded_error", "Overloaded"),
                  anthropic_text("Hello"))
    events = []
    loop = _loop(LoopOptions(raise_stream_errors=True), provider="anthropic-direct")
    assert run_loop(loop, ctx=_ctx(events)) == "Hello"
    assert len(fake.chat_requests) == 2
    assert sleep_calls == [2.0]
    assert _of_kind(events, "status") == [{
        "kind": "status", "phase": "retrying", "attempt": 1, "max_attempts": 5,
        "wait_s": 2.0, "http_status": 529, "message": "Overloaded",
        "request_id": "req_flags", "turn": 1,
    }]


def test_sse_error_ignored_when_flag_off(monkeypatch):
    _serve(monkeypatch, anthropic_error("api_error", "Internal server error"))
    loop = _loop(None, provider="anthropic-direct")
    assert run_loop(loop) == ""  # today: an empty answer, status complete
    assert loop.last_status == "complete"
    assert loop.last_final_text_empty is True


def test_guard_truncation_blocks_tool_calls(monkeypatch):
    fake = _serve(
        monkeypatch,
        anthropic_tool_use("toolu_1", "run_vmd_command", '{"command": "mol new', stop_reason="max_tokens"),
        anthropic_text("I will make a shorter call."),
    )
    events, bridge = [], SpyBridge()
    loop = _loop(LoopOptions(guard_truncation=True), provider="anthropic-direct")
    run_loop(loop, bridge=bridge, ctx=_ctx(events))
    assert bridge.calls == []
    result_msg = fake.chat_requests[1]["body"]["messages"][-1]
    block = result_msg["content"][0]
    assert result_msg["role"] == "user"
    assert (block["type"], block["tool_use_id"], block["is_error"]) == ("tool_result", "toolu_1", True)
    assert TRUNCATED_TOOL_ERROR in block["content"]
    assert [m["phase"] for m in _of_kind(events, "status")] == ["turn_truncated"]
    assert loop.last_tool_calls == 1


def test_guard_truncation_off_runs_with_empty_input(monkeypatch):
    for opts in (None, LoopOptions()):  # options=None is today's path (plan-01 carry-forward)
        _serve(
            monkeypatch,
            anthropic_tool_use("toolu_1", "run_vmd_command", '{"command": "mol new', stop_reason="max_tokens"),
            anthropic_text("ok"),
        )
        bridge = SpyBridge()
        run_loop(_loop(opts, provider="anthropic-direct"), bridge=bridge)
        assert bridge.calls == [{"tool_call_id": "toolu_1", "tool_name": "run_vmd_command",
                                 "tool_input": {}}]


def test_max_turns_from_options():
    bridge = SpyBridge()
    loop = _loop(LoopOptions(max_turns=3))
    loop._call = scripted_call([
        ("", [tool_use(f"tc_{n}", "run_vmd_command", command=f"puts {n}")]) for n in range(10)])
    run_loop(loop, bridge=bridge)
    assert len(bridge.calls) == 3
    assert loop.last_status == "max_turns"
    assert (loop.last_turns, loop.last_tool_calls) == (3, 3)
    assert loop.last_final_text_empty is True

    # options=None keeps today's cap (plan-01 carry-forward): MAX_TURNS model calls, no 29th,
    # and the recorder closes the run as 'max_turns' exactly as before LoopOptions existed.
    bridge, recorder, seen = SpyBridge(), StatusRecorder(), []
    loop = _loop(None)
    loop.recorder = recorder
    loop._call = scripted_call(
        [("", [tool_use(f"tc_{n}", "run_vmd_command", command=f"puts {n}")]) for n in range(40)],
        seen=seen)
    assert run_loop(loop, bridge=bridge) == ""
    assert ClaudeToolLoop.MAX_TURNS == 28
    assert len(seen) == 28
    assert [c["tool_input"]["command"] for c in bridge.calls] == [f"puts {n}" for n in range(28)]
    assert recorder.status == "max_turns"
    assert (loop.last_status, loop.last_turns, loop.last_tool_calls) == ("max_turns", 28, 28)
