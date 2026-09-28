"""P10-T06: final Tk goldens and the V8 additions (Part B V8; Part A section 6).

tests/tcl/test_v8_additions.tcl replays fixtures through the assembled panel
and writes portable dumps to $M3_OUT; this module compares them with
tests/fixtures/tk/ (rewritten only when CHATVMD_UPDATE_GOLDENS=1). The last
two tests need no Tcl or Tk and run in CI: every test V8 lists has an owner,
and every event fixture has a Tk golden.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from helpers import tk
from helpers.panel_goldens import EVENTS_DIR, compare_golden
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
TOTAL = 11
NEW_GOLDENS = ("loop_guard", "turn_retry", "11_dead_runtime")
V8_FILE = "tests/tcl/test_v8_additions.tcl"

# What each new golden must hold and must not hold (V4 Run footer and
# Timeline notes, C4 Panel, section 2c Block boundaries). Commands are matched
# by their first words only: the withdrawn panel is 1 px wide, so rows are
# ellipsized (never below 12 characters, V6).
CONTENT: Dict[str, Tuple[List[str], List[str]]] = {
    "loop_guard": (["color the protein by residue type", "Coloring by residue type.",
                    "Stopped: the model kept repeating the same step", "ResType", "evaluated"],
                   ["`", "Copy Tcl"]),
    "turn_retry": (["load 1hck", "Loading 1hck now.", "Done: 1hck is loaded.", "evaluated"],
                   ["Loading 1hLoading"]),
    "11_dead_runtime": (["load 1hck", "mol new", "Connection lost at"],
                        ["evaluated"]),
}

# Part B V8, every test it lists.
NATIVE = ["glue-1", "status-1", "err-1", "out-1", "md-1", "md-2", "expand-1", "fit-1", "tk85-1"]
CARDS = ["ro-1", "group-1", "group-2", "group-3", "offline-1", "composer-1", "theme-1"]
ADD = [
    "inline code never wraps",
    "the failing-statement highlight matches the executor's split",
    '"Not sent to the model" is shown',
    "sticky autoscroll leaves a scrolled-up view alone",
    "an unknown call_key does nothing",
    "no more than 30 images stay loaded",
    "clicking a chip jumps to its step",
]

# (V8 test, owner file, tcltest case in a .tcl file or pytest function in a
# .py file). An added item may have two owners: its component test and the
# re-run on the finished M3 panel in this task.
V8_OWNERS: List[Tuple[str, str, str]] = [
    ("glue-1", "tests/tcl/test_tool_rows.tcl", "glue-1"),
    ("status-1", "tests/tcl/test_tool_rows.tcl", "status-1"),
    ("err-1", "tests/tcl/test_tool_rows.tcl", "err-1"),
    ("out-1", "tests/tcl/test_tool_rows.tcl", "out-1"),
    ("md-1", "tests/tcl/test_markdown_render.tcl", "md-1"),
    ("md-2", "tests/tcl/test_markdown_render.tcl", "md-2"),
    ("expand-1", "tests/tcl/test_tool_rows.tcl", "expand-1"),
    ("fit-1", "tests/tcl/test_tool_rows.tcl", "fit-1"),
    ("tk85-1", "tests/tcl/test_snapshot_cards.tcl", "tk85-1"),
    ("ro-1", "tests/test_tk_transcript.py", "test_ro_1"),
    ("group-1", "tests/tcl/test_tool_rows.tcl", "group-1"),
    ("group-2", "tests/tcl/test_tool_rows.tcl", "group-2"),
    ("group-3", "tests/tcl/test_tool_rows.tcl", "group-3"),
    ("offline-1", "tests/tcl/test_statusbar_banner.tcl", "offline-1"),
    ("composer-1", "tests/tcl/test_composer.tcl", "composer-1"),
    ("theme-1", "tests/tcl/test_dark.tcl", "theme-1"),
    (ADD[0], "tests/test_tk_markdown_render.py", "test_inline_code_never_wraps"),
    (ADD[0], V8_FILE, "v8-add-inline_code_nowrap"),
    (ADD[1], "tests/test_tk_tool_rows.py", "test_failing_statement_highlight_matches_executor_split"),
    (ADD[1], V8_FILE, "v8-add-failing_statement_dark"),
    (ADD[2], "tests/test_tk_snapshot_cards.py", "test_not_sent_to_model_shown"),
    (ADD[3], "tests/test_tk_transcript.py", "test_sticky_autoscroll"),
    (ADD[3], V8_FILE, "v8-add-sticky_on_seal"),
    (ADD[4], "tests/test_tcl_viewmodel.py", "test_unknown_call_key_ignored"),
    (ADD[4], V8_FILE, "v8-add-unknown_call_key"),
    (ADD[5], "tests/test_tk_snapshot_cards.py", "test_max_30_images"),
    (ADD[5], V8_FILE, "v8-add-photo_cap_after_switch"),
    (ADD[6], "tests/test_tk_tool_rows.py", "test_chip_click_jumps"),
]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("m3_out")
    # TZ=UTC: "Connection lost at <time>" in 11_dead_runtime (plan 08's rule).
    result = run_tk_file("test_v8_additions.tcl", env={"M3_OUT": str(out), "TZ": "UTC"})
    return result, out


def _dump(run, name: str) -> str:
    result, out = run
    path = out / ("%s.txt" % name)
    assert path.is_file(), "no dump for %s\n%s" % (name, result.output)
    return path.read_text(encoding="utf-8")


def _assert_portable(text: str) -> None:
    assert str(REPO) not in text, "the checkout path leaked into the dump"
    for temp in ("/var/folders/", "/private/tmp/", "/tmp/pytest-"):
        assert temp not in text, "a temp path leaked into the dump"


@pytest.mark.parametrize("name", NEW_GOLDENS)
def test_golden_replay(run, name):
    assert_case(run[0], "v8-golden-%s" % name, TOTAL)
    text = _dump(run, name)
    present, absent = CONTENT[name]
    assert [s for s in present if s not in text] == [], text
    assert [s for s in absent if s in text] == [], text
    _assert_portable(text)
    compare_golden(text, tk.golden_path(name))


def test_golden_03_conversation_dark(run):
    assert_case(run[0], "v8-dark-fresh", TOTAL)
    assert_case(run[0], "v8-dark-same_text", TOTAL)
    text = _dump(run, "03_conversation_dark")
    body, marker, colours = text.partition("# tag colours\n")
    assert marker, text
    assert "**" not in body and "evaluated" in body
    assert re.search(r"^syn_cmd -foreground #79c0ff$", colours, re.MULTILINE), colours
    assert re.search(r"^md_code -background #313135$", colours, re.MULTILINE), colours
    _assert_portable(text)
    compare_golden(text, tk.golden_path("03_conversation_dark"))


def test_dark_switch_matches_fresh(run):
    assert_case(run[0], "v8-dark-switch_matches_fresh", TOTAL)


def test_unknown_call_key_noop_in_panel(run):
    assert_case(run[0], "v8-add-unknown_call_key", TOTAL)


def test_failing_statement_highlight_in_dark(run):
    assert_case(run[0], "v8-add-failing_statement_dark", TOTAL)


def test_photo_cap_survives_theme_switch(run):
    assert_case(run[0], "v8-add-photo_cap_after_switch", TOTAL)


def test_sticky_autoscroll_on_markdown_seal(run):
    assert_case(run[0], "v8-add-sticky_on_seal", TOTAL)


def test_inline_code_never_wraps_in_transcript(run):
    assert_case(run[0], "v8-add-inline_code_nowrap", TOTAL)


def _defined(rel: str, name: str) -> bool:
    path = REPO / rel
    if not path.is_file():
        return False
    if rel.endswith(".tcl"):
        pattern = r"^test\s+%s\s" % re.escape(name)
    else:
        pattern = r"^def %s\(" % re.escape(name)
    return re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE) is not None


def test_v8_list_complete():
    assert {item for item, _, _ in V8_OWNERS} == set(NATIVE + CARDS + ADD)
    missing = ["%s: %s in %s" % (item, name, rel) for item, rel, name in V8_OWNERS
               if not _defined(rel, name)]
    assert missing == []


def test_every_fixture_has_a_tk_golden():
    fixtures = sorted(p.stem for p in EVENTS_DIR.glob("*.jsonl"))
    assert fixtures == ["03_conversation", "11_dead_runtime", "loop_guard", "reasoning_answer", "turn_retry"]
    missing = [n for n in fixtures + ["03_conversation_dark"] if not tk.golden_path(n).is_file()]
    assert missing == []
