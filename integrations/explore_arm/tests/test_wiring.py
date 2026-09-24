"""TDD tests for the explore-arm wiring: the bridge wrapper (with a fake inner bridge),
the agent's tool surface, and the runner's registry/prompt hooks."""
import asyncio
import os
from pathlib import Path

import pytest

from scaffold import EXPLORE_DIRECTIVE, LabProtocol
from explore_bridge import ExploreScaffoldBridge
from hostpaths import resolve_vmd

HERE = Path(__file__).resolve().parent.parent            # integrations/explore_arm
VMD_AI = HERE.parent.parent                              # vmd_ai/
KNOWN_VMD = resolve_vmd()                                # machine-resolved (Mac or GPU server)

# the real anti-thrash suffix the shared bridge appends after repeated imbalance errors
STEER = (" You have hit this repeatedly — STOP hand-writing this loop and call "
         "vmd_traj_measure (over-all-frames) or vmd_measure (single value) instead; "
         "they run the correct, brace-balanced Tcl for you.")


class FakeInnerBridge:
    """Records execute_tool calls; returns per-tool canned results (a list pops in order)."""

    def __init__(self, responses=None):
        self.calls = []
        self.resets = 0
        self.closed = 0
        self._responses = dict(responses or {})

    def execute_tool(self, *, tool_name="", tool_input=None, **_):
        self.calls.append((tool_name, dict(tool_input or {})))
        r = self._responses.get(tool_name)
        if isinstance(r, list):
            return dict(r.pop(0)) if r else {"ok": True, "output": "ok", "error": ""}
        if isinstance(r, dict):
            return dict(r)
        return {"ok": True, "output": "fake-ok", "error": ""}

    def reset(self):
        self.resets += 1

    def close(self):
        self.closed += 1


def _bridge(min_experiments=2, max_experiments=15, responses=None):
    inner = FakeInnerBridge(responses)
    b = ExploreScaffoldBridge(inner, LabProtocol(min_experiments=min_experiments,
                                                 max_experiments=max_experiments))
    return b, inner


# ------------------------------------------------------------------ bridge routing
def test_lab_try_routes_to_inner_run_vmd_command():
    b, inner = _bridge()
    res = b.execute_tool(tool_name="lab_try", tool_input={"code": "puts 1"})
    assert inner.calls == [("run_vmd_command", {"command": "puts 1"})]
    assert res["ok"] is True
    assert res["tcl"] == "puts 1"          # for transcript/failure artifacts


def test_lab_try_appends_loop_breaker_guidance_on_repeated_error():
    err = {"ok": False, "output": "", "error": "bad option"}
    b, _ = _bridge(responses={"run_vmd_command": [dict(err), dict(err)]})
    r1 = b.execute_tool(tool_name="lab_try", tool_input={"code": "x"})
    r2 = b.execute_tool(tool_name="lab_try", tool_input={"code": "x"})
    assert "DIFFERENT hypothesis" not in r1["error"]
    assert "DIFFERENT hypothesis" in r2["error"]


def test_lab_try_sanitizes_domain_tool_steering():
    err = {"ok": False, "output": "", "error": "incomplete Tcl — unbalanced." + STEER}
    b, _ = _bridge(responses={"run_vmd_command": dict(err)})
    r = b.execute_tool(tool_name="lab_try", tool_input={"code": "for {"})
    assert "vmd_traj_measure" not in r["error"]
    assert "vmd_measure" not in r["error"]
    assert "incomplete Tcl" in r["error"]


def test_lab_note_records_without_inner_call():
    b, inner = _bridge()
    r = b.execute_tool(tool_name="lab_note", tool_input={"text": "fact A"})
    assert r["ok"] is True and "1 note" in r["output"]
    assert inner.calls == []


def test_lab_commit_refused_before_protocol_and_inner_not_called():
    b, inner = _bridge(min_experiments=2)
    r = b.execute_tool(tool_name="lab_commit", tool_input={"code": "final"})
    assert r["ok"] is False
    assert "COMMIT REJECTED" in r["error"]
    assert inner.calls == []               # the final code did NOT run


def test_lab_commit_refusal_echoes_notes():
    b, _ = _bridge(min_experiments=5)
    b.execute_tool(tool_name="lab_try", tool_input={"code": "a"})
    b.execute_tool(tool_name="lab_note", tool_input={"text": "syntax Z works"})
    r = b.execute_tool(tool_name="lab_commit", tool_input={"code": "final"})
    assert r["ok"] is False and "syntax Z works" in r["error"]


def test_lab_commit_executes_after_full_protocol():
    b, inner = _bridge(min_experiments=2)
    b.execute_tool(tool_name="lab_try", tool_input={"code": "a"})
    b.execute_tool(tool_name="lab_try", tool_input={"code": "b"})
    b.execute_tool(tool_name="lab_note", tool_input={"text": "n"})
    b.execute_tool(tool_name="lab_try", tool_input={"code": "verify"})
    r = b.execute_tool(tool_name="lab_commit", tool_input={"code": "final code"})
    assert r["ok"] is True
    assert inner.calls[-1] == ("run_vmd_command", {"command": "final code"})
    assert b.protocol.commits == 1
    assert r["tcl"] == "final code"


def test_run_vmd_command_is_aliased_to_lab_try():
    b, inner = _bridge()
    b.execute_tool(tool_name="run_vmd_command", tool_input={"command": "puts 2"})
    assert b.protocol.experiments == 1
    assert inner.calls == [("run_vmd_command", {"command": "puts 2"})]


def test_reset_clears_protocol_and_forwards():
    b, inner = _bridge(min_experiments=1)
    b.execute_tool(tool_name="lab_try", tool_input={"code": "a"})
    b.reset()
    assert inner.resets == 1
    assert b.protocol.experiments == 0


def test_unknown_tool_delegates_to_inner():
    b, inner = _bridge()
    b.execute_tool(tool_name="vmd_compute", tool_input={"expression": "max(x)"})
    assert inner.calls == [("vmd_compute", {"expression": "max(x)"})]


# ------------------------------------------------------------------- agent surface
def _agent_config():
    return {
        "provider": "vllm",
        "model": "test-model",
        "base_url": "http://localhost:9",     # never contacted during setup
        "api_key": "test-key",
        "vmd_ai_runtime_path": str(VMD_AI / "runtime"),
        "vmd_backend": "subprocess",
        "vmd_bin": KNOWN_VMD,
        "explore_min_experiments": 2,
        "explore_max_experiments": 9,
    }


def _explore_agent_cls():
    pytest.importorskip("evaluation_framework",
                        reason="SciVisAgentBench framework not importable")
    from explore_agent import ExploreAgent
    return ExploreAgent


@pytest.mark.skipif(not KNOWN_VMD or not os.path.exists(KNOWN_VMD),
                    reason="VMD binary not present")
def test_agent_setup_surface_and_prompt():
    ExploreAgent = _explore_agent_cls()
    agent = ExploreAgent(_agent_config())
    asyncio.run(agent.setup())
    try:
        names = [t.get("name") for t in agent._loop._tools_for_turn()]
        assert "run_vmd_command" not in names
        assert "capture_vmd_snapshot" not in names
        assert names[-3:] == ["lab_try", "lab_note", "lab_commit"]
        assert "run_vmd_command" not in agent._system_prompt
        assert EXPLORE_DIRECTIVE in agent._system_prompt
        assert isinstance(agent._bridge, ExploreScaffoldBridge)
        assert agent._bridge.protocol.min_experiments == 2
        assert agent._bridge.protocol.max_experiments == 9
    finally:
        asyncio.run(agent.teardown())


# --------------------------------------------------------------------- runner hooks
def test_registry_override_installs_explore_agent():
    pytest.importorskip("evaluation_framework",
                        reason="SciVisAgentBench framework not importable")
    from run_explore import install_explore_agent
    from explore_agent import ExploreAgent
    cls = install_explore_agent()
    from evaluation_framework.agent_registry import get_agent
    assert cls is ExploreAgent
    assert get_agent("vmd_ai") is ExploreAgent


def test_explore_build_prompt_retargets_tool_mentions():
    from run_explore import explore_build_prompt
    out = explore_build_prompt("/tmp/x.pdb", "/tmp/x.dcd", "the answer phrase", "/tmp/ans.txt")
    assert "run_vmd_command" not in out
    assert "lab_try" in out
    assert "the answer phrase" in out
    assert "/tmp/ans.txt" in out
