#!/usr/bin/env python3
"""test_answer_audit.py — pure tests for the G-B1 parser-audit tool (no VMD, no LLM).

Run: python3 test_answer_audit.py   -> expects ALL GOOD
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from audit_answer_parser import audit_entry, parse_legacy, parse_strict, tolerance_for  # noqa: E402
from run_atlas_traj import _parse_answer  # noqa: E402


def check(cond, label, fails):
    print(("  [PASS] " if cond else "  [FAIL] ") + label)
    if not cond:
        fails.append(label)


def main():
    fails = []

    # ---- strict parser: exactly one numeric token, gold-blind ----
    check(parse_strict("13.52\n") == 13.52, "strict: bare single number", fails)
    check(parse_strict("Answer: 13.52") == 13.52, "strict: one number amid words", fails)
    check(parse_strict("4.86 6.64") is None, "strict: two numbers -> None", fails)
    check(parse_strict("") is None, "strict: empty -> None", fails)
    check(parse_strict("no digits here") is None, "strict: no numbers -> None", fails)
    check(parse_strict("1.2e3") == 1200.0, "strict: scientific notation", fails)

    # ---- legacy parser must delegate to run_atlas_traj._parse_answer exactly ----
    for text, gold in [("4.86 6.64 1.0", 6.6), ("13.5", 13.0), ("", 5.0),
                       ("1 2 3 4 5", 3.0), ("7.7", None)]:
        check(parse_legacy(text, gold) == _parse_answer(text, gold),
              f"legacy delegates: {text!r} gold={gold}", fails)

    # ---- the audit's point: a dump legacy credits, strict rejects ----
    dump = "set value 4.86\n1.0 4.86 100\n"      # 4 tokens incl. gold-matching one
    e = audit_entry(dump, gold=4.86, tol=0.5)
    check(e["legacy_val"] == 4.86 and e["legacy_ok"] is True,
          "audit: legacy credits gold-nearest from dump", fails)
    check(e["strict_val"] is None and e["strict_ok"] is False,
          "audit: strict rejects multi-number dump", fails)
    check(e["flip"] is True, "audit: entry flagged as flip", fails)

    clean = audit_entry("4.90", gold=4.86, tol=0.5)
    check(clean["legacy_ok"] is True and clean["strict_ok"] is True and clean["flip"] is False,
          "audit: clean single answer passes both", fails)

    # ---- tolerance lookup covers easy + hard metric keys ----
    check(tolerance_for("meanrg") == 0.4, "tol: easy metric (meanrg=0.4)", fails)
    check(tolerance_for("meansasa") == 400.0, "tol: easy metric (meansasa=400)", fails)
    t = tolerance_for("rmsd_max")
    check(isinstance(t, float) and t > 0, "tol: hard metric resolves (rmsd_max)", fails)
    check(tolerance_for("not_a_metric") is None, "tol: unknown -> None", fails)

    print("ALL GOOD" if not fails else f"{len(fails)} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
