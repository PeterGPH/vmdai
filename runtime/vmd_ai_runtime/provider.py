from __future__ import annotations

import json
import os
import time
import threading
from typing import Callable
import urllib.request
import urllib.error


class ProviderError(RuntimeError):
    pass


def _clean_token(value: str | None) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _looks_like_openrouter_key(token: str) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    # OpenRouter keys normally start with "sk-or-".
    if token.startswith("sk-or-"):
        return True
    # Allow future formats while filtering obvious non-key placeholders.
    if " " in token:
        return False
    return len(token) >= 40


def resolve_openrouter_api_key() -> tuple[str, str]:
    """
    Resolve OpenRouter credential from environment, with a keyring fallback.

    Order:
      1. ``OPENROUTER_API_KEY`` env var
      2. ``ANTHROPIC_AUTH_TOKEN`` env var (only if it looks like an OR key)
      3. Saved keyring entry under provider="openrouter"

    Returns (key, source_label). ``source_label`` is the env var name or
    the literal "keyring" so callers can attribute the credential.
    """
    key = _clean_token(os.getenv("OPENROUTER_API_KEY"))
    if key:
        return key, "OPENROUTER_API_KEY"

    mapped = _clean_token(os.getenv("ANTHROPIC_AUTH_TOKEN"))
    if _looks_like_openrouter_key(mapped):
        return mapped, "ANTHROPIC_AUTH_TOKEN"

    # Keyring fallback. Imported lazily so unit tests that don't touch
    # credentials don't pull in the keyring backend.
    try:
        from .keys import read_keyring_for_provider
    except Exception:
        return "", ""
    saved, _err = read_keyring_for_provider("openrouter")
    saved = _clean_token(saved)
    if saved:
        return saved, "keyring"
    return "", ""


def resolve_anthropic_api_key() -> tuple[str, str]:
    """
    Resolve direct-Anthropic credential from environment with keyring fallback.

    Order:
      1. ``ANTHROPIC_API_KEY`` env var
      2. Saved keyring entry under provider="anthropic"
    """
    key = _clean_token(os.getenv("ANTHROPIC_API_KEY"))
    if key:
        return key, "ANTHROPIC_API_KEY"
    try:
        from .keys import read_keyring_for_provider
    except Exception:
        return "", ""
    saved, _err = read_keyring_for_provider("anthropic")
    saved = _clean_token(saved)
    if saved:
        return saved, "keyring"
    return "", ""


def resolve_ollama_host() -> tuple[str, str]:
    """
    Resolve the Ollama base URL.

    Order:
      1. ``VMD_AI_OLLAMA_HOST`` env var (e.g. ``http://192.168.1.5:11434``)
      2. ``OLLAMA_HOST`` env var (Ollama's own convention)
      3. Default ``http://localhost:11434``

    Returns ``(base_url, source_label)``. The url is normalized — no
    trailing slash, scheme defaults to ``http://`` if the user typed a
    bare ``host:port``.
    """
    raw = os.getenv("VMD_AI_OLLAMA_HOST")
    src = "VMD_AI_OLLAMA_HOST"
    if not raw:
        raw = os.getenv("OLLAMA_HOST")
        src = "OLLAMA_HOST" if raw else "default"
    raw = str(raw or "").strip()
    if not raw:
        return "http://localhost:11434", "default"
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw
    return raw.rstrip("/"), src


def resolve_ollama_model() -> tuple[str, str]:
    """
    Resolve which Ollama model to use.

    Order:
      1. ``VMD_AI_OLLAMA_MODEL`` env var
      2. ``OLLAMA_MODEL`` env var (Ollama's own convention)
      3. Empty (caller must surface a clear error — no hardcoded default)

    Returns ``(model_name, source_label)``. Empty model_name means the
    user hasn't told us which model to use; callers should raise
    ``ProviderError`` with a "set VMD_AI_OLLAMA_MODEL=..." hint.
    """
    name = str(os.getenv("VMD_AI_OLLAMA_MODEL") or "").strip()
    if name:
        return name, "VMD_AI_OLLAMA_MODEL"
    name = str(os.getenv("OLLAMA_MODEL") or "").strip()
    if name:
        return name, "OLLAMA_MODEL"
    return "", ""


def resolve_openai_compatible_api_key() -> tuple[str, str]:
    """
    Resolve the key for an OpenAI-compatible server (vLLM, SGLang, LM Studio).

    Order:
      1. ``VMD_AI_OPENAI_API_KEY`` env var
      2. Saved keyring entry under provider="openai-compatible"
      3. The literal ``EMPTY`` that local servers accept
    """
    key = _clean_token(os.getenv("VMD_AI_OPENAI_API_KEY"))
    if key:
        return key, "VMD_AI_OPENAI_API_KEY"
    try:
        from .keys import read_keyring_for_provider
    except Exception:
        return "EMPTY", "default"
    saved, _err = read_keyring_for_provider("openai-compatible")
    saved = _clean_token(saved)
    if saved:
        return saved, "keyring"
    return "EMPTY", "default"


class MockProvider:
    def stream_response(
        self,
        prompt: str,
        cancel_event: threading.Event,
        on_chunk: Callable[[str], None],
        *,
        model: str = "",
        system_prompt: str = "",
    ) -> str:
        text = f"Mock assistant response to: {prompt.strip() or 'empty prompt'}"
        words = text.split(" ")
        emitted = []
        for idx, word in enumerate(words):
            if cancel_event.is_set():
                break
            chunk = word if idx == 0 else f" {word}"
            emitted.append(chunk)
            on_chunk(chunk)
            time.sleep(0.04)
        return "".join(emitted)


class OpenRouterProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        app_name: str = "vmd-ai-skeleton",
        site_url: str = "https://localhost/vmd-ai",
        timeout_sec: int = 90,
    ):
        self._api_key = str(api_key or "").strip()
        self.base_url = str(base_url).rstrip("/")
        self.app_name = str(app_name or "vmd-ai-skeleton")
        self.site_url = str(site_url or "https://localhost/vmd-ai")
        self.timeout_sec = max(10, int(timeout_sec))

    @staticmethod
    def _env_key() -> str:
        key, _src = resolve_openrouter_api_key()
        return key

    @staticmethod
    def _extract_text(payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    txt = item.get("text")
                    if txt:
                        parts.append(str(txt))
            return "".join(parts)
        return ""

    def stream_response(
        self,
        prompt: str,
        cancel_event: threading.Event,
        on_chunk: Callable[[str], None],
        *,
        model: str = "",
        system_prompt: str = "",
    ) -> str:
        api_key = self._api_key or self._env_key()
        if not api_key:
            mapped = _clean_token(os.getenv("ANTHROPIC_AUTH_TOKEN"))
            if mapped:
                raise ProviderError(
                    "OPENROUTER_API_KEY is not set. ANTHROPIC_AUTH_TOKEN is present "
                    "but does not look like an OpenRouter key."
                )
            raise ProviderError("OPENROUTER_API_KEY is not set")

        messages = []
        if str(system_prompt or "").strip():
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(prompt or "")})

        body = {
            "model": str(model or "anthropic/claude-sonnet-4.6"),
            "messages": messages,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": self.site_url,
                "X-Title": self.app_name,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(f"OpenRouter request failed: {exc}") from exc

        text = self._extract_text(payload).strip()
        if not text:
            raise ProviderError("OpenRouter returned empty assistant text")

        words = text.split(" ")
        emitted = []
        for idx, word in enumerate(words):
            if cancel_event.is_set():
                break
            chunk = word if idx == 0 else f" {word}"
            emitted.append(chunk)
            on_chunk(chunk)
            time.sleep(0.02)
        return "".join(emitted)


class AnthropicDirectProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com/v1",
        timeout_sec: int = 90,
        api_version: str = "2023-06-01",
        default_model: str = "claude-sonnet-4-5",
    ):
        self._api_key = str(api_key or "").strip()
        self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = max(10, int(timeout_sec))
        self.api_version = str(api_version or "2023-06-01")
        self.default_model = str(default_model or "claude-sonnet-4-5")

    @staticmethod
    def _env_key() -> str:
        key, _src = resolve_anthropic_api_key()
        return key

    @staticmethod
    def _normalize_model(raw: str, default_model: str) -> str:
        model = str(raw or "").strip()
        if not model:
            model = str(os.getenv("ANTHROPIC_MODEL") or "").strip()
        if not model:
            model = default_model

        # Accept OpenRouter-style provider prefix.
        if "/" in model:
            model = model.split("/", 1)[1]

        # Minimal compatibility map from OpenRouter naming variants.
        mapped = {
            "claude-sonnet-4.6": "claude-sonnet-4-5",
            "claude-haiku-4.5": "claude-haiku-4-5",
        }
        return mapped.get(model, model)

    @staticmethod
    def _extract_text(payload: dict) -> str:
        content = payload.get("content") or []
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "".join(parts)

    def stream_response(
        self,
        prompt: str,
        cancel_event: threading.Event,
        on_chunk: Callable[[str], None],
        *,
        model: str = "",
        system_prompt: str = "",
    ) -> str:
        api_key = self._api_key or self._env_key()
        if not api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

        resolved_model = self._normalize_model(model, self.default_model)
        body = {
            "model": resolved_model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": str(prompt or "")}],
        }
        if str(system_prompt or "").strip():
            body["system"] = str(system_prompt)

        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": self.api_version,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                raw = exc.read().decode("utf-8")
                parsed = json.loads(raw)
                detail = str((parsed.get("error") or {}).get("message") or "")
            except Exception:
                detail = ""
            msg = f"Anthropic request failed: HTTP {exc.code}"
            if detail:
                msg += f" - {detail}"
            raise ProviderError(msg) from exc
        except Exception as exc:
            raise ProviderError(f"Anthropic request failed: {exc}") from exc

        text = self._extract_text(payload).strip()
        if not text:
            raise ProviderError("Anthropic returned empty assistant text")

        words = text.split(" ")
        emitted = []
        for idx, word in enumerate(words):
            if cancel_event.is_set():
                break
            chunk = word if idx == 0 else f" {word}"
            emitted.append(chunk)
            on_chunk(chunk)
            time.sleep(0.02)
        return "".join(emitted)


class OllamaProvider:
    """
    Local Ollama provider (https://ollama.com).

    Streams from ``POST {base_url}/api/chat`` using NDJSON (one JSON
    object per newline-delimited chunk). No auth header — Ollama is
    local-only by default. The model must already be pulled (``ollama
    pull <model>``) before the call lands.

    This is the simple, non-tool version used by the legacy
    ``provider.stream_response`` path. The agentic loop with tool
    calling lives in ``claude_loop._stream_ollama``.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_sec: int = 90,
    ):
        if base_url is None:
            url, _src = resolve_ollama_host()
            self.base_url = url
        else:
            self.base_url = str(base_url).rstrip("/")
        self.timeout_sec = max(10, int(timeout_sec))

    @staticmethod
    def _resolve_model(requested_model: str = "") -> str:
        explicit = str(requested_model or "").strip()
        if explicit:
            return explicit
        env_model, _src = resolve_ollama_model()
        if env_model:
            return env_model
        raise ProviderError(
            "Ollama model not set. Set VMD_AI_OLLAMA_MODEL "
            "(or OLLAMA_MODEL), or pass model=... explicitly."
        )

    def stream_response(
        self,
        prompt: str,
        cancel_event: threading.Event,
        on_chunk: Callable[[str], None],
        *,
        model: str = "",
        system_prompt: str = "",
    ) -> str:
        resolved_model = self._resolve_model(model)

        messages: list[dict] = []
        if str(system_prompt or "").strip():
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(prompt or "")})

        body = {
            "model": resolved_model,
            "messages": messages,
            "stream": True,
            # Ollama's "options" mirror llama.cpp sampling knobs. Keep
            # defaults; users can override per-model via Modelfile.
        }

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "accept": "application/x-ndjson",
            },
            method="POST",
        )

        emitted: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                # NDJSON: read one line at a time, parse each as JSON.
                for raw_line in resp:
                    if cancel_event.is_set():
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        # Malformed line — skip, don't fail the whole stream.
                        continue
                    # ``error`` short-circuits the stream with a useful
                    # message (model-not-found, etc.).
                    if "error" in obj:
                        raise ProviderError(
                            f"Ollama error: {obj['error']}"
                        )
                    msg = obj.get("message") or {}
                    chunk = str(msg.get("content") or "")
                    if chunk:
                        emitted.append(chunk)
                        on_chunk(chunk)
                    if obj.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                raw = exc.read().decode("utf-8")
                parsed = json.loads(raw)
                detail = str(parsed.get("error") or "")
            except Exception:
                detail = ""
            msg = (
                f"Ollama request failed: HTTP {exc.code} "
                f"(model={resolved_model!r}, host={self.base_url!r})"
            )
            if detail:
                msg += f" - {detail}"
            raise ProviderError(msg) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"Ollama unreachable at {self.base_url!r}: {exc.reason}. "
                f"Is `ollama serve` running?"
            ) from exc
        except Exception as exc:
            if isinstance(exc, ProviderError):
                raise
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        text = "".join(emitted).strip()
        if not text:
            raise ProviderError("Ollama returned empty assistant text")
        return "".join(emitted)


def build_provider(mode: str):
    selected = str(mode or "").strip().lower()
    if selected in ("openrouter", "claude", "claude-openrouter"):
        return "openrouter", OpenRouterProvider()
    if selected in ("anthropic-direct", "anthropic_api", "anthropic-direct-api"):
        return "anthropic-direct", AnthropicDirectProvider()
    if selected in ("ollama", "local-ollama", "local_ollama"):
        return "ollama", OllamaProvider()
    if selected in ("openai-compatible", "openai_compatible"):
        key, _src = resolve_openai_compatible_api_key()
        base = os.getenv("VMD_AI_OPENAI_BASE_URL") or "http://localhost:8000/v1"
        return "openai-compatible", OpenRouterProvider(api_key=key, base_url=base)
    return "mock", MockProvider()
