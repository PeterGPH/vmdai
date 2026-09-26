"""P02-T05: LoopOptions, RunContext, error classes and options plumbing (§2a, C6, C7)."""
from __future__ import annotations

import dataclasses
import json
from unittest import mock

import pytest

from helpers.fake_provider import run_loop, scripted_call
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    ProviderAuthError,
    ProviderBillingError,
    ProviderUnreachableError,
    RunContext,
)

FIELD_ORDER = [
    "num_ctx", "think", "keep_alive", "extra_body", "include_usage", "base_url",
    "temperature", "seed", "context_length", "connect_retries", "classify_unreachable",
    "classify_errors", "preflight", "first_byte_timeout_s", "cancellable_backoff",
    "report_cancelled", "turn_retry", "raise_stream_errors", "guard_truncation",
    "compact_in_run", "rescue", "tool_overrides", "supports_vision", "image_max_edge",
    "ollama_tool_name", "max_turns", "loop_guard", "result_format",
]
BOOL_FLAGS = ("include_usage", "classify_unreachable", "classify_errors", "preflight",
              "cancellable_backoff", "report_cancelled", "raise_stream_errors",
              "guard_truncation", "compact_in_run", "ollama_tool_name", "loop_guard")
NONE_FIELDS = ("num_ctx", "think", "keep_alive", "extra_body", "base_url", "temperature",
               "seed", "context_length", "connect_retries", "first_byte_timeout_s",
               "tool_overrides", "supports_vision", "image_max_edge")
STREAMER_KWARGS = {"messages", "model", "system_prompt", "timeout", "on_text",
                   "should_cancel", "tools"}
CHAT_ID = "chat_0123456789ab"


def test_defaults_match_today():
    assert [f.name for f in dataclasses.fields(LoopOptions)] == FIELD_ORDER
    opts = LoopOptions()
    for name in BOOL_FLAGS:
        assert getattr(opts, name) is False, name
    for name in NONE_FIELDS:
        assert getattr(opts, name) is None, name
    assert opts.turn_retry == 0
    assert opts.rescue == "all"
    assert opts.result_format == "legacy"
    assert opts.max_turns == ClaudeToolLoop.MAX_TURNS == 28
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m")
    assert loop.options is None and loop._ctx is None and loop._tool_mode is None


def test_product_ollama_preset():
    opts = LoopOptions.product({"provider": "ollama", "model": "qwen3.8:27b",
                                "base_url": "http://127.0.0.1:11435"})
    assert opts.num_ctx == 32768  # C7: the profile set no num_ctx
    assert opts.connect_retries == 0
    assert opts.preflight is True
    assert opts.first_byte_timeout_s == 120
    assert opts.image_max_edge == 1024
    assert opts.ollama_tool_name is True
    assert opts.rescue == "json"
    assert opts.result_format == "structured"
    assert opts.loop_guard is True
    assert opts.turn_retry == 1
    for name in ("classify_unreachable", "classify_errors", "cancellable_backoff",
                 "report_cancelled", "raise_stream_errors", "guard_truncation",
                 "compact_in_run"):
        assert getattr(opts, name) is True, name
    assert opts.supports_vision == "auto"
    assert opts.base_url == "http://127.0.0.1:11435"
    assert opts.max_turns == 28
    assert LoopOptions.product({"provider": "ollama"}, max_turns=12).max_turns == 12


def test_product_profile_options_override():
    profile = {"provider": "ollama", "model": "m",
               "options": {"num_ctx": 16384, "rescue": "all", "loop_guard": False,
                           "think": True, "bogus_key": 1, "max_turns": 5}}
    opts = LoopOptions.product(profile, max_turns=20)
    assert opts.num_ctx == 16384
    assert opts.rescue == "all"
    assert opts.loop_guard is False
    assert opts.think is True
    assert not hasattr(opts, "bogus_key")
    assert opts.max_turns == 20  # the max_turns setting wins over a profile key
    assert LoopOptions.product({"provider": "ollama", "options": {"num_ctx": None}}).num_ctx == 32768


def test_product_non_ollama():
    claude = LoopOptions.product({"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    assert claude.connect_retries == 1
    assert claude.preflight is False
    assert claude.num_ctx is None
    assert claude.first_byte_timeout_s is None
    assert claude.ollama_tool_name is False
    assert claude.image_max_edge == 1568
    assert claude.rescue == "json"
    assert claude.supports_vision == "auto"
    vllm = LoopOptions.product({"provider": "openai-compatible", "model": "m",
                                "base_url": "http://localhost:8000/v1"})
    assert vllm.supports_vision is False  # manual toggle, off by default (§2f)
    assert vllm.image_max_edge == 1024
    assert vllm.base_url == "http://localhost:8000/v1"
    assert vllm.connect_retries == 1


def test_asdict_json_serialisable():
    opts = LoopOptions.product({"provider": "ollama", "model": "m",
                                "options": {"extra_body": {"a": [1, 2]}, "keep_alive": "30m"}})
    data = opts.to_dict()
    assert data == dataclasses.asdict(opts)
    json.dumps(data)
    assert LoopOptions.from_dict(data) == opts
    assert LoopOptions.from_dict({"rescue": "off", "unknown": 1}) == LoopOptions(rescue="off")
    assert LoopOptions.from_dict(None) == LoopOptions()


def test_error_subclasses():
    cases = [(ClaudeLoopError, "other"), (ProviderUnreachableError, "unreachable"),
             (ProviderAuthError, "auth"), (ProviderBillingError, "billing"),
             (ModelNotFoundError, "model_not_found")]
    for cls, code in cases:
        exc = cls("API error HTTP 401: bad key", hint="Check the key", http_status=401)
        assert isinstance(exc, ClaudeLoopError) and isinstance(exc, RuntimeError)
        assert exc.code == code
        assert exc.hint == "Check the key"
        assert exc.http_status == 401
        assert str(exc) == "API error HTTP 401: bad key"
    plain = ClaudeLoopError("network error: refused")
    assert (plain.code, plain.hint, plain.http_status) == ("other", "", None)
    assert str(plain) == "network error: refused"


def _loops():
    return [
        ("_stream_anthropic_direct", ClaudeToolLoop("anthropic-direct", "sk-ant-x", "claude-sonnet-4-5"), "api_key"),
        ("_stream_ollama", ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b"), "base_url"),
        ("_stream_openrouter", ClaudeToolLoop("openrouter", "sk-or-x", "anthropic/claude-sonnet-4.6"), "api_key"),
    ]


def _call_once(target, loop):
    with mock.patch(f"vmd_ai_runtime.claude_loop.{target}", return_value=("t", [])) as fake:
        loop._call([{"role": "user", "content": "hi"}], "sys",
                   on_text=lambda chunk: None, should_cancel=lambda: False)
    return fake.call_args


def test_options_none_streamer_kwargs_exact():
    for target, loop, key_kw in _loops():
        call = _call_once(target, loop)
        assert call.args == ()
        assert set(call.kwargs) == STREAMER_KWARGS | {key_kw}, target


def test_options_set_streamer_kwargs():
    for target, loop, key_kw in _loops():
        loop.options = LoopOptions()
        call = _call_once(target, loop)
        assert set(call.kwargs) == STREAMER_KWARGS | {key_kw, "on_meta", "opts", "tool_mode"}, target
        assert call.kwargs["opts"] is loop.options
        assert call.kwargs["on_meta"] == loop._on_meta
        assert call.kwargs["tool_mode"] is None


def test_on_meta_enriches_and_forwards():
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m", options=LoopOptions())
    events = []
    loop._ctx = RunContext("req_9", CHAT_ID, on_event=events.append)
    loop._turn = 3
    loop._on_meta({"kind": "status", "phase": "retrying", "attempt": 1})
    loop._on_meta({"kind": "reasoning", "text": "hmm"})
    loop._on_meta({"kind": "stop_reason", "value": "max_tokens"})
    assert events == [
        {"role": "system", "type": "state", "text": "",
         "metadata": {"kind": "status", "phase": "retrying", "attempt": 1,
                      "request_id": "req_9", "turn": 3}},
        {"role": "reasoning", "type": "chunk", "text": "hmm",
         "metadata": {"request_id": "req_9", "turn": 3}},
    ]
    assert loop._turn_meta["stop_reason"] == {"kind": "stop_reason", "value": "max_tokens"}


def test_ctx_cleared_after_run_even_on_error():
    ctx = RunContext(request_id="req_1", chat_id=CHAT_ID)
    assert ctx.on_event is None and ctx.messages_out is None
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m", options=LoopOptions())
    seen = []

    def boom(messages, system_prompt, on_text, should_cancel):
        seen.append(loop._ctx)
        raise ClaudeLoopError("boom")

    loop._call = boom
    with pytest.raises(ClaudeLoopError, match="boom"):
        run_loop(loop, ctx=ctx)
    assert seen == [ctx]
    assert loop._ctx is None
    loop._call = scripted_call([("fine", [])])
    assert run_loop(loop, ctx=ctx) == "fine"
    assert loop._ctx is None
