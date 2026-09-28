"""P10-T01: dark tokens and appearance events (Part B V2, V7)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 8


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_dark.tcl")


def test_theme_1(results):
    assert_case(results, "theme-1", TOTAL)


def test_appearance_event_repaints_dialogs(results):
    assert_case(results, "dark-events_repaint_dialogs", TOTAL)


def test_no_macwindowstyle(results):
    assert_case(results, "dark-no_macwindowstyle", TOTAL)


def test_forced_appearance_sets_window_style(results):
    assert_case(results, "dark-forced_sets_window_appearance", TOTAL)


def test_dialog_opened_later_is_dark(results):
    assert_case(results, "dark-dialog_opened_later", TOTAL)


def test_save_applies_appearance(results):
    assert_case(results, "dark-save_applies", TOTAL)


def test_every_m2_token_has_a_dark_value(results):
    assert_case(results, "dark-every_m2_token", TOTAL)


def test_other_windows_untouched(results):
    assert_case(results, "dark-other_windows_untouched", TOTAL)
