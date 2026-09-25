"""S7 golden requests (spec §2a): options=None requests stay byte-identical.

Each case builds the real benchmark adapter (VmdAiAgent + setup()) and drives
a scripted run: turn 1 plain; turn 2 after two run_vmd_command results (one
ok, one error); turn 3 after a capture_vmd_snapshot result with image_b64.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from helpers import fake_evaluation_framework as fake
from helpers.golden import (
    COMMON_CONFIG,
    GOLDEN_DIR,
    PROVIDER_CONFIGS,
    assert_golden,
    build_benchmark_agent,
    drive_benchmark_run,
)

CASES = [("anthropic", "none"), ("openrouter_vllm", "none"), ("ollama", "none")]
EXPECTED_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openrouter_vllm": "http://localhost:8000/v1/chat/completions",
    "ollama": "http://127.0.0.1:11435/api/chat",
}


@pytest.mark.parametrize("provider,arm", CASES)
def test_golden(provider, arm):
    agent = build_benchmark_agent(dict(COMMON_CONFIG, **PROVIDER_CONFIGS[provider]))
    requests = drive_benchmark_run(agent, provider)
    assert [r["url"] for r in requests] == [EXPECTED_URLS[provider]] * 3
    if provider == "ollama":
        assert all(json.loads(r["body_text"])["options"] == {"num_ctx": 8192}
                   for r in requests)
    assert_golden(f"{provider}_{arm}", requests)


@contextmanager
def _isolated_framework_modules() -> Iterator[None]:
    saved = {name: mod for name, mod in sys.modules.items()
             if name == "evaluation_framework" or name.startswith("evaluation_framework.")}
    for name in saved:
        del sys.modules[name]
    try:
        yield
    finally:
        for name in [n for n in sys.modules
                     if n == "evaluation_framework" or n.startswith("evaluation_framework.")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_fake_framework_only_when_missing(tmp_path, monkeypatch):
    with _isolated_framework_modules():
        assert fake.install() is True
        module = sys.modules["evaluation_framework.base_agent"]
        assert getattr(module, fake.FAKE_MARKER) is True
        from evaluation_framework.agent_registry import register_agent

        class Probe:
            pass

        assert register_agent("probe")(Probe) is Probe
        assert fake.install() is False  # already importable: left alone

    real = tmp_path / "real" / "evaluation_framework"
    real.mkdir(parents=True)
    (real / "__init__.py").write_text("")
    (real / "base_agent.py").write_text(
        "class BaseAgent:\n    pass\n\n\nclass AgentResult:\n    pass\n"
    )
    (real / "agent_registry.py").write_text("def register_agent(name):\n    return lambda c: c\n")
    monkeypatch.syspath_prepend(str(real.parent))
    with _isolated_framework_modules():
        assert fake.install() is False
        module = sys.modules["evaluation_framework.base_agent"]
        assert not hasattr(module, fake.FAKE_MARKER)
        assert Path(module.__file__).parent == real


def test_golden_diff_is_readable():
    golden = json.loads((GOLDEN_DIR / "anthropic_none.json").read_text(encoding="utf-8"))
    requests = golden["requests"]

    reserialised = [dict(r) for r in requests]
    body = json.loads(reserialised[0]["body_text"])
    reserialised[0]["body_text"] = json.dumps(body, separators=(",", ":"))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", reserialised)
    message = str(info.value)
    assert "request 0 body_text: first difference at char" in message
    assert "parse to equal JSON; the bytes differ" in message

    changed = [dict(r) for r in requests]
    body = json.loads(changed[1]["body_text"])
    body["max_tokens"] = 4095
    changed[1]["body_text"] = json.dumps(body)
    changed[2] = dict(changed[2], headers=dict(changed[2]["headers"], **{"X-api-key": "sk-other"}))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", changed)
    message = str(info.value)
    assert '+ "max_tokens": 4095,' in message
    assert '- "max_tokens": 4096,' in message
    assert "request 2 header X-api-key: expected 'sk-ant-golden', got 'sk-other'" in message
