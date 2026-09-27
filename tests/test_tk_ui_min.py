"""The M1 ui.tcl fixes under Tk (P06-T10; spec §2h "Stage M1 keeps ui.tcl")."""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers import tk
from helpers.tcl import REPO, TclTestResult, module_result, module_run

TCL_FILE = REPO / "tests" / "tcl" / "test_ui_min.tcl"
TOTAL = 6


@module_run
def _run(tmp_path_factory) -> TclTestResult:
    return tk.run_tk_test(str(TCL_FILE))


@pytest.fixture(scope="module")
def result(request) -> TclTestResult:
    return module_result(request)


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_tk_helper_contract(monkeypatch):
    assert tk.golden_path("x") == REPO / "tests" / "fixtures" / "tk" / "x.txt"
    assert "load " in tk.tk_prelude() and " Tk\n" in tk.tk_prelude()
    assert tk.tk_prelude().endswith("wm withdraw .\n")
    monkeypatch.setenv("CHATVMD_UPDATE_GOLDENS", "1")
    assert tk.update_goldens() is True
    monkeypatch.delenv("CHATVMD_UPDATE_GOLDENS")
    assert tk.update_goldens() is False


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_role_change_closes_block(result):
    _assert_passed(result, ["ui-block-1"])


def test_folder_label_shows_dir(result):
    _assert_passed(result, ["ui-folder-1"])


def test_dropdown_does_not_feed_send_model(result):
    _assert_passed(result, ["ui-dropdown-1"])


def test_notify_one_line(result):
    _assert_passed(result, ["ui-notify-1", "ui-busy-1", "ui-close-1"])
