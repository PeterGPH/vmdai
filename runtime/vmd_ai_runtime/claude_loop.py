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
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from .provider import (
    ProviderError,
    resolve_anthropic_api_key,
    resolve_ollama_host,
    resolve_ollama_model,
    resolve_openrouter_api_key,
)
from .recorder import RunRecorder
from .wiki_store import (
    WikiError,
    WikiNotFound,
    WikiPathError,
    WikiSourceMissing,
    WikiStore,
)

logger = logging.getLogger("vmdai.claude_loop")

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


def _stream_request(req: urllib.request.Request, timeout: int, max_retries: int = 5):
    """Open the request and surface HTTP errors as ClaudeLoopError.

    Retries on rate-limit (429) and transient overload (5xx) with backoff,
    honoring the server's Retry-After header when present. This keeps a single
    throttle from killing a whole multi-turn agentic run. Returns the response
    context manager — the caller is responsible for closing it (use ``with``).
    """
    attempt = 0
    while True:
        try:
            return urllib.request.urlopen(req, timeout=timeout)
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
                _sleep(wait)
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
            raise ClaudeLoopError(
                f"API error HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            # Transient network blip (DNS, reset): a couple of retries.
            if attempt < max_retries:
                attempt += 1
                wait = min(30.0, 2.0 ** attempt)
                logger.warning("network error (%s); retry %d/%d in %.1fs",
                               exc, attempt, max_retries, wait)
                _sleep(wait)
                continue
            raise ClaudeLoopError(f"network error: {exc}") from exc


def _stream_anthropic_direct(
    messages: List[Dict],
    model: str,
    system_prompt: str,
    api_key: str,
    timeout: int,
    on_text: Callable[[str], None],
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
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

    text_parts: List[str] = []
    blocks_in_progress: Dict[int, Dict[str, Any]] = {}
    final_tool_blocks: List[Dict[str, Any]] = []

    with _stream_request(req, timeout) as resp:
        for event in _iter_sse_events(resp):
            if event is _DONE_SENTINEL:
                break
            if should_cancel():
                break

            etype = str(event.get("type") or "")

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

            if etype == "message_stop":
                break

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
) -> Tuple[str, List[Dict]]:
    """Stream a turn from OpenRouter / OpenAI-style chat completions."""
    or_messages = []
    if system_prompt:
        or_messages.append({"role": "system", "content": system_prompt})
    or_messages.extend(_to_openrouter_messages(messages))

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
    _base = os.environ.get("VMD_AI_OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    req = urllib.request.Request(
        _base + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
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

    with _stream_request(req, timeout) as resp:
        for event in _iter_sse_events(resp):
            if event is _DONE_SENTINEL:
                break
            if should_cancel():
                break

            choices = event.get("choices") or []
            if not choices:
                continue
            delta = (choices[0] or {}).get("delta") or {}

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


def _to_ollama_messages(messages: List[Dict]) -> List[Dict]:
    """Convert internal Anthropic-style messages to Ollama format.

    Ollama's ``/api/chat`` accepts an OpenAI-ish message list with
    these roles: ``system``, ``user``, ``assistant``, ``tool``. Each
    assistant turn may carry ``tool_calls``; tool results come as
    ``role=tool`` messages with the result text in ``content``.

    Differences from OpenRouter conversion:
      * ``arguments`` in tool_calls is an OBJECT (not a JSON string)
      * Ollama doesn't track ``tool_call_id`` the same way — we still
        emit it for round-trip clarity, but Ollama will ignore it.
      * Images in ``tool_result`` are dropped (Ollama vision models
        accept images differently; we keep this path text-only for
        now and surface a text marker instead).
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

        for block in content:
            btype = block.get("type", "")
            if btype == "text":
                text_parts.append(str(block.get("text") or ""))
            elif btype == "tool_use":
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
                    for b in tc_content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "image":
                            parts.append(
                                "[Snapshot captured — image not shown in "
                                "this provider mode]"
                            )
                        else:
                            parts.append(str(b.get("text") or ""))
                    tc_content = " ".join(p for p in parts if p)
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": str(tc_content),
                })
            # ``image`` blocks at top level are dropped — Ollama's
            # vision path requires multipart images on the user msg,
            # which we don't use here.

        if tool_results:
            out.extend(tool_results)
        elif tool_calls:
            msg_out: Dict[str, Any] = {
                "role": role,
                "content": "".join(text_parts) or "",
                "tool_calls": tool_calls,
            }
            out.append(msg_out)
        else:
            out.append({"role": role, "content": "".join(text_parts)})

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

    Returns the list of synthesized tool_use blocks (empty if none).
    Conservative on purpose: we'd rather miss a rescue than fire on
    unrelated content.
    """
    if not text or not allowed_names:
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
    # invocation when the model was offered that tool.
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
    ol_messages: List[Dict] = []
    if system_prompt:
        ol_messages.append({"role": "system", "content": system_prompt})
    ol_messages.extend(_to_ollama_messages(messages))

    tools_list = list(tools) if tools is not None else VMD_TOOLS
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
    body: Dict[str, Any] = {
        "model": model,
        "messages": ol_messages,
        "stream": True,
        "tools": _ollama_tools(tools_list),
        "options": options,
    }

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

    try:
        with _stream_request(req, timeout) as resp:
            for event in _iter_ndjson_events(resp):
                if should_cancel():
                    break
                if "error" in event:
                    raise ClaudeLoopError(
                        f"Ollama error: {event['error']}"
                    )
                msg = event.get("message") or {}
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
                    break
    except ClaudeLoopError:
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
        raise ClaudeLoopError(f"Ollama stream failed: {exc}") from exc

    text = "".join(text_parts)

    # JSON-in-content rescue: if the model didn't emit structured
    # tool_calls but pasted a tool-call-shaped JSON into the text body,
    # synthesize tool_use blocks from it. See _rescue_json_tool_calls.
    if not final_tool_blocks and text:
        allowed = {str(t.get("name") or "") for t in tools_list if t.get("name")}
        rescued = _rescue_json_tool_calls(text, allowed)
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
            # Drop the JSON text from history so the model doesn't learn
            # to repeat the pattern on the next turn. The UI already
            # received it via on_text — we just don't persist it.
            text = ""

    return text, final_tool_blocks


# ---------------------------------------------------------------------------
# Message-format conversion helpers
# ---------------------------------------------------------------------------

def _to_openrouter_messages(messages: List[Dict]) -> List[Dict]:
    """
    Convert internal Anthropic-style messages to OpenAI/OpenRouter format.

    Internal Anthropic format:
        {"role": "user"|"assistant", "content": str | list-of-blocks}

    OpenRouter format:
        {"role": "user"|"assistant", "content": str, "tool_calls": [...]}
        {"role": "tool", "tool_call_id": "...", "content": "..."}
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
    pass


# ---------------------------------------------------------------------------
# Tool result construction
# ---------------------------------------------------------------------------

def _build_tool_result_block(
    tool_use_id: str,
    result: Dict[str, Any],
    include_image: bool,
) -> Dict:
    """
    Build an Anthropic tool_result content block from the tool bridge result dict.

    For capture_vmd_snapshot results that include image_b64, the image is
    embedded as a base64 content block (only when include_image=True, i.e.
    when calling Anthropic directly).
    """
    ok = bool(result.get("ok", False))
    output = str(result.get("output") or "")
    error = str(result.get("error") or "")
    image_b64 = str(result.get("image_b64") or "")
    image_mime = str(result.get("image_mime") or "image/png")

    if ok:
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
# The Claude tool loop
# ---------------------------------------------------------------------------

class ClaudeToolLoop:
    """
    Drives multi-turn Claude conversations with VMD tool-use support.

    Instantiate once per provider configuration and call run() per chat turn.
    """

    MAX_TURNS = 28  # raised from 16: multi-step analysis tasks (RMSD/Rg/contacts) need more turns

    def __init__(
        self,
        provider_name: str,
        api_key: str,
        model: str,
        timeout: int = 90,
        docs_search: Optional[Any] = None,
        recorder: Optional[RunRecorder] = None,
        wiki_store: Optional[WikiStore] = None,
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
        return (tools + list(extra)) if extra else tools

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
        """
        tools = self._tools_for_turn()
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
        )

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
    ) -> str:
        """
        Run a full multi-turn tool-calling session.

        on_chunk(text)              called for each streamed text word
        on_tool_start(name, input)  called just before tool execution
        on_tool_result(id, name, result_dict) called after tool returns
        prior_messages              optional conversation history from a
                                    resumed chat (Anthropic-style format)

        Returns the final assistant text.
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

        # Open a recorder task for this chat.send. No-op if self.recorder
        # is None. Status is updated below; finalized in the finally block
        # so a cancel / exception still closes the run cleanly on disk.
        self._recorder_start_task(prompt, session_id)
        end_status = "complete"

        try:
            for turn in range(self.MAX_TURNS):
                if cancel_event.is_set():
                    end_status = "cancelled"
                    logger.info("cancelled before turn %d", turn + 1)
                    break

                logger.debug("loop turn %d/%d model=%s",
                             turn + 1, self.MAX_TURNS, self.model)

                try:
                    # Real SSE streaming: on_chunk fires for each text delta
                    # as the provider produces it. cancel_event is checked
                    # between SSE events so Stop interrupts mid-generation.
                    text, tool_blocks = self._call(
                        messages,
                        system_prompt,
                        on_text=on_chunk,
                        should_cancel=cancel_event.is_set,
                    )
                except ClaudeLoopError:
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc

                if text:
                    final_text = text

                # No tool calls → conversation complete
                if not tool_blocks:
                    logger.debug(
                        "loop complete after %d turns, no more tool calls",
                        turn + 1,
                    )
                    break

                # --- Build assistant message (Anthropic format) ---
                assistant_content: List[Dict] = []
                if text:
                    assistant_content.append({"type": "text", "text": text})
                assistant_content.extend(tool_blocks)
                messages.append({"role": "assistant",
                                 "content": assistant_content})

                # --- Execute each tool and collect results ---
                tool_result_blocks: List[Dict] = []

                for block in tool_blocks:
                    if cancel_event.is_set():
                        end_status = "cancelled"
                        break

                    tool_name = str(block.get("name") or "")
                    tool_id = str(block.get("id") or "")
                    tool_input = block.get("input") or {}

                    if on_tool_start:
                        try:
                            on_tool_start(tool_name, tool_input)
                        except Exception:
                            pass

                    logger.info("executing tool=%s id=%s",
                                tool_name, tool_id)

                    tool_t0 = time.perf_counter()
                    if tool_name == "search_docs":
                        # Python-resident tool — never round-trips to Tcl.
                        # Returned shape mirrors a Tcl tool result so the
                        # downstream tool_result builder doesn't need a
                        # special case.
                        result = self._dispatch_search_docs(tool_input)
                    elif tool_name == "wiki_list":
                        result = self._dispatch_wiki_list(tool_input)
                    elif tool_name == "wiki_read":
                        result = self._dispatch_wiki_read(tool_input)
                    elif tool_name == "wiki_update":
                        result = self._dispatch_wiki_update(tool_input)
                    elif tool_name == "wiki_verify_pins":
                        result = self._dispatch_wiki_verify_pins(tool_input)
                    else:
                        result = tool_bridge.execute_tool(
                            session_id=session_id,
                            tool_call_id=tool_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            session_queue=session_queue,
                            cancel_event=cancel_event,
                        )
                    tool_ms = (time.perf_counter() - tool_t0) * 1000.0

                    # Mirror the result into the on-disk recorder so this
                    # chat.send produces a replayable transcript.tcl +
                    # snapshots/. Failed tools are counted in the manifest
                    # but never written to transcript.tcl (by design).
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

                    tool_result_blocks.append(
                        _build_tool_result_block(
                            tool_use_id=tool_id,
                            result=result,
                            include_image=self._is_anthropic_direct,
                        )
                    )

                # --- Append tool results to conversation ---
                if tool_result_blocks:
                    messages.append(
                        {"role": "user", "content": tool_result_blocks}
                    )
            else:
                logger.warning("hit max turns (%d) without finishing",
                               self.MAX_TURNS)
                end_status = "max_turns"
        except Exception:
            end_status = "error"
            raise
        finally:
            self._recorder_end_task(end_status)

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
        try:
            if tool_name == "run_vmd_command":
                command = str(tool_input.get("command") or "")
                rationale = str(tool_input.get("rationale") or "")
                ok = bool(result.get("ok", False))
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
                self.recorder.record_snapshot(
                    ok=ok,
                    purpose=purpose,
                    image_bytes=image_bytes,
                    image_ext=ext,
                    duration_ms=duration_ms,
                )
            # search_docs is intentionally not recorded — it produces no
            # VMD state change, so replaying without it still works.
        except Exception:
            logger.warning("recorder hook failed", exc_info=True)

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

    return None


# ---------------------------------------------------------------------------
# History → Anthropic messages conversion
# ---------------------------------------------------------------------------

def events_to_messages(events: List[Dict]) -> List[Dict]:
    """Convert stored JSONL events into Anthropic-style alternating messages.

    Only ``user`` and ``assistant`` roles produce messages.  Consecutive events
    of the same role are merged into a single message (Claude API requires
    strict user/assistant alternation).

    Tool events, lifecycle events, and system events are skipped because we
    don't have enough information to rebuild full tool_use/tool_result blocks
    from the JSONL log.  The resulting message list gives Claude *textual*
    context of the prior conversation, which is sufficient for continuity.
    """
    messages: List[Dict] = []
    for ev in events:
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

    # Ensure the list doesn't end with a user message that will be duplicated
    # by the new prompt (the caller appends the new user message separately).
    return messages
