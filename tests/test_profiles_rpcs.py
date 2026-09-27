"""P07-T07: profiles.list / save / delete / activate (§3 RPC table, C7)."""
from __future__ import annotations

import threading

import pytest

from helpers.app_driver import call, error_code, make_token_app, result, send, wait_idle
from helpers.events_v2 import MetaScriptedLoop, ScriptTurn, of_kind, poll_all, start_v2
from vmd_ai_runtime import provider_catalog
from vmd_ai_runtime.settings_store import SettingsStore

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b",
        "options": {"num_ctx": 16384}}
LLAMA = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "llama3.1:8b", "options": {}}
CLAUDE = {"provider": "anthropic-direct", "model": "claude-sonnet-4-6", "options": {}}
OLLAMA_CAPS = {"tools": True, "vision": True, "thinking": False}
CLAUDE_CAPS = {"tools": True, "vision": True, "thinking": False}


@pytest.fixture
def show(monkeypatch):
    """provider_catalog.ollama_show without a server: tools and vision, no thinking."""
    calls = []

    def fake_show(base_url, model, timeout=3.0):
        calls.append((base_url, model))
        return {"capabilities": ["completion", "tools", "vision"]}

    monkeypatch.setattr(provider_catalog, "ollama_show", fake_show)
    return calls


def _app(tmp_path, **profiles):
    """An app that owns ~/.vmdai/settings.json; the first profile given is active."""
    store = SettingsStore()
    for index, (name, profile) in enumerate(profiles.items()):
        store.save_profile(name, profile, activate=(index == 0))
    return make_token_app(tmp_path, settings_store=store), store


def test_list(tmp_path, show):
    app, _store = _app(tmp_path, qwen=QWEN, claude=CLAUDE)
    session = start_v2(app, tmp_path, event_protocol=1)       # any token session
    assert result(call(app, "profiles.list", {}, session)) == {
        "active": "qwen", "profiles": {"qwen": QWEN, "claude": CLAUDE}, "settings_source": "file"}


def test_save_activate_capabilities(tmp_path, show):
    app, store = _app(tmp_path, qwen=QWEN)
    session = start_v2(app, tmp_path)
    saved = result(call(app, "profiles.save", {"name": "llama", "profile": LLAMA, "activate": True}, session))
    assert saved == {"ok": True, "capabilities": OLLAMA_CAPS}
    assert store.active_profile() == ("llama", LLAMA)
    assert show == [("http://127.0.0.1:9", "llama3.1:8b")]
    assert result(call(app, "profiles.save", {"name": "claude", "profile": CLAUDE}, session)) == {
        "ok": True, "capabilities": CLAUDE_CAPS}
    assert store.active_profile()[0] == "llama"                # save without activate keeps the active one
    assert result(call(app, "profiles.activate", {"name": "claude"}, session)) == {
        "ok": True, "capabilities": CLAUDE_CAPS}
    assert store.active_profile()[0] == "claude"
    for bad in ({"name": "../x", "profile": LLAMA},
                {"name": "x", "profile": "ollama"},
                {"name": "x", "profile": {"provider": "nope", "model": "m"}},
                {"name": "x", "profile": LLAMA, "activate": "yes"},
                {"profile": LLAMA}):
        assert error_code(call(app, "profiles.save", bad, session)) == "INVALID_PARAMS", bad


def test_delete_active_in_use(tmp_path, show):
    app, store = _app(tmp_path, qwen=QWEN, claude=CLAUDE)
    session = start_v2(app, tmp_path)
    assert error_code(call(app, "profiles.delete", {"name": "qwen"}, session)) == "IN_USE"
    assert result(call(app, "profiles.delete", {"name": "claude"}, session)) == {"ok": True}
    assert set(store.list_profiles()) == {"qwen"}
    assert error_code(call(app, "profiles.delete", {"name": "claude"}, session)) == "NOT_FOUND"
    assert error_code(call(app, "profiles.activate", {"name": "claude"}, session)) == "NOT_FOUND"


def test_activate_applies_next_request(tmp_path, show, monkeypatch):
    app, _store = _app(tmp_path, qwen=QWEN, llama=LLAMA)
    gate = threading.Event()

    def factory(profile):
        # One scripted loop per request, built from the profile the request starts with.
        return MetaScriptedLoop([ScriptTurn(text="answered by " + profile["model"],
                                            before=lambda: gate.wait(5))], model=profile["model"])

    monkeypatch.setattr(app, "_profile_loop_factory", factory)
    session = start_v2(app, tmp_path)
    first = result(send(app, session, "one"))
    assert result(call(app, "profiles.activate", {"name": "llama"}, session))["ok"] is True
    gate.set()                                               # the running request keeps its loop
    wait_idle(app, session)
    second = result(send(app, session, "two"))
    wait_idle(app, session)
    events = poll_all(app, session)
    assert [(m["request_id"], m["model"]) for m in of_kind(events, "request.started")] == [
        (first["request_id"], "qwen3.8:27b"), (second["request_id"], "llama3.1:8b")]
    finals = [e["text"] for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert finals == ["answered by qwen3.8:27b", "answered by llama3.1:8b"]


def test_all_require_auth(tmp_path, show):
    app, _store = _app(tmp_path, qwen=QWEN)
    tokenless = start_v2(app, tmp_path, token="")
    for method, params in (("profiles.list", {}), ("profiles.save", {"name": "x", "profile": LLAMA}),
                           ("profiles.delete", {"name": "qwen"}), ("profiles.activate", {"name": "qwen"})):
        assert error_code(call(app, method, params, tokenless)) == "AUTH_REQUIRED", method
    bare = make_token_app(tmp_path / "bare")                  # a runtime without a settings store
    session = start_v2(bare, tmp_path / "bare")
    envelope = call(bare, "profiles.list", {}, session)
    assert error_code(envelope) == "INVALID_PARAMS"
    assert envelope["error"]["data"] == {"reason": "no_settings_store"}


def test_save_keeps_num_ctx_on_model_change(tmp_path, show):
    """C7: a model change keeps the stored num_ctx unless the same call sets one."""
    app, store = _app(tmp_path, qwen=QWEN)
    session = start_v2(app, tmp_path)
    newer = dict(QWEN, model="qwen3.8:32b", options={})
    result(call(app, "profiles.save", {"name": "qwen", "profile": newer}, session))
    assert store.get_profile("qwen")["options"] == {"num_ctx": 16384}
    result(call(app, "profiles.save", {"name": "qwen", "profile": dict(newer, options={"num_ctx": 8192})}, session))
    assert store.get_profile("qwen")["options"] == {"num_ctx": 8192}
    vllm = {"provider": "openai-compatible", "base_url": "http://localhost:8000/v1", "model": "Qwen/Qwen3-8B",
            "options": {}}
    result(call(app, "profiles.save", {"name": "qwen", "profile": vllm}, session))
    assert store.get_profile("qwen")["options"] == {}          # not carried to another provider
