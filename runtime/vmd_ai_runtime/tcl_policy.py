"""
tcl_policy.py - the critical-Tcl accident guard (spec Part C, C1).

``check(command)`` statically scans model-written Tcl for words that must
never run inside the user's VMD session: shell commands, sockets, binary
extensions, quitting VMD, renaming commands, unsafe interpreters, pipes,
and writes/deletes/sources of protected paths.

This is an ACCIDENT GUARD FOR MODEL MISTAKES, not a sandbox. Tcl can build
a command name at run time (``set c exec; $c ls``) or evaluate a quoted
string (``eval "exec ls"``); a static check cannot see either, and the
tests pin both as known gaps.

Parsing follows Tcl's rules closely enough for that purpose:
  * statements end at a newline or ``;`` outside braces, quotes and brackets;
  * ``#`` in command position starts a comment that runs to the next newline
    not preceded by a backslash;
  * the first word of every statement is checked at top level, inside every
    ``[...]`` (also inside double-quoted words) and inside every braced word:
    every brace body is scanned as a script, an over-approximation that covers
    if/for/foreach/while/proc/after/catch/eval/namespace eval without a
    per-command table;
  * ``{*}`` is stripped; nesting deeper than 16 is itself a finding.

Stdlib-only and Python 3.9-compatible.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

MAX_DEPTH = 16
_PARSE_LIMIT = 48  # parser recursion cap; deeper brackets are skipped flat

FINDING_IDS = (
    "cmd_exec",
    "cmd_socket",
    "cmd_load",
    "cmd_quit",
    "cmd_rename",
    "interp_unsafe",
    "open_pipe",
    "protected_path",
    "too_deep",
)

_COMMAND_IDS = {
    "exec": "cmd_exec",
    "socket": "cmd_socket",
    "load": "cmd_load",
    "quit": "cmd_quit",
    "exit": "cmd_quit",
    "rename": "cmd_rename",
}

_FILE_WRITE_SUBCOMMANDS = ("delete", "rename", "copy", "link", "mkdir")
_OPEN_WRITE_MODES = ("w", "a", "w+", "a+")
_PROTECTED_UNDER_HOME = (".vmdai", ".vmdrc", ".ssh", os.path.join("Library", "LaunchAgents"))
_HOME_VARS = ("$env(HOME)", "$::env(HOME)", "${env(HOME)}", "${::env(HOME)}")

_WS = " \t\r\f\v"


@dataclass(frozen=True)
class Finding:
    id: str
    word: str
    statement_index: int
    text: str


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------

@dataclass
class _Word:
    kind: str                 # "brace" | "quote" | "bare"
    text: str                 # literal content (without braces/quotes)
    subs: List[str]           # scripts of [...] substitutions (quote/bare words)


@dataclass
class _Command:
    start: int
    end: int
    words: List[_Word]


def _skip_backslash(s: str, i: int) -> int:
    """``s[i]`` is a backslash: return the index after the escaped char."""
    return min(i + 2, len(s))


def _skip_bracket_flat(s: str, i: int) -> Tuple[str, int, bool]:
    """Find the ``]`` matching ``s[i] == "["`` by counting (no recursion)."""
    depth = 0
    j = i
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\":
            j = _skip_backslash(s, j)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1, True
        j += 1
    return s[i + 1:], n, False


def _parse_bracket(s: str, i: int, level: int) -> Tuple[str, int, bool]:
    """``s[i]`` is ``[``. Return (inner script, index after ``]``, complete)."""
    if level > _PARSE_LIMIT:
        return _skip_bracket_flat(s, i)
    _cmds, end, complete = _parse_script(s, i + 1, in_bracket=True, level=level + 1)
    if complete and end < len(s) and s[end] == "]":
        return s[i + 1:end], end + 1, True
    return s[i + 1:end], end, False


def _parse_word(s: str, i: int, in_bracket: bool, level: int) -> Tuple[_Word, int, bool]:
    n = len(s)
    if s.startswith("{*}", i) and i + 3 < n and s[i + 3] not in _WS + "\n;":
        i += 3
    c = s[i]
    if c == "{":
        depth = 1
        j = i + 1
        while j < n and depth:
            ch = s[j]
            if ch == "\\":
                j = _skip_backslash(s, j)
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        if depth:
            return _Word("brace", s[i + 1:], []), n, False
        word = _Word("brace", s[i + 1:j - 1], [])
        # Tcl rejects "extra characters after close-brace"; we just stop here.
        return word, j, True
    if c == '"':
        j = i + 1
        subs: List[str] = []
        while j < n:
            ch = s[j]
            if ch == "\\":
                j = _skip_backslash(s, j)
                continue
            if ch == "[":
                inner, j, ok = _parse_bracket(s, j, level)
                subs.append(inner)
                if not ok:
                    return _Word("quote", s[i + 1:j], subs), j, False
                continue
            if ch == '"':
                return _Word("quote", s[i + 1:j], subs), j + 1, True
            j += 1
        return _Word("quote", s[i + 1:], subs), n, False
    j = i
    subs = []
    while j < n:
        ch = s[j]
        if ch == "\\":
            if j + 1 < n and s[j + 1] == "\n":
                break
            j = _skip_backslash(s, j)
            continue
        if ch in _WS or ch in "\n;":
            break
        if in_bracket and ch == "]":
            break
        if ch == "[":
            inner, j, ok = _parse_bracket(s, j, level)
            subs.append(inner)
            if not ok:
                return _Word("bare", s[i:j], subs), j, False
            continue
        j += 1
    return _Word("bare", s[i:j], subs), j, True


def _parse_script(s: str, i: int = 0, in_bracket: bool = False,
                  level: int = 0,
                  newlines: Optional[Set[int]] = None) -> Tuple[List[_Command], int, bool]:
    """Parse commands from ``s[i:]``. Returns (commands, end index, complete).

    In bracket mode parsing stops at the unmatched ``]`` (not consumed).
    ``complete`` is False when a brace, quote or bracket is left open.
    When ``newlines`` is given, the index of every newline that ends a line
    at top level (between commands, ending a command, ending a comment) is
    added to it. Never raises.
    """
    n = len(s)
    cmds: List[_Command] = []
    while i < n:
        while i < n:
            ch = s[i]
            if ch in _WS or ch in "\n;":
                if ch == "\n" and newlines is not None:
                    newlines.add(i)
                i += 1
            elif ch == "\\" and i + 1 < n and s[i + 1] == "\n":
                i += 2
            else:
                break
        if i >= n:
            break
        if in_bracket and s[i] == "]":
            return cmds, i, True
        if s[i] == "#":
            while i < n:
                if s[i] == "\\":
                    i = _skip_backslash(s, i)
                    continue
                if s[i] == "\n":
                    if newlines is not None:
                        newlines.add(i)
                    break
                i += 1
            continue
        start = i
        words: List[_Word] = []
        while i < n:
            while i < n:
                ch = s[i]
                if ch in _WS:
                    i += 1
                elif ch == "\\" and i + 1 < n and s[i + 1] == "\n":
                    i += 2
                else:
                    break
            if i >= n or s[i] in "\n;":
                break
            if in_bracket and s[i] == "]":
                break
            word, i, ok = _parse_word(s, i, in_bracket, level)
            words.append(word)
            if not ok:
                cmds.append(_Command(start, i, words))
                return cmds, i, False
        cmds.append(_Command(start, i, words))
        if in_bracket and i < n and s[i] == "]":
            return cmds, i, True
    return cmds, i, not in_bracket


# ----------------------------------------------------------------------
# Statement split (same grouping as the executor's info-complete split)
# ----------------------------------------------------------------------

def split_statements(script: str) -> List[str]:
    """Split ``script`` the way executor.tcl does before running it.

    Lines are accumulated until the buffer is a complete Tcl script
    (``info complete``). Blank lines and full-line comments between
    statements are skipped; a comment line ending in a backslash also
    swallows the next line, as Tcl does. ``a; b`` on one line is one
    statement. An incomplete tail is returned as the last element.

    One linear parse finds the newlines that end a line at top level; a
    buffer is complete exactly when its last newline is one of them.
    """
    text = script or ""
    top: Set[int] = set()
    _parse_script(text, newlines=top)
    out: List[str] = []
    buf_start: Optional[int] = None
    in_comment = False
    pos = 0
    n = len(text)
    while pos <= n:
        nl = text.find("\n", pos)
        end = n if nl < 0 else nl
        at_top = nl < 0 or end in top
        if buf_start is None:
            line = text[pos:end]
            if in_comment:
                in_comment = not at_top
            elif line.strip() and line.strip().startswith("#"):
                in_comment = not at_top
            elif line.strip():
                buf_start = pos
        if buf_start is not None and at_top:
            stmt = text[buf_start:end].strip()
            if stmt:
                out.append(stmt)
            buf_start = None
        if nl < 0:
            break
        pos = nl + 1
    if buf_start is not None and text[buf_start:].strip():
        out.append(text[buf_start:].strip())
    return out


# ----------------------------------------------------------------------
# Path protection
# ----------------------------------------------------------------------

def _default_checkout_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _expand(path: str, home: str) -> Optional[str]:
    """Expand ``~`` and ``$env(HOME)`` in a literal path; None if not literal."""
    p = path
    for var in _HOME_VARS:
        if p == var or p.startswith(var + "/"):
            p = home + p[len(var):]
            break
    if p == "~" or p.startswith("~/"):
        p = home + p[1:]
    if "$" in p or "[" in p:
        return None
    return p


def is_protected_path(path: str, *, checkout_root: Optional[str] = None,
                      home: Optional[str] = None) -> bool:
    """True when the literal ``path`` is ``~``, ``/``, or under a protected tree."""
    home_dir = os.path.normpath(home or os.path.expanduser("~"))
    root = os.path.normpath(checkout_root or _default_checkout_root())
    expanded = _expand(path.strip(), home_dir)
    if expanded is None or not os.path.isabs(expanded):
        return False
    p = os.path.normpath(expanded)
    if p in ("/", home_dir):
        return True
    trees = [os.path.join(home_dir, sub) for sub in _PROTECTED_UNDER_HOME] + [root]
    for tree in trees:
        if p == tree or p.startswith(tree.rstrip("/") + "/"):
            return True
    return False


# ----------------------------------------------------------------------
# Scanner
# ----------------------------------------------------------------------

def _literal(word: _Word) -> Optional[str]:
    """The word's literal value, or None when it depends on substitution."""
    if word.subs:
        return None
    if word.kind == "brace":
        return word.text
    if "$" in word.text and word.text not in _HOME_VARS and not any(
            word.text.startswith(v + "/") for v in _HOME_VARS):
        return None
    return word.text


def _command_findings(words: List[_Word], text: str, index: int,
                      checkout_root: str, home: str) -> List[Finding]:
    if not words:
        return []
    name = _literal(words[0])
    if name is None:
        return []
    name = name.lstrip(":")
    args = [_literal(w) for w in words[1:]]
    preview = " ".join(text.split())[:200]
    found: List[Finding] = []

    def protected(p: Optional[str]) -> bool:
        return p is not None and is_protected_path(p, checkout_root=checkout_root, home=home)

    if name in _COMMAND_IDS:
        found.append(Finding(_COMMAND_IDS[name], name, index, preview))
    elif name == "interp":
        if args and args[0] == "create" and "-safe" not in args[1:]:
            found.append(Finding("interp_unsafe", "interp create", index, preview))
    elif name == "open":
        target = args[0] if args else None
        if target is not None and target.startswith("|"):
            found.append(Finding("open_pipe", "open |", index, preview))
        elif len(args) >= 2 and args[1] in _OPEN_WRITE_MODES and protected(target):
            found.append(Finding("protected_path", "open", index, str(target)))
    elif name == "file":
        if args and args[0] in _FILE_WRITE_SUBCOMMANDS:
            rest = args[1:]
            while rest and rest[0] is not None and rest[0].startswith("-"):
                done = rest[0] == "--"
                rest = rest[1:]
                if done:
                    break
            hits = [p for p in rest if protected(p)]
            if hits:
                found.append(Finding("protected_path", "file " + str(args[0]), index, str(hits[0])))
    elif name == "source":
        if args and protected(args[-1]):
            found.append(Finding("protected_path", "source", index, str(args[-1])))
    return found


def _scan(script: str, depth: int, index: int, findings: List[Finding],
          checkout_root: str, home: str) -> None:
    if depth > MAX_DEPTH:
        if not any(f.id == "too_deep" for f in findings):
            findings.append(Finding("too_deep", "", index, "nesting deeper than %d" % MAX_DEPTH))
        return
    cmds, _end, _complete = _parse_script(script)
    for cmd in cmds:
        text = script[cmd.start:cmd.end]
        findings.extend(_command_findings(cmd.words, text, index, checkout_root, home))
        for word in cmd.words:
            if word.kind == "brace":
                _scan(word.text, depth + 1, index, findings, checkout_root, home)
            for sub in word.subs:
                _scan(sub, depth + 1, index, findings, checkout_root, home)


def check(command: str, *, checkout_root: Optional[str] = None,
          home: Optional[str] = None) -> List[Finding]:
    """Return the critical findings in ``command`` (empty list = allowed)."""
    root = checkout_root or _default_checkout_root()
    home_dir = home or os.path.expanduser("~")
    findings: List[Finding] = []
    for idx, stmt in enumerate(split_statements(command or ""), start=1):
        _scan(stmt, 0, idx, findings, root, home_dir)
    return findings


_EXEC_STYLE = (
    "Not run: `{word}` is never run by ChatVMD. If the user needs it, show the "
    "command in a tcl code block so they can copy it and run it in the VMD "
    "console themselves."
)


def message_for(finding: Finding) -> str:
    """The model-facing error text for one finding (spec C1 wording)."""
    if finding.id == "cmd_quit":
        return "Not run: this would close the user's VMD session."
    if finding.id == "protected_path":
        return "Not run: ChatVMD never writes, deletes or sources %s." % finding.text
    if finding.id == "too_deep":
        return ("Not run: the command nests brackets or braces more than %d levels "
                "deep, too deep to check. Split it into smaller commands." % MAX_DEPTH)
    return _EXEC_STYLE.format(word=finding.word or finding.id)
