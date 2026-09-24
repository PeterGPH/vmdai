#!/usr/bin/env python3
"""test_analyze_disk.py — analyze() must work on a run that has NO summary.json (still running,
or died before/at the final write), reconstructing (gold, agent, ok) from the per-case answer
files + the gold cache. Adoption and the failure taxonomy come from the transcripts, which are
always on disk. Pure filesystem logic — no VMD.

  python integrations/scivisagentbench/test_analyze_disk.py
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze_tool_adoption import analyze  # noqa: E402


def _build(run):
    run.mkdir(parents=True, exist_ok=True)
    # answer files use '<name>__<metric>__s<seed>.txt'; transcripts use '<name>_<metric>_s<seed>.tcl'
    def ans(nm, mt, sd, v): (run / f"{nm}__{mt}__s{sd}.txt").write_text(f"{v}\n")
    def tcl(nm, mt, sd, t): (run / f"{nm}_{mt}_s{sd}.tcl").write_text(t)
    def resp(nm, mt, sd, t): (run / f"{nm}_{mt}_s{sd}.response.txt").write_text(t)

    # chainA nframes: tool_only (no .tcl), correct
    ans("chainA", "nframes", 1, 42); resp("chainA", "nframes", 1, "42.")
    # chainA meanrg: hand_computed, correct
    ans("chainA", "meanrg", 1, 13.5)
    tcl("chainA", "meanrg", 1, 'mol new "/x/a.pdb" waitfor all\nset g [measure rgyr $s]\nputs $f $g\n')
    # chainB meanrg: tool_only via marker, correct
    ans("chainB", "meanrg", 1, 10.0)
    tcl("chainB", "meanrg", 1,
        "# header\n# >>> via vmd_traj_measure: meanrg(protein) = 10.0\n"
        'mol new "/x/b.pdb" waitfor all\nset __v [expr {[measure rgyr $__p]}]\nputs "VMDAI_VALUE=$__v"\n'
        "# <<< end vmd_traj_measure\n")
    # chainB nframes: NO answer file (failure), hand-driven with brace thrash
    tcl("chainB", "nframes", 1,
        'mol new "/x/b.pdb" waitfor all\n\n# --- attempts that errored ---\n'
        "#  set n [molinfo top get numframes]  ;# ERR: incomplete Tcl — unclosed '{'\n"
        "#  set n [molinfo top get numframes]  ;# ERR: incomplete Tcl — unclosed '{'\n")
    resp("chainB", "nframes", 1, "persistent issue with the command.")
    # chainA meanrmsd/mean_rmsf/meansasa etc. + chainB others: NO files -> did not run (must be skipped)


GOLD = {"chainA": {"nframes": 42.0, "meanrg": 13.5, "meanrmsd": 1.0, "mean_rmsf": 0.5, "meansasa": 3000.0},
        "chainB": {"nframes": 42.0, "meanrg": 10.0, "meanrmsd": 1.0, "mean_rmsf": 0.5, "meansasa": 3000.0}}


def main():
    tmp = Path(tempfile.mkdtemp())
    run = tmp / "tools_partial"
    _build(run)
    gold_path = tmp / "gold.json"
    gold_path.write_text(json.dumps(GOLD))

    rows = analyze(run, gold_cache=str(gold_path))
    by = {(r["name"], r["metric"]): r for r in rows}
    fails = 0

    def check(label, cond):
        nonlocal fails
        fails += not cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    check("only the 4 cases that left artifacts are reconstructed", len(rows) == 4)
    check("rows carry case/gold/agent for failure drill-down",
          all({"case", "gold", "agent"} <= set(r) for r in rows))
    check("chainB/nframes row exposes agent=None (answer not written)",
          by.get(("chainB", "nframes")) and by[("chainB", "nframes")]["agent"] is None
          and by[("chainB", "nframes")]["case"] == "chainB_nframes_s1")
    check("chainA/nframes -> tool_only, correct",
          by.get(("chainA", "nframes")) == {**by.get(("chainA", "nframes"), {}),
              "name": "chainA", "metric": "nframes", "ok": True, "adoption": "tool_only", "reason": None})
    check("chainA/meanrg -> hand_computed, correct",
          by.get(("chainA", "meanrg", )) and by[("chainA", "meanrg")]["adoption"] == "hand_computed"
          and by[("chainA", "meanrg")]["ok"] is True)
    check("chainB/meanrg -> tool_only (marker), correct",
          by.get(("chainB", "meanrg")) and by[("chainB", "meanrg")]["adoption"] == "tool_only"
          and by[("chainB", "meanrg")]["ok"] is True)
    check("chainB/nframes -> hand_computed, FAIL via brace_thrash (no answer file)",
          by.get(("chainB", "nframes")) and by[("chainB", "nframes")]["ok"] is False
          and by[("chainB", "nframes")]["adoption"] == "hand_computed"
          and by[("chainB", "nframes")]["reason"] == "brace_thrash")

    print("ALL GOOD — disk-mode reconstruction matches the spec." if not fails
          else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
