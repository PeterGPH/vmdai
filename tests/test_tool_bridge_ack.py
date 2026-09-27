"""C2 / spec 2d: tool.ack with state, pickup and exec deadlines (VmdToolBridge)."""
from __future__ import annotations

import os
import time

import pytest

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime.settings_store import SettingsStore
from vmd_ai_runtime.tool_bridge import VmdToolBridge

TOKEN = "0123456789abcdef0123456789abcdef"


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def test_supports_call_meta_is_a_class_attribute():
    assert VmdToolBridge.__dict__["supports_call_meta"] is True


def test_token_tool_start_metadata(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, call_key="k0000000000a", request_id="req_aaaaaaaaaaaa")
    meta = call.tool_start()["metadata"]
    assert meta["call_key"] == "k0000000000a"
    assert meta["request_id"] == "req_aaaaaaaaaaaa"
    assert meta["approval"] == "auto"
    assert meta["snapshot_path"] == ""
    assert meta["tool_call_id"] == "tc_1" and meta["session_id"] == SESSION_ID
    call.cancel.set()
    call.join()


def test_tokenless_tool_start_metadata_unchanged(tmp_path):
    bridge = make_bridge(make_session(tmp_path, authenticated=False))
    call = BridgeCall(bridge, timeout=2)
    meta = call.tool_start()["metadata"]
    assert set(meta) == {"tool_call_id", "tool_name", "tool_input", "session_id"}
    assert bridge.resolve("tc_1", {"ok": True, "output": "0", "error": ""})
    assert call.join()["output"] == "0"


def test_pickup_timeout_message(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2)
    call = BridgeCall(bridge)
    result = call.join()
    assert result["ok"] is False
    assert result["executed"] == "no"
    assert result["error"] == "VMD did not pick up the command (no reply within 0.2 s)."
    assert 0.2 <= call.elapsed < 1.5
    assert bridge.ack(SESSION_ID, call.call_key, "running") == {"proceed": False, "reason": "cancelled"}


def test_awaiting_user_ack_no_pickup_timeout(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2, exec_timeout_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key, "awaiting_user") == {"proceed": True}
    time.sleep(0.6)
    assert call.alive(), "an awaiting_user ack must stop the pickup deadline"
    call.cancel.set()
    assert call.join()["executed"] == "no"


def test_stop_during_awaiting_user_executed_no_and_later_ack_refused(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key, "awaiting_user")["proceed"] is True
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 < 0.5, "no grace wait: nothing is running yet"
    assert (result["ok"], result["error"], result["executed"]) == (False, "cancelled", "no")
    assert bridge.ack(SESSION_ID, call.call_key, "running")["proceed"] is False


def test_running_ack_starts_exec_deadline(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2, exec_timeout_s=0.5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key) == {"proceed": True}
    result = call.join()
    assert result["executed"] == "unknown"
    assert result["error"] == "VMD did not finish the command within 0.5 s; outcome unknown."
    assert call.elapsed >= 0.5


def test_ack_unknown_call_and_foreign_session(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    assert bridge.ack(SESSION_ID, "nope00000000") == {"proceed": False, "reason": "unknown call"}
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack("sess_other000000", call.call_key)["proceed"] is False
    with pytest.raises(ValueError):
        bridge.ack(SESSION_ID, call.call_key, "bogus")
    call.cancel.set()
    call.join()


def test_token_call_resolvable_by_tool_call_id(tmp_path):
    # Compat: a client that posts by tool_call_id still resolves a token call.
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_call_id="tc_compat")
    call.tool_start()
    assert bridge.get_pending_session("tc_compat") == SESSION_ID
    assert bridge.resolve("tc_compat", {"ok": True, "output": "3", "error": ""}) is True
    result = call.join()
    assert (result["ok"], result["output"], result["executed"]) == (True, "3", "yes")
    assert bridge.get_pending_session("tc_compat") is None
    assert bridge.get_call_session(call.call_key) == SESSION_ID


def test_unknown_state_invalid_params(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN)
    resp = _rpc(app, "tool.ack", {"call_key": "k00000000001", "state": "bogus"}, sess)
    assert resp["error"]["code"] == "INVALID_PARAMS"
    assert resp["error"]["data"]["allowed"] == ["running", "awaiting_user"]


def test_rpc_tool_ack_round_trip(tmp_path, monkeypatch):
    app = make_app(tmp_path, launch_token=TOKEN)
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"])
    meta = call.tool_start()["metadata"]
    assert meta["call_key"] == call.call_key, "token sessions take the call_key path"
    assert _rpc(app, "tool.ack", {"call_key": call.call_key, "state": "awaiting_user"}, sess)["result"] == {"proceed": True}
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, sess)["result"] == {"proceed": True}
    other = start_token_session(app, TOKEN)
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, other)["error"]["code"] == "AUTH_FAILED"
    assert _rpc(app, "tool.ack", {"call_key": "zz0000000000"}, sess)["result"] == {
        "proceed": False, "reason": "unknown call"}
    call.cancel.set()
    assert call.join()["executed"] == "unknown"


def test_bridge_session_for_token_session(tmp_path):
    # make_app builds no SettingsStore (plan 03: only main.py passes one).
    app = make_app(tmp_path, launch_token=TOKEN, settings_store=SettingsStore())
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    app.settings_store.patch({"tool_exec_timeout_s": 120, "cancel_grace_s": 5})
    bs = app._bridge_session(sess["session_id"])
    assert bs.authenticated is True
    assert bs.cwd == os.path.realpath(str(tmp_path))
    assert bs.chat_dir is None, "token sessions create their chat on the first chat.send"
    assert bs.snapshot_dir.is_dir()
    assert bs.snapshot_dir.stat().st_mode & 0o777 == 0o700
    assert (bs.exec_timeout_s, bs.cancel_grace_s) == (120.0, 5.0)
    app.settings_store.patch({"cancel_grace_s": 0})
    assert app._bridge_session(sess["session_id"]).cancel_grace_s == 0.0, "0 means: do not wait"
    assert app._bridge_session("sess_unknown00000") is None
    bare = make_app(tmp_path / "bare", launch_token=TOKEN)
    bare_sess = start_token_session(bare, TOKEN)
    bs_bare = bare._bridge_session(bare_sess["session_id"])
    assert (bs_bare.exec_timeout_s, bs_bare.cancel_grace_s) == (None, None), "no store: bridge defaults"
