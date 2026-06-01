# VMD-LLM-Native Bench (`vmdbench`)

Measures how *LLM-native* VMD operation is: can an LLM understand the scene,
choose valid actions, verify the result, recover, and export a reproducible workflow.
Design spec: `../docs/superpowers/specs/2026-05-29-vmd-llm-native-bench-design.md`.

## Status: Plan 1 (Foundation) — LLM-free core
- `spec/`    task cards, closed assertion vocabulary, the 6 dimensions
- `env/`     canonical SceneState + HeadlessVMDEnv (drives `vmd -dispdev text`)
- `adapters/oracle_tcl.py`  reference-solution runner (verifier upper bound)
- `verify/`  assertion evaluators + runner (gate)
- `score/`   gated composite + per-dimension subscores
- `tasks/` + `oracles/`  three exemplar cards with reference solutions

## Requirements
- VMD on PATH (developed against 1.9.4a57; see `VERSION`)
- `pip install pyyaml`

## Run the bench on a reference solution
Run from the package parent (`vmd_ai/`) so `python -m` puts it on `sys.path`:
```
python -m vmdbench.cli score-oracle vmdbench/tasks/viz/viz_protein_dna_001.yaml vmdbench/oracles/viz_protein_dna_001.tcl
```

## Run the tests
Also from `vmd_ai/`:
```
python -m pytest vmdbench/tests -v
```

## Headless rendering note
`render snapshot` does NOT work in `-dispdev text` (produces an invalid stub).
Use `render TachyonInternal <file>`; the `file_rendered` assertion expects a real
(>1 KB) image.

## Not yet implemented (Plans 2–4)
- ChatVMD adapter (live LLM runs, raw-Tcl track), `harness/` factorial, provenance/version-pinning, 429 isolation
- Typed-tool track + `get_scene_state` observation; observability & workflow-efficiency scoring
- Recovery track (fault injection); `report/` leaderboard + radar; full ~40–50 task dataset
