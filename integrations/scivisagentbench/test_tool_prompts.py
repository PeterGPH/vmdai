#!/usr/bin/env python3
"""test_tool_prompts.py — the semantic-tool directive strength must be a config knob so the
cross-model sweep can run tools-soft ("prefer", the v2 condition) vs tools-mandatory (v3) without
editing code. Pure text — no VMD, no framework.

  python integrations/scivisagentbench/test_tool_prompts.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tool_prompts import tool_directive  # noqa: E402


def main():
    fails = 0

    def check(label, cond):
        nonlocal fails
        fails += not cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    soft = tool_directive({"tool_directive": "soft"})
    mand = tool_directive({"tool_directive": "mandatory"})
    dflt = tool_directive({})

    check("soft is the gentle 'prefer' variant", "PREFER TOOLS" in soft and "MANDATORY" not in soft)
    check("mandatory is the hard variant", "MANDATORY" in mand and "NEVER" in mand)
    check("default (no key) is mandatory (preserves v3 behavior)", dflt == mand)
    check("both name vmd_traj_measure", "vmd_traj_measure" in soft and "vmd_traj_measure" in mand)
    check("only mandatory forbids hand-counting frames",
          "count frames by hand" not in soft and "count frames by hand" in mand)
    check("unknown value falls back to mandatory (fail safe)",
          tool_directive({"tool_directive": "banana"}) == mand)

    print("ALL GOOD — tool_directive selects the right variant." if not fails
          else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
