"""statusbar.tcl and banner.tcl (P08-T09): status texts, narrow drops, the
one connection banner and its actions."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_statusbar_banner.tcl"
TESTS = [
    "status_texts",
    "status_clicks",
    "narrow_drop_order",
    "never_tunnel",
    "offline-1",
    "banner_kinds_actions",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL))


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_statusbar_banner_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_status_texts(result):
    assert_tcltests(result, ["status_texts", "status_clicks"])


def test_offline_1(result):
    assert_tcltests(result, ["offline-1"])


def test_narrow_drop_order(result):
    assert_tcltests(result, ["narrow_drop_order"])


def test_never_tunnel(result):
    assert_tcltests(result, ["never_tunnel"])


def test_banner_kinds_actions(result):
    assert_tcltests(result, ["banner_kinds_actions"])
