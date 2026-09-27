"""P04-T02: Ollama request-body fields come from LoopOptions (spec 2f, C7).

With options=None the body is today's: num_ctx 8192, temperature/seed from
VMD_AI_TEMPERATURE/VMD_AI_SEED, no think, no keep_alive (the S7 goldens pin
the bytes). With options set, every field comes from the profile and the
environment is never read.
"""
from __future__ import annotations

import dataclasses
from typing import Any, List, Optional

import pytest

from helpers.provider_fakes import FakeHttp, ndjson, patch_urlopen
from vmd_ai_runtime import claude_loop
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    LoopOptions,
    _stream_ollama,
    _to_ollama_messages,
    _vmd_tools,
)

BASE = "http://ollama.test"
MODEL = "qwen3.8:27b"
DONE = ndjson([
    {"message": {"role": "assistant", "content": "ok"}},
    {"done": True, "done_reason": "stop"},
])
NO_THINKING = b'{"error":"\\"qwen3.8:27b\\" does not support thinking"}'
TOOL_ROUND = [
    {"role": "user", "content": "load it"},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "otc_1", "name": "run_vmd_command",
         "input": {"command": "mol new 1hck.pdb"}},
    ]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "otc_1", "content": "ok", "is_error": False},
    ]},
]


@pytest.fixture(autouse=True)
def _clear_no_think_memo():
    claude_loop._NO_THINK.clear()
    yield
    claude_loop._NO_THINK.clear()


def product(**options: Any) -> LoopOptions:
    return LoopOptions.product({"provider": "ollama", "base_url": BASE, "model": MODEL,
                                "options": dict(options)})


def chat_fake(*chat_replies) -> FakeHttp:
    """Healthy preflight plus the scripted /api/chat replies (default: DONE)."""
    fake = FakeHttp().ollama_ok(MODEL)
    for status, body in chat_replies or ((200, DONE),):
        fake.add("/api/chat", body, status=status,
                 content_type="application/x-ndjson" if status < 400 else "application/json")
    return fake


def stream(fake: FakeHttp, opts: Optional[LoopOptions], *, messages=None,
           meta: Optional[List[dict]] = None):
    with patch_urlopen(fake):
        return _stream_ollama(
            messages=messages or [{"role": "user", "content": "hi"}], model=MODEL,
            system_prompt="sys", base_url=BASE, timeout=30, on_text=lambda s: None,
            should_cancel=lambda: False,
            tools=_vmd_tools(include_search_docs=False, include_wiki=False),
            on_meta=meta.append if meta is not None else None, opts=opts,
        )


def test_profile_without_num_ctx_sends_32768():
    fake = chat_fake()
    stream(fake, product())
    assert fake.bodies("/api/chat")[0]["options"]["num_ctx"] == 32768


def test_profile_16384_sends_16384():
    fake = chat_fake()
    stream(fake, product(num_ctx=16384))
    assert fake.bodies("/api/chat")[0]["options"]["num_ctx"] == 16384


def test_options_none_sends_8192():
    fake = FakeHttp().add("/api/chat", DONE, content_type="application/x-ndjson")
    stream(fake, None)
    body = fake.bodies("/api/chat")[0]
    assert body["options"] == {"num_ctx": 8192}
    assert "think" not in body and "keep_alive" not in body
    assert fake.paths() == ["/api/chat"]


@pytest.mark.parametrize("value", [None, True, False])
def test_think_sent_only_when_set(value):
    fake = chat_fake()
    stream(fake, dataclasses.replace(product(), think=value))
    body = fake.bodies("/api/chat")[0]
    if value is None:
        assert "think" not in body
    else:
        assert body["think"] is value


def test_think_400_retries_once_without():
    fake = chat_fake((400, NO_THINKING), (200, DONE))
    meta: List[dict] = []
    text, _blocks = stream(fake, dataclasses.replace(product(), think=True), meta=meta)
    assert text == "ok"
    assert [("think" in body) for body in fake.bodies("/api/chat")] == [True, False]
    assert [m["phase"] for m in meta if m.get("phase") == "think_unsupported"] == ["think_unsupported"]
    # /api/ps runs before every /api/chat (spec 2f), the retry included;
    # /api/version is served once and then comes from the 30 s cache.
    assert fake.paths() == ["/api/version", "/api/ps", "/api/chat", "/api/ps", "/api/chat"]
    # The memo keeps later requests to this server and model from sending think.
    stream(fake, dataclasses.replace(product(), think=True))
    assert "think" not in fake.bodies("/api/chat")[-1]


def test_think_400_without_think_is_raised():
    fake = chat_fake((400, NO_THINKING))
    with pytest.raises(ClaudeLoopError):
        stream(fake, product())
    assert len(fake.bodies("/api/chat")) == 1


def test_think_fallback_never_on_options_none():
    fake = FakeHttp().add("/api/chat", NO_THINKING, status=400)
    with pytest.raises(ClaudeLoopError):
        stream(fake, None)
    assert len(fake.bodies("/api/chat")) == 1
    assert not claude_loop._NO_THINK


def test_keep_alive_top_level():
    fake = chat_fake()
    stream(fake, product(keep_alive="30m"))
    body = fake.bodies("/api/chat")[0]
    assert body["keep_alive"] == "30m"
    assert "keep_alive" not in body["options"]


def test_temperature_seed_from_opts_ignore_env(monkeypatch):
    monkeypatch.setenv("VMD_AI_TEMPERATURE", "0.9")
    monkeypatch.setenv("VMD_AI_SEED", "99")
    fake = chat_fake()
    stream(fake, product(temperature=0.2, seed=7))
    sent = fake.bodies("/api/chat")[0]["options"]
    assert (sent["temperature"], sent["seed"]) == (0.2, 7)

    fake = chat_fake()
    stream(fake, product())
    sent = fake.bodies("/api/chat")[0]["options"]
    assert "temperature" not in sent and "seed" not in sent

    fake = FakeHttp().add("/api/chat", DONE, content_type="application/x-ndjson")
    stream(fake, None)  # options=None keeps today's env reads
    assert fake.bodies("/api/chat")[0]["options"] == {"num_ctx": 8192, "temperature": 0.9, "seed": 99}


def test_tool_messages_carry_tool_name():
    assert _to_ollama_messages(TOOL_ROUND)[-1] == {
        "role": "tool", "tool_call_id": "otc_1", "content": "ok"}
    assert _to_ollama_messages(TOOL_ROUND, tool_name=True)[-1] == {
        "role": "tool", "tool_call_id": "otc_1", "content": "ok", "tool_name": "run_vmd_command"}
    fake = chat_fake()
    stream(fake, product(), messages=TOOL_ROUND)  # product() turns ollama_tool_name on
    assert fake.bodies("/api/chat")[0]["messages"][-1]["tool_name"] == "run_vmd_command"
