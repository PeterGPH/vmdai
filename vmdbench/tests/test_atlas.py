"""Live regression for the ATLAS MD-trajectory cases: run a rigid/mid/floppy sample of the
generated oracles through the real verifier and assert each one's gate passes (frames_loaded +
mean Rg + aligned mean Calpha RMSF, against the calibrated scalar_within bands).

The ATLAS fixtures are CC-BY-NC 4.0 and may not be committed; each case is SKIPPED (not failed)
when its fixtures are absent, so a checkout without the ATLAS data stays green. Regenerate with
`python scripts/make_atlas_cards.py --list scripts/atlas_subset.txt`.
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.task_card import load_card
from vmdbench.verify.runner import verify_card

_TASKS = ROOT / "vmdbench" / "tasks" / "traj"
_ORACLES = ROOT / "vmdbench" / "oracles"
_FIX = ROOT / "vmdbench" / "fixtures"

# rigid -> mid -> floppy: spans the dynamics range while keeping the live suite bounded
_SAMPLE = ["atlas_dynamics_2erl_A_001", "atlas_dynamics_6ro6_A_001", "atlas_dynamics_5w82_E_001"]


class ATLASDynamicsLiveTests(unittest.TestCase):
    def test_sampled_atlas_oracles_pass_gate(self):
        ran = 0
        for cid in _SAMPLE:
            card_p, oracle_p = _TASKS / f"{cid}.yaml", _ORACLES / f"{cid}.tcl"
            if not (card_p.exists() and oracle_p.exists()):
                continue
            card = load_card(card_p)
            missing = [f for f in card.initial_state.get("files", []) if not (_FIX / f).exists()]
            with self.subTest(case=cid):
                if missing:
                    self.skipTest(f"{cid}: ATLAS fixtures absent {missing} (CC-BY-NC; run make_atlas_cards.py)")
                with tempfile.TemporaryDirectory() as d:
                    res = verify_card(card, oracle_p.read_text(), Path(d))
                    self.assertTrue(res.gate,
                                    [(r.kind, r.passed, r.observed) for r in res.required])
                    ran += 1
        if ran == 0:
            self.skipTest("no ATLAS cases generated (run scripts/make_atlas_cards.py)")


if __name__ == "__main__":
    unittest.main()
