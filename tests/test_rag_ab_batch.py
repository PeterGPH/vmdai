"""
Tests for scripts/rag_ab_batch.py — the suite runner + idiom scorer.

Validated separately from rag_ab.py itself so we lock in:
  * The idiom regex patterns actually fire on representative Tcl
  * Scoring is deterministic and order-independent
  * Winners are determined correctly across all four cases
    (rag wins, control wins, tie, both-failed)
  * CSV + summary JSON shapes are stable
  * --summary-only re-scores existing JSONs without re-running the API
  * --only filter works
  * skip-existing prevents redundant re-runs
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Dict, List
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
RUNTIME_DIR = ROOT / "runtime"
for p in (SCRIPTS_DIR, RUNTIME_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rag_ab_batch  # noqa: E402


# ----------------------------------------------------------------------
# Synthetic rag_ab JSON builder
# ----------------------------------------------------------------------

def _make_arm(tcl_blocks: List[str], *,
              search_queries: List[str] = (),
              snapshots: int = 0,
              error: str = None,
              elapsed: float = 1.23) -> Dict:
    tool_calls = []
    for q in search_queries:
        tool_calls.append({
            "tool_name": "search_docs",
            "tool_call_id": f"sd_{len(tool_calls)}",
            "tool_input": {"query": q, "scope": "all"},
        })
    for i, tcl in enumerate(tcl_blocks):
        tool_calls.append({
            "tool_name": "run_vmd_command",
            "tool_call_id": f"tc_{i}",
            "tool_input": {"command": tcl},
        })
    for i in range(snapshots):
        tool_calls.append({
            "tool_name": "capture_vmd_snapshot",
            "tool_call_id": f"snap_{i}",
            "tool_input": {"purpose": "x"},
        })
    return {
        "name": "test arm",
        "elapsed_s": elapsed,
        "error": error,
        "final_text": "",
        "chunks": [],
        "summary": {},
        "tool_calls": tool_calls,
    }


def _make_pair_json(tmp_path: Path, prompt_id: str,
                    prompt: str,
                    control: Dict, rag: Dict) -> Path:
    data = {
        "prompt": prompt,
        "provider_mode": "test",
        "control": control,
        "rag": rag,
    }
    p = tmp_path / f"{prompt_id}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ----------------------------------------------------------------------
# Idiom pattern fires correctly
# ----------------------------------------------------------------------

class IdiomPatternTests(unittest.TestCase):

    def test_newcartoon_detected(self):
        score = rag_ab_batch.score_arm(
            _make_arm(["mol representation NewCartoon 0.3 12.0 4.5"]),
            ["newcartoon"], "control",
        )
        self.assertTrue(score.hits["newcartoon"])

    def test_aochalky_detected(self):
        score = rag_ab_batch.score_arm(
            _make_arm(["mol material AOChalky"]),
            ["aochalky"], "control",
        )
        self.assertTrue(score.hits["aochalky"])

    def test_atp_selector_matches_anp_variant(self):
        # The kinase SKILL teaches the model to use a broad selector.
        score = rag_ab_batch.score_arm(
            _make_arm(['mol selection "resname ANP or resname ATP"']),
            ["atp_selector"], "control",
        )
        self.assertTrue(score.hits["atp_selector"])

    def test_within_select_detects_distance_cutoff(self):
        score = rag_ab_batch.score_arm(
            _make_arm(['mol selection "protein and within 4.5 of resname ATP"']),
            ["within_select"], "control",
        )
        self.assertTrue(score.hits["within_select"])

    def test_tachyon_matches_both_internal_and_external(self):
        a = rag_ab_batch.score_arm(
            _make_arm(["render TachyonInternal /tmp/x.tga"]),
            ["tachyon"], "control",
        )
        self.assertTrue(a.hits["tachyon"])
        b = rag_ab_batch.score_arm(
            _make_arm(["render Tachyon /tmp/x.dat"]),
            ["tachyon"], "control",
        )
        self.assertTrue(b.hits["tachyon"])

    def test_render_snapshot_distinct_from_tachyon(self):
        score = rag_ab_batch.score_arm(
            _make_arm(["render snapshot /tmp/x.tga"]),
            ["tachyon", "render_snapshot"], "control",
        )
        # snapshot does NOT count as tachyon — they're different categories.
        self.assertFalse(score.hits["tachyon"])
        self.assertTrue(score.hits["render_snapshot"])

    def test_imatinib_selector(self):
        score = rag_ab_batch.score_arm(
            _make_arm(['mol selection "resname STI"']),
            ["imatinib_sel"], "rag",
        )
        self.assertTrue(score.hits["imatinib_sel"])

    def test_pattern_is_case_insensitive(self):
        score = rag_ab_batch.score_arm(
            _make_arm(["MOL Representation newcartoon"]),
            ["newcartoon"], "control",
        )
        self.assertTrue(score.hits["newcartoon"])

    def test_missing_idiom_scored_as_miss(self):
        score = rag_ab_batch.score_arm(
            _make_arm(["mol new 1ubq.pdb"]),
            ["newcartoon", "tachyon"], "control",
        )
        self.assertFalse(score.hits["newcartoon"])
        self.assertFalse(score.hits["tachyon"])
        self.assertEqual(score.hit_count, 0)
        self.assertEqual(score.applicable, 2)
        self.assertAlmostEqual(score.coverage, 0.0)


# ----------------------------------------------------------------------
# Arm-level counting
# ----------------------------------------------------------------------

class ArmCountTests(unittest.TestCase):

    def test_counts_each_tool_type(self):
        arm = _make_arm(
            ["mol new x.pdb", "mol addrep top"],
            search_queries=["academic style"],
            snapshots=2,
        )
        score = rag_ab_batch.score_arm(arm, ["newcartoon"], "rag")
        self.assertEqual(score.vmd_command_count, 2)
        self.assertEqual(score.search_query_count, 1)
        self.assertEqual(score.snapshot_count, 2)

    def test_errored_arm_records_error_field(self):
        arm = _make_arm([], error="HTTP 429 rate limit")
        score = rag_ab_batch.score_arm(arm, ["newcartoon"], "rag")
        self.assertEqual(score.error, "HTTP 429 rate limit")


# ----------------------------------------------------------------------
# Winner determination
# ----------------------------------------------------------------------

class WinnerTests(unittest.TestCase):

    def _result(self, control_tcl, rag_tcl, expects,
                control_err=None, rag_err=None) -> rag_ab_batch.PromptResult:
        with tempfile.TemporaryDirectory() as tmp:
            json_path = _make_pair_json(
                Path(tmp), "test_prompt", "p",
                _make_arm(control_tcl, error=control_err),
                _make_arm(rag_tcl, error=rag_err),
            )
            spec = rag_ab_batch.PromptSpec(
                id="test_prompt", prompt="p", expects=expects,
            )
            return rag_ab_batch.score_prompt_json(json_path, spec)

    def test_rag_wins_when_more_idioms_hit(self):
        r = self._result(
            control_tcl=["mol new 1ubq.pdb"],
            rag_tcl=[
                "mol new 1ubq.pdb",
                "mol representation NewCartoon",
                "mol material AOChalky",
                "render TachyonInternal /tmp/x.tga",
            ],
            expects=["newcartoon", "aochalky", "tachyon"],
        )
        self.assertEqual(r.winner, "rag")

    def test_control_wins_when_more_idioms_hit(self):
        r = self._result(
            control_tcl=[
                "mol representation NewCartoon",
                "mol material AOChalky",
                "render TachyonInternal /tmp/x.tga",
            ],
            rag_tcl=["mol new 1ubq.pdb"],
            expects=["newcartoon", "aochalky", "tachyon"],
        )
        self.assertEqual(r.winner, "control")

    def test_tie_when_equal_coverage(self):
        r = self._result(
            control_tcl=["mol representation NewCartoon"],
            rag_tcl=["mol representation NewCartoon"],
            expects=["newcartoon", "aochalky"],
        )
        self.assertEqual(r.winner, "tie")

    def test_both_failed_when_both_errored(self):
        r = self._result(
            control_tcl=[], rag_tcl=[],
            expects=["newcartoon"],
            control_err="oops", rag_err="oops",
        )
        self.assertEqual(r.winner, "both_failed")

    def test_only_one_arm_errored_other_wins(self):
        r = self._result(
            control_tcl=[],
            rag_tcl=["mol representation NewCartoon"],
            expects=["newcartoon"],
            control_err="oops", rag_err=None,
        )
        self.assertEqual(r.winner, "rag")


# ----------------------------------------------------------------------
# CSV + summary
# ----------------------------------------------------------------------

class OutputShapeTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name)
        # Two synthetic prompts
        self.specs = [
            rag_ab_batch.PromptSpec(
                id="alpha", prompt="alpha test",
                expects=["newcartoon", "aochalky"],
            ),
            rag_ab_batch.PromptSpec(
                id="beta", prompt="beta test",
                expects=["tachyon"],
            ),
        ]
        _make_pair_json(
            self.out_dir, "alpha", "alpha test",
            _make_arm(["mol representation NewCartoon"]),
            _make_arm([
                "mol representation NewCartoon",
                "mol material AOChalky",
            ]),
        )
        _make_pair_json(
            self.out_dir, "beta", "beta test",
            _make_arm(["render snapshot foo.tga"]),
            _make_arm(["render TachyonInternal foo.tga"]),
        )
        self.results = [
            rag_ab_batch.score_prompt_json(self.out_dir / "alpha.json",
                                            self.specs[0]),
            rag_ab_batch.score_prompt_json(self.out_dir / "beta.json",
                                            self.specs[1]),
        ]

    def test_csv_has_one_row_per_arm_per_prompt(self):
        csv_path = self.out_dir / "scorecard.csv"
        rag_ab_batch.write_scorecard_csv(self.results, csv_path)
        lines = csv_path.read_text().splitlines()
        # 1 header + 2 prompts × 2 arms = 5 lines
        self.assertEqual(len(lines), 5)

    def test_csv_has_expected_header_columns(self):
        csv_path = self.out_dir / "scorecard.csv"
        rag_ab_batch.write_scorecard_csv(self.results, csv_path)
        header = csv_path.read_text().splitlines()[0].split(",")
        for col in ("prompt_id", "arm", "applicable", "hit_count",
                    "coverage"):
            self.assertIn(col, header)

    def test_summary_json_has_per_prompt_and_aggregates(self):
        path = self.out_dir / "summary.json"
        summary = rag_ab_batch.write_summary_json(self.results, path)
        self.assertEqual(summary["n_prompts"], 2)
        self.assertIn("wins", summary)
        self.assertIn("control_mean_coverage", summary)
        self.assertIn("rag_mean_coverage", summary)
        self.assertEqual(len(summary["per_prompt"]), 2)

    def test_summary_counts_correct_winners(self):
        # alpha: control 1/2, rag 2/2 → rag wins
        # beta:  control 0/1, rag 1/1 → rag wins
        path = self.out_dir / "summary.json"
        summary = rag_ab_batch.write_summary_json(self.results, path)
        self.assertEqual(summary["wins"]["rag"], 2)
        self.assertEqual(summary["wins"]["control"], 0)
        self.assertEqual(summary["wins"]["tie"], 0)


# ----------------------------------------------------------------------
# CLI behavior — no real API calls
# ----------------------------------------------------------------------

class CLIBehaviorTests(unittest.TestCase):

    def _stub_rag_ab_main(self, results_factory):
        """Replace rag_ab.main with a stub that writes a synthetic JSON
        to the path passed via --json and returns 0.
        """
        def fake_main(argv):
            # Parse --json out of argv
            json_path = None
            i = 0
            while i < len(argv):
                if argv[i] == "--json":
                    json_path = Path(argv[i + 1])
                    break
                i += 1
            assert json_path is not None
            data = results_factory()
            json_path.write_text(json.dumps(data), encoding="utf-8")
            return 0
        return fake_main

    def test_only_filter_runs_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            results_called = {"count": 0}

            def factory():
                results_called["count"] += 1
                return {
                    "prompt": "p", "provider_mode": "test",
                    "control": _make_arm([]),
                    "rag": _make_arm([]),
                }

            with mock.patch("rag_ab_batch.rag_ab.main",
                            new=self._stub_rag_ab_main(factory)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = rag_ab_batch.main([
                        "--out-dir", tmp,
                        "--provider", "mock",
                        "--sleep", "0",
                        "--sleep-between-prompts", "0",
                        "--only", "cdk2_atp",
                    ])
            self.assertEqual(rc, 0)
            self.assertEqual(results_called["count"], 1)
            self.assertTrue((Path(tmp) / "cdk2_atp.json").exists())
            self.assertFalse((Path(tmp) / "abl_imatinib.json").exists())

    def test_skip_existing_avoids_re_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Pre-seed cdk2_atp.json
            _make_pair_json(
                Path(tmp), "cdk2_atp", "p",
                _make_arm(["mol representation NewCartoon"]),
                _make_arm(["mol representation NewCartoon",
                           "mol material AOChalky"]),
            )
            results_called = {"count": 0}

            def factory():
                results_called["count"] += 1
                return {
                    "prompt": "p", "provider_mode": "test",
                    "control": _make_arm([]),
                    "rag": _make_arm([]),
                }

            with mock.patch("rag_ab_batch.rag_ab.main",
                            new=self._stub_rag_ab_main(factory)):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = rag_ab_batch.main([
                        "--out-dir", tmp,
                        "--provider", "mock", "--sleep", "0",
                        "--sleep-between-prompts", "0",
                        "--only", "cdk2_atp",
                        "--skip-existing",
                    ])
            self.assertEqual(rc, 0)
            # Should NOT have re-run because the JSON already exists
            self.assertEqual(results_called["count"], 0)

    def test_summary_only_does_not_invoke_rag_ab(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_pair_json(
                Path(tmp), "cdk2_atp", "p",
                _make_arm([]),
                _make_arm(["mol representation NewCartoon"]),
            )
            with mock.patch("rag_ab_batch.rag_ab.main") as fake:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = rag_ab_batch.main([
                        "--out-dir", tmp,
                        "--only", "cdk2_atp",
                        "--summary-only",
                    ])
            self.assertEqual(rc, 0)
            # rag_ab.main MUST NOT have been called
            fake.assert_not_called()
            # Summary file should exist
            self.assertTrue((Path(tmp) / "summary.json").exists())
            self.assertTrue((Path(tmp) / "scorecard.csv").exists())


if __name__ == "__main__":
    unittest.main()
