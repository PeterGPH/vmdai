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
TABLE = ["md-table-%d" % i for i in range(1, 4)]


@pytest.fixture(scope="module")
def results():
    return tcl.run_tcltest(str(TEST_FILE))


def _check(results, cases):
    total = len(SUBSET) + len(LITERAL) + len(TABLE)
    assert results.passed + results.failed == total, results.output
    assert sorted(failed_cases(results) & set(cases)) == [], results.output


def test_subset(results):
    _check(results, SUBSET)


def test_unclosed_markers_literal(results):
    _check(results, LITERAL)


def test_pipe_table_preformatted(results):
    """Live demo: a pipe table is one preformatted block, not one paragraph."""
    _check(results, TABLE)
