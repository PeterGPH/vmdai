# LLM Interface

vmd_ai drives a Claude-family model through two HTTP backends with no
external SDK. This doc summarizes how requests are formed, what tools
are exposed to the model, and where credentials come from.

## Architecture at a glance

```
VMD Tcl plugin
    ↓ JSON-RPC over loopback HTTP
RuntimeApp
    └─ ClaudeToolLoop
          ├─→ streaming HTTP ─→ OpenRouter / Anthropic direct
          ├─→ VmdToolBridge ─→ Tcl side (run_vmd_command, capture_vmd_snapshot)
          └─→ DocsSearch (Python-resident: search_docs)
```

## Providers

| Provider | Endpoint | Auth | Selected when |
|---|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | `Authorization: Bearer <key>` + `HTTP-Referer: https://localhost/vmd-ai` + `X-Title: vmd-ai` | OpenRouter key found, or `VMD_AI_PROVIDER=openrouter` |
| Anthropic direct | `https://api.anthropic.com/v1/messages` | `x-api-key: <key>` + `anthropic-version: 2023-06-01` | Only Anthropic key found, or `VMD_AI_PROVIDER=anthropic-direct` |
| Mock | none | none | No keys anywhere — runtime stays usable for offline UI testing |

All three provider classes live in
[`provider.py`](../runtime/vmd_ai_runtime/provider.py); the OpenRouter and
Anthropic streaming clients are in
[`claude_loop.py`](../runtime/vmd_ai_runtime/claude_loop.py). No `openai` or
`anthropic` SDK dependency — pure `urllib.request`.

## Streaming

Every API call uses SSE (`"stream": true`). The client is a stdlib
generator, `_iter_sse_events()`, that yields decoded `data: …` payloads
and a `_DONE_SENTINEL` for OpenAI's `[DONE]` line.

Two streaming functions consume those events:

- `_stream_anthropic_direct()` — handles `content_block_start`,
  `content_block_delta` (`text_delta` + `input_json_delta`),
  `content_block_stop`, `message_stop`.
- `_stream_openrouter()` — handles OpenAI-style `choices[0].delta` with
  content fragments and `tool_calls[]` deltas; terminates on `[DONE]`.

Both push text deltas to an `on_text` callback in real time and check
`should_cancel()` between events so the user's Stop button interrupts
mid-generation.

## Message format

Internal canonical form is **Anthropic-style**: alternating `user` /
`assistant` roles with content as either a string or a list of typed
blocks (`text`, `tool_use`, `tool_result`, `image`).

Conversion to OpenRouter happens in `_to_openrouter_messages()`:

- `tool_use` blocks → OpenAI `tool_calls[]`
- `tool_result` blocks → separate `role: tool` messages keyed by
  `tool_call_id`
- `image` blocks: kept as base64 for Anthropic direct; stripped to a
  text marker for OpenRouter (most routes don't accept multimodal in
  tool_result)

## Tool surface

Three tools, dynamically filtered per turn by `_tools_for_turn()`:

| Name | Args | Dispatch | Always available? |
|---|---|---|---|
| `run_vmd_command` | `command` (newline-separated Tcl), optional `rationale` | VmdToolBridge → Tcl side → live VMD | Yes |
| `capture_vmd_snapshot` | optional `purpose` | VmdToolBridge → Tcl render → TGA→PNG | Yes |
| `search_docs` | `query`, optional `k` (1-10), optional `scope` | DocsSearch (BM25 over local index) | Only when `~/.vmdai/docs_index/` exists |

`search_docs` is **Python-resident** — never round-trips to Tcl. The
other two go through
[`VmdToolBridge.execute_tool()`](../runtime/vmd_ai_runtime/tool_bridge.py),
which pushes a `tool_start` event to the session's queue and blocks on
a `threading.Event` until the Tcl bridge POSTs `tool.command_result`.

## Turn loop

`ClaudeToolLoop.run()` runs once per `chat.send` RPC, capped at
`MAX_TURNS = 16`:

```
1. Build messages = prior history + new prompt + tool results so far
2. Stream one HTTP turn → final_text + tool_use blocks
3. If no tool_use blocks: return final_text. Done.
4. Else: dispatch each tool → collect tool_result blocks → GOTO 1
```

Tools execute strictly in order — one at a time per turn — so the
model sees a deterministic sequence of results. A failed tool dispatch
becomes a `tool_result` with `is_error: true`; the model sees the
failure and can recover on the next turn.

## Authentication

Resolution order in
[`provider.py`](../runtime/vmd_ai_runtime/provider.py):

1. Process env (`OPENROUTER_API_KEY`, or `ANTHROPIC_AUTH_TOKEN` if it
   pattern-matches an OR key for OpenRouter; `ANTHROPIC_API_KEY` for
   direct).
2. OS keychain via `keyring` (service `vmd_ai`, accounts
   `openrouter_api_key` / `anthropic_api_key`).
3. None found → mock provider.

`KeyStore.save()` (called from the `keys.save` RPC) writes to keyring
**and** populates `os.environ` immediately so the current process can
use the key without restarting. `KeyStore.__init__` runs
`load_saved_into_env()` on every runtime boot so saved keys are
hydrated automatically.

## Default models

| Variable | Default | Used by |
|---|---|---|
| `VMD_AI_MODEL` | `anthropic/claude-sonnet-4.6` | OpenRouter |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Anthropic direct |
| `chat.send` `model` param | overrides per-call | Both |

The Anthropic direct provider also normalizes legacy dot-names
(`claude-sonnet-4.6` → `claude-sonnet-4-5`) to keep older OpenRouter
model strings working.

## Tool result construction

`_build_tool_result_block()` produces an Anthropic-format `tool_result`:

- Text-only success: `content: "<output>"`, `is_error: false`
- Error: `content: "Error: <error>"`, `is_error: true`
- Snapshot for Anthropic direct: `content: [text_block, image_block]`
  with image carried as base64
- Snapshot for OpenRouter: text only with the suffix
  `[Snapshot captured — image not shown in this provider mode]`

## RAG via `search_docs`

When the index at `~/.vmdai/docs_index/` exists,
`DocsSearch.is_available` flips true and the tool list grows to three.
Implementation:

- Pure-stdlib **BM25** over corpus chunks; lazy-loaded on first call
- Three scopes: `vmd_ref`, `user_guide`, `skills` (or `all`)
- Returns up to `k` ranked chunks as `{source, section, score, text}`
- Tool result is rendered as
  `[1] <path>  §<heading>  (score=0.873)\n<text>\n\n---\n\n[2] …`

Index is built by
[`vmd-ai-index --rebuild`](../runtime/vmd_ai_runtime/scripts/build_docs_index.py).
With `--auto-detect-vmd`, the indexer locates the local VMD install,
runs `dump_help.tcl` headlessly, and ingests the user-guide HTML if
present.

## Cancellation and timeouts

- Per-request timeout: 90s (configurable on `ClaudeToolLoop` constructor)
- Cancel: `cancel_event` (a `threading.Event`) is checked between SSE
  events; the client closes the HTTP connection cleanly
- Tool dispatch: `VmdToolBridge.execute_tool` polls `cancel_event`
  every 100ms during its 45s wait

## Security boundaries

- The Tcl side runs model-emitted commands at **global scope** with no
  sandbox — see [README.md](../README.md) "Security model" for the
  trust boundary.
- Per-RPC session-token auth (`X-Session-Token` header). Every method
  including `tool.command_result` requires it; the latter additionally
  binds tool-call IDs to the originating session, so one session can't
  forge results for another.
- Keys live in the OS keychain; in-process `os.environ` exposure is
  scoped to the runtime process, not its child Tcl bridge.

## Recorder side-channel

`ClaudeToolLoop` accepts an optional `RunRecorder` (see
`runtime/vmd_ai_runtime/recorder/`). When set, the loop mirrors every
successful `run_vmd_command` and `capture_vmd_snapshot` result to
`<workdir>/.vmdai_runs/<task_id>/transcript.tcl` + `snapshots/`. The
recorder is a pure consumer of tool-bridge results — it does **not**
change the tool surface, the protocol, or the streaming behavior.
Failures inside the recorder are logged and swallowed; the chat loop
must never break because of a recorder error.

Wiring lives in `RuntimeApp._run_claude_loop_response`: a fresh
recorder is built per `chat.send`, bound to `self.claude_loop.recorder`
just before `loop.run()`, and unbound after — so the shared loop
doesn't leak a recorder binding into the next request. Disable with
`VMD_AI_RECORDER=off`.

## What's intentionally NOT in scope (yet)

- No batched / parallel turns
- No prompt-caching headers (`cache_control` for Anthropic)
- No JSON mode / structured outputs
- No streaming tool-call execution — a full `content_block_stop` must
  fire before the tool runs
- No retry/backoff on rate-limit errors — surfaces as `ClaudeLoopError`
- No multi-modal user input — text only into `chat.send`; images only
  flow back from `capture_vmd_snapshot`

## File map

| File | Role |
|---|---|
| [`runtime/vmd_ai_runtime/claude_loop.py`](../runtime/vmd_ai_runtime/claude_loop.py) | Streaming clients, tool loop, system prompt, tool definitions |
| [`runtime/vmd_ai_runtime/provider.py`](../runtime/vmd_ai_runtime/provider.py) | Provider abstraction, key resolution, mock fallback |
| [`runtime/vmd_ai_runtime/keys.py`](../runtime/vmd_ai_runtime/keys.py) | Keychain integration, env hydration |
| [`runtime/vmd_ai_runtime/tool_bridge.py`](../runtime/vmd_ai_runtime/tool_bridge.py) | Tcl-side tool dispatch with per-call session binding |
| [`runtime/vmd_ai_runtime/docs_search.py`](../runtime/vmd_ai_runtime/docs_search.py) | BM25 retriever, markdown / HTML / plaintext chunkers |
| [`runtime/vmd_ai_runtime/scripts/build_docs_index.py`](../runtime/vmd_ai_runtime/scripts/build_docs_index.py) | Indexer CLI, VMD auto-detect, `dump_help.tcl` runner |
| [`runtime/vmd_ai_runtime/app.py`](../runtime/vmd_ai_runtime/app.py) | RPC dispatcher; wires the loop, bridge, store, and DocsSearch together |

## Sequence: one chat.send

```
Tcl panel              RuntimeApp           ClaudeToolLoop        Provider
   │                       │                       │                  │
   │ chat.send ──────────► │                       │                  │
   │                       │ start worker thread   │                  │
   │                       ├──────────────────────►│ run(prompt)      │
   │                       │                       │ _call ──────────►│
   │                       │                       │◄─────── SSE deltas
   │ ◄─── poll: chunks ────┤  (forwarded by run via on_chunk)         │
   │                       │                       │                  │
   │                       │  search_docs / VMD tool dispatch         │
   │                       │  (run_vmd_command round-trips to Tcl)    │
   │ ◄─── tool_start ──────┤                       │                  │
   │ ─── tool.command_result ─►│                   │                  │
   │                       │                       │ next turn ──────►│
   │                       │                       │   ◄─── final ────│
   │ ◄─── final message ───┤                       │                  │
```
