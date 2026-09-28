"""P09-T06: the History picker (Part B V4)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 4


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_history.tcl")


def test_columns_newest_50(results):
    assert_case(results, "history-columns_newest_50", TOTAL)


def test_format_updated(results):
    assert_case(results, "history-format_updated", TOTAL)


def test_locked_inline(results):
    assert_case(results, "history-locked_inline", TOTAL)


def test_disabled_while_busy(results):
    assert_case(results, "history-disabled_while_busy", TOTAL)
