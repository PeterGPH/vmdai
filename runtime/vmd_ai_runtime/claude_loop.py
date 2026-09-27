"""
claude_loop.py - Claude API tool-calling loop for VMD AI.

Drives a multi-turn conversation with Claude using the Anthropic Messages API
(either direct or via OpenRouter).  On each turn the model may call VMD tools:

  run_vmd_command      - execute any Tcl command in the live VMD session
  capture_vmd_snapshot - take a screenshot and feed it back to the model

Tool calls are dispatched asynchronously through VmdToolBridge, which bridges
to the Tcl plugin side via the existing JSON-RPC event queue.

No external SDK is required — all API calls use stdlib urllib.
"""
from __future__ import annotations

import base64
import copy
import dataclasses
import functools
import http.client
import json
import logging
import math
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import image_scale, provider_catalog
from .provider import (
    ProviderError,
    resolve_anthropic_api_key,
    resolve_ollama_host,
    resolve_ollama_model,
    resolve_openai_compatible_api_key,
    resolve_openrouter_api_key,
)
from .loop_guard import NUDGE_TEXT_TEMPLATE, LoopGuard
from .recorder import RunRecorder
from .conversation import (
    CONTEXT_WARN_FRACTION,
    compact_tool_results,
    compute_run_budget,
    context_tokens_for,
    messages_chars,
)
from .wiki_store import (
    WikiError,
    WikiNotFound,
    WikiPathError,
    WikiSourceMissing,
    WikiStore,
)

logger = logging.getLogger("vmdai.claude_loop")

# ---------------------------------------------------------------------------
# Loop options (per profile) and run context (per request): §2a
# ---------------------------------------------------------------------------
# options=None and ctx=None keep today's behaviour byte-for-byte (S7). Every
# behaviour change sits behind a LoopOptions field whose default is today's
# behaviour; LoopOptions.product(profile) is the ChatVMD preset.

_OLLAMA_PROVIDER_NAMES = ("ollama", "local-ollama", "local_ollama")
_ANTHROPIC_IMAGE_PROVIDERS = (
    "anthropic-direct", "anthropic_api", "anthropic-direct-api", "openrouter",
)
PRODUCT_OLLAMA_NUM_CTX = 32768        # C7: used when an Ollama profile sets none
PRODUCT_FIRST_BYTE_TIMEOUT_S = 120.0
LOCAL_IMAGE_MAX_EDGE = 1024
ANTHROPIC_IMAGE_MAX_EDGE = 1568


@dataclass
class LoopOptions:
    """Behaviour flags for one ClaudeToolLoop.

    ``LoopOptions()`` is today's behaviour. The field names are also the
    keys of a profile's ``options`` in ~/.vmdai/settings.json (§2f), and
    every field is JSON-serialisable (C6 records ``to_dict()``).
    """

    num_ctx: Optional[int] = None
    think: Optional[Any] = None
    keep_alive: Optional[Any] = None
    extra_body: Optional[Dict[str, Any]] = None
    include_usage: bool = False
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    seed: Optional[int] = None
    context_length: Optional[int] = None
    connect_retries: Optional[int] = None
    classify_unreachable: bool = False
    classify_errors: bool = False
    preflight: bool = False
    first_byte_timeout_s: Optional[float] = None
    cancellable_backoff: bool = False
    report_cancelled: bool = False
    turn_retry: int = 0
    raise_stream_errors: bool = False
    guard_truncation: bool = False
    compact_in_run: bool = False
    rescue: str = "all"
    tool_overrides: Optional[Dict[str, str]] = None
    supports_vision: Optional[Any] = None
    image_max_edge: Optional[int] = None
    ollama_tool_name: bool = False
    max_turns: int = 28
    loop_guard: bool = False
    result_format: str = "legacy"

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "LoopOptions":
        """Build from a dict; unknown keys (a newer settings.json) are ignored."""
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in dict(d or {}).items() if k in known})

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def product(cls, profile: Dict[str, Any], *, max_turns: int = 28) -> "LoopOptions":
        """The ChatVMD preset for ``profile`` ({provider, model, base_url?, options?}).

        The profile's ``options`` override the preset key by key (unknown
        keys are ignored). ``max_turns`` always comes from the setting.
        """
        profile = dict(profile or {})
        provider = str(profile.get("provider") or "").strip().lower()
        is_ollama = provider in _OLLAMA_PROVIDER_NAMES
        preset: Dict[str, Any] = {
            "connect_retries": 0 if is_ollama else 1,
            "classify_unreachable": True,
            "classify_errors": True,
            "cancellable_backoff": True,
            "report_cancelled": True,
            "turn_retry": 1,
            "raise_stream_errors": True,
            "guard_truncation": True,
            "compact_in_run": True,
            "rescue": "json",
            "supports_vision": False if provider == "openai-compatible" else "auto",
            "image_max_edge": (
                ANTHROPIC_IMAGE_MAX_EDGE
                if provider in _ANTHROPIC_IMAGE_PROVIDERS
                else LOCAL_IMAGE_MAX_EDGE
            ),
            "loop_guard": True,
            "result_format": "structured",
        }
        if is_ollama:
            preset.update({
                "num_ctx": PRODUCT_OLLAMA_NUM_CTX,
                "preflight": True,
                "first_byte_timeout_s": PRODUCT_FIRST_BYTE_TIMEOUT_S,
                "ollama_tool_name": True,
            })
        if profile.get("base_url"):
            preset["base_url"] = str(profile["base_url"])
        overrides = profile.get("options")
        if isinstance(overrides, dict):
            known = {f.name for f in dataclasses.fields(cls)}
            for key, value in overrides.items():
                if key not in known or key == "max_turns":
                    continue
                if key == "num_ctx" and value is None:
                    continue
                problem = option_type_error(key, value)
                if problem is not None:
                    # Plan 02 final review (a): a hand-edited settings.json cannot
                    # break the loop; the preset value stays.
                    logger.warning("ignoring profile option %s: %s", key, problem)
                    continue
                preset[key] = value
        preset["max_turns"] = int(max_turns)
        return cls(**preset)


# Carry-forward ruling (a): the value types a profile's options may hold.
# settings_store rejects an ill-typed value on write (SettingsError INVALID);
# LoopOptions.product drops one with a warning and keeps the preset. null is
# allowed exactly where the LoopOptions field defaults to None.
OPTION_INT_KEYS = ("num_ctx", "seed", "context_length", "connect_retries", "turn_retry", "image_max_edge")
OPTION_NUMBER_KEYS = ("temperature", "first_byte_timeout_s")
OPTION_BOOL_KEYS = ("classify_unreachable", "classify_errors", "preflight", "cancellable_backoff",
                    "report_cancelled", "raise_stream_errors", "guard_truncation", "compact_in_run",
                    "ollama_tool_name", "loop_guard", "include_usage")
OPTION_STR_KEYS = ("rescue", "result_format", "base_url")
OPTION_DICT_KEYS = ("extra_body", "tool_overrides")
OPTION_UNCHECKED_KEYS = ("think", "keep_alive", "supports_vision", "max_turns")
RESCUE_MODES = ("all", "json", "off")


def option_type_error(key: str, value: Any) -> Optional[str]:
    """Why ``value`` cannot be the profile option ``key``, or None when it can.

    Unknown keys and OPTION_UNCHECKED_KEYS are never an error.
    """
    if key in OPTION_UNCHECKED_KEYS:
        return None
    if value is None:
        defaults = {f.name: f.default for f in dataclasses.fields(LoopOptions)}
        return "must not be null" if key in defaults and defaults[key] is not None else None
    if key in OPTION_INT_KEYS:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return None if ok else "must be an integer, not %r" % (value,)
    if key in OPTION_NUMBER_KEYS:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        return None if ok else "must be a number, not %r" % (value,)
    if key in OPTION_BOOL_KEYS:
        return None if isinstance(value, bool) else "must be true or false, not %r" % (value,)
    if key == "rescue":
        return None if value in RESCUE_MODES else "must be one of all, json, off, not %r" % (value,)
    if key in OPTION_STR_KEYS:
        return None if isinstance(value, str) else "must be a string, not %r" % (value,)
    if key in OPTION_DICT_KEYS:
        return None if isinstance(value, dict) else "must be an object, not %r" % (value,)
    return None


@dataclass
class RunContext:
    """Per-request identity and sinks for ClaudeToolLoop.run (§2a)."""

    request_id: str
    chat_id: str
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None
    messages_out: Optional[Any] = None


# Streamer→loop meta kinds that the loop consumes itself; they are never
# forwarded to on_event (stop_reason: P02-T07, rescued: P02-T08,
# model_digest: plan 04).
_LOOP_ONLY_META = frozenset({"stop_reason", "rescued", "model_digest"})

# Backoff sleeps in _stream_request go through this hook (spec §2a). It is
# the only thing tests patch; production behaviour is exactly time.sleep.
_sleep = time.sleep

# ---------------------------------------------------------------------------
# VMD tool definitions (Anthropic tool_use format)
# ---------------------------------------------------------------------------

SEARCH_DOCS_TOOL: Dict[str, Any] = {
    "name": "search_docs",
    "description": (
        "Search VMD's Tcl reference, the user guide, and the bundled skills "
        "library for relevant snippets. Use this when you need command "
        "syntax (e.g., 'mol representation' parameters), the right "
        "selection-language keyword, or canonical workflows from the "
        "skills library. Cheap to call — prefer search_docs over guessing "
        "VMD-specific syntax."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language or technical query.",
            },
            "k": {
                "type": "integer",
                "description": "Number of chunks to return (1-10, default 5).",
            },
            "scope": {
                "type": "string",
                "enum": ["all", "vmd_ref", "user_guide", "skills"],
                "description": "Restrict search to a single corpus.",
            },
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Wiki tool definitions
# ---------------------------------------------------------------------------
# These tools form the "LLM Wiki" pattern: instead of re-deriving knowledge
# from raw docs every turn, the agent maintains a persistent, source-pinned
# wiki and reads from it. ``wiki_list`` is intentionally cheap — the index
# is one file — so the model is encouraged to call it first on every turn.

WIKI_LIST_TOOL: Dict[str, Any] = {
    "name": "wiki_list",
    "description": (
        "List the wiki's catalog of pages (reads index.md). Call this FIRST "
        "when you need background on a VMD concept, command, or the user's "
        "ongoing project. Returns the index plus a structured summary of "
        "every page (slug, frontmatter, pin count). Cheaper than search_docs."
    ),
    "input_schema": {"type": "object", "properties": {}},
}

WIKI_READ_TOOL: Dict[str, Any] = {
    "name": "wiki_read",
    "description": (
        "Read a wiki page by its slug (e.g. 'concepts/atomselect.md'). "
        "Returns the page body plus its pinned raw sources — every claim "
        "in a well-formed wiki page should trace back to one of these "
        "sources, which you can cite in your answer to the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": "Page slug relative to wiki root, e.g. "
                               "'concepts/atomselect.md'.",
            }
        },
        "required": ["page"],
    },
}

WIKI_UPDATE_TOOL: Dict[str, Any] = {
    "name": "wiki_update",
    "description": (
        "Create or update a wiki page. Use this to file new knowledge: a "
        "concept summary, a comparison, a per-project status, a useful "
        "snippet. Always provide 'sources' citing the raw files the page "
        "is derived from — the wiki store will hash them so future drift "
        "is detectable. 'reason' is appended to the wiki log for an "
        "auditable timeline."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": "Page slug, e.g. 'concepts/atomselect.md'.",
            },
            "content": {
                "type": "string",
                "description": "Full markdown body. Frontmatter the store "
                               "adds (sources, last_updated) will be merged "
                               "with whatever you include.",
            },
            "reason": {
                "type": "string",
                "description": "One-line justification for the wiki log.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Raw-source paths to pin (e.g. "
                               "'raw/vmd-manual/atomselect.html'). Each "
                               "must resolve to a real file under raw/.",
            },
        },
        "required": ["page", "content", "reason"],
    },
}

WIKI_VERIFY_TOOL: Dict[str, Any] = {
    "name": "wiki_verify_pins",
    "description": (
        "Re-hash every pinned raw source and report which wiki pages have "
        "drifted (source changed since pinning). Run periodically — "
        "drifted pages may contain stale claims."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": "Optional: verify just one page's pins.",
            }
        },
    },
}


def _vmd_tools(
    include_search_docs: bool = True,
    include_wiki: bool = False,
) -> List[Dict[str, Any]]:
    """Tool list shown to the model. ``search_docs`` is included only
    when a docs index is available — sending it in the tool list when
    the runtime would just return errors confuses the model. ``wiki``
    tools are added when a WikiStore is wired into the loop."""
    base: List[Dict[str, Any]] = [
        {
            "name": "run_vmd_command",
            "description": (
                "Run one or more VMD/Tcl commands in the current VMD session. "
                "Use newline-separated commands for multi-step operations. "
                "Always verify significant visual changes with capture_vmd_snapshot afterwards."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "One or more VMD Tcl commands. "
                            "Separate multiple commands with newlines."
                        ),
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Brief explanation of what this command achieves.",
                    },
                },
                "required": ["command"],
            },
        },
        {
            "name": "capture_vmd_snapshot",
            "description": (
                "Capture the current VMD viewport as a PNG image. "
                "Use this to verify rendering results, inspect representations, "
                "or describe the current molecular scene to the user. "
                "Pass save_path to ALSO write the image to disk as a deliverable "
                "(e.g. a screenshot the task asks you to save to a specific path)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "purpose": {
                        "type": "string",
                        "description": "Why you need to see the current viewport state.",
                    },
                    "save_path": {
                        "type": "string",
                        "description": (
                            "Optional. Write the rendered image to this path as a "
                            "deliverable (PNG/JPG by extension). Use the exact path the "
                            "task requests. Relative paths resolve to the working directory."
                        ),
                    },
                },
            },
        },
    ]
    if include_search_docs:
        base.append(SEARCH_DOCS_TOOL)
    if include_wiki:
        base.extend([WIKI_LIST_TOOL, WIKI_READ_TOOL, WIKI_UPDATE_TOOL, WIKI_VERIFY_TOOL])
    return base


# Default tool list (used by tests and any caller that doesn't filter).
VMD_TOOLS: List[Dict[str, Any]] = _vmd_tools(
    include_search_docs=True, include_wiki=False
)

# ---------------------------------------------------------------------------
# VMD system prompt
# ---------------------------------------------------------------------------

# Appended to system_prompt at run() time when a WikiStore is wired in.
# The base prompt is kept wiki-agnostic so the without-wiki arm of A/B
# benches doesn't see references to tools it can't use.
#
# Why this is opinionated: empirically, Claude ignores wiki_* tools when
# the prompt merely *advertises* them. The model has to be told that
# checking the wiki first is the expected workflow, not optional.
WIKI_SYSTEM_PROMPT_ADDENDUM = """

## Wiki workflow (REQUIRED — your knowledge base)

You have a persistent wiki of VMD knowledge that you maintain across
sessions. The wiki accumulates: every concept, command pattern, and
project-specific insight you compile gets reused on future turns. This
is NOT optional retrieval — it's your primary knowledge layer.

On every user turn, in this order:

1. **wiki_list** — read the index FIRST. See what pages already exist.
   This is cheap (one disk read) and tells you what's been compiled.

2. **wiki_read** the relevant page(s) BEFORE answering. Wiki pages
   carry pinned source citations — when you cite them in your answer,
   the user can trace the claim back to the raw doc.

3. **wiki_update** when you produce something worth keeping. This
   includes: a new concept summary, a comparison, a useful Tcl idiom,
   per-project context (what's loaded, what's been tried). The
   `sources` field is REQUIRED in practice — pages without citations
   degrade over time. Pin to files under raw/ that you actually used.

4. **wiki_verify_pins** occasionally — if you're revisiting an old
   topic, run this on the relevant page first to confirm the cited
   sources haven't drifted.

When you cite the wiki in your final answer, name the page slug and
the source path so the user can navigate: "From `concepts/atomselect.md`
(pinned to `raw/vmd-manual/atomselect.html`)..."

Do NOT skip wiki_list. Even when the wiki seems irrelevant, a 50-ms
disk read often surfaces a directly applicable page you wouldn't have
known existed.
"""


VMD_SYSTEM_PROMPT = """You are VMD AI, an expert assistant embedded in VMD (Visual Molecular Dynamics).

You have two tools:
- run_vmd_command: execute Tcl commands in the live VMD session
- capture_vmd_snapshot: take a screenshot of the current viewport

`capture_vmd_snapshot` is a TOOL, NOT a Tcl command. To take a screenshot,
emit it as a separate tool call — do NOT put the string "capture_vmd_snapshot"
inside `run_vmd_command`. It will fail with "invalid command name".

Typical workflow for "show me X":
  1. tool_call: run_vmd_command  (load + configure reps)
  2. tool_call: capture_vmd_snapshot  (separate call, no args needed)

## CRITICAL: VMD is NOT PyMOL

Selection syntax uses PLAIN strings — NO slashes, NO regex.
  RIGHT:  "protein"
  RIGHT:  "resname ATP"
  RIGHT:  "chain A and resname ATP"
  RIGHT:  "within 5 of resname LIG"
  WRONG:  "/resname ATP/"               ; this is PyMOL, will fail in VMD
  WRONG:  "/chain A/resname ATP/"       ; ditto

To load a structure by PDB ID, FETCH it — do NOT assume a local file exists.
  RIGHT:  mol pdbload 1HCK              ; downloads + loads in one step
  WRONG:  mol load pdb "1HCK.pdb"       ; only works if file is on disk
  WRONG:  fetch 1HCK                    ; that's PyMOL

If `mol pdbload` fails (no network), say so — do NOT retry with a different
fabricated filename.

## Tcl reference

Loading (file already on disk):
  mol load pdb "/path/to/file.pdb"
  mol load psf "protein.psf" dcd "traj.dcd"

Representations are built by STAGING settings then COMMITTING with addrep.
The selection is a SEPARATE line — do NOT inline it on `mol representation`.

  WRONG:  mol representation NewCartoon protein         ; selection inlined — fails
  WRONG:  mol representation Licorice resname ATP

  RIGHT (one rep at a time, four lines each):
    mol representation NewCartoon            ; pick style
    mol color Structure                      ; pick coloring
    mol selection "protein"                  ; pick atoms (a SEPARATE line)
    mol addrep top                           ; commit

  RIGHT (add another rep on top of the first):
    mol representation Licorice 0.3 12.0 12.0
    mol color Name
    mol selection "resname ATP"
    mol addrep top

Style options:        NewCartoon, Licorice, VDW, Surf, QuickSurf, Lines, Tube
Color-by options:     Name, Type, ResName, ResID, Chain, Beta, Index, Structure
Material options:     Opaque, Transparent, Ghost, Glossy, AOChalky

When picking ONE option from the lists above, write just that option (e.g.
`mol color ResName`). Do NOT type "or" or list the alternatives — they're
choices for you, not VMD syntax.

Delete the default rep before adding your own:
  mol delrep 0 top

Viewport:
  display projection Orthographic         ; or: Perspective
  display backgroundcolor white           ; or: black, or any color name
  axes location Off                       ; or: Origin, LowerLeft
  color Display Background white
  light 0 on                              ; or: off

Navigation:
  rotate x by 90
  translate by 0 0 -5
  scale by 1.2
  display resetview

Rendering (only when the user explicitly wants a file written to disk —
for screenshots back to the chat, use the capture_vmd_snapshot TOOL instead):
  render snapshot /tmp/scene.tga           ; quick OpenGL capture
  render TachyonInternal /tmp/scene.tga    ; higher quality
NOT `display render ...` — there is no `display render` command.

Animation:
  animate goto 0
  animate forward

Useful queries:
  molinfo list                             ; list loaded molecules
  molinfo top get numreps                  ; count representations
  set sel [atomselect top "protein"]
  $sel num                                 ; atom count
  $sel delete

## Guidelines
- After changing a representation or viewport, call capture_vmd_snapshot to verify.
- Use newline-separated commands for multi-step changes in a single tool call.
- If a command fails (you'll see the error in the result), diagnose and retry —
  do NOT fabricate a different PDB ID or filename hoping it will work."""


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _openrouter_tools(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic tool format → OpenAI/OpenRouter function format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


_DONE_SENTINEL = object()


def _iter_sse_events(resp):
    """Yield decoded SSE event payloads from an open HTTP response.

    Skips comments, empty lines, and `data: [DONE]` (yielded as the module
    sentinel ``_DONE_SENTINEL`` so callers can break on the OpenAI-style
    end marker). Malformed JSON lines are logged at DEBUG and skipped so
    one bad line doesn't kill the whole stream.
    """
    while True:
        line = resp.readline()
        if not line:
            return
        line = line.rstrip(b"\r\n")
        if not line or line.startswith(b":"):
            continue  # SSE keep-alive / comment
        if not line.startswith(b"data:"):
            continue  # Anthropic also emits "event:" lines we can ignore
        payload = line[5:].lstrip().decode("utf-8", errors="replace")
        if payload == "[DONE]":
            yield _DONE_SENTINEL
            continue
        try:
            yield json.loads(payload)
        except Exception as exc:
            logger.debug("skipping malformed SSE line: %s (%s)", payload[:80], exc)
            continue


def _retry_after_seconds(exc: urllib.error.HTTPError) -> Optional[float]:
    """Parse a Retry-After header (seconds form) if the server sent one."""
    try:
        ra = exc.headers.get("retry-after") or exc.headers.get("Retry-After")
    except Exception:
        ra = None
    if not ra:
        return None
    try:
        return max(0.0, float(ra))
    except Exception:
        return None  # ignore HTTP-date form; fall back to exponential backoff


# Status codes worth retrying: 429 rate limit, transient server overload.
_RETRY_STATUS = {429, 500, 502, 503, 529}
_HTTP_MAX_RETRIES = 5
_BACKOFF_SLICE_S = 0.1


class RunCancelled(Exception):
    """Stop was pressed while the loop waited in a backoff.

    Raised only with ``opts.cancellable_backoff``; run() turns it into
    status ``cancelled`` (§5 "Stop during backoff or streaming").
    """


def _status_message(http_status: Optional[int]) -> str:
    if http_status is None:
        return "Network error"
    if http_status == 429:
        return "Rate limited"
    if http_status == 529:
        return "Overloaded"
    return f"Server error (HTTP {http_status})"


def _retry_status(
    on_meta: Optional[Callable[[Dict[str, Any]], None]],
    attempt: int,
    max_attempts: int,
    wait: float,
    http_status: Optional[int],
) -> None:
    """Tell the loop a retry is coming (the panel shows "Retrying 2/5 in 8 s")."""
    if on_meta is None:
        return
    try:
        on_meta({
            "kind": "status",
            "phase": "retrying",
            "attempt": attempt,
            "max_attempts": max_attempts,
            "wait_s": wait,
            "http_status": http_status,
            "message": _status_message(http_status),
        })
    except Exception:
        logger.debug("on_meta status callback failed", exc_info=True)


def _cancellable_sleep(seconds: float, should_cancel: Optional[Callable[[], bool]]) -> None:
    """Sleep in 0.1 s slices through ``_sleep``; raise RunCancelled on Stop."""
    total = max(0.0, float(seconds))
    slices = int(math.ceil(total / _BACKOFF_SLICE_S - 1e-9))
    for index in range(slices):
        if should_cancel is not None and should_cancel():
            raise RunCancelled("cancelled during backoff")
        _sleep(min(_BACKOFF_SLICE_S, total - index * _BACKOFF_SLICE_S))
    if should_cancel is not None and should_cancel():
        raise RunCancelled("cancelled during backoff")


def _backoff_sleep(seconds: float, opts: Optional[LoopOptions],
                   should_cancel: Optional[Callable[[], bool]]) -> None:
    if opts is not None and opts.cancellable_backoff:
        _cancellable_sleep(seconds, should_cancel)
    else:
        _sleep(seconds)


def _classify_http_error(code: int, detail: str) -> "ClaudeLoopError":
    """Map a non-retried HTTP error to its ClaudeLoopError class (§2f, §5).

    The message is exactly the unclassified one, so logs and tracebacks
    read the same with and without ``classify_errors``.
    """
    message = f"API error HTTP {code}: {detail}"
    lowered = str(detail or "").lower()
    if code == 402 or "credit balance" in lowered:
        return ProviderBillingError(
            message, hint="Add credits, or switch to another profile.", http_status=code)
    if code in (401, 403):
        return ProviderAuthError(
            message, hint="Check the API key in Settings.", http_status=code)
    if code == 404:
        return ModelNotFoundError(
            message, hint="Choose a model this server provides.", http_status=code)
    return ClaudeLoopError(message, http_status=code)


def _set_read_timeout(resp: Any, timeout: float) -> None:
    """Best effort: once the first byte has arrived, reads use the per-read timeout."""
    try:
        resp.fp.raw._sock.settimeout(timeout)
    except Exception:
        pass


def _stream_request(
    req: urllib.request.Request,
    timeout: int,
    max_retries: int = 5,
    *,
    opts: Optional[LoopOptions] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
):
    """Open the request and surface HTTP errors as ClaudeLoopError.

    Retries on rate-limit (429) and transient overload (5xx) with backoff,
    honoring the server's Retry-After header when present. This keeps a single
    throttle from killing a whole multi-turn agentic run. Returns the response
    context manager — the caller is responsible for closing it (use ``with``).

    ``opts`` (None on the benchmark path, which behaves exactly as before):
      * ``connect_retries`` caps the retries on network errors;
      * ``cancellable_backoff`` sleeps in 0.1 s slices and raises
        RunCancelled when ``should_cancel()`` turns true;
      * ``classify_errors`` raises the ClaudeLoopError subclasses;
      * ``first_byte_timeout_s`` is the timeout until the response opens.
    ``on_meta`` receives a ``status`` item before each retry wait.
    """
    open_timeout = timeout
    if opts is not None and opts.first_byte_timeout_s:
        open_timeout = float(opts.first_byte_timeout_s)
    net_limit = max_retries
    if opts is not None and opts.connect_retries is not None:
        net_limit = int(opts.connect_retries)
    attempt = 0
    while True:
        try:
            resp = urllib.request.urlopen(req, timeout=open_timeout)
            if open_timeout != timeout:
                _set_read_timeout(resp, timeout)
            return resp
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_STATUS and attempt < max_retries:
                attempt += 1
                wait = _retry_after_seconds(exc)
                if wait is None:
                    wait = min(60.0, 2.0 ** attempt)  # 2, 4, 8, 16, 32, capped 60
                logger.warning(
                    "API HTTP %s; backing off %.1fs then retrying (%d/%d)",
                    exc.code, wait, attempt, max_retries,
                )
                _retry_status(on_meta, attempt, max_retries, wait, exc.code)
                _backoff_sleep(wait, opts, should_cancel)
                continue
            body_bytes = b""
            try:
                body_bytes = exc.read()
            except Exception:
                pass
            try:
                _j = json.loads(body_bytes)
                err = _j.get("error")
                if isinstance(err, dict):
                    detail = err.get("message", "")
                elif isinstance(err, str):
                    detail = err
                else:
                    detail = ""
                # vLLM/SGLang put the message at the top level, not under "error".
                if not detail:
                    detail = _j.get("message", "") or str(_j)[:500]
            except Exception:
                detail = body_bytes.decode("utf-8", errors="replace")[:500]
            if opts is not None and opts.classify_errors:
                raise _classify_http_error(exc.code, detail) from exc
            raise ClaudeLoopError(
                f"API error HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            # Transient network blip (DNS, reset): a couple of retries.
            if attempt < net_limit:
                attempt += 1
                wait = min(30.0, 2.0 ** attempt)
                logger.warning("network error (%s); retry %d/%d in %.1fs",
                               exc, attempt, net_limit, wait)
                _retry_status(on_meta, attempt, net_limit, wait, None)
                _backoff_sleep(wait, opts, should_cancel)
                continue
            if (
                opts is not None
                and opts.classify_unreachable
                and provider_catalog.classify_unreachable(exc) in ("refused", "reset")
            ):
                raise ProviderUnreachableError(
                    f"network error: {exc}",
                    hint=_generic_unreachable_hint(req.full_url),
                ) from exc
            raise ClaudeLoopError(f"network error: {exc}") from exc


def _open_stream(
    req: urllib.request.Request,
    timeout: int,
    opts: Optional[LoopOptions],
    should_cancel: Optional[Callable[[], bool]],
    on_meta: Optional[Callable[[Dict[str, Any]], None]],
):
    """Open a provider request. With ``opts=None`` this is exactly the old call."""
    if opts is None:
        return _stream_request(req, timeout)
    return _stream_request(req, timeout, opts=opts, should_cancel=should_cancel, on_meta=on_meta)


# ---------------------------------------------------------------------------
# Unreachable classification and the Ollama preflight (spec 2f). Only the
# options path reaches this code; options=None never does.
# ---------------------------------------------------------------------------


def _url_base(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _unreachable_case(exc: BaseException) -> Optional[str]:
    """'refused', 'reset' or 'timeout' when ``exc``, or an exception it was
    raised from, is a connection failure; None for anything else.

    provider_catalog.classify_unreachable judges each exception in the chain.
    A URLError whose reason is only text (for example a DNS failure, or
    ``URLError("Connection refused")``) is read by its words and counts as
    'refused' when they say nothing more specific."""
    current: Optional[BaseException] = exc
    for _ in range(8):
        if current is None:
            return None
        case = provider_catalog.classify_unreachable(current)
        if case is not None:
            return case
        if isinstance(current, urllib.error.URLError) and not isinstance(
            current, urllib.error.HTTPError
        ):
            text = str(current.reason).lower()
            if "timed out" in text:
                return "timeout"
            if "reset" in text or "closed" in text:
                return "reset"
            return "refused"
        current = current.__cause__ or current.__context__
    return None


def _reason_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        return str(exc.reason)
    return str(exc) or exc.__class__.__name__


def _generic_unreachable_hint(url: str) -> str:
    """Hint for a refused or reset connection when the provider is unknown
    (the wording provider_catalog.test_provider uses for non-Ollama servers)."""
    return f"Could not reach {_url_base(url)}. Check that the server is running."


def _http_status_of(exc: BaseException) -> Optional[int]:
    """The HTTP status behind a ClaudeLoopError: its http_status (plan 02
    sets it when classify_errors is on), else the HTTPError it came from."""
    status = getattr(exc, "http_status", None)
    if isinstance(status, int):
        return status
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, urllib.error.HTTPError):
        return int(cause.code)
    return None


def _ollama_unreachable_error(
    base_url: str,
    exc: BaseException,
    opts: Any,
    case: Optional[str] = None,
) -> "ClaudeLoopError":
    """Error for an Ollama server that cannot be reached. The message keeps
    today's wording; ``hint`` carries the case-specific advice (2f table)."""
    case = case or _unreachable_case(exc) or "refused"
    message = f"Ollama unreachable at {base_url!r}: {_reason_text(exc)}."
    if case == "refused":
        message += " Is `ollama serve` running?"
    hint = provider_catalog.unreachable_hint(base_url, case)
    if opts is not None and (opts.classify_unreachable or opts.classify_errors):
        return ProviderUnreachableError(message, hint=hint)
    return ClaudeLoopError(message, hint=hint)


def _ps_entry(models: Any, model: str) -> Optional[Dict[str, Any]]:
    """The /api/ps entry for ``model`` ('name' and 'name:latest' match)."""
    def _norm(name: Any) -> str:
        text = str(name or "")
        return text if ":" in text else text + ":latest"

    want = _norm(model)
    for entry in models or []:
        if isinstance(entry, dict) and want in (_norm(entry.get("name")), _norm(entry.get("model"))):
            return entry
    return None


def _ollama_preflight(
    base_url: str,
    model: str,
    opts: Any,
    on_meta: Optional[Callable[[Dict[str, Any]], None]],
) -> None:
    """GET /api/version (2 s, cached 30 s by provider_catalog), then GET
    /api/ps (2 s, never cached) before every /api/chat, so a dead or stale
    server fails in about 2 s even with a warm version cache (S6). Emits
    status 'loading_model' when the model is not resident, else the resident
    model's digest (C6)."""
    timeout = provider_catalog.PREFLIGHT_TIMEOUT_S
    try:
        provider_catalog.ollama_version(base_url, timeout=timeout)
        running = provider_catalog.ollama_ps(base_url, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise ClaudeLoopError(
            f"Ollama preflight failed at {base_url!r}: HTTP {exc.code}",
            http_status=int(exc.code),
        ) from exc
    except Exception as exc:
        case = _unreachable_case(exc)
        if case is None:
            raise ClaudeLoopError(f"Ollama preflight failed at {base_url!r}: {exc}") from exc
        raise _ollama_unreachable_error(base_url, exc, opts, case) from exc
    if on_meta is None:
        return
    entry = _ps_entry(running, model)
    if entry is None:
        on_meta({"kind": "status", "phase": "loading_model", "message": f"Loading {model}…"})
    elif entry.get("digest"):
        on_meta({"kind": "model_digest", "value": str(entry["digest"])})


# Per-(base_url, model) memo of servers that answered HTTP 400 to "think"
# (spec 2f). Module-level so it outlives the per-request loop; tests clear it.
_NO_THINK: set = set()
_NO_THINK_LOCK = threading.Lock()


def _think_key(base_url: str, model: str) -> Tuple[str, str]:
    return (str(base_url or "").rstrip("/"), str(model or ""))


def _think_disabled(base_url: str, model: str) -> bool:
    with _NO_THINK_LOCK:
        return _think_key(base_url, model) in _NO_THINK


def _remember_no_think(base_url: str, model: str) -> None:
    with _NO_THINK_LOCK:
        _NO_THINK.add(_think_key(base_url, model))


def _ollama_body_options(opts: Any) -> Dict[str, Any]:
    """The /api/chat ``options`` object on the options path: num_ctx from the
    profile (LoopOptions.product() fills 32768 when the profile has none,
    C7; a bare LoopOptions() keeps 8192), temperature and seed only when
    set. No environment reads."""
    options: Dict[str, Any] = {"num_ctx": int(opts.num_ctx) if opts.num_ctx else 8192}
    if opts.temperature is not None:
        options["temperature"] = float(opts.temperature)
    if opts.seed is not None:
        options["seed"] = int(opts.seed)
    return options


# ---------------------------------------------------------------------------
# Usage parsing (spec 2c "Usage semantics"): a value the provider did not
# report is None, never 0. Emitted once per turn through on_meta.
# ---------------------------------------------------------------------------

def _usage_int(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _usage_meta(source: str, evaluated: Any, output: Any, cache_read: Any) -> Dict[str, Any]:
    return {
        "kind": "usage",
        "input_tokens_evaluated": _usage_int(evaluated),
        "output_tokens": _usage_int(output),
        "cache_read_tokens": _usage_int(cache_read),
        "source": source,
    }


def _anthropic_usage_update(event: Dict[str, Any], etype: str, acc: Dict[str, Any]) -> None:
    """message_start carries input and cache-read tokens; message_delta the
    final output count."""
    if etype == "message_start":
        usage = (event.get("message") or {}).get("usage") or {}
        acc["input"] = usage.get("input_tokens")
        acc["cache_read"] = usage.get("cache_read_input_tokens")
    elif etype == "message_delta":
        usage = event.get("usage") or {}
        if "output_tokens" in usage:
            acc["output"] = usage.get("output_tokens")


def _openai_usage_meta(usage: Any) -> Dict[str, Any]:
    """The final chunk's usage (stream_options.include_usage). Cached prompt
    tokens are reported separately and left out of input_tokens_evaluated."""
    if not isinstance(usage, dict):
        return _usage_meta("openai", None, None, None)
    prompt = usage.get("prompt_tokens")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    evaluated = prompt
    if isinstance(prompt, int) and isinstance(cached, int):
        evaluated = prompt - cached
    return _usage_meta("openai", evaluated, usage.get("completion_tokens"), cached)


def _ollama_usage_meta(done_event: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ollama's prompt_eval_count leaves out the cached prefix, so it is
    input_tokens_evaluated, never context used."""
    event = done_event or {}
    return _usage_meta("ollama", event.get("prompt_eval_count"), event.get("eval_count"), None)


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoints (spec 2f): per-loop base_url and body extras.
# ---------------------------------------------------------------------------

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PROTECTED_BODY_KEYS = ("model", "messages", "tools", "stream")


def _openai_chat_url(base_url: str) -> str:
    """Join a /v1 base URL and /chat/completions without doubling slashes or
    the path (a base that already ends in /chat/completions is kept)."""
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _apply_openai_body_options(body: Dict[str, Any], opts: Any) -> None:
    """Options-path body fields: temperature/seed when set, the opt-in
    stream_options.include_usage (older vLLM rejects it), then extra_body
    merged at top level (it may not replace model, messages, tools or stream)."""
    if opts.temperature is not None:
        body["temperature"] = float(opts.temperature)
    if opts.seed is not None:
        body["seed"] = int(opts.seed)
    if opts.include_usage:
        body["stream_options"] = {"include_usage": True}
    for key, value in dict(opts.extra_body or {}).items():
        if key in _PROTECTED_BODY_KEYS:
            continue
        body[key] = copy.deepcopy(value)


# ---------------------------------------------------------------------------
# Vision (spec 2f): which providers get images, and at what size.
# ---------------------------------------------------------------------------

_ANTHROPIC_DIRECT_NAMES = ("anthropic-direct", "anthropic_api", "anthropic-direct-api")
_IMAGE_NOT_SHOWN = "[Snapshot captured — image not shown in this provider mode]"


def resolve_supports_vision(provider: str, value: Any, capabilities: Optional[Dict[str, bool]]) -> bool:
    """Resolve LoopOptions.supports_vision to a bool.

    True/False are explicit. None keeps today's rule (images only to
    anthropic-direct). "auto" is True for anthropic-direct, the /api/show
    ``vision`` capability for Ollama, and False for openai-compatible and
    openrouter, which have no capability probe (a manual toggle)."""
    name = str(provider or "").lower()
    if isinstance(value, bool):
        return value
    if value is None:
        return name in _ANTHROPIC_DIRECT_NAMES
    if str(value).lower() == "auto":
        if name in _ANTHROPIC_DIRECT_NAMES:
            return True
        if name in _OLLAMA_PROVIDER_NAMES:
            return bool((capabilities or {}).get("vision"))
    return False


def _images_allowed(opts: Any) -> bool:
    """Converters inline image blocks only when vision resolved to True."""
    return opts is not None and opts.supports_vision is True


def _image_block_b64(block: Dict[str, Any]) -> str:
    source = block.get("source") or {}
    if source.get("type") != "base64":
        return ""
    return str(source.get("data") or "")


@functools.lru_cache(maxsize=16)
def _downscaled_b64(data: str, max_edge: int) -> str:
    """Base64 of the PNG ``data`` fitted to ``max_edge`` (cached, so a
    snapshot that stays in the history is resized once, not every turn)."""
    try:
        png = base64.b64decode(data)
        small, _width, _height = image_scale.downscale_png(png, max_edge)
    except Exception:
        logger.warning("snapshot downscale failed; sending the original", exc_info=True)
        return data
    if small is png:
        return data
    return base64.b64encode(small).decode("ascii")


def _has_image(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("type") == "image":
        return True
    content = block.get("content")
    return block.get("type") == "tool_result" and isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "image" for b in content
    )


def _messages_have_images(messages: List[Dict]) -> bool:
    return any(
        isinstance(m, dict) and isinstance(m.get("content"), list)
        and any(_has_image(b) for b in m["content"])
        for m in messages
    )


def _image_for_call(block: Dict[str, Any], vision: bool, max_edge: int) -> Dict[str, Any]:
    if not vision:
        return {"type": "text", "text": _IMAGE_NOT_SHOWN}
    source = block.get("source") or {}
    data = _image_block_b64(block)
    if not data or max_edge <= 0 or str(source.get("media_type") or "image/png") != "image/png":
        return block
    small = _downscaled_b64(data, int(max_edge))
    if small == data:
        return block
    return dict(block, source=dict(source, data=small))


def _block_for_call(block: Any, vision: bool, max_edge: int) -> Any:
    if not isinstance(block, dict):
        return block
    if block.get("type") == "image":
        return _image_for_call(block, vision, max_edge)
    content = block.get("content")
    if block.get("type") == "tool_result" and isinstance(content, list):
        return dict(block, content=[
            _image_for_call(b, vision, max_edge)
            if isinstance(b, dict) and b.get("type") == "image" else b
            for b in content
        ])
    return block


def _images_for_call(messages: List[Dict], *, vision: bool, max_edge: int) -> List[Dict]:
    """Per-call view of ``messages`` for the options path (spec 2f Vision).

    With vision, every base64 PNG image block (top level or inside a
    tool_result) is downscaled to fit ``max_edge`` (1024 px local, 1568 px
    Anthropic); without vision, each becomes the text marker, so no provider
    ever receives an image. Covers this run's snapshots and the images
    build_prior hydrates from disk. Messages without images are shared, the
    in-run list is never modified, and ``messages`` itself comes back when
    no message holds an image."""
    out: List[Dict] = []
    changed = False
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list) and any(_has_image(b) for b in content):
            out.append(dict(msg, content=[_block_for_call(b, vision, max_edge) for b in content]))
            changed = True
        else:
            out.append(msg)
    return out if changed else messages


def _apply_tool_overrides(tools: List[Dict[str, Any]], overrides: Dict[str, str]) -> List[Dict[str, Any]]:
    """Copy of ``tools`` with descriptions replaced by name (spec 2g). The
    frozen schema dicts are never mutated."""
    out: List[Dict[str, Any]] = []
    for tool in tools:
        name = str(tool.get("name") or "")
        if name in overrides:
            tool = dict(tool)
            tool["description"] = overrides[name]
        out.append(tool)
    return out


def _stream_anthropic_direct(
    messages: List[Dict],
    model: str,
    system_prompt: str,
    api_key: str,
    timeout: int,
    on_text: Callable[[str], None],
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from Anthropic Messages API; return (text, tool_blocks).

    text deltas are pushed to ``on_text`` as they arrive (real streaming),
    so the UI can render typing-style output. Tool-use blocks are collected
    from ``content_block_start`` events and emit at end-of-turn so the
    caller can dispatch tool calls in stable order.
    """
    if "/" in model:
        model = model.split("/", 1)[1]
    model = model.replace("4.6", "4-6").replace("4.5", "4-5")

    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "tools": list(tools) if tools is not None else VMD_TOOLS,
        "messages": messages,
        "stream": True,
    }
    if system_prompt:
        body["system"] = system_prompt

    _apply_tool_mode(body, "anthropic", tool_mode)

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "accept": "text/event-stream",
        },
        method="POST",
    )

    if opts is None or not opts.raise_stream_errors:
        return _anthropic_consume(req, timeout, on_text, should_cancel, on_meta, opts)
    attempt = 0
    while True:
        try:
            return _anthropic_consume(req, timeout, on_text, should_cancel, on_meta, opts)
        except _SseOverloaded as exc:
            # An SSE overloaded_error before any output counts as HTTP 529 (§5).
            if attempt >= _HTTP_MAX_RETRIES:
                raise ClaudeLoopError(f"API error HTTP 529: {exc}", http_status=529) from exc
            attempt += 1
            wait = min(60.0, 2.0 ** attempt)
            logger.warning("SSE overloaded_error; backing off %.1fs then retrying (%d/%d)",
                           wait, attempt, _HTTP_MAX_RETRIES)
            _retry_status(on_meta, attempt, _HTTP_MAX_RETRIES, wait, 529)
            _backoff_sleep(wait, opts, should_cancel)


class _SseOverloaded(Exception):
    """An Anthropic SSE ``overloaded_error`` that arrived before any output."""


def _anthropic_consume(
    req: urllib.request.Request,
    timeout: int,
    on_text: Callable[[str], None],
    should_cancel: Callable[[], bool],
    on_meta: Optional[Callable[[Dict[str, Any]], None]],
    opts: Optional[LoopOptions],
) -> Tuple[str, List[Dict]]:
    """Open one Anthropic request and consume its SSE stream."""
    text_parts: List[str] = []
    blocks_in_progress: Dict[int, Dict[str, Any]] = {}
    usage_acc: Dict[str, Any] = {"input": None, "output": None, "cache_read": None}
    final_tool_blocks: List[Dict[str, Any]] = []
    raise_errors = opts is not None and opts.raise_stream_errors

    with _open_stream(req, timeout, opts, should_cancel, on_meta) as resp:
        for event in _iter_sse_events(resp):
            if event is _DONE_SENTINEL:
                break
            if should_cancel():
                break

            etype = str(event.get("type") or "")

            if on_meta is not None:
                _anthropic_usage_update(event, etype, usage_acc)

            if etype == "content_block_start":
                idx = int(event.get("index") or 0)
                cb = event.get("content_block") or {}
                if cb.get("type") == "tool_use":
                    blocks_in_progress[idx] = {
                        "type": "tool_use",
                        "id": str(cb.get("id") or ""),
                        "name": str(cb.get("name") or ""),
                        "_partial_json": "",
                    }
                continue

            if etype == "content_block_delta":
                idx = int(event.get("index") or 0)
                delta = event.get("delta") or {}
                dtype = str(delta.get("type") or "")
                if dtype == "text_delta":
                    chunk = str(delta.get("text") or "")
                    if chunk:
                        text_parts.append(chunk)
                        on_text(chunk)
                elif dtype == "input_json_delta":
                    fragment = str(delta.get("partial_json") or "")
                    if idx in blocks_in_progress and fragment:
                        blocks_in_progress[idx]["_partial_json"] += fragment
                continue

            if etype == "content_block_stop":
                idx = int(event.get("index") or 0)
                if idx in blocks_in_progress:
                    block = blocks_in_progress.pop(idx)
                    raw_json = block.pop("_partial_json", "") or "{}"
                    try:
                        block["input"] = json.loads(raw_json)
                    except Exception:
                        block["input"] = {}
                    final_tool_blocks.append(block)
                continue

            if etype == "message_delta":
                if on_meta is not None:
                    reason = (event.get("delta") or {}).get("stop_reason")
                    if reason:
                        on_meta({"kind": "stop_reason", "value": str(reason)})
                continue

            if etype == "error" and raise_errors:
                err = event.get("error") or {}
                err_type = str(err.get("type") or "")
                message = str(err.get("message") or err_type or "stream error")
                if (err_type == "overloaded_error" and not text_parts
                        and not final_tool_blocks and not blocks_in_progress):
                    raise _SseOverloaded(message)
                raise ClaudeLoopError(f"API stream error: {message}")

            if etype == "message_stop":
                break

    if on_meta is not None:
        on_meta(_usage_meta("anthropic", usage_acc["input"], usage_acc["output"],
                            usage_acc["cache_read"]))
    return "".join(text_parts), final_tool_blocks


def _stream_openrouter(
    messages: List[Dict],
    model: str,
    system_prompt: str,
    api_key: str,
    timeout: int,
    on_text: Callable[[str], None],
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from OpenRouter / OpenAI-style chat completions."""
    or_messages = []
    if system_prompt:
        or_messages.append({"role": "system", "content": system_prompt})
    if opts is None:
        or_messages.extend(_to_openrouter_messages(messages))
    else:
        or_messages.extend(
            _to_openrouter_messages(messages, include_images=_images_allowed(opts))
        )

    tools_list = list(tools) if tools is not None else VMD_TOOLS
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": 4096,
        "tools": _openrouter_tools(tools_list),
        "messages": or_messages,
        "stream": True,
    }

    # Endpoint is configurable so the same OpenAI-style path can target any
    # OpenAI-compatible server (OpenRouter by default, or a local vLLM/SGLang/
    # Ollama-OpenAI endpoint via VMD_AI_OPENAI_BASE_URL=http://host:8000/v1).
    # With options set, the URL, key and body extras come from opts alone;
    # the environment is read only on the options=None (benchmark) path.
    if opts is None:
        _base = os.environ.get("VMD_AI_OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
        _url = _base + "/chat/completions"
        _bearer = api_key
    else:
        _url = _openai_chat_url(opts.base_url or OPENROUTER_BASE_URL)
        _bearer = api_key or "EMPTY"
        _apply_openai_body_options(body, opts)
    _apply_tool_mode(body, "openai", tool_mode)
    req = urllib.request.Request(
        _url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_bearer}",
            "HTTP-Referer": "https://localhost/vmd-ai",
            "X-Title": "vmd-ai",
            "accept": "text/event-stream",
        },
        method="POST",
    )

    text_parts: List[str] = []
    # tool_calls_acc keyed by integer index; OpenAI streams arguments
    # as small string fragments we have to concatenate before json.loads.
    tool_calls_acc: Dict[int, Dict[str, Any]] = {}
    usage_seen: Any = None

    with _open_stream(req, timeout, opts, should_cancel, on_meta) as resp:
        for event in _iter_sse_events(resp):
            if event is _DONE_SENTINEL:
                break
            if should_cancel():
                break

            if on_meta is not None and isinstance(event.get("usage"), dict):
                usage_seen = event["usage"]
            choices = event.get("choices") or []
            if not choices:
                continue
            if on_meta is not None:
                finish = (choices[0] or {}).get("finish_reason")
                if finish:
                    on_meta({"kind": "stop_reason", "value": str(finish)})
            delta = (choices[0] or {}).get("delta") or {}
            if on_meta is not None:
                reasoning = delta.get("reasoning_content")
                if not isinstance(reasoning, str) or not reasoning:
                    reasoning = delta.get("reasoning")
                if isinstance(reasoning, str) and reasoning:
                    on_meta({"kind": "reasoning", "text": reasoning})

            content = delta.get("content")
            if isinstance(content, str) and content:
                text_parts.append(content)
                on_text(content)
            elif isinstance(content, list):
                # Some providers send delta.content as block list rather
                # than a flat string — flatten "text" fragments.
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    fragment = str(block.get("text") or "")
                    if fragment:
                        text_parts.append(fragment)
                        on_text(fragment)

            for tc_delta in delta.get("tool_calls") or []:
                idx = int(tc_delta.get("index") or 0)
                slot = tool_calls_acc.setdefault(
                    idx,
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": None, "arguments": ""},
                    },
                )
                if tc_delta.get("id"):
                    slot["id"] = str(tc_delta["id"])
                fn = tc_delta.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = str(fn["name"])
                if isinstance(fn.get("arguments"), str):
                    slot["function"]["arguments"] += fn["arguments"]

    if on_meta is not None:
        on_meta(_openai_usage_meta(usage_seen))

    final_tool_blocks: List[Dict[str, Any]] = []
    for idx in sorted(tool_calls_acc.keys()):
        tc = tool_calls_acc[idx]
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}
        if not isinstance(args, dict):
            args = {"value": args}
        final_tool_blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id") or f"tc_{idx}",
                "name": str(fn.get("name") or ""),
                "input": args,
            }
        )

    return "".join(text_parts), final_tool_blocks


# ---------------------------------------------------------------------------
# Ollama streaming
# ---------------------------------------------------------------------------

def _iter_ndjson_events(resp) -> Any:
    """Yield decoded JSON objects from an NDJSON stream.

    Ollama writes one JSON object per newline-delimited chunk to
    ``/api/chat`` when ``stream=true``. This generator is the NDJSON
    counterpart to ``_iter_sse_events`` for OpenAI/Anthropic.
    """
    for raw_line in resp:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = str(raw_line)
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            # Skip junk lines; don't fail the whole stream.
            continue


def _ollama_tools(tools: List[Dict]) -> List[Dict]:
    """Convert Anthropic-style tool defs to Ollama's tool format.

    Ollama follows the OpenAI shape — ``{type: "function", function:
    {name, description, parameters}}`` — and accepts the same JSON
    Schema for ``parameters`` that Anthropic uses for ``input_schema``.
    So this is just a structural rewrap.
    """
    out: List[Dict] = []
    for tool in tools:
        out.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema") or {
                    "type": "object", "properties": {},
                },
            },
        })
    return out


def _to_ollama_messages(
    messages: List[Dict],
    *,
    include_images: bool = False,
    tool_name: bool = False,
) -> List[Dict]:
    """Convert internal Anthropic-style messages to Ollama format.

    Ollama's ``/api/chat`` accepts an OpenAI-ish message list with
    these roles: ``system``, ``user``, ``assistant``, ``tool``. Each
    assistant turn may carry ``tool_calls``; tool results come as
    ``role=tool`` messages with the result text in ``content``.

    Differences from OpenRouter conversion:
      * ``arguments`` in tool_calls is an OBJECT (not a JSON string)
      * Ollama doesn't track ``tool_call_id`` the same way — we still
        emit it for round-trip clarity, but Ollama will ignore it.
      * Images in ``tool_result`` become a text marker unless
        include_images is set (vision on, LoopOptions path): then they
        move to a ``{"role": "user", "content": "Snapshot from
        capture_vmd_snapshot (call <id>).", "images": [b64]}`` message
        placed right after that turn's tool messages, and top-level image
        blocks ride on their own message's ``images``.

    tool_name (LoopOptions.ollama_tool_name) adds the name of the tool that
    produced each ``role=tool`` message, looked up from the earlier
    assistant ``tool_use`` block with the same id.
    """
    out: List[Dict] = []
    names_by_id: Dict[str, str] = {}
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue

        text_parts: List[str] = []
        tool_calls: List[Dict] = []
        tool_results: List[Dict] = []
        snapshot_messages: List[Dict] = []
        top_images: List[str] = []

        for block in content:
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
                names_by_id[str(block.get("id", ""))] = str(block.get("name", ""))
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": block.get("input") or {},
                    },
                })
            elif btype == "tool_result":
                tc_content = block.get("content", "")
                if isinstance(tc_content, list):
                    parts = []
                    images: List[str] = []
                    for b in tc_content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "image":
                            data = _image_block_b64(b)
                            if include_images and data:
                                images.append(data)
                            else:
                                parts.append(_IMAGE_NOT_SHOWN)
                        else:
                            parts.append(str(b.get("text") or ""))
                    tc_content = " ".join(p for p in parts if p)
                    if images:
                        snapshot_messages.append({
                            "role": "user",
                            "content": "Snapshot from capture_vmd_snapshot "
                                       f"(call {block.get('tool_use_id', '')}).",
                            "images": images,
                        })
                entry: Dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": str(tc_content),
                }
                if tool_name and names_by_id.get(str(block.get("tool_use_id", ""))):
                    entry["tool_name"] = names_by_id[str(block.get("tool_use_id", ""))]
                tool_results.append(entry)
            elif btype == "image" and include_images:
                data = _image_block_b64(block)
                if data:
                    top_images.append(data)
            # Without include_images, top-level ``image`` blocks are dropped
            # as before.

        if tool_results:
            out.extend(tool_results)
            out.extend(snapshot_messages)
        elif tool_calls:
            msg_out: Dict[str, Any] = {
                "role": role,
                "content": "".join(text_parts) or "",
                "tool_calls": tool_calls,
            }
            out.append(msg_out)
        else:
            plain: Dict[str, Any] = {"role": role, "content": "".join(text_parts)}
            if top_images:
                plain["images"] = top_images
            out.append(plain)

    return out


# Matches fenced code blocks: ```json {...} ``` or ``` {...} ```
_FENCED_JSON_RE = re.compile(r"```(?:json|tool_call|tool_use)?\s*(.+?)```", re.DOTALL)

# Matches fenced Tcl/VMD code blocks. Small Ollama models (notably
# qwen2.5-coder) emit "I'll execute this Tcl" + ```tcl block instead of
# a structured tool call. We treat such blocks as an implicit
# run_vmd_command invocation. Language tag is required (no bare ```)
# to keep false-positives low — we don't want to auto-execute Python /
# shell blocks the model might paste for illustration.
_FENCED_TCL_RE = re.compile(
    r"```(?:tcl|vmd|vmd-tcl)\s*\n(.+?)```",
    re.DOTALL | re.IGNORECASE,
)


def _rescue_json_tool_calls(
    text: str,
    allowed_names: set,
    mode: str = "all",
) -> List[Dict[str, Any]]:
    """Recover tool calls that small Ollama models pasted into the text body.

    Some local models (qwen2.5-coder, smaller llama variants, etc.) "know"
    about the tool schema but emit the call as a JSON block inside
    ``message.content`` instead of as a structured ``tool_calls`` field.
    Without this fallback, the agentic loop sees no tool_calls and the
    user's request silently no-ops.

    Two rescue passes, tried in order:

    1. **JSON-shaped tool calls** — collect candidates from fenced code
       blocks, the whole-body text, AND any inline ``{...}`` / ``[...]``
       runs embedded in prose (via streaming json.JSONDecoder). Accepts
       only shapes that name one of the tools we offered. Accepted shapes:
         * ``{"name": "...", "arguments": {...}}``
         * ``{"name": "...", "parameters": {...}}``  (Qwen variants)
         * ``{"function": {"name": "...", "arguments": "..."}}`` (OpenAI)
         * ``{"tool_calls": [<any of the above>, ...]}``
         * A bare list of the above
         * ``arguments`` may be a JSON-string instead of an object

    2. **```tcl / ```vmd fenced blocks** — code-tuned models often dodge
       the tool schema entirely and emit "here's the Tcl I'd run" in a
       fenced block. If pass 1 found nothing AND the agent was offered
       ``run_vmd_command``, treat fenced Tcl blocks as an implicit
       invocation. Language tag is required (no bare ``` fences) so we
       don't fire on Python/shell snippets the model might paste for
       illustration.

    ``mode`` (§2f Rescue): ``"all"`` runs both passes (today's behaviour,
    the options=None default); ``"json"`` runs pass 1 only, so a ```tcl
    block in prose never runs (S12); anything else (``"off"``) rescues
    nothing.

    Returns the list of synthesized tool_use blocks (empty if none).
    Conservative on purpose: we'd rather miss a rescue than fire on
    unrelated content.
    """
    mode = str(mode or "all").strip().lower()
    if not text or not allowed_names or mode not in ("all", "json"):
        return []

    # ---- Pass 1: JSON-shaped tool calls -----------------------------
    # Collect candidate JSON strings from three sources, in priority order:
    #   a) fenced code blocks (```json ... ```)
    #   b) the whole text body (model dropped the fence entirely)
    #   c) inline JSON objects/arrays embedded in prose (use the streaming
    #      json.JSONDecoder to find every `{...}` or `[...]` that parses)
    candidates: List[Any] = []
    for m in _FENCED_JSON_RE.finditer(text):
        chunk = m.group(1).strip()
        if chunk:
            try:
                candidates.append(json.loads(chunk))
            except Exception:
                pass
    # Whole-body attempt
    stripped = text.strip().strip(",;")
    if stripped and stripped[0] in "[{":
        try:
            candidates.append(json.loads(stripped))
        except Exception:
            pass
    # Inline scan: walk every `{` and `[` and try to raw_decode from
    # there. raw_decode returns (obj, end_index) for the longest valid
    # JSON prefix at that position, so this handles JSON embedded in
    # prose like:  "let me try:  {\"name\":...}  and here's why..."
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            obj, _end = decoder.raw_decode(text, i)
        except Exception:
            continue
        candidates.append(obj)

    seen_ids: set = set()
    for obj in candidates:
        # Dedupe identical re-parsed candidates (whole-body + inline scan
        # often discover the same object twice).
        try:
            key = json.dumps(obj, sort_keys=True)
        except Exception:
            key = repr(obj)
        if key in seen_ids:
            continue
        seen_ids.add(key)

        raw_calls: List[Any] = []
        if isinstance(obj, dict):
            if isinstance(obj.get("tool_calls"), list):
                raw_calls = obj["tool_calls"]
            else:
                raw_calls = [obj]
        elif isinstance(obj, list):
            raw_calls = obj
        else:
            continue

        blocks: List[Dict[str, Any]] = []
        for c in raw_calls:
            if not isinstance(c, dict):
                continue
            fn = c.get("function") if isinstance(c.get("function"), dict) else c
            name = fn.get("name") or c.get("name")
            if not name or name not in allowed_names:
                continue
            args = (
                fn.get("arguments")
                if "arguments" in fn
                else (fn.get("parameters") or fn.get("input"))
            )
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    continue
            if not isinstance(args, dict):
                continue
            blocks.append({
                "type": "tool_use",
                "id": str(c.get("id") or fn.get("id") or ""),
                "name": name,
                "input": args,
            })

        if blocks:
            return blocks

    # ---- Pass 2: ```tcl / ```vmd code blocks ------------------------
    # qwen2.5-coder and similar code-tuned local models often dodge the
    # tool schema entirely and emit "here's the Tcl I'd run" in a
    # fenced ```tcl block. Treat that as an implicit run_vmd_command
    # invocation when the model was offered that tool. Only in "all"
    # mode: the product ("json") never runs Tcl written in prose.
    if mode != "all":
        return []
    if "run_vmd_command" not in allowed_names:
        return []

    tcl_chunks: List[str] = []
    for m in _FENCED_TCL_RE.finditer(text):
        chunk = m.group(1).strip()
        if chunk:
            tcl_chunks.append(chunk)
    if not tcl_chunks:
        return []

    # Concatenate multiple ```tcl blocks into one command — the model
    # often splits a multi-step plan across blocks, but the bridge
    # already accepts newline-separated commands in a single call.
    combined = "\n".join(tcl_chunks)
    return [{
        "type": "tool_use",
        "id": "",
        "name": "run_vmd_command",
        "input": {"command": combined},
    }]


def _stream_ollama(
    messages: List[Dict],
    model: str,
    system_prompt: str,
    base_url: str,
    timeout: int,
    on_text: Callable[[str], None],
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
    _no_think_retry: bool = False,
) -> Tuple[str, List[Dict]]:
    """Stream one turn from Ollama's ``/api/chat`` with tool support.

    Returns ``(final_text, tool_use_blocks)`` in the same canonical
    shape as ``_stream_anthropic_direct`` / ``_stream_openrouter`` so
    the rest of the agentic loop is provider-agnostic.

    Tool calling notes:
      * Ollama emits tool_calls in a single NDJSON message — they are
        NOT streamed in fragments like OpenAI does.
      * The model decides per call; some models (llama3.1, qwen2.5,
        gpt-oss) support tools; smaller ones return only text.
      * We synthesize ``tool_call_id``s when Ollama doesn't provide
        them, so downstream code can correlate tool_use ↔ tool_result.
    """
    if opts is not None and opts.preflight:
        _ollama_preflight(base_url, model, opts, on_meta)
    ol_messages: List[Dict] = []
    if system_prompt:
        ol_messages.append({"role": "system", "content": system_prompt})
    if opts is None:
        ol_messages.extend(_to_ollama_messages(messages))
    else:
        ol_messages.extend(_to_ollama_messages(
            messages,
            include_images=_images_allowed(opts),
            tool_name=bool(opts.ollama_tool_name),
        ))

    tools_list = list(tools) if tools is not None else VMD_TOOLS
    if opts is None:
        options: Dict[str, Any] = {
            # Bigger context so multi-turn tool-calling sessions don't
            # rotate the agent's prior reasoning out of the window.
            "num_ctx": 8192,
        }
        # Temperature / seed pass-through. Read at request time (not loop
        # construction) so a wrapper script can set them between trials —
        # this is how the seed-bench plan gets independent runs.
        _temp_env = os.getenv("VMD_AI_TEMPERATURE")
        if _temp_env:
            try:
                options["temperature"] = float(_temp_env)
            except ValueError:
                pass
        _seed_env = os.getenv("VMD_AI_SEED")
        if _seed_env:
            try:
                options["seed"] = int(_seed_env)
            except ValueError:
                pass
    else:
        options = _ollama_body_options(opts)
    body: Dict[str, Any] = {
        "model": model,
        "messages": ol_messages,
        "stream": True,
        "tools": _ollama_tools(tools_list),
        "options": options,
    }
    if opts is not None:
        if opts.keep_alive is not None:
            body["keep_alive"] = opts.keep_alive
        if (
            opts.think is not None
            and not _no_think_retry
            and not _think_disabled(base_url, model)
        ):
            body["think"] = opts.think

    _apply_tool_mode(body, "ollama", tool_mode)

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "accept": "application/x-ndjson",
        },
        method="POST",
    )

    text_parts: List[str] = []
    final_tool_blocks: List[Dict[str, Any]] = []
    tool_call_counter = 0
    got_event = False
    done_event: Optional[Dict[str, Any]] = None

    try:
        with _open_stream(req, timeout, opts, should_cancel, on_meta) as resp:
            for event in _iter_ndjson_events(resp):
                got_event = True
                if should_cancel():
                    break
                if "error" in event:
                    raise ClaudeLoopError(
                        f"Ollama error: {event['error']}"
                    )
                msg = event.get("message") or {}
                if on_meta is not None:
                    thinking = msg.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        on_meta({"kind": "reasoning", "text": thinking})
                    if event.get("done"):
                        done_event = event
                # Text content — stream it.
                content = msg.get("content")
                if isinstance(content, str) and content:
                    text_parts.append(content)
                    on_text(content)
                # Tool calls — Ollama emits them whole, not in deltas.
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if not isinstance(args, dict):
                        args = {"value": args}
                    tool_call_counter += 1
                    final_tool_blocks.append({
                        "type": "tool_use",
                        "id": str(tc.get("id") or f"otc_{tool_call_counter}"),
                        "name": str(fn.get("name") or ""),
                        "input": args,
                    })
                if event.get("done"):
                    if on_meta is not None:
                        on_meta({"kind": "stop_reason",
                                 "value": str(event.get("done_reason") or "stop")})
                    break
    except RunCancelled:
        raise
    except ClaudeLoopError as exc:
        if opts is not None:
            cause = exc.__cause__
            if isinstance(cause, urllib.error.URLError) and not isinstance(
                cause, urllib.error.HTTPError
            ):
                raise _ollama_unreachable_error(base_url, cause, opts) from cause
            status = _http_status_of(exc)
            if status == 400 and "think" in body and not _no_think_retry:
                _remember_no_think(base_url, model)
                if on_meta is not None:
                    on_meta({
                        "kind": "status",
                        "phase": "think_unsupported",
                        "message": f"{model} does not support thinking; continuing without it.",
                    })
                return _stream_ollama(
                    messages=messages, model=model, system_prompt=system_prompt,
                    base_url=base_url, timeout=timeout, on_text=on_text,
                    should_cancel=should_cancel, tools=tools, on_meta=on_meta,
                    opts=opts, tool_mode=tool_mode, _no_think_retry=True,
                )
            if status == 404:
                # On /api/chat a 404 always means the model is not pulled;
                # plan 02's generic "Choose a model..." hint is replaced.
                exc.hint = f"ollama pull {model}"
        raise
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
            f"(model={model!r}, host={base_url!r})"
        )
        if detail:
            msg += f" - {detail}"
        raise ClaudeLoopError(msg) from exc
    except urllib.error.URLError as exc:
        raise ClaudeLoopError(
            f"Ollama unreachable at {base_url!r}: {exc.reason}. "
            f"Is `ollama serve` running?"
        ) from exc
    except Exception as exc:
        if (
            opts is not None
            and opts.classify_unreachable
            and not got_event
            and isinstance(exc, (ConnectionRefusedError, ConnectionResetError))
        ):
            raise _ollama_unreachable_error(base_url, exc, opts) from exc
        raise ClaudeLoopError(f"Ollama stream failed: {exc}") from exc

    if on_meta is not None:
        on_meta(_ollama_usage_meta(done_event))

    text = "".join(text_parts)

    # JSON-in-content rescue: if the model didn't emit structured
    # tool_calls but pasted a tool-call-shaped JSON into the text body,
    # synthesize tool_use blocks from it. See _rescue_json_tool_calls.
    # Rescue mode (§2f): options=None keeps "all"; the product uses "json".
    rescue_mode = opts.rescue if opts is not None else "all"
    if not final_tool_blocks and text and rescue_mode != "off" and tool_mode != "none":
        allowed = {str(t.get("name") or "") for t in tools_list if t.get("name")}
        rescued = _rescue_json_tool_calls(text, allowed, mode=rescue_mode)
        if rescued:
            for block in rescued:
                if not block.get("id"):
                    tool_call_counter += 1
                    block["id"] = f"otc_rescue_{tool_call_counter}"
            final_tool_blocks = rescued
            logger.info(
                "ollama: rescued %d tool call(s) from JSON-in-content "
                "(model=%s)", len(rescued), model,
            )
            if on_meta is not None:
                # The loop marks these calls origin "rescued" (§2c).
                on_meta({"kind": "rescued", "ids": [str(b["id"]) for b in rescued]})
            # Drop the JSON text from history so the model doesn't learn
            # to repeat the pattern on the next turn. The UI already
            # received it via on_text — we just don't persist it.
            text = ""

    return text, final_tool_blocks


# ---------------------------------------------------------------------------
# Message-format conversion helpers
# ---------------------------------------------------------------------------

def _to_openrouter_messages(
    messages: List[Dict],
    *,
    include_images: bool = False,
) -> List[Dict]:
    """
    Convert internal Anthropic-style messages to OpenAI/OpenRouter format.

    Internal Anthropic format:
        {"role": "user"|"assistant", "content": str | list-of-blocks}

    OpenRouter format:
        {"role": "user"|"assistant", "content": str, "tool_calls": [...]}
        {"role": "tool", "tool_call_id": "...", "content": "..."}

    include_images (vision on, LoopOptions path): each image inside a
    tool_result becomes a user message with an ``image_url`` data-URL part,
    placed right after that turn's tool messages.
    """
    out: List[Dict] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue

        text_parts: List[str] = []
        tool_calls: List[Dict] = []
        tool_results: List[Dict] = []
        snapshot_messages: List[Dict] = []

        for block in content:
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    }
                )
            elif btype == "tool_result":
                # Flatten image content to text if present
                tc_content = block.get("content", "")
                if isinstance(tc_content, list):
                    if include_images:
                        for b in tc_content:
                            if isinstance(b, dict) and b.get("type") == "image" and _image_block_b64(b):
                                mime = str((b.get("source") or {}).get("media_type") or "image/png")
                                snapshot_messages.append({"role": "user", "content": [
                                    {"type": "text", "text": "Snapshot from capture_vmd_snapshot "
                                                             f"(call {block['tool_use_id']})."},
                                    {"type": "image_url", "image_url": {
                                        "url": f"data:{mime};base64,{_image_block_b64(b)}"}},
                                ]})
                    tc_content = " ".join(
                        b.get("text", "") for b in tc_content if isinstance(b, dict)
                    )
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(tc_content),
                    }
                )
            elif btype == "image":
                # Skip — OpenRouter tool results don't accept inline images;
                # the model will rely on the text summary instead.
                pass

        if tool_results:
            out.extend(tool_results)
            out.extend(snapshot_messages)
        elif tool_calls:
            msg_out: Dict[str, Any] = {
                "role": role,
                "content": "".join(text_parts) or None,
                "tool_calls": tool_calls,
            }
            out.append(msg_out)
        else:
            out.append({"role": role, "content": "".join(text_parts)})

    return out


# ---------------------------------------------------------------------------
# Main error type
# ---------------------------------------------------------------------------

class ClaudeLoopError(RuntimeError):
    """A loop failure.

    ``code`` is the error-event code (§2f): ``other`` here, and
    ``unreachable``/``auth``/``billing``/``model_not_found`` on the
    subclasses, which the loop raises only when ``options.classify_errors``
    (or ``classify_unreachable``) is on. The message text never changes, so
    existing ``except ClaudeLoopError`` handlers keep working.
    """

    code = "other"

    def __init__(self, message: str = "", *, hint: str = "",
                 http_status: Optional[int] = None):
        super().__init__(message)
        self.hint = str(hint or "")
        self.http_status = http_status


class ProviderUnreachableError(ClaudeLoopError):
    code = "unreachable"


class ProviderAuthError(ClaudeLoopError):
    code = "auth"


class ProviderBillingError(ClaudeLoopError):
    code = "billing"


class ModelNotFoundError(ClaudeLoopError):
    code = "model_not_found"


# guard_truncation (§2a, §5): tool calls from a turn cut off by the output
# token limit are not run; each gets this error result instead.
TRUNCATED_TOOL_ERROR = (
    "Not run: your reply hit the output token limit while writing this tool "
    "call, so its arguments may be incomplete. Make a shorter call, or split "
    "the work into smaller steps."
)
_TRUNCATED_STOP_REASONS = frozenset({"max_tokens", "length"})

# Read errors after the response opened: a "stream drop" (§5).
_STREAM_DROP_TYPES = (ConnectionError, http.client.IncompleteRead, socket.timeout)


def _is_stream_drop(exc: BaseException) -> bool:
    """True for a read error after the response opened (reset, closed, read timeout).

    Opening errors (URLError), classified errors and Stop never count.
    """
    if isinstance(exc, (RunCancelled, urllib.error.URLError)):
        return False
    if isinstance(exc, ClaudeLoopError):
        if exc.code != "other":
            return False
        candidate = exc.__cause__
    else:
        candidate = exc
    if candidate is None or isinstance(candidate, urllib.error.URLError):
        return False
    return isinstance(candidate, _STREAM_DROP_TYPES)


# ---------------------------------------------------------------------------
# Tool result construction
# ---------------------------------------------------------------------------

def _structured_summary(result: Dict[str, Any]) -> str:
    """C3 model-facing text for product runs (``result_format="structured"``).

    Tells the model what actually happened: blocked (C1), not executed
    (Stop, pickup deadline, loop guard, C2 refusal), nothing run (C3
    pre-check), outcome unknown, or which statement failed and which ones
    are already applied in VMD.
    """
    ok = bool(result.get("ok", False))
    output = str(result.get("output") or "")
    error = str(result.get("error") or "")
    executed = str(result.get("executed") or "yes")
    statements = result.get("statements") or {}
    failed = statements.get("failed") or None
    if result.get("blocked"):
        return error or "Not run: blocked by ChatVMD."
    if executed == "no":
        if error.startswith("Nothing was run"):
            if failed and failed.get("text"):
                return "%s\nIncomplete statement: `%s`" % (error, failed["text"])
            return error
        if error == "cancelled":
            return "not executed: request stopped"
        if error.lower().startswith("not executed"):
            return error
        return "not executed: %s" % (error or "unknown reason")
    if executed == "unknown":
        return error or "stopped while running; outcome unknown"
    if ok:
        return output if output else "Command executed successfully."
    if failed and statements.get("total"):
        total = int(statements["total"])
        applied = int(statements.get("applied") or 0)
        index = int(failed.get("index") or applied + 1)
        lines = ["Failed at statement %d of %d: `%s`" % (index, total, failed.get("text") or "")]
        lines.append("Error: %s" % (error or "unknown error"))
        if failed.get("error_info"):
            lines.append(str(failed["error_info"]))
        if applied == 0:
            lines.append("No statements were applied.")
        elif applied == 1:
            lines.append("Statement 1 was applied and is still in effect; do not re-run it.")
        else:
            lines.append(
                "Statements 1–%d were applied and are still in effect; "
                "do not re-run them." % applied
            )
        if output:
            lines.append("Output before the error:\n%s" % output)
        return "\n".join(lines)
    return ("Error: %s" % error) if error else "Command failed with unknown error."


def _build_tool_result_block(
    tool_use_id: str,
    result: Dict[str, Any],
    include_image: bool,
    result_format: str = "legacy",
) -> Dict:
    """
    Build an Anthropic tool_result content block from the tool bridge result dict.

    For capture_vmd_snapshot results that include image_b64, the image is
    embedded as a base64 content block (only when include_image=True, i.e.
    when calling Anthropic directly).

    ``result_format="structured"`` (product runs only; C3) replaces the
    plain ``Error: ...`` text with :func:`_structured_summary`. The default
    ``"legacy"`` keeps today's text byte-for-byte (options=None / S7).
    """
    ok = bool(result.get("ok", False))
    output = str(result.get("output") or "")
    error = str(result.get("error") or "")
    image_b64 = str(result.get("image_b64") or "")
    image_mime = str(result.get("image_mime") or "image/png")

    if result_format == "structured":
        summary = _structured_summary(result)
    elif ok:
        summary = output if output else "Command executed successfully."
    else:
        summary = f"Error: {error}" if error else "Command failed with unknown error."

    content: Any
    if include_image and image_b64:
        content = [
            {"type": "text", "text": summary},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime,
                    "data": image_b64,
                },
            },
        ]
    else:
        # For OpenRouter or when no image: text only
        if image_b64 and not include_image:
            summary += " [Snapshot captured — image not shown in this provider mode]"
        content = summary

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": not ok,
    }


# ---------------------------------------------------------------------------
# C4: loop guard and wrap-up (product only; options=None never reaches these)
# ---------------------------------------------------------------------------

WRAP_UP_INSTRUCTION = (
    "Stop using tools. In a few lines, say what you changed in the VMD scene, "
    "what you measured (with values), what failed, and what the user could try next."
)

LOOP_GUARD_SKIP_RESULT: Dict[str, Any] = {
    "ok": False,
    "output": "",
    "error": "not executed: loop guard",
    "executed": "no",
}


def _apply_tool_mode(body: Dict[str, Any], flavor: str, tool_mode: Optional[str]) -> Dict[str, Any]:
    """C4 wrap-up: with ``tool_mode == "none"`` the model may not call tools.

    Ollama drops the ``tools`` key (``tools=None`` would fall back to
    VMD_TOOLS); Anthropic sends ``tool_choice {"type": "none"}``; OpenRouter
    and OpenAI-compatible servers send ``"tool_choice": "none"``. Any other
    mode leaves ``body`` untouched, so options=None requests never change.
    """
    if tool_mode != "none":
        return body
    if flavor == "ollama":
        body.pop("tools", None)
    elif flavor == "anthropic":
        body["tool_choice"] = {"type": "none"}
    else:
        body["tool_choice"] = "none"
    return body


def _append_to_tool_result(block: Dict[str, Any], text: str) -> None:
    """Append ``text`` to a tool_result block (string content or first text part)."""
    content = block.get("content")
    if isinstance(content, str):
        block["content"] = content + "\n\n" + text
        return
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                part["text"] = str(part.get("text") or "") + "\n\n" + text
                return
        content.insert(0, {"type": "text", "text": text})


# ---------------------------------------------------------------------------
# Loop → app contract helpers (§2a call_key, §2b canonical copies, §2c)
# ---------------------------------------------------------------------------

# Tools the runtime answers itself (executor "runtime"); the rest go to Tcl.
_RUNTIME_TOOLS = frozenset({
    "search_docs", "wiki_list", "wiki_read", "wiki_update", "wiki_verify_pins",
})


def _mint_call_key() -> str:
    """A fresh key for one tool execution: 12 hex characters (§2a).

    It names the image and output files and forms the canonical id
    ``call_<call_key>``; model ids (tc_0, otc_1) repeat across turns.
    """
    return uuid.uuid4().hex[:12]


def _canonical_message(message: Dict[str, Any], call_keys: List[str]) -> Dict[str, Any]:
    """Deep copy of ``message`` for messages_out (§2b Canonical copies).

    The i-th tool_use ``id`` (assistant turn) or tool_result
    ``tool_use_id`` (tool-results turn) becomes ``call_<call_keys[i]>``.
    The in-run message is never modified.
    """
    out = copy.deepcopy(message)
    content = out.get("content")
    if not isinstance(content, list):
        return out
    index = 0
    for block in content:
        if not isinstance(block, dict) or index >= len(call_keys):
            continue
        if block.get("type") == "tool_use":
            block["id"] = "call_" + call_keys[index]
            index += 1
        elif block.get("type") == "tool_result":
            block["tool_use_id"] = "call_" + call_keys[index]
            index += 1
    return out


def _tool_finished_meta(call_key: str, tool_name: str, executor: str,
                        result: Dict[str, Any], duration_ms: float) -> Dict[str, Any]:
    """``tool.finished`` metadata (§2c) from a bridge or runtime result dict.

    Fields a bridge does not report yet (plan 05 adds them) default to
    None; ``executed`` defaults to "yes" because the tool was dispatched.
    """
    output = str(result.get("output") or "")
    output_bytes = result.get("output_bytes")
    image = result.get("image")
    return {
        "kind": "tool.finished",
        "call_key": call_key,
        "tool_name": tool_name,
        "executor": executor,
        "ok": bool(result.get("ok", False)),
        "executed": str(result.get("executed") or "yes"),
        "output": output,
        "error": str(result.get("error") or ""),
        "truncated": bool(result.get("truncated", False)),
        "duration_ms": int(round(duration_ms)),
        "statements": result.get("statements"),
        "blocked": result.get("blocked"),
        "output_path": result.get("output_path"),
        "output_bytes": int(output_bytes) if output_bytes is not None else len(output.encode("utf-8")),
        "image": image if isinstance(image, dict) else None,
        "saved_path": result.get("saved_path"),
        "late": False,
    }


# ---------------------------------------------------------------------------
# The Claude tool loop
# ---------------------------------------------------------------------------

class ClaudeToolLoop:
    """
    Drives multi-turn Claude conversations with VMD tool-use support.

    Instantiate once per provider configuration and call run() per chat turn.
    """

    MAX_TURNS = 28  # raised from 16: multi-step analysis tasks (RMSD/Rg/contacts) need more turns

    # In-run compaction state (§2b); reset at the start of every run().
    last_compactions = 0
    _run_budget: Optional[int] = None
    _context_warned = False

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        timeout: int = 90,
        docs_search: Optional[Any] = None,
        recorder: Optional[RunRecorder] = None,
        wiki_store: Optional[WikiStore] = None,
        options: Optional[LoopOptions] = None,
    ):
        self.provider_name = str(provider_name or "mock").lower()
        self.api_key = str(api_key or "")
        self.model = str(model or "anthropic/claude-sonnet-4.6")
        self.timeout = max(30, int(timeout))
        # docs_search is a DocsSearch instance (or any object with a
        # ``.search(query, k, scope)`` method and ``.is_available``
        # property). Optional — when None, search_docs is not advertised
        # to the model and the agent falls back to its own knowledge.
        self.docs_search = docs_search
        # recorder writes per-task transcript.tcl + snapshots/ under a
        # workdir-scoped .vmdai_runs/. Set this to a RunRecorder before
        # calling run() to enable auto-recording; leave None to keep
        # the legacy "no on-disk artifact" behavior.
        self.recorder = recorder
        # wiki_store is a persistent, source-pinned knowledge base the
        # agent maintains over time (see wiki_store.py). When supplied,
        # four extra tools are advertised: wiki_list / wiki_read /
        # wiki_update / wiki_verify_pins. The model should call wiki_list
        # FIRST on most turns to look up prior knowledge before
        # rediscovering it from raw docs.
        self.wiki_store = wiki_store
        # Set from the Ollama preflight's /api/ps entry (C6); None elsewhere.
        self.last_model_digest: Optional[str] = None
        # Summed over the request's turns; None until a turn reports it.
        self.last_usage: Dict[str, Optional[int]] = {
            "input_tokens_evaluated": None, "output_tokens": None}
        # Behaviour flags (§2a). None keeps today's benchmark behaviour
        # byte-for-byte; the product passes LoopOptions.product(profile).
        self.options = options
        # Per-request context: set at the start of run(), cleared in its finally.
        self._ctx: Optional[RunContext] = None
        # "none" only for C4's wrap-up call (plan 05); forwarded to the streamers.
        self._tool_mode: Optional[str] = None
        # 1-based turn number and the loop-only meta items of that turn.
        self._turn = 0
        self._turn_meta: Dict[str, Dict[str, Any]] = {}
        # Outcome of the last run(); the app builds request.finished from it.
        self.last_status: Optional[str] = None
        self.last_turns = 0
        self.last_tool_calls = 0
        self.last_final_text_empty = False

    @property
    def _is_anthropic_direct(self) -> bool:
        return self.provider_name in ("anthropic-direct", "anthropic_api", "anthropic-direct-api")

    @property
    def _is_ollama(self) -> bool:
        return self.provider_name in ("ollama", "local-ollama", "local_ollama")

    def _dispatch_search_docs(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        """Run a search_docs call against the configured DocsSearch.

        Returns a dict shaped like the Tcl-bridge tool results so
        ``_build_tool_result_block`` can format it the same way:

            {ok: bool, output: str, error: str}

        On success the formatted ``output`` is the ranked snippets joined
        with separators — that's what the model sees in the tool_result
        block.  On any failure (no index, bad scope) ok=False with an
        informative error.
        """
        if self.docs_search is None or not getattr(
            self.docs_search, "is_available", False
        ):
            return {
                "ok": False,
                "output": "",
                "error": "search_docs is unavailable (no docs index built).",
            }
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return {
                "ok": False,
                "output": "",
                "error": "search_docs requires a non-empty 'query'.",
            }
        try:
            k = int(tool_input.get("k") or 5)
        except Exception:
            k = 5
        scope = str(tool_input.get("scope") or "all")

        try:
            payload = self.docs_search.search(query=query, k=k, scope=scope)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "output": "", "error": f"search failed: {exc}"}

        if not payload.get("ok"):
            return {
                "ok": False,
                "output": "",
                "error": str(payload.get("error") or "search failed"),
            }
        results = payload.get("results") or []
        if not results:
            return {
                "ok": True,
                "output": (
                    f"No matching docs for query: {query!r}. "
                    f"Try rephrasing or omit scope."
                ),
                "error": "",
            }

        rendered = []
        for i, hit in enumerate(results, start=1):
            rendered.append(
                f"[{i}] {hit['source']}  §{hit['section']}  "
                f"(score={hit['score']:.3f})\n{hit['text']}"
            )
        return {
            "ok": True,
            "output": "\n\n---\n\n".join(rendered),
            "error": "",
        }

    def _vision_enabled(self) -> bool:
        """Whether snapshot images go to this loop's model (spec 2f Vision).

        options=None keeps today's rule (anthropic-direct only). With options,
        True/False are used as-is; None and "auto" are resolved once through
        resolve_supports_vision (for Ollama, "auto" asks /api/show with the
        2 s preflight timeout) and the bool is stored back into self.options,
        so the converters see the same answer on every later call."""
        options = getattr(self, "options", None)
        if options is None:
            return self._is_anthropic_direct
        value = options.supports_vision
        if isinstance(value, bool):
            return value
        capabilities: Optional[Dict[str, bool]] = None
        if self._is_ollama and str(value).lower() == "auto":
            capabilities = self._ollama_capabilities()
        resolved = resolve_supports_vision(self.provider_name, value, capabilities)
        self.options = dataclasses.replace(options, supports_vision=resolved)
        return resolved

    def _ollama_capabilities(self) -> Optional[Dict[str, bool]]:
        options = getattr(self, "options", None)
        base = options.base_url if options is not None and options.base_url else self.api_key
        try:
            show = provider_catalog.ollama_show(
                base or "http://localhost:11434", self.model,
                timeout=provider_catalog.PREFLIGHT_TIMEOUT_S,
            )
            return dict(provider_catalog.model_capabilities(show))
        except Exception:
            logger.warning("ollama /api/show failed; treating %s as non-vision", self.model,
                           exc_info=True)
            return None

    def _tools_for_turn(self) -> List[Dict[str, Any]]:
        """Tool list to advertise to the provider this turn.

        ``search_docs`` is included only when a healthy DocsSearch index
        is loadable; otherwise the model would call a tool that always
        errors, which is worse than not having it at all. ``wiki_*``
        tools are included whenever a WikiStore is wired in — the store
        bootstraps an empty wiki on demand, so it never errors at idle.
        """
        include_docs = bool(self.docs_search) and bool(
            getattr(self.docs_search, "is_available", False)
        )
        include_wiki = self.wiki_store is not None
        tools = _vmd_tools(
            include_search_docs=include_docs,
            include_wiki=include_wiki,
        )
        # Optional extra tool schemas wired in by an embedder (e.g. semantic
        # vmd_measure / vmd_represent tools); dispatched to the tool_bridge.
        extra = getattr(self, "extra_tools", None)
        tools = (tools + list(extra)) if extra else tools
        options = getattr(self, "options", None)
        if options is not None and options.tool_overrides:
            tools = _apply_tool_overrides(tools, options.tool_overrides)
        return tools

    def _result_format(self) -> str:
        """C3: "structured" for product runs, "legacy" (today's text) otherwise."""
        options = getattr(self, "options", None)
        if options is None:
            return "legacy"
        return str(getattr(options, "result_format", "legacy") or "legacy")

    def _loop_guard_enabled(self) -> bool:
        """C4 is product-only: options=None has no detector and no wrap-up (S7)."""
        options = getattr(self, "options", None)
        return options is not None and bool(getattr(options, "loop_guard", False))

    def _guard_after_result(
        self,
        guard: LoopGuard,
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Dict[str, Any],
        call_key: str,
    ) -> Tuple[str, bool]:
        """C4: feed one tool result to the guard. Returns (nudge text, stop)."""
        verdict = guard.observe(tool_name, tool_input or {}, result or {})
        if verdict is None:
            return "", False
        if verdict == "nudge":
            text = NUDGE_TEXT_TEMPLATE.format(n=guard.streak)
            self._emit("system", "state", "", {
                "kind": "status", "phase": "loop_detected", "call_key": call_key,
                "stop": False, "message": text,
            })
            return text, False
        self._emit("system", "state", "", {
            "kind": "status", "phase": "loop_detected", "call_key": call_key,
            "stop": True, "message": "Stopped: the model kept repeating the same step",
        })
        return "", True

    def _skip_tool_block(self, block: Dict[str, Any], call_key: str, origin: str) -> Dict[str, Any]:
        """C4: a tool call left in the turn after the guard's stop.

        It is never dispatched, never recorded and not fed to the guard, but
        it still gets its tool.started/tool.finished pair (the panel's
        "not run" row) and a tool_result (every tool_use needs one).
        """
        tool_name = str(block.get("name") or "")
        executor = "runtime" if tool_name in _RUNTIME_TOOLS else "tcl"
        self._emit("system", "state", "", {
            "kind": "tool.started",
            "call_key": call_key,
            "tool_call_id": str(block.get("id") or ""),
            "tool_name": tool_name,
            "executor": executor,
            "origin": origin,
            "input": block.get("input") or {},
        })
        result = dict(LOOP_GUARD_SKIP_RESULT)
        self._emit("system", "state", "",
                   _tool_finished_meta(call_key, tool_name, executor, result, 0.0))
        return result

    def _run_wrap_up(
        self,
        messages: List[Dict],
        system_prompt: str,
        on_text: Callable[[str], None],
        cancel_event: threading.Event,
        turn_no: int,
    ) -> Tuple[str, bool]:
        """C4: one extra tool-less call that summarises a stopped run.

        Runs after the loop guard's stop and when max_turns is reached. The
        per-call copy ends with a separate user message holding the
        instruction as string content (the Ollama and OpenAI converters drop
        text parts next to tool results but keep string content).
        ``tool_mode="none"`` makes Ollama omit ``tools`` and the others send
        ``tool_choice`` none; tool calls in the reply are dropped. The call is
        never retried and never raises: an error becomes a notice. Returns
        (text, cancelled). The call counts as a turn; ``messages_out``
        receives only the reply text (plan 02's ``_finish_text_turn``).
        """
        self._turn = turn_no
        self._turn_meta = {}
        self.last_turns = turn_no
        self._emit("system", "state", "", {
            "kind": "status", "phase": "wrapping_up", "message": "Summarising what was done",
        })
        self._emit("system", "state", "", {"kind": "turn.started"})
        call_messages, _compacted = self._compact_for_call(messages)
        call_messages = list(call_messages) + [{"role": "user", "content": WRAP_UP_INSTRUCTION}]
        self._tool_mode = "none"
        try:
            text, _dropped_tool_calls = self._call(
                call_messages, system_prompt, on_text=on_text, should_cancel=cancel_event.is_set,
            )
        except Exception as exc:
            if cancel_event.is_set():
                return "", True
            self.last_wrap_up_error = str(exc) or exc.__class__.__name__
            logger.warning("wrap-up call failed: %s", self.last_wrap_up_error)
            self._emit("system", "state", "", {
                "kind": "status", "phase": "wrapping_up",
                "message": "Summary failed: %s" % self.last_wrap_up_error,
            })
            return "", False
        finally:
            self._tool_mode = None
        if cancel_event.is_set():
            return text or "", True
        text = text or ""
        self.last_wrapped_up = True
        # Seals the run's answer: assistant/message {final: true}, sets
        # last_final_text_empty, and appends the text (only) to messages_out.
        self._finish_text_turn(text)
        return text, False

    # ------------------------------------------------------------------
    # Wiki tool dispatchers
    # ------------------------------------------------------------------
    # Each dispatcher returns the {ok, output, error} shape the tool
    # result builder expects. We surface every WikiError as a structured
    # error rather than re-raising, so a bad page slug or a missing
    # source doesn't break the entire turn — the model can read the
    # error and recover.

    def _dispatch_wiki_list(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        if self.wiki_store is None:
            return {"ok": False, "output": "", "error": "wiki not configured"}
        try:
            # Ensure the wiki exists. bootstrap() is idempotent, so it's
            # safe to call on every list — the model can never end up
            # querying a non-existent wiki.
            self.wiki_store.bootstrap()
            index_text = self.wiki_store.read_index()
            pages = self.wiki_store.list_pages()
        except WikiError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

        rendered = [
            "# Wiki index (index.md)",
            index_text.rstrip("\n"),
            "",
            "# Pages discovered on disk",
        ]
        if not pages:
            rendered.append("(none — wiki is empty)")
        else:
            for p in pages:
                fm = p["frontmatter"] or {}
                sources = fm.get("sources") or []
                src_note = (
                    f"; sources={len(sources)}"
                    if sources
                    else "; sources=0"
                )
                rendered.append(
                    f"- {p['page']} (pins={p['pin_count']}{src_note})"
                )
        return {
            "ok": True,
            "output": "\n".join(rendered),
            "error": "",
            "pages": pages,
        }

    def _dispatch_wiki_read(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        if self.wiki_store is None:
            return {"ok": False, "output": "", "error": "wiki not configured"}
        page = str(tool_input.get("page") or "").strip()
        if not page:
            return {"ok": False, "output": "",
                    "error": "wiki_read requires a non-empty 'page'."}
        try:
            rec = self.wiki_store.read_page(page)
        except WikiNotFound as exc:
            return {"ok": False, "output": "", "error": str(exc)}
        except WikiError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

        # Render an output the model will read naturally. Pins are
        # surfaced explicitly so the model can cite them back to the
        # user without re-deriving from the frontmatter.
        lines = [f"# {rec.page}", rec.body.rstrip("\n"), ""]
        if rec.pins:
            lines.append("## Pinned sources")
            for pin in rec.pins:
                lines.append(
                    f"- {pin.path}  (sha256={pin.sha256[:12]}..., "
                    f"pinned_at={pin.pinned_at})"
                )
        else:
            lines.append("## Pinned sources\n(none — page has no citations)")
        return {
            "ok": True,
            "output": "\n".join(lines),
            "error": "",
            "page": rec.page,
            "frontmatter": rec.frontmatter,
            "pins": [p.to_json() for p in rec.pins],
        }

    def _dispatch_wiki_update(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        if self.wiki_store is None:
            return {"ok": False, "output": "", "error": "wiki not configured"}
        page = str(tool_input.get("page") or "").strip()
        content = str(tool_input.get("content") or "")
        reason = str(tool_input.get("reason") or "").strip()
        raw_sources = tool_input.get("sources") or []
        if not isinstance(raw_sources, list):
            return {"ok": False, "output": "",
                    "error": "sources must be an array of strings"}
        sources = [str(s) for s in raw_sources if str(s).strip()]
        if not page:
            return {"ok": False, "output": "", "error": "'page' is required"}
        if not reason:
            return {"ok": False, "output": "", "error": "'reason' is required"}

        try:
            self.wiki_store.bootstrap()
            rec = self.wiki_store.update_page(
                page=page,
                content=content,
                reason=reason,
                sources=sources or None,
            )
        except (WikiPathError, WikiSourceMissing) as exc:
            return {"ok": False, "output": "", "error": str(exc)}
        except WikiError as exc:
            return {"ok": False, "output": "", "error": str(exc)}

        pin_summary = ", ".join(p.path for p in rec.pins) if rec.pins else "(none)"
        return {
            "ok": True,
            "output": (
                f"Wrote {rec.page}. Pinned sources: {pin_summary}."
            ),
            "error": "",
            "page": rec.page,
            "pins": [p.to_json() for p in rec.pins],
        }

    def _dispatch_wiki_verify_pins(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        if self.wiki_store is None:
            return {"ok": False, "output": "", "error": "wiki not configured"}
        page = str(tool_input.get("page") or "").strip() or None
        try:
            report = self.wiki_store.verify_pins(page=page)
        except WikiError as exc:
            return {"ok": False, "output": "", "error": str(exc)}
        summary = report["summary"]
        lines = [
            "# verify_pins",
            f"fresh={summary.get('fresh', 0)}  "
            f"drift={summary.get('drift', 0)}  "
            f"missing={summary.get('missing', 0)}  "
            f"empty={summary.get('empty', 0)}",
        ]
        for entry in report["checked"]:
            lines.append(f"- {entry['page']}: {entry['status']}")
            for d in entry.get("drift", []) or []:
                lines.append(
                    f"    drift: {d['source']}  expected={d['expected'][:12]}... "
                    f"actual={d['actual'][:12]}..."
                )
            for m in entry.get("missing", []) or []:
                lines.append(f"    missing: {m}")
        return {
            "ok": True,
            "output": "\n".join(lines),
            "error": "",
            "report": report,
        }

    def _call(
        self,
        messages: List[Dict],
        system_prompt: str,
        on_text: Callable[[str], None],
        should_cancel: Callable[[], bool],
    ) -> Tuple[str, List[Dict]]:
        """Run a streaming turn against the configured provider.

        Text deltas are pushed to ``on_text`` as the API returns them, so
        the UI sees real-time output instead of a buffered turn split into
        fake "chunks". Tool-use blocks are returned at end-of-turn so the
        caller can dispatch them in stable order.

        With ``self.options`` set the streamers also receive ``on_meta``
        (streamer→loop callback), ``opts`` and ``tool_mode``; with
        ``options=None`` they are called exactly as before (S7).
        """
        tools = self._tools_for_turn()
        if self.options is not None and _messages_have_images(messages):
            # Per-call image view (spec 2f Vision): downscaled when this loop's
            # resolved vision is on, a text marker when it is off. The in-run
            # list (and messages_out) keep the full image.
            vision = self._vision_enabled()
            messages = _images_for_call(
                messages, vision=vision, max_edge=int(self.options.image_max_edge or 0)
            )
        extra: Dict[str, Any] = {}
        if self.options is not None:
            extra = {
                "on_meta": self._on_meta,
                "opts": self.options,
                "tool_mode": self._tool_mode,
            }
        if self._is_anthropic_direct:
            return _stream_anthropic_direct(
                messages=messages,
                model=self.model,
                system_prompt=system_prompt,
                api_key=self.api_key,
                timeout=self.timeout,
                on_text=on_text,
                should_cancel=should_cancel,
                tools=tools,
                **extra,
            )
        if self._is_ollama:
            # For Ollama, ``api_key`` is repurposed to hold the base URL
            # (no auth header) — keeps ClaudeToolLoop's constructor
            # surface unchanged across providers.
            return _stream_ollama(
                messages=messages,
                model=self.model,
                system_prompt=system_prompt,
                base_url=self.api_key or "http://localhost:11434",
                timeout=self.timeout,
                on_text=on_text,
                should_cancel=should_cancel,
                tools=tools,
                **extra,
            )
        return _stream_openrouter(
            messages=messages,
            model=self.model,
            system_prompt=system_prompt,
            api_key=self.api_key,
            timeout=self.timeout,
            on_text=on_text,
            should_cancel=should_cancel,
            tools=tools,
            **extra,
        )

    def _compact_for_call(self, messages: List[Dict]) -> Tuple[List[Dict], bool]:
        """The message list for the next provider call (§2b In-run compaction).

        At 90% of the run budget, emit one ``status context_near_full`` per
        request. At 100%, return a copy in which the tool results of all but
        the last 2 tool rounds are 300-character stubs (a C5 output-path note
        stays as the last line) and every image but the newest is a text
        stub. The in-run ``messages`` list, and therefore messages_out, keeps
        the full bodies; the estimate is character-based on purpose.
        """
        budget = self._run_budget
        if budget is None:
            return messages, False
        used = messages_chars(messages)
        if used >= CONTEXT_WARN_FRACTION * budget and not self._context_warned:
            self._context_warned = True
            self._on_meta({
                "kind": "status",
                "phase": "context_near_full",
                "message": "Context is nearly full; older tool output will be shortened.",
                "used_chars": used,
                "budget_chars": budget,
            })
        if used < budget:
            return messages, False
        self.last_compactions += 1
        return compact_tool_results(messages, keep_rounds=2, keep_images=1), True

    def _on_meta(self, item: Dict[str, Any]) -> None:
        """Streamer→loop callback, wired only when ``options`` is set.

        Loop-only kinds (stop_reason, rescued, model_digest) are kept in
        ``self._turn_meta`` for this turn. ``reasoning`` becomes a reasoning
        chunk event; every other item (status, usage) becomes a
        ``system/state`` event carrying the item plus request_id and turn.
        """
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind == "rescued":
            self._prov_rescued = getattr(self, "_prov_rescued", 0) + len(item.get("ids") or [])
        elif kind == "stop_reason" and item.get("value") in ("max_tokens", "length"):
            self._prov_truncated = getattr(self, "_prov_truncated", 0) + 1

        if not isinstance(item, dict):
            return
        kind = str(item.get("kind") or "")
        if kind == "model_digest":
            value = item.get("value")
            self.last_model_digest = str(value) if value else None
        if kind == "usage":
            for key in ("input_tokens_evaluated", "output_tokens"):
                value = item.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    self.last_usage[key] = (self.last_usage.get(key) or 0) + value
        if kind in _LOOP_ONLY_META:
            self._turn_meta[kind] = dict(item)
            return
        if kind == "reasoning":
            self._emit("reasoning", "chunk", str(item.get("text") or ""))
            return
        self._emit("system", "state", "", dict(item))

    def _emit(self, role: str, type: str, text: str = "",
              metadata: Optional[Dict[str, Any]] = None) -> None:
        """Send one ``{role, type, text, metadata}`` item to ctx.on_event.

        The metadata gains ``request_id`` and ``turn``. A failing sink is
        logged and never breaks the run. No ctx or no on_event: no-op.
        """
        ctx = self._ctx
        if ctx is None or ctx.on_event is None:
            return
        meta = dict(metadata or {})
        meta.setdefault("request_id", ctx.request_id)
        if self._turn:
            meta.setdefault("turn", self._turn)
        try:
            ctx.on_event({"role": role, "type": type, "text": str(text or ""), "metadata": meta})
        except Exception:
            logger.warning("on_event sink failed", exc_info=True)

    def _call_turn(
        self,
        messages: List[Dict],
        system_prompt: str,
        on_text: Callable[[str], None],
        cancel_event: threading.Event,
    ) -> Tuple[str, List[Dict]]:
        """One model call, retried ``options.turn_retry`` times after a stream drop.

        The retry repeats only the model call with the same messages, so a
        tool that already ran is never run again. Each retry emits
        ``turn.retry`` so the panel discards the partial block (§2c).
        """
        retries_left = self.options.turn_retry if self.options is not None else 0
        while True:
            try:
                return self._call(
                    messages,
                    system_prompt,
                    on_text=on_text,
                    should_cancel=cancel_event.is_set,
                )
            except Exception as exc:
                if retries_left <= 0 or cancel_event.is_set() or not _is_stream_drop(exc):
                    raise
                retries_left -= 1
                logger.warning("stream dropped on turn %d (%s); retrying the turn",
                               self._turn, exc)
                self._turn_meta = {}
                self._emit("system", "state", "",
                           {"kind": "turn.retry", "reason": "stream dropped"})

    def _turn_truncated(self) -> bool:
        """True when guard_truncation is on and this turn hit the token limit."""
        if self.options is None or not self.options.guard_truncation:
            return False
        item = self._turn_meta.get("stop_reason") or {}
        return str(item.get("value") or "") in _TRUNCATED_STOP_REASONS

    def _text_sink(self, on_chunk: Callable[[str], None]) -> Callable[[str], None]:
        """on_chunk, plus an ``assistant/chunk`` event when ctx.on_event is set."""
        ctx = self._ctx
        if ctx is None or ctx.on_event is None:
            return on_chunk

        def _sink(chunk: str) -> None:
            on_chunk(chunk)
            self._emit("assistant", "chunk", chunk)

        return _sink

    def _out(self, message: Dict[str, Any]) -> None:
        """Append a deep copy of ``message`` to ctx.messages_out, if any."""
        ctx = self._ctx
        if ctx is None or ctx.messages_out is None:
            return
        try:
            ctx.messages_out.append(copy.deepcopy(message))
        except Exception:
            logger.warning("messages_out append failed", exc_info=True)

    def _finish_text_turn(self, text: str) -> None:
        """Seal the run's last turn.

        Its text goes to messages_out only; it is never part of a request
        body, so the S7 golden requests do not change (§2b).
        """
        self.last_final_text_empty = not text
        self._emit("assistant", "message", text, {"final": True})
        if text:
            self._out({"role": "assistant", "content": [{"type": "text", "text": text}]})

    def _rescued_ids(self) -> set:
        item = self._turn_meta.get("rescued") or {}
        return {str(i) for i in (item.get("ids") or [])}

    def _dispatch_tool(
        self,
        tool_bridge,
        *,
        session_id: str,
        tool_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        session_queue,
        cancel_event: threading.Event,
        call_key: str,
    ) -> Dict[str, Any]:
        """Run one tool: runtime-resident tools here, everything else on the bridge."""
        if tool_name == "search_docs":
            # Python-resident tool — never round-trips to Tcl. Returned
            # shape mirrors a Tcl tool result so the downstream
            # tool_result builder doesn't need a special case.
            return self._dispatch_search_docs(tool_input)
        if tool_name == "wiki_list":
            return self._dispatch_wiki_list(tool_input)
        if tool_name == "wiki_read":
            return self._dispatch_wiki_read(tool_input)
        if tool_name == "wiki_update":
            return self._dispatch_wiki_update(tool_input)
        if tool_name == "wiki_verify_pins":
            return self._dispatch_wiki_verify_pins(tool_input)
        kwargs: Dict[str, Any] = {
            "session_id": session_id,
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "session_queue": session_queue,
            "cancel_event": cancel_event,
        }
        # Only a bridge whose *class* declares supports_call_meta = True gets
        # the two new keywords. Reading the class, and requiring "is True",
        # keeps __getattr__ wrappers and mocks on the six legacy keywords.
        if getattr(type(tool_bridge), "supports_call_meta", False) is True:
            kwargs["call_key"] = call_key
            kwargs["request_id"] = self._ctx.request_id if self._ctx is not None else None
        return tool_bridge.execute_tool(**kwargs)

    def _run_tool_block(
        self,
        block: Dict[str, Any],
        call_key: str,
        *,
        tool_bridge,
        session_id: str,
        session_queue,
        cancel_event: threading.Event,
        on_tool_start: Optional[Callable[[str, Dict], None]],
        on_tool_result: Optional[Callable[[str, str, Dict], None]],
        truncated: bool,
        origin: str,
    ) -> Dict[str, Any]:
        """Execute one tool_use block and emit its tool.started/tool.finished pair."""
        tool_name = str(block.get("name") or "")
        tool_id = str(block.get("id") or "")
        tool_input = block.get("input") or {}

        if on_tool_start:
            try:
                on_tool_start(tool_name, tool_input)
            except Exception:
                pass

        executor = "runtime" if tool_name in _RUNTIME_TOOLS else "tcl"
        self._emit("system", "state", "", {
            "kind": "tool.started",
            "call_key": call_key,
            "tool_call_id": tool_id,
            "tool_name": tool_name,
            "executor": executor,
            "origin": origin,
            "input": tool_input,
        })
        logger.info("executing tool=%s id=%s call_key=%s", tool_name, tool_id, call_key)

        tool_t0 = time.perf_counter()
        if truncated:
            result: Dict[str, Any] = {"ok": False, "output": "",
                                      "error": TRUNCATED_TOOL_ERROR, "executed": "no"}
        else:
            result = self._dispatch_tool(
                tool_bridge,
                session_id=session_id,
                tool_id=tool_id,
                tool_name=tool_name,
                tool_input=tool_input,
                session_queue=session_queue,
                cancel_event=cancel_event,
                call_key=call_key,
            )
        tool_ms = (time.perf_counter() - tool_t0) * 1000.0
        self.last_tool_calls += 1

        # Mirror the result into the on-disk recorder so this chat.send
        # produces a replayable transcript.tcl + snapshots/. Failed tools are
        # counted in the manifest but never written to transcript.tcl; a
        # guarded (truncated) call never ran, so it is not recorded at all.
        if not truncated:
            self._recorder_record(
                tool_name=tool_name,
                tool_input=tool_input,
                result=result,
                duration_ms=tool_ms,
            )

        if on_tool_result:
            try:
                on_tool_result(tool_id, tool_name, result)
            except Exception:
                pass

        self._emit("system", "state", "",
                   _tool_finished_meta(call_key, tool_name, executor, result, tool_ms))
        return result

    def run(
        self,
        prompt: str,
        system_prompt: str,
        tool_bridge,                        # VmdToolBridge instance
        session_id: str,
        session_queue,                       # EventQueue
        cancel_event: threading.Event,
        on_chunk: Callable[[str], None],
        on_tool_start: Optional[Callable[[str, Dict], None]] = None,
        on_tool_result: Optional[Callable[[str, str, Dict], None]] = None,
        prior_messages: Optional[List[Dict]] = None,
        ctx: Optional[RunContext] = None,
    ) -> str:
        """
        Run a full multi-turn tool-calling session.

        on_chunk(text)              called for each streamed text word
        on_tool_start(name, input)  called just before tool execution
        on_tool_result(id, name, result_dict) called after tool returns
        prior_messages              optional conversation history from a
                                    resumed chat (Anthropic-style format)
        ctx                         optional RunContext: request_id and
                                    chat_id, on_event (loop events, §2c) and
                                    messages_out (canonical copies, §2b).
                                    None keeps today's behaviour.

        Returns the final assistant text. The outcome is also left on
        ``last_status`` ('complete' | 'cancelled' | 'error' | 'max_turns'),
        ``last_turns``, ``last_tool_calls`` and ``last_final_text_empty``.
        """
        # Conversation history maintained in Anthropic-style format internally.
        # If resuming a prior chat, inject the history before the new prompt.
        messages: List[Dict] = list(prior_messages or [])
        messages.append({"role": "user", "content": prompt})
        final_text = ""

        # Wiki opinion injection. The wiki tools are useless if the model
        # doesn't know it's expected to use them — empirically Claude
        # ignores them when the system prompt is silent. We append a
        # short directive only when wiki_store is wired so the without-
        # wiki arm of A/B benches doesn't see references to tools it
        # doesn't have.
        if self.wiki_store is not None:
            system_prompt = system_prompt + WIKI_SYSTEM_PROMPT_ADDENDUM

        # In-run compaction (§2b): only with options.compact_in_run. The
        # budget uses the final system prompt and the tools sent on turn 1.
        self.last_compactions = 0
        self._context_warned = False
        self._run_budget = None
        if self.options is not None and getattr(self.options, "compact_in_run", False):
            self._run_budget = compute_run_budget(
                context_tokens_for(self.provider_name, self.options),
                len(system_prompt),
                len(json.dumps(self._tools_for_turn())),
            )

        self._ctx = ctx
        self.last_wrapped_up = False
        self.last_wrap_up_error = None
        self._prov_tool_calls = 0
        self._prov_rescued = 0
        self._prov_truncated = 0
        self.last_model_digest = None
        self.last_usage = {"input_tokens_evaluated": None, "output_tokens": None}
        self._turn = 0
        self._turn_meta = {}
        self.last_status = None
        self.last_turns = 0
        self.last_tool_calls = 0
        self.last_final_text_empty = True
        opts = self.options
        max_turns = opts.max_turns if opts is not None else self.MAX_TURNS
        on_text = self._text_sink(on_chunk)

        # messages_out gets only new messages, starting with the prompt.
        self._out(messages[-1])

        # Open a recorder task for this chat.send. No-op if self.recorder
        # is None. Status is updated below; finalized in the finally block
        # so a cancel / exception still closes the run cleanly on disk.
        # With ctx the recorder gets the real chat id (§2a).
        self._recorder_start_task(prompt, ctx.chat_id if ctx is not None else session_id)
        end_status = "complete"

        try:
            guard = LoopGuard() if self._loop_guard_enabled() else None
            guard_stop = False
            for turn in range(max_turns):
                if cancel_event.is_set():
                    end_status = "cancelled"
                    logger.info("cancelled before turn %d", turn + 1)
                    break

                self._turn = turn + 1
                self._turn_meta = {}
                self.last_turns = turn + 1
                self._emit("system", "state", "", {"kind": "turn.started"})
                logger.debug("loop turn %d/%d model=%s",
                             turn + 1, max_turns, self.model)

                try:
                    # Real SSE streaming: on_text fires for each text delta
                    # as the provider produces it. cancel_event is checked
                    # between SSE events so Stop interrupts mid-generation.
                    # Only the per-call copy is compacted; ``messages`` (and
                    # therefore messages_out) keeps the full bodies.
                    call_messages = messages
                    if self._run_budget is not None:
                        call_messages, _compacted = self._compact_for_call(messages)
                    text, tool_blocks = self._call_turn(
                        call_messages, system_prompt, on_text, cancel_event,
                    )
                except (ClaudeLoopError, RunCancelled):
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc

                self._recorder_update_meta()

                if text:
                    final_text = text

                # report_cancelled: Stop during the stream ends the run as
                # cancelled instead of complete (§2a).
                if opts is not None and opts.report_cancelled and cancel_event.is_set():
                    end_status = "cancelled"
                    self._finish_text_turn(text)
                    logger.info("stopped during turn %d", turn + 1)
                    break

                # No tool calls → conversation complete
                if not tool_blocks:
                    logger.debug(
                        "loop complete after %d turns, no more tool calls",
                        turn + 1,
                    )
                    self._finish_text_turn(text)
                    break

                # --- Build assistant message (Anthropic format) ---
                assistant_content: List[Dict] = []
                if text:
                    assistant_content.append({"type": "text", "text": text})
                assistant_content.extend(tool_blocks)
                messages.append({"role": "assistant",
                                 "content": assistant_content})

                call_keys = [_mint_call_key() for _ in tool_blocks]
                self._emit("assistant", "message", text, {"final": False})
                self._out(_canonical_message(messages[-1], call_keys))

                truncated = self._turn_truncated()
                if truncated:
                    self._emit("system", "state", "", {
                        "kind": "status",
                        "phase": "turn_truncated",
                        "message": "The reply was cut off; its tool calls were not run.",
                    })
                rescued_ids = self._rescued_ids()

                # --- Execute each tool and collect results ---
                tool_result_blocks: List[Dict] = []
                result_keys: List[str] = []

                for block, call_key in zip(tool_blocks, call_keys):
                    if cancel_event.is_set():
                        end_status = "cancelled"
                        break
                    tool_id = str(block.get("id") or "")
                    origin = "rescued" if tool_id in rescued_ids else "model"
                    if guard_stop:
                        # C4: the guard stopped the run; the rest of this
                        # turn's calls are not run and do not count.
                        result = self._skip_tool_block(block, call_key, origin)
                    else:
                        result = self._run_tool_block(
                            block,
                            call_key,
                            tool_bridge=tool_bridge,
                            session_id=session_id,
                            session_queue=session_queue,
                            cancel_event=cancel_event,
                            on_tool_start=on_tool_start,
                            on_tool_result=on_tool_result,
                            truncated=truncated,
                            origin=origin,
                        )
                    nudge_text = ""
                    if guard is not None and not guard_stop and not cancel_event.is_set():
                        nudge_text, guard_stop = self._guard_after_result(
                            guard, str(block.get("name") or ""), block.get("input") or {},
                            result, call_key,
                        )
                    result_block = _build_tool_result_block(
                        tool_use_id=tool_id,
                        result=result,
                        include_image=self._vision_enabled(),
                        result_format=self._result_format(),
                    )
                    if nudge_text:
                        _append_to_tool_result(result_block, nudge_text)
                    tool_result_blocks.append(result_block)
                    result_keys.append(call_key)

                # --- Append tool results to conversation ---
                if tool_result_blocks:
                    messages.append(
                        {"role": "user", "content": tool_result_blocks}
                    )
                    self._out(_canonical_message(messages[-1], result_keys))
                if guard_stop and end_status != "cancelled":
                    end_status = "stuck"
                    logger.info("loop guard stopped the run after turn %d", turn + 1)
                    break
            else:
                logger.warning("hit max turns (%d) without finishing",
                               max_turns)
                end_status = "max_turns"
                # report_cancelled: Stop during the last allowed turn's tool
                # round is still a cancel (options=None keeps max_turns; S7).
                if opts is not None and opts.report_cancelled and cancel_event.is_set():
                    end_status = "cancelled"

            if (guard is not None and end_status in ("stuck", "max_turns")
                    and not cancel_event.is_set()):
                wrap_text, wrap_cancelled = self._run_wrap_up(
                    messages, system_prompt, on_text, cancel_event, self.last_turns + 1
                )
                if wrap_cancelled:
                    end_status = "cancelled"
                elif wrap_text:
                    final_text = wrap_text
        except RunCancelled:
            end_status = "cancelled"
            logger.info("stopped during a provider backoff")
        except Exception:
            end_status = "error"
            raise
        finally:
            self._recorder_update_meta()
            self.last_status = end_status
            self._recorder_end_task(end_status)
            self._ctx = None

        return final_text

    # ------------------------------------------------------------------
    # Recorder hooks — all no-ops when self.recorder is None
    # ------------------------------------------------------------------

    def _recorder_start_task(self, prompt: str, session_id: str) -> None:
        if self.recorder is None:
            return
        cwd_str = (
            str(self.recorder.runs_root.parent)
            if self.recorder.runs_root else os.getcwd()
        )
        try:
            self.recorder.start_task(
                prompt,
                chat_id=session_id,
                model=self.model,
                cwd=cwd_str,
            )
        except Exception:
            # Recorder must never break the chat loop. Log + continue.
            logger.warning("recorder.start_task failed", exc_info=True)

    def _recorder_record(
        self,
        *,
        tool_name: str,
        tool_input: Dict[str, Any],
        result: Dict[str, Any],
        duration_ms: float,
    ) -> None:
        if self.recorder is None:
            return
        self._prov_tool_calls = getattr(self, "_prov_tool_calls", 0) + 1
        if result.get("blocked"):
            # C1: a blocked call never reached VMD; it changes neither
            # transcript.tcl nor the manifest counts.
            return
        try:
            if tool_name == "run_vmd_command":
                command = str(tool_input.get("command") or "")
                rationale = str(tool_input.get("rationale") or "")
                ok = bool(result.get("ok", False))
                statements = result.get("statements") or {}
                failed = statements.get("failed") or {}
                applied_text = str(result.get("applied_text") or "")
                if not ok and applied_text and failed.get("index"):
                    # C3 partial failure: statements 1..applied are in effect.
                    self.recorder.record_vmd_command(
                        command,
                        ok=False,
                        rationale=rationale,
                        duration_ms=duration_ms,
                        applied_text=applied_text,
                        failed_index=int(failed["index"]),
                        total=int(statements.get("total") or 0),
                        error=str(result.get("error") or ""),
                    )
                else:
                    self.recorder.record_vmd_command(
                        command,
                        ok=ok,
                        rationale=rationale,
                        duration_ms=duration_ms,
                    )
            elif tool_name == "capture_vmd_snapshot":
                purpose = str(tool_input.get("purpose") or "")
                ok = bool(result.get("ok", False))
                image_b64 = str(result.get("image_b64") or "")
                image_mime = str(
                    result.get("image_mime") or "image/png"
                )
                image_bytes: Optional[bytes] = None
                if image_b64:
                    try:
                        image_bytes = base64.b64decode(image_b64)
                    except Exception:
                        image_bytes = None
                ext = "png"
                if image_mime in ("image/jpeg", "image/jpg"):
                    ext = "jpg"
                elif image_mime == "image/tga":
                    ext = "tga"
                # The product bridge renders with TachyonInternal and may have
                # written a save_path deliverable (spec 2d); benchmark bridges
                # return neither key, so their transcript lines are unchanged.
                extra: Dict[str, Any] = {}
                image = result.get("image")
                if isinstance(image, dict):
                    extra["renderer"] = str(image.get("renderer") or "TachyonInternal")
                if result.get("saved_path"):
                    extra["saved_path"] = str(result["saved_path"])
                self.recorder.record_snapshot(
                    ok=ok,
                    purpose=purpose,
                    image_bytes=image_bytes,
                    image_ext=ext,
                    duration_ms=duration_ms,
                    **extra,
                )
            # search_docs is intentionally not recorded — it produces no
            # VMD state change, so replaying without it still works.
        except Exception:
            logger.warning("recorder hook failed", exc_info=True)

    def _recorder_update_meta(self) -> None:
        """C6: push digest, usage and counts into the recorder manifest.

        Only for product runs (``self._ctx`` set) and only when the recorder
        was built with provenance meta; benchmark runs build no recorder.
        """
        if self.recorder is None or self._ctx is None:
            return
        update = getattr(self.recorder, "update_meta", None)
        if update is None:
            return
        usage = dict(getattr(self, "last_usage", None) or {})
        try:
            update(
                model_digest=self._provenance_digest(),
                usage={
                    "input_tokens_evaluated": usage.get("input_tokens_evaluated"),
                    "output_tokens": usage.get("output_tokens"),
                },
                counts={
                    "tool_calls": int(getattr(self, "_prov_tool_calls", 0)),
                    "rescued_calls": int(getattr(self, "_prov_rescued", 0)),
                    "truncated_turns": int(getattr(self, "_prov_truncated", 0)),
                    "compactions": int(getattr(self, "last_compactions", 0) or 0),
                },
            )
        except Exception:
            logger.warning("recorder.update_meta failed", exc_info=True)

    def _provenance_digest(self) -> Optional[str]:
        """Ollama model digest: /api/ps (preflight), else the cached /api/tags
        entry, else None. Never sends a request of its own (C6)."""
        digest = getattr(self, "last_model_digest", None)
        if digest:
            return str(digest)
        if not self._is_ollama:
            return None
        options = getattr(self, "options", None)
        base = (getattr(options, "base_url", None) if options is not None else None) or self.api_key
        try:
            from .provider_catalog import cached_tag_digest
            return cached_tag_digest(base or "http://localhost:11434", self.model)
        except Exception:
            return None

    def _recorder_end_task(self, status: str) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder.end_task(status=status)
        except Exception:
            logger.warning("recorder.end_task failed", exc_info=True)


# ---------------------------------------------------------------------------
# Provider-aware factory
# ---------------------------------------------------------------------------

def build_claude_loop(
    provider_name: str,
    docs_search: Optional[Any] = None,
    wiki_store: Optional[WikiStore] = None,
    model: Optional[str] = None,
) -> Optional[ClaudeToolLoop]:
    """
    Build a ClaudeToolLoop for the given provider if API keys are available.
    Returns None for mock/unknown providers (fall back to simple streaming).

    ``docs_search`` is an optional DocsSearch instance (or a duck-typed
    equivalent). When supplied and ``is_available``, the model is offered
    a third tool, ``search_docs``, that retrieves snippets from the local
    docs index. When omitted or unavailable, the agent runs in the
    pre-RAG configuration — useful for A/B comparisons.

    ``wiki_store`` is an optional WikiStore for the LLM Wiki pattern.
    When supplied, the model gains four extra tools (wiki_list, wiki_read,
    wiki_update, wiki_verify_pins) and is expected to consult the wiki
    before falling back to raw doc search.

    ``model`` overrides the env-derived model string. The UI's
    ``provider.set`` RPC passes the user-picked model through here so the
    in-app picker actually controls which model is used (otherwise the
    Ollama branch was env-only and the dropdown was cosmetic).
    """
    name = str(provider_name or "").lower()
    explicit_model = (model or "").strip() or None

    if name in ("openrouter", "claude", "claude-openrouter"):
        key, _source = resolve_openrouter_api_key()
        if not key:
            return None
        chosen = explicit_model or os.getenv("VMD_AI_MODEL") or "anthropic/claude-sonnet-4.6"
        return ClaudeToolLoop(
            provider_name="openrouter",
            api_key=key,
            model=chosen,
            docs_search=docs_search,
            wiki_store=wiki_store,
        )

    if name in ("anthropic-direct", "anthropic_api", "anthropic-direct-api"):
        key, _source = resolve_anthropic_api_key()
        if not key:
            return None
        chosen = explicit_model or os.getenv("VMD_AI_MODEL") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-6"
        return ClaudeToolLoop(
            provider_name="anthropic-direct",
            api_key=key,
            model=chosen,
            docs_search=docs_search,
            wiki_store=wiki_store,
        )

    if name in ("ollama", "local-ollama", "local_ollama"):
        # Ollama needs no API key — but the model MUST be specified.
        # We pack the base URL into ``api_key`` to keep the constructor
        # surface uniform across providers; _call() unpacks it.
        if explicit_model:
            chosen = explicit_model
        else:
            chosen, _model_src = resolve_ollama_model()
        if not chosen:
            logger.warning(
                "Ollama provider requested but no model configured. "
                "Set VMD_AI_OLLAMA_MODEL (or OLLAMA_MODEL), or pick a model in the UI."
            )
            return None
        base_url, _host_src = resolve_ollama_host()
        return ClaudeToolLoop(
            provider_name="ollama",
            api_key=base_url,   # repurposed: base URL, not a real key
            model=chosen,
            docs_search=docs_search,
            wiki_store=wiki_store,
        )

    if name in ("openai-compatible", "openai_compatible"):
        # A local vLLM/SGLang/LM Studio server. The key falls back to "EMPTY";
        # on this env-driven path the URL comes from VMD_AI_OPENAI_BASE_URL.
        key, _source = resolve_openai_compatible_api_key()
        chosen = explicit_model or os.getenv("VMD_AI_MODEL") or ""
        if not chosen:
            logger.warning("openai-compatible provider requested but no model configured.")
            return None
        return ClaudeToolLoop(
            provider_name="openai-compatible",
            api_key=key,
            model=chosen,
            docs_search=docs_search,
            wiki_store=wiki_store,
        )

    return None


# ---------------------------------------------------------------------------
# History → Anthropic messages conversion
# ---------------------------------------------------------------------------

def events_to_messages(events: List[Dict], drop_trailing_user: bool = False) -> List[Dict]:
    """Convert stored JSONL events into Anthropic-style alternating messages.

    Only ``user`` and ``assistant`` roles produce messages.  Consecutive events
    of the same role are merged into a single message (Claude API requires
    strict user/assistant alternation).

    Tool events, lifecycle events, and system events are skipped because we
    don't have enough information to rebuild full tool_use/tool_result blocks
    from the JSONL log.  The resulting message list gives Claude *textual*
    context of the prior conversation, which is sufficient for continuity.

    ``drop_trailing_user`` skips the last user message event when no
    assistant message follows it: the prompt chat.send has just persisted,
    which run() appends again (the resume dedupe fix, spec §2b).
    """
    skip_index = -1
    if drop_trailing_user:
        for index in range(len(events) - 1, -1, -1):
            ev = events[index]
            if str(ev.get("type") or "") != "message" or not str(ev.get("text") or "").strip():
                continue
            role = str(ev.get("role") or "")
            if role == "assistant":
                break
            if role == "user":
                skip_index = index
                break

    messages: List[Dict] = []
    for index, ev in enumerate(events):
        if index == skip_index:
            continue
        role = str(ev.get("role") or "")
        etype = str(ev.get("type") or "")
        text = str(ev.get("text") or "").strip()

        # Only keep user messages and completed assistant messages
        if role == "user" and etype == "message" and text:
            if messages and messages[-1]["role"] == "user":
                # Merge consecutive user messages
                messages[-1]["content"] += f"\n{text}"
            else:
                messages.append({"role": "user", "content": text})

        elif role == "assistant" and etype == "message" and text:
            if messages and messages[-1]["role"] == "assistant":
                messages[-1]["content"] += f"\n{text}"
            else:
                messages.append({"role": "assistant", "content": text})

    return messages
