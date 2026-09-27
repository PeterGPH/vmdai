"""P07-T04: the v2 display log in events.jsonl, sealed reasoning, message-only counts (§2c, §7)."""
from __future__ import annotations

import json

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds,
                               poll_all, product_result, run_cmd, start_v2)

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}


def _run(tmp_path, script, *, event_protocol=2, prompts=("load 1hck",)):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(script)
    app.tool_bridge = ProductBridge([product_result(output="0"), product_result(output="0")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    replies = []
    for prompt in prompts:
        replies.append(result(send(app, session, prompt)))
        wait_idle(app, session)
    return app, session, replies, poll_all(app, session)


def _stored(app, chat_id):
    return app.store.read_events(chat_id, limit=10 ** 9)


def test_no_chunks_persisted(tmp_path):
    script = [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD], reasoning="Load it first.", usage=USAGE,
                   status={"phase": "loading_model", "message": "Loading qwen3.8:27b"}),
        ScriptTurn(text="Partial", drop_after_text=True),
        ScriptTurn(text="Done.", usage=USAGE),
    ]
    app, _session, (reply,), _events = _run(tmp_path, script)
    stored = _stored(app, reply["chat_id"])
    assert kinds(stored) == [
        ("user", "message", None),
        ("system", "state", "request.started"),
        ("reasoning", "message", None),
        ("assistant", "message", None),
        ("system", "state", "tool.started"),
        ("system", "state", "tool.finished"),
        ("assistant", "message", None),
        ("system", "state", "request.finished"),
    ]
    assert all(e["metadata"]["v"] == 2 for e in stored)

    v1_app, _s, (v1_reply,), _e = _run(tmp_path / "v1", script, event_protocol=1)
    v1_stored = _stored(v1_app, v1_reply["chat_id"])       # v1 persistence stays as it is
    assert [e["type"] for e in v1_stored].count("chunk") == 3
    assert kinds(v1_stored)[-1] == ("assistant", "message", None)


def test_one_sealed_reasoning_per_turn(tmp_path):
    script = [
        ScriptTurn(reasoning="Check the file first.", tool_blocks=[LOAD]),
        ScriptTurn(reasoning="It loaded; answer.", text="Loaded 1hck."),
    ]
    app, _session, (reply,), events = _run(tmp_path, script)
    sealed = [e for e in events if e["role"] == "reasoning" and e["type"] == "message"]
    assert [(e["metadata"]["turn"], e["text"]) for e in sealed] == [
        (1, "Check the file first."), (2, "It loaded; answer.")]
    for event in sealed:
        assert set(event["metadata"]) == {"request_id", "turn", "duration_ms", "v"}
        assert isinstance(event["metadata"]["duration_ms"], int) and event["metadata"]["duration_ms"] >= 0
        at = events.index(event)
        assert events[at - 1]["role"] == "reasoning" and events[at - 1]["type"] == "chunk"
        assert events[at + 1]["role"] != "reasoning"
    stored = _stored(app, reply["chat_id"])
    assert [(e["metadata"]["turn"], e["text"]) for e in stored if e["role"] == "reasoning"] == [
        (1, "Check the file first."), (2, "It loaded; answer.")]


def test_turn_retry_discards_reasoning(tmp_path):
    script = [ScriptTurn(reasoning="First try", drop_after_text=True),
              ScriptTurn(reasoning="Second try", text="Done.")]
    app, _session, (reply,), events = _run(tmp_path, script)
    sealed = [(e["metadata"]["turn"], e["text"]) for e in events if e["role"] == "reasoning" and e["type"] == "message"]
    assert sealed == [(1, "Second try")]
    assert [e["text"] for e in _stored(app, reply["chat_id"]) if e["role"] == "reasoning"] == ["Second try"]


def test_turn_retry_after_sealed_reasoning(tmp_path):
    script = [
        ScriptTurn(reasoning="First try.", text="Partial", drop_after_text=True),
        ScriptTurn(reasoning="Second try.", text="Done."),
    ]
    app, _session, (reply,), events = _run(tmp_path, script)
    sealed = [(e["metadata"]["turn"], e["text"]) for e in events
              if e["role"] == "reasoning" and e["type"] == "message"]
    assert sealed == [(1, "First try."), (1, "Second try.")]
    retry_at = next(i for i, e in enumerate(events)
                    if (e.get("metadata") or {}).get("kind") == "turn.retry")
    first_reasoning_at = next(i for i, e in enumerate(events)
                              if e["role"] == "reasoning" and e["type"] == "message")
    assert first_reasoning_at < retry_at

    stored = _stored(app, reply["chat_id"])
    assert [(e["metadata"]["turn"], e["text"]) for e in stored if e["role"] == "reasoning"] == [
        (1, "Second try.")]
    assert kinds(stored) == [
        ("user", "message", None),
        ("system", "state", "request.started"),
        ("reasoning", "message", None),
        ("assistant", "message", None),
        ("system", "state", "request.finished"),
    ]


def test_message_count_user_assistant_only(tmp_path):
    script = [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD]),
        ScriptTurn(text="Done."),
        ScriptTurn(tool_blocks=[run_cmd("tc_2", "mol delrep 0 top")]),   # a tool-only turn: empty text
        ScriptTurn(text="Ok."),
    ]
    app, _session, (first, second), _events = _run(tmp_path, script, prompts=("load 1hck", "clear the reps"))
    chat_id = first["chat_id"]
    # user x2, "Loading.", "Done.", "Ok."; the empty tool-only turn and every state event don't count
    assert app.store.get_manifest(chat_id)["message_count"] == 5
    rows = [json.loads(line) for line in app.store.index_path.read_text(encoding="utf-8").splitlines()]
    assert [r for r in rows if r["chat_id"] == chat_id][-1]["message_count"] == 5
    # one index row per chat.send (the user message) plus one per request.finished, not one per event
    assert len([r for r in rows if r["chat_id"] == chat_id]) == 1 + 2 * 2


def test_recount_legacy_manifest(tmp_path):
    app = make_token_app(tmp_path)
    store = app.store
    chat_id = store.create_chat("legacy")
    legacy = [
        {"role": "user", "type": "message", "text": "load", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "chunk", "text": "Lo", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "chunk", "text": "aded.", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "message", "text": "Loaded.", "metadata": {"request_id": "req_a"}},
        {"role": "tool_result", "type": "message", "text": "0", "metadata": {"tool_call_id": "tc_1", "ok": True}},
        {"role": "system", "type": "lifecycle", "text": "cancelled", "metadata": {"request_id": "req_b"}},
        {"role": "user", "type": "message", "text": "again", "metadata": {"request_id": "req_b"}},
        {"role": "assistant", "type": "message", "text": "", "metadata": {"request_id": "req_b"}},
    ]
    store.append_display_events(chat_id, legacy)
    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 9                         # a legacy manifest counted every event
    store._write_manifest(chat_id, manifest)
    assert store.recount_messages(chat_id) == 3
    assert store.get_manifest(chat_id)["message_count"] == 3

    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 42
    store._write_manifest(chat_id, manifest)
    store.append_events(chat_id, [{"role": "user", "type": "message", "text": "third", "metadata": {}}])
    assert store.get_manifest(chat_id)["message_count"] == 4   # §7: recomputed when next touched

    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 42
    store._write_manifest(chat_id, manifest)
    session = start_v2(app, tmp_path)
    resumed = result(call(app, "chat.resume", {"chat_id": chat_id}, session))
    assert resumed["message_count"] == 4
    assert store.get_manifest(chat_id)["message_count"] == 4


def test_late_tool_finished_persisted(tmp_path, monkeypatch):
    app = make_token_app(tmp_path)                        # the real VmdToolBridge
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))
    app.claude_loop = MetaScriptedLoop([ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")])])
    session = start_v2(app, tmp_path)
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        reply = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        plugin.post(key, ok=True, output="3 atoms")
    stored = _stored(app, reply["chat_id"])
    finished = [e["metadata"] for e in stored if e["metadata"].get("kind") == "tool.finished"]
    assert [(m["call_key"], m["late"], m["executed"]) for m in finished] == [
        (key, False, "unknown"), (key, True, "yes")]
    assert kinds(stored)[-1] == ("system", "state", "tool.finished")   # after request.finished
    assert not [e for e in stored if e["role"] == "tool_start"]
