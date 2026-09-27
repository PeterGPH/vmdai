"""Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).

The adopted cases come from the native prototype's proto_test (glue-1,
status-1, err-1, out-1, expand-1, fit-1) and the cards prototype's
test_proto (group-1..3), rewritten against the view-model ops."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_tool_rows.tcl"
ADOPTED = ["glue-1", "status-1", "err-1", "out-1", "expand-1", "fit-1", "group-1", "group-2", "group-3"]
TESTS = ADOPTED + [
    "highlight-split",
    "full-output-link",
    "chip-jump",
    "unknown-key",
    "header-footer",
    "expand-all",
    "menus",
    "row-labels",
    "row-click",
    "refit-order",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_tool_rows_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


@pytest.mark.parametrize("name", ADOPTED)
def test_adopted(result, name):
    assert_tcltests(result, [name])


def test_failing_statement_highlight_matches_executor_split(result):
    assert_tcltests(result, ["highlight-split"])


def test_open_full_output_link(result):
    assert_tcltests(result, ["full-output-link"])


def test_chip_click_jumps(result):
    assert_tcltests(result, ["chip-jump"])


def test_unknown_call_key_noop(result):
    assert_tcltests(result, ["unknown-key"])


def test_run_header_footer_expand_and_menus(result):
    assert_tcltests(result, ["header-footer", "expand-all", "menus", "row-labels", "row-click", "refit-order"])
