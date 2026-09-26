"""P02-T09: rescue modes all / json / off (§2f Rescue, S12)."""
from __future__ import annotations

import urllib.request

from helpers.fake_provider import FakeUrlopen, SpyBridge, ollama_text, run_loop
from vmd_ai_runtime.claude_loop import (
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
    _rescue_json_tool_calls,
)

CHAT_ID = "chat_0123456789ab"
ALLOWED = {"run_vmd_command", "capture_vmd_snapshot"}
TCL_PROSE = (
    "To load it in VMD you would run:\n\n"
    "```tcl\nmol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n```\n\n"
    "That shows the cartoon."
)
JSON_CALL = '{"name": "run_vmd_command", "arguments": {"command": "mol new 1hck.pdb"}}'


def _product_loop():
    profile = {"provider": "ollama", "model": "qwen3.8:27b", "base_url": "http://ollama.test"}
    return ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b",
                          options=LoopOptions.product(profile))


def _started(events):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == "tool.started"]


def test_json_mode_ignores_fenced_tcl(monkeypatch):
    """S12: a prose answer with a ```tcl block runs nothing in the product."""
    fake = FakeUrlopen([ollama_text(TCL_PROSE)])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    events, bridge = [], SpyBridge()
    loop = _product_loop()
    assert loop.options.rescue == "json"
    out = run_loop(loop, prompt="how do I load 1hck?", bridge=bridge,
                   ctx=RunContext("req_s12", CHAT_ID, on_event=events.append))
    assert out == TCL_PROSE  # the answer is kept as prose
    assert bridge.calls == []  # nothing reached VMD, so no tool_start was pushed
    assert _started(events) == []
    assert len(fake.chat_requests) == 1
    assert _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="json") == []


def test_json_mode_rescues_offered_tool_json(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        FakeUrlopen([ollama_text(JSON_CALL), ollama_text("Loaded.")]))
    events, bridge = [], SpyBridge()
    out = run_loop(_product_loop(), bridge=bridge,
                   ctx=RunContext("req_json", CHAT_ID, on_event=events.append))
    assert out == "Loaded."
    assert [c["tool_input"] for c in bridge.calls] == [{"command": "mol new 1hck.pdb"}]
    assert [s["origin"] for s in _started(events)] == ["rescued"]
    blocks = _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="json")
    assert [(b["name"], b["input"]) for b in blocks] == [
        ("run_vmd_command", {"command": "mol new 1hck.pdb"})]


def test_json_mode_rejects_unknown_tool():
    unknown = '{"name": "delete_everything", "arguments": {"path": "/"}}'
    assert _rescue_json_tool_calls(unknown, ALLOWED, mode="json") == []
    mixed = "```json\n" + unknown + "\n```\n```tcl\nfile delete -force ~/data\n```"
    assert _rescue_json_tool_calls(mixed, ALLOWED, mode="json") == []
    # The same text in "all" mode would run the Tcl block: that is why the
    # product uses "json".
    assert _rescue_json_tool_calls(mixed, ALLOWED, mode="all")[0]["input"] == {
        "command": "file delete -force ~/data"}


def test_off_mode(monkeypatch):
    assert _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="off") == []
    assert _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="off") == []
    monkeypatch.setattr(urllib.request, "urlopen", FakeUrlopen([ollama_text(JSON_CALL)]))
    bridge = SpyBridge()
    loop = ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b",
                          options=LoopOptions(rescue="off"))
    assert run_loop(loop, bridge=bridge) == JSON_CALL
    assert bridge.calls == []


def test_all_mode_unchanged(monkeypatch):
    default = _rescue_json_tool_calls(TCL_PROSE, ALLOWED)
    assert default == _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="all")
    assert default == [{"type": "tool_use", "id": "", "name": "run_vmd_command",
                        "input": {"command": "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon"}}]
    assert (_rescue_json_tool_calls(JSON_CALL, ALLOWED)
            == _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="all"))

    # Plan-01 carry-forward (S7): with options=None and ctx=None (the
    # benchmark path) the fenced ```tcl rescue (pass 2) still fires end to
    # end through run() and reaches the bridge.
    fake = FakeUrlopen([ollama_text(TCL_PROSE), ollama_text("Done.")])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    bridge = SpyBridge()
    legacy = ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b")
    assert legacy.options is None
    assert run_loop(legacy, prompt="how do I load 1hck?", bridge=bridge) == "Done."
    assert [(c["tool_name"], c["tool_input"]) for c in bridge.calls] == [
        ("run_vmd_command", {"command": "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon"})]
    assert len(fake.chat_requests) == 2
