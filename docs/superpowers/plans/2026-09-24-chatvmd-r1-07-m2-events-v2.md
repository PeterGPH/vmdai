# ChatVMD Round 1 — Plan 07: ChatVMD R1 — M2 event contract v2 and runtime persistence

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the display half of the event contract: negotiated v2 events, request.finished on every path, late tool.finished, display-log persistence and replay, monotonic seq, long-poll, profiles.* RPCs, and the five scenario fixtures recorded from the runtime.

**Architecture:** In a token session that negotiates `event_protocol: 2`, every `ctx.on_event` item goes through one per-request sink, `_EventMapper`, which tags it `v: 2`, seals each turn's reasoning and writes the display kinds to `events.jsonl`; v1 sessions keep exactly today's events. Both worker paths (agent loop and mock) emit `request.started` first and `request.finished` from a `finally`, and the late-result hook adds a second `tool.finished {late: true}`. `EventQueue` keeps `seq` monotonic, trims delivered events and long-polls on a `Condition`; `chat.history.get` replays the deduplicated display log, and `profiles.*` edits `settings.json` through `SettingsStore`.

**Tech Stack:** Python 3.9–3.12 standard library only (`threading.Condition`, `json`, `re`, `dataclasses`), pytest. This plan has no Tcl or Tk code; the fixtures it writes are consumed by the Tcl view-model in plan 08.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md`. This plan implements:
- §2c: Recommendation (negotiation, envelope), Rules (execution vs display channels, block boundaries, sealing, `request.finished` is guaranteed), Persistence, and Sequence numbers.
- §2a: Legacy callbacks, and the `on_event` item shape.
- §2d: M2 long-poll; Cancel semantics (late results produce a second `tool.finished`).
- §2f: Error codes (error events and actions).
- §3: RPC rows `session.start`, `chat.events.poll`, `chat.resume`, `chat.history.get` and `profiles.*`; the `store.py`/`events.py` row (message-only counts, monotonic `seq`, `wait()`).
- §6: Scenario fixtures.
- §7: Existing chats (replay dedupe, `message_count` recount).
- Part C: C1/C3/C5 display fields on `tool.finished`; C4 (`stuck`, `wrapped_up`, the fifth fixture `loop_guard`); C7 (Model change for `profiles.save`).

Part C wins where it conflicts with Parts A/B.

**Branch:** `chatvmd-r1-07-m2-events-v2`, created from `main` after plans 05 and 06 are merged.

## Global Constraints

- Repo /Users/pinhaogu/Documents/GitHub/vmdai, base branch main (HEAD 6f5f937 at planning). Run every command from the repo root. Each plan runs on its own branch, cut from main after its depends_on plans are merged.
- Every commit message ends with: Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
- The runtime (runtime/vmd_ai_runtime/**, runtime/main.py) is stdlib-only and must import and run on Python 3.9 (/usr/bin/python3 is 3.9.6). Not allowed: match statements, X | Y unions evaluated at run time (e.g. isinstance(x, int | None)). Keep `from __future__ import annotations`. Pillow and keyring stay optional imports. tcl_policy.py and loop_guard.py are stdlib-only and 3.9-compatible.
- S7 / §7: with options=None and ctx=None there are no benchmark-visible changes. Unchanged: the ClaudeToolLoop constructor, run, _call(messages, system_prompt, on_text, should_cancel), _tools_for_turn, extra_tools, the six execute_tool keywords (session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event) and the result dict. MAX_TURNS stays 28. Every behaviour change sits behind a LoopOptions flag whose default is today's behaviour.
- Frozen byte-for-byte: VMD_SYSTEM_PROMPT, WIKI_SYSTEM_PROMPT_ADDENDUM, SEARCH_DOCS_TOOL, WIKI_LIST_TOOL, WIKI_READ_TOOL, WIKI_UPDATE_TOOL, WIKI_VERIFY_TOOL, VMD_TOOLS, the output of _vmd_tools(...), and the output of image_utils.read_image_as_png_bytes and tga_to_png_bytes (M0 hash guards). integrations/scivisagentbench/vmd_ai_agent.py builds ClaudeToolLoop without options and never passes ctx or options. Round 1 edits only its docstring.
- call_key = uuid.uuid4().hex[:12], minted once per tool execution. call_key= and request_id= reach execute_tool only when getattr(type(tool_bridge), 'supports_call_meta', False) is True, and only VmdToolBridge declares that.
- Tests are hermetic. Before each test, tests/conftest.py clears VMD_AI_*, ANTHROPIC_*, OPENROUTER_* and OLLAMA_*, points HOME at a temp dir, patches or stubs keyring, stubs settings_store.probe_local_ollama to return [], and calls provider_catalog.clear_caches(). The live gates VMD_AI_LIVE_OLLAMA, VMD_AI_LIVE_MODEL, VMD_AI_VMD_BIN, VMD_AI_TCLSH, VMD_AI_TCL_TM and VMD_AI_TK_LIB are read only through the live_env fixture. Tests patch only vmd_ai_runtime.claude_loop._sleep, never time.sleep. Tcl and Tk tests use a temp HOME and absolute temp paths.
- Suites: `env -u VMD_AI_PROVIDER python -m pytest tests -q` passes in under 60 s (S9; baseline 459 passed plus the known failure test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint, marked xfail(strict=True) from M0 until M1). `python -m pytest vmdbench/tests -q` stays at 90 passed. `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q` stays at 62 passed. CI (.github/workflows/tests.yml) runs on ubuntu-latest with Python 3.9 and 3.12, installs tcl8.6 with apt and only pytest with pip, and runs `python -m pytest tests -q`.
- Tcl for tests: use VMD_AI_TCLSH, else the first tclsh8.6 or tclsh on PATH whose `info patchlevel` is 8.6.x (reject /usr/bin/tclsh 8.5.9). Load http with `::tcl::tm::path add /Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6` (or VMD_AI_TCL_TM), then `package require -exact http 2.9.5`. Load json from plugin/lib/json with `package require -exact json 1.1.2`; until M1 vendors it, use VMD's plugins/noarch/tcl/json1.0. For Tk, `set ::tk_library /Applications/VMD.app/Contents/Frameworks/Tk.framework/Versions/8.6/Resources/Scripts`, then load that framework's Tk binary (override: VMD_AI_TK_LIB). Tk tests skip when a probe subprocess cannot load Tk within 10 s. Tests take no screenshots.
- Plugin Tcl passes the 8.5-safe lint. Banned: try, lmap, `string cat`, `dict map`, tailcall, coroutine, oo::, zlib, `binary encode|decode`, `lsort -stride`, `chan pipe`. Calls that exist only in 8.6 are wrapped in catch. ttk: configure only ChatVMD.* styles and never call `ttk::style theme use`. Namespace initialisers use `if {![info exists v]}`.
- Security: every HTTP request must carry Host 127.0.0.1:<port> or localhost:<port> and no Origin header; otherwise the runtime answers HTTP 403 with code FORBIDDEN. The launch token is 128 random bits. Under --announce it is printed only in `VMDAI_READY {"port":…,"pid":…,"version":…,"protocol":2,"launch_token":…}`. Without --announce it is written to ~/.vmdai/run/runtime-<port>.json {port,pid,token,protocol} with mode 0600 and removed on clean exit. A tokenless session.start is accepted only when the runtime started without --announce. chat_id must match ^chat_[0-9a-f]{12}$. tcl_policy is an accident guard, not a sandbox.
- Protocols: the runtime `protocol` is 2 from M1 (READY line, /health, runtime.info). `event_protocol` is negotiated in session.start and defaults to 1. The M1 plugin sends 1 and the M2 plugin sends 2. Tokenless sessions keep exactly today's methods, params and events; only C1's block applies to them.
- Error codes. RPC errors (UPPER_SNAKE), existing: INVALID_PARAMS, METHOD_NOT_FOUND, AUTH_FAILED, REQUEST_CONFLICT, NOT_FOUND, PROVIDER_INIT_FAILED, BIND_FORBIDDEN; new: AUTH_REQUIRED, FORBIDDEN, CHAT_LOCKED, NO_MODEL, IN_USE. Error events (lower_snake metadata.code): unreachable, auth, billing, model_not_found, other. metadata.action is one of open_settings, switch_profile, choose_model, test_connection, open_log.
- Timeouts. Tool pickup: 45 s until the ack. Tool execution: tool_exec_timeout_s 900 after a running ack. cancel_grace_s: 30. Ollama /api/version: 2 s, cached 30 s. /api/ps: 2 s, before every /api/chat, never cached. first_byte_timeout_s: 120. First-run probe: 127.0.0.1:11435 then :11434, 300 ms each. models.list and provider.test probes: 3 s; catalog cached 60 s. An unreachable Ollama fails within 3 s (S6). Plugin RPCs: default 3000 ms; chat.events.poll wait_ms+3000; models.list and provider.test 10000; runtime.shutdown 1500. READY within 20 s. SIGTERM exit within 2 s. kill -9 1.5 s after kill. Reconnect backoff 0.5–8 s with at most 3 respawns. Recovery within 10 s (S3). M1 short-poll every 250 ms with one poll outstanding; M2 long-poll wait_ms ≤ 2000. Result-queue retry 0.25→2 s. Tooltips after 600 ms.
- Caps. Model-facing tool output over 6000 chars is saved to chats/<id>/outputs/<call_key>.txt and cut to the first 3000 plus the last 2500 chars, with the note '[output truncated: N lines, K KB. Full text: <absolute path>. …]'. The executor posts up to 1 MB; past that it appends '[executor limit: output cut at 1 MB]' and sends truncated:true. The messages.jsonl store cap is 6000 chars on the output section only, with a warning at 2 MB. failed_statement ≤ 200 chars; error_info = first 3 lines, ≤ 500 chars; stubs 300 chars. Context warning at 90% of run_budget, compaction at 100%. 3.5 chars/token. run_budget = 3.5 × (context_tokens − 4096) − len(system prompt) − len(tools JSON). build_prior keeps ≤ 0.6 × run_budget. Images in context: 1 for ollama and openai-compatible, 3 for anthropic-direct and openrouter. Downscale to a 1024 px long edge for local models and 1568 px for Anthropic. Thumbnails fit 256×192. At most 30 live photos. Delivered events are trimmed beyond 1000. Pipe tail: 50 lines kept, 12 shown. History: newest 50. Prompt recall: 50.
- Context sizes. Ollama num_ctx defaults to 32768 in the product when the profile sets none (C7). First run writes min(32768, context_length), or 32768 when context_length is absent. options=None keeps num_ctx 8192. context_tokens: the resolved num_ctx for ollama; options.context_length (default 32768) for openai-compatible; 114k tokens (400k chars) for anthropic-direct and openrouter.
- LoopOptions.product(profile) sets: rescue 'json', result_format 'structured', loop_guard on, max_turns from the setting (28), connect_retries 0 for ollama and 1 otherwise, and the other gated flags on. options=None keeps rescue 'all', result_format 'legacy', no loop guard and 5 connect retries. rescue 'json' rescues only tool-call-shaped JSON that names an offered tool. ```tcl blocks in prose never run (S12). Round 1 always sends approval 'auto'.
- Files. ~/.vmdai/settings.json: {version:1, active, profiles, reasoning_visible:true, wiki_enabled:false, approval_mode:'auto', max_turns:28, tool_exec_timeout_s:900, cancel_grace_s:30}. ~/.vmdai/plugin.json: {version:1, python, appearance, expand_steps, geometry}. Writes to settings.json, manifest.json and index.jsonl happen under fcntl.flock on ~/.vmdai/.store.lock. Per-chat lock: chats/<id>/.lock (LOCK_EX|LOCK_NB). Per chat: messages.jsonl, images/<call_key>.png, images/<call_key>_thumb.png, outputs/<call_key>.txt. Log: ~/.vmdai/logs/runtime.log (rotating).
- Plugin: `package provide vmd_ai 2.0`; menu path 'VMD AI'. Entry points: ::vmdai::start (returns the window path), ::vmdai::stop, ::vmdai::cleanup, ::vmdai::reload, and the alias ::vmdai::ui::show_panel. Launch: `open |[list $python -u main.py --port 0 --announce --watch-stdin 2>@1] r+`. Python is resolved from VMD_AI_PYTHON, then plugin.json python, then auto_execok python3, and made absolute. Attach only via VMD_AI_ATTACH=host:port; the plugin never kills an attached runtime.
- Panel: default size 560×780, wm minsize 380 420, title 'ChatVMD — ‹chat title›'; closing does wm withdraw. Width classes: narrow < 440, regular 440–720, wide > 720. The status bar and toolbar never show the word 'tunnel'. The transcript is made read-only through a renamed widget command, never -state disabled. The mono font is the first available of SF Mono, Menlo and DejaVu Sans Mono, never a hard-coded Menlo.
- Goldens live in tests/fixtures/tk/<scenario>.txt, tests/fixtures/events/<name>.jsonl and tests/fixtures/ops/<name>.ops, and are rewritten only when CHATVMD_UPDATE_GOLDENS=1. The S7 request goldens in tests/fixtures/golden_requests/ are captured once in M0 and never regenerated.
- Do not modify docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md. Where Part C amendments conflict with Parts A/B, Part C wins.

**Plan-specific constraints**

- A v1 session gets exactly today's events and persistence, whether it is tokenless or a token session that asked for (or defaulted to) `event_protocol: 1`. Every v2-only branch tests `_wants_v2(state)`, which is true only when `state.event_protocol >= 2`. A tokenless session can never reach 2.
- Every v2 event the runtime pushes gets `metadata.v = 2` in exactly one place, `RuntimeApp._push_v2`. Events emitted while a request's worker runs travel through that request's `_EventMapper.push`, which adds `request_id`, seals reasoning and persists display kinds. Two events bypass the mapper. The user message is pushed by `chat.send` before the worker exists, and `chat.send` persists it as it does today. The late `tool.finished` goes through `_push_late_finished`.
- The v2 display log is written with `ChatStore.append_display_events`, which appends lines and does not touch the manifest. The manifest (and `index.jsonl`) is touched twice per request: once when `chat.send` persists the user message (pre-existing; auto-title reads `message_count`), and once when `request.finished` is pushed. It is never touched per display event. `message_count` is recomputed from `events.jsonl` on every touch.
- `role=tool_start` stays the only instruction to run Tcl. This plan never changes its metadata, never tags it `v: 2`, never persists it, and never replays it from history.
- Line numbers under **Files** are from commit 6f5f937. Plans 02–06 move them. Find each edit by its quoted anchor text; Task 0 prints every anchor.
- The claude_loop change (`_tool_finished_meta(..., late=False)`) is additive. The S7 guards (golden requests, hashes, bridge guard, retry pin) must stay green after every task that touches `claude_loop.py`.

## Review Focus

1. A tokenless (v1) session never receives a single v2 event, not even when it asks for `event_protocol: 2`. Owner P07-T01: `tests/test_events_v2_shapes.py::test_v1_session_unchanged` and `::test_tokenless_cannot_negotiate_v2`.
2. A late `tool.finished` arrives after `request.finished`, or after the next request has started. It must be pushed exactly once, carry the original `request_id` and `call_key`, and land in the display log. Owner P07-T03: `tests/test_tool_finished_fields.py::test_late_after_next_request` (with `::test_late_after_finished`; persistence in P07-T04 `tests/test_display_log.py::test_late_tool_finished_persisted`).
3. The client long-polls with an `after_seq` beyond `last_seq` (a runtime restart or a reset queue). The poll must return at once with the real `last_seq`, never sleep for `wait_ms`. Owner P07-T06: `tests/test_long_poll.py::test_after_seq_ahead_returns_promptly`.
4. A chat log mixes v1 chunks (an M1-plugin request) with v2 events (an M2-plugin request) and must replay without duplicates, and without `tool_start`. Owner P07-T05: `tests/test_event_seq.py::test_mixed_log_replay`.
5. An exception in the `on_event` mapping must not skip `request.finished`, and the run itself continues. Owner P07-T02: `tests/test_request_lifecycle_events.py::test_on_event_crash_still_finishes`.

## File Structure

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `runtime/vmd_ai_runtime/app.py` | modify | T01–T07 | `_wants_v2`, `_EventMapper`, `is_display_event`; negotiation; v2 pushes; worker paths with `request.started`/`request.finished`; error events; late `tool.finished`; display-log persistence; history replay; long-poll; `profiles.*` |
| `runtime/vmd_ai_runtime/constants.py` | modify | T02 | `ACTION_FOR_CODE` |
| `runtime/vmd_ai_runtime/claude_loop.py` | modify | T03 | `_tool_finished_meta(..., late=False)` |
| `runtime/vmd_ai_runtime/store.py` | modify | T04 | message-only counts, recount on touch, `append_display_events`, `touch_manifest`, `recount_messages` |
| `runtime/vmd_ai_runtime/events.py` | modify | T05, T06 | monotonic `seq`, `drop_pending`, trimming, `display_log`, `wait` |
| `runtime/vmd_ai_runtime/protocol.py` | modify | T06, T07 | `wait_ms`, `MAX_WAIT_MS`, `profiles.*` validators |
| `tests/helpers/events_v2.py` | create | T01 | v2 session driver, `MetaScriptedLoop`, `ProductBridge`, `FakePlugin` |
| `tests/helpers/make_event_fixtures.py` | create | T08 | scenario generator and normaliser |
| `tests/test_events_v2_shapes.py` | create | T01 | shapes, v1 unchanged, no double emission |
| `tests/test_request_lifecycle_events.py` | create | T02 | `request.*` on every path, error codes |
| `tests/test_tool_finished_fields.py` | create | T03 | display fields, late `tool.finished` |
| `tests/test_display_log.py` | create | T04 | persistence, sealing, counts |
| `tests/test_event_seq.py` | create | T05 | seq, trim, replay |
| `tests/test_long_poll.py` | create | T06 | long-poll |
| `tests/test_profiles_rpcs.py` | create | T07 | `profiles.*` |
| `tests/test_event_fixtures.py` | create | T08 | regenerate and check the five fixtures |
| `tests/fixtures/events/*.jsonl` | create | T08 | five scenario fixtures |
| `tests/test_launch_token.py` | modify | T01 | plan 02's M1 expectation (`event_protocol` answered 1) becomes 2 |
| `tests/test_store_locks.py` | modify | T04 | plan 03's concurrency test appends messages, not chunks |

---

### Task 0: Pre-flight — confirm plans 01–06 are merged and their interfaces exist

**Files:**
- Create (temporary, never committed): `tests/test_zz_preflight_07.py`

**Interfaces:**
- Consumes: every interface named under "Consumes" in Tasks 1–8 (plans 02–06).
- Produces: the baseline pass count `B` that the "Expected" lines below build on.

- [ ] **Step 1: Cut the branch and record the baselines**

Run:
```bash
git switch main
git log --oneline -1
git switch -c chatvmd-r1-07-m2-events-v2
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -3
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
ls plugin/net.tcl plugin/runtime.tcl plugin/executor.tcl tests/helpers/scripted_runtime.py tests/helpers/app_driver.py tests/helpers/bridge_harness.py
ls tests/fixtures/events 2>&1 | head -1
```
Expected:
- The first pytest line reads `B passed` (possibly with `S skipped`), `0 failed`, and no `xfailed` (plan 04 removed the mark). Write `B` down; every later "Expected" count is relative to it.
- `90 passed`, then `62 passed`.
- The six `ls` paths exist (plans 03, 05 and 06 are merged).
- The last line reads `ls: tests/fixtures/events: No such file or directory`.

- [ ] **Step 2: Write the interface check**

Create `tests/test_zz_preflight_07.py`. It runs under the hermetic conftest.

```python
"""Plan 07 pre-flight: the interfaces plans 02-06 must have produced. Never committed."""
from __future__ import annotations

import inspect

from helpers.app_driver import (TOKEN, InstantBridge, ScriptedLoop, make_token_app, result, send,
                                start, state_of, wait_idle)
from helpers.runtime_fixture import start_token_session
from vmd_ai_runtime import conversation, protocol, provider_catalog
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import (ClaudeLoopError, ClaudeToolLoop, ModelNotFoundError,
                                        ProviderAuthError, ProviderBillingError,
                                        ProviderUnreachableError, _tool_finished_meta)
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.sessions import RequestState, SessionState
from vmd_ai_runtime.settings_store import SettingsError, normalize_provider
from vmd_ai_runtime.store import ChatStore
from vmd_ai_runtime.tool_bridge import VmdToolBridge


def _params(fn):
    return list(inspect.signature(fn).parameters)


def test_plan07_preflight(tmp_path):
    # claude_loop (plans 02, 04, 05)
    assert _params(_tool_finished_meta) == ["call_key", "tool_name", "executor", "result", "duration_ms"]
    for name in ("_on_meta", "_emit", "_vision_enabled", "_call_turn"):
        assert hasattr(ClaudeToolLoop, name), name
    classes = (ProviderUnreachableError, ProviderAuthError, ProviderBillingError, ModelNotFoundError, ClaudeLoopError)
    assert [c.code for c in classes] == ["unreachable", "auth", "billing", "model_not_found", "other"]
    exc = ModelNotFoundError("Model not found: m", hint="ollama pull m", http_status=404)
    assert (str(exc), exc.hint, exc.http_status) == ("Model not found: m", "ollama pull m", 404)

    # RuntimeApp helpers this plan calls or edits (plans 02-05)
    for name in ("_turn_tracker", "_new_loop_for", "_clear_active", "_request_running",
                 "_resume_token_session", "_recorder_meta", "_max_turns_for", "_capabilities_for",
                 "_settings_rpc_error", "_on_late_result", "_tool_timeouts", "_require_auth",
                 "profile_for_session", "_profile_loop_factory", "_bridge_session",
                 "_provider_set_profile", "_system_prompt_for_mode"):
        assert hasattr(RuntimeApp, name), name
    assert _params(RuntimeApp._system_prompt_for_request)[:3] == ["self", "state", "loop"]
    assert _params(RuntimeApp._build_recorder_for_session)[:3] == ["self", "state", "meta"]
    assert _params(RuntimeApp._run_claude_loop_response) == [
        "self", "session_id", "request_id", "prompt", "cancel_event", "prior_messages",
        "loop", "chat_id", "system_prompt"]
    assert _params(RuntimeApp._run_provider_response) == [
        "self", "session_id", "request_id", "prompt", "cancel_event", "prior_messages"]

    # events / store / sessions / protocol / settings (plans 02, 03, 05)
    assert sorted(n for n in vars(EventQueue) if not n.startswith("__")) == ["clear", "last_seq", "poll", "push"]
    for name in ("chat_dir", "lock_root", "_touch_manifest", "_write_manifest", "_append_index_row"):
        assert hasattr(ChatStore(str(tmp_path / "s")), name), name
    assert {"authenticated", "event_protocol", "chat_lock", "lock"} <= set(SessionState.__dataclass_fields__)
    assert {"turn", "started_at"} <= set(RequestState.__dataclass_fields__)
    assert protocol.EVENT_PROTOCOLS == (1, 2)
    assert protocol._PROFILE_NAME_RE.match("qwen-tunnel") and not protocol._PROFILE_NAME_RE.match("../x")
    assert conversation.ALL_EVENTS >= 10 ** 9 and hasattr(conversation, "Appender")
    assert callable(provider_catalog.ollama_show) and callable(provider_catalog.model_capabilities)
    assert hasattr(VmdToolBridge, "post_result") and hasattr(VmdToolBridge, "ack")
    assert issubclass(SettingsError, Exception) and normalize_provider("ollama") == "ollama"

    # Behaviour: M1 still answers display protocol 1, and a run fills every last_* field.
    app = make_token_app(tmp_path)
    assert app.tool_bridge.on_late_result == app._on_late_result
    assert start_token_session(app, TOKEN, event_protocol=2, cwd=str(tmp_path))["event_protocol"] == 1
    app.tool_bridge = InstantBridge()
    loop = ScriptedLoop([("", [{"type": "tool_use", "id": "tc_0", "name": "run_vmd_command",
                                "input": {"command": "mol list"}}]), ("Done.", [])])
    app.claude_loop = loop
    session = start(app, tmp_path)
    sent = result(send(app, session, "hi"))
    wait_idle(app, session)
    for name in ("last_status", "last_turns", "last_tool_calls", "last_final_text_empty",
                 "last_usage", "last_wrapped_up", "last_wrap_up_error"):
        assert hasattr(loop, name), name
    assert (loop.last_status, loop.last_turns, loop.last_tool_calls) == ("complete", 2, 1)
    assert loop.last_usage == {"input_tokens_evaluated": None, "output_tokens": None}
    assert sent["chat_id"] and app.store.exists(sent["chat_id"])
    assert isinstance(state_of(app, session).queue.last_seq, int)
```

- [ ] **Step 3: Run it and print the edit anchors**

Run:
```bash
env -u VMD_AI_PROVIDER python -m pytest tests/test_zz_preflight_07.py -q 2>&1 | tail -2
grep -n '^class RuntimeApp\|from . import conversation\|^import time\|event_protocol=1,\|"user", "message", params\["text"\], {"request_id": request_id}\|if reply.get("accepted") and not reply.get("duplicate"):\|# Persist a tool_result event for transcript history\|def _turn_tracker\|on_event=self._turn_tracker(request)\|def _run_claude_loop_response\|# Background thread: simple provider\|def _run_provider_response\|^    # Helpers\|def _on_late_result\|state.queue.clear()\|"last_seq": last_seq,\|if method == "chat.history.get"\|if method == "chat.events.poll"\|result\["runtime"\] = {"version": RUNTIME_VERSION\|def _provider_set_profile\|raise RpcError("METHOD_NOT_FOUND"' runtime/vmd_ai_runtime/app.py
grep -n '"saved_path": result.get("saved_path"),\|"late": False,\|result: Dict\[str, Any\], duration_ms: float) -> Dict\[str, Any\]:' runtime/vmd_ai_runtime/claude_loop.py
grep -n 'def append_events\|def _touch_manifest\|def _write_manifest' runtime/vmd_ai_runtime/store.py
grep -n 'if method == "chat.events.poll"\|def _as_profile_name\|def validate_rpc_payload\|raise RpcError("METHOD_NOT_FOUND"' runtime/vmd_ai_runtime/protocol.py
grep -n 'CONVERSATION_MODES' runtime/vmd_ai_runtime/constants.py
grep -n 'if not state.authenticated and model and model != loop.model:\|if loop is self._assigned_loop:' runtime/vmd_ai_runtime/app.py
grep -n '"type": "chunk", "text": "x"' tests/test_store_locks.py
grep -n 'assert two\["event_protocol"\] == 1' tests/test_launch_token.py
grep -rn '_turn_tracker' tests/ | head -3
```
Expected:
- The first command prints `1 passed`.
- `app.py` shows each anchor. `state.queue.clear()` appears twice (the tokenless `chat.resume` branch and `_resume_token_session`). `raise RpcError("METHOD_NOT_FOUND"` appears once. `^import time` may print nothing; Task 2 adds it then.
- `claude_loop.py` shows the three `_tool_finished_meta` lines. `"late": False,` appears exactly once.
- `store.py` shows the three `def` lines.
- `protocol.py` shows its four anchors.
- `constants.py` shows `CONVERSATION_MODES = (..., "full")`.
- The model-override grep prints two lines inside `_run_claude_loop_response`: P03-T08's tokenless-only override and its assigned-loop branch. Tasks 1 and 2 keep both.
- The `test_store_locks.py` grep prints one line inside `def touch():`.
- The `test_launch_token.py` grep prints one line.
- The last grep prints nothing: no test refers to `_turn_tracker`.

If any assertion fails or an anchor is missing, stop. The named interface from plans 02–06 is missing or different, and it must be fixed there before this plan starts.

- [ ] **Step 4: Delete the check (it is never committed)**

Run: `rm tests/test_zz_preflight_07.py && git status --short`
Expected: no output.

---

### Task 1: P07-T01 — Negotiate event_protocol 2 and map loop events

**Files:**
- Create: `tests/helpers/events_v2.py`
- Create: `tests/test_events_v2_shapes.py`
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - New module-level `_wants_v2` and `_EventMapper`, inserted before `class RuntimeApp:` (6f5f937: line 38).
  - The `session.start` branch (6f5f937: 191-220; the `event_protocol=1,` argument plan 02 added).
  - The `chat.send` user event (6f5f937: 251-253; plan 03's `user_event = state.queue.push(` statement).
  - The `tool.command_result` branch (6f5f937: 463-516; plan 05's call_key branch and today's `# Persist a tool_result event` block at 502-514).
  - New methods `_make_on_event` and `_push_v2`.
  - `_run_claude_loop_response` (6f5f937: 557-677; replaced whole, as plans 03–05 left it).
  - Plan 03's `_turn_tracker` (deleted).
- Modify: `tests/test_launch_token.py` (plan 02's `test_event_protocol_values`: the answer to a request for 2).

**Interfaces:**
- Consumes: loop on_event items (P02-T08). Also used here: `helpers.app_driver` (`TOKEN`, `Session`, `call`, `result`, `send`, `state_of`, `wait_idle`, `make_token_app`; P03-T04); `ClaudeToolLoop._on_meta` (P02-T05, P04-T03); `LoopOptions.product` (P02-T05); the real `VmdToolBridge`'s `tool.ack`/`tool.command_result` by `call_key` (P05-T01/T02); `RuntimeApp._clear_active`, `_system_prompt_for_request(state, loop)`, `_recorder_meta`, `_build_recorder_for_session(state, meta)` (P03-T04, P04-T06, P05-T10); `RuntimeApp._assigned_loop` and the tokenless-only model override in `_run_claude_loop_response` (P02-T10, P03-T04/T08), which Step 8 keeps.
- Produces:
  - session.start {event_protocol:2} -> event_protocol 2 (token sessions only)
  - RuntimeApp._make_on_event(state: SessionState, request: RequestState) -> Callable[[Dict[str, Any]], None]
  - v2 envelopes carry metadata.request_id and metadata.v = 2
  - (plan additions) `app._wants_v2(state) -> bool`. `app._EventMapper`, the callable that `_make_on_event` returns: attributes `v2`, `request_id`, `chat_id`; method `push(role, event_type, text='', metadata=None) -> Optional[Dict]`. `RuntimeApp._push_v2(state, role, event_type, text, metadata) -> Dict`. A v2 session's user message carries `v: 2`. The v1 `tool_result` event is pushed only to v1 sessions.
  - (test helpers) `tests/helpers/events_v2.py`:
    - Constants `MODEL`, `OLLAMA_URL`, `PROFILE_OPTIONS`.
    - Functions `product_options(**overrides) -> LoopOptions`, `start_v2(app, tmp_path, *, event_protocol=2, token=TOKEN) -> Session`, `poll_all(app, session, after_seq=0) -> List[Dict]`, `kinds(events)`, `of_kind(events, kind) -> List[Dict]`, `tool_block(tool_id, name, **input)`, `run_cmd(tool_id, command, rationale=None)`, `product_result(**overrides)`.
    - Classes: `@dataclass ScriptTurn(text, tool_blocks, reasoning, status, usage, drop_after_text, raise_error, before)`; `MetaScriptedLoop(script, *, wrap_up_text='', model=MODEL, options=None, wrap_up_error=None, **kw)` with `.calls`; `ProductBridge(results=None)` with `.calls`; `FakePlugin(app, session, answer=None)` (a context manager) with `.events`, `.held`, `.post(call_key, **params)`, `.wait_held(count=1, timeout=5.0)`, `.wait_for(predicate, timeout=5.0)`.

- [ ] **Step 1: Write the plan's test helper**

Create `tests/helpers/events_v2.py`:

```python
"""Plan 07 test helpers: v2 sessions, a meta-scripted model and product-shaped bridges.

* start_v2 / poll_all / kinds / of_kind drive a RuntimeApp in process.
* ScriptTurn + MetaScriptedLoop: a ClaudeToolLoop whose model turns come from a
  script. A turn can stream status, reasoning and usage through the loop's own
  _on_meta path (exactly as the streamers do), drop the stream once
  (turn_retry), block on a callback, or raise.
* ProductBridge / product_result: a supports_call_meta bridge that answers with
  the full product result dict (plan 05) without any plugin.
* FakePlugin plays executor.tcl against the real VmdToolBridge over the
  in-process RPC: it acks every tool_start and posts tool.command_result by
  call_key, or holds the call (a long VMD command) for the test to post later.
"""
from __future__ import annotations

import copy
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers.app_driver import TOKEN, Session, call, result
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions

MODEL = "qwen3.8:27b"
OLLAMA_URL = "http://ollama.test"
PROFILE_OPTIONS: Dict[str, Any] = {"supports_vision": True, "think": True}


def product_options(**overrides: Any) -> LoopOptions:
    """LoopOptions.product for an Ollama profile; vision and think are on unless overridden."""
    options = dict(PROFILE_OPTIONS)
    options.update(overrides)
    return LoopOptions.product(
        {"provider": "ollama", "base_url": OLLAMA_URL, "model": MODEL, "options": options})


def start_v2(app, tmp_path: Path, *, event_protocol: int = 2, token: str = TOKEN) -> Session:
    """session.start with cwd <tmp_path>/work; ``token=""`` starts a tokenless session."""
    work = Path(tmp_path) / "work"
    work.mkdir(parents=True, exist_ok=True)
    params: Dict[str, Any] = {"cwd": str(work), "event_protocol": event_protocol}
    if token:
        params["launch_token"] = token
    return Session(result(call(app, "session.start", params)))


def poll_all(app, session: Session, after_seq: int = 0) -> List[Dict[str, Any]]:
    """Every queued event after ``after_seq`` (follows has_more)."""
    events: List[Dict[str, Any]] = []
    while True:
        batch = result(call(app, "chat.events.poll", {"after_seq": after_seq, "limit": 500}, session))
        events.extend(batch["events"])
        after_seq = batch["last_seq"]
        if not batch["has_more"]:
            return events


def kinds(events: List[Dict[str, Any]]) -> List[Tuple[str, str, Optional[str]]]:
    """(role, type, metadata.kind) per event."""
    return [(e["role"], e["type"], (e.get("metadata") or {}).get("kind")) for e in events]


def of_kind(events: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    """The metadata of every event whose metadata.kind is ``kind``."""
    return [e["metadata"] for e in events if (e.get("metadata") or {}).get("kind") == kind]


def tool_block(tool_id: str, name: str, **tool_input: Any) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": dict(tool_input)}


def run_cmd(tool_id: str, command: str, rationale: Optional[str] = None) -> Dict[str, Any]:
    tool_input: Dict[str, Any] = {"command": command}
    if rationale:
        tool_input["rationale"] = rationale
    return tool_block(tool_id, "run_vmd_command", **tool_input)


def product_result(**overrides: Any) -> Dict[str, Any]:
    """The product bridge's result dict (plan 05) with every key present."""
    out: Dict[str, Any] = {
        "ok": True, "output": "", "error": "", "executed": "yes", "truncated": False,
        "duration_ms": 0, "statements": None, "blocked": None, "output_path": None,
        "output_bytes": None, "image": None, "saved_path": None, "applied_text": "",
    }
    out.update(overrides)
    if out["output_bytes"] is None:
        out["output_bytes"] = len(str(out["output"]).encode("utf-8"))
    return out


@dataclass
class ScriptTurn:
    """One scripted model call. It streams status, then reasoning, then text."""

    text: str = ""
    tool_blocks: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    status: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None
    drop_after_text: bool = False
    raise_error: Optional[BaseException] = None
    before: Optional[Callable[[], Any]] = None


def _pieces(text: str) -> List[str]:
    """Streamed chunks that join back to ``text`` (a word plus its trailing space)."""
    return re.findall(r"\S+\s*|\s+", text)


class MetaScriptedLoop(ClaudeToolLoop):
    """A product-configured ClaudeToolLoop whose model calls come from a script.

    ``_call`` replaces the streamers, so no request leaves the process. After
    the script ends every call answers ``Done.``. C4's wrap-up call (the loop
    sets ``_tool_mode = "none"`` for it) answers ``wrap_up_text``, or raises
    ``wrap_up_error`` when one is given.
    """

    def __init__(self, script: List[ScriptTurn], *, wrap_up_text: str = "", model: str = MODEL,
                 options: Optional[LoopOptions] = None,
                 wrap_up_error: Optional[BaseException] = None, **kw: Any) -> None:
        kw.setdefault("provider_name", "ollama")
        kw.setdefault("api_key", OLLAMA_URL)
        super().__init__(model=model, options=options if options is not None else product_options(), **kw)
        self.script: List[ScriptTurn] = list(script)
        self.wrap_up_text = wrap_up_text
        self.wrap_up_error = wrap_up_error
        self.calls: List[List[Dict[str, Any]]] = []
        self._script_lock = threading.Lock()

    def _call(self, messages, system_prompt, on_text, should_cancel):
        with self._script_lock:
            self.calls.append(copy.deepcopy(messages))
            if getattr(self, "_tool_mode", None) == "none":
                if self.wrap_up_error is not None:
                    raise self.wrap_up_error
                turn = ScriptTurn(text=self.wrap_up_text)
            elif self.script:
                turn = self.script.pop(0)
            else:
                turn = ScriptTurn(text="Done.")
        if turn.before is not None:
            turn.before()
        if turn.raise_error is not None:
            raise turn.raise_error
        if turn.status is not None:
            self._on_meta(dict(turn.status, kind="status"))
        for piece in _pieces(turn.reasoning):
            self._on_meta({"kind": "reasoning", "text": piece})
        for piece in _pieces(turn.text):
            on_text(piece)
        if turn.drop_after_text:
            raise ConnectionResetError(54, "Connection reset by peer")
        if turn.usage is not None:
            self._on_meta(dict(turn.usage, kind="usage"))
        return turn.text, copy.deepcopy(turn.tool_blocks)


class ProductBridge:
    """Answers tool calls with product result dicts; opts in to call metadata on its class.

    Each item of ``results`` is a result dict, or a callable that takes the
    execute_tool keywords and returns one (it may block or raise).
    """

    supports_call_meta = True

    def __init__(self, results: Optional[List[Any]] = None) -> None:
        self.results: List[Any] = list(results or [])
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def execute_tool(self, **kwargs: Any) -> Dict[str, Any]:
        with self._lock:
            self.calls.append({k: kwargs.get(k) for k in ("tool_name", "tool_input", "call_key", "request_id")})
            item = self.results.pop(0) if self.results else product_result(output="ok")
        if callable(item):
            item = item(kwargs)
        return copy.deepcopy(item)


class FakePlugin:
    """Plays executor.tcl for one session over the in-process RPC.

    ``answer(meta)`` gets the tool_start metadata and returns the
    tool.command_result params (without call_key), or None to ack the call
    and hold it (a long VMD command the test answers later with ``post``).
    Every event the plugin polls is kept in ``events``.
    """

    def __init__(self, app, session: Session,
                 answer: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> None:
        self.app = app
        self.session = session
        self.answer = answer if answer is not None else (lambda meta: {"ok": True, "output": "ok"})
        self.events: List[Dict[str, Any]] = []
        self.held: List[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "FakePlugin":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        after = 0
        while not self._stop.is_set():
            reply = call(self.app, "chat.events.poll", {"after_seq": after, "limit": 200}, self.session)
            batch = reply.get("result") or {"events": [], "last_seq": after}
            for event in batch["events"]:
                self.events.append(event)
                if event.get("role") == "tool_start":
                    self._execute(dict(event.get("metadata") or {}))
            after = batch["last_seq"]
            if not batch["events"]:
                time.sleep(0.01)

    def _execute(self, meta: Dict[str, Any]) -> None:
        call_key = str(meta.get("call_key") or "")
        call(self.app, "tool.ack", {"call_key": call_key}, self.session)
        params = self.answer(meta)
        if params is None:
            self.held.append(call_key)
            return
        body = dict(params)
        body["call_key"] = call_key
        call(self.app, "tool.command_result", body, self.session)

    def post(self, call_key: str, **params: Any) -> Dict[str, Any]:
        """Post a result for a held call; returns {accepted, late, duplicate}."""
        body = dict(params)
        body["call_key"] = call_key
        return result(call(self.app, "tool.command_result", body, self.session))

    def wait_held(self, count: int = 1, timeout: float = 5.0) -> List[str]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.held) >= count:
                return list(self.held[:count])
            time.sleep(0.01)
        raise AssertionError("the plugin never held %d call(s)" % count)

    def wait_for(self, predicate: Callable[[Dict[str, Any]], bool], timeout: float = 5.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in list(self.events):
                if predicate(event):
                    return event
            time.sleep(0.01)
        raise AssertionError("the plugin never saw the expected event")
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_events_v2_shapes.py`:

```python
"""P07-T01: event_protocol 2 negotiation and the v2 mapping of loop events (§2a, §2c)."""
from __future__ import annotations

import pytest

from helpers.app_driver import TOKEN, make_token_app, result, send, state_of, wait_idle
from helpers.events_v2 import (MODEL, FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds,
                               of_kind, poll_all, product_result, run_cmd, start_v2)

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}


def _script():
    return [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD], reasoning="Load it first.",
                   status={"phase": "loading_model", "message": "Loading qwen3.8:27b"}, usage=USAGE),
        ScriptTurn(text="Partial", drop_after_text=True),   # turn 2 drops once: turn.retry
        ScriptTurn(text="Done.", usage=USAGE),
    ]


def _run(tmp_path, *, event_protocol=2, token=TOKEN):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(_script())
    app.tool_bridge = ProductBridge([product_result(output="0")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol, token=token)
    mode = "full" if token else "local_first"
    # model=MODEL keeps a tokenless session's model override (P03-T04/T08) from
    # swapping the scripted loop for a real one; token sessions ignore it.
    reply = result(send(app, session, "load 1hck", conversation_mode=mode, model=MODEL))
    wait_idle(app, session)
    return app, session, reply, poll_all(app, session)


def test_shape_per_kind(tmp_path):
    _app, session, reply, events = _run(tmp_path)
    rid = reply["request_id"]
    assert session.result["event_protocol"] == 2
    assert all(e["metadata"]["v"] == 2 for e in events if e["metadata"].get("request_id") == rid)

    assert of_kind(events, "turn.started") == [
        {"kind": "turn.started", "request_id": rid, "turn": 1, "v": 2},
        {"kind": "turn.started", "request_id": rid, "turn": 2, "v": 2},
    ]
    reasoning = [e for e in events if e["role"] == "reasoning" and e["type"] == "chunk"]
    assert "".join(e["text"] for e in reasoning) == "Load it first."
    assert reasoning[0]["metadata"] == {"request_id": rid, "turn": 1, "v": 2}
    chunk = next(e for e in events if e["role"] == "assistant" and e["type"] == "chunk")
    assert chunk["metadata"] == {"request_id": rid, "turn": 1, "v": 2}
    sealed = [(e["text"], e["metadata"]) for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert sealed == [
        ("Loading.", {"request_id": rid, "turn": 1, "final": False, "v": 2}),
        ("Done.", {"request_id": rid, "turn": 2, "final": True, "v": 2}),
    ]

    started, = of_kind(events, "tool.started")
    assert set(started) == {"kind", "request_id", "turn", "call_key", "tool_call_id", "tool_name",
                            "executor", "origin", "input", "v"}
    assert (started["tool_call_id"], started["tool_name"], started["executor"], started["origin"],
            started["input"]) == ("tc_1", "run_vmd_command", "tcl", "model", {"command": "mol new 1hck.pdb"})
    finished, = of_kind(events, "tool.finished")
    assert set(finished) == {"kind", "request_id", "turn", "call_key", "tool_name", "executor", "ok",
                             "executed", "output", "error", "truncated", "duration_ms", "statements",
                             "blocked", "output_path", "output_bytes", "image", "saved_path", "late", "v"}
    assert finished["call_key"] == started["call_key"]
    assert (finished["ok"], finished["executed"], finished["output"], finished["late"]) == (True, "yes", "0", False)

    usage = of_kind(events, "usage")
    assert usage[0] == dict(USAGE, kind="usage", request_id=rid, turn=1, v=2)
    assert of_kind(events, "status") == [{"kind": "status", "phase": "loading_model",
                                          "message": "Loading qwen3.8:27b", "request_id": rid,
                                          "turn": 1, "v": 2}]
    assert of_kind(events, "turn.retry") == [{"kind": "turn.retry", "reason": "stream dropped",
                                              "request_id": rid, "turn": 2, "v": 2}]


@pytest.mark.parametrize("token", [TOKEN, ""], ids=["token_v1", "tokenless"])
def test_v1_session_unchanged(tmp_path, token):
    """Review focus 1: a v1 session sees exactly today's events, and none tagged v2."""
    _app, _session, _reply, events = _run(tmp_path, event_protocol=1, token=token)
    assert all("v" not in e["metadata"] and "kind" not in e["metadata"] for e in events)
    assert not [e for e in events if e["role"] == "reasoning" or e["type"] == "state"]
    assert kinds(events) == ([("system", "lifecycle", None), ("system", "message", None),
                              ("user", "message", None)]
                             + [("assistant", "chunk", None)] * 3
                             + [("assistant", "message", None)])
    assert "".join(e["text"] for e in events if e["type"] == "chunk") == "Loading.PartialDone."
    assert events[-1]["text"] == "Done."


def test_tokenless_cannot_negotiate_v2(tmp_path):
    app, session, _reply, events = _run(tmp_path, event_protocol=2, token="")
    assert "event_protocol" not in session.result          # exactly today's session.start fields
    assert state_of(app, session).event_protocol == 1
    assert all("v" not in e["metadata"] for e in events)
    assert not [e for e in events if e["type"] == "state"]


def test_no_double_emission(tmp_path):
    app, _session, reply, events = _run(tmp_path)
    for event in events:
        if event["role"] == "assistant":
            assert event["metadata"].get("v") == 2 and "turn" in event["metadata"], event
    per_turn = {}
    for event in events:
        if event["role"] == "assistant" and event["type"] == "chunk":
            per_turn.setdefault(event["metadata"]["turn"], []).append(event["text"])
    assert {turn: "".join(parts) for turn, parts in per_turn.items()} == {1: "Loading.", 2: "PartialDone."}
    assert [e["metadata"]["turn"] for e in events
            if e["role"] == "assistant" and e["type"] == "message"] == [1, 2]
    assert not [e for e in events if e["type"] == "lifecycle" and e["text"] == "cancelled"]
    stored = app.store.read_events(reply["chat_id"], limit=10 ** 9)
    assert not [e for e in stored if e["role"] == "assistant" and "v" not in e["metadata"]]


@pytest.mark.parametrize("event_protocol,expect_tool_result", [(2, False), (1, True)])
def test_no_tool_result_for_v2(tmp_path, event_protocol, expect_tool_result):
    app = make_token_app(tmp_path)                          # the real VmdToolBridge
    app.claude_loop = MetaScriptedLoop([ScriptTurn(tool_blocks=[LOAD]), ScriptTurn(text="Done.")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    answer = lambda meta: {"ok": True, "output": "0", "statements_total": 1, "statements_applied": 1}
    with FakePlugin(app, session, answer=answer):
        result(send(app, session, "load 1hck"))
        wait_idle(app, session)
    events = poll_all(app, session)
    assert bool([e for e in events if e["role"] == "tool_result"]) is expect_tool_result
    if event_protocol == 2:
        finished, = of_kind(events, "tool.finished")
        assert (finished["ok"], finished["output"], finished["statements"]) == (
            True, "0", {"total": 1, "applied": 1, "failed": None})
```

In `tests/test_launch_token.py`, inside `test_event_protocol_values`, replace:

```python
    # The M1 runtime speaks display protocol 1 only; plan 07 negotiates 2.
    two = start_token_session(app, TOKEN, event_protocol=2, cwd=str(tmp_path))
    assert two["event_protocol"] == 1
```

with:

```python
    # Plan 07 (M2): a token session that asks for display protocol 2 gets it.
    two = start_token_session(app, TOKEN, event_protocol=2, cwd=str(tmp_path))
    assert two["event_protocol"] == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_events_v2_shapes.py tests/test_launch_token.py -q 2>&1 | tail -8`
Expected: `4 failed`, the rest passed. Why each one fails, against the M1 runtime:
- `test_shape_per_kind` fails with `assert 1 == 2`: session.start still answers `event_protocol` 1.
- `test_no_double_emission` fails because the assistant chunks carry no `v`.
- `test_no_tool_result_for_v2[2-False]` fails because a `tool_result` event is still pushed.
- `test_event_protocol_values` fails with `assert 1 == 2`.

`test_v1_session_unchanged[token_v1]`, `test_v1_session_unchanged[tokenless]`, `test_tokenless_cannot_negotiate_v2` and `test_no_tool_result_for_v2[1-True]` already pass. They pin today's v1 behaviour.

- [ ] **Step 4: Add the per-request event sink to `runtime/vmd_ai_runtime/app.py`**

Insert directly before the line `class RuntimeApp:`:

```python
def _wants_v2(state: Any) -> bool:
    """True when this session negotiated the v2 display events (§2c).

    Only a token-authenticated session.start can ask for event_protocol 2,
    so a tokenless (v1) session never gets here.
    """
    try:
        return int(getattr(state, "event_protocol", 1) or 1) >= 2
    except (TypeError, ValueError):
        return False


class _EventMapper:
    """The ``ctx.on_event`` sink of one request (§2a Legacy callbacks, §2c).

    Every loop item keeps ``RequestState.turn`` current for runtime.info.
    For a v2 session the item also becomes a queue event (``push``); for a
    v1 session it is dropped, because v1 events come from the legacy
    callbacks. A failure here is logged and never reaches the loop.
    """

    def __init__(self, app: "RuntimeApp", state: "SessionState", request: "RequestState") -> None:
        self.app = app
        self.state = state
        self.request = request
        self.request_id = str(request.request_id)
        self.chat_id: Optional[str] = state.chat_id
        self.v2 = _wants_v2(state)

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
        if self.v2:
            self.push(str(item.get("role") or ""), str(item.get("type") or ""),
                      str(item.get("text") or ""), metadata)

    def push(self, role: str, event_type: str, text: str = "",
             metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Push one v2 event of this request; does nothing for a v1 session."""
        if not self.v2:
            return None
        meta = dict(metadata or {})
        meta.setdefault("request_id", self.request_id)
        return self.app._push_v2(self.state, role, event_type, text, meta)


```

(`Any`, `Dict` and `Optional` are already imported from `typing` by plans 02–05.)

- [ ] **Step 5: Negotiate `event_protocol` in `session.start`**

In the `session.start` branch, replace:

```python
                # M1 speaks display protocol 1 only; plan 07 negotiates 2.
                event_protocol=1,
```

with:

```python
                # §2c: a token session may negotiate display protocol 2; a
                # tokenless session always gets today's v1 events.
                event_protocol=int(params.get("event_protocol") or 1) if authenticated else 1,
```

(`result["event_protocol"] = state.event_protocol`, which plan 02 added to the token-session result, now reports 2.)

- [ ] **Step 6: Tag the v2 user message, and keep `tool_result` for v1 only**

In the `chat.send` branch, replace:

```python
                user_event = state.queue.push(
                    "user", "message", params["text"], {"request_id": request_id}
                )
```

with:

```python
                if _wants_v2(state):
                    # A v2 display event (§2c): _push_v2 adds v: 2.
                    user_event = self._push_v2(
                        state, "user", "message", params["text"], {"request_id": request_id}
                    )
                else:
                    user_event = state.queue.push(
                        "user", "message", params["text"], {"request_id": request_id}
                    )
```

In the `tool.command_result` branch (plan 05's call_key path), replace:

```python
                if reply.get("accepted") and not reply.get("duplicate"):
                    # v1 transcript entry, as for tool_call_id results.
```

with:

```python
                if reply.get("accepted") and not reply.get("duplicate") and not _wants_v2(state):
                    # v1 transcript entry, as for tool_call_id results. A v2
                    # session gets tool.finished from the loop instead (§2c).
```

Further down, in the same branch (today's `tool_call_id` path), replace:

```python
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
```

with:

```python
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
```

- [ ] **Step 7: Add `_make_on_event` and `_push_v2`**

Insert directly before the line `    def _run_claude_loop_response(`:

```python
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

```

- [ ] **Step 8: Route the worker through the sink; make legacy callbacks no-ops for v2**

Replace the whole `_run_claude_loop_response` method, from its `    def _run_claude_loop_response(` line through the last line before the `    # ------------------------------------------------------------------` banner that precedes `    # Background thread: simple provider (mock / fallback)`, with:

```python
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
        The loop's on_event items go to _make_on_event: a v2 session gets
        them as queue events and the legacy callbacks below do nothing; a v1
        session keeps today's chunk/message/error events (§2a, §2c).
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
        chunk_events: List[Dict[str, Any]] = []
        events_to_persist: List[Dict[str, Any]] = []

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
            loop.recorder = self._build_recorder_for_session(state, meta)
            messages_out = None
            if getattr(state, "authenticated", False) and chat_id:
                messages_out = conversation.Appender(self.store.chat_dir(chat_id), request_id)
            ctx = RunContext(request_id=request_id, chat_id=chat_id or "",
                             on_event=mapper, messages_out=messages_out)
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
            events_to_persist.append(state.queue.push(
                "error", "message", f"Agent error: {exc}",
                {"request_id": request_id, "provider": self.provider_name},
            ))
        except Exception as exc:
            events_to_persist.append(state.queue.push(
                "error", "message", f"Unexpected error: {exc}", {"request_id": request_id},
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
            if events_to_persist and chat_id:
                self.store.append_events(chat_id, events_to_persist)
            self._clear_active(state, request_id)

```

This version still pushes v1-shaped error events for v2 sessions. Task 2 replaces them with v2 error events and adds `request.started`/`request.finished`.

Everything plans 03–05 put in this method is kept, so v1 sessions see no change: the early return when `loop` is None (P03-T04), the tokenless per-session model override (P03-T04, limited to tokenless sessions by P03-T08; plan 02's `test_per_request_loop_gets_wiki_store` depends on it), the messages.jsonl Appender (P03-T04), `_system_prompt_for_request(state, loop)` (P04-T06), the recorder provenance `meta` (P05-T10), and `provider: self.provider_name` on the v1 `Agent error:` event. The only changes are `on_event=mapper` in place of `self._turn_tracker(request)`, the v2 guards on `on_chunk` and the final events, and the system prompt and recorder being built inside the `try` (so Task 2 can report their failures in `request.finished`).

- [ ] **Step 9: Delete plan 03's `_turn_tracker`**

Delete this whole method (plan 03, P03-T09); `_EventMapper` now tracks the turn for every session:

```python
    @staticmethod
    def _turn_tracker(request) -> Callable[[Dict[str, Any]], None]:
        """on_event for v1 sessions: keeps RequestState.turn current for runtime.info.

        v1 sessions get no queue events from on_event (§2a Legacy callbacks);
        P07-T01 replaces this with _make_on_event for v2 sessions.
        """
        def on_event(item: Dict[str, Any]) -> None:
            metadata = item.get("metadata") or {}
            if request is not None and metadata.get("kind") == "turn.started":
                try:
                    request.turn = int(metadata.get("turn") or 0)
                except (TypeError, ValueError):
                    pass
        return on_event
```

Run: `grep -n "_turn_tracker" runtime/vmd_ai_runtime/app.py`
Expected: no output.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_events_v2_shapes.py tests/test_launch_token.py tests/test_runtime_info_rpcs.py tests/test_memory_integration.py tests/test_tool_bridge_results.py tests/test_loop_factory.py tests/test_profile_loop_factory.py -q 2>&1 | tail -2`
Expected: all passed, 0 failed. `test_runtime_info_rpcs.py::test_active_request_reported` still sees `turn >= 1`, because `_EventMapper` tracks it now. Plan 02's `test_loop_factory.py::test_per_request_loop_gets_wiki_store` and plan 03's `test_profile_loop_factory.py::test_token_send_ignores_model` still pass, because the tokenless-only model override is kept.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+7 passed`, 0 failed.

- [ ] **Step 11: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py tests/helpers/events_v2.py tests/test_events_v2_shapes.py tests/test_launch_token.py
git commit -m "feat(runtime): negotiate event_protocol 2 and map loop events to v2 (P07-T01)

A token session that asks for event_protocol 2 gets it; tokenless
sessions stay on v1. Each request's on_event sink (_EventMapper) tracks
the turn and, for v2 sessions, pushes every loop item as a queue event
tagged v: 2 with its request_id. Legacy callbacks are no-ops for v2, and
the v1 tool_result event is no longer pushed to v2 sessions.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: P07-T02 — request.started/request.finished on every path and error events

**Files:**
- Create: `tests/test_request_lifecycle_events.py`
- Modify: `runtime/vmd_ai_runtime/constants.py`: append `ACTION_FOR_CODE` at the end of the file (6f5f937: after line 36).
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - Imports: `import time`, and `ACTION_FOR_CODE` from `.constants`.
  - `_EventMapper` (replaced whole; Task 1 version).
  - `_run_claude_loop_response` (replaced whole; Task 1 version).
  - `_run_provider_response` (6f5f937: 683-741, replaced whole).
  - New methods `_request_started_meta`, `_request_finished_meta`, `_error_meta`.

**Interfaces:**
- Consumes: last_status, last_turns, last_tool_calls, last_final_text_empty, last_usage, last_wrapped_up (P02-T07, P04-T03, P05-T09). Also used: `ClaudeToolLoop.last_wrap_up_error` (P05-T09 addition); `ClaudeLoopError.code/.hint/.http_status` and its four subclasses (P02-T05); `RuntimeApp._max_turns_for(loop)` (P03-T09); `RunRecorder.current_task_dir` (existing); `_EventMapper`, `_push_v2`, `_wants_v2` (Task 1); `helpers.events_v2` (Task 1).
- Produces:
  - request.started {kind, request_id, chat_id, provider, model, max_turns, vision, think}
  - request.finished {kind, request_id, status, wrapped_up, turns, tool_calls, final_text_empty, duration_ms, usage, error, run_dir}
  - constants.ACTION_FOR_CODE
  - error event metadata {request_id, code, http_status, hint, action}
  - (plan additions)
    - `RuntimeApp._request_started_meta(loop, request_id, chat_id) -> Dict`.
    - `RuntimeApp._request_finished_meta(loop, mapper, *, entered_run, failure_text, started) -> Dict` (staticmethod).
    - `RuntimeApp._error_meta(exc) -> Dict` (staticmethod).
    - `_EventMapper.recorder` and `.run_dir`: the recorder's task directory, captured at the first loop event.
    - Field values:
      - `request.finished.error` is the error event's text (`str(exc)` for a `ClaudeLoopError`, `"Unexpected error: …"` otherwise), or `last_wrap_up_error` (C4), or null.
      - `usage` is `{input_tokens_evaluated, output_tokens}`, with null for any value the provider did not report.
      - The mock path reports `max_turns: 1`, `vision: false`, `think: null` and `turns: 1`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_request_lifecycle_events.py`:

```python
"""P07-T02: request.started/request.finished on every worker path, and v2 error events (§2c, §2f)."""
from __future__ import annotations

import os

import pytest

from helpers.app_driver import error_code, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MODEL, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds, of_kind,
                               poll_all, product_result, run_cmd, start_v2)
from vmd_ai_runtime.claude_loop import (ClaudeLoopError, ModelNotFoundError, ProviderAuthError,
                                        ProviderBillingError, ProviderUnreachableError)
from vmd_ai_runtime.constants import ACTION_FOR_CODE
from vmd_ai_runtime.settings_store import SettingsStore

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}
NO_USAGE = {"input_tokens_evaluated": None, "output_tokens": None}
FINISHED_KEYS = {"kind", "request_id", "status", "wrapped_up", "turns", "tool_calls", "final_text_empty",
                 "duration_ms", "usage", "error", "run_dir", "v"}


def _app(tmp_path, script, results=None):
    app = make_token_app(tmp_path)
    loop = MetaScriptedLoop(script)
    app.claude_loop = loop
    app.tool_bridge = ProductBridge(results if results is not None else [product_result(output="0")])
    return app, loop


def _send(app, tmp_path, text="load 1hck"):
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, text))
    wait_idle(app, session)
    return reply, poll_all(app, session)


def _at(events, kind):
    return [i for i, e in enumerate(events) if (e.get("metadata") or {}).get("kind") == kind]


def test_complete(tmp_path):
    app, _loop = _app(tmp_path, [ScriptTurn(text="Loading.", tool_blocks=[LOAD], usage=USAGE),
                                 ScriptTurn(text="Done.", usage=USAGE)])
    reply, events = _send(app, tmp_path)
    rid = reply["request_id"]
    started, = of_kind(events, "request.started")
    assert started == {"kind": "request.started", "request_id": rid, "chat_id": reply["chat_id"],
                       "provider": "ollama", "model": MODEL, "max_turns": 28, "vision": True,
                       "think": True, "v": 2}
    finished, = of_kind(events, "request.finished")
    assert set(finished) == FINISHED_KEYS
    assert (finished["request_id"], finished["status"], finished["wrapped_up"], finished["turns"],
            finished["tool_calls"], finished["final_text_empty"], finished["error"]) == (
        rid, "complete", False, 2, 1, False, None)
    assert finished["usage"] == {"input_tokens_evaluated": 240, "output_tokens": 18}
    assert isinstance(finished["duration_ms"], int) and finished["duration_ms"] >= 0
    runs = os.path.realpath(str(tmp_path / "work" / ".vmdai_runs"))
    assert finished["run_dir"].startswith(runs + os.sep)
    user_at = next(i for i, e in enumerate(events) if e["role"] == "user")
    assert _at(events, "request.started") == [user_at + 1]
    assert _at(events, "request.finished") == [len(events) - 1]


def test_cancelled(tmp_path):
    def stop_then_answer(kwargs):
        kwargs["cancel_event"].set()          # the user pressed Stop while the tool ran
        return product_result(output="0")

    app, _loop = _app(tmp_path, [ScriptTurn(tool_blocks=[LOAD]), ScriptTurn(text="never sent")],
                      [stop_then_answer])
    _reply, events = _send(app, tmp_path)
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["turns"], finished["tool_calls"], finished["final_text_empty"],
            finished["error"]) == ("cancelled", 1, 1, True, None)
    assert not [e for e in events if e["type"] == "lifecycle" and e["text"] == "cancelled"]
    assert _at(events, "request.finished") == [len(events) - 1]


ERRORS = [
    (lambda: ProviderUnreachableError("Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?",
                                      hint="Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"),
     "unreachable", None, "test_connection"),
    (lambda: ProviderAuthError("HTTP 401 from the provider: invalid x-api-key", http_status=401),
     "auth", 401, "open_settings"),
    (lambda: ProviderBillingError("Your credit balance is too low to access the Anthropic API.",
                                  http_status=400),
     "billing", 400, "switch_profile"),
    (lambda: ModelNotFoundError("Model not found: qwen3.8:27b", hint="ollama pull qwen3.8:27b", http_status=404),
     "model_not_found", 404, "choose_model"),
    (lambda: ClaudeLoopError("stream failed: HTTP 500", http_status=500), "other", 500, "open_log"),
]


@pytest.mark.parametrize("make_exc,code,http_status,action", ERRORS, ids=[e[1] for e in ERRORS])
def test_error_codes_and_actions(tmp_path, make_exc, code, http_status, action):
    exc = make_exc()
    app, _loop = _app(tmp_path, [ScriptTurn(raise_error=exc)])
    reply, events = _send(app, tmp_path)
    errors = [e for e in events if e["role"] == "error"]
    assert len(errors) == 1
    assert (errors[0]["type"], errors[0]["text"]) == ("message", str(exc))
    assert errors[0]["metadata"] == {"request_id": reply["request_id"], "code": code,
                                     "http_status": http_status, "hint": exc.hint,
                                     "action": action, "v": 2}
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["error"], finished["turns"], finished["tool_calls"]) == (
        "error", str(exc), 1, 0)
    assert events.index(errors[0]) < _at(events, "request.finished")[0]
    assert not [e for e in events if e["text"].startswith("Agent error:")]


def test_action_for_code_catalogue():
    assert ACTION_FOR_CODE == {"unreachable": "test_connection", "auth": "open_settings",
                               "billing": "switch_profile", "model_not_found": "choose_model",
                               "other": "open_log"}


def test_unexpected_exception(tmp_path, monkeypatch):
    app, loop = _app(tmp_path, [ScriptTurn(text="unused")])

    def boom(**kwargs):
        raise ValueError("loop exploded")

    monkeypatch.setattr(loop, "run", boom)
    reply, events = _send(app, tmp_path)
    error, = [e for e in events if e["role"] == "error"]
    assert error["text"] == "Unexpected error: loop exploded"
    assert error["metadata"] == {"request_id": reply["request_id"], "code": "other", "http_status": None,
                                 "hint": "", "action": "open_log", "v": 2}
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["error"]) == ("error", "Unexpected error: loop exploded")


def test_mock_path(tmp_path):
    app = make_token_app(tmp_path)                 # mock provider, no loop, no settings store
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, "hello"))
    wait_idle(app, session)
    events = poll_all(app, session)
    rid = reply["request_id"]
    started, = of_kind(events, "request.started")
    assert started == {"kind": "request.started", "request_id": rid, "chat_id": reply["chat_id"],
                       "provider": "mock", "model": "anthropic/claude-sonnet-4.6", "max_turns": 1,
                       "vision": False, "think": None, "v": 2}
    assert of_kind(events, "turn.started") == [{"kind": "turn.started", "request_id": rid, "turn": 1, "v": 2}]
    chunks = [e for e in events if e["type"] == "chunk"]
    assert chunks and all(e["metadata"] == {"request_id": rid, "turn": 1, "v": 2} for e in chunks)
    sealed = [(e["text"], e["metadata"]) for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert sealed == [("Mock assistant response to: hello",
                       {"request_id": rid, "turn": 1, "final": True, "v": 2})]
    finished, = of_kind(events, "request.finished")
    assert {k: finished[k] for k in ("status", "wrapped_up", "turns", "tool_calls", "final_text_empty",
                                     "usage", "error", "run_dir")} == {
        "status": "complete", "wrapped_up": False, "turns": 1, "tool_calls": 0,
        "final_text_empty": False, "usage": NO_USAGE, "error": None, "run_dir": None}
    assert _at(events, "request.finished") == [len(events) - 1]


def test_prerun_failure(tmp_path, monkeypatch):
    app, loop = _app(tmp_path, [ScriptTurn(text="never")])

    def boom(state, meta=None):
        raise RuntimeError("recorder exploded")

    monkeypatch.setattr(app, "_build_recorder_for_session", boom)
    _reply, events = _send(app, tmp_path)
    assert loop.calls == []                        # loop.run was never reached
    assert [k[2] for k in kinds(events) if k[2] in ("request.started", "request.finished")] == [
        "request.started", "request.finished"]
    error, = [e for e in events if e["role"] == "error"]
    assert (error["text"], error["metadata"]["code"]) == ("Unexpected error: recorder exploded", "other")
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["turns"], finished["tool_calls"], finished["final_text_empty"],
            finished["usage"], finished["error"], finished["run_dir"]) == (
        "error", 0, 0, True, NO_USAGE, "Unexpected error: recorder exploded", None)


def test_no_model_has_no_finished(tmp_path):
    store = SettingsStore()
    store.patch({"max_turns": 28})                 # settings.json exists and holds no profile
    app = make_token_app(tmp_path, settings_store=store)
    session = start_v2(app, tmp_path)
    assert error_code(send(app, session, "hello")) == "NO_MODEL"
    events = poll_all(app, session)
    assert not [e for e in events if (e["metadata"] or {}).get("kind") in ("request.started", "request.finished")]
    assert not [e for e in events if e["role"] == "user"]


def test_stuck_wrap_up_error_is_message_not_card(tmp_path):
    """C4: a failed wrap-up leaves status stuck, wrapped_up false and its message in error; no error card."""
    error = 'mol modcolor: invalid coloring method "ResidueType"'
    fail = product_result(ok=False, error=error)
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(
        [ScriptTurn(tool_blocks=[run_cmd("tc_%d" % n, "mol modcolor 0 top ResidueType")]) for n in (1, 2, 3, 4)],
        wrap_up_error=ClaudeLoopError("HTTP 400: bad request"))
    app.tool_bridge = ProductBridge([fail, fail, fail, fail])
    _reply, events = _send(app, tmp_path)
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["wrapped_up"], finished["error"]) == (
        "stuck", False, "HTTP 400: bad request")
    assert not [e for e in events if e["role"] == "error"]


def test_on_event_crash_still_finishes(tmp_path, monkeypatch):
    """Review focus 5: a broken mapping must not skip request.finished, and the run goes on."""
    app, _loop = _app(tmp_path, [ScriptTurn(text="Loading.", tool_blocks=[LOAD]), ScriptTurn(text="Done.")])
    bridge = app.tool_bridge
    real_push = app._push_v2

    def flaky(state, role, event_type, text, metadata):
        if metadata.get("kind") == "tool.started":
            raise RuntimeError("mapping broke")
        return real_push(state, role, event_type, text, metadata)

    monkeypatch.setattr(app, "_push_v2", flaky)
    _reply, events = _send(app, tmp_path)
    assert of_kind(events, "tool.started") == []
    assert len(bridge.calls) == 1                  # the tool still ran
    finished, = of_kind(events, "request.finished")
    assert (finished["status"], finished["tool_calls"], finished["final_text_empty"]) == ("complete", 1, False)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_request_lifecycle_events.py -q 2>&1 | tail -4`
Expected: a collection error, `ImportError: cannot import name 'ACTION_FOR_CODE' from 'vmd_ai_runtime.constants'`.

- [ ] **Step 3: Add the error-code catalogue to `runtime/vmd_ai_runtime/constants.py`**

Append at the end of the file:

```python

# §2f Error codes: the card action the panel offers for each error-event code
# (metadata.code of a role=error event, i.e. ClaudeLoopError.code).
ACTION_FOR_CODE = {
    "unreachable": "test_connection",
    "auth": "open_settings",
    "billing": "switch_profile",
    "model_not_found": "choose_model",
    "other": "open_log",
}
```

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_request_lifecycle_events.py -q 2>&1 | tail -4`
Expected: `12 failed, 2 passed`. `test_action_for_code_catalogue` and `test_no_model_has_no_finished` pass (P03-T08 raises `NO_MODEL` before any event). Each of the others fails on `ValueError: not enough values to unpack (expected 1, got 0)` from `started, = of_kind(events, "request.started")` or `finished, = of_kind(...)`, or on an `assert` about the error metadata.

- [ ] **Step 4: Imports in `runtime/vmd_ai_runtime/app.py`**

Make sure the stdlib imports include `import time` (add it after `import threading` if missing). Add `ACTION_FOR_CODE` to the existing `from .constants import …` line. For example, `from .constants import CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_VERSION` becomes `from .constants import ACTION_FOR_CODE, CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_VERSION`; keep every other name that plans 02–05 import on that line.

Run: `grep -n "^import time\|ACTION_FOR_CODE" runtime/vmd_ai_runtime/app.py`
Expected: two lines.

- [ ] **Step 5: Let the sink capture the run directory**

Replace the whole `class _EventMapper:` (Task 1) with:

```python
class _EventMapper:
    """The ``ctx.on_event`` sink of one request (§2a Legacy callbacks, §2c).

    Every loop item keeps ``RequestState.turn`` current for runtime.info.
    For a v2 session the item also becomes a queue event (``push``); for a
    v1 session it is dropped, because v1 events come from the legacy
    callbacks. The recorder's task directory is captured at the first loop
    event for ``request.finished.run_dir`` (the recorder has ended its task
    by the time the worker builds request.finished). A failure here is
    logged and never reaches the loop.
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
        return self.app._push_v2(self.state, role, event_type, text, meta)
```

- [ ] **Step 6: Emit request.started/request.finished and v2 error events from the agent worker**

Replace the whole `_run_claude_loop_response` method (the Task 1 version, up to the banner before `# Background thread: simple provider (mock / fallback)`) with:

```python
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

```

- [ ] **Step 7: The mock path emits the same envelope for v2 sessions**

Replace the whole `_run_provider_response` method, from `    def _run_provider_response(` through the last line before the `    # ------------------------------------------------------------------` banner that precedes `    # Helpers`, with:

```python
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

```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_request_lifecycle_events.py tests/test_events_v2_shapes.py tests/test_memory_integration.py tests/test_profile_loop_factory.py tests/test_runtime_integration.py tests/test_security_notice.py -q 2>&1 | tail -2`
Expected: all passed (`14 passed` in `test_request_lifecycle_events.py`), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+21 passed`, 0 failed.

- [ ] **Step 9: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/constants.py tests/test_request_lifecycle_events.py
git commit -m "feat(runtime): request.started/finished on every path and v2 error events (P07-T02)

v2 sessions get request.started first and request.finished from a finally
on the agent path, the mock path and pre-run failures, with status,
turns, tool calls, usage (null when unreported), duration, wrapped_up,
error and run_dir. Errors become one v2 error event carrying code,
http_status, hint and the ACTION_FOR_CODE action. A crash in the event
mapping never skips request.finished. v1 events are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: P07-T03 — tool.finished display fields and late tool.finished

**Files:**
- Create: `tests/test_tool_finished_fields.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py`: `_tool_finished_meta`. Plan 02 (P02-T08) added it just before the `# The Claude tool loop` banner (6f5f937: line 1354).
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - Imports: `_tool_finished_meta` from `.claude_loop`.
  - `_on_late_result` (plan 05, P05-T02; replaced whole).
  - New method `_push_late_finished`.

**Interfaces:**
- Consumes: on_late_result (P05-T02); result dict (P05-T02..T07). Specifically:
  - `VmdToolBridge.on_late_result(session_id, call_key, info)`. `info` is the full product result dict plus `late: True`, `request_id`, `tool_name` and `chat_dir`, and is called once per accepted late result (duplicates are refused).
  - `RuntimeApp._tool_timeouts()` (P05-T01), patched in the tests to shorten `cancel_grace_s`.
  - `FakePlugin`, `ProductBridge`, `product_options` (Task 1). `_push_v2`, `_wants_v2` (Task 1).
- Produces:
  - late tool.finished {..., late: true} pushed once per accepted late result
  - (plan additions) `claude_loop._tool_finished_meta(call_key, tool_name, executor, result, duration_ms, *, late: bool = False)`; `RuntimeApp._push_late_finished(session_id, call_key, info) -> Optional[Dict]`. The late event carries the original `request_id` and `call_key`, `executor: "tcl"`, the executor-reported `duration_ms` and every display field. It goes only to a v2 session that is still on the call's chat. The `late_result` line of plan 05 is still written for every session.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_finished_fields.py`:

```python
"""P07-T03: tool.finished display fields (C1, C3, C5) and the late tool.finished (§2d)."""
from __future__ import annotations

import json
import threading

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, of_kind,
                               poll_all, product_options, product_result, run_cmd, start_v2, tool_block)
from vmd_ai_runtime.claude_loop import _tool_finished_meta

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
BLOCKED = [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]
FAILED_STATEMENT = {"index": 3, "text": "bogus",
                    "error_info": 'invalid command name "bogus"\n    while executing\n"bogus"'}
IMAGE = {"path": "/w/chats/chat_000000000001/images/k.png",
         "thumb_path": "/w/chats/chat_000000000001/images/k_thumb.png", "width": 847, "height": 1024,
         "src_width": 1280, "src_height": 1547, "renderer": "TachyonInternal"}
CUT = ("0\n1\n[output truncated: 20000 lines, 107 KB. Full text: /w/chats/chat_000000000001/outputs/k.txt. "
       "Don't print it again: compute what you need (measure, a narrower selection), or read a slice "
       "of that file with Tcl.]\n19999")


def test_fields_blocked_statements_output_path_image_saved_path(tmp_path):
    results = [
        product_result(ok=False, executed="no", blocked=BLOCKED,
                       error="Not run: `exec` is never run by ChatVMD. If the user needs it, show the command "
                             "in a tcl code block so they can copy it and run it in the VMD console themselves."),
        product_result(ok=False, error='invalid command name "bogus"', applied_text="mol new a.pdb\nmol delrep 0 top\n",
                       statements={"total": 4, "applied": 2, "failed": FAILED_STATEMENT}),
        product_result(output=CUT, truncated=True, output_bytes=108889,
                       output_path="/w/chats/chat_000000000001/outputs/k.txt"),
        product_result(image=IMAGE, saved_path="/w/fig1.png", image_b64=TINY_PNG_B64, image_mime="image/png"),
    ]
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop([
        ScriptTurn(tool_blocks=[
            run_cmd("tc_1", "exec ls"),
            run_cmd("tc_2", "mol new a.pdb\nmol delrep 0 top\nbogus\nputs x"),
            run_cmd("tc_3", "puts [$sel get {x y z}]"),
            tool_block("tc_4", "capture_vmd_snapshot", purpose="final figure", save_path="fig1.png"),
        ]),
        ScriptTurn(text="Done."),
    ], options=product_options(supports_vision=False))
    app.tool_bridge = ProductBridge(results)
    session = start_v2(app, tmp_path)
    result(send(app, session, "four steps"))
    wait_idle(app, session)
    events = poll_all(app, session)
    blocked, failed, cut, snap = of_kind(events, "tool.finished")
    assert (blocked["ok"], blocked["executed"], blocked["blocked"]) == (False, "no", BLOCKED)
    assert blocked["error"].startswith("Not run: `exec` is never run by ChatVMD.")
    assert (failed["ok"], failed["executed"], failed["statements"]) == (
        False, "yes", {"total": 4, "applied": 2, "failed": FAILED_STATEMENT})
    assert (cut["output"], cut["truncated"], cut["output_path"], cut["output_bytes"]) == (
        CUT, True, "/w/chats/chat_000000000001/outputs/k.txt", 108889)
    assert (snap["image"], snap["saved_path"], snap["tool_name"]) == (IMAGE, "/w/fig1.png", "capture_vmd_snapshot")
    for meta in (blocked, failed, cut):
        assert meta["image"] is None and meta["saved_path"] is None
    assert [m["late"] for m in (blocked, failed, cut, snap)] == [False] * 4
    assert TINY_PNG_B64 not in json.dumps(events)        # base64 never reaches a display event


def test_tool_finished_meta_late_flag():
    meta = _tool_finished_meta("k00000000001", "run_vmd_command", "tcl", product_result(output="x"), 12.4, late=True)
    assert (meta["late"], meta["duration_ms"], meta["output"], meta["output_bytes"]) == (True, 12, "x", 1)
    assert _tool_finished_meta("k00000000001", "run_vmd_command", "tcl", product_result(), 0.0)["late"] is False


def _held_run(tmp_path, monkeypatch, script):
    app = make_token_app(tmp_path)                        # the real VmdToolBridge
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))   # cancel_grace_s 0.1 s
    app.claude_loop = MetaScriptedLoop(script)
    return app, start_v2(app, tmp_path)


def _index(events, predicate):
    return [i for i, e in enumerate(events) if predicate(e["metadata"] or {})]


def test_late_after_finished(tmp_path, monkeypatch):
    app, session = _held_run(tmp_path, monkeypatch, [ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")])])
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        first = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        reply = plugin.post(key, ok=True, output="3 atoms", statements_total=1, statements_applied=1)
        again = plugin.post(key, ok=True, output="3 atoms", statements_total=1, statements_applied=1)
    events = poll_all(app, session)
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    assert again["duplicate"] is True
    finished = of_kind(events, "tool.finished")
    assert [(m["call_key"], m["executed"], m["late"]) for m in finished] == [
        (key, "unknown", False), (key, "yes", True)]           # one row update, not two
    late = finished[1]
    assert (late["request_id"], late["ok"], late["output"], late["tool_name"], late["executor"], late["v"]) == (
        first["request_id"], True, "3 atoms", "run_vmd_command", "tcl", 2)
    assert late["statements"] == {"total": 1, "applied": 1, "failed": None}
    assert of_kind(events, "request.finished")[0]["status"] == "cancelled"
    end, = _index(events, lambda m: m.get("kind") == "request.finished")
    late_at, = _index(events, lambda m: m.get("late") is True)
    assert late_at > end


def test_late_after_next_request(tmp_path, monkeypatch):
    """Review focus 2: the late row update lands while the next request is running."""
    gate = threading.Event()
    app, session = _held_run(tmp_path, monkeypatch, [
        ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")]),
        ScriptTurn(text="Second answer.", before=lambda: gate.wait(5)),
    ])
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        first = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        second = result(send(app, session, "and now?"))
        plugin.wait_for(lambda e: (e["metadata"] or {}).get("kind") == "turn.started"
                        and e["metadata"].get("request_id") == second["request_id"])
        reply = plugin.post(key, ok=True, output="3 atoms")
        gate.set()
        wait_idle(app, session)
    events = poll_all(app, session)
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    late, = [m for m in of_kind(events, "tool.finished") if m["late"]]
    assert (late["call_key"], late["request_id"], late["output"]) == (key, first["request_id"], "3 atoms")
    started2, = _index(events, lambda m: m.get("kind") == "request.started" and m["request_id"] == second["request_id"])
    finished2, = _index(events, lambda m: m.get("kind") == "request.finished" and m["request_id"] == second["request_id"])
    late_at, = _index(events, lambda m: m.get("late") is True)
    assert started2 < late_at < finished2
    assert of_kind(events, "request.finished")[1]["status"] == "complete"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_finished_fields.py -q 2>&1 | tail -5`
Expected: `3 failed, 1 passed`.
- `test_tool_finished_meta_late_flag` fails with `TypeError: _tool_finished_meta() got an unexpected keyword argument 'late'`.
- Both late tests fail. In `test_late_after_finished`, the assertion on `[(m["call_key"], …)]` fails because only one `tool.finished` is present. In `test_late_after_next_request`, `ValueError: not enough values to unpack` is raised.
- `test_fields_blocked_statements_output_path_image_saved_path` passes already: it pins the C1/C3/C5 display fields that P02-T08's `_tool_finished_meta` copies from the plan-05 result dict, now delivered to v2 sessions by Task 1.

- [ ] **Step 3: Give `_tool_finished_meta` a `late` keyword (additive; S7 unaffected)**

In `runtime/vmd_ai_runtime/claude_loop.py`, replace:

```python
                        result: Dict[str, Any], duration_ms: float) -> Dict[str, Any]:
```

with:

```python
                        result: Dict[str, Any], duration_ms: float, *,
                        late: bool = False) -> Dict[str, Any]:
```

and, in the same function, replace:

```python
        "saved_path": result.get("saved_path"),
        "late": False,
```

with:

```python
        "saved_path": result.get("saved_path"),
        # True only for the second tool.finished the app emits when a result
        # arrives after its request gave up on it (§2d Cancel semantics).
        "late": bool(late),
```

- [ ] **Step 4: Emit the late `tool.finished` from `runtime/vmd_ai_runtime/app.py`**

Add `_tool_finished_meta` to the existing `from .claude_loop import (…)` block, keeping every name already there.

Replace the whole `_on_late_result` method (plan 05) with:

```python
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
        return self._push_v2(state, "system", "state", "", meta)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_finished_fields.py tests/test_tool_bridge_results.py tests/test_loop_events.py -q 2>&1 | tail -2`
Expected: all passed (`4 passed` in the new file), 0 failed.

Run the S7 guards: `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_hashes.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_retry_pin.py -q 2>&1 | tail -1`
Expected: all passed, 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+25 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py runtime/vmd_ai_runtime/app.py tests/test_tool_finished_fields.py
git commit -m "feat(runtime): late tool.finished for v2 sessions; pin the display fields (P07-T03)

When the bridge accepts a result after its request gave up, the runtime
still writes the late_result line and now pushes a second tool.finished
with late: true (original request_id and call_key) to a v2 session on
that chat, once per accepted result, even after request.finished or
while the next request runs. tool.finished carries blocked, statements,
output_path/output_bytes, image and saved_path; base64 never does.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: P07-T04 — Display-log persistence and message-only counts

**Files:**
- Create: `tests/test_display_log.py`
- Modify: `runtime/vmd_ai_runtime/store.py`: `append_events` and `_touch_manifest` (6f5f937: 40-51 and 120-136; plan 03's P03-T03 rewrote the file). New methods `append_display_events`, `touch_manifest`, `recount_messages`, `counts_as_message` and `_count_messages`.
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - New module-level `PERSISTED_STATE_KINDS` and `is_display_event`, after `_wants_v2`.
  - `_EventMapper` (replaced whole; Task 2 version).
  - New method `_persist_display`.
  - `_push_late_finished` (Task 3): its last line.
  - `_resume_token_session` (plan 03): its `message_count` line.
- Modify: `tests/test_store_locks.py`: plan 03's `test_store_lock_serialises_index_appends` appends assistant *messages* instead of chunks. Chunks no longer count, so its count of 161 still proves that no read-modify-write is lost.

**Interfaces:**
- Consumes: v2 events (P07-T01..T03). Also used: `ChatStore.lock_root`, `_write_manifest`, `_append_index_row`, `locks.store_lock` (P03-T03); `FakePlugin` (Task 1); `_push_late_finished` (Task 3).
- Produces:
  - ChatStore.recount_messages(chat_id: str) -> int
  - persisted kinds: user message, request.started, tool.started, assistant/message per turn, reasoning/message per turn, tool.finished, error, request.finished, lifecycle
  - (plan additions)
    - `ChatStore.append_display_events(chat_id, events) -> int` appends lines and does not touch the manifest.
    - `ChatStore.touch_manifest(chat_id) -> None`.
    - `ChatStore.counts_as_message(event) -> bool` (staticmethod): true for every user message, and for an assistant message with non-empty text.
    - `ChatStore._count_messages(chat_id) -> int`.
    - `_touch_manifest` now recounts `message_count` from `events.jsonl`; `delta_messages` is accepted and ignored.
    - `app.is_display_event(event) -> bool`; `app.PERSISTED_STATE_KINDS`; `RuntimeApp._persist_display(chat_id, event) -> bool`.
    - `_EventMapper.seal_reasoning() -> Optional[Dict]`.
    - A v2 session receives a sealed `reasoning/message {request_id, turn, duration_ms, v}` live, just before the first non-reasoning event after that turn's reasoning (or before `request.finished`). `turn.retry` drops unsealed reasoning.
    - For a token session, `chat.resume` reports the recounted `message_count`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_display_log.py`:

```python
"""P07-T04: the v2 display log in events.jsonl, sealed reasoning, message-only counts (§2c, §7)."""
from __future__ import annotations

import json

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (FakePlugin, MetaScriptedLoop, ProductBridge, ScriptTurn, kinds,
                               poll_all, product_result, run_cmd, start_v2)

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")
USAGE = {"input_tokens_evaluated": 120, "output_tokens": 9, "cache_read_tokens": None, "source": "ollama"}


def _run(tmp_path, script, *, event_protocol=2, prompts=("load 1hck",)):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(script)
    app.tool_bridge = ProductBridge([product_result(output="0"), product_result(output="0")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    replies = []
    for prompt in prompts:
        replies.append(result(send(app, session, prompt)))
        wait_idle(app, session)
    return app, session, replies, poll_all(app, session)


def _stored(app, chat_id):
    return app.store.read_events(chat_id, limit=10 ** 9)


def test_no_chunks_persisted(tmp_path):
    script = [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD], reasoning="Load it first.", usage=USAGE,
                   status={"phase": "loading_model", "message": "Loading qwen3.8:27b"}),
        ScriptTurn(text="Partial", drop_after_text=True),
        ScriptTurn(text="Done.", usage=USAGE),
    ]
    app, _session, (reply,), _events = _run(tmp_path, script)
    stored = _stored(app, reply["chat_id"])
    assert kinds(stored) == [
        ("user", "message", None),
        ("system", "state", "request.started"),
        ("reasoning", "message", None),
        ("assistant", "message", None),
        ("system", "state", "tool.started"),
        ("system", "state", "tool.finished"),
        ("assistant", "message", None),
        ("system", "state", "request.finished"),
    ]
    assert all(e["metadata"]["v"] == 2 for e in stored)

    v1_app, _s, (v1_reply,), _e = _run(tmp_path / "v1", script, event_protocol=1)
    v1_stored = _stored(v1_app, v1_reply["chat_id"])       # v1 persistence stays as it is
    assert [e["type"] for e in v1_stored].count("chunk") == 3
    assert kinds(v1_stored)[-1] == ("assistant", "message", None)


def test_one_sealed_reasoning_per_turn(tmp_path):
    script = [
        ScriptTurn(reasoning="Check the file first.", tool_blocks=[LOAD]),
        ScriptTurn(reasoning="It loaded; answer.", text="Loaded 1hck."),
    ]
    app, _session, (reply,), events = _run(tmp_path, script)
    sealed = [e for e in events if e["role"] == "reasoning" and e["type"] == "message"]
    assert [(e["metadata"]["turn"], e["text"]) for e in sealed] == [
        (1, "Check the file first."), (2, "It loaded; answer.")]
    for event in sealed:
        assert set(event["metadata"]) == {"request_id", "turn", "duration_ms", "v"}
        assert isinstance(event["metadata"]["duration_ms"], int) and event["metadata"]["duration_ms"] >= 0
        at = events.index(event)
        assert events[at - 1]["role"] == "reasoning" and events[at - 1]["type"] == "chunk"
        assert events[at + 1]["role"] != "reasoning"
    stored = _stored(app, reply["chat_id"])
    assert [(e["metadata"]["turn"], e["text"]) for e in stored if e["role"] == "reasoning"] == [
        (1, "Check the file first."), (2, "It loaded; answer.")]


def test_turn_retry_discards_reasoning(tmp_path):
    script = [ScriptTurn(reasoning="First try", drop_after_text=True),
              ScriptTurn(reasoning="Second try", text="Done.")]
    app, _session, (reply,), events = _run(tmp_path, script)
    sealed = [(e["metadata"]["turn"], e["text"]) for e in events if e["role"] == "reasoning" and e["type"] == "message"]
    assert sealed == [(1, "Second try")]
    assert [e["text"] for e in _stored(app, reply["chat_id"]) if e["role"] == "reasoning"] == ["Second try"]


def test_message_count_user_assistant_only(tmp_path):
    script = [
        ScriptTurn(text="Loading.", tool_blocks=[LOAD]),
        ScriptTurn(text="Done."),
        ScriptTurn(tool_blocks=[run_cmd("tc_2", "mol delrep 0 top")]),   # a tool-only turn: empty text
        ScriptTurn(text="Ok."),
    ]
    app, _session, (first, second), _events = _run(tmp_path, script, prompts=("load 1hck", "clear the reps"))
    chat_id = first["chat_id"]
    # user x2, "Loading.", "Done.", "Ok."; the empty tool-only turn and every state event don't count
    assert app.store.get_manifest(chat_id)["message_count"] == 5
    rows = [json.loads(line) for line in app.store.index_path.read_text(encoding="utf-8").splitlines()]
    assert [r for r in rows if r["chat_id"] == chat_id][-1]["message_count"] == 5
    # one index row per chat.send (the user message) plus one per request.finished, not one per event
    assert len([r for r in rows if r["chat_id"] == chat_id]) == 1 + 2 * 2


def test_recount_legacy_manifest(tmp_path):
    app = make_token_app(tmp_path)
    store = app.store
    chat_id = store.create_chat("legacy")
    legacy = [
        {"role": "user", "type": "message", "text": "load", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "chunk", "text": "Lo", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "chunk", "text": "aded.", "metadata": {"request_id": "req_a"}},
        {"role": "assistant", "type": "message", "text": "Loaded.", "metadata": {"request_id": "req_a"}},
        {"role": "tool_result", "type": "message", "text": "0", "metadata": {"tool_call_id": "tc_1", "ok": True}},
        {"role": "system", "type": "lifecycle", "text": "cancelled", "metadata": {"request_id": "req_b"}},
        {"role": "user", "type": "message", "text": "again", "metadata": {"request_id": "req_b"}},
        {"role": "assistant", "type": "message", "text": "", "metadata": {"request_id": "req_b"}},
    ]
    store.append_display_events(chat_id, legacy)
    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 9                         # a legacy manifest counted every event
    store._write_manifest(chat_id, manifest)
    assert store.recount_messages(chat_id) == 3
    assert store.get_manifest(chat_id)["message_count"] == 3

    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 42
    store._write_manifest(chat_id, manifest)
    store.append_events(chat_id, [{"role": "user", "type": "message", "text": "third", "metadata": {}}])
    assert store.get_manifest(chat_id)["message_count"] == 4   # §7: recomputed when next touched

    manifest = store.get_manifest(chat_id)
    manifest["message_count"] = 42
    store._write_manifest(chat_id, manifest)
    session = start_v2(app, tmp_path)
    resumed = result(call(app, "chat.resume", {"chat_id": chat_id}, session))
    assert resumed["message_count"] == 4
    assert store.get_manifest(chat_id)["message_count"] == 4


def test_late_tool_finished_persisted(tmp_path, monkeypatch):
    app = make_token_app(tmp_path)                        # the real VmdToolBridge
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))
    app.claude_loop = MetaScriptedLoop([ScriptTurn(tool_blocks=[run_cmd("tc_1", "long_job")])])
    session = start_v2(app, tmp_path)
    with FakePlugin(app, session, answer=lambda meta: None) as plugin:
        reply = result(send(app, session, "run the long job"))
        key, = plugin.wait_held()
        result(call(app, "chat.cancel", {}, session))
        wait_idle(app, session)
        plugin.post(key, ok=True, output="3 atoms")
    stored = _stored(app, reply["chat_id"])
    finished = [e["metadata"] for e in stored if e["metadata"].get("kind") == "tool.finished"]
    assert [(m["call_key"], m["late"], m["executed"]) for m in finished] == [
        (key, False, "unknown"), (key, True, "yes")]
    assert kinds(stored)[-1] == ("system", "state", "tool.finished")   # after request.finished
    assert not [e for e in stored if e["role"] == "tool_start"]
```

In `tests/test_store_locks.py`, inside `test_store_lock_serialises_index_appends`, replace:

```python
            store.append_events(chat_id, [{"role": "assistant", "type": "chunk", "text": "x", "metadata": {}}])
```

with:

```python
            # message_count counts user and assistant messages only (plan 07, §2c)
            store.append_events(chat_id, [{"role": "assistant", "type": "message", "text": "x", "metadata": {}}])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_display_log.py tests/test_store_locks.py -q 2>&1 | tail -8`
Expected: `6 failed`, the rest passed. Why each one fails:
- `test_no_chunks_persisted`: the stored log holds only the user message.
- `test_one_sealed_reasoning_per_turn` and `test_turn_retry_discards_reasoning`: no `reasoning/message` event.
- `test_message_count_user_assistant_only`: `assert 2 == 5`. Only the two user messages are stored, each counted as one event.
- `test_recount_legacy_manifest`: `AttributeError: 'ChatStore' object has no attribute 'append_display_events'`.
- `test_late_tool_finished_persisted`: no `tool.finished` is stored.

`test_store_locks.py` passes both before and after this change: 161 messages give 161 under either counting rule.

- [ ] **Step 3: Message-only counts and display appends in `runtime/vmd_ai_runtime/store.py`**

Replace the whole `append_events` method:

```python
    def append_events(self, chat_id: str, events: Iterable[Dict[str, Any]]) -> int:
        if not chat_id:
            return 0
        chat_dir = self.chat_dir(chat_id)
        if not chat_dir.exists():
            return 0
        events_path = chat_dir / "events.jsonl"
        count = 0
        with events_path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                count += 1
        self._touch_manifest(chat_id, delta_messages=count)
        return count
```

with:

```python
    def append_events(self, chat_id: str, events: Iterable[Dict[str, Any]]) -> int:
        """Append events and touch the manifest (updated_at, message_count, index row)."""
        if not chat_id or not self.chat_dir(chat_id).exists():
            return 0
        count = self.append_display_events(chat_id, events)
        self._touch_manifest(chat_id)
        return count

    def append_display_events(self, chat_id: str, events: Iterable[Dict[str, Any]]) -> int:
        """Append events to events.jsonl without touching the manifest (§2c Persistence).

        The v2 display log is written one event at a time while a request
        runs. The runtime touches the manifest once per request (at
        request.finished), so index.jsonl gains one row per request, not one
        per event.
        """
        if not chat_id:
            return 0
        chat_dir = self.chat_dir(chat_id)
        if not chat_dir.exists():
            return 0
        count = 0
        with (chat_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                count += 1
        return count

    def touch_manifest(self, chat_id: str) -> None:
        """Bump updated_at, recount message_count and append an index row."""
        self._touch_manifest(chat_id)

    def recount_messages(self, chat_id: str) -> int:
        """Recompute message_count from events.jsonl and store it (§2c, §7); returns it.

        updated_at is left alone. An index row is appended only when the
        stored count was wrong (a legacy manifest counted every event).
        """
        if not chat_id:
            return 0
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return 0
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return 0
            count = self._count_messages(chat_id)
            if manifest.get("message_count") != count:
                manifest["message_count"] = count
                self._write_manifest(chat_id, manifest)
                self._append_index_row({
                    "chat_id": chat_id,
                    "title": manifest.get("title") or "New Chat",
                    "updated_at": manifest.get("updated_at") or _now_iso(),
                    "message_count": count,
                })
        return count

    @staticmethod
    def counts_as_message(event: Any) -> bool:
        """message_count counts user messages and non-empty assistant messages (§2c)."""
        if not isinstance(event, dict) or event.get("type") != "message":
            return False
        role = event.get("role")
        if role == "user":
            return True
        return role == "assistant" and bool(str(event.get("text") or "").strip())

    def _count_messages(self, chat_id: str) -> int:
        path = self.chat_dir(chat_id) / "events.jsonl"
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if '"message"' not in line:        # cheap skip for chunk and state lines
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if self.counts_as_message(event):
                    count += 1
        return count
```

Replace the whole `_touch_manifest` method (plan 03's version, from `    def _touch_manifest(self, chat_id: str, delta_messages: int = 0) -> None:` through its closing `            })`) with:

```python
    def _touch_manifest(self, chat_id: str, delta_messages: int = 0) -> None:
        """Bump updated_at, recount message_count and append an index row.

        ``delta_messages`` is accepted for old callers and ignored. The count
        (user and assistant messages only, §2c) is recomputed from
        events.jsonl on every touch. That corrects a legacy manifest the
        next time it is touched (§7), and concurrent appends can never lose
        a count.
        """
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return
            manifest["updated_at"] = _now_iso()
            manifest["message_count"] = self._count_messages(chat_id)
            self._write_manifest(chat_id, manifest)
            self._append_index_row({
                "chat_id": chat_id,
                "title": manifest.get("title") or "New Chat",
                "updated_at": manifest["updated_at"],
                "message_count": manifest["message_count"],
            })
```

- [ ] **Step 4: Decide what the display log keeps (`runtime/vmd_ai_runtime/app.py`)**

Insert directly after the `_wants_v2` function (and before `class _EventMapper:`):

```python
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


```

- [ ] **Step 5: Seal reasoning and persist in the per-request sink**

Replace the whole `class _EventMapper:` (Task 2 version) with:

```python
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
```

- [ ] **Step 6: `_persist_display`, the late event, and the recounted resume**

Insert directly after the `_push_v2` method:

```python
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

```

In `_push_late_finished` (Task 3), replace its last line:

```python
        return self._push_v2(state, "system", "state", "", meta)
```

with:

```python
        event = self._push_v2(state, "system", "state", "", meta)
        self._persist_display(chat_id, event)      # "tool.finished (including late:true ones)"
        return event
```

In `_resume_token_session` (plan 03), replace:

```python
            "message_count": manifest.get("message_count", 0),
            "last_seq": last_seq,
```

with:

```python
            "message_count": self.store.recount_messages(chat_id),
            "last_seq": last_seq,
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_display_log.py tests/test_store_locks.py tests/test_store.py tests/test_events_v2_shapes.py tests/test_request_lifecycle_events.py tests/test_tool_finished_fields.py tests/test_memory_integration.py -q 2>&1 | tail -2`
Expected: all passed (`6 passed` in `test_display_log.py`), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+31 passed`, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/store.py runtime/vmd_ai_runtime/app.py tests/test_display_log.py tests/test_store_locks.py
git commit -m "feat(runtime): v2 display log, sealed reasoning, message-only counts (P07-T04)

v2 sessions persist user messages, request.started, tool.started, one
assistant message per turn, one sealed reasoning/message per turn (also
pushed live), tool.finished (late ones too), errors and request.finished.
Chunks and live-only state events are not stored. The manifest is touched
once per request, and message_count is recounted from events.jsonl on
every touch (user and non-empty assistant messages), which also fixes
legacy manifests. v1 persistence is unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: P07-T05 — Monotonic seq, trimming, replay via chat.history.get

**Files:**
- Create: `tests/test_event_seq.py`
- Modify: `runtime/vmd_ai_runtime/events.py`: the whole file (6f5f937: 1-53, plus plan 03's `last_seq` property).
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - Import `display_log` from `.events`.
  - The `chat.history.get` branch (6f5f937: 313-321).
  - `_resume_token_session` (plan 03): `state.queue.clear()` becomes `state.queue.drop_pending()`.

**Interfaces:**
- Consumes: EventQueue.last_seq (P03-T04). Also used: `_resume_token_session` (P03-T04; Task 4 changed its `message_count`); `conversation.ALL_EVENTS` (P03-T02); `is_display_event` (Task 4); `ChatStore.append_display_events` (Task 4).
- Produces:
  - EventQueue(trim_after: int = 1000); EventQueue.drop_pending() -> int
  - (plan additions)
    - `events.DEFAULT_TRIM_AFTER = 1000`.
    - `events.display_log(events) -> List[Dict]`. It drops every `role=tool_start` event, and every v1 chunk whose request also stored an assistant message; everything else keeps its order.
    - A token session's `chat.history.get` returns the whole display log. It ignores `limit`, and returns no tail cut and no `tool_start`.
    - A token session's `chat.resume` keeps `seq`: it returns `last_seq` equal to the queue's last seq before the resume, and `chat_resumed` gets `last_seq + 1`.
    - Tokenless `chat.resume` and `chat.history.get` are unchanged.
    - A poll that confirms delivery up to `after_seq` lets the queue drop delivered events beyond the newest `trim_after`; undelivered events are never trimmed.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_seq.py`:

```python
"""P07-T05: monotonic seq for token sessions, trimming, and history replay (§2c, §7)."""
from __future__ import annotations

import pytest

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MODEL, MetaScriptedLoop, ProductBridge, ScriptTurn, poll_all,
                               product_result, run_cmd, start_v2)
from vmd_ai_runtime.app import is_display_event
from vmd_ai_runtime.events import EventQueue, display_log

LOAD = run_cmd("tc_1", "mol new 1hck.pdb")


def _app(tmp_path, script):
    app = make_token_app(tmp_path)
    app.claude_loop = MetaScriptedLoop(script)
    app.tool_bridge = ProductBridge([product_result(output="0")])
    return app


@pytest.mark.parametrize("event_protocol", [1, 2])
def test_token_resume_keeps_seq(tmp_path, event_protocol):
    app = _app(tmp_path, [ScriptTurn(text="Hello.")])
    session = start_v2(app, tmp_path, event_protocol=event_protocol)
    result(send(app, session, "hi"))
    wait_idle(app, session)
    before = app.sessions.get(session.session_id).queue.last_seq
    assert before > 3
    other = app.store.create_chat("other")
    resumed = result(call(app, "chat.resume", {"chat_id": other}, session))
    assert resumed["last_seq"] == before
    assert [(e["seq"], e["text"]) for e in poll_all(app, session)] == [(before + 1, "chat_resumed")]


def test_tokenless_resume_resets(tmp_path):
    app = _app(tmp_path, [ScriptTurn(text="Hello.")])
    session = start_v2(app, tmp_path, token="")
    result(send(app, session, "hi", conversation_mode="local_first", model=MODEL))   # no model override
    wait_idle(app, session)
    assert app.sessions.get(session.session_id).queue.last_seq > 3
    other = app.store.create_chat("other")
    resumed = result(call(app, "chat.resume", {"chat_id": other}, session))
    assert set(resumed) == {"ok", "chat_id", "title", "message_count"}     # today's fields
    assert [(e["seq"], e["text"]) for e in poll_all(app, session)] == [(1, "chat_resumed")]


def test_trim_beyond_1000():
    queue = EventQueue()
    assert queue.trim_after == 1000
    for i in range(1500):
        queue.push("assistant", "chunk", str(i))
    queue.poll(after_seq=1400, limit=10)                  # the client has now seen 1..1400
    kept = queue.poll(after_seq=0, limit=500)["events"]
    assert kept[0]["seq"] == 401                          # the newest 1000 delivered events stay
    tail = queue.poll(after_seq=1400, limit=500)["events"]
    assert [e["seq"] for e in tail] == list(range(1401, 1501))   # undelivered: never trimmed
    small = EventQueue(trim_after=2)
    for i in range(5):
        small.push("system", "lifecycle", str(i))
    assert [e["seq"] for e in small.poll(after_seq=4, limit=10)["events"]] == [5]
    assert [e["seq"] for e in small.poll(after_seq=0, limit=10)["events"]] == [3, 4, 5]


def test_drop_pending_keeps_seq():
    queue = EventQueue()
    for text in ("a", "b", "c"):
        queue.push("system", "lifecycle", text)
    assert queue.drop_pending() == 3
    assert queue.last_seq == 3 and queue.poll(0, 10)["events"] == []
    assert queue.push("system", "lifecycle", "d")["seq"] == 4
    queue.clear()                                         # tokenless resume: today's reset
    assert queue.last_seq == 0 and queue.push("system", "lifecycle", "e")["seq"] == 1


def test_history_get_full_display_log(tmp_path):
    app = _app(tmp_path, [ScriptTurn(reasoning="Load first.", text="Loading.", tool_blocks=[LOAD]),
                          ScriptTurn(text="Done.")])
    session = start_v2(app, tmp_path)
    reply = result(send(app, session, "load 1hck"))
    wait_idle(app, session)
    live = poll_all(app, session)
    history = result(call(app, "chat.history.get", {"chat_id": reply["chat_id"]}, session))["events"]
    # A resumed chat replays exactly the display events the live session saw (§2c).
    assert history == [e for e in live if is_display_event(e) and "request_id" in e["metadata"]]

    chat_id = app.store.create_chat("long")
    rows = [{"seq": i, "ts": 0.0, "role": "user" if i % 2 else "assistant", "type": "message",
             "text": "m%d" % i, "metadata": {"request_id": "req_%012d" % (i // 2), "v": 2}}
            for i in range(1, 251)]
    app.store.append_display_events(chat_id, rows)
    full = result(call(app, "chat.history.get", {"chat_id": chat_id}, session))["events"]
    assert [e["seq"] for e in full] == list(range(1, 251))          # no tail cut for a token session
    tokenless = start_v2(app, tmp_path, token="")
    tail = result(call(app, "chat.history.get", {"chat_id": chat_id}, tokenless))["events"]
    assert [e["seq"] for e in tail] == list(range(51, 251))         # today's limit of 200


def test_mixed_log_replay(tmp_path):
    """Review focus 4: an M1 (v1) request and an M2 (v2) request in one chat replay without duplicates."""
    app = _app(tmp_path, [ScriptTurn(text="Loaded 1hck."), ScriptTurn(text="Colored red.")])
    v1 = start_v2(app, tmp_path, event_protocol=1)
    chat_id = result(send(app, v1, "load 1hck"))["chat_id"]
    wait_idle(app, v1)
    result(call(app, "session.stop", {}, v1))             # the M1 panel closes; the chat lock is freed
    v2 = start_v2(app, tmp_path)
    result(call(app, "chat.resume", {"chat_id": chat_id}, v2))
    result(send(app, v2, "color it red"))
    wait_idle(app, v2)
    # An older v1 request that failed kept its chunks; the legacy direct path stored a tool_start.
    app.store.append_events(chat_id, [
        {"seq": 90, "ts": 0.0, "role": "user", "type": "message", "text": "and now?",
         "metadata": {"request_id": "req_e"}},
        {"seq": 91, "ts": 0.0, "role": "assistant", "type": "chunk", "text": "Half an ans",
         "metadata": {"request_id": "req_e"}},
        {"seq": 92, "ts": 0.0, "role": "error", "type": "message", "text": "Agent error: boom",
         "metadata": {"request_id": "req_e"}},
        {"seq": 93, "ts": 0.0, "role": "tool_start", "type": "message", "text": "[VMD] mol list",
         "metadata": {"tool_call_id": "direct_1"}},
    ])
    stored = app.store.read_events(chat_id, limit=10 ** 9)
    assert [e["text"] for e in stored if e["type"] == "chunk"] == ["Loaded ", "1hck.", "Half an ans"]
    replay = result(call(app, "chat.history.get", {"chat_id": chat_id}, v2))["events"]
    assert [e["text"] for e in replay if e["type"] == "chunk"] == ["Half an ans"]   # no message for req_e
    assert not [e for e in replay if e["role"] == "tool_start"]
    assert [(e["role"], e["text"]) for e in replay if e["type"] == "message"] == [
        ("user", "load 1hck"), ("assistant", "Loaded 1hck."),
        ("user", "color it red"), ("assistant", "Colored red."),
        ("user", "and now?"), ("error", "Agent error: boom"),
    ]
    assert display_log(stored) == replay
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_event_seq.py -q 2>&1 | tail -4`
Expected: a collection error, `ImportError: cannot import name 'display_log' from 'vmd_ai_runtime.events'`.

- [ ] **Step 3: Rewrite `runtime/vmd_ai_runtime/events.py`**

Replace the whole file with:

```python
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from .constants import EVENT_ROLES, EVENT_TYPES

# Delivered events kept for a re-poll after a transport blip (§2c Sequence numbers).
DEFAULT_TRIM_AFTER = 1000


class EventQueue:
    """One session's event queue, polled by the plugin (§2c).

    ``seq`` only grows. ``drop_pending`` (a token session's chat.resume)
    empties the queue without resetting it; only ``clear`` (a tokenless
    chat.resume, today's behaviour) resets it. A poll with ``after_seq = N``
    confirms delivery of events up to N. Beyond the newest ``trim_after``
    delivered events the oldest are dropped, and undelivered events are
    never trimmed.
    """

    def __init__(self, trim_after: int = DEFAULT_TRIM_AFTER) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._seq = 0
        self._delivered = 0
        self.trim_after = max(0, int(trim_after))

    def push(self, role: str, event_type: str, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if role not in EVENT_ROLES:
            raise ValueError(f"Unsupported role: {role}")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {event_type}")
        item = {
            "seq": 0,
            "ts": time.time(),
            "role": role,
            "type": event_type,
            "text": str(text or ""),
            "metadata": dict(metadata or {}),
        }
        with self._lock:
            self._seq += 1
            item["seq"] = self._seq
            self._events.append(item)
        return item

    def clear(self) -> None:
        """Drop all events and reset the sequence counter (tokenless chat.resume)."""
        with self._lock:
            self._events.clear()
            self._seq = 0
            self._delivered = 0

    def drop_pending(self) -> int:
        """Drop every queued event but keep ``seq`` (a token session's chat.resume, §2c).

        Returns how many events were dropped.
        """
        with self._lock:
            dropped = len(self._events)
            self._events.clear()
            return dropped

    @property
    def last_seq(self) -> int:
        """Sequence number of the newest event pushed (0 when none)."""
        with self._lock:
            return self._seq

    def poll(self, after_seq: int, limit: int) -> Dict[str, Any]:
        safe_after = max(0, int(after_seq or 0))
        safe_limit = max(1, min(int(limit or 50), 500))
        with self._lock:
            # Polling past an event confirms its delivery.
            if safe_after > self._delivered:
                self._delivered = min(safe_after, self._seq)
            self._trim_locked()
            items = [e for e in self._events if int(e.get("seq") or 0) > safe_after]
            batch = items[:safe_limit]
            last_seq = int(batch[-1]["seq"]) if batch else safe_after
            has_more = len(items) > len(batch)
            return {
                "events": batch,
                "last_seq": last_seq,
                "has_more": has_more,
            }

    def _trim_locked(self) -> None:
        """Keep at most ``trim_after`` delivered events (a prefix, since seq only grows)."""
        delivered = 0
        for event in self._events:
            if int(event.get("seq") or 0) > self._delivered:
                break
            delivered += 1
        excess = delivered - self.trim_after
        if excess > 0:
            del self._events[:excess]


def display_log(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The events a resumed chat replays through vm::apply (§2c Persistence, §7).

    * role=tool_start (the execution channel) is never replayed.
    * A v1 chunk is dropped when its request also stored an assistant
      message, so a log that mixes M1 (v1) and M2 (v2) requests replays
      without duplicates. A request that never stored a message keeps its
      chunks.

    Everything else keeps its order.
    """
    sealed = {
        str((e.get("metadata") or {}).get("request_id") or "")
        for e in events
        if e.get("role") == "assistant" and e.get("type") == "message"
    }
    out: List[Dict[str, Any]] = []
    for event in events:
        if event.get("role") == "tool_start":
            continue
        if event.get("type") == "chunk":
            request_id = str((event.get("metadata") or {}).get("request_id") or "")
            if request_id and request_id in sealed:
                continue
        out.append(event)
    return out
```

- [ ] **Step 4: Keep `seq` on token resume, and replay the display log (`runtime/vmd_ai_runtime/app.py`)**

Add the import next to the other package imports:

```python
from .events import display_log
```

In `_resume_token_session` (plan 03), replace:

```python
            state.queue.clear()
            # Polling after last_seq delivers the chat_resumed event below.
            last_seq = state.queue.last_seq
```

with:

```python
            # §2c: a token session's seq never resets; resume drops what is
            # queued and polling after last_seq delivers chat_resumed below.
            state.queue.drop_pending()
            last_seq = state.queue.last_seq
```

(The tokenless `chat.resume` branch keeps its own `state.queue.clear()`.)

Replace the whole `chat.history.get` branch:

```python
        if method == "chat.history.get":
            state = self._get_session(params["session_id"], session_token)
            _ = state
            chat_id = params["chat_id"]
            manifest = self.store.get_manifest(chat_id)
            if manifest is None:
                raise RpcError("NOT_FOUND", f"chat {chat_id} not found")
            events = self.store.read_events(chat_id, limit=params["limit"])
            return {"chat_id": chat_id, "manifest": manifest, "events": events}
```

with:

```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_event_seq.py tests/test_events.py tests/test_memory_integration.py tests/test_display_log.py tests/test_runtime_info_rpcs.py -q 2>&1 | tail -2`
Expected: all passed (`7 passed` in `test_event_seq.py`), 0 failed. Plan 03's `test_resume_locked_chat_returns_chat_locked` still polls after `last_seq` and gets exactly `chat_resumed`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+38 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/events.py runtime/vmd_ai_runtime/app.py tests/test_event_seq.py
git commit -m "feat(runtime): monotonic seq, trimming, display-log replay (P07-T05)

A token session's chat.resume drops queued events but keeps seq and
returns last_seq; tokenless sessions keep today's reset. Delivered events
beyond the newest 1000 are trimmed; undelivered ones never are.
chat.history.get gives token sessions the whole display log without
tool_start, and drops a v1 request's chunks when its message was stored,
so mixed M1/M2 chats replay without duplicates.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: P07-T06 — Long-poll chat.events.poll wait_ms

**Files:**
- Create: `tests/test_long_poll.py`
- Modify: `runtime/vmd_ai_runtime/events.py`: the whole file (the Task 5 version).
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - The `chat.events.poll` branch (6f5f937: 298-303).
  - The token-session block of the `session.start` result (plan 02's `result["runtime"] = …` line).
- Modify: `runtime/vmd_ai_runtime/protocol.py`:
  - `MAX_WAIT_MS`, next to plan 02's `EVENT_PROTOCOLS`.
  - The `chat.events.poll` validator (6f5f937: 79-84).

**Interfaces:**
- Consumes: EventQueue (P07-T05). Also used: `CAPABILITIES` (constants); `validate_method_params`, `_as_int` (protocol).
- Produces:
  - EventQueue.wait(after_seq: int, timeout_s: float) -> bool
  - chat.events.poll wait_ms (≤ 2000)
  - session.start capabilities.long_poll = true
  - (plan additions)
    - `protocol.MAX_WAIT_MS = 2000`. `wait_ms` is passed through only when present, so a v1 poll's params are unchanged. A negative value is rejected with `INVALID_PARAMS`.
    - With `wait_ms`, a cursor ahead of the queue returns at once with the queue's real `last_seq`. Without `wait_ms` (the M1 short-poll), today's echo of `after_seq` is kept.
    - Only token sessions see `capabilities.long_poll`; the shared `CAPABILITIES` constant is not mutated.
    - `push`, `clear` and `drop_pending` notify the waiters.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_long_poll.py`:

```python
"""P07-T06: chat.events.poll long-poll with wait_ms (§2d M2)."""
from __future__ import annotations

import threading
import time

import pytest

from helpers.app_driver import call, make_token_app, result, state_of
from helpers.events_v2 import start_v2
from vmd_ai_runtime.constants import CAPABILITIES
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.protocol import MAX_WAIT_MS, validate_method_params


def _session(tmp_path):
    app = make_token_app(tmp_path)
    return app, start_v2(app, tmp_path)


def _poll(app, session, after_seq, wait_ms):
    t0 = time.monotonic()
    reply = result(call(app, "chat.events.poll",
                        {"after_seq": after_seq, "limit": 50, "wait_ms": wait_ms}, session))
    return reply, time.monotonic() - t0


def test_immediate_when_pending(tmp_path):
    app, session = _session(tmp_path)                 # session.start queued two events
    reply, elapsed = _poll(app, session, 0, 2000)
    assert reply["events"][0]["text"] == "session_started"
    assert elapsed < 0.2


def test_wakes_on_push(tmp_path):
    app, session = _session(tmp_path)
    queue = state_of(app, session).queue
    last = queue.last_seq
    timer = threading.Timer(0.3, lambda: queue.push("system", "lifecycle", "ping"))
    timer.start()
    try:
        reply, elapsed = _poll(app, session, last, 2000)
    finally:
        timer.cancel()
    assert [e["text"] for e in reply["events"]] == ["ping"]
    assert 0.25 <= elapsed < 1.5


def test_times_out_empty(tmp_path):
    app, session = _session(tmp_path)
    last = state_of(app, session).queue.last_seq
    reply, elapsed = _poll(app, session, last, 300)
    assert reply == {"events": [], "last_seq": last, "has_more": False}
    assert 0.28 <= elapsed < 1.0


def test_wait_ms_clamped_2000():
    assert MAX_WAIT_MS == 2000
    params = validate_method_params("chat.events.poll", {"session_id": "s", "after_seq": 0, "wait_ms": 60000})
    assert params["wait_ms"] == 2000
    assert "wait_ms" not in validate_method_params("chat.events.poll", {"session_id": "s"})
    with pytest.raises(RpcError) as info:
        validate_method_params("chat.events.poll", {"session_id": "s", "wait_ms": -1})
    assert info.value.code == "INVALID_PARAMS"


def test_after_seq_ahead_returns_promptly(tmp_path):
    """Review focus 3: a cursor beyond last_seq never sleeps; the reply carries the real last_seq."""
    app, session = _session(tmp_path)
    last = state_of(app, session).queue.last_seq
    reply, elapsed = _poll(app, session, last + 500, 2000)
    assert reply == {"events": [], "last_seq": last, "has_more": False}
    assert elapsed < 0.2
    plain = result(call(app, "chat.events.poll", {"after_seq": last + 500, "limit": 50}, session))
    assert plain["last_seq"] == last + 500            # the M1 short-poll keeps today's echo


def test_capability_advertised(tmp_path):
    app = make_token_app(tmp_path)
    token = start_v2(app, tmp_path, event_protocol=1)
    assert token.result["capabilities"] == dict(CAPABILITIES, long_poll=True)
    tokenless = start_v2(app, tmp_path, token="")
    assert tokenless.result["capabilities"] == CAPABILITIES
    assert "long_poll" not in CAPABILITIES            # the shared constant is not mutated


def test_queue_wait_unit():
    queue = EventQueue()
    t0 = time.monotonic()
    assert queue.wait(0, 0.2) is False
    assert 0.18 <= time.monotonic() - t0 < 1.0
    queue.push("system", "lifecycle", "a")
    t0 = time.monotonic()
    assert queue.wait(0, 2.0) is True and time.monotonic() - t0 < 0.1
    assert queue.wait(7, 2.0) is True                 # ahead of the queue: returns at once
    queue.drop_pending()
    assert queue.wait(1, 0.05) is False               # seq kept, nothing newer queued
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_long_poll.py -q 2>&1 | tail -4`
Expected: a collection error, `ImportError: cannot import name 'MAX_WAIT_MS' from 'vmd_ai_runtime.protocol'`.

- [ ] **Step 3: Validate `wait_ms` in `runtime/vmd_ai_runtime/protocol.py`**

Directly after the line `EVENT_PROTOCOLS = (1, 2)` insert:

```python

# M2 long-poll (§2d): chat.events.poll holds the request at most this long.
MAX_WAIT_MS = 2000
```

Replace the `chat.events.poll` validator:

```python
    if method == "chat.events.poll":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "after_seq": _as_int(p.get("after_seq"), "after_seq", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=50),
        }
```

with:

```python
    if method == "chat.events.poll":
        out = {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "after_seq": _as_int(p.get("after_seq"), "after_seq", minimum=0, default=0),
            "limit": _as_int(p.get("limit"), "limit", minimum=1, default=50),
        }
        # M2 long-poll (§2d): passed through only when present, so a v1
        # short-poll gets exactly today's params; clamped to 2000 ms.
        if p.get("wait_ms") is not None:
            out["wait_ms"] = min(_as_int(p.get("wait_ms"), "wait_ms", minimum=0, default=0), MAX_WAIT_MS)
        return out
```

- [ ] **Step 4: Add `wait` to `runtime/vmd_ai_runtime/events.py`**

Replace the whole file (the Task 5 version) with:

```python
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

from .constants import EVENT_ROLES, EVENT_TYPES

# Delivered events kept for a re-poll after a transport blip (§2c Sequence numbers).
DEFAULT_TRIM_AFTER = 1000


class EventQueue:
    """One session's event queue, polled by the plugin (§2c).

    ``seq`` only grows. ``drop_pending`` (a token session's chat.resume)
    empties the queue without resetting it; only ``clear`` (a tokenless
    chat.resume, today's behaviour) resets it. A poll with ``after_seq = N``
    confirms delivery of events up to N. Beyond the newest ``trim_after``
    delivered events the oldest are dropped, and undelivered events are
    never trimmed. ``wait`` blocks a long-poll until ``push`` notifies it
    (§2d M2).
    """

    def __init__(self, trim_after: int = DEFAULT_TRIM_AFTER) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._events: List[Dict[str, Any]] = []
        self._seq = 0
        self._delivered = 0
        self.trim_after = max(0, int(trim_after))

    def push(self, role: str, event_type: str, text: str, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if role not in EVENT_ROLES:
            raise ValueError(f"Unsupported role: {role}")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported event type: {event_type}")
        item = {
            "seq": 0,
            "ts": time.time(),
            "role": role,
            "type": event_type,
            "text": str(text or ""),
            "metadata": dict(metadata or {}),
        }
        with self._cond:
            self._seq += 1
            item["seq"] = self._seq
            self._events.append(item)
            self._cond.notify_all()
        return item

    def clear(self) -> None:
        """Drop all events and reset the sequence counter (tokenless chat.resume)."""
        with self._cond:
            self._events.clear()
            self._seq = 0
            self._delivered = 0
            self._cond.notify_all()

    def drop_pending(self) -> int:
        """Drop every queued event but keep ``seq`` (a token session's chat.resume, §2c).

        Returns how many events were dropped.
        """
        with self._cond:
            dropped = len(self._events)
            self._events.clear()
            self._cond.notify_all()
            return dropped

    @property
    def last_seq(self) -> int:
        """Sequence number of the newest event pushed (0 when none)."""
        with self._lock:
            return self._seq

    def wait(self, after_seq: int, timeout_s: float) -> bool:
        """Block until an event newer than ``after_seq`` is queued (True) or
        ``timeout_s`` passes (False) (§2d M2 long-poll).

        Returns True at once when such an event is already queued. It also
        returns True at once when ``after_seq`` is ahead of this queue (a
        client out of step with a new or reset queue), so a long-poll never
        sleeps on a cursor that cannot advance.
        """
        safe_after = max(0, int(after_seq or 0))
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._cond:
            while True:
                if safe_after > self._seq:
                    return True
                if self._events and int(self._events[-1].get("seq") or 0) > safe_after:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(remaining)

    def poll(self, after_seq: int, limit: int) -> Dict[str, Any]:
        safe_after = max(0, int(after_seq or 0))
        safe_limit = max(1, min(int(limit or 50), 500))
        with self._lock:
            # Polling past an event confirms its delivery.
            if safe_after > self._delivered:
                self._delivered = min(safe_after, self._seq)
            self._trim_locked()
            items = [e for e in self._events if int(e.get("seq") or 0) > safe_after]
            batch = items[:safe_limit]
            last_seq = int(batch[-1]["seq"]) if batch else safe_after
            has_more = len(items) > len(batch)
            return {
                "events": batch,
                "last_seq": last_seq,
                "has_more": has_more,
            }

    def _trim_locked(self) -> None:
        """Keep at most ``trim_after`` delivered events (a prefix, since seq only grows)."""
        delivered = 0
        for event in self._events:
            if int(event.get("seq") or 0) > self._delivered:
                break
            delivered += 1
        excess = delivered - self.trim_after
        if excess > 0:
            del self._events[:excess]


def display_log(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The events a resumed chat replays through vm::apply (§2c Persistence, §7).

    * role=tool_start (the execution channel) is never replayed.
    * A v1 chunk is dropped when its request also stored an assistant
      message, so a log that mixes M1 (v1) and M2 (v2) requests replays
      without duplicates. A request that never stored a message keeps its
      chunks.

    Everything else keeps its order.
    """
    sealed = {
        str((e.get("metadata") or {}).get("request_id") or "")
        for e in events
        if e.get("role") == "assistant" and e.get("type") == "message"
    }
    out: List[Dict[str, Any]] = []
    for event in events:
        if event.get("role") == "tool_start":
            continue
        if event.get("type") == "chunk":
            request_id = str((event.get("metadata") or {}).get("request_id") or "")
            if request_id and request_id in sealed:
                continue
        out.append(event)
    return out
```

- [ ] **Step 5: Long-poll in the RPC and advertise it (`runtime/vmd_ai_runtime/app.py`)**

Replace the `chat.events.poll` branch:

```python
        if method == "chat.events.poll":
            state = self._get_session(params["session_id"], session_token)
            polled = state.queue.poll(
                after_seq=params["after_seq"], limit=params["limit"]
            )
            return polled
```

with:

```python
        if method == "chat.events.poll":
            state = self._get_session(params["session_id"], session_token)
            wait_ms = int(params.get("wait_ms") or 0)
            if wait_ms > 0:
                # M2 long-poll (§2d): hold the request until an event newer
                # than after_seq is queued or wait_ms passes. No lock is held
                # while waiting (the server runs one thread per request).
                state.queue.wait(params["after_seq"], wait_ms / 1000.0)
                last_seq = state.queue.last_seq
                if params["after_seq"] > last_seq:
                    # The client's cursor is ahead of this queue (a restarted
                    # runtime or a reset queue): answer at once with the real
                    # last_seq so the client can resync.
                    return {"events": [], "last_seq": last_seq, "has_more": False}
            polled = state.queue.poll(
                after_seq=params["after_seq"], limit=params["limit"]
            )
            return polled
```

In the `session.start` branch, directly after the line `result["runtime"] = {"version": RUNTIME_VERSION, "pid": os.getpid()}`, insert (same indentation):

```python
                # M2 long-poll (§2d); tokenless sessions keep today's capabilities.
                result["capabilities"] = dict(CAPABILITIES, long_poll=True)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_long_poll.py tests/test_event_seq.py tests/test_events.py tests/test_protocol.py tests/test_launch_token.py -q 2>&1 | tail -2`
Expected: all passed (`7 passed` in `test_long_poll.py`), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+45 passed`, 0 failed, still under 60 s (the long-poll tests add about 1 s).

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/events.py runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/protocol.py tests/test_long_poll.py
git commit -m "feat(runtime): long-poll chat.events.poll with wait_ms (P07-T06)

chat.events.poll accepts wait_ms (clamped to 2000) and blocks on a
Condition that push notifies; pending events return at once, an idle
queue returns empty after wait_ms, and a cursor ahead of the queue returns
at once with the real last_seq. Token sessions see
capabilities.long_poll; v1 short-poll params and results are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: P07-T07 — profiles.* RPCs

**Files:**
- Create: `tests/test_profiles_rpcs.py`
- Modify: `runtime/vmd_ai_runtime/protocol.py`:
  - New helper `_as_profile_key`, before `def validate_rpc_payload(`.
  - New validators `profiles.list`, `profiles.save`, `profiles.delete` and `profiles.activate`, before the final `raise RpcError("METHOD_NOT_FOUND", …)` (6f5f937: line 161).
- Modify: `runtime/vmd_ai_runtime/app.py`:
  - A new `profiles.*` branch before the final `raise RpcError("METHOD_NOT_FOUND", …)` of `_dispatch` (6f5f937: line 518).
  - New methods `_profiles_rpc` and `_keep_num_ctx`, after plan 03's `_provider_set_profile`.

**Interfaces:**
- Consumes: SettingsStore (P03-T05); provider_catalog.model_capabilities (P03-T07). Also used:
  - `RuntimeApp._capabilities_for(profile)`, which calls `provider_catalog.ollama_show` and `model_capabilities` (P03-T09).
  - `RuntimeApp._settings_rpc_error(exc)` (P03-T09): `IN_USE` and `NOT_FOUND` stay as they are; `READ_ONLY` and `INVALID` become `INVALID_PARAMS`.
  - `RuntimeApp._require_auth(state)` (P02-T02); `settings_store.normalize_provider`, `SettingsError` (P03-T05).
  - `protocol._PROFILE_NAME_RE` (P03-T09); `RuntimeApp._profile_loop_factory` (P03-T08), patched in one test.
- Produces:
  - profiles.list -> {active, profiles, settings_source}
  - profiles.save {name, profile, activate?} -> {ok, capabilities}
  - profiles.delete {name} -> {ok} or IN_USE
  - profiles.activate {name} -> {ok, capabilities}
  - (plan additions)
    - `protocol._as_profile_key(value) -> str` (a required name).
    - `RuntimeApp._profiles_rpc(method, params) -> Dict`.
    - `RuntimeApp._keep_num_ctx(existing, profile) -> Dict` (staticmethod; C7 Model change: when `profiles.save` replaces a same-provider profile, the stored `options.num_ctx` is kept unless the new profile sets one).
    - Errors:
      - Every method needs a token session (`AUTH_REQUIRED`).
      - A runtime without a settings store answers `INVALID_PARAMS` with `data.reason: "no_settings_store"`.
      - An unknown name gives `NOT_FOUND`.
      - A bad name, profile or `activate` gives `INVALID_PARAMS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profiles_rpcs.py`:

```python
"""P07-T07: profiles.list / save / delete / activate (§3 RPC table, C7)."""
from __future__ import annotations

import threading

import pytest

from helpers.app_driver import call, error_code, make_token_app, result, send, wait_idle
from helpers.events_v2 import MetaScriptedLoop, ScriptTurn, of_kind, poll_all, start_v2
from vmd_ai_runtime import provider_catalog
from vmd_ai_runtime.settings_store import SettingsStore

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b",
        "options": {"num_ctx": 16384}}
LLAMA = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "llama3.1:8b", "options": {}}
CLAUDE = {"provider": "anthropic-direct", "model": "claude-sonnet-4-6", "options": {}}
OLLAMA_CAPS = {"tools": True, "vision": True, "thinking": False}
CLAUDE_CAPS = {"tools": True, "vision": True, "thinking": False}


@pytest.fixture
def show(monkeypatch):
    """provider_catalog.ollama_show without a server: tools and vision, no thinking."""
    calls = []

    def fake_show(base_url, model, timeout=3.0):
        calls.append((base_url, model))
        return {"capabilities": ["completion", "tools", "vision"]}

    monkeypatch.setattr(provider_catalog, "ollama_show", fake_show)
    return calls


def _app(tmp_path, **profiles):
    """An app that owns ~/.vmdai/settings.json; the first profile given is active."""
    store = SettingsStore()
    for index, (name, profile) in enumerate(profiles.items()):
        store.save_profile(name, profile, activate=(index == 0))
    return make_token_app(tmp_path, settings_store=store), store


def test_list(tmp_path, show):
    app, _store = _app(tmp_path, qwen=QWEN, claude=CLAUDE)
    session = start_v2(app, tmp_path, event_protocol=1)       # any token session
    assert result(call(app, "profiles.list", {}, session)) == {
        "active": "qwen", "profiles": {"qwen": QWEN, "claude": CLAUDE}, "settings_source": "file"}


def test_save_activate_capabilities(tmp_path, show):
    app, store = _app(tmp_path, qwen=QWEN)
    session = start_v2(app, tmp_path)
    saved = result(call(app, "profiles.save", {"name": "llama", "profile": LLAMA, "activate": True}, session))
    assert saved == {"ok": True, "capabilities": OLLAMA_CAPS}
    assert store.active_profile() == ("llama", LLAMA)
    assert show == [("http://127.0.0.1:9", "llama3.1:8b")]
    assert result(call(app, "profiles.save", {"name": "claude", "profile": CLAUDE}, session)) == {
        "ok": True, "capabilities": CLAUDE_CAPS}
    assert store.active_profile()[0] == "llama"                # save without activate keeps the active one
    assert result(call(app, "profiles.activate", {"name": "claude"}, session)) == {
        "ok": True, "capabilities": CLAUDE_CAPS}
    assert store.active_profile()[0] == "claude"
    for bad in ({"name": "../x", "profile": LLAMA},
                {"name": "x", "profile": "ollama"},
                {"name": "x", "profile": {"provider": "nope", "model": "m"}},
                {"name": "x", "profile": LLAMA, "activate": "yes"},
                {"profile": LLAMA}):
        assert error_code(call(app, "profiles.save", bad, session)) == "INVALID_PARAMS", bad


def test_delete_active_in_use(tmp_path, show):
    app, store = _app(tmp_path, qwen=QWEN, claude=CLAUDE)
    session = start_v2(app, tmp_path)
    assert error_code(call(app, "profiles.delete", {"name": "qwen"}, session)) == "IN_USE"
    assert result(call(app, "profiles.delete", {"name": "claude"}, session)) == {"ok": True}
    assert set(store.list_profiles()) == {"qwen"}
    assert error_code(call(app, "profiles.delete", {"name": "claude"}, session)) == "NOT_FOUND"
    assert error_code(call(app, "profiles.activate", {"name": "claude"}, session)) == "NOT_FOUND"


def test_activate_applies_next_request(tmp_path, show, monkeypatch):
    app, _store = _app(tmp_path, qwen=QWEN, llama=LLAMA)
    gate = threading.Event()

    def factory(profile):
        # One scripted loop per request, built from the profile the request starts with.
        return MetaScriptedLoop([ScriptTurn(text="answered by " + profile["model"],
                                            before=lambda: gate.wait(5))], model=profile["model"])

    monkeypatch.setattr(app, "_profile_loop_factory", factory)
    session = start_v2(app, tmp_path)
    first = result(send(app, session, "one"))
    assert result(call(app, "profiles.activate", {"name": "llama"}, session))["ok"] is True
    gate.set()                                               # the running request keeps its loop
    wait_idle(app, session)
    second = result(send(app, session, "two"))
    wait_idle(app, session)
    events = poll_all(app, session)
    assert [(m["request_id"], m["model"]) for m in of_kind(events, "request.started")] == [
        (first["request_id"], "qwen3.8:27b"), (second["request_id"], "llama3.1:8b")]
    finals = [e["text"] for e in events if e["role"] == "assistant" and e["type"] == "message"]
    assert finals == ["answered by qwen3.8:27b", "answered by llama3.1:8b"]


def test_all_require_auth(tmp_path, show):
    app, _store = _app(tmp_path, qwen=QWEN)
    tokenless = start_v2(app, tmp_path, token="")
    for method, params in (("profiles.list", {}), ("profiles.save", {"name": "x", "profile": LLAMA}),
                           ("profiles.delete", {"name": "qwen"}), ("profiles.activate", {"name": "qwen"})):
        assert error_code(call(app, method, params, tokenless)) == "AUTH_REQUIRED", method
    bare = make_token_app(tmp_path / "bare")                  # a runtime without a settings store
    session = start_v2(bare, tmp_path / "bare")
    envelope = call(bare, "profiles.list", {}, session)
    assert error_code(envelope) == "INVALID_PARAMS"
    assert envelope["error"]["data"] == {"reason": "no_settings_store"}


def test_save_keeps_num_ctx_on_model_change(tmp_path, show):
    """C7: a model change keeps the stored num_ctx unless the same call sets one."""
    app, store = _app(tmp_path, qwen=QWEN)
    session = start_v2(app, tmp_path)
    newer = dict(QWEN, model="qwen3.8:32b", options={})
    result(call(app, "profiles.save", {"name": "qwen", "profile": newer}, session))
    assert store.get_profile("qwen")["options"] == {"num_ctx": 16384}
    result(call(app, "profiles.save", {"name": "qwen", "profile": dict(newer, options={"num_ctx": 8192})}, session))
    assert store.get_profile("qwen")["options"] == {"num_ctx": 8192}
    vllm = {"provider": "openai-compatible", "base_url": "http://localhost:8000/v1", "model": "Qwen/Qwen3-8B",
            "options": {}}
    result(call(app, "profiles.save", {"name": "qwen", "profile": vllm}, session))
    assert store.get_profile("qwen")["options"] == {}          # not carried to another provider
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_profiles_rpcs.py -q 2>&1 | tail -4`
Expected: `6 failed`. Each one fails on an `AssertionError` whose envelope carries `'code': 'METHOD_NOT_FOUND', 'message': 'Unknown method: profiles.…'`, or, for `test_all_require_auth`, on `assert 'METHOD_NOT_FOUND' == 'AUTH_REQUIRED'`.

- [ ] **Step 3: Validate the new methods in `runtime/vmd_ai_runtime/protocol.py`**

Insert directly before `def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:`:

```python
def _as_profile_key(value: Any) -> str:
    """A required profile name: 1-64 letters, digits, '.', '_' or '-' (profiles.*)."""
    text = _as_str(value, "name")
    if not _PROFILE_NAME_RE.match(text):
        raise RpcError("INVALID_PARAMS", "name must be 1-64 letters, digits, '.', '_' or '-'",
                       {"name": text[:80]})
    return text


```

Insert directly before the final `    raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")` of `validate_method_params`:

```python
    # ---- profiles.* (§3; the M2 settings dialog; token sessions only, checked in app.py) ----

    if method == "profiles.list":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method in ("profiles.delete", "profiles.activate"):
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "name": _as_profile_key(p.get("name")),
        }

    if method == "profiles.save":
        profile = p.get("profile")
        if not isinstance(profile, dict):
            raise RpcError("INVALID_PARAMS", "profile must be an object")
        activate = p.get("activate", False)
        if not isinstance(activate, bool):
            raise RpcError("INVALID_PARAMS", "activate must be true or false")
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "name": _as_profile_key(p.get("name")),
            "profile": profile,
            "activate": activate,
        }

```

- [ ] **Step 4: Serve them in `runtime/vmd_ai_runtime/app.py`**

Insert directly before the final `        raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")` of `_dispatch`:

```python
        # ---- Profiles (§3 RPC table; the M2 settings dialog) ----

        if method in ("profiles.list", "profiles.save", "profiles.delete", "profiles.activate"):
            state = self._get_session(params["session_id"], session_token)
            self._require_auth(state)
            return self._profiles_rpc(method, params)

```

Add these methods directly after `_provider_set_profile` (plan 03):

```python
    def _profiles_rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """profiles.list / save / delete / activate (§3; the M2 settings dialog).

        Changes apply to the next request. chat.send builds each request's
        loop from the active profile (P03-T08), so a running request keeps
        the loop it started with.
        """
        store = self.settings_store
        if store is None:
            raise RpcError("INVALID_PARAMS", "this runtime does not manage ~/.vmdai/settings.json",
                           {"reason": "no_settings_store"})
        try:
            if method == "profiles.list":
                data = store.load()
                return {
                    "active": data.get("active"),
                    "profiles": store.list_profiles(),
                    "settings_source": store.settings_source,
                }
            name = params["name"]
            if method == "profiles.delete":
                store.delete_profile(name)                 # IN_USE for the active profile
                return {"ok": True}
            if method == "profiles.activate":
                store.activate(name)
                return {"ok": True, "capabilities": self._capabilities_for(store.get_profile(name) or {})}
            profile = self._keep_num_ctx(store.get_profile(name), params["profile"])
            saved = store.save_profile(name, profile, activate=bool(params.get("activate")))
            return {"ok": True, "capabilities": self._capabilities_for(saved)}
        except SettingsError as exc:
            raise self._settings_rpc_error(exc)

    @staticmethod
    def _keep_num_ctx(existing: Optional[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
        """C7 Model change: replacing a same-provider profile keeps its stored
        options.num_ctx unless the new profile sets one (changing num_ctx
        reloads the model on the server)."""
        out = dict(profile)
        if not isinstance(existing, dict):
            return out
        if normalize_provider(existing.get("provider")) != normalize_provider(out.get("provider")):
            return out
        stored = (existing.get("options") or {}).get("num_ctx")
        options = out.get("options")
        if options is None:
            options = {}
        if stored is not None and isinstance(options, dict) and "num_ctx" not in options:
            options = dict(options)
            options["num_ctx"] = stored
            out["options"] = options
        return out
```

(`SettingsError` and `normalize_provider` are already imported from `.settings_store` by plan 03.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_profiles_rpcs.py tests/test_runtime_info_rpcs.py tests/test_settings_store.py tests/test_protocol.py -q 2>&1 | tail -2`
Expected: all passed (`6 passed` in `test_profiles_rpcs.py`), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+51 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/protocol.py runtime/vmd_ai_runtime/app.py tests/test_profiles_rpcs.py
git commit -m "feat(runtime): profiles.list/save/delete/activate RPCs (P07-T07)

Token sessions can list, save (create or replace), delete and activate
settings.json profiles; save and activate report the model's tools,
vision and thinking capabilities, deleting the active profile is IN_USE,
and changes apply from the next request. Replacing a same-provider
profile keeps its num_ctx unless the call sets one (C7).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: P07-T08 — Scenario event fixtures recorded from the runtime

**Files:**
- Create: `tests/helpers/make_event_fixtures.py`
- Create: `tests/test_event_fixtures.py`
- Create (generated by Step 4, then committed):
  - `tests/fixtures/events/03_conversation.jsonl`
  - `tests/fixtures/events/11_dead_runtime.jsonl`
  - `tests/fixtures/events/reasoning_answer.jsonl`
  - `tests/fixtures/events/turn_retry.jsonl`
  - `tests/fixtures/events/loop_guard.jsonl`

**Interfaces:**
- Consumes: ScriptedLoopFactory (P06-T11) is *not* used (see Deviations 11); v2 events (P07-T01..T03). Also used: `MetaScriptedLoop`, `ScriptTurn`, `ProductBridge`, `product_result`, `run_cmd`, `tool_block`, `start_v2`, `poll_all` (Task 1); `helpers.app_driver.make_token_app`, `send`, `result`, `call`, `wait_idle` (P03-T04); the loop guard and wrap-up (P05-T09); sealed reasoning (Task 4).
- Produces:
  - five fixture files, one §2c envelope per line
  - plugin-local kinds in fixtures: local.connection {state, detail, request_lost}, local.request_ended {request_id}, local.send_failed {code, message}
  - (plan additions) The fixture format, which plans 08–10 rely on:
    - **Lines.** Each line is `json.dumps(event, sort_keys=True, ensure_ascii=True)` of `{seq, ts, role, type, text, metadata}`, the same ASCII JSON the wire carries.
    - **What is recorded.** The runtime events are exactly what the v2 session polled, including the `session_started` lifecycle event and the security notice. They exclude `role=tool_start`, because `ProductBridge` stands in for the executor.
    - **Normalisation.**
      - `ts` becomes `1790208000.0 + 0.5 × line`.
      - `duration_ms` is 500 ms per line between the start line and the end line: `tool.started`→`tool.finished` by `call_key`, `request.started`→`request.finished` by `request_id`, and the first reasoning chunk→`reasoning/message` by turn.
      - `req_…`, `chat_…` and `sess_…` ids and call keys are numbered in order of appearance: `req_000000000001`, `chat_000000000001`, `000000000001`.
      - The repository root becomes `@REPO@` and the scenario's temp dir becomes `@WORK@`. The snapshot image is `@REPO@/docs/design/round1/assets/snap_1hck.png`, 1280×1547.
    - **Plugin-local events** (11_dead_runtime only) have `seq: 0`, `role: "system"`, `type: "state"` and `metadata {kind, v: 2, …fields}`.
    - **Module API.** `SCENARIOS`, `generate(name, work) -> List[Dict]`, `normalise(events, work) -> List[Dict]`, `dumps(events) -> str`, `fixture_path(name) -> Path`, `read_fixture(name) -> List[Dict]` and `update_goldens() -> bool`; the scenario text constants `CONVERSATION_PROMPTS`, `CONVERSATION_FINALS`, `REASONING_1`, `REASONING_2`, `TURN_RETRY_STREAMED`, `TURN_RETRY_SEALED` and `LOOP_GUARD_WRAP_UP`.

- [ ] **Step 1: Write the generator**

Create `tests/helpers/make_event_fixtures.py`:

```python
"""Generate the five v2 scenario event fixtures from the runtime (§6, C4).

Each scenario drives RuntimeApp in process: a token session that negotiated
event_protocol 2, a scripted model (helpers.events_v2.MetaScriptedLoop, which
streams reasoning, usage and status through the loop's own on_meta path) and
a product-shaped bridge. What the session polls is normalised and written one
§2c envelope per line to tests/fixtures/events/<name>.jsonl.
tests/test_event_fixtures.py regenerates every fixture and compares it with
the file; CHATVMD_UPDATE_GOLDENS=1 rewrites the files.

Normalisation (stable across runs and machines):
  * ts          -> 1790208000.0 + 0.5 s per line
  * duration_ms -> 500 ms per line from the start line to the end line
                   (tool.started -> tool.finished by call_key,
                    request.started -> request.finished by request_id,
                    first reasoning chunk -> reasoning/message by turn)
  * req_/chat_/sess_ ids and call keys -> numbered in order of appearance
                   (req_000000000001, chat_000000000001, 000000000001)
  * repository root -> @REPO@, the scenario's temp dir -> @WORK@
11_dead_runtime ends with plugin-local events (seq 0) the M2 plugin emits
itself after the runtime dies: local.connection, local.send_failed,
local.request_ended.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Sequence

from helpers.app_driver import call, make_token_app, result, send, wait_idle
from helpers.events_v2 import (MetaScriptedLoop, ProductBridge, ScriptTurn, poll_all, product_result,
                               run_cmd, start_v2, tool_block)

REPO = Path(__file__).resolve().parents[2]
EVENTS_DIR = REPO / "tests" / "fixtures" / "events"
SCENARIOS = ("03_conversation", "11_dead_runtime", "reasoning_answer", "turn_retry", "loop_guard")
BASE_TS = 1790208000.0          # 2026-09-24T00:00:00Z
STEP_S = 0.5                    # normalised seconds between consecutive lines
SNAPSHOT_PNG = REPO / "docs" / "design" / "round1" / "assets" / "snap_1hck.png"   # 1280 x 1547

CONVERSATION_PROMPTS = ("load 1hck and show it as a cartoon", "what is its radius of gyration?")
CONVERSATION_FINALS = ("Loaded **1hck** as a cartoon on a white background.",
                       "The radius of gyration is 20.84 Å.")
REASONING_1 = "The user wants the atom count. A selection of all atoms gives it."
REASONING_2 = "The selection reported 2442 atoms, so that is the answer."
TURN_RETRY_STREAMED = "Loading 1hLoading 1hck now."
TURN_RETRY_SEALED = "Loading 1hck now."
LOOP_GUARD_WRAP_UP = ("I could not color by residue type: VMD rejected `mol modcolor 0 top ResidueType` "
                      "four times, so the scene is unchanged. The coloring method is called `ResType`; "
                      "try `mol modcolor 0 top ResType`.")


def update_goldens() -> bool:
    return os.environ.get("CHATVMD_UPDATE_GOLDENS") == "1"


def fixture_path(name: str) -> Path:
    return EVENTS_DIR / ("%s.jsonl" % name)


def dumps(events: Sequence[Dict[str, Any]]) -> str:
    """One ASCII JSON envelope per line, keys sorted."""
    return "".join(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n" for event in events)


def read_fixture(name: str) -> List[Dict[str, Any]]:
    text = fixture_path(name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def generate(name: str, work: Path) -> List[Dict[str, Any]]:
    """Run scenario ``name`` against a fresh RuntimeApp rooted in ``work``; normalised events."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    return normalise(_BUILDERS[name](work), work)


# --- running a scenario ------------------------------------------------------

@contextlib.contextmanager
def _recorder_off() -> Iterator[None]:
    """No .vmdai_runs run directories (request.finished.run_dir is then null)."""
    old = os.environ.get("VMD_AI_RECORDER")
    os.environ["VMD_AI_RECORDER"] = "off"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("VMD_AI_RECORDER", None)
        else:
            os.environ["VMD_AI_RECORDER"] = old


def _usage(evaluated: int, out: int) -> Dict[str, Any]:
    return {"input_tokens_evaluated": evaluated, "output_tokens": out, "cache_read_tokens": None,
            "source": "ollama"}


def _run_requests(work: Path, script: List[ScriptTurn], results: List[Any], prompts: Sequence[str],
                  *, wrap_up_text: str = "") -> List[Dict[str, Any]]:
    with _recorder_off():
        app = make_token_app(work)
        app.claude_loop = MetaScriptedLoop(script, wrap_up_text=wrap_up_text)
        app.tool_bridge = ProductBridge(results)
        session = start_v2(app, work)
        for prompt in prompts:
            result(send(app, session, prompt))
            wait_idle(app, session, timeout=10.0)
        return poll_all(app, session)


def _poll_until(app, session, predicate: Callable[[Dict[str, Any]], bool],
                timeout: float = 10.0) -> List[Dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = poll_all(app, session)
        if any(predicate(event) for event in events):
            return events
        time.sleep(0.01)
    raise AssertionError("the scenario never reached the expected event")


def _local(kind: str, **fields: Any) -> Dict[str, Any]:
    """A plugin-local event (never sent by the runtime, so seq 0)."""
    metadata: Dict[str, Any] = {"kind": kind, "v": 2}
    metadata.update(fields)
    return {"seq": 0, "ts": 0.0, "role": "system", "type": "state", "text": "", "metadata": metadata}


# --- the five scenarios ------------------------------------------------------

def _conversation(work: Path) -> List[Dict[str, Any]]:
    """Two requests: prose, a command that works, a failing then recovered command, a snapshot, answers."""
    image = {"path": str(SNAPSHOT_PNG), "thumb_path": str(SNAPSHOT_PNG), "width": 847, "height": 1024,
             "src_width": 1280, "src_height": 1547, "renderer": "TachyonInternal"}
    failed = {"index": 2, "text": "display backgroundcolor white",
              "error_info": 'display: invalid option "backgroundcolor"\n    while executing\n'
                            '"display backgroundcolor white"'}
    script = [
        ScriptTurn(text="I'll load 1hck and show it as a cartoon.",
                   tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb\nmol delrep 0 top\n"
                                        "mol representation NewCartoon\nmol addrep top",
                                        "Load the structure and draw it as a cartoon.")],
                   usage=_usage(5120, 61)),
        ScriptTurn(tool_blocks=[run_cmd("tc_2", "color Display Background white\ndisplay backgroundcolor white",
                                        "Make the background white.")], usage=_usage(5390, 38)),
        ScriptTurn(text="`display backgroundcolor` does not exist; the color command alone is enough.",
                   tool_blocks=[run_cmd("tc_3", "color Display Background white",
                                        "Set the background with the supported command.")],
                   usage=_usage(5520, 44)),
        ScriptTurn(tool_blocks=[tool_block("tc_4", "capture_vmd_snapshot", purpose="check the cartoon")],
                   usage=_usage(5610, 20)),
        ScriptTurn(text=CONVERSATION_FINALS[0], usage=_usage(6710, 25)),
        ScriptTurn(tool_blocks=[run_cmd("tc_5", "set sel [atomselect top protein]\nmeasure rgyr $sel",
                                        "Radius of gyration of the protein.")], usage=_usage(6900, 35)),
        ScriptTurn(text=CONVERSATION_FINALS[1], usage=_usage(7010, 14)),
    ]
    results = [
        product_result(statements={"total": 4, "applied": 4, "failed": None}, duration_ms=412),
        product_result(ok=False, error='display: invalid option "backgroundcolor"',
                       applied_text="color Display Background white\n",
                       statements={"total": 2, "applied": 1, "failed": failed}, duration_ms=38),
        product_result(statements={"total": 1, "applied": 1, "failed": None}, duration_ms=12),
        product_result(image=image, duration_ms=930),
        product_result(output="20.8431", statements={"total": 2, "applied": 2, "failed": None}, duration_ms=25),
    ]
    return _run_requests(work, script, results, CONVERSATION_PROMPTS)


def _dead_runtime(work: Path) -> List[Dict[str, Any]]:
    """request.started and tool.started, then the runtime dies: local notices, no request.finished."""
    gate = threading.Event()

    def never_answers(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        gate.wait(10)
        return product_result(ok=False, executed="unknown", error="stopped while running; outcome unknown")

    script = [ScriptTurn(text="Loading 1hck.", tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb", "Load it.")],
                         usage=_usage(5120, 30))]
    with _recorder_off():
        app = make_token_app(work)
        app.claude_loop = MetaScriptedLoop(script)
        app.tool_bridge = ProductBridge([never_answers])
        session = start_v2(app, work)
        result(send(app, session, "load 1hck"))
        events = _poll_until(app, session, lambda e: (e.get("metadata") or {}).get("kind") == "tool.started")
        # The runtime "dies" here: nothing it pushes after tool.started is recorded.
        call(app, "chat.cancel", {}, session)
        gate.set()
        wait_idle(app, session, timeout=10.0)
    request_id = next(e["metadata"]["request_id"] for e in events
                      if e["metadata"].get("kind") == "request.started")
    return events + [
        _local("local.connection", state="reconnecting", detail="Runtime not reachable; retry in 0.5 s",
               request_lost=False),
        _local("local.send_failed", code="transport", message="Runtime not reachable"),
        _local("local.connection", state="ready", detail="Reconnected to a new runtime", request_lost=True),
        _local("local.request_ended", request_id=request_id),
    ]


def _reasoning_answer(work: Path) -> List[Dict[str, Any]]:
    """Reasoning in two turns: the reasoning->tool and reasoning->answer boundaries."""
    script = [
        ScriptTurn(reasoning=REASONING_1,
                   tool_blocks=[run_cmd("tc_1", "set sel [atomselect top all]\n$sel num", "Count the atoms.")],
                   usage=_usage(5120, 48)),
        ScriptTurn(reasoning=REASONING_2, text="1hck has 2442 atoms.", usage=_usage(5260, 22)),
    ]
    results = [product_result(output="2442", statements={"total": 2, "applied": 2, "failed": None},
                              duration_ms=18)]
    return _run_requests(work, script, results, ("how many atoms does 1hck have?",))


def _turn_retry(work: Path) -> List[Dict[str, Any]]:
    """A stream that drops mid-turn: the partial block is discarded and the turn retried once."""
    script = [
        ScriptTurn(text="Loading 1h", drop_after_text=True),
        ScriptTurn(text=TURN_RETRY_SEALED, tool_blocks=[run_cmd("tc_1", "mol new 1hck.pdb", "Load it.")],
                   usage=_usage(5120, 30)),
        ScriptTurn(text="Done: 1hck is loaded.", usage=_usage(5200, 12)),
    ]
    results = [product_result(output="0", statements={"total": 1, "applied": 1, "failed": None}, duration_ms=35)]
    return _run_requests(work, script, results, ("load 1hck",))


def _loop_guard(work: Path) -> List[Dict[str, Any]]:
    """C4: the same failing call four times: nudge on the third, stop and wrap up on the fourth."""
    def same(n: int) -> Dict[str, Any]:
        return run_cmd("tc_%d" % n, "mol modcolor 0 top ResidueType", "Color by residue type.")

    error = 'mol modcolor: invalid coloring method "ResidueType"'
    fail = product_result(ok=False, error=error, duration_ms=9,
                          statements={"total": 1, "applied": 0,
                                      "failed": {"index": 1, "text": "mol modcolor 0 top ResidueType",
                                                 "error_info": error}})
    script = [
        ScriptTurn(text="Coloring by residue type.", tool_blocks=[same(1)], usage=_usage(5120, 30)),
        ScriptTurn(tool_blocks=[same(2)], usage=_usage(5300, 26)),
        ScriptTurn(tool_blocks=[same(3)], usage=_usage(5480, 26)),
        ScriptTurn(tool_blocks=[same(4)], usage=_usage(5660, 26)),
    ]
    return _run_requests(work, script, [fail, fail, fail, fail], ("color the protein by residue type",),
                         wrap_up_text=LOOP_GUARD_WRAP_UP)


_BUILDERS: Dict[str, Callable[[Path], List[Dict[str, Any]]]] = {
    "03_conversation": _conversation,
    "11_dead_runtime": _dead_runtime,
    "reasoning_answer": _reasoning_answer,
    "turn_retry": _turn_retry,
    "loop_guard": _loop_guard,
}


# --- normalisation -----------------------------------------------------------

_ID_FAMILIES = (
    (re.compile(r"req_[0-9a-f]{12}"), "req_%012d"),
    (re.compile(r"chat_[0-9a-f]{12}"), "chat_%012d"),
    (re.compile(r"sess_[0-9a-f]{12}"), "sess_%012d"),
)


def normalise(events: Sequence[Dict[str, Any]], work: Path) -> List[Dict[str, Any]]:
    """Make a scenario's events identical across runs and machines (see the module docstring)."""
    out = copy.deepcopy(list(events))
    names: Dict[str, str] = {}
    counters: Dict[str, int] = {}

    def name_for(raw: str, template: str) -> str:
        if raw not in names:
            counters[template] = counters.get(template, 0) + 1
            names[raw] = template % counters[template]
        return names[raw]

    for event in out:                                     # call keys, in order of appearance
        key = (event.get("metadata") or {}).get("call_key")
        if isinstance(key, str) and key:
            name_for(key, "%012d")
    call_keys = dict(names)
    roots = sorted({str(work), os.path.realpath(str(work))}, key=len, reverse=True)

    def fix(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: fix(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fix(v) for v in value]
        if not isinstance(value, str):
            return value
        if value in call_keys:
            return call_keys[value]
        for pattern, template in _ID_FAMILIES:
            value = pattern.sub(lambda m, t=template: name_for(m.group(0), t), value)
        for root in roots:
            value = value.replace(root, "@WORK@")
        return value.replace(str(REPO), "@REPO@")

    out = [fix(event) for event in out]
    start_line: Dict[Any, int] = {}
    for index, event in enumerate(out):
        event["ts"] = round(BASE_TS + STEP_S * index, 3)
        meta = event.get("metadata") or {}
        kind = meta.get("kind")
        if kind == "tool.started":
            start_line[("tool", meta.get("call_key"))] = index
        elif kind == "request.started":
            start_line[("request", meta.get("request_id"))] = index
        elif event.get("role") == "reasoning" and event.get("type") == "chunk":
            start_line.setdefault(("reasoning", meta.get("request_id"), meta.get("turn")), index)
        if "duration_ms" in meta:
            if kind == "tool.finished":
                begin = start_line.get(("tool", meta.get("call_key")), index)
            elif kind == "request.finished":
                begin = start_line.get(("request", meta.get("request_id")), index)
            elif event.get("role") == "reasoning":
                begin = start_line.get(("reasoning", meta.get("request_id"), meta.get("turn")), index)
            else:
                begin = index
            meta["duration_ms"] = int(round((index - begin) * STEP_S * 1000))
    return out
```

- [ ] **Step 2: Write the fixture tests**

Create `tests/test_event_fixtures.py`:

```python
"""P07-T08: the five v2 scenario fixtures stay true to the runtime (§6 Scenario fixtures, C4)."""
from __future__ import annotations

import pytest

from helpers.make_event_fixtures import (CONVERSATION_FINALS, CONVERSATION_PROMPTS, LOOP_GUARD_WRAP_UP,
                                         REASONING_1, REASONING_2, SCENARIOS, TURN_RETRY_SEALED,
                                         TURN_RETRY_STREAMED, dumps, fixture_path, generate,
                                         read_fixture, update_goldens)
from vmd_ai_runtime.constants import EVENT_ROLES, EVENT_TYPES

ENVELOPE_KEYS = {"seq", "ts", "role", "type", "text", "metadata"}


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixtures_match_runtime(name, tmp_path):
    text = dumps(generate(name, tmp_path))
    path = fixture_path(name)
    if update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.is_file(), ("missing %s; create it with "
                            "CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_event_fixtures.py -q" % path)
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_envelopes(name):
    events = read_fixture(name)
    assert events
    for event in events:
        assert set(event) == ENVELOPE_KEYS, event
        assert event["role"] in EVENT_ROLES and event["type"] in EVENT_TYPES, event
        assert event["role"] != "tool_start"
        meta = event["metadata"]
        if "request_id" in meta or str(meta.get("kind", "")).startswith("local."):
            assert meta["v"] == 2, event
    seqs = [e["seq"] for e in events if e["seq"]]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def _meta(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def _messages(events, role):
    return [e for e in events if e["role"] == role and e["type"] == "message"]


def test_contents_03_conversation():
    events = read_fixture("03_conversation")
    assert [e["text"] for e in _messages(events, "user")] == list(CONVERSATION_PROMPTS)
    assert [m["status"] for m in _meta(events, "request.finished")] == ["complete", "complete"]
    finished = _meta(events, "tool.finished")
    assert [m["ok"] for m in finished] == [True, False, True, True, True]
    assert finished[1]["statements"]["failed"]["index"] == 2
    assert finished[3]["image"]["src_width"] == 1280
    assert finished[3]["image"]["thumb_path"] == "@REPO@/docs/design/round1/assets/snap_1hck.png"
    finals = [e["text"] for e in _messages(events, "assistant") if e["metadata"]["final"]]
    assert finals == list(CONVERSATION_FINALS)


def test_contents_11_dead_runtime():
    events = read_fixture("11_dead_runtime")
    kinds = [e["metadata"].get("kind") for e in events]
    assert "request.finished" not in kinds and "tool.finished" not in kinds
    assert kinds.count("tool.started") == 1
    assert kinds[-4:] == ["local.connection", "local.send_failed", "local.connection", "local.request_ended"]
    assert [e["seq"] for e in events[-4:]] == [0, 0, 0, 0]
    assert events[-2]["metadata"]["request_lost"] is True
    started, = _meta(events, "request.started")
    assert events[-1]["metadata"]["request_id"] == started["request_id"]


def test_contents_reasoning_answer():
    events = read_fixture("reasoning_answer")
    sealed = [(e["metadata"]["turn"], e["text"]) for e in _messages(events, "reasoning")]
    assert sealed == [(1, REASONING_1), (2, REASONING_2)]
    for turn in (1, 2):
        chunks = [i for i, e in enumerate(events)
                  if e["role"] == "reasoning" and e["type"] == "chunk" and e["metadata"]["turn"] == turn]
        seal = next(i for i, e in enumerate(events)
                    if e["role"] == "reasoning" and e["type"] == "message" and e["metadata"]["turn"] == turn)
        assert seal == chunks[-1] + 1                     # sealed before anything else of that turn
    assert _meta(events, "request.started")[0]["think"] is True


def test_contents_turn_retry():
    events = read_fixture("turn_retry")
    retry, = _meta(events, "turn.retry")
    assert (retry["turn"], retry["reason"]) == (1, "stream dropped")
    streamed = [e["text"] for e in events
                if e["role"] == "assistant" and e["type"] == "chunk" and e["metadata"]["turn"] == 1]
    assert "".join(streamed) == TURN_RETRY_STREAMED
    assert [e["text"] for e in _messages(events, "assistant") if e["metadata"]["turn"] == 1] == [TURN_RETRY_SEALED]


def test_contents_loop_guard():
    events = read_fixture("loop_guard")
    phases = [m["phase"] for m in _meta(events, "status")]
    assert "loop_detected" in phases and "wrapping_up" in phases
    # C4: the first trigger nudges, the second stops the run.
    assert [m["stop"] for m in _meta(events, "status") if m["phase"] == "loop_detected"] == [False, True]
    finished, = _meta(events, "request.finished")
    assert (finished["status"], finished["wrapped_up"]) == ("stuck", True)
    assert [m["ok"] for m in _meta(events, "tool.finished")] == [False, False, False, False]
    finals = [e["text"] for e in _messages(events, "assistant") if e["metadata"].get("final")]
    assert finals == [LOOP_GUARD_WRAP_UP]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_event_fixtures.py -q 2>&1 | tail -4`
Expected: `15 failed`.
- The five `test_fixtures_match_runtime[…]` fail with `AssertionError: missing …/tests/fixtures/events/<name>.jsonl; create it with CHATVMD_UPDATE_GOLDENS=1 …`.
- The five `test_fixture_envelopes[…]` and the five `test_contents_…` fail with `FileNotFoundError`.

Generation itself must not raise. If it does, the traceback names the plan 05 or plan 07 behaviour that the scenario exercised and did not get; fix that before going on.

- [ ] **Step 4: Generate the fixtures from the runtime**

Run: `CHATVMD_UPDATE_GOLDENS=1 env -u VMD_AI_PROVIDER python -m pytest tests/test_event_fixtures.py -q -k fixtures_match_runtime 2>&1 | tail -2`
Expected: `5 passed` (the files are written).

Run: `head -1 tests/fixtures/events/03_conversation.jsonl && grep -c '' tests/fixtures/events/*.jsonl && grep -c '@REPO@' tests/fixtures/events/03_conversation.jsonl`
Expected:
- The first line is exactly `{"metadata": {"chat_id": null}, "role": "system", "seq": 1, "text": "session_started", "ts": 1790208000.0, "type": "lifecycle"}`.
- The line counts are printed for the five files; `11_dead_runtime.jsonl` is the shortest.
- The last number is `1` (the snapshot's `tool.finished`, whose `path` and `thumb_path` both use `@REPO@`).

Read `tests/fixtures/events/loop_guard.jsonl` once and confirm the order (plan 05 emits the guard's `status` right after the `tool.finished` it judged): three identical failed `tool.finished` rows, a `status` with `phase: "loop_detected"` and `stop: false` (the nudge), the fourth failed row, a second `loop_detected` with `stop: true`, `phase: "wrapping_up"`, the wrap-up turn's `turn.started` and chunks, the wrap-up `assistant/message` with `final: true`, and then `request.finished` with `status: "stuck"` and `wrapped_up: true`.

- [ ] **Step 5: Run the fixture tests (twice: the regeneration must be stable)**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_event_fixtures.py -q 2>&1 | tail -2 && env -u VMD_AI_PROVIDER python -m pytest tests/test_event_fixtures.py -q 2>&1 | tail -2`
Expected: `15 passed` both times.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+66 passed`, 0 failed, under 60 s.

- [ ] **Step 6: Commit**

```bash
git add tests/helpers/make_event_fixtures.py tests/test_event_fixtures.py tests/fixtures/events/03_conversation.jsonl tests/fixtures/events/11_dead_runtime.jsonl tests/fixtures/events/reasoning_answer.jsonl tests/fixtures/events/turn_retry.jsonl tests/fixtures/events/loop_guard.jsonl
git commit -m "test(runtime): five v2 scenario event fixtures recorded from the runtime (P07-T08)

03_conversation, 11_dead_runtime, reasoning_answer, turn_retry and
loop_guard are generated by driving RuntimeApp with a v2 session and a
scripted model, normalised (ts, durations, ids, paths) and compared on
every test run; CHATVMD_UPDATE_GOLDENS=1 rewrites them. 11_dead_runtime
ends with the plugin-local local.connection, local.send_failed and
local.request_ended events that the M2 view-model consumes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Plan exit check

- [ ] Run the three suites and the 3.9 import check:

```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
python -m pytest tests/test_py39_compat.py tests/test_benchmark_golden_requests.py tests/test_benchmark_hashes.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_retry_pin.py -q 2>&1 | tail -1
git status --short
```
Expected:
- `B+66 passed`, 0 failed, under 60 s.
- `90 passed`, then `62 passed`.
- The last pytest line shows all passed (the 3.9 check skips where `/usr/bin/python3` is not 3.9).
- `git status` prints nothing.

- [ ] Exit criteria, each with its tests:
  - **§2c display half:**
    - `test_events_v2_shapes.py` (negotiation, a shape pin per kind, v1 unchanged, no double emission, no `tool_result` for v2).
    - `test_display_log.py::test_one_sealed_reasoning_per_turn`.
  - **request.finished on every path:** `test_request_lifecycle_events.py` (complete, cancelled, the five error codes, unexpected exception, mock, pre-run failure, `NO_MODEL` without events, a crash in the mapping, a failed C4 wrap-up).
  - **Persistence, replay, monotonic seq, long-poll:**
    - `test_display_log.py`
    - `test_event_seq.py`
    - `test_long_poll.py`
  - **profiles.\* RPCs:** `test_profiles_rpcs.py`.
  - **C1/C3/C4/C5 display fields:**
    - `test_tool_finished_fields.py::test_fields_blocked_statements_output_path_image_saved_path` (C1 `blocked`, C3 `statements.failed`, C5 `output_path`/`output_bytes`).
    - C4 `stuck`/`wrapped_up`/`error`: `test_stuck_wrap_up_error_is_message_not_card` and `test_event_fixtures.py::test_contents_loop_guard`.
  - **Five event fixtures:** `test_event_fixtures.py` (regenerated and compared, envelopes and contents).
- [ ] Hand-off to plan 08 (view-model), which reads these fixtures:
  - A live v2 stream carries `reasoning/message` (the sealed reasoning of a turn) right after that turn's last reasoning chunk.
  - `tool.finished` may come twice for one `call_key`; the second has `late: true`, and it can arrive after `request.finished` or during the next request.
  - Image paths in fixtures use the `@REPO@` placeholder.
  - Plugin-local events have `seq: 0` and a `local.` kind.
  - `chat.history.get` for a token session returns the full display log, without `tool_start` and with deduplicated v1 chunks.

## Deviations from skeleton

1. **Task 0 (pre-flight) added.** This plan edits code that plans 02–05 rewrote. The pre-flight checks their interfaces behaviourally in a throwaway pytest file, and prints every edit anchor.
2. **New plan-local helper `tests/helpers/events_v2.py` (Task 1).** It is not in the skeleton's file list. Tasks 1–8 all need one v2 session driver, and the skeleton's helpers cannot express the product result dict or the loop's `on_meta` items. It holds:
   - `MetaScriptedLoop`: a scripted model that streams reasoning, status and usage through the loop's own `on_meta` path, drops a stream once, blocks, raises, or fails the C4 wrap-up.
   - `ProductBridge` and `product_result`: plan-05-shaped results with no plugin.
   - `FakePlugin`: acks and posts by `call_key` against the real `VmdToolBridge`.
3. **P07-T01 does not modify `protocol.py`.** Plan 02 (P02-T02) already validates `event_protocol ∈ {1, 2}` and passes it through, so negotiation is only the answer in `app.py`. Instead, P07-T01 modifies `tests/test_launch_token.py`: plan 02's `test_event_protocol_values` asserted the M1 answer (1) to a request for 2.
4. **`_make_on_event` returns an `_EventMapper`.** It is a callable object, so it matches the skeleton's `Callable[[Dict[str, Any]], None]`. The workers also use its `v2`, `push`, `chat_id` and `run_dir`, and one object per request keeps the turn, the reasoning buffer and the run directory together. Plan 03's `_turn_tracker` is deleted, as P03-T09 anticipated. The rewritten `_run_claude_loop_response` keeps everything plans 03–05 put there (the tokenless-only model override, the Appender, the recorder provenance, `self.provider_name` on the v1 error event), so tokenless tests that assign a scripted loop pass `model=MODEL` to `chat.send`, exactly as a tokenless client names its model.
5. **`request.finished` details (P07-T02).**
   - `error` is the error event's text (a string), or C4's `last_wrap_up_error`, or null.
   - "Failures before the run starts" means failures in the worker before `loop.run`. A `chat.send` that fails before it starts a worker (`NO_MODEL`, `REQUEST_CONFLICT`) is an RPC error with no `request.*` events, as §2f says for `NO_MODEL`.
   - The mock path reports `max_turns: 1`, `vision: false`, `think: null`.
   - `ClaudeLoopError` text is `str(exc)` (no `Agent error:` prefix) for v2; v1 text is unchanged.
6. **The claude_loop change (P07-T03) is only a keyword.** `_tool_finished_meta(..., *, late=False)` lets the app build the late event with the exact loop shape. The late event is pushed only to a v2 session that is still on the call's chat; the `late_result` line of plan 05 is written for every session.
7. **Counting and writes (P07-T04).**
   - `message_count` is recomputed from `events.jsonl` on every manifest touch instead of adding a delta. This is what §7's "recomputed when a manifest is next touched" needs, and it cannot lose counts under concurrent appends.
   - Empty assistant messages (tool-only turns) are not counted.
   - New store methods: `append_display_events` (no manifest touch), `touch_manifest`, `counts_as_message` and `_count_messages`. The v2 display log is appended per event while the manifest is touched at chat.send and at request.finished, so `index.jsonl` grows two rows per request, not one per event.
   - `recount_messages` is also used by a token session's `chat.resume`.
   - Plan 03's `tests/test_store_locks.py` concurrency test now appends assistant messages instead of chunks (its count of 161 is unchanged).
8. **Sealed reasoning is also pushed live (P07-T04),** not only persisted. The view-model then sees the same `reasoning/message` live and on replay, and seals the reasoning block before the answer or tool row. `turn.retry` drops unsealed reasoning. Final-review fix: a sealed reasoning/message is persisted only with the next persisted display event of its request, and a turn.retry for its turn drops it unpersisted, so replay matches the live view after the view-model's retry discard.
9. **Replay (P07-T05).** `events.display_log` is added. For a token session, `chat.history.get` returns the whole display log (`limit` is ignored), never returns `tool_start`, and drops a v1 request's chunks when its assistant message was stored. Tokenless behaviour is unchanged.
10. **Long-poll (P07-T06).**
    - `protocol.MAX_WAIT_MS` is added.
    - With `wait_ms`, an `after_seq` beyond the queue returns at once with the queue's real `last_seq`. Without `wait_ms`, the M1 short-poll keeps today's echo.
    - `capabilities.long_poll` goes to every token session, including `event_protocol: 1` ones (harmless for the M1 plugin); tokenless sessions keep today's `CAPABILITIES`.
11. **Fixture generation (P07-T08).** The fixtures are generated in process with `MetaScriptedLoop` and `ProductBridge`, not with P06-T11's `ScriptedLoopFactory` plus `serve_runtime`. A `(text, tool_blocks)` script cannot produce reasoning, usage, status, `turn.retry` or the C4 wrap-up, and `serve_runtime` would only add HTTP around the same `RuntimeApp` code path. As a result:
    - The fixtures exclude `role=tool_start` (no executor), turn the recorder off (`run_dir: null`), and use `@REPO@`/`@WORK@` path placeholders.
    - The plugin-local events of `11_dead_runtime` are appended by the generator, with `seq: 0`.
    - `test_fixture_envelopes[*]` and `test_contents_*` are added, so a regenerated fixture cannot silently lose its scenario.
12. **`profiles.*` (P07-T07).**
    - `profiles.save` applies C7's Model change: a replaced same-provider profile keeps its `num_ctx` unless the call sets one.
    - A runtime without a settings store answers `INVALID_PARAMS {reason: "no_settings_store"}`.
    - `protocol._as_profile_key` is added for the required `name`.
13. **Tests beyond the skeleton's lists:**
    - P07-T02: `test_action_for_code_catalogue`, `test_stuck_wrap_up_error_is_message_not_card` (C4 contract).
    - P07-T03: `test_tool_finished_meta_late_flag`.
    - P07-T04: `test_turn_retry_discards_reasoning`, `test_late_tool_finished_persisted`.
    - P07-T05: `test_drop_pending_keeps_seq`.
    - P07-T06: `test_queue_wait_unit`.
    - P07-T07: `test_save_keeps_num_ctx_on_model_change`.
    - P07-T08: `test_fixture_envelopes[*]`, `test_contents_*`.
