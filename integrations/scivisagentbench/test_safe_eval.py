#!/usr/bin/env python3
"""test_safe_eval.py — the security gate for vmd_compute. Allowed expressions compute correctly;
everything outside the allow-list raises ComputeError. Pure — no VMD. Run:
  python integrations/scivisagentbench/test_safe_eval.py
"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from safe_eval import safe_eval, ComputeError  # noqa: E402

NS = {"rgyr": [10.0, 11.0, 12.0, 9.0], "rmsd": [0.0, 1.0, 3.0, 2.0], "sasa": [100.0, 250.0, 175.0]}

OK_CASES = [   # (expr, expected)
    ("max(rmsd)", 3.0), ("min(rgyr)", 9.0), ("mean(rgyr)", 10.5),
    ("ptp(sasa)", 150.0), ("argmin(rgyr)", 3), ("argmax(rmsd)", 2),
    ("rgyr[-1]-rgyr[0]", -1.0), ("rgyr[-1]/rgyr[0]", 0.9), ("rgyr[0]", 10.0),
    ("max(sasa)-min(sasa)", 150.0), ("abs(rgyr[-1]-rgyr[0])", 1.0),
    ("mean(rgyr > mean(rgyr))", 0.5),           # fraction above mean -> 2/4
    ("sum(rmsd)", 6.0),
]
BAD_CASES = [   # expressions that MUST raise ComputeError
    "__import__('os').system('id')", "().__class__.__bases__", "open('/etc/passwd')",
    "rgyr.__class__", "unknown_series", "lambda x: x", "[x for x in rgyr]",
    "rgyr.sum()", "exec('x=1')", "globals()", "max(rgyr).__reduce__",
    "", "   ", "1;2", "import os",
]


def approx(a, b): return abs(float(a) - float(b)) < 1e-9


def main():
    fails = 0
    for expr, want in OK_CASES:
        try:
            got = safe_eval(expr, NS)
            ok = approx(got, want) and type(got) in (int, float)
        except Exception as e:  # noqa: BLE001
            ok = False; got = f"RAISED {type(e).__name__}: {e}"
        print(f"  [{'PASS' if ok else 'FAIL'}] {expr!r} -> {got}" + ("" if ok else f"  (want {want})"))
        fails += not ok
    for expr in BAD_CASES:
        try:
            got = safe_eval(expr, NS); ok = False
        except ComputeError:
            ok = True; got = "ComputeError (correctly rejected)"
        except Exception as e:  # noqa: BLE001  wrong exception type is still a fail
            ok = False; got = f"WRONG EXC {type(e).__name__}: {e}"
        print(f"  [{'PASS' if ok else 'FAIL'}] reject {expr!r} -> {got}")
        fails += not ok
    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
