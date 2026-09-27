"""P03-T09: runtime.info, session.set_cwd, models.list, provider.test, provider.set, settings.set
(§2c Stage split, §3 RPC table, §2e privileged ops, S11)."""
from __future__ import annotations

import json
import os
import threading
import time

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
from vmd_ai_runtime import provider_catalog, settings_store
from vmd_ai_runtime.claude_loop import LoopOptions
from vmd_ai_runtime.constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from vmd_ai_runtime.settings_store import SettingsStore

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b",
        "options": {"num_ctx": 16384}}
INFO_KEYS = {"version", "protocol", "pid", "provider", "model", "agent_loop", "vision", "tools", "rag",
             "wiki", "max_turns", "log_path", "settings_source", "first_run"}


def _app(tmp_path, profile=QWEN):
    store = SettingsStore()
    if profile is not None:
        store.save_profile("qwen", profile, activate=True)
    return make_token_app(tmp_path, settings_store=store)


def test_runtime_info_shape(tmp_path):
    app = _app(tmp_path)
    session = start(app, tmp_path)
    info = result(call(app, "runtime.info", {}, session))
    assert set(info) == INFO_KEYS
    assert (info["version"], info["protocol"], info["pid"]) == (RUNTIME_VERSION, RUNTIME_PROTOCOL, os.getpid())
    assert (info["provider"], info["model"], info["agent_loop"]) == ("ollama", "qwen3.8:27b", True)
    assert info["tools"] == ["run_vmd_command", "capture_vmd_snapshot"]
    assert (info["rag"], info["wiki"], info["vision"], info["max_turns"]) == (False, False, False, 28)
    assert info["settings_source"] == "file" and info["first_run"] == {"servers": []}
    assert isinstance(info["log_path"], str) and info["log_path"]
    tokenless = start(app, tmp_path, token="")
    assert set(result(call(app, "runtime.info", {}, tokenless))) == INFO_KEYS
    assert error_code(call(app, "runtime.info", {})) == "INVALID_PARAMS"
    # No usable profile: a token session reports no provider, never the env/mock fallback (§2f).
    blank = make_token_app(tmp_path / "blank", settings_store=SettingsStore(home=str(tmp_path / "blank")))
    none = result(call(blank, "runtime.info", {}, start(blank, tmp_path / "blank")))
    assert (none["provider"], none["model"], none["agent_loop"], none["tools"]) == ("", "", False, [])


def test_active_request_reported(tmp_path):
    app = _app(tmp_path)
    app.tool_bridge = InstantBridge()
    gate = threading.Event()
    loop = ScriptedLoop([("", [tool_use("tc_0", "molinfo list")]), ("done", [])],
                        before_call=lambda number, messages: number == 2 and gate.wait(5),
                        options=LoopOptions())
    app.claude_loop = loop
    session = start(app, tmp_path)
    t0 = time.time()
    request_id = result(send(app, session, "list molecules"))["request_id"]
    try:
        deadline = time.monotonic() + 5
        while len(loop.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        active = result(call(app, "runtime.info", {}, session))["active_request"]
    finally:
        gate.set()
    assert active["request_id"] == request_id
    assert active["turn"] >= 1
    assert t0 - 1 <= active["started_at"] <= time.time()
    assert isinstance(active["last_seq"], int) and active["last_seq"] >= 1
    wait_idle(app, session)
    assert "active_request" not in result(call(app, "runtime.info", {}, session))


def test_first_run_servers_empty_once_settings_exist(tmp_path, monkeypatch):
    servers = [{"base_url": "http://127.0.0.1:11435", "version": "0.12.3", "models": []}]
    probes = []
    monkeypatch.setattr(settings_store, "probe_local_ollama", lambda *a, **k: probes.append(1) or servers)
    fresh = make_token_app(tmp_path, settings_store=SettingsStore())
    assert result(call(fresh, "runtime.info", {}, start(fresh, tmp_path)))["first_run"] == {"servers": servers}
    assert probes == [1]
    SettingsStore().save_profile("qwen", QWEN, activate=True)
    later = make_token_app(tmp_path, settings_store=SettingsStore())
    assert result(call(later, "runtime.info", {}, start(later, tmp_path)))["first_run"] == {"servers": []}
    assert probes == [1]


def test_set_cwd_requires_auth_and_dir(tmp_path):
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    target = tmp_path / "project"
    target.mkdir()
    assert error_code(call(app, "session.set_cwd", {"cwd": str(target)}, tokenless)) == "AUTH_REQUIRED"
    assert error_code(call(app, "session.set_cwd", {"cwd": str(tmp_path / "missing")}, token_session)) == "INVALID_PARAMS"
    assert error_code(call(app, "session.set_cwd", {}, token_session)) == "INVALID_PARAMS"
    reply = result(call(app, "session.set_cwd", {"cwd": str(target)}, token_session))
    assert reply == {"ok": True, "cwd": os.path.realpath(str(target))}
    assert state_of(app, token_session).cwd == os.path.realpath(str(target))


def test_models_list_base_url_requires_auth(tmp_path, monkeypatch):
    seen = []

    def fake_list(provider, base_url, api_key="", timeout=3.0):
        seen.append((provider, base_url, api_key))
        return {"models": [], "source": "server"}

    monkeypatch.setattr(provider_catalog, "list_models", fake_list)
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    remote = {"provider": "ollama", "base_url": "http://10.0.0.5:11434"}
    assert error_code(call(app, "models.list", remote, tokenless)) == "AUTH_REQUIRED"
    assert result(call(app, "models.list", {}, token_session)) == {"models": [], "source": "server"}
    result(call(app, "models.list", remote, token_session))
    result(call(app, "models.list", {"provider": "openai-compatible"}, tokenless))
    assert seen == [("ollama", "http://127.0.0.1:9", ""),
                    ("ollama", "http://10.0.0.5:11434", ""),
                    ("openai-compatible", "http://localhost:8000/v1", "EMPTY")]
    assert error_code(call(app, "models.list", {"base_url": "file:///etc/passwd"}, token_session)) == "INVALID_PARAMS"


def test_provider_test_base_url_requires_auth(tmp_path, monkeypatch):
    seen = []

    def fake_test(provider, base_url, model, api_key="", timeout=3.0):
        seen.append((provider, base_url, model))
        return {"ok": True}

    monkeypatch.setattr(provider_catalog, "test_provider", fake_test)
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    assert error_code(call(app, "provider.test", {"base_url": "http://10.0.0.5:11434"}, tokenless)) == "AUTH_REQUIRED"
    assert result(call(app, "provider.test", {}, token_session)) == {"ok": True}
    result(call(app, "provider.test", {"model": "llama3.1:8b"}, token_session))
    assert seen == [("ollama", "http://127.0.0.1:9", "qwen3.8:27b"), ("ollama", "http://127.0.0.1:9", "llama3.1:8b")]


def test_provider_set_persists_to_active_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_catalog, "ollama_show",
                        lambda base_url, model, timeout=3.0: {"capabilities": ["completion", "tools", "vision"]})
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    reply = result(call(app, "provider.set", {"provider": "ollama", "model": "qwen3.8:32b"}, token_session))
    assert reply["profile"] == "qwen" and reply["model"] == "qwen3.8:32b"
    assert reply["capabilities"] == {"tools": True, "vision": True, "thinking": False}
    stored = app.settings_store.get_profile("qwen")
    assert stored["model"] == "qwen3.8:32b" and stored["options"] == {"num_ctx": 16384}
    result(call(app, "provider.set", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5",
                                      "profile": "claude"}, token_session))
    assert app.settings_store.get_profile("claude") == {"provider": "anthropic-direct",
                                                        "model": "claude-sonnet-4-5", "options": {}}
    assert app.settings_store.active_profile()[0] == "qwen"
    bad = call(app, "provider.set", {"provider": "ollama", "options": {"turn_retry": "1"}}, token_session)
    assert error_code(bad) == "INVALID_PARAMS" and "turn_retry" in bad["error"]["message"]
    assert "turn_retry" not in app.settings_store.get_profile("qwen")["options"]
    privileged = ({"provider": "ollama", "base_url": "http://10.0.0.5:11434"},
                  {"provider": "ollama", "options": {"num_ctx": 8192}},
                  {"provider": "ollama", "profile": "qwen"})
    for params in privileged:
        assert error_code(call(app, "provider.set", params, tokenless)) == "AUTH_REQUIRED"
    assert app.settings_store.get_profile("qwen")["model"] == "qwen3.8:32b"


def test_provider_set_activates_when_none_is_active(tmp_path):
    """First run seeded `claude` from last_provider.txt but never activated it (§2f).
    Applying that provider in the M1 panel must make it the active profile, or
    the next chat.send would still return NO_MODEL."""
    store = SettingsStore()
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)
    reply = result(call(app, "provider.set", {"provider": "anthropic-direct", "model": "claude-sonnet-4-6"}, session))
    assert reply["profile"] == "claude"
    assert store.active_profile() == ("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-6",
                                                 "options": {}})
    blank = SettingsStore(home=str(tmp_path / "blank"))
    other = make_token_app(tmp_path / "blank", settings_store=blank)
    made = result(call(other, "provider.set", {"provider": "openai-compatible", "model": "Qwen/Qwen3-8B"},
                       start(other, tmp_path / "blank")))
    assert (made["profile"], made["agent_loop"]) == ("openai-compatible", True)
    assert blank.active_profile() == ("openai-compatible", {
        "provider": "openai-compatible", "model": "Qwen/Qwen3-8B",
        "base_url": "http://localhost:8000/v1", "options": {}})


def test_provider_set_switch_keeps_other_profiles(tmp_path):
    """I1 (whole-branch review): a provider switch with no explicit ``profile``
    lands on (or creates) a profile of the requested provider instead of
    overwriting the active profile in place, so switching providers and back
    restores the tunnel profile's base_url and options untouched."""
    tunnel = {"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b",
              "options": {"num_ctx": 16384, "keep_alive": "30m"}}
    store = SettingsStore()
    store.save_profile("ollama-11435", tunnel, activate=True)
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)

    reply = result(call(app, "provider.set", {"provider": "anthropic-direct",
                                              "model": "claude-sonnet-4-5"}, session))
    assert reply["profile"] == "claude"
    assert store.active_profile()[0] == "claude"
    assert store.get_profile("ollama-11435") == tunnel

    reply = result(call(app, "provider.set", {"provider": "ollama", "model": "qwen3.8:27b"}, session))
    assert reply["profile"] == "ollama-11435"
    assert store.active_profile()[0] == "ollama-11435"
    restored = store.get_profile("ollama-11435")
    assert restored["base_url"] == "http://127.0.0.1:11435"
    assert restored["options"] == {"num_ctx": 16384, "keep_alive": "30m"}

    # A default-named `ollama` profile, when present, is preferred over ollama-11435.
    store.save_profile("ollama", {"provider": "ollama", "model": "llama3.1:8b", "options": {}})
    result(call(app, "provider.set", {"provider": "anthropic-direct", "model": "claude-sonnet-4-6"}, session))
    reply = result(call(app, "provider.set", {"provider": "ollama", "model": "qwen3.8:27b"}, session))
    assert reply["profile"] == "ollama"
    assert store.active_profile()[0] == "ollama"

    # No anthropic-direct profile exists, but a differently-provider'd
    # `claude` profile does: the switch creates and activates `claude-2`.
    other = SettingsStore(home=str(tmp_path / "other"))
    other.save_profile("claude", {"provider": "openrouter", "model": "anthropic/claude-sonnet-4.6"},
                       activate=True)
    other_app = make_token_app(tmp_path / "other_app", settings_store=other)
    other_session = start(other_app, tmp_path / "other_app")
    reply = result(call(other_app, "provider.set", {"provider": "anthropic-direct",
                                                    "model": "claude-sonnet-4-5"}, other_session))
    assert reply["profile"] == "claude-2"
    assert other.active_profile()[0] == "claude-2"
    assert other.get_profile("claude-2")["provider"] == "anthropic-direct"
    assert other.get_profile("claude")["provider"] == "openrouter"          # untouched


def test_settings_set_persisted_keys_require_auth(tmp_path):
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    for key, value in (("wiki_enabled", True), ("max_turns", 12), ("tool_exec_timeout_s", 60),
                       ("cancel_grace_s", 5), ("approval_mode", "auto")):
        assert error_code(call(app, "settings.set", {"patch": {key: value}}, tokenless)) == "AUTH_REQUIRED"
    per_session = result(call(app, "settings.set", {"patch": {"mode": "tutor", "reasoning_visible": False}}, tokenless))
    assert per_session["settings"]["mode"] == "tutor" and "persisted" not in per_session
    assert app.settings_store.load()["reasoning_visible"] is True
    reply = result(call(app, "settings.set", {"patch": {"max_turns": 12, "wiki_enabled": True}}, token_session))
    assert reply["persisted"]["max_turns"] == 12 and reply["persisted"]["wiki_enabled"] is True
    assert SettingsStore().load()["max_turns"] == 12


def test_approval_mode_only_auto(tmp_path):
    app = _app(tmp_path)
    session = start(app, tmp_path)
    assert error_code(call(app, "settings.set", {"patch": {"approval_mode": "ask"}}, session)) == "INVALID_PARAMS"
    reply = result(call(app, "settings.set", {"patch": {"approval_mode": "auto"}}, session))
    assert reply["persisted"]["approval_mode"] == "auto"


def test_read_only_settings_rejected_over_rpc(tmp_path):
    store = SettingsStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken")
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)
    envelope = call(app, "settings.set", {"patch": {"max_turns": 5}}, session)
    assert error_code(envelope) == "INVALID_PARAMS"
    assert envelope["error"]["data"] == {"reason": "read_only", "settings_source": "invalid"}
    assert result(call(app, "runtime.info", {}, session))["settings_source"] == "invalid"
    assert store.path.read_text() == "{broken"


def test_hand_edited_top_level_settings_fall_back(tmp_path):
    """M1: a malformed top-level value falls back to its default instead of crashing."""
    store = SettingsStore()
    store.save_profile("qwen", QWEN, activate=True)
    data = json.loads(store.path.read_text())
    data["max_turns"] = None
    data["wiki_enabled"] = "false"
    store.path.write_text(json.dumps(data))
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)
    info = result(call(app, "runtime.info", {}, session))
    assert info["max_turns"] == 28 and info["wiki"] is False
    reply = result(send(app, session, "hello"))
    assert reply["request_id"]
    wait_idle(app, session)

    other_home = tmp_path / "other"
    other = SettingsStore(home=str(other_home))
    other.path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"version": 1, "active": None, "profiles": []})
    other.path.write_text(raw)
    other_app = make_token_app(tmp_path / "other_app", settings_store=other)
    other_session = start(other_app, tmp_path / "other_app")
    assert other.settings_source == "invalid"
    envelope = call(other_app, "provider.set", {"provider": "ollama", "model": "m"}, other_session)
    assert error_code(envelope) == "INVALID_PARAMS"
    assert envelope["error"]["data"]["reason"] == "read_only"
    assert other.path.read_text() == raw
