"""pkgIndex, entry points, menu, reload (S4) and the ~/.vmdrc installer (P06-T09)."""
from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer
from helpers.tcl import REPO, TclTestResult, find_tclsh, run_tcl, run_tcltest, tcl_skip_reason, tcl_word
from vmd_ai_runtime.launch import write_token_file

TCL_FILE = REPO / "tests" / "tcl" / "test_init.tcl"
INSTALLER = REPO / "scripts" / "install_plugin.tcl"
PLUGIN = REPO / "plugin"
TOTAL = 5
TOKEN = "fedcba9876543210fedcba9876543210"
BEGIN = "# >>> vmdai >>>"
END = "# <<< vmdai <<<"


def _handler():
    numbers = itertools.count(1)

    def handler(method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
        if method == "session.start":
            n = next(numbers)
            return {"result": {"session_id": f"sess_{n}", "session_token": f"tok_{n}",
                               "chat_id": None, "event_protocol": 1}}
        if method == "chat.events.poll":
            return {"result": {"events": [], "last_seq": 0, "has_more": False}}
        return {"result": {"ok": True}}

    return handler


@pytest.fixture(scope="module")
def init_run(tmp_path_factory) -> TclTestResult:
    home = tmp_path_factory.mktemp("init") / "home"
    home.mkdir()
    with FakeRpcServer(_handler()) as fake:
        write_token_file(fake.port, 4242, TOKEN, 2, home=str(home))
        return run_tcltest(str(TCL_FILE), env={"HOME": str(home),
                                               "VMDAI_ATTACH_PORT": str(fake.port)})


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(init_run):
    assert (init_run.passed, init_run.failed) == (TOTAL, 0), init_run.output


def test_package_provide_2_0(init_run):
    _assert_passed(init_run, ["init-pkg-1", "init-start-1"])


def test_menu_path_vmd_ai(init_run):
    _assert_passed(init_run, ["init-menu-1"])


def test_reload_twice_after_info_empty(init_run):
    _assert_passed(init_run, ["init-reload-1", "init-stop-1"])


# --- installer ------------------------------------------------------------------

def _install(vmdrc: Path, *args: str, answer: str = "") -> subprocess.CompletedProcess:
    reason = tcl_skip_reason()
    if reason:
        pytest.skip(reason)
    return subprocess.run([find_tclsh(), str(INSTALLER), "--vmdrc", str(vmdrc), *args],
                          input=answer, capture_output=True, text=True, timeout=30)


def test_installer_idempotent(tmp_path):
    vmdrc = tmp_path / "home dir" / ".vmdrc"
    vmdrc.parent.mkdir()
    original = "# my VMD settings\ncolor Display Background white\n"
    vmdrc.write_text(original, encoding="utf-8")

    first = _install(vmdrc, "--yes")
    assert first.returncode == 0, first.stderr
    installed = vmdrc.read_text(encoding="utf-8")
    assert installed.startswith(original + "\n" + BEGIN + "\n")
    assert installed.endswith(END + "\n")
    assert installed.count(BEGIN) == 1
    assert f"lappend auto_path {tcl_word(str(PLUGIN))}; package require vmd_ai 2.0" in installed
    assert "play [file join $env(VMDDIR) .vmdrc]" not in installed  # the user's file stays in charge
    assert (tmp_path / "home dir" / ".vmdrc.vmdai-backup").read_text(encoding="utf-8") == original

    again = _install(vmdrc, "--yes")
    assert again.returncode == 0 and "already installed" in again.stdout
    assert vmdrc.read_text(encoding="utf-8") == installed

    # An older block (another plugin path) is replaced in place.
    moved = installed.replace(tcl_word(str(PLUGIN)), "/old/place/plugin")
    vmdrc.write_text(moved, encoding="utf-8")
    assert _install(vmdrc, "--yes").returncode == 0
    assert vmdrc.read_text(encoding="utf-8") == installed

    removed = _install(vmdrc, "--uninstall", "--yes")
    assert removed.returncode == 0, removed.stderr
    assert vmdrc.read_text(encoding="utf-8") == original


def test_installer_new_file_keeps_vmd_defaults_and_uninstall_deletes(tmp_path):
    vmdrc = tmp_path / ".vmdrc"
    assert _install(vmdrc, "--yes").returncode == 0
    text = vmdrc.read_text(encoding="utf-8")
    assert text.startswith(BEGIN + "\n") and "play [file join $env(VMDDIR) .vmdrc]" in text
    assert not (tmp_path / ".vmdrc.vmdai-backup").exists()
    assert _install(vmdrc, "--yes").returncode == 0
    assert vmdrc.read_text(encoding="utf-8") == text
    assert _install(vmdrc, "--uninstall", "--yes").returncode == 0
    assert not vmdrc.exists()


def test_installer_asks_first(tmp_path):
    vmdrc = tmp_path / ".vmdrc"
    vmdrc.write_text("menu main on\n", encoding="utf-8")
    declined = _install(vmdrc, answer="n\n")
    assert declined.returncode == 1 and "Nothing changed." in declined.stdout
    assert BEGIN in declined.stdout  # the block was shown before asking
    assert vmdrc.read_text(encoding="utf-8") == "menu main on\n"
    dry = _install(vmdrc, "--dry-run")
    assert dry.returncode == 0 and vmdrc.read_text(encoding="utf-8") == "menu main on\n"
    accepted = _install(vmdrc, answer="y\n")
    assert accepted.returncode == 0 and BEGIN in vmdrc.read_text(encoding="utf-8")


def test_vmdrc_block_loads_the_plugin(tmp_path):
    """Played by VMD at start: the block puts plugin/ on auto_path and loads vmd_ai 2.0."""
    vmdrc = tmp_path / ".vmdrc"
    assert _install(vmdrc, "--yes").returncode == 0
    proc = run_tcl(
        "set ::played {}\n"
        "proc play {path} { lappend ::played [file tail $path] }\n"
        "set ::menu {}\n"
        "proc vmd_install_extension {args} { lappend ::menu $args }\n"
        "set env(VMDDIR) [file join $env(HOME) vmddir]\n"
        "file mkdir $env(VMDDIR)\n"
        "close [open [file join $env(VMDDIR) .vmdrc] w]\n"
        f"source {tcl_word(str(vmdrc))}\n"
        "puts [list [package present vmd_ai] $::menu $::played [info exists vmdai_err]]\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "2.0 {{vmd_ai ::vmdai::start {VMD AI}}} .vmdrc 0"
