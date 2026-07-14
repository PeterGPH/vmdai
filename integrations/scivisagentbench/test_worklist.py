#!/usr/bin/env python3
"""test_worklist.py — pure test of the within-arm concurrency helper. No VMD, no agents.
Run: python integrations/scivisagentbench/test_worklist.py
"""
import asyncio, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_atlas_traj import _run_worklist  # noqa: E402


def check(cond, label, fails):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    return fails + (0 if cond else 1)


def _run(n_agents, n_items):
    """Drive _run_worklist with fake agents; return (processed_items, peak_concurrency, agents_used)."""
    live = {"now": 0, "peak": 0}
    processed, agents_used = [], []

    async def run_one(agent, item):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        await asyncio.sleep(0.005)          # hold the slot so overlap is observable
        processed.append(item); agents_used.append(agent)
        live["now"] -= 1

    agents = [f"agent{i}" for i in range(n_agents)]
    items = list(range(n_items))
    asyncio.run(_run_worklist(items, agents, run_one))
    return processed, live["peak"], agents_used


def main():
    fails = 0
    # N=4 over 20 items
    processed, peak, used = _run(4, 20)
    fails = check(sorted(processed) == list(range(20)), "every item runs exactly once (N=4)", fails)
    fails = check(peak == 4, f"peak concurrency == N (got {peak})", fails)
    fails = check(peak <= 4, "never exceeds N", fails)
    fails = check(set(used) <= {f"agent{i}" for i in range(4)}, "each item ran on a provided agent", fails)

    # N=1 -> strictly sequential, in order
    processed1, peak1, _ = _run(1, 10)
    fails = check(peak1 == 1, "N=1 peak concurrency is 1 (sequential)", fails)
    fails = check(processed1 == list(range(10)), "N=1 preserves item order", fails)

    # more agents than items -> fine, peak bounded by item count
    processed2, peak2, _ = _run(8, 3)
    fails = check(sorted(processed2) == [0, 1, 2] and peak2 <= 3, "more agents than items is safe", fails)

    print("ALL GOOD" if not fails else f"{fails} FAILED")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
