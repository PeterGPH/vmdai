from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


# Map a provider key to the env var the rest of the runtime reads from.
#
# Keeping this map central means a single edit adds support for a new
# provider; nothing in provider.py / claude_loop.py has to learn about
# keyring directly.
_PROVIDER_ENV: Dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai-compatible": "VMD_AI_OPENAI_API_KEY",
}

_KEYRING_SERVICE = "vmd_ai"


@dataclass
class KeySaveResult:
    ok: bool
    source: str
    message: str


def _normalize_provider(name: str) -> str:
    return str(name or "").strip().lower()


def _account_for(provider: str) -> str:
    return f"{provider}_api_key"


def _env_var_for(provider: str) -> Optional[str]:
    return _PROVIDER_ENV.get(_normalize_provider(provider))


def read_keyring_for_provider(provider: str) -> Tuple[str, Optional[str]]:
    """Best-effort lookup of a saved key for ``provider``.

    Returns ``(key, error)``. ``key`` is empty when nothing is stored or the
    keyring backend is unavailable; ``error`` is set when the lookup itself
    failed (separate from "no key stored").
    """
    name = _normalize_provider(provider)
    if not name:
        return "", "provider is required"
    try:
        import keyring  # type: ignore[import-not-found]

        backend = keyring.get_keyring()
        priority = float(getattr(backend, "priority", 0) or 0)
        if priority <= 0:
            return "", None
        value = keyring.get_password(_KEYRING_SERVICE, _account_for(name))
        return str(value or "").strip(), None
    except Exception as exc:
        return "", f"keychain read failed: {exc}"


class KeyStore:
    def __init__(self) -> None:
        self._keyring = None
        self._sources: Dict[str, str] = {}
        try:
            import keyring  # type: ignore[import-not-found]

            backend = keyring.get_keyring()
            priority = getattr(backend, "priority", 0) or 0
            if float(priority) > 0:
                self._keyring = keyring
        except Exception:
            self._keyring = None

        # On startup, hydrate the process env from any saved keys so the
        # runtime can pick them up via the existing provider.resolve_*
        # paths without the user having to re-export environment vars.
        self.load_saved_into_env()

    def save(self, provider: str, value: str) -> KeySaveResult:
        name = _normalize_provider(provider)
        token = str(value or "").strip()
        if not name or not token:
            return KeySaveResult(ok=False, source="none", message="provider and key are required")
        if self._keyring is None:
            return KeySaveResult(ok=False, source="none", message="No keychain backend available")
        try:
            self._keyring.set_password(_KEYRING_SERVICE, _account_for(name), token)
        except Exception as exc:
            return KeySaveResult(ok=False, source="none", message=f"Failed to save key: {exc}")

        self._sources[name] = "keyring"

        # Make the key usable for the current process immediately so
        # subsequent chat.send calls can authenticate without restart.
        env_var = _env_var_for(name)
        if env_var:
            os.environ[env_var] = token

        return KeySaveResult(ok=True, source="keyring", message="saved")

    def test(self, provider: str) -> Dict[str, str | bool]:
        name = _normalize_provider(provider)
        if not name:
            return {"ok": False, "message": "provider is required", "source": "none"}

        # Prefer env (covers both env-set keys and prior load_saved_into_env
        # calls) before falling back to a fresh keyring lookup.
        env_var = _env_var_for(name)
        if env_var and str(os.getenv(env_var) or "").strip():
            self._sources[name] = "env"
            return {"ok": True, "message": "key found", "source": "env"}

        if self._keyring is None:
            return {"ok": False, "message": "No keychain backend available", "source": "none"}
        try:
            value = self._keyring.get_password(_KEYRING_SERVICE, _account_for(name))
        except Exception as exc:
            return {"ok": False, "message": f"keychain read failed: {exc}", "source": "none"}
        if value:
            self._sources[name] = "keyring"
            return {"ok": True, "message": "key found", "source": "keyring"}
        return {"ok": False, "message": "key missing", "source": self._sources.get(name, "none")}

    def get_sources(self) -> Dict[str, str]:
        return dict(self._sources)

    def load_saved_into_env(self) -> Dict[str, str]:
        """Populate process env from keyring for every known provider.

        Skips providers whose env var is already set (env always wins, so
        a user who exports a key in the launching shell keeps that key).

        Returns a map of ``{provider: source}`` recording which providers
        ended up resolved and from where.
        """
        loaded: Dict[str, str] = {}
        if self._keyring is None:
            return loaded

        for provider, env_var in _PROVIDER_ENV.items():
            if str(os.getenv(env_var) or "").strip():
                self._sources[provider] = "env"
                loaded[provider] = "env"
                continue
            try:
                value = self._keyring.get_password(
                    _KEYRING_SERVICE, _account_for(provider)
                )
            except Exception:
                value = None
            if value:
                os.environ[env_var] = str(value).strip()
                self._sources[provider] = "keyring"
                loaded[provider] = "keyring"
        return loaded
