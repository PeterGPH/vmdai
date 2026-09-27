"""P04-T03: reasoning and usage parsing (spec 2c Usage semantics, 2f Reasoning).

Reasoning deltas (Ollama message.thinking, OpenAI delta.reasoning_content or
delta.reasoning) reach on_meta and never on_text, so they cannot glue onto
the answer. Each streamer emits one usage item per turn; an unreported value
is None, never 0.
"""
from __future__ import annotations

from typing import List

from helpers.provider_fakes import FakeHttp, ndjson, patch_urlopen, run_loop, sse
from vmd_ai_runtime.claude_loop import (
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
    _stream_anthropic_direct,
    _stream_ollama,
    _stream_openrouter,
)

BASE = "http://ollama.test"
MODEL = "qwen3.8:27b"
NDJSON = "application/x-ndjson"
SSE = "text/event-stream"


def ollama(fake: FakeHttp, texts: List[str], metas: List[dict]):
    with patch_urlopen(fake):
        return _stream_ollama(
            messages=[{"role": "user", "content": "hi"}], model=MODEL, system_prompt="",
            base_url=BASE, timeout=30, on_text=texts.append, should_cancel=lambda: False,
            tools=[], on_meta=metas.append, opts=LoopOptions(),
        )


def openai(fake: FakeHttp, texts: List[str], metas: List[dict]):
    with patch_urlopen(fake):
        return _stream_openrouter(
            messages=[{"role": "user", "content": "hi"}], model="qwen3-32b", system_prompt="",
            api_key="k", timeout=30, on_text=texts.append, should_cancel=lambda: False,
            tools=[], on_meta=metas.append, opts=LoopOptions(),
        )


def kinds(metas: List[dict], kind: str) -> List[dict]:
    return [m for m in metas if m.get("kind") == kind]


def test_ollama_thinking_to_reasoning_not_text():
    fake = FakeHttp().add("/api/chat", ndjson([
        {"message": {"role": "assistant", "content": "", "thinking": "Let me "}},
        {"message": {"role": "assistant", "content": "", "thinking": "think."}},
        {"message": {"role": "assistant", "content": "Answer."}},
        {"done": True, "done_reason": "stop", "prompt_eval_count": 120, "eval_count": 9},
    ]), content_type=NDJSON)
    texts: List[str] = []
    metas: List[dict] = []
    text, blocks = ollama(fake, texts, metas)
    assert text == "Answer." and blocks == []
    assert texts == ["Answer."]
    assert [m["text"] for m in kinds(metas, "reasoning")] == ["Let me ", "think."]


def test_thinking_only_turn():
    fake = FakeHttp().add("/api/chat", ndjson([
        {"message": {"role": "assistant", "content": "", "thinking": "I should load it."}},
        {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_vmd_command", "arguments": {"command": "mol new 1hck.pdb"}}},
        ]}},
        {"done": True, "done_reason": "stop"},
    ]), content_type=NDJSON)
    texts: List[str] = []
    metas: List[dict] = []
    text, blocks = ollama(fake, texts, metas)
    assert text == ""
    assert texts == []
    assert [b["name"] for b in blocks] == ["run_vmd_command"]
    assert [m["text"] for m in kinds(metas, "reasoning")] == ["I should load it."]


def test_ollama_usage_prompt_eval_count():
    chat = ndjson([
        {"message": {"role": "assistant", "content": "Hi."}},
        {"done": True, "done_reason": "stop", "prompt_eval_count": 120, "eval_count": 9},
    ])
    fake = FakeHttp().add("/api/chat", chat, content_type=NDJSON)
    metas: List[dict] = []
    ollama(fake, [], metas)
    assert kinds(metas, "usage") == [{"kind": "usage", "input_tokens_evaluated": 120,
                                      "output_tokens": 9, "cache_read_tokens": None,
                                      "source": "ollama"}]

    events: List[dict] = []
    loop = ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=MODEL, options=LoopOptions())
    with patch_urlopen(fake):
        run_loop(loop, ctx=RunContext(request_id="req_1", chat_id="chat_000000000001",
                                      on_event=events.append))
    usage_events = [e for e in events if (e.get("metadata") or {}).get("kind") == "usage"]
    assert len(usage_events) == 1
    md = usage_events[0]["metadata"]
    assert (md["input_tokens_evaluated"], md["output_tokens"], md["source"]) == (120, 9, "ollama")
    assert md["request_id"] == "req_1"
    assert loop.last_usage == {"input_tokens_evaluated": 120, "output_tokens": 9}


def test_anthropic_usage_message_start_delta():
    stream = sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 1000, "cache_read_input_tokens": 200, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    ])
    fake = FakeHttp().add("/v1/messages", stream, content_type=SSE)
    metas: List[dict] = []
    with patch_urlopen(fake):
        text, _blocks = _stream_anthropic_direct(
            messages=[{"role": "user", "content": "hi"}], model="claude-sonnet-4-5",
            system_prompt="", api_key="k", timeout=30, on_text=lambda s: None,
            should_cancel=lambda: False, tools=[], on_meta=metas.append, opts=LoopOptions(),
        )
    assert text == "Hi"
    assert kinds(metas, "usage") == [{"kind": "usage", "input_tokens_evaluated": 1000,
                                      "output_tokens": 42, "cache_read_tokens": 200,
                                      "source": "anthropic"}]


def test_openai_final_chunk_usage_before_choices_skip():
    fake = FakeHttp().add("/api/v1/chat/completions", sse([
        {"choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 3,
                                  "prompt_tokens_details": {"cached_tokens": 10}}},
        "[DONE]",
    ]), content_type=SSE)
    texts: List[str] = []
    metas: List[dict] = []
    text, _blocks = openai(fake, texts, metas)
    assert text == "Hi"
    assert kinds(metas, "usage") == [{"kind": "usage", "input_tokens_evaluated": 40,
                                      "output_tokens": 3, "cache_read_tokens": 10,
                                      "source": "openai"}]


def test_openai_reasoning_content():
    fake = FakeHttp().add("/api/v1/chat/completions", sse([
        {"choices": [{"index": 0, "delta": {"reasoning_content": "a"}}]},
        {"choices": [{"index": 0, "delta": {"reasoning": "b"}}]},
        {"choices": [{"index": 0, "delta": {"content": "X"}, "finish_reason": "stop"}]},
        "[DONE]",
    ]), content_type=SSE)
    texts: List[str] = []
    metas: List[dict] = []
    text, _blocks = openai(fake, texts, metas)
    assert text == "X" and texts == ["X"]
    assert [m["text"] for m in kinds(metas, "reasoning")] == ["a", "b"]


def test_missing_usage_is_null():
    fake = FakeHttp().add("/api/chat", ndjson([
        {"message": {"role": "assistant", "content": "Hi."}},
        {"done": True, "done_reason": "stop"},
    ]), content_type=NDJSON)
    metas: List[dict] = []
    ollama(fake, [], metas)
    assert kinds(metas, "usage") == [{"kind": "usage", "input_tokens_evaluated": None,
                                      "output_tokens": None, "cache_read_tokens": None,
                                      "source": "ollama"}]
    loop = ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=MODEL, options=LoopOptions())
    with patch_urlopen(fake):
        run_loop(loop)
    assert loop.last_usage == {"input_tokens_evaluated": None, "output_tokens": None}

    fake = FakeHttp().add("/api/v1/chat/completions", sse([
        {"choices": [{"index": 0, "delta": {"content": "X"}, "finish_reason": "stop"}]},
        "[DONE]",
    ]), content_type=SSE)
    metas = []
    openai(fake, [], metas)
    assert kinds(metas, "usage") == [{"kind": "usage", "input_tokens_evaluated": None,
                                      "output_tokens": None, "cache_read_tokens": None,
                                      "source": "openai"}]
