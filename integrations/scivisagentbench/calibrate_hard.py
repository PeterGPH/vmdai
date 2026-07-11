#!/usr/bin/env python3
"""calibrate_hard.py — derive HARD-tier tolerances from the oracle (never hand-typed).

Runs gold_oracle_traj_hard.tcl over every fixture pair, collects each scored key's gold values
across chains, and prints the distribution + a recommended absolute tolerance. Copy the
recommended values into hard_metrics.py, then re-run to confirm. Determinism is enforced
separately by replay_clean; this only sizes the accept band.

  python integrations/scivisagentbench/calibrate_hard.py --fixtures-dir vmdbench/fixtures \
      --vmd "$VMD_AI_VMD_BIN"
"""
import argparse, os, sys, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_atlas_traj import pairs_in, compute_gold, DEFAULT_VMD, HARD_ORACLE  # noqa: E402
from hard_metrics import HARD_METRICS  # noqa: E402

# per-key floor: the smallest tolerance that still absorbs VMD jitter + definitional variants.
# rg_argmin_frame is an exact integer (band 0.5); the rest floor at a physically negligible error.
FLOORS = {"rg_std": 0.02, "rmsd_max": 0.05, "sasa_range": 30.0, "rmsf_max": 0.05,
          "rg_argmin_frame": 0.5, "rg_delta": 0.05, "rg_ratio": 0.005}


def recommend_tol(values, frac=0.03, floor=0.0):
    """A tolerance = max(floor, frac * median(|value|)). Empty -> floor."""
    if not values:
        return floor
    med = statistics.median(abs(v) for v in values)
    return max(floor, frac * med)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=str(HERE / "atlas_fixtures"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--frac", type=float, default=0.03, help="tol as fraction of median magnitude")
    args = ap.parse_args()

    pairs = pairs_in(args.fixtures_dir)
    if not pairs:
        print(f"no fixture pairs in {args.fixtures_dir}"); return 1
    cols = {k: [] for k in HARD_METRICS}
    for name, pdb, dcd in pairs:
        g, err = compute_gold(os.path.expanduser(args.vmd), pdb, dcd, oracle=HARD_ORACLE)
        if not g:
            print(f"  {name}: FAILED {err}"); continue
        for k in cols:
            if k in g:
                cols[k].append(g[k])
    print(f"\n{'key':18}{'n':>4}{'min':>12}{'median':>12}{'max':>12}{'recommend_tol':>16}")
    for k in HARD_METRICS:
        vs = cols[k]
        if not vs:
            print(f"{k:18}{0:>4}{'-':>12}{'-':>12}{'-':>12}{'-':>16}"); continue
        tol = recommend_tol(vs, frac=args.frac, floor=FLOORS.get(k, 0.0))
        print(f"{k:18}{len(vs):>4}{min(vs):>12.3f}{statistics.median(vs):>12.3f}"
              f"{max(vs):>12.3f}{tol:>16.3f}")
    print("\ncopy each recommend_tol into HARD_METRICS[...] tol, then re-run the oracle test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
