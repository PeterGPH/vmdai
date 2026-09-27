"""P04-T04: OpenAI-compatible endpoints take base_url, extra_body and
include_usage from LoopOptions; environment variables are read only on the
options=None (benchmark) path (spec 2f)."""
from __future__ import annotations

from typing import Optional

import pytest

from helpers.provider_fakes import FakeHttp, patch_urlopen, sse
from vmd_ai_runtime.claude_loop import LoopOptions, _openai_chat_url, _stream_openrouter

BASE_V1 = "http://vllm.test:8000/v1"
CHAT_URL = "http://vllm.test:8000/v1/chat/completions"
ANSWER = sse([
    {"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}]},
    "[DONE]",
])


def openai_fake(path: str = "/v1/chat/completions") -> FakeHttp:
    return FakeHttp().add(path, ANSWER, content_type="text/event-stream")


def stream(fake: FakeHttp, opts: Optional[LoopOptions], *, api_key: str = "k") -> str:
    with patch_urlopen(fake):
        text, _blocks = _stream_openrouter(
            messages=[{"role": "user", "content": "hi"}], model="qwen3-32b", system_prompt="sys",
            api_key=api_key, timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
            tools=[], on_meta=None, opts=opts,
        )
    return text


def test_url_from_opts_ignores_env(monkeypatch):
    monkeypatch.setenv("VMD_AI_OPENAI_BASE_URL", "http://wrong.test:1/v1")
    fake = openai_fake()
    assert stream(fake, LoopOptions(base_url=BASE_V1)) == "ok"
    assert fake.requests[0]["url"] == CHAT_URL


@pytest.mark.parametrize("base", [
    BASE_V1, BASE_V1 + "/", BASE_V1 + "//", BASE_V1 + "/chat/completions", "  " + BASE_V1 + "/ ",
])
def test_base_url_join(base):
    assert _openai_chat_url(base) == CHAT_URL
    fake = openai_fake()
    stream(fake, LoopOptions(base_url=base))
    assert fake.requests[0]["url"] == CHAT_URL


def test_default_base_url_when_opts_has_none():
    fake = openai_fake("/api/v1/chat/completions")
    stream(fake, LoopOptions())
    assert fake.requests[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"


def test_extra_body_merged():
    fake = openai_fake()
    stream(fake, LoopOptions(
        base_url=BASE_V1, temperature=0.1, seed=3,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_k": 20,
                    "messages": "ignored", "stream": False},
    ))
    body = fake.bodies("/v1/chat/completions")[0]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["top_k"] == 20
    assert isinstance(body["messages"], list) and body["stream"] is True
    assert (body["temperature"], body["seed"]) == (0.1, 3)


def test_include_usage_opt_in():
    fake = openai_fake()
    stream(fake, LoopOptions(base_url=BASE_V1))
    assert "stream_options" not in fake.bodies("/v1/chat/completions")[0]

    fake = openai_fake()
    stream(fake, LoopOptions(base_url=BASE_V1, include_usage=True))
    assert fake.bodies("/v1/chat/completions")[0]["stream_options"] == {"include_usage": True}

    fake = openai_fake("/api/v1/chat/completions")
    stream(fake, None)
    assert "stream_options" not in fake.bodies("/api/v1/chat/completions")[0]


def test_empty_key_bearer_empty():
    fake = openai_fake()
    stream(fake, LoopOptions(base_url=BASE_V1), api_key="")
    assert fake.requests[0]["headers"]["Authorization"] == "Bearer EMPTY"

    fake = openai_fake("/api/v1/chat/completions")
    stream(fake, None, api_key="")
    assert fake.requests[0]["headers"]["Authorization"] == "Bearer "


def test_options_none_reads_env(monkeypatch):
    monkeypatch.setenv("VMD_AI_OPENAI_BASE_URL", "http://env.test:9000/v1/")
    fake = openai_fake()
    stream(fake, None)
    assert fake.requests[0]["url"] == "http://env.test:9000/v1/chat/completions"
