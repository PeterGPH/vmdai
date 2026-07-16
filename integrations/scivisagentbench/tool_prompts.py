#!/usr/bin/env python3
"""tool_prompts.py — the semantic-tool directive appended to the system prompt, as a config knob.

`tool_directive: "soft"`  reproduces the v2 condition (a gentle "prefer tools" nudge).
`tool_directive: "mandatory"` (default) is the v3 condition (hard "you MUST" + anti-patterns).
Making it a knob lets a cross-model sweep run both conditions without editing code. Kept free of
the benchmark framework so it is unit-testable on its own.
"""

# v2: the model may use run_vmd_command freely; tools are merely preferred.
TOOL_DIRECTIVE_SOFT = (
    "\n\nPREFER TOOLS: for a single-structure numeric value call vmd_measure(metric, selection"
    "[, save_path]); for a value averaged over a TRAJECTORY call vmd_traj_measure(metric, structure, "
    "trajectory[, selection, save_path]) — both run the correct VMD Tcl and return the number. For a "
    "representation call vmd_represent(style, color, selection). Use run_vmd_command only for what these "
    "don't cover."
)

# v3: routing to the tools is required, with the specific anti-patterns that killed the v2 failures.
TOOL_DIRECTIVE_MANDATORY = (
    "\n\nUSE TOOLS — MANDATORY for numeric answers: for a single-structure value call "
    "vmd_measure(metric, selection[, save_path]); for ANY quantity over a TRAJECTORY — including "
    "the plain frame count — call vmd_traj_measure(metric, structure, trajectory[, selection, "
    "save_path]). Both run the correct, brace-balanced VMD Tcl and return the number, and will "
    "write it if you pass save_path. For a representation call vmd_represent(style, color, "
    "selection). Use run_vmd_command ONLY for things these three don't cover.\n"
    "NEVER count frames by hand (no `molinfo get numframes`, no manual frame loop) — use "
    "vmd_traj_measure(metric=nframes). NEVER 'adjust' a tool's result (no -1, no rounding). And "
    "NEVER write a value you suspect is wrong (e.g. 0 frames) — if a hand result looks wrong, call "
    "the tool and trust it."
)


def tool_directive(config):
    """Return the directive text for config['tool_directive'] ('soft' | 'mandatory'). Defaults to
    mandatory (preserving v3 behavior); any unrecognized value also falls back to mandatory."""
    mode = str((config or {}).get("tool_directive", "mandatory")).strip().lower()
    return TOOL_DIRECTIVE_SOFT if mode == "soft" else TOOL_DIRECTIVE_MANDATORY


# workbench (v1): the tool returns the RAW per-frame series; the model chooses the reduction. The
# directive explains the loop but deliberately hands over NO metric name/formula — that is the test.
WORKBENCH_DIRECTIVE = (
    "\n\nTRAJECTORY WORKBENCH: you have two tools. vmd_traj_series(quantity, structure, "
    "trajectory) returns the raw PER-FRAME series for one observable (quantity is one of "
    "rgyr, sasa, rmsd_to_frame0, rmsf_per_residue) and binds it to a short name (rgyr, sasa, "
    "rmsd, rmsf). vmd_compute(expression) then reduces the bound series with an expression YOU "
    "write over that name — for example vmd_compute(\"median(rgyr)\") or vmd_compute(\"std(sasa)\"). "
    "Available functions: max min mean std var median sum abs sqrt ptp argmin argmax len; you can "
    "index a series (series[0] is the first frame, series[-1] the last) and use comparisons. "
    "Decide which quantity AND which reduction the question calls for — the series is data, "
    "choosing the reduction is your judgment. "
    "To RECORD your final answer, call vmd_compute again with save_path set to the exact output "
    "file named in the task (e.g. vmd_compute(\"median(rgyr)\", save_path=\"/…/answer.txt\")) — the "
    "tool writes the computed value for you. Do NOT re-type the number or write the file yourself "
    "with run_vmd_command; that is where wrong answers creep in."
)


def workbench_directive(config):
    """Directive for the workbench arm (config['enable_workbench_tools'])."""
    return WORKBENCH_DIRECTIVE
