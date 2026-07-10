# Paper outlines — vmd_ai / vmdbench

Framings for the same body of work. Recommendation: **D or B now (weeks) → A later (months)**;
fold the retrieval result (C) in as a *result*, not its own paper. **D (the tool-adoption
inversion) uses the freshest data — the cross-model sweep — and carries the most novel single
finding; B is the verification-methodology thesis. They are siblings that share the same
verified harness as their instrument.**

## Results in hand (shared evidence)

- **Completion ≠ correctness.** SciVisAgentBench rubric scored a radius of gyration of **329 Å**
  (gold 9.67) as full marks; on visualization, the agent wrote "yes, licorice" while building
  **zero representations**. Both pass the rubric; both are caught by verification.
- **Correctness ⊥ model tier.** Local Qwen-72B got Rg exact where a frontier model returned 329 Å.
- **RAG, five arms.** none / rag / ragforce / autorag / inject. Optional and reactive retrieval
  fail (the agent won't call a docs tool even when ordered); **proactive injection wins**
  (4.4 vs 2.x / 5), DocPrompting-aligned.
- **Generalization.** 5 proteins (327–9,058 atoms): inject **55 vs none 42 / 75**, gain on the
  syntax-hard measures.
- **Verification machinery.** oracle `scalar_within` (analysis) + `representation_exists` /
  scene-state assertions (visualization); gold **cross-validated** vs MDAnalysis + Biopython (19/20).
- **Reusable artifact.** every solved task emits a runnable `.tcl`.
- **Capability ≠ adoption (cross-model tool sweep, NEW).** Qwen2.5-7B/14B/72B on 465
  trajectory checks: a correct `vmd_traj_measure` primitive + enforced routing lifts the
  **7B 20.4→99%** and the **72B 16.3→100%** — a 7B matching a 72B at 1/10 the size; without
  the tool only `nframes` survives (real observables ≈0%). Surprise: the 72B *under*-adopts
  the tool under a soft nudge (**77% vs the 14B's 100%**) and self-sabotages on the metric it
  deems trivial (`nframes` 0% adoption, 78% correct). Failures are behavioral — knowingly-wrong
  17 / brace-thrash 14 / over-correction 3 — not arithmetic. *(Because the tool is verified
  correct, every failure is a delegation failure.)*

---

## Option B — Position / workshop paper  *(fastest; ~most of it exists)*

**Working title:** *Completion Is Not Correctness: Outcome Benchmarks Overstate Scientific
Visualization Agents.*

**Abstract (draft).** LLM agents are increasingly evaluated on scientific tools with
completion- or LLM-judge-based benchmarks. Using molecular visualization (VMD) as a case study,
we show this systematically overstates agent quality: a benchmark awards full marks to a radius
of gyration 34× too large and to a "rendered" image that was never drawn. We argue for
*correctness verification* — comparing computed values against a tool-computed oracle and
checking the actual scene state rather than a textual claim — and demonstrate it catches errors
both in analysis and in visualization, across models and structures. We release a verification
harness and call for correctness-grounded benchmarks for scientific agents.

**Sections**
1. **Introduction** — agents driving scientific software; how they're scored today (completion /
   LLM-judge); thesis: that overstates correctness for tasks with a ground truth.
2. **Background & related** — SciVisAgentBench; LLM-as-judge reliability limits; SWE-bench
   (execution-verified code); DocPrompting (retrieval-conditioned generation).
3. **The hollowness** — concrete failures that pass the rubric: Rg = 329 Å; the licorice false-yes.
   *(Fig 1: rubric "pass" vs oracle truth.)*
4. **Correctness verification** — `scalar_within` over an oracle for analysis; `representation_exists`
   / scene-state assertions for visualization; oracle gold cross-validated against MDAnalysis + Biopython.
5. **What it reveals** — completion-vs-correctness gap; correctness doesn't track model tier; brief
   injection prescription.
6. **Discussion & limitations** — local-model class, modest suite; a call to action.

**Figures/tables:** (1) rubric-pass vs oracle-true examples; (2) completion-score vs correctness-score
scatter per model; (3) viz none-vs-inject (licorice false-yes).

**Gap checklist (small):** tighten the evidence, add 1–2 clean cross-model examples, write. Most of
this is the existing report.

---

## Option A — Benchmark paper  *(highest impact; months of scaling)*

**Working title:** *vmdbench: A Correctness-Verified Benchmark for LLM Agents in Molecular Visualization.*

**Abstract (draft).** We present vmdbench, a benchmark that evaluates LLM agents controlling VMD by
*correctness* rather than completion: each task is checked against a tool-computed oracle (for
analysis) or scene-state assertions (for visualization), with a closed assertion vocabulary and gold
cross-validated by independent tools. Across N tasks spanning proteins, nucleic acids, membranes,
complexes, and trajectories, and M models, we find that completion/LLM-judge scores systematically
overstate correctness, that proactive knowledge injection — not optional retrieval — closes much of
the gap, and that reliability and correctness are distinct axes. We release the cards, oracles, and harness.

**Sections**
1. Introduction.
2. Related work — agent benchmarks, scientific-viz agents, execution/outcome verification.
3. **Benchmark design** — task taxonomy (analysis / visualization / trajectory × easy/medium/hard);
   closed assertion vocabulary (`scalar_within`, `representation_exists`, `display_property`,
   `file_rendered`, …); oracle gold + cross-validation; the agent adapter + headless-VMD harness.
4. **Tasks & data** — N cases over M structures (incl. multi-chain complexes + MD trajectories); how
   gold is generated and verified.
5. **Baselines** — models × {completion score, correctness score}; the leaderboard *(main table)*.
6. **Analyses** — completion-correctness gap; RAG/injection ablation; cross-structure generalization;
   reliability-vs-correctness.
7. Reproducibility & artifact.
8. Limitations & future work.

**Figures/tables:** leaderboard (completion vs correctness per model); per-category breakdown;
ablation bars; generalization across structures.

**Gap checklist (large):** scale the task suite (dozens of cases, diverse systems **including
trajectories**, difficulty tiers, all gold-verified); multi-model multi-seed runs on a dedicated GPU;
full related work; public artifact.

---

## Option D — Tool-adoption / small-model-rescue paper  *(workshop; freshest data, most novel finding)*

**Working title:** *When Bigger Under-Delegates: A Value-Verified Study of Tool Adoption in VMD
Trajectory-Analysis Agents.*

**Thesis.** Distinct from B ("completion ≠ correctness", about the *scoring*), D is about *model
behavior*: **capability ≠ adoption**. Using the verified harness as a clean instrument (a *correct*
tool ⇒ every failure is a delegation failure, not a computation failure), we surface an inverse
adoption gradient and a small-model rescue.

**Abstract (draft, ~200w).** Agentic benchmarks for scientific visualization typically score task
*completion* with an LLM judge, which cannot separate a plausible answer from a correct one. We
introduce a value-verified benchmark for VMD trajectory analysis — 31 chains × 5 trajectory-averaged
observables × 3 seeds (465 checks), each graded by comparing the agent's *computed value* to a
deterministic gold oracle and gated on cross-run reproducibility — and use it to study Qwen2.5-7B/
14B/72B driving VMD with and without a correct, brace-safe measurement tool. Two findings. (1) A
correct primitive plus enforced routing lifts a 7B from **20→99%** and a 72B from **16→100%**,
matching the large model at a tenth of the parameters; without tools only the trivial frame-count
survives (≈0% on every real observable). (2) Counterintuitively, **capability inversely predicts
tool adoption**: under a soft directive the 72B adopts the tool only **77%** of the time — *less*
than the 14B's 100% — and self-sabotages precisely on the metric it deems trivial (`nframes`: 0%
adoption, 78% correct), while smaller models defer and stay correct. Enforced routing eliminates the
gap. We argue value-verification and adoption-aware routing — not raw scale — govern the reliability
of tool-using scientific agents.

**Contributions**
1. A **value-verified** viz-agent benchmark (465 checks; gold-oracle *value* comparison + a
   `replay_clean` determinism gate) — a ground-truth alternative to LLM-judged / completion scoring.
2. **Small-model rescue** — correct tool + enforced routing takes a 7B 20.4→99% and a 72B 16.3→100%;
   the no-tool arm collapses to the single hand-computable metric (nframes 100%, real observables ≈0%).
3. **The inverse adoption gradient** — capability *negatively* correlates with adoption; the strongest
   model under-delegates on tasks it deems easy and fails them; directive strength is the lever.
4. A **behavioral failure taxonomy** (knowingly-wrong / brace-thrash / over-correction) made legible
   only by value-verification — failures are delegation/behavior, not arithmetic.

**Sections**
1. **Introduction** — judges can't tell plausible from correct; agents wrap correct expert tools;
   open question: does *scale* or *scaffolding* govern reliability? State the two findings.
2. **Related work** — ground-truth agent benchmarks (SWE-bench tests) vs judge/completion viz
   benchmarks (SciVisAgentBench); tool-selection benchmarks (BFCL, τ-bench, ToolBench); over-/under-
   reliance on tools; scientific LLM agents (ChemCrow, Coscientist).
3. **Benchmark design (the instrument)** — ATLAS trajectories; `PROBE>` protocol; gold oracle;
   oracle-derived `scalar_within` bands; the `replay_clean` determinism gate; the 465-check grid.
4. **Setup** — Qwen2.5-7B/14B/72B via local vLLM; arms `none` / soft / mandatory routing; the
   `vmd_traj_measure` tool. **Up front:** the tool mirrors the oracle, so it measures *execution
   reliability + adoption*, not analysis reasoning.
5. **Results** — (a) `none→tool` rescue table; (b) per-metric collapse without tools; (c) the
   adoption inversion + per-metric adoption; (d) failure taxonomy.
6. **Discussion** — capability ≠ adoption; enforced routing as the practical lever; deployment
   implication (a cheap, private, on-prem 7B + correct tools beats a 72B on reliability).
7. **Conclusion & future** — a harder tier that *underspecifies* the task (model must choose the
   analysis) to promote the benchmark from reliability to reasoning; more tool + model families.

**Figures/tables:** (1) rescue table none/soft/mandatory × 7B/14B/72B; (2) per-metric none collapse
(7B: nframes 100%, rest ≈0%); (3) adoption inversion (soft-directive adoption% vs model size);
(4) failure-taxonomy bars.

**Threats to validity (state up front):** 72B is **AWQ + an older code path** — land the clean
72B re-run before submission to harden the central inversion claim; **adoption% is transcript-
inferred**, not logged (tool-derived%, value==gold to 1e-9, is the reliable proxy — add direct
per-case tool-call logging); single domain / tool-family / model-family; suite saturates at 100%.

**Gap checklist (small):** clean 72B re-run (the one that matters); 14B `none` cell (pending);
direct tool-call logging; write. The rescue + inversion numbers, harness, and figures already exist.

---

## Shared next build (feeds both)

A **multi-model baseline** — Claude, GPT, Qwen variants, (Llama) through the *same* harness,
multi-seed, dedicated GPU — producing a per-model **completion-vs-correctness** table. That table is
B's key figure and A's backbone. (Scaffolded in `run_baselines.sh` + `compare_models.py`.)
