from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.dimensions import Dimension
from vmdbench.verify.checks import CheckResult
from vmdbench.verify.runner import VerifyResult
from vmdbench.score.scorer import score_task


def _vr(gate, required, optional):
    return VerifyResult(task_id="t", gate=gate,
                        required=[CheckResult(k, p, where=w) for (k, p, w) in required],
                        optional=[CheckResult(k, p, where=w) for (k, p, w) in optional])


class ScorerTests(unittest.TestCase):
    def test_gate_zero_zeros_gated_dims(self):
        vr = _vr(False,
                 [("representation_exists", False, {}), ("selection_count", True, {})],
                 [])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.SEMANTIC_GROUNDING])
        self.assertFalse(s.solved)
        self.assertEqual(s.dim_scores[Dimension.ACTIONABILITY], 0.0)
        self.assertEqual(s.dim_scores[Dimension.SEMANTIC_GROUNDING], 0.0)
        self.assertEqual(s.composite, 0.0)

    def test_full_pass_scores_one(self):
        vr = _vr(True,
                 [("representation_exists", True, {}), ("selection_count", True, {})],
                 [("no_runtime_errors", True, {})])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.SEMANTIC_GROUNDING,
                                       Dimension.VERIFICATION_RECOVERY])
        self.assertTrue(s.solved)
        self.assertEqual(s.dim_scores[Dimension.ACTIONABILITY], 1.0)
        self.assertEqual(s.dim_scores[Dimension.SEMANTIC_GROUNDING], 1.0)
        self.assertAlmostEqual(s.composite, 1.0, places=6)

    def test_reproducibility_signal(self):
        vr = _vr(True, [("molecule_loaded", True, {})], [])
        s = score_task(vr, dimensions=[Dimension.REPRODUCIBILITY],
                       repro_signals={"exports_ok": True, "replay_clean": True})
        self.assertEqual(s.dim_scores[Dimension.REPRODUCIBILITY], 1.0)

    def test_unevaluable_dim_excluded_from_composite(self):
        vr = _vr(True, [("representation_exists", True, {})], [])
        s = score_task(vr, dimensions=[Dimension.ACTIONABILITY, Dimension.OBSERVABILITY])
        self.assertIn(Dimension.OBSERVABILITY, s.not_evaluated)
        self.assertAlmostEqual(s.composite, 1.0, places=6)  # only actionability counts


if __name__ == "__main__":
    unittest.main()
