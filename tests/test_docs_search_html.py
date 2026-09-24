"""
Unit tests for the HTML chunker (chunk_html) and the HTML→ingest pipeline.

The chunker uses stdlib html.parser only — these tests assert the
contract: clean section splits on H1/H2/H3, drop script/style/nav cruft,
preserve <pre> whitespace (commands/code), and recover from malformed
markup without raising.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.docs_search import (  # noqa: E402
    DocsSearch,
    build_index_from_chunks,
    chunk_html,
)
from vmd_ai_runtime.scripts.build_docs_index import cli as indexer_cli  # noqa: E402


FIXTURE_HTML = ROOT / "tests" / "fixtures" / "docs" / "user_guide_html" / "selections.html"


# ----------------------------------------------------------------------
# Direct chunk_html unit tests
# ----------------------------------------------------------------------

class HtmlChunkerTests(unittest.TestCase):

    def test_splits_on_h1_h2_h3_boundaries(self):
        html = (
            "<html><body>"
            "<h1>A</h1><p>body A</p>"
            "<h2>B</h2><p>body B</p>"
            "<h3>C</h3><p>body C</p>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].section, "A")
        self.assertEqual(chunks[1].section, "B")
        self.assertEqual(chunks[2].section, "C")
        self.assertIn("body A", chunks[0].text)
        self.assertIn("body B", chunks[1].text)

    def test_strips_script_and_style_tags(self):
        html = (
            "<html><head>"
            "<script>var leak = 'BAD_SECRET';</script>"
            "<style>.x { color: BAD_CSS; }</style>"
            "</head><body>"
            "<h1>Visible</h1><p>real content</p>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        joined = " ".join(c.text for c in chunks)
        self.assertNotIn("BAD_SECRET", joined)
        self.assertNotIn("BAD_CSS", joined)
        self.assertIn("real content", joined)

    def test_strips_nav_footer_aside(self):
        html = (
            "<html><body>"
            "<nav>nav cruft</nav>"
            "<aside>aside cruft</aside>"
            "<h1>Real</h1><p>good content</p>"
            "<footer>footer cruft</footer>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        joined = " ".join(c.text for c in chunks)
        self.assertNotIn("nav cruft", joined)
        self.assertNotIn("aside cruft", joined)
        self.assertNotIn("footer cruft", joined)
        self.assertIn("good content", joined)

    def test_preserves_pre_whitespace(self):
        """Code blocks in <pre> must keep their newlines so command
        examples don't collapse onto one line."""
        html = (
            "<html><body>"
            "<h1>Examples</h1>"
            "<pre>line1\nline2\nline3</pre>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 1)
        text = chunks[0].text
        self.assertIn("line1", text)
        self.assertIn("line2", text)
        self.assertIn("line3", text)
        # The three lines must remain on separate lines.
        self.assertIn("line1\nline2", text)

    def test_html_entities_decoded(self):
        html = (
            "<html><body>"
            "<h1>Entities</h1>"
            "<p>5 &lt; 10 &amp;&amp; 10 &gt; 5</p>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        text = chunks[0].text
        self.assertIn("5 < 10", text)
        self.assertIn("&&", text)
        self.assertIn("10 > 5", text)

    def test_pre_text_not_recollapsed(self):
        html = (
            "<html><body>"
            "<h1>X</h1>"
            "<pre>  indented\n    deeper</pre>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        # Inside <pre>, two-space indents should survive.
        self.assertIn("  indented", chunks[0].text)
        self.assertIn("    deeper", chunks[0].text)

    def test_inline_tags_text_concatenated(self):
        html = (
            "<html><body>"
            "<h1>X</h1>"
            "<p>Use <code>mol representation</code> to <em>stage</em> a rep.</p>"
            "</body></html>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 1)
        self.assertIn("mol representation", chunks[0].text)
        self.assertIn("stage", chunks[0].text)

    def test_malformed_html_does_not_raise(self):
        """Real HTML in the wild has unclosed tags and orphan markup;
        the chunker should produce *something* without raising."""
        bad = (
            "<html><body>"
            "<h1>Opened never closed"
            "<p>some text"
            "<h2>Next section"
            "<p>more"
            "</body></html>"
        )
        # Must not raise; should still return at least one chunk.
        chunks = chunk_html("/tmp/bad.html", bad, "user_guide")
        self.assertGreaterEqual(len(chunks), 1)

    def test_multiple_h1s_treated_as_separate_sections(self):
        html = (
            "<h1>First</h1><p>a</p>"
            "<h1>Second</h1><p>b</p>"
        )
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].section, "First")
        self.assertEqual(chunks[1].section, "Second")

    def test_section_with_no_body_kept_when_heading_present(self):
        """A heading with no body content still surfaces in the index —
        the heading itself is a useful retrieval anchor."""
        html = "<h1>Empty</h1>"
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section, "Empty")

    def test_no_headings_produces_single_intro_chunk(self):
        """A document with no h1/h2/h3 still has retrievable content;
        the chunker emits one 'intro'-labeled chunk rather than dropping
        the page entirely. Intentional: VMD's per-command HTML pages
        sometimes ship without H1s, and we'd lose them otherwise."""
        html = "<html><body><p>just a paragraph</p></body></html>"
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].section, "intro")
        self.assertIn("just a paragraph", chunks[0].text)

    def test_long_section_splits_into_sub_chunks(self):
        paragraphs = ["x" * 1500 for _ in range(5)]
        body = "".join(f"<p>{p}</p>" for p in paragraphs)
        html = f"<h1>big</h1>{body}"
        chunks = chunk_html("/tmp/x.html", html, "user_guide", max_chars=4000)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertEqual(c.section, "big")

    def test_chunks_carry_scope_and_source(self):
        html = "<h1>One</h1><p>body</p>"
        chunks = chunk_html("/tmp/x.html", html, "user_guide")
        self.assertEqual(chunks[0].scope, "user_guide")
        self.assertEqual(chunks[0].source, "/tmp/x.html")


# ----------------------------------------------------------------------
# End-to-end: indexer ingests HTML + retrieval finds the right chunks
# ----------------------------------------------------------------------

class HtmlIndexerEndToEndTests(unittest.TestCase):

    def test_html_fixture_is_indexed_by_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = indexer_cli([
                "--rebuild",
                "--out", tmp,
                "--user-guide", str(FIXTURE_HTML.parent),
                "--skills", "/dev/null",  # force-empty
            ])
            self.assertEqual(rc, 0)
            ds = DocsSearch(index_dir=tmp)
            self.assertTrue(ds.is_available)

    def test_within_query_finds_distance_section(self):
        """The fixture has a 'Distance selectors' section. A user query
        about 'within' or proximity should bring it back in top-3."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer_cli([
                "--rebuild",
                "--out", tmp,
                "--user-guide", str(FIXTURE_HTML.parent),
                "--skills", "/dev/null",
            ])
            ds = DocsSearch(index_dir=tmp)
            res = ds.search(
                "How do I select atoms within 5 angstrom of a ligand?", k=3
            )
            self.assertTrue(res["ok"])
            joined = " ".join(r["text"] for r in res["results"])
            self.assertIn("within", joined.lower())
            # The cross-molecule warning is in this section — it's
            # exactly the kind of nuance the agent benefits from.
            self.assertIn("measure contacts", joined)

    def test_pre_blocks_survive_round_trip(self):
        """Command examples from <pre> blocks should be retrievable
        verbatim — that's the whole point of preserving whitespace."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer_cli([
                "--rebuild",
                "--out", tmp,
                "--user-guide", str(FIXTURE_HTML.parent),
                "--skills", "/dev/null",
            ])
            ds = DocsSearch(index_dir=tmp)
            res = ds.search("mol selection chain A", k=5)
            self.assertTrue(res["ok"])
            joined = " ".join(r["text"] for r in res["results"])
            self.assertIn("protein and chain A", joined)

    def test_script_content_does_not_leak(self):
        """Confirms end-to-end: the BM25 index never sees content from
        <script>/<style>/<nav>/<footer>, so a user query for the cruft
        words returns zero results (or very low scores)."""
        with tempfile.TemporaryDirectory() as tmp:
            indexer_cli([
                "--rebuild",
                "--out", tmp,
                "--user-guide", str(FIXTURE_HTML.parent),
                "--skills", "/dev/null",
            ])
            ds = DocsSearch(index_dir=tmp)
            res = ds.search("noisy nav cruft", k=5)
            joined = " ".join(r["text"] for r in res["results"])
            self.assertNotIn("noisy", joined)
            self.assertNotIn("nav cruft", joined)


if __name__ == "__main__":
    unittest.main()
