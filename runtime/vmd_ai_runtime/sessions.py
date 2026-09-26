from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .constants import DEFAULT_SETTINGS
from .events import EventQueue
from .locks import ChatLock


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
    # None for a token session until its first chat.send creates the chat (§2b).
    chat_id: Optional[str]
    settings: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    queue: EventQueue = field(default_factory=EventQueue)
    active_request: Optional[RequestState] = None
    # True when session.start carried the runtime's launch token (§2e).
    # Tokenless sessions keep today's methods and fields; privileged calls
    # check this flag through RuntimeApp._require_auth.
    authenticated: bool = False
    # Negotiated display-event protocol (§2c). The M1 runtime answers 1.
    event_protocol: int = 1
    # Sanitised VMD/Tcl versions from session.start (C6); token sessions only.
    vmd_env: Optional[Dict[str, str]] = None
    # Held by chat.send while it checks for and starts a request (§3).
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # Held while this session has its chat open (token sessions only, §2b).
    chat_lock: Optional[ChatLock] = field(default=None, repr=False, compare=False)


class SessionManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: Dict[str, SessionState] = {}

    def create_session(
        self,
        cwd: str,
        chat_id: str,
        *,
        authenticated: bool = False,
        event_protocol: int = 1,
        vmd_env: Optional[Dict[str, str]] = None,
    ) -> SessionState:
        root = os.path.realpath(cwd or os.getcwd())
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        token = uuid.uuid4().hex
        state = SessionState(
            session_id=sid,
            session_token=token,
            cwd=root,
            chat_id=chat_id,
            authenticated=bool(authenticated),
            event_protocol=int(event_protocol),
            vmd_env=dict(vmd_env) if vmd_env else None,
        )
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
