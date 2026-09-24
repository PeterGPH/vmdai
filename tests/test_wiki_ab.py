"""
test_wiki_ab.py — deterministic A/B comparison: wiki-on vs wiki-off.

These tests don't hit an LLM. They use ``make_scripted_trial_fn`` to
replay the *same* tool-call sequence under both configurations and
verify that:

  1. With wiki enabled, wiki_* calls succeed and produce knowledge
     accumulation (pages filed, sources pinned, log entries written).
  2. With wiki disabled, those exact same calls return structured
     errors — the agent has nothing to fall back on without the wiki.
  3. The bench harness's derived metrics (citation_rate, pages_filed,
     tool distribution) reflect the difference correctly.

This is the regression net for the wiki feature. Run live-LLM evals via
``scripts/bench_wiki.py`` for quality measurements; these tests just
guarantee the plumbing keeps working.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from vmd_ai_runtime.wiki_bench import (  # noqa: E402
    ScriptedStep,
    make_scripted_trial_fn,
    run_bench,
    write_report,
)
from vmd_ai_runtime.wiki_store import WikiStore  # noqa: E402


# ---------------------------------------------------------------------------
# Test base — gives each test a tmp wiki + raw root pre-seeded with one
# concept page so the with-wiki arm has something to find.
# ---------------------------------------------------------------------------

class _ABTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.wiki_root = base / "wiki"
        self.raw_root = base / "raw"
        self.raw_root.mkdir()
        (self.raw_root / "atomselect.html").write_text(
            "<h1>atomselect</h1>\nselection language\n", encoding="utf-8"
        )
        (self.raw_root / "representations.html").write_text(
            "<h1>Representations</h1>\nNewCartoon Licorice VDW\n",
            encoding="utf-8",
        )
        self.wiki = WikiStore(self.wiki_root, raw_root=self.raw_root)
        self.wiki.bootstrap()
        # Pre-seed the wiki with one well-formed concept page so the
        # with-wiki arm can demonstrate the "knowledge already compiled"
        # benefit. The without-wiki arm has no such advantage.
        self.wiki.update_page(
            "concepts/atomselect.md",
            "# atomselect\nUsed for selection. See manual.\n",
            reason="pre-seed for A/B bench",
            sources=["raw/atomselect.html"],
        )


# ---------------------------------------------------------------------------
# Scripted agent: the wiki-driven "good citizen" the LLM should aim for
# ---------------------------------------------------------------------------

class WikiDrivenAgentTests(_ABTestBase):
    """A model that uses wiki tools when they're available.

    Script: list → read existing page → file a follow-up page citing a
    source. Under wiki-on, all three succeed and produce measurable
    knowledge accumulation. Under wiki-off, all three fail.
    """
    SCRIPT = [
        ScriptedStep("wiki_list", {}),
        ScriptedStep("wiki_read", {"page": "concepts/atomselect.md"}),
        ScriptedStep("wiki_update", {
            "page": "concepts/representations.md",
            "content": "# Representations\nNewCartoon/Licorice/VDW.\n",
            "reason": "ingested representations doc",
            "sources": ["raw/representations.html"],
        }),
    ]

    def _run(self):
        trial_fn = make_scripted_trial_fn(self.SCRIPT)
        return run_bench(
            prompts=["How do I select a ligand and show it as VDW?"],
            trial_fn=trial_fn,
            with_wiki_store=self.wiki,
            config={"script": "wiki_driven"},
        )

    def test_with_wiki_arm_succeeds(self):
        report = self._run()
        with_trial = next(
            t for t in report.trials if t.arm == "with_wiki"
        )
        # Every scripted tool call must have succeeded.
        for call in with_trial.tool_calls:
            self.assertTrue(call.ok,
                            f"with_wiki: {call.name} failed: {call.error}")
        # The agent read one existing page and wrote one new page.
        self.assertEqual(with_trial.pages_read, ["concepts/atomselect.md"])
        self.assertEqual(with_trial.pages_updated, ["concepts/representations.md"])
        # The new page cited a source — that's the citation signal.
        self.assertIn("raw/representations.html", with_trial.sources_cited)

    def test_without_wiki_arm_fails(self):
        report = self._run()
        without_trial = next(
            t for t in report.trials if t.arm == "without_wiki"
        )
        # All three wiki calls return structured "not configured" errors.
        for call in without_trial.tool_calls:
            self.assertFalse(call.ok)
            self.assertIn("wiki", call.error.lower())
        # No knowledge was accumulated — that's the cost of having no wiki.
        self.assertEqual(without_trial.pages_read, [])
        self.assertEqual(without_trial.pages_updated, [])
        self.assertEqual(without_trial.sources_cited, [])

    def test_summary_reflects_difference(self):
        report = self._run()
        with_arm = report.summaries["with_wiki"]
        without_arm = report.summaries["without_wiki"]

        # Citation rate is the headline metric — wiki arm should cite,
        # no-wiki arm cannot.
        self.assertGreater(with_arm.citation_rate, 0.0)
        self.assertEqual(without_arm.citation_rate, 0.0)

        # Pages filed: only the wiki arm accumulates knowledge.
        self.assertGreater(with_arm.pages_filed, 0)
        self.assertEqual(without_arm.pages_filed, 0)

        # Both arms call the same tools by name (because the script is
        # the same), but distinct_sources_cited diverges sharply.
        self.assertGreater(with_arm.distinct_sources_cited,
                           without_arm.distinct_sources_cited)


# ---------------------------------------------------------------------------
# Multiple-prompt bench — proves accumulation across turns
# ---------------------------------------------------------------------------

class AccumulationTests(_ABTestBase):
    """The wiki pattern's central claim: knowledge accumulates.

    Run a sequence of three "ingest" prompts that each file a new page.
    By the end, the with-wiki arm has 4 pages (1 seeded + 3 filed); the
    without-wiki arm has none.
    """

    def test_three_ingest_turns(self):
        prompts = ["ingest doc A", "ingest doc B", "ingest doc C"]
        scripts = {
            "ingest doc A": [ScriptedStep("wiki_update", {
                "page": "concepts/a.md", "content": "A\n",
                "reason": "ingest A", "sources": ["raw/atomselect.html"],
            })],
            "ingest doc B": [ScriptedStep("wiki_update", {
                "page": "concepts/b.md", "content": "B\n",
                "reason": "ingest B", "sources": ["raw/representations.html"],
            })],
            "ingest doc C": [ScriptedStep("wiki_update", {
                "page": "concepts/c.md", "content": "C\n",
                "reason": "ingest C",
                "sources": ["raw/atomselect.html", "raw/representations.html"],
            })],
        }

        # Per-prompt scripted runner. Each prompt has its own scripted
        # tool sequence so the harness exercises the multi-prompt path.
        def trial_fn(prompt, wiki_store):
            return make_scripted_trial_fn(scripts[prompt])(prompt, wiki_store)

        report = run_bench(
            prompts=prompts,
            trial_fn=trial_fn,
            with_wiki_store=self.wiki,
            config={"script": "accumulation"},
        )

        with_arm = report.summaries["with_wiki"]
        without_arm = report.summaries["without_wiki"]
        self.assertEqual(with_arm.pages_filed, 3)
        self.assertEqual(without_arm.pages_filed, 0)
        # All three with-wiki trials cited at least one source.
        self.assertEqual(with_arm.citation_rate, 1.0)
        # The wiki has actually grown on disk — verify by listing.
        slugs = {p["page"] for p in self.wiki.list_pages()}
        self.assertIn("concepts/atomselect.md", slugs)  # seed
        self.assertIn("concepts/a.md", slugs)
        self.assertIn("concepts/b.md", slugs)
        self.assertIn("concepts/c.md", slugs)


# ---------------------------------------------------------------------------
# Report rendering + round-trip
# ---------------------------------------------------------------------------

class ReportTests(_ABTestBase):
    def test_report_round_trip_json(self):
        trial_fn = make_scripted_trial_fn([
            ScriptedStep("wiki_list", {}),
            ScriptedStep("wiki_read", {"page": "concepts/atomselect.md"}),
        ])
        report = run_bench(
            prompts=["look up atomselect"],
            trial_fn=trial_fn,
            with_wiki_store=self.wiki,
        )
        out_dir = Path(self.tmp.name) / "report"
        json_path, md_path = write_report(report, out_dir)
        self.assertTrue(json_path.exists())
        self.assertTrue(md_path.exists())
        # JSON round-trips.
        loaded = json.loads(json_path.read_text())
        self.assertEqual(loaded["prompts"], ["look up atomselect"])
        self.assertIn("with_wiki", loaded["summaries"])
        self.assertIn("without_wiki", loaded["summaries"])
        # Markdown contains the headline table headers.
        md = md_path.read_text()
        self.assertIn("# Wiki A/B Benchmark Report", md)
        self.assertIn("citation rate", md)
        self.assertIn("pages filed", md)


# ---------------------------------------------------------------------------
# Reality check — the agent that doesn't try the wiki at all
# ---------------------------------------------------------------------------

class NoWikiCallsBaseline(_ABTestBase):
    """If the model never calls the wiki tools, both arms should look
    identical — proves the harness isn't accidentally biasing results."""

    def test_identical_when_no_wiki_calls(self):
        # search_docs without an index will return an error in both
        # arms identically — perfect for this control.
        trial_fn = make_scripted_trial_fn([
            ScriptedStep("search_docs", {"query": "atomselect"}),
        ])
        report = run_bench(
            prompts=["just search"],
            trial_fn=trial_fn,
            with_wiki_store=self.wiki,
        )
        with_arm = report.summaries["with_wiki"]
        without_arm = report.summaries["without_wiki"]
        self.assertEqual(with_arm.pages_filed, without_arm.pages_filed)
        self.assertEqual(with_arm.distinct_sources_cited,
                         without_arm.distinct_sources_cited)
        self.assertEqual(with_arm.citation_rate, without_arm.citation_rate)


if __name__ == "__main__":
    unittest.main()
