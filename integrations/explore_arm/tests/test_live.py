"""Live tests: the lab surface against a REAL VMD interpreter (skip without the binary).

These prove the premise the arm rests on — the environment is self-documenting enough
to explore (errors are informative, wrong invocations reveal usage) — and that a
gate-approved lab_commit really executes end-to-end and writes files.
"""
import os

import pytest

from scaffold import LabProtocol
from explore_bridge import ExploreScaffoldBridge
from hostpaths import resolve_vmd

KNOWN_VMD = resolve_vmd()                # machine-resolved (Mac or GPU server)
pytestmark = pytest.mark.skipif(not KNOWN_VMD or not os.path.exists(KNOWN_VMD),
                                reason="VMD binary not present")


@pytest.fixture(scope="module")
def bridge():
    from subprocess_vmd_bridge import SubprocessVmdBridge
    inner = SubprocessVmdBridge(vmd_bin=KNOWN_VMD, timeout=60)
    b = ExploreScaffoldBridge(inner, LabProtocol(min_experiments=2))
    yield b
    b.close()


def test_live_lab_try_executes_real_tcl(bridge):
    r = bridge.execute_tool(tool_name="lab_try", tool_input={"code": "puts [expr 6*7]"})
    assert r["ok"] is True
    assert "42" in r["output"]


def test_live_lab_try_error_is_informative(bridge):
    r = bridge.execute_tool(tool_name="lab_try",
                            tool_input={"code": "definitely_not_a_command_xyz"})
    assert r["ok"] is False
    assert r["error"].strip()          # a real, readable error — the arm's documentation


def test_live_wrong_invocation_reveals_usage(bridge):
    # the self-documenting-environment premise: an under-specified call returns usage text
    r = bridge.execute_tool(tool_name="lab_try", tool_input={"code": "molinfo"})
    text = ((r.get("output") or "") + " " + (r.get("error") or "")).lower()
    assert "usage" in text or "molinfo" in text


def test_live_commit_after_protocol_writes_file(bridge, tmp_path):
    # self-sufficient protocol run: explore x2, note, verify, then commit
    bridge.execute_tool(tool_name="lab_try", tool_input={"code": "puts a"})
    bridge.execute_tool(tool_name="lab_try", tool_input={"code": "puts b"})
    bridge.execute_tool(tool_name="lab_note", tool_input={"text": "puts + open/close work"})
    bridge.execute_tool(tool_name="lab_try", tool_input={"code": "puts verify-ok"})
    out = tmp_path / "answer.txt"
    code = f'set f [open "{out}" w]; puts $f 3.14; close $f'
    r = bridge.execute_tool(tool_name="lab_commit", tool_input={"code": code})
    assert r["ok"] is True, r
    assert out.read_text().strip() == "3.14"
