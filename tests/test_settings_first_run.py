"""P03-T06: first run: probe, profile_from_server (C7), last_provider seed (§2f)."""
from __future__ import annotations

import inspect
import time

from helpers.fake_ollama import FakeOllama, FakeOllamaServer, FakeUrlopen, stale_listener
from vmd_ai_runtime.settings_store import SettingsStore, profile_from_server

TOOLS = ["completion", "tools"]


def _one_model(context_length):
    return FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS + ["thinking", "vision"],
                                       "context_length": context_length}})


def test_profile_from_server_num_ctx():
    base = "http://127.0.0.1:11435"
    for context_length, expected in ((131072, 32768), (8192, 8192), (None, 32768)):
        profile = profile_from_server(base, urlopen=FakeUrlopen({base: _one_model(context_length)}))
        assert profile == {"provider": "ollama", "base_url": base, "model": "qwen3.8:27b",
                           "options": {"num_ctx": expected}}


def test_probe_order_11435_then_11434(real_probe_local_ollama):
    ports = inspect.signature(real_probe_local_ollama).parameters["ports"].default
    assert tuple(ports) == (11435, 11434)
    first = _one_model(40960)
    second = FakeOllama({"llama3.1:8b": {"capabilities": TOOLS}}, version="0.11.0")
    with FakeOllamaServer(first) as a, FakeOllamaServer(second) as b:
        servers = real_probe_local_ollama(ports=(a.port, b.port), timeout=0.3)
    assert servers == [
        {"base_url": a.base_url, "version": "0.12.3", "models": ["qwen3.8:27b"]},
        {"base_url": b.base_url, "version": "0.11.0", "models": ["llama3.1:8b"]},
    ]
    assert first.requests[0][0] < second.requests[0][0]
    assert first.paths() == ["/api/version", "/api/tags"]


def test_first_responding_becomes_active(tmp_path):
    a, b = "http://127.0.0.1:11435", "http://127.0.0.1:11434"
    opener = FakeUrlopen({a: _one_model(131072),
                          b: FakeOllama({"llama3.1:8b": {"capabilities": TOOLS, "context_length": 8192}})})
    servers = [{"base_url": a, "version": "0.12.3", "models": ["qwen3.8:27b"]},
               {"base_url": b, "version": "0.12.3", "models": ["llama3.1:8b"]}]
    store = SettingsStore(home=str(tmp_path))
    data = store.first_run(servers, urlopen=opener)
    assert data["active"] == "ollama-11435"
    assert data["profiles"] == {
        "ollama-11435": {"provider": "ollama", "base_url": a, "model": "qwen3.8:27b", "options": {"num_ctx": 32768}},
        "ollama-11434": {"provider": "ollama", "base_url": b, "model": "llama3.1:8b", "options": {"num_ctx": 8192}},
    }
    assert store.settings_source == "file"
    empty = SettingsStore(home=str(tmp_path / "empty"))
    assert empty.first_run([], urlopen=opener)["profiles"] == {}
    assert not empty.exists()


def test_seed_from_last_provider_never_active(tmp_path):
    (tmp_path / ".vmdai").mkdir()
    (tmp_path / ".vmdai" / "last_provider.txt").write_text("anthropic-direct\tclaude-sonnet-4-5")
    data = SettingsStore(home=str(tmp_path)).first_run([])
    assert data["active"] is None
    assert data["profiles"] == {"claude": {"provider": "anthropic-direct", "model": "claude-sonnet-4-5", "options": {}}}
    other = tmp_path / "other"
    (other / ".vmdai").mkdir(parents=True)
    (other / ".vmdai" / "last_provider.txt").write_text("openrouter\tanthropic/claude-sonnet-4.6")
    base = "http://127.0.0.1:11435"
    data = SettingsStore(home=str(other)).first_run(
        [{"base_url": base, "version": "0.12.3", "models": ["qwen3.8:27b"]}],
        urlopen=FakeUrlopen({base: _one_model(40960)}))
    assert data["active"] == "ollama-11435"
    assert data["profiles"]["openrouter"] == {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1",
                                              "model": "anthropic/claude-sonnet-4.6", "options": {}}


def test_ollama_seed_merged_into_ollama_port_profile(tmp_path):
    (tmp_path / ".vmdai").mkdir()
    (tmp_path / ".vmdai" / "last_provider.txt").write_text("ollama\tqwen-small:4b\n")
    base = "http://127.0.0.1:11435"
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS, "context_length": 131072},
                       "qwen-small:4b": {"capabilities": TOOLS, "context_length": 16384}})
    data = SettingsStore(home=str(tmp_path)).first_run(
        [{"base_url": base, "version": "0.12.3", "models": ["qwen3.8:27b", "qwen-small:4b"]}],
        urlopen=FakeUrlopen({base: fake}))
    assert data["profiles"] == {"ollama-11435": {"provider": "ollama", "base_url": base,
                                                 "model": "qwen-small:4b", "options": {"num_ctx": 16384}}}
    assert data["active"] == "ollama-11435"


def test_model_prefers_tools_capability():
    base = "http://127.0.0.1:11434"
    fake = FakeOllama({"llava:7b": {"capabilities": ["completion", "vision"], "context_length": 4096},
                       "qwen3.8:27b": {"capabilities": TOOLS, "context_length": 40960}})
    profile = profile_from_server(base, urlopen=FakeUrlopen({base: fake}))
    assert profile["model"] == "qwen3.8:27b" and profile["options"] == {"num_ctx": 32768}
    only_text = FakeOllama({"llava:7b": {"capabilities": ["completion"], "context_length": 4096}})
    assert profile_from_server(base, urlopen=FakeUrlopen({base: only_text}))["model"] == "llava:7b"


def test_probe_bounded_timeout(real_probe_local_ollama):
    """Review focus: a stale tunnel (accepts, never answers) costs about 300 ms per port."""
    with stale_listener() as first, stale_listener() as second:
        t0 = time.monotonic()
        servers = real_probe_local_ollama(ports=(first, second), timeout=0.3)
        elapsed = time.monotonic() - t0
    assert servers == []
    assert elapsed < 1.5
