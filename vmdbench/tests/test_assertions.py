from __future__ import annotations
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vmdbench.spec.assertions import (
    KNOWN_KINDS, validate_assertion, AssertionError as VBAssertionError,
    register_custom_check, CUSTOM_CHECKS,
)


class AssertionContractTests(unittest.TestCase):
    def test_known_kinds_closed_set(self):
        for k in ["molecule_loaded", "representation_exists", "selection_count",
                  "selection_visible", "display_property", "file_rendered",
                  "no_runtime_errors", "distinct_chain_colors", "frames_loaded",
                  "camera_changed", "file_exists", "representation_count", "custom_check"]:
            self.assertIn(k, KNOWN_KINDS)

    def test_validate_good_assertion(self):
        validate_assertion({"kind": "representation_exists",
                            "where": {"selection": "protein", "style": "NewCartoon"}})

    def test_unknown_kind_rejected(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "make_it_pretty", "where": {}})

    def test_missing_where_rejected(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "representation_exists"})

    def test_custom_check_requires_registered_ref(self):
        with self.assertRaises(VBAssertionError):
            validate_assertion({"kind": "custom_check", "where": {"ref": "not_registered"}})
        register_custom_check("my_reviewed_check", lambda scene, ctx, where: True)
        validate_assertion({"kind": "custom_check", "where": {"ref": "my_reviewed_check"}})
        self.assertIn("my_reviewed_check", CUSTOM_CHECKS)


if __name__ == "__main__":
    unittest.main()
