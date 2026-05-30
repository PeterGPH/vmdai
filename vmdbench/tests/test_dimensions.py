from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.dimensions import Dimension, DEFAULT_WEIGHTS, KIND_DIMENSIONS


class DimensionTests(unittest.TestCase):
    def test_six_dimensions(self):
        self.assertEqual(len(list(Dimension)), 6)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(DEFAULT_WEIGHTS.values()), 1.0, places=6)
        self.assertEqual(set(DEFAULT_WEIGHTS), set(Dimension))

    def test_kind_map_uses_valid_dimensions(self):
        for kind, dims in KIND_DIMENSIONS.items():
            self.assertTrue(dims, f"{kind} maps to no dimension")
            for d in dims:
                self.assertIsInstance(d, Dimension)

    def test_known_kind_mapping(self):
        self.assertIn(Dimension.SEMANTIC_GROUNDING, KIND_DIMENSIONS["selection_count"])
        self.assertIn(Dimension.ACTIONABILITY, KIND_DIMENSIONS["representation_exists"])


if __name__ == "__main__":
    unittest.main()
