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

    fails += test_select_mode()
    fails += test_recommend_tol()

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


def test_select_mode():
    import run_atlas_traj as R
    fails = 0
    m_e, b_e, o_e = R.select_mode(False)
    fails = check(m_e is R.METRICS and b_e is R.build_prompt, "easy mode -> METRICS/build_prompt", fails)
    fails = check(o_e == R.ORACLE, "easy mode -> easy oracle", fails)
    m_h, b_h, o_h = R.select_mode(True)
    fails = check(set(m_h) == set(R_hard_keys()), "hard mode -> HARD_METRICS", fails)
    fails = check(str(o_h).endswith("gold_oracle_traj_hard.tcl"), "hard mode -> hard oracle", fails)
    return fails


def R_hard_keys():
    from hard_metrics import HARD_METRICS
    return set(HARD_METRICS)


def test_recommend_tol():
    from calibrate_hard import recommend_tol
    fails = 0
    # 3% of the median (11.0) = 0.33, above the floor -> 0.33
    fails = check(abs(recommend_tol([10.0, 11.0, 12.0], frac=0.03, floor=0.1) - 0.33) < 1e-9,
                  "recommend_tol scales with median", fails)
    # floor dominates when the fraction is tiny
    fails = check(recommend_tol([10.0, 11.0, 12.0], frac=0.0, floor=0.5) == 0.5,
                  "recommend_tol respects the floor", fails)
    fails = check(recommend_tol([], floor=0.7) == 0.7, "recommend_tol handles empty -> floor", fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(main())
