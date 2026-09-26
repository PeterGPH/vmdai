"""provider_catalog.py - model catalogues, connection tests and Ollama probes.

Only these Ollama endpoints are called: /api/version, /api/tags, /api/show
and /api/ps (never /api/chat or /api/generate). OpenAI-compatible servers and
OpenRouter are asked for GET <base>/models. Every request goes through
``urllib.request.urlopen`` by attribute access, so tests and the cassette
fake (C9) can serve it. Caches are keyed by base_url and emptied by
clear_caches(); ``_now`` is the clock tests patch.

Numbers (§2a, §2f): /api/version has a 2 s timeout and is cached 30 s;
/api/ps has a 2 s timeout and is never cached; models.list and provider.test
probes use 3 s; catalogues and /api/show results are cached 60 s.
Stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import copy
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .settings_store import DEFAULT_BASE_URLS, context_length_from_show, normalize_provider

_now = time.monotonic

CATALOG_TTL_S = 60.0
VERSION_TTL_S = 30.0
PROBE_TIMEOUT_S = 3.0
PREFLIGHT_TIMEOUT_S = 2.0
OLLAMA_LOCAL_PORT = 11434
ANTHROPIC_STATIC_MODELS = ("claude-sonnet-4-6", "claude-sonnet-4-5")
UNREACHABLE_CASES = ("refused", "reset", "timeout")
NO_TOOLS_HINT = ("This model does not advertise tool support. ChatVMD needs tools to run VMD "
                 "commands; choose a model with the tools capability.")

_lock = threading.Lock()
_version_cache: Dict[str, Tuple[float, str]] = {}
_tags_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_show_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_catalog_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def clear_caches() -> None:
    """Forget every cached version, tag list, /api/show result and catalogue."""
    with _lock:
        _version_cache.clear()
        _tags_cache.clear()
        _show_cache.clear()
        _catalog_cache.clear()


def _base(base_url: Optional[str], provider: str = "ollama") -> str:
    return str(base_url or DEFAULT_BASE_URLS.get(provider) or "").strip().rstrip("/")


def _fresh(entry: Optional[Tuple[float, Any]], ttl: float) -> bool:
    return entry is not None and (_now() - entry[0]) < ttl


def _request_json(method: str, url: str, *, body: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None, timeout: float = PROBE_TIMEOUT_S) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    all_headers = {"Accept": "application/json"}
    if data is not None:
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8") or "null")


def _auth_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": "Bearer " + api_key} if api_key else {}


def _describe(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    text = str(reason if reason is not None else exc).strip()
    return text or exc.__class__.__name__


def _elapsed_ms(t0: float) -> int:
    return int(round((time.monotonic() - t0) * 1000.0))


# -- Ollama probes ----------------------------------------------------------

def ollama_version(base_url: str, timeout: float = PREFLIGHT_TIMEOUT_S) -> str:
    """GET /api/version, cached 30 s per base_url. Raises the transport error."""
    base = _base(base_url)
    with _lock:
        entry = _version_cache.get(base)
    if _fresh(entry, VERSION_TTL_S):
        return entry[1]
    payload = _request_json("GET", base + "/api/version", timeout=timeout)
    version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
    with _lock:
        _version_cache[base] = (_now(), version)
    return version


def ollama_ps(base_url: str, timeout: float = PREFLIGHT_TIMEOUT_S) -> List[Dict[str, Any]]:
    """GET /api/ps (loaded models); never cached. Raises the transport error."""
    payload = _request_json("GET", _base(base_url) + "/api/ps", timeout=timeout)
    models = payload.get("models") if isinstance(payload, dict) else None
    return [m for m in models or [] if isinstance(m, dict)]


def _ollama_tags(base: str, timeout: float) -> List[Dict[str, Any]]:
    payload = _request_json("GET", base + "/api/tags", timeout=timeout)
    models = payload.get("models") if isinstance(payload, dict) else None
    tags = [m for m in models or [] if isinstance(m, dict)]
    with _lock:
        _tags_cache[base] = (_now(), tags)
    return tags


def ollama_show(base_url: str, model: str, timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """POST /api/show {model}, cached 60 s per (base_url, model). Raises the transport error."""
    base = _base(base_url)
    key = (base, str(model))
    with _lock:
        entry = _show_cache.get(key)
    if _fresh(entry, CATALOG_TTL_S):
        return copy.deepcopy(entry[1])
    payload = _request_json("POST", base + "/api/show", body={"model": str(model)}, timeout=timeout)
    show = payload if isinstance(payload, dict) else {}
    with _lock:
        _show_cache[key] = (_now(), show)
    return copy.deepcopy(show)


def model_capabilities(show: Dict[str, Any]) -> Dict[str, bool]:
    """tools/vision/thinking from /api/show; a ``thinking`` object wins over the list (§2f)."""
    if not isinstance(show, dict):
        show = {}
    caps = [str(c) for c in show.get("capabilities") or []]
    thinking_field = show.get("thinking")
    if isinstance(thinking_field, bool):
        thinking = thinking_field
    elif isinstance(thinking_field, dict):
        thinking = bool(thinking_field.get("supported", True))
    else:
        thinking = "thinking" in caps
    return {"tools": "tools" in caps, "vision": "vision" in caps, "thinking": thinking}


def cached_tag_digest(base_url: str, model: str) -> Optional[str]:
    """The digest of ``model`` from a /api/tags answer seen in the last 60 s, else None."""
    with _lock:
        entry = _tags_cache.get(_base(base_url))
    if not _fresh(entry, CATALOG_TTL_S):
        return None
    for tag in entry[1]:
        if model in (tag.get("name"), tag.get("model")):
            digest = tag.get("digest")
            return str(digest) if digest else None
    return None


# -- Unreachable classification (§2f) -----------------------------------------

def classify_unreachable(exc: BaseException) -> Optional[str]:
    """'refused', 'reset' or 'timeout' for a dead server; None for anything else."""
    reason: Any = exc
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        reason = exc.reason
    if isinstance(reason, ConnectionRefusedError):
        return "refused"
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                           http.client.RemoteDisconnected, http.client.BadStatusLine)):
        return "reset"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    return None


def unreachable_hint(base_url: str, case: str) -> str:
    """The user-facing hint for one of the three unreachable cases (§2f table)."""
    raw = str(base_url or "").strip()
    parts = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
    host = parts.hostname or "127.0.0.1"
    try:
        port = parts.port or OLLAMA_LOCAL_PORT
    except ValueError:
        port = OLLAMA_LOCAL_PORT
    local = host in ("127.0.0.1", "localhost", "::1")
    tunnel = local and port != OLLAMA_LOCAL_PORT
    where = "%s:%d" % (host, port)
    if case == "refused":
        if tunnel:
            return "Nothing is listening on %s. Is the SSH tunnel up?" % where
        if local:
            return "Nothing is listening on %s. Is `ollama serve` running?" % where
        return "Nothing is listening on %s. Is `ollama serve` running on %s?" % (where, host)
    if case == "reset":
        if tunnel:
            return ("The tunnel on :%d is up, but Ollama on the GPU server is not answering. "
                    "Start `ollama serve` there." % port)
        return "%s accepted the connection but Ollama did not answer. Restart `ollama serve`." % where
    if case == "timeout":
        if tunnel:
            return "No reply from :%d within 2 s. The tunnel may be stale; restart it." % port
        return "No reply from %s within 2 s. Ollama may be stuck; restart `ollama serve`." % where
    raise ValueError("case must be one of " + ", ".join(UNREACHABLE_CASES))


# -- models.list ---------------------------------------------------------------

def _ollama_catalog(base: str, timeout: float) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    for tag in _ollama_tags(base, timeout):
        name = str(tag.get("name") or tag.get("model") or "")
        if not name:
            continue
        entry: Dict[str, Any] = {"id": name, "label": name}
        if isinstance(tag.get("size"), int):
            entry["size"] = tag["size"]
        try:
            show = ollama_show(base, name, timeout)
        except Exception:
            show = None
        if show is not None:
            entry["capabilities"] = model_capabilities(show)
            context_length = context_length_from_show(show)
            if context_length:
                entry["context_length"] = context_length
        models.append(entry)
    return models


def _openai_catalog(base: str, api_key: str, timeout: float) -> List[Dict[str, Any]]:
    payload = _request_json("GET", base + "/models", headers=_auth_headers(api_key), timeout=timeout)
    data = payload.get("data") if isinstance(payload, dict) else None
    models: List[Dict[str, Any]] = []
    for item in data or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        entry: Dict[str, Any] = {"id": str(item["id"]), "label": str(item.get("name") or item["id"])}
        if isinstance(item.get("context_length"), int):
            entry["context_length"] = item["context_length"]
        models.append(entry)
    return models


def list_models(provider: str, base_url: Optional[str], *, api_key: str = "",
                timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """{models:[{id,label,size?,capabilities?,context_length?}], source, error?, hint?}."""
    name = normalize_provider(provider)
    if name == "anthropic-direct":
        return {"models": [{"id": m, "label": m} for m in ANTHROPIC_STATIC_MODELS], "source": "static"}
    if name not in ("ollama", "openai-compatible", "openrouter"):
        return {"models": [], "source": "none", "error": "unknown provider %r" % (provider or "")}
    base = _base(base_url, name)
    key = (name, base)
    with _lock:
        entry = _catalog_cache.get(key)
    if _fresh(entry, CATALOG_TTL_S):
        cached = copy.deepcopy(entry[1])
        cached["source"] = "cache"
        return cached
    try:
        models = _ollama_catalog(base, timeout) if name == "ollama" else _openai_catalog(base, api_key, timeout)
    except Exception as exc:
        out: Dict[str, Any] = {"models": [], "source": "error", "error": _describe(exc)}
        case = classify_unreachable(exc)
        if case is not None and name == "ollama":
            out["hint"] = unreachable_hint(base, case)
        return out
    result = {"models": models, "source": "server"}
    with _lock:
        _catalog_cache[key] = (_now(), copy.deepcopy(result))
    return result


# -- provider.test -------------------------------------------------------------

def _test_ollama_model(base: str, model: str, timeout: float, out: Dict[str, Any]) -> None:
    if not model:
        out["ok"] = True
        return
    try:
        tags = _ollama_tags(base, timeout)
        loaded = ollama_ps(base, timeout)
    except Exception as exc:
        out["error"] = _describe(exc)
        return
    out["model_present"] = any(model in (t.get("name"), t.get("model")) for t in tags)
    out["loaded"] = any(model in (p.get("name"), p.get("model")) for p in loaded)
    if not out["model_present"]:
        out["error"] = "Model %s is not on this server" % model
        out["hint"] = "ollama pull %s" % model
        return
    try:
        caps = model_capabilities(ollama_show(base, model, timeout))
    except Exception:
        caps = {}
    out["capabilities"] = caps
    out["ok"] = True
    if caps and not caps.get("tools"):
        out["hint"] = NO_TOOLS_HINT


def test_provider(provider: str, base_url: Optional[str], model: str, *, api_key: str = "",
                  timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """{ok, reachable, latency_ms, model_present, loaded, capabilities, version?, error?, hint?}.

    ``version`` is the Ollama server version from /api/version (Ollama only)."""
    name = normalize_provider(provider)
    model = str(model or "").strip()
    out: Dict[str, Any] = {"ok": False, "reachable": False, "latency_ms": None,
                           "model_present": None, "loaded": None, "capabilities": {}}
    if name == "anthropic-direct":
        out.update(ok=bool(api_key), reachable=None)
        if api_key:
            out["capabilities"] = {"tools": True, "vision": True, "thinking": False}
        else:
            out["error"] = "No Anthropic API key"
            out["hint"] = "Set ANTHROPIC_API_KEY, or save a key with keys.save."
        return out
    if name not in ("ollama", "openai-compatible", "openrouter"):
        out["error"] = "unknown provider %r" % (provider or "")
        return out
    base = _base(base_url, name)
    t0 = time.monotonic()
    try:
        if name == "ollama":
            payload = _request_json("GET", base + "/api/version", timeout=timeout)
            version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
            with _lock:
                _version_cache[base] = (_now(), version)
        else:
            payload = _request_json("GET", base + "/models", headers=_auth_headers(api_key), timeout=timeout)
    except urllib.error.HTTPError as exc:
        out.update(reachable=True, latency_ms=_elapsed_ms(t0), error="HTTP %d from %s" % (exc.code, base))
        if exc.code in (401, 403):
            out["hint"] = "The server rejected the API key."
        return out
    except Exception as exc:
        out["error"] = _describe(exc)
        case = classify_unreachable(exc)
        if case is not None and name == "ollama":
            out["hint"] = unreachable_hint(base, case)
        elif case is not None:
            out["hint"] = "Could not reach %s. Check that the server is running." % base
        return out
    out.update(reachable=True, latency_ms=_elapsed_ms(t0))
    if name == "ollama":
        if version:
            # Part B V4 Test connection: "Connected · 212 ms · Ollama <version>".
            out["version"] = version
        _test_ollama_model(base, model, timeout, out)
        return out
    data = payload.get("data") if isinstance(payload, dict) else None
    ids = [str(d.get("id")) for d in data or [] if isinstance(d, dict) and d.get("id")]
    out["model_present"] = (model in ids) if model else None
    out["ok"] = bool(out["model_present"]) if model else True
    if model and not out["model_present"]:
        out["error"] = "Model %s is not served by %s" % (model, base)
    return out
