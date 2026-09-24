#!/usr/bin/env python3
"""fetch_atlas.py — pull one ATLAS chain's MD trajectory into a small vmdbench fixture.

ATLAS (https://www.dsimb.inserm.fr/ATLAS) ships standardized 100 ns all-atom MD per
representative protein chain. This grabs ONE chain's analysis bundle (protein-only,
1000 frames), strides one replica down to a tiny committable trajectory, copies the
topology PDB, and records the ATLAS gold (mean Rg / mean RMSF) for scalar_within bands.

  python scripts/fetch_atlas.py 2erl_A                 # fetch + stride (every 25th frame)
  python scripts/fetch_atlas.py 2erl_A --stride 20 --replica 1
  python scripts/fetch_atlas.py 2erl_A --check         # metadata only (length + gold), no download

LICENSE: ATLAS data is CC-BY-NC 4.0 (attribution + NON-COMMERCIAL). Only commit derived
fixtures if that is acceptable for this repo; keep the provenance written to <chain>_gold.json.
"""
from __future__ import annotations
import argparse, glob, json, os, shutil, statistics, subprocess, sys, urllib.request, zipfile
from pathlib import Path

API = "https://www.dsimb.inserm.fr/ATLAS/api/ATLAS"
DEFAULT_VMD = "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64"
REPO = Path(__file__).resolve().parents[1]   # .../vmd_ai


def _get(url, dest=None, timeout=600):
    req = urllib.request.Request(url, headers={"User-Agent": "vmdbench-fetch_atlas"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    if dest:
        Path(dest).write_bytes(data)
        return dest
    return data


def metadata(chain):
    return json.loads(_get(f"{API}/metadata/{chain}").decode())[chain]


def _mean_col(tsv, prefix):
    """Mean over every numeric cell of columns whose header starts with `prefix`."""
    rows = [l.rstrip("\n").split("\t") for l in open(tsv) if l.strip()]
    cols = [i for i, h in enumerate(rows[0]) if h.strip().startswith(prefix)]
    vals = []
    for r in rows[1:]:
        for i in cols:
            try:
                vals.append(float(r[i]))
            except (ValueError, IndexError):
                pass
    return round(statistics.mean(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser(description="Fetch one ATLAS chain into a small vmdbench trajectory fixture.")
    ap.add_argument("chain", help="ATLAS pdb_chain, e.g. 2erl_A (lowercase pdb id + _ + chain)")
    ap.add_argument("--variant", default="analysis", choices=["analysis", "protein", "total"],
                    help="analysis=1000 frames protein-only (default); protein=10000; total=+solvent (huge)")
    ap.add_argument("--replica", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--stride", type=int, default=25, help="keep every Nth frame of the 1000-frame source")
    ap.add_argument("--dest", default=str(REPO / "vmdbench" / "fixtures"))
    ap.add_argument("--cache", default=str(REPO / ".atlas_cache"))
    ap.add_argument("--vmd", default=os.environ.get("VMD_BIN", DEFAULT_VMD))
    ap.add_argument("--check", action="store_true", help="print metadata (length + gold) only; no download")
    args = ap.parse_args()

    md = metadata(args.chain)
    print(f"[atlas] {args.chain}: {md.get('protein_name')}  length={md.get('length')}  "
          f"avg_gyration={md.get('avg_gyration')} A  avg_RMSF={md.get('avg_RMSF')} A  "
          f"(a/b/coil {md.get('alpha%')}/{md.get('beta%')}/{md.get('coil%')})")
    if args.check:
        return 0

    cache = Path(args.cache); cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / f"{args.chain}_{args.variant}.zip"
    if not zip_path.exists():
        print(f"[atlas] downloading {args.variant} bundle ...")
        _get(f"{API}/{args.variant}/{args.chain}", dest=zip_path)
    ex = cache / f"{args.chain}_{args.variant}"
    if ex.exists():
        shutil.rmtree(ex)
    ex.mkdir()
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(ex)

    def one(pat):
        hits = sorted(glob.glob(str(ex / "**" / pat), recursive=True))
        return hits[0] if hits else None

    pdb = one("*.pdb")
    xtc = one(f"*_R{args.replica}.xtc") or one("*.xtc")
    if not pdb or not xtc:
        print(f"[atlas] ERROR: pdb/xtc not found under {ex}")
        return 1
    mean_rg = (_mean_col(one("*gyr*.tsv"), "gyr") if one("*gyr*.tsv") else None)
    mean_rmsf = (_mean_col(one("*RMSF*.tsv"), "RMSF") if one("*RMSF*.tsv") else None)
    mean_rmsd = (_mean_col(one("*RMSD*.tsv"), "RMSD") if one("*RMSD*.tsv") else None)

    dest = Path(args.dest); dest.mkdir(parents=True, exist_ok=True)
    fix_pdb = dest / f"{args.chain}.pdb"
    fix_dcd = dest / f"{args.chain}_R{args.replica}_s{args.stride}.dcd"
    shutil.copyfile(pdb, fix_pdb)

    # stride the (already protein-only) trajectory into a tiny DCD via VMD; skip frame 0
    # (the minimized PDB start) so the DCD holds only trajectory frames.
    tcl = (f'mol new "{pdb}" waitfor all\n'
           f'mol addfile "{xtc}" step {args.stride} waitfor all\n'
           f'animate write dcd "{fix_dcd}" beg 1 end -1\n'
           f'puts "FIXFRAMES=[expr {{[molinfo top get numframes]-1}}]"\n'
           f'quit\n')
    tf = cache / "_stride.tcl"; tf.write_text(tcl)
    try:
        out = subprocess.run([args.vmd, "-dispdev", "text", "-e", str(tf)],
                             capture_output=True, text=True, timeout=600).stdout
    except FileNotFoundError:
        print(f"[atlas] ERROR: VMD not found at {args.vmd!r}; set --vmd or $VMD_BIN")
        return 1
    nframes = next((l.split("=")[1].strip() for l in out.splitlines() if l.startswith("FIXFRAMES=")), "?")

    gold = {"chain": args.chain, "replica": args.replica, "stride": args.stride,
            "fixture_frames": nframes, "atlas_mean_rg": mean_rg, "atlas_mean_rmsf": mean_rmsf,
            "atlas_mean_rmsd": mean_rmsd,
            "metadata_avg_gyration": md.get("avg_gyration"), "metadata_avg_RMSF": md.get("avg_RMSF"),
            "length": md.get("length"), "protein_name": md.get("protein_name"),
            "license": "CC-BY-NC-4.0", "source": f"{API}/{args.variant}/{args.chain}",
            "cite": "Vander Meersche et al., ATLAS, Nucleic Acids Research 2024 (52:D1 D384)"}
    (dest / f"{args.chain}_gold.json").write_text(json.dumps(gold, indent=2))

    print(f"[atlas] fixture -> {fix_pdb.name} + {fix_dcd.name} "
          f"({fix_dcd.stat().st_size // 1024} KB, {nframes} traj frames)")
    print(f"[atlas] gold: mean Rg={mean_rg} A, mean RMSF={mean_rmsf} A  -> suggested bands:")
    if mean_rg:
        print(f"          - {{kind: scalar_within, where: {{name: meanrg, expect: {mean_rg}, tol: 0.6}}}}")
    if mean_rmsf:
        print(f"          - {{kind: scalar_within, where: {{name: mean_rmsf, min: 0.2, max: {round(mean_rmsf*1.6,2)}}}}}  "
              f"# strided traj undersamples RMSF; calibrate to the oracle")
    print(f"[atlas] CC-BY-NC 4.0 — attribution + non-commercial. Provenance: {fix_pdb.with_name(args.chain + '_gold.json').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
