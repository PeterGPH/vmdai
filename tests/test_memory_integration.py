"""P03-T04: app memory wiring, lazy chats, resume conflicts (S1, §2b, §3)."""
from __future__ import annotations

import json
import re
import threading

from helpers.app_driver import (
    InstantBridge,
    ScriptedLoop,
    call,
    error_code,
    make_token_app,
    result,
    send,
    start,
    state_of,
    tool_use,
    wait_idle,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.locks import ChatLock

CHAT_ID_RE = re.compile(r"^chat_[0-9a-f]{12}$")


def _blocks(messages, kind):
    return [b for m in messages if isinstance(m.get("content"), list) for b in m["content"] if b.get("type") == kind]


def test_followup_sees_prior_tool_blocks(tmp_path):
    """S1: the second chat.send's prior carries turn 1's tool_use and tool_result."""
    app = make_token_app(tmp_path)
    app.tool_bridge = InstantBridge(lambda tool_input: "Info) Loaded 1hck")
    loop = ScriptedLoop([
        ("Loading.", [tool_use("tc_0", "mol new 1hck.pdb")]),
        ("Loaded 1hck.", []),
        ("Coloured it red.", []),
    ])
    app.claude_loop = loop
    session = start(app, tmp_path)
    first = result(send(app, session, "load 1hck"))
    wait_idle(app, session)
    second = result(send(app, session, "now color it red"))
    wait_idle(app, session)
    assert first["chat_id"] == second["chat_id"]
    seen = loop.calls[2]
    assert seen[0] == {"role": "user", "content": "load 1hck"}
    assert seen[-1] == {"role": "user", "content": "now color it red"}
    uses = _blocks(seen[:-1], "tool_use")
    results = _blocks(seen[:-1], "tool_result")
    assert len(uses) == 1 and re.match(r"^call_[0-9a-f]{12}$", uses[0]["id"])
    assert uses[0]["input"] == {"command": "mol new 1hck.pdb"}
    assert results[0]["tool_use_id"] == uses[0]["id"]
    assert "Info) Loaded 1hck" in json.dumps(results[0])


def test_messages_jsonl_written_incrementally(tmp_path):
    app = make_token_app(tmp_path)
    app.tool_bridge = InstantBridge()
    counts = []
    holder = []

    def before_call(number, messages):
        chat_dir = app.store.chat_dir(state_of(app, holder[0]).chat_id)
        counts.append(len(conversation.read_lines(chat_dir)))

    app.claude_loop = ScriptedLoop([("", [tool_use("tc_0", "molinfo list")]), ("Two molecules.", [])],
                                   before_call=before_call)
    session = start(app, tmp_path)
    holder.append(session)
    request_id = result(send(app, session, "what is loaded?"))["request_id"]
    wait_idle(app, session)
    lines = conversation.read_lines(app.store.chat_dir(state_of(app, session).chat_id))
    assert counts == [1, 3]          # prompt; then prompt + assistant turn + tool results
    assert [line["message"]["role"] for line in lines] == ["user", "assistant", "user", "assistant"]
    assert {line["request_id"] for line in lines} == {request_id}


def test_lazy_chat_creation(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path)
    assert session.result["chat_id"] is None
    assert app.store.list_chats() == []
    reply = result(send(app, session, "hello"))
    wait_idle(app, session)
    assert CHAT_ID_RE.match(reply["chat_id"]) and app.store.exists(reply["chat_id"])
    assert [row["chat_id"] for row in app.store.list_chats()] == [reply["chat_id"]]
    assert state_of(app, session).chat_lock.held
    assert ChatLock(app.store.chat_dir(reply["chat_id"])).acquire() is False


def test_resume_conflict_while_busy(tmp_path):
    app = make_token_app(tmp_path)
    gate = threading.Event()
    app.claude_loop = ScriptedLoop([("slow answer", [])], before_call=lambda number, messages: gate.wait(5))
    session = start(app, tmp_path)
    result(send(app, session, "take your time"))
    other = app.store.create_chat("other")
    try:
        assert error_code(call(app, "chat.resume", {"chat_id": other}, session)) == "REQUEST_CONFLICT"
        assert error_code(send(app, session, "again")) == "REQUEST_CONFLICT"
    finally:
        gate.set()
    wait_idle(app, session)
    assert result(call(app, "chat.resume", {"chat_id": other}, session))["chat_id"] == other


def test_resume_locked_chat_returns_chat_locked(tmp_path):
    """Review focus: two runtimes resume the same chat; the second gets CHAT_LOCKED."""
    first_app = make_token_app(tmp_path)
    first_app.claude_loop = ScriptedLoop([("hi", [])])
    first = start(first_app, tmp_path)
    chat_id = result(send(first_app, first, "hello"))["chat_id"]
    wait_idle(first_app, first)
    second_app = make_token_app(tmp_path)          # a second runtime on the same chats directory
    second = start(second_app, tmp_path)
    envelope = call(second_app, "chat.resume", {"chat_id": chat_id}, second)
    assert error_code(envelope) == "CHAT_LOCKED"
    assert envelope["error"]["data"] == {"chat_id": chat_id}
    assert result(call(first_app, "session.stop", {}, first))["ok"] is True
    resumed = result(call(second_app, "chat.resume", {"chat_id": chat_id}, second))
    assert resumed["chat_id"] == chat_id and isinstance(resumed["last_seq"], int)
    assert state_of(second_app, second).chat_lock.held
    polled = result(call(second_app, "chat.events.poll", {"after_seq": resumed["last_seq"], "limit": 50}, second))
    assert [event["text"] for event in polled["events"]] == ["chat_resumed"]


def test_new_chat_releases_lock(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path)
    chat_id = result(send(app, session, "hello"))["chat_id"]
    wait_idle(app, session)
    probe = ChatLock(app.store.chat_dir(chat_id))
    assert probe.acquire() is False
    result(call(app, "session.stop", {}, session))        # New Chat = session.stop + session.start
    assert probe.acquire() is True
    probe.release()
    assert start(app, tmp_path).result["chat_id"] is None


def test_tokenless_eager_creation_unchanged(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path, token="")
    chat_id = session.result["chat_id"]
    assert CHAT_ID_RE.match(chat_id) and app.store.exists(chat_id)
    reply = result(send(app, session, "hello", conversation_mode="local_first"))
    wait_idle(app, session)
    assert reply == {"request_id": reply["request_id"]}          # no chat_id field for tokenless sessions
    assert not conversation.messages_path(app.store.chat_dir(chat_id)).exists()
    assert state_of(app, session).chat_lock is None


def test_hybrid_resume_no_duplicate_prompt(tmp_path):
    app = make_token_app(tmp_path)
    loop = ScriptedLoop([("first answer", []), ("second answer", [])])
    app.claude_loop = loop
    session = start(app, tmp_path, token="")
    result(send(app, session, "first question", conversation_mode="local_first"))
    wait_idle(app, session)
    result(send(app, session, "second question", conversation_mode="hybrid_resume"))
    wait_idle(app, session)
    assert loop.calls[1] == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]


def test_token_resume_legacy_chat_imports_history(tmp_path):
    app = make_token_app(tmp_path)
    legacy = app.store.create_chat("old chat")
    app.store.append_events(legacy, [
        {"role": "user", "type": "message", "text": "load 1hck", "metadata": {}},
        {"role": "assistant", "type": "chunk", "text": "Lo", "metadata": {}},
        {"role": "assistant", "type": "message", "text": "Loaded.", "metadata": {}},
    ])
    loop = ScriptedLoop([("Red now.", [])])
    app.claude_loop = loop
    session = start(app, tmp_path)
    result(call(app, "chat.resume", {"chat_id": legacy}, session))
    result(send(app, session, "color it red"))
    wait_idle(app, session)
    assert loop.calls[0] == [
        {"role": "user", "content": "load 1hck"},
        {"role": "assistant", "content": "Loaded."},
        {"role": "user", "content": "color it red"},
    ]
    ids = [line["request_id"] for line in conversation.read_lines(app.store.chat_dir(legacy))]
    assert ids[:2] == ["legacy_1", "legacy_1"] and ids[2].startswith("req_")


def test_event_queue_last_seq():
    queue = EventQueue()
    assert queue.last_seq == 0
    queue.push("system", "lifecycle", "a")
    queue.push("system", "lifecycle", "b")
    assert queue.last_seq == 2


def test_run_budget_for_matches_loop(tmp_path):
    app = make_token_app(tmp_path)
    loop = ScriptedLoop([], provider_name="ollama", api_key="http://127.0.0.1:9")
    system = "system prompt"
    expected = conversation.compute_run_budget(8192, len(system), len(json.dumps(loop._tools_for_turn())))
    assert app._run_budget_for(loop, system) == expected
