"""
tool_bridge.py - Manages async VMD tool execution between Python and Tcl.

Architecture:
  1. Claude loop calls execute_tool() with a tool name + args
  2. execute_tool() pushes a 'tool_start' event onto the session's EventQueue
  3. The Tcl bridge polls that queue, sees the event, runs the VMD command
  4. The Tcl bridge POSTs tool.command_result back to the Python RPC server
  5. The RPC handler calls resolve() which unblocks execute_tool()
  6. execute_tool() returns the result dict to the Claude loop

This is a loopback callback — both sides are on 127.0.0.1 and share nothing
except the session's EventQueue and this bridge's pending-call registry.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .image_utils import read_image_as_png_bytes

logger = logging.getLogger("vmdai.tool_bridge")

# How long (seconds) to wait for Tcl to execute a tool and post the result.
TOOL_TIMEOUT_SEC = 45


@dataclass
class _PendingCall:
    tool_call_id: str
    tool_name: str
    session_id: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None


class VmdToolBridge:
    """
    Thread-safe registry of in-flight VMD tool calls.

    One instance lives on RuntimeApp and is shared across all sessions.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._pending: Dict[str, _PendingCall] = {}

    def get_pending_session(self, tool_call_id: str) -> Optional[str]:
        """Return the session_id that owns a pending call, or None if unknown.

        Used by the RPC handler to verify that a tool.command_result POST
        belongs to the session that originated the tool call. Without this
        check any local process able to guess a tool_call_id could resolve
        another session's pending tool call.
        """
        with self._lock:
            pending = self._pending.get(str(tool_call_id or ""))
        return pending.session_id if pending else None

    # ------------------------------------------------------------------
    # Called by the Claude loop (background thread)
    # ------------------------------------------------------------------

    def execute_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        session_queue,          # EventQueue from sessions.py
        cancel_event: threading.Event,
        timeout: float = TOOL_TIMEOUT_SEC,
    ) -> Dict[str, Any]:
        """
        Push a tool-start event to the session's event queue, then block
        until the Tcl bridge posts the result via tool.command_result.

        Returns a dict with at least:
            {"ok": bool, "output": str, "error": str}
        and optionally:
            {"image_b64": str, "image_mime": str}  # for capture_vmd_snapshot
        """
        pending = _PendingCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            session_id=str(session_id or ""),
        )
        with self._lock:
            self._pending[tool_call_id] = pending

        try:
            # Emit the tool_start event so the Tcl bridge sees it on next poll.
            session_queue.push(
                "tool_start",
                "message",
                _format_tool_label(tool_name, tool_input),
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "session_id": session_id,
                },
            )
            logger.debug(
                "tool_start pushed tool=%s id=%s", tool_name, tool_call_id
            )

            # Wait for Tcl bridge to resolve this call.
            deadline = timeout
            poll_interval = 0.1
            while deadline > 0:
                if cancel_event.is_set():
                    return {"ok": False, "output": "", "error": "cancelled"}
                if pending.done.wait(timeout=poll_interval):
                    break
                deadline -= poll_interval
            else:
                logger.warning(
                    "tool timed out tool=%s id=%s", tool_name, tool_call_id
                )
                return {
                    "ok": False,
                    "output": "",
                    "error": f"VMD tool timed out after {TOOL_TIMEOUT_SEC}s",
                }

            result = pending.result or {}

            # For snapshot tool: read the rendered file and base64-encode it.
            if tool_name == "capture_vmd_snapshot" and result.get("ok"):
                snap_file = str(result.get("snapshot_file") or "")
                if snap_file and os.path.isfile(snap_file):
                    png_bytes = read_image_as_png_bytes(snap_file)
                    if png_bytes:
                        result["image_b64"] = base64.b64encode(png_bytes).decode()
                        result["image_mime"] = "image/png"
                    # Clean up the temp file
                    try:
                        os.unlink(snap_file)
                    except Exception:
                        pass

            return result

        finally:
            with self._lock:
                self._pending.pop(tool_call_id, None)

    # ------------------------------------------------------------------
    # Called by the RPC handler (tool.command_result)
    # ------------------------------------------------------------------

    def resolve(self, tool_call_id: str, result: Dict[str, Any]) -> bool:
        """
        Called when the Tcl bridge POSTs tool.command_result.
        Unblocks the waiting execute_tool() call.
        Returns True if the call was found, False if it was already gone/timed-out.
        """
        with self._lock:
            pending = self._pending.get(tool_call_id)
        if pending is None:
            logger.warning(
                "resolve: unknown tool_call_id=%s (timed out?)", tool_call_id
            )
            return False
        pending.result = result
        pending.done.set()
        logger.debug("tool resolved id=%s ok=%s", tool_call_id, result.get("ok"))
        return True


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _format_tool_label(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Human-readable summary for the tool_start transcript event."""
    if tool_name == "run_vmd_command":
        cmd = str(tool_input.get("command") or "").strip()
        preview = cmd[:80] + "…" if len(cmd) > 80 else cmd
        return f"[VMD] {preview}"
    if tool_name == "capture_vmd_snapshot":
        purpose = str(tool_input.get("purpose") or "inspect viewport").strip()
        return f"[Snapshot] {purpose}"
    return f"[{tool_name}]"
