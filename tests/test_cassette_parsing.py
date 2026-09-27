"""P04-T08: response parsing pinned by recorded and synthesized cassettes (C9).

Request bodies are pinned by the S7 goldens; these tests pin how responses
are parsed. Recorded cassettes come from a real Ollama, so every expectation
about their content is computed from the cassette itself.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import json
from typing import Any, Dict, List

import pytest

from helpers.cassette import load_cassette, play, use_cassette
from helpers.provider_fakes import RecordingBridge, run_loop, solid_png
from vmd_ai_runtime import claude_loop, provider_catalog
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    RunContext,
    _ollama_preflight,
    _stream_anthropic_direct,
    _stream_ollama,
    _stream_openrouter,
    _vmd_tools,
)

BASE = "http://ollama.test"
VLLM = "http://vllm.test:8000/v1"
TOOLS = _vmd_tools(include_search_docs=False, include_wiki=False)
LOAD = [{"role": "user", "content": "Load the local file 1hck.pdb into VMD."}]
PLAIN = [{"role": "user", "content": "In one short sentence, what does the VMD command `mol new` do?"}]


@pytest.fixture(autouse=True)
def _clear_no_think_memo():
    claude_loop._NO_THINK.clear()
    yield
    claude_loop._NO_THINK.clear()


def product(model: str, **overrides: Any) -> LoopOptions:
    opts = LoopOptions.product({"provider": "ollama", "base_url": BASE, "model": model, "options": {}})
    return dataclasses.replace(opts, **overrides)


def ollama_turn(cas: Dict[str, Any], messages: List[Dict[str, Any]], opts: LoopOptions):
    # Each recording started with cold caches, so each replay does too.
    provider_catalog.clear_caches()
    texts: List[str] = []
    metas: List[dict] = []
    with play(cas) as player:
        text, blocks = _stream_ollama(
            messages=messages, model=cas["meta"]["model"], system_prompt="sys", base_url=BASE,
            timeout=30, on_text=texts.append, should_cancel=lambda: False, tools=TOOLS,
            on_meta=metas.append, opts=opts,
        )
    return text, blocks, texts, metas, player


def openai_turn(cas: Dict[str, Any], opts: LoopOptions):
    texts: List[str] = []
    metas: List[dict] = []
    with play(cas):
        text, blocks = _stream_openrouter(
            messages=[{"role": "user", "content": "How many chains?"}], model=cas["meta"]["model"],
            system_prompt="sys", api_key="", timeout=30, on_text=texts.append,
            should_cancel=lambda: False, tools=TOOLS, on_meta=metas.append, opts=opts,
        )
    return text, blocks, texts, metas


def chat_lines(cas: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for ex in cas["exchanges"]:
        if ex["path"] == "/api/chat" and ex["status"] == 200:
            lines.extend(json.loads(line) for line in ex["body_lines"] if line.strip())
    return lines


def field(lines: List[Dict[str, Any]], key: str) -> str:
    return "".join(str((line.get("message") or {}).get(key) or "") for line in lines)


def usage_items(metas: List[dict]) -> List[dict]:
    return [m for m in metas if m.get("kind") == "usage"]


def test_reasoning_to_on_meta_only():
    cas = load_cassette("ollama", "thinking_tool_call")
    lines = chat_lines(cas)
    assert field(lines, "thinking"), "the recording must hold message.thinking"
    text, blocks, texts, metas, _player = ollama_turn(cas, LOAD, product(cas["meta"]["model"], think=True))
    assert "".join(m["text"] for m in metas if m.get("kind") == "reasoning") == field(lines, "thinking")
    assert "".join(texts) == field(lines, "content") == text
    assert blocks, "the recording holds a tool call"

    oa = load_cassette("openai-compatible", "reasoning_usage")
    text, _blocks, texts, metas = openai_turn(oa, LoopOptions(base_url=VLLM, include_usage=True))
    assert "".join(m["text"] for m in metas if m.get("kind") == "reasoning") == "The user asks for the chain count."
    assert text == "".join(texts) == "The structure has one chain."


def _drop_counts(line: str) -> str:
    if not line.strip():
        return line
    obj = json.loads(line)
    obj.pop("prompt_eval_count", None)
    obj.pop("eval_count", None)
    return json.dumps(obj)


def test_usage_null_when_absent():
    cas = load_cassette("ollama", "plain_answer")
    done = [line for line in chat_lines(cas) if line.get("done")][-1]
    opts = product(cas["meta"]["model"], think=False)
    metas = ollama_turn(cas, PLAIN, opts)[3]
    assert usage_items(metas) == [{"kind": "usage", "input_tokens_evaluated": done.get("prompt_eval_count"),
                                   "output_tokens": done.get("eval_count"), "cache_read_tokens": None,
                                   "source": "ollama"}]

    stripped = copy.deepcopy(cas)
    for ex in stripped["exchanges"]:
        if ex["path"] == "/api/chat":
            ex["body_lines"] = [_drop_counts(line) for line in ex["body_lines"]]
    metas = ollama_turn(stripped, PLAIN, opts)[3]
    assert usage_items(metas) == [{"kind": "usage", "input_tokens_evaluated": None, "output_tokens": None,
                                   "cache_read_tokens": None, "source": "ollama"}]

    oa = load_cassette("openai-compatible", "reasoning_usage")
    metas = openai_turn(oa, LoopOptions(base_url=VLLM, include_usage=True))[3]
    assert usage_items(metas) == [{"kind": "usage", "input_tokens_evaluated": 812, "output_tokens": 24,
                                   "cache_read_tokens": None, "source": "openai"}]
    no_usage = copy.deepcopy(oa)
    no_usage["exchanges"][0]["body_lines"] = [
        line for line in no_usage["exchanges"][0]["body_lines"] if '"usage"' not in line]
    metas = openai_turn(no_usage, LoopOptions(base_url=VLLM))[3]
    assert usage_items(metas) == [{"kind": "usage", "input_tokens_evaluated": None, "output_tokens": None,
                                   "cache_read_tokens": None, "source": "openai"}]


def test_ollama_tool_calls_parse():
    cas = load_cassette("ollama", "tool_call")
    expected = []
    for line in chat_lines(cas):
        for call in (line.get("message") or {}).get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                args = json.loads(args)
            expected.append((fn.get("name"), args))
    assert expected, "the recording holds at least one tool call"
    assert any(name == "run_vmd_command" for name, _args in expected)
    blocks = ollama_turn(cas, LOAD, product(cas["meta"]["model"], think=False))[1]
    assert [(b["name"], b["input"]) for b in blocks] == expected
    assert all(b["type"] == "tool_use" and b["id"] for b in blocks)


def test_truncated_tool_calls_not_run():
    cas = load_cassette("ollama", "truncated_tool_call")
    lines = chat_lines(cas)
    assert [line.get("done_reason") for line in lines if line.get("done")] == ["length"]
    model = cas["meta"]["model"]
    opts = product(model, think=False, max_turns=1, loop_guard=False, supports_vision=False)
    loop = ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=model, options=opts)
    bridge = RecordingBridge()
    events: List[dict] = []
    with play(cas):
        run_loop(loop, "Load 1hck.pdb, then set the background to white.", bridge=bridge,
                 ctx=RunContext(request_id="req_trunc", chat_id="chat_000000000001",
                                on_event=events.append))
    assert bridge.calls == []
    if field(lines, "tool_calls"):
        assert any((e.get("metadata") or {}).get("phase") == "turn_truncated" for e in events)


def test_model_not_found_hint_from_404():
    cas = load_cassette("ollama", "model_not_found")
    model = cas["meta"]["model"]
    error_text = json.loads(cas["exchanges"][-1]["body_lines"][0])["error"]
    with pytest.raises(ModelNotFoundError) as info:
        ollama_turn(cas, LOAD, product(model, think=False))
    exc = info.value
    assert exc.code == "model_not_found"
    assert exc.hint == f"ollama pull {model}"
    assert error_text in str(exc)
    assert not isinstance(exc, claude_loop.ProviderUnreachableError)


def test_think_400_fallback_once():
    cas = load_cassette("ollama", "think_unsupported")
    text, _blocks, _texts, metas, player = ollama_turn(cas, PLAIN, product(cas["meta"]["model"], think=True))
    assert text == "VMD loads molecules."
    chats = [r["body"] for r in player.requests if r["path"] == "/api/chat"]
    assert [("think" in body) for body in chats] == [True, False]
    assert len([m for m in metas if m.get("phase") == "think_unsupported"]) == 1


def test_sse_error_raises():
    cas = load_cassette("anthropic-direct", "usage_error")
    opts = LoopOptions.product({"provider": "anthropic-direct", "model": cas["meta"]["model"], "options": {}})

    def call(metas: List[dict]):
        return _stream_anthropic_direct(
            messages=[{"role": "user", "content": "hi"}], model=cas["meta"]["model"], system_prompt="sys",
            api_key="test-key", timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
            tools=TOOLS, on_meta=metas.append, opts=opts,
        )

    with use_cassette("anthropic-direct", "usage_error"):
        metas: List[dict] = []
        text, blocks = call(metas)
        assert (text, blocks) == ("Done.", [])
        assert usage_items(metas) == [{"kind": "usage", "input_tokens_evaluated": 1024, "output_tokens": 42,
                                       "cache_read_tokens": 256, "source": "anthropic"}]
        with pytest.raises(ClaudeLoopError):
            call([])


def test_rescue_json_only_offered_tools():
    cas = load_cassette("ollama", "rescue_json")
    model = cas["meta"]["model"]
    opts = product(model, think=False, supports_vision=False, loop_guard=False)
    loop = ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=model, options=opts)
    bridge = RecordingBridge()
    with play(cas):
        answer = run_loop(loop, "How do I make the background white?", bridge=bridge)
        assert bridge.calls == []  # S12: a fenced tcl block in prose never runs
        assert "color Display Background white" in answer
        _text, blocks = _stream_ollama(
            messages=[{"role": "user", "content": "Load 1hck.pdb"}], model=model, system_prompt="sys",
            base_url=BASE, timeout=30, on_text=lambda s: None, should_cancel=lambda: False,
            tools=TOOLS, on_meta=lambda item: None, opts=opts,
        )
    assert [(b["name"], b["input"]) for b in blocks] == [("run_vmd_command", {"command": "mol new 1hck.pdb"})]
    assert "mol delete all" not in json.dumps(blocks)
    assert "shell_exec" not in json.dumps(blocks)


def test_vision_turn_request_carries_images():
    cas = load_cassette("ollama", "vision_turn")
    b64 = base64.b64encode(solid_png(32, 24, (1, 2, 3))).decode("ascii")
    messages = [
        {"role": "user", "content": "Take a snapshot, then tell me what colour the beta strands are."},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "otc_1", "name": "capture_vmd_snapshot",
                                           "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "otc_1", "is_error": False,
                                      "content": [{"type": "text", "text": "Snapshot captured."},
                                                  {"type": "image", "source": {
                                                      "type": "base64", "media_type": "image/png",
                                                      "data": b64}}]}]},
    ]
    opts = product(cas["meta"]["model"], think=False, supports_vision=True)
    text, _blocks, texts, _metas, player = ollama_turn(cas, messages, opts)
    sent = [r["body"] for r in player.requests if r["path"] == "/api/chat"][0]["messages"]
    assert sent[-2]["role"] == "tool"
    assert sent[-1]["role"] == "user" and sent[-1]["images"] == [b64]
    assert text and text == "".join(texts) == field(chat_lines(cas), "content")


def test_preflight_parses_recorded_version_ps():
    cas = load_cassette("ollama", "version_ps")
    model = cas["meta"]["model"]
    running = json.loads(cas["exchanges"][1]["body_lines"][0]).get("models") or []
    loaded = [m for m in running if model in (m.get("name"), m.get("model"))]
    metas: List[dict] = []
    with use_cassette("ollama", "version_ps"):
        _ollama_preflight(BASE, model, product(model), metas.append)
    if loaded:
        assert metas == [{"kind": "model_digest", "value": loaded[0]["digest"]}]
    else:
        assert metas == [{"kind": "status", "phase": "loading_model", "message": f"Loading {model}…"}]
