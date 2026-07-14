#!/usr/bin/env python3
"""test_workbench_wiring.py — pure checks for the workbench directive + transcript recording.
Run: python integrations/scivisagentbench/test_workbench_wiring.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tool_prompts import workbench_directive  # noqa: E402
from transcript_util import semantic_tool_transcript_entry  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    d = workbench_directive({})
    # the directive explains the loop but must NOT hand over the reduction (no metric/formula giveaways)
    for tok in ("vmd_traj_series", "vmd_compute"):
        fails = check(tok in d, f"directive names {tok}", fails)
    for giveaway in ("mean", "maximum", "std", "average", "radius of gyration"):
        fails = check(giveaway.lower() not in d.lower(), f"directive omits giveaway '{giveaway}'", fails)

    # vmd_traj_series has tcl -> recorded; vmd_compute has an expr -> recorded
    s = semantic_tool_transcript_entry("vmd_traj_series",
            {"ok": True, "output": "series 'rmsd' fetched", "tcl": 'mol new "x"\nputs "VMDAI_SERIES 1.0"'})
    fails = check(s is not None and "via vmd_traj_series" in s["cmd"], "series call recorded", fails)
    c = semantic_tool_transcript_entry("vmd_compute",
            {"ok": True, "output": "max(rmsd) = 3.0", "expr": "max(rmsd)"})
    fails = check(c is not None and "max(rmsd)" in c["cmd"], "compute call recorded (expr)", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
