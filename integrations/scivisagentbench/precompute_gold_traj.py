#!/usr/bin/env python3
"""precompute_gold_traj.py — compute the trajectory gold ONCE for every fixture pair and cache
it to JSON, so concurrent run_atlas_traj arms load it (via --gold-cache) instead of each
recomputing the same VMD gold. Gold is deterministic, so this is a pure speedup + consistency.

  python precompute_gold_traj.py --fixtures-dir atlas_fixtures --vmd /software/vmd-1.9.3/bin/vmd \
      --out atlas_gold_cache.json
"""
import argparse, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_atlas_traj import pairs_in, compute_gold, DEFAULT_VMD, METRICS, HARD_ORACLE, ORACLE  # noqa: E402
from hard_metrics import HARD_METRICS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures-dir", default=str(HERE / "atlas_fixtures"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--out", default=str(HERE / "atlas_gold_cache.json"))
    ap.add_argument("--hard", action="store_true", help="precompute HARD-tier gold")
    args = ap.parse_args()
    oracle = HARD_ORACLE if args.hard else ORACLE
    need = set(HARD_METRICS) if args.hard else set(METRICS)

    pairs = pairs_in(args.fixtures_dir)
    if not pairs:
        print(f"no <chain>.pdb + <chain>_*.dcd pairs in {args.fixtures_dir}")
        return 1
    cache, bad = {}, []
    for name, pdb, dcd in pairs:
        g, err = compute_gold(os.path.expanduser(args.vmd), pdb, dcd, oracle=oracle)
        missing = need - set(g)
        if g and not missing:
            cache[name] = g
            print(f"  {name}: ok  (" + ", ".join(f"{k}={round(v, 2)}" for k, v in sorted(g.items())) + ")")
        else:
            bad.append((name, err or f"missing {sorted(missing)}"))
            print(f"  {name}: FAILED — {err or f'missing {sorted(missing)}'}")
    json.dump(cache, open(args.out, "w"), indent=2, default=str)
    print(f"\nwrote {len(cache)}/{len(pairs)} chains -> {args.out}")
    if bad:
        print(f"  {len(bad)} FAILED: " + ", ".join(n for n, _ in bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
