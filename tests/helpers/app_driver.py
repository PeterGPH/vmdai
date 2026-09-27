"""In-process driver for RuntimeApp tests (plan 03).

Builds on plan 02's helpers.runtime_fixture: make_token_app is make_app with
a launch token, and call() is rpc() for a Session object, so a test can
assert on the raw envelope's ``result`` or ``error.code``. ScriptedLoop
replays model turns; InstantBridge answers tool calls at once with the
strict six-keyword signature.
"""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from helpers.runtime_fixture import make_app, rpc
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.constants import DEFAULT_SETTINGS

TOKEN = "0123456789abcdef0123456789abcdef"


class Session:
    """A started session: the session.start result and the ids rpc() needs."""

    def __init__(self, result: Dict[str, Any]) -> None:
        self.result = result
        self.session_id = result["session_id"]
        self.token = result["session_token"]


def make_token_app(tmp_path: Path, **kw: Any) -> RuntimeApp:
    """plan 02's make_app (mock provider, no RAG, no wiki) that also knows TOKEN.

    Tokenless sessions are still accepted (allow_tokenless_v1 defaults to True).
    """
    kw.setdefault("launch_token", TOKEN)
    return make_app(tmp_path, **kw)


def call(app: RuntimeApp, method: str, params: Optional[Dict[str, Any]] = None,
         session: Optional[Session] = None) -> Dict[str, Any]:
    """One JSON-RPC call in process; returns the whole envelope ({result} or {error})."""
    return rpc(app, method, params, session.result if session is not None else None)


def result(envelope: Dict[str, Any]) -> Any:
    assert "result" in envelope, envelope
    return envelope["result"]


def error_code(envelope: Dict[str, Any]) -> str:
    assert "error" in envelope, envelope
    return envelope["error"]["code"]


def start(app: RuntimeApp, tmp_path: Path, *, token: str = TOKEN) -> Session:
    """session.start with a temp cwd; ``token=""`` starts a tokenless session."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    params: Dict[str, Any] = {"cwd": str(work), "event_protocol": 1}
    if token:
        params["launch_token"] = token
    return Session(result(call(app, "session.start", params)))


def send(app: RuntimeApp, session: Session, text: str, **extra: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {"text": text, "conversation_mode": "full"}
    params.update(extra)
    return call(app, "chat.send", params, session)


def state_of(app: RuntimeApp, session: Session):
    return app.sessions.get(session.session_id)


def wait_idle(app: RuntimeApp, session: Session, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = state_of(app, session)
        request = state.active_request if state is not None else None
        if request is None or (request.thread is not None and not request.thread.is_alive()):
            return
        time.sleep(0.01)
    raise AssertionError("request still running after %.1f s" % timeout)


def tool_use(tool_id: str, command: str) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": "run_vmd_command", "input": {"command": command}}


class InstantBridge:
    """Strict six-keyword bridge that answers every tool call at once."""

    def __init__(self, output: Callable[[Dict[str, Any]], str] = lambda tool_input: "ok") -> None:
        self.output = output
        self.calls: List[Dict[str, Any]] = []

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name, "tool_input": tool_input})
        return {"ok": True, "output": self.output(tool_input), "error": ""}


class ScriptedLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose model turns come from a script.

    Each ``_call`` records a deep copy of the messages it was given, runs
    ``before_call(call_number, messages)`` when set (call_number starts at 1),
    and returns the next ``(text, tool_blocks)`` pair, or ``("Done.", [])``
    once the script is used up. The default model is the session default
    (DEFAULT_SETTINGS["model"]), so plan 02's per-session model override
    never swaps an assigned ScriptedLoop for a plain ClaudeToolLoop.
    """

    def __init__(self, script: Sequence[Tuple[str, List[Dict[str, Any]]]], *,
                 before_call: Optional[Callable[[int, List[Dict[str, Any]]], Any]] = None,
                 **kw: Any) -> None:
        kw.setdefault("provider_name", "anthropic-direct")
        kw.setdefault("api_key", "sk-test")
        kw.setdefault("model", DEFAULT_SETTINGS["model"])
        super().__init__(**kw)
        self.script = list(script)
        self.calls: List[List[Dict[str, Any]]] = []
        self.before_call = before_call
        self._script_lock = threading.Lock()

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self.calls.append(copy.deepcopy(messages))
        if self.before_call is not None:
            self.before_call(len(self.calls), messages)
        with self._script_lock:
            text, blocks = self.script.pop(0) if self.script else ("Done.", [])
        if text:
            on_text(text)
        return text, copy.deepcopy(blocks)
