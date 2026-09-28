"""toolbar.tcl (P08-T10): icons, title, the ⋯ menu, 600 ms tooltips, busy state."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_toolbar.tcl"
TESTS = [
    "test_menu_items",
    "icons-keys",
    "test_tooltips_600ms",
    "test_disabled_while_busy",
    "title-fit",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL))


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_toolbar_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_menu_items(result):
    assert_tcltests(result, ["test_menu_items", "icons-keys"])


def test_tooltips_600ms(result):
    assert_tcltests(result, ["test_tooltips_600ms"])


def test_disabled_while_busy(result):
    assert_tcltests(result, ["test_disabled_while_busy", "title-fit"])
