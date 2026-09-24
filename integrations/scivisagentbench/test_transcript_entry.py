#!/usr/bin/env python3
"""test_transcript_entry.py — semantic_tool_transcript_entry() turns a semantic tool's result
(which now carries the Tcl it executed) into a tcl_log entry wrapped in a >>>/<<< marker, so a
tool-solved case still emits a reproducible <case>.tcl. Pure logic — no model, no VMD.

  python integrations/scivisagentbench/test_transcript_entry.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from transcript_util import semantic_tool_transcript_entry as entry  # noqa: E402

TCL = 'mol new "/x/a.pdb" waitfor all\nset __v [molinfo top get numframes]\nputs "VMDAI_VALUE=$__v"'


def main():
    fails = 0

    def check(label, cond):
        nonlocal fails
        fails += not cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    e = entry("vmd_traj_measure", {"ok": True, "tcl": TCL, "value": "42",
                                   "output": "nframes(protein) over trajectory = 42", "error": ""})
    check("returns an entry for a semantic tool that carries tcl", e is not None)
    check("entry.ok is True", e and e.get("ok") is True)
    check("cmd opens with a '# >>> via vmd_traj_measure' marker",
          e and e["cmd"].startswith("# >>> via vmd_traj_measure:"))
    check("cmd closes with the matching '# <<< end vmd_traj_measure'",
          e and e["cmd"].rstrip().endswith("# <<< end vmd_traj_measure"))
    check("cmd embeds the executed Tcl verbatim", e and TCL in e["cmd"])
    check("marker carries the result note", e and "nframes(protein) over trajectory = 42" in e["cmd"])

    check("failed tool call still records its tcl (ok=False)",
          (lambda x: x is not None and x.get("ok") is False)(
              entry("vmd_measure", {"ok": False, "tcl": TCL, "error": "Tcl error", "output": ""})))

    check("None for run_vmd_command (handled by the existing path)",
          entry("run_vmd_command", {"ok": True, "tcl": TCL}) is None)
    check("None for a semantic tool with no tcl in the result",
          entry("vmd_traj_measure", {"ok": True, "value": "42", "output": "x"}) is None)
    check("None for an unknown tool name",
          entry("capture_vmd_snapshot", {"ok": True, "tcl": TCL}) is None)

    print("ALL GOOD — transcript entry helper matches the spec." if not fails
          else f"{fails} case(s) FAILED.")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
