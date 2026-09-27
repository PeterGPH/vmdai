"""Spec 2g prompt lint: every example command line in CHATVMD_SYSTEM_PROMPT
(both variants) starts with words VMD's user guide documents.

Example lines are the prompt lines indented by exactly four spaces. The first
word must be in the guide's Table 9.1 ("Summary of core text commands"), a
core Tcl command, or an object call ($sel ...). For display, mol, molecule,
axes and animate, the second word must also be a documented subcommand (a
"• <word>" bullet in the guide). VMD_SYSTEM_PROMPT is exempt on purpose: its
`display backgroundcolor` line is a frozen, hash-pinned defect. The C1 and C8
lines name words in prose and are not examples, so they are never linted.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import FrozenSet, List, Tuple

import pytest

from vmd_ai_runtime.prompts import chatvmd_system_prompt

UG = Path(__file__).resolve().parents[1] / "docs" / "vmd_user_guide" / "ug.txt"
TCL_CORE = frozenset({
    "set", "puts", "foreach", "for", "while", "if", "expr", "incr", "proc", "return",
    "lappend", "lindex", "llength", "list", "format", "string", "catch",
})
SUBCOMMAND_WORDS = frozenset({"display", "mol", "molecule", "axes", "animate"})


def build_allowlist(text: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    start = text.index("   First Word")
    end = text.index("Table 9.1: Summary")
    first = set()
    for line in text[start:end].splitlines()[1:]:
        column = re.split(r"\s{2,}", line.strip(), maxsplit=1)[0]
        for word in re.split(r",\s*|\s+or\s+", column):
            if re.fullmatch(r"[a-z][a-z0-9_]*", word):
                first.add(word)
    subcommands = set(re.findall(r"•\s+([A-Za-z][A-Za-z0-9_]*)", text))
    return frozenset(first), frozenset(subcommands)


def example_lines(prompt: str) -> List[str]:
    return [line[4:] for line in prompt.splitlines()
            if line.startswith("    ") and not line.startswith("     ")]


def violations(prompt: str, first: FrozenSet[str], subcommands: FrozenSet[str]) -> List[str]:
    bad: List[str] = []
    for line in example_lines(prompt):
        code = line.split(";#", 1)[0].strip()
        if not code:
            continue
        words = code.split()
        head = words[0]
        if head.startswith("$"):
            continue
        if head not in first and head not in TCL_CORE:
            bad.append(line)
            continue
        if head in SUBCOMMAND_WORDS and (len(words) < 2 or words[1] not in subcommands):
            bad.append(line)
    return bad


@pytest.fixture(scope="module")
def allowlist() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    return build_allowlist(UG.read_text(encoding="utf-8", errors="replace"))


def test_allowlist_is_built_from_the_guide(allowlist):
    first, subcommands = allowlist
    assert {"mol", "display", "color", "molinfo", "measure", "render", "axes", "rotate", "quit"} <= first
    assert {"projection", "resetview", "pdbload", "representation", "addrep", "location"} <= subcommands
    assert "backgroundcolor" not in subcommands


@pytest.mark.parametrize("vision", [True, False])
def test_example_commands_in_ug_allowlist(allowlist, vision):
    first, subcommands = allowlist
    prompt = chatvmd_system_prompt(vision)
    assert len(example_lines(prompt)) >= 10
    assert violations(prompt, first, subcommands) == []


def test_lint_flags_the_known_defect(allowlist):
    first, subcommands = allowlist
    sample = ("prose\n    display backgroundcolor white\n    frobnicate 1\n"
              "    color Display Background white\n")
    assert violations(sample, first, subcommands) == ["display backgroundcolor white", "frobnicate 1"]
