from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.env.scene_state import SceneState, parse_probe_lines

SAMPLE = """\
Info) startup junk ignored
PROBE> mol_list=0
PROBE> mol_top=0
PROBE> mol0_name=mini.pdb
PROBE> mol0_filename=/tmp/mini.pdb
PROBE> mol0_filetype=pdb
PROBE> mol0_numatoms=9
PROBE> mol0_numframes=1
PROBE> mol0_frame=0
PROBE> mol0_numreps=2
PROBE> rep0_0_style=NewCartoon 0.300000 12.000000 4.500000 0
PROBE> rep0_0_selection=protein
PROBE> rep0_0_color=Chain
PROBE> rep0_0_material=Opaque
PROBE> rep0_0_visible=1
PROBE> rep0_1_style=VDW 1.000000 12.000000
PROBE> rep0_1_selection=water
PROBE> rep0_1_color=ColorID 1
PROBE> rep0_1_material=Opaque
PROBE> rep0_1_visible=0
PROBE> display_background=white
PROBE> display_projection=Orthographic
PROBE> axes_location=Off
PROBE> view_center={3.9 2.6 1.5}
PROBE> view_rotate_matrix={{1 0 0 0} {0 1 0 0} {0 0 1 0} {0 0 0 1}}
PROBE> view_scale_matrix={{0.13 0 0 0} {0 0.13 0 0} {0 0 0.13 0} {0 0 0 1}}
PROBE> sel0_count=2
PROBE> sel1_error=atomselect: cannot parse selection text: resname (
ERROR) Could not read file /nonexistent.pdb
"""


class SceneStateParseTests(unittest.TestCase):
    def setUp(self):
        self.scene = parse_probe_lines(SAMPLE, selection_texts=["water", "resname ("])

    def test_molecule_parsed(self):
        self.assertEqual(len(self.scene.molecules), 1)
        m = self.scene.molecules[0]
        self.assertEqual(m.id, 0)
        self.assertEqual(m.num_atoms, 9)
        self.assertEqual(m.num_frames, 1)
        self.assertEqual(m.name, "mini.pdb")

    def test_reps_parsed(self):
        self.assertEqual(len(self.scene.representations), 2)
        r0 = self.scene.representations[0]
        self.assertEqual(r0.style_name, "NewCartoon")
        self.assertEqual(r0.selection, "protein")
        self.assertEqual(r0.color, "Chain")
        self.assertTrue(r0.visible)
        self.assertFalse(self.scene.representations[1].visible)

    def test_display_parsed(self):
        self.assertEqual(self.scene.display.background, "white")
        self.assertEqual(self.scene.display.projection, "Orthographic")
        self.assertEqual(self.scene.display.axes, "Off")

    def test_selection_counts(self):
        self.assertEqual(self.scene.selections["water"], 2)
        self.assertNotIn("resname (", self.scene.selections)  # errored selection omitted

    def test_errors_collected(self):
        joined = " ".join(self.scene.errors)
        self.assertIn("Could not read file", joined)
        self.assertIn("cannot parse selection text", joined)

    def test_camera_changed_default_false(self):
        # identity rotate + this scale is the loaded default; helper reports not-changed
        self.assertFalse(self.scene.camera_changed())


if __name__ == "__main__":
    unittest.main()
