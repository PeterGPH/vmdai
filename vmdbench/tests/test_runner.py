from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card
from vmdbench.verify.runner import verify_card

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class RunnerLiveTests(unittest.TestCase):
    def _verify(self, card_rel, oracle_rel):
        card = load_card(TASKS / card_rel)
        tcl = (ORACLES / oracle_rel).read_text()
        with tempfile.TemporaryDirectory() as d:
            return verify_card(card, tcl, Path(d))

    def test_viz_oracle_passes_gate(self):
        res = self._verify("viz/viz_protein_dna_001.yaml", "viz_protein_dna_001.tcl")
        failed = [r.kind for r in res.required if not r.passed]
        self.assertTrue(res.gate, f"oracle should satisfy verifier; failed: {failed}\nobserved: "
                                  f"{[(r.kind, r.observed) for r in res.required]}")

    def test_select_oracle_passes_gate(self):
        res = self._verify("select/select_water_count_001.yaml", "select_water_count_001.tcl")
        self.assertTrue(res.gate, [(r.kind, r.observed) for r in res.required])

    def test_traj_oracle_passes_gate(self):
        res = self._verify("traj/traj_render_001.yaml", "traj_render_001.tcl")
        self.assertTrue(res.gate, [(r.kind, r.observed) for r in res.required])

    def test_view_orient_oracle_passes_gate(self):
        # Exercises representation_count + camera_changed (kinds the other cards don't use).
        res = self._verify("viz/view_orient_001.yaml", "view_orient_001.tcl")
        failed = [r.kind for r in res.required if not r.passed]
        self.assertTrue(res.gate, f"oracle should satisfy verifier; failed: {failed}\nobserved: "
                                  f"{[(r.kind, r.observed) for r in res.required]}")

    def test_empty_transcript_fails_gate(self):
        card = load_card(TASKS / "viz/viz_protein_dna_001.yaml")
        with tempfile.TemporaryDirectory() as d:
            res = verify_card(card, "# does nothing\n", Path(d))
        self.assertFalse(res.gate)


if __name__ == "__main__":
    unittest.main()
