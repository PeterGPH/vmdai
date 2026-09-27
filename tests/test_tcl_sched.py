"""sched.tcl registry and config.tcl (P06-T02; spec §2d, S4). Runs tests/tcl/test_sched.tcl."""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_sched.tcl"
TOTAL = 12


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_teardown_empties_after_info(result):
    _assert_passed(result, ["sched-teardown-1", "sched-teardown-2"])


def test_resource_no_orphans(result):
    _assert_passed(result, ["sched-fire-1", "sched-cancel-1", "sched-throw-1",
                            "sched-closing-1", "sched-fileevent-1"])


def test_resolve_python_order(result):
    _assert_passed(result, ["config-python-1", "config-python-2"])


def test_attach_target_parse(result):
    _assert_passed(result, ["config-attach-1", "config-attach-2"])


def test_plugin_json_round_trip(result):
    _assert_passed(result, ["config-json-1"])
