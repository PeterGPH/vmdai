"""tclexport.tcl (P08-T11): the Copy/Save .tcl ledger. No Tk, so it runs in CI."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run, run_tcltest

TCL = REPO / "tests" / "tcl" / "test_tclexport.tcl"
TESTS = ["test_applied_kept_rest_commented", "test_run_and_chat_tcl"]


@module_run
def _run(tmp_path_factory):
    return run_tcltest(str(TCL))


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_tclexport_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_applied_kept_rest_commented(result):
    assert_tcltests(result, ["test_applied_kept_rest_commented"])


def test_run_and_chat_tcl(result):
    assert_tcltests(result, ["test_run_and_chat_tcl"])
