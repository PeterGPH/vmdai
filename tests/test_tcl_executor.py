"""executor.tcl: approve, ack, pre-check, puts capture, post (P06-T08; C2, C3, C5, S10).

Runs tests/tcl/test_executor.tcl with VMD's mol, display and render stubbed.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_executor.tcl"
TOTAL = 16


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_puts_captured(result):
    _assert_passed(result, ["exec-puts-1"])


def test_puts_variants(result):
    _assert_passed(result, ["exec-puts-2", "exec-puts-3"])


def test_executing_reset_when_puts_cannot_be_captured(result):
    _assert_passed(result, ["exec-puts-4"])


def test_code_2_is_success(result):
    _assert_passed(result, ["exec-code2-1"])


def test_partial_failed_index_applied_text_error_info(result):
    _assert_passed(result, ["exec-split-1", "exec-partial-1"])


def test_incomplete_tail_runs_nothing(result):
    _assert_passed(result, ["exec-precheck-1"])


def test_1mb_ceiling_truncated(result):
    _assert_passed(result, ["exec-ceiling-1"])


def test_ack_proceed_false_skips(result):
    _assert_passed(result, ["exec-ack-1", "exec-epoch-1"])


def test_duplicate_call_key_skipped(result):
    _assert_passed(result, ["exec-dup-1", "exec-cancel-1"])


def test_approval_ask_posts_no_without_ack(result):
    _assert_passed(result, ["exec-approval-1"])


def test_snapshot_tachyon_to_snapshot_path(result):
    _assert_passed(result, ["exec-snap-1", "exec-snap-2"])
