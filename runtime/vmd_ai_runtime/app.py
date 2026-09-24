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

import os
import threading
from typing import Any, Dict

from pathlib import Path

from .claude_loop import ClaudeToolLoop, ClaudeLoopError, VMD_SYSTEM_PROMPT, build_claude_loop, events_to_messages
from .recorder import RunRecorder
from .constants import CAPABILITIES, DEFAULT_SETTINGS
from .docs_search import DocsSearch
from .errors import RpcError
from .keys import KeyStore
from .logging_utils import redact_sensitive
from .protocol import validate_method_params, validate_rpc_payload
from .provider import (
    build_provider,
    resolve_ollama_model,
    resolve_openrouter_api_key,
)
from .sessions import RequestState, SessionManager
from .store import ChatStore
from .tool_bridge import VmdToolBridge
from .wiki_store import WikiStore


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
    ):
        self.sessions = SessionManager()
        self.store = ChatStore(store_dir)
        # KeyStore.__init__ hydrates os.environ from any keys saved in the
        # OS keychain, so the provider auto-detect below sees them.
        self.keys = KeyStore()
        self.logger = logger
        self.tool_bridge = VmdToolBridge()
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
                from .provider import resolve_anthropic_api_key
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

        # Build the Claude tool loop (None if no key / mock mode). The
        # docs_search instance is wired in here so the agent can call
        # search_docs when an index is available; the wiki_store is wired
        # in so the agent can call wiki_list / wiki_read / wiki_update /
        # wiki_verify_pins as the persistent knowledge base.
        self.claude_loop: ClaudeToolLoop | None = build_claude_loop(
            env_provider,
            docs_search=self.docs_search,
            wiki_store=self.wiki_store,
        )

        if self.logger:
            self.logger.info(
                "provider=%s agent_loop=%s",
                self.provider_name,
                self.claude_loop is not None,
            )

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

    def _dispatch(self, method: str, params: Dict[str, Any], session_token: str) -> Dict[str, Any]:

        # ---- Session lifecycle ----

        if method == "session.start":
            chat_id = self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(cwd=params["cwd"], chat_id=chat_id)
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
            return {
                "session_id": state.session_id,
                "session_token": state.session_token,
                "capabilities": CAPABILITIES,
                "defaults": dict(state.settings),
                "chat_id": chat_id,
                "provider": self.provider_name,
                "agent_loop": self.claude_loop is not None,
            }

        if method == "session.stop":
            state = self._get_session(params["session_id"], session_token)
            self._cancel_active_request(state)
            self.sessions.remove(state.session_id)
            return {"ok": True}

        # ---- Chat ----

        if method == "chat.send":
            state = self._get_session(params["session_id"], session_token)
            if params.get("model"):
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
            if params.get("conversation_mode"):
                state.settings["conversation_mode"] = params["conversation_mode"]

            with threading.Lock():
                if (
                    state.active_request
                    and state.active_request.thread
                    and state.active_request.thread.is_alive()
                ):
                    raise RpcError("REQUEST_CONFLICT", "an active request is already running")

            request_id = f"req_{os.urandom(6).hex()}"
            request = RequestState(request_id=request_id)
            state.active_request = request

            user_event = state.queue.push(
                "user", "message", params["text"], {"request_id": request_id}
            )
            self.store.append_events(state.chat_id, [user_event])

            # Auto-set chat title from the first user message
            manifest = self.store.get_manifest(state.chat_id)
            if manifest and manifest.get("message_count", 0) <= 1:
                title = params["text"][:60].strip()
                if len(params["text"]) > 60:
                    title += "..."
                self.store.update_title(state.chat_id, title)

            # Use Claude tool loop when available; fall back to simple provider
            if self.claude_loop is not None:
                target = self._run_claude_loop_response
            else:
                target = self._run_provider_response

            # Build prior context when conversation_mode asks for it
            conv_mode = str(state.settings.get("conversation_mode") or "local_first")
            prior_messages = None
            if conv_mode in ("hybrid_resume", "resume_only") and self.claude_loop is not None:
                try:
                    raw_events = self.store.read_events(state.chat_id, limit=200)
                    prior_messages = events_to_messages(raw_events)
                except Exception:
                    prior_messages = None

            thread = threading.Thread(
                target=target,
                args=(state.session_id, request_id, params["text"], request.cancel_event, prior_messages),
                daemon=True,
            )
            request.thread = thread
            thread.start()
            return {"request_id": request_id}

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
            _ = state
            chat_id = params["chat_id"]
            manifest = self.store.get_manifest(chat_id)
            if manifest is None:
                raise RpcError("NOT_FOUND", f"chat {chat_id} not found")
            events = self.store.read_events(chat_id, limit=params["limit"])
            return {"chat_id": chat_id, "manifest": manifest, "events": events}

        if method == "chat.resume":
            state = self._get_session(params["session_id"], session_token)
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
                "agent_loop": self.claude_loop is not None,
            }

        if method == "settings.set":
            state = self._get_session(params["session_id"], session_token)
            patch = dict(params.get("patch") or {})
            for name in ("model", "mode", "conversation_mode", "reasoning_visible", "debug_mode"):
                if name in patch:
                    state.settings[name] = patch[name]
            return {"ok": True, "settings": dict(state.settings)}

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
            requested = str(params["provider"] or "").strip().lower()
            if not requested:
                raise RpcError("INVALID_PARAMS", "provider is required")

            picked_model = str(params.get("model") or "").strip() or None
            try:
                self.provider_name, self.provider = build_provider(requested)
                self.claude_loop = build_claude_loop(
                    requested,
                    docs_search=self.docs_search,
                    wiki_store=self.wiki_store,
                    model=picked_model,
                )
            except Exception as exc:
                raise RpcError(
                    "PROVIDER_INIT_FAILED",
                    f"failed to initialize provider '{requested}': {exc}",
                    {"provider": requested},
                )

            if picked_model:
                state.settings["model"] = picked_model

            if self.logger:
                self.logger.info(
                    "provider switched to %s (agent_loop=%s, model=%s)",
                    self.provider_name,
                    self.claude_loop is not None,
                    state.settings.get("model"),
                )

            return {
                "ok": True,
                "provider": self.provider_name,
                "agent_loop": self.claude_loop is not None,
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

        if method == "tool.command_result":
            # tool.command_result is the only inbound channel from the Tcl
            # bridge after VMD has executed a tool call. Three checks:
            #   1. Session token must match (same as every other authed RPC).
            #   2. tool_call_id must correspond to a pending bridge call.
            #   3. The pending call must belong to *this* session — otherwise
            #      a session could resolve another session's pending tool.
            state = self._get_session(params["session_id"], session_token)

            tool_call_id = params["tool_call_id"]
            pending_session = self.tool_bridge.get_pending_session(tool_call_id)
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

            resolved = self.tool_bridge.resolve(tool_call_id, result)
            if not resolved:
                # Already timed out — log and ignore
                if self.logger:
                    self.logger.warning(
                        "tool.command_result for unknown/timed-out id=%s", tool_call_id
                    )

            # Persist a tool_result event for transcript history
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

        raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")

    # ------------------------------------------------------------------
    # Recorder factory — one fresh RunRecorder per chat.send
    # ------------------------------------------------------------------

    def _build_recorder_for_session(self, state) -> RunRecorder | None:
        """Build a RunRecorder for this chat.send, or None.

        Resolution rules:
          1. ``VMD_AI_RECORDER=off`` → no recorder, return None.
          2. ``state.cwd`` is a real directory → ``<cwd>/.vmdai_runs/``.
          3. Otherwise fall back to ``~/.vmdai/runs/`` so we never
             silently drop the artifact (option (c) in the plan).

        Returns None on any construction failure — the recorder is a
        side-channel; failing to build one must never break chat.send.
        """
        if os.getenv("VMD_AI_RECORDER", "on").lower() == "off":
            return None
        try:
            cwd = (state.cwd or "").strip()
            if cwd and os.path.isdir(cwd):
                return RunRecorder.for_cwd(cwd)
            # Centralized fallback so we don't pollute the home dir
            # directly — everything lives under ~/.vmdai/runs/<task_id>/.
            fallback = Path(os.path.expanduser("~/.vmdai")) / "runs"
            return RunRecorder(runs_root=fallback)
        except Exception:
            if self.logger:
                self.logger.warning(
                    "recorder construction failed", exc_info=True,
                )
            return None

    # ------------------------------------------------------------------
    # Background thread: Claude agent loop
    # ------------------------------------------------------------------

    def _run_claude_loop_response(
        self,
        session_id: str,
        request_id: str,
        prompt: str,
        cancel_event: threading.Event,
        prior_messages: list | None = None,
    ) -> None:
        """
        Full agentic response: Claude calls VMD tools as needed until done.
        Runs on a daemon thread; pushes chunk/lifecycle events to the queue.
        """
        state = self.sessions.get(session_id)
        if state is None:
            return

        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        mode = str(state.settings.get("mode") or "work")
        system_prompt = VMD_SYSTEM_PROMPT + f"\n\nMode: {mode}."
        chunk_events = []

        def on_chunk(chunk: str) -> None:
            ev = state.queue.push(
                "assistant", "chunk", chunk, {"request_id": request_id}
            )
            chunk_events.append(ev)

        def on_tool_start(tool_name: str, tool_input: dict) -> None:
            # Tool start events are pushed directly by VmdToolBridge
            pass

        def on_tool_result(tool_id: str, tool_name: str, result: dict) -> None:
            # Transcript entry for tool results is written in tool.command_result handler
            pass

        # Temporarily override the model on the loop if settings differ
        loop = self.claude_loop
        if loop is not None and model and model != loop.model:
            from .claude_loop import ClaudeToolLoop
            loop = ClaudeToolLoop(
                provider_name=loop.provider_name,
                api_key=loop.api_key,
                model=model,
                timeout=loop.timeout,
                docs_search=self.docs_search,
            )

        # Build a per-task RunRecorder for this chat.send. The recorder
        # writes <state.cwd>/.vmdai_runs/<task_id>/transcript.tcl plus
        # snapshots — every successful tool call deposits a replayable
        # artifact on disk, automatically. Set VMD_AI_RECORDER=off to
        # disable. Falls back to ~/.vmdai/runs/ when state.cwd is empty
        # so we never silently drop artifacts.
        recorder = self._build_recorder_for_session(state)
        prev_recorder = loop.recorder if loop is not None else None
        if loop is not None:
            loop.recorder = recorder

        try:
            output = loop.run(  # type: ignore[union-attr]
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
            )
        except ClaudeLoopError as exc:
            err_event = state.queue.push(
                "error",
                "message",
                f"Agent error: {exc}",
                {"request_id": request_id, "provider": self.provider_name},
            )
            self.store.append_events(state.chat_id, [err_event])
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            if loop is not None:
                loop.recorder = prev_recorder
            return
        except Exception as exc:
            err_event = state.queue.push(
                "error",
                "message",
                f"Unexpected error: {exc}",
                {"request_id": request_id},
            )
            self.store.append_events(state.chat_id, [err_event])
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            if loop is not None:
                loop.recorder = prev_recorder
            return

        # Finalize
        events_to_persist = list(chunk_events)
        if cancel_event.is_set():
            cancel_ev = state.queue.push(
                "system", "lifecycle", "cancelled", {"request_id": request_id}
            )
            events_to_persist.append(cancel_ev)
        else:
            final_ev = state.queue.push(
                "assistant", "message", output, {"request_id": request_id}
            )
            events_to_persist.append(final_ev)

        if events_to_persist:
            self.store.append_events(state.chat_id, events_to_persist)

        if state.active_request and state.active_request.request_id == request_id:
            state.active_request = None

        # Unbind the per-task recorder so the shared loop doesn't carry
        # this run's recorder into the next chat.send.
        if loop is not None:
            loop.recorder = prev_recorder

    # ------------------------------------------------------------------
    # Background thread: simple provider (mock / fallback)
    # ------------------------------------------------------------------

    def _run_provider_response(
        self,
        session_id: str,
        request_id: str,
        prompt: str,
        cancel_event: threading.Event,
        prior_messages: list | None = None,
    ) -> None:
        """Simple non-agentic streaming: used when no API key is set (mock mode)."""
        state = self.sessions.get(session_id)
        if state is None:
            return
        chunk_events = []

        def on_chunk(chunk: str) -> None:
            event = state.queue.push(
                "assistant", "chunk", chunk, {"request_id": request_id}
            )
            chunk_events.append(event)

        try:
            output = self.provider.stream_response(
                prompt=prompt,
                cancel_event=cancel_event,
                on_chunk=on_chunk,
                model=str(state.settings.get("model") or DEFAULT_SETTINGS["model"]),
                system_prompt=self._system_prompt_for_mode(
                    str(state.settings.get("mode") or "work")
                ),
            )
        except Exception as exc:
            err_event = state.queue.push(
                "error",
                "message",
                f"Provider error: {exc}",
                {"request_id": request_id, "provider": self.provider_name},
            )
            self.store.append_events(state.chat_id, [err_event])
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            return

        events_to_persist = list(chunk_events)
        if cancel_event.is_set():
            cancel_ev = state.queue.push(
                "system", "lifecycle", "cancelled", {"request_id": request_id}
            )
            events_to_persist.append(cancel_ev)
        else:
            final_ev = state.queue.push(
                "assistant", "message", output, {"request_id": request_id}
            )
            events_to_persist.append(final_ev)

        if events_to_persist:
            self.store.append_events(state.chat_id, events_to_persist)

        if state.active_request and state.active_request.request_id == request_id:
            state.active_request = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cancel_active_request(self, state) -> None:
        active = state.active_request
        if not active:
            return
        active.cancel_event.set()

    @staticmethod
    def _system_prompt_for_mode(mode: str) -> str:
        if str(mode or "").strip().lower() == "tutor":
            return "Mode: Tutor. Explain commands and reasoning while you answer."
        return "Mode: Work. Be concise and task-oriented."
