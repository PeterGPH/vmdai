"""composer.tcl (P08-T08): input, placeholders, Send/Stop in one cell, the draft."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_composer.tcl"
TESTS = [
    "composer-1",
    "test_grows_1_to_6",
    "test_return_busy_noop",
    "test_draft_survives",
    "test_placeholders",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL))


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_composer_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_composer_1(result):
    assert_tcltests(result, ["composer-1"])


def test_grows_1_to_6(result):
    assert_tcltests(result, ["test_grows_1_to_6"])


def test_return_busy_noop(result):
    assert_tcltests(result, ["test_return_busy_noop"])


def test_draft_survives(result):
    assert_tcltests(result, ["test_draft_survives"])


def test_placeholders(result):
    assert_tcltests(result, ["test_placeholders"])
