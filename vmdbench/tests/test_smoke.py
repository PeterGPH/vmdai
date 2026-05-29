from __future__ import annotations
import sys, unittest, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.tests.fixtures import write_mini_pdb, EXPECTED_NUMATOMS


class SmokeTests(unittest.TestCase):
    def test_vmd_present(self):
        self.assertIsNotNone(shutil.which("vmd"), "vmd must be on PATH for the bench")

    def test_vmd_loads_fixture_headless(self):
        with tempfile.TemporaryDirectory() as d:
            pdb = write_mini_pdb(Path(d) / "mini.pdb")
            script = Path(d) / "probe.tcl"
            script.write_text(
                f'mol new "{pdb}" waitfor all\n'
                'puts "PROBE> numatoms=[molinfo top get numatoms]"\n'
                'quit\n'
            )
            out = subprocess.run(
                ["vmd", "-dispdev", "text", "-eofexit", "-e", str(script)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertIn(f"PROBE> numatoms={EXPECTED_NUMATOMS}", out.stdout,
                          msg=f"stdout was:\n{out.stdout}\nstderr:\n{out.stderr}")


if __name__ == "__main__":
    unittest.main()
