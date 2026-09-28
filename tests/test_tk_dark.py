"""P10-T01: dark tokens and appearance events (Part B V2, V7)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 10
# dark-events_repaint_dialogs and dark-forced_sets_window_appearance carry
# -constraints aquaWs, so on a non-aqua Tk both are skipped, not run.
AQUA_ONLY = 2


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_dark.tcl")


def _case(results, case, aqua_only=False):
    assert results.skipped in (0, AQUA_ONLY), results.output
    if aqua_only and results.skipped:
        pytest.skip("aqua-only tcltest case (constraint aquaWs)")
    else:
        assert_case(results, case, TOTAL - results.skipped)


def test_theme_1(results):
    _case(results, "theme-1")


def test_appearance_event_repaints_dialogs(results):
    _case(results, "dark-events_repaint_dialogs", aqua_only=True)


def test_no_macwindowstyle(results):
    _case(results, "dark-no_macwindowstyle")


def test_forced_appearance_sets_window_style(results):
    _case(results, "dark-forced_sets_window_appearance", aqua_only=True)


def test_dialog_opened_later_is_dark(results):
    _case(results, "dark-dialog_opened_later")


def test_save_applies_appearance(results):
    _case(results, "dark-save_applies")


def test_every_m2_token_has_a_dark_value(results):
    _case(results, "dark-every_m2_token")


def test_other_windows_untouched(results):
    _case(results, "dark-other_windows_untouched")


def test_empty_card_hover_follows_theme(results):
    _case(results, "dark-empty_card_hover")


def test_no_isdark_offers_light_dark(results):
    _case(results, "dark-no_isdark")
