"""Run one plan-09 Tk tcltest file and report its cases to pytest.

Each tests/test_tk_*.py module runs its tcltest file once (a module-scoped
fixture) and then has one pytest function per tcltest case, so a failure
names the case. The file skips as a whole when Tk is unavailable
(helpers.tk.run_tk_test calls pytest.skip).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Set

from helpers import tcl, tk
from helpers.tcl import TclTestResult

REPO = Path(__file__).resolve().parents[2]
TCL_DIR = REPO / "tests" / "tcl"
_FAILED_RE = re.compile(r"^==== (\S+) .*FAILED\s*$", re.MULTILINE)


def run_tk_file(name: str, env: Optional[Dict[str, str]] = None) -> TclTestResult:
    """Run tests/tcl/<name> under Tk with the harness environment."""
    merged = {"VMDAI_TCL_TM": tcl.http_tm_dir() or ""}
    if env:
        merged.update(env)
    return tk.run_tk_test(str(TCL_DIR / name), env=merged, timeout=120)


def failed_cases(result: TclTestResult) -> Set[str]:
    return set(_FAILED_RE.findall(result.output))


def assert_case(result: TclTestResult, case: str, total: int) -> None:
    """``case`` passed, and all ``total`` cases of the file ran."""
    assert case not in failed_cases(result), result.output
    ran = result.passed + result.failed
    assert ran == total, (
        f"expected {total} tcltest cases, got passed={result.passed} "
        f"failed={result.failed} skipped={result.skipped}\n{result.output}"
    )
