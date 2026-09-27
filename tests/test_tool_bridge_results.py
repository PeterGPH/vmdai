"""spec 2d Post/Cancel, 2b Late results, C2, C3: tool.command_result by call_key."""
from __future__ import annotations

import time

import pytest

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime import conversation
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.protocol import validate_method_params
from vmd_ai_runtime.tool_bridge import BridgeSession

TOKEN = "0123456789abcdef0123456789abcdef"


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def _post(bridge, call, **fields):
    params = {"call_key": call.call_key, "ok": True, "output": "", "error": ""}
    params.update(fields)
    return bridge.post_result(SESSION_ID, params)


def test_not_acked_cancel_immediate(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 < 0.5
    assert (result["ok"], result["executed"], result["error"]) == (False, "no", "cancelled")
    assert bridge.ack(SESSION_ID, call.call_key)["proceed"] is False


def test_running_cancel_waits_grace_then_unknown(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=0.3)
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 >= 0.3
    assert result["executed"] == "unknown"
    assert result["error"] == "stopped while running; outcome unknown"


def test_stop_between_ack_and_result(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=1.0)
    late_calls = []
    bridge.on_late_result = lambda sid, key, info: late_calls.append((sid, key, info))

    # (1) The result arrives inside the grace window: a consistent "yes".
    call = BridgeCall(bridge, call_key="k0000000000b")
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    call.cancel.set()
    time.sleep(0.1)
    assert _post(bridge, call, output="done") == {"accepted": True, "late": False, "duplicate": False}
    result = call.join()
    assert (result["ok"], result["executed"], result["output"]) == (True, "yes", "done")

    # (2) The result arrives after the grace window: "unknown" now, stored as late.
    bridge.cancel_grace_s = 0.2
    call2 = BridgeCall(bridge, call_key="k0000000000c", request_id="req_bbbbbbbbbbbb")
    call2.tool_start()
    bridge.ack(SESSION_ID, call2.call_key)
    call2.cancel.set()
    assert call2.join()["executed"] == "unknown"
    reply = _post(bridge, call2, output="late output")
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    assert len(late_calls) == 1
    sid, key, info = late_calls[0]
    assert (sid, key) == (SESSION_ID, "k0000000000c")
    assert info["late"] is True and info["executed"] == "yes" and info["output"] == "late output"
    assert info["request_id"] == "req_bbbbbbbbbbbb"
    assert info["tool_name"] == "run_vmd_command"
    assert info["chat_dir"] == str(session.chat_dir)
    assert _post(bridge, call2, output="late output") == {"accepted": True, "late": True, "duplicate": True}
    assert len(late_calls) == 1


def test_posted_executed_no_overrides(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    _post(bridge, call, ok=True, executed="no",
          error="Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)")
    result = call.join()
    assert (result["ok"], result["executed"]) == (False, "no")
    assert result["error"].startswith("Nothing was run")


def test_unacked_result_accepted_as_pickup(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=2.0)
    call = BridgeCall(bridge)
    call.tool_start()
    reply = _post(bridge, call, ok=False, executed="no", error="This panel cannot ask for approval")
    assert reply["accepted"] is True
    result = call.join(wait=1.0)
    assert call.elapsed < 1.0, "the refusal must stop the pickup deadline"
    assert (result["executed"], result["error"]) == ("no", "This panel cannot ask for approval")


def test_duplicate(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    assert _post(bridge, call, output="a") == {"accepted": True, "late": False, "duplicate": False}
    assert call.join()["output"] == "a"
    assert _post(bridge, call, output="a") == {"accepted": True, "late": False, "duplicate": True}
    assert bridge.post_result(SESSION_ID, {"call_key": "zzz000000000"}) == {
        "accepted": False, "late": False, "duplicate": False}
    assert bridge.post_result("sess_other000000", {"call_key": call.call_key})["accepted"] is False


def test_statements_mapping(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_input={"command": "mol new a.pdb\nmol delrep 0 top\nbogus\nputs x"})
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    _post(bridge, call, ok=False, error='invalid command name "bogus"',
          statements_total=4, statements_applied=2, failed_index=3, failed_statement="bogus",
          error_info='invalid command name "bogus"\n    while executing\n"bogus"',
          applied_text="mol new a.pdb\nmol delrep 0 top\n", duration_ms=41)
    result = call.join()
    assert result["statements"] == {
        "total": 4, "applied": 2,
        "failed": {"index": 3, "text": "bogus",
                   "error_info": 'invalid command name "bogus"\n    while executing\n"bogus"'},
    }
    assert result["applied_text"] == "mol new a.pdb\nmol delrep 0 top\n"
    assert result["duration_ms"] == 41
    ok_call = BridgeCall(bridge, call_key="k0000000000d")
    ok_call.tool_start()
    bridge.ack(SESSION_ID, ok_call.call_key)
    bridge.post_result(SESSION_ID, {"call_key": "k0000000000d", "ok": True, "output": "",
                                     "statements_total": 1, "statements_applied": 1})
    assert ok_call.join()["statements"] == {"total": 1, "applied": 1, "failed": None}


def test_late_result_stored_as_late_result_line(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    chat_dir = tmp_path / "chat_for_late"
    chat_dir.mkdir()
    snap = tmp_path / "snap"
    snap.mkdir()
    app.tool_bridge.session_lookup = lambda sid: BridgeSession(
        chat_dir=chat_dir, cwd=str(tmp_path), authenticated=True, snapshot_dir=snap,
        cancel_grace_s=0.1)
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"], request_id="req_cccccccccccc")
    call.tool_start()
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, sess)["result"]["proceed"] is True
    call.cancel.set()
    assert call.join()["executed"] == "unknown"
    resp = _rpc(app, "tool.command_result",
                {"call_key": call.call_key, "ok": True, "output": "3 atoms"}, sess)
    assert resp["result"] == {"accepted": True, "late": True, "duplicate": False}
    lines = [line for line in conversation.read_lines(chat_dir) if line.get("kind") == "late_result"]
    assert len(lines) == 1
    line = lines[0]
    assert (line["call_key"], line["request_id"], line["ok"], line["executed"], line["output"]) == (
        call.call_key, "req_cccccccccccc", True, "yes", "3 atoms")


def test_rpc_command_result_by_call_key(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"])
    call.tool_start()
    other = start_token_session(app, TOKEN)
    params = {"call_key": call.call_key, "ok": True, "output": "x",
              "statements_total": 1, "statements_applied": 1}
    assert _rpc(app, "tool.command_result", params, other)["error"]["code"] == "AUTH_FAILED"
    unknown = _rpc(app, "tool.command_result", dict(params, call_key="zz0000000000"), sess)
    assert unknown["error"]["code"] == "TOOL_CALL_UNKNOWN"
    assert _rpc(app, "tool.command_result", params, sess)["result"] == {
        "accepted": True, "late": False, "duplicate": False}
    result = call.join()
    assert (result["ok"], result["output"], result["statements"]) == (
        True, "x", {"total": 1, "applied": 1, "failed": None})
    assert _rpc(app, "tool.command_result", params, sess)["result"]["duplicate"] is True
    events = _rpc(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, sess)["result"]["events"]
    posted = [e for e in events if e["role"] == "tool_result"]
    assert len(posted) == 1 and posted[0]["metadata"]["call_key"] == call.call_key


def test_protocol_command_result_fields():
    p = validate_method_params("tool.command_result", {
        "session_id": "s", "call_key": "k1", "ok": False, "output": "  out  ",
        "executed": "no", "statements_total": 4, "statements_applied": 2, "failed_index": 3,
        "failed_statement": "x" * 300, "error_info": "l1\nl2\nl3\nl4", "applied_text": "a\n b \n",
        "duration_ms": 12, "truncated": True})
    assert p["tool_call_id"] == ""
    assert p["applied_text"] == "a\n b \n", "applied_text is an exact source prefix"
    assert len(p["failed_statement"]) == 200
    assert p["error_info"] == "l1\nl2\nl3"
    assert (p["statements_total"], p["statements_applied"], p["failed_index"], p["duration_ms"]) == (4, 2, 3, 12)
    assert p["executed"] == "no" and p["truncated"] is True
    legacy = validate_method_params("tool.command_result", {"session_id": "s", "tool_call_id": "tc", "ok": True})
    assert legacy["call_key"] == "" and legacy["executed"] == "yes" and legacy["statements_total"] is None
    with pytest.raises(RpcError) as bad_executed:
        validate_method_params("tool.command_result", {"session_id": "s", "call_key": "k", "executed": "maybe"})
    assert bad_executed.value.code == "INVALID_PARAMS"
    with pytest.raises(RpcError) as no_id:
        validate_method_params("tool.command_result", {"session_id": "s", "ok": True})
    assert no_id.value.code == "INVALID_PARAMS"
    with pytest.raises(RpcError):
        validate_method_params("tool.command_result", {"session_id": "s", "call_key": "k", "statements_total": -1})
