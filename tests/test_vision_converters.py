"""P04-T05: snapshot images reach vision models only (S5, spec 2f Vision).

On the options path ClaudeToolLoop._call sends a per-call view of the
messages: images are downscaled to image_max_edge when the loop's resolved
vision is on and replaced by a text marker when it is off, whether they came
from this run's snapshot or from build_prior.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from helpers.provider_fakes import (
    FakeHttp,
    RecordingBridge,
    ndjson,
    patch_urlopen,
    run_loop,
    solid_png,
    sse,
)
from vmd_ai_runtime import image_scale, provider_catalog
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import (
    ClaudeToolLoop,
    LoopOptions,
    _to_ollama_messages,
    _to_openrouter_messages,
    resolve_supports_vision,
)
from vmd_ai_runtime.settings_store import SettingsStore

BASE = "http://ollama.test"
MODEL = "qwen3.8:27b"
TOKEN = "0123456789abcdef0123456789abcdef"
PNG = solid_png(64, 48, (10, 20, 30))
B64 = base64.b64encode(PNG).decode("ascii")
SNAP_ROUND = [
    {"role": "user", "content": "show me"},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "otc_1", "name": "capture_vmd_snapshot", "input": {}},
    ]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "otc_1", "is_error": False,
                                  "content": [
                                      {"type": "text", "text": "Snapshot captured."},
                                      {"type": "image", "source": {"type": "base64",
                                                                   "media_type": "image/png",
                                                                   "data": B64}},
                                  ]}]},
]
EARLIER_CHAT = SNAP_ROUND + [{"role": "assistant", "content": "It shows a cartoon of 1hck."}]
CALL_SNAPSHOT = ndjson([
    {"message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "capture_vmd_snapshot", "arguments": {}}}]}},
    {"done": True, "done_reason": "stop"},
])
ANSWER = ndjson([
    {"message": {"role": "assistant", "content": "A cartoon."}},
    {"done": True, "done_reason": "stop"},
])
ANTHROPIC_ANSWER = sse([
    {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Nothing new."}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
    {"type": "message_stop"},
])


def snapshot_fake(*, preflight: bool = True) -> FakeHttp:
    fake = FakeHttp().ollama_ok(MODEL) if preflight else FakeHttp()
    fake.add("/api/chat", CALL_SNAPSHOT, content_type="application/x-ndjson")
    fake.add("/api/chat", ANSWER, content_type="application/x-ndjson")
    return fake


def snapshot_bridge(png: bytes = PNG) -> RecordingBridge:
    return RecordingBridge([{"ok": True, "output": "Snapshot captured.", "error": "",
                             "image_b64": base64.b64encode(png).decode("ascii"),
                             "image_mime": "image/png"}])


def product_loop(**options: Any) -> ClaudeToolLoop:
    opts = LoopOptions.product({"provider": "ollama", "base_url": BASE, "model": MODEL,
                                "options": dict(options)})
    return ClaudeToolLoop(provider_name="ollama", api_key=BASE, model=MODEL, options=opts)


def show_with(*capabilities: str) -> Tuple[Any, List[Tuple[str, str, float]]]:
    calls: List[Tuple[str, str, float]] = []

    def show(base_url, model, timeout=3.0):
        calls.append((base_url, model, timeout))
        return {"capabilities": list(capabilities)}

    return show, calls


def test_ollama_images_after_tool_messages():
    out = _to_ollama_messages(SNAP_ROUND, include_images=True)
    assert out[-2] == {"role": "tool", "tool_call_id": "otc_1", "content": "Snapshot captured."}
    assert out[-1] == {"role": "user",
                       "content": "Snapshot from capture_vmd_snapshot (call otc_1).",
                       "images": [B64]}
    legacy = _to_ollama_messages(SNAP_ROUND)
    assert legacy[-1]["role"] == "tool" and "image not shown" in legacy[-1]["content"]
    assert not any("images" in m for m in legacy)


def test_openai_image_url_data_part():
    out = _to_openrouter_messages(SNAP_ROUND, include_images=True)
    assert out[-2]["role"] == "tool" and out[-2]["tool_call_id"] == "otc_1"
    assert out[-1] == {"role": "user", "content": [
        {"type": "text", "text": "Snapshot from capture_vmd_snapshot (call otc_1)."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
    ]}
    assert _to_openrouter_messages(SNAP_ROUND)[-1]["role"] == "tool"


def test_non_vision_profile_never_sends_image():
    fake = snapshot_fake()
    loop = product_loop(supports_vision=False)
    with patch_urlopen(fake):
        answer = run_loop(loop, "show me", bridge=snapshot_bridge())
    assert answer == "A cartoon."
    second = fake.bodies("/api/chat")[1]
    assert not any("images" in m for m in second["messages"])
    tool_messages = [m for m in second["messages"] if m["role"] == "tool"]
    assert "image not shown" in tool_messages[-1]["content"]
    assert B64 not in json.dumps(second)


def test_non_vision_strips_prior_images():
    opts = LoopOptions.product({"provider": "anthropic-direct", "model": "claude-sonnet-4-5",
                                "options": {"supports_vision": False}})
    loop = ClaudeToolLoop("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5", options=opts)
    fake = FakeHttp().add("/v1/messages", ANTHROPIC_ANSWER, content_type="text/event-stream")
    with patch_urlopen(fake):
        answer = run_loop(loop, "What did the snapshot show?", prior_messages=EARLIER_CHAT)
    assert answer == "Nothing new."
    sent = json.dumps(fake.bodies("/v1/messages")[0])
    assert B64 not in sent and '"type": "image"' not in sent
    assert "image not shown" in sent
    # The caller's history is never modified.
    assert EARLIER_CHAT[2]["content"][0]["content"][1]["type"] == "image"


def test_vision_profile_sends_image_after_tool_message():
    fake = snapshot_fake()
    loop = product_loop(supports_vision=True)
    with patch_urlopen(fake):
        run_loop(loop, "show me", bridge=snapshot_bridge())
    messages = fake.bodies("/api/chat")[1]["messages"]
    assert messages[-2]["role"] == "tool" and "image not shown" not in messages[-2]["content"]
    assert messages[-1]["role"] == "user" and messages[-1]["images"] == [B64]
    assert messages[-1]["content"].startswith("Snapshot from capture_vmd_snapshot (call ")


def test_vision_downscales_to_image_max_edge():
    fake = snapshot_fake()
    loop = product_loop(supports_vision=True)  # product(): image_max_edge 1024 for Ollama
    with patch_urlopen(fake):
        run_loop(loop, "show me", bridge=snapshot_bridge(solid_png(2048, 1536, (5, 6, 7))))
    sent = base64.b64decode(fake.bodies("/api/chat")[1]["messages"][-1]["images"][0])
    assert image_scale.png_size(sent) == (1024, 768)


def test_prior_image_resolves_auto_before_first_call(monkeypatch):
    show, calls = show_with("completion", "tools", "vision")
    monkeypatch.setattr(provider_catalog, "ollama_show", show)
    fake = FakeHttp().ollama_ok(MODEL).add("/api/chat", ANSWER, content_type="application/x-ndjson")
    loop = product_loop()  # supports_vision "auto", the product default for Ollama
    with patch_urlopen(fake):
        run_loop(loop, "What colour was it?", prior_messages=EARLIER_CHAT)
    first = fake.bodies("/api/chat")[0]["messages"]
    assert [m["images"] for m in first if m.get("images")] == [[B64]]
    # One /api/show, bounded by the 2 s preflight timeout.
    assert calls == [(BASE, MODEL, 2.0)]


def test_options_none_anthropic_only():
    assert ClaudeToolLoop("anthropic-direct", "k", "claude-sonnet-4-5")._vision_enabled() is True
    assert ClaudeToolLoop("ollama", BASE, MODEL)._vision_enabled() is False
    assert ClaudeToolLoop("openrouter", "k", "m")._vision_enabled() is False
    fake = snapshot_fake(preflight=False)
    loop = ClaudeToolLoop("ollama", BASE, MODEL)
    with patch_urlopen(fake):
        run_loop(loop, "show me", bridge=snapshot_bridge())
    second = fake.bodies("/api/chat")[1]
    assert not any("images" in m for m in second["messages"])
    assert "image not shown" in second["messages"][-1]["content"]


def test_auto_uses_show_capabilities(monkeypatch):
    assert resolve_supports_vision("ollama", "auto", {"vision": True, "tools": True}) is True
    assert resolve_supports_vision("ollama", "auto", {"vision": False}) is False
    assert resolve_supports_vision("ollama", "auto", None) is False
    assert resolve_supports_vision("anthropic-direct", None, None) is True
    assert resolve_supports_vision("anthropic-direct", "auto", None) is True
    assert resolve_supports_vision("ollama", None, {"vision": True}) is False
    assert resolve_supports_vision("openrouter", "auto", {"vision": True}) is False
    assert resolve_supports_vision("openai-compatible", "auto", {"vision": True}) is False
    assert resolve_supports_vision("openai-compatible", True, None) is True

    show, calls = show_with("completion", "tools", "vision")
    monkeypatch.setattr(provider_catalog, "ollama_show", show)
    loop = product_loop(supports_vision="auto")
    assert loop._vision_enabled() is True
    assert loop._vision_enabled() is True
    assert calls == [(BASE, MODEL, 2.0)]  # resolved once, then stored in loop.options
    assert loop.options.supports_vision is True

    show, _calls = show_with("completion", "tools")
    monkeypatch.setattr(provider_catalog, "ollama_show", show)
    assert product_loop(supports_vision="auto")._vision_enabled() is False

    def broken(base_url, model, timeout=3.0):
        raise OSError("server down")

    monkeypatch.setattr(provider_catalog, "ollama_show", broken)
    assert product_loop(supports_vision="auto")._vision_enabled() is False


def _rpc(app: RuntimeApp, method: str, params: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    reply = app.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                           session_token=token or "")
    assert "result" in reply, reply
    return reply["result"]


def test_runtime_info_vision_is_resolved(tmp_path, monkeypatch):
    show, _calls = show_with("completion", "tools", "vision")
    monkeypatch.setattr(provider_catalog, "ollama_show", show)
    store = SettingsStore()
    store.save_profile("qwen", {"provider": "ollama", "base_url": BASE, "model": MODEL,
                                "options": {"supports_vision": "auto"}}, activate=True)
    app = RuntimeApp(store_dir=str(tmp_path / "chats"), enable_rag=False, enable_wiki=False,
                     launch_token=TOKEN, allow_tokenless_v1=False, settings_store=store)
    started = _rpc(app, "session.start", {"cwd": str(tmp_path), "launch_token": TOKEN, "event_protocol": 1})
    info = _rpc(app, "runtime.info", {"session_id": started["session_id"]}, started["session_token"])
    assert info["vision"] is True
    assert RuntimeApp._vision_for(None) is False
    assert RuntimeApp._vision_for(ClaudeToolLoop("anthropic-direct", "k", "claude-sonnet-4-5")) is True
    assert RuntimeApp._vision_for(ClaudeToolLoop("ollama", BASE, MODEL)) is False
    blind = ClaudeToolLoop("ollama", BASE, MODEL, options=LoopOptions(supports_vision=False))
    assert RuntimeApp._vision_for(blind) is False
