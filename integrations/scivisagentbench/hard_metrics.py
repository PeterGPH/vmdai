#!/usr/bin/env python3
"""hard_metrics.py — the HARD/reasoning tier catalog for `run_atlas_traj.py --hard`.

Each task HIDES the formulation: the prompt states a scientific goal in plain language (no metric
name, no formula, no VMD command) and asks for a COMPOSED observable the semantic tool cannot
answer in one call. Gold is a single determinate number from gold_oracle_traj_hard.tcl.
Spec: docs/superpowers/specs/2026-07-10-hard-reasoning-tier-design.md

Tolerances below are provisional-WIDE so the harness runs; tighten with calibrate_hard.py before
the real eval. Values are (question incl. unit, absolute tolerance, scored?) to match the 3-tuple
the run_atlas_traj main loop unpacks.
"""
HARD_METRICS = {
    "rg_std": (
        "Proteins breathe: their overall size fluctuates as they move. How much does this "
        "protein's overall size fluctuate over the whole trajectory? Report a single number in "
        "Angstroms.", 0.30, True),
    "rmsd_max": (
        "Over the trajectory, how far does the backbone get from the starting structure at its "
        "most-deviated point? Report that largest deviation as a single number in Angstroms.",
        1.5, True),
    "sasa_range": (
        "The protein's exposed surface area changes frame to frame. How large is the swing "
        "between its most-exposed and least-exposed frames? Report a single number in square "
        "Angstroms.", 1500.0, True),
    "rmsf_max": (
        "Some residues move much more than others. How mobile is the single most mobile residue "
        "over the trajectory? Report a single number in Angstroms.", 1.0, True),
    "rg_argmin_frame": (
        "At which frame of the trajectory is the protein at its most compact? Report the frame "
        "index as a single integer (the first frame is 0).", 0.5, True),
    "rg_delta": (
        "Comparing the last frame to the first, how much larger or smaller is the protein's "
        "overall size? Report a single signed number in Angstroms (negative if it shrank).",
        1.5, True),
    "rg_ratio": (
        "By what factor does the protein's overall size change from the first frame to the last? "
        "Report a single dimensionless number (1.0 means no change).", 0.15, True),
}

# intended_quantity per key — the spec-adequacy annotation (spec §8). Used by tests + calibration.
HARD_INTENT = {
    "rg_std": "population standard deviation of per-frame radius of gyration (protein), Angstrom",
    "rmsd_max": "maximum over frames of aligned Calpha RMSD-to-frame-0, Angstrom",
    "sasa_range": "max(SASA) - min(SASA) over frames (protein, measure sasa 1.4), Angstrom^2",
    "rmsf_max": "maximum per-residue Calpha RMSF over the trajectory, Angstrom",
    "rg_argmin_frame": "0-based frame index minimizing radius of gyration",
    "rg_delta": "Rg(last) - Rg(first), signed, Angstrom",
    "rg_ratio": "Rg(last) / Rg(first), dimensionless",
}


def build_hard_prompt(pdb, dcd, question, answer_path):
    """Recipe-stripped prompt: keep ONLY the mechanical plumbing (load + write); the reasoning
    (which metric / formula / VMD command) is withheld on purpose — that IS the task."""
    return (
        "You are controlling VMD headlessly through the run_vmd_command tool (Tcl).\n"
        "Load this structure and its trajectory:\n"
        f'    mol new "{pdb}" waitfor all\n'
        f'    mol addfile "{dcd}" waitfor all\n'
        f"{question}\n"
        "Report a single number and write ONLY that value (digits only, no words) to this exact "
        "file:\n"
        f'    set f [open "{answer_path}" w]; puts $f $value; close $f\n'
        "Finish in as few commands as possible."
    )
