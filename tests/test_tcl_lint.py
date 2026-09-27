"""Tcl 8.5-safe lint for the plugin (spec §2h) and the vendored json 1.1.2 (§2d)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Pattern, Tuple

from helpers import tcl

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
VENDORED = PLUGIN / "lib" / "json"
VMD_JSON_TCL = Path(tcl.VMD_JSON_DIR) / "json.tcl"

# Command-position words: start of a line, or after `;`, `[` or `{`.
_CMD = r"(?:^|[;\[{])\s*"

BANNED: Dict[str, Pattern[str]] = {
    "try": re.compile(_CMD + r"try\s+\{", re.MULTILINE),
    "lmap": re.compile(_CMD + r"lmap\s", re.MULTILINE),
    "string cat": re.compile(r"\bstring\s+cat\b"),
    "dict map": re.compile(r"\bdict\s+map\b"),
    "tailcall": re.compile(r"\btailcall\b"),
    "coroutine": re.compile(r"\bcoroutine\b"),
    "oo::": re.compile(r"\boo::"),
    "zlib": re.compile(r"\bzlib\b"),
    "binary encode|decode": re.compile(r"\bbinary\s+(?:encode|decode)\b"),
    "lsort -stride": re.compile(r"\blsort\b[^\n]*\s-stride\b"),
    "chan pipe": re.compile(r"\bchan\s+pipe\b"),
}


def _code_lines(text: str) -> str:
    """The file with whole-line comments blanked (line numbers are kept)."""
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def lint_text(text: str) -> List[Tuple[int, str]]:
    """(line number, banned name) for every banned construct in ``text``."""
    code = _code_lines(text)
    hits = []
    for name, pattern in BANNED.items():
        for match in pattern.finditer(code):
            hits.append((code.count("\n", 0, match.start()) + 1, name))
    return sorted(hits)


def plugin_tcl_files() -> List[Path]:
    return sorted(p for p in PLUGIN.rglob("*.tcl") if VENDORED not in p.parents)


def test_lint_patterns_catch_examples():
    bad = {
        "try {set x 1} on error {e} {}": "try",
        "set l [lmap x $xs {incr x}]": "lmap",
        "set s [string cat a b]": "string cat",
        "dict map {k v} $d {set v}": "dict map",
        "proc f {} { tailcall g }": "tailcall",
        "coroutine c body": "coroutine",
        "oo::class create Foo": "oo::",
        "zlib deflate $data": "zlib",
        "binary encode base64 $data": "binary encode|decode",
        "lsort -stride 2 $pairs": "lsort -stride",
        "chan pipe": "chan pipe",
    }
    for text, name in bad.items():
        assert [n for _, n in lint_text(text)] == [name], text
    good = [
        'puts "please try again"',
        "set retry 1",
        "# coroutine and zlib in a comment",
        "    # try { } in an indented comment",
        "lsort -unique $xs",
        "string map {a b} $s",
        "dict for {k v} $d {}",
        "binary format a2 xy",
        "set entry [lindex $row 0]",
    ]
    for text in good:
        assert lint_text(text) == [], text


def test_no_banned_constructs():
    files = plugin_tcl_files()
    assert files, "no plugin Tcl files found"
    assert all("lib" not in p.relative_to(PLUGIN).parts[:1] for p in files)
    problems = []
    for path in files:
        for line, name in lint_text(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(REPO)}:{line}: {name}")
    assert problems == []


def test_vendored_json_loads_exact_112():
    assert (VENDORED / "json.tcl").is_file()
    assert (VENDORED / "pkgIndex.tcl").is_file()
    terms = (VENDORED / "license.terms").read_text(encoding="utf-8")
    assert "tcllib" in terms and "hereby grant permission" in terms
    assert tcl.json_pkg_dir() == str(VENDORED)
    proc = tcl.run_tcl(
        f"lappend auto_path {tcl.tcl_word(str(VENDORED))}\n"
        "puts [package require -exact json 1.1.2]\n"
        "puts [package ifneeded json 1.1.2]\n"
        'set d [json::json2dict {{"t": "\\u00c5\\u2192\\u00b0", "n": [1, 2]}}]\n'
        'puts [list [expr {[dict get $d t] eq "\\u00c5\\u2192\\u00b0"}] [dict get $d n]]\n'
    )
    assert proc.returncode == 0, proc.stderr
    version, ifneeded, decoded = proc.stdout.splitlines()
    assert version == "1.1.2"
    assert str(VENDORED / "json.tcl") in ifneeded
    assert decoded == "1 {1 2}"
    if VMD_JSON_TCL.is_file():
        vendored = hashlib.sha256((VENDORED / "json.tcl").read_bytes()).hexdigest()
        assert vendored == hashlib.sha256(VMD_JSON_TCL.read_bytes()).hexdigest()
