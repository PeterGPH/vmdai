"""settings_store.py - runtime-owned profiles in ~/.vmdai/settings.json (§2f).

Schema (version 1):
  {"version": 1, "active": <name or null>,
   "profiles": {<name>: {"provider", "model", "base_url"?, "key_ref"?, "options": {...}}},
   "reasoning_visible": true, "wiki_enabled": false, "approval_mode": "auto",
   "max_turns": 28, "tool_exec_timeout_s": 900, "cancel_grace_s": 30}

Every write re-reads the file under the flock on ~/.vmdai/.store.lock and
replaces it atomically with mode 0600. A file that does not parse, or whose
version is newer than SETTINGS_VERSION, is never overwritten: settings_source
reports "invalid" or "newer" and writes raise SettingsError("READ_ONLY"). A
file with no version (or version 0) is migrated in place. Profile options
keep unknown keys; LoopOptions.product ignores them. The effective profile
(resolve_profile) follows §7: CLI flag > active profile; VMD_AI_PROVIDER is seed-only and never used live.
Known option keys must have the LoopOptions type (claude_loop.option_type_error); unknown keys are kept.
Stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .locks import store_lock

logger = logging.getLogger("vmdai.settings")

SETTINGS_VERSION = 1
TOP_LEVEL_DEFAULTS: Dict[str, Any] = {
    "reasoning_visible": True,
    "wiki_enabled": False,
    "approval_mode": "auto",
    "max_turns": 28,
    "tool_exec_timeout_s": 900,
    "cancel_grace_s": 30,
}
KNOWN_PROVIDERS = ("anthropic-direct", "openrouter", "ollama", "openai-compatible")
DEFAULT_BASE_URLS: Dict[str, str] = {
    "ollama": "http://localhost:11434",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai-compatible": "http://localhost:8000/v1",
}
DEFAULT_PROFILE_NAMES: Dict[str, str] = {
    "anthropic-direct": "claude",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "openai-compatible": "openai-compatible",
}
DEFAULT_MODELS: Dict[str, str] = {
    "anthropic-direct": "claude-sonnet-4-6",
    "openrouter": "anthropic/claude-sonnet-4.6",
}
DEFAULT_OLLAMA_NUM_CTX = 32768
LOCAL_OLLAMA_PORTS = (11435, 11434)        # the SSH tunnel first, then a local Ollama
SHOW_TIMEOUT_S = 3.0
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ALIASES: Dict[str, str] = {
    "anthropic-direct": "anthropic-direct", "anthropic_api": "anthropic-direct",
    "anthropic-direct-api": "anthropic-direct", "anthropic": "anthropic-direct",
    "openrouter": "openrouter", "claude": "openrouter", "claude-openrouter": "openrouter",
    "ollama": "ollama", "local-ollama": "ollama", "local_ollama": "ollama",
    "openai-compatible": "openai-compatible", "openai_compatible": "openai-compatible",
    "vllm": "openai-compatible",
}


def normalize_provider(name: Any) -> str:
    """Canonical provider name, or '' for anything unknown (including mock)."""
    return _ALIASES.get(str(name or "").strip().lower(), "")


class SettingsError(Exception):
    """A rejected settings change; ``code`` is IN_USE, READ_ONLY, NOT_FOUND or INVALID."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def default_settings() -> Dict[str, Any]:
    data: Dict[str, Any] = {"version": SETTINGS_VERSION, "active": None, "profiles": {}}
    data.update(copy.deepcopy(TOP_LEVEL_DEFAULTS))
    return data


def _with_defaults(data: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(data)
    out.setdefault("active", None)
    if not isinstance(out.get("profiles"), dict):
        out["profiles"] = {}
    for key, value in TOP_LEVEL_DEFAULTS.items():
        out.setdefault(key, copy.deepcopy(value))
    return out


def _check_name(name: Any) -> str:
    text = str(name or "")
    if not PROFILE_NAME_RE.match(text):
        raise SettingsError("INVALID", "profile names are 1-64 letters, digits, '.', '_' or '-'")
    return text


def _clean_profile(profile: Any) -> Dict[str, Any]:
    if not isinstance(profile, dict):
        raise SettingsError("INVALID", "a profile must be an object")
    provider = normalize_provider(profile.get("provider"))
    if not provider:
        raise SettingsError("INVALID", "provider must be one of " + ", ".join(KNOWN_PROVIDERS))
    options = profile.get("options") or {}
    if not isinstance(options, dict):
        raise SettingsError("INVALID", "profile options must be an object")
    from .claude_loop import option_type_error  # late import: claude_loop -> provider_catalog -> settings_store (P04)
    for key, value in options.items():
        problem = option_type_error(str(key), value)
        if problem is not None:
            raise SettingsError("INVALID", "options.%s %s" % (key, problem))
    from .errors import RpcError  # late import: no cycle, but keeps protocol optional at module load
    from .protocol import _as_base_url
    for field, value in (("base_url", profile.get("base_url")), ("options.base_url", options.get("base_url"))):
        if value not in (None, ""):
            try:
                _as_base_url(value)
            except RpcError:
                raise SettingsError("INVALID", "%s must be an http(s) URL" % field)
    out = copy.deepcopy(profile)
    out["provider"] = provider
    out["model"] = str(profile.get("model") or "")
    out["options"] = copy.deepcopy(options)
    if out.get("base_url") in (None, ""):
        out.pop("base_url", None)
    else:
        out["base_url"] = str(out["base_url"]).rstrip("/")
    return out


def checked_setting(data: Mapping[str, Any], name: str) -> Any:
    """``data[name]``, or its default when the value is malformed (M1).

    Guards against a hand-edited settings.json: ``max_turns: null`` would
    otherwise crash the agent-loop build (``int(None)``), and
    ``wiki_enabled: "false"`` is truthy and would silently turn the wiki on.
    """
    default = TOP_LEVEL_DEFAULTS[name]
    value = data.get(name, default)
    try:
        _check_patch({name: value})
    except SettingsError as exc:
        logger.warning("settings.json: %s; using the default %r", exc.message, default)
        return default
    return value


def _check_patch(patch: Any) -> Dict[str, Any]:
    if not isinstance(patch, dict):
        raise SettingsError("INVALID", "patch must be an object")
    out: Dict[str, Any] = {}
    for key, value in patch.items():
        if key not in TOP_LEVEL_DEFAULTS:
            raise SettingsError("INVALID", "unknown setting %r" % key)
        if key in ("reasoning_visible", "wiki_enabled"):
            if not isinstance(value, bool):
                raise SettingsError("INVALID", "%s must be true or false" % key)
        elif key == "approval_mode":
            if value != "auto":
                raise SettingsError("INVALID", "approval_mode must be 'auto' in this version")
        else:
            minimum = 0 if key == "cancel_grace_s" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise SettingsError("INVALID", "%s must be an integer >= %d" % (key, minimum))
        out[key] = value
    return out


class SettingsStore:
    """Reads and writes <home>/.vmdai/settings.json."""

    def __init__(self, home: Optional[str] = None) -> None:
        self.home = Path(home) if home else Path(os.path.expanduser("~"))
        self.root = self.home / ".vmdai"
        self.path = self.root / "settings.json"

    # -- reading ---------------------------------------------------------

    def exists(self) -> bool:
        return self.path.is_file()

    def _read(self) -> Tuple[Dict[str, Any], str]:
        """(data, source); source is file, newer, invalid, default or migrate."""
        if not self.path.is_file():
            return default_settings(), "default"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default_settings(), "invalid"
        if not isinstance(data, dict):
            return default_settings(), "invalid"
        if "profiles" in data and not isinstance(data["profiles"], dict):
            return default_settings(), "invalid"
        version = data.get("version", 0)
        if isinstance(version, bool) or not isinstance(version, int):
            return default_settings(), "invalid"
        if version > SETTINGS_VERSION:
            return _with_defaults(data), "newer"
        if version < SETTINGS_VERSION:
            return data, "migrate"
        return _with_defaults(data), "file"

    @property
    def settings_source(self) -> str:
        _data, source = self._read()
        return "file" if source == "migrate" else source

    def load(self) -> Dict[str, Any]:
        """The settings with defaults filled in; migrates a version-0 file in place."""
        data, source = self._read()
        if source == "migrate":
            with store_lock(self.root):
                data, source = self._read()
                if source == "migrate":
                    data = self._migrate(data)
                    self._write(data)
        return _with_defaults(data)

    def active_profile(self) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        data = self.load()
        name = data.get("active")
        profile = data["profiles"].get(name) if isinstance(name, str) else None
        if not isinstance(profile, dict):
            return None, None
        return name, copy.deepcopy(profile)

    def get_profile(self, name: str) -> Optional[Dict[str, Any]]:
        profile = self.load()["profiles"].get(str(name))
        return copy.deepcopy(profile) if isinstance(profile, dict) else None

    def list_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {name: copy.deepcopy(p) for name, p in self.load()["profiles"].items() if isinstance(p, dict)}

    # -- writing ---------------------------------------------------------

    @staticmethod
    def _migrate(data: Dict[str, Any]) -> Dict[str, Any]:
        out = _with_defaults(data)
        out["version"] = SETTINGS_VERSION
        return out

    def _write(self, data: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
        os.chmod(str(tmp), 0o600)
        os.replace(str(tmp), str(self.path))

    def _mutate(self, change: Callable[[Dict[str, Any]], Any]) -> Any:
        """Read, change and write the file under the store lock.

        ``change`` edits the dict in place and may raise SettingsError, in
        which case nothing is written.
        """
        with store_lock(self.root):
            data, source = self._read()
            if source in ("newer", "invalid"):
                reason = "was written by a newer ChatVMD" if source == "newer" else "is not a valid settings file"
                raise SettingsError("READ_ONLY", "%s %s; it will not be overwritten" % (self.path, reason))
            data = self._migrate(data)
            outcome = change(data)
            self._write(data)
            return outcome

    def save_profile(self, name: str, profile: Dict[str, Any], activate: bool = False) -> Dict[str, Any]:
        name = _check_name(name)
        clean = _clean_profile(profile)

        def change(data: Dict[str, Any]) -> Dict[str, Any]:
            data["profiles"][name] = clean
            if activate:
                data["active"] = name
            return copy.deepcopy(clean)

        return self._mutate(change)

    def delete_profile(self, name: str) -> None:
        def change(data: Dict[str, Any]) -> None:
            if name not in data["profiles"]:
                raise SettingsError("NOT_FOUND", "no profile named %r" % name)
            if data.get("active") == name:
                raise SettingsError("IN_USE", "profile %r is active; activate another profile first" % name)
            del data["profiles"][name]

        self._mutate(change)

    def activate(self, name: str) -> None:
        def change(data: Dict[str, Any]) -> None:
            if name not in data["profiles"]:
                raise SettingsError("NOT_FOUND", "no profile named %r" % name)
            data["active"] = name

        self._mutate(change)

    def patch(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        clean = _check_patch(patch)

        def change(data: Dict[str, Any]) -> Dict[str, Any]:
            data.update(clean)
            return {key: checked_setting(data, key) for key in TOP_LEVEL_DEFAULTS}

        return self._mutate(change)

    def update_profile(self, name: str, *, provider: Optional[str] = None, model: Optional[str] = None,
                       base_url: Optional[str] = None,
                       options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Edit one profile. Options merge key by key, so a model change keeps
        num_ctx unless ``options`` sets it (C7). A provider change resets
        base_url to that provider's default and clears options and key_ref."""
        def change(data: Dict[str, Any]) -> Dict[str, Any]:
            current = data["profiles"].get(name)
            if not isinstance(current, dict):
                raise SettingsError("NOT_FOUND", "no profile named %r" % name)
            updated = copy.deepcopy(current)
            if provider is not None:
                new_provider = normalize_provider(provider)
                if not new_provider:
                    raise SettingsError("INVALID", "provider must be one of " + ", ".join(KNOWN_PROVIDERS))
                if new_provider != normalize_provider(updated.get("provider")):
                    updated["provider"] = new_provider
                    updated["options"] = {}
                    updated.pop("key_ref", None)
                    updated.pop("base_url", None)
                    if new_provider in DEFAULT_BASE_URLS:
                        updated["base_url"] = DEFAULT_BASE_URLS[new_provider]
            if model is not None:
                updated["model"] = str(model)
            if base_url is not None:
                updated["base_url"] = str(base_url)
            if options is not None:
                if not isinstance(options, dict):
                    raise SettingsError("INVALID", "profile options must be an object")
                merged = dict(updated.get("options") or {})
                merged.update(options)
                updated["options"] = merged
            data["profiles"][name] = _clean_profile(updated)
            return copy.deepcopy(data["profiles"][name])

        return self._mutate(change)

    def first_run(self, servers: Sequence[Dict[str, Any]], *, last_provider_path: Optional[str] = None,
                  urlopen: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
        """Create profiles on a machine with no settings.json (§2f First run, C7).

        Each responding Ollama becomes ``ollama-<port>`` with its first model
        that has the tools capability and ``num_ctx = min(32768, context_length)``;
        the first one becomes active. ``last_provider.txt`` (``<provider>\\t<model>``)
        seeds ``claude`` or ``openrouter`` (never active) or picks the model of
        the matching ``ollama-<port>`` profile. Writes nothing when no profile
        was created, so the next start probes again.
        """
        opener = urlopen or _default_urlopen
        created: Dict[str, Dict[str, Any]] = {}
        served: Dict[str, List[str]] = {}
        active: Optional[str] = None
        for server in servers or []:
            base_url = str(server.get("base_url") or "").rstrip("/")
            if not base_url:
                continue
            try:
                profile = profile_from_server(base_url, urlopen=opener, server=server)
            except Exception:
                logger.warning("first run: could not read models from %s", base_url, exc_info=True)
                continue
            if not profile.get("model"):
                continue
            name = "ollama-%d" % _port_of(base_url)
            created[name] = profile
            served[name] = [str(m) for m in server.get("models") or []]
            if active is None:
                active = name
        seed_path = Path(last_provider_path) if last_provider_path else self.root / "last_provider.txt"
        seed = _read_last_provider(seed_path)
        if seed is not None:
            provider, model = seed
            if provider == "anthropic-direct" and "claude" not in created:
                created["claude"] = {"provider": provider, "model": model or DEFAULT_MODELS[provider], "options": {}}
            elif provider == "openrouter" and "openrouter" not in created:
                created["openrouter"] = {"provider": provider, "base_url": DEFAULT_BASE_URLS[provider],
                                         "model": model or DEFAULT_MODELS[provider], "options": {}}
            elif provider == "ollama" and model:
                for name, models in served.items():
                    if model in models:
                        created[name]["model"] = model
                        created[name]["options"]["num_ctx"] = _num_ctx_for(created[name]["base_url"], model, opener)
                        break
        if not created:
            return self.load()

        def change(data: Dict[str, Any]) -> None:
            if data["profiles"]:
                return          # another runtime finished its first run first
            for name, profile in created.items():
                data["profiles"][name] = _clean_profile(profile)
            data["active"] = active

        self._mutate(change)
        return self.load()


def _env_profile(provider: str, env: Mapping[str, str]) -> Dict[str, Any]:
    """A profile built from the environment, for the CLI flag or VMD_AI_PROVIDER."""
    if provider == "ollama":
        host = str(env.get("VMD_AI_OLLAMA_HOST") or env.get("OLLAMA_HOST") or "").strip()
        if host and not host.startswith(("http://", "https://")):
            host = "http://" + host
        return {"provider": "ollama", "base_url": (host or DEFAULT_BASE_URLS["ollama"]).rstrip("/"),
                "model": str(env.get("VMD_AI_OLLAMA_MODEL") or env.get("OLLAMA_MODEL") or ""), "options": {}}
    if provider == "openai-compatible":
        base = str(env.get("VMD_AI_OPENAI_BASE_URL") or DEFAULT_BASE_URLS[provider]).rstrip("/")
        return {"provider": provider, "base_url": base, "model": str(env.get("VMD_AI_MODEL") or ""),
                "options": {}}
    if provider == "openrouter":
        return {"provider": provider, "base_url": DEFAULT_BASE_URLS[provider],
                "model": str(env.get("VMD_AI_MODEL") or DEFAULT_MODELS[provider]), "options": {}}
    return {"provider": "anthropic-direct",
            "model": str(env.get("VMD_AI_MODEL") or env.get("ANTHROPIC_MODEL") or DEFAULT_MODELS["anthropic-direct"]),
            "options": {}}


def resolve_profile(store: SettingsStore, cli_provider: Optional[str],
                    env: Mapping[str, str]) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
    """(name, profile, source) of the effective profile (§7 Precedence).

    source is "cli" (--provider names a profile or a provider), "profile"
    (the active profile) or "none". VMD_AI_PROVIDER is seed-only (§7) and is
    never used live: with no CLI choice and no active profile the result is
    "none", which a v2 chat.send reports as NO_MODEL.
    """
    cli = str(cli_provider or "").strip()
    if cli:
        named = store.get_profile(cli)
        if named is not None:
            return cli, named, "cli"
        provider = normalize_provider(cli)
        if provider:
            return None, _env_profile(provider, env), "cli"
    name, profile = store.active_profile()
    if profile is not None:
        return name, profile, "profile"
    return None, None, "none"


# ---------------------------------------------------------------------------
# First run: probe local Ollama servers (§2f, C7). Only /api/version,
# /api/tags and /api/show are called, never /api/chat or /api/generate.
# ---------------------------------------------------------------------------

def _default_urlopen(request: Any, timeout: Optional[float] = None) -> Any:
    """urllib.request.urlopen, looked up at call time so tests and cassettes can patch it."""
    return urllib.request.urlopen(request, timeout=timeout)


def _http_json(urlopen: Callable[..., Any], method: str, url: str,
               body: Optional[Dict[str, Any]] = None, timeout: float = SHOW_TIMEOUT_S) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8") or "null")


def context_length_from_show(show: Dict[str, Any]) -> Optional[int]:
    """``model_info["<general.architecture>.context_length"]`` from /api/show, or None."""
    info = show.get("model_info") if isinstance(show, dict) else None
    if not isinstance(info, dict):
        return None
    arch = info.get("general.architecture")
    keys = ["%s.context_length" % arch] if arch else []
    keys += sorted(str(k) for k in info if str(k).endswith(".context_length"))
    for key in keys:
        value = info.get(key)
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _capped_num_ctx(show: Dict[str, Any]) -> int:
    context_length = context_length_from_show(show)
    return min(DEFAULT_OLLAMA_NUM_CTX, context_length) if context_length else DEFAULT_OLLAMA_NUM_CTX


def _show(urlopen: Callable[..., Any], base_url: str, model: str) -> Dict[str, Any]:
    try:
        show = _http_json(urlopen, "POST", base_url + "/api/show", {"model": model})
    except Exception:
        return {}
    return show if isinstance(show, dict) else {}


def _num_ctx_for(base_url: str, model: str, urlopen: Callable[..., Any]) -> int:
    return _capped_num_ctx(_show(urlopen, base_url, model))


def _tag_names(tags: Any) -> List[str]:
    models = tags.get("models") if isinstance(tags, dict) else None
    names = []
    for tag in models or []:
        if isinstance(tag, dict) and (tag.get("name") or tag.get("model")):
            names.append(str(tag.get("name") or tag.get("model")))
    return names


def _port_of(base_url: str) -> int:
    try:
        return int(urllib.parse.urlsplit(base_url).port or 11434)
    except ValueError:
        return 11434


def profile_from_server(base_url: str, *, urlopen: Callable[..., Any],
                        server: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """An ``ollama`` profile for one server: its first model with the tools
    capability (else its first model) and ``num_ctx = min(32768, context_length)``
    from /api/show, or 32768 when the length is missing (C7)."""
    base = str(base_url).rstrip("/")
    if server is not None and server.get("models") is not None:
        names = [str(m) for m in server["models"] if m]
    else:
        names = _tag_names(_http_json(urlopen, "GET", base + "/api/tags"))
    chosen, chosen_show = "", {}
    for name in names:
        show = _show(urlopen, base, name)
        if not chosen:
            chosen, chosen_show = name, show
        if "tools" in (show.get("capabilities") or []):
            chosen, chosen_show = name, show
            break
    return {"provider": "ollama", "base_url": base, "model": chosen,
            "options": {"num_ctx": _capped_num_ctx(chosen_show)}}


def probe_local_ollama(ports: Sequence[int] = LOCAL_OLLAMA_PORTS, timeout: float = 0.3) -> List[Dict[str, Any]]:
    """Ask 127.0.0.1:<port>/api/version on each port, in order, ``timeout`` s each.

    A responder is listed as {base_url, version, models}; a refused, reset
    or silent port is skipped, so a stale tunnel costs about ``timeout``.
    """
    servers: List[Dict[str, Any]] = []
    for port in ports:
        base_url = "http://127.0.0.1:%d" % int(port)
        try:
            payload = _http_json(_default_urlopen, "GET", base_url + "/api/version", timeout=timeout)
        except Exception:
            continue
        if not isinstance(payload, dict) or "version" not in payload:
            continue
        try:
            models = _tag_names(_http_json(_default_urlopen, "GET", base_url + "/api/tags", timeout=SHOW_TIMEOUT_S))
        except Exception:
            models = []
        servers.append({"base_url": base_url, "version": str(payload["version"]), "models": models})
    return servers


def _read_last_provider(path: Path) -> Optional[Tuple[str, str]]:
    """(provider, model) from the plugin's last_provider.txt, or None."""
    try:
        line = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    provider, _tab, model = line.partition("\t")
    provider = normalize_provider(provider)
    return (provider, model.strip()) if provider else None
