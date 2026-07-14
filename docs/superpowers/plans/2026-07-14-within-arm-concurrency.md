# Within-Arm Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Run N tasks concurrently within each benchmark arm (a pool of N isolated agents draining a shared work-list) so vLLM batches the requests and the sweep runs ~10× faster; `--concurrency` defaults to 1 (identical to today).

**Architecture:** A pure `_run_worklist(items, agents, run_one)` helper spawns one worker per agent, each draining a shared cursor — exactly `len(agents)` tasks in flight, each on its own agent (own bridge/VMD/`_series`). `run_arm` builds the flat work-list, creates N agents, defines the per-task body as `run_one`, drains, then aggregates as before. asyncio is single-threaded and the only `await` per task is `agent.run_task`, so all recording is race-free without locks.

**Tech Stack:** Python 3 asyncio; runnable-`main` test in `integrations/scivisagentbench`.

## Global Constraints

- `--concurrency` default **1** → behaviorally identical to today (one agent, one worker, same order).
- No locks: the only `await` in `run_one` is `agent.run_task`; all recording is synchronous → atomic in asyncio. Do not add threads.
- Each concurrent slot gets its OWN agent (own bridge/VMD/`_series`) — never share an agent across concurrent tasks.
- Keep the aggregation/scoreboard/summary code (current lines 185–204) unchanged.
- Spec: `docs/superpowers/specs/2026-07-14-within-arm-concurrency-design.md`.
- Run from vmd_ai/. Branch vmdbench-design. Commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## File Structure

- **Create** `integrations/scivisagentbench/test_worklist.py` — pure unit test of `_run_worklist`.
- **Modify** `integrations/scivisagentbench/run_atlas_traj.py` — add `_run_worklist`, refactor `run_arm` to build a work-list + N-agent pool, add `--concurrency`.
- **Modify** `integrations/scivisagentbench/run_atlas_parallel.sh` — pass a `CONC` env → `--concurrency`.

---

### Task 1: `_run_worklist` helper + pure test

**Files:**
- Modify: `integrations/scivisagentbench/run_atlas_traj.py` (add the helper only)
- Test: `integrations/scivisagentbench/test_worklist.py`

**Interfaces:**
- Produces: `async def _run_worklist(items, agents, run_one) -> None` — drains `items` across `len(agents)` workers (one agent each); `run_one(agent, item)` is awaited; bounded concurrency = `len(agents)`; each item runs exactly once.

- [ ] **Step 1: Write the failing test**

Create `integrations/scivisagentbench/test_worklist.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python integrations/scivisagentbench/test_worklist.py`
Expected: FAIL — `ImportError: cannot import name '_run_worklist'`.

- [ ] **Step 3: Add `_run_worklist` to run_atlas_traj.py**

Insert this function just above `async def run_arm(args):` (before line 121):

```python
async def _run_worklist(items, agents, run_one):
    """Drain `items` across len(agents) worker coroutines, one agent each. run_one(agent, item) is
    awaited per task. Bounded concurrency = len(agents); each item runs exactly once on some agent.
    Single-threaded asyncio: `cursor` read+increment has no await between it, so it is atomic."""
    cursor = {"i": 0}

    async def worker(agent):
        while True:
            i = cursor["i"]
            if i >= len(items):
                return
            cursor["i"] = i + 1
            await run_one(agent, items[i])

    await asyncio.gather(*(worker(a) for a in agents))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python integrations/scivisagentbench/test_worklist.py`
Expected: PASS — `ALL GOOD` (bounded concurrency, all items once, N=1 sequential in order).

- [ ] **Step 5: Commit**

```bash
git add integrations/scivisagentbench/run_atlas_traj.py integrations/scivisagentbench/test_worklist.py
git commit -m "feat(vmdbench): _run_worklist — bounded N-agent concurrency helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Refactor `run_arm` to a work-list + N-agent pool

**Files:**
- Modify: `integrations/scivisagentbench/run_atlas_traj.py` (`run_arm` + `main`)
- Modify: `integrations/scivisagentbench/run_atlas_parallel.sh`

**Interfaces:**
- Consumes: `_run_worklist` (Task 1).
- Produces: `--concurrency` flag; `run_arm` runs tasks across a pool.

- [ ] **Step 1: Refactor `run_arm`**

Replace the body from `agent = get_agent("vmd_ai")(config)` (line 143) through the end of the `finally:` block (line 183) with the work-list + pool version. Concretely:

Replace lines 143–183 with:

```python
    seeds = max(1, int(args.seeds))
    conc = max(1, int(getattr(args, "concurrency", 1)))
    save_fails = os.environ.get("VMD_AI_SAVE_FAILURES", "1") != "0"
    if save_fails:
        (outdir / "failures.jsonl").unlink(missing_ok=True)

    # ---- flat work-list (skip_fn applied once, up front) ----
    items = []
    for seed in range(1, seeds + 1):
        for name, pdb, dcd in pairs:
            for mkey, (phrase, tol, scored) in metrics.items():
                if skip_fn and skip_fn(mkey, gold.get(name, {})):
                    continue
                items.append((seed, name, pdb, dcd, mkey, phrase, tol, scored))

    results, detail = {}, {}
    counters = {"fail_saved": 0}

    async def run_one(agent, item):
        seed, name, pdb, dcd, mkey, phrase, tol, scored = item
        ans_path = str(outdir / f"{name}__{mkey}__s{seed}.txt")
        if os.path.exists(ans_path):
            os.remove(ans_path)
        prompt = prompt_builder(pdb, dcd, phrase, ans_path)
        case_name = f"{name}_{mkey}_s{seed}"
        tcfg = {"working_dir": str(outdir), "case_dir": str(outdir),
                "case_name": case_name, "timeout": args.timeout}
        result = None
        try:
            result = await agent.run_task(prompt, tcfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  [s{seed}] {name}/{mkey}: run error: {exc}")
        g = gold.get(name, {}).get(mkey)
        val = None
        if os.path.exists(ans_path):
            fs = [float(x) for x in FLOAT.findall(open(ans_path, errors="replace").read())]
            if fs and g is not None:
                val = min(fs, key=lambda x: abs(x - g))
        ok = (val is not None and g is not None and abs(val - g) <= tol) if scored else None
        results.setdefault((name, mkey), []).append(ok)
        detail[f"{name}__{mkey}__s{seed}"] = {"gold": g, "agent": val, "ok": ok}
        print(f"  [s{seed}] {name:8} {mkey:10} gold={g} agent={val} -> "
              + ("PASS" if ok else ("FAIL" if ok is False else "-")))
        if save_fails and scored and ok is False:
            _save_failure(outdir, name, mkey, seed, phrase, tol, g, val, ans_path, result, args.tag)
            counters["fail_saved"] += 1

    # ---- pool of `conc` isolated agents (each own bridge/VMD/_series) ----
    print(f"  [arm {args.tag}] {len(items)} tasks over {conc} concurrent agent(s)")
    agents = []
    for _ in range(conc):
        a = get_agent("vmd_ai")(config)
        await a.setup()
        agents.append(a)
    try:
        await _run_worklist(items, agents, run_one)
    finally:
        for a in agents:
            try:
                await a.teardown()
            except Exception:  # noqa: BLE001
                pass

    n_fail_saved = counters["fail_saved"]
```

(The aggregation/scoreboard/summary block after this — the `names = [...]` through `return 0` — is unchanged; it reads `results`/`detail`/`n_fail_saved`.)

- [ ] **Step 2: Add the `--concurrency` flag in `main()`**

After the `--seeds` argument (line ~215), add:

```python
    ap.add_argument("--concurrency", type=int, default=1,
                    help="tasks run concurrently within the arm, each on its own agent+VMD "
                         "(default 1 = sequential; try 8 to saturate vLLM's KV cache)")
```

- [ ] **Step 3: Verify N=1 unchanged + flag present**

Run: `python integrations/scivisagentbench/test_worklist.py` → still `ALL GOOD`.
Run: `python integrations/scivisagentbench/run_atlas_traj.py --help` → exit 0, lists `--concurrency`.
(The end-to-end N=8 behavior is validated on the server — the module needs `evaluation_framework`.)

- [ ] **Step 4: Plumb `CONC` through run_atlas_parallel.sh**

In `run_atlas_parallel.sh`, add near the other env-knob defaults (after `TIMEOUT=...`, ~line 22):

```bash
CONC="${CONC:-1}"                                  # tasks concurrent per arm (each own agent+VMD)
```

Then add `--concurrency "$CONC"` to the arm-launch `python run_atlas_traj.py` line (the line already carrying `--gold-cache ... ${HARD:+--hard}`):

```bash
    --gold-cache "$GOLD_CACHE" ${HARD:+--hard} --concurrency "$CONC" > "$log" 2>&1 &
```

Update the "Env knobs" comment header to mention `CONC`.

- [ ] **Step 5: Verify the shell parses**

Run: `bash -n integrations/scivisagentbench/run_atlas_parallel.sh` → exit 0.

- [ ] **Step 6: Commit**

```bash
git add integrations/scivisagentbench/run_atlas_traj.py integrations/scivisagentbench/run_atlas_parallel.sh
git commit -m "feat(vmdbench): --concurrency (N-agent pool per arm) + CONC knob in the sweep

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **N=1 must be identical to the old loop** — same order, same agent, same per-task body. The refactor just moves the per-task body into `run_one` and the triple-loop into the `items` build; verify nothing else changed (especially the answer-file removal, the `min(fs, key=…)` nearest-gold pick, and the `_save_failure` call).
- **Do NOT add locks or threads** — asyncio single-thread + sync recording is the whole safety argument (spec §4).
- The end-to-end multi-agent run needs `evaluation_framework` (server-only), so trust the `_run_worklist` unit test + code review here; validate the real speedup on the server (`CONC=8`).
- Usage once shipped: `CONC=8 HARD=1 RUN=… SEEDS=3 FIXDIR=… bash run_atlas_parallel.sh none tools workbench`.
