# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Scope & layout

Covers **`vmd_ai/`**, the VMD-AI subtree of a PyMOL-open-source fork (the repo's top-level
`pyproject.toml` is PyMOL's — ignore it for this work). Run all commands from `vmd_ai/` so
`python -m vmdbench…` resolves.

Four largely-independent subsystems:
- **`runtime/` (`vmd_ai_runtime`) + `plugin/`** — the ChatVMD product: a Tcl/Tk VMD panel
  (`plugin/`) talks JSON-RPC to a Python runtime (`runtime/`) whose `ClaudeToolLoop`
  (`claude_loop.py`) drives VMD by emitting Tcl. `docs_search.py` (RAG over VMD/Tcl docs)
  and a wiki store are optional augmentations toggled as A/B "arms."
- **`vmdbench/`** — the benchmark (below). A programmatic **correctness** verifier for VMD
  agents; the thesis (`docs/scivisagentbench_vs_vmdbench.md`) is *verify the computed value /
  rendered pixels, not LLM-judged completion*.
- **`integrations/scivisagentbench/`** — a harness that wraps the unchanged `ClaudeToolLoop`
  (via a `BaseAgent` adapter) through headless VMD to score it on SciVisAgentBench tasks and a
  portable structure×metric grid, across arms (none / rag / wiki / autorag / inject).
- **`scripts/`** — tooling, notably the ATLAS MD-trajectory → benchmark-case pipeline.

⚠️ **Security:** the agent evaluates **Tcl at global scope, which is not sandboxed** (`exec`,
`file delete`, `socket`, …) — effectively shell-equivalent. Prompt-injection via loaded files
(PDB REMARKs, trajectory metadata) is a real vector; don't point it at untrusted input.

## Commands (run from `vmd_ai/`)

- **Tests:** `python -m pytest vmdbench/tests -q`. Single test:
  `python -m pytest vmdbench/tests/test_checks.py -q -k scalar_within`. The "live" tests
  (`test_oracle.py`, `test_atlas.py`, the `*LiveTests` image classes) shell out to VMD and
  skip/error without it. Needs `pyyaml` (`pillow` only for the optional PNG image path).
- **Score / calibrate a card:** `python -m vmdbench.cli score-oracle <card.yaml> <oracle.tcl>
  [--timeout N]` — runs the reference tcl under real VMD and prints each assertion's `observed`
  value, the gated composite, and `replay_clean`. It is the *only* CLI subcommand and doubles
  as the calibration tool.
- **ATLAS cases:** `scripts/select_atlas_subset.py -n 30` → `scripts/fetch_atlas.py <chain>` →
  `scripts/make_atlas_cards.py --list scripts/atlas_subset.txt` (fetch → stride a small DCD
  fixture → generate+calibrate+verify an oracle/card per chain).
- **SciVisAgentBench arms (long — detach it):**
  `bash integrations/scivisagentbench/run_25cell_retrieval.sh rag wiki` — needs an
  OpenAI-compatible model endpoint at `http://localhost:8000/v1`.

## vmdbench verification pipeline (the cross-file part)

A **task card** (YAML in `tasks/{viz,traj,analysis,select}/`) declares
`verify.required[]`/`optional[]` assertions and its fixture files. An **oracle** (`.tcl` in
`oracles/`) is the *gold* reference solution. `verify/runner.py:verify_card()` copies
`initial_state.files` from `fixtures/` (by basename) into a workdir, runs the tcl under
`env/headless_vmd.py:HeadlessVMDEnv` (`vmd -dispdev text`), evaluates every assertion, and
gates (all `required` pass ⇒ `gate`). `score/scorer.py` maps that to per-dimension + composite
scores (a failed gate zeros the task).

**The `PROBE>` protocol is the coupling point.** HeadlessVMDEnv appends scene introspection,
and the solution emits lines like `PROBE> measure_<name>=<val>`, `mol<id>_numframes=…`,
`rep<m>_<r>_<attr>=…`. `env/scene_state.py:parse_probe_lines()` turns these into a `SceneState`
(molecules, representations, selections, **measures**, display, camera). Evaluators in
`verify/checks.py` read *only* the `SceneState` (plus `ctx.workdir` for file/image checks) — so
**to assert on anything, the solution must first emit it as a `PROBE>` line.**

**Adding an assertion kind = a 3-file change + a TDD test:**
1. `verify/checks.py` — `@_register("<kind>") def fn(where, scene, ctx, a) -> CheckResult`.
2. `spec/dimensions.py` — add `"<kind>": [Dimension.X]` to `KIND_DIMENSIONS` (this also
   auto-admits it to `KNOWN_KINDS`).
3. `spec/assertions.py` — list its required `where` keys in `_REQUIRED_WHERE` (rejects
   malformed cards at load time, not mid-run).

The correctness-focused kinds are `scalar_within` (a computed value in a band) and
`image_foreground`/`image_palette` (reference-free pixel checks that decode the render via the
pure-stdlib `env/image_probe.py`); the rest are scene-graph checks.

## Calibrating a card

Bands are **derived from the oracle, never hand-typed**: run `score-oracle`, read the
`observed` values, set the `scalar_within` / `image_*` / `frames_loaded` bounds around them, and
require both `solved:true` **and** `replay_clean:true` (determinism across repeated VMD runs).
`make_atlas_cards.py` automates this as a two-pass loop (wide bands → read observed → tight
bands → verify).

## Gotchas

- **Rendering:** `render snapshot` is a broken stub under `-dispdev text` — always
  `render TachyonInternal <file>`; `file_rendered` expects a real (>1 KB) image.
- **VMD binary** resolves via `VMD_AI_VMD_BIN` (bridge) / `--vmd` (`score-oracle` and
  `run_multistructure.py`) / config `vmd_bin`. `run_multistructure.py` carries **two** VMD
  references — the agent's `vmd_bin` *and* its own `DEFAULT_VMD` for the gold oracle — both must
  point at a real binary. Known paths: `/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64`
  (Mac dev; min 1.9.4a57), `/software/vmd-1.9.3/bin/vmd` (the `tbgl` GPU server).
- **ATLAS data is CC-BY-NC 4.0** (non-commercial + attribution) — do not commit ATLAS-derived
  `fixtures/*` without confirming that license is acceptable; provenance is in each
  `*_gold.json`. Raw multi-GB downloads live in the gitignored `.atlas_cache/`.
- **SciVisAgentBench harness** is designed to run agent+VMD locally and only call the *model*
  remotely (vLLM). Failed cases auto-save to `test_results/multistructure/<arm>/failures/`
  (`.tcl` + `.log`) with a `failures.jsonl` index.

## Git

Feature work is on branch `vmdbench-design` (off `master`). End commit messages with a
`Co-Authored-By: Claude …` trailer.
