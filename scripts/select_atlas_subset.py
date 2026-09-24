#!/usr/bin/env python3
"""select_atlas_subset.py — pick a size-stratified, non-redundant ATLAS subset for benchmarking.

Reads the ATLAS catalog (the *_ATLAS_info.tsv inside the /parsable bundle), filters to
non-redundant chains within a length window, then deterministically stratifies by length so
the subset spans small->large (variety in size, fold, and flexibility comes along). Writes a
manifest TSV (chain + gold + estimated download size) and a plain chain list for batch fetch.

  python scripts/select_atlas_subset.py -n 30 --max-len 150
  python scripts/select_atlas_subset.py -n 50 --min-len 50 --max-len 250 --all

Catalog + downloads are cached under .atlas_cache/ (gitignored). ATLAS data is CC-BY-NC 4.0.
"""
from __future__ import annotations
import argparse, csv, glob, sys, urllib.request, zipfile
from pathlib import Path

PARSABLE = "https://www.dsimb.inserm.fr/ATLAS/api/parsable"
REPO = Path(__file__).resolve().parents[1]
MB_PER_RES = 93.6 / 415.0   # 16pk_A (415 res) analysis bundle = 93.6 MB -> linear estimate


def load_catalog(cache):
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    hits = glob.glob(str(cache / "**" / "*ATLAS_info.tsv"), recursive=True)
    if not hits:
        z = cache / "parsable.zip"
        if not z.exists():
            req = urllib.request.Request(PARSABLE, headers={"User-Agent": "vmdbench"})
            with urllib.request.urlopen(req, timeout=180) as r:
                z.write_bytes(r.read())
        with zipfile.ZipFile(z) as zf:
            zf.extractall(cache)
        hits = glob.glob(str(cache / "**" / "*ATLAS_info.tsv"), recursive=True)
    return list(csv.DictReader(open(sorted(hits)[0]), delimiter="\t"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--num", type=int, default=30)
    ap.add_argument("--min-len", type=int, default=40)
    ap.add_argument("--max-len", type=int, default=150)
    ap.add_argument("--all", action="store_true", help="include redundant chains too")
    ap.add_argument("--cache", default=str(REPO / ".atlas_cache"))
    ap.add_argument("--out", default=str(REPO / "scripts" / "atlas_subset.tsv"))
    args = ap.parse_args()

    rows = load_catalog(args.cache)

    def L(r):
        try:
            return int(float(r["length"]))
        except (ValueError, KeyError):
            return -1

    def nr(r):
        return str(r.get("non_redundant_protein", "")).lower() in ("true", "1", "yes")

    pool = [r for r in rows if args.min_len <= L(r) <= args.max_len and (args.all or nr(r))]
    pool.sort(key=L)
    if not pool:
        print("no chains match the filter"); return 1

    # deterministic size-stratified pick: evenly-spaced indices across the length-sorted pool
    n = min(args.num, len(pool))
    idx = sorted(set(round(i * (len(pool) - 1) / (n - 1)) for i in range(n))) if n > 1 else [0]
    pick = [pool[i] for i in idx]
    j = 0
    while len(pick) < n and j < len(pool):   # backfill any rounding collisions
        if pool[j] not in pick:
            pick.append(pool[j])
        j += 1
    pick.sort(key=L)

    cols = ["PDB", "length", "avg_RMSF", "avg_gyration", "alpha%", "beta%", "coil%", "protein_name"]
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(cols + ["est_dl_MB"])
        for r in pick:
            w.writerow([r.get(c, "") for c in cols] + [round(L(r) * MB_PER_RES, 1)])
    out.with_suffix(".txt").write_text("\n".join(r["PDB"] for r in pick) + "\n")

    print(f"selected {len(pick)} / {len(pool)} eligible chains  "
          f"(len {args.min_len}-{args.max_len}, {'all' if args.all else 'non-redundant'})\n")
    print(f"  {'chain':9}{'len':>4}{'RMSF':>6}{'Rg':>7}{'a/b/coil':>12}{'~MB':>6}  name")
    tot = 0.0
    for r in pick:
        mb = L(r) * MB_PER_RES; tot += mb
        abc = f"{r.get('alpha%','?')}/{r.get('beta%','?')}/{r.get('coil%','?')}"
        print(f"  {r['PDB']:9}{L(r):>4}{r.get('avg_RMSF','?'):>6}{r.get('avg_gyration','?'):>7}"
              f"{abc:>12}{mb:>6.0f}  {(r.get('protein_name') or '')[:34]}")
    print(f"\n  total raw download ~{tot/1024:.1f} GB  |  strided fixtures ~{len(pick)*0.3:.0f} MB committable")
    print(f"  manifest -> {out}")
    print(f"  chain list -> {out.with_suffix('.txt')}")
    print(f"  batch fetch:  while read c; do python scripts/fetch_atlas.py $c --stride 25; done < {out.with_suffix('.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
