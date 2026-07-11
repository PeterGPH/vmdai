#!/usr/bin/env python3
"""test_hard_metrics.py — pure tests for the HARD-tier catalog + prompt builder (no VMD).
Run: python integrations/scivisagentbench/test_hard_metrics.py
"""
import re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hard_metrics import HARD_METRICS, HARD_INTENT, build_hard_prompt  # noqa: E402

GIVEAWAYS = ("rgyr", "gyration", "measure", "numframes", "rmsf", "rmsd", "sasa",
             "solvent-accessible", "radius of")


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    # 1. prompt strips every giveaway but keeps the plumbing
    p = build_hard_prompt("/x/a.pdb", "/x/a.dcd", HARD_METRICS["rg_std"][0], "/x/o.txt")
    low = p.lower()
    for tok in GIVEAWAYS:
        fails = check(tok not in low, f"prompt omits giveaway '{tok}'", fails)
    for plumb in ('mol new "/x/a.pdb"', 'mol addfile "/x/a.dcd"', 'open "/x/o.txt"'):
        fails = check(plumb in p, f"prompt keeps plumbing '{plumb}'", fails)

    # 2. every question string (not just rg_std) is giveaway-free
    for key, (question, tol, scored) in HARD_METRICS.items():
        ql = question.lower()
        bad = [t for t in GIVEAWAYS if t in ql]
        fails = check(not bad, f"question '{key}' giveaway-free (found {bad})", fails)
        fails = check(isinstance(tol, (int, float)) and tol > 0, f"'{key}' tol>0", fails)
        fails = check(scored is True, f"'{key}' scored", fails)

    # 3. catalog <-> intent parity + oracle key parity
    fails = check(set(HARD_METRICS) == set(HARD_INTENT), "HARD_METRICS/HARD_INTENT keys match", fails)
    oracle = (HERE / "gold_oracle_traj_hard.tcl").read_text()
    emitted = set(re.findall(r"emit\s+(\w+)", oracle))
    missing = set(HARD_METRICS) - emitted
    fails = check(not missing, f"oracle emits every scored key (missing {missing})", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
