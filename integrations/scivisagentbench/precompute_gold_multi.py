#!/usr/bin/env python3
"""precompute_gold_multi.py — compute the static-structure gold ONCE and cache to JSON, so
concurrent run_multistructure arms load it (--gold-cache) instead of each recomputing.

  python precompute_gold_multi.py --structures-dir fixtures_multi \
      --vmd /software/vmd-1.9.3/bin/vmd --out gold_cache_multi.json
"""
import argparse, glob, json, os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_multistructure import compute_gold, DEFAULT_VMD, METRICS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", default=str(HERE / "fixtures_multi"))
    ap.add_argument("--vmd", default=DEFAULT_VMD)
    ap.add_argument("--out", default=str(HERE / "gold_cache_multi.json"))
    args = ap.parse_args()

    structs = sorted(glob.glob(os.path.join(args.structures_dir, "*.pdb"))
                     + glob.glob(os.path.join(args.structures_dir, "*.cif")))
    if not structs:
        print(f"no structures in {args.structures_dir}")
        return 1
    need = set(METRICS)   # the SCORED metrics (the oracle emits a few extra)
    cache, bad = {}, []
    for s in structs:
        name = Path(s).stem.upper()
        g, err = compute_gold(os.path.expanduser(args.vmd), s)
        missing = need - set(g)
        if g and not missing:
            cache[name] = g
            print(f"  {name}: ok")
        else:
            bad.append((name, err or f"missing {sorted(missing)}"))
            print(f"  {name}: FAILED — {err or f'missing {sorted(missing)}'}")
    json.dump(cache, open(args.out, "w"), indent=2, default=str)
    print(f"\nwrote {len(cache)}/{len(structs)} structures -> {args.out}")
    if bad:
        print("  FAILED: " + ", ".join(n for n, _ in bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
