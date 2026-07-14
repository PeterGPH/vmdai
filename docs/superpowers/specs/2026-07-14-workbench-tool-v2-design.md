# Design spec — v2 "workbench" tool (series + free-expression compute)

- **Date:** 2026-07-14
- **Branch:** `vmdbench-design`
- **Status:** approved design, pending implementation plan
- **Builds on:** the hard/reasoning tier (`docs/superpowers/specs/2026-07-10-hard-reasoning-tier-design.md`)

## 1. Problem

The v1 semantic tool `vmd_traj_measure` mirrors the oracle and computes **canned means**. The hard
tier showed the consequence: on `max`/`range` questions the tool returns the *mean* (the wrong
quantity) with 100% completion and 0% correctness, and on a capable model (72B) it *lowers*
correctness by overwriting the model's own reasoning. The tool conflates two things it should
separate:

- **execution** (running the frame loop, doing arithmetic) — which the tool *should* make reliable;
- **formulation** (deciding *what* to compute) — which the *model* must supply.

v1 bakes in the formulation. v2 separates them.

## 2. Goal

A composable **workbench**: the tool returns the per-frame **series** (data, not answers), and a
safe **compute** step reduces it by a free expression the model writes. The model must map the
English question to `(quantity, reduction)` — pure formulation reasoning — while the tool removes
the Tcl-syntax and arithmetic barriers.

**Success:** on the hard tier, a workbench arm scores materially **above** both the v1-tool arm
(no longer misled into the mean) and the none arm (execution barrier removed), and the residual
errors are genuine *formulation* errors (wrong reduction/quantity), not syntax or arithmetic. The
easy tier stays easy (model just picks `mean`).

**Non-goals (v2):** arbitrary Python execution; new observables beyond the four the oracle already
computes; visualization. The workbench is added as a **new arm alongside** `none`/`tools`-v1, not a
replacement — the comparison is the point.

## 3. The two tools

```
vmd_traj_series(quantity: str) -> {"name": str, "n": int, "preview": [floats]}
    # runs VMD once, computes the RAW per-frame series for a named observable, and BINDS it
    # to `name` in the bridge's compute namespace. Returns a short preview + length, NOT the
    # full array (avoid dumping 42+ floats into context; the model reduces via vmd_compute).
    # quantity ∈ {"rgyr", "sasa", "rmsd_to_frame0", "rmsf_per_residue"}; name is the short key
    # ("rgyr","sasa","rmsd","rmsf"). Selection is implied by the quantity (protein / protein CA),
    # mirroring the oracle exactly so results are gold-consistent.

vmd_compute(expression: str) -> {"value": float}
    # PURE PYTHON — no VMD. Safe-evaluates `expression` over the bound series (numpy arrays).
    # e.g. "max(rmsd)"  "std(rgyr)"  "ptp(sasa)"  "rgyr[-1]-rgyr[0]"  "rgyr[-1]/rgyr[0]"
    #      "argmin(rgyr)"  "mean(rgyr > mean(rgyr))"  (fraction, via boolean reduction)
```

**The agent loop (ReAct, already the ClaudeToolLoop shape):** read question → reason
`(quantity, reduction)` → `vmd_traj_series` → `vmd_compute` → observe → answer (re-measure if it
doubts the number). Named series persist across calls in one task, so the model can fetch several
and combine them.

## 4. The safe-eval sandbox (security-critical)

`vmd_compute` MUST NOT be `eval()`. It parses the expression with `ast.parse(expr, mode="eval")`
and walks the tree against a strict allow-list; anything else raises `ComputeError` with a clear
message. (Note: the surrounding Tcl agent is already unsandboxed — but `vmd_compute` is a *new*
attack surface we keep clean by construction, and a clean evaluator is also what makes the tool's
results trustworthy.)

**Allowed AST nodes:** `Expression`, `Constant`(numbers only), `Name`(load; must be a bound series
or an allowed constant `pi`/`e`), `BinOp`(`+ - * / // % **`), `UnaryOp`(`+ -`), `Call`(only to
allow-listed functions, no keywords/starargs), `Subscript`+`Index`/`Constant` slice
(`rgyr[-1]`, `rgyr[0]`), `Compare`(`< <= > >= == !=`).

**Disallowed (→ ComputeError):** `Attribute` (no `.foo`), `Lambda`, comprehensions, `import`,
dunder names (`__.*__`), any `Name` not bound, any `Call` target not in the allow-list.

**Allowed functions (mapped to numpy):** `max min mean std var median sum abs sqrt ptp argmin
argmax len`. `ptp` = peak-to-peak (range). `argmin`/`argmax` return 0-based **int** indices.
Boolean arrays from `Compare` reduce under `mean`/`sum` (→ fraction/count).

**Evaluation:** over `numpy` arrays for the bound series; return a Python `float` (or int for
argmin/argmax). Empty/unbound name → `ComputeError`.

Lives in a standalone module `safe_eval.py` with `safe_eval(expression, namespace) -> float`,
unit-tested in isolation (no VMD).

## 5. Series computation (gold-consistent)

`vmd_traj_series` runs Tcl (via the existing bridge `_run_tcl`) that mirrors the hard oracle's
per-frame loops, emitting the series over `PROBE>`-style lines the bridge parses into a Python
list:

- `rgyr` → `measure rgyr` of `protein`, per frame → bound `rgyr`
- `sasa` → `measure sasa 1.4` of `protein`, per frame → bound `sasa`
- `rmsd_to_frame0` → aligned Cα RMSD to frame 0 (`measure fit` then `measure rmsd`), per frame → `rmsd`
- `rmsf_per_residue` → `measure rmsf` of `protein and name CA` (per-residue vector) → `rmsf`

Because the series come from the same VMD measures as `gold_oracle_traj_hard.tcl`,
`vmd_compute("max(rmsd)")` equals the gold `rmsd_max` **exactly** — but only if the model chooses
`max`. The tool is oracle-*capable* again; what it now tests is the *reduction choice*, i.e. the
formulation.

## 6. Agent wiring & the new arm

- Two schemas `VMD_TRAJ_SERIES_SCHEMA`, `VMD_COMPUTE_SCHEMA` advertised via
  `self._loop.extra_tools` (same mechanism as `VMD_TRAJ_MEASURE_SCHEMA`).
- Bridge gains `_traj_series(quantity)` (Tcl → list → bind) and `_compute(expression)`
  (`safe_eval`). A per-task series namespace on the bridge, cleared per task.
- A **workbench directive** (in `tool_prompts.py`) explains the loop: "fetch the raw per-frame
  series with `vmd_traj_series`, then reduce it with a `vmd_compute` expression — the series is
  data, you decide the reduction." Toggled by `config["enable_workbench_tools"]`.
- New `config_arm_workbench.json` (`enable_workbench_tools: true`). The sweep runs it as an arm:
  `run_atlas_parallel.sh none tools workbench`.
- Transcript: record each `vmd_traj_series`/`vmd_compute` call (extend `transcript_util.py`) so
  adoption/behaviour is analyzable (which quantity, which reduction, how many iterations).

## 7. Gold & scoring — unchanged

The workbench arm answers the **same hard-tier questions** and is scored by the **same** hard gold
(`gold_cache_*_hard.json`) via `scalar_within` with the calibrated tolerances. No new gold, no new
metrics. Only the agent's *tools* differ.

## 8. Testing (TDD)

- **`safe_eval` (pure, critical):** allowed expressions compute correctly against known arrays
  (`max`,`std`,`ptp`,`argmin`,indexing,`rgyr[-1]-rgyr[0]`, boolean-mean fraction); **disallowed**
  expressions raise `ComputeError` (attribute access, unbound name, lambda, dunder, non-listed
  call, import). This is the security gate — exhaustive.
- **`vmd_traj_series` (live):** the fetched series' own reductions match the hard oracle
  (`max(rmsd)==gold rmsd_max`, `ptp(sasa)==gold sasa_range`, `std`… ) on the `2erl_A` fixture;
  skips without VMD.
- **Wiring:** the two schemas are advertised when `enable_workbench_tools`; the directive text
  contains no metric giveaways; the bridge binds/looks-up series names correctly.

## 9. Guardrails / risks

- **Safe-eval is the security surface** — the allow-list test must be exhaustive; a fuzz list of
  malicious expressions (`__import__`, `().__class__`, `open`, attribute walks) must all raise.
- **Re-saturation risk:** if the workbench makes the hard tier trivially solvable, that's actually
  the *intended* signal (execution barrier removed → score reflects reasoning). But watch `rg_ratio`
  (already gameable) and confirm errors are formulation errors via the transcript.
- **Series preview leakage:** `vmd_traj_series` returns a short preview only; returning the full
  array would let the model (poorly) do arithmetic in-context and muddy the "compute does the math"
  separation. Keep the preview to ≤5 values + length.
- **Namespace hygiene:** clear the series namespace per task so one task's series can't leak into
  another.

## 10. Out of scope / future

Model-chosen `selection` (arbitrary atomselect) as a third reasoning axis; a Python execution
substrate (broader than expression eval); visualization observables; multi-trajectory composition.
