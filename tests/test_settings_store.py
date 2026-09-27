"""P03-T05: settings_store schema, migration, precedence, flock (§2f, §7, C7)."""
from __future__ import annotations

import json
import stat

import pytest

from vmd_ai_runtime import settings_store
from vmd_ai_runtime.settings_store import SettingsError, SettingsStore, resolve_profile

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b",
        "options": {"num_ctx": 32768, "think": True, "keep_alive": "30m"}}


def _settings_file(tmp_path):
    path = tmp_path / ".vmdai" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_round_trip(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    assert store.path == tmp_path / ".vmdai" / "settings.json"
    assert not store.exists() and store.settings_source == "default"
    assert store.active_profile() == (None, None)
    assert store.save_profile("qwen-tunnel", QWEN, activate=True) == QWEN
    again = SettingsStore(home=str(tmp_path))
    assert again.exists() and again.settings_source == "file"
    assert again.active_profile() == ("qwen-tunnel", QWEN)
    assert again.list_profiles() == {"qwen-tunnel": QWEN}
    data = again.load()
    assert data["version"] == settings_store.SETTINGS_VERSION == 1
    assert settings_store.TOP_LEVEL_DEFAULTS == {
        "reasoning_visible": True, "wiki_enabled": False, "approval_mode": "auto",
        "max_turns": 28, "tool_exec_timeout_s": 900, "cancel_grace_s": 30}
    for key, value in settings_store.TOP_LEVEL_DEFAULTS.items():
        assert data[key] == value
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.patch({"max_turns": 12, "wiki_enabled": True})["max_turns"] == 12
    assert SettingsStore(home=str(tmp_path)).load()["wiki_enabled"] is True


def test_migrates_version_0(tmp_path):
    path = _settings_file(tmp_path)
    path.write_text(json.dumps({"active": "qwen", "profiles": {"qwen": QWEN}, "max_turns": 20}))
    store = SettingsStore(home=str(tmp_path))
    data = store.load()
    on_disk = json.loads(path.read_text())
    assert on_disk["version"] == 1 and on_disk["profiles"] == {"qwen": QWEN} and on_disk["active"] == "qwen"
    assert on_disk["max_turns"] == 20 and on_disk["reasoning_visible"] is True
    assert data == on_disk and store.settings_source == "file"
    path.write_text(json.dumps({"version": 0, "profiles": {}}))
    assert SettingsStore(home=str(tmp_path)).load()["version"] == 1


def test_newer_version_read_only(tmp_path):
    path = _settings_file(tmp_path)
    raw = json.dumps({"version": 2, "active": "qwen", "profiles": {"qwen": QWEN}, "future": {"x": 1}})
    path.write_text(raw)
    store = SettingsStore(home=str(tmp_path))
    assert store.settings_source == "newer"
    assert store.active_profile() == ("qwen", QWEN)
    writes = (lambda: store.save_profile("b", QWEN), lambda: store.patch({"max_turns": 3}),
              lambda: store.activate("qwen"), lambda: store.update_profile("qwen", model="m"),
              lambda: store.delete_profile("qwen"))
    for write in writes:
        with pytest.raises(SettingsError) as info:
            write()
        assert info.value.code == "READ_ONLY"
    assert path.read_text() == raw


def test_invalid_json_read_only(tmp_path):
    """Review focus: a hand-edited file that does not parse is never overwritten."""
    path = _settings_file(tmp_path)
    raw = '{"version": 1, "active": "qwen", "profiles": {"qwen": {"provider": "ollama",}}'
    path.write_text(raw)
    store = SettingsStore(home=str(tmp_path))
    assert store.exists() and store.settings_source == "invalid"
    assert store.load()["profiles"] == {} and store.active_profile() == (None, None)
    with pytest.raises(SettingsError) as info:
        store.save_profile("qwen", QWEN, activate=True)
    assert info.value.code == "READ_ONLY"
    assert path.read_text() == raw
    path.write_text("[1, 2]")
    assert SettingsStore(home=str(tmp_path)).settings_source == "invalid"


def test_unknown_option_keys_preserved(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", dict(QWEN, options={"num_ctx": 16384, "future_knob": {"a": 1}}), activate=True)
    store.update_profile("qwen", model="qwen3.8:32b")
    store.patch({"max_turns": 30})
    profile = SettingsStore(home=str(tmp_path)).get_profile("qwen")
    assert profile["options"] == {"num_ctx": 16384, "future_knob": {"a": 1}}
    assert profile["model"] == "qwen3.8:32b"


def test_delete_active_in_use(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", QWEN, activate=True)
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    with pytest.raises(SettingsError) as info:
        store.delete_profile("qwen")
    assert info.value.code == "IN_USE"
    store.delete_profile("claude")
    assert set(store.list_profiles()) == {"qwen"}
    with pytest.raises(SettingsError) as missing:
        store.delete_profile("claude")
    assert missing.value.code == "NOT_FOUND"
    with pytest.raises(SettingsError) as unknown:
        store.activate("nope")
    assert unknown.value.code == "NOT_FOUND"


def test_model_change_keeps_num_ctx(tmp_path):
    """C7: a model change keeps the stored num_ctx unless the same call sets it."""
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", dict(QWEN, options={"num_ctx": 16384}), activate=True)
    assert store.update_profile("qwen", model="llama3.1:8b")["options"]["num_ctx"] == 16384
    changed = store.update_profile("qwen", model="qwen3.8:27b", options={"num_ctx": 8192})
    assert changed["options"]["num_ctx"] == 8192
    assert store.get_profile("qwen")["model"] == "qwen3.8:27b"


def test_provider_change_resets_base_url_and_options(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("main", QWEN, activate=True)
    claude = store.update_profile("main", provider="anthropic-direct", model="claude-sonnet-4-5")
    assert claude == {"provider": "anthropic-direct", "model": "claude-sonnet-4-5", "options": {}}
    back = store.update_profile("main", provider="ollama", model="qwen3.8:27b")
    assert back["base_url"] == "http://localhost:11434" and back["options"] == {}
    with pytest.raises(SettingsError) as info:
        store.update_profile("main", provider="mock")
    assert info.value.code == "INVALID"


def test_patch_validates_top_level(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    bad_patches = ({"approval_mode": "ask"}, {"max_turns": 0}, {"max_turns": True},
                   {"wiki_enabled": "yes"}, {"colour": "red"}, {"cancel_grace_s": -1})
    for bad in bad_patches:
        with pytest.raises(SettingsError) as info:
            store.patch(bad)
        assert info.value.code == "INVALID"
    assert not store.exists()


def test_precedence_cli_profile_env(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    env = {"VMD_AI_PROVIDER": "anthropic-direct", "ANTHROPIC_MODEL": "claude-sonnet-4-5"}
    # VMD_AI_PROVIDER is seed-only (§7): with no active profile it is ignored.
    assert resolve_profile(store, None, env) == (None, None, "none")
    assert resolve_profile(store, None, {}) == (None, None, "none")
    store.save_profile("qwen", QWEN, activate=True)
    assert resolve_profile(store, None, env) == ("qwen", QWEN, "profile")
    name, profile, source = resolve_profile(store, "openrouter", env)
    assert (name, source) == (None, "cli")
    assert profile["provider"] == "openrouter" and profile["base_url"] == "https://openrouter.ai/api/v1"
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    name, profile, source = resolve_profile(store, "claude", env)
    assert (name, source, profile["provider"]) == ("claude", "cli", "anthropic-direct")
    assert settings_store.normalize_provider("anthropic") == "anthropic-direct"
    assert settings_store.normalize_provider("vllm") == "openai-compatible"
    assert settings_store.normalize_provider("mock") == ""


def test_ill_typed_option_values_rejected(tmp_path):
    """Plan 02 final review (a): an ill-typed known option is INVALID and nothing is written."""
    import dataclasses
    from vmd_ai_runtime import claude_loop
    groups = (claude_loop.OPTION_INT_KEYS + claude_loop.OPTION_NUMBER_KEYS + claude_loop.OPTION_BOOL_KEYS
              + claude_loop.OPTION_STR_KEYS + claude_loop.OPTION_DICT_KEYS + claude_loop.OPTION_UNCHECKED_KEYS)
    assert sorted(groups) == sorted(f.name for f in dataclasses.fields(claude_loop.LoopOptions))
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", QWEN, activate=True)
    before = store.path.read_text()
    for bad in ({"turn_retry": "1"}, {"num_ctx": True}, {"num_ctx": "32768"}, {"temperature": "0.2"},
                {"rescue": "maybe"}, {"loop_guard": "no"}, {"extra_body": [1]}, {"base_url": 5},
                {"turn_retry": None}):
        for write in (lambda: store.save_profile("other", dict(QWEN, options=bad)),
                      lambda: store.update_profile("qwen", options=bad)):
            with pytest.raises(SettingsError) as info:
                write()
            assert info.value.code == "INVALID" and next(iter(bad)) in info.value.message
    assert store.path.read_text() == before
    fine = {"turn_retry": 2, "temperature": 0, "seed": None, "rescue": "off", "think": "high",
            "supports_vision": "auto", "future_knob": [1]}
    assert store.save_profile("other", dict(QWEN, options=fine))["options"] == fine


def test_base_url_must_be_http(tmp_path):
    """M5: both profile.base_url and options.base_url get the http(s) check."""
    store = SettingsStore(home=str(tmp_path))
    with pytest.raises(SettingsError) as info:
        store.save_profile("qwen", dict(QWEN, base_url="file:///etc/passwd"))
    assert info.value.code == "INVALID" and "base_url" in info.value.message
    assert not store.path.exists()
    with pytest.raises(SettingsError) as info:
        store.save_profile("qwen", dict(QWEN, options=dict(QWEN["options"], base_url="ftp://x")))
    assert info.value.code == "INVALID" and "base_url" in info.value.message
    assert not store.path.exists()
    store.save_profile("qwen", dict(QWEN, base_url="http://127.0.0.1:11435"), activate=True)
    before = store.path.read_text()
    with pytest.raises(SettingsError) as info:
        store.update_profile("qwen", options={"base_url": "ftp://x"})
    assert info.value.code == "INVALID"
    assert store.path.read_text() == before
