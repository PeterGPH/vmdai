"""spec 2d Snapshot, 2c Thumbnails, S10, S11: runtime-owned snapshot files."""
from __future__ import annotations

import base64
import os
import tempfile
import uuid
from pathlib import Path

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session, write_tga
from helpers.runtime_fixture import make_app, start_token_session
from helpers.tcl import requires_tcl, run_tcl
from vmd_ai_runtime import app as app_module
from vmd_ai_runtime import tool_bridge as tb
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.recorder import RunRecorder

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
TOKEN = "0123456789abcdef0123456789abcdef"


def _snapshot_call(bridge, tool_input=None, call_key="k5a5a5a5a5a5"):
    call = BridgeCall(bridge, tool_name="capture_vmd_snapshot",
                      tool_input=tool_input if tool_input is not None else {"purpose": "check"},
                      call_key=call_key)
    meta = call.tool_start()["metadata"]
    bridge.ack(SESSION_ID, call_key)
    return call, meta["snapshot_path"]


def _post(bridge, call_key, snapshot_file, ok=True):
    return bridge.post_result(SESSION_ID, {"call_key": call_key, "ok": ok, "output": "rendered",
                                           "error": "", "snapshot_file": snapshot_file})


def test_snapshot_path_is_chosen_by_runtime(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=0.1)
    call, snap = _snapshot_call(bridge)
    assert snap == str(session.snapshot_dir / "vmdai_snap_k5a5a5a5a5a5.tga")
    call.cancel.set()
    call.join()


def test_foreign_snapshot_file_rejected_not_deleted(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call, snap = _snapshot_call(bridge)
    foreign = write_tga(tmp_path / "precious.tga")
    _post(bridge, call.call_key, str(foreign))
    result = call.join()
    assert result["ok"] is False
    assert result["error"] == "snapshot file rejected: not the path the runtime chose"
    assert foreign.exists(), "the runtime must never delete a path it did not choose"
    assert "image_b64" not in result


def test_tokenless_tmp_path_accepted_after_realpath(tmp_path):
    bridge = make_bridge(make_session(tmp_path, authenticated=False))
    # Unique per run (I2): a fixed id would collide with another suite
    # writing/reading/deleting the same /tmp path on the same host.
    tcid = "tc_snap_" + uuid.uuid4().hex[:8]
    legacy = Path("/tmp/vmdai_snap_%s.tga" % tcid)
    write_tga(legacy)
    try:
        call = BridgeCall(bridge, tool_name="capture_vmd_snapshot", tool_input={"purpose": "x"},
                          tool_call_id=tcid, timeout=3)
        call.tool_start()
        bridge.resolve(tcid, {"ok": True, "output": "ok", "error": "",
                              "snapshot_file": os.path.realpath(str(legacy))})
        result = call.join()
        assert result["ok"] is True and result["image_mime"] == "image/png"
        assert not legacy.exists()
    finally:
        if legacy.exists():
            legacy.unlink()

    tcid2 = "tc_snap_" + uuid.uuid4().hex[:8]
    fd, other = tempfile.mkstemp(suffix=".tga")
    os.close(fd)
    write_tga(Path(other))
    try:
        call = BridgeCall(bridge, tool_name="capture_vmd_snapshot", tool_input={"purpose": "x"},
                          tool_call_id=tcid2, timeout=3)
        call.tool_start()
        bridge.resolve(tcid2, {"ok": True, "output": "ok", "error": "", "snapshot_file": other})
        result = call.join()
        assert result["ok"] is False and "rejected" in result["error"]
        assert os.path.exists(other)
    finally:
        os.unlink(other)


def test_legacy_id_with_path_characters_rejected():
    assert tb._legacy_snapshot_allowed("/tmp/x.tga", "../../x") is False
    assert tb._legacy_snapshot_allowed("/tmp/vmdai_snap_ok_1.tga", "ok_1") is True
    assert tb._legacy_snapshot_allowed("/tmp/vmdai_snap_functions.run:0.tga", "functions.run:0") is True


def test_image_and_thumb_written(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge)
    write_tga(Path(snap), 640, 480)
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is True, result
    images = session.chat_dir / "images"
    full = images / "k5a5a5a5a5a5.png"
    thumb = images / "k5a5a5a5a5a5_thumb.png"
    assert full.read_bytes().startswith(PNG_MAGIC)
    assert thumb.read_bytes().startswith(PNG_MAGIC)
    img = result["image"]
    assert img["path"] == str(full) and img["thumb_path"] == str(thumb)
    assert (img["width"], img["height"], img["src_width"], img["src_height"]) == (640, 480, 640, 480)
    assert img["renderer"] == "TachyonInternal"
    assert result["image_b64"] and result["image_mime"] == "image/png"
    assert result["output"] == "Snapshot rendered (640×480)."
    assert not Path(snap).exists(), "the temp TGA is deleted"


def test_save_path_relative_to_session_cwd(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"purpose": "figure", "save_path": "fig1.png"})
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    target = Path(session.cwd) / "fig1.png"
    assert result["ok"] is True
    assert target.read_bytes().startswith(PNG_MAGIC)
    assert result["saved_path"] == str(target)
    assert result["output"].endswith("Saved to %s." % target)


def test_save_path_jpg_without_pillow_png_note(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "to_jpeg", lambda png, quality=90: None)
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"save_path": "fig.jpg"})
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    png_target = Path(session.cwd) / "fig.png"
    assert result["ok"] is True
    assert result["saved_path"] == str(png_target)
    assert png_target.read_bytes().startswith(PNG_MAGIC)
    assert not (Path(session.cwd) / "fig.jpg").exists()
    assert "JPEG needs Pillow; saved as PNG instead." in result["output"]


def test_save_path_bad_dir(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"save_path": "missing_dir/fig.png"}, call_key="k5a5a5a5a5b1")
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is False
    assert result["error"].startswith("save_path directory does not exist: ")
    assert result["image_b64"], "the render itself still reaches the model"
    assert not (Path(session.cwd) / "missing_dir").exists()

    call2, snap2 = _snapshot_call(bridge, {"save_path": "../escape.png"}, call_key="k5a5a5a5a5b2")
    write_tga(Path(snap2))
    _post(bridge, call2.call_key, snap2)
    result2 = call2.join()
    assert result2["ok"] is False
    assert result2["error"] == "save_path must not contain '..': ../escape.png"
    assert not (tmp_path / "escape.png").exists()


def test_recorder_logs_render_tachyon_for_save_path(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("figure")
    rec.record_snapshot(ok=True, purpose="fig", image_bytes=PNG_MAGIC,
                        renderer="TachyonInternal", saved_path="/work/fig 1.png")
    rec.record_snapshot(ok=True, purpose="plain", image_bytes=PNG_MAGIC)
    rec.end_task()
    text = rec.read_transcript(tid)
    assert "render TachyonInternal snapshots/turn_001.png" in text
    assert "render TachyonInternal {/work/fig 1.png}" in text
    assert "# save_path : /work/fig 1.png" in text
    assert "render snapshot snapshots/turn_002.png" in text


def test_loop_records_snapshot_with_renderer(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("fig")
    png = PNG_MAGIC + b"\0" * 16
    loop._recorder_record(
        tool_name="capture_vmd_snapshot",
        tool_input={"purpose": "fig", "save_path": "fig1.png"},
        result={"ok": True, "output": "", "error": "",
                "image_b64": base64.b64encode(png).decode("ascii"), "image_mime": "image/png",
                "image": {"renderer": "TachyonInternal"}, "saved_path": "/w/fig1.png"},
        duration_ms=3.0,
    )
    text = loop.recorder.read_transcript(tid)
    assert "render TachyonInternal snapshots/turn_001.png" in text
    assert "render TachyonInternal {/w/fig1.png}" in text


def test_session_stop_removes_snapshot_dir(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    snap_dir = app._snapshot_dir_for(sess["session_id"])
    assert snap_dir.is_dir()
    resp = app.handle_rpc({"jsonrpc": "2.0", "id": "s", "method": "session.stop",
                           "params": {"session_id": sess["session_id"]}},
                          session_token=sess["session_token"])
    assert resp["result"]["ok"] is True
    assert not snap_dir.exists()


# ----------------------------------------------------------------------
# Final-review fix wave: M1 (save_path protection), M3 (guarded disk
# writes), T03 (ok before the foreign-path check), M2 (exit sweep), M8
# (recorder quoting for a save_path with a brace in it).
# ----------------------------------------------------------------------

def test_save_path_protected_refused(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    home = Path(os.path.expanduser("~"))

    dest = home / ".vmdrc"
    call, snap = _snapshot_call(bridge, {"save_path": "~/.vmdrc"}, call_key="k5a5a5a5a5c1")
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is False
    assert result["error"] == "save_path is a protected location: %s" % dest
    assert not dest.exists()

    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    target = ssh_dir / "authorized_keys"
    link = Path(session.cwd) / "link.png"
    link.symlink_to(target)

    call2, snap2 = _snapshot_call(bridge, {"save_path": "link.png"}, call_key="k5a5a5a5a5c2")
    write_tga(Path(snap2))
    _post(bridge, call2.call_key, snap2)
    result2 = call2.join()
    assert result2["ok"] is False
    assert result2["error"] == "save_path is a protected location: %s" % link
    assert not target.exists()


def test_save_path_existing_non_image_refused(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    work = Path(session.cwd)

    pdb = work / "structure.pdb"
    pdb.write_bytes(b"HEADER    some pdb content\n")
    original = pdb.read_bytes()
    call, snap = _snapshot_call(bridge, {"save_path": "structure.pdb"}, call_key="k5a5a5a5a5d1")
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is False
    assert result["error"] == "save_path would overwrite a file that is not an image: %s" % pdb
    assert pdb.read_bytes() == original

    fig = work / "fig.png"
    fig.write_bytes(b"stale png bytes")
    call2, snap2 = _snapshot_call(bridge, {"save_path": "fig.png"}, call_key="k5a5a5a5a5d2")
    write_tga(Path(snap2))
    _post(bridge, call2.call_key, snap2)
    result2 = call2.join()
    assert result2["ok"] is True
    assert fig.read_bytes().startswith(PNG_MAGIC)


def test_snapshot_image_write_failure_keeps_image_b64(tmp_path):
    session = make_session(tmp_path)
    (session.chat_dir / "images").write_text("not a directory")
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, call_key="k5a5a5a5a5e1")
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is True
    assert result["image_b64"]
    assert result["image"]["path"] is None
    assert result["image"]["thumb_path"] is None
    assert not Path(snap).exists(), "the temp TGA is still deleted"


def test_failed_render_keeps_its_error_with_foreign_path(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, call_key="k5a5a5a5a5f1")
    foreign = write_tga(tmp_path / "foreign.tga")
    bridge.post_result(SESSION_ID, {
        "call_key": call.call_key, "ok": False, "output": "", "error": "render failed: disk",
        "snapshot_file": str(foreign),
    })
    result = call.join()
    assert result["error"] == "render failed: disk"
    assert foreign.exists()


@requires_tcl()
def test_save_path_with_braces_replays_in_tclsh(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("odd")
    rec.record_snapshot(ok=True, purpose="odd", image_bytes=PNG_MAGIC,
                        renderer="TachyonInternal", saved_path="/w/odd}name {x.png")
    rec.end_task()
    transcript = rec.runs_root / tid / "transcript.tcl"
    proc = run_tcl(
        "set CALLS {}\n"
        "proc render {args} {global CALLS; lappend CALLS $args}\n"
        "proc unknown {args} {error \"unexpected: $args\"}\n"
        "source {%s}\n"
        "puts [lindex $CALLS 1 1]\n" % transcript.as_posix()
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "/w/odd}name {x.png"


def test_snapshot_dirs_swept_at_exit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module.atexit, "register",
                        lambda fn, *args: calls.append((fn, args)))
    app = make_app(tmp_path)
    snap_dir = app._snapshot_dir_for("sess_x")
    assert snap_dir.is_dir()
    fn, args = calls[-1]
    assert fn is app_module._remove_snapshot_dirs
    fn(*args)
    assert not snap_dir.exists()
    assert app._snapshot_dirs == {}
