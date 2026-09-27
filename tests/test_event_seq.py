"""P07-T05: monotonic seq for token sessions, trimming, and history replay (§2c, §7)."""
from __future__ import annotations

import pytest

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MODEL, MetaScriptedLoop, ProductBridge, ScriptTurn, poll_all,
                               product_result, run_cmd, start_v2)
from vmd_ai_runtime.app import is_display_event
from vmd_ai_runtime.events import EventQueue, display_log

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")


def _app(tmp_path, script):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(script)
    app.tool_bridge = ProductBridge([product_result(output="0")])
    return app


@pytest.mark.parametrize("event_protocol", [1, 2])
def test_token_resume_keeps_seq(tmp_path, event_protocol):
    app = _app(tmp_path, [ScriptTurn(text="Hello.")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    result(send(app, session, "hi"))
    wait_idle(app, session)
    before = app.sessions.get(session.session_id).queue.last_seq
    assert before > 3
    other = app.store.create_chat("other")
    resumed = result(call(app, "chat.resume", {"chat_id": other}, session))
    assert resumed["last_seq"] == before
    assert [(e["seq"], e["text"]) for e in poll_all(app, session)] == [(before + 1, "chat_resumed")]


def test_tokenless_resume_resets(tmp_path):
    app = _app(tmp_path, [ScriptTurn(text="Hello.")])
    session = start_v2(app, tmp_path, token="")
    result(send(app, session, "hi", conversation_mode="local_first", model=MODEL))   # no model override
    wait_idle(app, session)
    assert app.sessions.get(session.session_id).queue.last_seq > 3
    other = app.store.create_chat("other")
    resumed = result(call(app, "chat.resume", {"chat_id": other}, session))
    assert set(resumed) == {"ok", "chat_id", "title", "message_count"}     # today's fields
    assert [(e["seq"], e["text"]) for e in poll_all(app, session)] == [(1, "chat_resumed")]


def test_trim_beyond_1000():
    queue = EventQueue()
    assert queue.trim_after == 1000
    for i in range(1500):
        queue.push("assistant", "chunk", str(i))
    queue.poll(after_seq=1400, limit=10)                  # the client has now seen 1..1400
    kept = queue.poll(after_seq=0, limit=500)["events"]
    assert kept[0]["seq"] == 401                          # the newest 1000 delivered events stay
    tail = queue.poll(after_seq=1400, limit=500)["events"]
    assert [e["seq"] for e in tail] == list(range(1401, 1501))   # undelivered: never trimmed
    small = EventQueue(trim_after=2)
    for i in range(5):
        small.push("system", "lifecycle", str(i))
    assert [e["seq"] for e in small.poll(after_seq=4, limit=10)["events"]] == [5]
    assert [e["seq"] for e in small.poll(after_seq=0, limit=10)["events"]] == [3, 4, 5]


def test_drop_pending_keeps_seq():
    queue = EventQueue()
    for text in ("a", "b", "c"):
        queue.push("system", "lifecycle", text)
    assert queue.drop_pending() == 3
    assert queue.last_seq == 3 and queue.poll(0, 10)["events"] == []
    assert queue.push("system", "lifecycle", "d")["seq"] == 4
    queue.clear()                                         # tokenless resume: today's reset
    assert queue.last_seq == 0 and queue.push("system", "lifecycle", "e")["seq"] == 1


def test_history_get_full_display_log(tmp_path):
    app = _app(tmp_path, [ScriptTurn(reasoning="Load first.", text="Loading.", tool_blocks=[LOAD]),
                          ScriptTurn(text="Done.")])
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, "load 1hck"))
    wait_idle(app, session)
    live = poll_all(app, session)
    history = result(call(app, "chat.history.get", {"chat_id": reply["chat_id"]}, session))["events"]
    # A resumed chat replays exactly the display events the live session saw (§2c).
    assert history == [e for e in live if is_display_event(e) and "request_id" in e["metadata"]]

    chat_id = app.store.create_chat("long")
    rows = [{"seq": i, "ts": 0.0, "role": "user" if i % 2 else "assistant", "type": "message",
             "text": "m%d" % i, "metadata": {"request_id": "req_%012d" % (i // 2), "v": 2}}
            for i in range(1, 251)]
    app.store.append_display_events(chat_id, rows)
    full = result(call(app, "chat.history.get", {"chat_id": chat_id}, session))["events"]
    assert [e["seq"] for e in full] == list(range(1, 251))          # no tail cut for a token session
    tokenless = start_v2(app, tmp_path, token="")
    tail = result(call(app, "chat.history.get", {"chat_id": chat_id}, tokenless))["events"]
    assert [e["seq"] for e in tail] == list(range(51, 251))         # today's limit of 200


def test_mixed_log_replay(tmp_path):
    """Review focus 4: an M1 (v1) request and an M2 (v2) request in one chat replay without duplicates."""
    app = _app(tmp_path, [ScriptTurn(text="Loaded 1hck."), ScriptTurn(text="Colored red.")])
    v1 = start_v2(app, tmp_path, event_protocol=1)
    chat_id = result(send(app, v1, "load 1hck"))["chat_id"]
    wait_idle(app, v1)
    result(call(app, "session.stop", {}, v1))             # the M1 panel closes; the chat lock is freed
    v2 = start_v2(app, tmp_path)
    result(call(app, "chat.resume", {"chat_id": chat_id}, v2))
    result(send(app, v2, "color it red"))
    wait_idle(app, v2)
    # An older v1 request that failed kept its chunks; the legacy direct path stored a tool_start.
    app.store.append_events(chat_id, [
        {"seq": 90, "ts": 0.0, "role": "user", "type": "message", "text": "and now?",
         "metadata": {"request_id": "req_e"}},
        {"seq": 91, "ts": 0.0, "role": "assistant", "type": "chunk", "text": "Half an ans",
         "metadata": {"request_id": "req_e"}},
        {"seq": 92, "ts": 0.0, "role": "error", "type": "message", "text": "Agent error: boom",
         "metadata": {"request_id": "req_e"}},
        {"seq": 93, "ts": 0.0, "role": "tool_start", "type": "message", "text": "[VMD] mol list",
         "metadata": {"tool_call_id": "direct_1"}},
    ])
    stored = app.store.read_events(chat_id, limit=10 ** 9)
    assert [e["text"] for e in stored if e["type"] == "chunk"] == ["Loaded ", "1hck.", "Half an ans"]
    replay = result(call(app, "chat.history.get", {"chat_id": chat_id}, v2))["events"]
    assert [e["text"] for e in replay if e["type"] == "chunk"] == ["Half an ans"]   # no message for req_e
    assert not [e for e in replay if e["role"] == "tool_start"]
    assert [(e["role"], e["text"]) for e in replay if e["type"] == "message"] == [
        ("user", "load 1hck"), ("assistant", "Loaded 1hck."),
        ("user", "color it red"), ("assistant", "Colored red."),
        ("user", "and now?"), ("error", "Agent error: boom"),
    ]
    assert display_log(stored) == replay
