"""The real plugin in tclsh against a real RuntimeApp with a scripted model (P06-T11).

Spec §6 "Bridge integration", S3 and S10. pytest serves RuntimeApp with
ScriptedLoopFactory on port 0; tests/tcl/driver.tcl sources plugin/init.tcl,
attaches with VMD_AI_ATTACH and the token file, runs one scenario and writes
what it saw as JSON. The restart scenarios coordinate through marker files.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pytest

from helpers import tcl
from helpers.scripted_runtime import RunningRuntime, ScriptedLoopFactory, serve_runtime

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "tcl" / "driver.tcl"
LONG = " ".join(f"word{i}" for i in range(250))


def _tool(call_id: str, name: str, **tool_input: str) -> Dict[str, Any]:
    return {"id": call_id, "name": name, "input": tool_input}


SCRIPTS = {
    "round_trip": [
        ("Loading.", [_tool("tc_1", "run_vmd_command",
                            command='mol new 1abc.pdb\nputs "atoms: 42"', rationale="Load")]),
        ("", [_tool("tc_2", "capture_vmd_snapshot", purpose="Check the view")]),
        ("Loaded 42 atoms.", []),
    ],
    "cancel_before_ack": [("", [_tool("tc_1", "run_vmd_command", command="mol new 1abc.pdb")])],
    "cancel_after_ack": [("Running.", [_tool("tc_1", "run_vmd_command",
                                             command="set ::t 0\nafter 800 {set ::t 1}\nvwait ::t\nset ::ran 1")])],
    "has_more": [(LONG, [])],
    "restart": [("Loaded.", []), ("Colored.", [])],
    "race": [("First answer here.", []), ("Second answer with several words in it.", [])],
}

Run = Tuple[Dict[str, Any], ScriptedLoopFactory, RunningRuntime]
_CACHE: Dict[str, Run] = {}


def _drive(tmp_path: Path, scenario: str,
           on_restart: Optional[Callable[[RunningRuntime], None]] = None) -> Run:
    reason = tcl.tcl_skip_reason(needs_http=True, needs_json=True)
    if reason:
        pytest.skip(reason)
    home, sync, out = tmp_path / "rt_home", tmp_path / "sync", tmp_path / "out.json"
    home.mkdir()
    sync.mkdir()
    factory = ScriptedLoopFactory(SCRIPTS["restart" if on_restart else scenario])
    runtime = serve_runtime(home, factory)
    env = {"HOME": str(home), "VMD_AI_ATTACH": f"127.0.0.1:{runtime.port}",
           "VMDAI_SCENARIO": scenario, "VMDAI_OUT": str(out), "VMDAI_SYNC": str(sync)}
    done: Dict[str, Any] = {}

    def run() -> None:
        done["proc"] = tcl.run_tcl(DRIVER.read_text(encoding="utf-8"), needs_http=True,
                                   needs_json=True, env=env, timeout=90)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        if on_restart is not None:
            deadline = time.monotonic() + 30
            while not (sync / "ready_for_restart").exists():
                assert worker.is_alive() and time.monotonic() < deadline, done
                time.sleep(0.02)
            on_restart(runtime)
            (sync / "restarted").touch()
        worker.join(timeout=100)
    finally:
        runtime.stop()
    proc = done["proc"]
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    assert "error" not in data, data.get("error")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return data, factory, runtime


def _cached(key: str, tmp_path: Path, scenario: str, on_restart=None) -> Run:
    # Function scope keeps the hermetic conftest active; each scenario runs once.
    if key not in _CACHE:
        _CACHE[key] = _drive(tmp_path, scenario, on_restart)
    return _CACHE[key]


def test_tool_round_trip_with_ack(tmp_path):
    data, factory, _ = _cached("round_trip", tmp_path, "round_trip")
    assert data["acks"] == ["ok proceed true", "ok proceed true"]
    assert data["vmd_calls"] == ["mol new 1abc.pdb", "display update", "render TachyonInternal"]
    assert data["roles"].count("tool_result/message") == 2
    assert data["roles"][-1] == "assistant/message"
    assert data["text"].endswith("Loaded 42 atoms.")
    assert data["queue"] == 0 and data["ledger"] == 2
    assert len(factory.calls) == 3


def test_puts_output_reaches_model(tmp_path):
    """S10: what the command printed is in the tool result of the next model call."""
    _, factory, _ = _cached("round_trip", tmp_path, "round_trip")
    after_command = json.dumps(factory.calls[1][-1])
    assert "atoms: 42" in after_command
    assert "tool_result" in after_command


def test_cancel_before_ack(tmp_path):
    data, _, _ = _cached("cancel_before_ack", tmp_path, "cancel_before_ack")
    assert data["cancel_sent"] is True
    assert data["acks"] == ["ok proceed false reason cancelled"]
    assert data["vmd_calls"] == []
    assert "system/lifecycle" in data["roles"]


def test_cancel_after_ack(tmp_path):
    data, _, _ = _cached("cancel_after_ack", tmp_path, "cancel_after_ack")
    assert data["ran"] == 1 and data["acks"] == ["ok proceed true"]
    assert data["queue"] == 0
    assert data["roles"][-1] == "system/lifecycle"
    assert data["elapsed_ms"] < 10000  # the result came back inside the grace period


def test_new_chat_resume_race(tmp_path):
    data, _, _ = _cached("race", tmp_path, "race")
    assert data["chat_id"] == data["chat_a"]
    assert data["second_text"] == "Second answer with several words in it."
    assert data["seqs_ordered"] is True
    assert data["session_starts"] == 2 and data["stops"] == 1 and data["resumes"] == 1


def test_has_more_draining_200(tmp_path):
    data, _, _ = _cached("has_more", tmp_path, "has_more")
    assert data["text"] == LONG
    assert data["roles"].count("assistant/chunk") == 250
    assert data["polls"] >= 4
    assert data["drain_ms"] < 600  # three has_more re-polls at once, not 3 x 250 ms


def _kill_then_restart(runtime: RunningRuntime) -> None:
    runtime.stop()
    time.sleep(1.0)
    runtime.restart_same_port()


def test_kill_restart_one_notice_send_within_10s(tmp_path):
    """S3: one notice per state change, recovery and a working chat.send within 10 s."""
    data, _, runtime = _cached("kill", tmp_path, "restart", _kill_then_restart)
    assert data["transitions"] == ["ready>reconnecting", "reconnecting>ready"]
    assert data["notices"] == ["warn Lost the connection to the AI runtime; reconnecting.",
                               "info Reconnected to the AI runtime."]
    assert data["elapsed_ms"] < 10000
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(runtime.apps) == 2


def test_auth_failed_recovery(tmp_path):
    """A restart with no downtime is seen as AUTH_FAILED: new session, same chat."""
    data, _, runtime = _cached("auth", tmp_path, "restart", lambda rt: rt.restart_same_port())
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(data["notices"]) <= len(data["transitions"])
    assert data["statuses"] == []  # idle when it happened: no request was lost
    assert len(runtime.apps) == 2
