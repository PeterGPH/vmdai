"""View-model (plan 08, P08-T01..T03): tcltest units plus op goldens.

The op goldens replay the runtime-recorded scenario fixtures
(tests/fixtures/events/<name>.jsonl, plan 07) through ::vmdai::vm::apply
and compare the ops, one per line, with tests/fixtures/ops/<name>.ops.
Scenario checks derived from spec §6 run on every replay, so a regenerated
golden that loses the point of its scenario still fails.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

import pytest

from helpers.panel_goldens import (
    EVENTS_DIR,
    OPS_DIR,
    assert_tcltests,
    compare_golden,
    parse_ops,
)
from helpers.tcl import REPO, module_result, module_run, run_tcl, run_tcltest

TCL = REPO / "tests" / "tcl" / "test_viewmodel.tcl"

UNIT_TESTS = [
    "user_block_ops",
    "block_closes_on_role_request_turn_change",
    "non_chunk_event_closes_block",
    "seal_replaces_streamed_text",
    "seal_empty_discards",
    "final_answer_under_rule",
    "reasoning_seal_and_replay",
    "turn_retry_discards",
    "run_and_tool_ops",
    "tool_open_args",
    "status_ops_follow_phases",
    "snapshot_op",
    "format_op_round_trip",
    "trust_notice_no_op",
]

UNIT_TESTS += [
    "notrun_label_order",
    "tool_state_values",
    "unknown_call_key_ignored",
    "second_finished_ignored_unless_late",
    "late_updates_row_after_finished",
    "error_card_actions_and_no_model",
    "local_connection_notices",
    "request_ended_local",
]

UNIT_TESTS += [
    "status_text_phases",
    "run_summary_strings",
    "finished_after_n_steps",
    "max_turns_uses_request_started",
    "stuck_notes",
]

# Final-review fix wave (plan 08).
UNIT_TESTS += [
    "local_connection_restart",
    "reasoning_live_duration",
]

REPLAY = r"""
source [file join $env(VMDAI_PLUGIN_DIR) viewmodel.tcl]
set in [open $env(CHATVMD_EVENTS) r]
fconfigure $in -encoding utf-8
set out [open $env(CHATVMD_OPS_OUT) w]
fconfigure $out -encoding utf-8 -translation lf
::vmdai::vm::init S
while {[gets $in line] >= 0} {
    if {[string trim $line] eq ""} continue
    foreach op [::vmdai::vm::apply S [json::json2dict $line]] {
        puts $out [::vmdai::vm::format_op $op]
    }
}
close $in
close $out
"""


@module_run
def _run(tmp_path_factory):
    return run_tcltest(str(TCL), env={"TZ": "UTC"})


@pytest.fixture(scope="module")
def vm_result(request):
    return module_result(request)


@pytest.mark.parametrize("name", UNIT_TESTS)
def test_viewmodel_unit(vm_result, name):
    assert_tcltests(vm_result, [name])


def test_viewmodel_counts(vm_result):
    assert (vm_result.passed, vm_result.failed) == (len(UNIT_TESTS), 0), vm_result.output


def test_user_block_ops(vm_result):
    assert_tcltests(vm_result, ["user_block_ops"])


def test_block_closes_on_role_request_turn_change(vm_result):
    assert_tcltests(vm_result, ["block_closes_on_role_request_turn_change", "non_chunk_event_closes_block"])


def test_seal_replaces_streamed_text(vm_result):
    assert_tcltests(vm_result, ["seal_replaces_streamed_text", "seal_empty_discards", "final_answer_under_rule"])


def test_trust_notice_no_op(vm_result):
    assert_tcltests(vm_result, ["trust_notice_no_op"])


def test_notrun_label_order(vm_result):
    assert_tcltests(vm_result, ["notrun_label_order", "tool_state_values"])


def test_unknown_call_key_ignored(vm_result):
    assert_tcltests(vm_result, ["unknown_call_key_ignored"])


def test_second_finished_ignored_unless_late(vm_result):
    assert_tcltests(vm_result, ["second_finished_ignored_unless_late"])


def test_late_updates_row_after_finished(vm_result):
    assert_tcltests(vm_result, ["late_updates_row_after_finished"])


def test_error_card_actions_and_no_model(vm_result):
    assert_tcltests(vm_result, ["error_card_actions_and_no_model"])


def test_local_events(vm_result):
    assert_tcltests(vm_result, ["local_connection_notices", "request_ended_local"])


def test_status_text_phases(vm_result):
    assert_tcltests(vm_result, ["status_text_phases"])


def test_run_summary_strings(vm_result):
    assert_tcltests(vm_result, ["run_summary_strings"])


def test_finished_after_n_steps(vm_result):
    assert_tcltests(vm_result, ["finished_after_n_steps", "stuck_notes"])


def test_max_turns_uses_request_started(vm_result):
    assert_tcltests(vm_result, ["max_turns_uses_request_started"])


def replay_ops(name: str, tmp_path: Path) -> str:
    out = tmp_path / f"{name}.ops"
    proc = run_tcl(
        REPLAY,
        needs_json=True,
        env={
            "TZ": "UTC",
            "CHATVMD_EVENTS": str(EVENTS_DIR / f"{name}.jsonl"),
            "CHATVMD_OPS_OUT": str(out),
        },
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text(encoding="utf-8")


def check_block_lifecycle(ops: List[List[str]]) -> None:
    """Every block op names a block that is open; nothing follows a seal or discard."""
    state: Dict[str, str] = {}
    for op in ops:
        kind, args = op[0], op[1:]
        if kind in ("block.open", "reasoning.open"):
            assert args[0] not in state, op
            state[args[0]] = "open"
        elif kind in ("block.append", "reasoning.append"):
            assert state.get(args[0]) == "open", op
        elif kind in ("block.seal", "reasoning.seal"):
            assert state.get(args[0]) == "open", op
            state[args[0]] = "sealed"
        elif kind == "block.discard":
            assert state.get(args[0]) in ("open", "sealed"), op
            state[args[0]] = "discarded"


def check_tools(ops: List[List[str]]) -> None:
    """tool.close, snapshot and run.chip only name tools that tool.open announced once."""
    opened: List[str] = []
    for op in ops:
        if op[0] == "tool.open":
            assert op[1] not in opened, op
            opened.append(op[1])
        elif op[0] in ("tool.close", "snapshot"):
            assert op[1] in opened, op
        elif op[0] == "run.chip":
            assert op[2] in opened, op


SCENARIO_CHECKS: Dict[str, List[Callable[[List[List[str]]], None]]] = {}


def scenario(name: str):
    def register(fn):
        SCENARIO_CHECKS.setdefault(name, []).append(fn)
        return fn
    return register


@scenario("03_conversation")
def _two_requests_failure_recovered_snapshot(ops):
    assert len([op for op in ops if op[0] == "run.open"]) == 2
    states = [op[2] for op in ops if op[0] == "tool.close"]
    assert "err" in states and "ok" in states[states.index("err") + 1:], states
    assert any(op[0] == "tool.open" and op[2] == "capture_vmd_snapshot" for op in ops)
    assert any(op[0] == "rule" for op in ops)
    assert [op[2] for op in ops if op[0] == "run.close"] == ["complete", "complete"]
    assert ops[-1] == ["status", "idle"]


@scenario("reasoning_answer")
def _reasoning_then_answer(ops):
    reasoning = {op[1] for op in ops if op[0] == "reasoning.open"}
    answers = {op[1] for op in ops if op[0] == "block.open" and op[2] == "assistant"}
    assert reasoning and answers and not (reasoning & answers)
    last_seal = max(i for i, op in enumerate(ops) if op[0] == "reasoning.seal")
    assert any(op[0] == "block.seal" for op in ops[last_seal:])


@scenario("turn_retry")
def _retried_block_discarded(ops):
    # a discard not followed by the final answer's rule is the retry's discard
    retried = [
        op[1] for i, op in enumerate(ops[:-1])
        if op[0] == "block.discard" and ops[i + 1][0] not in ("rule", "block.discard")
    ]
    sealed = {op[1] for op in ops if op[0] == "block.seal"}
    assert retried and not (set(retried) & sealed), ops
    assert sealed


@scenario("loop_guard")
def _stuck_run_ends_with_wrap_up(ops):
    assert [op[2] for op in ops if op[0] == "run.close"] == ["stuck"]
    last_rule = max(i for i, op in enumerate(ops) if op[0] == "rule")
    assert any(op[0] == "block.seal" for op in ops[last_rule:])
    assert ops[-1] == ["status", "idle"]


@scenario("11_dead_runtime")
def _lost_runtime_notices(ops):
    assert any(op[0] == "run.open" for op in ops)
    assert any(op[0] == "tool.open" for op in ops)
    assert not any(op[0] == "run.close" and op[2] == "complete" for op in ops)
    notices = [op[2] for op in ops if op[0] == "notice"]
    assert any(n.startswith("Connection lost at ") for n in notices), notices


@scenario("loop_guard")
def _stuck_note(ops):
    notes = [op[2] for op in ops if op[0] == "notice"]
    assert "Stopped: the model kept repeating the same step" in notes, notes
    note_at = max(i for i, op in enumerate(ops) if op[0] == "notice")
    close_at = max(i for i, op in enumerate(ops) if op[0] == "run.close")
    assert note_at < close_at


def run_scenario_checks(name: str, ops: List[List[str]]) -> None:
    check_block_lifecycle(ops)
    check_tools(ops)
    for check in SCENARIO_CHECKS[name]:
        check(ops)


@pytest.mark.parametrize("name", sorted(SCENARIO_CHECKS))
def test_ops_golden(name, tmp_path):
    text = replay_ops(name, tmp_path)
    run_scenario_checks(name, parse_ops(text))
    compare_golden(text, OPS_DIR / f"{name}.ops")
