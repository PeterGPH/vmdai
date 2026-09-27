"""P07-T06: chat.events.poll long-poll with wait_ms (§2d M2)."""
from __future__ import annotations

import threading
import time

import pytest

from helpers.app_driver import call, make_token_app, result, state_of
from helpers.events_v2 import start_v2
from vmd_ai_runtime.constants import CAPABILITIES
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.protocol import MAX_WAIT_MS, validate_method_params


def _session(tmp_path):
    app = make_token_app(tmp_path)
    return app, start_v2(app, tmp_path)


def _poll(app, session, after_seq, wait_ms):
    t0 = time.monotonic()
    reply = result(call(app, "chat.events.poll",
                        {"after_seq": after_seq, "limit": 50, "wait_ms": wait_ms}, session))
    return reply, time.monotonic() - t0


def test_immediate_when_pending(tmp_path):
    app, session = _session(tmp_path)                 # session.start queued two events
    reply, elapsed = _poll(app, session, 0, 2000)
    assert reply["events"][0]["text"] == "session_started"
    assert elapsed < 0.2


def test_wakes_on_push(tmp_path):
    app, session = _session(tmp_path)
    queue = state_of(app, session).queue
    last = queue.last_seq
    timer = threading.Timer(0.15, lambda: queue.push("system", "lifecycle", "ping"))
    timer.start()
    try:
        reply, elapsed = _poll(app, session, last, 2000)
    finally:
        timer.cancel()
    assert [e["text"] for e in reply["events"]] == ["ping"]
    assert 0.12 <= elapsed < 1.5


def test_times_out_empty(tmp_path):
    app, session = _session(tmp_path)
    last = state_of(app, session).queue.last_seq
    reply, elapsed = _poll(app, session, last, 150)
    assert reply == {"events": [], "last_seq": last, "has_more": False}
    assert 0.13 <= elapsed < 1.0


def test_wait_ms_clamped_2000():
    assert MAX_WAIT_MS == 2000
    params = validate_method_params("chat.events.poll", {"session_id": "s", "after_seq": 0, "wait_ms": 60000})
    assert params["wait_ms"] == 2000
    assert "wait_ms" not in validate_method_params("chat.events.poll", {"session_id": "s"})
    with pytest.raises(RpcError) as info:
        validate_method_params("chat.events.poll", {"session_id": "s", "wait_ms": -1})
    assert info.value.code == "INVALID_PARAMS"


def test_after_seq_ahead_returns_promptly(tmp_path):
    """Review focus 3: a cursor beyond last_seq never sleeps; the reply carries the real last_seq."""
    app, session = _session(tmp_path)
    last = state_of(app, session).queue.last_seq
    reply, elapsed = _poll(app, session, last + 500, 2000)
    assert reply == {"events": [], "last_seq": last, "has_more": False}
    assert elapsed < 0.2
    plain = result(call(app, "chat.events.poll", {"after_seq": last + 500, "limit": 50}, session))
    assert plain["last_seq"] == last + 500            # the M1 short-poll keeps today's echo


def test_capability_advertised(tmp_path):
    app = make_token_app(tmp_path)
    token = start_v2(app, tmp_path, event_protocol=1)
    assert token.result["capabilities"] == dict(CAPABILITIES, long_poll=True)
    tokenless = start_v2(app, tmp_path, token="")
    assert tokenless.result["capabilities"] == CAPABILITIES
    assert "long_poll" not in CAPABILITIES            # the shared constant is not mutated


def test_queue_wait_unit():
    queue = EventQueue()
    t0 = time.monotonic()
    assert queue.wait(0, 0.2) is False
    assert 0.18 <= time.monotonic() - t0 < 1.0
    queue.push("system", "lifecycle", "a")
    t0 = time.monotonic()
    assert queue.wait(0, 2.0) is True and time.monotonic() - t0 < 0.1
    assert queue.wait(7, 2.0) is True                 # ahead of the queue: returns at once
    queue.drop_pending()
    assert queue.wait(1, 0.05) is False               # seq kept, nothing newer queued
