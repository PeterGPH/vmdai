"""
Tests for scripts/rag_ab_extract.py.

Covers everything the extractor must guarantee, especially the bugs
caught during manual replay sessions:

  1. The generated .tcl files PARSE cleanly through real `tclsh`.
     (Catches: bracket-substitution typos, malformed if/then/else,
     missing escapes — i.e. the original `[snapshot turn N]` bug.)

  2. Snapshot calls emit `render TachyonInternal`, NOT `render snapshot`.
     `render snapshot` produces 18-byte TGA headers when the OpenGL
     framebuffer isn't initialized; TachyonInternal renders the scene
     graph directly.

  3. Snapshot calls are guarded by `[molinfo num] > 0` so the very
     first probe snapshot (taken before any successful mol load)
     doesn't produce an empty file. The puts uses no square brackets
     (which Tcl would treat as command substitution).

  4. The render-quality preamble is present (1920² resize,
     antialiasing, AO + shadows enabled). Without it the default
     headless render is 512x512 + aliased = unusable for figures.

  5. run_vmd_command tool calls preserve the model's exact Tcl
     verbatim, with rationale as a comment.

  6. search_docs calls become commented-out informational lines —
     they're recorded so a human reader sees what the agent queried
     for, but they don't translate to runnable Tcl.

  7. If an arm errored mid-run, a "NOTE: the arm errored" footer is
     appended explaining that the trace is partial.

  8. Both arms (`control.tcl` and `rag.tcl`) are produced from one
     JSON input, side by side.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import rag_ab_extract  # noqa: E402
from helpers.tcl import find_tclsh, tcl_skip_reason  # noqa: E402

TCLSH = find_tclsh()
_TCL_SKIP = tcl_skip_reason()


# ----------------------------------------------------------------------
# Fixtures — synthesize realistic rag_ab JSON output
# ----------------------------------------------------------------------

def _make_control_arm() -> dict:
    return {
        "name": "control (no RAG)",
        "elapsed_s": 57.0,
        "error": None,
        "final_text": "Done.",
        "chunks": [],
        "summary": {},
        "tool_calls": [
            {
                "tool_name": "run_vmd_command",
                "tool_call_id": "toolu_001",
                "tool_input": {
                    "command": "mol new 1ubq.pdb",
                    "rationale": "load test structure",
                },
            },
            {
                "tool_name": "capture_vmd_snapshot",
                "tool_call_id": "toolu_002",
                "tool_input": {"purpose": "check load"},
            },
            {
                "tool_name": "run_vmd_command",
                "tool_call_id": "toolu_003",
                "tool_input": {
                    "command": (
                        "mol representation NewCartoon 0.3 12.0 4.5\n"
                        "mol color Structure\nmol addrep top"
                    ),
                    "rationale": "build cartoon rep",
                },
            },
            {
                "tool_name": "run_vmd_command",
                "tool_call_id": "toolu_004",
                "tool_input": {
                    "command": "render TachyonInternal /tmp/final.tga",
                },
            },
            {
                "tool_name": "capture_vmd_snapshot",
                "tool_call_id": "toolu_005",
                "tool_input": {"purpose": "final"},
            },
        ],
    }


def _make_rag_arm() -> dict:
    return {
        "name": "rag (search_docs available)",
        "elapsed_s": 35.0,
        "error": "ClaudeLoopError: HTTP 429 rate limit",
        "final_text": "",
        "chunks": [],
        "summary": {},
        "tool_calls": [
            {
                "tool_name": "search_docs",
                "tool_call_id": "sd_0",
                "tool_input": {
                    "query": "academic style protein ligand",
                    "scope": "skills",
                },
            },
            {
                "tool_name": "run_vmd_command",
                "tool_call_id": "toolu_010",
                "tool_input": {
                    "command": "mol load webpdb 1HCK",
                    "rationale": "load CDK2/AMPPNP from kinase SKILL",
                },
            },
            {
                "tool_name": "capture_vmd_snapshot",
                "tool_call_id": "toolu_011",
                "tool_input": {"purpose": "verify load"},
            },
        ],
    }


def _make_json(tmp: Path) -> Path:
    path = tmp / "rag_ab_in.json"
    data = {
        "prompt": "present CDK2 academically with ATP",
        "provider_mode": "anthropic-direct",
        "control": _make_control_arm(),
        "rag": _make_rag_arm(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ----------------------------------------------------------------------
# Extractor CLI / output shape
# ----------------------------------------------------------------------

class ExtractorOutputShapeTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.in_json = _make_json(self.tmp_path)
        self.out_dir = self.tmp_path / "replay"
        rc = rag_ab_extract.main([
            str(self.in_json),
            "--out-dir", str(self.out_dir),
        ])
        self.assertEqual(rc, 0)

    def test_produces_both_arm_scripts(self):
        self.assertTrue((self.out_dir / "control.tcl").exists())
        self.assertTrue((self.out_dir / "rag.tcl").exists())

    def test_scripts_contain_header_metadata(self):
        ctrl = (self.out_dir / "control.tcl").read_text()
        for needle in [
            "# VMD AI · A/B harness replay",
            "# arm        : control (no RAG)",
            "# prompt     : present CDK2 academically with ATP",
            "vmd -e control.tcl",
            "file mkdir snapshots",
        ]:
            self.assertIn(needle, ctrl, msg=f"missing in control.tcl: {needle!r}")

    def test_errored_arm_gets_partial_trace_note(self):
        rag = (self.out_dir / "rag.tcl").read_text()
        self.assertIn("NOTE: the arm errored", rag)
        self.assertIn("HTTP 429", rag)


# ----------------------------------------------------------------------
# Render-quality preamble
# ----------------------------------------------------------------------

class RenderQualityPreambleTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.in_json = _make_json(self.tmp_path)
        self.out_dir = self.tmp_path / "replay"
        rag_ab_extract.main([
            str(self.in_json), "--out-dir", str(self.out_dir),
        ])
        self.script = (self.out_dir / "control.tcl").read_text()

    def test_resolution_is_bumped_above_default(self):
        self.assertIn("display resize 1920 1920", self.script)

    def test_antialiasing_enabled(self):
        self.assertIn("display antialias on", self.script)

    def test_ambient_occlusion_enabled(self):
        self.assertIn("display ambientocclusion on", self.script)

    def test_shadows_enabled(self):
        self.assertIn("display shadows on", self.script)

    def test_preamble_runs_before_model_commands(self):
        # The first model command in our fixture is "mol new 1ubq.pdb".
        # The preamble's "display resize" must appear BEFORE it,
        # otherwise the first auto-snapshot uses the default size.
        idx_preamble = self.script.find("display resize 1920 1920")
        idx_first_cmd = self.script.find("mol new 1ubq.pdb")
        self.assertGreater(idx_preamble, 0)
        self.assertGreater(idx_first_cmd, idx_preamble)


# ----------------------------------------------------------------------
# Snapshot translation — TachyonInternal + molinfo guard
# ----------------------------------------------------------------------

class SnapshotTranslationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.in_json = _make_json(self.tmp_path)
        self.out_dir = self.tmp_path / "replay"
        rag_ab_extract.main([
            str(self.in_json), "--out-dir", str(self.out_dir),
        ])
        self.script = (self.out_dir / "control.tcl").read_text()

    def test_snapshot_uses_tachyon_not_render_snapshot(self):
        # `render snapshot` produces 18-byte TGA headers when there's
        # no OpenGL framebuffer. The replay path must use TachyonInternal.
        self.assertIn("render TachyonInternal", self.script)
        # Anywhere `render snapshot ` appears, it should only be inside
        # commands the MODEL emitted (e.g. embedded in user-provided
        # rationale comments) — not as a top-level extractor command.
        for line in self.script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue   # comments are allowed to mention it
            self.assertNotIn(
                "render snapshot ",
                stripped,
                msg=f"extractor must not emit `render snapshot`: {line!r}",
            )

    def test_snapshot_is_guarded_by_molinfo_num(self):
        # The `if [molinfo num] > 0` guard prevents zero-byte TGAs
        # when the model snapshots before a successful mol load.
        self.assertIn("if {[molinfo num] > 0}", self.script)

    def test_else_branch_uses_no_unescaped_brackets_in_puts(self):
        # Regression test for the original bug:
        #     puts "[snapshot turn 02] skipped — …"
        # Tcl interpreted [snapshot turn 02] as command substitution
        # and failed with `invalid command name "snapshot"`.
        # The else branch must use plain text (no square brackets).
        for line in self.script.splitlines():
            if line.strip().startswith("puts") and "snapshot" in line:
                self.assertNotIn(
                    "[snapshot",
                    line,
                    msg=f"bracket substitution leaked: {line!r}",
                )

    def test_snapshot_paths_increment_per_turn(self):
        # Each snapshot must write to a distinct turn_NNN.tga so
        # subsequent renders don't clobber prior ones.
        import re
        paths = re.findall(r"render TachyonInternal snapshots/turn_(\d+)\.tga",
                           self.script)
        self.assertEqual(len(paths), 2, msg="control fixture has 2 snapshots")
        self.assertEqual(len(set(paths)), 2, msg="snapshot paths must differ")


# ----------------------------------------------------------------------
# run_vmd_command and search_docs translation
# ----------------------------------------------------------------------

class CommandTranslationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.in_json = _make_json(self.tmp_path)
        self.out_dir = self.tmp_path / "replay"
        rag_ab_extract.main([
            str(self.in_json), "--out-dir", str(self.out_dir),
        ])
        self.control = (self.out_dir / "control.tcl").read_text()
        self.rag = (self.out_dir / "rag.tcl").read_text()

    def test_run_vmd_command_tcl_preserved_verbatim(self):
        self.assertIn("mol new 1ubq.pdb", self.control)
        self.assertIn("mol representation NewCartoon 0.3 12.0 4.5",
                      self.control)
        self.assertIn("mol color Structure", self.control)
        self.assertIn("render TachyonInternal /tmp/final.tga", self.control)

    def test_rationale_appears_as_comment(self):
        self.assertIn("# rationale : load test structure", self.control)
        self.assertIn("# rationale : build cartoon rep", self.control)

    def test_search_docs_becomes_comment_not_runnable(self):
        # search_docs has no real Tcl equivalent; record as comment.
        self.assertIn("search_docs not replayable", self.rag)
        self.assertIn("academic style protein ligand", self.rag)
        # And it must NOT translate to anything that looks like a Tcl
        # call (the line should start with `#`).
        for line in self.rag.splitlines():
            if "academic style protein ligand" in line:
                self.assertTrue(
                    line.lstrip().startswith("#"),
                    msg=f"search_docs leaked as command: {line!r}",
                )

    def test_turn_numbering_runs_through_all_calls(self):
        # turn N comments include 01, 02, 03, 04, 05 for the control arm.
        for n in (1, 2, 3, 4, 5):
            self.assertIn(f"# --- turn {n:02d}", self.control)


# ----------------------------------------------------------------------
# Real-tclsh parse check — the integration test
# ----------------------------------------------------------------------

@unittest.skipIf(_TCL_SKIP is not None, _TCL_SKIP or "")
class TclParseTests(unittest.TestCase):

    def _stubbed_run(self, script_path: Path) -> tuple[int, str]:
        """Run the script through tclsh with every VMD command stubbed.

        Verifies pure Tcl syntax (catches bracket-substitution bugs,
        unbalanced braces, malformed if/else). Returns (rc, stderr).
        """
        harness = (
            # Catch-all for unknown VMD commands.
            'proc unknown {args} { return "" }\n'
            # Stub real Tk-side or VMD-side commands the script uses.
            'proc display {args} { return "" }\n'
            'proc mol {args} { return "" }\n'
            'proc molinfo {args} { return 0 }\n'
            'proc render {args} { return "" }\n'
            'proc rotate {args} { return "" }\n'
            'proc scale {args} { return "" }\n'
            'proc translate {args} { return "" }\n'
            'proc color {args} { return "" }\n'
            'proc light {args} { return "" }\n'
            'proc axes {args} { return "" }\n'
            'proc material {args} { return "" }\n'
            'proc atomselect {args} { return "" }\n'
            'proc measure {args} { return {0 0 0} }\n'
            'proc file {args} { return "" }\n'
            'proc package {args} { return "" }\n'
            'proc http {args} { return "" }\n'
            f"source {script_path.as_posix()}\n"
        )
        proc = subprocess.run(
            [TCLSH], input=harness, capture_output=True,
            text=True, timeout=10,
        )
        return proc.returncode, proc.stderr

    def test_control_script_parses_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            in_json = _make_json(tmp_path)
            out_dir = tmp_path / "replay"
            rag_ab_extract.main([str(in_json), "--out-dir", str(out_dir)])
            rc, err = self._stubbed_run(out_dir / "control.tcl")
            self.assertEqual(rc, 0,
                             msg=f"control.tcl failed to parse:\n{err}")

    def test_rag_script_parses_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            in_json = _make_json(tmp_path)
            out_dir = tmp_path / "replay"
            rag_ab_extract.main([str(in_json), "--out-dir", str(out_dir)])
            rc, err = self._stubbed_run(out_dir / "rag.tcl")
            self.assertEqual(rc, 0,
                             msg=f"rag.tcl failed to parse:\n{err}")


if __name__ == "__main__":
    unittest.main()
