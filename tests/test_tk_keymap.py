"""P09-T03: keyboard and interaction map (Part B V5)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 5


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_keymap.tcl")


def test_esc_stops(results):
    assert_case(results, "keys-esc_stops", TOTAL)


def test_mod_e_toggles(results):
    assert_case(results, "keys-mod_e_toggles", TOTAL)


def test_copy_displaychars(results):
    assert_case(results, "keys-copy_displaychars", TOTAL)


def test_up_down_history(results):
    assert_case(results, "keys-up_down_history", TOTAL)


def test_tab_order(results):
    assert_case(results, "keys-tab_order", TOTAL)
