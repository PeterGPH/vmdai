"""P07-T08: the five v2 scenario fixtures stay true to the runtime (§6 Scenario fixtures, C4)."""
from __future__ import annotations

import pytest

from helpers.make_event_fixtures import (CONVERSATION_FINALS, CONVERSATION_PROMPTS, LOOP_GUARD_WRAP_UP,
                                         REASONING_1, REASONING_2, SCENARIOS, TURN_RETRY_SEALED,
                                         TURN_RETRY_STREAMED, dumps, fixture_path, generate,
                                         read_fixture, update_goldens)
from vmd_ai_runtime.constants import EVENT_ROLES, EVENT_TYPES

ENVELOPE_KEYS = {"seq", "ts", "role", "type", "text", "metadata"}


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixtures_match_runtime(name, tmp_path):
    text = dumps(generate(name, tmp_path))
    path = fixture_path(name)
    if update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.is_file(), ("missing %s; create it with "
                            "CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_event_fixtures.py -q" % path)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_envelopes(name):
    events = read_fixture(name)
    assert events
    for event in events:
        assert set(event) == ENVELOPE_KEYS, event
        assert event["role"] in EVENT_ROLES and event["type"] in EVENT_TYPES, event
        assert event["role"] != "tool_start"
        meta = event["metadata"]
        if "request_id" in meta or str(meta.get("kind", "")).startswith("local."):
            assert meta["v"] == 2, event
    seqs = [e["seq"] for e in events if e["seq"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def _meta(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def _messages(events, role):
    return [e for e in events if e["role"] == role and e["type"] == "message"]


def test_contents_03_conversation():
    events = read_fixture("03_conversation")
    assert [e["text"] for e in _messages(events, "user")] == list(CONVERSATION_PROMPTS)
    assert [m["status"] for m in _meta(events, "request.finished")] == ["complete", "complete"]
    finished = _meta(events, "tool.finished")
    assert [m["ok"] for m in finished] == [True, False, True, True, True]
    assert finished[1]["statements"]["failed"]["index"] == 2
    assert finished[3]["image"]["src_width"] == 1280
    assert finished[3]["image"]["thumb_path"] == "@REPO@/docs/design/round1/assets/snap_1hck.png"
    finals = [e["text"] for e in _messages(events, "assistant") if e["metadata"]["final"]]
    assert finals == list(CONVERSATION_FINALS)


def test_contents_11_dead_runtime():
    events = read_fixture("11_dead_runtime")
    kinds = [e["metadata"].get("kind") for e in events]
    assert "request.finished" not in kinds and "tool.finished" not in kinds
    assert kinds.count("tool.started") == 1
    assert kinds[-4:] == ["local.connection", "local.send_failed", "local.connection", "local.request_ended"]
    assert [e["seq"] for e in events[-4:]] == [0, 0, 0, 0]
    assert events[-2]["metadata"]["request_lost"] is True
    started, = _meta(events, "request.started")
    assert events[-1]["metadata"]["request_id"] == started["request_id"]


def test_contents_reasoning_answer():
    events = read_fixture("reasoning_answer")
    sealed = [(e["metadata"]["turn"], e["text"]) for e in _messages(events, "reasoning")]
    assert sealed == [(1, REASONING_1), (2, REASONING_2)]
    for turn in (1, 2):
        chunks = [i for i, e in enumerate(events)
                  if e["role"] == "reasoning" and e["type"] == "chunk" and e["metadata"]["turn"] == turn]
        seal = next(i for i, e in enumerate(events)
                    if e["role"] == "reasoning" and e["type"] == "message" and e["metadata"]["turn"] == turn)
        assert seal == chunks[-1] + 1                     # sealed before anything else of that turn
    assert _meta(events, "request.started")[0]["think"] is True


def test_contents_turn_retry():
    events = read_fixture("turn_retry")
    retry, = _meta(events, "turn.retry")
    assert (retry["turn"], retry["reason"]) == (1, "stream dropped")
    streamed = [e["text"] for e in events
                if e["role"] == "assistant" and e["type"] == "chunk" and e["metadata"]["turn"] == 1]
    assert "".join(streamed) == TURN_RETRY_STREAMED
    assert [e["text"] for e in _messages(events, "assistant") if e["metadata"]["turn"] == 1] == [TURN_RETRY_SEALED]


def test_contents_loop_guard():
    events = read_fixture("loop_guard")
    phases = [m["phase"] for m in _meta(events, "status")]
    assert "loop_detected" in phases and "wrapping_up" in phases
    # C4: the first trigger nudges, the second stops the run.
    assert [m["stop"] for m in _meta(events, "status") if m["phase"] == "loop_detected"] == [False, True]
    finished, = _meta(events, "request.finished")
    assert (finished["status"], finished["wrapped_up"]) == ("stuck", True)
    assert [m["ok"] for m in _meta(events, "tool.finished")] == [False, False, False, False]
    finals = [e["text"] for e in _messages(events, "assistant") if e["metadata"].get("final")]
    assert finals == [LOOP_GUARD_WRAP_UP]
