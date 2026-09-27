"""P07-T02: request.started/request.finished on every worker path, and v2 error events (§2c, §2f)."""
from __future__ import annotations

import os

import pytest

from helpers.app_driver import error_code, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MODEL, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds, of_kind,
                               poll_all, product_result, run_cmd, start_v2)
from vmd_ai_runtime.claude_loop import (ClaudeLoopError, ModelNotFoundError, ProviderAuthError,
                                        ProviderBillingError, ProviderUnreachableError)
from vmd_ai_runtime.constants import ACTION_FOR_CODE
from vmd_ai_runtime.settings_store import SettingsStore

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}
NO_USAGE = {"input_tokens_evaluated": None, "output_tokens": None}
FINISHED_KEYS = {"kind", "request_id", "status", "wrapped_up", "turns", "tool_calls", "final_text_empty",
                 "duration_ms", "usage", "error", "run_dir", "v"}


def _app(tmp_path, script, results=None):
    app = make_token_app(tmp_path)
    loop = MetaScriptedLoop(script)
    app.claude_loop = loop
    app.tool_bridge = ProductBridge(results if results is not None else [product_result(output="0")])
    return app, loop


def _send(app, tmp_path, text="load 1hck"):
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, text))
    wait_idle(app, session)
    return reply, poll_all(app, session)


def _at(events, kind):
    return [i for i, e in enumerate(events) if (e.get("metadata") or {}).get("kind") == kind]


def test_complete(tmp_path):
    app, _loop = _app(tmp_path, [ScriptTurn(text="Loading.", tool_blocks=[LOAD], usage=USAGE),
                                 ScriptTurn(text="Done.", usage=USAGE)])
    reply, events = _send(app, tmp_path)
    rid = reply["request_id"]
    started, = of_kind(events, "request.started")
    assert started == {"kind": "request.started", "request_id": rid, "chat_id": reply["chat_id"],
                       "provider": "ollama", "model": MODEL, "max_turns": 28, "vision": True,
                       "think": True, "v": 2}
    finished, = of_kind(events, "request.finished")
    assert set(finished) == FINISHED_KEYS
    assert (finished["request_id"], finished["status"], finished["wrapped_up"], finished["turns"],
            finished["tool_calls"], finished["final_text_empty"], finished["error"]) == (
        rid, "complete", False, 2, 1, False, None)
    assert finished["usage"] == {"input_tokens_evaluated": 240, "output_tokens": 18}
    assert isinstance(finished["duration_ms"], int) and finished["duration_ms"] >= 0
    runs = os.path.realpath(str(tmp_path / "work" / ".vmdai_runs"))
    assert finished["run_dir"].startswith(runs + os.sep)
    user_at = next(i for i, e in enumerate(events) if e["role"] == "user")
    assert _at(events, "request.started") == [user_at + 1]
    assert _at(events, "request.finished") == [len(events) - 1]


def test_cancelled(tmp_path):
    def stop_then_answer(kwargs):
        kwargs["cancel_event"].set()          # the user pressed Stop while the tool ran
        return product_result(output="0")

    app, _loop = _app(tmp_path, [ScriptTurn(tool_blocks=[LOAD]), ScriptTurn(text="never sent")],
                      [stop_then_answer])
    _reply, events = _send(app, tmp_path)
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["turns"], finished["tool_calls"], finished["final_text_empty"],
            finished["error"]) == ("cancelled", 1, 1, True, None)
    assert not [e for e in events if e["type"] == "lifecycle" and e["text"] == "cancelled"]
    assert _at(events, "request.finished") == [len(events) - 1]


ERRORS = [
    (lambda: ProviderUnreachableError("Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?",
                                      hint="Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"),
     "unreachable", None, "test_connection"),
    (lambda: ProviderAuthError("HTTP 401 from the provider: invalid x-api-key", http_status=401),
     "auth", 401, "open_settings"),
    (lambda: ProviderBillingError("Your credit balance is too low to access the Anthropic API.",
                                  http_status=400),
     "billing", 400, "switch_profile"),
    (lambda: ModelNotFoundError("Model not found: qwen3.8:27b", hint="ollama pull qwen3.8:27b", http_status=404),
     "model_not_found", 404, "choose_model"),
    (lambda: ClaudeLoopError("stream failed: HTTP 500", http_status=500), "other", 500, "open_log"),
]


@pytest.mark.parametrize("make_exc,code,http_status,action", ERRORS, ids=[e[1] for e in ERRORS])
def test_error_codes_and_actions(tmp_path, make_exc, code, http_status, action):
    exc = make_exc()
    app, _loop = _app(tmp_path, [ScriptTurn(raise_error=exc)])
    reply, events = _send(app, tmp_path)
    errors = [e for e in events if e["role"] == "error"]
    assert len(errors) == 1
    assert (errors[0]["type"], errors[0]["text"]) == ("message", str(exc))
    assert errors[0]["metadata"] == {"request_id": reply["request_id"], "code": code,
                                     "http_status": http_status, "hint": exc.hint,
                                     "action": action, "v": 2}
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["error"], finished["turns"], finished["tool_calls"]) == (
        "error", str(exc), 1, 0)
    assert events.index(errors[0]) < _at(events, "request.finished")[0]
    assert not [e for e in events if e["text"].startswith("Agent error:")]


def test_action_for_code_catalogue():
    assert ACTION_FOR_CODE == {"unreachable": "test_connection", "auth": "open_settings",
                               "billing": "switch_profile", "model_not_found": "choose_model",
                               "other": "open_log"}


def test_unexpected_exception(tmp_path, monkeypatch):
    app, loop = _app(tmp_path, [ScriptTurn(text="unused")])

    def boom(**kwargs):
        raise ValueError("loop exploded")

    monkeypatch.setattr(loop, "run", boom)
    reply, events = _send(app, tmp_path)
    error, = [e for e in events if e["role"] == "error"]
    assert error["text"] == "Unexpected error: loop exploded"
    assert error["metadata"] == {"request_id": reply["request_id"], "code": "other", "http_status": None,
                                 "hint": "", "action": "open_log", "v": 2}
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["error"]) == ("error", "Unexpected error: loop exploded")


def test_mock_path(tmp_path):
    app = make_token_app(tmp_path)                 # mock provider, no loop, no settings store
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, "hello"))
    wait_idle(app, session)
    events = poll_all(app, session)
    rid = reply["request_id"]
    started, = of_kind(events, "request.started")
    assert started == {"kind": "request.started", "request_id": rid, "chat_id": reply["chat_id"],
                       "provider": "mock", "model": "anthropic/claude-sonnet-4.6", "max_turns": 1,
                       "vision": False, "think": None, "v": 2}
    assert of_kind(events, "turn.started") == [{"kind": "turn.started", "request_id": rid, "turn": 1, "v": 2}]
    chunks = [e for e in events if e["type"] == "chunk"]
    assert chunks and all(e["metadata"] == {"request_id": rid, "turn": 1, "v": 2} for e in chunks)
    sealed = [(e["text"], e["metadata"]) for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert sealed == [("Mock assistant response to: hello",
                       {"request_id": rid, "turn": 1, "final": True, "v": 2})]
    finished, = of_kind(events, "request.finished")
    assert set(finished) == FINISHED_KEYS
    assert {k: finished[k] for k in ("status", "wrapped_up", "turns", "tool_calls", "final_text_empty",
                                     "usage", "error", "run_dir")} == {
        "status": "complete", "wrapped_up": False, "turns": 1, "tool_calls": 0,
        "final_text_empty": False, "usage": NO_USAGE, "error": None, "run_dir": None}
    assert _at(events, "request.finished") == [len(events) - 1]


def test_prerun_failure(tmp_path, monkeypatch):
    app, loop = _app(tmp_path, [ScriptTurn(text="never")])

    def boom(state, meta=None):
        raise RuntimeError("recorder exploded")

    monkeypatch.setattr(app, "_build_recorder_for_session", boom)
    _reply, events = _send(app, tmp_path)
    assert loop.calls == []                        # loop.run was never reached
    assert [k[2] for k in kinds(events) if k[2] in ("request.started", "request.finished")] == [
        "request.started", "request.finished"]
    error, = [e for e in events if e["role"] == "error"]
    assert (error["text"], error["metadata"]["code"]) == ("Unexpected error: recorder exploded", "other")
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["turns"], finished["tool_calls"], finished["final_text_empty"],
            finished["usage"], finished["error"], finished["run_dir"]) == (
        "error", 0, 0, True, NO_USAGE, "Unexpected error: recorder exploded", None)


def test_no_model_has_no_finished(tmp_path):
    store = SettingsStore()
    store.patch({"max_turns": 28})                 # settings.json exists and holds no profile
    app = make_token_app(tmp_path, settings_store=store)
    session = start_v2(app, tmp_path)
    assert error_code(send(app, session, "hello")) == "NO_MODEL"
    events = poll_all(app, session)
    assert not [e for e in events if (e["metadata"] or {}).get("kind") in ("request.started", "request.finished")]
    assert not [e for e in events if e["role"] == "user"]


def test_stuck_wrap_up_error_is_message_not_card(tmp_path):
    """C4: a failed wrap-up leaves status stuck, wrapped_up false and its message in error; no error card."""
    error = 'mol modcolor: invalid coloring method "ResidueType"'
    fail = product_result(ok=False, error=error)
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(
        [ScriptTurn(tool_blocks=[run_cmd("tc_%d" % n, "mol modcolor 0 top ResidueType")]) for n in (1, 2, 3, 4)],
        wrap_up_error=ClaudeLoopError("HTTP 400: bad request"))
    app.tool_bridge = ProductBridge([fail, fail, fail, fail])
    _reply, events = _send(app, tmp_path)
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["wrapped_up"], finished["error"]) == (
        "stuck", False, "HTTP 400: bad request")
    assert not [e for e in events if e["role"] == "error"]


def test_on_event_crash_still_finishes(tmp_path, monkeypatch):
    """Review focus 5: a broken mapping must not skip request.finished, and the run goes on."""
    app, _loop = _app(tmp_path, [ScriptTurn(text="Loading.", tool_blocks=[LOAD]), ScriptTurn(text="Done.")])
    bridge = app.tool_bridge
    real_push = app._push_v2

    def flaky(state, role, event_type, text, metadata):
        if metadata.get("kind") == "tool.started":
            raise RuntimeError("mapping broke")
        return real_push(state, role, event_type, text, metadata)

    monkeypatch.setattr(app, "_push_v2", flaky)
    _reply, events = _send(app, tmp_path)
    assert of_kind(events, "tool.started") == []
    assert len(bridge.calls) == 1                  # the tool still ran
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["tool_calls"], finished["final_text_empty"]) == ("complete", 1, False)
