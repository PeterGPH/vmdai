#!/usr/bin/env python3
"""
aggregate_seeds.py — merge N rag_wiki_ab.py out-dirs (one per seed) into
a single multi-seed report with means and standard deviations.

Why this exists
---------------
A single rag_wiki_ab.py run produces one scorecard.csv. Across 3+ seeds,
you want to know: for each (prompt, arm), what's the mean and standard
deviation of idiom_coverage and citation_rate? And: across all prompts,
what's the per-arm mean ± std vs the baseline?

Without this, single-seed numbers look more precise than they are. The
std across seeds is the honest measure of how much of an effect is real
vs noise. A Δidiom of +0.10 with σ = 0.04 is a result; the same +0.10
with σ = 0.15 is noise.

Usage
-----
    python scripts/aggregate_seeds.py \\
        rag_wiki_results_v1_ollama_seed1 \\
        rag_wiki_results_v1_ollama_seed2 \\
        rag_wiki_results_v1_ollama_seed3 \\
        --out-dir rag_wiki_results_v1_ollama_agg

Outputs
-------
    <out-dir>/multi_seed_summary.json
    <out-dir>/multi_seed_scorecard.csv    one row per (prompt, arm) with
                                          mean / std / n_seeds across the
                                          N input dirs
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


METRICS = (
    "idiom_coverage",
    "cited_any",
    "vmd_commands",
    "search_queries",
    "wiki_reads",
    "wiki_updates",
    "elapsed_s",
    "pages_filed",
)


def _read_scorecard(d: Path) -> List[Dict[str, str]]:
    sc = d / "scorecard.csv"
    if not sc.exists():
        raise SystemExit(f"missing scorecard: {sc}")
    with sc.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return statistics.stdev(xs)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "in_dirs", nargs="+",
        help="One or more rag_wiki_ab.py output directories (seed 1, "
             "seed 2, …). Each must contain scorecard.csv.",
    )
    p.add_argument(
        "--out-dir", default="rag_wiki_seeds_agg",
        help="Where to write multi_seed_scorecard.csv + "
             "multi_seed_summary.json (default: ./rag_wiki_seeds_agg).",
    )
    p.add_argument(
        "--baseline", default="none",
        help="Arm to use as the no-retrieval baseline for Δ computation "
             "(default: none).",
    )
    args = p.parse_args(argv)

    in_dirs = [Path(d).expanduser().resolve() for d in args.in_dirs]
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per (prompt, arm) → list of metric dicts, one per seed.
    cells: Dict[Tuple[str, str], List[Dict[str, float]]] = defaultdict(list)
    seed_labels: List[str] = []
    for d in in_dirs:
        seed_labels.append(d.name)
        for row in _read_scorecard(d):
            key = (row["prompt_id"], row["arm"])
            cells[key].append({m: _f(row.get(m, "")) for m in METRICS})

    # --- per (prompt, arm) means / stds ----------------------------------
    out_rows: List[Dict[str, str]] = []
    for (pid, arm), seed_rows in sorted(cells.items()):
        row: Dict[str, str] = {
            "prompt_id": pid,
            "arm": arm,
            "n_seeds": str(len(seed_rows)),
        }
        for m in METRICS:
            vals = [r[m] for r in seed_rows]
            row[f"{m}_mean"] = f"{statistics.mean(vals):.4f}"
            row[f"{m}_std"] = f"{_std(vals):.4f}"
        out_rows.append(row)

    csv_path = out_dir / "multi_seed_scorecard.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        if out_rows:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            w.writeheader()
            for r in out_rows:
                w.writerow(r)

    # --- per-arm headline (mean across all prompts, σ across seeds) ------
    by_arm: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    for (pid, arm), seed_rows in cells.items():
        # For each prompt, average the seeds first to get one number per
        # prompt — then later we take the mean across prompts. This keeps
        # prompts weighted equally regardless of how many seeds they got.
        prompt_means = {
            m: statistics.mean([r[m] for r in seed_rows]) for m in METRICS
        }
        by_arm[arm].append(prompt_means)

    arm_summary: Dict[str, Dict[str, float]] = {}
    for arm, prompt_rows in by_arm.items():
        n = len(prompt_rows)
        agg = {"n_prompts": float(n)}
        for m in METRICS:
            vals = [r[m] for r in prompt_rows]
            agg[f"{m}_mean"] = statistics.mean(vals) if vals else 0.0
            agg[f"{m}_std_across_prompts"] = _std(vals)
        arm_summary[arm] = agg

    # --- deltas + interaction (vs baseline, mean across prompts) ---------
    baseline = arm_summary.get(args.baseline) or {}
    deltas: Dict[str, Dict[str, float]] = {}
    if baseline:
        for arm, vals in arm_summary.items():
            if arm == args.baseline:
                continue
            deltas[arm] = {
                "Δidiom_coverage_mean":
                    vals["idiom_coverage_mean"]
                    - baseline["idiom_coverage_mean"],
                "Δcitation_rate_mean":
                    vals["cited_any_mean"] - baseline["cited_any_mean"],
                "Δavg_elapsed_s":
                    vals["elapsed_s_mean"] - baseline["elapsed_s_mean"],
            }

    interaction = None
    if all(a in deltas for a in ("rag", "wiki", "both")):
        interaction = {
            "idiom_coverage":
                deltas["both"]["Δidiom_coverage_mean"]
                - (deltas["rag"]["Δidiom_coverage_mean"]
                   + deltas["wiki"]["Δidiom_coverage_mean"]),
            "citation_rate":
                deltas["both"]["Δcitation_rate_mean"]
                - (deltas["rag"]["Δcitation_rate_mean"]
                   + deltas["wiki"]["Δcitation_rate_mean"]),
        }

    summary = {
        "seeds": seed_labels,
        "n_seeds": len(seed_labels),
        "baseline_arm": args.baseline,
        "per_arm": arm_summary,
        "deltas_vs_baseline": deltas,
        "interaction_both_minus_rag_plus_wiki": interaction,
    }
    summary_path = out_dir / "multi_seed_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # --- text headline ---------------------------------------------------
    bar = "─" * 68
    print(bar)
    print(f"Multi-seed aggregation ({len(seed_labels)} seeds)")
    print(bar)
    print(f"seeds : {seed_labels}")
    print()
    print(f"{'arm':<8} {'n_pr':>5}  {'idiom µ':>8}  {'idiom σ':>8}  "
          f"{'cite µ':>7}  {'sec µ':>6}")
    for arm in sorted(arm_summary.keys()):
        v = arm_summary[arm]
        print(f"{arm:<8} {int(v['n_prompts']):>5}  "
              f"{v['idiom_coverage_mean']:>8.3f}  "
              f"{v['idiom_coverage_std_across_prompts']:>8.3f}  "
              f"{v['cited_any_mean']:>7.2f}  "
              f"{v['elapsed_s_mean']:>6.1f}")
    if deltas:
        print()
        print(f"Δ vs '{args.baseline}':")
        for arm, d in deltas.items():
            print(f"  {arm:<6}  Δidiom={d['Δidiom_coverage_mean']:+.3f}  "
                  f"Δcite={d['Δcitation_rate_mean']:+.2f}  "
                  f"Δsec={d['Δavg_elapsed_s']:+.1f}")
    if interaction:
        print()
        print(
            "interaction (Δboth − Δrag − Δwiki): "
            f"idiom={interaction['idiom_coverage']:+.3f}  "
            f"cite={interaction['citation_rate']:+.2f}"
        )
    print()
    print(f"wrote {csv_path}")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
