"""
test_wiki_tools_integration.py — exercises the wiki tools through the
ClaudeToolLoop dispatch surface.

These tests don't hit any LLM provider — they instantiate a
ClaudeToolLoop with stub provider/api_key/model values and call the
``_dispatch_wiki_*`` methods directly. That's enough to verify:

  * Tool list correctly advertises wiki tools when wiki_store is wired.
  * Tool list omits them when wiki_store is None.
  * Each dispatcher returns the {ok, output, error} shape the tool
    result builder expects.
  * End-to-end: agent calls wiki_update → wiki_list shows the new page
    → wiki_read returns it with pins → wiki_verify_pins is fresh →
    upstream change → wiki_verify_pins reports drift.
  * Source pinning hashes match what's on disk.
  * Errors (bad slug, missing page, missing source) surface as
    structured errors, not exceptions.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeToolLoop,
    WIKI_LIST_TOOL,
    WIKI_READ_TOOL,
    WIKI_UPDATE_TOOL,
    WIKI_VERIFY_TOOL,
    _vmd_tools,
)
from vmd_ai_runtime.wiki_store import WikiStore  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.wiki_root = base / "wiki"
        self.raw_root = base / "raw"
        self.raw_root.mkdir()
        # Two upstream sources the agent can pin to.
        (self.raw_root / "atomselect.html").write_text(
            "<h1>atomselect command</h1>\n<p>Selection language.</p>\n",
            encoding="utf-8",
        )
        (self.raw_root / "representations.html").write_text(
            "<h1>Representations</h1>\n<p>NewCartoon, Licorice, VDW...</p>\n",
            encoding="utf-8",
        )
        self.wiki = WikiStore(self.wiki_root, raw_root=self.raw_root)
        self.wiki.bootstrap()
        # ``provider_name="mock"`` keeps build_claude_loop logic out
        # of the way — we never call .run(), only the dispatch methods.
        self.loop = ClaudeToolLoop(
            provider_name="openrouter",
            api_key="stub",
            model="stub-model",
            wiki_store=self.wiki,
        )


# ---------------------------------------------------------------------------
# Tool list advertisement
# ---------------------------------------------------------------------------

class ToolListTests(_Base):
    def test_wiki_tools_advertised_when_store_present(self):
        tools = self.loop._tools_for_turn()
        names = {t["name"] for t in tools}
        self.assertIn("wiki_list", names)
        self.assertIn("wiki_read", names)
        self.assertIn("wiki_update", names)
        self.assertIn("wiki_verify_pins", names)

    def test_wiki_tools_omitted_when_store_missing(self):
        bare_loop = ClaudeToolLoop(
            provider_name="openrouter",
            api_key="stub",
            model="stub-model",
        )
        tools = bare_loop._tools_for_turn()
        names = {t["name"] for t in tools}
        self.assertNotIn("wiki_list", names)
        self.assertNotIn("wiki_read", names)

    def test_each_wiki_tool_has_anthropic_compatible_schema(self):
        for tool in (WIKI_LIST_TOOL, WIKI_READ_TOOL, WIKI_UPDATE_TOOL, WIKI_VERIFY_TOOL):
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("input_schema", tool)
            self.assertEqual(tool["input_schema"]["type"], "object")
            self.assertIn("properties", tool["input_schema"])


# ---------------------------------------------------------------------------
# wiki_list
# ---------------------------------------------------------------------------

class WikiListTests(_Base):
    def test_empty_wiki_returns_default_index(self):
        result = self.loop._dispatch_wiki_list({})
        self.assertTrue(result["ok"])
        self.assertIn("Wiki Index", result["output"])
        # No pages discovered yet (only the special files).
        self.assertEqual(result["pages"], [])

    def test_list_reflects_newly_added_pages(self):
        self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "# atomselect\nBody.\n",
            "reason": "seed",
            "sources": ["raw/atomselect.html"],
        })
        result = self.loop._dispatch_wiki_list({})
        slugs = [p["page"] for p in result["pages"]]
        self.assertIn("concepts/atomselect.md", slugs)
        self.assertIn("concepts/atomselect.md (pins=1; sources=1)", result["output"])

    def test_missing_store_returns_structured_error(self):
        bare_loop = ClaudeToolLoop(
            provider_name="openrouter", api_key="stub", model="stub-model",
        )
        result = bare_loop._dispatch_wiki_list({})
        self.assertFalse(result["ok"])
        self.assertIn("not configured", result["error"])


# ---------------------------------------------------------------------------
# wiki_read
# ---------------------------------------------------------------------------

class WikiReadTests(_Base):
    def test_read_existing_page_surfaces_pins(self):
        self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "# atomselect\nThe selection language.\n",
            "reason": "seed",
            "sources": ["raw/atomselect.html"],
        })
        result = self.loop._dispatch_wiki_read({"page": "concepts/atomselect.md"})
        self.assertTrue(result["ok"])
        self.assertIn("selection language", result["output"])
        self.assertIn("Pinned sources", result["output"])
        self.assertIn("raw/atomselect.html", result["output"])
        # Hash must match what's on disk so a downstream verify will
        # report fresh.
        expected = hashlib.sha256(
            (self.raw_root / "atomselect.html").read_bytes()
        ).hexdigest()
        self.assertEqual(result["pins"][0]["sha256"], expected)

    def test_read_missing_page_returns_structured_error(self):
        result = self.loop._dispatch_wiki_read({"page": "concepts/missing.md"})
        self.assertFalse(result["ok"])
        self.assertIn("does not exist", result["error"])

    def test_read_empty_page_arg(self):
        result = self.loop._dispatch_wiki_read({"page": ""})
        self.assertFalse(result["ok"])
        self.assertIn("non-empty", result["error"])

    def test_read_page_without_pins_shows_no_citation_marker(self):
        self.loop._dispatch_wiki_update({
            "page": "concepts/orphan.md",
            "content": "Body.\n",
            "reason": "seed without sources",
        })
        result = self.loop._dispatch_wiki_read({"page": "concepts/orphan.md"})
        self.assertTrue(result["ok"])
        self.assertIn("no citations", result["output"])


# ---------------------------------------------------------------------------
# wiki_update
# ---------------------------------------------------------------------------

class WikiUpdateTests(_Base):
    def test_update_creates_page_and_pins_sources(self):
        result = self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "# atomselect\nBody.\n",
            "reason": "initial draft",
            "sources": ["raw/atomselect.html", "raw/representations.html"],
        })
        self.assertTrue(result["ok"], result)
        # The on-disk file exists, the pin sidecar exists.
        self.assertTrue((self.wiki_root / "concepts" / "atomselect.md").exists())
        self.assertTrue(
            (self.wiki_root / ".pins" / "concepts" / "atomselect.md.pins.json").exists()
        )
        # Two pins recorded.
        self.assertEqual(len(result["pins"]), 2)

    def test_update_with_missing_source_returns_structured_error(self):
        result = self.loop._dispatch_wiki_update({
            "page": "concepts/x.md",
            "content": "Body\n",
            "reason": "bad pin",
            "sources": ["raw/does-not-exist.html"],
        })
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["error"])
        # Critically: the page must NOT have been written, because the
        # store rejected the update before reaching the write step.
        self.assertFalse((self.wiki_root / "concepts" / "x.md").exists())

    def test_update_rejects_path_traversal(self):
        # Try several path-traversal shapes. Each must be rejected with
        # a structured error rather than crashing the loop. We don't
        # pin the wording — the store may reject at any of several
        # checkpoints (dot-segment guard, resolve-under-root, etc.).
        for evil in ("../escape.md", "/etc/passwd", "concepts/../../escape.md"):
            with self.subTest(page=evil):
                result = self.loop._dispatch_wiki_update({
                    "page": evil,
                    "content": "Body\n",
                    "reason": "evil",
                })
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"].strip())
                # File must NOT have been written.
                self.assertFalse(
                    (self.wiki_root / "escape.md").exists(),
                    f"page was created for traversal slug {evil!r}",
                )

    def test_update_requires_reason(self):
        result = self.loop._dispatch_wiki_update({
            "page": "x.md",
            "content": "Body\n",
            "reason": "",
        })
        self.assertFalse(result["ok"])
        self.assertIn("reason", result["error"])

    def test_update_sources_must_be_list(self):
        result = self.loop._dispatch_wiki_update({
            "page": "x.md",
            "content": "Body\n",
            "reason": "r",
            "sources": "raw/atomselect.html",   # string, not list
        })
        self.assertFalse(result["ok"])
        self.assertIn("array", result["error"])


# ---------------------------------------------------------------------------
# wiki_verify_pins
# ---------------------------------------------------------------------------

class WikiVerifyPinsTests(_Base):
    def test_fresh_initially(self):
        self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "Body\n",
            "reason": "seed",
            "sources": ["raw/atomselect.html"],
        })
        result = self.loop._dispatch_wiki_verify_pins({})
        self.assertTrue(result["ok"])
        self.assertEqual(result["report"]["summary"]["fresh"], 1)
        self.assertEqual(result["report"]["summary"].get("drift", 0), 0)
        self.assertIn("fresh=1", result["output"])

    def test_drift_after_source_change(self):
        self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "Body\n",
            "reason": "seed",
            "sources": ["raw/atomselect.html"],
        })
        # Simulate the user updating the raw doc upstream.
        (self.raw_root / "atomselect.html").write_text(
            "<h1>atomselect v2</h1>\n", encoding="utf-8"
        )
        result = self.loop._dispatch_wiki_verify_pins({})
        self.assertEqual(result["report"]["summary"]["drift"], 1)
        # Output should call out the drifted page by slug so the agent
        # can decide to revise it.
        self.assertIn("concepts/atomselect.md: drift", result["output"])

    def test_single_page_verify(self):
        self.loop._dispatch_wiki_update({
            "page": "a.md",
            "content": "Body\n",
            "reason": "seed",
            "sources": ["raw/atomselect.html"],
        })
        self.loop._dispatch_wiki_update({
            "page": "b.md",
            "content": "Body\n",
            "reason": "seed",
            "sources": ["raw/representations.html"],
        })
        result = self.loop._dispatch_wiki_verify_pins({"page": "a.md"})
        self.assertEqual(len(result["report"]["checked"]), 1)
        self.assertEqual(result["report"]["checked"][0]["page"], "a.md")


# ---------------------------------------------------------------------------
# End-to-end workflow (what a real agent turn looks like)
# ---------------------------------------------------------------------------

class WorkflowTests(_Base):
    def test_full_agent_turn(self):
        """Simulate the canonical wiki-driven agent turn:

        1. list — empty wiki, only the bootstrap index
        2. update — file a new concept page citing two raw sources
        3. list — now shows the new page
        4. read — fetches it back, pins surface in output
        5. verify — fresh
        6. simulate upstream change — verify now reports drift
        """
        # 1
        r1 = self.loop._dispatch_wiki_list({})
        self.assertEqual(r1["pages"], [])

        # 2
        r2 = self.loop._dispatch_wiki_update({
            "page": "concepts/atomselect.md",
            "content": "# atomselect\nThe selection language.\n",
            "reason": "first ingest from manual + representations",
            "sources": ["raw/atomselect.html", "raw/representations.html"],
        })
        self.assertTrue(r2["ok"])

        # 3
        r3 = self.loop._dispatch_wiki_list({})
        slugs = [p["page"] for p in r3["pages"]]
        self.assertIn("concepts/atomselect.md", slugs)

        # 4
        r4 = self.loop._dispatch_wiki_read({"page": "concepts/atomselect.md"})
        self.assertTrue(r4["ok"])
        self.assertIn("Pinned sources", r4["output"])
        self.assertEqual(len(r4["pins"]), 2)

        # 5
        r5 = self.loop._dispatch_wiki_verify_pins({})
        self.assertEqual(r5["report"]["summary"]["fresh"], 1)

        # 6
        (self.raw_root / "atomselect.html").write_text(
            "<h1>v2</h1>", encoding="utf-8"
        )
        r6 = self.loop._dispatch_wiki_verify_pins({"page": "concepts/atomselect.md"})
        self.assertEqual(r6["report"]["summary"]["drift"], 1)


if __name__ == "__main__":
    unittest.main()
