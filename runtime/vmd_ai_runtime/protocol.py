from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Optional

from .constants import CONVERSATION_MODES
from .errors import RpcError

# Chat ids are minted as chat_<12 hex> (store.py). Anything else is refused
# before it can reach a filesystem path (§2e Input validation).
CHAT_ID_RE = re.compile(r"chat_[0-9a-f]{12}")

# Display-event protocols a client may ask for in session.start (§2c).
EVENT_PROTOCOLS = (1, 2)

# M2 long-poll (§2d): chat.events.poll holds the request at most this long.
MAX_WAIT_MS = 2000

# session.start vmd_env (C6): at most these four string fields, 64 chars each.
VMD_ENV_KEYS = ("vmd_version", "arch", "tcl_patchlevel", "tk_patchlevel")
VMD_ENV_MAX_CHARS = 64


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


def _as_opt_int(value: Any, field: str) -> Optional[int]:
    """An optional non-negative int: None when absent."""
    if value is None or value == "":
        return None
    return _as_int(value, field, minimum=0)


def _as_raw_str(value: Any) -> str:
    """Exact text, not stripped: applied_text must be a source prefix (C3)."""
    return "" if value is None else str(value)


def _first_lines(text: str, lines: int, limit: int) -> str:
    """The first ``lines`` lines of ``text``, at most ``limit`` characters."""
    return "\n".join(text.splitlines()[:lines])[:limit]


def _as_chat_id(value: Any, field: str = "chat_id", required: bool = True) -> str:
    text = _as_str(value, field, required=required)
    if text and CHAT_ID_RE.fullmatch(text) is None:
        raise RpcError(
            "INVALID_PARAMS",
            f"{field} is invalid",
            {"pattern": "^chat_[0-9a-f]{12}$"},
        )
    return text


def _sanitize_vmd_env(value: Any) -> Optional[Dict[str, str]]:
    """Keep the four known vmd_env fields as strings of at most 64 chars (C6)."""
    if not isinstance(value, dict):
        return None
    out: Dict[str, str] = {}
    for key in VMD_ENV_KEYS:
        raw = value.get(key)
        if raw is None or isinstance(raw, (dict, list, tuple, bool)):
            continue
        text = str(raw).strip()[:VMD_ENV_MAX_CHARS]
        if text:
            out[key] = text
    return out or None


_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _as_base_url(value: Any) -> str:
    """'' when absent; otherwise an http(s) URL with a host, at most 512 characters."""
    text = _as_str(value, "base_url", required=False)
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    if (parts.scheme not in ("http", "https") or not parts.netloc or len(text) > 512
            or any(ch.isspace() for ch in text)):
        raise RpcError("INVALID_PARAMS", "base_url must be an http(s) URL", {"base_url": text[:80]})
    return text


def _as_optional_dict(value: Any, field: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RpcError("INVALID_PARAMS", f"{field} must be an object")
    return value


def _as_profile_name(value: Any) -> str:
    text = _as_str(value, "profile", required=False)
    if text and not _PROFILE_NAME_RE.match(text):
        raise RpcError("INVALID_PARAMS", "profile must be 1-64 letters, digits, '.', '_' or '-'")
    return text


def _as_profile_key(value: Any) -> str:
    """A required profile name: 1-64 letters, digits, '.', '_' or '-' (profiles.*)."""
    text = _as_str(value, "name")
    if not _PROFILE_NAME_RE.match(text):
        raise RpcError("INVALID_PARAMS", "name must be 1-64 letters, digits, '.', '_' or '-'",
                       {"name": text[:80]})
    return text


def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = _as_dict(payload)
    method = _as_str(body.get("method"), "method")
    params = _as_dict(body.get("params") or {})
    req_id = body.get("id")
    return {"method": method, "params": params, "id": req_id}


def validate_method_params(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    p = _as_dict(params)

    if method == "session.start":
        out = {
            "cwd": _as_str(p.get("cwd") or ".", "cwd", required=False) or ".",
            "ui_mode": _as_str(p.get("ui_mode") or "qt", "ui_mode", required=False) or "qt",
            "client_version": _as_str(p.get("client_version") or "dev", "client_version", required=False) or "dev",
            "platform": _as_str(p.get("platform") or "unknown", "platform", required=False) or "unknown",
        }
        # New params are passed through only when present, so a tokenless
        # client gets exactly today's dict.
        if p.get("launch_token") not in (None, ""):
            out["launch_token"] = _as_str(p.get("launch_token"), "launch_token")
        if p.get("event_protocol") is not None:
            event_protocol = _as_int(p.get("event_protocol"), "event_protocol", minimum=1)
            if event_protocol not in EVENT_PROTOCOLS:
                raise RpcError(
                    "INVALID_PARAMS",
                    "event_protocol must be 1 or 2",
                    {"allowed": list(EVENT_PROTOCOLS)},
                )
            out["event_protocol"] = event_protocol
        vmd_env = _sanitize_vmd_env(p.get("vmd_env"))
        if vmd_env is not None:
            out["vmd_env"] = vmd_env
        return out

    if method == "runtime.shutdown":
        return {"launch_token": _as_str(p.get("launch_token"), "launch_token")}

    if method == "session.stop":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "chat.send":
        conversation_mode = _as_str(p.get("conversation_mode") or "local_first", "conversation_mode", required=False)
        if conversation_mode not in CONVERSATION_MODES:
            raise RpcError("INVALID_PARAMS", "conversation_mode is invalid", {"allowed": list(CONVERSATION_MODES)})
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id", required=False),
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
        out = {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "after_seq": _as_int(p.get("after_seq"), "after_seq", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=50),
        }
        # M2 long-poll (§2d): passed through only when present, so a v1
        # short-poll gets exactly today's params; clamped to 2000 ms.
        if p.get("wait_ms") is not None:
            out["wait_ms"] = min(_as_int(p.get("wait_ms"), "wait_ms", minimum=0, default=0), MAX_WAIT_MS)
        return out

    if method == "chat.history.list":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "offset": _as_int(p.get("offset"), "offset", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=20),
        }

    if method == "chat.history.get":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id"),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=200),
        }

    if method == "chat.resume":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id"),
        }

    if method == "settings.get":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "settings.set":
        patch = _as_dict(p.get("patch") or {})
        return {"session_id": _as_str(p.get("session_id"), "session_id"), "patch": patch}

    if method == "provider.set":
        # {provider, model} is today's ui.tcl call; base_url, options and
        # profile need a token session (checked in app.py, §2e).
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider":   _as_str(p.get("provider"), "provider"),
            "model":      _as_str(p.get("model") or "", "model", required=False),
            "base_url":   _as_base_url(p.get("base_url")),
            "options":    _as_optional_dict(p.get("options"), "options"),
            "profile":    _as_profile_name(p.get("profile")),
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

    if method == "tool.ack":
        # Posted by the M1 executor before it runs a tool_start (C2).
        state = _as_str(p.get("state") or "running", "state", required=False)
        if state not in ("running", "awaiting_user"):
            raise RpcError(
                "INVALID_PARAMS",
                "state must be 'running' or 'awaiting_user'",
                {"allowed": ["running", "awaiting_user"]},
            )
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "call_key": _as_str(p.get("call_key"), "call_key"),
            "state": state,
        }

    if method == "tool.command_result":
        # Posted by the Tcl bridge after executing a VMD tool call. Token
        # sessions name the call by call_key (spec 2d, C2, C3); tokenless
        # sessions keep tool_call_id, which must match a pending call.
        call_key = _as_str(p.get("call_key") or "", "call_key", required=False)
        executed = _as_str(p.get("executed") or "yes", "executed", required=False)
        if executed not in ("yes", "no"):
            raise RpcError("INVALID_PARAMS", "executed must be 'yes' or 'no'",
                           {"allowed": ["yes", "no"]})
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "tool_call_id": _as_str(p.get("tool_call_id"), "tool_call_id", required=not call_key),
            "ok": bool(p.get("ok", False)),
            "output": _as_str(p.get("output") or "", "output", required=False),
            "error": _as_str(p.get("error") or "", "error", required=False),
            # snapshot_file: local path written by VMD's render command. The
            # runtime reads and deletes it only if it is the path it chose.
            "snapshot_file": _as_str(p.get("snapshot_file") or "", "snapshot_file", required=False),
            "call_key": call_key,
            "executed": executed,
            "statements_total": _as_opt_int(p.get("statements_total"), "statements_total"),
            "statements_applied": _as_opt_int(p.get("statements_applied"), "statements_applied"),
            "failed_index": _as_opt_int(p.get("failed_index"), "failed_index"),
            "failed_statement": _as_str(
                p.get("failed_statement") or "", "failed_statement", required=False)[:200],
            "error_info": _first_lines(_as_raw_str(p.get("error_info")), 3, 500),
            "applied_text": _as_raw_str(p.get("applied_text")),
            "duration_ms": _as_opt_int(p.get("duration_ms"), "duration_ms"),
            "truncated": bool(p.get("truncated", False)),
        }

    if method == "runtime.info":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "session.set_cwd":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "cwd": _as_str(p.get("cwd"), "cwd"),
        }

    if method == "models.list":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider": _as_str(p.get("provider") or "", "provider", required=False),
            "base_url": _as_base_url(p.get("base_url")),
        }

    if method == "provider.test":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider": _as_str(p.get("provider") or "", "provider", required=False),
            "base_url": _as_base_url(p.get("base_url")),
            "model": _as_str(p.get("model") or "", "model", required=False),
        }

    # ---- profiles.* (§3; the M2 settings dialog; token sessions only, checked in app.py) ----

    if method == "profiles.list":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method in ("profiles.delete", "profiles.activate"):
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "name": _as_profile_key(p.get("name")),
        }

    if method == "profiles.save":
        profile = p.get("profile")
        if not isinstance(profile, dict):
            raise RpcError("INVALID_PARAMS", "profile must be an object")
        activate = p.get("activate", False)
        if not isinstance(activate, bool):
            raise RpcError("INVALID_PARAMS", "activate must be true or false")
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "name": _as_profile_key(p.get("name")),
            "profile": profile,
            "activate": activate,
        }

    raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")
