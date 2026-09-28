"""theme.tcl (P08-T04): named fonts, light tokens, paint registry, ChatVMD.* styles."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, module_result, module_run
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_theme.tcl"
TESTS = [
    "test_fonts_defined",
    "test_mono_family_fallback",
    "test_tokens",
    "test_repaint_registry",
    "test_only_chatvmd_styles",
    "fit_helpers",
    "fit_middle_binary",
]


@module_run
def _run(tmp_path_factory):
    return run_tk_test(str(TCL))


@pytest.fixture(scope="module")
def result(request):
    return module_result(request)


def test_theme_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_fonts_defined(result):
    assert_tcltests(result, ["test_fonts_defined"])


def test_mono_family_fallback(result):
    assert_tcltests(result, ["test_mono_family_fallback"])


def test_repaint_registry(result):
    assert_tcltests(result, ["test_repaint_registry", "test_tokens"])


def test_only_chatvmd_styles(result):
    assert_tcltests(result, ["test_only_chatvmd_styles"])


def test_fit_helpers(result):
    assert_tcltests(result, ["fit_helpers"])


def test_fit_middle_binary_search(result):
    assert_tcltests(result, ["fit_middle_binary"])
