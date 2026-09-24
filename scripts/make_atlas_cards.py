#!/usr/bin/env python3
"""make_atlas_cards.py — turn ATLAS chains into verified vmdbench trajectory cases.

Per chain: fetch+stride (fetch_atlas.py) -> write oracle + card -> calibrate the scalar_within
bands from the ORACLE's own output (the reproducible vmdbench gold, cross-checked vs ATLAS) ->
score-oracle to confirm gate + replay_clean. Emits, per chain:
   vmdbench/tasks/traj/atlas_dynamics_<chain>_001.yaml
   vmdbench/oracles/atlas_dynamics_<chain>_001.tcl

  python scripts/make_atlas_cards.py --list scripts/atlas_subset.txt --limit 5
  python scripts/make_atlas_cards.py 2gkr_I 6ro6_A --stride 25

ATLAS data is CC-BY-NC 4.0 (attribution + non-commercial) — see each card/oracle header.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS = REPO / "vmdbench" / "tasks" / "traj"
ORACLES = REPO / "vmdbench" / "oracles"
FIX = REPO / "vmdbench" / "fixtures"

ORACLE_TMPL = """# atlas_dynamics_@CHAIN@_001 oracle — @NAME@ (@LEN@ res), ATLAS replica @REP@,
# ~@FRAMES@ frames. Emits trajectory observables as PROBE> measure_ lines; the HeadlessVMDEnv
# wrapper appends scene introspection + quit.
# ATLAS data CC-BY-NC 4.0 — cite Vander Meersche et al., NAR 2024 (52:D1 D384).
mol new @PDB@ waitfor all
mol addfile @DCD@ waitfor all
set n [molinfo top get numframes]
set prot [atomselect top "protein"]
set g 0.0
set sa 0.0
for {set i 0} {$i < $n} {incr i} {
  $prot frame $i
  set g  [expr {$g  + [measure rgyr $prot]}]
  set sa [expr {$sa + [measure sasa 1.4 $prot]}]
}
puts "PROBE> measure_meanrg=[expr {$g / $n}]"
puts "PROBE> measure_meansasa=[expr {$sa / $n}]"
set ca  [atomselect top "protein and name CA"]
set ref [atomselect top "protein and name CA" frame 0]
set all [atomselect top "all"]
set rsum 0.0
for {set i 0} {$i < $n} {incr i} {
  $ca frame $i; $all frame $i
  $all move [measure fit $ca $ref]
  set rsum [expr {$rsum + [measure rmsd $ca $ref]}]
}
puts "PROBE> measure_meanrmsd=[expr {$rsum / $n}]"
set rmsf [measure rmsf $ca]
set s 0.0
foreach v $rmsf { set s [expr {$s + $v}] }
puts "PROBE> measure_mean_rmsf=[expr {$s / [llength $rmsf]}]"
"""

CARD_TMPL = """task_id: atlas_dynamics_@CHAIN@_001
category: trajectory
bucket: synthesis
difficulty: medium
dimensions: [actionability, semantic_grounding]
initial_state:
  files: [@PDB@, @DCD@]
  pdb: @PDBID@
  molecules_loaded: false
allowed_interface: [raw_tcl]
# Real all-atom MD from ATLAS (@CHAIN@ = @NAME@, @LEN@ res; replica @REP@, ~@FRAMES@ frames).
# Trajectory CORRECTNESS: mean Rg + mean Calpha-RMSD-to-frame-0 + mean Calpha RMSF (ATLAS-published)
# + mean SASA (1.4 A probe; VMD-computed, ATLAS does not pre-publish it). Bands calibrated from the
# oracle (vmdbench gold); ATLAS cross-check Rg @ARG@ / RMSD @ARMSD@ / RMSF @ARMSF@ A.
# ATLAS data CC-BY-NC 4.0 — cite Vander Meersche et al., NAR 2024 (52:D1 D384).
user_prompt: >
  Load @PDB@ and its MD trajectory @DCD@, then report (align the frames to frame 0 first):
  "PROBE> measure_meanrg=<value>" (mean radius of gyration over all frames),
  "PROBE> measure_meanrmsd=<value>" (mean alpha-carbon RMSD to the first frame),
  "PROBE> measure_mean_rmsf=<value>" (mean per-residue alpha-carbon RMSF), and
  "PROBE> measure_meansasa=<value>" (mean solvent-accessible surface area, measure sasa 1.4).
verify:
  required:
    - {kind: molecule_loaded, where: {}}
    - {kind: frames_loaded,   where: {min: @FMIN@}}
    - {kind: scalar_within,   where: {name: meanrg,    expect: @RG@, tol: @RGTOL@}}
    - {kind: scalar_within,   where: {name: meanrmsd,  expect: @RMSD@, tol: @RMSDTOL@}}
    - {kind: scalar_within,   where: {name: mean_rmsf, min: @RMIN@, max: @RMAX@}}
    - {kind: scalar_within,   where: {name: meansasa,  expect: @SASA@, tol: @SASATOL@}}
  optional:
    - {kind: no_runtime_errors, where: {}}
reproducibility:
  exports: [tcl]
  replay_clean: @REPLAY@
"""


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"@{k}@", str(v))
    return t


def score(card, oracle, timeout):
    out = subprocess.run([sys.executable, "-m", "vmdbench.cli", "score-oracle", str(card), str(oracle),
                          "--timeout", str(timeout)], cwd=str(REPO), capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def observed(d):
    o = {"meanrg": None, "meanrmsd": None, "mean_rmsf": None, "meansasa": None, "frames": None}
    for a in (d or {}).get("verify", {}).get("required", []):
        if a["kind"] == "frames_loaded":
            o["frames"] = a["observed"]
        elif a["kind"] == "scalar_within" and a["where"].get("name") in o:
            o[a["where"]["name"]] = a["observed"]
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chains", nargs="*")
    ap.add_argument("--list")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stride", type=int, default=25)
    ap.add_argument("--replica", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    chains = list(args.chains)
    if args.list:
        chains += [l.strip() for l in open(args.list) if l.strip() and not l.startswith("#")]
    if args.limit:
        chains = chains[:args.limit]
    if not chains:
        print("no chains given"); return 1
    TASKS.mkdir(parents=True, exist_ok=True); ORACLES.mkdir(parents=True, exist_ok=True)

    results = []
    for chain in chains:
        print(f"\n=== {chain} ===")
        pdb, dcd = f"{chain}.pdb", f"{chain}_R{args.replica}_s{args.stride}.dcd"
        if not (FIX / dcd).exists():
            r = subprocess.run([sys.executable, str(REPO / "scripts" / "fetch_atlas.py"), chain,
                                "--stride", str(args.stride), "--replica", str(args.replica)],
                               cwd=str(REPO), capture_output=True, text=True)
            sys.stdout.write(r.stdout)
            if not (FIX / dcd).exists():
                print(f"  !! fetch failed: {(r.stderr or '').strip().splitlines()[-1:]}")
                results.append((chain, "fetch-fail")); continue
        gold = json.loads((FIX / f"{chain}_gold.json").read_text()) if (FIX / f"{chain}_gold.json").exists() else {}
        name = (gold.get("protein_name") or chain)[:40]
        length, pdbid = gold.get("length", "?"), chain.split("_")[0].upper()
        oracle_path = ORACLES / f"atlas_dynamics_{chain}_001.tcl"
        card_path = TASKS / f"atlas_dynamics_{chain}_001.yaml"
        common = dict(CHAIN=chain, NAME=name, LEN=length, REP=args.replica, PDB=pdb, DCD=dcd, PDBID=pdbid,
                      ARG=gold.get("atlas_mean_rg", "?"), ARMSF=gold.get("atlas_mean_rmsf", "?"),
                      ARMSD=gold.get("atlas_mean_rmsd", "?"))

        # pass 1: wide bands, no replay -> read the oracle's actual values
        oracle_path.write_text(fill(ORACLE_TMPL, FRAMES="?", **common))
        card_path.write_text(fill(CARD_TMPL, FRAMES="?", FMIN=1, RG=0, RGTOL=100000, RMSD=0, RMSDTOL=100000,
                                  RMIN=0, RMAX=100000, SASA=0, SASATOL=10000000, REPLAY="false", **common))
        o = observed(score(card_path, oracle_path, args.timeout))
        if any(o[k] is None for k in ("meanrg", "meanrmsd", "mean_rmsf", "meansasa")):
            print("  !! oracle produced no measures (VMD/trajectory error)")
            results.append((chain, "oracle-fail")); continue
        rg, rmsd, rmsf = round(o["meanrg"], 2), round(o["meanrmsd"], 2), round(o["mean_rmsf"], 3)
        sasa, fr = round(o["meansasa"], 1), int(o["frames"] or 1)
        rgtol = round(max(0.5, 0.08 * rg), 2)
        rmsdtol = round(max(0.3, 0.15 * rmsd), 2)
        sasatol = round(max(100.0, 0.08 * sasa), 1)
        rmin, rmax, fmin = round(max(0.1, 0.5 * rmsf), 2), round(max(0.5, 1.7 * rmsf), 2), max(1, fr - 2)

        # pass 2: calibrated bands + replay -> verify
        oracle_path.write_text(fill(ORACLE_TMPL, FRAMES=fr, **common))
        card_path.write_text(fill(CARD_TMPL, FRAMES=fr, FMIN=fmin, RG=rg, RGTOL=rgtol, RMSD=rmsd, RMSDTOL=rmsdtol,
                                  RMIN=rmin, RMAX=rmax, SASA=sasa, SASATOL=sasatol, REPLAY="true", **common))
        d = score(card_path, oracle_path, args.timeout)
        solved = (d or {}).get("score", {}).get("solved")
        rc = (d or {}).get("replay_clean")
        print(f"  rg={rg}±{rgtol}  rmsd={rmsd}±{rmsdtol}  rmsf[{rmin},{rmax}](obs {rmsf})  "
              f"sasa={sasa}±{sasatol}  frames={fr}  -> solved={solved} replay_clean={rc}")
        results.append((chain, "ok" if solved else "verify-fail"))

    ok = [c for c, s in results if s == "ok"]
    print(f"\n=== generated {len(ok)}/{len(results)} verified ATLAS cases ===")
    for c, s in results:
        print(f"  {c:10} {s}")
    return 0 if len(ok) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
