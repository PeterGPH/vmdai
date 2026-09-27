"""Opt-in live tests against a real Ollama (spec 6 "Live tests", S5).

Skipped unless both live gates are set, for example:

    VMD_AI_LIVE_OLLAMA=http://127.0.0.1:11435 VMD_AI_LIVE_MODEL=qwen3.8:27b \
        python -m pytest tests/test_live_ollama.py -q

The gates are read only through the conftest's live_env fixture. A value of
VMD_AI_LIVE_OLLAMA that is not an http(s) URL means the default tunnel,
http://127.0.0.1:11435.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest import mock

import pytest

from helpers.provider_fakes import RecordingBridge, run_loop
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions
from vmd_ai_runtime.prompts import chatvmd_system_prompt

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO / "docs" / "design" / "round1" / "assets" / "snap_1hck.png"
URLOPEN_TARGET = "vmd_ai_runtime.claude_loop.urllib.request.urlopen"


def live_target(live_env: Dict[str, str]) -> Tuple[str, str]:
    base = str(live_env.get("VMD_AI_LIVE_OLLAMA") or "")
    model = str(live_env.get("VMD_AI_LIVE_MODEL") or "")
    if not base or not model:
        pytest.skip("set VMD_AI_LIVE_OLLAMA and VMD_AI_LIVE_MODEL to run the live Ollama tests")
    if not base.startswith(("http://", "https://")):
        base = "http://127.0.0.1:11435"
    return base.rstrip("/"), model


def live_loop(base: str, model: str, **options: Any) -> ClaudeToolLoop:
    opts = LoopOptions.product({"provider": "ollama", "base_url": base, "model": model,
                                "options": dict(options)})
    opts = dataclasses.replace(opts, max_turns=3, loop_guard=False)
    return ClaudeToolLoop(provider_name="ollama", api_key=base, model=model, options=opts)


def spy_urlopen(bodies: List[Dict[str, Any]]):
    real = urllib.request.urlopen

    def spy(req, timeout=None, **kwargs):
        data = getattr(req, "data", None)
        if data:
            try:
                bodies.append(json.loads(data))
            except Exception:
                pass
        return real(req, timeout=timeout, **kwargs)

    return spy


def test_live_tool_turn(live_env):
    base, model = live_target(live_env)
    loop = live_loop(base, model, supports_vision=False)
    bridge = RecordingBridge()
    run_loop(loop, "Load the local file 1hck.pdb into VMD with one run_vmd_command call, then stop.",
             bridge=bridge, system_prompt=chatvmd_system_prompt(False))
    commands = [call["tool_input"].get("command", "") for call in bridge.calls
                if call["tool_name"] == "run_vmd_command"]
    assert commands, f"no run_vmd_command call; calls were {bridge.calls!r}"
    assert any("1hck" in command.lower() for command in commands)


def test_live_vision_turn_snap_1hck(live_env):
    base, model = live_target(live_env)
    loop = live_loop(base, model, supports_vision="auto")
    assert loop._vision_enabled() is True, "the model must report the vision capability in /api/show"
    bridge = RecordingBridge([{
        "ok": True, "output": "Snapshot captured.", "error": "",
        "image_b64": base64.b64encode(SNAPSHOT.read_bytes()).decode("ascii"),
        "image_mime": "image/png",
    }])
    bodies: List[Dict[str, Any]] = []
    with mock.patch(URLOPEN_TARGET, new=spy_urlopen(bodies)):
        answer = run_loop(
            loop,
            "Call capture_vmd_snapshot once. Then, looking only at the returned image, answer in a "
            "few words: what colour are the arrow-shaped beta strands, and what colour are the helices?",
            bridge=bridge, system_prompt=chatvmd_system_prompt(True),
        )
    sent_images = [m for body in bodies for m in body.get("messages", []) if m.get("images")]
    assert sent_images, "no /api/chat request carried the snapshot"
    text = answer.lower()
    assert "yellow" in text, answer
    assert any(word in text for word in ("purple", "magenta", "violet")), answer
