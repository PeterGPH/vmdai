"""A real RuntimeApp with a scripted model, served over HTTP (P06-T11; spec §6).

``ScriptedLoopFactory(script)`` is a ``loop_factory``: the script is a list of
``(text, tool_calls)`` model turns, served in order across requests; each
tool call is a dict with ``id``, ``name`` and ``input`` (the loop adds
``type: tool_use``). A turn's text is streamed a word at a time, as a real
provider streams it, so a long text gives many chunk events. Once the script
is used up every turn answers ``("Done.", [])``. Building a loop consumes
nothing (plan 02's factory contract); turns are taken when the loop runs.
``factory.calls`` holds a deep copy of the messages of every model call, so a
test can check what the model saw (S10).

``serve_runtime(home, loop_factory)`` builds a token-only RuntimeApp (like
``main.py --announce``: no tokenless sessions) with its chats under
``home/.vmdai/chats``, serves it on 127.0.0.1:<ephemeral> and writes the
attach token file ``home/.vmdai/run/runtime-<port>.json``. ``stop()`` takes
it down as a crash would (the port closes; chat locks and requests die with
it). ``restart_same_port()`` then starts a new RuntimeApp on the same port
with a new token and token file, sharing the chat store, like a runtime
restarted by ``scripts/run_runtime.sh``. The pid in ``/health`` stays the
pytest process's, so the plugin notices the restart through AUTH_FAILED.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers.runtime_fixture import make_app
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.constants import DEFAULT_SETTINGS
from vmd_ai_runtime.launch import generate_launch_token, write_token_file
from vmd_ai_runtime.server import create_server

Turn = Tuple[str, List[Dict[str, Any]]]


class ScriptedLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose model turns come from its factory's script."""

    def __init__(self, factory: "ScriptedLoopFactory") -> None:
        super().__init__(provider_name="anthropic-direct", api_key="sk-test",
                         model=DEFAULT_SETTINGS["model"])
        self._factory = factory

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self._factory.calls.append(copy.deepcopy(messages))
        text, tool_calls = self._factory.next_turn()
        for piece in re.findall(r"\S+\s*", text):
            if should_cancel():
                break
            on_text(piece)
        blocks = [dict(copy.deepcopy(call), type="tool_use") for call in tool_calls]
        return text, blocks


class ScriptedLoopFactory:
    """loop_factory(profile) -> ScriptedLoop, all loops sharing one script.

    The script is a list of ``(text, tool_calls)`` model turns, served in
    order across requests; each tool call is a dict with ``id``, ``name`` and
    ``input`` (the loop adds ``type: tool_use``). Once the script is used up
    every turn answers ``("Done.", [])``.
    """

    def __init__(self, script: List[Turn]) -> None:
        self.script: List[Turn] = list(script)
        self.calls: List[List[Dict[str, Any]]] = []
        self._lock = threading.Lock()

    def __call__(self, profile: Optional[Dict[str, Any]]) -> ScriptedLoop:
        return ScriptedLoop(self)

    def next_turn(self) -> Turn:
        with self._lock:
            return self.script.pop(0) if self.script else ("Done.", [])


@dataclass
class RunningRuntime:
    home: Path
    loop_factory: Callable[[Optional[Dict[str, Any]]], Optional[ClaudeToolLoop]]
    port: int = 0
    token: str = ""
    token_file: Optional[Path] = None
    app: Optional[RuntimeApp] = None
    _server: Any = None
    _thread: Optional[threading.Thread] = None
    apps: List[RuntimeApp] = field(default_factory=list)

    def _start(self, port: int) -> None:
        self.token = generate_launch_token()
        self.app = make_app(self.home / ".vmdai", launch_token=self.token,
                            allow_tokenless_v1=False, loop_factory=self.loop_factory)
        self.apps.append(self.app)
        self._server = create_server(self.app, host="127.0.0.1", port=port)
        self.port = int(self._server.server_port)
        self.token_file = write_token_file(self.port, os.getpid(), self.token, 2, home=str(self.home))
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Close the port and end every session's request and chat lock."""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        app = self.app
        if app is not None:
            for state in list(getattr(app.sessions, "_sessions", {}).values()):
                try:
                    app._cancel_active_request(state)
                except Exception:
                    pass
                release = getattr(app, "_release_chat_lock", None)
                if release is not None:
                    release(state)

    def restart_same_port(self) -> None:
        """A new RuntimeApp (new token and token file) on the same port."""
        self.stop()
        self._start(self.port)


def serve_runtime(home: Path, loop_factory) -> RunningRuntime:
    runtime = RunningRuntime(home=Path(home), loop_factory=loop_factory)
    runtime._start(0)
    return runtime
