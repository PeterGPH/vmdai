#!/usr/bin/env python3
"""transcript_util.py — pure helpers for the agent's .tcl transcript.

Kept free of the benchmark framework (evaluation_framework) so it is unit-testable on its own.
"""
from typing import Any, Dict, Optional

# semantic tools whose harness-authored Tcl we fold back into the transcript (run_vmd_command is
# already logged by the agent's own on_tool_start/on_tool_result path).
SEMANTIC_TOOLS = ("vmd_measure", "vmd_traj_measure", "vmd_represent", "vmd_traj_series", "vmd_compute")


def semantic_tool_transcript_entry(name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Turn a semantic tool's result (which carries the Tcl it executed as result['tcl']) into a
    tcl_log entry, wrapped in a '# >>> via <tool> … # <<< end <tool>' marker so a tool-solved case
    still emits a reproducible <case>.tcl AND the transcript labels tool-vs-hand work legibly.
    Returns None when there is nothing to record (not a semantic tool, or no tcl in the result)."""
    if name not in SEMANTIC_TOOLS:
        return None
    result = result or {}
    if name == "vmd_compute":                      # pure-python reduce: record the expression
        expr = result.get("expr")
        if not expr:
            return None
        note = str(result.get("output") or "").splitlines()[:1]
        cmd = f"# >>> via vmd_compute: {expr}" + (f"  # {note[0][:80]}" if note else "")
        return {"cmd": cmd, "ok": bool(result.get("ok")), "err": str(result.get("error") or "")}
    tcl = result.get("tcl")
    if not tcl:
        return None
    note_lines = str(result.get("output") or "").splitlines()
    note = note_lines[0][:100] if note_lines else ""
    cmd = f"# >>> via {name}: {note}\n{tcl}\n# <<< end {name}"
    return {"cmd": cmd, "ok": bool(result.get("ok")), "err": str(result.get("error") or "")}
