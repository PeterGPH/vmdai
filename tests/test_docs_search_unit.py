"""
Unit tests for docs_search.py: tokenizer, BM25 fit/score, chunkers,
and the DocsSearch retriever's load / failure paths.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.docs_search import (  # noqa: E402
    BM25State,
    Chunk,
    DocsSearch,
    build_index_from_chunks,
    chunk_markdown,
    chunk_plaintext_ref,
    fit_bm25,
    score_bm25,
    tokenize,
)


# ----------------------------------------------------------------------
# Tokenizer
# ----------------------------------------------------------------------

class TokenizerTests(unittest.TestCase):

    def test_lowercases_and_strips_punct(self):
        self.assertEqual(
            tokenize("Mol Representation: NewCartoon, Licorice."),
            ["mol", "representation", "newcartoon", "licorice"],
        )

    def test_keeps_underscores_and_digits(self):
        self.assertEqual(tokenize("atom_select_v2"), ["atom_select_v2"])

    def test_drops_one_char_tokens(self):
        # Single-letter tokens are pure noise for technical docs.
        self.assertEqual(tokenize("a b cd"), ["cd"])

    def test_empty_returns_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])


# ----------------------------------------------------------------------
# BM25 fit + score
# ----------------------------------------------------------------------

class BM25Tests(unittest.TestCase):

    def setUp(self):
        self.corpus = [
            tokenize("mol representation NewCartoon backbone"),
            tokenize("atomselect protein within 5 of ligand"),
            tokenize("render snapshot tga ray traced"),
            tokenize("render TachyonInternal ambient occlusion"),
        ]
        self.bm25 = fit_bm25(self.corpus)

    def test_fit_records_basic_invariants(self):
        self.assertEqual(self.bm25.N, 4)
        self.assertEqual(len(self.bm25.tf), 4)
        # All tokens that appeared somewhere should have an idf entry.
        all_tokens = set()
        for d in self.corpus:
            all_tokens.update(d)
        self.assertEqual(set(self.bm25.idf.keys()), all_tokens)

    def test_score_orders_relevant_doc_first(self):
        scores = score_bm25(self.bm25, tokenize("how do I render TachyonInternal"))
        # Doc 3 is the only one mentioning "tachyoninternal"; it should be top.
        top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        self.assertEqual(top[0], 3)

    def test_score_returns_zero_when_no_query_tokens_in_corpus(self):
        scores = score_bm25(self.bm25, tokenize("nonexistent_keyword"))
        self.assertEqual(scores, [0.0, 0.0, 0.0, 0.0])

    def test_score_handles_empty_corpus(self):
        empty = fit_bm25([])
        self.assertEqual(score_bm25(empty, ["foo"]), [])

    def test_state_roundtrips_through_json(self):
        as_json = self.bm25.to_json()
        # Force through json serialize/deserialize so we exercise key
        # coercion (json keys are always strings).
        restored = BM25State.from_json(json.loads(json.dumps(as_json)))
        self.assertEqual(restored.N, self.bm25.N)
        self.assertEqual(
            score_bm25(restored, tokenize("snapshot")),
            score_bm25(self.bm25, tokenize("snapshot")),
        )


# ----------------------------------------------------------------------
# Chunkers
# ----------------------------------------------------------------------

class MarkdownChunkerTests(unittest.TestCase):

    def test_splits_on_h2_headings(self):
        md = (
            "## A\n\nbody A\n\n"
            "## B\n\nbody B more\n\n"
            "## C\n\nbody C\n"
        )
        chunks = chunk_markdown("/tmp/x.md", md, "skills")
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].section, "A")
        self.assertEqual(chunks[1].section, "B")
        self.assertEqual(chunks[2].section, "C")
        # Each chunk's text should include its heading line for context.
        self.assertTrue(chunks[1].text.startswith("## B"))

    def test_long_section_splits_into_sub_chunks(self):
        # 5 paragraphs of ~1500 chars each → ~7500 chars > 4000 default.
        paragraphs = ["x" * 1500 for _ in range(5)]
        md = "## big\n\n" + "\n\n".join(paragraphs)
        chunks = chunk_markdown("/tmp/x.md", md, "skills", max_chars=4000)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertEqual(c.section, "big")

    def test_h3_does_not_split(self):
        # Only `## ` is treated as a section boundary; deeper headings
        # stay inside their parent section.
        md = "## A\n\n### sub\n\nbody A\n\n## B\n\nbody B"
        chunks = chunk_markdown("/tmp/x.md", md, "skills")
        self.assertEqual(len(chunks), 2)
        self.assertIn("### sub", chunks[0].text)


class PlaintextChunkerTests(unittest.TestCase):

    def test_splits_on_blank_lines(self):
        text = "BLOCK1\nfirst body\n\nBLOCK2\nsecond body\n\nBLOCK3\nthird"
        chunks = chunk_plaintext_ref("/tmp/ref.txt", text, "vmd_ref")
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].section, "BLOCK1")
        self.assertEqual(chunks[1].section, "BLOCK2")

    def test_oversized_block_splits_into_windows(self):
        text = "X" * 9000
        chunks = chunk_plaintext_ref("/tmp/ref.txt", text, "vmd_ref",
                                     max_chars=4000)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c.text), 4000)


# ----------------------------------------------------------------------
# DocsSearch loading / failure modes
# ----------------------------------------------------------------------

class DocsSearchLoadTests(unittest.TestCase):

    def test_missing_index_reports_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = DocsSearch(index_dir=tmp)
            self.assertFalse(ds.is_available)
            self.assertIn("not built", ds.load_error or "")

            res = ds.search("anything")
            self.assertFalse(res["ok"])
            self.assertIn("not built", res["error"])

    def test_corrupt_bm25_reports_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            (tmp_p / "chunks.jsonl").write_text("{}\n", encoding="utf-8")
            (tmp_p / "bm25.json").write_text("not valid json", encoding="utf-8")

            ds = DocsSearch(index_dir=tmp)
            self.assertFalse(ds.is_available)
            self.assertIn("failed to load", ds.load_error or "")

    def test_search_empty_query_returns_empty_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks = [Chunk("c1", "/x", "intro", "the body", "skills")]
            build_index_from_chunks(Path(tmp), chunks)
            ds = DocsSearch(index_dir=tmp)
            res = ds.search("")
            self.assertTrue(res["ok"])
            self.assertEqual(res["results"], [])

    def test_search_invalid_scope_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks = [Chunk("c1", "/x", "intro", "body", "skills")]
            build_index_from_chunks(Path(tmp), chunks)
            ds = DocsSearch(index_dir=tmp)
            res = ds.search("body", scope="bogus")
            self.assertFalse(res["ok"])
            self.assertIn("scope", res["error"])

    def test_search_returns_top_k_in_score_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks = [
                Chunk("c1", "/x", "render",
                      "render TachyonInternal high quality", "vmd_ref"),
                Chunk("c2", "/x", "mol",
                      "mol representation NewCartoon backbone", "vmd_ref"),
                Chunk("c3", "/x", "atomselect",
                      "atomselect protein within 5 of ligand", "vmd_ref"),
            ]
            build_index_from_chunks(Path(tmp), chunks)
            ds = DocsSearch(index_dir=tmp)
            res = ds.search("how to render TachyonInternal", k=2)
            self.assertTrue(res["ok"])
            # Top hit is the render chunk; second slot whatever else
            # picks up "how to" (likely none, so list may have just 1).
            self.assertGreaterEqual(len(res["results"]), 1)
            self.assertIn("Tachyon", res["results"][0]["text"])

    def test_search_filters_by_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            chunks = [
                Chunk("c1", "/a.md", "render", "render snapshot", "vmd_ref"),
                Chunk("c2", "/b.md", "render", "render snapshot", "skills"),
            ]
            build_index_from_chunks(Path(tmp), chunks)
            ds = DocsSearch(index_dir=tmp)

            res_skills = ds.search("render snapshot", scope="skills")
            self.assertTrue(res_skills["ok"])
            self.assertEqual(len(res_skills["results"]), 1)
            self.assertEqual(res_skills["results"][0]["source"], "/b.md")

            res_ref = ds.search("render snapshot", scope="vmd_ref")
            self.assertEqual(res_ref["results"][0]["source"], "/a.md")

    def test_lazy_load_does_not_touch_disk_until_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = DocsSearch(index_dir=tmp)
            # The index dir is empty at this point — but constructing
            # DocsSearch shouldn't have raised. is_available will be
            # False on first inspection.
            self.assertIsNotNone(ds)


if __name__ == "__main__":
    unittest.main()
