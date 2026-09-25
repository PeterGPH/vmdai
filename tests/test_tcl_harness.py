"""tests/helpers/tcl.py: interpreter discovery, package paths, skips, tcltest counts."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from helpers import tcl

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "tests" / "tcl" / "test_harness_smoke.tcl"


def _fake_tclsh(directory: Path, patchlevel: str) -> Path:
    """A shell script named tclsh that answers `info patchlevel` with ``patchlevel``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "tclsh"
    path.write_text(f"#!/bin/sh\ncat > /dev/null\necho {patchlevel}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_find_tclsh_prefers_86():
    found = tcl.find_tclsh()
    if found is None:
        pytest.skip(tcl.tcl_skip_reason() or "no tclsh 8.6")
    assert tcl._patchlevel(found).startswith("8.6.")


def test_rejects_85_first_on_path(tmp_path, monkeypatch):
    monkeypatch.delitem(tcl.LIVE_ENV, "VMD_AI_TCLSH", raising=False)
    real = tcl.find_tclsh()
    fake_dir = tmp_path / "old_tcl"
    _fake_tclsh(fake_dir, "8.5.9")

    monkeypatch.setenv("PATH", str(fake_dir) + os.pathsep + os.environ["PATH"])
    assert tcl.find_tclsh() == real

    monkeypatch.setenv("PATH", str(fake_dir))
    assert tcl.find_tclsh() is None
    reason = tcl.tcl_skip_reason()
    assert reason is not None and reason.startswith("no Tcl 8.6 interpreter")
    mark = tcl.requires_tcl().mark
    assert mark.args == (True,) and mark.kwargs["reason"] == reason
    with pytest.raises(pytest.skip.Exception, match="no Tcl 8.6 interpreter"):
        tcl.run_tcl("puts hi")


def test_http_295_loads():
    proc = tcl.run_tcl(
        "puts [package present http]\nputs [info patchlevel]\n", needs_http=True
    )
    assert proc.returncode == 0, proc.stderr
    http_version, patchlevel = proc.stdout.split()
    assert http_version == "2.9.5"
    assert patchlevel.startswith("8.6.")


def test_json_112_loads():
    proc = tcl.run_tcl(
        'puts [package present json]\nputs [json::json2dict {{"a": [1, 2], "b": "x"}}]\n',
        needs_json=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["1.1.2", "a {1 2} b x"]


def test_run_tcltest_counts(tmp_path):
    result = tcl.run_tcltest(str(SMOKE))
    assert (result.passed, result.failed, result.skipped) == (2, 0, 0), result.output

    mixed = tmp_path / "mixed dir" / "t_mixed.tcl"
    mixed.parent.mkdir()
    mixed.write_text(
        "package require tcltest 2\n"
        "namespace import ::tcltest::*\n"
        "test m-1 {passes} -body {expr {1 + 1}} -result 2\n"
        "test m-2 {fails} -body {expr {1 + 1}} -result 3\n"
        "test m-3 {skipped} -constraints noSuchConstraint -body {} -result {}\n"
        "cleanupTests\n"
    )
    result = tcl.run_tcltest(str(mixed))
    assert (result.passed, result.failed, result.skipped) == (1, 1, 1), result.output
    assert "m-2" in result.output

    broken = tmp_path / "t_broken.tcl"
    broken.write_text("error {boom before any test}\n")
    result = tcl.run_tcltest(str(broken))
    assert (result.passed, result.failed) == (0, 1)
    assert "boom before any test" in result.output


def test_skip_reason_text(tmp_path, monkeypatch):
    if tcl.find_tclsh() is None:
        pytest.skip(tcl.tcl_skip_reason() or "no tclsh 8.6")
    monkeypatch.delitem(tcl.LIVE_ENV, "VMD_AI_TCL_TM", raising=False)
    monkeypatch.setattr(tcl, "VMD_TCL_TM_DIR", str(tmp_path / "no_vmd_app"))
    monkeypatch.setattr(tcl, "VMD_JSON_DIR", str(tmp_path / "no_json"))
    monkeypatch.setattr(tcl, "PLUGIN_JSON_DIR", tmp_path / "no_plugin_json")

    assert tcl.tcl_skip_reason() is None
    http_reason = tcl.tcl_skip_reason(needs_http=True)
    assert http_reason is not None and http_reason.startswith("http 2.9.5 not found")
    json_reason = tcl.tcl_skip_reason(needs_json=True)
    assert json_reason is not None and json_reason.startswith("json 1.1.2 not found")
    with pytest.raises(pytest.skip.Exception, match="http 2.9.5 not found"):
        tcl.run_tcl("puts hi", needs_http=True)
    with pytest.raises(pytest.skip.Exception, match="json 1.1.2 not found"):
        tcl.run_tcltest(str(SMOKE), needs_json=True)


def test_no_bare_tclsh_in_tests():
    """C9: every Tcl-running test goes through helpers.tcl, never a bare `tclsh`."""
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""which\(\s*["']tclsh|\[\s*["']tclsh["']""", text):
            offenders.append(path.name)
    assert offenders == []
