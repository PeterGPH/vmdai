from __future__ import annotations
import sys, unittest, tempfile, textwrap
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import TaskCard, load_card, CardError

GOOD = textwrap.dedent("""\
    task_id: viz_demo_001
    category: visualization
    bucket: synthesis
    difficulty: easy
    dimensions: [actionability, semantic_grounding]
    initial_state:
      files: [fixtures/mini.pdb]
      pdb: MINI
      molecules_loaded: false
    allowed_interface: [raw_tcl]
    user_prompt: Load and show protein as cartoon.
    verify:
      required:
        - {kind: molecule_loaded, where: {pdb: MINI}}
        - {kind: representation_exists, where: {selection: protein, style: NewCartoon}}
      optional:
        - {kind: no_runtime_errors, where: {}}
    reproducibility:
      exports: [tcl]
      replay_clean: true
""")


class TaskCardTests(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "card.yaml"
        p.write_text(text)
        return p

    def test_load_good_card(self):
        card = load_card(self._write(GOOD))
        self.assertEqual(card.task_id, "viz_demo_001")
        self.assertEqual(card.category, "visualization")
        self.assertEqual(len(card.required), 2)
        self.assertEqual(len(card.optional), 1)
        self.assertEqual([d.value for d in card.dimensions], ["actionability", "semantic_grounding"])

    def test_unknown_assertion_kind_rejected(self):
        bad = GOOD.replace("kind: molecule_loaded", "kind: bogus_kind")
        with self.assertRaises(CardError):
            load_card(self._write(bad))

    def test_missing_required_field_rejected(self):
        bad = GOOD.replace("task_id: viz_demo_001\n", "")
        with self.assertRaises(CardError):
            load_card(self._write(bad))

    def test_selection_texts_collected(self):
        card = load_card(self._write(GOOD))
        self.assertEqual(card.selection_texts(), [])  # no selection_count/visible in this card


if __name__ == "__main__":
    unittest.main()
