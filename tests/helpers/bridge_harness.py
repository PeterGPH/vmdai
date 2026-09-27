"""Drive VmdToolBridge.execute_tool on a worker thread (plan 05 tests)."""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.tool_bridge import BridgeSession, VmdToolBridge

SESSION_ID = "sess_0123456789ab"
CHAT_ID = "chat_0123456789ab"


def make_session(tmp_path: Path, *, authenticated: bool = True, with_chat: bool = True) -> BridgeSession:
    """A BridgeSession rooted in ``tmp_path`` (chat dir, cwd and snapshot dir)."""
    chat_dir = tmp_path / "chats" / CHAT_ID
    if with_chat:
        chat_dir.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    return BridgeSession(
        chat_dir=chat_dir if with_chat else None,
        cwd=str(work),
        authenticated=authenticated,
        snapshot_dir=snap,
    )


def make_bridge(session: Optional[BridgeSession], **kw: Any) -> VmdToolBridge:
    """A VmdToolBridge whose session_lookup knows only SESSION_ID."""
    return VmdToolBridge(
        session_lookup=lambda sid: session if sid == SESSION_ID else None, **kw
    )


def write_tga(path: Path, width: int = 64, height: int = 48) -> Path:
    """Write an uncompressed 24-bit TGA (what VMD's renderers produce)."""
    header = bytearray(18)
    header[2] = 2
    struct.pack_into("<H", header, 12, width)
    struct.pack_into("<H", header, 14, height)
    header[16] = 24
    pixels = bytes([30, 60, 90]) * (width * height)
    path.write_bytes(bytes(header) + pixels)
    return path


class BridgeCall:
    """One execute_tool call running on a daemon thread."""

    def __init__(
        self,
        bridge: VmdToolBridge,
        *,
        tool_name: str = "run_vmd_command",
        tool_input: Optional[Dict[str, Any]] = None,
        call_key: Optional[str] = "k00000000001",
        request_id: Optional[str] = "req_000000000001",
        tool_call_id: str = "tc_1",
        session_id: str = SESSION_ID,
        timeout: float = 45,
    ):
        self.bridge = bridge
        self.queue = EventQueue()
        self.cancel = threading.Event()
        self.call_key = call_key
        self.result: Optional[Dict[str, Any]] = None
        self.returned_at: Optional[float] = None
        self.started_at = time.monotonic()
        kwargs = dict(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=dict(tool_input if tool_input is not None else {"command": "mol list"}),
            session_queue=self.queue,
            cancel_event=self.cancel,
            timeout=timeout,
            call_key=call_key,
            request_id=request_id,
        )

        def _run() -> None:
            self.result = bridge.execute_tool(**kwargs)
            self.returned_at = time.monotonic()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def tool_start(self, wait: float = 2.0) -> Dict[str, Any]:
        """The pushed tool_start event (waits for it)."""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            events = [e for e in self.queue.poll(0, 50)["events"] if e["role"] == "tool_start"]
            if events:
                return events[0]
            time.sleep(0.01)
        raise AssertionError("no tool_start event was pushed")

    def join(self, wait: float = 3.0) -> Dict[str, Any]:
        self.thread.join(timeout=wait)
        assert not self.thread.is_alive(), "execute_tool did not return"
        assert self.result is not None
        return self.result

    def alive(self) -> bool:
        return self.thread.is_alive()

    @property
    def elapsed(self) -> float:
        end = self.returned_at if self.returned_at is not None else time.monotonic()
        return end - self.started_at
