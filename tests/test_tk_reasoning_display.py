"""P09-T08: reasoning display (Part B V4) and the Settings toggle."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 4


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_reasoning_display.tcl")


def test_thinking_timer(results):
    assert_case(results, "reasoning-thinking_timer", TOTAL)


def test_thought_for_expand(results):
    assert_case(results, "reasoning-thought_for_expand", TOTAL)


def test_hidden_when_off(results):
    assert_case(results, "reasoning-hidden_when_off", TOTAL)


def test_setting_saved(results):
    assert_case(results, "reasoning-setting_saved", TOTAL)
