from __future__ import annotations
import sys, unittest, tempfile, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASKS = ROOT / "vmdbench" / "tasks"
ORACLES = ROOT / "vmdbench" / "oracles"


class CliLiveTests(unittest.TestCase):
    def test_score_oracle_emits_json_with_solved_true(self):
        with tempfile.TemporaryDirectory() as d:
            out = subprocess.run(
                [sys.executable, "-m", "vmdbench.cli", "score-oracle",
                 str(TASKS / "viz/viz_protein_dna_001.yaml"),
                 str(ORACLES / "viz_protein_dna_001.tcl"),
                 "--workdir", d],
                cwd=str(ROOT), capture_output=True, text=True, timeout=300,
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            payload = json.loads(out.stdout)
            self.assertTrue(payload["verify"]["gate"])
            self.assertTrue(payload["score"]["solved"])
            self.assertTrue(payload["replay_clean"])
            self.assertGreater(payload["score"]["composite"], 0.0)


if __name__ == "__main__":
    unittest.main()
