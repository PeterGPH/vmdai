# Design spec — vmdbench hard/reasoning tier (trajectory-analysis)

- **Date:** 2026-07-10
- **Branch:** `vmdbench-design`
- **Status:** approved design, pending implementation plan
- **Scope of this spec:** trajectory-analysis only (the ATLAS-traj benchmark path). Visualization
  and selection tiers are explicitly out of scope for v1.

## 1. Problem

The current ATLAS-traj benchmark is **saturated**: a correct semantic tool (`vmd_traj_measure`)
that mirrors the gold oracle drives a 7B to ~99% and a 72B to 100%. The cause is that the prompt
hands over the entire solution. The rendered prompt for `meanrg` today is:

```
You are controlling VMD headlessly through the run_vmd_command tool (Tcl).
1. Load the structure and ITS TRAJECTORY (both files):
     mol new "<pdb>" waitfor all
     mol addfile "<dcd>" waitfor all
2. Compute the MEAN radius of gyration of the protein AVERAGED over ALL trajectory
   frames, in Angstroms. Loop over all frames: 'set n [molinfo top get numframes]',
   then for each frame set the selection's frame with '$sel frame $i' before measuring.
3. Write ONLY that single numeric value (digits only, no words) to <answer_path>.
Finish in as few commands as possible.
```

Five giveaways are supplied for free: ① the metric ("radius of gyration"), ② the formula
("MEAN … AVERAGED over ALL frames"), ③ the selection ("of the protein"), ④ the VMD idiom (the
`numframes` + `$sel frame $i` loop), ⑤ the output plumbing. The task is transcription, not
reasoning, so a tool that mirrors the oracle wins trivially.

## 2. Goal & success criteria

A parallel task set over the **same ATLAS fixtures** where the prompt describes a *scientific
quantity in plain language* — no metric name, no formula, no VMD command — and the answer is a
**composed** quantity the semantic tool cannot answer in a single call. Gold stays a single
determinate, reproducible number.

**Success:**
1. The easy tier stays ~100% (tool arm) but the hard tier drops materially — target: strong,
   tool-equipped models well below 100%.
2. The `none → tool` lift is **smaller** on the hard tier than on the easy tier — i.e. the tool
   cannot rescue *formulation*. This gap is the paper's headline.

**Non-goals (v1):** categorical / ranking / label answers (the type-(ii) "choice" questions);
visualization or selection tasks; new model training.

## 3. Task catalog

All quantities are computed from four per-frame series the oracle already builds — `rg[i]`
(protein radius of gyration at frame `i`), `sasa[i]` (protein SASA at frame `i`), `rmsd[i]`
(Cα RMSD of frame `i` to frame 0 after `measure fit`), and the per-residue vector `rmsf[r]`
(Cα RMSF) — so every gold value is exact and reproducible.

| # | Key | Plain-science prompt (intent) | Gold formula | Unit |
|---|-----|-------------------------------|--------------|------|
| **H1 — a statistic other than the mean** |
| 1 | `rg_std` | "how much does the protein's overall size fluctuate over the trajectory?" | population std-dev of `rg[i]` | Å |
| 2 | `rmsd_max` | "the largest deviation of the backbone from the starting structure at any point" | `max_i rmsd[i]` | Å |
| 3 | `sasa_range` | "how much does the exposed surface area swing between its most- and least-exposed frames?" | `max(sasa) − min(sasa)` | Å² |
| 4 | `rmsf_max` | "the mobility of the single most mobile residue" | `max_r rmsf[r]` | Å |
| **H2 — locate an extreme (still numeric)** |
| 5 | `rg_argmin_frame` | "at which frame is the protein most compact?" | `argmin_i rg[i]` | frame index (int) |
| **H3 — relational / two-point** |
| 6 | `rg_delta` | "how much larger or smaller is the protein at the end vs the start?" | `rg[last] − rg[first]` (signed) | Å |
| 7 | `rg_ratio` | "by what factor does its size change from start to end?" | `rg[last] / rg[first]` | dimensionless |
| **H4 — conditional (stretch, ship after H1–H3)** |
| 8 | `rg_frac_above_mean` | "for what fraction of the trajectory is the protein larger than its average size?" | `#{i : rg[i] > mean(rg)} / n` | fraction 0–1 |

**v1 = H1–H3 (7 tasks) × 31 chains ≈ 217 checks/seed.** H4 is a stretch item. Each task carries an
`intended_quantity` annotation (used by the spec-adequacy guardrail, §8).

## 4. Prompt design (recipe stripped)

Keep the mechanical plumbing (the load lines and the file-write line) so the experiment isolates
exactly one variable — *formulation* — and strip the three reasoning giveaways (metric, formula,
loop idiom):

```
You are controlling VMD headlessly through the run_vmd_command tool (Tcl).
Load this structure and its trajectory:
    mol new "<pdb>" waitfor all
    mol addfile "<dcd>" waitfor all
<SCIENTIFIC QUESTION — plain terms, no metric name / command / loop idiom>
Report a single number (<unit>) and write ONLY that value to:
    set f [open "<answer>" w]; puts $f $value; close $f
```

`build_hard_prompt(pdb, dcd, question, unit, answer_path)` fills this template. A unit test asserts
the produced prompt contains **none** of `rgyr`, `measure`, `numframes`, `rmsf`, `sasa`, `fit`
(the giveaway tokens).

## 5. Gold oracle extension

New file **`gold_oracle_traj_hard.tcl`** (the easy `gold_oracle_traj.tcl` is left untouched). One
deterministic pass builds the `rg[]`, `sasa[]`, `rmsd[]`, and `rmsf[]` series with the same loops
already present in the easy oracle, then emits each derived quantity as a `GOLD <key> <value>`
line (the protocol the harness already parses):

```
GOLD rg_std <v>
GOLD rmsd_max <v>
GOLD sasa_range <v>
GOLD rmsf_max <v>
GOLD rg_argmin_frame <int>
GOLD rg_delta <v>
GOLD rg_ratio <v>
GOLD rg_frac_above_mean <v>     ;# stretch
```

Each block is `catch{}`-wrapped and emits `GOLD_ERROR <key> <msg>` on failure, matching the easy
oracle's behavior. **Definitions fixed in the oracle** (to keep gold determinate): `rg_std` is the
*population* standard deviation (divide by `n`); `rg_argmin_frame` is 0-based; `rg_frac_above_mean`
uses strict `>`.

## 6. Scoring & calibration

- Reuse **`scalar_within`** with **oracle-derived bands** via the existing two-pass calibration
  (wide band → read observed → tight band). A new gold cache file `gold_cache_<fix>_hard.json`
  keeps hard gold separate from easy gold.
- Gate on **`replay_clean`** (determinism across repeated VMD runs) exactly as today.
- **Bands must absorb defensible definitional variants** (see §8): e.g. population-vs-sample
  std-dev differ by `sqrt(n/(n-1))` (~2% at n≈25), so `rg_std`'s tolerance is set wide enough to
  accept both. `rg_delta`, `rg_ratio`, `rmsd_max`, `sasa_range`, `rmsf_max` have unambiguous
  single definitions.
- **`rg_argmin_frame` is the determinism/uniqueness risk.** It is scored as an **exact integer
  match** (`scalar_within` band ±0.5). At calibration, a chain **keeps** the task only if its
  minimum-Rg frame is unique with a clear margin — the next-smallest frame's Rg must exceed the
  minimum by ≥ 0.5% of the minimum (comfortably above VMD's run-to-run numerical jitter, which
  `replay_clean` already bounds). Chains that fail this margin **drop** the task; the keep/drop
  decision is recorded per chain at calibration time.

## 7. Integration & file layout (minimal, isolated)

- `gold_oracle_traj_hard.tcl` — new (§5).
- `hard_metrics.py` — new. Holds `HARD_METRICS = {key: (question, unit, tol, intended_quantity)}`
  and `build_hard_prompt()`.
- `run_atlas_traj.py` — reused via a `--hard` switch that selects `HARD_METRICS`, the hard oracle,
  the hard gold cache, and a `hard_*` tag namespace. **The easy code path is unchanged.**
- Reuse unchanged: the per-(chain, metric, seed) loop, `scalar_within`, `replay_clean`, the gold
  cache mechanism, the failure-capture/`failures.jsonl`, and the scoreboard.

## 8. Guardrails

**Spec-adequacy (the SWE-bench-Verified lesson).** Each task carries an `intended_quantity`. Before
a full run, **pilot on a strong, tool-equipped model**; classify each miss as either **hard**
(right quantity, wrong execution) or **ambiguous** (a defensible *different* quantity). Ambiguous
wordings are reworded or their tolerance widened to accept the variants. This is what prevents the
tier from being "unsolvable by construction" rather than "hard."

**Determinism.** Every hard gold must pass `replay_clean`. `rg_argmin_frame` gets the explicit
uniqueness check in §6.

## 9. Testing (TDD)

- **Gold formulas:** unit-test `gold_oracle_traj_hard.tcl`'s outputs against a tiny,
  hand-checkable synthetic trajectory (a handful of frames with known Rg/SASA/RMSD/RMSF) so each
  formula (`std`, `max`, `range`, `argmin`, `delta`, `ratio`, `frac`) is verified independently of
  VMD's larger machinery. (Live test — skips without VMD, matching the existing `*LiveTests`.)
- **Prompt stripping:** unit-test `build_hard_prompt()` output contains none of the giveaway tokens
  (§4) and does contain the load + write plumbing.
- **Catalog integrity:** unit-test every `HARD_METRICS` key has a matching `GOLD <key>` emitted by
  the oracle and a non-empty `intended_quantity`.

## 10. Evaluation plan

Run **both arms** (`none` + tool) × the existing model set (Qwen2.5 7B/14B/72B) on the hard tier,
seeds as today. Expected outcome table (to be filled by the run):

| tier | none | tool (soft) | tool (mandatory) |
|------|------|-------------|------------------|
| easy | 16–20% | ~99% | ~100% |
| hard | (low) | **≪100%** | **≪100%** |

The claim is the *interaction*: on the hard tier the tool's lift shrinks, because it cannot supply
the formulation.

## 11. Risks / open items

- **Difficulty may still be too low** if models decode the plain-science wording easily. Mitigation:
  the composed quantities (§3) have no single `measure` command; if a model still one-shots them,
  escalate to H4-style conditionals and the deferred type-(ii) choice questions.
- **`rg_argmin_frame` determinism** — handled per-chain at calibration (§6); may be dropped for some
  chains.
- **Band width vs discrimination** — bands wide enough to absorb definitional variants (§6) must
  still be tight enough to fail a wrong quantity. Calibration checks that the *intended* value and
  the nearest *alternative* quantity fall on opposite sides of the band.

## 12. Out of scope / future

Type-(ii) choice/ranking/label questions (needs a new `categorical_match` verifier); a
visualization/selection hard tier; mining tasks from published papers/scripts (the SWE-bench-style
construction pipeline) to scale beyond the reused ATLAS fixtures.
