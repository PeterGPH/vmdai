"""P03-T07: provider_catalog (§3, §2f Probes, Thinking detection, Unreachable classification; C9).

Never import provider_catalog.test_provider by name into this module: pytest
would collect it as a test. Always call it as provider_catalog.test_provider(...).
"""
from __future__ import annotations

import time
import urllib.request

import pytest

from helpers.fake_ollama import FakeOllama, FakeOllamaServer, closed_port, stale_listener
from vmd_ai_runtime import provider_catalog

TOOLS = ["completion", "tools"]


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(provider_catalog, "_now", lambda: now[0])
    return now


def test_list_models_ollama_cached_60s(clock):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS + ["vision"], "context_length": 131072,
                                       "size": 17000000000}})
    with FakeOllamaServer(fake) as server:
        first = provider_catalog.list_models("ollama", server.base_url)
        assert first == {"source": "server", "models": [{
            "id": "qwen3.8:27b", "label": "qwen3.8:27b", "size": 17000000000,
            "capabilities": {"tools": True, "vision": True, "thinking": False}, "context_length": 131072}]}
        calls = len(fake.requests)
        clock[0] += 59
        again = provider_catalog.list_models("ollama", server.base_url)
        assert again["source"] == "cache" and again["models"] == first["models"]
        assert len(fake.requests) == calls
        clock[0] += 2
        assert provider_catalog.list_models("ollama", server.base_url)["source"] == "server"
        assert len(fake.requests) > calls


def test_version_cached_30s_ps_never_cached(clock):
    fake = FakeOllama({"m": {"capabilities": TOOLS}}, loaded=["m"])
    with FakeOllamaServer(fake) as server:
        assert provider_catalog.ollama_version(server.base_url) == "0.12.3"
        clock[0] += 29
        assert provider_catalog.ollama_version(server.base_url) == "0.12.3"
        assert fake.paths().count("/api/version") == 1
        clock[0] += 2
        provider_catalog.ollama_version(server.base_url)
        assert fake.paths().count("/api/version") == 2
        for _ in range(3):
            assert [m["name"] for m in provider_catalog.ollama_ps(server.base_url)] == ["m"]
        assert fake.paths().count("/api/ps") == 3


def test_clear_caches(clock):
    fake = FakeOllama({"m": {"capabilities": TOOLS}})
    with FakeOllamaServer(fake) as server:
        provider_catalog.list_models("ollama", server.base_url)
        provider_catalog.ollama_version(server.base_url)
        assert provider_catalog.cached_tag_digest(server.base_url, "m") == fake.digest("m")
        assert provider_catalog.cached_tag_digest(server.base_url, "other") is None
        provider_catalog.clear_caches()
        assert provider_catalog.cached_tag_digest(server.base_url, "m") is None
        before = len(fake.requests)
        assert provider_catalog.list_models("ollama", server.base_url)["source"] == "server"
        provider_catalog.ollama_version(server.base_url)
        assert fake.paths()[before:].count("/api/version") == 1


def test_capabilities_prefer_thinking_object():
    caps = provider_catalog.model_capabilities
    assert caps({"capabilities": ["completion", "tools", "vision", "thinking"]}) == {
        "tools": True, "vision": True, "thinking": True}
    assert caps({"capabilities": ["completion", "tools"], "thinking": {"supported": True}})["thinking"] is True
    assert caps({"capabilities": ["thinking"], "thinking": {"supported": False}})["thinking"] is False
    assert caps({"capabilities": ["thinking"], "thinking": False})["thinking"] is False
    assert caps({}) == {"tools": False, "vision": False, "thinking": False}


def test_provider_test_warns_without_tools():
    fake = FakeOllama({"llava:7b": {"capabilities": ["completion", "vision"]},
                       "qwen3.8:27b": {"capabilities": TOOLS}}, loaded=["qwen3.8:27b"])
    with FakeOllamaServer(fake) as server:
        plain = provider_catalog.test_provider("ollama", server.base_url, "llava:7b")
        good = provider_catalog.test_provider("ollama", server.base_url, "qwen3.8:27b")
        missing = provider_catalog.test_provider("ollama", server.base_url, "nope:1b")
    assert plain["ok"] is True and plain["reachable"] is True and plain["model_present"] is True
    assert plain["loaded"] is False and plain["capabilities"]["tools"] is False
    assert plain["hint"] == provider_catalog.NO_TOOLS_HINT
    assert isinstance(plain["latency_ms"], int)
    assert good["ok"] is True and good["loaded"] is True and "hint" not in good
    assert good["version"] == "0.12.3"                  # FakeOllama's /api/version (Part B V4)
    assert missing["ok"] is False and missing["model_present"] is False
    assert missing["hint"] == "ollama pull nope:1b"


def test_unreachable_hints_exact_wording():
    hint = provider_catalog.unreachable_hint
    assert hint("http://127.0.0.1:11435", "refused") == \
        "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"
    assert hint("http://127.0.0.1:11435", "reset") == \
        "The tunnel on :11435 is up, but Ollama on the GPU server is not answering. Start `ollama serve` there."
    assert hint("http://127.0.0.1:11435", "timeout") == \
        "No reply from :11435 within 2 s. The tunnel may be stale; restart it."
    assert hint("http://127.0.0.1:11434", "refused") == \
        "Nothing is listening on 127.0.0.1:11434. Is `ollama serve` running?"
    base = "http://127.0.0.1:%d" % closed_port()
    refused = provider_catalog.test_provider("ollama", base, "m")
    assert refused["reachable"] is False and refused["ok"] is False
    assert refused["hint"] == hint(base, "refused")
    with stale_listener() as stale:
        t0 = time.monotonic()
        silent = provider_catalog.test_provider("ollama", "http://127.0.0.1:%d" % stale, "m", timeout=0.3)
        assert time.monotonic() - t0 < 1.5
    assert silent["reachable"] is False and "within 2 s" in silent["hint"]


def test_only_allowlisted_paths(clock):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS, "context_length": 40960}}, loaded=["qwen3.8:27b"])
    with FakeOllamaServer(fake) as server:
        provider_catalog.list_models("ollama", server.base_url)
        provider_catalog.test_provider("ollama", server.base_url, "qwen3.8:27b")
        provider_catalog.ollama_version(server.base_url)
        provider_catalog.ollama_ps(server.base_url)
        provider_catalog.ollama_show(server.base_url, "qwen3.8:27b")
    assert set(fake.paths()) <= {"/api/version", "/api/tags", "/api/show", "/api/ps"}
    assert "/api/chat" not in fake.paths() and "/api/generate" not in fake.paths()


def test_urlopen_reached_by_attribute(monkeypatch, clock):
    seen = []
    real = urllib.request.urlopen

    def spy(request, *args, **kwargs):
        seen.append(request.full_url)
        return real(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    with FakeOllamaServer(FakeOllama({"m": {"capabilities": TOOLS}})) as server:
        provider_catalog.ollama_version(server.base_url)
    assert seen == [server.base_url + "/api/version"]


def test_openai_compatible_and_anthropic_catalogs(clock):
    fake = FakeOllama({"Qwen/Qwen3-8B": {}})
    with FakeOllamaServer(fake) as server:
        listed = provider_catalog.list_models("openai-compatible", server.base_url + "/v1", api_key="EMPTY")
        tested = provider_catalog.test_provider("openai-compatible", server.base_url + "/v1",
                                                "Qwen/Qwen3-8B", api_key="EMPTY")
    assert listed == {"source": "server", "models": [{"id": "Qwen/Qwen3-8B", "label": "Qwen/Qwen3-8B"}]}
    assert tested["ok"] is True and tested["model_present"] is True and tested["loaded"] is None
    anthropic = provider_catalog.list_models("anthropic-direct", None)
    assert anthropic["source"] == "static" and anthropic["models"][0]["id"] == "claude-sonnet-4-6"
    assert provider_catalog.list_models("mock", None)["source"] == "none"
