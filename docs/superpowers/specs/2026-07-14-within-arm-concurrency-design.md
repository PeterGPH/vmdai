# Design spec — within-arm task concurrency (speed up the sweep)

- **Date:** 2026-07-14
- **Branch:** `vmdbench-design`
- **Status:** approved design, pending implementation plan

## 1. Problem

`run_atlas_traj.py:run_arm` processes its ~498 tasks **sequentially** (`for seed → chain → metric:
await agent.run_task`). One agent → one in-flight LLM request at a time. `run_atlas_parallel.sh`
runs 3 arms as 3 processes, so vLLM sees only ~3 concurrent requests. vLLM's continuous batching
and KV cache can serve far more, so the GPU sits mostly idle and the full 31×6×3 sweep takes hours.

## 2. Goal

Run **N tasks concurrently within each arm** so vLLM batches them (KV cache fills, GPU saturates),
cutting the full sweep from hours to tens of minutes. Add `--concurrency N` (default **1**, which
must be behaviorally identical to today).

**Non-goals:** cross-arm scheduling changes; changing gold/scoring; changing the agent or bridge
internals. Only `run_arm`'s task loop + a config knob.

## 3. Design — a pool of N isolated agents + N workers

Concurrent tasks **cannot share one agent/bridge** — they'd collide on the VMD molecule state, the
`atomselect top`, the agent conversation, and (v2) the bridge's `self._series` namespace. So each
concurrent slot gets **its own agent** (hence its own `SubprocessVmdBridge` + VMD subprocess).

Pattern: **N long-lived agents, N worker coroutines, one shared work-list.** Each worker owns one
agent and pulls tasks until the list is drained. Exactly N tasks are in flight; each task runs on a
distinct agent.

```
items    = [ (seed, name, pdb, dcd, mkey, phrase, tol, scored) … ]   # skip_fn applied
agents   = [ make_agent()  for _ in range(N) ]   # each await agent.setup()
await _run_worklist(items, agents, run_one)      # run_one(agent, item) = the per-task body
```

The pure orchestration helper (unit-testable with fakes, no VMD/agent):

```python
async def _run_worklist(items, agents, run_one):
    """Drain `items` across len(agents) workers, one agent each. run_one(agent, item) is awaited.
    Bounded concurrency = len(agents); each item runs exactly once on some agent."""
    cursor = {"i": 0}
    async def worker(agent):
        while True:
            i = cursor["i"]
            if i >= len(items):
                return
            cursor["i"] = i + 1          # read+increment: no await between → atomic in asyncio
            await run_one(agent, items[i])
    await asyncio.gather(*(worker(a) for a in agents))
```

## 4. Why no locks are needed

asyncio is single-threaded/cooperative. The **only** `await` in a task is `agent.run_task`;
everything else in `run_one` (writing the answer file, `results.setdefault(...).append`,
`detail[...] = ...`, `_save_failure`, incrementing the fail counter) is **synchronous** and
therefore runs to completion without yielding — no interleaving, no races. Keys are per-case and
distinct, so even the shared `results`/`detail` dicts are safe. The fail counter becomes a mutable
container (`counters = {"fail_saved": 0}`) so nested `run_one` can mutate it.

## 5. N=1 equivalence

`--concurrency 1` → one agent, one worker → the work-list is drained in the same order as today's
nested loop. Same agent, same per-task body, same recording → behaviorally identical. The default
is 1, so existing runs are unchanged unless the flag is passed.

## 6. Integration

- `run_atlas_traj.py`: extract the per-task body (current lines 156–181) into `run_one(agent,
  item)`; build `items` (applying `skip_fn`); create N agents; `await _run_worklist(...)`; keep the
  aggregation/scoreboard/summary code unchanged (reads `results`/`detail`). Add `--concurrency`
  (`type=int, default=1`). Tear down all N agents in `finally`.
- `run_atlas_parallel.sh`: pass a `CONC` env → `--concurrency "$CONC"` (default 1 when unset, so
  the easy path is unchanged). Document it.

## 7. Concurrency ceiling & guidance

Total concurrent vLLM requests = (arms running) × N. Each slot = one VMD subprocess (CPU, text
mode) + one HTTP client. **Recommend N=8** (3 arms × 8 = 24 concurrent — a healthy vLLM batch, 24
VMD procs, comfortable on the box). Users can push higher (N=16) on a big node. Keep the per-task
`timeout` so a stuck task frees its slot.

## 8. Risks

- **Agent setup isolation:** N agents each call `await agent.setup()`. Must be instance-isolated
  (own bridge, own paths). For the hard-tier arms (none/tools/workbench) setup is cheap and
  instance-local; verify no fixed global temp path is written by two agents. (RAG/wiki arms load an
  index per agent — heavier, but out of scope for the hard-tier sweep.)
- **VMD process count:** N per arm × arms. Bounded by N; the recommended N=8 is safe. Document it.
- **Interleaved prints:** the per-task PASS/FAIL lines print out of order under concurrency
  (cosmetic; the scoreboard is order-independent). Optionally prefix each line so it's readable.
- **Framework import on Mac:** `run_arm` imports `evaluation_framework` (server-only), so the
  refactor's end-to-end test runs on the server; the Mac test covers `_run_worklist` in isolation.

## 9. Testing

- **`_run_worklist` (pure, Mac-runnable):** with fake agents + a `run_one` that tracks live
  concurrency — assert (a) every item runs exactly once, (b) peak concurrency == len(agents), never
  more, (c) each item ran on one of the provided agents. Also N=1 → strictly sequential
  (peak concurrency 1, items in order).
- **Refactor correctness:** by code review (N=1 == the old nested loop) + a real server run at N=8
  compared against a prior N=1 run's numbers (same gold-scored results, faster wall-clock).
