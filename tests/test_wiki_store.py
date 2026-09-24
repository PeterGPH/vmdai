"""
test_wiki_store.py — comprehensive tests for the LLM Wiki module.

Covers, in roughly this order:
  - Frontmatter parser (round-trip, edge cases)
  - Bootstrap (creates schema/index/log on demand, force=False is idempotent)
  - Page paths: safety against traversal, absolute paths, dotfile dirs
  - Page CRUD: create, read, overwrite, list
  - Source pinning: sha256 + size recorded, "raw/" prefix stripped,
    missing sources rejected, paths outside raw_root rejected
  - Pin drift: detected via sha mismatch, surfaced via verify_pins()
  - Pin removal: clearing sources deletes the sidecar
  - Log format: greppable timestamp prefix, append-only
  - Atomicity: no half-written page survives an interrupted write
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make ``vmd_ai_runtime`` importable when this test is run directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from vmd_ai_runtime.wiki_store import (  # noqa: E402
    DEFAULT_INDEX_BODY,
    DEFAULT_LOG_BODY,
    DEFAULT_SCHEMA_BODY,
    PageRecord,
    SourcePin,
    WikiError,
    WikiNotFound,
    WikiPathError,
    WikiSourceMissing,
    WikiStore,
    parse_frontmatter,
    render_frontmatter,
)


# ---------------------------------------------------------------------------
# Frontmatter parser
# ---------------------------------------------------------------------------

class FrontmatterTests(unittest.TestCase):
    def test_no_frontmatter_returns_empty_dict_and_full_content(self):
        text = "# A page with no frontmatter\n\nBody."
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {})
        self.assertEqual(body, text)

    def test_simple_key_value(self):
        text = "---\nlast_updated: 2026-05-19\n---\nBody.\n"
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {"last_updated": "2026-05-19"})
        self.assertEqual(body, "Body.\n")

    def test_block_list(self):
        text = (
            "---\n"
            "sources:\n"
            "  - raw/a.html\n"
            "  - raw/b.html\n"
            "---\n"
            "Body.\n"
        )
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {"sources": ["raw/a.html", "raw/b.html"]})
        self.assertEqual(body, "Body.\n")

    def test_inline_list(self):
        text = '---\nrelated: [foo.md, "bar.md"]\n---\nBody.\n'
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {"related": ["foo.md", "bar.md"]})

    def test_quoted_value_unquoted(self):
        text = '---\ntitle: "hello: world"\n---\n\nBody.\n'
        fm, body = parse_frontmatter(text)
        self.assertEqual(fm, {"title": "hello: world"})

    def test_unclosed_frontmatter_treats_as_body(self):
        text = "---\nsources:\n  - raw/a.html\n# never closes\nBody.\n"
        fm, body = parse_frontmatter(text)
        # No closing fence → parser returns the whole thing as body.
        self.assertEqual(fm, {})
        self.assertEqual(body, text)

    def test_render_round_trip(self):
        fm_in = {
            "sources": ["raw/a.html", "raw/b.html"],
            "related": ["other.md"],
            "last_updated": "2026-05-19",
        }
        rendered = render_frontmatter(fm_in)
        fm_out, body = parse_frontmatter(rendered + "Body\n")
        self.assertEqual(fm_out, fm_in)
        self.assertEqual(body, "Body\n")

    def test_render_empty_returns_empty_string(self):
        self.assertEqual(render_frontmatter({}), "")

    def test_render_empty_list(self):
        rendered = render_frontmatter({"sources": []})
        fm, _ = parse_frontmatter(rendered + "x\n")
        self.assertEqual(fm, {"sources": []})


# ---------------------------------------------------------------------------
# Test base — gives each test a tmp wiki + raw root and a couple of fake
# source files to pin.
# ---------------------------------------------------------------------------

class _WikiTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.wiki_root = base / "wiki"
        self.raw_root = base / "raw"
        self.raw_root.mkdir()
        # Seed two raw "sources" with known content so we can later
        # mutate one and detect drift.
        (self.raw_root / "manual.html").write_text(
            "<h1>VMD Manual</h1>\n<p>atomselect docs</p>\n",
            encoding="utf-8",
        )
        (self.raw_root / "ref").mkdir()
        (self.raw_root / "ref" / "tcl.html").write_text(
            "<h1>Tcl Reference</h1>\n",
            encoding="utf-8",
        )
        self.store = WikiStore(self.wiki_root, raw_root=self.raw_root)
        self.store.bootstrap()


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

class BootstrapTests(_WikiTestBase):
    def test_bootstrap_creates_special_files(self):
        self.assertTrue((self.wiki_root / "CLAUDE.md").exists())
        self.assertTrue((self.wiki_root / "index.md").exists())
        self.assertTrue((self.wiki_root / "log.md").exists())
        self.assertTrue((self.wiki_root / ".pins").is_dir())

    def test_bootstrap_idempotent_by_default(self):
        # Write a marker into index.md, then bootstrap again. The marker
        # must survive — bootstrap is non-destructive without force.
        (self.wiki_root / "index.md").write_text("MY EDITS\n", encoding="utf-8")
        created = self.store.bootstrap()
        self.assertFalse(created["index.md"])
        self.assertEqual(
            (self.wiki_root / "index.md").read_text(encoding="utf-8"),
            "MY EDITS\n",
        )

    def test_bootstrap_force_overwrites(self):
        (self.wiki_root / "index.md").write_text("MY EDITS\n", encoding="utf-8")
        created = self.store.bootstrap(force=True)
        self.assertTrue(created["index.md"])
        self.assertIn("Wiki Index", (self.wiki_root / "index.md").read_text())


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

class PathSafetyTests(_WikiTestBase):
    def test_absolute_path_rejected(self):
        with self.assertRaises(WikiPathError):
            self.store.update_page("/etc/passwd", "x", reason="evil")

    def test_dotdot_traversal_rejected(self):
        with self.assertRaises(WikiPathError):
            self.store.update_page("../escape.md", "x", reason="evil")

    def test_dotfile_dir_rejected(self):
        # ``.pins`` is reserved for sidecars; the agent shouldn't be
        # able to write a page there.
        with self.assertRaises(WikiPathError):
            self.store.update_page(".pins/sneaky.md", "x", reason="evil")

    def test_empty_slug_rejected(self):
        with self.assertRaises(WikiPathError):
            self.store.update_page("", "x", reason="evil")

    def test_md_extension_added_if_missing(self):
        rec = self.store.update_page("concepts/foo", "Body\n", reason="seed")
        self.assertEqual(rec.page, "concepts/foo.md")
        self.assertTrue((self.wiki_root / "concepts" / "foo.md").exists())

    def test_source_path_outside_raw_rejected(self):
        # An absolute path or a path with ``..`` to the parent must fail.
        with self.assertRaises(WikiPathError):
            self.store.update_page(
                "concepts/x.md", "Body\n",
                reason="bad", sources=["../etc/passwd"],
            )

    def test_source_missing_file_rejected(self):
        with self.assertRaises(WikiSourceMissing):
            self.store.update_page(
                "concepts/x.md", "Body\n",
                reason="bad", sources=["raw/does-not-exist.html"],
            )

    def test_source_must_be_regular_file(self):
        # Pointing the agent at a directory should be rejected.
        with self.assertRaises(WikiSourceMissing):
            self.store.update_page(
                "concepts/x.md", "Body\n",
                reason="bad", sources=["raw/ref"],
            )

    def test_source_pinning_requires_raw_root(self):
        store_no_raw = WikiStore(self.wiki_root)
        with self.assertRaises(WikiPathError):
            store_no_raw.update_page(
                "x.md", "body", reason="r", sources=["raw/manual.html"]
            )


# ---------------------------------------------------------------------------
# Read / list
# ---------------------------------------------------------------------------

class ReadListTests(_WikiTestBase):
    def test_read_missing_page_raises(self):
        with self.assertRaises(WikiNotFound):
            self.store.read_page("nope.md")

    def test_read_index_returns_default(self):
        text = self.store.read_index()
        self.assertEqual(text, DEFAULT_INDEX_BODY)

    def test_read_index_missing_raises(self):
        (self.wiki_root / "index.md").unlink()
        with self.assertRaises(WikiNotFound):
            self.store.read_index()

    def test_list_pages_skips_special_files(self):
        self.store.update_page("concepts/atomselect.md", "Body\n", reason="seed")
        entries = self.store.list_pages()
        slugs = [e["page"] for e in entries]
        self.assertIn("concepts/atomselect.md", slugs)
        for special in ("index.md", "log.md", "CLAUDE.md"):
            self.assertNotIn(special, slugs)

    def test_list_pages_returns_frontmatter(self):
        self.store.update_page(
            "concepts/atomselect.md",
            "Body about atomselect.\n",
            reason="seed",
            sources=["raw/manual.html"],
        )
        entries = self.store.list_pages()
        atom_entry = next(e for e in entries if e["page"] == "concepts/atomselect.md")
        self.assertIn("sources", atom_entry["frontmatter"])
        self.assertEqual(atom_entry["pin_count"], 1)


# ---------------------------------------------------------------------------
# Update / source pinning
# ---------------------------------------------------------------------------

class SourcePinningTests(_WikiTestBase):
    def test_pin_records_hash_and_size(self):
        rec = self.store.update_page(
            "concepts/atomselect.md",
            "# atomselect\nBody.\n",
            reason="seed",
            sources=["raw/manual.html"],
        )
        self.assertEqual(len(rec.pins), 1)
        pin = rec.pins[0]
        expected_hash = hashlib.sha256(
            (self.raw_root / "manual.html").read_bytes()
        ).hexdigest()
        self.assertEqual(pin.sha256, expected_hash)
        self.assertEqual(pin.size, (self.raw_root / "manual.html").stat().st_size)
        # Canonical path uses raw_root's basename so the wiki is portable.
        self.assertEqual(pin.path, "raw/manual.html")

    def test_pin_sidecar_written(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        sidecar = self.wiki_root / ".pins" / "concepts" / "atomselect.md.pins.json"
        self.assertTrue(sidecar.exists())
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["page"], "concepts/atomselect.md")
        self.assertEqual(len(payload["pins"]), 1)
        self.assertEqual(payload["pins"][0]["path"], "raw/manual.html")

    def test_sources_written_into_frontmatter(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed",
            sources=["raw/manual.html", "raw/ref/tcl.html"],
        )
        page_text = (self.wiki_root / "concepts" / "atomselect.md").read_text()
        self.assertIn("sources:", page_text)
        self.assertIn("raw/manual.html", page_text)
        self.assertIn("raw/ref/tcl.html", page_text)
        self.assertIn("last_updated:", page_text)

    def test_update_with_no_sources_removes_pin_sidecar(self):
        self.store.update_page(
            "x.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        sidecar = self.wiki_root / ".pins" / "x.md.pins.json"
        self.assertTrue(sidecar.exists())
        # Re-update without sources.
        self.store.update_page("x.md", "Body 2\n", reason="rewrite", sources=[])
        self.assertFalse(sidecar.exists())

    def test_raw_prefix_optional(self):
        # The agent can pass either "raw/manual.html" or "manual.html" —
        # the result should be identical.
        rec_a = self.store.update_page(
            "a.md", "Body\n", reason="seed",
            sources=["manual.html"],
        )
        rec_b = self.store.update_page(
            "b.md", "Body\n", reason="seed",
            sources=["raw/manual.html"],
        )
        self.assertEqual(rec_a.pins[0].sha256, rec_b.pins[0].sha256)
        self.assertEqual(rec_a.pins[0].path, rec_b.pins[0].path)

    def test_read_back_returns_pins(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        rec = self.store.read_page("concepts/atomselect.md")
        self.assertEqual(len(rec.pins), 1)
        self.assertEqual(rec.pins[0].path, "raw/manual.html")
        self.assertIn("sources", rec.frontmatter)


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------

class DriftDetectionTests(_WikiTestBase):
    def test_fresh_when_no_changes(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        report = self.store.verify_pins()
        statuses = {r["page"]: r["status"] for r in report["checked"]}
        self.assertEqual(statuses["concepts/atomselect.md"], "fresh")
        self.assertEqual(report["summary"]["fresh"], 1)
        self.assertEqual(report["summary"].get("drift", 0), 0)

    def test_drift_detected_when_source_content_changes(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        # Mutate the upstream source.
        (self.raw_root / "manual.html").write_text(
            "<h1>VMD Manual v2</h1>\n", encoding="utf-8"
        )
        report = self.store.verify_pins("concepts/atomselect.md")
        entry = report["checked"][0]
        self.assertEqual(entry["status"], "drift")
        self.assertEqual(len(entry["drift"]), 1)
        self.assertNotEqual(
            entry["drift"][0]["expected"],
            entry["drift"][0]["actual"],
        )

    def test_missing_source_reported(self):
        self.store.update_page(
            "concepts/atomselect.md", "Body\n",
            reason="seed", sources=["raw/manual.html"],
        )
        (self.raw_root / "manual.html").unlink()
        report = self.store.verify_pins("concepts/atomselect.md")
        entry = report["checked"][0]
        self.assertEqual(entry["status"], "missing")
        self.assertIn("raw/manual.html", entry["missing"])

    def test_empty_when_page_has_no_pins(self):
        self.store.update_page(
            "concepts/orphan.md", "Body with no citations\n",
            reason="seed",
        )
        report = self.store.verify_pins("concepts/orphan.md")
        entry = report["checked"][0]
        self.assertEqual(entry["status"], "empty")

    def test_verify_all_pages(self):
        self.store.update_page("a.md", "body", reason="seed", sources=["raw/manual.html"])
        self.store.update_page("b.md", "body", reason="seed", sources=["raw/ref/tcl.html"])
        # Mutate one source so we get a mixed report.
        (self.raw_root / "manual.html").write_text("changed\n", encoding="utf-8")
        report = self.store.verify_pins()
        statuses = {r["page"]: r["status"] for r in report["checked"]}
        self.assertEqual(statuses["a.md"], "drift")
        self.assertEqual(statuses["b.md"], "fresh")
        self.assertEqual(report["summary"]["drift"], 1)
        self.assertEqual(report["summary"]["fresh"], 1)


# ---------------------------------------------------------------------------
# Log file
# ---------------------------------------------------------------------------

class LogTests(_WikiTestBase):
    def test_log_entry_has_greppable_prefix(self):
        self.store.update_page("x.md", "body", reason="initial draft")
        log = (self.wiki_root / "log.md").read_text(encoding="utf-8")
        # Greppable: ## [YYYY-MM-DD HH:MM:SS] kind | page — detail
        import re
        match = re.search(
            r"^## \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] update \| x\.md — initial draft$",
            log,
            re.MULTILINE,
        )
        self.assertIsNotNone(match, f"log entry missing or malformed in:\n{log}")

    def test_log_is_append_only(self):
        self.store.update_page("x.md", "body", reason="r1")
        self.store.update_page("y.md", "body", reason="r2")
        log = (self.wiki_root / "log.md").read_text(encoding="utf-8")
        # Both reasons must be present and in order.
        self.assertLess(log.index("r1"), log.index("r2"))

    def test_log_auto_created_if_deleted(self):
        (self.wiki_root / "log.md").unlink()
        self.store.update_page("x.md", "body", reason="post-delete")
        self.assertTrue((self.wiki_root / "log.md").exists())
        self.assertIn("post-delete", (self.wiki_root / "log.md").read_text())


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------

class AtomicityTests(_WikiTestBase):
    def test_failed_rename_does_not_corrupt_existing_page(self):
        # Seed a page.
        self.store.update_page("x.md", "ORIGINAL\n", reason="seed")
        original = (self.wiki_root / "x.md").read_text()

        # Force os.replace to fail; the fallback path then writes the
        # final file directly. Either way, the file must end up either
        # ORIGINAL or NEW — never a truncated mess.
        real_replace = os.replace
        def boom(src, dst):
            raise OSError("simulated rename failure")

        with mock.patch("vmd_ai_runtime.wiki_store.os.replace", side_effect=boom):
            try:
                self.store.update_page("x.md", "NEW CONTENT\n", reason="retry")
            except Exception:
                pass

        final = (self.wiki_root / "x.md").read_text(encoding="utf-8")
        # The fallback in _atomic_write does a direct write_text on the
        # target — so we expect NEW (just no atomic rename). The key
        # invariant we're testing: the file is not empty/corrupted.
        self.assertTrue(final.strip(), "page was truncated by failed update")
        self.assertIn("NEW CONTENT", final)


# ---------------------------------------------------------------------------
# End-to-end: full ingest workflow
# ---------------------------------------------------------------------------

class WorkflowTests(_WikiTestBase):
    """A representative end-to-end flow modeling a real ingest:

    1. Agent reads index (empty)
    2. Agent files a concept page with sources pinned
    3. Agent files a project page linking back to the concept
    4. Agent re-reads — sees its own work, including pins
    5. Source upstream changes; verify_pins flags drift
    """
    def test_full_workflow(self):
        # 1
        self.assertEqual(self.store.read_index(), DEFAULT_INDEX_BODY)
        # 2
        self.store.update_page(
            "concepts/atomselect.md",
            "# atomselect\nThe atomselect command...\n",
            reason="seed page from VMD manual",
            sources=["raw/manual.html"],
        )
        # 3
        self.store.update_page(
            "projects/demo.md",
            "# Demo project\nUses [[concepts/atomselect.md]] heavily.\n",
            reason="track demo project",
        )
        # 4
        rec = self.store.read_page("concepts/atomselect.md")
        self.assertEqual(len(rec.pins), 1)
        self.assertEqual(rec.pins[0].path, "raw/manual.html")
        self.assertIn("atomselect", rec.body)
        # 5
        (self.raw_root / "manual.html").write_text("v2\n", encoding="utf-8")
        report = self.store.verify_pins()
        statuses = {r["page"]: r["status"] for r in report["checked"]}
        self.assertEqual(statuses["concepts/atomselect.md"], "drift")
        self.assertEqual(statuses["projects/demo.md"], "empty")


if __name__ == "__main__":
    unittest.main()
