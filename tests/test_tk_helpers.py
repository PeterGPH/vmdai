"""Regression test for the tclsh-stdin-swallows-stderr defect (P08-T04 follow-up).

Tk on aqua swaps stdout/stderr for console channels when stdin is a
zero-length char device (/dev/null, which pytest's fd capture installs),
which swallows every diagnostic. ``run_tcl``/``run_tcltest`` (tests/helpers/
tcl.py) now pass ``input=""`` so the child gets a real (empty) stdin pipe
instead of inheriting pytest's /dev/null; these tests fail RED (empty
output) without that fix.
"""
from __future__ import annotations

import pytest

from helpers.tcl import run_tcl
from helpers.tk import run_tk_test, tk_prelude, tk_skip_reason

SENTINEL = "chatvmd-stdin-sentinel"


def test_run_tk_test_reports_stderr(tmp_path):
    test_file = tmp_path / "test_stdin_sentinel.tcl"
    test_file.write_text(
        "package require tcltest 2\n"
        f"error {SENTINEL}\n"
        "::tcltest::cleanupTests\n"
    )
    result = run_tk_test(str(test_file))
    assert (result.passed, result.failed) == (0, 1), result.output
    assert SENTINEL in result.output


def test_run_tcl_reports_stderr_with_tk_prelude():
    reason = tk_skip_reason()
    if reason is not None:
        pytest.skip(reason)
    proc = run_tcl(tk_prelude() + f"puts stderr {SENTINEL}; exit 3\n")
    assert proc.returncode == 3
    assert SENTINEL in proc.stderr
