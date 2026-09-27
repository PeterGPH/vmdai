"""Plan 07 test helpers: v2 sessions, a meta-scripted model and product-shaped bridges.

* start_v2 / poll_all / kinds / of_kind drive a RuntimeApp in process.
* ScriptTurn + MetaScriptedLoop: a ClaudeToolLoop whose model turns come from a
  script. A turn can stream status, reasoning and usage through the loop's own
  _on_meta path (exactly as the streamers do), drop the stream once
  (turn_retry), block on a callback, or raise.
* ProductBridge / product_result: a supports_call_meta bridge that answers with
  the full product result dict (plan 05) without any plugin.
* FakePlugin plays executor.tcl against the real VmdToolBridge over the
  in-process RPC: it acks every tool_start and posts tool.command_result by
  call_key, or holds the call (a long VMD command) for the test to post later.
"""
from __future__ import annotations

import copy
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers.app_driver import TOKEN, Session, call, result
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions

MODEL = "qwen3.8:27b"
OLLAMA_URL = "http://ollama.test"
PROFILE_OPTIONS: Dict[str, Any] = {"supports_vision": True, "think": True}


def product_options(**overrides: Any) -> LoopOptions:
    """LoopOptions.product for an Ollama profile; vision and think are on unless overridden."""
    options = dict(PROFILE_OPTIONS)
    options.update(overrides)
    return LoopOptions.product(
        {"provider": "ollama", "base_url": OLLAMA_URL, "model": MODEL, "options": options})


def start_v2(app, tmp_path: Path, *, event_protocol: int = 2, token: str = TOKEN) -> Session:
    """session.start with cwd <tmp_path>/work; ``token=""`` starts a tokenless session."""
    work = Path(tmp_path) / "work"
    work.mkdir(parents=True, exist_ok=True)
    params: Dict[str, Any] = {"cwd": str(work), "event_protocol": event_protocol}
    if token:
        params["launch_token"] = token
    return Session(result(call(app, "session.start", params)))


def poll_all(app, session: Session, after_seq: int = 0) -> List[Dict[str, Any]]:
    """Every queued event after ``after_seq`` (follows has_more)."""
    events: List[Dict[str, Any]] = []
    while True:
        batch = result(call(app, "chat.events.poll", {"after_seq": after_seq, "limit": 500}, session))
        events.extend(batch["events"])
        after_seq = batch["last_seq"]
        if not batch["has_more"]:
            return events


def kinds(events: List[Dict[str, Any]]) -> List[Tuple[str, str, Optional[str]]]:
    """(role, type, metadata.kind) per event."""
    return [(e["role"], e["type"], (e.get("metadata") or {}).get("kind")) for e in events]


def of_kind(events: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    """The metadata of every event whose metadata.kind is ``kind``."""
    return [e["metadata"] for e in events if (e.get("metadata") or {}).get("kind") == kind]


def tool_block(tool_id: str, name: str, **tool_input: Any) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": dict(tool_input)}


def run_cmd(tool_id: str, command: str, rationale: Optional[str] = None) -> Dict[str, Any]:
    tool_input: Dict[str, Any] = {"command": command}
    if rationale:
        tool_input["rationale"] = rationale
    return tool_block(tool_id, "run_vmd_command", **tool_input)


def product_result(**overrides: Any) -> Dict[str, Any]:
    """The product bridge's result dict (plan 05) with every key present."""
    out: Dict[str, Any] = {
        "ok": True, "output": "", "error": "", "executed": "yes", "truncated": False,
        "duration_ms": 0, "statements": None, "blocked": None, "output_path": None,
        "output_bytes": None, "image": None, "saved_path": None, "applied_text": "",
    }
    out.update(overrides)
    if out["output_bytes"] is None:
        out["output_bytes"] = len(str(out["output"]).encode("utf-8"))
    return out


@dataclass
class ScriptTurn:
    """One scripted model call. It streams status, then reasoning, then text."""

    text: str = ""
    tool_blocks: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    status: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None
    drop_after_text: bool = False
    raise_error: Optional[BaseException] = None
    before: Optional[Callable[[], Any]] = None


def _pieces(text: str) -> List[str]:
    """Streamed chunks that join back to ``text`` (a word plus its trailing space)."""
    return re.findall(r"\S+\s*|\s+", text)


class MetaScriptedLoop(ClaudeToolLoop):
    """A product-configured ClaudeToolLoop whose model calls come from a script.

    ``_call`` replaces the streamers, so no request leaves the process. After
    the script ends every call answers ``Done.``. C4's wrap-up call (the loop
    sets ``_tool_mode = "none"`` for it) answers ``wrap_up_text``, or raises
    ``wrap_up_error`` when one is given.
    """

    def __init__(self, script: List[ScriptTurn], *, wrap_up_text: str = "", model: str = MODEL,
                 options: Optional[LoopOptions] = None,
                 wrap_up_error: Optional[BaseException] = None, **kw: Any) -> None:
        kw.setdefault("provider_name", "ollama")
        kw.setdefault("api_key", OLLAMA_URL)
        super().__init__(model=model, options=options if options is not None else product_options(), **kw)
        self.script: List[ScriptTurn] = list(script)
        self.wrap_up_text = wrap_up_text
        self.wrap_up_error = wrap_up_error
        self.calls: List[List[Dict[str, Any]]] = []
        self._script_lock = threading.Lock()

    def _call(self, messages, system_prompt, on_text, should_cancel):
        with self._script_lock:
            self.calls.append(copy.deepcopy(messages))
            if getattr(self, "_tool_mode", None) == "none":
                if self.wrap_up_error is not None:
                    raise self.wrap_up_error
                turn = ScriptTurn(text=self.wrap_up_text)
            elif self.script:
                turn = self.script.pop(0)
            else:
                turn = ScriptTurn(text="Done.")
        if turn.before is not None:
            turn.before()
        if turn.raise_error is not None:
            raise turn.raise_error
        if turn.status is not None:
            self._on_meta(dict(turn.status, kind="status"))
        for piece in _pieces(turn.reasoning):
            self._on_meta({"kind": "reasoning", "text": piece})
        for piece in _pieces(turn.text):
            on_text(piece)
        if turn.drop_after_text:
            raise ConnectionResetError(54, "Connection reset by peer")
        if turn.usage is not None:
            self._on_meta(dict(turn.usage, kind="usage"))
        return turn.text, copy.deepcopy(turn.tool_blocks)


class ProductBridge:
    """Answers tool calls with product result dicts; opts in to call metadata on its class.

    Each item of ``results`` is a result dict, or a callable that takes the
    execute_tool keywords and returns one (it may block or raise).
    """

    supports_call_meta = True

    def __init__(self, results: Optional[List[Any]] = None) -> None:
        self.results: List[Any] = list(results or [])
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def execute_tool(self, **kwargs: Any) -> Dict[str, Any]:
        with self._lock:
            self.calls.append({k: kwargs.get(k) for k in ("tool_name", "tool_input", "call_key", "request_id")})
            item = self.results.pop(0) if self.results else product_result(output="ok")
        if callable(item):
            item = item(kwargs)
        return copy.deepcopy(item)


class FakePlugin:
    """Plays executor.tcl for one session over the in-process RPC.

    ``answer(meta)`` gets the tool_start metadata and returns the
    tool.command_result params (without call_key), or None to ack the call
    and hold it (a long VMD command the test answers later with ``post``).
    Every event the plugin polls is kept in ``events``.
    """

    def __init__(self, app, session: Session,
                 answer: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> None:
        self.app = app
        self.session = session
        self.answer = answer if answer is not None else (lambda meta: {"ok": True, "output": "ok"})
        self.events: List[Dict[str, Any]] = []
        self.held: List[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "FakePlugin":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        after = 0
        while not self._stop.is_set():
            reply = call(self.app, "chat.events.poll", {"after_seq": after, "limit": 200}, self.session)
            batch = reply.get("result") or {"events": [], "last_seq": after}
            for event in batch["events"]:
                self.events.append(event)
                if event.get("role") == "tool_start":
                    self._execute(dict(event.get("metadata") or {}))
            after = batch["last_seq"]
            if not batch["events"]:
                time.sleep(0.01)

    def _execute(self, meta: Dict[str, Any]) -> None:
        call_key = str(meta.get("call_key") or "")
        call(self.app, "tool.ack", {"call_key": call_key}, self.session)
        params = self.answer(meta)
        if params is None:
            self.held.append(call_key)
            return
        body = dict(params)
        body["call_key"] = call_key
        call(self.app, "tool.command_result", body, self.session)

    def post(self, call_key: str, **params: Any) -> Dict[str, Any]:
        """Post a result for a held call; returns {accepted, late, duplicate}."""
        body = dict(params)
        body["call_key"] = call_key
        return result(call(self.app, "tool.command_result", body, self.session))

    def wait_held(self, count: int = 1, timeout: float = 5.0) -> List[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.held) >= count:
                return list(self.held[:count])
            time.sleep(0.01)
        raise AssertionError("the plugin never held %d call(s)" % count)

    def wait_for(self, predicate: Callable[[Dict[str, Any]], bool], timeout: float = 5.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in list(self.events):
                if predicate(event):
                    return event
            time.sleep(0.01)
        raise AssertionError("the plugin never saw the expected event")
