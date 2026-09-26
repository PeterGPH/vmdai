"""S7 bridge guard (spec §2a "Bridge guard"): with options=None every bridge's
execute_tool receives exactly the six legacy keywords, and the adapter never
passes ctx or options.  P02-T08 adds the LoopOptions.product() variant here.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

import pytest

from helpers.fake_evaluation_framework import install as install_fake_framework
from helpers.golden import (
    TASK_PROMPT,
    TINY_PNG_B64,
    RecordingUrlopen,
    benchmark_config,
    scripted_responses,
)
from vmd_ai_runtime.claude_loop import ClaudeToolLoop

REPO = Path(__file__).resolve().parents[1]
SCIVIS_DIR = REPO / "integrations" / "scivisagentbench"
EXPLORE_DIR = REPO / "integrations" / "explore_arm"
SCRIPTS_DIR = REPO / "scripts"

LEGACY_KWARGS = frozenset(
    {"session_id", "tool_call_id", "tool_name", "tool_input", "session_queue", "cancel_event"}
)
SCRIPTED_TOOLS = ["run_vmd_command", "run_vmd_command", "capture_vmd_snapshot"]
_GOLDEN_PROVIDER = {
    "anthropic-direct": "anthropic",
    "openrouter": "openrouter_vllm",
    "ollama": "ollama",
}
_OK = {"ok": True, "output": "ok", "error": ""}
_SNAP = {"ok": True, "output": "snapshot", "error": "", "image_b64": TINY_PNG_B64,
         "image_mime": "image/png"}


def _on_path(*dirs: Path) -> None:
    for directory in dirs:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))


def spy_bridge(bridge: Any) -> Tuple[Any, List[Dict[str, Any]]]:
    """Record the keywords of every execute_tool call, then call the real method.

    The real (strict) signature still runs, so an extra keyword raises TypeError.
    """
    calls: List[Dict[str, Any]] = []
    original = bridge.execute_tool

    def execute_tool(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        assert args == (), f"positional arguments passed: {args!r}"
        calls.append(dict(kwargs))
        return original(**kwargs)

    bridge.execute_tool = execute_tool
    return bridge, calls


def run_guard(loop: ClaudeToolLoop, bridge: Any, *,
              requests_out: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Drive the scripted 3-turn run through ``loop`` against a spied ``bridge``."""
    spied, calls = spy_bridge(bridge)
    recorder = RecordingUrlopen(scripted_responses(_GOLDEN_PROVIDER[loop.provider_name]))
    with mock.patch("urllib.request.urlopen", recorder):
        loop.run(
            prompt=TASK_PROMPT,
            system_prompt="bridge guard",
            tool_bridge=spied,
            session_id="guard",
            session_queue=None,
            cancel_event=threading.Event(),
            on_chunk=lambda text: None,
        )
    assert recorder.unconsumed == 0
    if requests_out is not None:
        requests_out.extend(recorder.requests)
    return calls


def _anthropic_loop() -> ClaudeToolLoop:
    return ClaudeToolLoop(provider_name="anthropic-direct", api_key="sk-ant-guard",
                          model="claude-sonnet-4-5")


def _headless() -> Any:
    _on_path(SCIVIS_DIR)
    from headless_vmd_bridge import HeadlessVmdBridge

    bridge = HeadlessVmdBridge()
    bridge._run_tcl = lambda command: dict(_OK)
    bridge._snapshot = lambda purpose: dict(_SNAP)
    return bridge


def _rag_ab() -> Any:
    _on_path(SCRIPTS_DIR)
    return importlib.import_module("rag_ab")._StubBridge()


def _bench_wiki() -> Any:
    _on_path(SCRIPTS_DIR)
    return importlib.import_module("bench_wiki").StubToolBridge()


def _claude_loop_recorder_stub() -> Any:
    return importlib.import_module("test_claude_loop_recorder")._StubBridge()


def _recorder_integration_stub() -> Any:
    execute = importlib.import_module("test_recorder_integration")._stub_bridge_execute
    return type("RecorderIntegrationStub", (), {"execute_tool": execute})()


STRICT_BRIDGES: List[Tuple[str, Callable[[], Any]]] = [
    ("headless", _headless),
    ("rag_ab", _rag_ab),
    ("bench_wiki", _bench_wiki),
    ("claude_loop_recorder_stub", _claude_loop_recorder_stub),
    ("recorder_integration_stub", _recorder_integration_stub),
]


@pytest.mark.parametrize("name,factory", STRICT_BRIDGES, ids=[n for n, _ in STRICT_BRIDGES])
def test_strict_bridges_receive_six_keywords(name, factory):
    calls = run_guard(_anthropic_loop(), factory())
    assert [c["tool_name"] for c in calls] == SCRIPTED_TOOLS
    for call in calls:
        assert set(call) == LEGACY_KWARGS


def test_benchmark_chain_receives_six_keywords():
    _on_path(EXPLORE_DIR, SCIVIS_DIR)
    import subprocess_vmd_bridge as svb
    from explore_bridge import ExploreScaffoldBridge
    from retrieval_bridge import RetrievalAugmentingBridge
    from scaffold import LabProtocol

    with mock.patch.object(svb, "_resolve_vmd", return_value=("/nonexistent/vmd", None)):
        inner = svb.SubprocessVmdBridge(timeout=5)
    inner._start = lambda: None
    inner._run_tcl = lambda command: dict(_OK)
    inner._snapshot = lambda purpose, save_path=None: dict(_SNAP)
    inner, inner_calls = spy_bridge(inner)
    chain = ExploreScaffoldBridge(RetrievalAugmentingBridge(inner, docs_search=None),
                                  LabProtocol())

    outer_calls = run_guard(_anthropic_loop(), chain)
    assert [c["tool_name"] for c in outer_calls] == SCRIPTED_TOOLS
    assert [c["tool_name"] for c in inner_calls] == SCRIPTED_TOOLS
    for call in outer_calls + inner_calls:
        assert set(call) == LEGACY_KWARGS


def test_explore_tools_for_turn_zero_arg_lambda(tmp_path):
    install_fake_framework()
    _on_path(EXPLORE_DIR, SCIVIS_DIR)
    from explore_agent import ExploreAgent

    agent = ExploreAgent(benchmark_config("openrouter_vllm", "none", tmp_path))
    asyncio.run(agent.setup())
    assert "_tools_for_turn" in vars(agent._loop)  # the instance-level lambda
    lab_tools = ["lab_try", "lab_note", "lab_commit"]
    assert [t["name"] for t in agent._loop._tools_for_turn()] == lab_tools

    headless = agent._bridge.inner
    headless._run_tcl = lambda command: dict(_OK)
    headless._snapshot = lambda purpose: dict(_SNAP)
    requests: List[Dict[str, Any]] = []
    calls = run_guard(agent._loop, agent._bridge, requests_out=requests)
    assert [c["tool_name"] for c in calls] == SCRIPTED_TOOLS
    for request in requests:
        body = json.loads(request["body_text"])
        assert [t["function"]["name"] for t in body["tools"]] == lab_tools


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def test_adapter_never_passes_ctx_or_options():
    for path in (SCIVIS_DIR / "vmd_ai_agent.py", EXPLORE_DIR / "explore_agent.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                names = [kw.arg for kw in node.keywords]
                assert "ctx" not in names and "options" not in names, (
                    f"{path.name}:{node.lineno} passes ctx/options"
                )

    tree = ast.parse((SCIVIS_DIR / "vmd_ai_agent.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    ctor = [c for c in calls if _dotted(c.func) == "ClaudeToolLoop"]
    assert len(ctor) == 1
    assert [kw.arg for kw in ctor[0].keywords] == [
        "provider_name", "api_key", "model", "timeout", "docs_search", "wiki_store",
    ]
    runs = [c for c in calls if _dotted(c.func) == "self._loop.run"]
    assert len(runs) == 1
    assert [kw.arg for kw in runs[0].keywords] == [
        "prompt", "system_prompt", "tool_bridge", "session_id", "session_queue",
        "cancel_event", "on_chunk", "on_tool_start", "on_tool_result", "prior_messages",
    ]
