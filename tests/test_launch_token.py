"""P02-T02: launch token, token file, READY line and authenticated sessions (§2e, C6, S11)."""
from __future__ import annotations

import json
import os
import stat

import pytest

from helpers.runtime_fixture import make_app, rpc, start_token_session, start_tokenless_session
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.launch import (
    format_ready_line,
    generate_launch_token,
    read_token_file,
    remove_token_file,
    token_file_path,
    write_token_file,
)
from vmd_ai_runtime.protocol import CHAT_ID_RE, validate_method_params

TOKEN = "0123456789abcdef0123456789abcdef"
TODAY_START_KEYS = {"session_id", "session_token", "capabilities", "defaults",
                    "chat_id", "provider", "agent_loop"}


def _code(resp):
    assert "error" in resp, resp
    return resp["error"]["code"]


def test_generate_token_128_bits():
    first, second = generate_launch_token(), generate_launch_token()
    assert len(first) == 32
    assert first == first.lower() and int(first, 16) >= 0
    assert first != second


def test_token_file_mode_0600_and_fields(tmp_path):
    home = str(tmp_path)
    path = token_file_path(8765, home)
    assert path == tmp_path / ".vmdai" / "run" / "runtime-8765.json"
    path.parent.mkdir(parents=True)
    path.write_text("stale")
    os.chmod(path, 0o644)
    assert write_token_file(8765, 4321, TOKEN, 2, home=home) == path
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert read_token_file(path) == {"port": 8765, "pid": 4321, "token": TOKEN, "protocol": 2}
    assert list(path.parent.glob("*.tmp")) == []
    remove_token_file(path)
    assert not path.exists()
    remove_token_file(path)  # a second remove is a no-op


def test_ready_line_format():
    line = format_ready_line(51234, 4321, "0.3.0", 2, TOKEN)
    assert line == ('VMDAI_READY {"port":51234,"pid":4321,"version":"0.3.0",'
                    '"protocol":2,"launch_token":"' + TOKEN + '"}')
    assert json.loads(line.split(" ", 1)[1])["launch_token"] == TOKEN


def test_tokenless_start_rejected_when_announced(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN, allow_tokenless_v1=False)
    assert _code(rpc(app, "session.start", {"cwd": str(tmp_path)})) == "AUTH_REQUIRED"
    assert app.store.list_chats() == []  # a refused start creates no chat


def test_tokenless_start_accepted_without_announce(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    result = start_tokenless_session(app, cwd=str(tmp_path))
    assert set(result) == TODAY_START_KEYS  # exactly today's fields
    state = app.sessions.get(result["session_id"])
    assert state.authenticated is False
    assert state.event_protocol == 1


def test_wrong_launch_token_auth_failed(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN, allow_tokenless_v1=False)
    resp = rpc(app, "session.start", {"cwd": str(tmp_path), "launch_token": "f" * 32})
    assert _code(resp) == "AUTH_FAILED"
    no_token = make_app(tmp_path / "other")
    resp = rpc(no_token, "session.start", {"cwd": str(tmp_path), "launch_token": TOKEN})
    assert _code(resp) == "AUTH_FAILED"


def test_vmd_env_sanitised_and_kept_only_for_token_sessions(tmp_path):
    env = {"vmd_version": "1.9.4a57", "arch": "MACOSXARM64", "tcl_patchlevel": "8.6.12",
           "tk_patchlevel": "x" * 100, "evil": "rm -rf ~", "nested": {"a": 1}}
    app = make_app(tmp_path, launch_token=TOKEN)
    token_session = start_token_session(app, TOKEN, cwd=str(tmp_path), vmd_env=env)
    assert app.sessions.get(token_session["session_id"]).vmd_env == {
        "vmd_version": "1.9.4a57", "arch": "MACOSXARM64",
        "tcl_patchlevel": "8.6.12", "tk_patchlevel": "x" * 64,
    }
    plain = rpc(app, "session.start", {"cwd": str(tmp_path), "vmd_env": env})["result"]
    assert app.sessions.get(plain["session_id"]).vmd_env is None
    assert "vmd_env" not in validate_method_params("session.start", {"vmd_env": "text"})


def test_runtime_shutdown_requires_launch_token(tmp_path):
    calls = []
    app = make_app(tmp_path, launch_token=TOKEN, on_shutdown=lambda: calls.append("stop"))
    assert _code(rpc(app, "runtime.shutdown", {})) == "INVALID_PARAMS"
    assert _code(rpc(app, "runtime.shutdown", {"launch_token": "0" * 32})) == "AUTH_FAILED"
    assert calls == []
    assert rpc(app, "runtime.shutdown", {"launch_token": TOKEN})["result"] == {"ok": True}
    assert calls == ["stop"]
    no_token = make_app(tmp_path / "other")
    assert _code(rpc(no_token, "runtime.shutdown", {"launch_token": TOKEN})) == "AUTH_FAILED"


def test_chat_id_validation():
    good = "chat_0123456789ab"
    assert CHAT_ID_RE.fullmatch(good)
    assert validate_method_params("chat.resume", {"session_id": "s", "chat_id": good})["chat_id"] == good
    assert validate_method_params("chat.send", {"session_id": "s", "text": "hi", "chat_id": ""})["chat_id"] == ""
    for bad in ("../etc", "chat_../../x1", "chat_ABCDEF012345", "chat_0123",
                "chat_0123456789abc", "x"):
        for method, params in (
            ("chat.resume", {"session_id": "s", "chat_id": bad}),
            ("chat.history.get", {"session_id": "s", "chat_id": bad}),
            ("chat.send", {"session_id": "s", "text": "hi", "chat_id": bad}),
        ):
            with pytest.raises(RpcError) as info:
                validate_method_params(method, params)
            assert info.value.code == "INVALID_PARAMS", (method, bad)


def test_event_protocol_values(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    one = start_token_session(app, TOKEN, event_protocol=1, cwd=str(tmp_path))
    assert one["event_protocol"] == 1
    assert one["runtime"] == {"version": "0.3.0", "pid": os.getpid()}
    assert TODAY_START_KEYS <= set(one)
    # Plan 07 (M2): a token session that asks for display protocol 2 gets it.
    two = start_token_session(app, TOKEN, event_protocol=2, cwd=str(tmp_path))
    assert two["event_protocol"] == 2
    assert app.sessions.get(two["session_id"]).authenticated is True
    for bad in (3, 0, "abc"):
        resp = rpc(app, "session.start",
                   {"cwd": str(tmp_path), "launch_token": TOKEN, "event_protocol": bad})
        assert _code(resp) == "INVALID_PARAMS", bad


def test_require_auth_raises_for_tokenless(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    plain = start_tokenless_session(app, cwd=str(tmp_path))
    with pytest.raises(RpcError) as info:
        app._require_auth(app.sessions.get(plain["session_id"]))
    assert info.value.code == "AUTH_REQUIRED"
    token_session = start_token_session(app, TOKEN, cwd=str(tmp_path))
    app._require_auth(app.sessions.get(token_session["session_id"]))  # no raise
