#!/usr/bin/env python3
"""test_anti_thrash.py — the brace-imbalance guard must, after REPEATED consecutive rejections,
redirect the model to the semantic tool instead of letting it thrash the whole budget (the
2erl meansasa=None failure mode: ~12 identical 'incomplete Tcl' rejections, no answer).

_run_tcl short-circuits on imbalance BEFORE touching VMD, so this needs no VMD binary.

  python integrations/scivisagentbench/test_anti_thrash.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subprocess_vmd_bridge import SubprocessVmdBridge  # noqa: E402

UNBALANCED = "for {set i 0} {$i < 3} {incr i} {"   # one unclosed '{' — guard rejects, no VMD needed


def _fresh_bridge():
    # bypass __init__ (which resolves a real VMD binary); we only exercise the pre-VMD guard.
    b = SubprocessVmdBridge.__new__(SubprocessVmdBridge)
    b._timeout = 45
    b._imbalance_streak = 0
    return b


def main():
    b = _fresh_bridge()
    fails = 0

    r1 = b._run_tcl(UNBALANCED)
    ok1 = (not r1.get("ok")) and "incomplete Tcl" in (r1.get("error") or "") \
        and "vmd_traj_measure" not in (r1.get("error") or "")
    fails += not ok1
    print(f"  [{'PASS' if ok1 else 'FAIL'}] 1st rejection: imbalance error, NO tool redirect yet")

    r2 = b._run_tcl(UNBALANCED)
    ok2 = (not r2.get("ok")) and "vmd_traj_measure" in (r2.get("error") or "")
    fails += not ok2
    print(f"  [{'PASS' if ok2 else 'FAIL'}] 2nd consecutive rejection: redirects to the semantic tool")

    r3 = b._run_tcl(UNBALANCED)
    ok3 = "vmd_traj_measure" in (r3.get("error") or "")
    fails += not ok3
    print(f"  [{'PASS' if ok3 else 'FAIL'}] 3rd rejection: still redirecting")

    print("ALL GOOD — anti-thrash redirect works." if not fails else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
