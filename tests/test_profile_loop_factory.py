"""P03-T08: profile-driven loop_factory, NO_MODEL, openai-compatible (§2f, §7)."""
from __future__ import annotations

import inspect
import logging
import subprocess
import sys
from pathlib import Path

from helpers.app_driver import (
    ScriptedLoop,
    call,
    error_code,
    make_token_app,
    result,
    send,
    start,
    state_of,
    wait_idle,
)
from helpers.fake_ollama import FakeOllama, FakeOllamaServer
from vmd_ai_runtime import keys, provider, settings_store
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, build_claude_loop
from vmd_ai_runtime.constants import CAPABILITIES
from vmd_ai_runtime.settings_store import SettingsStore

ROOT = Path(__file__).resolve().parents[1]
QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b", "options": {}}


def _store(profile=None, **top):
    store = SettingsStore()                 # ~/.vmdai under the hermetic HOME
    if profile is not None:
        store.save_profile("qwen", profile, activate=True)
    if top:
        store.patch(top)
    return store


def test_token_send_without_profile_no_model(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store())
    session = start(app, tmp_path)
    assert session.result["profile"] is None
    assert session.result["agent_loop"] is False
    envelope = send(app, session, "hello")
    assert error_code(envelope) == "NO_MODEL"
    assert envelope["error"]["data"]["action"] == "open_settings"
    assert app.store.list_chats() == []
    assert state_of(app, session).active_request is None


def test_ollama_profile_builds_product_options(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store(QWEN, max_turns=12), enable_wiki=True,
                         wiki_root=str(tmp_path / "wiki"), wiki_raw_root=str(tmp_path / "raw"))
    session = start(app, tmp_path)
    assert session.result["profile"] == {"name": "qwen", "provider": "ollama", "model": "qwen3.8:27b",
                                         "base_url": "http://127.0.0.1:9"}
    loop = app._new_loop_for(state_of(app, session))
    assert isinstance(loop, ClaudeToolLoop) and loop.provider_name == "ollama"
    assert loop.api_key == "http://127.0.0.1:9" and loop.model == "qwen3.8:27b"
    assert loop.options.num_ctx == 32768 and loop.options.max_turns == 12
    assert loop.options.rescue == "json" and loop.options.compact_in_run is True
    assert loop.wiki_store is None                          # wiki_enabled defaults to false
    app.settings_store.patch({"wiki_enabled": True})
    fresh = app._new_loop_for(state_of(app, session))
    assert fresh.wiki_store is app.wiki_store and fresh is not loop


def test_openai_compatible_profile_without_base_url_uses_local_default(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store({"provider": "openai-compatible", "model": "x", "options": {}}))
    session = start(app, tmp_path)
    loop = app._new_loop_for(state_of(app, session))
    assert loop.provider_name == "openai-compatible"
    assert loop.options.base_url == settings_store.DEFAULT_BASE_URLS["openai-compatible"] == "http://localhost:8000/v1"


def test_profile_beats_env_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("VMD_AI_PROVIDER", "anthropic-direct")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    app = make_token_app(tmp_path, settings_store=_store(QWEN), provider_mode=None)
    token_session = start(app, tmp_path)
    tokenless = start(app, tmp_path, token="")
    assert app._new_loop_for(state_of(app, token_session)).provider_name == "ollama"
    assert app._new_loop_for(state_of(app, tokenless)).provider_name == "anthropic-direct"
    cli = make_token_app(tmp_path, settings_store=app.settings_store, provider_mode=None,
                         cli_provider="anthropic-direct")
    assert cli._new_loop_for(state_of(cli, start(cli, tmp_path))).provider_name == "anthropic-direct"


def test_tokenless_mock_unchanged(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store())
    session = start(app, tmp_path, token="")
    reply = result(send(app, session, "hello", conversation_mode="local_first"))
    wait_idle(app, session)
    events = result(call(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, session))["events"]
    assert "request_id" in reply
    assert any(e["role"] == "assistant" and e["type"] == "message" for e in events)


def test_token_send_ignores_model(tmp_path, monkeypatch):
    seen = []

    def fake_call(self, messages, system_prompt, on_text, should_cancel):
        seen.append((self.provider_name, self.model, self.options.num_ctx))
        return "hi", []

    monkeypatch.setattr(ClaudeToolLoop, "_call", fake_call)
    app = make_token_app(tmp_path, settings_store=_store(QWEN))
    session = start(app, tmp_path)
    before = state_of(app, session).settings["model"]
    result(send(app, session, "hello", model="some/other-model"))
    wait_idle(app, session)
    assert seen == [("ollama", "qwen3.8:27b", 32768)]      # the profile's model, not the param
    assert state_of(app, session).settings["model"] == before

    # §2f Rescue: rescue "all" is an explicit profile opt-in, and a notice
    # explains it, once per session; the json default gives no notice.
    def rescue_notices():
        events = result(call(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, session))["events"]
        return [e for e in events if (e.get("metadata") or {}).get("notice") == "rescue_all"]

    assert rescue_notices() == []
    app.settings_store.save_profile("qwen", dict(QWEN, options={"rescue": "all"}), activate=True)
    for _ in range(2):
        result(send(app, session, "again"))
        wait_idle(app, session)
    notices = rescue_notices()
    assert len(notices) == 1
    assert (notices[0]["role"], notices[0]["type"]) == ("system", "message")
    assert 'options.rescue is "all"' in notices[0]["text"] and "settings.json" in notices[0]["text"]


def test_provider_set_keeps_profile_routing(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store(QWEN))
    tokenless = start(app, tmp_path, token="")
    app.claude_loop = ScriptedLoop([])
    result(call(app, "provider.set", {"provider": "mock"}, tokenless))   # plan 02 restores the base factory
    token_session = start(app, tmp_path)
    loop = app._new_loop_for(state_of(app, token_session))
    assert loop.provider_name == "ollama" and loop.options is not None


def test_build_claude_loop_has_no_profile_lookup(tmp_path):
    _store(QWEN)                                        # an active Ollama profile in ~/.vmdai
    assert build_claude_loop("ollama") is None          # still env-only: no VMD_AI_OLLAMA_MODEL
    for fn in (build_claude_loop, provider.resolve_anthropic_api_key, provider.resolve_openrouter_api_key,
               provider.resolve_ollama_model, provider.resolve_ollama_host, keys.read_keyring_for_provider):
        assert "settings" not in inspect.getsource(fn)


def test_openai_compatible_names_known(monkeypatch):
    assert provider.build_provider("openai-compatible")[0] == "openai-compatible"
    assert keys._PROVIDER_ENV["openai-compatible"] == "VMD_AI_OPENAI_API_KEY"
    assert "openai-compatible" in CAPABILITIES["keys"]
    assert provider.resolve_openai_compatible_api_key() == ("EMPTY", "default")
    loop = build_claude_loop("openai-compatible", model="Qwen/Qwen3-8B")
    assert loop.provider_name == "openai-compatible" and loop.api_key == "EMPTY"
    assert build_claude_loop("openai-compatible") is None       # no model and no VMD_AI_MODEL
    monkeypatch.setenv("VMD_AI_OPENAI_API_KEY", "sk-local")
    assert provider.resolve_openai_compatible_api_key() == ("sk-local", "VMD_AI_OPENAI_API_KEY")


def test_first_run_on_start(tmp_path, monkeypatch):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": ["completion", "tools"], "context_length": 131072}})
    calls = []
    with FakeOllamaServer(fake) as server:
        servers = [{"base_url": server.base_url, "version": "0.12.3", "models": ["qwen3.8:27b"]}]
        monkeypatch.setattr(settings_store, "probe_local_ollama", lambda *a, **k: calls.append(1) or servers)
        store = SettingsStore()
        app = make_token_app(tmp_path, settings_store=store)
    assert calls == [1] and app.first_run_servers == servers
    assert store.active_profile() == ("ollama-%d" % server.port, {
        "provider": "ollama", "base_url": server.base_url, "model": "qwen3.8:27b", "options": {"num_ctx": 32768}})
    again = make_token_app(tmp_path, settings_store=SettingsStore())
    assert calls == [1] and again.first_run_servers == []


def test_main_help_lists_provider_flag():
    out = subprocess.run([sys.executable, str(ROOT / "runtime" / "main.py"), "--help"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "--provider" in out.stdout


def test_product_drops_ill_typed_override(caplog):
    """Plan 02 final review (a): a hand-edited ill-typed option keeps the preset value."""
    profile = {"provider": "ollama", "model": "m",
               "options": {"turn_retry": "1", "num_ctx": True, "rescue": "maybe", "loop_guard": "no",
                           "temperature": 0.2, "seed": 7, "think": "high"}}
    with caplog.at_level(logging.WARNING, logger="vmdai.claude_loop"):
        opts = LoopOptions.product(profile)
    assert (opts.turn_retry, opts.num_ctx, opts.rescue, opts.loop_guard) == (1, 32768, "json", True)
    assert (opts.temperature, opts.seed, opts.think) == (0.2, 7, "high")
    warned = " ".join(r.getMessage() for r in caplog.records)
    for key in ("turn_retry", "num_ctx", "rescue", "loop_guard"):
        assert key in warned


def test_has_agent_loop_never_builds_and_build_errors_are_provider_init_failed(tmp_path, monkeypatch):
    """Plan 02 final review (b): has_agent_loop asks the cheap predicate; a factory that
    raises at request time is PROVIDER_INIT_FAILED and starts nothing."""
    app = make_token_app(tmp_path, settings_store=_store(QWEN))
    built = []

    def boom(profile):
        built.append(profile.get("provider"))
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "_profile_loop_factory", boom)
    session = start(app, tmp_path)
    assert session.result["agent_loop"] is True and built == []
    assert result(call(app, "settings.get", {}, session))["agent_loop"] is True and built == []
    envelope = send(app, session, "hello")
    assert error_code(envelope) == "PROVIDER_INIT_FAILED" and built == ["ollama"]
    assert envelope["error"]["data"] == {"provider": "ollama"} and "boom" in envelope["error"]["message"]
    assert state_of(app, session).active_request is None and app.store.list_chats() == []
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    real_factory = type(app)._profile_loop_factory
    for profile in (dict(QWEN, source="profile"), dict(QWEN, model="", source="profile"),
                    {"provider": "openrouter", "model": "m", "source": "profile"},
                    {"provider": "anthropic-direct", "model": "claude-sonnet-4-5", "source": "profile"},
                    {"provider": "mock", "model": "m", "source": "profile"}):
        assert app._can_build_profile(profile) == (real_factory(app, profile) is not None), profile
