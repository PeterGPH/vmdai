"""
Step R — RunRecorder tests.

Covers:
    construction        · runs_root config, for_cwd factory, no-runs-root error
    task lifecycle      · start/end, auto-supersede, idempotent end, unique ids
    record success      · transcript.tcl gets the command, manifest counts move
    record failure      · transcript.tcl untouched; failed_count increments
    snapshot success    · image file written, render line added
    snapshot failure    · no file written, no transcript line
    per-task isolation  · two tasks in same root have separate directories
    manifest correctness· every field present, atomic write doesn't corrupt
    Tcl-syntax validity · tclsh parses every transcript without error
    Tcl-replay smoke    · stub vmd procs + tclsh successfully run the transcript

Pure stdlib + tclsh (8.6+). Each test uses a fresh tempdir.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.recorder import RunRecorder, RunRecorderError  # noqa: E402
from helpers.tcl import find_tclsh, tcl_skip_reason  # noqa: E402

TCLSH = find_tclsh()
_TCL_SKIP = tcl_skip_reason()


# ----------------------------------------------------------------------
# Construction
# ----------------------------------------------------------------------

class ConstructionTests(unittest.TestCase):

    def test_no_runs_root_rejects_start_task(self):
        rec = RunRecorder()
        with self.assertRaises(RunRecorderError):
            rec.start_task("anything")

    def test_for_cwd_factory(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            self.assertEqual(rec.runs_root, Path(tmp) / ".vmdai_runs")

    def test_for_cwd_uses_process_cwd_by_default(self):
        rec = RunRecorder.for_cwd()
        self.assertEqual(rec.runs_root, Path.cwd() / ".vmdai_runs")

    def test_runs_root_created_on_first_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            self.assertFalse(rec.runs_root.exists())
            rec.start_task("test prompt")
            self.assertTrue(rec.runs_root.exists())


# ----------------------------------------------------------------------
# Task lifecycle
# ----------------------------------------------------------------------

class TaskLifecycleTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = RunRecorder.for_cwd(self.tmp.name)

    def test_start_task_creates_directory(self):
        tid = self.rec.start_task("visualize docked pose")
        task_dir = self.rec.runs_root / tid
        self.assertTrue(task_dir.is_dir())
        self.assertTrue((task_dir / "manifest.json").is_file())
        self.assertTrue((task_dir / "transcript.tcl").is_file())
        self.assertTrue((task_dir / "snapshots").is_dir())

    def test_task_id_contains_slug(self):
        tid = self.rec.start_task("visualize ligand pocket")
        self.assertIn("visualize", tid)

    def test_task_ids_are_unique(self):
        ids = [self.rec.start_task("same prompt") for _ in range(5)]
        self.rec.end_task()
        self.assertEqual(len(set(ids)), 5)

    def test_starting_new_task_supersedes_prior(self):
        a = self.rec.start_task("task a")
        b = self.rec.start_task("task b")
        self.assertNotEqual(a, b)
        manifest_a = self.rec.read_manifest(a)
        self.assertEqual(manifest_a["status"], "superseded")
        manifest_b = self.rec.read_manifest(b)
        self.assertEqual(manifest_b["status"], "active")

    def test_end_task_marks_complete(self):
        tid = self.rec.start_task("x")
        self.rec.end_task()
        self.assertEqual(self.rec.read_manifest(tid)["status"], "complete")
        self.assertIn("ended_at", self.rec.read_manifest(tid))

    def test_end_task_with_custom_status(self):
        tid = self.rec.start_task("x")
        self.rec.end_task(status="cancelled")
        self.assertEqual(self.rec.read_manifest(tid)["status"], "cancelled")

    def test_end_task_idempotent(self):
        tid = self.rec.start_task("x")
        self.assertEqual(self.rec.end_task(), tid)
        # Second end is a no-op
        self.assertIsNone(self.rec.end_task())

    def test_current_properties_track_state(self):
        self.assertIsNone(self.rec.current_task_id)
        self.assertFalse(self.rec.is_active)
        tid = self.rec.start_task("x")
        self.assertEqual(self.rec.current_task_id, tid)
        self.assertTrue(self.rec.is_active)
        self.rec.end_task()
        self.assertIsNone(self.rec.current_task_id)
        self.assertFalse(self.rec.is_active)


# ----------------------------------------------------------------------
# Recording — VMD commands
# ----------------------------------------------------------------------

class CommandRecordingTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = RunRecorder.for_cwd(self.tmp.name)
        self.tid = self.rec.start_task("test", chat_id="chat_x", model="claude-x")

    def test_record_success_appears_in_transcript(self):
        rv = self.rec.record_vmd_command(
            "mol new 1ubq.pdb",
            ok=True,
            rationale="load the test structure",
            duration_ms=12.3,
        )
        self.assertEqual(rv, 1)
        text = self.rec.read_transcript(self.tid)
        self.assertIn("mol new 1ubq.pdb", text)
        self.assertIn("turn 01", text)
        self.assertIn("load the test structure", text)

    def test_record_failure_not_in_transcript(self):
        rv = self.rec.record_vmd_command(
            "mol_color ResName",   # bad identifier
            ok=False,
            duration_ms=1.0,
        )
        self.assertIsNone(rv)
        text = self.rec.read_transcript(self.tid)
        self.assertNotIn("mol_color", text)

    def test_manifest_counters_track_outcomes(self):
        self.rec.record_vmd_command("mol new 1ubq.pdb", ok=True)
        self.rec.record_vmd_command("mol_color foo", ok=False)
        self.rec.record_vmd_command("mol delete top", ok=True)
        m = self.rec.read_manifest(self.tid)
        self.assertEqual(m["turn_count"], 3)
        self.assertEqual(m["successful_count"], 2)
        self.assertEqual(m["failed_count"], 1)

    def test_turn_numbers_are_consecutive_across_outcomes(self):
        # turn_count increments even on failure; verifies the audit
        # trail in the manifest stays gap-free.
        self.rec.record_vmd_command("a", ok=True)      # turn 1
        self.rec.record_vmd_command("b", ok=False)     # turn 2 (failed)
        rv = self.rec.record_vmd_command("c", ok=True) # turn 3
        self.assertEqual(rv, 3)
        text = self.rec.read_transcript(self.tid)
        # Successful turns marked 01 and 03 (no 02 in transcript)
        self.assertIn("turn 01", text)
        self.assertIn("turn 03", text)
        self.assertNotIn("turn 02", text)

    def test_record_outside_task_is_noop(self):
        self.rec.end_task()
        rv = self.rec.record_vmd_command("anything", ok=True)
        self.assertIsNone(rv)

    def test_rationale_is_optional(self):
        self.rec.record_vmd_command("mol new 1ubq.pdb", ok=True)
        text = self.rec.read_transcript(self.tid)
        self.assertIn("mol new 1ubq.pdb", text)
        # No rationale comment line should appear
        self.assertNotIn("# rationale", text)

    def test_multiline_command_preserved(self):
        cmd = "set lig [atomselect 0 \"resname LIG\"]\n$lig num\n$lig delete"
        self.rec.record_vmd_command(cmd, ok=True)
        text = self.rec.read_transcript(self.tid)
        self.assertIn("$lig num", text)
        self.assertIn("$lig delete", text)


# ----------------------------------------------------------------------
# Recording — snapshots
# ----------------------------------------------------------------------

class SnapshotRecordingTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rec = RunRecorder.for_cwd(self.tmp.name)
        self.tid = self.rec.start_task("snapshot test")

    def test_snapshot_writes_image_file(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        rv = self.rec.record_snapshot(
            ok=True,
            purpose="final pose",
            image_bytes=png,
            image_ext="png",
        )
        self.assertEqual(rv, 1)
        snap = self.rec.runs_root / self.tid / "snapshots" / "turn_001.png"
        self.assertTrue(snap.is_file())
        self.assertEqual(snap.read_bytes(), png)
        text = self.rec.read_transcript(self.tid)
        self.assertIn("render snapshot snapshots/turn_001.png", text)
        self.assertIn("final pose", text)

    def test_snapshot_failure_does_not_save_image(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        rv = self.rec.record_snapshot(ok=False, image_bytes=png)
        self.assertIsNone(rv)
        snap_dir = self.rec.runs_root / self.tid / "snapshots"
        self.assertEqual(list(snap_dir.iterdir()), [])
        m = self.rec.read_manifest(self.tid)
        self.assertEqual(m["snapshot_count"], 0)
        self.assertEqual(m["failed_count"], 1)

    def test_unsafe_extension_falls_back_to_png(self):
        rv = self.rec.record_snapshot(
            ok=True,
            image_bytes=b"raw",
            image_ext="exe",   # not allowed
        )
        self.assertEqual(rv, 1)
        snap = self.rec.runs_root / self.tid / "snapshots" / "turn_001.png"
        self.assertTrue(snap.is_file())

    def test_snapshot_count_tracks_only_successes(self):
        self.rec.record_snapshot(ok=True, image_bytes=b"a")
        self.rec.record_snapshot(ok=False)
        self.rec.record_snapshot(ok=True, image_bytes=b"b")
        m = self.rec.read_manifest(self.tid)
        self.assertEqual(m["snapshot_count"], 2)


# ----------------------------------------------------------------------
# Isolation
# ----------------------------------------------------------------------

class IsolationTests(unittest.TestCase):

    def test_two_tasks_have_separate_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            t1 = rec.start_task("task one")
            rec.record_vmd_command("mol new a.pdb", ok=True)
            rec.end_task()
            t2 = rec.start_task("task two")
            rec.record_vmd_command("mol new b.pdb", ok=True)
            rec.end_task()
            self.assertIn("mol new a.pdb", rec.read_transcript(t1))
            self.assertNotIn("mol new b.pdb", rec.read_transcript(t1))
            self.assertIn("mol new b.pdb", rec.read_transcript(t2))
            self.assertNotIn("mol new a.pdb", rec.read_transcript(t2))

    def test_list_tasks_returns_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            ids = []
            for i in range(3):
                ids.append(rec.start_task(f"task {i}"))
                rec.end_task()
            listed = rec.list_tasks()
            self.assertEqual(len(listed), 3)
            for tid in ids:
                self.assertIn(tid, listed)


# ----------------------------------------------------------------------
# Manifest correctness
# ----------------------------------------------------------------------

class ManifestTests(unittest.TestCase):

    def test_manifest_has_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task(
                "field check",
                chat_id="chat_x",
                model="claude-test",
                cwd="/work",
            )
            m = rec.read_manifest(tid)
            for field in (
                "task_id", "status", "prompt", "chat_id", "model", "cwd",
                "started_at", "last_activity_at",
                "turn_count", "successful_count", "failed_count", "snapshot_count",
            ):
                self.assertIn(field, m, f"missing field: {field}")
            self.assertEqual(m["prompt"], "field check")
            self.assertEqual(m["chat_id"], "chat_x")
            self.assertEqual(m["model"], "claude-test")
            self.assertEqual(m["cwd"], "/work")

    def test_manifest_atomic_write_no_partial_state(self):
        # Read manifest after every record; must always be valid JSON.
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task("atomic test")
            for i in range(20):
                rec.record_vmd_command(f"set x {i}", ok=True)
                m = json.loads(
                    (rec.runs_root / tid / "manifest.json").read_text()
                )
                self.assertEqual(m["turn_count"], i + 1)
            rec.end_task()


# ----------------------------------------------------------------------
# Tcl syntax validation (real tclsh)
# ----------------------------------------------------------------------

@unittest.skipIf(_TCL_SKIP is not None, _TCL_SKIP or "")
class TclValidityTests(unittest.TestCase):

    def _tcl_parse(self, transcript: Path) -> tuple[int, str]:
        """Run ``tclsh`` against ``transcript`` and return (rc, stderr).

        We stub every VMD-specific command so tclsh doesn't blow up on
        unknown procs — that way we're testing *Tcl syntax*, not VMD
        availability. The parser-error path goes through stderr.
        """
        stub = (
            # Glob-catch unknown commands: if a `mol`/`atomselect`/etc
            # is called, return "" so the transcript executes cleanly.
            "proc unknown {args} { return \"\" }\n"
        )
        # Run as `tclsh -c "stub; source transcript"` — tclsh has no
        # -c flag in 8.6, so feed via stdin and source the file.
        proc = subprocess.run(
            [TCLSH],
            input=stub + f"source {transcript.as_posix()}\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode, proc.stderr

    def test_empty_transcript_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task("empty")
            rec.end_task()
            rc, err = self._tcl_parse(rec.runs_root / tid / "transcript.tcl")
            self.assertEqual(rc, 0, f"tclsh failed: {err}")

    def test_typical_session_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task("session")
            rec.record_vmd_command("mol new 1ubq.pdb", ok=True,
                                   rationale="load structure")
            rec.record_vmd_command(
                "set sel [atomselect 0 \"protein\"]\n$sel num\n$sel delete",
                ok=True,
            )
            rec.record_vmd_command("mol representation NewCartoon", ok=True)
            rec.record_vmd_command("BAD_CMD", ok=False)  # not in transcript
            rec.record_snapshot(ok=True, image_bytes=b"\x89PNG\r\n\x1a\n",
                                purpose="final view")
            rec.end_task()
            rc, err = self._tcl_parse(rec.runs_root / tid / "transcript.tcl")
            self.assertEqual(rc, 0, f"tclsh failed: {err}")

    def test_command_with_braces_and_dollars_parses(self):
        """Brace/dollar/bracket density is where naive emission breaks."""
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task("braces")
            rec.record_vmd_command(
                "for {set f 0} {$f < 10} {incr f} {\n    puts [list $f $f]\n}",
                ok=True,
            )
            rec.end_task()
            rc, err = self._tcl_parse(rec.runs_root / tid / "transcript.tcl")
            self.assertEqual(rc, 0, f"tclsh failed: {err}")


# ----------------------------------------------------------------------
# End-to-end replay smoke
# ----------------------------------------------------------------------

@unittest.skipIf(_TCL_SKIP is not None, _TCL_SKIP or "")
class ReplaySmokeTests(unittest.TestCase):
    """The point of this whole subpackage is reproducibility — so the
    last test simulates the full happy path: record a docking-like
    sequence, then run the resulting transcript.tcl through tclsh and
    verify it executes top-to-bottom with all commands taking effect.

    We stub the VMD-specific commands with Tcl procs that record what
    they were called with, so we can assert the replay actually
    invoked them in the right order.
    """

    def test_recorded_session_replays_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = RunRecorder.for_cwd(tmp)
            tid = rec.start_task(
                "docking visualization",
                chat_id="chat_abc",
                model="claude-sonnet-4.6",
            )
            rec.record_vmd_command(
                "mol new receptor.pdbqt",
                ok=True, rationale="load receptor",
            )
            rec.record_vmd_command(
                "mol new vina_out.pdbqt",
                ok=True, rationale="load poses",
            )
            rec.record_vmd_command("typo_in_tcl",
                                   ok=False)  # not recorded
            rec.record_vmd_command(
                "mol representation Licorice 0.25 12 12",
                ok=True,
            )
            rec.record_snapshot(ok=True, image_bytes=b"\x89PNG\r\n\x1a\n",
                                purpose="check the pose")
            rec.end_task()

            transcript = rec.runs_root / tid / "transcript.tcl"
            self.assertTrue(transcript.exists())

            # Drive tclsh: collect every recorded call into a list, then
            # print it so we can assert on the replay order.
            harness = (
                "set CALLS [list]\n"
                "proc record {name args} { global CALLS; "
                "lappend CALLS [linsert $args 0 $name] }\n"
                "proc mol {args} { record mol {*}$args }\n"
                "proc render {args} { record render {*}$args }\n"
                "proc unknown {args} { record UNKNOWN {*}$args }\n"
                f"source {transcript.as_posix()}\n"
                "foreach c $CALLS { puts $c }\n"
            )
            proc = subprocess.run(
                [TCLSH],
                input=harness,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0,
                             msg=f"tclsh stderr: {proc.stderr}")
            output = proc.stdout.strip().splitlines()
            # We expect: 3 successful mol calls + 1 render snapshot
            self.assertEqual(len(output), 4,
                             msg=f"got: {output}")
            self.assertIn("mol new receptor.pdbqt", output[0])
            self.assertIn("mol new vina_out.pdbqt", output[1])
            self.assertIn("Licorice", output[2])
            self.assertIn("snapshot", output[3])
            # The failed turn must not have produced a call.
            for line in output:
                self.assertNotIn("typo_in_tcl", line)


if __name__ == "__main__":
    unittest.main()
