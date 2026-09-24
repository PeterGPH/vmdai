from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .constants import DEFAULT_SETTINGS
from .events import EventQueue


@dataclass
class RequestState:
    request_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


@dataclass
class SessionState:
    session_id: str
    session_token: str
    cwd: str
    chat_id: str
    settings: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    queue: EventQueue = field(default_factory=EventQueue)
    active_request: Optional[RequestState] = None


class SessionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, SessionState] = {}

    def create_session(self, cwd: str, chat_id: str) -> SessionState:
        root = os.path.realpath(cwd or os.getcwd())
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        token = uuid.uuid4().hex
        state = SessionState(session_id=sid, session_token=token, cwd=root, chat_id=chat_id)
        with self._lock:
            self._sessions[sid] = state
        return state

    def get(self, session_id: str) -> Optional[SessionState]:
        with self._lock:
            return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def verify(self, session_id: str, token: str) -> Optional[SessionState]:
        state = self.get(session_id)
        if state is None:
            return None
        if state.session_token != str(token or ""):
            return None
        return state
