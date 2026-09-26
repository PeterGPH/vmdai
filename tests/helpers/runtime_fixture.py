"""In-process runtime helpers (plan 02, P02-T02).

Build a RuntimeApp against temp dirs, start tokenless or token sessions,
call RPCs without HTTP, wait for a request to finish, and serve the app on
an ephemeral port. Plans 03-07 build on these.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.server import create_server


def make_app(tmp_path: Path, **kw: Any) -> RuntimeApp:
    """RuntimeApp with its chat store under ``tmp_path`` (mock provider, no RAG, no wiki by default)."""
    kw.setdefault("store_dir", str(Path(tmp_path) / "chats"))
    kw.setdefault("provider_mode", "mock")
    kw.setdefault("enable_rag", False)
    kw.setdefault("enable_wiki", False)
    return RuntimeApp(**kw)


def rpc(app: RuntimeApp, method: str, params: Optional[Dict[str, Any]] = None,
        session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dispatch one JSON-RPC call in process; returns the whole response ({result} or {error})."""
    body = dict(params or {})
    token = ""
    if session is not None:
        body.setdefault("session_id", session["session_id"])
        token = session["session_token"]
    payload = {"jsonrpc": "2.0", "id": "t", "method": method, "params": body}
    return app.handle_rpc(payload, session_token=token)


def _default_cwd() -> str:
    # The hermetic conftest points HOME at a temp dir, so the recorder's
    # <cwd>/.vmdai_runs never lands in the checkout.
    return os.path.expanduser("~")


def start_tokenless_session(app: RuntimeApp, *, cwd: Optional[str] = None) -> Dict[str, Any]:
    resp = rpc(app, "session.start", {"cwd": cwd or _default_cwd()})
    if "result" not in resp:
        raise AssertionError(f"session.start failed: {resp}")
    return resp["result"]


def start_token_session(app: RuntimeApp, token: str, *, event_protocol: int = 1,
                        cwd: Optional[str] = None,
                        vmd_env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "cwd": cwd or _default_cwd(),
        "ui_mode": "panel",
        "client_version": "test",
        "platform": "test",
        "launch_token": token,
        "event_protocol": event_protocol,
    }
    if vmd_env is not None:
        params["vmd_env"] = vmd_env
    resp = rpc(app, "session.start", params)
    if "result" not in resp:
        raise AssertionError(f"session.start failed: {resp}")
    return resp["result"]


def wait_idle(app: RuntimeApp, session_id: str, timeout: float = 5.0) -> None:
    """Block until the session has no active request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = app.sessions.get(session_id)
        if state is None or state.active_request is None:
            return
        time.sleep(0.02)
    raise AssertionError(f"request in {session_id} did not finish within {timeout} s")


@contextlib.contextmanager
def serve_app(app: RuntimeApp) -> Iterator[int]:
    """Serve ``app`` on 127.0.0.1:<ephemeral>; yields the port."""
    server = create_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield int(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
