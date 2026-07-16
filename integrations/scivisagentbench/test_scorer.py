#!/usr/bin/env python3
"""test_scorer.py — the answer-file parser must not be gameable by a dumped script/state file.
A clean answer is a single value; a many-number dump (e.g. a VMD save_state) is rejected so the
nearest-to-gold pick can't cherry-pick a gold-matching number out of the noise. Pure; no VMD.
Run: python integrations/scivisagentbench/test_scorer.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_atlas_traj import _parse_answer  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def main():
    fails = 0
    fails = check(_parse_answer("6.638625621795654", 6.64) == 6.638625621795654,
                  "clean single number -> that number", fails)
    fails = check(_parse_answer("", 6.64) is None, "empty file -> None", fails)
    fails = check(_parse_answer("6.64", None) is None, "gold None -> None", fails)
    fails = check(_parse_answer("2", 2.0) == 2.0, "integer answer", fails)
    fails = check(_parse_answer("computed over 42 frames, max = 6.64", 6.64) == 6.64,
                  "a little context (2 numbers) -> nearest gold", fails)
    fails = check(_parse_answer("1 2 3 6.64", 6.64) == 6.64, "4 numbers still parsed", fails)
    fails = check(_parse_answer("1 2 3 4 6.64", 6.64) is None,
                  "5+ numbers -> rejected (a dump, not an answer)", fails)
    # the real exploit: a VMD save_state dumped into the answer file (hundreds of numbers, gold~0.9)
    dump = "#!/usr/local/bin/vmd\nset viewplist {}\n" + " ".join(str(x) for x in
             [1.47, 1.9, 3, 1, 2, 0.5, 0.9, 0.72, 0.96, 1.0] * 100)
    fails = check(_parse_answer(dump, 0.9) is None,
                  "dumped save_state (100s of numbers) -> rejected, NOT cherry-picked to 0.9", fails)
    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
