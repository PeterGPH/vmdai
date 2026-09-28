"""P09-T01: panel.tcl grid assembly (Part B V3, V6) and the component-target guard."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set

import pytest

from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TOTAL = 6
TARGET_FILES = {"panel": "panel.tcl", "settings": "settings.tcl", "history": "history.tcl"}


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_panel.tcl")


def test_grid_rows(results):
    assert_case(results, "panel-grid_rows", TOTAL)


def test_minsize_default_geometry(results):
    assert_case(results, "panel-minsize_default_geometry", TOTAL)


def test_withdraw_keeps_request(results):
    assert_case(results, "panel-withdraw_keeps_request", TOTAL)


def test_width_classes(results):
    assert_case(results, "panel-width_classes", TOTAL)


def test_menu_actions(results):
    assert_case(results, "panel-menu_actions", TOTAL)


def test_start_opens_panel(results):
    assert_case(results, "panel-start_opens_panel", TOTAL)


def _defined(namespace: str) -> Set[str]:
    """Procs and namespace variables that ``namespace``'s file defines."""
    text = (PLUGIN / TARGET_FILES[namespace]).read_text(encoding="utf-8")
    procs = set(re.findall(r"^\s*proc\s+::vmdai::%s::(\w+)" % namespace, text, re.MULTILINE))
    variables = set(re.findall(r"\bvariable\s+(\w+)", text))
    return procs | variables


def test_component_targets_defined():
    """Every ::vmdai::panel|settings|history name a plugin file calls exists.

    Plan 08's toolbar, banner and status bar call these by name; so do this
    plan's own files. A target file that does not exist yet (settings.tcl
    before P09-T04, history.tcl before P09-T06) is skipped.
    """
    missing = []
    for path in sorted(PLUGIN.glob("*.tcl")):
        text = path.read_text(encoding="utf-8")
        for namespace, name in re.findall(r"(?<!\$)::vmdai::(panel|settings|history)::(\w+)", text):
            if not (PLUGIN / TARGET_FILES[namespace]).exists():
                continue
            if name not in _defined(namespace):
                missing.append(f"{path.name}: ::vmdai::{namespace}::{name}")
    assert sorted(set(missing)) == []
