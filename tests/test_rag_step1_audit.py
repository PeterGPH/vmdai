"""
Step 1 — audit module tests.

Covers:
    GoldenSet · load / validate / error paths
    Metrics   · recall@k, MRR@k, nDCG@k, mean/percentile edge cases
    Audit     · corpus loading, deterministic output, report shape,
                CLI smoke, baseline numbers on the fixture corpus

These tests are pure stdlib (no fastembed, no torch) and run in <1s.
They lock in the baseline so subsequent steps can be evaluated as
deltas against it.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.rag.audit import (  # noqa: E402
    audit,
    load_corpus,
    main as audit_main,
)
from vmd_ai_runtime.rag.golden import (  # noqa: E402
    GoldenSetError,
    load_golden,
    summarize,
)
from vmd_ai_runtime.rag.metrics import (  # noqa: E402
    mean,
    mrr_at_k,
    ndcg_at_k,
    percentile,
    recall_at_k,
)


FIXTURE_CORPUS = ROOT / "tests" / "fixtures" / "docs"
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "rag_golden.jsonl"


# ----------------------------------------------------------------------
# Golden set
# ----------------------------------------------------------------------

class GoldenLoadTests(unittest.TestCase):

    def test_loads_repo_golden_set(self):
        items = load_golden(GOLDEN_PATH)
        self.assertGreaterEqual(len(items), 10)
        qids = [it.qid for it in items]
        self.assertEqual(len(set(qids)), len(qids), "qids must be unique")

    def test_summary_counts(self):
        items = load_golden(GOLDEN_PATH)
        summ = summarize(items)
        self.assertEqual(summ["total"], len(items))
        self.assertGreater(summ["tag_counts"].get("identifier", 0), 0)
        self.assertGreater(summ["tag_counts"].get("paraphrase", 0), 0)
        self.assertGreaterEqual(summ["avg_relevant_per_query"], 1.0)

    def test_matches_predicate_on_suffix(self):
        items = load_golden(GOLDEN_PATH)
        item = next(it for it in items if it.qid == "id-atomselect")
        # Exact suffix
        self.assertTrue(item.matches(
            {"source": "vmd_ref/atomselect.md", "section": "atomselect"}
        ))
        # Longer-prefix suffix still matches
        self.assertTrue(item.matches(
            {"source": "/abs/path/to/vmd_ref/atomselect.md",
             "section": "atomselect"}
        ))
        # Wrong section
        self.assertFalse(item.matches(
            {"source": "vmd_ref/atomselect.md", "section": "atomselect frame"}
        ))
        # Wrong file
        self.assertFalse(item.matches(
            {"source": "vmd_ref/mol.md", "section": "atomselect"}
        ))


class GoldenValidationTests(unittest.TestCase):

    def _write(self, content: str) -> Path:
        tmp = Path(tempfile.mkstemp(suffix=".jsonl")[1])
        tmp.write_text(content, encoding="utf-8")
        self.addCleanup(tmp.unlink)
        return tmp

    def test_missing_file_raises(self):
        with self.assertRaises(GoldenSetError):
            load_golden("/nonexistent/path.jsonl")

    def test_empty_file_raises(self):
        p = self._write("")
        with self.assertRaises(GoldenSetError):
            load_golden(p)

    def test_invalid_json_raises_with_line(self):
        p = self._write('{"qid":"a","query":"q","relevant":[["s","x"]]}\nNOPE\n')
        with self.assertRaisesRegex(GoldenSetError, r"line 2"):
            load_golden(p)

    def test_duplicate_qid_raises(self):
        p = self._write(
            '{"qid":"x","query":"q","relevant":[["s","x"]]}\n'
            '{"qid":"x","query":"q2","relevant":[["s","y"]]}\n'
        )
        with self.assertRaisesRegex(GoldenSetError, r"duplicate qid"):
            load_golden(p)

    def test_missing_required_field(self):
        p = self._write('{"qid":"x","query":"q"}\n')
        with self.assertRaisesRegex(GoldenSetError, r"missing required"):
            load_golden(p)

    def test_empty_relevant_list(self):
        p = self._write('{"qid":"x","query":"q","relevant":[]}\n')
        with self.assertRaisesRegex(GoldenSetError, r"non-empty list"):
            load_golden(p)

    def test_relevant_must_be_pairs(self):
        p = self._write('{"qid":"x","query":"q","relevant":[["s"]]}\n')
        with self.assertRaisesRegex(GoldenSetError, r"\[source_suffix, section\]"):
            load_golden(p)

    def test_comments_and_blank_lines_skipped(self):
        p = self._write(
            "# header comment\n"
            "\n"
            '{"qid":"x","query":"q","relevant":[["s","sec"]]}\n'
            "\n"
        )
        items = load_golden(p)
        self.assertEqual(len(items), 1)


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------

class MetricsTests(unittest.TestCase):

    def _pred(self, source_section_pairs):
        wanted = set(source_section_pairs)
        return lambda c: (c["source"], c["section"]) in wanted

    def _make(self, *pairs):
        return [{"source": s, "section": sec} for s, sec in pairs]

    def test_recall_at_k_hit(self):
        retrieved = self._make(("a", "1"), ("b", "2"), ("c", "3"))
        is_rel = self._pred([("b", "2")])
        self.assertEqual(recall_at_k(retrieved, is_rel, 3), 1.0)
        self.assertEqual(recall_at_k(retrieved, is_rel, 2), 1.0)
        self.assertEqual(recall_at_k(retrieved, is_rel, 1), 0.0)

    def test_recall_at_k_total_relevant_normalization(self):
        retrieved = self._make(("a", "1"), ("b", "2"), ("c", "3"))
        is_rel = self._pred([("a", "1"), ("c", "3")])
        # 2 of 5 total relevant
        self.assertAlmostEqual(
            recall_at_k(retrieved, is_rel, 3, total_relevant=5), 2 / 5,
        )

    def test_mrr_at_k(self):
        retrieved = self._make(("a", "1"), ("b", "2"), ("c", "3"))
        self.assertAlmostEqual(
            mrr_at_k(retrieved, self._pred([("a", "1")]), 3), 1.0,
        )
        self.assertAlmostEqual(
            mrr_at_k(retrieved, self._pred([("b", "2")]), 3), 1 / 2,
        )
        self.assertAlmostEqual(
            mrr_at_k(retrieved, self._pred([("c", "3")]), 3), 1 / 3,
        )
        self.assertEqual(
            mrr_at_k(retrieved, self._pred([("z", "9")]), 3), 0.0,
        )

    def test_ndcg_first_position_is_one(self):
        retrieved = self._make(("a", "1"), ("b", "2"))
        is_rel = self._pred([("a", "1")])
        self.assertAlmostEqual(ndcg_at_k(retrieved, is_rel, 2), 1.0)

    def test_ndcg_no_hit_is_zero(self):
        retrieved = self._make(("a", "1"), ("b", "2"))
        is_rel = self._pred([("z", "9")])
        self.assertEqual(ndcg_at_k(retrieved, is_rel, 2), 0.0)

    def test_ndcg_monotonic_with_rank(self):
        retrieved = self._make(("a", "1"), ("b", "2"), ("c", "3"))
        first = ndcg_at_k(retrieved, self._pred([("a", "1")]), 3)
        second = ndcg_at_k(retrieved, self._pred([("b", "2")]), 3)
        third = ndcg_at_k(retrieved, self._pred([("c", "3")]), 3)
        self.assertGreater(first, second)
        self.assertGreater(second, third)

    def test_k_zero_is_zero(self):
        retrieved = self._make(("a", "1"))
        is_rel = self._pred([("a", "1")])
        self.assertEqual(recall_at_k(retrieved, is_rel, 0), 0.0)
        self.assertEqual(mrr_at_k(retrieved, is_rel, 0), 0.0)
        self.assertEqual(ndcg_at_k(retrieved, is_rel, 0), 0.0)

    def test_empty_retrieved_is_zero(self):
        is_rel = self._pred([("a", "1")])
        self.assertEqual(recall_at_k([], is_rel, 5), 0.0)
        self.assertEqual(mrr_at_k([], is_rel, 5), 0.0)
        self.assertEqual(ndcg_at_k([], is_rel, 5), 0.0)

    def test_mean_empty(self):
        self.assertEqual(mean([]), 0.0)

    def test_percentile_edges(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(percentile(vals, 0), 1.0)
        self.assertEqual(percentile(vals, 100), 5.0)
        self.assertAlmostEqual(percentile(vals, 50), 3.0)

    def test_percentile_interpolation(self):
        vals = [10.0, 20.0]
        # halfway between 10 and 20
        self.assertAlmostEqual(percentile(vals, 50), 15.0)

    def test_percentile_empty(self):
        self.assertEqual(percentile([], 50), 0.0)


# ----------------------------------------------------------------------
# Corpus loading
# ----------------------------------------------------------------------

class CorpusLoadTests(unittest.TestCase):

    def test_fixture_corpus_loads(self):
        chunks = load_corpus(FIXTURE_CORPUS)
        self.assertGreater(len(chunks), 0)
        sources = {c.source for c in chunks}
        # Sanity-check expected files are represented (relative paths).
        self.assertTrue(any("atomselect.md" in s for s in sources))
        self.assertTrue(any("render.md" in s for s in sources))
        self.assertTrue(any("mol.md" in s for s in sources))
        self.assertTrue(any("intro.md" in s for s in sources))
        self.assertTrue(any("SKILL.md" in s for s in sources))

    def test_scopes_assigned(self):
        chunks = load_corpus(FIXTURE_CORPUS)
        scopes = {c.scope for c in chunks}
        self.assertIn("vmd_ref", scopes)
        self.assertIn("user_guide", scopes)
        self.assertIn("skills", scopes)

    def test_chunks_have_unique_ids(self):
        chunks = load_corpus(FIXTURE_CORPUS)
        ids = [c.id for c in chunks]
        self.assertEqual(len(set(ids)), len(ids))

    def test_missing_corpus_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_corpus(ROOT / "tests" / "fixtures" / "nope")


# ----------------------------------------------------------------------
# Audit determinism + shape
# ----------------------------------------------------------------------

class AuditTests(unittest.TestCase):

    def test_audit_runs_and_returns_report(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        self.assertEqual(report.k, 5)
        self.assertGreater(report.corpus.chunk_count, 0)
        self.assertGreater(len(report.queries), 0)
        self.assertEqual(len(report.queries), report.golden_summary["total"])

    def test_audit_is_deterministic(self):
        # Two runs of the audit on the same inputs should produce
        # byte-identical per-query results (latency aside, which we
        # strip before comparing).
        r1 = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5).to_dict()
        r2 = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5).to_dict()

        def strip_latency(d):
            d = dict(d)
            d["elapsed_ms"] = 0.0
            d["queries"] = [
                {**q, "latency_ms": 0.0} for q in d["queries"]
            ]
            d["summary"] = {
                **d["summary"],
                "latency_p50_ms": 0.0,
                "latency_p95_ms": 0.0,
            }
            return d

        self.assertEqual(strip_latency(r1), strip_latency(r2))

    def test_identifier_query_hits_top_1(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        q = next(q for q in report.queries if q.qid == "id-atomselect")
        # BM25 should put the exact match at rank 1 for a bare identifier.
        self.assertEqual(q.hit_rank, 1, f"top_hits={q.top_hits}")
        self.assertEqual(q.recall_at_k, 1.0)
        self.assertEqual(q.mrr_at_k, 1.0)

    def test_expected_bm25_failures_have_no_hit(self):
        # Queries tagged 'expected-bm25-fail' demonstrate the vocabulary
        # mismatch problem this whole upgrade exists to solve. They
        # MUST miss the top-k today; if any of them start hitting after
        # a change, that's a signal the golden set needs new failure
        # modes (and the audit is no longer a useful baseline).
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        expected_failures = [
            q for q in report.queries if "expected-bm25-fail" in q.tags
        ]
        self.assertGreater(
            len(expected_failures), 0,
            "Golden set must contain at least one expected-bm25-fail tag.",
        )
        for q in expected_failures:
            self.assertIsNone(
                q.hit_rank,
                msg=(
                    f"Query {q.qid!r} was tagged expected-bm25-fail but "
                    f"BM25 found it at rank {q.hit_rank}. Either remove "
                    f"the tag or the audit baseline is wrong."
                ),
            )

    def test_summary_is_in_zero_one(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        for metric in ("mean_recall_at_k", "mean_mrr_at_k", "mean_ndcg_at_k"):
            v = report.summary[metric]
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_latency_is_nonnegative(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        for q in report.queries:
            self.assertGreaterEqual(q.latency_ms, 0.0)
        self.assertGreaterEqual(report.summary["latency_p50_ms"], 0.0)
        self.assertGreaterEqual(report.summary["latency_p95_ms"], 0.0)

    def test_to_text_does_not_crash(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        text = report.to_text()
        self.assertIn("RAG audit", text)
        self.assertIn("summary", text)

    def test_report_json_round_trip(self):
        report = audit(FIXTURE_CORPUS, GOLDEN_PATH, k=5)
        d = report.to_dict()
        # Must be JSON-serialisable.
        s = json.dumps(d, sort_keys=True)
        round_tripped = json.loads(s)
        self.assertEqual(round_tripped["k"], 5)
        self.assertEqual(round_tripped["corpus"]["chunk_count"],
                         report.corpus.chunk_count)


# ----------------------------------------------------------------------
# CLI smoke
# ----------------------------------------------------------------------

class AuditCLITests(unittest.TestCase):

    def test_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "baseline.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = audit_main([
                    "--corpus", str(FIXTURE_CORPUS),
                    "--golden", str(GOLDEN_PATH),
                    "--out", str(out),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertIn("queries", data)
            self.assertIn("summary", data)

    def test_cli_text_mode(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = audit_main([
                "--corpus", str(FIXTURE_CORPUS),
                "--golden", str(GOLDEN_PATH),
                "--text",
            ])
        self.assertEqual(rc, 0)
        self.assertIn("RAG audit", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
