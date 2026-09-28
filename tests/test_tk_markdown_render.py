"""P10-T04: Markdown rendered on seal (Part B V4 Markdown; V8 md-1, md-2, inline code)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 11


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_markdown_render.tcl")


def test_md_1(results):
    assert_case(results, "md-1", TOTAL)


def test_md_2(results):
    assert_case(results, "md-2", TOTAL)


def test_inline_code_never_wraps(results):
    assert_case(results, "md-inline-nowrap", TOTAL)


def test_code_block_copy_header(results):
    assert_case(results, "md-codehdr", TOTAL)


def test_render_keeps_basetags(results):
    assert_case(results, "md-basetags", TOTAL)


def test_render_through_proxy(results):
    assert_case(results, "md-proxy", TOTAL)


def test_only_sealed_blocks_rendered(results):
    assert_case(results, "md-seal", TOTAL)


def test_copy_gives_plain_spaces(results):
    assert_case(results, "md-copy-plain", TOTAL)


def test_code_block_lines_tight(results):
    assert_case(results, "md-pre-spacing", TOTAL)


def test_inline_code_tint_hugs_line(results):
    assert_case(results, "md-icode-tint", TOTAL)


def test_pipe_table_as_code_block(results):
    """Live demo: a pipe table shows its lines in the code style (no renderer)."""
    assert_case(results, "md-table", TOTAL)
