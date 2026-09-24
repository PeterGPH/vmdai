#!/usr/bin/env python3
"""
rag_ab_extract.py — turn rag_ab JSON output into replayable Tcl scripts.

The rag_ab harness stubs the VMD bridge, so it captures every Tcl
command the model emitted but never actually runs them. This script
takes that capture and writes one ``.tcl`` file per arm so you can:

    vmd -e control_arm.tcl
    vmd -dispdev text -e rag_arm.tcl

…and see the visual difference between the two arms side by side.

Each emitted run_vmd_command becomes one block in the output:

    # ─── turn N | tool_call_id | <rationale> ───
    <Tcl commands>

capture_vmd_snapshot calls (which the live plugin renders) are
converted into ``render snapshot`` lines so replay produces images.
search_docs calls are noted as comments only — they don't translate
to Tcl.

Usage:

    python scripts/rag_ab_extract.py cdk2_ab_v2.json --out-dir ./cdk2_replay/
    # produces ./cdk2_replay/control.tcl and ./cdk2_replay/rag.tcl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List


def _emit_block(turn_n: int, call: Dict) -> str:
    name = call.get("tool_name", "?")
    tool_id = call.get("tool_call_id", "?")
    tinput = call.get("tool_input", {})
    rationale = tinput.get("rationale", "")
    header = f"\n# --- turn {turn_n:02d} | {name} | {tool_id} ---\n"
    if rationale:
        for line in rationale.splitlines():
            header += f"# rationale : {line}\n"
    header += "\n"

    if name == "run_vmd_command":
        cmd = tinput.get("command", "")
        return header + cmd.rstrip() + "\n"
    if name == "capture_vmd_snapshot":
        purpose = tinput.get("purpose", "")
        snap = f"snapshots/turn_{turn_n:03d}.tga"
        body = ""
        if purpose:
            body += f"# purpose : {purpose}\n"
        # Use TachyonInternal instead of `render snapshot` — the former
        # is a software ray-tracer that produces a valid TGA regardless
        # of OpenGL state. `render snapshot` writes a 0-byte file when
        # no molecule is loaded or the framebuffer isn't initialized,
        # which surfaces as a confusing "zero image size" error when
        # converting to PNG later.
        # Guard with [molinfo num] so the very first probe snapshot
        # (which often runs before any successful mol load) is skipped
        # rather than producing an empty file.
        body += f"display update\n"
        body += f"if {{[molinfo num] > 0}} {{\n"
        body += f"    render TachyonInternal {snap}\n"
        body += f"}} else {{\n"
        # NB: no square brackets in this puts string — Tcl would treat
        # them as command substitution and look for a `snapshot` proc.
        body += f"    puts \"snapshot turn {turn_n:02d} skipped — no molecule loaded yet\"\n"
        body += f"}}\n"
        return header + body
    if name == "search_docs":
        q = tinput.get("query", "")
        return header + f"# (search_docs not replayable; query was: {q!r})\n"
    return header + f"# (skipped: unknown tool {name})\n"


def _render_arm_script(prompt: str, arm: Dict, label: str) -> str:
    saved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    err = arm.get("error") or "(none)"
    out: List[str] = []
    out.append(f"# VMD AI · A/B harness replay")
    out.append(f"# arm        : {arm.get('name') or label}")
    out.append(f"# prompt     : {prompt}")
    out.append(f"# saved_at   : {saved_at}")
    out.append(f"# elapsed_s  : {arm.get('elapsed_s', 0):.2f}")
    out.append(f"# arm error  : {err}")
    out.append("#")
    out.append("# Replay with:")
    out.append(f"#   vmd -e {label}.tcl")
    out.append(f"#   vmd -dispdev text -e {label}.tcl    (headless)")
    out.append("#")
    out.append("# Snapshots will be written under ./snapshots/ relative to cwd.")
    out.append("")
    out.append("file mkdir snapshots")
    out.append("")
    # ─── Render-quality preamble ────────────────────────────────────
    # TachyonInternal renders at the current display size. The headless
    # default is 512x512 with no antialiasing — fine for sanity checks,
    # too rough for papers. Bump to 1920² with AO + shadows + AA on.
    # Override per-script by editing these lines after extraction.
    out.append("# Render quality (auto-injected). Comment out any line you don't want.")
    out.append("display resize 1920 1920")
    out.append("display antialias on")
    out.append("display rendermode Normal")
    out.append("display depthcue on")
    out.append("display ambientocclusion on")
    out.append("display aoambient  0.85")
    out.append("display aodirect   0.45")
    out.append("display shadows on")
    out.append("")

    calls = arm.get("tool_calls") or []
    for turn_n, call in enumerate(calls, start=1):
        out.append(_emit_block(turn_n, call))

    if arm.get("error"):
        out.append(f"\n# NOTE: the arm errored mid-run with:\n# {arm['error']!r}")
        out.append("# Tcl above is the partial trace up to the failure.\n")

    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("json_path", help="cdk2_ab_v2.json (output of rag_ab.py)")
    p.add_argument("--out-dir", default="./rag_ab_replay",
                   help="Directory to write control.tcl + rag.tcl into")
    args = p.parse_args(argv)

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    prompt = data.get("prompt", "")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for label in ("control", "rag"):
        arm = data.get(label) or {}
        if not arm:
            print(f"[extract] no '{label}' arm in {args.json_path}",
                  file=sys.stderr)
            continue
        script = _render_arm_script(prompt, arm, label)
        out_file = out_dir / f"{label}.tcl"
        out_file.write_text(script, encoding="utf-8")
        cmds = sum(
            1 for c in (arm.get("tool_calls") or [])
            if c.get("tool_name") == "run_vmd_command"
        )
        snaps = sum(
            1 for c in (arm.get("tool_calls") or [])
            if c.get("tool_name") == "capture_vmd_snapshot"
        )
        print(f"[extract] {out_file}  "
              f"({cmds} vmd commands, {snaps} snapshots)")

    print(f"\n[extract] Replay either arm with:")
    print(f"    cd {out_dir} && vmd -e control.tcl")
    print(f"    cd {out_dir} && vmd -e rag.tcl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
