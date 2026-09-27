"""Connection state machine and notices (P06-T06; spec §2d, S3).

Runs tests/tcl/test_state_machine.tcl, which fakes the scheduler, the process
seams and /health so every transition is driven by hand.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_state_machine.tcl"
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


def test_one_notice_per_transition(result):
    _assert_passed(result, ["sm-notice-1", "sm-ok-1", "sm-stop-1"])


def test_backoff_sequence(result):
    _assert_passed(result, ["sm-backoff-1", "sm-backoff-2"])


def test_respawn_cap_3(result):
    _assert_passed(result, ["sm-respawn-1", "sm-respawn-2", "sm-respawn-3", "sm-retry-1", "sm-hung-1"])


def test_new_pid_triggers_recover(result):
    _assert_passed(result, ["sm-newpid-1", "sm-auth-1"])
