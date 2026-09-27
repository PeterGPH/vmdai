from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from .constants import EVENT_ROLES, EVENT_TYPES

# Delivered events kept for a re-poll after a transport blip (§2c Sequence numbers).
DEFAULT_TRIM_AFTER = 1000


class EventQueue:
    """One session's event queue, polled by the plugin (§2c).

    ``seq`` only grows. ``drop_pending`` (a token session's chat.resume)
    empties the queue without resetting it; only ``clear`` (a tokenless
    chat.resume, today's behaviour) resets it. A poll with ``after_seq = N``
    confirms delivery of events up to N. Beyond the newest ``trim_after``
    delivered events the oldest are dropped, and undelivered events are
    never trimmed. ``wait`` blocks a long-poll until ``push`` notifies it
    (§2d M2).
    """

    def __init__(self, trim_after: int = DEFAULT_TRIM_AFTER) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._events: List[Dict[str, Any]] = []
        self._seq = 0
        self._delivered = 0
        self.trim_after = max(0, int(trim_after))

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
        with self._cond:
            self._seq += 1
            item["seq"] = self._seq
            self._events.append(item)
            self._cond.notify_all()
        return item

    def clear(self) -> None:
        """Drop all events and reset the sequence counter (tokenless chat.resume)."""
        with self._cond:
            self._events.clear()
            self._seq = 0
            self._delivered = 0
            self._cond.notify_all()

    def drop_pending(self) -> int:
        """Drop every queued event but keep ``seq`` (a token session's chat.resume, §2c).

        Returns how many events were dropped.
        """
        with self._cond:
            dropped = len(self._events)
            self._events.clear()
            self._cond.notify_all()
            return dropped

    @property
    def last_seq(self) -> int:
        """Sequence number of the newest event pushed (0 when none)."""
        with self._lock:
            return self._seq

    def wait(self, after_seq: int, timeout_s: float) -> bool:
        """Block until an event newer than ``after_seq`` is queued (True) or
        ``timeout_s`` passes (False) (§2d M2 long-poll).

        Returns True at once when such an event is already queued. It also
        returns True at once when ``after_seq`` is ahead of this queue (a
        client out of step with a new or reset queue), so a long-poll never
        sleeps on a cursor that cannot advance.
        """
        safe_after = max(0, int(after_seq or 0))
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._cond:
            while True:
                if safe_after > self._seq:
                    return True
                if self._events and int(self._events[-1].get("seq") or 0) > safe_after:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)

    def poll(self, after_seq: int, limit: int) -> Dict[str, Any]:
        safe_after = max(0, int(after_seq or 0))
        safe_limit = max(1, min(int(limit or 50), 500))
        with self._lock:
            # Polling past an event confirms its delivery.
            if safe_after > self._delivered:
                self._delivered = min(safe_after, self._seq)
            self._trim_locked()
            items = [e for e in self._events if int(e.get("seq") or 0) > safe_after]
            batch = items[:safe_limit]
            last_seq = int(batch[-1]["seq"]) if batch else safe_after
            has_more = len(items) > len(batch)
            return {
                "events": batch,
                "last_seq": last_seq,
                "has_more": has_more,
            }

    def _trim_locked(self) -> None:
        """Keep at most ``trim_after`` delivered events (a prefix, since seq only grows)."""
        delivered = 0
        for event in self._events:
            if int(event.get("seq") or 0) > self._delivered:
                break
            delivered += 1
        excess = delivered - self.trim_after
        if excess > 0:
            del self._events[:excess]


def display_log(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The events a resumed chat replays through vm::apply (§2c Persistence, §7).

    * role=tool_start (the execution channel) is never replayed.
    * A v1 chunk is dropped when its request also stored an assistant
      message, so a log that mixes M1 (v1) and M2 (v2) requests replays
      without duplicates. A request that never stored a message keeps its
      chunks.

    Everything else keeps its order.
    """
    sealed = {
        str((e.get("metadata") or {}).get("request_id") or "")
        for e in events
        if e.get("role") == "assistant" and e.get("type") == "message"
    }
    out: List[Dict[str, Any]] = []
    for event in events:
        if event.get("role") == "tool_start":
            continue
        if event.get("type") == "chunk":
            request_id = str((event.get("metadata") or {}).get("request_id") or "")
            if request_id and request_id in sealed:
                continue
        out.append(event)
    return out
