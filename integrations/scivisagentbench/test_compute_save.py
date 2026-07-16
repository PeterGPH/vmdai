#!/usr/bin/env python3
"""test_compute_save.py — pure test of vmd_compute's save_path write + guided unbound-series error.
Drives the bridge's _compute directly (no VMD spawn — _compute is pure safe_eval + file write).
Run: python integrations/scivisagentbench/test_compute_save.py
"""
import os, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subprocess_vmd_bridge import SubprocessVmdBridge  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    b = SubprocessVmdBridge(vmd_bin="/bin/echo")   # constructs w/o VMD; _compute never spawns
    b._series = {"rgyr": [10.0, 11.0, 12.0, 9.0], "rmsd": [0.0, 1.0, 3.0, 2.0]}

    with tempfile.TemporaryDirectory() as d:
        ans = os.path.join(d, "sub", "answer.txt")   # nested dir exercises makedirs
        r = b._compute({"expression": "max(rmsd)", "save_path": ans})
        fails = check(r["ok"] and r["value"] == 3.0, "compute returns value", fails)
        fails = check(os.path.exists(ans) and open(ans).read().strip() == "3.0",
                      "save_path writes the exact computed value", fails)
        fails = check("written to" in r["output"], "note records the write", fails)

    r = b._compute({"expression": "max(rgyr)"})   # no save_path -> no file, unchanged
    fails = check(r["ok"] and r["value"] == 12.0, "no save_path still returns the value", fails)

    b._series = {"rgyr": [10.0, 11.0]}             # rmsd NOT bound
    r = b._compute({"expression": "max(rmsd)"})
    fails = check(not r["ok"], "unbound series -> ok False", fails)
    fails = check("rmsd_to_frame0" in r["error"] and "vmd_traj_series" in r["error"],
                  "unbound-series error names the fetch call + quantity", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
