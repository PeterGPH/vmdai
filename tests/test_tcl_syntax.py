"""P10-T02: Tcl syntax tokens (pure Tcl) and step-detail colours (Tk)."""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import tcl
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
TOKENS_FILE = REPO / "tests" / "tcl" / "test_syntax.tcl"
TOKENS_TOTAL = 6
DETAIL_TOTAL = 3


@pytest.fixture(scope="module")
def tokens():
    return tcl.run_tcltest(str(TOKENS_FILE))


@pytest.fixture(scope="module")
def detail():
    return run_tk_file("test_syntax_detail.tcl")


def test_tokens_classes(tokens):
    assert (tokens.passed, tokens.failed) == (TOKENS_TOTAL, 0), tokens.output


def test_detail_is_coloured(detail):
    assert_case(detail, "syntax-detail-colours", DETAIL_TOTAL)


def test_syntax_stays_in_the_command(detail):
    assert_case(detail, "syntax-detail-only-command", DETAIL_TOTAL)


def test_dimmed_text_stays_dim(detail):
    assert_case(detail, "syntax-dim-wins", DETAIL_TOTAL)
