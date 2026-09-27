"""P07-T01: event_protocol 2 negotiation and the v2 mapping of loop events (§2a, §2c)."""
from __future__ import annotations

import pytest

from helpers.app_driver import TOKEN, call, make_token_app, result, send, state_of, wait_idle
from helpers.events_v2 import (MODEL, FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds,
                               of_kind, poll_all, product_result, run_cmd, start_v2)

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}


def _script():
    return [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD], reasoning="Load it first.",
                   status={"phase": "loading_model", "message": "Loading qwen3.8:27b"}, usage=USAGE),
        ScriptTurn(text="Partial", drop_after_text=True),   # turn 2 drops once: turn.retry
        ScriptTurn(text="Done.", usage=USAGE),
    ]


def _run(tmp_path, *, event_protocol=2, token=TOKEN):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(_script())
    app.tool_bridge = ProductBridge([product_result(output="0")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol, token=token)
    mode = "full" if token else "local_first"
    # model=MODEL keeps a tokenless session's model override (P03-T04/T08) from
    # swapping the scripted loop for a real one; token sessions ignore it.
    reply = result(send(app, session, "load 1hck", conversation_mode=mode, model=MODEL))
    wait_idle(app, session)
    return app, session, reply, poll_all(app, session)


def test_shape_per_kind(tmp_path):
    _app, session, reply, events = _run(tmp_path)
    rid = reply["request_id"]
    assert session.result["event_protocol"] == 2
    assert all(e["metadata"]["v"] == 2 for e in events if e["metadata"].get("request_id") == rid)

    assert of_kind(events, "turn.started") == [
        {"kind": "turn.started", "request_id": rid, "turn": 1, "v": 2},
        {"kind": "turn.started", "request_id": rid, "turn": 2, "v": 2},
    ]
    reasoning = [e for e in events if e["role"] == "reasoning" and e["type"] == "chunk"]
    assert "".join(e["text"] for e in reasoning) == "Load it first."
    assert reasoning[0]["metadata"] == {"request_id": rid, "turn": 1, "v": 2}
    chunk = next(e for e in events if e["role"] == "assistant" and e["type"] == "chunk")
    assert chunk["metadata"] == {"request_id": rid, "turn": 1, "v": 2}
    sealed = [(e["text"], e["metadata"]) for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert sealed == [
        ("Loading.", {"request_id": rid, "turn": 1, "final": False, "v": 2}),
        ("Done.", {"request_id": rid, "turn": 2, "final": True, "v": 2}),
    ]

    started, = of_kind(events, "tool.started")
    assert set(started) == {"kind", "request_id", "turn", "call_key", "tool_call_id", "tool_name",
                            "executor", "origin", "input", "v"}
    assert (started["tool_call_id"], started["tool_name"], started["executor"], started["origin"],
            started["input"]) == ("tc_1", "run_vmd_command", "tcl", "model", {"command": "mol new 1hck.pdb"})
    finished, = of_kind(events, "tool.finished")
    assert set(finished) == {"kind", "request_id", "turn", "call_key", "tool_name", "executor", "ok",
                             "executed", "output", "error", "truncated", "duration_ms", "statements",
                             "blocked", "output_path", "output_bytes", "image", "saved_path", "late", "v"}
    assert finished["call_key"] == started["call_key"]
    assert (finished["ok"], finished["executed"], finished["output"], finished["late"]) == (True, "yes", "0", False)

    usage = of_kind(events, "usage")
    assert usage[0] == dict(USAGE, kind="usage", request_id=rid, turn=1, v=2)
    assert of_kind(events, "status") == [{"kind": "status", "phase": "loading_model",
                                          "message": "Loading qwen3.8:27b", "request_id": rid,
                                          "turn": 1, "v": 2}]
    assert of_kind(events, "turn.retry") == [{"kind": "turn.retry", "reason": "stream dropped",
                                              "request_id": rid, "turn": 2, "v": 2}]


@pytest.mark.parametrize("token", [TOKEN, ""], ids=["token_v1", "tokenless"])
def test_v1_session_unchanged(tmp_path, token):
    """Review focus 1: a v1 session sees exactly today's events, and none tagged v2."""
    _app, _session, _reply, events = _run(tmp_path, event_protocol=1, token=token)
    assert all("v" not in e["metadata"] and "kind" not in e["metadata"] for e in events)
    assert not [e for e in events if e["role"] == "reasoning" or e["type"] == "state"]
    assert kinds(events) == ([("system", "lifecycle", None), ("system", "message", None),
                              ("user", "message", None)]
                             + [("assistant", "chunk", None)] * 3
                             + [("assistant", "message", None)])
    assert "".join(e["text"] for e in events if e["type"] == "chunk") == "Loading.PartialDone."
    assert events[-1]["text"] == "Done."


def test_tokenless_cannot_negotiate_v2(tmp_path):
    app, session, _reply, events = _run(tmp_path, event_protocol=2, token="")
    assert "event_protocol" not in session.result          # exactly today's session.start fields
    assert state_of(app, session).event_protocol == 1
    assert all("v" not in e["metadata"] for e in events)
    assert not [e for e in events if e["type"] == "state"]


def test_no_double_emission(tmp_path):
    app, _session, reply, events = _run(tmp_path)
    for event in events:
        if event["role"] == "assistant":
            assert event["metadata"].get("v") == 2 and "turn" in event["metadata"], event
    per_turn = {}
    for event in events:
        if event["role"] == "assistant" and event["type"] == "chunk":
            per_turn.setdefault(event["metadata"]["turn"], []).append(event["text"])
    assert {turn: "".join(parts) for turn, parts in per_turn.items()} == {1: "Loading.", 2: "PartialDone."}
    assert [e["metadata"]["turn"] for e in events
            if e["role"] == "assistant" and e["type"] == "message"] == [1, 2]
    assert not [e for e in events if e["type"] == "lifecycle" and e["text"] == "cancelled"]
    stored = app.store.read_events(reply["chat_id"], limit=10 ** 9)
    assert not [e for e in stored if e["role"] == "assistant" and "v" not in e["metadata"]]


@pytest.mark.parametrize("event_protocol,expect_tool_result", [(2, False), (1, True)])
def test_no_tool_result_for_v2(tmp_path, event_protocol, expect_tool_result):
    app = make_token_app(tmp_path)                          # the real VmdToolBridge
    app.claude_loop = MetaScriptedLoop([ScriptTurn(tool_blocks=[LOAD]), ScriptTurn(text="Done.")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    answer = lambda meta: {"ok": True, "output": "0", "statements_total": 1, "statements_applied": 1}
    with FakePlugin(app, session, answer=answer):
        result(send(app, session, "load 1hck"))
        wait_idle(app, session)
    events = poll_all(app, session)
    assert bool([e for e in events if e["role"] == "tool_result"]) is expect_tool_result
    if event_protocol == 2:
        finished, = of_kind(events, "tool.finished")
        assert (finished["ok"], finished["output"], finished["statements"]) == (
            True, "0", {"total": 1, "applied": 1, "failed": None})


def test_late_call_key_result_lands_in_issuing_chat(tmp_path):
    """Standing M7 carry-forward (plan 05): a late call_key result is stored
    in the chat that issued the call, never in the session's current chat,
    which chat.resume may have since switched away from."""
    app = make_token_app(tmp_path)                          # the real VmdToolBridge
    app.tool_bridge.cancel_grace_s = 0.0                     # deterministic instant give-up
    app.claude_loop = MetaScriptedLoop([ScriptTurn(tool_blocks=[LOAD]), ScriptTurn(text="Done.")])
    session = start_v2(app, tmp_path, event_protocol=1)
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:  # ack, then hold forever
        result(send(app, session, "load 1hck"))
        call_key, = plugin.wait_held(1)
        chat_a = state_of(app, session).chat_id

        result(call(app, "chat.cancel", {"session_id": session.session_id}, session))
        wait_idle(app, session)

        chat_b = app.store.create_chat(title_hint="Chat B")
        result(call(app, "chat.resume", {"chat_id": chat_b}, session))
        assert state_of(app, session).chat_id == chat_b

        post_reply = plugin.post(call_key, ok=True, output="0")

    assert post_reply["late"] is True
    events_a = app.store.read_events(chat_a, limit=10 ** 6)
    events_b = app.store.read_events(chat_b, limit=10 ** 6)
    assert [e for e in events_a
            if e["role"] == "tool_result" and e["metadata"]["call_key"] == call_key]
    assert not [e for e in events_b if e["role"] == "tool_result"]
