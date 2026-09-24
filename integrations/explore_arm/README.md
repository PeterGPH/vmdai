# explore_arm — the knowledge-free self-exploration arm

A new benchmark arm for the atlas-traj suite that gives the model **zero domain
content** — no canned tools, no injected reference, no skills — only a generic
exploration *process*: three content-free lab tools plus an **enforced
explore → distill → verify → commit protocol**. Whatever correctness emerges is
latent model knowledge elicited by process, not knowledge compiled into the
scaffold. It completes the arm axis:

    none            →  explore (THIS: process-only)  →  rag / inject (knowledge injected)
                                                     →  tools / workbench (knowledge compiled)

All new code lives in this folder; nothing in `runtime/`, `vmdbench/`, or
`integrations/scivisagentbench/` is modified. Gold, tolerances, and scoring are
byte-identical to the other arms (`run_atlas_traj.run_arm` is reused verbatim).

## The scaffold

The model's entire action surface is three tools (`run_vmd_command` and
`capture_vmd_snapshot` are hidden — fewer tools measurably increase environment
engagement):

| tool | phase | behavior |
|---|---|---|
| `lab_try(code)` | EXPLORE / VERIFY | runs one small experiment in the live interpreter; the result or error comes back verbatim — errors are framed as documentation, never as failure |
| `lab_note(text)` | DISTILL | records one verified fact in the lab notebook; notes are echoed back at commit time |
| `lab_commit(code)` | COMMIT | runs the final end-to-end solution — **refused** until the gate opens |

**The gate** (`scaffold.LabProtocol`): a commit executes only after
≥ `explore_min_experiments` lab_try calls, ≥ 1 lab_note, and ≥ 1 lab_try *after*
the latest note (the verify run). Refusals return a structured message naming
exactly what is missing, plus the notes so far.

**Guardrails** (both content-free): an identical error twice in a row appends a
"form a DIFFERENT hypothesis" nudge; exceeding `explore_max_experiments` appends
a soft budget warning (warn-only — the protocol cannot deadlock; the task
timeout stays the hard bound).

**Genericness lint** — what makes "knowledge-free" a *checkable* property, not a
claim: `scaffold.lint_texts()` scans every scaffold-authored string (directive +
tool schemas) for `FORBIDDEN_TOKENS` (VMD command names, MD vocabulary) and the
test suite asserts the result is empty. The wrapper also sanitizes the one place
the shared bridge would leak domain steering into this arm (its anti-thrash
error suffix advertises `vmd_traj_measure`).

Two deliberate scope notes:
- The base system prompt and task prompt are shared with the other arms (their
  tool mentions are retargeted at the lab surface; every other word identical) —
  the *scaffold* adds zero domain content beyond that shared baseline.
- The answer file may legitimately be written during the VERIFY lab_try; the
  commit re-produces it end-to-end. Scoring is unchanged either way.

## Files

- `scaffold.py` — pure logic: directive, schemas, lint, `LabProtocol` gate machine
- `explore_bridge.py` — `ExploreScaffoldBridge`, a decorator over any VMD bridge
- `explore_agent.py` — `ExploreAgent(VmdAiAgent)`: swaps in the lab surface after normal setup
- `run_explore.py` — runner: registry-swaps `"vmd_ai"` → `ExploreAgent`, retargets the
  prompt, then delegates to `run_atlas_traj.run_arm` (gold/scoring/failures reused)
- `config_explore.json` — vLLM-endpoint config + the two protocol knobs
- `tests/` — the TDD suite (see below)

## Run the tests

From `vmd_ai/`:

```bash
python -m pytest integrations/explore_arm/tests -q          # full suite (35 tests)
python -m pytest integrations/explore_arm/tests -q -k live  # just the real-VMD tests
```

No LLM or network needed. `test_scaffold.py` (18) is pure logic; `test_wiring.py` (13)
drives the bridge with a fake inner bridge and boots the real agent surface;
`test_live.py` (4) runs the lab chain against real VMD (auto-skips without the binary,
and includes the arm's premise test: a wrong invocation reveals usage text).

## Run the arm

Serve a model (see `../scivisagentbench/SERVE_LOCAL_MODEL.md`), then from this folder:

```bash
python run_explore.py --config config_explore.json --seeds 3 \
    --gold-cache ../scivisagentbench/gold_cache_atlas_fixtures.json

# hard/reasoning tier
python run_explore.py --config config_explore.json --hard --tag explore_hard --seeds 3

# gate-threshold sweep without editing the config
python run_explore.py --min-experiments 5 --tag explore_min5
```

`--bench` defaults to `~/SciVisAgentBench` and falls back to the in-repo
`SciVisAgentBench-main/` automatically. Compare against the base arms by running
`run_atlas_traj.py` with `config_arm_none.json` / workbench configs as usual —
same fixtures, same gold cache, same summary format.

## Running on the GPU server (tbgl)

The code and config are machine-portable: `hostpaths.py` resolves the VMD binary
(env `VMD_AI_VMD_BIN` → config `vmd_bin` → known install paths, which include the
server's `/software/vmd-1.9.3/bin/vmd`) and the runtime path (defaults to this
clone's `vmd_ai/runtime`), and `run_explore.py` injects the resolved values before
the arm starts — so a config written on the Mac never hard-crashes the server.
Two ways to run against the GPU-served model:

**A. Everything on the server** (harness + VMD + vLLM):

```bash
# 0. ship this folder to the server clone (coordinates as in scripts/sync_hard_tier_to_server.sh):
SRV=pinhao2@tbgl-gpu-01 RMT=/data/server10/pinhao2/ML/PyMolAI/vmd_ai
rsync -av --exclude __pycache__ integrations/explore_arm/ "$SRV:$RMT/integrations/explore_arm/"

# 1. on tbgl — serve the model (see ../scivisagentbench/SERVE_LOCAL_MODEL.md; pin one idle
#    GPU with CUDA_VISIBLE_DEVICES, AWQ 4-bit, --tool-call-parser hermes for Qwen)
# 2. then, from this folder in the server's clone:
python run_explore.py --config config_explore.json --seeds 3 \
    --gold-cache ../scivisagentbench/gold_cache_atlas_fixtures.json
# VMD auto-resolves to /software/vmd-1.9.3/bin/vmd; override with VMD_BIN / VMD_AI_VMD_BIN
```

**B. Harness + VMD on the Mac, model on the server** (the harness's designed mode —
agent+VMD local, only the *model* remote): tunnel the endpoint and run locally
unchanged:

```bash
ssh -N -L 8000:localhost:8000 <tbgl>     # keep open in another terminal
python run_explore.py --config config_explore.json --seeds 3
```

Either way, **`model` in the config must exactly match the served model id**
(`curl localhost:8000/v1/models`) — the startup line `[vmd_ai] ready: provider=…
model=…` is the provenance record, and a label/served mismatch is exactly how the
`qwen14b_wb2` misrun happened. The tests also run on the server
(`python -m pytest tests -q`): the live suite picks up the server's VMD via the
same resolution.

## Artifacts & process metrics

Per task, next to the usual `<case>.tcl` / `<case>.response.txt` / failure bundles:

- `<case>.lab.json` — the full protocol record: every experiment (code, ok, error,
  guidance), notes, commit rejections, plus the summary counters:
  `experiments, notes, errors, error_recoveries, commit_rejections, commits,
  loop_nudges, cap_warnings`.
- The same summary (minus events) rides in the AgentResult metadata under `"explore"`.

These are the judge-free process metrics for the analysis: error-recovery rate,
loop rate, gate resistance (rejections), notes volume, experiments-to-commit —
to be correlated with per-task correctness from `summary.json`.

Note: lab commands are recorded in `<case>.lab.json` (not in the `<case>.tcl`
transcript, which only tracks the hidden `run_vmd_command` path).
