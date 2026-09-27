"""The real plugin in tclsh against a real RuntimeApp with a scripted model (P06-T11).

Spec §6 "Bridge integration", S3 and S10. pytest serves RuntimeApp with
ScriptedLoopFactory on port 0; tests/tcl/driver.tcl sources plugin/init.tcl,
attaches with VMD_AI_ATTACH and the token file, runs one scenario and writes
what it saw as JSON. The restart scenarios coordinate through marker files.

Each run (a scenario, or the restart scenario with one way of restarting)
happens once per session. The first test that needs one starts every run the
session's selected tests need, each on its own thread with its own runtime,
tclsh and temp dir, and waits for all of them, so they overlap one another
but never another test (the hermetic conftest stays active throughout).
"""
from __future__ import annotations

import concurrent.futures
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
# key -> (True, Run) or (False, the exception _drive raised)
_OUTCOMES: Dict[str, Tuple[bool, Any]] = {}


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


def _uses(key: str):
    """Mark a test as reading the RUNS entry ``key``."""
    def mark(fn):
        fn.run_key = key
        return fn
    return mark


def _outcome(tmp_path: Path, key: str) -> Tuple[bool, Any]:
    scenario, on_restart = RUNS[key]
    try:
        tmp_path.mkdir()
        return True, _drive(tmp_path, scenario, on_restart)
    except BaseException as exc:  # noqa: BLE001 - pytest.skip and failures alike
        return False, exc


def _cached(request: pytest.FixtureRequest, tmp_path: Path) -> Run:
    # Function scope keeps the hermetic conftest active; each run happens once.
    key = request.function.run_key
    if key not in _OUTCOMES:
        wanted = {getattr(getattr(item, "function", None), "run_key", None)
                  for item in request.session.items}
        pending = [k for k in RUNS if k not in _OUTCOMES and (k in wanted or k == key)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(pending),
                                                   thread_name_prefix="bridge-run") as pool:
            futures = {k: pool.submit(_outcome, tmp_path / k, k) for k in pending}
            for k, future in futures.items():
                _OUTCOMES[k] = future.result()
    ok, value = _OUTCOMES[key]
    if not ok:
        raise value
    return value


@_uses("round_trip")
def test_tool_round_trip_with_ack(request, tmp_path):
    data, factory, _ = _cached(request, tmp_path)
    assert data["acks"] == ["ok proceed true", "ok proceed true"]
    assert data["vmd_calls"] == ["mol new 1abc.pdb", "display update", "render TachyonInternal"]
    assert data["roles"].count("tool_result/message") == 2
    assert data["roles"][-1] == "assistant/message"
    assert data["text"].endswith("Loaded 42 atoms.")
    assert data["queue"] == 0 and data["ledger"] == 2
    assert len(factory.calls) == 3


@_uses("round_trip")
def test_puts_output_reaches_model(request, tmp_path):
    """S10: what the command printed is in the tool result of the next model call."""
    _, factory, _ = _cached(request, tmp_path)
    after_command = json.dumps(factory.calls[1][-1])
    assert "atoms: 42" in after_command
    assert "tool_result" in after_command


@_uses("cancel_before_ack")
def test_cancel_before_ack(request, tmp_path):
    data, _, _ = _cached(request, tmp_path)
    assert data["cancel_sent"] is True
    assert data["acks"] == ["ok proceed false reason cancelled"]
    assert data["vmd_calls"] == []
    assert "system/lifecycle" in data["roles"]


@_uses("cancel_after_ack")
def test_cancel_after_ack(request, tmp_path):
    data, _, _ = _cached(request, tmp_path)
    assert data["ran"] == 1 and data["acks"] == ["ok proceed true"]
    assert data["queue"] == 0
    assert data["roles"][-1] == "system/lifecycle"
    assert data["elapsed_ms"] < 10000  # the result came back inside the grace period


@_uses("race")
def test_new_chat_resume_race(request, tmp_path):
    data, _, _ = _cached(request, tmp_path)
    assert data["chat_id"] == data["chat_a"]
    assert data["second_text"] == "Second answer with several words in it."
    assert data["seqs_ordered"] is True
    assert data["session_starts"] == 2 and data["stops"] == 1 and data["resumes"] == 1


@_uses("has_more")
def test_has_more_draining_200(request, tmp_path):
    data, _, _ = _cached(request, tmp_path)
    assert data["text"] == LONG
    assert data["roles"].count("assistant/chunk") == 250
    assert data["polls"] >= 4
    # Structural: back-to-back polls while has_more, not a wall-clock budget
    # on drain_ms (Minor 8; drain_ms stays in the output for information).
    assert data["more_replies"] >= 1
    assert data["more_gap_max_ms"] < 200


def _kill_then_restart(runtime: RunningRuntime) -> None:
    runtime.stop()
    time.sleep(1.0)
    runtime.restart_same_port()


def _restart_now(runtime: RunningRuntime) -> None:
    runtime.restart_same_port()


# key -> (driver scenario, what pytest does at the restart marker)
RUNS: Dict[str, Tuple[str, Optional[Callable[[RunningRuntime], None]]]] = {
    "round_trip": ("round_trip", None),
    "cancel_before_ack": ("cancel_before_ack", None),
    "cancel_after_ack": ("cancel_after_ack", None),
    "race": ("race", None),
    "has_more": ("has_more", None),
    "kill": ("restart", _kill_then_restart),
    "auth": ("restart", _restart_now),
}


@_uses("kill")
def test_kill_restart_one_notice_send_within_10s(request, tmp_path):
    """S3: one notice per state change, recovery and a working chat.send within 10 s."""
    data, _, runtime = _cached(request, tmp_path)
    assert data["transitions"] == ["ready>reconnecting", "reconnecting>ready"]
    assert data["notices"] == ["warn Lost the connection to the AI runtime; reconnecting.",
                               "info Reconnected to the AI runtime."]
    assert data["elapsed_ms"] < 10000
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(runtime.apps) == 2


@_uses("auth")
def test_auth_failed_recovery(request, tmp_path):
    """A restart with no downtime is seen as AUTH_FAILED: new session, same chat."""
    data, _, runtime = _cached(request, tmp_path)
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(data["notices"]) <= len(data["transitions"])
    assert data["statuses"] == []  # idle when it happened: no request was lost
    assert len(runtime.apps) == 2
