"""C4: the repeat detector (runtime/vmd_ai_runtime/loop_guard.py)."""
from __future__ import annotations

from vmd_ai_runtime.loop_guard import NUDGE_TEXT_TEMPLATE, LoopGuard, signature

FAIL = {"ok": False, "output": "", "error": "invalid command name \"mol_color\""}
OK = {"ok": True, "output": "0 1 2", "error": ""}


def cmd(text, rationale="r"):
    return {"command": text, "rationale": rationale}


def test_three_different_mol_never_trigger():
    g = LoopGuard()
    for text in ("mol new a.pdb", "mol delrep 0 top", "mol addrep top"):
        assert g.observe("run_vmd_command", cmd(text), FAIL) is None
    assert g.streak == 1


def test_three_identical_failures_nudge_fourth_stops():
    g = LoopGuard()
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "nudge"
    assert g.streak == 3
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "stop"


def test_four_identical_successes_nudge():
    g = LoopGuard()
    verdicts = [g.observe("run_vmd_command", cmd("molinfo list"), OK) for _ in range(5)]
    assert verdicts == [None, None, None, "nudge", "stop"]


def test_snapshot_exempt_from_b():
    g = LoopGuard()
    snap = {"ok": True, "output": "Snapshot rendered", "error": ""}
    verdicts = [g.observe("capture_vmd_snapshot", {"purpose": "check"}, snap) for _ in range(6)]
    assert verdicts == [None] * 6
    bad = {"ok": False, "output": "", "error": "render failed"}
    verdicts = [g.observe("capture_vmd_snapshot", {"purpose": "check"}, bad) for _ in range(3)]
    assert verdicts == [None, None, "nudge"]


def test_different_call_resets():
    g = LoopGuard()
    g.observe("run_vmd_command", cmd("mol_color x"), FAIL)
    g.observe("run_vmd_command", cmd("mol_color x"), FAIL)
    assert g.observe("run_vmd_command", cmd("mol new a.pdb"), OK) is None
    assert g.streak == 1
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "nudge"


def test_same_command_different_output_resets_b():
    g = LoopGuard()
    for _ in range(3):
        g.observe("run_vmd_command", cmd("molinfo top"), OK)
    other = {"ok": True, "output": "3", "error": ""}
    assert g.observe("run_vmd_command", cmd("molinfo top"), other) is None
    assert g.streak == 1


def test_blocked_exec_curl_triggers_a():
    blocked = {
        "ok": False, "output": "", "executed": "no",
        "error": "Not run: `exec` is never run by ChatVMD. If the user needs it, show the "
                 "command in a tcl code block so they can copy it and run it in the VMD "
                 "console themselves.",
        "blocked": [{"id": "cmd_exec", "word": "exec", "text": "exec curl -O x"}],
    }
    g = LoopGuard()
    got = [g.observe("run_vmd_command",
                     cmd("exec curl -O https://files.rcsb.org/download/1hck.pdb"), blocked)
           for _ in range(3)]
    assert got == [None, None, "nudge"]


def test_signature_ignores_rationale_whitespace():
    a = signature("run_vmd_command",
                  {"command": "mol new  a.pdb\n\tmol delrep 0 top", "rationale": "x"}, FAIL)
    b = signature("run_vmd_command",
                  {"command": "mol new a.pdb mol delrep 0 top ", "rationale": "other"}, FAIL)
    assert a == b
    g = LoopGuard()
    g.observe("run_vmd_command", {"command": "mol_color  x", "rationale": "one"}, FAIL)
    g.observe("run_vmd_command", {"command": "mol_color x\n", "rationale": "two"}, FAIL)
    assert g.observe("run_vmd_command", {"command": " mol_color x"}, FAIL) == "nudge"


def test_signature_uses_first_200_error_chars():
    e1 = dict(FAIL, error="E" * 200 + "tail-one")
    e2 = dict(FAIL, error="E" * 200 + "tail-two")
    assert signature("t", {}, e1) == signature("t", {}, e2)


def test_nudge_text():
    assert NUDGE_TEXT_TEMPLATE.format(n=3) == (
        "Loop check: this exact call has now run 3 times with the same result. "
        "Do not repeat it; change the command, or stop and explain the problem to the user."
    )
