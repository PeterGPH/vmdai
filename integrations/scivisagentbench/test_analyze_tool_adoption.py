#!/usr/bin/env python3
"""test_analyze_tool_adoption.py — unit-test the pure case classifier used to measure
semantic-tool ADOPTION and taxonomize failures over a completed atlas-traj run.

No VMD, no fixtures: classify_case() is pure text logic, so this runs anywhere.
The three real-run cases below are the exact artifacts from tools_v2/ (1pch nframes=0,
1x6j nframes=41, 2erl meansasa=None) — they are the spec.

  python integrations/scivisagentbench/test_analyze_tool_adoption.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze_tool_adoption import classify_case  # noqa: E402


# ---- real transcripts captured from the tools_v2 run -----------------------
TCL_1PCH = '''# vmd_ai working Tcl transcript — 1pch_A_nframes_s1
mol new "/x/1pch_A.pdb" waitfor all
mol addfile "/x/1pch_A_R1_s25.dcd" waitfor all
set n [molinfo top get numframes]
set f [open "/x/1pch_A__nframes__s1.txt" w]; puts $f $n; close $f
set f [open "/x/1pch_A__nframes__s1.txt" w]; puts $f 0; close $f
'''
RESP_1PCH = ("It appears that the number of frames reported by VMD is 0, which suggests there "
             "might be an issue with the trajectory file. However, I will proceed with writing "
             "the value 0 to the file as requested.")

TCL_1X6J = '''# vmd_ai working Tcl transcript — 1x6j_A_nframes_s1
mol new "/x/1x6j_A.pdb" waitfor all
mol addfile "/x/1x6j_A_R1_s25.dcd" waitfor all
set n [expr [molinfo top get numframes] - 1]
set f [open "/x/1x6j_A__nframes__s1.txt" w]
puts $f $n
close $f
'''
RESP_1X6J = "The trajectory file still reports 0 frames. Let's try a different approach."

TCL_2ERL = '''# vmd_ai working Tcl transcript — 2erl_A_meansasa_s1
mol new "/x/2erl_A.pdb" waitfor all
mol addfile "/x/2erl_A_R1_s25.dcd" waitfor all

# --- attempts that errored (excluded from the script above) ---
#   mol new "/x/2erl_A.pdb ...    ;# ERR: incomplete Tcl — 3 unclosed '{' — close the loop body
#   mol new "/x/2erl_A.pdb ...    ;# ERR: incomplete Tcl — 3 unclosed '{' — close the loop body
#   set n [molinfo top get numframes]    ;# ERR: incomplete Tcl — 3 unclosed '{'
'''
RESP_2ERL = "There is a persistent issue with the command. Let's break it into smaller parts."


CASES = [
    # label, kwargs, expected (adoption, failure_reason)
    ("tool_only pass (no tcl file)",
     dict(tcl_text=None, response_text="Done.", agent_val=42.0, gold_val=42.0, ok=True,
          harness_error=None),
     ("tool_only", None)),

    ("tool_plus_write pass (loads+write, no measurement)",
     dict(tcl_text='mol new "/x/a.pdb" waitfor all\nset f [open "/x/o.txt" w]; puts $f 13.5; close $f\n',
          response_text="Wrote it.", agent_val=13.5, gold_val=13.5, ok=True, harness_error=None),
     ("tool_plus_write", None)),

    ("hand_computed pass (measured by hand, still correct)",
     dict(tcl_text='mol new "/x/a.pdb" waitfor all\nset n [molinfo top get numframes]\nputs $f $n\n',
          response_text="42.", agent_val=42.0, gold_val=42.0, ok=True, harness_error=None),
     ("hand_computed", None)),

    ("1pch: hand + knowingly wrote a value it believed wrong",
     dict(tcl_text=TCL_1PCH, response_text=RESP_1PCH, agent_val=0.0, gold_val=42.0, ok=False,
          harness_error=None),
     ("hand_computed", "knowingly_wrong")),

    ("1x6j: hand + gratuitous -1 over-correction",
     dict(tcl_text=TCL_1X6J, response_text=RESP_1X6J, agent_val=41.0, gold_val=42.0, ok=False,
          harness_error=None),
     ("hand_computed", "over_corrected")),

    ("2erl: hand + brace-imbalance thrash, no answer",
     dict(tcl_text=TCL_2ERL, response_text=RESP_2ERL, agent_val=None, gold_val=3041.76, ok=False,
          harness_error=None),
     ("hand_computed", "brace_thrash")),

    ("hand + real harness timeout",
     dict(tcl_text='mol new "/x/a.pdb" waitfor all\nset s [measure sasa 1.4 $sel]\n',
          response_text="working...", agent_val=None, gold_val=3000.0, ok=False,
          harness_error="task timed out after 300s"),
     ("hand_computed", "timeout")),

    ("hand + plain wrong value (no special pathology)",
     dict(tcl_text='mol new "/x/a.pdb" waitfor all\nset g [measure rgyr $sel]\nputs $f $g\n',
          response_text="computed rgyr.", agent_val=9.9, gold_val=13.5, ok=False,
          harness_error=None),
     ("hand_computed", "wrong_value")),

    # --- marked-transcript format (new): the tool's own Tcl is recorded under a >>>/<<< block.
    # Its internal molinfo/measure lines must NOT be counted as hand-written measurement.
    ("marked tool_only (tool block only, its molinfo is not 'hand')",
     dict(tcl_text=('# vmd_ai working Tcl transcript — 2es9_B_nframes_s1\n'
                    '# >>> via vmd_traj_measure: nframes(protein) over trajectory = 42\n'
                    'mol new "/x/a.pdb" waitfor all\nmol addfile "/x/a.dcd" waitfor all\n'
                    'set __v [molinfo top get numframes]\nputs "VMDAI_VALUE=$__v"\n'
                    '# <<< end vmd_traj_measure\n'),
          response_text="42.", agent_val=42.0, gold_val=42.0, ok=True, harness_error=None),
     ("tool_only", None)),

    ("marked tool_plus_write (tool block + hand file write, no hand measurement)",
     dict(tcl_text=('# header\n'
                    '# >>> via vmd_traj_measure: meanrg(protein) over trajectory = 13.5\n'
                    'mol new "/x/a.pdb" waitfor all\nset __p [atomselect top "protein"]\n'
                    'set __v [expr {[measure rgyr $__p]}]\nputs "VMDAI_VALUE=$__v"\n'
                    '# <<< end vmd_traj_measure\n'
                    'set f [open "/x/o.txt" w]; puts $f 13.5; close $f\n'),
          response_text="wrote it.", agent_val=13.5, gold_val=13.5, ok=True, harness_error=None),
     ("tool_plus_write", None)),

    # a brace-imbalance rejection can only come from a hand-written run_vmd_command, so it means
    # hand-driving EVEN WHEN the transcript truncation hides the measure/for on a later line
    # (the real 'tool_plus_write meansasa brace_thrash' misclassification in tools_v2).
    ("thrash whose measurement is hidden by transcript truncation -> hand_computed, not tool",
     dict(tcl_text=('# vmd_ai working Tcl transcript — 2erl_A_meansasa_s3\n'
                    'mol new "/data/x/2erl_A.pdb" waitfor all\n\n'
                    '# --- attempts that errored (excluded from the script above) ---\n'
                    "#   mol new \"/data/x/atlas_fixtures/2erl_A.pdb\" waitfor all    ;# ERR: incomplete Tcl — 3 unclosed '{'\n"
                    "#   mol new \"/data/x/atlas_fixtures/2erl_A.pdb\" waitfor all    ;# ERR: incomplete Tcl — 3 unclosed '{'\n"),
          response_text="persistent brace issue.", agent_val=None, gold_val=3041.76, ok=False,
          harness_error=None),
     ("hand_computed", "brace_thrash")),

    # a small model often calls the tool (marker + correct value) AND leaves failed run_vmd_command
    # attempts in the errored-comment section. Those never ran, so they must NOT flip it to hand.
    ("marked tool success + FAILED hand attempts (didn't run) -> tool_only, not hand",
     dict(tcl_text=('# vmd_ai working Tcl transcript — 1h02_B_mean_rmsf_s1\n'
                    '# >>> via vmd_traj_measure: mean_rmsf(protein) = 2.63 (written to /long/path\n'
                    'mol new "/x/a.pdb" waitfor all\nmol addfile "/x/a.dcd" waitfor all\n'
                    'set __ca [atomselect top "protein and name CA"]; set __f [measure rmsf $__ca]\n'
                    'puts "VMDAI_VALUE=$__v"\n'
                    '# <<< end vmd_traj_measure\n\n'
                    '# --- attempts that errored (excluded from the script above) ---\n'
                    "#   set g [for {set i 0}    ;# ERR: incomplete Tcl — 3 unclosed '{'\n"
                    "#   set g [for {set i 0}    ;# ERR: incomplete Tcl — 3 unclosed '{'\n"),
          response_text="ok", agent_val=2.63, gold_val=2.63, ok=True, harness_error=None),
     ("tool_only", None)),

    ("marked tool block BUT model also hand-measured outside it -> hand_computed",
     dict(tcl_text=('# header\n'
                    '# >>> via vmd_traj_measure: meanrg(protein) over trajectory = 13.5\n'
                    'set __v [expr {[measure rgyr $__p]}]\nputs "VMDAI_VALUE=$__v"\n'
                    '# <<< end vmd_traj_measure\n'
                    'set n [molinfo top get numframes]\nputs $f $n\n'),
          response_text="also counted frames by hand.", agent_val=10.0, gold_val=42.0, ok=False,
          harness_error=None),
     ("hand_computed", "wrong_value")),
]


def main():
    fails = 0
    for label, kwargs, expected in CASES:
        got = classify_case(**kwargs)
        ok = got == expected
        fails += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}\n"
              + ("" if ok else f"        expected {expected}, got {got}\n"))
    print("ALL GOOD — classifier matches the spec." if not fails
          else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
