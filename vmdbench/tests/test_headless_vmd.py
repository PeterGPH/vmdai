from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.headless_vmd import HeadlessVMDEnv
from vmdbench.tests.fixtures import write_mini_pdb, EXPECTED_NUMATOMS


class HeadlessVMDTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.pdb = write_mini_pdb(self.work / "mini.pdb")
        self.env = HeadlessVMDEnv()

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_introspect(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'mol modstyle 0 0 NewCartoon\n'
            'mol modselect 0 0 protein\n'
            'mol modcolor 0 0 Chain\n'
        )
        res = self.env.run(body, workdir=self.work, selection_texts=["water", "protein"])
        self.assertEqual(res.returncode, 0)
        self.assertEqual(len(res.scene.molecules), 1)
        self.assertEqual(res.scene.molecules[0].num_atoms, EXPECTED_NUMATOMS)
        self.assertEqual(res.scene.representations[0].style_name, "NewCartoon")
        self.assertEqual(res.scene.representations[0].selection, "protein")
        self.assertEqual(res.scene.selections["water"], 2)
        self.assertGreater(res.scene.selections["protein"], 0)
        self.assertEqual(res.scene.errors, [])

    def test_runtime_error_recorded_but_introspection_runs(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'mol new "/nonexistent/path/nope.pdb" waitfor all\n'  # raises, caught
        )
        res = self.env.run(body, workdir=self.work, selection_texts=[])
        self.assertTrue(any("nope.pdb" in e or "Unable to load" in e or "Could not read" in e
                            for e in res.scene.errors), res.scene.errors)
        self.assertEqual(len(res.scene.molecules), 1)  # first load survived; bad load left no orphan

    def test_tachyon_render_produces_real_file(self):
        body = (
            'mol new "mini.pdb" waitfor all\n'
            'render TachyonInternal out.tga\n'
        )
        res = self.env.run(body, workdir=self.work, selection_texts=[])
        out = self.work / "out.tga"
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 1000)  # real render, not the 18-byte snapshot stub


if __name__ == "__main__":
    unittest.main()
