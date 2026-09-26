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
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .locks import store_lock

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
    out = copy.deepcopy(profile)
    out["provider"] = provider
    out["model"] = str(profile.get("model") or "")
    out["options"] = copy.deepcopy(options)
    if out.get("base_url") in (None, ""):
        out.pop("base_url", None)
    else:
        out["base_url"] = str(out["base_url"]).rstrip("/")
    return out


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
                reason = "was written by a newer ChatVMD" if source == "newer" else "is not valid JSON"
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
            return {key: data.get(key, TOP_LEVEL_DEFAULTS[key]) for key in TOP_LEVEL_DEFAULTS}

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
