"""P10-T03: the Markdown subset -> spans (pure Tcl, runs in CI)."""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import tcl
from helpers.tk_cases import failed_cases

REPO = Path(__file__).resolve().parents[1]
TEST_FILE = REPO / "tests" / "tcl" / "test_markdown.tcl"
SUBSET = ["md-subset-%d" % i for i in range(1, 6)]
LITERAL = ["md-literal-%d" % i for i in range(1, 5)]


@pytest.fixture(scope="module")
def results():
    return tcl.run_tcltest(str(TEST_FILE))


def _check(results, cases):
    assert results.passed + results.failed == len(SUBSET) + len(LITERAL), results.output
    assert sorted(failed_cases(results) & set(cases)) == [], results.output


def test_subset(results):
    _check(results, SUBSET)


def test_unclosed_markers_literal(results):
    _check(results, LITERAL)
