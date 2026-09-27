"""transcript.tcl core (P08-T05): read-only proxy, blocks, reasoning, notes,
error cards, sticky autoscroll, and the S2 Tk goldens."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests, check_no_glue, compare_golden, replay_tk
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import golden_path, run_tk_test

TCL = REPO / "tests" / "tcl" / "test_transcript.tcl"
TESTS = [
    "ro-1",
    "blocks-seal",
    "blocks-discard",
    "unknown-op",
    "reasoning-1",
    "notice-1",
    "error-card-1",
    "sticky-autoscroll",
    "non-bmp",
    "clear-1",
    "menu-prose",
    "wheel-embeds",
    "relayout-widths",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_transcript_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_ro_1(result):
    assert_tcltests(result, ["ro-1"])


def test_blocks_seal_and_discard(result):
    assert_tcltests(result, ["blocks-seal", "blocks-discard", "unknown-op"])


def test_reasoning(result):
    assert_tcltests(result, ["reasoning-1"])


def test_notes_and_error_cards(result):
    assert_tcltests(result, ["notice-1", "error-card-1"])


def test_sticky_autoscroll(result):
    assert_tcltests(result, ["sticky-autoscroll"])


def test_non_bmp(result):
    assert_tcltests(result, ["non-bmp"])


def test_clear_and_menu(result):
    assert_tcltests(result, ["clear-1", "menu-prose", "wheel-embeds", "relayout-widths"])


def check_golden(name, tmp_path):
    text = replay_tk(name, tmp_path)
    check_no_glue(text)
    compare_golden(text, golden_path(name))


def test_golden_03_conversation(tmp_path):
    check_golden("03_conversation", tmp_path)


def test_golden_reasoning_answer(tmp_path):
    check_golden("reasoning_answer", tmp_path)
