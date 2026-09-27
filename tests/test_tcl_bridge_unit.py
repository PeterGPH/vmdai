"""bridge.tcl: session, poll pump, routing, request state, workdir (P06-T07).

Runs tests/tcl/test_bridge_unit.tcl, which fakes net::call, the runtime state
machine, the executor and the panel, so every reply is scripted.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, module_result, module_run, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_bridge_unit.tcl"
TOTAL = 17


@module_run
def _run(tmp_path_factory) -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


@pytest.fixture(scope="module")
def result(request) -> TclTestResult:
    return module_result(request)


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_session_start_body_has_vmd_env(result):
    _assert_passed(result, ["bridge-start-1"])


def test_undecodable_poll_is_transport_error_after_seq_kept(result):
    _assert_passed(result, ["bridge-poll-bad-1"])


def test_has_more_drains(result):
    _assert_passed(result, ["bridge-poll-more-1"])


def test_tool_start_deferred_while_executing(result):
    _assert_passed(result, ["bridge-defer-1"])


def test_busy_only_after_send_ok(result):
    _assert_passed(result, ["bridge-busy-1", "bridge-busy-2", "bridge-end-1"])


def test_reconcile_idle_when_no_active_request(result):
    _assert_passed(result, ["bridge-reconcile-1", "bridge-reconcile-2"])


def test_apply_workdir_cd_and_set_cwd(result):
    _assert_passed(result, ["bridge-workdir-1"])


def test_session_changes_drop_stale_replies(result):
    _assert_passed(result, ["bridge-race-1", "bridge-resume-1", "bridge-recover-1", "bridge-auth-1"])


def test_recover_resume_retries_lock_then_warns(result):
    _assert_passed(result, ["bridge-recover-2", "bridge-recover-3", "bridge-recover-4"])
