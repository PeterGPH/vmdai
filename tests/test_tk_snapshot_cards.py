"""Snapshot cards, the 30-photo cap and the full-size viewer (P08-T07)."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_snapshot_cards.tcl"
TESTS = [
    "tk85-1",
    "thumb_fallback",
    "autocrop-1",
    "scale-fit",
    "not-sent",
    "max-30",
    "card-actions",
    "last-card-visible",
    "stack-narrow",
    "viewer-1",
    # Final-review fix wave (plan 08).
    "percent-path",
    "save-png-fails-softly",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_snapshot_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_tk85_1(result):
    assert_tcltests(result, ["tk85-1", "thumb_fallback"])


def test_max_30_images(result):
    assert_tcltests(result, ["max-30"])


def test_not_sent_to_model_shown(result):
    assert_tcltests(result, ["not-sent"])


def test_autocrop_scale_fit(result):
    assert_tcltests(result, ["autocrop-1", "scale-fit"])


def test_card_actions_layout_and_viewer(result):
    assert_tcltests(result, ["card-actions", "last-card-visible", "stack-narrow", "viewer-1"])


def test_percent_path_and_failed_save_png(result):
    assert_tcltests(result, ["percent-path", "save-png-fails-softly"])
