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
from typing import Iterable, List, Tuple

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcl
from helpers.tk import tk_prelude, tk_skip_reason, update_goldens

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


# ---- Tk goldens (P08-T05) ------------------------------------------------------
#
# ::vmdai::transcript::dump writes "images N", then one line per displayed
# text line: "NNN <style tags> | <text>", tabs shown as ⇥, per-item tags
# (anything with ":") left out, embedded windows as <card> or <rule>.

# The element kinds a style tag marks. S2: a displayed line holds one kind.
GLUE_KINDS = {
    "header": {"role", "runhdr"},
    "prose": {"prose", "user"},
    "reasoning": {"think", "thinkbody"},
    "row": {"row", "errline", "preview", "detail"},
    "note": {"note", "footer"},
    "card": {"ecard", "thumb"},
    "rule": {"rule"},
}

_DUMP_LINE = re.compile(r"(\d{3,}) ([^|]*)\| (.*)")

REPLAY_TK = r"""
wm withdraw .
source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . $env(CHATVMD_GEOMETRY)
::vmdai::transcript::create .tx
pack .tx -fill both -expand 1
update
::vmdai::vm::init S
set in [open $env(CHATVMD_EVENTS) r]
fconfigure $in -encoding utf-8
while {[gets $in line] >= 0} {
    if {[string trim $line] eq ""} continue
    set line [string map [list @REPO@ $env(VMDAI_REPO)] $line]
    ::vmdai::transcript::apply_ops [::vmdai::vm::apply S [json::json2dict $line]]
}
close $in
update
set out [open $env(CHATVMD_DUMP_OUT) w]
fconfigure $out -encoding utf-8 -translation lf
puts -nonewline $out [::vmdai::transcript::dump]
close $out
if {$::vmdai::transcript::S(errors)} {
    puts stderr "transcript op errors: $::vmdai::transcript::S(last_error)"
    exit 2
}
exit 0
"""


def parse_dump(text: str) -> Tuple[int, List[Tuple[int, List[str], str]]]:
    """(image count, [(line number, style tags, text)]) from a transcript dump."""
    lines = text.splitlines()
    head = re.fullmatch(r"images (\d+)", lines[0])
    assert head, f"bad dump header {lines[0]!r}"
    rows = []
    for line in lines[1:]:
        m = _DUMP_LINE.fullmatch(line)
        assert m, f"bad dump line {line!r}"
        rows.append((int(m.group(1)), m.group(2).split(), m.group(3)))
    return int(head.group(1)), rows


def check_no_glue(text: str) -> None:
    """S2: prose, reasoning, notes, cards and tool rows never share a line."""
    _images, rows = parse_dump(text)
    for number, tags, body in rows:
        kinds = sorted(k for k, names in GLUE_KINDS.items() if names & set(tags))
        assert len(kinds) <= 1, f"line {number} mixes {kinds}: {body!r}"


def replay_tk(name: str, tmp_path: Path, geometry: str = "560x780") -> str:
    """Replay tests/fixtures/events/<name>.jsonl through the view-model into a
    withdrawn transcript and return its dump. Skips without Tk."""
    reason = tk_skip_reason()
    if reason:
        pytest.skip(reason)
    out = tmp_path / f"{name}.dump"
    proc = run_tcl(
        tk_prelude() + REPLAY_TK,
        needs_json=True,
        env={
            "TZ": "UTC",
            "VMDAI_REPO": str(REPO),
            "CHATVMD_EVENTS": str(EVENTS_DIR / f"{name}.jsonl"),
            "CHATVMD_DUMP_OUT": str(out),
            "CHATVMD_GEOMETRY": geometry,
        },
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text(encoding="utf-8")
