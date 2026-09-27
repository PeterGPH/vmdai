"""Real-VMD checks (P06-T12; spec §2c Wire encoding, §2d Snapshot, §6 Live tests).

Opt-in: set VMD_AI_VMD_BIN to a VMD binary (read through the live_env
fixture), e.g. /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64. Each test
runs ``vmd -dispdev text -e <script>`` in a temp directory with a temp HOME;
the script writes its findings to $VMDAI_OUT as JSON and quits.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from helpers.fake_rpc_server import FakeRpcServer
from helpers.tcl import REPO, find_tclsh

PLUGIN = REPO / "plugin"
PDB = REPO / "vmdbench" / "fixtures" / "1crn.pdb"
ARROW = "".join(map(chr, (0xC5, 0x2192, 0xB0)))

# Loads the plugin's no-Tk modules and gives the script a JSON writer.
PRELUDE = """
set plugin $env(VMDAI_PLUGIN_DIR)
foreach m {config sched net executor} { source [file join $plugin $m.tcl] }
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
"""


def _vmd(live_env: Dict[str, str]) -> str:
    vmd = live_env.get("VMD_AI_VMD_BIN")
    if not vmd:
        pytest.skip("set VMD_AI_VMD_BIN to run the real-VMD checks")
    return vmd


def _run_vmd(vmd: str, body: str, tmp_path: Path, home: Optional[Path] = None,
             env: Optional[Dict[str, str]] = None, prelude: bool = True) -> Dict[str, Any]:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    out = tmp_path / "out.json"
    script = tmp_path / "check.tcl"
    script.write_text((PRELUDE if prelude else "") + body + "\nquit\n", encoding="utf-8")
    run_env = dict(os.environ, VMDAI_OUT=str(out), VMDAI_PLUGIN_DIR=str(PLUGIN),
                   HOME=str(home or tmp_path / "vmd_home"))
    Path(run_env["HOME"]).mkdir(exist_ok=True)
    run_env.update(env or {})
    proc = subprocess.run([vmd, "-dispdev", "text", "-e", str(script)], cwd=work, env=run_env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          errors="replace", timeout=120)
    assert out.exists(), (proc.stdout + proc.stderr)[-3000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_live_headless_tachyon_render_over_1kb(live_env, tmp_path):
    """§2d Snapshot: the executor's render TachyonInternal writes a real image in real VMD."""
    vmd = _vmd(live_env)
    data = _run_vmd(vmd, f"""
set r [::vmdai::executor::exec_command "mol new {{{PDB}}} waitfor all\\nmol modstyle 0 top NewCartoon\\nputs \\"atoms: \\[molinfo top get numatoms\\]\\""]
set path [file join [pwd] snap.tga]
set s [::vmdai::executor::capture_snapshot {{}} $path]
write_out [list ok b [dict get $r ok] output s [dict get $r output] applied i [dict get $r statements_applied] \\
    snap_ok b [dict get $s ok] snap_error s [dict get $s error] path s $path]
""", tmp_path)
    assert data["ok"] is True and data["applied"] == 3
    assert "atoms: 327" in data["output"]
    assert data["snap_ok"] is True, data["snap_error"]
    tga = Path(data["path"]).read_bytes()
    assert len(tga) > 1024
    width, height = struct.unpack("<HH", tga[12:16])
    assert width > 0 and height > 0


def test_live_unicode_round_trip_inside_vmd(live_env, tmp_path):
    """S8 inside VMD's own Tcl and http: ASCII replies always; raw UTF-8 with http >= 2.9."""
    vmd = _vmd(live_env)

    def echo(method, params, headers):
        return {"result": params}

    with FakeRpcServer(echo) as plain, FakeRpcServer(echo, ensure_ascii=False) as utf8:
        data = _run_vmd(vmd, """
set text [format %c%c%c 0xc5 0x2192 0xb0]
proc got {tag args} { set ::got($tag) $args }
foreach tag {ascii utf8} url [list $env(FAKE_ASCII) $env(FAKE_UTF8)] {
    ::vmdai::net::configure -base_url $url
    ::vmdai::net::call echo [list text s $text] [list got $tag]
    vwait ::got($tag)
}
set a [dict get [lindex $::got(ascii) 1] text]
set u [dict get [lindex $::got(utf8) 1] text]
write_out [list http s [package present http] encoding s [encoding system] \\
    ascii_intact b [expr {$a eq $text}] utf8_intact b [expr {$u eq $text}] \\
    utf8_hex s [binary scan [encoding convertto utf-8 $u] H* hex; set hex]]
""", tmp_path, env={"FAKE_ASCII": plain.base_url, "FAKE_UTF8": utf8.base_url})
        requests = plain.calls("echo") + utf8.calls("echo")
    assert all(r.body.isascii() and r.params["text"] == ARROW for r in requests)
    assert data["ascii_intact"] is True
    major_minor = tuple(int(x) for x in data["http"].split(".")[:2])
    if major_minor >= (2, 9):
        assert data["utf8_intact"] is True, data


def test_live_vmdrc_block_loads_plugin(live_env, tmp_path):
    """The installer's ~/.vmdrc block loads vmd_ai 2.0 when VMD starts (no Tk needed)."""
    vmd = _vmd(live_env)
    home = tmp_path / "vmd_home"
    home.mkdir()
    tclsh = find_tclsh()
    if tclsh is None:
        pytest.skip("no Tcl 8.6 tclsh to run the installer")
    subprocess.run([tclsh, str(REPO / "scripts" / "install_plugin.tcl"), "--vmdrc",
                    str(home / ".vmdrc"), "--yes"], check=True, capture_output=True)
    data = _run_vmd(vmd, """
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
write_out [list vmd_ai s [package present vmd_ai] start s [info commands ::vmdai::start] \\
    state s [::vmdai::runtime::state] leftover b [info exists vmdai_err]]
""", tmp_path, home=home, prelude=False)
    assert data == {"vmd_ai": "2.0", "start": "::vmdai::start", "state": "stopped",
                    "leftover": False}
