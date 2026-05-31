from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card
from vmdbench.adapters.oracle_tcl import run_oracle

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class OracleLiveTests(unittest.TestCase):
    def test_select_oracle_reports_gold_counts(self):
        card = load_card(TASKS / "select" / "select_water_count_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            run = run_oracle(card, ORACLES / "select_water_count_001.tcl", Path(d))
            self.assertEqual(run.result.scene.selections["water"], 2)
            self.assertGreater(run.result.scene.selections["protein"], 0)
            self.assertEqual(run.result.scene.errors, [])

    def test_viz_oracle_builds_reps_and_renders(self):
        card = load_card(TASKS / "viz" / "viz_protein_dna_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            run = run_oracle(card, ORACLES / "viz_protein_dna_001.tcl", Path(d))
            scene = run.result.scene
            styles = {r.style_name for r in scene.representations}
            self.assertIn("NewCartoon", styles)
            self.assertIn("Licorice", styles)
            self.assertEqual(scene.display.background, "white")
            self.assertTrue((run.workdir / "out.tga").exists())
            self.assertGreater((run.workdir / "out.tga").stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
