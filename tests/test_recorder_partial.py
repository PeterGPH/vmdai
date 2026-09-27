"""C3: the recorder writes the applied prefix and comments out the rest."""
from __future__ import annotations

from helpers.tcl import requires_tcl, run_tcl
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.recorder import RunRecorder

COMMAND = "mol new a.pdb\nmol delrep 0 top\nmol_color x {\n}\nputs done \\"
APPLIED = "mol new a.pdb\nmol delrep 0 top\n"
ERROR = 'invalid command name "mol_color"\n    while executing\n"mol_color x {\n}"'


def _partial(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("partial")
    rec.record_vmd_command(COMMAND, ok=False, rationale="r", duration_ms=5,
                           applied_text=APPLIED, failed_index=3, total=4, error=ERROR)
    rec.end_task()
    return rec, tid


def test_recorder_prefix_and_commented_rest(tmp_path):
    rec, tid = _partial(tmp_path)
    text = rec.read_transcript(tid)
    assert (
        "\nmol new a.pdb\nmol delrep 0 top\n"
        "# statement 3 of 4 failed (invalid command name \"mol_color\"); "
        "statements 3–4 were not applied:\n"
        "# mol_color x {\n# }\n# puts done \\ \n"
    ) in text
    manifest = rec.read_manifest(tid)
    assert (manifest["failed_count"], manifest["successful_count"], manifest["turn_count"]) == (1, 0, 1)


@requires_tcl()
def test_partial_transcript_parses_in_tclsh(tmp_path):
    rec, tid = _partial(tmp_path)
    transcript = rec.runs_root / tid / "transcript.tcl"
    proc = run_tcl(
        "set CALLS {}\n"
        "proc mol {args} {global CALLS; lappend CALLS $args}\n"
        "proc unknown {args} {error \"unexpected: $args\"}\n"
        "source {%s}\n"
        "puts $CALLS\n" % transcript.as_posix()
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "{new a.pdb} {delrep 0 top}"


def test_failed_without_applied_text_writes_nothing(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("f")
    rec.record_vmd_command("bogus", ok=False)
    rec.record_vmd_command("mol new a.pdb\nbogus", ok=False, applied_text="",
                           failed_index=1, total=2, error="x")
    rec.end_task()
    text = rec.read_transcript(tid)
    assert "bogus" not in text and "mol new a.pdb" not in text
    assert rec.read_manifest(tid)["failed_count"] == 2


def test_loop_maps_statements_to_recorder(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("partial")
    loop._recorder_record(
        tool_name="run_vmd_command",
        tool_input={"command": COMMAND, "rationale": "r"},
        result={"ok": False, "output": "", "error": ERROR, "executed": "yes",
                "statements": {"total": 4, "applied": 2,
                               "failed": {"index": 3, "text": "mol_color x {\n}", "error_info": ERROR}},
                "applied_text": APPLIED},
        duration_ms=5.0,
    )
    text = loop.recorder.read_transcript(tid)
    assert "\nmol delrep 0 top\n# statement 3 of 4 failed" in text
    assert "# mol_color x {" in text
