"""Live cross-validation of gold_oracle_traj_hard.tcl: run the hard oracle under real VMD on a
committed ATLAS fixture, assert (a) all scored keys are emitted, (b) physical invariant relations
hold, and (c) the Rg-derived quantities match an INDEPENDENT MDAnalysis computation. Skips (never
fails) when VMD, the fixture, or MDAnalysis is absent, so a plain checkout stays green.
"""
from __future__ import annotations
import os, re, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "integrations" / "scivisagentbench" / "gold_oracle_traj_hard.tcl"
FIX = ROOT / "vmdbench" / "fixtures"
PDB, DCD = FIX / "2erl_A.pdb", FIX / "2erl_A_R1_s25.dcd"
VMD = os.environ.get("VMD_AI_VMD_BIN", "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64")
SCORED = ("rg_std", "rmsd_max", "sasa_range", "rmsf_max", "rg_argmin_frame", "rg_delta", "rg_ratio")


def _run_oracle():
    env = dict(os.environ, GOLD_STRUCT=str(PDB), GOLD_TRAJ=str(DCD))
    out = subprocess.run([VMD, "-dispdev", "text", "-e", str(ORACLE)], env=env,
                         capture_output=True, text=True, timeout=600).stdout
    g = {}
    for line in out.splitlines():
        m = re.match(r"\s*GOLD\s+(\S+)\s+(\S+)", line)
        if m:
            try: g[m.group(1)] = float(m.group(2))
            except ValueError: pass
    return g


class HardOracleLiveTests(unittest.TestCase):
    def setUp(self):
        if not Path(VMD).exists():
            self.skipTest(f"VMD not found at {VMD} (set VMD_AI_VMD_BIN)")
        if not (PDB.exists() and DCD.exists()):
            self.skipTest(f"ATLAS fixture 2erl_A absent (CC-BY-NC; run scripts/make_atlas_cards.py)")
        self.g = _run_oracle()

    def test_all_scored_keys_emitted(self):
        missing = [k for k in SCORED if k not in self.g]
        self.assertFalse(missing, f"oracle did not emit {missing}; got {sorted(self.g)}")

    def test_invariant_relations(self):
        g = self.g
        n = g["nframes"]
        self.assertGreaterEqual(g["rg_std"], 0.0)
        self.assertGreaterEqual(g["sasa_range"], 0.0)
        self.assertGreaterEqual(g["rmsd_max"], g["meanrmsd"] - 1e-6)   # max >= mean
        self.assertGreaterEqual(g["rmsf_max"], g["mean_rmsf"] - 1e-6)
        self.assertTrue(0 <= g["rg_argmin_frame"] <= n - 1)
        self.assertEqual(g["rg_argmin_frame"], round(g["rg_argmin_frame"]))  # integer
        self.assertAlmostEqual(g["rg_delta"], g["rg_last"] - g["rg_first"], places=4)
        self.assertAlmostEqual(g["rg_ratio"], g["rg_last"] / g["rg_first"], places=4)
        self.assertLessEqual(g["rg_min"], g["meanrg"] + 1e-6)
        self.assertIn("rg_second_min", g)
        self.assertGreaterEqual(g["rg_second_min"], g["rg_min"] - 1e-6)

    def test_rg_quantities_match_mdanalysis(self):
        try:
            import numpy as np
            import MDAnalysis as mda
        except ImportError:
            self.skipTest("MDAnalysis not installed")
        g = self.g
        # VMD's `mol new <pdb>` + `mol addfile <dcd>` makes the PDB's coordinates frame 0,
        # so nframes = 1 + len(DCD). Replicate that exact frame set so the cross-check is
        # apples-to-apples (otherwise MDAnalysis is off-by-one vs VMD).
        rg0 = mda.Universe(str(PDB)).select_atoms("protein").radius_of_gyration()
        ut = mda.Universe(str(PDB), str(DCD))
        rgt = [ut.select_atoms("protein").radius_of_gyration() for _ in ut.trajectory]
        rgs = np.array([rg0] + rgt)
        self.assertEqual(len(rgs), int(g["nframes"]))   # frame-set convention lock
        self.assertAlmostEqual(g["rg_std"], float(rgs.std()), delta=0.05)          # population std
        self.assertAlmostEqual(g["rg_delta"], float(rgs[-1] - rgs[0]), delta=0.05)
        self.assertAlmostEqual(g["rg_ratio"], float(rgs[-1] / rgs[0]), delta=0.01)
        self.assertEqual(int(g["rg_argmin_frame"]), int(rgs.argmin()))


if __name__ == "__main__":
    unittest.main()
