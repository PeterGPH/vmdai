#!/usr/bin/env python3
"""test_traj_measure.py — verify the vmd_traj_measure semantic tool against the trajectory gold.

Runs the bridge tool end-to-end on a real fixture and checks every metric matches the
independently-validated oracle (gold_oracle_traj.tcl) within tolerance. Also checks the
brace-corruption bypass premise: the tool takes a brace-free call yet executes a brace-heavy
frame loop. Requires VMD (set VMD_AI_VMD_BIN or have `vmd` on PATH); skips cleanly otherwise.

  python integrations/scivisagentbench/test_traj_measure.py
"""
import os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from subprocess_vmd_bridge import SubprocessVmdBridge, _imbalance  # noqa: E402

ORACLE = HERE / "gold_oracle_traj.tcl"
CHAIN = os.environ.get("TEST_CHAIN", "2erl_A")


def _find_fixture():
    """Locate <CHAIN>.pdb + a <CHAIN>_*.dcd, trying the harness fixtures dir first (server:
    what gets synced) then vmdbench/fixtures (Mac)."""
    import glob
    for base in (HERE / "atlas_fixtures", REPO / "vmdbench" / "fixtures"):
        pdb = base / f"{CHAIN}.pdb"
        dcds = sorted(glob.glob(str(base / f"{CHAIN}_*.dcd")))
        if pdb.exists() and dcds:
            return pdb, Path(dcds[0])
    return None, None


PDB, DCD = _find_fixture()
TOL = {"nframes": 0.5, "meanrg": 0.02, "meanrmsd": 0.02, "mean_rmsf": 0.02, "meansasa": 1.0}


def _vmd_bin():
    return os.environ.get("VMD_AI_VMD_BIN") or os.environ.get("VMDBENCH_VMD_BIN") or "vmd"


def oracle_gold(vmd):
    out = subprocess.run([vmd, "-dispdev", "text", "-e", str(ORACLE)],
                         env=dict(os.environ, GOLD_STRUCT=str(PDB), GOLD_TRAJ=str(DCD)),
                         capture_output=True, text=True, timeout=300).stdout
    g = {}
    for line in out.splitlines():
        m = re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)
        if m:
            try: g[m.group(1)] = float(m.group(2))
            except ValueError: pass
    return g


def main():
    if PDB is None or not (PDB.exists() and DCD.exists()):
        print(f"SKIP: fixtures for {CHAIN!r} not found under atlas_fixtures/ or vmdbench/fixtures/ "
              "(set TEST_CHAIN to a chain you have)"); return 0
    print(f"fixture: {PDB.name} + {DCD.name}")
    vmd = _vmd_bin()
    try:
        # feed `quit` on stdin so VMD exits cleanly — `-e /dev/null` would leave it waiting for input.
        subprocess.run([vmd, "-dispdev", "text"], input="quit\n", capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"SKIP: VMD not runnable at {vmd!r} (set VMD_AI_VMD_BIN)"); return 0

    gold = oracle_gold(vmd)
    print(f"oracle gold ({CHAIN}): " + ", ".join(f"{k}={round(v,3)}" for k, v in sorted(gold.items())))

    bridge = SubprocessVmdBridge()
    ok_all = True
    try:
        for metric, tol in TOL.items():
            bridge.reset()   # fresh scene per case, as the harness does
            r = bridge.execute_tool(tool_name="vmd_traj_measure",
                                    tool_input={"metric": metric, "structure": str(PDB), "trajectory": str(DCD)})
            passed = r.get("ok") and r.get("value") is not None and metric in gold \
                and abs(float(r["value"]) - gold[metric]) <= tol
            ok_all &= bool(passed)
            got = r.get("value")
            print(f"  [{'PASS' if passed else 'FAIL'}] {metric:10} tool={got} gold={gold.get(metric)}"
                  + ("" if passed else f"   <- {r.get('error') or 'mismatch'}"))
            # the tool must hand back the Tcl it ran (for the reproducible transcript), balanced.
            tcl_ok = bool(r.get("tcl")) and _imbalance(r["tcl"]) is None
            ok_all &= tcl_ok
            print(f"  [{'PASS' if tcl_ok else 'FAIL'}] {metric:10} returns balanced tcl for the transcript")

        # error paths
        bad = bridge.execute_tool(tool_name="vmd_traj_measure",
                                  tool_input={"metric": "bogus", "structure": str(PDB), "trajectory": str(DCD)})
        ok_all &= bad.get("ok") is False and "unknown metric" in (bad.get("error") or "")
        print(f"  [{'PASS' if bad.get('ok') is False else 'FAIL'}] unknown metric rejected cleanly")

        miss = bridge.execute_tool(tool_name="vmd_traj_measure",
                                   tool_input={"metric": "meanrg", "structure": str(PDB), "trajectory": "/nope.dcd"})
        ok_all &= miss.get("ok") is False and "not found" in (miss.get("error") or "")
        print(f"  [{'PASS' if miss.get('ok') is False else 'FAIL'}] missing file rejected cleanly")
    finally:
        bridge.close()

    # premise check: the harness-authored loop Tcl is balanced (would pass pre-validation),
    # even though the model's call carries no braces at all.
    for metric in ("meanrg", "meanrmsd", "mean_rmsf", "meansasa"):
        body = SubprocessVmdBridge._TRAJ_TCL[metric].replace("@SEL@", "protein")
        assert _imbalance(body) is None, f"{metric} body is unbalanced!"
    print("  [PASS] all frame-loop bodies are brace-balanced (bypass the tool-call corruption)")

    print("\n" + ("ALL GOOD — vmd_traj_measure matches the oracle." if ok_all
                  else "SOME CHECKS FAILED."))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
