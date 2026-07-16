# Design spec — workbench accuracy: `vmd_compute` writes its result + guided errors

- **Date:** 2026-07-16
- **Branch:** `vmdbench-design`
- **Status:** approved design, pending implementation plan
- **Builds on:** the v1 workbench (`docs/superpowers/specs/2026-07-14-workbench-tool-v2-design.md`)

## 1. Problem (grounded in the failure data)

The workbench's remaining errors are dominated by an **execution fumble**, not reasoning. In the
14B workbench run, **53% of done-but-wrong cases (76 / 144)** are: `vmd_compute` computed the gold
value *exactly*, but the model then wrote a **different** number to the answer file. Examples:

- `rmsd_max`: tool `max(rmsd) = 6.6386` (= gold), agent wrote **5.892**.
- `rmsf_max`: tool `max(rmsf) = 9.637` (= gold), agent wrote **25.912**.

Cause: `vmd_compute` *returns* the value but does not *write* it. The model must re-type the result
into the answer file via `run_vmd_command`, and botches the transcription. (The canned
`vmd_traj_measure` avoided this — it had a `save_path` that wrote its value directly.)

The other failure class — **Pathology A, wrong quantity** (e.g. fetching `rmsd` when the question is
about size/`rgyr`) — is a *genuine reasoning error* and is intentionally left alone (fixing it would
mean telling the model "rgyr = size," leaking the formulation the tier tests).

## 2. Goal

Stop penalizing the model for transcription slips: when it chooses a reduction correctly and the
tool computes it, that value must be what gets recorded. Plus, guide recoverable errors so the model
self-corrects instead of flailing.

**Success:** the "tool-right / agent-wrong" fumble class → ~0. Expected lift: 14B workbench ~40% →
~55%; 72B ~45% → ~65–70% (if its fumble rate is similar). Reasoning (which quantity + reduction)
is untouched, so the benchmark still measures formulation reasoning — arguably *more* purely.

**Non-goals:** helping the model pick the right quantity/reduction (that's the reasoning under test);
new observables/selections; the concurrency ceiling (separate).

## 3. Design

### Fix 1 — `vmd_compute(expression, save_path=None)` writes the computed value

- **Bridge** `_compute(ti)`: read `save_path = ti.get("save_path")`. After `safe_eval` yields `val`,
  if `save_path` is set, write `str(val) + "\n"` to it (same pattern as `_traj_measure`'s save:
  `os.makedirs(dirname, exist_ok=True)`; open/write; append `"(written to <path>)"` to the note; on
  write failure, note the failure but still return the value). Return unchanged when `save_path` is
  omitted (back-compatible).
- **Schema** `VMD_COMPUTE_SCHEMA`: add an optional `save_path` string property — "absolute path to
  write the computed value to (use the output file named in the task) — records your final answer
  faithfully; do not re-type the number yourself."
- **Directive** (`workbench_directive`): add — "The task names an output file. For your FINAL answer,
  call `vmd_compute(expression, save_path=<that exact path>)` — the tool writes the computed value
  for you. Do NOT write the answer yourself with run_vmd_command (that is where wrong numbers creep
  in)."

The harness reads the answer file exactly as today (nearest-float-to-gold parse), so a tool-written
value scores correctly with no scorer change.

### Fix 2 — guided error feedback so the model recovers

- **Unbound series:** when `vmd_compute`'s expression references a name that isn't bound, return a
  message that names the fetch call to make. Map the short name back to its quantity via the inverse
  of `_SERIES_NAME` (`{"rmsd":"rmsd_to_frame0", ...}`): *"vmd_compute: series 'rmsd' not bound — fetch
  it first with vmd_traj_series(quantity='rmsd_to_frame0'). Currently bound: [rgyr]."* (Surface this
  from `safe_eval`'s existing unknown-name `ComputeError` — either enrich that message with the
  quantity hint in `_compute`, or have `_compute` pre-check names before calling `safe_eval`.)
- **Malformed expression / no series yet:** keep returning the `ComputeError` reason, prefixed
  `vmd_compute:` and, when nothing is bound, the existing "call vmd_traj_series first" hint.

Errors are returned as `{ok: False, error: <hint>, expr}` (unchanged shape) — the agent loop feeds
the error back to the model, which retries.

## 4. Benchmark honesty

Fix 1 records the *model's own chosen reduction's* result; it does not choose the reduction or
reveal the gold. Fix 2 guides *how to call the tool*, not *what to compute*. Quantity names stay
bare (`rgyr`, `sasa`, `rmsd_to_frame0`, `rmsf_per_residue`) — no gloss of what they measure — so
Pathology A stays a real reasoning test. Net: the tier measures reduction *choice* more cleanly,
with the transcription-noise removed.

## 5. Testing (TDD)

- **`_compute` save_path (live-ish / unit):** with a bound series, `vmd_compute("max(rmsd)",
  save_path=tmp)` writes exactly the computed value to `tmp` (matches the returned `value`); without
  `save_path`, no file is written and behavior is unchanged. (Can be tested by driving the bridge's
  `_compute` with a pre-seeded `self._series` — no VMD needed for the compute+write half.)
- **Guided unbound-series error:** `vmd_compute("max(rmsd)")` with only `rgyr` bound → `ok False`
  and the error names `vmd_traj_series(quantity='rmsd_to_frame0')` and lists bound `[rgyr]`.
- **Directive:** `workbench_directive` mentions `save_path` and still contains no scored formula
  (the existing `test_workbench_wiring` giveaway checks stay green).
- **Regression:** `test_safe_eval` (unchanged) + full suite green.

## 6. Rollout / validation

Re-run one model's workbench arm (14B, CONC=2) after the change and confirm the "tool-right /
agent-wrong" class drops toward 0 and correctness rises to ~55%. Then re-run the 3-model table for
the report. No scorer/gold change, so easy/none/canned arms are unaffected.

## 7. Files

- `integrations/scivisagentbench/subprocess_vmd_bridge.py` — `_compute` save_path + unbound-series hint.
- `integrations/scivisagentbench/vmd_ai_agent.py` — `VMD_COMPUTE_SCHEMA` gains `save_path`.
- `integrations/scivisagentbench/tool_prompts.py` — `workbench_directive` write-the-answer instruction.
- `integrations/scivisagentbench/safe_eval.py` — (optional) enrich the unknown-name error, or handle in `_compute`.
- Tests: extend `test_workbench_wiring.py` / add a `_compute` save_path+error test.
