"""
Roundtrip tests for the indexer CLI: build → load → search produces
the answers we'd expect on the fixture corpus.
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

from vmd_ai_runtime.docs_search import DocsSearch  # noqa: E402
from vmd_ai_runtime.scripts.build_docs_index import cli as indexer_cli  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "docs"


class IndexerCliRoundtripTests(unittest.TestCase):

    def _build(self, out_dir: Path) -> int:
        return indexer_cli([
            "--rebuild",
            "--out", str(out_dir),
            "--vmd-ref", str(FIXTURES / "vmd_ref"),
            "--user-guide", str(FIXTURES / "user_guide"),
            "--skills", str(FIXTURES / "skills"),
        ])

    def test_build_writes_manifest_chunks_and_bm25(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rc = self._build(out)
            self.assertEqual(rc, 0)
            self.assertTrue((out / "manifest.json").exists())
            self.assertTrue((out / "chunks.jsonl").exists())
            self.assertTrue((out / "bm25.json").exists())

            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["version"], 1)
            # Fixture has 3 vmd_ref files, 1 user_guide, 1 skill.
            self.assertGreater(manifest["chunk_count"], 5)
            scopes = manifest["scope_counts"]
            self.assertIn("vmd_ref", scopes)
            self.assertIn("user_guide", scopes)
            self.assertIn("skills", scopes)

    def test_built_index_is_searchable_via_docssearch(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(self._build(out), 0)

            ds = DocsSearch(index_dir=str(out))
            self.assertTrue(ds.is_available)

            # Sanity check — known content from the fixture corpus.
            res = ds.search("how do I render TachyonInternal")
            self.assertTrue(res["ok"])
            self.assertGreaterEqual(len(res["results"]), 1)
            top = res["results"][0]
            self.assertIn("Tachyon", top["text"])
            self.assertIn("render", top["source"])

    def test_where_subcommand_prints_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(self._build(out), 0)
            # --where should succeed (rc=0) when an index exists.
            self.assertEqual(indexer_cli(["--where", "--out", str(out)]), 0)

    def test_no_sources_returns_error(self):
        # Run with explicit empty paths — no sources, no chunks.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            empty_skills = Path(tmp) / "no_such_skills"
            rc = indexer_cli([
                "--rebuild",
                "--out", str(out),
                "--skills", str(empty_skills),
            ])
            self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
