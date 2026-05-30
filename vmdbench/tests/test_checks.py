from __future__ import annotations
import sys, unittest, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.scene_state import SceneState, Molecule, Representation, Display
from vmdbench.verify.checks import evaluate, CheckContext


def _scene():
    return SceneState(
        molecules=[Molecule(id=0, name="mini.pdb", num_atoms=9, num_frames=1)],
        representations=[
            Representation(mol_id=0, rep_id=0, style="NewCartoon 0.3", selection="protein", color="Chain", visible=True),
            Representation(mol_id=0, rep_id=1, style="VDW 1.0", selection="water", color="ColorID 1", visible=False),
        ],
        selections={"water": 2, "protein": 5},
        display=Display(background="white", projection="Orthographic", axes="Off"),
        camera={"rotate_matrix": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]},
        errors=[],
    )


class ChecksTests(unittest.TestCase):
    def setUp(self):
        self.scene = _scene()
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = CheckContext(workdir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _ev(self, a):
        return evaluate(a, self.scene, self.ctx)

    def test_molecule_loaded(self):
        self.assertTrue(self._ev({"kind": "molecule_loaded", "where": {}}).passed)

    def test_representation_exists_match_and_miss(self):
        self.assertTrue(self._ev({"kind": "representation_exists",
                                  "where": {"selection": "protein", "style": "NewCartoon"}}).passed)
        self.assertFalse(self._ev({"kind": "representation_exists",
                                   "where": {"selection": "protein", "style": "VDW"}}).passed)

    def test_selection_visible_false(self):
        self.assertTrue(self._ev({"kind": "selection_visible",
                                  "where": {"selection": "water"}, "visible": False}).passed)

    def test_selection_count_expect(self):
        self.assertTrue(self._ev({"kind": "selection_count", "where": {"selection": "water", "expect": 2}}).passed)
        self.assertFalse(self._ev({"kind": "selection_count", "where": {"selection": "water", "expect": 3}}).passed)
        self.assertTrue(self._ev({"kind": "selection_count", "where": {"selection": "protein", "min": 1}}).passed)

    def test_display_property(self):
        self.assertTrue(self._ev({"kind": "display_property", "where": {"bg_color": "white"}}).passed)
        self.assertFalse(self._ev({"kind": "display_property", "where": {"bg_color": "black"}}).passed)

    def test_distinct_chain_colors(self):
        self.assertTrue(self._ev({"kind": "distinct_chain_colors", "where": {"min_distinct": 2}}).passed)

    def test_no_runtime_errors(self):
        self.assertTrue(self._ev({"kind": "no_runtime_errors", "where": {}}).passed)
        self.scene.errors.append("boom")
        self.assertFalse(self._ev({"kind": "no_runtime_errors", "where": {}}).passed)

    def test_frames_loaded(self):
        self.assertTrue(self._ev({"kind": "frames_loaded", "where": {"min": 1}}).passed)

    def test_file_rendered(self):
        target = self.ctx.workdir / "out.tga"
        target.write_bytes(b"\x00" * 2048)
        self.assertTrue(self._ev({"kind": "file_rendered",
                                  "where": {"path": "out.tga", "min_bytes": 1000}}).passed)
        self.assertFalse(self._ev({"kind": "file_rendered",
                                   "where": {"path": "missing.tga", "min_bytes": 1000}}).passed)


if __name__ == "__main__":
    unittest.main()
