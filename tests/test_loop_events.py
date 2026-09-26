"""P02-T08: call_key, on_event emission and canonical messages_out (§2a, §2b, §2c)."""
from __future__ import annotations

import re
import urllib.request

from helpers.fake_provider import (
    FakeUrlopen,
    SpyBridge,
    StatusRecorder,
    event_kinds,
    ollama_text,
    run_loop,
    scripted_call,
    tool_use,
)
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext

CHAT_ID = "chat_0123456789ab"
LOAD = tool_use("tc_0", "run_vmd_command", command="mol new 1hck.pdb")


def _loop(opts=None):
    return ClaudeToolLoop("openrouter", "sk-or-test", "test/model",
                          options=LoopOptions() if opts is None else opts)


def _meta(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def test_event_sequence_two_turns():
    events = []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])])
    run_loop(loop, ctx=RunContext("req_1", CHAT_ID, on_event=events.append))
    assert event_kinds(events) == [
        ("system", "state", "turn.started"),
        ("assistant", "chunk", None),
        ("assistant", "message", None),
        ("system", "state", "tool.started"),
        ("system", "state", "tool.finished"),
        ("system", "state", "turn.started"),
        ("assistant", "chunk", None),
        ("assistant", "message", None),
    ]
    sealed = [(e["text"], e["metadata"]["final"], e["metadata"]["turn"])
              for e in events if e["type"] == "message"]
    assert sealed == [("Loading.", False, 1), ("Done.", True, 2)]
    assert all(e["metadata"]["request_id"] == "req_1" for e in events)
    started, = _meta(events, "tool.started")
    finished, = _meta(events, "tool.finished")
    key = started["call_key"]
    assert re.fullmatch(r"[0-9a-f]{12}", key)
    assert started == {"kind": "tool.started", "call_key": key, "tool_call_id": "tc_0",
                       "tool_name": "run_vmd_command", "executor": "tcl", "origin": "model",
                       "input": {"command": "mol new 1hck.pdb"},
                       "request_id": "req_1", "turn": 1}
    assert finished == {"kind": "tool.finished", "call_key": key,
                        "tool_name": "run_vmd_command", "executor": "tcl", "ok": True,
                        "executed": "yes", "output": "ok", "error": "", "truncated": False,
                        "duration_ms": finished["duration_ms"], "statements": None,
                        "blocked": None, "output_path": None, "output_bytes": 2,
                        "image": None, "saved_path": None, "late": False,
                        "request_id": "req_1", "turn": 1}


def test_runtime_tools_emit_pair_with_executor_runtime():
    events, bridge = [], SpyBridge()
    loop = _loop()  # docs_search is None, so search_docs answers with an error
    loop._call = scripted_call([("", [tool_use("tc_0", "search_docs", query="mol new")]),
                                ("ok", [])])
    run_loop(loop, bridge=bridge, ctx=RunContext("req_2", CHAT_ID, on_event=events.append))
    assert bridge.calls == []
    started, = _meta(events, "tool.started")
    finished, = _meta(events, "tool.finished")
    assert (started["executor"], finished["executor"]) == ("runtime", "runtime")
    assert finished["ok"] is False
    assert "search_docs is unavailable" in finished["error"]


def test_rescued_origin(monkeypatch):
    call_json = '{"name": "run_vmd_command", "arguments": {"command": "mol new 1hck.pdb"}}'
    monkeypatch.setattr(urllib.request, "urlopen",
                        FakeUrlopen([ollama_text(call_json), ollama_text("Loaded.")]))
    events, bridge = [], SpyBridge()
    loop = ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b", options=LoopOptions())
    out = run_loop(loop, bridge=bridge, ctx=RunContext("req_r", CHAT_ID, on_event=events.append))
    assert out == "Loaded."
    assert [(s["origin"], s["tool_call_id"]) for s in _meta(events, "tool.started")] == [
        ("rescued", "otc_rescue_1")]
    sealed = [e["text"] for e in events if e["type"] == "message"]
    assert sealed == ["", "Loaded."]  # sealing hides the JSON the rescue consumed
    assert bridge.calls[0]["tool_input"] == {"command": "mol new 1hck.pdb"}


def test_messages_out_canonical_ids():
    events, out, seen = [], [], []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])], seen=seen)
    run_loop(loop, prompt="load it",
             ctx=RunContext("req_3", CHAT_ID, on_event=events.append, messages_out=out))
    key = _meta(events, "tool.started")[0]["call_key"]
    assert out[0] == {"role": "user", "content": "load it"}
    assert out[1]["content"][1]["id"] == "call_" + key
    assert out[2]["content"][0]["tool_use_id"] == "call_" + key
    # The in-run history that turn 2 sent keeps the model's own ids.
    assert seen[1][1]["content"][1]["id"] == "tc_0"
    assert seen[1][2]["content"][0]["tool_use_id"] == "tc_0"


def test_final_turn_only_in_messages_out():
    out, seen = [], []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])], seen=seen)
    run_loop(loop, ctx=RunContext("req_4", CHAT_ID, messages_out=out))
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    assert out[3] == {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}
    assert len(seen) == 2 and len(seen[1]) == 3  # no request ever carries the final turn
    assert loop.last_final_text_empty is False

    empty_out = []
    loop = _loop()
    loop._call = scripted_call([("", [LOAD]), ("", [])])
    run_loop(loop, ctx=RunContext("req_5", CHAT_ID, messages_out=empty_out))
    assert [m["role"] for m in empty_out] == ["user", "assistant", "user"]
    assert loop.last_final_text_empty is True


def test_on_event_exception_does_not_break_run():
    class BrokenOut:
        def append(self, message):
            raise OSError("disk full")

    def broken_sink(item):
        raise RuntimeError("sink broke")

    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])])
    ctx = RunContext("req_6", CHAT_ID, on_event=broken_sink, messages_out=BrokenOut())
    assert run_loop(loop, ctx=ctx) == "Done."
    assert loop.last_status == "complete"
    assert loop.last_tool_calls == 1


def test_recorder_chat_id_from_ctx():
    recorder = StatusRecorder()
    loop = ClaudeToolLoop("openrouter", "sk-or-test", "test/model", recorder=recorder)
    loop._call = scripted_call([("hi", [])])
    run_loop(loop, ctx=RunContext("req_7", CHAT_ID))
    assert recorder.chat_id == CHAT_ID
    run_loop(loop)  # ctx=None keeps the benchmark's session_id
    assert recorder.chat_id == "sess_test"
