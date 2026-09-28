"""P09-T07: the v2 switch, long-poll, view-model wiring and the ui.tcl shim."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TOTAL = 10


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_bridge_v2.tcl")


def test_event_protocol_2_negotiated(results):
    assert_case(results, "v2-event_protocol_2_negotiated", TOTAL)


def test_long_poll_used(results):
    assert_case(results, "v2-long_poll_used", TOTAL)


def test_runtime_state_to_banner_and_local_events(results):
    assert_case(results, "v2-runtime_state_to_banner_and_local_events", TOTAL)


def test_refused_send_keeps_draft(results):
    assert_case(results, "v2-refused_send_keeps_draft", TOTAL)


def test_send_transport_failure_restores_draft(results):
    assert_case(results, "v2-send_transport_failure_restores_draft", TOTAL)


def test_session_start_failure_noted(results):
    assert_case(results, "v2-session_start_failure_noted", TOTAL)


def test_no_model_card(results):
    assert_case(results, "v2-no_model_card", TOTAL)


def test_request_finished_ends_busy(results):
    assert_case(results, "v2-request_finished_ends_busy", TOTAL)


def test_resume_replays_history(results):
    assert_case(results, "v2-resume_replays_history", TOTAL)


def test_settings_after_restart(results):
    assert_case(results, "v2-settings_after_restart", TOTAL)


def test_ui_shim_covers_callers():
    """ui.tcl is a small shim that still defines every ::vmdai::ui:: name used elsewhere."""
    shim = (PLUGIN / "ui.tcl").read_text(encoding="utf-8")
    defined = set(re.findall(r"^proc\s+::vmdai::ui::(\w+)", shim, re.MULTILINE))
    defined |= set(re.findall(r"\bvariable\s+(\w+)", shim))
    used = set()
    for path in PLUGIN.glob("*.tcl"):
        if path.name != "ui.tcl":
            used |= set(re.findall(r"::vmdai::ui::(\w+)", path.read_text(encoding="utf-8")))
    assert sorted(used - defined) == []
    assert len(shim.splitlines()) < 80
