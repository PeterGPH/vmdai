from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card

TASKS_DIR = ROOT / "vmdbench" / "tasks"


class CardsLoadTests(unittest.TestCase):
    def test_all_cards_load_and_validate(self):
        cards = list(TASKS_DIR.rglob("*.yaml"))
        self.assertGreaterEqual(len(cards), 3)
        ids = []
        for p in cards:
            card = load_card(p)
            ids.append(card.task_id)
        self.assertEqual(len(ids), len(set(ids)), f"duplicate task_ids: {ids}")

    def test_select_card_collects_selection_texts(self):
        card = load_card(TASKS_DIR / "select" / "select_water_count_001.yaml")
        self.assertEqual(set(card.selection_texts()), {"water", "protein"})


if __name__ == "__main__":
    unittest.main()
