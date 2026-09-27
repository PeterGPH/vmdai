"""
tool_bridge.py - Manages async VMD tool execution between Python and Tcl.

Architecture:
  1. Claude loop calls execute_tool() with a tool name + args
  2. execute_tool() pushes a 'tool_start' event onto the session's EventQueue
  3. The Tcl bridge polls that queue, sees the event, runs the VMD command
  4. The Tcl bridge POSTs tool.command_result back to the Python RPC server
  5. The RPC handler resolves the pending call, which unblocks execute_tool()
  6. execute_tool() returns the result dict to the Claude loop

Two paths share this class:
  * Token-authenticated sessions (the M1 plugin) use the call registry keyed
    by ``call_key``: ``tool.ack {call_key, state}`` answers ``proceed``
    atomically against cancellation; a pickup deadline (45 s) runs until the
    first ack; a ``running`` ack starts the exec deadline (900 s); Stop waits
    ``cancel_grace_s`` for a running command (spec 2d, C2).
  * Tokenless sessions (old plugins) keep today's protocol: ``tool_call_id``,
    one 45 s timeout, ``resolve()``.
"""
from __future__ import annotations

import base64
import collections
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional

from . import tcl_policy
from .image_utils import read_image_as_png_bytes
from .image_scale import make_thumbnail, png_size, to_jpeg

logger = logging.getLogger("vmdai.tool_bridge")

# How long (seconds) to wait for Tcl to execute a tool and post the result.
TOOL_TIMEOUT_SEC = 45

ACK_STATES = ("running", "awaiting_user")
_POLL_S = 0.05
_KEEP_FINISHED = 512
_CHECKOUT_ROOT = str(Path(__file__).resolve().parents[2])

MODEL_OUTPUT_CAP = 6000
MODEL_HEAD_CHARS = 3000
MODEL_TAIL_CHARS = 2500

# Extensions save_path may overwrite without an explicit --force (M1): an
# existing file with any other extension is presumed to be user data, not a
# prior snapshot, and is refused.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif")


@dataclass
class BridgeSession:
    """What the bridge needs to know about the session that owns a call."""
    chat_dir: Optional[Path]
    cwd: str
    authenticated: bool
    snapshot_dir: Path
    exec_timeout_s: Optional[float] = None
    cancel_grace_s: Optional[float] = None


@dataclass
class _PendingCall:
    tool_call_id: str
    tool_name: str
    session_id: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None
    # --- token-session fields (unused on the legacy path) ---
    call_key: str = ""
    request_id: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    chat_dir: Optional[Path] = None
    cwd: str = ""
    snapshot_path: str = ""
    exec_timeout_s: float = 900.0
    started: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "pending"              # pending | awaiting_user | running
    exec_deadline: Optional[float] = None
    cancelled: bool = False
    finished: bool = False              # execute_tool has returned
    raw: Optional[Dict[str, Any]] = None
    late: bool = False


class VmdToolBridge:
    """
    Thread-safe registry of in-flight VMD tool calls.

    One instance lives on RuntimeApp and is shared across all sessions.
    """

    # The loop passes call_key= and request_id= only to bridges whose CLASS
    # declares this (spec 2a); wrappers that delegate via __getattr__ never
    # opt in by accident.
    supports_call_meta = True

    def __init__(
        self,
        pickup_timeout_s: float = 45.0,
        exec_timeout_s: float = 900.0,
        cancel_grace_s: float = 30.0,
        session_lookup: Optional[Callable[[str], Optional[BridgeSession]]] = None,
    ):
        self._lock = threading.Lock()
        self._pending: Dict[str, _PendingCall] = {}
        self._calls: Dict[str, _PendingCall] = {}
        self._finished_order: Deque[str] = collections.deque()
        self.pickup_timeout_s = float(pickup_timeout_s)
        self.exec_timeout_s = float(exec_timeout_s)
        self.cancel_grace_s = float(cancel_grace_s)
        self.session_lookup = session_lookup
        self.on_late_result: Optional[Callable[[str, str, Dict[str, Any]], None]] = None

    def get_pending_session(self, tool_call_id: str,
                            session_id: Optional[str] = None) -> Optional[str]:
        """Return the session_id that owns a pending call, or None if unknown.

        Used by the RPC handler to verify that a tool.command_result POST
        belongs to the session that originated the tool call. ``session_id``
        scopes the compat (call_key-less) lookup to that session (M6).
        """
        tcid = str(tool_call_id or "")
        with self._lock:
            pending = self._pending.get(tcid)
        if pending is None:
            pending = self._token_call_by_tool_call_id(tcid, session_id=session_id)
        return pending.session_id if pending else None

    def get_call_session(self, call_key: str) -> Optional[str]:
        """Return the session_id that owns ``call_key`` (pending or finished)."""
        with self._lock:
            pending = self._calls.get(str(call_key or ""))
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
        call_key: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one VMD tool call through the plugin and return its result dict.

        C1: run_vmd_command is checked by tcl_policy first, for every session;
        a finding returns executed "no" and nothing is ever pushed to VMD.
        """
        sess = self._lookup(session_id)
        if tool_name == "run_vmd_command":
            blocked = self._policy_block(tool_input)
            if blocked is not None:
                return blocked
        if call_key and sess is not None and sess.authenticated:
            return self._execute_token(
                sess,
                session_id=str(session_id or ""),
                tool_call_id=str(tool_call_id or ""),
                tool_name=tool_name,
                tool_input=dict(tool_input or {}),
                session_queue=session_queue,
                cancel_event=cancel_event,
                call_key=str(call_key),
                request_id=str(request_id or ""),
            )
        return self._execute_legacy(
            sess,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            session_queue=session_queue,
            cancel_event=cancel_event,
            timeout=timeout,
            call_key=call_key,
        )

    def _lookup(self, session_id: str) -> Optional[BridgeSession]:
        if self.session_lookup is None:
            return None
        try:
            return self.session_lookup(str(session_id or ""))
        except Exception:
            logger.warning("session_lookup failed for %s", session_id, exc_info=True)
            return None

    def _policy_block(self, tool_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """C1: the blocked result for a critical command, or None when allowed."""
        command = str((tool_input or {}).get("command") or "")
        findings = tcl_policy.check(command, checkout_root=_CHECKOUT_ROOT)
        if not findings:
            return None
        blocked = [{"id": f.id, "word": f.word, "text": f.text} for f in findings]
        logger.info("tcl_policy blocked %s", ",".join(b["id"] for b in blocked))
        result = _empty_result()
        result.update({
            "ok": False,
            "executed": "no",
            "error": tcl_policy.message_for(findings[0]),
            "blocked": blocked,
        })
        return result

    # ---- legacy (tokenless) path ----------------------------------------

    def _execute_legacy(self, sess: Optional[BridgeSession], *, session_id, tool_call_id,
                        tool_name, tool_input, session_queue, cancel_event, timeout, call_key):
        pending = _PendingCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            session_id=str(session_id or ""),
        )
        with self._lock:
            self._pending[tool_call_id] = pending

        try:
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
            logger.debug("tool_start pushed tool=%s id=%s", tool_name, tool_call_id)

            deadline = timeout
            poll_interval = 0.1
            while deadline > 0:
                if cancel_event.is_set():
                    return {"ok": False, "output": "", "error": "cancelled"}
                if pending.done.wait(timeout=poll_interval):
                    break
                deadline -= poll_interval
            else:
                logger.warning("tool timed out tool=%s id=%s", tool_name, tool_call_id)
                return {
                    "ok": False,
                    "output": "",
                    "error": f"VMD tool timed out after {TOOL_TIMEOUT_SEC}s",
                }

            result = pending.result or {}

            # For snapshot tool: read the rendered file and base64-encode it.
            # Old plugins may only use /tmp/vmdai_snap_<tool_call_id>.tga
            # (spec 2d); any other path is rejected, never read or deleted.
            if tool_name == "capture_vmd_snapshot" and result.get("ok"):
                snap_file = str(result.get("snapshot_file") or "")
                if snap_file and _legacy_snapshot_allowed(snap_file, tool_call_id):
                    if os.path.isfile(snap_file):
                        png_bytes = read_image_as_png_bytes(snap_file)
                        if png_bytes:
                            result["image_b64"] = base64.b64encode(png_bytes).decode()
                            result["image_mime"] = "image/png"
                        try:
                            os.unlink(snap_file)
                        except Exception:
                            pass
                elif snap_file:
                    logger.warning("rejected snapshot_file %r for %s", snap_file, tool_call_id)
                    result["ok"] = False
                    result["error"] = ("snapshot file rejected: the plugin may only use "
                                       "/tmp/vmdai_snap_<tool_call_id>.tga")

            if sess is not None and sess.chat_dir is not None:
                # C5: the model sees head + note + tail; the full text is saved.
                _cut_output_in_place(result, sess.chat_dir, str(call_key or tool_call_id))

            return result

        finally:
            with self._lock:
                self._pending.pop(tool_call_id, None)

    # ---- token path ------------------------------------------------------

    def _execute_token(self, sess: BridgeSession, *, session_id, tool_call_id, tool_name,
                       tool_input, session_queue, cancel_event, call_key, request_id):
        exec_s = sess.exec_timeout_s if sess.exec_timeout_s is not None else self.exec_timeout_s
        grace_s = sess.cancel_grace_s if sess.cancel_grace_s is not None else self.cancel_grace_s
        snapshot_path = ""
        if tool_name == "capture_vmd_snapshot":
            snapshot_path = str(Path(sess.snapshot_dir) / ("vmdai_snap_%s.tga" % call_key))
        pending = _PendingCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            session_id=session_id,
            call_key=call_key,
            request_id=request_id,
            tool_input=tool_input,
            chat_dir=sess.chat_dir,
            cwd=sess.cwd,
            snapshot_path=snapshot_path,
            exec_timeout_s=float(exec_s),
        )
        with self._lock:
            self._calls[call_key] = pending

        try:
            session_queue.push(
                "tool_start",
                "message",
                _format_tool_label(tool_name, tool_input),
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "session_id": session_id,
                    "call_key": call_key,
                    "request_id": request_id,
                    "approval": "auto",
                    "snapshot_path": snapshot_path,
                },
            )
            pickup_deadline = time.monotonic() + self.pickup_timeout_s

            while not pending.done.is_set():
                if cancel_event.is_set():
                    return self._cancel(pending, grace_s)
                now = time.monotonic()
                with pending.lock:
                    state = pending.state
                    exec_deadline = pending.exec_deadline
                if state == "pending" and now >= pickup_deadline:
                    out = self._give_up(
                        pending, "no",
                        "VMD did not pick up the command (no reply within %g s)." % self.pickup_timeout_s,
                        expect_state="pending",
                    )
                    if out is not None:
                        return out
                    continue
                if state == "running" and exec_deadline is not None and now >= exec_deadline:
                    out = self._give_up(
                        pending, "unknown",
                        "VMD did not finish the command within %g s; outcome unknown." % exec_s,
                        expect_state="running",
                    )
                    if out is not None:
                        return out
                    continue
                pending.done.wait(timeout=_POLL_S)
            return self._take_result(pending)
        except BaseException:
            # An abandoned call (e.g. session_queue.push raised) must never
            # stay live in the registry: retire it so a later ack() reports
            # it cancelled instead of the caller's exception leaking a
            # call nobody will ever resolve or clean up (M8).
            with pending.lock:
                already_done = pending.done.is_set()
                if not already_done:
                    pending.cancelled = True
            if not already_done:
                self._retire(call_key)
            raise

    def _cancel(self, pending: _PendingCall, grace_s: float) -> Dict[str, Any]:
        """Stop (spec 2d): not acked or awaiting_user -> 'no' at once; running -> grace."""
        with pending.lock:
            if not pending.done.is_set() and pending.state != "running":
                pending.cancelled = True
                return self._finish_without_result(pending, "no", "cancelled")
        if pending.done.wait(timeout=max(0.0, grace_s)):
            return self._take_result(pending)
        out = self._give_up(pending, "unknown", "stopped while running; outcome unknown")
        return out if out is not None else self._take_result(pending)

    def _give_up(self, pending: _PendingCall, executed: str, error: str,
                expect_state: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Stop waiting. Returns None when a result already arrived, the ack
        moved the call on from ``expect_state`` before this ran (I1: the
        pickup deadline must not fire on a call an ack just accepted), or —
        for the exec deadline — a fresh keep-alive ack has since pushed
        ``exec_deadline`` into the future, racing the old deadline.
        """
        with pending.lock:
            if pending.done.is_set() or (expect_state and pending.state != expect_state):
                return None
            if (expect_state == "running" and pending.exec_deadline is not None
                    and pending.exec_deadline > time.monotonic()):
                return None
            pending.cancelled = True
            return self._finish_without_result(pending, executed, error)

    def _finish_without_result(self, pending: _PendingCall, executed: str,
                               error: str) -> Dict[str, Any]:
        """Caller holds ``pending.lock``."""
        pending.finished = True
        self._retire(pending.call_key)
        result = _empty_result()
        result.update({
            "ok": False,
            "executed": executed,
            "error": error,
            "duration_ms": int((time.monotonic() - pending.started) * 1000),
        })
        return result

    def _take_result(self, pending: _PendingCall) -> Dict[str, Any]:
        with pending.lock:
            pending.finished = True
        self._retire(pending.call_key)
        return self._finalize(pending)

    def _retire(self, call_key: str) -> None:
        """Keep finished calls (dedupe, late results), bounded."""
        with self._lock:
            self._finished_order.append(call_key)
            while len(self._finished_order) > _KEEP_FINISHED:
                self._calls.pop(self._finished_order.popleft(), None)

    def _finalize(self, pending: _PendingCall) -> Dict[str, Any]:
        """Turn the posted result into the product result dict (C2, C3).

        A posted ``executed: "no"`` always wins over the ack-derived status
        (C2 refusal, C3 pre-check), and such a call is never ``ok``.
        """
        raw = dict(pending.raw or {})
        executed = "no" if str(raw.get("executed") or "yes") == "no" else "yes"
        ok = bool(raw.get("ok", False)) and executed == "yes"
        output = str(raw.get("output") or "")
        error = str(raw.get("error") or "")
        if executed == "no" and not error:
            error = "not executed"
        duration = raw.get("duration_ms")
        if duration is None:
            duration = int((time.monotonic() - pending.started) * 1000)
        result = _empty_result()
        result.update({
            "ok": ok,
            "output": output,
            "error": error,
            "executed": executed,
            "truncated": bool(raw.get("truncated", False)),
            "duration_ms": int(duration),
            "statements": _statements_from(raw, ok),
            "output_bytes": len(output.encode("utf-8", "replace")),
            "applied_text": str(raw.get("applied_text") or ""),
        })
        if pending.tool_name == "capture_vmd_snapshot":
            self._attach_snapshot(pending, raw, result)
        if pending.chat_dir is not None:
            _cut_output_in_place(result, pending.chat_dir, pending.call_key)
        return result

    def _attach_snapshot(self, pending: _PendingCall, raw: Dict[str, Any],
                         result: Dict[str, Any]) -> None:
        """Read the render the runtime asked for, write image + thumbnail files,
        honour save_path, and delete the temp TGA (spec 2d Snapshot, 2c).

        The runtime reads and deletes ONLY ``pending.snapshot_path``; a posted
        ``snapshot_file`` naming any other path is rejected and left alone (S11).
        """
        expected = pending.snapshot_path
        posted = str(raw.get("snapshot_file") or "")
        try:
            if not result["ok"]:
                # A failed render's own error must survive even when the
                # plugin also posted a foreign path (T03): don't let the
                # rejection message below replace it.
                return
            if posted and os.path.realpath(posted) != os.path.realpath(expected):
                logger.warning("rejected snapshot_file %r (expected %r)", posted, expected)
                result["ok"] = False
                result["error"] = "snapshot file rejected: not the path the runtime chose"
                return
            png = read_image_as_png_bytes(expected) if os.path.isfile(expected) else None
            if not png:
                result["ok"] = False
                result["error"] = "Snapshot file missing or unreadable: %s" % expected
                return
            width, height = png_size(png)
            result["image_b64"] = base64.b64encode(png).decode("ascii")
            result["image_mime"] = "image/png"
            image: Dict[str, Any] = {
                "path": None,
                "thumb_path": None,
                "width": width,
                "height": height,
                "src_width": width,
                "src_height": height,
                "renderer": "TachyonInternal",
            }
            if pending.chat_dir is not None:
                images = Path(pending.chat_dir) / "images"
                try:
                    images.mkdir(parents=True, exist_ok=True)
                    full = images / ("%s.png" % pending.call_key)
                    full.write_bytes(png)
                    image["path"] = str(full)
                    thumb = images / ("%s_thumb.png" % pending.call_key)
                    thumb_png, _thumb_w, _thumb_h = make_thumbnail(png, 256, 192)
                    thumb.write_bytes(thumb_png)
                    image["thumb_path"] = str(thumb)
                except OSError:
                    # The render still reaches the model as image_b64 (M3);
                    # only the on-disk copy is missing.
                    logger.warning("failed to write snapshot image files under %s",
                                   images, exc_info=True)
            result["image"] = image
            note = "Snapshot rendered (%d×%d)." % (width, height)
            save_path = str(pending.tool_input.get("save_path") or "").strip()
            if save_path:
                saved, message = _write_save_path(png, save_path, pending.cwd,
                                                  checkout_root=_CHECKOUT_ROOT)
                if saved is None:
                    result["ok"] = False
                    result["error"] = message
                else:
                    result["saved_path"] = saved
                    note += " " + message
            result["output"] = note
        finally:
            try:
                if expected and os.path.isfile(expected):
                    os.unlink(expected)
            except OSError:
                pass

    def _token_call_by_tool_call_id(self, tool_call_id: str,
                                    session_id: Optional[str] = None) -> Optional[_PendingCall]:
        """Compat: an unresolved token call that a client names by tool_call_id.

        Model-issued tool_call_ids repeat across sessions (``tc_0``,
        ``otc_1``); when the caller knows which session it is acting for,
        scope the match to it so two sessions can never resolve or read
        each other's pending call (M6) — a mismatch is simply "not pending"
        rather than falling back to a stranger's call.
        """
        with self._lock:
            candidates = [
                p for p in reversed(list(self._calls.values()))
                if p.tool_call_id == tool_call_id and not p.finished and p.raw is None
            ]
        if session_id is not None:
            sid = str(session_id)
            return next((p for p in candidates if p.session_id == sid), None)
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    # Called by the RPC handler
    # ------------------------------------------------------------------

    def ack(self, session_id: str, call_key: str, state: str = "running") -> Dict[str, Any]:
        """``tool.ack``: answer ``proceed`` atomically against cancellation (C2).

        Any ack stops the pickup deadline. ``running`` starts the exec
        deadline; ``awaiting_user`` starts none.
        """
        if state not in ACK_STATES:
            raise ValueError("state must be one of %s" % (ACK_STATES,))
        with self._lock:
            pending = self._calls.get(str(call_key or ""))
        if pending is None or pending.session_id != str(session_id or ""):
            return {"proceed": False, "reason": "unknown call"}
        with pending.lock:
            if pending.cancelled or pending.finished:
                return {"proceed": False, "reason": "cancelled"}
            if pending.done.is_set():
                return {"proceed": False, "reason": "already resolved"}
            if state == "running":
                pending.state = "running"
                pending.exec_deadline = time.monotonic() + pending.exec_timeout_s
            else:
                pending.state = "awaiting_user"
        return {"proceed": True}

    def get_call_chat_id(self, call_key: str) -> Optional[str]:
        """The chat_id ``call_key`` was issued in (M7 late-result carry-forward).

        Read from the call registry's ``chat_dir`` (fixed at call-issue
        time), so a caller can route a late result to the chat that
        actually issued the call rather than the session's current chat_id,
        which chat.resume may since have switched away from. None when the
        call is unknown or was issued with no chat (mock/no-store setups).
        """
        with self._lock:
            pending = self._calls.get(str(call_key or ""))
        if pending is None or pending.chat_dir is None:
            return None
        return pending.chat_dir.name

    def post_result(self, session_id: str, params: Dict[str, Any]) -> Dict[str, bool]:
        """``tool.command_result`` by call_key. Returns {accepted, late, duplicate}.

        * The first result for a waiting call resolves it, acked or not: an
          un-acked result (a C2 refusal) counts as pickup.
        * A repeat of an accepted result is a duplicate (the plugin's result
          queue retries until it sees ``accepted``).
        * A result for a call execute_tool already gave up on is accepted as
          late: it is finalised the same way and handed to ``on_late_result``.
        """
        call_key = str(params.get("call_key") or "")
        with self._lock:
            pending = self._calls.get(call_key)
        if pending is None or pending.session_id != str(session_id or ""):
            return {"accepted": False, "late": False, "duplicate": False}
        with pending.lock:
            if pending.raw is not None:
                return {"accepted": True, "late": pending.late, "duplicate": True}
            pending.raw = dict(params)
            if not pending.finished:
                pending.done.set()
                return {"accepted": True, "late": False, "duplicate": False}
            pending.late = True
        late = self._finalize(pending)
        late.update({
            "late": True,
            "request_id": pending.request_id,
            "tool_name": pending.tool_name,
            "chat_dir": str(pending.chat_dir) if pending.chat_dir is not None else None,
        })
        callback = self.on_late_result
        if callback is not None:
            try:
                callback(pending.session_id, call_key, late)
            except Exception:
                logger.warning("on_late_result failed for %s", call_key, exc_info=True)
        return {"accepted": True, "late": True, "duplicate": False}

    def resolve(self, tool_call_id: str, result: Dict[str, Any],
               session_id: Optional[str] = None) -> bool:
        """
        Called when the Tcl bridge POSTs tool.command_result by tool_call_id.
        Unblocks the waiting execute_tool() call.
        Returns True if the call was found, False if it was already gone/timed
        out, or (M6) it belongs to another session than ``session_id``.
        """
        with self._lock:
            pending = self._pending.get(tool_call_id)
        if pending is None:
            token_call = self._token_call_by_tool_call_id(str(tool_call_id or ""), session_id=session_id)
            if token_call is not None:
                with token_call.lock:
                    if token_call.raw is None and not token_call.finished:
                        token_call.raw = dict(result)
                        token_call.done.set()
                        return True
            logger.warning("resolve: unknown tool_call_id=%s (timed out?)", tool_call_id)
            return False
        pending.result = result
        pending.done.set()
        logger.debug("tool resolved id=%s ok=%s", tool_call_id, result.get("ok"))
        return True


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _empty_result() -> Dict[str, Any]:
    """The product result dict with every key present (plan-specific constraint)."""
    return {
        "ok": False, "output": "", "error": "", "executed": "yes",
        "truncated": False, "duration_ms": 0, "statements": None, "blocked": None,
        "output_path": None, "output_bytes": 0, "image": None, "saved_path": None,
        "applied_text": "",
    }


def _statements_from(raw: Dict[str, Any], ok: bool) -> Optional[Dict[str, Any]]:
    """C3: {total, applied, failed} from the posted statement fields, or None."""
    total = raw.get("statements_total")
    if total is None:
        return None
    failed = None
    if not ok and raw.get("failed_index"):
        failed = {
            "index": int(raw["failed_index"]),
            "text": str(raw.get("failed_statement") or ""),
            "error_info": str(raw.get("error_info") or ""),
        }
    return {
        "total": int(total),
        "applied": int(raw.get("statements_applied") or 0),
        "failed": failed,
    }


def _legacy_snapshot_allowed(path: str, tool_call_id: str) -> bool:
    """Old plugins may only post /tmp/vmdai_snap_<tool_call_id>.tga (compared after realpath)."""
    tcid = str(tool_call_id or "")
    if not tcid or any(ch in tcid for ch in "/\\\x00"):
        return False
    allowed = "/tmp/vmdai_snap_%s.tga" % tcid
    return os.path.realpath(path) == os.path.realpath(allowed)


def _write_save_path(png: bytes, save_path: str, cwd: str, *,
                     checkout_root: str = _CHECKOUT_ROOT):
    """Write the save_path deliverable (S10). Returns (absolute path, note) or (None, error).

    Relative paths resolve against the session cwd. JPEG needs Pillow;
    without it the image is written as .png and the note says so. A missing
    directory or a '..' component is refused. So is a destination under a
    protected tree (M1: checked both literally and after realpath, since a
    symlink or a HOME resolved through another symlink can point there
    without the literal path looking protected) or an existing file whose
    extension says it isn't one of ours to overwrite. Nothing is ever
    deleted.
    """
    raw = os.path.expanduser(save_path)
    if ".." in Path(raw).parts:
        return None, "save_path must not contain '..': %s" % save_path
    dest = raw if os.path.isabs(raw) else os.path.join(cwd or os.getcwd(), raw)
    dest = os.path.normpath(dest)
    parent = os.path.dirname(dest) or "."
    if not os.path.isdir(parent):
        return None, "save_path directory does not exist: %s" % parent
    ext = os.path.splitext(dest)[1].lower()
    note = ""
    data = png
    if ext in (".jpg", ".jpeg"):
        jpeg = to_jpeg(png)
        if jpeg is None:
            dest = os.path.splitext(dest)[0] + ".png"
            note = " (JPEG needs Pillow; saved as PNG instead.)"
        else:
            data = jpeg
    real_home = os.path.realpath(os.path.expanduser("~"))
    if (tcl_policy.is_protected_path(dest, checkout_root=checkout_root)
            or tcl_policy.is_protected_path(os.path.realpath(dest),
                                            checkout_root=checkout_root, home=real_home)):
        return None, "save_path is a protected location: %s" % dest
    if os.path.exists(dest) and os.path.splitext(dest)[1].lower() not in _IMAGE_EXTS:
        return None, "save_path would overwrite a file that is not an image: %s" % dest
    try:
        with open(dest, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        return None, "could not write save_path %s: %s" % (dest, exc)
    return dest, "Saved to %s.%s" % (dest, note)


def truncation_note(n_lines: int, n_bytes: int, path: str, executor_cut: bool) -> str:
    """The C5 line that joins head and tail (names the saved file)."""
    kb = max(1, int(round(n_bytes / 1024.0)))
    where = ("Saved text (cut at 1 MB in VMD): %s" % path) if executor_cut else ("Full text: %s" % path)
    return (
        "[output truncated: %d lines, %d KB. %s. Don't print it again: compute what you "
        "need (measure, a narrower selection), or read a slice of that file with Tcl.]"
        % (n_lines, kb, where)
    )


def unsaved_truncation_note(n_lines: int, n_bytes: int, reason: str) -> str:
    """The C5 line used when the full text could not be saved to disk (M3):
    the model still gets head + tail, but no ``output_path`` to read more from."""
    kb = max(1, int(round(n_bytes / 1024.0)))
    return (
        "[output truncated: %d lines, %d KB. The full text could not be saved (%s). "
        "Don't print it again: compute what you need (measure, a narrower selection).]"
        % (n_lines, kb, reason)
    )


def _cut_head(window: str) -> str:
    """Cut the head window at its last newline, else last whitespace, else exactly."""
    pos = window.rfind("\n")
    if pos <= 0:
        pos = max(window.rfind(" "), window.rfind("\t"))
    return window[:pos] if pos > 0 else window


def _cut_tail(window: str) -> str:
    """Start the tail window after its first newline, else first whitespace, else exactly."""
    pos = window.find("\n")
    if 0 <= pos < len(window) - 1:
        return window[pos + 1:]
    candidates = [p for p in (window.find(" "), window.find("\t")) if p >= 0]
    if candidates and min(candidates) < len(window) - 1:
        return window[min(candidates) + 1:]
    return window


def cut_for_model(text: str, *, head: int = MODEL_HEAD_CHARS, tail: int = MODEL_TAIL_CHARS,
                  note: str = "") -> str:
    """Keep the first ``head`` and last ``tail`` characters, each cut at a line
    (else word) boundary inside its window, joined by ``note`` (C5)."""
    if len(text) <= head + tail:
        return text
    head_part = _cut_head(text[:head])
    tail_part = _cut_tail(text[-tail:])
    return head_part + "\n" + note + "\n" + tail_part


def _cut_output_in_place(result: Dict[str, Any], chat_dir: Path, call_key: str) -> None:
    """C5: save output over 6000 chars to outputs/<call_key>.txt and cut the
    model's copy to head + note + tail. Lone surrogates (undecodable text that
    reached the JSON) become '?' so the text is always valid UTF-8."""
    data = str(result.get("output") or "").encode("utf-8", "replace")
    output = data.decode("utf-8")
    result["output"] = output
    result["output_bytes"] = len(data)
    if len(output) <= MODEL_OUTPUT_CAP:
        return
    safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", str(call_key or "call"))
    outputs = Path(chat_dir) / "outputs"
    path = outputs / ("%s.txt" % safe_key)
    n_lines = output.count("\n") + 1
    try:
        outputs.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        # VMD already ran the command; a disk problem here must cut the
        # model's copy same as ever, just without a file to point at (M3).
        note = unsaved_truncation_note(n_lines, len(data), str(exc))
        result["output"] = cut_for_model(output, note=note)
        result["output_path"] = None
        result["truncated"] = True
        return
    executor_cut = bool(result.get("truncated"))
    note = truncation_note(n_lines, len(data), str(path), executor_cut)
    result["output"] = cut_for_model(output, note=note)
    result["output_path"] = str(path)
    result["truncated"] = True


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
