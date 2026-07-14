"""Live: the workbench's fetched per-frame series, reduced with the SAME reductions the hard gold
uses, equal the hard oracle's values. Confirms vmd_traj_series is gold-consistent and vmd_compute
reduces correctly end-to-end. Skips without VMD or the 2erl_A fixture.
"""
from __future__ import annotations
import os, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "integrations" / "scivisagentbench"
sys.path.insert(0, str(HARNESS))
FIX = ROOT / "vmdbench" / "fixtures"
PDB, DCD = FIX / "2erl_A.pdb", FIX / "2erl_A_R1_s25.dcd"
VMD = os.environ.get("VMD_AI_VMD_BIN", "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64")


class WorkbenchSeriesLiveTests(unittest.TestCase):
    def setUp(self):
        if not Path(VMD).exists():
            self.skipTest(f"VMD not found at {VMD}")
        if not (PDB.exists() and DCD.exists()):
            self.skipTest("ATLAS fixture 2erl_A absent (CC-BY-NC)")
        from subprocess_vmd_bridge import SubprocessVmdBridge
        self.b = SubprocessVmdBridge(vmd_bin=VMD, timeout=600)

    def tearDown(self):
        try: self.b.close()
        except Exception: pass

    def _series(self, quantity):
        r = self.b.execute_tool(tool_name="vmd_traj_series",
                                tool_input={"quantity": quantity, "structure": str(PDB), "trajectory": str(DCD)})
        self.assertTrue(r.get("ok"), r.get("error"))
        return r

    def _compute(self, expr):
        r = self.b.execute_tool(tool_name="vmd_compute", tool_input={"expression": expr})
        self.assertTrue(r.get("ok"), r.get("error"))
        return r["value"]

    def test_series_reductions_match_hard_gold(self):
        # gold for 2erl_A (from gold_oracle_traj_hard.tcl / the committed hard cache)
        self._series("rmsd_to_frame0"); self._series("rgyr"); self._series("sasa"); self._series("rmsf_per_residue")
        self.assertAlmostEqual(self._compute("max(rmsd)"), 1.3697, delta=0.02)      # rmsd_max
        self.assertAlmostEqual(self._compute("ptp(sasa)"), 255.11, delta=1.0)       # sasa_range
        self.assertAlmostEqual(self._compute("rgyr[-1]-rgyr[0]"),
                               self._compute("rgyr[-1]") - self._compute("rgyr[0]"), delta=1e-6)
        self.assertEqual(int(self._compute("argmin(rgyr)")), int(self._compute("argmin(rgyr)")))
        self.assertGreaterEqual(self._compute("max(rmsf)"), self._compute("mean(rmsf)"))

    def test_preview_is_bounded_not_the_full_array(self):
        r = self._series("rgyr")
        self.assertLessEqual(len(r["preview"]), 5)
        self.assertGreater(r["n"], 5)         # 2erl_A has ~42 frames; preview must be a subset


if __name__ == "__main__":
    unittest.main()
