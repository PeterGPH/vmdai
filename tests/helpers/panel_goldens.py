"""Helpers for the M2 panel tests (plan 08): tcltest pass lines, op goldens.

* ``assert_tcltests(result, names)``: every named tcltest passed.
  The Tcl files run with ``-verbose {pass body error}``, so each pass is a
  ``++++ <name> PASSED`` line in ``result.output``.
* ``parse_op_line`` reads one line of ``tests/fixtures/ops/<name>.ops``
  (written by ``::vmdai::vm::format_op``: bare words and double-quoted words
  with the escapes \\\\ \\" \\n \\r \\t).
* ``compare_golden(actual, path)`` rewrites the golden only when
  CHATVMD_UPDATE_GOLDENS=1 and otherwise fails with a unified diff.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Iterable, List

from helpers.tcl import REPO, TclTestResult
from helpers.tk import update_goldens

EVENTS_DIR = REPO / "tests" / "fixtures" / "events"
OPS_DIR = REPO / "tests" / "fixtures" / "ops"

_WORD = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t"}


def tcltest_passed(result: TclTestResult, name: str) -> bool:
    pattern = rf"^\+\+\+\+ {re.escape(name)} PASSED$"
    return re.search(pattern, result.output, re.MULTILINE) is not None


def assert_tcltests(result: TclTestResult, names: Iterable[str]) -> None:
    missing = [n for n in names if not tcltest_passed(result, n)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def parse_op_line(line: str) -> List[str]:
    words = []
    for m in _WORD.finditer(line):
        if m.group(1) is not None:
            words.append(re.sub(r"\\(.)", lambda k: _ESCAPES.get(k.group(1), k.group(1)), m.group(1)))
        else:
            words.append(m.group(2))
    return words


def parse_ops(text: str) -> List[List[str]]:
    return [parse_op_line(line) for line in text.splitlines() if line.strip()]


def compare_golden(actual: str, path: Path) -> None:
    if update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"missing golden {path}; run with CHATVMD_UPDATE_GOLDENS=1"
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(True), actual.splitlines(True), str(path), "actual"
            )
        )
        raise AssertionError(f"golden mismatch:\n{diff}")
