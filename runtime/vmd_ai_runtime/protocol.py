from __future__ import annotations

from typing import Any, Dict

from .constants import CONVERSATION_MODES
from .errors import RpcError


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise RpcError("INVALID_PARAMS", "params must be an object", {"type": str(type(value))})


def _as_str(value: Any, field: str, required: bool = True) -> str:
    if value is None:
        if required:
            raise RpcError("INVALID_PARAMS", f"{field} is required")
        return ""
    text = str(value).strip()
    if required and not text:
        raise RpcError("INVALID_PARAMS", f"{field} is required")
    return text


def _as_int(value: Any, field: str, minimum: int = 0, default: int = 0) -> int:
    if value is None:
        return default
    try:
        out = int(value)
    except Exception:
        raise RpcError("INVALID_PARAMS", f"{field} must be an integer")
    if out < minimum:
        raise RpcError("INVALID_PARAMS", f"{field} must be >= {minimum}")
    return out


def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = _as_dict(payload)
    method = _as_str(body.get("method"), "method")
    params = _as_dict(body.get("params") or {})
    req_id = body.get("id")
    return {"method": method, "params": params, "id": req_id}


def validate_method_params(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    p = _as_dict(params)

    if method == "session.start":
        return {
            "cwd": _as_str(p.get("cwd") or ".", "cwd", required=False) or ".",
            "ui_mode": _as_str(p.get("ui_mode") or "qt", "ui_mode", required=False) or "qt",
            "client_version": _as_str(p.get("client_version") or "dev", "client_version", required=False) or "dev",
            "platform": _as_str(p.get("platform") or "unknown", "platform", required=False) or "unknown",
        }

    if method == "session.stop":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "chat.send":
        conversation_mode = _as_str(p.get("conversation_mode") or "local_first", "conversation_mode", required=False)
        if conversation_mode not in CONVERSATION_MODES:
            raise RpcError("INVALID_PARAMS", "conversation_mode is invalid", {"allowed": list(CONVERSATION_MODES)})
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_str(p.get("chat_id"), "chat_id", required=False),
            "text": _as_str(p.get("text"), "text"),
            "model": _as_str(p.get("model") or "", "model", required=False),
            "mode": _as_str(p.get("mode") or "work", "mode", required=False),
            "conversation_mode": conversation_mode,
        }

    if method == "chat.cancel":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "request_id": _as_str(p.get("request_id") or "", "request_id", required=False),
        }

    if method == "chat.events.poll":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "after_seq": _as_int(p.get("after_seq"), "after_seq", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=50),
        }

    if method == "chat.history.list":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "offset": _as_int(p.get("offset"), "offset", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=20),
        }

    if method == "chat.history.get":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_str(p.get("chat_id"), "chat_id"),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=200),
        }

    if method == "chat.resume":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_str(p.get("chat_id"), "chat_id"),
        }

    if method == "settings.get":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "settings.set":
        patch = _as_dict(p.get("patch") or {})
        return {"session_id": _as_str(p.get("session_id"), "session_id"), "patch": patch}

    if method == "provider.set":
        # Posted by the Tcl UI when the user changes the provider
        # dropdown. The runtime rebuilds its provider + claude_loop in
        # place; model is optional and just updates settings.model.
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider":   _as_str(p.get("provider"), "provider"),
            "model":      _as_str(p.get("model") or "", "model", required=False),
        }

    if method in ("keys.save", "keys.test"):
        out = {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider": _as_str(p.get("provider"), "provider"),
        }
        if method == "keys.save":
            out["key"] = _as_str(p.get("key"), "key")
        return out

    if method == "tool.run_vmd_command":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "command": _as_str(p.get("command"), "command"),
            "cwd": _as_str(p.get("cwd") or "", "cwd", required=False),
        }

    if method == "tool.capture_snapshot":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "width": _as_int(p.get("width"), "width", minimum=1, default=1024),
            "height": _as_int(p.get("height"), "height", minimum=1, default=768),
            "include_state": bool(p.get("include_state", True)),
        }

    if method == "tool.command_result":
        # Posted by the Tcl bridge after executing a VMD tool call.
        # tool_call_id must match a pending call in VmdToolBridge.
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "tool_call_id": _as_str(p.get("tool_call_id"), "tool_call_id"),
            "ok": bool(p.get("ok", False)),
            "output": _as_str(p.get("output") or "", "output", required=False),
            "error": _as_str(p.get("error") or "", "error", required=False),
            # snapshot_file: local path written by VMD's render command.
            # Python runtime reads this file, encodes as PNG, then discards it.
            "snapshot_file": _as_str(p.get("snapshot_file") or "", "snapshot_file", required=False),
        }

    raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")
