from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from .constants import EVENT_ROLES, EVENT_TYPES


class EventQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._seq = 0

    def push(self, role: str, event_type: str, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if role not in EVENT_ROLES:
            raise ValueError(f"Unsupported role: {role}")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {event_type}")
        item = {
            "seq": 0,
            "ts": time.time(),
            "role": role,
            "type": event_type,
            "text": str(text or ""),
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._seq += 1
            item["seq"] = self._seq
            self._events.append(item)
        return item

    def clear(self) -> None:
        """Drop all events and reset the sequence counter."""
        with self._lock:
            self._events.clear()
            self._seq = 0

    @property
    def last_seq(self) -> int:
        """Sequence number of the newest event pushed (0 when none)."""
        with self._lock:
            return self._seq

    def poll(self, after_seq: int, limit: int) -> Dict[str, Any]:
        safe_after = max(0, int(after_seq or 0))
        safe_limit = max(1, min(int(limit or 50), 500))
        with self._lock:
            items = [e for e in self._events if int(e.get("seq") or 0) > safe_after]
            batch = items[:safe_limit]
            last_seq = int(batch[-1]["seq"]) if batch else safe_after
            has_more = len(items) > len(batch)
            return {
                "events": batch,
                "last_seq": last_seq,
                "has_more": has_more,
            }
