"""P09-T02: the empty state (Part B V4)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 6


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_empty_state.tcl")


def test_cards_2x2_or_column(results):
    assert_case(results, "empty-cards_2x2_or_column", TOTAL)


def test_card_fills_composer_never_sends(results):
    assert_case(results, "empty-card_fills_composer_never_sends", TOTAL)


def test_ready_group_first_run_servers(results):
    assert_case(results, "empty-ready_group_first_run_servers", TOTAL)


def test_trust_row(results):
    assert_case(results, "empty-trust_row", TOTAL)


def test_hide(results):
    assert_case(results, "empty-hide", TOTAL)


def test_short_height_compacts(results):
    assert_case(results, "empty-short_height_compacts", TOTAL)
