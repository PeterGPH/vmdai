"""
app.py - RuntimeApp: the central JSON-RPC dispatcher for VMD AI.

Key additions over the skeleton:
  - VmdToolBridge handles async tool calls from the Claude loop back to Tcl
  - ClaudeToolLoop drives multi-turn conversations with run_vmd_command /
    capture_vmd_snapshot tool use
  - tool.command_result RPC method lets the Tcl bridge post VMD execution results
  - Falls back to simple mock streaming when no API key is configured
"""
from __future__ import annotations

import atexit
import copy
import dataclasses
import hashlib
import hmac
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pathlib import Path

from . import conversation
from . import provider_catalog
from . import settings_store as settings_mod
from .claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
    WIKI_SYSTEM_PROMPT_ADDENDUM,
    _ollama_tools,
    _openrouter_tools,
    _tool_finished_meta,
    build_claude_loop,
)
from .locks import ChatLock
from .recorder import RunRecorder
from .constants import ACTION_FOR_CODE, CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_PROTOCOL, RUNTIME_VERSION
from .docs_search import DocsSearch
from .errors import RpcError
from .events import display_log
from .keys import KeyStore
from .logging_utils import default_log_path, redact_sensitive
from .prompts import NON_VISION_TOOL_OVERRIDES, chatvmd_system_prompt, session_block
from .protocol import validate_method_params, validate_rpc_payload
from .provider import (
    build_provider,
    resolve_anthropic_api_key,
    resolve_ollama_model,
    resolve_openai_compatible_api_key,
    resolve_openrouter_api_key,
)
from .provider_catalog import strip_url_secrets
from .settings_store import (
    DEFAULT_BASE_URLS,
    DEFAULT_PROFILE_NAMES,
    TOP_LEVEL_DEFAULTS,
    SettingsError,
    SettingsStore,
    checked_setting,
    normalize_provider,
    resolve_profile,
)
from .sessions import RequestState, SessionManager, SessionState
from .store import ChatStore
from .tool_bridge import BridgeSession, VmdToolBridge
from .wiki_store import WikiStore


# §2f Rescue: shown once per token session whose profile opts into rescue "all".
RESCUE_ALL_NOTICE = (
    "This profile runs tool calls that the model writes as plain text "
    "(options.rescue is \"all\"), including tcl code blocks in its answers. "
    "Set options.rescue to \"json\" in ~/.vmdai/settings.json to run only "
    "tool-call JSON that names an offered tool."
)


# settings.json keys settings.set may write (§2f Schema); they need a token session.
PERSISTED_SETTING_KEYS = tuple(TOP_LEVEL_DEFAULTS)


def _canonical_sha256(obj: Any) -> str:
    """SHA-256 of canonical JSON (sorted keys, compact separators): C6 tools_sha256."""
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _tools_as_sent(loop) -> List[Dict[str, Any]]:
    """The ``tools`` list a turn-1 request body carries (C6: after
    tool_overrides, in the provider's own shape)."""
    tools = loop._tools_for_turn()
    if getattr(loop, "_is_anthropic_direct", False):
        return list(tools)
    if getattr(loop, "_is_ollama", False):
        return _ollama_tools(tools)
    return _openrouter_tools(tools)


def _remove_snapshot_dirs(dirs: Dict[str, str], lock: threading.Lock) -> None:
    """atexit hook (M2): sweep any per-session snapshot temp dirs still open
    when the process exits (SIGTERM, ``--watch-stdin`` EOF, a session that
    never called session.stop). ``dirs`` is the live ``_snapshot_dirs`` map —
    cleared here, under ``lock``, before the directories are removed."""
    with lock:
        paths = list(dirs.values())
        dirs.clear()
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def _wants_v2(state: Any) -> bool:
    """True when this session negotiated the v2 display events (§2c).

    Only a token-authenticated session.start can ask for event_protocol 2,
    so a tokenless (v1) session never gets here.
    """
    try:
        return int(getattr(state, "event_protocol", 1) or 1) >= 2
    except (TypeError, ValueError):
        return False


# §2c Persistence: the system/state kinds events.jsonl keeps. Chunks,
# turn.started, usage, status and turn.retry are live-only.
PERSISTED_STATE_KINDS = frozenset({"request.started", "tool.started", "tool.finished", "request.finished"})


def is_display_event(event: Dict[str, Any]) -> bool:
    """True for the events a chat's display log (events.jsonl) keeps (§2c Persistence).

    Kept: user messages, request.started, tool.started, one assistant
    message per turn, one sealed reasoning/message per turn, tool.finished
    (late ones too), error, request.finished and lifecycle events.
    Never kept: chunks and role=tool_start (the execution channel).
    """
    role = str(event.get("role") or "")
    event_type = str(event.get("type") or "")
    if event_type == "chunk" or role == "tool_start":
        return False
    if event_type == "lifecycle":
        return True
    if event_type == "state":
        return (event.get("metadata") or {}).get("kind") in PERSISTED_STATE_KINDS
    return event_type == "message" and role in ("user", "assistant", "reasoning", "error")


class _EventMapper:
    """The ``ctx.on_event`` sink of one request (§2a Legacy callbacks, §2c).

    Every loop item keeps ``RequestState.turn`` current for runtime.info.
    For a v2 session the item also becomes a queue event (``push``); for a
    v1 session it is dropped, because v1 events come from the legacy
    callbacks. ``push`` also:

    * collects a turn's reasoning chunks and pushes one sealed
      ``reasoning/message`` just before the first non-reasoning event that
      follows them (or before request.finished). ``turn.retry`` drops the
      unsealed reasoning, because the retried attempt streams it again;
    * writes the display kinds to events.jsonl (``is_display_event``) and
      touches the manifest once, at request.finished.

    The recorder's task directory is captured at the first loop event for
    ``request.finished.run_dir``. A failure here is logged and never
    reaches the loop.
    """

    def __init__(self, app: "RuntimeApp", state: "SessionState", request: "RequestState") -> None:
        self.app = app
        self.state = state
        self.request = request
        self.request_id = str(request.request_id)
        self.chat_id: Optional[str] = state.chat_id
        self.v2 = _wants_v2(state)
        self.recorder: Any = None
        self.run_dir: Optional[str] = None
        self._reasoning_open = False
        self._reasoning_turn: Any = None
        self._reasoning_parts: List[str] = []
        self._reasoning_t0 = 0.0

    def __call__(self, item: Dict[str, Any]) -> None:
        try:
            self._handle(item)
        except Exception:
            if self.app.logger:
                self.app.logger.warning("v2 event mapping failed for %s", self.request_id, exc_info=True)

    def _handle(self, item: Dict[str, Any]) -> None:
        metadata = dict(item.get("metadata") or {})
        if metadata.get("kind") == "turn.started":
            try:
                self.request.turn = int(metadata.get("turn") or 0)
            except (TypeError, ValueError):
                pass
        self._note_run_dir()
        if self.v2:
            self.push(str(item.get("role") or ""), str(item.get("type") or ""),
                      str(item.get("text") or ""), metadata)

    def _note_run_dir(self) -> None:
        if self.run_dir is None and self.recorder is not None:
            task_dir = getattr(self.recorder, "current_task_dir", None)
            if task_dir:
                self.run_dir = str(task_dir)

    def push(self, role: str, event_type: str, text: str = "",
             metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Push one v2 event of this request; does nothing for a v1 session."""
        if not self.v2:
            return None
        meta = dict(metadata or {})
        meta.setdefault("request_id", self.request_id)
        kind = meta.get("kind")
        if role == "reasoning" and event_type == "chunk":
            self._buffer_reasoning(meta.get("turn"), text)
        elif kind == "turn.retry":
            self._drop_reasoning()
        else:
            self.seal_reasoning()
        event = self.app._push_v2(self.state, role, event_type, text, meta)
        self.app._persist_display(self.chat_id, event)
        if kind == "request.finished" and self.chat_id:
            self.app.store.touch_manifest(self.chat_id)
        return event

    def _buffer_reasoning(self, turn: Any, text: str) -> None:
        if self._reasoning_open and turn != self._reasoning_turn:
            self.seal_reasoning()
        if not self._reasoning_open:
            self._reasoning_open = True
            self._reasoning_turn = turn
            self._reasoning_parts = []
            self._reasoning_t0 = time.monotonic()
        self._reasoning_parts.append(text)

    def _drop_reasoning(self) -> None:
        self._reasoning_open = False
        self._reasoning_turn = None
        self._reasoning_parts = []

    def seal_reasoning(self) -> Optional[Dict[str, Any]]:
        """Push the open reasoning as one ``reasoning/message`` (live and persisted)."""
        if not self._reasoning_open:
            return None
        meta: Dict[str, Any] = {
            "request_id": self.request_id,
            "turn": self._reasoning_turn,
            "duration_ms": int(round((time.monotonic() - self._reasoning_t0) * 1000)),
        }
        text = "".join(self._reasoning_parts)
        self._drop_reasoning()
        event = self.app._push_v2(self.state, "reasoning", "message", text, meta)
        self.app._persist_display(self.chat_id, event)
        return event


class RuntimeApp:
    def __init__(
        self,
        store_dir: str | None = None,
        logger=None,
        provider_mode: str | None = None,
        docs_index_dir: str | None = None,
        enable_rag: bool = True,
        wiki_root: str | None = None,
        wiki_raw_root: str | None = None,
        enable_wiki: bool = True,
        launch_token: Optional[str] = None,
        allow_tokenless_v1: bool = True,
        on_shutdown: Optional[Callable[[], None]] = None,
        loop_factory: Optional[Callable[[Dict[str, Any]], Optional[ClaudeToolLoop]]] = None,
        settings_store: Optional[SettingsStore] = None,
        cli_provider: Optional[str] = None,
    ):
        # Runtime-owned profiles (§2f). Only main.py passes a store; tests
        # and the A/B scripts keep plan 02's env-driven behaviour.
        self.settings_store = settings_store
        self.cli_provider = (str(cli_provider).strip() or None) if cli_provider else None
        self.first_run_servers: List[Dict[str, Any]] = []
        self._profile_router: Optional[Callable[[Optional[Dict[str, Any]]], Optional[ClaudeToolLoop]]] = None
        self.sessions = SessionManager()
        # Launch token (§2e). main.py generates it; None (in-process tests)
        # means no session can authenticate and runtime.shutdown is refused.
        # allow_tokenless_v1 is False under --announce, so a tokenless
        # session.start is accepted only from old plugins and dev scripts.
        self.launch_token: Optional[str] = str(launch_token) if launch_token else None
        self.allow_tokenless_v1 = bool(allow_tokenless_v1)
        self._on_shutdown = on_shutdown
        self.store = ChatStore(store_dir)
        # KeyStore.__init__ hydrates os.environ from any keys saved in the
        # OS keychain, so the provider auto-detect below sees them.
        self.keys = KeyStore()
        self.logger = logger
        self._snapshot_lock = threading.Lock()
        self._snapshot_dirs: Dict[str, str] = {}
        atexit.register(_remove_snapshot_dirs, self._snapshot_dirs, self._snapshot_lock)
        self.tool_bridge = VmdToolBridge(session_lookup=self._bridge_session)
        self.tool_bridge.on_late_result = self._on_late_result
        # Round-2 hook (spec 1, 2g): each callable returns extra per-request
        # context (for example scene state) appended after the <session> block.
        self.context_providers: List[Callable[[SessionState], str]] = []
        # docs_search is constructed even when no index has been built —
        # ``is_available`` is False until ``vmd-ai-index --rebuild`` runs.
        # Pass enable_rag=False to force-disable for the no-RAG arm of an
        # A/B test even if an index is present.
        self.docs_search: DocsSearch | None = (
            DocsSearch(index_dir=docs_index_dir) if enable_rag else None
        )

        # Wiki store — the LLM Wiki pattern's persistent knowledge base.
        # Defaults: wiki at ~/.vmdai/wiki/, raw sources at ~/.vmdai/raw/
        # (sharing roots with the docs index keeps source pinning honest).
        # Pass enable_wiki=False for the no-wiki arm of A/B comparisons.
        self.wiki_store: WikiStore | None = None
        if enable_wiki:
            home = Path(os.path.expanduser("~"))
            w_root = Path(wiki_root) if wiki_root else home / ".vmdai" / "wiki"
            r_root = Path(wiki_raw_root) if wiki_raw_root else home / ".vmdai" / "raw"
            # raw_root may not exist yet — that's fine; pinning will
            # error gracefully if the agent cites a missing source.
            try:
                self.wiki_store = WikiStore(w_root, raw_root=r_root)
                self.wiki_store.bootstrap()
            except Exception:
                if self.logger:
                    self.logger.warning(
                        "wiki bootstrap failed at %s", w_root, exc_info=True,
                    )
                self.wiki_store = None

        # Resolve provider. Auto-detect now also picks up keyring-stored
        # keys via resolve_*_api_key (env still wins). Resolution order
        # when VMD_AI_PROVIDER is unset:
        #   1. OpenRouter key found → openrouter
        #   2. Anthropic key found  → anthropic-direct
        #   3. VMD_AI_OLLAMA_MODEL (or OLLAMA_MODEL) set → ollama
        #   4. nothing → mock (offline demo mode)
        env_provider = str(provider_mode or os.getenv("VMD_AI_PROVIDER") or "").strip().lower()
        if not env_provider:
            openrouter_key, _source = resolve_openrouter_api_key()
            if openrouter_key:
                env_provider = "openrouter"
            else:
                anthropic_key, _src = resolve_anthropic_api_key()
                if anthropic_key:
                    env_provider = "anthropic-direct"
                else:
                    ollama_model, _om_src = resolve_ollama_model()
                    if ollama_model:
                        env_provider = "ollama"
                    else:
                        env_provider = "mock"

        self.provider_name, self.provider = build_provider(env_provider)

        # Every request gets a fresh ClaudeToolLoop from the loop factory
        # (§3), so no loop, recorder or model override is shared between
        # requests. The default factory builds from the legacy profile: the
        # env/--provider choice plus the model picked through provider.set.
        # The docs_search and wiki_store instances are wired into every loop.
        self._loop_provider = env_provider
        self._loop_model: Optional[str] = None
        self._base_loop_factory: Callable[[Optional[Dict[str, Any]]], Optional[ClaudeToolLoop]] = (
            loop_factory if loop_factory is not None else self._default_loop_factory
        )
        self._loop_factory = self._base_loop_factory
        self._assigned_loop: Optional[ClaudeToolLoop] = None

        if self.logger:
            self.logger.info(
                "provider=%s agent_loop=%s",
                self.provider_name,
                self.has_agent_loop(),
            )

        if settings_store is not None and loop_factory is None:
            # Settings profiles (token sessions) get the product loop; the
            # legacy {provider, model} profile keeps plan 02's factory. The
            # router is the base factory, so provider.set's reset keeps it.
            legacy_factory = self._base_loop_factory

            def _route(profile: Optional[Dict[str, Any]]) -> Optional[ClaudeToolLoop]:
                if profile is not None and "source" in profile:
                    return self._profile_loop_factory(profile)
                return legacy_factory(profile)

            self._base_loop_factory = _route
            self._loop_factory = _route
            self._profile_router = _route
        if settings_store is not None and not settings_store.exists():
            # First run (§2f): probe :11435 then :11434, 300 ms each.
            try:
                self.first_run_servers = list(settings_mod.probe_local_ollama())
                settings_store.first_run(self.first_run_servers)
            except Exception:
                if self.logger:
                    self.logger.warning("first-run probe failed", exc_info=True)

    # ------------------------------------------------------------------
    # Loop factory (§3): a fresh ClaudeToolLoop per request
    # ------------------------------------------------------------------

    @property
    def claude_loop(self) -> Optional[ClaudeToolLoop]:
        """The loop assigned from outside (tests), or None.

        The runtime keeps no loop of its own: chat.send builds one per
        request through the loop factory. Assigning a loop installs a
        factory that returns that object, so tests that set
        ``app.claude_loop = FakeLoop(...)`` keep working unchanged.
        """
        return self._assigned_loop

    @claude_loop.setter
    def claude_loop(self, loop: Optional[ClaudeToolLoop]) -> None:
        self._assigned_loop = loop
        self._loop_factory = lambda _profile: loop

    def _default_loop_factory(self, profile: Optional[Dict[str, Any]]) -> Optional[ClaudeToolLoop]:
        """Build a loop for ``profile`` with the app's docs and wiki stores."""
        if not profile:
            return None
        return build_claude_loop(
            str(profile.get("provider") or ""),
            docs_search=self.docs_search,
            wiki_store=self.wiki_store,
            model=profile.get("model") or None,
        )

    def profile_for_session(self, state: Optional[SessionState] = None) -> Optional[Dict[str, Any]]:
        """The profile a request of ``state`` runs with (§7 Precedence).

        Token sessions of a runtime that owns settings.json use
        resolve_profile (CLI flag > active profile; VMD_AI_PROVIDER is
        seed-only and never used live); the
        returned copy adds ``name`` and ``source``, and None means there is
        no usable profile (NO_MODEL). Everything else gets the legacy
        profile {provider, model}: the env/--provider choice and the model
        of the last provider.set.
        """
        if state is not None and getattr(state, "authenticated", False) and self.settings_store is not None:
            name, profile, source = resolve_profile(self.settings_store, self.cli_provider, os.environ)
            if profile is None:
                return None
            out = copy.deepcopy(profile)
            out["name"] = name
            out["source"] = source
            return out
        return {"provider": self._loop_provider, "model": self._loop_model}

    def has_agent_loop(self, state: Optional[SessionState] = None) -> bool:
        """True when a request of ``state`` would run the agent loop, not mock mode.

        Settings profiles get the cheap predicate (_can_build_profile), which
        never builds a ClaudeToolLoop; everything else asks the active
        factory (plan 02 review ruling (b)).
        """
        try:
            profile = self.profile_for_session(state)
            router = self._profile_router
            if router is not None and self._loop_factory is router and profile is not None and "source" in profile:
                return self._can_build_profile(profile)   # ruling (b): no loop is built
            return self._loop_factory(profile) is not None
        except Exception:
            if self.logger:
                self.logger.warning("loop factory failed", exc_info=True)
            return False

    def _build_loop(self, profile: Optional[Dict[str, Any]]) -> Optional[ClaudeToolLoop]:
        try:
            return self._loop_factory(profile)
        except Exception as exc:
            raise RpcError(
                "PROVIDER_INIT_FAILED",
                f"failed to build the agent loop: {exc}",
                {"provider": (profile or {}).get("provider")},
            )

    # ------------------------------------------------------------------
    # Settings profiles (§2f)
    # ------------------------------------------------------------------

    def _profile_loop_parts(self, profile: Optional[Dict[str, Any]]) -> Optional[tuple]:
        """(provider, model, api_key) for a settings profile, or None when no loop can be built.

        Cheap: builds no ClaudeToolLoop. The factory and _can_build_profile share it."""
        if not profile:
            return None
        provider_name = normalize_provider(profile.get("provider"))
        model = str(profile.get("model") or "").strip()
        if not provider_name or not model:
            return None
        if provider_name == "ollama":
            api_key = str(profile.get("base_url") or DEFAULT_BASE_URLS["ollama"]).rstrip("/")
        else:
            api_key = self._api_key_for(provider_name)
            if not api_key:
                return None
        return provider_name, model, api_key

    def _can_build_profile(self, profile: Optional[Dict[str, Any]]) -> bool:
        """Plan 02 final review (b): the profile factory's cheap can_build predicate."""
        return self._profile_loop_parts(profile) is not None

    def _profile_loop_factory(self, profile: Dict[str, Any]) -> Optional[ClaudeToolLoop]:
        """One product loop for a settings profile (§2f, C7).

        Options come from LoopOptions.product(profile) with max_turns from
        settings.json; keys from provider.resolve_* (env, then keyring). The
        wiki is wired only when settings.wiki_enabled is true (§2g). Returns
        None when the profile has no model or a needed key is missing.
        """
        parts = self._profile_loop_parts(profile)
        if parts is None:
            return None
        provider_name, model, api_key = parts
        if not profile.get("base_url") and provider_name in DEFAULT_BASE_URLS:
            profile = dict(profile, base_url=DEFAULT_BASE_URLS[provider_name])
        options = LoopOptions.product(profile, max_turns=int(self._setting("max_turns")))
        wiki = self.wiki_store if self._setting("wiki_enabled") else None
        return ClaudeToolLoop(provider_name=provider_name, api_key=api_key, model=model,
                              docs_search=self.docs_search, wiki_store=wiki, options=options)

    @staticmethod
    def _api_key_for(provider_name: str) -> str:
        if provider_name == "anthropic-direct":
            return resolve_anthropic_api_key()[0]
        if provider_name == "openrouter":
            return resolve_openrouter_api_key()[0]
        if provider_name == "openai-compatible":
            return resolve_openai_compatible_api_key()[0]
        return ""

    def _setting(self, name: str) -> Any:
        """A top-level settings.json value, or its default when there is no store
        or the stored value is malformed (M1)."""
        if self.settings_store is None:
            return TOP_LEVEL_DEFAULTS[name]
        return checked_setting(self.settings_store.load(), name)

    def _profile_summary(self, state) -> Optional[Dict[str, Any]]:
        profile = self.profile_for_session(state)
        if profile is None or "source" not in profile:
            return None
        summary = {"name": profile.get("name"), "provider": profile.get("provider"),
                   "model": profile.get("model", "")}
        if profile.get("base_url"):
            summary["base_url"] = profile["base_url"]
        return summary

    @staticmethod
    def _no_model_error() -> RpcError:
        return RpcError(
            "NO_MODEL",
            "No model configured. Choose a provider and model, or add a profile to ~/.vmdai/settings.json.",
            {"action": "open_settings"},
        )

    # ------------------------------------------------------------------
    # M1 RPC helpers (§2c, §3)
    # ------------------------------------------------------------------

    @staticmethod
    def _vision_for(loop: Optional[ClaudeToolLoop]) -> bool:
        """runtime.info.vision: the loop's resolved supports_vision (spec 2f).

        "auto" asks /api/show once for Ollama (2 s timeout, cached 60 s by
        provider_catalog); a failed probe reads as no vision."""
        if loop is None:
            return False
        try:
            return bool(loop._vision_enabled())
        except Exception:
            return False

    def _max_turns_for(self, loop: Optional[ClaudeToolLoop]) -> int:
        options = getattr(loop, "options", None) if loop is not None else None
        if options is not None:
            return int(options.max_turns)
        if loop is not None:
            return int(loop.MAX_TURNS)
        return int(self._setting("max_turns"))

    @staticmethod
    def _log_path() -> str:
        for handler in logging.getLogger().handlers:
            name = getattr(handler, "baseFilename", None)
            if name:
                return str(name)
        return default_log_path()

    def _runtime_info(self, state) -> Dict[str, Any]:
        loop = self._new_loop_for(state)
        profile = self.profile_for_session(state) or {}
        # A token session of a runtime that owns settings.json never runs the
        # env/mock provider (§2f), so with no usable profile it reports "".
        fallback = "" if (state.authenticated and self.settings_store is not None) else self.provider_name
        info: Dict[str, Any] = {
            "version": RUNTIME_VERSION,
            "protocol": RUNTIME_PROTOCOL,
            "pid": os.getpid(),
            "provider": loop.provider_name if loop is not None else str(profile.get("provider") or fallback),
            "model": loop.model if loop is not None else str(profile.get("model") or ""),
            "agent_loop": loop is not None,
            "vision": self._vision_for(loop),
            "tools": [str(tool.get("name")) for tool in loop._tools_for_turn()] if loop is not None else [],
            "rag": bool(self.docs_search is not None and getattr(self.docs_search, "is_available", False)),
            "wiki": bool(loop is not None and loop.wiki_store is not None),
            "max_turns": self._max_turns_for(loop),
            "log_path": self._log_path(),
            "settings_source": (self.settings_store.settings_source
                                if self.settings_store is not None else "default"),
            "first_run": {"servers": copy.deepcopy(self.first_run_servers)},
        }
        active = state.active_request
        if self._request_running(state):
            info["active_request"] = {
                "request_id": active.request_id,
                "turn": int(active.turn),
                "started_at": float(active.started_at),
                "last_seq": state.queue.last_seq,
            }
        return info

    def _catalog_target(self, state, params: Dict[str, Any]) -> Tuple[str, str, str, str]:
        """(provider, base_url, model, api_key) for models.list/provider.test.

        Missing params come from the session's profile when the provider
        matches, else from the provider's defaults.
        """
        profile = self.profile_for_session(state) or {}
        profile_provider = normalize_provider(profile.get("provider"))
        provider_name = normalize_provider(params.get("provider")) or profile_provider
        same = provider_name == profile_provider
        base_url = (params.get("base_url") or (profile.get("base_url") if same else "")
                    or DEFAULT_BASE_URLS.get(provider_name) or "")
        model = params.get("model") or (profile.get("model") if same else "") or ""
        return provider_name, str(base_url), str(model), self._api_key_for(provider_name)

    def _capabilities_for(self, profile: Dict[str, Any]) -> Dict[str, bool]:
        provider_name = normalize_provider(profile.get("provider"))
        options = profile.get("options") or {}
        if provider_name == "ollama" and profile.get("model"):
            base_url = profile.get("base_url") or DEFAULT_BASE_URLS["ollama"]
            try:
                show = provider_catalog.ollama_show(base_url, profile["model"], timeout=2.0)
            except Exception:
                return {"tools": False, "vision": False, "thinking": False}
            return provider_catalog.model_capabilities(show)
        return {"tools": True,
                "vision": provider_name == "anthropic-direct" or options.get("supports_vision") is True,
                "thinking": False}

    def _settings_rpc_error(self, exc: SettingsError) -> RpcError:
        if exc.code in ("IN_USE", "NOT_FOUND"):
            return RpcError(exc.code, exc.message)
        if exc.code == "READ_ONLY":
            source = self.settings_store.settings_source if self.settings_store is not None else "default"
            return RpcError("INVALID_PARAMS", exc.message, {"reason": "read_only", "settings_source": source})
        return RpcError("INVALID_PARAMS", exc.message)

    @staticmethod
    def _apply_target(store: SettingsStore, provider_name: str) -> str:
        """The profile name a provider *switch* (no explicit ``profile``) lands on (I1).

        Prefers an existing profile of ``provider_name`` — the default-named
        one, else the first one found — over creating a fresh profile, so
        switching providers and back restores that profile's base_url and
        options untouched instead of overwriting the active profile in place.
        Only when no profile of this provider exists does it fall back to
        creating one, trying ``<default>``, ``<default>-2``, ``<default>-3``, ...
        """
        profiles = store.load()["profiles"]
        same = [n for n, p in profiles.items()
                if isinstance(p, dict) and normalize_provider(p.get("provider")) == provider_name]
        default_name = DEFAULT_PROFILE_NAMES[provider_name]
        if default_name in same:
            return default_name
        if same:
            return same[0]
        name = default_name
        suffix = 2
        while name in profiles:
            name = "%s-%d" % (default_name, suffix)
            suffix += 1
        return name

    def _provider_set_profile(self, state, params: Dict[str, Any]) -> Dict[str, Any]:
        """provider.set for a token session: persist into the active, named or
        provider-matching profile.

        Applies to the next request. With an explicit ``profile`` name it
        edits (or creates) that profile in place, unchanged from before.
        Without a name:
          - if the active profile already runs the requested provider, it is
            edited in place (M1 ui.tcl Apply, §2f) — a plain model change
            never disturbs another profile;
          - otherwise this is a provider *switch*: ``_apply_target`` picks
            (or creates) a profile of that provider and activates it, so a
            round trip through another provider and back restores the
            original profile's base_url and options (whole-branch review I1)
            instead of overwriting the active profile in place;
          - with no active profile at all, the provider's default-named
            profile is edited (or created) and activated: first run may have
            seeded ``claude``/``openrouter`` from last_provider.txt without
            activating it, and applying it is the user's explicit choice.
        """
        store = self.settings_store
        provider_name = normalize_provider(params.get("provider"))
        if not provider_name:
            raise RpcError("INVALID_PARAMS",
                           "provider must be one of anthropic-direct, openrouter, ollama, openai-compatible",
                           {"provider": params.get("provider")})
        model = str(params.get("model") or "").strip() or None
        base_url = str(params.get("base_url") or "").strip() or None
        options = params.get("options")
        name = str(params.get("profile") or "").strip()
        switch = False
        try:
            active_name, active = store.active_profile()
            if not name:
                if active is not None and normalize_provider(active.get("provider")) == provider_name:
                    name = active_name
                else:
                    name = self._apply_target(store, provider_name)
                    switch = True
            if store.get_profile(name) is None:
                profile: Dict[str, Any] = {"provider": provider_name, "model": model or "",
                                           "options": dict(options or {})}
                url = base_url or DEFAULT_BASE_URLS.get(provider_name)
                if url:
                    profile["base_url"] = url
                store.save_profile(name, profile, activate=(active_name is None or switch))
            else:
                store.update_profile(name, provider=provider_name, model=model, base_url=base_url, options=options)
                if active_name is None or switch:
                    store.activate(name)
        except SettingsError as exc:
            raise self._settings_rpc_error(exc)
        saved = store.get_profile(name) or {}
        if saved.get("model"):
            state.settings["model"] = saved["model"]
        return {
            "ok": True,
            "provider": provider_name,
            "model": saved.get("model", ""),
            "profile": name,
            "agent_loop": self.has_agent_loop(state),
            "capabilities": self._capabilities_for(saved),
        }

    # ------------------------------------------------------------------
    # RPC dispatch
    # ------------------------------------------------------------------

    def handle_rpc(self, payload: Dict[str, Any], session_token: str = "") -> Dict[str, Any]:
        # Pull req_id out of the raw payload up front so error responses
        # can echo it even if the rest of the body is malformed.
        req_id = payload.get("id") if isinstance(payload, dict) else None
        method = "<unknown>"

        try:
            parsed = validate_rpc_payload(payload)
            method = parsed["method"]
            params = validate_method_params(method, parsed["params"])
            req_id = parsed.get("id")
            result = self._dispatch(method, params, session_token)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except RpcError as exc:
            if self.logger:
                self.logger.warning(
                    "rpc error method=%s code=%s message=%s",
                    method,
                    exc.code,
                    redact_sensitive(exc.message),
                )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": exc.code,
                    "message": redact_sensitive(exc.message),
                    "data": exc.data or {},
                },
            }
        except Exception as exc:
            # Final guardrail: any unexpected exception must still return
            # a proper JSON-RPC error envelope. Without this, the HTTP
            # handler closes the socket mid-response and Tcl sees
            # status=eof — opaque on the client side and a pain to debug.
            if self.logger:
                self.logger.exception("unhandled rpc error method=%s", method)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": redact_sensitive(str(exc) or exc.__class__.__name__),
                    "data": {"method": method},
                },
            }

    def _get_session(self, session_id: str, token: str):
        state = self.sessions.verify(session_id, token)
        if state is None:
            raise RpcError("AUTH_FAILED", "invalid session or token")
        return state

    def _token_matches(self, candidate: str) -> bool:
        if not self.launch_token or not candidate:
            return False
        return hmac.compare_digest(
            str(candidate).encode("utf-8"), self.launch_token.encode("utf-8")
        )

    def _require_auth(self, state: SessionState) -> None:
        """Raise AUTH_REQUIRED unless ``state`` was started with the launch token.

        Privileged calls (§2e) check this: provider.set with base_url,
        options or profile; settings.json writes; session.set_cwd; and
        models.list/provider.test with an arbitrary base_url.
        """
        if not getattr(state, "authenticated", False):
            raise RpcError(
                "AUTH_REQUIRED",
                "this call needs a session started with the launch token",
            )

    def _dispatch(self, method: str, params: Dict[str, Any], session_token: str) -> Dict[str, Any]:

        # ---- Runtime lifecycle ----

        if method == "runtime.shutdown":
            if not self._token_matches(params["launch_token"]):
                raise RpcError("AUTH_FAILED", "invalid launch token")
            if self.logger:
                self.logger.info("runtime.shutdown requested over RPC")
            if self._on_shutdown is not None:
                self._on_shutdown()
            return {"ok": True}

        # ---- Session lifecycle ----

        if method == "session.start":
            launch_token = str(params.get("launch_token") or "")
            authenticated = False
            if launch_token:
                if not self._token_matches(launch_token):
                    raise RpcError("AUTH_FAILED", "invalid launch token")
                authenticated = True
            elif not self.allow_tokenless_v1:
                raise RpcError(
                    "AUTH_REQUIRED",
                    "this runtime was started with --announce; "
                    "session.start needs the launch token",
                )
            # Token sessions create their chat lazily on the first chat.send
            # (§2b Lock lifecycle); tokenless sessions keep eager creation.
            chat_id = None if authenticated else self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(
                cwd=params["cwd"],
                chat_id=chat_id,
                authenticated=authenticated,
                # §2c: a token session may negotiate display protocol 2; a
                # tokenless session always gets today's v1 events.
                event_protocol=int(params.get("event_protocol") or 1) if authenticated else 1,
                vmd_env=params.get("vmd_env") if authenticated else None,
            )
            state.queue.push("system", "lifecycle", "session_started", {"chat_id": chat_id})
            # Surface a one-time security notice so users see the trust
            # boundary before they send their first prompt. The model
            # executes Tcl in the live VMD process, which means it can
            # call `exec`, `file delete`, `socket`, etc. — full machine
            # access via the VMD interpreter. Sandboxing is on the
            # roadmap; until then, this is the only warning users get.
            state.queue.push(
                "system",
                "message",
                (
                    "Security note: VMD AI executes the model's Tcl commands "
                    "directly in your VMD process. Tcl can run shell commands "
                    "and access files. Treat the assistant like a trusted "
                    "shell user — avoid loading sensitive data while running."
                ),
                {"notice": "tcl_trust_boundary"},
            )
            result = {
                "session_id": state.session_id,
                "session_token": state.session_token,
                "capabilities": CAPABILITIES,
                "defaults": dict(state.settings),
                "chat_id": chat_id,
                "provider": self.provider_name,
                "agent_loop": self.has_agent_loop(state),
            }
            if authenticated:
                result["event_protocol"] = state.event_protocol
                result["runtime"] = {"version": RUNTIME_VERSION, "pid": os.getpid()}
                result["profile"] = self._profile_summary(state)
            return result

        if method == "session.stop":
            state = self._get_session(params["session_id"], session_token)
            with state.lock:
                self._cancel_active_request(state)
                self._release_chat_lock(state)
                self.sessions.remove(state.session_id)
            self._drop_snapshot_dir(state.session_id)
            return {"ok": True}

        # ---- Chat ----

        if method == "chat.send":
            state = self._get_session(params["session_id"], session_token)
            # A token session always runs its profile's model (§2h).
            if params.get("model") and not state.authenticated:
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
            if params.get("conversation_mode"):
                state.settings["conversation_mode"] = params["conversation_mode"]

            # The session lock makes check-then-start atomic (plan 02). The
            # chat is captured here, so the worker keeps writing to it even if
            # the session later resumes another chat.
            with state.lock:
                if self.sessions.get(state.session_id) is not state:
                    # M4: a request that raced _get_session before session.stop
                    # released this session's lock and removed it (§3).
                    raise RpcError("AUTH_FAILED", "invalid session or token")
                if self._request_running(state):
                    raise RpcError("REQUEST_CONFLICT", "an active request is already running")
                # A fresh loop for this request (None: mock mode).
                loop = self._new_loop_for(state)
                if loop is None and state.authenticated and self.settings_store is not None:
                    # Mock mode is not reachable from the product (§2f).
                    raise self._no_model_error()
                loop_options = getattr(loop, "options", None)
                if (state.authenticated and loop_options is not None
                        and getattr(loop_options, "rescue", None) == "all"
                        and not getattr(state, "rescue_all_noticed", False)):
                    # §2f: rescue "all" is an explicit profile opt-in, and a
                    # notice explains it (once per session).
                    state.rescue_all_noticed = True
                    state.queue.push("system", "message", RESCUE_ALL_NOTICE, {"notice": "rescue_all"})
                if state.chat_id is None:
                    self._open_new_chat(state)
                chat_id = state.chat_id
                request_id = f"req_{os.urandom(6).hex()}"
                request = RequestState(request_id=request_id)
                state.active_request = request
                try:
                    if _wants_v2(state):
                        # A v2 display event (§2c): _push_v2 adds v: 2.
                        user_event = self._push_v2(
                            state, "user", "message", params["text"], {"request_id": request_id}
                        )
                    else:
                        user_event = state.queue.push(
                            "user", "message", params["text"], {"request_id": request_id}
                        )
                    self.store.append_events(chat_id, [user_event])

                    # Auto-set chat title from the first user message
                    manifest = self.store.get_manifest(chat_id)
                    if manifest and manifest.get("message_count", 0) <= 1:
                        title = params["text"][:60].strip()
                        if len(params["text"]) > 60:
                            title += "..."
                        self.store.update_title(chat_id, title)

                    conv_mode = str(state.settings.get("conversation_mode") or "local_first")
                    if loop is not None:
                        system_prompt = self._system_prompt_for_request(state, loop)
                        try:
                            prior_messages = self._prior_for(state, chat_id, conv_mode, loop, system_prompt)
                        except Exception:
                            if self.logger:
                                self.logger.warning("building the prior failed; sending without history",
                                                    exc_info=True)
                            prior_messages = None
                        thread = threading.Thread(
                            target=self._run_claude_loop_response,
                            args=(state.session_id, request_id, params["text"], request.cancel_event,
                                  prior_messages),
                            kwargs={"loop": loop, "chat_id": chat_id, "system_prompt": system_prompt},
                            daemon=True,
                        )
                    else:
                        thread = threading.Thread(
                            target=self._run_provider_response,
                            args=(state.session_id, request_id, params["text"], request.cancel_event, None),
                            daemon=True,
                        )
                    request.thread = thread
                    thread.start()
                except Exception:
                    self._clear_active(state, request_id)
                    raise

            reply: Dict[str, Any] = {"request_id": request_id}
            if state.authenticated:
                reply["chat_id"] = chat_id
            return reply

        if method == "chat.cancel":
            state = self._get_session(params["session_id"], session_token)
            if not state.active_request:
                return {"ok": True, "cancelled": False}
            if params.get("request_id") and params["request_id"] != state.active_request.request_id:
                return {"ok": True, "cancelled": False}
            state.active_request.cancel_event.set()
            return {"ok": True, "cancelled": True}

        if method == "chat.events.poll":
            state = self._get_session(params["session_id"], session_token)
            polled = state.queue.poll(
                after_seq=params["after_seq"], limit=params["limit"]
            )
            return polled

        if method == "chat.history.list":
            state = self._get_session(params["session_id"], session_token)
            _ = state
            rows = self.store.list_chats(
                limit=params["limit"], offset=params["offset"]
            )
            return {"items": rows}

        if method == "chat.history.get":
            state = self._get_session(params["session_id"], session_token)
            chat_id = params["chat_id"]
            manifest = self.store.get_manifest(chat_id)
            if manifest is None:
                raise RpcError("NOT_FOUND", f"chat {chat_id} not found")
            if getattr(state, "authenticated", False):
                # A token session replays the whole display log through
                # vm::apply (§2c Persistence): no tail cut and no tool_start,
                # and a v1 request's chunks are dropped when its message was stored.
                events = display_log(self.store.read_events(chat_id, limit=conversation.ALL_EVENTS))
            else:
                events = self.store.read_events(chat_id, limit=params["limit"])
            return {"chat_id": chat_id, "manifest": manifest, "events": events}

        if method == "chat.resume":
            state = self._get_session(params["session_id"], session_token)
            if state.authenticated:
                return self._resume_token_session(state, params["chat_id"])
            self._cancel_active_request(state)
            chat_id = params["chat_id"]
            manifest = self.store.get_manifest(chat_id)
            if manifest is None:
                raise RpcError("NOT_FOUND", f"chat {chat_id} not found")
            # Swap the session's chat_id and reset the event queue
            state.chat_id = chat_id
            state.queue.clear()
            # Push a lifecycle event so the Tcl side knows we switched
            state.queue.push("system", "lifecycle", "chat_resumed", {"chat_id": chat_id})
            return {
                "ok": True,
                "chat_id": chat_id,
                "title": manifest.get("title", ""),
                "message_count": manifest.get("message_count", 0),
            }

        # ---- Settings ----

        if method == "settings.get":
            state = self._get_session(params["session_id"], session_token)
            return {
                "settings": dict(state.settings),
                "key_sources": self.keys.get_sources(),
                "provider": self.provider_name,
                "agent_loop": self.has_agent_loop(state),
            }

        if method == "settings.set":
            state = self._get_session(params["session_id"], session_token)
            patch = dict(params.get("patch") or {})
            persisted = {key: patch[key] for key in PERSISTED_SETTING_KEYS if key in patch}
            owns_settings = bool(state.authenticated) and self.settings_store is not None
            if persisted and not owns_settings and set(persisted) - {"reasoning_visible"}:
                # reasoning_visible stays a per-session key for tokenless clients.
                self._require_auth(state)
            saved = None
            if owns_settings and persisted:
                try:
                    saved = self.settings_store.patch(persisted)
                except SettingsError as exc:
                    raise self._settings_rpc_error(exc)
            for name in ("model", "mode", "conversation_mode", "reasoning_visible", "debug_mode"):
                if name in patch:
                    state.settings[name] = patch[name]
            reply: Dict[str, Any] = {"ok": True, "settings": dict(state.settings)}
            if owns_settings:
                reply["persisted"] = saved if saved is not None else {
                    key: self._setting(key) for key in PERSISTED_SETTING_KEYS}
            return reply

        # ---- Provider switching ----
        #
        # The Tcl UI exposes a dropdown letting the user choose between
        # openrouter / anthropic-direct / ollama at runtime. We rebuild
        # both the simple provider and the Claude tool loop in-place so
        # the next chat.send uses the new backend. In-flight requests
        # keep running on whatever provider they started with — switching
        # mid-turn would be racy and isn't worth the complexity for a
        # single-user desktop tool.

        if method == "provider.set":
            state = self._get_session(params["session_id"], session_token)
            privileged = (bool(params.get("base_url")) or params.get("options") is not None
                          or bool(params.get("profile")))
            if privileged:
                self._require_auth(state)
            if state.authenticated and self.settings_store is not None:
                return self._provider_set_profile(state, params)
            requested = str(params["provider"] or "").strip().lower()
            if not requested:
                raise RpcError("INVALID_PARAMS", "provider is required")

            picked_model = str(params.get("model") or "").strip() or None
            try:
                provider_name, provider = build_provider(requested)
                agent_loop = self._base_loop_factory(
                    {"provider": requested, "model": picked_model}
                ) is not None
            except Exception as exc:
                raise RpcError(
                    "PROVIDER_INIT_FAILED",
                    f"failed to initialize provider '{requested}': {exc}",
                    {"provider": requested},
                )

            self.provider_name, self.provider = provider_name, provider
            self._loop_provider = requested
            self._loop_model = picked_model
            # Never install a shared loop: drop any loop assigned from
            # outside and go back to a fresh loop per request (§3).
            self._assigned_loop = None
            self._loop_factory = self._base_loop_factory

            if picked_model:
                state.settings["model"] = picked_model

            if self.logger:
                self.logger.info(
                    "provider switched to %s (agent_loop=%s, model=%s)",
                    self.provider_name,
                    agent_loop,
                    state.settings.get("model"),
                )

            return {
                "ok": True,
                "provider": self.provider_name,
                "agent_loop": agent_loop,
                "model": state.settings.get("model"),
            }

        # ---- Keys ----

        if method == "keys.save":
            _ = self._get_session(params["session_id"], session_token)
            result = self.keys.save(params["provider"], params["key"])
            return {"ok": bool(result.ok), "source": result.source, "message": result.message}

        if method == "keys.test":
            _ = self._get_session(params["session_id"], session_token)
            return self.keys.test(params["provider"])

        # ---- Legacy direct tool invocation (kept for Tcl-side manual testing) ----

        if method == "tool.run_vmd_command":
            state = self._get_session(params["session_id"], session_token)
            # This path is for direct Tcl-initiated calls, not the agent loop.
            # The agent loop drives tool calls through tool.command_result instead.
            tool_event = state.queue.push(
                "tool_start",
                "message",
                f"[VMD] {params['command'][:80]}",
                {
                    "tool_call_id": f"direct_{os.urandom(4).hex()}",
                    "tool_name": "run_vmd_command",
                    "tool_input": {"command": params["command"]},
                    "session_id": state.session_id,
                },
            )
            self.store.append_events(state.chat_id, [tool_event])
            return {"ok": True, "queued": True}

        if method == "tool.capture_snapshot":
            state = self._get_session(params["session_id"], session_token)
            tool_event = state.queue.push(
                "tool_start",
                "message",
                "[Snapshot] direct request",
                {
                    "tool_call_id": f"direct_{os.urandom(4).hex()}",
                    "tool_name": "capture_vmd_snapshot",
                    "tool_input": {
                        "width": params["width"],
                        "height": params["height"],
                    },
                    "session_id": state.session_id,
                },
            )
            self.store.append_events(state.chat_id, [tool_event])
            return {"ok": True, "queued": True}

        # ---- Tool result callback (posted by Tcl bridge) ----

        if method == "tool.ack":
            # C2: the executor acks before running a tool_start. Any ack stops
            # the pickup deadline; the answer is atomic against Stop.
            state = self._get_session(params["session_id"], session_token)
            owner = self.tool_bridge.get_call_session(params["call_key"])
            if owner is None:
                return {"proceed": False, "reason": "unknown call"}
            if owner != state.session_id:
                raise RpcError(
                    "AUTH_FAILED",
                    "call_key does not belong to this session",
                    {"call_key": params["call_key"]},
                )
            return self.tool_bridge.ack(state.session_id, params["call_key"], params["state"])

        if method == "tool.command_result":
            # tool.command_result is the only inbound channel from the Tcl
            # bridge after VMD has executed a tool call. Three checks:
            #   1. Session token must match (same as every other authed RPC).
            #   2. tool_call_id must correspond to a pending bridge call.
            #   3. The pending call must belong to *this* session — otherwise
            #      a session could resolve another session's pending tool.
            state = self._get_session(params["session_id"], session_token)

            call_key = params.get("call_key") or ""
            if call_key:
                owner = self.tool_bridge.get_call_session(call_key)
                if owner is None:
                    raise RpcError(
                        "TOOL_CALL_UNKNOWN",
                        "call_key is not known (never issued or long expired)",
                        {"call_key": call_key},
                    )
                if owner != state.session_id:
                    raise RpcError(
                        "AUTH_FAILED",
                        "call_key does not belong to this session",
                        {"call_key": call_key},
                    )
                reply = self.tool_bridge.post_result(state.session_id, params)
                if reply.get("accepted") and not reply.get("duplicate") and not _wants_v2(state):
                    # v1 transcript entry, as for tool_call_id results. A v2
                    # session gets tool.finished from the loop instead (§2c).
                    ok = bool(params["ok"]) and params.get("executed") != "no"
                    label = (
                        params.get("output", "")[:120]
                        if ok
                        else f"Error: {params.get('error', '')[:120]}"
                    )
                    result_event = state.queue.push(
                        "tool_result",
                        "message",
                        label,
                        {
                            "tool_call_id": params.get("tool_call_id") or "",
                            "call_key": call_key,
                            "ok": ok,
                            "late": bool(reply.get("late")),
                        },
                    )
                    # M7: stored in the chat that issued the call — not the
                    # session's current chat, which chat.resume may since
                    # have switched away from.
                    target_chat_id = self.tool_bridge.get_call_chat_id(call_key) or state.chat_id
                    if target_chat_id:
                        self.store.append_events(target_chat_id, [result_event])
                return dict(reply)

            tool_call_id = params["tool_call_id"]
            pending_session = self.tool_bridge.get_pending_session(
                tool_call_id, session_id=state.session_id)
            if pending_session is None:
                raise RpcError(
                    "TOOL_CALL_UNKNOWN",
                    "tool_call_id is not pending (already resolved or timed out)",
                    {"tool_call_id": tool_call_id},
                )
            if pending_session != state.session_id:
                raise RpcError(
                    "AUTH_FAILED",
                    "tool_call_id does not belong to this session",
                    {"tool_call_id": tool_call_id},
                )

            result = {
                "ok": params["ok"],
                "output": params.get("output") or "",
                "error": params.get("error") or "",
                "snapshot_file": params.get("snapshot_file") or "",
            }

            resolved = self.tool_bridge.resolve(tool_call_id, result, session_id=state.session_id)
            if not resolved:
                # Already timed out — log and ignore
                if self.logger:
                    self.logger.warning(
                        "tool.command_result for unknown/timed-out id=%s", tool_call_id
                    )

            # Persist a tool_result event for transcript history (v1 only; a
            # v2 session gets tool.finished from the loop instead, §2c).
            if not _wants_v2(state):
                label = (
                    result["output"][:120]
                    if result["ok"]
                    else f"Error: {result['error'][:120]}"
                )
                result_event = state.queue.push(
                    "tool_result",
                    "message",
                    label,
                    {"tool_call_id": tool_call_id, "ok": result["ok"]},
                )
                self.store.append_events(state.chat_id, [result_event])

            return {"ok": True, "resolved": resolved}

        # ---- M1 runtime RPCs (§2c Stage split, §3) ----

        if method == "runtime.info":
            state = self._get_session(params["session_id"], session_token)
            return self._runtime_info(state)

        if method == "session.set_cwd":
            state = self._get_session(params["session_id"], session_token)
            self._require_auth(state)
            path = os.path.realpath(os.path.expanduser(params["cwd"]))
            if not os.path.isdir(path):
                raise RpcError("INVALID_PARAMS", "cwd is not a directory", {"cwd": params["cwd"]})
            state.cwd = path
            return {"ok": True, "cwd": path}

        if method == "models.list":
            state = self._get_session(params["session_id"], session_token)
            if params.get("base_url"):
                self._require_auth(state)
            provider_name, base_url, _model, api_key = self._catalog_target(state, params)
            return provider_catalog.list_models(provider_name, base_url, api_key=api_key)

        if method == "provider.test":
            state = self._get_session(params["session_id"], session_token)
            if params.get("base_url"):
                self._require_auth(state)
            provider_name, base_url, model, api_key = self._catalog_target(state, params)
            return provider_catalog.test_provider(provider_name, base_url, model, api_key=api_key)

        raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")

    # ------------------------------------------------------------------
    # Recorder factory — one fresh RunRecorder per chat.send
    # ------------------------------------------------------------------

    def _build_recorder_for_session(self, state, meta: Optional[Dict[str, Any]] = None) -> RunRecorder | None:
        """Build a RunRecorder for this chat.send, or None.

        Resolution rules:
          1. ``VMD_AI_RECORDER=off`` → no recorder, return None.
          2. ``state.cwd`` is a real directory → ``<cwd>/.vmdai_runs/``.
          3. Otherwise fall back to ``~/.vmdai/runs/`` so we never
             silently drop the artifact (option (c) in the plan).

        ``meta`` (C6, product runs only) adds the provenance/usage/counts
        manifest keys and the provenance header lines.

        Returns None on any construction failure — the recorder is a
        side-channel; failing to build one must never break chat.send.
        """
        if os.getenv("VMD_AI_RECORDER", "on").lower() == "off":
            return None
        try:
            cwd = (state.cwd or "").strip()
            if cwd and os.path.isdir(cwd):
                return RunRecorder.for_cwd(cwd, meta=meta)
            # Centralized fallback so we don't pollute the home dir
            # directly — everything lives under ~/.vmdai/runs/<task_id>/.
            fallback = Path(os.path.expanduser("~/.vmdai")) / "runs"
            return RunRecorder(runs_root=fallback, meta=meta)
        except Exception:
            if self.logger:
                self.logger.warning(
                    "recorder construction failed", exc_info=True,
                )
            return None

    def _recorder_meta(self, state, loop, request_id: str) -> Dict[str, Any]:
        """C6 static provenance for a product run's recorder manifest."""
        options = getattr(loop, "options", None)
        base_url = ""
        if options is not None and getattr(options, "base_url", None):
            base_url = str(options.base_url)
        elif getattr(loop, "_is_ollama", False):
            base_url = str(loop.api_key or "")
        opts = None
        if options is not None:
            opts = options.to_dict()
            if opts.get("base_url"):
                opts["base_url"] = strip_url_secrets(str(opts["base_url"]))
        try:
            vision = bool(loop._vision_enabled())
        except Exception:
            vision = False
        # The prompt before the per-request <session> block (the variant plus
        # today's mode line, exactly as P04-T06's _system_prompt_for_request
        # builds it), plus the wiki addendum run() appends when wiki is on
        # (C6 Hashes).
        mode = str(state.settings.get("mode") or "work")
        prompt = chatvmd_system_prompt(vision) + f"\n\nMode: {mode}."
        if getattr(loop, "wiki_store", None) is not None:
            prompt += WIKI_SYSTEM_PROMPT_ADDENDUM
        profile_name = None
        store = getattr(self, "settings_store", None)
        if store is not None:
            try:
                profile_name = store.active_profile()[0]
            except Exception:
                profile_name = None
        return {
            "request_id": request_id,
            "profile": profile_name,
            "provider": loop.provider_name,
            "base_url": strip_url_secrets(base_url) if base_url else None,
            "model": loop.model,
            "model_digest": None,
            "runtime_version": RUNTIME_VERSION,
            "vmd_env": getattr(state, "vmd_env", None),
            "options": opts,
            "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "tools_sha256": _canonical_sha256(_tools_as_sent(loop)),
        }

    # ------------------------------------------------------------------
    # Product bridge support (plan 05)
    # ------------------------------------------------------------------

    def _bridge_session(self, session_id: str) -> Optional[BridgeSession]:
        """What VmdToolBridge needs to know about ``session_id`` (None if unknown)."""
        state = self.sessions.get(session_id)
        if state is None:
            return None
        chat_dir = None
        if state.chat_id:
            try:
                chat_dir = Path(self.store.chat_dir(state.chat_id))
            except Exception:
                chat_dir = None
        exec_s, grace_s = self._tool_timeouts()
        return BridgeSession(
            chat_dir=chat_dir,
            cwd=str(state.cwd or ""),
            authenticated=bool(getattr(state, "authenticated", False)),
            snapshot_dir=self._snapshot_dir_for(state.session_id),
            exec_timeout_s=exec_s,
            cancel_grace_s=grace_s,
        )

    def _snapshot_dir_for(self, session_id: str) -> Path:
        """Per-session 0700 temp dir where the plugin renders snapshots (spec 2d)."""
        with self._snapshot_lock:
            path = self._snapshot_dirs.get(session_id)
            if path is None or not os.path.isdir(path):
                path = tempfile.mkdtemp(prefix="vmdai_snap_")
                self._snapshot_dirs[session_id] = path
        return Path(path)

    def _drop_snapshot_dir(self, session_id: str) -> None:
        """Delete the per-session snapshot temp dir (it only ever holds renders)."""
        with self._snapshot_lock:
            path = self._snapshot_dirs.pop(session_id, None)
        if path:
            shutil.rmtree(path, ignore_errors=True)

    def _tool_timeouts(self) -> Tuple[Optional[float], Optional[float]]:
        """(tool_exec_timeout_s, cancel_grace_s) from settings.json; None = bridge default.

        Read on every tool call, so a changed setting applies to the next
        call. settings_store validates exec >= 1 and grace >= 0 (0 = do not
        wait for a running command after Stop).
        """
        store = getattr(self, "settings_store", None)
        if store is None:
            return None, None
        try:
            data = store.load()
        except Exception:
            return None, None
        if not isinstance(data, dict):
            return None, None

        def _number(key: str, minimum: float) -> Optional[float]:
            try:
                value = float(data.get(key))
            except (TypeError, ValueError):
                return None
            return value if value >= minimum else None

        return _number("tool_exec_timeout_s", 1.0), _number("cancel_grace_s", 0.0)

    def _on_late_result(self, session_id: str, call_key: str, info: Dict[str, Any]) -> None:
        """A tool result arrived after its request gave up on it (§2b Late results, §2d).

        It is stored as a ``late_result`` line in the chat the call belonged
        to, so build_prior can note it before the next prompt. A v2 session
        still on that chat also gets a second ``tool.finished`` with
        ``late: true`` for the call_key. VmdToolBridge calls this once per
        accepted late result (duplicates are refused), even after the run's
        request.finished or after the next request has started.
        """
        chat_dir = info.get("chat_dir")
        if chat_dir:
            try:
                conversation.Appender(Path(chat_dir), str(info.get("request_id") or "")).append_late_result(
                    call_key,
                    bool(info.get("ok", False)),
                    str(info.get("executed") or "yes"),
                    str(info.get("output") or ""),
                    str(info.get("error") or ""),
                )
            except Exception:
                if self.logger:
                    self.logger.warning("could not store late result %s", call_key, exc_info=True)
        try:
            self._push_late_finished(session_id, call_key, info)
        except Exception:
            if self.logger:
                self.logger.warning("could not emit the late tool.finished %s", call_key, exc_info=True)

    def _push_late_finished(self, session_id: str, call_key: str,
                            info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The late ``tool.finished`` for a v2 session still on the call's chat (§2c, §2d).

        It carries the original request_id and call_key, so the view-model
        updates that row in place (state "late"). v1 sessions get only the
        late_result line.
        """
        state = self.sessions.get(session_id)
        if state is None or not _wants_v2(state):
            return None
        chat_dir = info.get("chat_dir")
        chat_id = Path(str(chat_dir)).name if chat_dir else None
        if not chat_id or chat_id != state.chat_id:
            return None
        duration = info.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            duration = 0
        meta = _tool_finished_meta(call_key, str(info.get("tool_name") or ""), "tcl", info,
                                   float(duration), late=True)
        meta["request_id"] = str(info.get("request_id") or "")
        event = self._push_v2(state, "system", "state", "", meta)
        self._persist_display(chat_id, event)      # "tool.finished (including late:true ones)"
        return event

    # ------------------------------------------------------------------
    # Background thread: Claude agent loop
    # ------------------------------------------------------------------

    def _make_on_event(self, state: SessionState, request: RequestState) -> "_EventMapper":
        """The on_event sink of one request (§2a, §2c); an ``_EventMapper``.

        It is a Callable[[Dict[str, Any]], None]. A v2 session gets every
        loop item as a queue event; a v1 session gets none (its events come
        from the legacy callbacks), and the turn is tracked for both.
        """
        return _EventMapper(self, state, request)

    def _push_v2(self, state: SessionState, role: str, event_type: str, text: str,
                 metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Push one v2 display event (§2c): the metadata gains ``v: 2``."""
        meta = dict(metadata or {})
        meta["v"] = 2
        return state.queue.push(role, event_type, text, meta)

    def _persist_display(self, chat_id: Optional[str], event: Optional[Dict[str, Any]]) -> bool:
        """Append one v2 display event to chats/<id>/events.jsonl (§2c Persistence).

        Live-only kinds are skipped. The manifest is not touched here;
        _EventMapper touches it once per request, at request.finished.
        """
        if not chat_id or not isinstance(event, dict) or not is_display_event(event):
            return False
        try:
            self.store.append_display_events(chat_id, [event])
        except Exception:
            if self.logger:
                self.logger.warning("could not persist a display event to %s", chat_id, exc_info=True)
            return False
        return True

    def _run_claude_loop_response(
        self,
        session_id: str,
        request_id: str,
        prompt: str,
        cancel_event: threading.Event,
        prior_messages: Optional[list] = None,
        loop: Optional[ClaudeToolLoop] = None,
        chat_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        """Full agentic response on a daemon thread (§4).

        chat.send passes the per-request loop, the chat captured when the
        request started, and the system prompt the prior was budgeted for.
        Token sessions also get a messages.jsonl Appender (full memory, §2b).

        v2 sessions: request.started is the first event, and request.finished
        comes from the ``finally`` on every path, including failures before
        loop.run (§2c "request.finished is guaranteed"). An error becomes one
        v2 error event with code, http_status, hint and action (§2f). The
        legacy callbacks do nothing. v1 sessions keep today's events.
        """
        state = self.sessions.get(session_id)
        if state is None:
            return
        if loop is None:
            # chat.send always passes the request's loop (P03-T04); building
            # one here could raise PROVIDER_INIT_FAILED on this thread.
            self._clear_active(state, request_id)
            return
        if chat_id is None:
            chat_id = state.chat_id
        request = state.active_request
        if request is None or request.request_id != request_id:
            request = RequestState(request_id=request_id)
        mapper = self._make_on_event(state, request)
        mapper.chat_id = chat_id
        v2 = mapper.v2
        started = time.monotonic()
        chunk_events: List[Dict[str, Any]] = []
        events_to_persist: List[Dict[str, Any]] = []
        failure_text: Optional[str] = None
        entered_run = False

        def on_chunk(chunk: str) -> None:
            if v2:
                return  # the loop's assistant chunk items carry the text (§2a)
            chunk_events.append(
                state.queue.push("assistant", "chunk", chunk, {"request_id": request_id})
            )

        def on_tool_start(tool_name: str, tool_input: dict) -> None:
            # Tool start events are pushed directly by VmdToolBridge
            pass

        def on_tool_result(tool_id: str, tool_name: str, result: dict) -> None:
            # v1: tool.command_result writes the transcript entry; v2: tool.finished
            pass

        # Token sessions always run their profile's model (§2h); the session
        # model override stays for tokenless clients only (P03-T04/T08). A
        # tokenless session is always v1, so this never touches a v2 request.
        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        if not state.authenticated and model and model != loop.model:
            if loop is self._assigned_loop:
                loop = ClaudeToolLoop(
                    provider_name=loop.provider_name,
                    api_key=loop.api_key,
                    model=model,
                    timeout=loop.timeout,
                    docs_search=self.docs_search,
                    wiki_store=self.wiki_store,
                )
            else:
                loop.model = model

        prev_recorder = loop.recorder
        try:
            if v2:
                mapper.push("system", "state", "", self._request_started_meta(loop, request_id, chat_id))
            if system_prompt is None:
                system_prompt = self._system_prompt_for_request(state, loop)
            meta = None
            if getattr(state, "authenticated", False):
                try:
                    meta = self._recorder_meta(state, loop, request_id)
                except Exception:
                    meta = None
                    if self.logger:
                        self.logger.warning("recorder provenance failed", exc_info=True)
            recorder = self._build_recorder_for_session(state, meta)
            loop.recorder = recorder
            mapper.recorder = recorder
            messages_out = None
            if getattr(state, "authenticated", False) and chat_id:
                messages_out = conversation.Appender(self.store.chat_dir(chat_id), request_id)
            ctx = RunContext(request_id=request_id, chat_id=chat_id or "",
                             on_event=mapper, messages_out=messages_out)
            entered_run = True
            output = loop.run(
                prompt=prompt,
                system_prompt=system_prompt,
                tool_bridge=self.tool_bridge,
                session_id=session_id,
                session_queue=state.queue,
                cancel_event=cancel_event,
                on_chunk=on_chunk,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
                prior_messages=prior_messages,
                ctx=ctx,
            )
        except ClaudeLoopError as exc:
            failure_text = str(exc) or exc.__class__.__name__
            if v2:
                mapper.push("error", "message", failure_text, self._error_meta(exc))
            else:
                events_to_persist.append(state.queue.push(
                    "error", "message", f"Agent error: {exc}",
                    {"request_id": request_id, "provider": self.provider_name},
                ))
        except Exception as exc:
            failure_text = f"Unexpected error: {exc}"
            if v2:
                mapper.push("error", "message", failure_text, self._error_meta(exc))
            else:
                events_to_persist.append(state.queue.push(
                    "error", "message", failure_text, {"request_id": request_id},
                ))
        else:
            if not v2:
                events_to_persist.extend(chunk_events)
                if cancel_event.is_set():
                    events_to_persist.append(state.queue.push(
                        "system", "lifecycle", "cancelled", {"request_id": request_id}))
                else:
                    events_to_persist.append(state.queue.push(
                        "assistant", "message", output, {"request_id": request_id}))
        finally:
            loop.recorder = prev_recorder
            if v2:
                try:
                    mapper.push("system", "state", "", self._request_finished_meta(
                        loop, mapper, entered_run=entered_run,
                        failure_text=failure_text, started=started))
                except Exception:
                    if self.logger:
                        self.logger.warning("request.finished failed for %s", request_id, exc_info=True)
            if events_to_persist and chat_id:
                self.store.append_events(chat_id, events_to_persist)
            self._clear_active(state, request_id)

    def _request_started_meta(self, loop: Any, request_id: str, chat_id: Optional[str]) -> Dict[str, Any]:
        """request.started metadata (§2c): what this request runs with."""
        options = getattr(loop, "options", None)
        try:
            vision = bool(loop._vision_enabled())
        except Exception:
            vision = False
        try:
            max_turns = int(self._max_turns_for(loop))
        except Exception:
            max_turns = int(getattr(loop, "MAX_TURNS", 28))
        return {
            "kind": "request.started",
            "request_id": request_id,
            "chat_id": chat_id,
            "provider": str(getattr(loop, "provider_name", "") or ""),
            "model": str(getattr(loop, "model", "") or ""),
            "max_turns": max_turns,
            "vision": vision,
            "think": getattr(options, "think", None) if options is not None else None,
        }

    @staticmethod
    def _request_finished_meta(loop: Any, mapper: "_EventMapper", *, entered_run: bool,
                               failure_text: Optional[str], started: float) -> Dict[str, Any]:
        """request.finished metadata (§2c), filled from whatever is known.

        Before loop.run is entered nothing ran: status error, zero turns.
        After it, the loop's last_* fields describe this run (run() resets
        them first). C4: a wrap-up that failed leaves its message in error.
        """
        if entered_run:
            status = "error" if failure_text is not None else str(getattr(loop, "last_status", None) or "complete")
            turns = int(getattr(loop, "last_turns", 0) or 0)
            tool_calls = int(getattr(loop, "last_tool_calls", 0) or 0)
            final_text_empty = bool(getattr(loop, "last_final_text_empty", True))
            usage = dict(getattr(loop, "last_usage", None) or {})
            wrapped_up = bool(getattr(loop, "last_wrapped_up", False))
        else:
            status, turns, tool_calls, final_text_empty, usage, wrapped_up = "error", 0, 0, True, {}, False
        error = failure_text
        if error is None and getattr(loop, "last_wrap_up_error", None):
            error = str(loop.last_wrap_up_error)
        return {
            "kind": "request.finished",
            "request_id": mapper.request_id,
            "status": status,
            "wrapped_up": wrapped_up,
            "turns": turns,
            "tool_calls": tool_calls,
            "final_text_empty": final_text_empty,
            "duration_ms": int(round((time.monotonic() - started) * 1000)),
            "usage": {"input_tokens_evaluated": usage.get("input_tokens_evaluated"),
                      "output_tokens": usage.get("output_tokens")},
            "error": error,
            "run_dir": mapper.run_dir,
        }

    @staticmethod
    def _error_meta(exc: BaseException) -> Dict[str, Any]:
        """Metadata of a v2 error event (§2c, §2f Error codes).

        code is ClaudeLoopError.code (unreachable, auth, billing,
        model_not_found) or "other" for anything else; action follows code.
        """
        code = str(getattr(exc, "code", "") or "") if isinstance(exc, ClaudeLoopError) else ""
        if code not in ACTION_FOR_CODE:
            code = "other"
        http_status = getattr(exc, "http_status", None)
        if isinstance(http_status, bool) or not isinstance(http_status, int):
            http_status = None
        return {
            "code": code,
            "http_status": http_status,
            "hint": str(getattr(exc, "hint", "") or ""),
            "action": ACTION_FOR_CODE[code],
        }

    # ------------------------------------------------------------------
    # Background thread: simple provider (mock / fallback)
    # ------------------------------------------------------------------

    def _run_provider_response(
        self,
        session_id: str,
        request_id: str,
        prompt: str,
        cancel_event: threading.Event,
        prior_messages: Optional[list] = None,
    ) -> None:
        """Simple non-agentic streaming: used when no API key is set (mock mode).

        v1 sessions keep today's events. v2 sessions get the envelope of a
        one-turn run: request.started, turn.started, chunks, the sealed final
        assistant/message and request.finished from the ``finally`` (§2c).
        """
        state = self.sessions.get(session_id)
        if state is None:
            return
        request = state.active_request
        if request is None or request.request_id != request_id:
            request = RequestState(request_id=request_id)
        mapper = self._make_on_event(state, request)
        v2 = mapper.v2
        started = time.monotonic()
        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        chunk_events: List[Dict[str, Any]] = []
        events_to_persist: List[Dict[str, Any]] = []
        failure_text: Optional[str] = None
        output = ""

        def on_chunk(chunk: str) -> None:
            if v2:
                mapper.push("assistant", "chunk", chunk, {"turn": 1})
                return
            chunk_events.append(
                state.queue.push("assistant", "chunk", chunk, {"request_id": request_id})
            )

        try:
            if v2:
                mapper.push("system", "state", "", {
                    "kind": "request.started", "request_id": request_id, "chat_id": state.chat_id,
                    "provider": self.provider_name, "model": model, "max_turns": 1,
                    "vision": False, "think": None,
                })
                request.turn = 1
                mapper.push("system", "state", "", {"kind": "turn.started", "turn": 1})
            output = self.provider.stream_response(
                prompt=prompt,
                cancel_event=cancel_event,
                on_chunk=on_chunk,
                model=model,
                system_prompt=self._system_prompt_for_mode(
                    str(state.settings.get("mode") or "work")
                ),
            )
        except Exception as exc:
            failure_text = f"Provider error: {exc}"
            if v2:
                mapper.push("error", "message", failure_text, self._error_meta(exc))
            else:
                events_to_persist.append(state.queue.push(
                    "error", "message", failure_text,
                    {"request_id": request_id, "provider": self.provider_name},
                ))
        else:
            if v2:
                mapper.push("assistant", "message", output, {"turn": 1, "final": True})
            else:
                events_to_persist.extend(chunk_events)
                if cancel_event.is_set():
                    events_to_persist.append(state.queue.push(
                        "system", "lifecycle", "cancelled", {"request_id": request_id}))
                else:
                    events_to_persist.append(state.queue.push(
                        "assistant", "message", output, {"request_id": request_id}))
        finally:
            if v2:
                if failure_text is not None:
                    status = "error"
                elif cancel_event.is_set():
                    status = "cancelled"
                else:
                    status = "complete"
                try:
                    mapper.push("system", "state", "", {
                        "kind": "request.finished", "request_id": request_id, "status": status,
                        "wrapped_up": False, "turns": 1, "tool_calls": 0,
                        "final_text_empty": not output,
                        "duration_ms": int(round((time.monotonic() - started) * 1000)),
                        "usage": {"input_tokens_evaluated": None, "output_tokens": None},
                        "error": failure_text, "run_dir": None,
                    })
                except Exception:
                    if self.logger:
                        self.logger.warning("request.finished failed for %s", request_id, exc_info=True)
            if events_to_persist and state.chat_id:
                self.store.append_events(state.chat_id, events_to_persist)
            self._clear_active(state, request_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cancel_active_request(self, state) -> None:
        active = state.active_request
        if not active:
            return
        active.cancel_event.set()

    # ------------------------------------------------------------------
    # Memory, chats and locks (§2b)
    # ------------------------------------------------------------------

    def _new_loop_for(self, state) -> Optional[ClaudeToolLoop]:
        """A fresh loop for one request of this session, or None (mock mode).

        The one place request code builds a loop: plan 02's _build_loop
        (PROVIDER_INIT_FAILED on errors) over profile_for_session.
        """
        return self._build_loop(self.profile_for_session(state))

    @staticmethod
    def _request_running(state) -> bool:
        active = state.active_request
        return active is not None and (active.thread is None or active.thread.is_alive())

    @staticmethod
    def _clear_active(state, request_id: str) -> None:
        if state.active_request is not None and state.active_request.request_id == request_id:
            state.active_request = None

    @staticmethod
    def _release_chat_lock(state) -> None:
        lock = getattr(state, "chat_lock", None)
        if lock is not None:
            lock.release()
        state.chat_lock = None

    def _open_new_chat(self, state) -> str:
        """Create this session's chat on its first chat.send and lock it."""
        chat_id = self.store.create_chat(title_hint="VMD AI Chat")
        lock = ChatLock(self.store.chat_dir(chat_id))
        if not lock.acquire():
            raise RpcError("CHAT_LOCKED", "could not lock the new chat", {"chat_id": chat_id})
        self._release_chat_lock(state)
        state.chat_lock = lock
        state.chat_id = chat_id
        return chat_id

    def _resume_token_session(self, state, chat_id: str) -> Dict[str, Any]:
        """chat.resume for a token session: conflicts, per-chat lock, last_seq."""
        with state.lock:
            if self.sessions.get(state.session_id) is not state:
                # M4: a request that raced _get_session before session.stop
                # released this session's lock and removed it (§3).
                raise RpcError("AUTH_FAILED", "invalid session or token")
            if self._request_running(state):
                raise RpcError("REQUEST_CONFLICT",
                               "a request is running; stop it before switching chats",
                               {"chat_id": chat_id})
            manifest = self.store.get_manifest(chat_id)
            if manifest is None:
                raise RpcError("NOT_FOUND", f"chat {chat_id} not found")
            if chat_id != state.chat_id:
                lock = ChatLock(self.store.chat_dir(chat_id))
                if not lock.acquire():
                    raise RpcError("CHAT_LOCKED", "This chat is open in another VMD window.",
                                   {"chat_id": chat_id})
                self._release_chat_lock(state)
                state.chat_lock = lock
                state.chat_id = chat_id
            # §2c: a token session's seq never resets; resume drops what is
            # queued and polling after last_seq delivers chat_resumed below.
            state.queue.drop_pending()
            last_seq = state.queue.last_seq
            state.queue.push("system", "lifecycle", "chat_resumed", {"chat_id": chat_id})
        return {
            "ok": True,
            "chat_id": chat_id,
            "title": manifest.get("title", ""),
            "message_count": self.store.recount_messages(chat_id),
            "last_seq": last_seq,
        }

    def _system_prompt_for_request(self, state, loop) -> str:
        """The CHATVMD prompt for one request of ``loop`` (spec 2g).

        Picks the vision or non-vision variant from the loop's resolved
        vision and gives a non-vision product loop the tool-description
        overrides, so the prompt and the tool list agree. Then appends
        today's mode line, the per-request <session> block and any
        context_providers text. Resolving vision here also means images
        that build_prior returns are handled correctly from the first call."""
        try:
            vision = bool(loop._vision_enabled())
        except Exception:
            vision = False
        options = getattr(loop, "options", None)
        if options is not None and not vision and not options.tool_overrides:
            loop.options = dataclasses.replace(options, tool_overrides=dict(NON_VISION_TOOL_OVERRIDES))
        mode = str(state.settings.get("mode") or "work")
        prompt = chatvmd_system_prompt(vision) + f"\n\nMode: {mode}."
        prompt += session_block(str(state.cwd or ""), str(getattr(loop, "model", "") or ""))
        for provider in list(self.context_providers):
            try:
                extra = str(provider(state) or "").strip()
            except Exception:
                if self.logger:
                    self.logger.warning("context provider failed", exc_info=True)
                continue
            if extra:
                prompt += "\n\n" + extra
        return prompt

    def _run_budget_for(self, loop: ClaudeToolLoop, system_prompt: str) -> int:
        """run_budget for this loop (§2b Budget), counting the wiki addendum run() adds."""
        prompt = system_prompt
        if loop.wiki_store is not None:
            prompt = prompt + WIKI_SYSTEM_PROMPT_ADDENDUM
        tools_chars = len(json.dumps(loop._tools_for_turn()))
        context_tokens = conversation.context_tokens_for(loop.provider_name, getattr(loop, "options", None))
        return conversation.compute_run_budget(context_tokens, len(prompt), tools_chars)

    def _prior_for(self, state, chat_id: str, conv_mode: str, loop: ClaudeToolLoop,
                   system_prompt: str) -> Optional[List[Dict[str, Any]]]:
        """Prior messages for this request (§2b), or None.

        Token sessions in "full" mode read messages.jsonl, seeding it once
        from a legacy chat's text history. hybrid_resume/resume_only (and
        "full" from a tokenless session) use the legacy text path with the
        duplicate-prompt fix. local_first sends no history.
        """
        if state.authenticated and conv_mode == "full":
            chat_dir = self.store.chat_dir(chat_id)
            if not conversation.messages_path(chat_dir).exists():
                legacy = conversation.legacy_prior(
                    self.store.read_events(chat_id, limit=conversation.ALL_EVENTS))
                conversation.import_legacy(chat_dir, legacy)
            prior = conversation.build_prior(
                chat_dir,
                self._run_budget_for(loop, system_prompt),
                conversation.max_images_for(loop.provider_name),
            )
            return prior or None
        if conv_mode in ("hybrid_resume", "resume_only", "full"):
            events = self.store.read_events(chat_id, limit=conversation.ALL_EVENTS)
            return conversation.trim_text_prior(
                conversation.legacy_prior(events), self._run_budget_for(loop, system_prompt)) or None
        return None

    @staticmethod
    def _system_prompt_for_mode(mode: str) -> str:
        if str(mode or "").strip().lower() == "tutor":
            return "Mode: Tutor. Explain commands and reasoning while you answer."
        return "Mode: Work. Be concise and task-oriented."
