# ChatVMD Round 1 — Plan 03: ChatVMD R1 — M1 memory, profiles and catalog RPCs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-turn memory that keeps tool context (S1); runtime-owned profiles with first-run discovery and the C7 context default; the provider catalog; and the M1 RPCs the plugin needs (runtime.info, session.set_cwd, models.list, provider.test).

**Architecture:** A new `conversation.py` owns the append-only `chats/<id>/messages.jsonl` log: the loop's canonical `messages_out` copies (plan 02) go through `conversation.Appender`, and `build_prior` rebuilds a budgeted, repaired prior for the next request without ever writing. A new `settings_store.py` owns `~/.vmdai/settings.json` (profiles, migration, precedence, first run) under the `locks.py` flocks, and `provider_catalog.py` owns every Ollama/OpenAI-compatible probe with base_url-keyed caches. `RuntimeApp` routes token-authenticated sessions through the active profile (`LoopOptions.product`), creates their chats lazily under a per-chat lock, and serves the new M1 RPCs; tokenless sessions and every `options=None` path keep today's behaviour.

**Tech Stack:** Python 3.9-compatible stdlib runtime (`json`, `fcntl`, `urllib`, `threading`, `dataclasses`); pytest 9 (`tmp_path`, `monkeypatch`, `caplog`); real 127.0.0.1 sockets for probe tests. No Tcl or Tk in this plan.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — §2b (File, Writes, Canonical copies, Reading never writes, Budget, In-run compaction, Repairing, Late results, Store limits, Legacy chats, Concurrency, Lock lifecycle, Mode); §2c Stage split (M1 RPCs) and Busy state after a reconnect (`runtime.info.active_request`); §2e Compatibility (privileged operations); §2f Where provider settings live, Schema, Providers and keys, Writes, Ollama specifics (Probes, Thinking detection), Unreachable classification (hints), Rescue (`provider.test` warning), First run, Error codes; §3 rows app.py, settings_store.py, conversation.py, provider_catalog.py, store.py/events.py, protocol.py, provider.py/keys.py/constants.py and RPC rows session.start, chat.send, chat.resume, provider.set, settings.set, models.list, provider.test, runtime.info, session.set_cwd; §7 Existing chats, Several runtimes, `last_provider.txt` precedence; C5 Memory; C7 (Product default, Cap at first run, Precedence, Model change, Tests); C9 (catalog caches keyed by base_url, `urlopen` by attribute access). Part C wins where it conflicts with Parts A/B.

**Branch:** `chatvmd-r1-03-m1-memory-profiles`, created from `main` after plan 02 (`chatvmd-r1-02-m1-runtime-foundation`, which itself follows plan 01) is merged.

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

- Each new runtime module (`conversation.py`, `locks.py`, `settings_store.py`, `provider_catalog.py`) is stdlib-only, starts with `from __future__ import annotations`, and is appended to `RUNTIME_MODULES` in `tests/test_py39_compat.py` in the task that creates it.
- `RuntimeApp` never builds a `SettingsStore` by itself; only `runtime/main.py` passes one. With `settings_store=None` the app behaves exactly as plan 02 left it (tests, A/B scripts, attach-mode fixtures).
- Only these Ollama endpoints are ever probed: `/api/version`, `/api/tags`, `/api/show`, `/api/ps`. Every HTTP call in `settings_store` and `provider_catalog` reaches `urllib.request.urlopen` by attribute access at call time.
- Nothing that reads memory writes it: `build_prior`, `read_lines` and `legacy_prior` never touch the disk. The only memory writers are `Appender`, `import_legacy` (a legacy chat's first full-memory send) and the image files the Appender creates.
- A write to a settings file whose `settings_source` is `newer` or `invalid` raises `SettingsError("READ_ONLY")`; over RPC it becomes `INVALID_PARAMS` with `data {"reason": "read_only", "settings_source": …}` (the RPC catalogue has no READ_ONLY code).
- Plan-02 names this plan relies on beyond the skeleton (Task 0 verifies each): `RuntimeApp._build_loop(profile)` (wraps factory errors as `PROVIDER_INIT_FAILED`), `_default_loop_factory`, `_base_loop_factory` (what `provider.set` restores), `_loop_factory` (what the `claude_loop` setter replaces) and `_assigned_loop`; the per-session model override in plan 02's `_run_claude_loop_response`; `ClaudeToolLoop.options`; `ClaudeToolLoop._call_turn` (the single model-call site in `run()`); `ClaudeToolLoop._on_meta` forwarding a `{"kind": "status", …}` item to `ctx.on_event` as a `system/state` item; the loop's `turn.started` item carrying `metadata.turn`; `messages_out` receiving the prompt, each assistant turn, each tool-results message and the final turn with `call_<call_key>` ids; `tests/helpers/runtime_fixture.make_app` and `rpc` (which returns the whole envelope); `tests/test_main_lifecycle.py::_env`.
- No test reaches the real ports 11435/11434: in-process apps get plan 01's `probe_local_ollama` stub, and subprocess runtimes get an empty `settings.json` in their temp HOME (P03-T08).

## Review Focus

- A crash mid-write leaves a truncated last line in messages.jsonl; that line is skipped and earlier exchanges are intact. Owner P03-T01: test_read_lines_skips_unknown_kind_and_undecodable.
- Resuming a legacy chat with no messages.jsonl and 200+ mostly-chunk events must keep every message event. Owner P03-T02: test_legacy_prior_reads_all_message_events_and_drops_trailing_user.
- A hand-edited settings.json with invalid JSON: the runtime still starts, never overwrites the file, and reports settings_source 'invalid'. Owner P03-T05: test_invalid_json_read_only (the RPC side is also pinned by P03-T09 test_read_only_settings_rejected_over_rpc).
- Two runtimes resume the same chat and the second gets CHAT_LOCKED; the lock is freed when the holder is SIGKILLed. Owner P03-T03: test_chat_lock_released_on_kill (the RPC side is also pinned by P03-T04 test_resume_locked_chat_returns_chat_locked).
- The first-run probe meets a stale tunnel (accepts, never answers) and stays bounded to about 300 ms per port. Owner P03-T06: test_probe_bounded_timeout.

## File map

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `runtime/vmd_ai_runtime/conversation.py` | create | T01, T02 | messages.jsonl Appender/reader; build_prior, repair, budget, stubs, legacy path |
| `runtime/vmd_ai_runtime/locks.py` | create | T03 | `store_lock` (flock on `.store.lock`) and `ChatLock` (`chats/<id>/.lock`) |
| `runtime/vmd_ai_runtime/store.py` | modify | T03 | public `chat_dir`/`exists`, manifest and index writes under `store_lock` |
| `runtime/vmd_ai_runtime/settings_store.py` | create | T05, T06 | settings.json schema, migration, precedence, first run |
| `runtime/vmd_ai_runtime/provider_catalog.py` | create | T07 | models.list/provider.test probes, preflight helpers, caches, hints |
| `runtime/vmd_ai_runtime/app.py` | modify | T04, T08, T09 | memory wiring, lazy chats, locks, profile loops, NO_MODEL, M1 RPCs |
| `runtime/vmd_ai_runtime/claude_loop.py` | modify | T02, T08, T10 | `events_to_messages(drop_trailing_user)`, openai-compatible factory, in-run compaction |
| `runtime/vmd_ai_runtime/sessions.py` | modify | T04, T09 | `SessionState.chat_id` optional, `chat_lock`; `RequestState.turn/started_at` |
| `runtime/vmd_ai_runtime/events.py` | modify | T04 | `EventQueue.last_seq` |
| `runtime/vmd_ai_runtime/constants.py` | modify | T04, T08 | `"full"` conversation mode; `openai-compatible` key id |
| `runtime/vmd_ai_runtime/protocol.py` | modify | T09 | validators for the M1 RPCs and the new provider.set params |
| `runtime/vmd_ai_runtime/provider.py`, `keys.py` | modify | T08 | `openai-compatible` provider and key |
| `runtime/main.py` | modify | T08 | `--provider`; passes `SettingsStore()` |
| `tests/helpers/conversation_data.py` | create | T01 | message builders and a tiny PNG for memory tests |
| `tests/helpers/app_driver.py` | create | T04 | `Session` wrapper over plan 02's `runtime_fixture.make_app`/`rpc`, `ScriptedLoop`, `InstantBridge` |
| `tests/helpers/fake_ollama.py` | create | T06 | in-memory Ollama, a real-socket server, an injectable urlopen, dead sockets |
| `tests/test_conversation_appender.py` … `tests/test_compact_in_run.py` | create | T01–T10 | one test module per task |
| `tests/test_py39_compat.py` | modify | T01, T03, T05, T07 | append the new modules to `RUNTIME_MODULES` |
| `tests/test_main_lifecycle.py` | modify | T08 | plan 02's `_env` writes an empty settings.json into the temp HOME, so subprocess runtimes never probe the real ports 11435/11434 |

**How to apply the edit steps.** "Replace" steps quote the exact current text (as it stands after plan 02 and the previous tasks of this plan) and the new text; apply them with the Edit tool, using the quoted text as `old_string`. Every quoted block is unique in its file. Line numbers refer to commit 6f5f937; plans 01 and 02 move most of them, so locate code by the quoted text.

---

### Task 0: Pre-flight

**Files:** none (read-only checks; creates the branch).

**Interfaces:**
- Consumes: plan 01 (`tests/conftest.py` `_hermetic`, `real_probe_local_ollama`, `live_env`; `tests/test_py39_compat.py` `RUNTIME_MODULES`) and plan 02 (`constants.RUNTIME_PROTOCOL/RUNTIME_VERSION`; `LoopOptions`, `LoopOptions.product`, `RunContext`, `ClaudeToolLoop(options=)`, `run(ctx=)`, `_call_turn`, `_on_meta`, `_emit`; `SessionState.authenticated/event_protocol/vmd_env/lock`; `SessionManager.create_session(cwd, chat_id, *, authenticated, event_protocol, vmd_env)`; `RuntimeApp(launch_token=, allow_tokenless_v1=, loop_factory=)`, `_require_auth`, `profile_for_session`, `has_agent_loop`, `_build_loop`, `_default_loop_factory`, `_base_loop_factory`, `_loop_factory`, `_assigned_loop`, the `claude_loop` property; `protocol.CHAT_ID_RE`; `logging_utils.default_log_path`; `tests/helpers/runtime_fixture.make_app`, `rpc`; `tests/test_main_lifecycle.py::_env`).
- Produces: the branch `chatvmd-r1-03-m1-memory-profiles`.

- [ ] **Step 1: Create the branch**

```bash
cd /Users/pinhaogu/Documents/GitHub/vmdai
git checkout main && git pull --ff-only origin main
git log --oneline -1
git checkout -b chatvmd-r1-03-m1-memory-profiles
```

Expected: the last line is `Switched to a new branch 'chatvmd-r1-03-m1-memory-profiles'`, and `git log` shows plan 02's merge.

- [ ] **Step 2: Confirm the suites are green before any change**

```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
```

Expected: the first summary reads `N passed, 1 xfailed in T s` (no `failed`, no `error`; the xfail is `test_unreachable_host_raises_with_hint`; T < 60; if the line also shows `S skipped`, S stays the same through this plan); then `90 passed`; then `62 passed`. Stop and report if any suite is red. **Write down N:** every later whole-suite step expects exactly N plus the tests this plan has added so far (the running total is given in each step; the plan adds 86 tests in all).

- [ ] **Step 3: Check the plan-01 test surface**

```bash
grep -n "real_probe_local_ollama\|probe_local_ollama\|clear_caches\|raising=False\|hasattr" tests/conftest.py
grep -n "RUNTIME_MODULES" tests/test_py39_compat.py
ls tests/helpers/
```

Expected: `conftest.py` defines the `real_probe_local_ollama` fixture and stubs `settings_store.probe_local_ollama`; that stub must tolerate a `settings_store` module that does not define `probe_local_ollama` yet (it passes `raising=False` or checks `hasattr`), because `settings_store.py` exists from P03-T05 and `probe_local_ollama` lands in P03-T06. If the stub would raise, change only that `monkeypatch.setattr(...)` call to pass `raising=False`, run `env -u VMD_AI_PROVIDER python -m pytest tests -q`, and commit it alone:

```bash
git add tests/conftest.py
git commit -m "test: tolerate settings_store without probe_local_ollama in the hermetic stub

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

`RUNTIME_MODULES = [` must be present, and `tests/helpers/` must list `live.py`, `keyring_stub.py`, `tcl.py`, `golden.py`, `runtime_fixture.py` and `fake_provider.py`.

- [ ] **Step 4: Check the plan-02 runtime surface**

```bash
grep -n "RUNTIME_PROTOCOL\|RUNTIME_VERSION" runtime/vmd_ai_runtime/constants.py
grep -n "^class LoopOptions\|^class RunContext\|def product\|compact_in_run: bool\|context_length: Optional\|self.options = \|def _on_meta\|def _emit\|def _call_turn\|def _mint_call_key\|self._call_turn(\|self._call(\|MAX_TURNS = 28" runtime/vmd_ai_runtime/claude_loop.py
grep -n "authenticated: bool\|event_protocol: int\|vmd_env: Optional\|lock: threading.Lock\|def create_session" runtime/vmd_ai_runtime/sessions.py
grep -n "def _require_auth\|def profile_for_session\|def has_agent_loop\|def _build_loop\|def _default_loop_factory\|self._base_loop_factory\b.*= \|self._loop_factory = \|self._assigned_loop\b.*= \|def claude_loop\|create_chat(title_hint" runtime/vmd_ai_runtime/app.py
grep -n "CHAT_ID_RE\|launch_token\|event_protocol" runtime/vmd_ai_runtime/protocol.py
grep -n "def default_log_path" runtime/vmd_ai_runtime/logging_utils.py
grep -n "def make_app\|def rpc\|def start_token_session\|def wait_idle" tests/helpers/runtime_fixture.py
grep -n "^def _env" tests/test_main_lifecycle.py
```

Expected: every command prints at least one line. In `claude_loop.py`, `self._call(` appears exactly once (inside `_call_turn`) and `self._call_turn(` exactly once (inside `run()`, called as `self._call_turn(` then `messages, system_prompt, on_text, cancel_event,` on the next line); `MAX_TURNS = 28` is the class attribute line with its "raised from 16" comment. In `app.py`, `self._loop_factory = ` appears in `__init__`, in the `claude_loop` setter and in `provider.set`; `create_chat(title_hint="VMD AI Chat")` appears exactly once, inside the `session.start` branch. Every later task quotes plan 02's code as these commands find it; if plan 02 named anything differently, stop and reconcile the quoted text before starting P03-T01.

- [ ] **Step 5: Check the loop behaviour this plan builds on**

```bash
PYTHONPATH=runtime python - <<'EOF'
import inspect, threading
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext

opts = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "m"})
assert opts.num_ctx == 32768 and opts.compact_in_run is True and opts.rescue == "json", opts
assert LoopOptions().num_ctx is None and LoopOptions().compact_in_run is False
assert "ctx" in inspect.signature(ClaudeToolLoop.run).parameters

class Loop(ClaudeToolLoop):
    def _call(self, messages, system_prompt, on_text, should_cancel):
        self._on_meta({"kind": "status", "phase": "context_near_full"})
        return "hi", []

assert Loop(provider_name="ollama", api_key="u", model="m", options=opts).options is opts
out, events = [], []
Loop(provider_name="anthropic-direct", api_key="k", model="m", options=LoopOptions()).run(
    prompt="p", system_prompt="s", tool_bridge=None, session_id="sess_x",
    session_queue=None, cancel_event=threading.Event(), on_chunk=lambda t: None,
    ctx=RunContext(request_id="req_x", chat_id="chat_000000000000",
                   on_event=events.append, messages_out=out))
assert out[0] == {"role": "user", "content": "p"} and out[-1]["role"] == "assistant", out
kinds = [(e.get("metadata") or {}).get("kind") for e in events]
assert "turn.started" in kinds and "status" in kinds, kinds
print("plan-02 loop surface OK")
EOF
```

Expected: `plan-02 loop surface OK`. No commit (unless Step 3 required one).

---

### Task P03-T01: conversation.Appender and the messages.jsonl format

**Files:**
- Create: `tests/helpers/conversation_data.py` (plan-local helper, see Deviations)
- Create: `runtime/vmd_ai_runtime/conversation.py`
- Create: `tests/test_conversation_appender.py`
- Modify: `tests/test_py39_compat.py` (the `RUNTIME_MODULES = [...]` literal added by P01-T09)

**Interfaces:**
- Consumes: messages_out contract with call_<call_key> ids (P02-T08)
- Produces:
  - conversation.CHARS_PER_TOKEN = 3.5; STORE_OUTPUT_CAP = 6000
  - conversation.messages_path(chat_dir: Path) -> Path
  - class conversation.Appender(chat_dir: Path, request_id: str, *, clock=time.time) with .append(message: Dict[str, Any]) -> None and .append_late_result(call_key: str, ok: bool, executed: str, output: str, error: str) -> None
  - conversation.read_lines(chat_dir: Path) -> List[Dict[str, Any]]
  - conversation.cap_output_section(text: str, cap: int = 6000) -> str
  - plan-local additions: `conversation.split_output_section(text: str) -> Tuple[str, str]`, `conversation.TAIL_MARKERS`, `conversation.FAILURE_HEAD_PREFIX = "Failed at statement "`, `conversation.OUTPUT_START_LINE = "Output before the error:"` (the line plan 05's `_structured_summary` puts before a failed command's output), `conversation.KNOWN_KINDS`, `conversation.STORE_WARN_BYTES = 2 * 1024 * 1024`, `conversation.MESSAGES_FILE = "messages.jsonl"`
  - test helpers: `helpers.conversation_data.tiny_png(width, height) -> bytes`, `user(text)`, `assistant_text(text)`, `assistant_tools(text, *calls)`, `tool_results(*results)`, `image_block(png)`, `snapshot_result(call_key, png, text="Snapshot captured.")`, `write_exchange(chat_dir, request_id, messages)`, `tool_pairs_ok(messages) -> bool`

- [ ] **Step 1: Add the shared message builders**

Create `tests/helpers/conversation_data.py`:

```python
"""Message builders for the conversation-memory tests (plan 03).

Messages use the loop's Anthropic-style shape. Tool ids follow the canonical
form the loop writes to messages_out: ``call_<call_key>``.
"""
from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from vmd_ai_runtime.conversation import Appender


def tiny_png(width: int, height: int) -> bytes:
    """A valid 8-bit RGB PNG of the given size (all black)."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def user(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": text}


def assistant_text(text: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def assistant_tools(text: str, *calls: Tuple[str, str, Dict[str, Any]]) -> Dict[str, Any]:
    """An assistant turn with optional text and one tool_use per (call_key, name, input)."""
    content: List[Dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    for call_key, name, tool_input in calls:
        content.append({"type": "tool_use", "id": "call_" + call_key, "name": name, "input": tool_input})
    return {"role": "assistant", "content": content}


def tool_results(*results: Tuple[str, bool, str]) -> Dict[str, Any]:
    """A tool-results message with one tool_result per (call_key, ok, text)."""
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "call_" + call_key, "content": text, "is_error": not ok}
        for call_key, ok, text in results
    ]}


def image_block(png: bytes) -> Dict[str, Any]:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                        "data": base64.b64encode(png).decode("ascii")}}


def snapshot_result(call_key: str, png: bytes, text: str = "Snapshot captured.") -> Dict[str, Any]:
    """A tool-results message for capture_vmd_snapshot carrying an inline image."""
    return {"role": "user", "content": [{
        "type": "tool_result",
        "tool_use_id": "call_" + call_key,
        "content": [{"type": "text", "text": text}, image_block(png)],
        "is_error": False,
    }]}


def write_exchange(chat_dir: Path, request_id: str, messages: Sequence[Dict[str, Any]]) -> None:
    """Append one exchange to chat_dir/messages.jsonl the way the loop would."""
    appender = Appender(chat_dir, request_id, clock=lambda: 1000.0)
    for message in messages:
        appender.append(message)


def tool_pairs_ok(messages: Sequence[Dict[str, Any]]) -> bool:
    """True when every tool_use is answered by the next message and every
    tool_result follows the assistant turn that asked for it."""
    for index, message in enumerate(messages):
        content = message.get("content")
        blocks = content if isinstance(content, list) else []
        uses = [b["id"] for b in blocks if b.get("type") == "tool_use"]
        results = [b["tool_use_id"] for b in blocks if b.get("type") == "tool_result"]
        if results:
            previous = messages[index - 1].get("content") if index > 0 else None
            asked = {b.get("id") for b in (previous if isinstance(previous, list) else [])
                     if b.get("type") == "tool_use"}
            if not set(results) <= asked:
                return False
        if uses:
            following = messages[index + 1].get("content") if index + 1 < len(messages) else None
            answered = {b.get("tool_use_id") for b in (following if isinstance(following, list) else [])
                        if b.get("type") == "tool_result"}
            if set(uses) - answered:
                return False
    return True
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_conversation_appender.py`:

```python
"""P03-T01: conversation.Appender and the messages.jsonl format (§2b, C5)."""
from __future__ import annotations

import json
import logging

from helpers.conversation_data import (
    assistant_tools,
    snapshot_result,
    tiny_png,
    tool_results,
    user,
)
from vmd_ai_runtime import conversation


def _lines(chat_dir):
    text = conversation.messages_path(chat_dir).read_text(encoding="ascii")
    return [json.loads(line) for line in text.splitlines()]


def test_one_line_per_append(tmp_path):
    appender = conversation.Appender(tmp_path, "req_1", clock=lambda: 1000.0)
    messages = [
        user("load 1hck"),
        assistant_tools("Loading.", ("abcdef012345", "run_vmd_command", {"command": "mol new 1hck.pdb"})),
        tool_results(("abcdef012345", True, "Info) Loaded 1hck")),
    ]
    for message in messages:
        appender.append(message)
    lines = _lines(tmp_path)
    assert len(lines) == 3
    for line, message in zip(lines, messages):
        assert line == {"v": 1, "kind": "message", "request_id": "req_1", "ts": 1000.0, "message": message}
    assert conversation.messages_path(tmp_path) == tmp_path / "messages.jsonl"
    assert conversation.CHARS_PER_TOKEN == 3.5 and conversation.STORE_OUTPUT_CAP == 6000


def test_image_block_becomes_image_ref_and_file(tmp_path):
    png = tiny_png(8, 6)
    conversation.Appender(tmp_path, "req_1").append(snapshot_result("abcdef012345", png))
    stored = _lines(tmp_path)[0]["message"]["content"][0]
    assert stored["type"] == "tool_result" and stored["tool_use_id"] == "call_abcdef012345"
    assert stored["content"][0] == {"type": "text", "text": "Snapshot captured."}
    assert stored["content"][1] == {"type": "image_ref", "path": "images/abcdef012345.png",
                                    "media_type": "image/png", "width": 8, "height": 6}
    assert (tmp_path / "images" / "abcdef012345.png").read_bytes() == png
    assert '"base64"' not in conversation.messages_path(tmp_path).read_text(encoding="ascii")


def test_existing_image_file_not_rewritten(tmp_path):
    (tmp_path / "images").mkdir()
    existing = tmp_path / "images" / "abcdef012345.png"
    existing.write_bytes(b"written by the bridge")
    conversation.Appender(tmp_path, "req_1").append(snapshot_result("abcdef012345", tiny_png(4, 4)))
    assert existing.read_bytes() == b"written by the bridge"
    assert _lines(tmp_path)[0]["message"]["content"][0]["content"][1]["path"] == "images/abcdef012345.png"


def test_late_result_line(tmp_path):
    appender = conversation.Appender(tmp_path, "req_9", clock=lambda: 2000.5)
    appender.append_late_result("abcdef012345", True, "yes", "RMSD 1.23", "")
    assert _lines(tmp_path) == [{
        "v": 1, "kind": "late_result", "request_id": "req_9", "ts": 2000.5,
        "call_key": "abcdef012345", "ok": True, "executed": "yes", "output": "RMSD 1.23", "error": "",
    }]


def test_store_cap_output_section_only(tmp_path):
    note = ("[output truncated: 20000 lines, 117 KB. Full text: /tmp/chats/chat_0/outputs/abcdef012345.txt. "
            "Don't print it again: compute what you need (measure, a narrower selection), "
            "or read a slice of that file with Tcl.]")
    nudge = "Loop check: this exact call has now run 3 times with the same result."
    body = "".join("%05d 1.000 2.000 3.000\n" % i for i in range(20000))
    text = body + note + "\n" + nudge
    capped = conversation.cap_output_section(text)
    assert capped.endswith("\n" + note + "\n" + nudge)
    output_part, tail = conversation.split_output_section(capped)
    assert tail == "\n" + note + "\n" + nudge
    assert len(output_part) <= conversation.STORE_OUTPUT_CAP + 50
    assert output_part.startswith("00000 1.000") and output_part.endswith("19999 1.000 2.000 3.000")
    assert conversation.cap_output_section("short\n" + note) == "short\n" + note
    # C3's failure lines sit in front of the output and are not counted or cut.
    failure = ("Failed at statement 2 of 2: `puts $big`\nError: boom\n"
               "Statement 1 was applied and is still in effect; do not re-run it.\n"
               "Output before the error:\n")
    assert conversation.cap_output_section(failure + "o" * 5900) == failure + "o" * 5900
    capped_failure = conversation.cap_output_section(failure + "o" * 9000)
    assert capped_failure.startswith(failure) and capped_failure.endswith("o" * 3000)
    assert len(capped_failure) <= len(failure) + conversation.STORE_OUTPUT_CAP + 50
    conversation.Appender(tmp_path, "req_1").append(tool_results(("abcdef012345", True, text)))
    assert _lines(tmp_path)[0]["message"]["content"][0]["content"] == capped


def test_warns_at_2mb(tmp_path, caplog):
    appender = conversation.Appender(tmp_path, "req_1")
    with caplog.at_level(logging.WARNING, logger="vmdai.conversation"):
        appender.append(user("x" * (conversation.STORE_WARN_BYTES + 10)))
        appender.append(user("again"))
    warnings = [r for r in caplog.records if "over 2 MB" in r.getMessage()]
    assert len(warnings) == 1


def test_read_lines_skips_unknown_kind_and_undecodable(tmp_path, caplog):
    """Review focus: a crash mid-write leaves a truncated last line; it is
    skipped and the earlier lines survive."""
    appender = conversation.Appender(tmp_path, "req_1", clock=lambda: 1.0)
    appender.append(user("first"))
    appender.append_late_result("abcdef012345", False, "unknown", "", "stopped")
    with open(conversation.messages_path(tmp_path), "ab") as handle:
        handle.write(b'{"v":1,"kind":"pending_approval","request_id":"req_1"}\n')
        handle.write(b"this is not json\n")
        handle.write(b"\xff\xfe\n")
        handle.write(b'{"v":1,"kind":"message","request_id":"req_2","ts":2.0,"mess')
    with caplog.at_level(logging.WARNING, logger="vmdai.conversation"):
        lines = conversation.read_lines(tmp_path)
    assert [line["kind"] for line in lines] == ["message", "late_result"]
    assert lines[0]["message"] == user("first")
    assert len([r for r in caplog.records if "skipped" in r.getMessage()]) == 4
    assert conversation.read_lines(tmp_path / "missing") == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_conversation_appender.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'vmd_ai_runtime.conversation'` (raised from `tests/helpers/conversation_data.py`), `1 error`.

- [ ] **Step 4: Write the module**

Create `runtime/vmd_ai_runtime/conversation.py`:

```python
"""conversation.py - the per-chat canonical message log (chats/<id>/messages.jsonl).

Spec §2b and C5. One JSON object per line, append-only, never rewritten:

  {"v":1,"kind":"message","request_id":...,"ts":...,"message":{"role":...,"content":...}}
  {"v":1,"kind":"late_result","request_id":...,"ts":...,"call_key":...,"ok":...,
   "executed":"yes|no|unknown","output":...,"error":...}

The loop hands the Appender canonical copies (tool ids already rewritten to
``call_<call_key>``). The Appender replaces each base64 image with an
``image_ref`` block backed by ``images/<call_key>.png`` (it writes the file
only when the bridge has not) and caps each tool result's output section at
STORE_OUTPUT_CAP characters, leaving C3's failure lines, the C5 note and the
C4 nudge intact. Readers skip lines they do not understand. Stdlib only;
imports on 3.9.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import logging
import re
import struct
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("vmdai.conversation")

CHARS_PER_TOKEN = 3.5
STORE_OUTPUT_CAP = 6000
STORE_WARN_BYTES = 2 * 1024 * 1024
MESSAGES_FILE = "messages.jsonl"
LINE_VERSION = 1
KNOWN_KINDS = ("message", "late_result")
# Lines that follow a tool's own output and are never cut: the C5 truncation
# note, the executor's 1 MB note and the C4 loop-guard nudge.
TAIL_MARKERS = ("[output truncated:", "[executor limit:", "Loop check:")
# C3's structured failure text (result_format "structured", plan 05's
# _structured_summary) starts with FAILURE_HEAD_PREFIX and puts the tool's
# own output after an OUTPUT_START_LINE line. The failure lines up to and
# including that line are outside the store cap too (C5 Memory).
FAILURE_HEAD_PREFIX = "Failed at statement "
OUTPUT_START_LINE = "Output before the error:"

_WRITE_LOCK = threading.Lock()
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def messages_path(chat_dir: Path) -> Path:
    """Path of a chat's canonical message log."""
    return Path(chat_dir) / MESSAGES_FILE


def split_output_section(text: str) -> Tuple[str, str]:
    """Split a tool-result text into (output section, tail).

    The tail starts at the first line after the first one that begins with a
    TAIL_MARKERS prefix and keeps its leading newline, so output + tail == text.
    """
    text = str(text or "")
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].lstrip().startswith(TAIL_MARKERS):
            return "\n".join(lines[:index]), "\n" + "\n".join(lines[index:])
    return text, ""


def _split_failure_head(body: str) -> Tuple[str, str]:
    """(C3 failure lines, tool output) of an output section; ("", body) otherwise."""
    marker = "\n" + OUTPUT_START_LINE + "\n"
    if not body.startswith(FAILURE_HEAD_PREFIX) or marker not in body:
        return "", body
    cut = body.index(marker) + len(marker)
    return body[:cut], body[cut:]


def cap_output_section(text: str, cap: int = STORE_OUTPUT_CAP) -> str:
    """Cap only the output section at ``cap`` characters (head plus tail).

    C3's failure lines in front of the output, and the C5 note and C4 nudge
    after it, are neither counted nor cut.
    """
    text = str(text or "")
    body, tail = split_output_section(text)
    failure_head, output = _split_failure_head(body)
    if len(output) <= cap:
        return text
    head_len = cap // 2
    tail_len = cap - head_len
    marker = "\n[stored copy cut: %d chars omitted]\n" % (len(output) - cap)
    return failure_head + output[:head_len] + marker + output[len(output) - tail_len:] + tail


def _call_key_from_id(tool_use_id: Any) -> str:
    raw = str(tool_use_id or "")
    if raw.startswith("call_"):
        raw = raw[len("call_"):]
    return _UNSAFE_KEY_CHARS.sub("_", raw)[:64] or "unknown"


def _image_size(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    if len(data) >= 24 and data[:8] == _PNG_MAGIC:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return None, None


class Appender:
    """Writes one messages.jsonl line per appended message (§2b Writes).

    ``ctx.messages_out`` is duck-typed: the loop only calls ``append``.
    """

    def __init__(self, chat_dir: Path, request_id: str, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.chat_dir = Path(chat_dir)
        self.request_id = str(request_id)
        self._clock = clock
        self._warned = False

    def append(self, message: Dict[str, Any]) -> None:
        self._write({
            "v": LINE_VERSION,
            "kind": "message",
            "request_id": self.request_id,
            "ts": self._clock(),
            "message": self._stored_message(message),
        })

    def append_late_result(self, call_key: str, ok: bool, executed: str,
                           output: str, error: str) -> None:
        self._write({
            "v": LINE_VERSION,
            "kind": "late_result",
            "request_id": self.request_id,
            "ts": self._clock(),
            "call_key": str(call_key),
            "ok": bool(ok),
            "executed": str(executed or "unknown"),
            "output": cap_output_section(str(output or "")),
            "error": str(error or ""),
        })

    # -- internals -------------------------------------------------------

    def _write(self, line: Dict[str, Any]) -> None:
        data = (json.dumps(line, ensure_ascii=True) + "\n").encode("ascii")
        path = messages_path(self.chat_dir)
        with _WRITE_LOCK:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as handle:
                handle.write(data)
                handle.flush()
            size = path.stat().st_size
        if size >= STORE_WARN_BYTES and not self._warned:
            self._warned = True
            logger.warning("messages.jsonl of %s is %.1f MB (over 2 MB)",
                           self.chat_dir.name, size / (1024.0 * 1024.0))

    def _stored_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        out = {key: copy.deepcopy(value) for key, value in message.items() if key != "content"}
        content = message.get("content")
        if not isinstance(content, list):
            out["content"] = copy.deepcopy(content)
            return out
        blocks: List[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                blocks.append(self._stored_tool_result(block))
            elif isinstance(block, dict) and block.get("type") == "image":
                blocks.append(self._stored_image(block, None, 0))
            else:
                blocks.append(copy.deepcopy(block))
        out["content"] = blocks
        return out

    def _stored_tool_result(self, block: Dict[str, Any]) -> Dict[str, Any]:
        out = {key: copy.deepcopy(value) for key, value in block.items() if key != "content"}
        key = _call_key_from_id(block.get("tool_use_id"))
        content = block.get("content")
        if isinstance(content, str):
            out["content"] = cap_output_section(content)
            return out
        if not isinstance(content, list):
            out["content"] = copy.deepcopy(content)
            return out
        parts: List[Any] = []
        image_index = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                capped = dict(part)
                capped["text"] = cap_output_section(str(part.get("text") or ""))
                parts.append(capped)
            elif isinstance(part, dict) and part.get("type") == "image":
                parts.append(self._stored_image(part, key, image_index))
                image_index += 1
            else:
                parts.append(copy.deepcopy(part))
        out["content"] = parts
        return out

    def _stored_image(self, block: Dict[str, Any], key: Optional[str], index: int) -> Dict[str, Any]:
        source = block.get("source") or {}
        if source.get("type") != "base64":
            return copy.deepcopy(block)
        try:
            data = base64.b64decode(str(source.get("data") or ""))
        except (binascii.Error, ValueError, TypeError):
            return {"type": "text", "text": "[snapshot could not be stored]"}
        media_type = str(source.get("media_type") or "image/png")
        ext = "jpg" if media_type in ("image/jpeg", "image/jpg") else "png"
        if key is None:
            key = "img_" + hashlib.sha1(data).hexdigest()[:12]
        name = "%s.%s" % (key, ext) if index == 0 else "%s_%d.%s" % (key, index + 1, ext)
        target = self.chat_dir / "images" / name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        width, height = _image_size(data)
        return {"type": "image_ref", "path": "images/" + name,
                "media_type": media_type, "width": width, "height": height}


def read_lines(chat_dir: Path) -> List[Dict[str, Any]]:
    """Every line of messages.jsonl this runtime understands, in file order.

    Lines that do not decode, and lines with an unknown ``kind``, are skipped
    with a warning (a crash mid-write leaves a truncated last line).
    """
    path = messages_path(chat_dir)
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    with open(path, "rb") as handle:
        for number, raw in enumerate(handle, start=1):
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                line = json.loads(text)
            except ValueError:
                logger.warning("%s line %d does not decode; skipped", path, number)
                continue
            kind = line.get("kind") if isinstance(line, dict) else None
            if kind not in KNOWN_KINDS:
                logger.warning("%s line %d has unknown kind %r; skipped", path, number, kind)
                continue
            if kind == "message" and not isinstance(line.get("message"), dict):
                logger.warning("%s line %d has no message object; skipped", path, number)
                continue
            out.append(line)
    return out
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_conversation_appender.py -q`
Expected: `7 passed`.

- [ ] **Step 6: Register the module for the Python 3.9 import check**

In `tests/test_py39_compat.py`, add `"vmd_ai_runtime.conversation",` as a new element of the `RUNTIME_MODULES = [ ... ]` literal (keep the existing entries). This is required, not cosmetic: plan 01's `test_runtime_module_list_is_complete` fails the suite for any `vmd_ai_runtime` module missing from that list.

Run: `python -m pytest tests/test_py39_compat.py -q`
Expected: `4 passed` on the dev Mac (plan 01's module-list check plus the three `/usr/bin/python3` 3.9 checks); `1 passed, 3 skipped` on a machine whose `/usr/bin/python3` is not 3.9.

- [ ] **Step 7: Run the whole product suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+7 passed, 1 xfailed` (N from Task 0 Step 2), no failures.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/conversation.py tests/helpers/conversation_data.py tests/test_conversation_appender.py tests/test_py39_compat.py
git commit -m "feat(runtime): messages.jsonl Appender and reader (P03-T01)

Append-only canonical log: one line per message, image_ref files, a
6000-char store cap on the output section only, a 2 MB warning, and a
reader that skips unknown kinds and undecodable lines.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T02: build_prior: repair, budget, images, late notes, legacy path

**Files:**
- Modify: `runtime/vmd_ai_runtime/conversation.py` (append after `read_lines`)
- Modify: `runtime/vmd_ai_runtime/claude_loop.py:2056-2090` (`events_to_messages`, at 6f5f937; plan 02 shifts the line numbers — find it by `def events_to_messages`)
- Create: `tests/test_conversation_prior.py`

**Interfaces:**
- Consumes: conversation.read_lines, Appender (P03-T01); LoopOptions (P02-T05)
- Produces:
  - conversation.RESERVED_OUTPUT_TOKENS = 4096; PRIOR_FRACTION = 0.6; ANTHROPIC_CONTEXT_TOKENS = 114286; UNKNOWN_OUTCOME_TEXT
  - conversation.compute_run_budget(context_tokens: int, system_prompt_chars: int, tools_json_chars: int) -> int
  - conversation.context_tokens_for(provider: str, options: Optional[Any]) -> int
  - conversation.max_images_for(provider: str) -> int
  - conversation.stub_tool_result_text(text: str, head: int = 300) -> str (keeps the trailing output-path note)
  - conversation.build_prior(chat_dir: Path, budget_chars: int, max_images: int) -> List[Dict[str, Any]] — `budget_chars` is the request's run budget; build_prior keeps at most `PRIOR_FRACTION × budget_chars`
  - conversation.legacy_prior(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]
  - claude_loop.events_to_messages(events, drop_trailing_user: bool = False)
  - plan-local additions (used by P03-T04 and P03-T10): `conversation.ALL_EVENTS = 10**9`, `STUB_HEAD_CHARS = 300`, `CONTEXT_WARN_FRACTION = 0.9`, `OLLAMA_LEGACY_NUM_CTX = 8192`, `DEFAULT_CONTEXT_TOKENS = 32768`, `messages_chars(messages) -> int`, `repair_messages(messages) -> List[Dict]`, `compact_tool_results(messages, *, keep_rounds: int, keep_images: Optional[int] = None) -> List[Dict]`, `import_legacy(chat_dir, messages, *, clock=time.time) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_conversation_prior.py`:

```python
"""P03-T02: build_prior, budget, repair, late notes, legacy path (§2b, C5, C7)."""
from __future__ import annotations

import base64
import os

from helpers.conversation_data import (
    assistant_text,
    assistant_tools,
    snapshot_result,
    tiny_png,
    tool_pairs_ok,
    tool_results,
    user,
    write_exchange,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.claude_loop import LoopOptions, events_to_messages
from vmd_ai_runtime.store import ChatStore


def _blocks(messages, kind):
    """All blocks of ``kind``, including parts nested inside tool_result content."""
    out = []
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if block.get("type") == kind:
                out.append(block)
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                out.extend(part for part in block["content"] if part.get("type") == kind)
    return out


def test_budget_math():
    assert conversation.RESERVED_OUTPUT_TOKENS == 4096
    assert conversation.PRIOR_FRACTION == 0.6
    assert conversation.ANTHROPIC_CONTEXT_TOKENS == 114286
    assert conversation.compute_run_budget(32768, 1000, 500) == 98852
    assert conversation.compute_run_budget(4096, 10, 10) == 0
    assert conversation.max_images_for("ollama") == 1
    assert conversation.max_images_for("openai-compatible") == 1
    assert conversation.max_images_for("anthropic-direct") == 3
    assert conversation.max_images_for("openrouter") == 3


def test_keeps_whole_exchanges_newest_first_within_60_percent(tmp_path):
    exchanges = []
    for i in range(5):
        messages = [user("question %d " % i + "q" * 400), assistant_text("answer %d " % i + "a" * 400)]
        write_exchange(tmp_path, "req_%d" % i, messages)
        exchanges.append(messages)
    sizes = [conversation.messages_chars(m) for m in exchanges]
    budget = int((sizes[4] + sizes[3] + sizes[2] // 2) / conversation.PRIOR_FRACTION) + 1
    assert conversation.build_prior(tmp_path, budget, max_images=1) == exchanges[3] + exchanges[4]


def test_latest_exchange_always_kept_and_oversized_bodies_stubbed(tmp_path):
    messages = [
        user("do three things"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "a"})), tool_results(("k1", True, "x" * 5000)),
        assistant_tools("", ("k2", "run_vmd_command", {"command": "b"})), tool_results(("k2", True, "y" * 5000)),
        assistant_tools("", ("k3", "run_vmd_command", {"command": "c"})), tool_results(("k3", True, "z" * 5000)),
        assistant_text("done"),
    ]
    write_exchange(tmp_path, "req_1", messages)
    prior = conversation.build_prior(tmp_path, 1000, max_images=1)
    results = _blocks(prior, "tool_result")
    assert prior[0] == user("do three things") and prior[-1] == assistant_text("done")
    assert results[0]["content"].startswith("x" * 300) and len(results[0]["content"]) < 400
    assert results[1]["content"].startswith("y" * 300) and len(results[1]["content"]) < 400
    assert results[2]["content"] == "z" * 5000
    assert tool_pairs_ok(prior)


def test_tool_pair_never_split(tmp_path):
    exchanges = []
    for i in range(4):
        key = "k%d" % i
        messages = [
            user("step %d" % i),
            assistant_tools("", (key + "a", "run_vmd_command", {"command": "a"})), tool_results((key + "a", True, "o" * 900)),
            assistant_tools("", (key + "b", "run_vmd_command", {"command": "b"})), tool_results((key + "b", False, "e" * 900)),
            assistant_text("done %d" % i),
        ]
        write_exchange(tmp_path, "req_%d" % i, messages)
        exchanges.append(messages)
    one = conversation.messages_chars(exchanges[0])
    for prior_budget in range(one // 2, 5 * one, max(1, one // 7)):
        prior = conversation.build_prior(tmp_path, int(prior_budget / conversation.PRIOR_FRACTION), 1)
        assert tool_pairs_ok(prior)
        assert prior[0]["role"] == "user" and prior[0]["content"].startswith("step ")


def test_image_cap_keeps_newest_inline_and_stubs_older(tmp_path):
    for i in range(3):
        write_exchange(tmp_path, "req_%d" % i, [
            user("snap %d" % i),
            assistant_tools("", ("key%d" % i, "capture_vmd_snapshot", {})),
            snapshot_result("key%d" % i, tiny_png(4 + i, 3)),
            assistant_text("shot %d" % i),
        ])
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=1)
    images = _blocks(prior, "image")
    assert len(images) == 1
    assert base64.b64decode(images[0]["source"]["data"]) == tiny_png(6, 3)
    texts = " ".join(block["text"] for block in _blocks(prior, "text"))
    assert "images/key0.png" in texts and "images/key1.png" in texts
    assert _blocks(prior, "image_ref") == []


def test_image_ref_hydrated_to_base64(tmp_path):
    png = tiny_png(8, 6)
    write_exchange(tmp_path, "req_1", [
        user("snap"),
        assistant_tools("", ("abcdef012345", "capture_vmd_snapshot", {})),
        snapshot_result("abcdef012345", png),
        assistant_text("done"),
    ])
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=3)
    (image,) = _blocks(prior, "image")
    assert image["source"]["type"] == "base64" and image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == png
    os.remove(tmp_path / "images" / "abcdef012345.png")
    prior = conversation.build_prior(tmp_path, 10 ** 6, max_images=3)
    assert _blocks(prior, "image") == []
    assert any("snapshot file missing: images/abcdef012345.png" in b["text"] for b in _blocks(prior, "text"))


def test_dangling_tool_use_repaired_with_unknown_outcome(tmp_path):
    assert conversation.UNKNOWN_OUTCOME_TEXT == "outcome unknown: the runtime stopped during this command"
    write_exchange(tmp_path / "a", "req_1", [
        user("go"), assistant_tools("", ("k1", "run_vmd_command", {"command": "x"}))])
    prior = conversation.build_prior(tmp_path / "a", 10 ** 6, 1)
    assert prior[-1] == {"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": "call_k1",
        "content": conversation.UNKNOWN_OUTCOME_TEXT, "is_error": True}]}
    write_exchange(tmp_path / "b", "req_1", [
        user("go"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "x"}), ("k2", "run_vmd_command", {"command": "y"})),
        tool_results(("k1", True, "fine")),
    ])
    prior = conversation.build_prior(tmp_path / "b", 10 ** 6, 1)
    assert [b["tool_use_id"] for b in prior[-1]["content"]] == ["call_k1", "call_k2"]
    assert prior[-1]["content"][1]["content"] == conversation.UNKNOWN_OUTCOME_TEXT
    assert tool_pairs_ok(prior)


def test_late_result_rendered_as_note_before_next_prompt(tmp_path):
    write_exchange(tmp_path, "req_a", [
        user("run it"),
        assistant_tools("", ("k1", "run_vmd_command", {"command": "slow"})),
        tool_results(("k1", False, "stopped while running; outcome unknown")),
        assistant_text("stopped"),
    ])
    conversation.Appender(tmp_path, "req_a").append_late_result("k1", True, "yes", "RMSD 1.23", "")
    write_exchange(tmp_path, "req_b", [user("next"), assistant_text("ok")])
    conversation.Appender(tmp_path, "req_b").append_late_result("k2", False, "yes", "", "boom")
    prior = conversation.build_prior(tmp_path, 10 ** 6, 1)
    index = prior.index(user("next"))
    note = prior[index - 1]
    assert note["role"] == "user" and "call_k1" in note["content"] and "RMSD 1.23" in note["content"]
    assert "call_k2" in prior[-1]["content"] and "boom" in prior[-1]["content"]


def test_reading_never_writes(tmp_path):
    write_exchange(tmp_path, "req_1", [
        user("go"), assistant_tools("", ("k1", "capture_vmd_snapshot", {})), snapshot_result("k1", tiny_png(4, 4))])
    write_exchange(tmp_path, "req_2", [user("again"), assistant_tools("", ("k2", "run_vmd_command", {"command": "x"}))])

    def snapshot():
        return {str(p): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else b"")
                for p in sorted(tmp_path.rglob("*"))}

    before = snapshot()
    conversation.build_prior(tmp_path, 10 ** 6, 1)
    conversation.build_prior(tmp_path, 10, 0)
    assert snapshot() == before


def test_context_tokens_resolved_num_ctx():
    """C7: the budget uses the resolved num_ctx."""
    product = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b"})
    explicit = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435",
                                    "model": "qwen3.8:27b", "options": {"num_ctx": 16384}})
    assert conversation.context_tokens_for("ollama", None) == 8192
    assert conversation.context_tokens_for("ollama", LoopOptions()) == 8192
    assert conversation.context_tokens_for("ollama", product) == 32768
    assert conversation.context_tokens_for("ollama", explicit) == 16384
    assert conversation.context_tokens_for("openai-compatible", LoopOptions()) == 32768
    assert conversation.context_tokens_for("openai-compatible", LoopOptions(context_length=65536)) == 65536
    assert conversation.context_tokens_for("anthropic-direct", None) == 114286
    assert conversation.context_tokens_for("openrouter", None) == 114286
    small = conversation.compute_run_budget(conversation.context_tokens_for("ollama", None), 4000, 1300)
    large = conversation.compute_run_budget(conversation.context_tokens_for("ollama", product), 4000, 1300)
    assert small == int(3.5 * (8192 - 4096)) - 5300
    assert large == int(3.5 * (32768 - 4096)) - 5300


def test_stub_keeps_output_path_note():
    note = ("[output truncated: 20000 lines, 117 KB. Full text: /x/outputs/abcdef012345.txt. "
            "Don't print it again: read a slice of that file with Tcl.]")
    stub = conversation.stub_tool_result_text("z" * 5000 + "\n" + note + "\nLoop check: this exact call has now run 3 times.")
    assert stub.startswith("z" * 300) and stub.endswith("\n" + note)
    assert len(stub) < 300 + len(note) + 60
    assert conversation.stub_tool_result_text("short") == "short"


def test_legacy_prior_reads_all_message_events_and_drops_trailing_user(tmp_path):
    """Review focus: a legacy chat with 200+ mostly-chunk events keeps every message event."""
    store = ChatStore(root_dir=str(tmp_path / "chats"))
    chat_id = store.create_chat("legacy")
    events = [{"role": "user", "type": "message", "text": "first question", "metadata": {}}]
    events += [{"role": "assistant", "type": "chunk", "text": "w", "metadata": {}} for _ in range(300)]
    events += [{"role": "assistant", "type": "message", "text": "first answer", "metadata": {}},
               {"role": "system", "type": "lifecycle", "text": "cancelled", "metadata": {}},
               {"role": "user", "type": "message", "text": "second question", "metadata": {}}]
    events += [{"role": "assistant", "type": "chunk", "text": "w", "metadata": {}} for _ in range(60)]
    events += [{"role": "assistant", "type": "message", "text": "second answer", "metadata": {}},
               {"role": "user", "type": "message", "text": "the prompt chat.send just persisted", "metadata": {}}]
    store.append_events(chat_id, events)
    stored = store.read_events(chat_id, limit=conversation.ALL_EVENTS)
    assert len(stored) == len(events)
    assert conversation.legacy_prior(stored) == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
        {"role": "assistant", "content": "second answer"},
    ]
    assert events_to_messages(stored)[-1] == {"role": "user", "content": "the prompt chat.send just persisted"}
    two_users = [{"role": "user", "type": "message", "text": "q1"}, {"role": "user", "type": "message", "text": "q2"}]
    assert events_to_messages(two_users, drop_trailing_user=True) == [{"role": "user", "content": "q1"}]


def test_import_legacy_writes_one_exchange_per_user_turn(tmp_path):
    legacy = [user("q1"), {"role": "assistant", "content": "a1"}, user("q2"), {"role": "assistant", "content": "a2"}]
    assert conversation.import_legacy(tmp_path, legacy) == 4
    lines = conversation.read_lines(tmp_path)
    assert [(line["request_id"], line["message"]) for line in lines] == [
        ("legacy_1", legacy[0]), ("legacy_1", legacy[1]), ("legacy_2", legacy[2]), ("legacy_2", legacy[3])]
    assert conversation.import_legacy(tmp_path, legacy) == 0
    assert conversation.build_prior(tmp_path, 10 ** 6, 1) == legacy
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_conversation_prior.py -q`
Expected: `13 failed`, each with `AttributeError: module 'vmd_ai_runtime.conversation' has no attribute …` (`build_prior`, `messages_chars`, `RESERVED_OUTPUT_TOKENS`, `ALL_EVENTS`, `stub_tool_result_text`, `import_legacy`, …). The legacy test stops at `conversation.ALL_EVENTS` before it reaches `events_to_messages(..., drop_trailing_user=True)`.

- [ ] **Step 3: Add `drop_trailing_user` to `events_to_messages`**

In `runtime/vmd_ai_runtime/claude_loop.py`, replace the whole `events_to_messages` function (at 6f5f937: lines 2056-2090) with:

```python
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
```

- [ ] **Step 4: Add the reading side of `conversation.py`**

Append to `runtime/vmd_ai_runtime/conversation.py` (after `read_lines`):

```python
# ---------------------------------------------------------------------------
# Reading: build_prior never writes (§2b)
# ---------------------------------------------------------------------------

RESERVED_OUTPUT_TOKENS = 4096
PRIOR_FRACTION = 0.6
ANTHROPIC_CONTEXT_TOKENS = 114286          # 400k characters at 3.5 chars/token
OLLAMA_LEGACY_NUM_CTX = 8192               # options=None, or options without num_ctx
DEFAULT_CONTEXT_TOKENS = 32768             # C7 product default / openai-compatible
STUB_HEAD_CHARS = 300
CONTEXT_WARN_FRACTION = 0.9
ALL_EVENTS = 10 ** 9                       # ChatStore.read_events limit meaning "no tail"
UNKNOWN_OUTCOME_TEXT = "outcome unknown: the runtime stopped during this command"
OUTPUT_NOTE_PREFIX = "[output truncated:"

_OLLAMA_NAMES = ("ollama", "local-ollama", "local_ollama")
_OPENAI_COMPATIBLE_NAMES = ("openai-compatible", "openai_compatible")
_LARGE_CONTEXT_NAMES = ("anthropic-direct", "anthropic_api", "anthropic-direct-api",
                        "openrouter", "claude", "claude-openrouter")


def compute_run_budget(context_tokens: int, system_prompt_chars: int, tools_json_chars: int) -> int:
    """Characters a request may spend on messages (§2b Budget); never negative."""
    budget = int(CHARS_PER_TOKEN * (int(context_tokens) - RESERVED_OUTPUT_TOKENS))
    return max(0, budget - int(system_prompt_chars) - int(tools_json_chars))


def context_tokens_for(provider: str, options: Optional[Any]) -> int:
    """Context window in tokens for a provider and its (duck-typed) LoopOptions."""
    name = str(provider or "").strip().lower()
    if name in _OLLAMA_NAMES:
        return int(getattr(options, "num_ctx", None) or OLLAMA_LEGACY_NUM_CTX)
    if name in _OPENAI_COMPATIBLE_NAMES:
        return int(getattr(options, "context_length", None) or DEFAULT_CONTEXT_TOKENS)
    if name in _LARGE_CONTEXT_NAMES:
        return ANTHROPIC_CONTEXT_TOKENS
    return DEFAULT_CONTEXT_TOKENS


def max_images_for(provider: str) -> int:
    """Images kept inline in context: 3 for Anthropic/OpenRouter, else 1."""
    return 3 if str(provider or "").strip().lower() in _LARGE_CONTEXT_NAMES else 1


def _without_image_data(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("type") in ("image", "image_ref"):
            return {"type": "image"}
        return {key: _without_image_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_image_data(item) for item in value]
    return value


def messages_chars(messages: List[Dict[str, Any]]) -> int:
    """Character estimate of messages as sent, ignoring image payloads."""
    return sum(len(json.dumps(_without_image_data(m), ensure_ascii=False)) for m in messages)


def _output_note(tail: str) -> str:
    for line in tail.split("\n"):
        if line.lstrip().startswith(OUTPUT_NOTE_PREFIX):
            return line.strip()
    return ""


def stub_tool_result_text(text: str, head: int = STUB_HEAD_CHARS) -> str:
    """A ``head``-char stub of a tool result; a C5 output-path note stays as the last line."""
    text = str(text or "")
    body, tail = split_output_section(text)
    note = _output_note(tail)
    if len(body) <= head and not tail:
        return text
    stub = body if len(body) <= head else (
        body[:head] + " ... [%d chars omitted to save context]" % (len(body) - head))
    return stub + ("\n" + note if note else "")


def _is_result(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "tool_result"


def _is_tool_round(message: Dict[str, Any]) -> bool:
    content = message.get("content")
    return (message.get("role") == "user" and isinstance(content, list)
            and any(_is_result(block) for block in content))


def _tool_use_ids(message: Dict[str, Any]) -> List[str]:
    content = message.get("content")
    if message.get("role") != "assistant" or not isinstance(content, list):
        return []
    return [str(b.get("id")) for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]


def _unknown_result(tool_use_id: str) -> Dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_use_id,
            "content": UNKNOWN_OUTCOME_TEXT, "is_error": True}


def repair_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Answer dangling tool_use blocks and drop orphan tool_result blocks.

    Returns a new list; messages that need no change are shared, never mutated.
    """
    out: List[Dict[str, Any]] = []
    expected: List[str] = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "assistant" and content in ("", None, []):
            continue
        if expected:
            if _is_tool_round(message):
                answered = [b for b in content if _is_result(b) and str(b.get("tool_use_id")) in expected]
                others = [b for b in content if not _is_result(b)]
                have = {str(b.get("tool_use_id")) for b in answered}
                missing = [_unknown_result(x) for x in expected if x not in have]
                out.append(dict(message, content=answered + missing + others))
                expected = []
                continue
            out.append({"role": "user", "content": [_unknown_result(x) for x in expected]})
            expected = []
        if _is_tool_round(message):
            rest = [b for b in content if not _is_result(b)]
            if rest:
                out.append(dict(message, content=rest))
            continue
        out.append(message)
        expected = _tool_use_ids(message)
    if expected:
        out.append({"role": "user", "content": [_unknown_result(x) for x in expected]})
    return out


def _image_slots(messages: List[Dict[str, Any]]) -> List[Tuple[int, int, Optional[int]]]:
    """(message index, block index, part index or None) of every image, oldest first."""
    slots: List[Tuple[int, int, Optional[int]]] = []
    for i, message in enumerate(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for j, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("image", "image_ref"):
                slots.append((i, j, None))
            elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                for k, part in enumerate(block["content"]):
                    if isinstance(part, dict) and part.get("type") in ("image", "image_ref"):
                        slots.append((i, j, k))
    return slots


def _image_stub(block: Dict[str, Any]) -> Dict[str, Any]:
    path = str(block.get("path") or "") if block.get("type") == "image_ref" else ""
    suffix = ": " + path if path else ""
    return {"type": "text", "text": "[earlier snapshot not shown to save context%s]" % suffix}


def _replace_images(messages: List[Dict[str, Any]], drop: set) -> List[Dict[str, Any]]:
    if not drop:
        return messages
    out = list(messages)
    for i in sorted({slot[0] for slot in drop}):
        blocks: List[Any] = []
        for j, block in enumerate(out[i]["content"]):
            if (i, j, None) in drop:
                blocks.append(_image_stub(block))
            elif _is_result(block) and isinstance(block.get("content"), list):
                parts = [_image_stub(part) if (i, j, k) in drop else part
                         for k, part in enumerate(block["content"])]
                blocks.append(dict(block, content=parts))
            else:
                blocks.append(block)
        out[i] = dict(out[i], content=blocks)
    return out


def _stub_result(block: Dict[str, Any]) -> Dict[str, Any]:
    content = block.get("content")
    if isinstance(content, str):
        return dict(block, content=stub_tool_result_text(content))
    if isinstance(content, list):
        parts = [{"type": "text", "text": stub_tool_result_text(str(p.get("text") or ""))}
                 if isinstance(p, dict) and p.get("type") == "text" else p for p in content]
        return dict(block, content=parts)
    return block


def compact_tool_results(messages: List[Dict[str, Any]], *, keep_rounds: int,
                         keep_images: Optional[int] = None) -> List[Dict[str, Any]]:
    """Stub the tool results of all but the last ``keep_rounds`` tool rounds.

    With ``keep_images`` set, images outside the kept rounds become text stubs
    unless they are among the newest ``keep_images`` images. Returns a new
    list; changed messages are new dicts and the input is never mutated.
    """
    rounds = [i for i, message in enumerate(messages) if _is_tool_round(message)]
    protected = set(rounds[-keep_rounds:]) if keep_rounds > 0 else set()
    stubbed = set(rounds) - protected
    out = [dict(m, content=[_stub_result(b) if _is_result(b) else b for b in m["content"]])
           if i in stubbed else m for i, m in enumerate(messages)]
    if keep_images is not None:
        slots = _image_slots(out)
        keep = set(slots[-keep_images:]) if keep_images > 0 else set()
        out = _replace_images(out, {s for s in slots if s not in keep and s[0] not in protected})
    return out


def _limit_images(messages: List[Dict[str, Any]], keep: int) -> List[Dict[str, Any]]:
    slots = _image_slots(messages)
    drop = set(slots[:-keep]) if keep > 0 else set(slots)
    return _replace_images(messages, drop)


def _hydrate_block(block: Dict[str, Any], chat_dir: Path) -> Dict[str, Any]:
    rel = str(block.get("path") or "")
    root = chat_dir.resolve()
    target = (chat_dir / rel).resolve()
    data = b""
    if root in target.parents:
        try:
            data = target.read_bytes()
        except OSError:
            data = b""
    if not data:
        return {"type": "text", "text": "[snapshot file missing: %s]" % rel}
    return {"type": "image", "source": {"type": "base64",
                                        "media_type": str(block.get("media_type") or "image/png"),
                                        "data": base64.b64encode(data).decode("ascii")}}


def _hydrate(messages: List[Dict[str, Any]], chat_dir: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            out.append(message)
            continue
        changed = False
        blocks: List[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_ref":
                blocks.append(_hydrate_block(block, chat_dir))
                changed = True
            elif (_is_result(block) and isinstance(block.get("content"), list)
                  and any(isinstance(p, dict) and p.get("type") == "image_ref" for p in block["content"])):
                parts = [_hydrate_block(p, chat_dir) if isinstance(p, dict) and p.get("type") == "image_ref"
                         else p for p in block["content"]]
                blocks.append(dict(block, content=parts))
                changed = True
            else:
                blocks.append(block)
        out.append(dict(message, content=blocks) if changed else message)
    return out


def _late_note(line: Dict[str, Any]) -> Dict[str, Any]:
    detail = str(line.get("output") or line.get("error") or "").strip().replace("\n", " ")
    if len(detail) > 200:
        detail = detail[:200] + "..."
    status = "ok" if line.get("ok") else "failed"
    text = "[late result] call_%s finished after its request ended: %s (executed: %s). %s" % (
        line.get("call_key"), status, line.get("executed") or "unknown", detail)
    return {"role": "user", "content": text.strip()}


def _group(lines: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Exchanges in order of first appearance, and the notes after the last one.

    A late_result becomes a note in front of the next exchange that starts
    after it, i.e. "before the next prompt".
    """
    exchanges: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    pending: List[Dict[str, Any]] = []
    for line in lines:
        if line["kind"] == "late_result":
            pending.append(_late_note(line))
            continue
        request_id = str(line.get("request_id") or "")
        exchange = by_id.get(request_id)
        if exchange is None:
            exchange = {"notes": pending, "messages": []}
            pending = []
            by_id[request_id] = exchange
            exchanges.append(exchange)
        exchange["messages"].append(line["message"])
    return exchanges, pending


def build_prior(chat_dir: Path, budget_chars: int, max_images: int) -> List[Dict[str, Any]]:
    """Prior messages for the next request (§2b Reading never writes).

    1. read messages.jsonl; 2. repair dangling tool_use blocks; 3. keep whole
    exchanges newest first within PRIOR_FRACTION x ``budget_chars`` (the
    request's run budget), always keeping the latest one and stubbing its
    older tool results when it alone is too big; 4. keep the newest
    ``max_images`` images inline; 5. hydrate the kept image_refs to base64.
    """
    chat_dir = Path(chat_dir)
    lines = read_lines(chat_dir)
    if not lines:
        return []
    exchanges, trailing = _group(lines)
    blocks = [list(ex["notes"]) + repair_messages(ex["messages"]) for ex in exchanges]
    limit = int(PRIOR_FRACTION * max(0, int(budget_chars)))
    kept: List[List[Dict[str, Any]]] = []
    used = messages_chars(trailing)
    for index in range(len(blocks) - 1, -1, -1):
        chunk = blocks[index]
        size = messages_chars(chunk)
        if index == len(blocks) - 1:
            if used + size > limit:
                chunk = compact_tool_results(chunk, keep_rounds=1)
                size = messages_chars(chunk)
        elif used + size > limit:
            break
        kept.insert(0, chunk)
        used += size
    prior = [message for chunk in kept for message in chunk] + list(trailing)
    return _hydrate(_limit_images(prior, max(0, int(max_images))), chat_dir)


def legacy_prior(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Text-only prior for a chat without messages.jsonl (§2b Legacy chats).

    Every ``type=message`` event counts (no 200-event tail); the prompt that
    chat.send has just persisted is dropped so it is not sent twice.
    """
    from .claude_loop import events_to_messages  # late import: claude_loop imports this module

    message_events = [e for e in events if isinstance(e, dict) and e.get("type") == "message"]
    return events_to_messages(message_events, drop_trailing_user=True)


def import_legacy(chat_dir: Path, messages: List[Dict[str, Any]], *,
                  clock: Callable[[], float] = time.time) -> int:
    """Seed a new messages.jsonl from a legacy chat's text history.

    Each user message starts an exchange ``legacy_<n>``. Never touches an
    existing messages.jsonl and never rewrites events.jsonl. Returns the
    number of lines written.
    """
    chat_dir = Path(chat_dir)
    if not messages or messages_path(chat_dir).exists():
        return 0
    turn = 0
    appender = Appender(chat_dir, "legacy_0", clock=clock)
    for message in messages:
        if message.get("role") == "user":
            turn += 1
            appender = Appender(chat_dir, "legacy_%d" % turn, clock=clock)
        appender.append(message)
    return len(messages)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_conversation_prior.py tests/test_conversation_appender.py -q`
Expected: `20 passed`.

- [ ] **Step 6: Run the S7 guards and the product suite**

Run: `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_hashes.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_retry_pin.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures (only `events_to_messages` changed, and its default is today's output).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+20 passed, 1 xfailed`.

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/conversation.py runtime/vmd_ai_runtime/claude_loop.py tests/test_conversation_prior.py
git commit -m "feat(runtime): build_prior with repair, budget, images and legacy path (P03-T02)

build_prior reads messages.jsonl, repairs dangling tool calls, keeps whole
exchanges newest first within 60% of the run budget, caps inline images,
renders late results as notes and never writes. events_to_messages gains
drop_trailing_user for the legacy dedupe fix.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T03: Store lock, per-chat lock, public chat_dir

**Files:**
- Create: `runtime/vmd_ai_runtime/locks.py`
- Modify: `runtime/vmd_ai_runtime/store.py:1-140` (whole file; plan 02 does not touch it)
- Create: `tests/test_store_locks.py`
- Modify: `tests/test_py39_compat.py` (`RUNTIME_MODULES` literal)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - locks.store_lock(root: Path) -> ContextManager[None] (flock on root/'.store.lock')
  - class locks.ChatLock(chat_dir: Path) with .acquire() -> bool, .release() -> None, .held -> bool
  - ChatStore.chat_dir(chat_id: str) -> Path; ChatStore.exists(chat_id: str) -> bool
  - manifest and index writes happen under store_lock
  - plan-local additions: `ChatStore.lock_root: Path` (`~/.vmdai` for the default store, the store directory itself for a custom `root_dir`); `ChatStore.append_events` returns 0 for a falsy `chat_id` (a token session has `chat_id` null until its first `chat.send`); `ChatStore._chat_dir` stays as an alias

- [ ] **Step 1: Write the failing tests**

Create `tests/test_store_locks.py`:

```python
"""P03-T03: store lock, per-chat lock, public chat_dir (§2b Concurrency, §2f Writes, §7)."""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from vmd_ai_runtime.locks import ChatLock
from vmd_ai_runtime.store import ChatStore

RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"

CHAT_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from vmd_ai_runtime.locks import ChatLock
lock = ChatLock(Path(sys.argv[2]))
print("held" if lock.acquire() else "busy", flush=True)
time.sleep(60)
"""

STORE_HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from vmd_ai_runtime.locks import store_lock
with store_lock(Path(sys.argv[2])):
    print("locked", flush=True)
    time.sleep(float(sys.argv[3]))
"""


def _spawn(script, *args):
    proc = subprocess.Popen([sys.executable, "-c", script, str(RUNTIME_DIR)] + [str(a) for a in args],
                            stdout=subprocess.PIPE, text=True)
    return proc, proc.stdout.readline().strip()


def test_chat_lock_exclusive_across_processes(tmp_path):
    proc, line = _spawn(CHAT_HOLDER, tmp_path)
    try:
        assert line == "held"
        mine = ChatLock(tmp_path)
        assert mine.acquire() is False and mine.held is False
    finally:
        proc.kill()
        proc.wait(5)


def test_chat_lock_released_on_kill(tmp_path):
    """Review focus: the OS frees the per-chat lock when the holder is SIGKILLed."""
    proc, line = _spawn(CHAT_HOLDER, tmp_path)
    assert line == "held"
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(5)
    mine = ChatLock(tmp_path)
    assert mine.acquire() is True and mine.held is True
    other = ChatLock(tmp_path)
    assert other.acquire() is False            # exclusive inside one process too
    mine.release()
    assert mine.held is False and other.acquire() is True
    other.release()
    assert (tmp_path / ".lock").exists()


def test_store_lock_serialises_index_appends(tmp_path):
    store = ChatStore(root_dir=str(tmp_path / "chats"))
    assert store.lock_root == tmp_path / "chats"
    chat_id = store.create_chat("t")
    proc, line = _spawn(STORE_HOLDER, store.lock_root, 0.8)
    try:
        assert line == "locked"
        t0 = time.monotonic()
        store.append_events(chat_id, [{"role": "user", "type": "message", "text": "hi", "metadata": {}}])
        assert time.monotonic() - t0 >= 0.4          # waited for the other process
    finally:
        proc.wait(5)

    def touch():
        for _ in range(40):
            store.append_events(chat_id, [{"role": "assistant", "type": "chunk", "text": "x", "metadata": {}}])

    threads = [threading.Thread(target=touch) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = [json.loads(line) for line in store.index_path.read_text(encoding="utf-8").splitlines()]
    assert store.get_manifest(chat_id)["message_count"] == 161    # no lost read-modify-write
    assert rows[-1]["message_count"] == 161


def test_create_chat_unchanged_for_legacy_callers(tmp_path):
    store = ChatStore(root_dir=str(tmp_path))
    chat_id = store.create_chat("My chat")
    assert re.match(r"^chat_[0-9a-f]{12}$", chat_id)
    assert store.chat_dir(chat_id) == tmp_path / chat_id == store._chat_dir(chat_id)
    assert store.exists(chat_id)
    assert not store.exists("chat_000000000000") and not store.exists("")
    manifest = store.get_manifest(chat_id)
    assert set(manifest) == {"chat_id", "title", "created_at", "updated_at", "message_count"}
    assert manifest["title"] == "My chat" and manifest["message_count"] == 0
    assert (store.chat_dir(chat_id) / "events.jsonl").read_text() == ""
    assert json.loads(store.index_path.read_text().splitlines()[0])["chat_id"] == chat_id
    assert store.append_events(None, [{"role": "user"}]) == 0
    assert ChatStore().lock_root == Path(os.path.expanduser("~/.vmdai"))   # the hermetic HOME
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_store_locks.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'vmd_ai_runtime.locks'`, `1 error`.

- [ ] **Step 3: Write `locks.py`**

Create `runtime/vmd_ai_runtime/locks.py`:

```python
"""locks.py - advisory file locks shared by every runtime on this machine.

store_lock(root): an exclusive fcntl.flock on root/.store.lock around every
write to settings.json, a chat's manifest.json and index.jsonl (§2f Writes).
ChatLock(chat_dir): a non-blocking exclusive flock on chats/<id>/.lock held
while a session has that chat open (§2b Concurrency).

flock locks belong to an open file description, so two opens in one process
exclude each other too, and the OS drops them when the process dies (even on
SIGKILL). File descriptors from os.open are not inherited by child processes.
POSIX only; stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import errno
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

STORE_LOCK_NAME = ".store.lock"
CHAT_LOCK_NAME = ".lock"
_BUSY_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES)


@contextmanager
def store_lock(root: Path) -> Iterator[None]:
    """Hold the exclusive store lock for the duration of the ``with`` block.

    Never nest two store_lock blocks for the same root in one thread: the
    second open would wait for the first forever.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(root / STORE_LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


class ChatLock:
    """Exclusive, non-blocking lock on chats/<id>/.lock."""

    def __init__(self, chat_dir: Path) -> None:
        self.path = Path(chat_dir) / CHAT_LOCK_NAME
        self._fd: Optional[int] = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> bool:
        """Take the lock; False when another holder (process or object) has it."""
        if self._fd is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in _BUSY_ERRNOS:
                return False
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
```

- [ ] **Step 4: Put ChatStore's shared writes under the store lock**

Replace the whole of `runtime/vmd_ai_runtime/store.py` with:

```python
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .locks import store_lock


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ChatStore:
    """Chats under ~/.vmdai/chats (or ``root_dir``).

    Writes to a chat's manifest.json and to index.jsonl run under the
    store lock (locks.store_lock), because several runtimes may share the
    directory (§2f Writes, §7 Several runtimes). The default store shares
    ~/.vmdai/.store.lock with settings.json; a custom ``root_dir`` keeps its
    own lock file inside that directory.
    """

    def __init__(self, root_dir: str | None = None):
        self.root_dir = Path(root_dir or os.path.expanduser("~/.vmdai/chats"))
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_dir / "index.jsonl"
        self.lock_root = self.root_dir.parent if root_dir is None else self.root_dir

    def chat_dir(self, chat_id: str) -> Path:
        return self.root_dir / chat_id

    def _chat_dir(self, chat_id: str) -> Path:
        # Kept for callers written before chat_dir became public.
        return self.chat_dir(chat_id)

    def exists(self, chat_id: str) -> bool:
        return bool(chat_id) and (self.chat_dir(chat_id) / "manifest.json").is_file()

    def create_chat(self, title_hint: str = "") -> str:
        chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        chat_dir = self.chat_dir(chat_id)
        chat_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "chat_id": chat_id,
            "title": title_hint.strip() or "New Chat",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "message_count": 0,
        }
        with store_lock(self.lock_root):
            self._write_manifest(chat_id, manifest)
            (chat_dir / "events.jsonl").touch()
            self._append_index_row({"chat_id": chat_id, "title": manifest["title"], "updated_at": manifest["updated_at"]})
        return chat_id

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

    def list_chats(self, limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        latest: Dict[str, Dict[str, Any]] = {}
        with self.index_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                chat_id = str(row.get("chat_id") or "")
                if not chat_id:
                    continue
                latest[chat_id] = row
        rows = sorted(latest.values(), key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        safe_offset = max(0, int(offset or 0))
        safe_limit = max(1, min(int(limit or 30), 200))
        return rows[safe_offset:safe_offset + safe_limit]

    def get_manifest(self, chat_id: str) -> Dict[str, Any] | None:
        """Return the manifest dict for a chat, or None if it doesn't exist."""
        if not chat_id:
            return None
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def read_events(self, chat_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Read persisted events from a chat's JSONL log.

        Returns at most *limit* events (most recent if the file has more).
        """
        events_path = self.chat_dir(chat_id) / "events.jsonl"
        if not events_path.exists():
            return []
        all_events: List[Dict[str, Any]] = []
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    all_events.append(json.loads(line))
                except Exception:
                    continue
        # Return the tail (most-recent events) if we exceed *limit*
        if len(all_events) > limit:
            return all_events[-limit:]
        return all_events

    def update_title(self, chat_id: str, title: str) -> None:
        """Update the display title for a chat."""
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return
            manifest["title"] = title.strip() or manifest.get("title", "New Chat")
            self._write_manifest(chat_id, manifest)

    def _touch_manifest(self, chat_id: str, delta_messages: int = 0) -> None:
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        if not manifest_path.exists():
            return
        with store_lock(self.lock_root):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                return
            manifest["updated_at"] = _now_iso()
            manifest["message_count"] = int(manifest.get("message_count") or 0) + int(delta_messages or 0)
            self._write_manifest(chat_id, manifest)
            self._append_index_row({
                "chat_id": chat_id,
                "title": manifest.get("title") or "New Chat",
                "updated_at": manifest["updated_at"],
                "message_count": manifest["message_count"],
            })

    # Callers hold the store lock; these two never take it themselves.

    def _write_manifest(self, chat_id: str, manifest: Dict[str, Any]) -> None:
        manifest_path = self.chat_dir(chat_id) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_index_row(self, row: Dict[str, Any]) -> None:
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_store_locks.py tests/test_store.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Register the module for the Python 3.9 import check**

In `tests/test_py39_compat.py`, add `"vmd_ai_runtime.locks",` to the `RUNTIME_MODULES` literal.

Run: `python -m pytest tests/test_py39_compat.py -q`
Expected: `4 passed` (or `1 passed, 3 skipped` without a 3.9 `/usr/bin/python3`).

- [ ] **Step 7: Run the whole product suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+24 passed, 1 xfailed`.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/locks.py runtime/vmd_ai_runtime/store.py tests/test_store_locks.py tests/test_py39_compat.py
git commit -m "feat(runtime): store and per-chat flock locks; public ChatStore.chat_dir (P03-T03)

Manifest and index writes run under ~/.vmdai/.store.lock; ChatLock holds
chats/<id>/.lock with LOCK_EX|LOCK_NB, which the OS frees when a runtime
dies. append_events ignores a chat_id that is still null.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T04: App memory wiring: full mode, lazy chats, resume conflicts (S1)

**Files:**
- Create: `tests/helpers/app_driver.py` (plan-local helper, see Deviations)
- Create: `tests/test_memory_integration.py`
- Modify: `runtime/vmd_ai_runtime/constants.py:36` (`CONVERSATION_MODES`)
- Modify: `runtime/vmd_ai_runtime/events.py:35-39` (add `last_seq` after `clear`)
- Modify: `runtime/vmd_ai_runtime/sessions.py:1-28` (imports; `SessionState.chat_id` and a new last field after plan 02's `lock`)
- Modify: `runtime/vmd_ai_runtime/app.py` — at 6f5f937: imports 13-35, `session.start` 191-220 (the `create_chat` line is 192), `session.stop` 222-226, `chat.send` 230-287, `chat.resume` 323-340, `_run_claude_loop_response` 557-677, `_cancel_active_request` 747-751. Plan 02 rewrote `chat.send` and `_run_claude_loop_response` and moved the rest; every step below quotes plan 02's text.
- Not modified: `runtime/vmd_ai_runtime/protocol.py` — the `chat.send` validator already checks `conversation_mode` against `CONVERSATION_MODES` (see Deviations).

**Interfaces:**
- Consumes: Appender, build_prior, legacy_prior, compute_run_budget, context_tokens_for, max_images_for (P03-T01/T02); ChatLock, ChatStore.chat_dir (P03-T03); RunContext (P02-T05); profile_for_session, loop_factory (P02-T10); plan-local `conversation.ALL_EVENTS`, `import_legacy`, `ChatStore.exists` (P03-T02/T03); `SessionState.authenticated`, `SessionState.lock` (P02-T02/T10); plan 02's `RuntimeApp._build_loop(profile)`, `_assigned_loop`; `helpers.runtime_fixture.make_app`, `rpc` (P02-T02)
- Produces:
  - CONVERSATION_MODES adds 'full'
  - token session.start -> chat_id null; first chat.send creates the chat, locks it and returns {request_id, chat_id}
  - SessionState.chat_lock: Optional[ChatLock]
  - token chat.resume: REQUEST_CONFLICT, CHAT_LOCKED; result adds last_seq
  - RuntimeApp._run_budget_for(loop, system_prompt: str) -> int
  - EventQueue.last_seq -> int
  - ctx = RunContext(request_id, chat_id, on_event, Appender(chat_dir, request_id))
  - plan-local additions: `RuntimeApp._new_loop_for(state) -> Optional[ClaudeToolLoop]` (`self._build_loop(self.profile_for_session(state))`: the one place request code builds a loop), `_open_new_chat(state) -> str`, `_release_chat_lock(state) -> None`, `_request_running(state) -> bool`, `_clear_active(state, request_id) -> None`, `_system_prompt_for_request(state) -> str`, `_prior_for(state, chat_id, conv_mode, loop, system_prompt) -> Optional[List[Dict]]`, `_resume_token_session(state, chat_id) -> Dict`; `_run_claude_loop_response(session_id, request_id, prompt, cancel_event, prior_messages=None, loop=None, chat_id=None, system_prompt=None)`
  - test helpers: `helpers.app_driver.TOKEN`, `Session`, `make_token_app(tmp_path, **kw)`, `call(app, method, params=None, session=None) -> envelope`, `result(envelope)`, `error_code(envelope)`, `start(app, tmp_path, *, token=TOKEN) -> Session`, `send(app, session, text, **extra)`, `state_of(app, session)`, `wait_idle(app, session, timeout=5.0)`, `tool_use(tool_id, command)`, `InstantBridge`, `ScriptedLoop`

- [ ] **Step 1: Add the RPC driver used by the app-level tests**

Create `tests/helpers/app_driver.py`:

```python
"""In-process driver for RuntimeApp tests (plan 03).

Builds on plan 02's helpers.runtime_fixture: make_token_app is make_app with
a launch token, and call() is rpc() for a Session object, so a test can
assert on the raw envelope's ``result`` or ``error.code``. ScriptedLoop
replays model turns; InstantBridge answers tool calls at once with the
strict six-keyword signature.
"""
from __future__ import annotations

import copy
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from helpers.runtime_fixture import make_app, rpc
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.constants import DEFAULT_SETTINGS

TOKEN = "0123456789abcdef0123456789abcdef"


class Session:
    """A started session: the session.start result and the ids rpc() needs."""

    def __init__(self, result: Dict[str, Any]) -> None:
        self.result = result
        self.session_id = result["session_id"]
        self.token = result["session_token"]


def make_token_app(tmp_path: Path, **kw: Any) -> RuntimeApp:
    """plan 02's make_app (mock provider, no RAG, no wiki) that also knows TOKEN.

    Tokenless sessions are still accepted (allow_tokenless_v1 defaults to True).
    """
    kw.setdefault("launch_token", TOKEN)
    return make_app(tmp_path, **kw)


def call(app: RuntimeApp, method: str, params: Optional[Dict[str, Any]] = None,
         session: Optional[Session] = None) -> Dict[str, Any]:
    """One JSON-RPC call in process; returns the whole envelope ({result} or {error})."""
    return rpc(app, method, params, session.result if session is not None else None)


def result(envelope: Dict[str, Any]) -> Any:
    assert "result" in envelope, envelope
    return envelope["result"]


def error_code(envelope: Dict[str, Any]) -> str:
    assert "error" in envelope, envelope
    return envelope["error"]["code"]


def start(app: RuntimeApp, tmp_path: Path, *, token: str = TOKEN) -> Session:
    """session.start with a temp cwd; ``token=""`` starts a tokenless session."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    params: Dict[str, Any] = {"cwd": str(work), "event_protocol": 1}
    if token:
        params["launch_token"] = token
    return Session(result(call(app, "session.start", params)))


def send(app: RuntimeApp, session: Session, text: str, **extra: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {"text": text, "conversation_mode": "full"}
    params.update(extra)
    return call(app, "chat.send", params, session)


def state_of(app: RuntimeApp, session: Session):
    return app.sessions.get(session.session_id)


def wait_idle(app: RuntimeApp, session: Session, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = state_of(app, session)
        request = state.active_request if state is not None else None
        if request is None or (request.thread is not None and not request.thread.is_alive()):
            return
        time.sleep(0.01)
    raise AssertionError("request still running after %.1f s" % timeout)


def tool_use(tool_id: str, command: str) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": "run_vmd_command", "input": {"command": command}}


class InstantBridge:
    """Strict six-keyword bridge that answers every tool call at once."""

    def __init__(self, output: Callable[[Dict[str, Any]], str] = lambda tool_input: "ok") -> None:
        self.output = output
        self.calls: List[Dict[str, Any]] = []

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name, "tool_input": tool_input})
        return {"ok": True, "output": self.output(tool_input), "error": ""}


class ScriptedLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose model turns come from a script.

    Each ``_call`` records a deep copy of the messages it was given, runs
    ``before_call(call_number, messages)`` when set (call_number starts at 1),
    and returns the next ``(text, tool_blocks)`` pair, or ``("Done.", [])``
    once the script is used up. The default model is the session default
    (DEFAULT_SETTINGS["model"]), so plan 02's per-session model override
    never swaps an assigned ScriptedLoop for a plain ClaudeToolLoop.
    """

    def __init__(self, script: Sequence[Tuple[str, List[Dict[str, Any]]]], *,
                 before_call: Optional[Callable[[int, List[Dict[str, Any]]], Any]] = None,
                 **kw: Any) -> None:
        kw.setdefault("provider_name", "anthropic-direct")
        kw.setdefault("api_key", "sk-test")
        kw.setdefault("model", DEFAULT_SETTINGS["model"])
        super().__init__(**kw)
        self.script = list(script)
        self.calls: List[List[Dict[str, Any]]] = []
        self.before_call = before_call
        self._script_lock = threading.Lock()

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self.calls.append(copy.deepcopy(messages))
        if self.before_call is not None:
            self.before_call(len(self.calls), messages)
        with self._script_lock:
            text, blocks = self.script.pop(0) if self.script else ("Done.", [])
        if text:
            on_text(text)
        return text, copy.deepcopy(blocks)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_memory_integration.py`:

```python
"""P03-T04: app memory wiring, lazy chats, resume conflicts (S1, §2b, §3)."""
from __future__ import annotations

import json
import re
import threading

from helpers.app_driver import (
    InstantBridge,
    ScriptedLoop,
    call,
    error_code,
    make_token_app,
    result,
    send,
    start,
    state_of,
    tool_use,
    wait_idle,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.locks import ChatLock

CHAT_ID_RE = re.compile(r"^chat_[0-9a-f]{12}$")


def _blocks(messages, kind):
    return [b for m in messages if isinstance(m.get("content"), list) for b in m["content"] if b.get("type") == kind]


def test_followup_sees_prior_tool_blocks(tmp_path):
    """S1: the second chat.send's prior carries turn 1's tool_use and tool_result."""
    app = make_token_app(tmp_path)
    app.tool_bridge = InstantBridge(lambda tool_input: "Info) Loaded 1hck")
    loop = ScriptedLoop([
        ("Loading.", [tool_use("tc_0", "mol new 1hck.pdb")]),
        ("Loaded 1hck.", []),
        ("Coloured it red.", []),
    ])
    app.claude_loop = loop
    session = start(app, tmp_path)
    first = result(send(app, session, "load 1hck"))
    wait_idle(app, session)
    second = result(send(app, session, "now color it red"))
    wait_idle(app, session)
    assert first["chat_id"] == second["chat_id"]
    seen = loop.calls[2]
    assert seen[0] == {"role": "user", "content": "load 1hck"}
    assert seen[-1] == {"role": "user", "content": "now color it red"}
    uses = _blocks(seen[:-1], "tool_use")
    results = _blocks(seen[:-1], "tool_result")
    assert len(uses) == 1 and re.match(r"^call_[0-9a-f]{12}$", uses[0]["id"])
    assert uses[0]["input"] == {"command": "mol new 1hck.pdb"}
    assert results[0]["tool_use_id"] == uses[0]["id"]
    assert "Info) Loaded 1hck" in json.dumps(results[0])


def test_messages_jsonl_written_incrementally(tmp_path):
    app = make_token_app(tmp_path)
    app.tool_bridge = InstantBridge()
    counts = []
    holder = []

    def before_call(number, messages):
        chat_dir = app.store.chat_dir(state_of(app, holder[0]).chat_id)
        counts.append(len(conversation.read_lines(chat_dir)))

    app.claude_loop = ScriptedLoop([("", [tool_use("tc_0", "molinfo list")]), ("Two molecules.", [])],
                                   before_call=before_call)
    session = start(app, tmp_path)
    holder.append(session)
    request_id = result(send(app, session, "what is loaded?"))["request_id"]
    wait_idle(app, session)
    lines = conversation.read_lines(app.store.chat_dir(state_of(app, session).chat_id))
    assert counts == [1, 3]          # prompt; then prompt + assistant turn + tool results
    assert [line["message"]["role"] for line in lines] == ["user", "assistant", "user", "assistant"]
    assert {line["request_id"] for line in lines} == {request_id}


def test_lazy_chat_creation(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path)
    assert session.result["chat_id"] is None
    assert app.store.list_chats() == []
    reply = result(send(app, session, "hello"))
    wait_idle(app, session)
    assert CHAT_ID_RE.match(reply["chat_id"]) and app.store.exists(reply["chat_id"])
    assert [row["chat_id"] for row in app.store.list_chats()] == [reply["chat_id"]]
    assert state_of(app, session).chat_lock.held
    assert ChatLock(app.store.chat_dir(reply["chat_id"])).acquire() is False


def test_resume_conflict_while_busy(tmp_path):
    app = make_token_app(tmp_path)
    gate = threading.Event()
    app.claude_loop = ScriptedLoop([("slow answer", [])], before_call=lambda number, messages: gate.wait(5))
    session = start(app, tmp_path)
    result(send(app, session, "take your time"))
    other = app.store.create_chat("other")
    try:
        assert error_code(call(app, "chat.resume", {"chat_id": other}, session)) == "REQUEST_CONFLICT"
        assert error_code(send(app, session, "again")) == "REQUEST_CONFLICT"
    finally:
        gate.set()
    wait_idle(app, session)
    assert result(call(app, "chat.resume", {"chat_id": other}, session))["chat_id"] == other


def test_resume_locked_chat_returns_chat_locked(tmp_path):
    """Review focus: two runtimes resume the same chat; the second gets CHAT_LOCKED."""
    first_app = make_token_app(tmp_path)
    first_app.claude_loop = ScriptedLoop([("hi", [])])
    first = start(first_app, tmp_path)
    chat_id = result(send(first_app, first, "hello"))["chat_id"]
    wait_idle(first_app, first)
    second_app = make_token_app(tmp_path)          # a second runtime on the same chats directory
    second = start(second_app, tmp_path)
    envelope = call(second_app, "chat.resume", {"chat_id": chat_id}, second)
    assert error_code(envelope) == "CHAT_LOCKED"
    assert envelope["error"]["data"] == {"chat_id": chat_id}
    assert result(call(first_app, "session.stop", {}, first))["ok"] is True
    resumed = result(call(second_app, "chat.resume", {"chat_id": chat_id}, second))
    assert resumed["chat_id"] == chat_id and isinstance(resumed["last_seq"], int)
    assert state_of(second_app, second).chat_lock.held
    polled = result(call(second_app, "chat.events.poll", {"after_seq": resumed["last_seq"], "limit": 50}, second))
    assert [event["text"] for event in polled["events"]] == ["chat_resumed"]


def test_new_chat_releases_lock(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path)
    chat_id = result(send(app, session, "hello"))["chat_id"]
    wait_idle(app, session)
    probe = ChatLock(app.store.chat_dir(chat_id))
    assert probe.acquire() is False
    result(call(app, "session.stop", {}, session))        # New Chat = session.stop + session.start
    assert probe.acquire() is True
    probe.release()
    assert start(app, tmp_path).result["chat_id"] is None


def test_tokenless_eager_creation_unchanged(tmp_path):
    app = make_token_app(tmp_path)
    app.claude_loop = ScriptedLoop([("hi", [])])
    session = start(app, tmp_path, token="")
    chat_id = session.result["chat_id"]
    assert CHAT_ID_RE.match(chat_id) and app.store.exists(chat_id)
    reply = result(send(app, session, "hello", conversation_mode="local_first"))
    wait_idle(app, session)
    assert reply == {"request_id": reply["request_id"]}          # no chat_id field for tokenless sessions
    assert not conversation.messages_path(app.store.chat_dir(chat_id)).exists()
    assert state_of(app, session).chat_lock is None


def test_hybrid_resume_no_duplicate_prompt(tmp_path):
    app = make_token_app(tmp_path)
    loop = ScriptedLoop([("first answer", []), ("second answer", [])])
    app.claude_loop = loop
    session = start(app, tmp_path, token="")
    result(send(app, session, "first question", conversation_mode="local_first"))
    wait_idle(app, session)
    result(send(app, session, "second question", conversation_mode="hybrid_resume"))
    wait_idle(app, session)
    assert loop.calls[1] == [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second question"},
    ]


def test_token_resume_legacy_chat_imports_history(tmp_path):
    app = make_token_app(tmp_path)
    legacy = app.store.create_chat("old chat")
    app.store.append_events(legacy, [
        {"role": "user", "type": "message", "text": "load 1hck", "metadata": {}},
        {"role": "assistant", "type": "chunk", "text": "Lo", "metadata": {}},
        {"role": "assistant", "type": "message", "text": "Loaded.", "metadata": {}},
    ])
    loop = ScriptedLoop([("Red now.", [])])
    app.claude_loop = loop
    session = start(app, tmp_path)
    result(call(app, "chat.resume", {"chat_id": legacy}, session))
    result(send(app, session, "color it red"))
    wait_idle(app, session)
    assert loop.calls[0] == [
        {"role": "user", "content": "load 1hck"},
        {"role": "assistant", "content": "Loaded."},
        {"role": "user", "content": "color it red"},
    ]
    ids = [line["request_id"] for line in conversation.read_lines(app.store.chat_dir(legacy))]
    assert ids[:2] == ["legacy_1", "legacy_1"] and ids[2].startswith("req_")


def test_event_queue_last_seq():
    queue = EventQueue()
    assert queue.last_seq == 0
    queue.push("system", "lifecycle", "a")
    queue.push("system", "lifecycle", "b")
    assert queue.last_seq == 2


def test_run_budget_for_matches_loop(tmp_path):
    app = make_token_app(tmp_path)
    loop = ScriptedLoop([], provider_name="ollama", api_key="http://127.0.0.1:9")
    system = "system prompt"
    expected = conversation.compute_run_budget(8192, len(system), len(json.dumps(loop._tools_for_turn())))
    assert app._run_budget_for(loop, system) == expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_memory_integration.py -q`
Expected: `11 failed` — the `chat.send` tests with `AssertionError: {'jsonrpc': '2.0', 'id': 't', 'error': {'code': 'INVALID_PARAMS', 'message': 'conversation_mode is invalid', …}}` ("full" is not a mode yet), `test_lazy_chat_creation` on `assert 'chat_…' is None`, `AttributeError: 'EventQueue' object has no attribute 'last_seq'`, `AttributeError: 'SessionState' object has no attribute 'chat_lock'`, `AttributeError: 'RuntimeApp' object has no attribute '_run_budget_for'`, and `test_hybrid_resume_no_duplicate_prompt` because plan 02 still sends the prompt twice.

- [ ] **Step 4: Constants, events and sessions**

In `runtime/vmd_ai_runtime/constants.py`, replace:

```python
CONVERSATION_MODES = ("local_first", "hybrid_resume", "resume_only")
```

with:

```python
CONVERSATION_MODES = ("local_first", "hybrid_resume", "resume_only", "full")
```

In `runtime/vmd_ai_runtime/events.py`, replace:

```python
    def clear(self) -> None:
        """Drop all events and reset the sequence counter."""
        with self._lock:
            self._events.clear()
            self._seq = 0
```

with:

```python
    def clear(self) -> None:
        """Drop all events and reset the sequence counter."""
        with self._lock:
            self._events.clear()
            self._seq = 0

    @property
    def last_seq(self) -> int:
        """Sequence number of the newest event pushed (0 when none)."""
        with self._lock:
            return self._seq
```

In `runtime/vmd_ai_runtime/sessions.py`, replace:

```python
from .events import EventQueue
```

with:

```python
from .events import EventQueue
from .locks import ChatLock
```

then replace:

```python
    cwd: str
    chat_id: str
```

with:

```python
    cwd: str
    # None for a token session until its first chat.send creates the chat (§2b).
    chat_id: Optional[str]
```

and replace (the last field plan 02 added):

```python
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
```

with:

```python
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # Held while this session has its chat open (token sessions only, §2b).
    chat_lock: Optional[ChatLock] = field(default=None, repr=False, compare=False)
```

- [ ] **Step 5: App imports and the session lifecycle edits**

In `runtime/vmd_ai_runtime/app.py`, replace:

```python
import hmac
import os
import threading
from typing import Any, Callable, Dict, Optional
```

with:

```python
import hmac
import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional
```

Replace (app.py no longer uses `events_to_messages`):

```python
from .claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    RunContext,
    VMD_SYSTEM_PROMPT,
    build_claude_loop,
    events_to_messages,
)
```

with:

```python
from . import conversation
from .claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    RunContext,
    VMD_SYSTEM_PROMPT,
    WIKI_SYSTEM_PROMPT_ADDENDUM,
    build_claude_loop,
)
from .locks import ChatLock
```

In the `session.start` branch, replace:

```python
            chat_id = self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(
```

with:

```python
            # Token sessions create their chat lazily on the first chat.send
            # (§2b Lock lifecycle); tokenless sessions keep eager creation.
            chat_id = None if authenticated else self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(
```

In the `session.stop` branch, replace:

```python
            self._cancel_active_request(state)
            self.sessions.remove(state.session_id)
```

with:

```python
            self._cancel_active_request(state)
            self._release_chat_lock(state)
            self.sessions.remove(state.session_id)
```

At the top of the `chat.resume` branch, replace:

```python
        if method == "chat.resume":
            state = self._get_session(params["session_id"], session_token)
            self._cancel_active_request(state)
```

with (the tokenless code below it stays as it is):

```python
        if method == "chat.resume":
            state = self._get_session(params["session_id"], session_token)
            if state.authenticated:
                return self._resume_token_session(state, params["chat_id"])
            self._cancel_active_request(state)
```

- [ ] **Step 6: Replace the `chat.send` branch**

Replace the whole `chat.send` branch that plan 02 wrote — from `        if method == "chat.send":` through its `            return {"request_id": request_id}` (just before `        if method == "chat.cancel":`) — with:

```python
        if method == "chat.send":
            state = self._get_session(params["session_id"], session_token)
            if params.get("model"):
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
            if params.get("conversation_mode"):
                state.settings["conversation_mode"] = params["conversation_mode"]

            # The session lock makes check-then-start atomic (plan 02). The
            # chat is captured here, so the worker keeps writing to it even if
            # the session later resumes another chat.
            with state.lock:
                if self._request_running(state):
                    raise RpcError("REQUEST_CONFLICT", "an active request is already running")
                # A fresh loop for this request (None: mock mode).
                loop = self._new_loop_for(state)
                if state.chat_id is None:
                    self._open_new_chat(state)
                chat_id = state.chat_id
                request_id = f"req_{os.urandom(6).hex()}"
                request = RequestState(request_id=request_id)
                state.active_request = request
                try:
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
                        system_prompt = self._system_prompt_for_request(state)
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
```

- [ ] **Step 7: Replace `_run_claude_loop_response` and add the helpers**

Replace the whole `_run_claude_loop_response` method that plan 02 wrote — from `    def _run_claude_loop_response(` through its last lines

```python
        # Unbind the per-task recorder so an assigned (shared) loop doesn't
        # carry this run's recorder into the next chat.send.
        loop.recorder = prev_recorder
```

— with:

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
        """Full agentic response on a daemon thread.

        chat.send passes the loop it built for this request, the chat it
        captured when the request started, and the system prompt the prior
        was budgeted for. Token sessions also get a messages.jsonl Appender
        (full memory, §2b).
        """
        state = self.sessions.get(session_id)
        if state is None:
            return
        if loop is None:
            self._clear_active(state, request_id)
            return
        if chat_id is None:
            chat_id = state.chat_id
        if system_prompt is None:
            system_prompt = self._system_prompt_for_request(state)
        chunk_events: List[Dict[str, Any]] = []

        def on_chunk(chunk: str) -> None:
            chunk_events.append(
                state.queue.push("assistant", "chunk", chunk, {"request_id": request_id})
            )

        def on_tool_start(tool_name: str, tool_input: dict) -> None:
            # Tool start events are pushed directly by VmdToolBridge
            pass

        def on_tool_result(tool_id: str, tool_name: str, result: dict) -> None:
            # Transcript entry for tool results is written in tool.command_result handler
            pass

        # The session's model setting overrides the loop's model (plan 02).
        # A per-request loop is adjusted in place; an assigned loop is shared
        # between requests, so it gets a copy that keeps the wiki store.
        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        if model and model != loop.model:
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

        messages_out = None
        if state.authenticated and chat_id:
            messages_out = conversation.Appender(self.store.chat_dir(chat_id), request_id)
        ctx = RunContext(request_id=request_id, chat_id=chat_id or "", on_event=None,
                         messages_out=messages_out)

        # Per-request recorder; restored afterwards so an assigned (shared)
        # loop never carries it into the next request.
        prev_recorder = loop.recorder
        loop.recorder = self._build_recorder_for_session(state)
        events_to_persist: List[Dict[str, Any]] = []
        try:
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

Then replace the `_cancel_active_request` method:

```python
    def _cancel_active_request(self, state) -> None:
        active = state.active_request
        if not active:
            return
        active.cancel_event.set()
```

with itself followed by the memory helpers:

```python
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
            state.queue.clear()
            # Polling after last_seq delivers the chat_resumed event below.
            last_seq = state.queue.last_seq
            state.queue.push("system", "lifecycle", "chat_resumed", {"chat_id": chat_id})
        return {
            "ok": True,
            "chat_id": chat_id,
            "title": manifest.get("title", ""),
            "message_count": manifest.get("message_count", 0),
            "last_seq": last_seq,
        }

    def _system_prompt_for_request(self, state) -> str:
        mode = str(state.settings.get("mode") or "work")
        return VMD_SYSTEM_PROMPT + f"\n\nMode: {mode}."

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
            return conversation.legacy_prior(events) or None
        return None
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_memory_integration.py -q`
Expected: `11 passed`.

- [ ] **Step 9: Run the app-level suites plan 02 owns, then the whole product suite**

Run: `python -m pytest tests/test_loop_factory.py tests/test_launch_token.py tests/test_agent_integration.py tests/test_recorder_integration.py tests/test_runtime_integration.py tests/test_provider_selection.py tests/test_security_notice.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+35 passed, 1 xfailed`.

- [ ] **Step 10: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/constants.py runtime/vmd_ai_runtime/events.py runtime/vmd_ai_runtime/sessions.py tests/helpers/app_driver.py tests/test_memory_integration.py
git commit -m "feat(runtime): full-memory chats, lazy creation and resume locks (S1, P03-T04)

Token sessions create their chat on the first chat.send, lock it, write
messages.jsonl through the Appender and send a budgeted build_prior with
tool blocks. chat.resume gains REQUEST_CONFLICT, CHAT_LOCKED and last_seq;
legacy chats are seeded once into messages.jsonl; tokenless sessions keep
eager creation plus the duplicate-prompt fix.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T05: settings_store: schema, migration, precedence, flock

**Files:**
- Create: `runtime/vmd_ai_runtime/settings_store.py`
- Create: `tests/test_settings_store.py`
- Modify: `tests/test_py39_compat.py` (`RUNTIME_MODULES` literal)

**Interfaces:**
- Consumes: locks.store_lock (P03-T03)
- Produces:
  - settings_store.SETTINGS_VERSION = 1; TOP_LEVEL_DEFAULTS
  - class SettingsError(Exception) with .code in IN_USE|READ_ONLY|NOT_FOUND|INVALID
  - class SettingsStore(home: Optional[str] = None): .path, .exists(), .load(), .settings_source ('file'|'newer'|'invalid'|'default'), .active_profile() -> Tuple[Optional[str], Optional[Dict]], .get_profile(name), .list_profiles(), .save_profile(name, profile, activate=False), .delete_profile(name), .activate(name), .patch(patch) -> Dict, .update_profile(name, *, provider=None, model=None, base_url=None, options=None) -> Dict
  - settings_store.resolve_profile(store, cli_provider: Optional[str], env: Mapping[str, str]) -> Tuple[Optional[str], Optional[Dict], str]
  - plan-local additions: `normalize_provider(name) -> str` ('' for unknown), `KNOWN_PROVIDERS`, `DEFAULT_BASE_URLS`, `DEFAULT_PROFILE_NAMES`, `DEFAULT_MODELS`, `DEFAULT_OLLAMA_NUM_CTX = 32768`, `default_settings() -> Dict`, `SettingsStore.root` (`<home>/.vmdai`); `resolve_profile` sources are `'cli' | 'profile' | 'none'` (VMD_AI_PROVIDER is seed-only); `save_profile` and `update_profile` return the stored profile; `patch` returns the top-level settings after the write

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_store.py`:

```python
"""P03-T05: settings_store schema, migration, precedence, flock (§2f, §7, C7)."""
from __future__ import annotations

import json
import stat

import pytest

from vmd_ai_runtime import settings_store
from vmd_ai_runtime.settings_store import SettingsError, SettingsStore, resolve_profile

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b",
        "options": {"num_ctx": 32768, "think": True, "keep_alive": "30m"}}


def _settings_file(tmp_path):
    path = tmp_path / ".vmdai" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_round_trip(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    assert store.path == tmp_path / ".vmdai" / "settings.json"
    assert not store.exists() and store.settings_source == "default"
    assert store.active_profile() == (None, None)
    assert store.save_profile("qwen-tunnel", QWEN, activate=True) == QWEN
    again = SettingsStore(home=str(tmp_path))
    assert again.exists() and again.settings_source == "file"
    assert again.active_profile() == ("qwen-tunnel", QWEN)
    assert again.list_profiles() == {"qwen-tunnel": QWEN}
    data = again.load()
    assert data["version"] == settings_store.SETTINGS_VERSION == 1
    assert settings_store.TOP_LEVEL_DEFAULTS == {
        "reasoning_visible": True, "wiki_enabled": False, "approval_mode": "auto",
        "max_turns": 28, "tool_exec_timeout_s": 900, "cancel_grace_s": 30}
    for key, value in settings_store.TOP_LEVEL_DEFAULTS.items():
        assert data[key] == value
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert store.patch({"max_turns": 12, "wiki_enabled": True})["max_turns"] == 12
    assert SettingsStore(home=str(tmp_path)).load()["wiki_enabled"] is True


def test_migrates_version_0(tmp_path):
    path = _settings_file(tmp_path)
    path.write_text(json.dumps({"active": "qwen", "profiles": {"qwen": QWEN}, "max_turns": 20}))
    store = SettingsStore(home=str(tmp_path))
    data = store.load()
    on_disk = json.loads(path.read_text())
    assert on_disk["version"] == 1 and on_disk["profiles"] == {"qwen": QWEN} and on_disk["active"] == "qwen"
    assert on_disk["max_turns"] == 20 and on_disk["reasoning_visible"] is True
    assert data == on_disk and store.settings_source == "file"
    path.write_text(json.dumps({"version": 0, "profiles": {}}))
    assert SettingsStore(home=str(tmp_path)).load()["version"] == 1


def test_newer_version_read_only(tmp_path):
    path = _settings_file(tmp_path)
    raw = json.dumps({"version": 2, "active": "qwen", "profiles": {"qwen": QWEN}, "future": {"x": 1}})
    path.write_text(raw)
    store = SettingsStore(home=str(tmp_path))
    assert store.settings_source == "newer"
    assert store.active_profile() == ("qwen", QWEN)
    writes = (lambda: store.save_profile("b", QWEN), lambda: store.patch({"max_turns": 3}),
              lambda: store.activate("qwen"), lambda: store.update_profile("qwen", model="m"),
              lambda: store.delete_profile("qwen"))
    for write in writes:
        with pytest.raises(SettingsError) as info:
            write()
        assert info.value.code == "READ_ONLY"
    assert path.read_text() == raw


def test_invalid_json_read_only(tmp_path):
    """Review focus: a hand-edited file that does not parse is never overwritten."""
    path = _settings_file(tmp_path)
    raw = '{"version": 1, "active": "qwen", "profiles": {"qwen": {"provider": "ollama",}}'
    path.write_text(raw)
    store = SettingsStore(home=str(tmp_path))
    assert store.exists() and store.settings_source == "invalid"
    assert store.load()["profiles"] == {} and store.active_profile() == (None, None)
    with pytest.raises(SettingsError) as info:
        store.save_profile("qwen", QWEN, activate=True)
    assert info.value.code == "READ_ONLY"
    assert path.read_text() == raw
    path.write_text("[1, 2]")
    assert SettingsStore(home=str(tmp_path)).settings_source == "invalid"


def test_unknown_option_keys_preserved(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", dict(QWEN, options={"num_ctx": 16384, "future_knob": {"a": 1}}), activate=True)
    store.update_profile("qwen", model="qwen3.8:32b")
    store.patch({"max_turns": 30})
    profile = SettingsStore(home=str(tmp_path)).get_profile("qwen")
    assert profile["options"] == {"num_ctx": 16384, "future_knob": {"a": 1}}
    assert profile["model"] == "qwen3.8:32b"


def test_delete_active_in_use(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", QWEN, activate=True)
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    with pytest.raises(SettingsError) as info:
        store.delete_profile("qwen")
    assert info.value.code == "IN_USE"
    store.delete_profile("claude")
    assert set(store.list_profiles()) == {"qwen"}
    with pytest.raises(SettingsError) as missing:
        store.delete_profile("claude")
    assert missing.value.code == "NOT_FOUND"
    with pytest.raises(SettingsError) as unknown:
        store.activate("nope")
    assert unknown.value.code == "NOT_FOUND"


def test_model_change_keeps_num_ctx(tmp_path):
    """C7: a model change keeps the stored num_ctx unless the same call sets it."""
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("qwen", dict(QWEN, options={"num_ctx": 16384}), activate=True)
    assert store.update_profile("qwen", model="llama3.1:8b")["options"]["num_ctx"] == 16384
    changed = store.update_profile("qwen", model="qwen3.8:27b", options={"num_ctx": 8192})
    assert changed["options"]["num_ctx"] == 8192
    assert store.get_profile("qwen")["model"] == "qwen3.8:27b"


def test_provider_change_resets_base_url_and_options(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    store.save_profile("main", QWEN, activate=True)
    claude = store.update_profile("main", provider="anthropic-direct", model="claude-sonnet-4-5")
    assert claude == {"provider": "anthropic-direct", "model": "claude-sonnet-4-5", "options": {}}
    back = store.update_profile("main", provider="ollama", model="qwen3.8:27b")
    assert back["base_url"] == "http://localhost:11434" and back["options"] == {}
    with pytest.raises(SettingsError) as info:
        store.update_profile("main", provider="mock")
    assert info.value.code == "INVALID"


def test_patch_validates_top_level(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    bad_patches = ({"approval_mode": "ask"}, {"max_turns": 0}, {"max_turns": True},
                   {"wiki_enabled": "yes"}, {"colour": "red"}, {"cancel_grace_s": -1})
    for bad in bad_patches:
        with pytest.raises(SettingsError) as info:
            store.patch(bad)
        assert info.value.code == "INVALID"
    assert not store.exists()


def test_precedence_cli_profile_env(tmp_path):
    store = SettingsStore(home=str(tmp_path))
    env = {"VMD_AI_PROVIDER": "anthropic-direct", "ANTHROPIC_MODEL": "claude-sonnet-4-5"}
    # VMD_AI_PROVIDER is seed-only (§7): with no active profile it is ignored.
    assert resolve_profile(store, None, env) == (None, None, "none")
    assert resolve_profile(store, None, {}) == (None, None, "none")
    store.save_profile("qwen", QWEN, activate=True)
    assert resolve_profile(store, None, env) == ("qwen", QWEN, "profile")
    name, profile, source = resolve_profile(store, "openrouter", env)
    assert (name, source) == (None, "cli")
    assert profile["provider"] == "openrouter" and profile["base_url"] == "https://openrouter.ai/api/v1"
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    name, profile, source = resolve_profile(store, "claude", env)
    assert (name, source, profile["provider"]) == ("claude", "cli", "anthropic-direct")
    assert settings_store.normalize_provider("anthropic") == "anthropic-direct"
    assert settings_store.normalize_provider("vllm") == "openai-compatible"
    assert settings_store.normalize_provider("mock") == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_settings_store.py -q`
Expected: collection error `ImportError: cannot import name 'settings_store' from 'vmd_ai_runtime'`, `1 error`.

- [ ] **Step 3: Write the module**

Create `runtime/vmd_ai_runtime/settings_store.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_settings_store.py -q`
Expected: `10 passed`.

- [ ] **Step 5: Register the module and run the suites**

In `tests/test_py39_compat.py`, add `"vmd_ai_runtime.settings_store",` to the `RUNTIME_MODULES` literal.

Run: `python -m pytest tests/test_py39_compat.py -q`
Expected: `4 passed` (or `1 passed, 3 skipped`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+45 passed, 1 xfailed` (the hermetic probe stub tolerates the missing `probe_local_ollama`, Task 0 Step 3).

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/settings_store.py tests/test_settings_store.py tests/test_py39_compat.py
git commit -m "feat(runtime): settings_store profiles, migration and precedence (P03-T05)

settings.json is written under the store lock, atomically and 0600; a newer
or unparsable file is never overwritten. Options keep unknown keys, a model
change keeps num_ctx (C7), and resolve_profile applies CLI > active
profile; VMD_AI_PROVIDER is seed-only and never used live (§7).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T06: First run: probe, profile_from_server (C7), last_provider seed

**Files:**
- Create: `tests/helpers/fake_ollama.py` (plan-local helper, see Deviations)
- Modify: `runtime/vmd_ai_runtime/settings_store.py` (imports; one new `SettingsStore` method; new module-level functions at the end)
- Create: `tests/test_settings_first_run.py`

**Interfaces:**
- Consumes: SettingsStore (P03-T05); conftest real_probe_local_ollama (P01-T01)
- Produces:
  - settings_store.probe_local_ollama(ports: Sequence[int] = (11435, 11434), timeout: float = 0.3) -> List[Dict[str, Any]] — each server is `{"base_url": "http://127.0.0.1:<port>", "version": str, "models": [name, …]}`
  - settings_store.profile_from_server(base_url: str, *, urlopen: Callable[..., Any], server: Optional[Dict] = None) -> Dict[str, Any]
  - SettingsStore.first_run(servers, *, last_provider_path=None, urlopen=None) -> Dict[str, Any] (the settings after the run; writes nothing when no profile was created)
  - plan-local additions: `settings_store.context_length_from_show(show: Dict) -> Optional[int]` (used by P03-T07), `LOCAL_OLLAMA_PORTS = (11435, 11434)`, `SHOW_TIMEOUT_S = 3.0`
  - test helpers: `helpers.fake_ollama.FakeOllama(models=None, version="0.12.3", loaded=None)` with `.requests`, `.paths()`, `.digest(name)`, `.handle(method, path, body)`; `FakeOllamaServer(fake)` context manager with `.port`, `.base_url`; `FakeUrlopen({base_url: FakeOllama})`; `stale_listener()` context manager yielding a port; `closed_port() -> int`

- [ ] **Step 1: Add the Ollama stand-ins**

Create `tests/helpers/fake_ollama.py`:

```python
"""Ollama stand-ins for runtime tests (plan 03).

FakeOllama answers the probe endpoints the runtime may call (/api/version,
/api/tags, /api/show, /api/ps) plus the OpenAI-style GET /v1/models, and
records every request as (monotonic time, method, path, body).
FakeOllamaServer serves one on a real 127.0.0.1 socket; FakeUrlopen serves
several to code that takes an injected ``urlopen``. stale_listener() and
closed_port() give the dead-server cases.

A model spec is a dict with optional keys: capabilities (list), context_length
(int), arch (str, default "qwen3"), size (int), thinking (any; copied into
/api/show as-is).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple


class FakeOllama:
    def __init__(self, models: Optional[Dict[str, Dict[str, Any]]] = None, version: str = "0.12.3",
                 loaded: Optional[List[str]] = None) -> None:
        self.models = dict(models or {})
        self.version = version
        self.loaded = list(loaded or [])
        self.requests: List[Tuple[float, str, str, Dict[str, Any]]] = []
        self._lock = threading.Lock()

    def paths(self) -> List[str]:
        with self._lock:
            return [path for _when, _method, path, _body in self.requests]

    @staticmethod
    def digest(name: str) -> str:
        return hashlib.sha256(name.encode("utf-8")).hexdigest()

    def _tag(self, name: str) -> Dict[str, Any]:
        spec = self.models.get(name, {})
        return {"name": name, "model": name, "size": int(spec.get("size", 1000)), "digest": self.digest(name)}

    def _show(self, name: str) -> Dict[str, Any]:
        spec = self.models[name]
        arch = str(spec.get("arch", "qwen3"))
        info: Dict[str, Any] = {"general.architecture": arch}
        if spec.get("context_length") is not None:
            info["%s.context_length" % arch] = spec["context_length"]
        show: Dict[str, Any] = {"capabilities": list(spec.get("capabilities", ["completion"])),
                                "model_info": info, "details": {"family": arch}}
        if "thinking" in spec:
            show["thinking"] = spec["thinking"]
        return show

    def handle(self, method: str, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        path = urllib.parse.urlsplit(path).path
        with self._lock:
            self.requests.append((time.monotonic(), method, path, body))
        if method == "GET" and path == "/api/version":
            return 200, {"version": self.version}
        if method == "GET" and path == "/api/tags":
            return 200, {"models": [self._tag(name) for name in self.models]}
        if method == "GET" and path == "/api/ps":
            return 200, {"models": [self._tag(name) for name in self.loaded]}
        if method == "POST" and path == "/api/show":
            name = str(body.get("model") or body.get("name") or "")
            if name not in self.models:
                return 404, {"error": "model '%s' not found" % name}
            return 200, self._show(name)
        if method == "GET" and path == "/v1/models":
            return 200, {"object": "list", "data": [{"id": name, "object": "model"} for name in self.models]}
        return 404, {"error": "not found"}


class FakeOllamaServer:
    """Serve a FakeOllama on 127.0.0.1:<ephemeral port>."""

    def __init__(self, fake: FakeOllama) -> None:
        self.fake = fake
        self.port = 0
        self.base_url = ""

    def __enter__(self) -> "FakeOllamaServer":
        fake = self.fake

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, status: int, payload: Dict[str, Any]) -> None:
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                self._reply(*fake.handle("GET", self.path, {}))

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                self._reply(*fake.handle("POST", self.path, body if isinstance(body, dict) else {}))

            def log_message(self, *args: Any) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.port = int(self._httpd.server_address[1])
        self.base_url = "http://127.0.0.1:%d" % self.port
        # A short poll interval keeps shutdown() fast (the default 0.5 s would
        # add half a second to every test that uses a server; S9).
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


class _Response(io.BytesIO):
    def __init__(self, status: int, raw: bytes) -> None:
        super().__init__(raw)
        self.status = status


class FakeUrlopen:
    """A callable with urlopen's signature that routes by scheme://host:port.

    An unknown address raises URLError(ConnectionRefusedError), like a closed port.
    """

    def __init__(self, servers: Mapping[str, FakeOllama]) -> None:
        self.servers = {base.rstrip("/"): fake for base, fake in servers.items()}
        self.timeouts: List[Optional[float]] = []

    def __call__(self, request: Any, timeout: Optional[float] = None, **_kw: Any) -> _Response:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        parts = urllib.parse.urlsplit(url)
        self.timeouts.append(timeout)
        fake = self.servers.get("%s://%s" % (parts.scheme, parts.netloc))
        if fake is None:
            raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        data = getattr(request, "data", None)
        body = json.loads(data.decode("utf-8")) if data else {}
        method = request.get_method() if hasattr(request, "get_method") else "GET"
        status, payload = fake.handle(method, parts.path, body)
        raw = json.dumps(payload).encode("utf-8")
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "HTTP %d" % status, {}, io.BytesIO(raw))
        return _Response(status, raw)


@contextlib.contextmanager
def stale_listener() -> Iterator[int]:
    """A port that accepts TCP connections but never answers (a stale tunnel)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    try:
        yield int(sock.getsockname()[1])
    finally:
        sock.close()


def closed_port() -> int:
    """A loopback port with nothing listening (connection refused)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_settings_first_run.py`:

```python
"""P03-T06: first run: probe, profile_from_server (C7), last_provider seed (§2f)."""
from __future__ import annotations

import inspect
import time

from helpers.fake_ollama import FakeOllama, FakeOllamaServer, FakeUrlopen, stale_listener
from vmd_ai_runtime.settings_store import SettingsStore, profile_from_server

TOOLS = ["completion", "tools"]


def _one_model(context_length):
    return FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS + ["thinking", "vision"],
                                       "context_length": context_length}})


def test_profile_from_server_num_ctx():
    base = "http://127.0.0.1:11435"
    for context_length, expected in ((131072, 32768), (8192, 8192), (None, 32768)):
        profile = profile_from_server(base, urlopen=FakeUrlopen({base: _one_model(context_length)}))
        assert profile == {"provider": "ollama", "base_url": base, "model": "qwen3.8:27b",
                           "options": {"num_ctx": expected}}


def test_probe_order_11435_then_11434(real_probe_local_ollama):
    ports = inspect.signature(real_probe_local_ollama).parameters["ports"].default
    assert tuple(ports) == (11435, 11434)
    first = _one_model(40960)
    second = FakeOllama({"llama3.1:8b": {"capabilities": TOOLS}}, version="0.11.0")
    with FakeOllamaServer(first) as a, FakeOllamaServer(second) as b:
        servers = real_probe_local_ollama(ports=(a.port, b.port), timeout=0.3)
    assert servers == [
        {"base_url": a.base_url, "version": "0.12.3", "models": ["qwen3.8:27b"]},
        {"base_url": b.base_url, "version": "0.11.0", "models": ["llama3.1:8b"]},
    ]
    assert first.requests[0][0] < second.requests[0][0]
    assert first.paths() == ["/api/version", "/api/tags"]


def test_first_responding_becomes_active(tmp_path):
    a, b = "http://127.0.0.1:11435", "http://127.0.0.1:11434"
    opener = FakeUrlopen({a: _one_model(131072),
                          b: FakeOllama({"llama3.1:8b": {"capabilities": TOOLS, "context_length": 8192}})})
    servers = [{"base_url": a, "version": "0.12.3", "models": ["qwen3.8:27b"]},
               {"base_url": b, "version": "0.12.3", "models": ["llama3.1:8b"]}]
    store = SettingsStore(home=str(tmp_path))
    data = store.first_run(servers, urlopen=opener)
    assert data["active"] == "ollama-11435"
    assert data["profiles"] == {
        "ollama-11435": {"provider": "ollama", "base_url": a, "model": "qwen3.8:27b", "options": {"num_ctx": 32768}},
        "ollama-11434": {"provider": "ollama", "base_url": b, "model": "llama3.1:8b", "options": {"num_ctx": 8192}},
    }
    assert store.settings_source == "file"
    empty = SettingsStore(home=str(tmp_path / "empty"))
    assert empty.first_run([], urlopen=opener)["profiles"] == {}
    assert not empty.exists()


def test_seed_from_last_provider_never_active(tmp_path):
    (tmp_path / ".vmdai").mkdir()
    (tmp_path / ".vmdai" / "last_provider.txt").write_text("anthropic-direct\tclaude-sonnet-4-5")
    data = SettingsStore(home=str(tmp_path)).first_run([])
    assert data["active"] is None
    assert data["profiles"] == {"claude": {"provider": "anthropic-direct", "model": "claude-sonnet-4-5", "options": {}}}
    other = tmp_path / "other"
    (other / ".vmdai").mkdir(parents=True)
    (other / ".vmdai" / "last_provider.txt").write_text("openrouter\tanthropic/claude-sonnet-4.6")
    base = "http://127.0.0.1:11435"
    data = SettingsStore(home=str(other)).first_run(
        [{"base_url": base, "version": "0.12.3", "models": ["qwen3.8:27b"]}],
        urlopen=FakeUrlopen({base: _one_model(40960)}))
    assert data["active"] == "ollama-11435"
    assert data["profiles"]["openrouter"] == {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1",
                                              "model": "anthropic/claude-sonnet-4.6", "options": {}}


def test_ollama_seed_merged_into_ollama_port_profile(tmp_path):
    (tmp_path / ".vmdai").mkdir()
    (tmp_path / ".vmdai" / "last_provider.txt").write_text("ollama\tqwen-small:4b\n")
    base = "http://127.0.0.1:11435"
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS, "context_length": 131072},
                       "qwen-small:4b": {"capabilities": TOOLS, "context_length": 16384}})
    data = SettingsStore(home=str(tmp_path)).first_run(
        [{"base_url": base, "version": "0.12.3", "models": ["qwen3.8:27b", "qwen-small:4b"]}],
        urlopen=FakeUrlopen({base: fake}))
    assert data["profiles"] == {"ollama-11435": {"provider": "ollama", "base_url": base,
                                                 "model": "qwen-small:4b", "options": {"num_ctx": 16384}}}
    assert data["active"] == "ollama-11435"


def test_model_prefers_tools_capability():
    base = "http://127.0.0.1:11434"
    fake = FakeOllama({"llava:7b": {"capabilities": ["completion", "vision"], "context_length": 4096},
                       "qwen3.8:27b": {"capabilities": TOOLS, "context_length": 40960}})
    profile = profile_from_server(base, urlopen=FakeUrlopen({base: fake}))
    assert profile["model"] == "qwen3.8:27b" and profile["options"] == {"num_ctx": 32768}
    only_text = FakeOllama({"llava:7b": {"capabilities": ["completion"], "context_length": 4096}})
    assert profile_from_server(base, urlopen=FakeUrlopen({base: only_text}))["model"] == "llava:7b"


def test_probe_bounded_timeout(real_probe_local_ollama):
    """Review focus: a stale tunnel (accepts, never answers) costs about 300 ms per port."""
    with stale_listener() as first, stale_listener() as second:
        t0 = time.monotonic()
        servers = real_probe_local_ollama(ports=(first, second), timeout=0.3)
        elapsed = time.monotonic() - t0
    assert servers == []
    assert elapsed < 1.5
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_settings_first_run.py -q`
Expected: collection error `ImportError: cannot import name 'profile_from_server' from 'vmd_ai_runtime.settings_store'`, `1 error`.

- [ ] **Step 4: Add the first-run code**

In `runtime/vmd_ai_runtime/settings_store.py`, extend the imports to:

```python
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
```

Add after `DEFAULT_OLLAMA_NUM_CTX = 32768`:

```python
LOCAL_OLLAMA_PORTS = (11435, 11434)        # the SSH tunnel first, then a local Ollama
SHOW_TIMEOUT_S = 3.0
```

Add this method to `SettingsStore`, after `update_profile`:

```python
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
```

Append at the end of the module:

```python
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


def probe_local_ollama(ports: Sequence[int] = (11435, 11434), timeout: float = 0.3) -> List[Dict[str, Any]]:
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_settings_first_run.py tests/test_settings_store.py -q`
Expected: `17 passed`.

- [ ] **Step 6: Run the whole product suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+52 passed, 1 xfailed` (the hermetic conftest now stubs the real `probe_local_ollama`).

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/settings_store.py tests/helpers/fake_ollama.py tests/test_settings_first_run.py
git commit -m "feat(runtime): first-run Ollama probe and C7 num_ctx cap (P03-T06)

probe_local_ollama asks :11435 then :11434 with a 300 ms budget each;
first_run saves ollama-<port> profiles with the first tools model and
num_ctx = min(32768, context_length), activates the first responder, and
seeds last_provider.txt without ever activating the seed.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T07: provider_catalog: models.list, provider.test, preflight helpers

**Files:**
- Create: `runtime/vmd_ai_runtime/provider_catalog.py`
- Create: `tests/test_provider_catalog.py`
- Modify: `tests/test_py39_compat.py` (`RUNTIME_MODULES` literal)

**Interfaces:**
- Consumes: nothing from the skeleton's earlier tasks; plan-local: `settings_store.normalize_provider`, `DEFAULT_BASE_URLS`, `context_length_from_show` (P03-T05/T06); test helpers `helpers.fake_ollama.*` (P03-T06)
- Produces:
  - provider_catalog.list_models(provider: str, base_url: Optional[str], *, api_key: str = '', timeout: float = 3.0) -> Dict[str, Any]
  - provider_catalog.test_provider(provider, base_url, model, *, api_key='', timeout=3.0) -> Dict[str, Any]
  - provider_catalog.ollama_version(base_url: str, timeout: float = 2.0) -> str
  - provider_catalog.ollama_ps(base_url: str, timeout: float = 2.0) -> List[Dict[str, Any]]
  - provider_catalog.ollama_show(base_url: str, model: str, timeout: float = 3.0) -> Dict[str, Any]
  - provider_catalog.model_capabilities(show: Dict[str, Any]) -> Dict[str, bool]
  - provider_catalog.cached_tag_digest(base_url: str, model: str) -> Optional[str]
  - provider_catalog.unreachable_hint(base_url: str, case: str) -> str (case refused|reset|timeout)
  - provider_catalog.clear_caches() -> None; provider_catalog._now clock hook
  - plan-local additions: `classify_unreachable(exc) -> Optional[str]` ('refused'|'reset'|'timeout'|None; P04-T01 reuses it), `NO_TOOLS_HINT`, `ANTHROPIC_STATIC_MODELS`, `CATALOG_TTL_S = 60.0`, `VERSION_TTL_S = 30.0`. `list_models` returns `{models, source}` with source `server|cache|static|error|none`, plus `error` and (Ollama unreachable) `hint`. `ollama_version`/`ollama_ps`/`ollama_show` raise the underlying urllib/socket error so callers can classify it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_provider_catalog.py`:

```python
"""P03-T07: provider_catalog (§3, §2f Probes, Thinking detection, Unreachable classification; C9).

Never import provider_catalog.test_provider by name into this module: pytest
would collect it as a test. Always call it as provider_catalog.test_provider(...).
"""
from __future__ import annotations

import time
import urllib.request

import pytest

from helpers.fake_ollama import FakeOllama, FakeOllamaServer, closed_port, stale_listener
from vmd_ai_runtime import provider_catalog

TOOLS = ["completion", "tools"]


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(provider_catalog, "_now", lambda: now[0])
    return now


def test_list_models_ollama_cached_60s(clock):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS + ["vision"], "context_length": 131072,
                                       "size": 17000000000}})
    with FakeOllamaServer(fake) as server:
        first = provider_catalog.list_models("ollama", server.base_url)
        assert first == {"source": "server", "models": [{
            "id": "qwen3.8:27b", "label": "qwen3.8:27b", "size": 17000000000,
            "capabilities": {"tools": True, "vision": True, "thinking": False}, "context_length": 131072}]}
        calls = len(fake.requests)
        clock[0] += 59
        again = provider_catalog.list_models("ollama", server.base_url)
        assert again["source"] == "cache" and again["models"] == first["models"]
        assert len(fake.requests) == calls
        clock[0] += 2
        assert provider_catalog.list_models("ollama", server.base_url)["source"] == "server"
        assert len(fake.requests) > calls


def test_version_cached_30s_ps_never_cached(clock):
    fake = FakeOllama({"m": {"capabilities": TOOLS}}, loaded=["m"])
    with FakeOllamaServer(fake) as server:
        assert provider_catalog.ollama_version(server.base_url) == "0.12.3"
        clock[0] += 29
        assert provider_catalog.ollama_version(server.base_url) == "0.12.3"
        assert fake.paths().count("/api/version") == 1
        clock[0] += 2
        provider_catalog.ollama_version(server.base_url)
        assert fake.paths().count("/api/version") == 2
        for _ in range(3):
            assert [m["name"] for m in provider_catalog.ollama_ps(server.base_url)] == ["m"]
        assert fake.paths().count("/api/ps") == 3


def test_clear_caches(clock):
    fake = FakeOllama({"m": {"capabilities": TOOLS}})
    with FakeOllamaServer(fake) as server:
        provider_catalog.list_models("ollama", server.base_url)
        provider_catalog.ollama_version(server.base_url)
        assert provider_catalog.cached_tag_digest(server.base_url, "m") == fake.digest("m")
        assert provider_catalog.cached_tag_digest(server.base_url, "other") is None
        provider_catalog.clear_caches()
        assert provider_catalog.cached_tag_digest(server.base_url, "m") is None
        before = len(fake.requests)
        assert provider_catalog.list_models("ollama", server.base_url)["source"] == "server"
        provider_catalog.ollama_version(server.base_url)
        assert fake.paths()[before:].count("/api/version") == 1


def test_capabilities_prefer_thinking_object():
    caps = provider_catalog.model_capabilities
    assert caps({"capabilities": ["completion", "tools", "vision", "thinking"]}) == {
        "tools": True, "vision": True, "thinking": True}
    assert caps({"capabilities": ["completion", "tools"], "thinking": {"supported": True}})["thinking"] is True
    assert caps({"capabilities": ["thinking"], "thinking": {"supported": False}})["thinking"] is False
    assert caps({"capabilities": ["thinking"], "thinking": False})["thinking"] is False
    assert caps({}) == {"tools": False, "vision": False, "thinking": False}


def test_provider_test_warns_without_tools():
    fake = FakeOllama({"llava:7b": {"capabilities": ["completion", "vision"]},
                       "qwen3.8:27b": {"capabilities": TOOLS}}, loaded=["qwen3.8:27b"])
    with FakeOllamaServer(fake) as server:
        plain = provider_catalog.test_provider("ollama", server.base_url, "llava:7b")
        good = provider_catalog.test_provider("ollama", server.base_url, "qwen3.8:27b")
        missing = provider_catalog.test_provider("ollama", server.base_url, "nope:1b")
    assert plain["ok"] is True and plain["reachable"] is True and plain["model_present"] is True
    assert plain["loaded"] is False and plain["capabilities"]["tools"] is False
    assert plain["hint"] == provider_catalog.NO_TOOLS_HINT
    assert isinstance(plain["latency_ms"], int)
    assert good["ok"] is True and good["loaded"] is True and "hint" not in good
    assert good["version"] == "0.12.3"                  # FakeOllama's /api/version (Part B V4)
    assert missing["ok"] is False and missing["model_present"] is False
    assert missing["hint"] == "ollama pull nope:1b"


def test_unreachable_hints_exact_wording():
    hint = provider_catalog.unreachable_hint
    assert hint("http://127.0.0.1:11435", "refused") == \
        "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"
    assert hint("http://127.0.0.1:11435", "reset") == \
        "The tunnel on :11435 is up, but Ollama on the GPU server is not answering. Start `ollama serve` there."
    assert hint("http://127.0.0.1:11435", "timeout") == \
        "No reply from :11435 within 2 s. The tunnel may be stale; restart it."
    assert hint("http://127.0.0.1:11434", "refused") == \
        "Nothing is listening on 127.0.0.1:11434. Is `ollama serve` running?"
    base = "http://127.0.0.1:%d" % closed_port()
    refused = provider_catalog.test_provider("ollama", base, "m")
    assert refused["reachable"] is False and refused["ok"] is False
    assert refused["hint"] == hint(base, "refused")
    with stale_listener() as stale:
        t0 = time.monotonic()
        silent = provider_catalog.test_provider("ollama", "http://127.0.0.1:%d" % stale, "m", timeout=0.3)
        assert time.monotonic() - t0 < 1.5
    assert silent["reachable"] is False and "within 2 s" in silent["hint"]


def test_only_allowlisted_paths(clock):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": TOOLS, "context_length": 40960}}, loaded=["qwen3.8:27b"])
    with FakeOllamaServer(fake) as server:
        provider_catalog.list_models("ollama", server.base_url)
        provider_catalog.test_provider("ollama", server.base_url, "qwen3.8:27b")
        provider_catalog.ollama_version(server.base_url)
        provider_catalog.ollama_ps(server.base_url)
        provider_catalog.ollama_show(server.base_url, "qwen3.8:27b")
    assert set(fake.paths()) <= {"/api/version", "/api/tags", "/api/show", "/api/ps"}
    assert "/api/chat" not in fake.paths() and "/api/generate" not in fake.paths()


def test_urlopen_reached_by_attribute(monkeypatch, clock):
    seen = []
    real = urllib.request.urlopen

    def spy(request, *args, **kwargs):
        seen.append(request.full_url)
        return real(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    with FakeOllamaServer(FakeOllama({"m": {"capabilities": TOOLS}})) as server:
        provider_catalog.ollama_version(server.base_url)
    assert seen == [server.base_url + "/api/version"]


def test_openai_compatible_and_anthropic_catalogs(clock):
    fake = FakeOllama({"Qwen/Qwen3-8B": {}})
    with FakeOllamaServer(fake) as server:
        listed = provider_catalog.list_models("openai-compatible", server.base_url + "/v1", api_key="EMPTY")
        tested = provider_catalog.test_provider("openai-compatible", server.base_url + "/v1",
                                                "Qwen/Qwen3-8B", api_key="EMPTY")
    assert listed == {"source": "server", "models": [{"id": "Qwen/Qwen3-8B", "label": "Qwen/Qwen3-8B"}]}
    assert tested["ok"] is True and tested["model_present"] is True and tested["loaded"] is None
    anthropic = provider_catalog.list_models("anthropic-direct", None)
    assert anthropic["source"] == "static" and anthropic["models"][0]["id"] == "claude-sonnet-4-6"
    assert provider_catalog.list_models("mock", None)["source"] == "none"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_provider_catalog.py -q`
Expected: collection error `ImportError: cannot import name 'provider_catalog' from 'vmd_ai_runtime'`, `1 error`.

- [ ] **Step 3: Write the module**

Create `runtime/vmd_ai_runtime/provider_catalog.py`:

```python
"""provider_catalog.py - model catalogues, connection tests and Ollama probes.

Only these Ollama endpoints are called: /api/version, /api/tags, /api/show
and /api/ps (never /api/chat or /api/generate). OpenAI-compatible servers and
OpenRouter are asked for GET <base>/models. Every request goes through
``urllib.request.urlopen`` by attribute access, so tests and the cassette
fake (C9) can serve it. Caches are keyed by base_url and emptied by
clear_caches(); ``_now`` is the clock tests patch.

Numbers (§2a, §2f): /api/version has a 2 s timeout and is cached 30 s;
/api/ps has a 2 s timeout and is never cached; models.list and provider.test
probes use 3 s; catalogues and /api/show results are cached 60 s.
Stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import copy
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .settings_store import DEFAULT_BASE_URLS, context_length_from_show, normalize_provider

_now = time.monotonic

CATALOG_TTL_S = 60.0
VERSION_TTL_S = 30.0
PROBE_TIMEOUT_S = 3.0
PREFLIGHT_TIMEOUT_S = 2.0
OLLAMA_LOCAL_PORT = 11434
ANTHROPIC_STATIC_MODELS = ("claude-sonnet-4-6", "claude-sonnet-4-5")
UNREACHABLE_CASES = ("refused", "reset", "timeout")
NO_TOOLS_HINT = ("This model does not advertise tool support. ChatVMD needs tools to run VMD "
                 "commands; choose a model with the tools capability.")

_lock = threading.Lock()
_version_cache: Dict[str, Tuple[float, str]] = {}
_tags_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_show_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_catalog_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}


def clear_caches() -> None:
    """Forget every cached version, tag list, /api/show result and catalogue."""
    with _lock:
        _version_cache.clear()
        _tags_cache.clear()
        _show_cache.clear()
        _catalog_cache.clear()


def _base(base_url: Optional[str], provider: str = "ollama") -> str:
    return str(base_url or DEFAULT_BASE_URLS.get(provider) or "").strip().rstrip("/")


def _fresh(entry: Optional[Tuple[float, Any]], ttl: float) -> bool:
    return entry is not None and (_now() - entry[0]) < ttl


def _request_json(method: str, url: str, *, body: Optional[Dict[str, Any]] = None,
                  headers: Optional[Dict[str, str]] = None, timeout: float = PROBE_TIMEOUT_S) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    all_headers = {"Accept": "application/json"}
    if data is not None:
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8") or "null")


def _auth_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": "Bearer " + api_key} if api_key else {}


def _describe(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    text = str(reason if reason is not None else exc).strip()
    return text or exc.__class__.__name__


def _elapsed_ms(t0: float) -> int:
    return int(round((time.monotonic() - t0) * 1000.0))


# -- Ollama probes ----------------------------------------------------------

def ollama_version(base_url: str, timeout: float = PREFLIGHT_TIMEOUT_S) -> str:
    """GET /api/version, cached 30 s per base_url. Raises the transport error."""
    base = _base(base_url)
    with _lock:
        entry = _version_cache.get(base)
    if _fresh(entry, VERSION_TTL_S):
        return entry[1]
    payload = _request_json("GET", base + "/api/version", timeout=timeout)
    version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
    with _lock:
        _version_cache[base] = (_now(), version)
    return version


def ollama_ps(base_url: str, timeout: float = PREFLIGHT_TIMEOUT_S) -> List[Dict[str, Any]]:
    """GET /api/ps (loaded models); never cached. Raises the transport error."""
    payload = _request_json("GET", _base(base_url) + "/api/ps", timeout=timeout)
    models = payload.get("models") if isinstance(payload, dict) else None
    return [m for m in models or [] if isinstance(m, dict)]


def _ollama_tags(base: str, timeout: float) -> List[Dict[str, Any]]:
    payload = _request_json("GET", base + "/api/tags", timeout=timeout)
    models = payload.get("models") if isinstance(payload, dict) else None
    tags = [m for m in models or [] if isinstance(m, dict)]
    with _lock:
        _tags_cache[base] = (_now(), tags)
    return tags


def ollama_show(base_url: str, model: str, timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """POST /api/show {model}, cached 60 s per (base_url, model). Raises the transport error."""
    base = _base(base_url)
    key = (base, str(model))
    with _lock:
        entry = _show_cache.get(key)
    if _fresh(entry, CATALOG_TTL_S):
        return copy.deepcopy(entry[1])
    payload = _request_json("POST", base + "/api/show", body={"model": str(model)}, timeout=timeout)
    show = payload if isinstance(payload, dict) else {}
    with _lock:
        _show_cache[key] = (_now(), show)
    return copy.deepcopy(show)


def model_capabilities(show: Dict[str, Any]) -> Dict[str, bool]:
    """tools/vision/thinking from /api/show; a ``thinking`` object wins over the list (§2f)."""
    if not isinstance(show, dict):
        show = {}
    caps = [str(c) for c in show.get("capabilities") or []]
    thinking_field = show.get("thinking")
    if isinstance(thinking_field, bool):
        thinking = thinking_field
    elif isinstance(thinking_field, dict):
        thinking = bool(thinking_field.get("supported", True))
    else:
        thinking = "thinking" in caps
    return {"tools": "tools" in caps, "vision": "vision" in caps, "thinking": thinking}


def cached_tag_digest(base_url: str, model: str) -> Optional[str]:
    """The digest of ``model`` from a /api/tags answer seen in the last 60 s, else None."""
    with _lock:
        entry = _tags_cache.get(_base(base_url))
    if not _fresh(entry, CATALOG_TTL_S):
        return None
    for tag in entry[1]:
        if model in (tag.get("name"), tag.get("model")):
            digest = tag.get("digest")
            return str(digest) if digest else None
    return None


# -- Unreachable classification (§2f) -----------------------------------------

def classify_unreachable(exc: BaseException) -> Optional[str]:
    """'refused', 'reset' or 'timeout' for a dead server; None for anything else."""
    reason: Any = exc
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        reason = exc.reason
    if isinstance(reason, ConnectionRefusedError):
        return "refused"
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                           http.client.RemoteDisconnected, http.client.BadStatusLine)):
        return "reset"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    return None


def unreachable_hint(base_url: str, case: str) -> str:
    """The user-facing hint for one of the three unreachable cases (§2f table)."""
    raw = str(base_url or "").strip()
    parts = urllib.parse.urlsplit(raw if "://" in raw else "http://" + raw)
    host = parts.hostname or "127.0.0.1"
    try:
        port = parts.port or OLLAMA_LOCAL_PORT
    except ValueError:
        port = OLLAMA_LOCAL_PORT
    local = host in ("127.0.0.1", "localhost", "::1")
    tunnel = local and port != OLLAMA_LOCAL_PORT
    where = "%s:%d" % (host, port)
    if case == "refused":
        if tunnel:
            return "Nothing is listening on %s. Is the SSH tunnel up?" % where
        if local:
            return "Nothing is listening on %s. Is `ollama serve` running?" % where
        return "Nothing is listening on %s. Is `ollama serve` running on %s?" % (where, host)
    if case == "reset":
        if tunnel:
            return ("The tunnel on :%d is up, but Ollama on the GPU server is not answering. "
                    "Start `ollama serve` there." % port)
        return "%s accepted the connection but Ollama did not answer. Restart `ollama serve`." % where
    if case == "timeout":
        if tunnel:
            return "No reply from :%d within 2 s. The tunnel may be stale; restart it." % port
        return "No reply from %s within 2 s. Ollama may be stuck; restart `ollama serve`." % where
    raise ValueError("case must be one of " + ", ".join(UNREACHABLE_CASES))


# -- models.list ---------------------------------------------------------------

def _ollama_catalog(base: str, timeout: float) -> List[Dict[str, Any]]:
    models: List[Dict[str, Any]] = []
    for tag in _ollama_tags(base, timeout):
        name = str(tag.get("name") or tag.get("model") or "")
        if not name:
            continue
        entry: Dict[str, Any] = {"id": name, "label": name}
        if isinstance(tag.get("size"), int):
            entry["size"] = tag["size"]
        try:
            show = ollama_show(base, name, timeout)
        except Exception:
            show = None
        if show is not None:
            entry["capabilities"] = model_capabilities(show)
            context_length = context_length_from_show(show)
            if context_length:
                entry["context_length"] = context_length
        models.append(entry)
    return models


def _openai_catalog(base: str, api_key: str, timeout: float) -> List[Dict[str, Any]]:
    payload = _request_json("GET", base + "/models", headers=_auth_headers(api_key), timeout=timeout)
    data = payload.get("data") if isinstance(payload, dict) else None
    models: List[Dict[str, Any]] = []
    for item in data or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        entry: Dict[str, Any] = {"id": str(item["id"]), "label": str(item.get("name") or item["id"])}
        if isinstance(item.get("context_length"), int):
            entry["context_length"] = item["context_length"]
        models.append(entry)
    return models


def list_models(provider: str, base_url: Optional[str], *, api_key: str = "",
                timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """{models:[{id,label,size?,capabilities?,context_length?}], source, error?, hint?}."""
    name = normalize_provider(provider)
    if name == "anthropic-direct":
        return {"models": [{"id": m, "label": m} for m in ANTHROPIC_STATIC_MODELS], "source": "static"}
    if name not in ("ollama", "openai-compatible", "openrouter"):
        return {"models": [], "source": "none", "error": "unknown provider %r" % (provider or "")}
    base = _base(base_url, name)
    key = (name, base)
    with _lock:
        entry = _catalog_cache.get(key)
    if _fresh(entry, CATALOG_TTL_S):
        cached = copy.deepcopy(entry[1])
        cached["source"] = "cache"
        return cached
    try:
        models = _ollama_catalog(base, timeout) if name == "ollama" else _openai_catalog(base, api_key, timeout)
    except Exception as exc:
        out: Dict[str, Any] = {"models": [], "source": "error", "error": _describe(exc)}
        case = classify_unreachable(exc)
        if case is not None and name == "ollama":
            out["hint"] = unreachable_hint(base, case)
        return out
    result = {"models": models, "source": "server"}
    with _lock:
        _catalog_cache[key] = (_now(), copy.deepcopy(result))
    return result


# -- provider.test -------------------------------------------------------------

def _test_ollama_model(base: str, model: str, timeout: float, out: Dict[str, Any]) -> None:
    if not model:
        out["ok"] = True
        return
    try:
        tags = _ollama_tags(base, timeout)
        loaded = ollama_ps(base, timeout)
    except Exception as exc:
        out["error"] = _describe(exc)
        return
    out["model_present"] = any(model in (t.get("name"), t.get("model")) for t in tags)
    out["loaded"] = any(model in (p.get("name"), p.get("model")) for p in loaded)
    if not out["model_present"]:
        out["error"] = "Model %s is not on this server" % model
        out["hint"] = "ollama pull %s" % model
        return
    try:
        caps = model_capabilities(ollama_show(base, model, timeout))
    except Exception:
        caps = {}
    out["capabilities"] = caps
    out["ok"] = True
    if caps and not caps.get("tools"):
        out["hint"] = NO_TOOLS_HINT


def test_provider(provider: str, base_url: Optional[str], model: str, *, api_key: str = "",
                  timeout: float = PROBE_TIMEOUT_S) -> Dict[str, Any]:
    """{ok, reachable, latency_ms, model_present, loaded, capabilities, version?, error?, hint?}.

    ``version`` is the Ollama server version from /api/version (Ollama only)."""
    name = normalize_provider(provider)
    model = str(model or "").strip()
    out: Dict[str, Any] = {"ok": False, "reachable": False, "latency_ms": None,
                           "model_present": None, "loaded": None, "capabilities": {}}
    if name == "anthropic-direct":
        out.update(ok=bool(api_key), reachable=None)
        if api_key:
            out["capabilities"] = {"tools": True, "vision": True, "thinking": False}
        else:
            out["error"] = "No Anthropic API key"
            out["hint"] = "Set ANTHROPIC_API_KEY, or save a key with keys.save."
        return out
    if name not in ("ollama", "openai-compatible", "openrouter"):
        out["error"] = "unknown provider %r" % (provider or "")
        return out
    base = _base(base_url, name)
    t0 = time.monotonic()
    try:
        if name == "ollama":
            payload = _request_json("GET", base + "/api/version", timeout=timeout)
            version = str(payload.get("version") or "") if isinstance(payload, dict) else ""
            with _lock:
                _version_cache[base] = (_now(), version)
        else:
            payload = _request_json("GET", base + "/models", headers=_auth_headers(api_key), timeout=timeout)
    except urllib.error.HTTPError as exc:
        out.update(reachable=True, latency_ms=_elapsed_ms(t0), error="HTTP %d from %s" % (exc.code, base))
        if exc.code in (401, 403):
            out["hint"] = "The server rejected the API key."
        return out
    except Exception as exc:
        out["error"] = _describe(exc)
        case = classify_unreachable(exc)
        if case is not None and name == "ollama":
            out["hint"] = unreachable_hint(base, case)
        elif case is not None:
            out["hint"] = "Could not reach %s. Check that the server is running." % base
        return out
    out.update(reachable=True, latency_ms=_elapsed_ms(t0))
    if name == "ollama":
        if version:
            # Part B V4 Test connection: "Connected · 212 ms · Ollama <version>".
            out["version"] = version
        _test_ollama_model(base, model, timeout, out)
        return out
    data = payload.get("data") if isinstance(payload, dict) else None
    ids = [str(d.get("id")) for d in data or [] if isinstance(d, dict) and d.get("id")]
    out["model_present"] = (model in ids) if model else None
    out["ok"] = bool(out["model_present"]) if model else True
    if model and not out["model_present"]:
        out["error"] = "Model %s is not served by %s" % (model, base)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_provider_catalog.py -q`
Expected: `9 passed`.

- [ ] **Step 5: Register the module and run the suites**

In `tests/test_py39_compat.py`, add `"vmd_ai_runtime.provider_catalog",` to the `RUNTIME_MODULES` literal.

Run: `python -m pytest tests/test_py39_compat.py -q`
Expected: `4 passed` (or `1 passed, 3 skipped`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+61 passed, 1 xfailed` (the conftest now calls the real `provider_catalog.clear_caches()` before each test).

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/provider_catalog.py tests/test_provider_catalog.py tests/test_py39_compat.py
git commit -m "feat(runtime): provider_catalog probes, caches and hints (P03-T07)

models.list/provider.test probes with 3 s timeouts, a 60 s catalogue
cache, /api/version cached 30 s, /api/ps never cached, thinking detection
that prefers the /api/show object, the three unreachable hints, and only
the four allow-listed Ollama paths, all through urllib.request.urlopen.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T08: Profile-driven loop_factory, NO_MODEL, openai-compatible names

**Files:**
- Modify: `runtime/vmd_ai_runtime/provider.py:117-136` (add a resolver after `resolve_ollama_model`) and `:518-526` (`build_provider`) — plan 02 does not touch this file
- Modify: `runtime/vmd_ai_runtime/keys.py:13-16` (`_PROVIDER_ENV`)
- Modify: `runtime/vmd_ai_runtime/constants.py:28-34` (`CAPABILITIES["keys"]`)
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — the `from .provider import (...)` block (6f5f937: 28-34) and `build_claude_loop` (6f5f937: 1971-2049; insert before its final `return None`)
- Modify: `runtime/vmd_ai_runtime/app.py` — imports; `RuntimeApp.__init__` (signature and its last statements); plan 02's `profile_for_session`; new helpers before the `# RPC dispatch` banner; the `session.start` result; the `chat.send` branch and `_run_claude_loop_response` from P03-T04
- Modify: `runtime/main.py` (plan 02's imports, `parse_args` and the `RuntimeApp(...)` call in `_serve`)
- Modify: `tests/test_main_lifecycle.py` (plan 02's `_env` helper; see Deviations)
- Create: `tests/test_profile_loop_factory.py`

**Interfaces:**
- Consumes: SettingsStore, resolve_profile, first_run, probe_local_ollama (P03-T05/T06); LoopOptions.product (P02-T05); loop_factory (P02-T10); plan-local `RuntimeApp._new_loop_for` (P03-T04), `settings_store.normalize_provider`, `DEFAULT_BASE_URLS`, `TOP_LEVEL_DEFAULTS` (P03-T05); plan 02's `RuntimeApp._base_loop_factory`, `_loop_factory`, `has_agent_loop`
- Produces:
  - RuntimeApp(..., settings_store: Optional[SettingsStore] = None, cli_provider: Optional[str] = None)
  - RuntimeApp.profile_for_session: token sessions read the active profile
  - RuntimeApp._profile_loop_factory(profile: Dict[str, Any]) -> Optional[ClaudeToolLoop]
  - RpcError NO_MODEL from token chat.send; token chat.send ignores model
  - token session.start result adds profile
  - build_provider/_PROVIDER_ENV/CAPABILITIES.keys/build_claude_loop accept 'openai-compatible' (key falls back to 'EMPTY')
  - main.py --provider -> cli_provider
  - plan-local additions: `provider.resolve_openai_compatible_api_key() -> Tuple[str, str]` (env `VMD_AI_OPENAI_API_KEY`, then keyring `openai-compatible`, then `("EMPTY", "default")`); `RuntimeApp.settings_store`, `RuntimeApp.cli_provider`; `RuntimeApp.first_run_servers: List[Dict]` (probe results when this start ran the first run, else `[]`); `RuntimeApp._api_key_for(provider) -> str`; `RuntimeApp._setting(name) -> Any`; `RuntimeApp._profile_summary(state) -> Optional[Dict]` (`{name, provider, model, base_url?}`); `RuntimeApp._no_model_error() -> RpcError`; profiles returned by `profile_for_session` for token sessions carry `name` and `source` (`cli|profile|env`), and `None` means no usable profile. With a settings store and no explicit `loop_factory`, the base factory becomes a router: a profile with `source` goes to `_profile_loop_factory`, anything else to plan 02's `_default_loop_factory` (so plan 02's `provider.set` reset keeps the router).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_loop_factory.py`:

```python
"""P03-T08: profile-driven loop_factory, NO_MODEL, openai-compatible (§2f, §7)."""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from helpers.app_driver import (
    ScriptedLoop,
    call,
    error_code,
    make_token_app,
    result,
    send,
    start,
    state_of,
    wait_idle,
)
from helpers.fake_ollama import FakeOllama, FakeOllamaServer
from vmd_ai_runtime import keys, provider, settings_store
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, build_claude_loop
from vmd_ai_runtime.constants import CAPABILITIES
from vmd_ai_runtime.settings_store import SettingsStore

ROOT = Path(__file__).resolve().parents[1]
QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b", "options": {}}


def _store(profile=None, **top):
    store = SettingsStore()                 # ~/.vmdai under the hermetic HOME
    if profile is not None:
        store.save_profile("qwen", profile, activate=True)
    if top:
        store.patch(top)
    return store


def test_token_send_without_profile_no_model(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store())
    session = start(app, tmp_path)
    assert session.result["profile"] is None
    assert session.result["agent_loop"] is False
    envelope = send(app, session, "hello")
    assert error_code(envelope) == "NO_MODEL"
    assert envelope["error"]["data"]["action"] == "open_settings"
    assert app.store.list_chats() == []
    assert state_of(app, session).active_request is None


def test_ollama_profile_builds_product_options(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store(QWEN, max_turns=12), enable_wiki=True,
                         wiki_root=str(tmp_path / "wiki"), wiki_raw_root=str(tmp_path / "raw"))
    session = start(app, tmp_path)
    assert session.result["profile"] == {"name": "qwen", "provider": "ollama", "model": "qwen3.8:27b",
                                         "base_url": "http://127.0.0.1:9"}
    loop = app._new_loop_for(state_of(app, session))
    assert isinstance(loop, ClaudeToolLoop) and loop.provider_name == "ollama"
    assert loop.api_key == "http://127.0.0.1:9" and loop.model == "qwen3.8:27b"
    assert loop.options.num_ctx == 32768 and loop.options.max_turns == 12
    assert loop.options.rescue == "json" and loop.options.compact_in_run is True
    assert loop.wiki_store is None                          # wiki_enabled defaults to false
    app.settings_store.patch({"wiki_enabled": True})
    fresh = app._new_loop_for(state_of(app, session))
    assert fresh.wiki_store is app.wiki_store and fresh is not loop


def test_profile_beats_env_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("VMD_AI_PROVIDER", "anthropic-direct")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    app = make_token_app(tmp_path, settings_store=_store(QWEN), provider_mode=None)
    token_session = start(app, tmp_path)
    tokenless = start(app, tmp_path, token="")
    assert app._new_loop_for(state_of(app, token_session)).provider_name == "ollama"
    assert app._new_loop_for(state_of(app, tokenless)).provider_name == "anthropic-direct"
    cli = make_token_app(tmp_path, settings_store=app.settings_store, provider_mode=None,
                         cli_provider="anthropic-direct")
    assert cli._new_loop_for(state_of(cli, start(cli, tmp_path))).provider_name == "anthropic-direct"


def test_tokenless_mock_unchanged(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store())
    session = start(app, tmp_path, token="")
    reply = result(send(app, session, "hello", conversation_mode="local_first"))
    wait_idle(app, session)
    events = result(call(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, session))["events"]
    assert "request_id" in reply
    assert any(e["role"] == "assistant" and e["type"] == "message" for e in events)


def test_token_send_ignores_model(tmp_path, monkeypatch):
    seen = []

    def fake_call(self, messages, system_prompt, on_text, should_cancel):
        seen.append((self.provider_name, self.model, self.options.num_ctx))
        return "hi", []

    monkeypatch.setattr(ClaudeToolLoop, "_call", fake_call)
    app = make_token_app(tmp_path, settings_store=_store(QWEN))
    session = start(app, tmp_path)
    before = state_of(app, session).settings["model"]
    result(send(app, session, "hello", model="some/other-model"))
    wait_idle(app, session)
    assert seen == [("ollama", "qwen3.8:27b", 32768)]      # the profile's model, not the param
    assert state_of(app, session).settings["model"] == before

    # §2f Rescue: rescue "all" is an explicit profile opt-in, and a notice
    # explains it, once per session; the json default gives no notice.
    def rescue_notices():
        events = result(call(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, session))["events"]
        return [e for e in events if (e.get("metadata") or {}).get("notice") == "rescue_all"]

    assert rescue_notices() == []
    app.settings_store.save_profile("qwen", dict(QWEN, options={"rescue": "all"}), activate=True)
    for _ in range(2):
        result(send(app, session, "again"))
        wait_idle(app, session)
    notices = rescue_notices()
    assert len(notices) == 1
    assert (notices[0]["role"], notices[0]["type"]) == ("system", "message")
    assert 'options.rescue is "all"' in notices[0]["text"] and "settings.json" in notices[0]["text"]


def test_provider_set_keeps_profile_routing(tmp_path):
    app = make_token_app(tmp_path, settings_store=_store(QWEN))
    tokenless = start(app, tmp_path, token="")
    app.claude_loop = ScriptedLoop([])
    result(call(app, "provider.set", {"provider": "mock"}, tokenless))   # plan 02 restores the base factory
    token_session = start(app, tmp_path)
    loop = app._new_loop_for(state_of(app, token_session))
    assert loop.provider_name == "ollama" and loop.options is not None


def test_build_claude_loop_has_no_profile_lookup(tmp_path):
    _store(QWEN)                                        # an active Ollama profile in ~/.vmdai
    assert build_claude_loop("ollama") is None          # still env-only: no VMD_AI_OLLAMA_MODEL
    for fn in (build_claude_loop, provider.resolve_anthropic_api_key, provider.resolve_openrouter_api_key,
               provider.resolve_ollama_model, provider.resolve_ollama_host, keys.read_keyring_for_provider):
        assert "settings" not in inspect.getsource(fn)


def test_openai_compatible_names_known(monkeypatch):
    assert provider.build_provider("openai-compatible")[0] == "openai-compatible"
    assert keys._PROVIDER_ENV["openai-compatible"] == "VMD_AI_OPENAI_API_KEY"
    assert "openai-compatible" in CAPABILITIES["keys"]
    assert provider.resolve_openai_compatible_api_key() == ("EMPTY", "default")
    loop = build_claude_loop("openai-compatible", model="Qwen/Qwen3-8B")
    assert loop.provider_name == "openai-compatible" and loop.api_key == "EMPTY"
    assert build_claude_loop("openai-compatible") is None       # no model and no VMD_AI_MODEL
    monkeypatch.setenv("VMD_AI_OPENAI_API_KEY", "sk-local")
    assert provider.resolve_openai_compatible_api_key() == ("sk-local", "VMD_AI_OPENAI_API_KEY")


def test_first_run_on_start(tmp_path, monkeypatch):
    fake = FakeOllama({"qwen3.8:27b": {"capabilities": ["completion", "tools"], "context_length": 131072}})
    calls = []
    with FakeOllamaServer(fake) as server:
        servers = [{"base_url": server.base_url, "version": "0.12.3", "models": ["qwen3.8:27b"]}]
        monkeypatch.setattr(settings_store, "probe_local_ollama", lambda *a, **k: calls.append(1) or servers)
        store = SettingsStore()
        app = make_token_app(tmp_path, settings_store=store)
    assert calls == [1] and app.first_run_servers == servers
    assert store.active_profile() == ("ollama-%d" % server.port, {
        "provider": "ollama", "base_url": server.base_url, "model": "qwen3.8:27b", "options": {"num_ctx": 32768}})
    again = make_token_app(tmp_path, settings_store=SettingsStore())
    assert calls == [1] and again.first_run_servers == []


def test_main_help_lists_provider_flag():
    out = subprocess.run([sys.executable, str(ROOT / "runtime" / "main.py"), "--help"],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "--provider" in out.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_profile_loop_factory.py -q`
Expected: `9 failed, 1 passed` — seven tests with `TypeError: RuntimeApp.__init__() got an unexpected keyword argument 'settings_store'` (Python 3.9 omits the `RuntimeApp.` prefix), `test_openai_compatible_names_known` with `AssertionError: assert 'mock' == 'openai-compatible'`, and `test_main_help_lists_provider_flag` because `--provider` is missing from `--help`. Only `test_build_claude_loop_has_no_profile_lookup` passes already: it pins today's env-only factories, which this task must keep.

- [ ] **Step 3: Teach provider.py, keys.py and constants.py the new provider name**

In `runtime/vmd_ai_runtime/provider.py`, replace:

```python
    name = str(os.getenv("OLLAMA_MODEL") or "").strip()
    if name:
        return name, "OLLAMA_MODEL"
    return "", ""
```

with:

```python
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
```

In `build_provider`, replace:

```python
    if selected in ("ollama", "local-ollama", "local_ollama"):
        return "ollama", OllamaProvider()
    return "mock", MockProvider()
```

with:

```python
    if selected in ("ollama", "local-ollama", "local_ollama"):
        return "ollama", OllamaProvider()
    if selected in ("openai-compatible", "openai_compatible"):
        key, _src = resolve_openai_compatible_api_key()
        base = os.getenv("VMD_AI_OPENAI_BASE_URL") or "http://localhost:8000/v1"
        return "openai-compatible", OpenRouterProvider(api_key=key, base_url=base)
    return "mock", MockProvider()
```

In `runtime/vmd_ai_runtime/keys.py`, replace:

```python
_PROVIDER_ENV: Dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
```

with:

```python
_PROVIDER_ENV: Dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai-compatible": "VMD_AI_OPENAI_API_KEY",
}
```

In `runtime/vmd_ai_runtime/constants.py`, replace:

```python
    "keys": ["openrouter", "anthropic"],
```

with:

```python
    "keys": ["openrouter", "anthropic", "openai-compatible"],
```

- [ ] **Step 4: Teach build_claude_loop the new name (env-driven path, no profile lookup)**

In `runtime/vmd_ai_runtime/claude_loop.py`, replace:

```python
    resolve_ollama_model,
    resolve_openrouter_api_key,
)
```

with:

```python
    resolve_ollama_model,
    resolve_openai_compatible_api_key,
    resolve_openrouter_api_key,
)
```

and in `build_claude_loop` replace its last lines:

```python
        base_url, _host_src = resolve_ollama_host()
        return ClaudeToolLoop(
            provider_name="ollama",
            api_key=base_url,   # repurposed: base URL, not a real key
            model=chosen,
            docs_search=docs_search,
            wiki_store=wiki_store,
        )

    return None
```

with:

```python
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
```

- [ ] **Step 5: Route token sessions through the settings profile in app.py**

In `runtime/vmd_ai_runtime/app.py`, replace:

```python
import hmac
import json
```

with:

```python
import copy
import hmac
import json
```

Replace:

```python
from . import conversation
from .claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    RunContext,
```

with:

```python
from . import conversation
from . import settings_store as settings_mod
from .claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
```

Replace:

```python
from .provider import (
    build_provider,
    resolve_ollama_model,
    resolve_openrouter_api_key,
)
```

with:

```python
from .provider import (
    build_provider,
    resolve_anthropic_api_key,
    resolve_ollama_model,
    resolve_openai_compatible_api_key,
    resolve_openrouter_api_key,
)
from .settings_store import (
    DEFAULT_BASE_URLS,
    TOP_LEVEL_DEFAULTS,
    SettingsStore,
    normalize_provider,
    resolve_profile,
)
```

Extend the constructor. Replace:

```python
        loop_factory: Optional[Callable[[Dict[str, Any]], Optional[ClaudeToolLoop]]] = None,
    ):
        self.sessions = SessionManager()
```

with:

```python
        loop_factory: Optional[Callable[[Dict[str, Any]], Optional[ClaudeToolLoop]]] = None,
        settings_store: Optional[SettingsStore] = None,
        cli_provider: Optional[str] = None,
    ):
        # Runtime-owned profiles (§2f). Only main.py passes a store; tests
        # and the A/B scripts keep plan 02's env-driven behaviour.
        self.settings_store = settings_store
        self.cli_provider = (str(cli_provider).strip() or None) if cli_provider else None
        self.first_run_servers: List[Dict[str, Any]] = []
        self.sessions = SessionManager()
```

Then add the router and the first run at the end of `__init__`. Replace:

```python
        if self.logger:
            self.logger.info(
                "provider=%s agent_loop=%s",
                self.provider_name,
                self.has_agent_loop(),
            )
```

with:

```python
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
        if settings_store is not None and not settings_store.exists():
            # First run (§2f): probe :11435 then :11434, 300 ms each.
            try:
                self.first_run_servers = list(settings_mod.probe_local_ollama())
                settings_store.first_run(self.first_run_servers)
            except Exception:
                if self.logger:
                    self.logger.warning("first-run probe failed", exc_info=True)
```

Replace plan 02's `profile_for_session`:

```python
    def profile_for_session(self, state: Optional[SessionState] = None) -> Optional[Dict[str, Any]]:
        """The profile a request of ``state`` runs with.

        M1 foundation: the legacy profile {provider, model} from the
        env/--provider choice and the last provider.set. Plan 03 makes
        token sessions read the active profile in settings.json.
        """
        return {"provider": self._loop_provider, "model": self._loop_model}
```

with:

```python
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
```

Plan 02's `has_agent_loop` stays as it is: it asks `self._loop_factory` about `profile_for_session(state)`, which now covers token sessions.

Add the profile helpers before the dispatch banner. Replace:

```python
    # ------------------------------------------------------------------
    # RPC dispatch
    # ------------------------------------------------------------------
```

with:

```python
    # ------------------------------------------------------------------
    # Settings profiles (§2f)
    # ------------------------------------------------------------------

    def _profile_loop_factory(self, profile: Dict[str, Any]) -> Optional[ClaudeToolLoop]:
        """One product loop for a settings profile (§2f, C7).

        Options come from LoopOptions.product(profile) with max_turns from
        settings.json; keys from provider.resolve_* (env, then keyring). The
        wiki is wired only when settings.wiki_enabled is true (§2g). Returns
        None when the profile has no model or a needed key is missing.
        """
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
        options = LoopOptions.product(profile, max_turns=int(self._setting("max_turns")))
        wiki = self.wiki_store if self._setting("wiki_enabled") else None
        return ClaudeToolLoop(
            provider_name=provider_name,
            api_key=api_key,
            model=model,
            docs_search=self.docs_search,
            wiki_store=wiki,
            options=options,
        )

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
        """A top-level settings.json value, or its default when there is no store."""
        if self.settings_store is None:
            return TOP_LEVEL_DEFAULTS[name]
        return self.settings_store.load().get(name, TOP_LEVEL_DEFAULTS[name])

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
    # RPC dispatch
    # ------------------------------------------------------------------
```

In the `session.start` branch, replace:

```python
                result["runtime"] = {"version": RUNTIME_VERSION, "pid": os.getpid()}
            return result
```

with:

```python
                result["runtime"] = {"version": RUNTIME_VERSION, "pid": os.getpid()}
                result["profile"] = self._profile_summary(state)
            return result
```

In the `chat.send` branch (P03-T04), replace:

```python
            if params.get("model"):
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
```

with:

```python
            # A token session always runs its profile's model (§2h).
            if params.get("model") and not state.authenticated:
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
```

and replace:

```python
                loop = self._new_loop_for(state)
                if state.chat_id is None:
```

with:

```python
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
```

Add the notice text as a module-level constant in `app.py`, directly above `class RuntimeApp`:

```python
# §2f Rescue: shown once per token session whose profile opts into rescue "all".
RESCUE_ALL_NOTICE = (
    "This profile runs tool calls that the model writes as plain text "
    "(options.rescue is \"all\"), including tcl code blocks in its answers. "
    "Set options.rescue to \"json\" in ~/.vmdai/settings.json to run only "
    "tool-call JSON that names an offered tool."
)
```

In `_run_claude_loop_response` (P03-T04), replace:

```python
        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        if model and model != loop.model:
```

with:

```python
        # Token sessions always run their profile's model (§2h); the session
        # model override stays for tokenless clients only.
        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        if not state.authenticated and model and model != loop.model:
```

- [ ] **Step 6: `--provider` in main.py, and keep subprocess runtimes off the real ports**

In `runtime/main.py`, replace:

```python
from vmd_ai_runtime.logging_utils import configure_logging, default_log_path
```

with:

```python
from vmd_ai_runtime.logging_utils import configure_logging, default_log_path
from vmd_ai_runtime.settings_store import SettingsStore, normalize_provider
```

Replace:

```python
    parser.add_argument(
        "--disable-wiki",
```

with:

```python
    parser.add_argument(
        "--provider",
        default=None,
        help="Profile or provider name for this runtime (anthropic-direct, openrouter, "
             "ollama, openai-compatible). Beats the active profile in ~/.vmdai/settings.json.",
    )
    parser.add_argument(
        "--disable-wiki",
```

Replace:

```python
        on_shutdown=_request_shutdown,
    )
```

with:

```python
        on_shutdown=_request_shutdown,
        provider_mode=normalize_provider(args.provider) or None,
        settings_store=SettingsStore(),
        cli_provider=args.provider,
    )
```

The runtime now runs the first-run probe at startup when `~/.vmdai/settings.json` is missing. Plan 02's lifecycle tests start `main.py` with a fresh temp HOME, so without a change they would probe the real ports 11435/11434 (§6 forbids that; with the owner's tunnel up they would even reach the real Ollama). In `tests/test_main_lifecycle.py`, replace:

```python
def _env(extra=None):
    # The hermetic conftest already cleared VMD_AI_*/ANTHROPIC_*/... and set a temp HOME.
    env = dict(os.environ)
```

with:

```python
def _env(extra=None):
    # The hermetic conftest already cleared VMD_AI_*/ANTHROPIC_*/... and set a temp HOME.
    env = dict(os.environ)
    # An empty settings.json in the temp HOME keeps the runtime's first-run
    # probe (plan 03) away from the real ports 11435/11434 (§6).
    settings = Path(env["HOME"]) / ".vmdai" / "settings.json"
    if not settings.exists():
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"version": 1, "active": null, "profiles": {}}\n', encoding="utf-8")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_profile_loop_factory.py -q`
Expected: `10 passed`.

- [ ] **Step 8: Run the S7 guards, the product suite and the benchmark suites**

Run: `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_hashes.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_wiring.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures.

Run: `python -m pytest tests/test_main_lifecycle.py tests/test_loop_factory.py tests/test_memory_integration.py tests/test_launch_token.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+71 passed, 1 xfailed`, under 60 s.

Run: `python -m pytest vmdbench/tests -q 2>&1 | tail -1 && python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1`
Expected: `90 passed`, then `62 passed`.

- [ ] **Step 9: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/provider.py runtime/vmd_ai_runtime/keys.py runtime/vmd_ai_runtime/constants.py runtime/vmd_ai_runtime/claude_loop.py runtime/main.py tests/test_main_lifecycle.py tests/test_profile_loop_factory.py
git commit -m "feat(runtime): profile-driven loops, NO_MODEL, openai-compatible (P03-T08)

Token sessions of a runtime that owns settings.json build each request's
loop from the effective profile with LoopOptions.product; with no usable
profile chat.send returns NO_MODEL instead of mock mode, and the model
param and the session model override no longer apply to them. First run
happens at startup. openai-compatible joins build_provider,
build_claude_loop, the key map and CAPABILITIES; main.py gains --provider.
Subprocess lifecycle tests get an empty settings.json so they never probe
the real Ollama ports.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T09: M1 RPCs: runtime.info, session.set_cwd, models.list, provider.test, provider.set, settings.set

**Files:**
- Modify: `runtime/vmd_ai_runtime/protocol.py` — imports (6f5f937: 1-6), new helpers before `validate_rpc_payload`, the `provider.set` validator (6f5f937: 113-121), new validators before the final `raise RpcError("METHOD_NOT_FOUND", …)` (6f5f937: 161)
- Modify: `runtime/vmd_ai_runtime/sessions.py:3-17` (imports, `RequestState`)
- Modify: `runtime/vmd_ai_runtime/app.py` — imports and a module constant before `class RuntimeApp`; the `settings.set` branch (6f5f937: 353-359); the top of the `provider.set` branch (6f5f937: 371-372); new branches before the final `raise RpcError("METHOD_NOT_FOUND", …)` of `_dispatch` (6f5f937: 518); the `ctx = RunContext(...)` statement in `_run_claude_loop_response` (P03-T04); new helper methods before the `# RPC dispatch` banner
- Create: `tests/test_runtime_info_rpcs.py`

**Interfaces:**
- Consumes: provider_catalog (P03-T07); SettingsStore (P03-T05); _require_auth (P02-T02); plan-local `RuntimeApp._new_loop_for`, `_request_running` (P03-T04), `_setting`, `_api_key_for`, `first_run_servers` (P03-T08); `constants.RUNTIME_PROTOCOL`, `RUNTIME_VERSION` (P02-T01); `logging_utils.default_log_path` (P02-T03)
- Produces:
  - runtime.info -> {version, protocol, pid, provider, model, agent_loop, vision, tools[], rag, wiki, max_turns, log_path, settings_source, active_request?{request_id, turn, started_at, last_seq}, first_run{servers[]}}
  - RequestState.turn: int; RequestState.started_at: float
  - session.set_cwd {cwd} -> {ok, cwd} (Auth)
  - models.list {provider?, base_url?} -> {models, source, error?}
  - provider.test {provider?, base_url?, model?} -> {ok, reachable, latency_ms, model_present, loaded, capabilities, version?, error?, hint?} (`version`: the Ollama server version, Ollama only; plan 09 shows it in Test connection)
  - provider.set new params base_url, options, profile (Auth) -> adds capabilities{tools, vision, thinking}; without profile it edits the active profile
  - settings.set persisted keys approval_mode ('auto' only), wiki_enabled, reasoning_visible, max_turns, tool_exec_timeout_s, cancel_grace_s (Auth)
  - plan-local additions: `app.PERSISTED_SETTING_KEYS`; `RuntimeApp._runtime_info(state)`, `_vision_for(loop)`, `_max_turns_for(loop)`, `_log_path()`, `_catalog_target(state, params) -> (provider, base_url, model, api_key)`, `_capabilities_for(profile)`, `_provider_set_profile(state, params)`, `_settings_rpc_error(exc) -> RpcError`, `_turn_tracker(request)` (the v1 `on_event`; P07-T01 replaces it with `_make_on_event`); `protocol._as_base_url`, `_as_optional_dict`, `_as_profile_name`. runtime.info needs a session (any session; no launch token). provider.set on a token session answers `{ok, provider, model, profile, agent_loop, capabilities}`; with no active profile it edits (or creates) the provider's default-named profile (`claude`, `openrouter`, `ollama`, `openai-compatible`) and activates it, so a profile seeded from last_provider.txt becomes active once the user applies it. runtime.info reports `provider: ""` and `model: ""` for a token session with no usable profile (never the env/mock provider). settings.set on a token session adds `persisted` (the top-level settings after the write).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runtime_info_rpcs.py`:

```python
"""P03-T09: runtime.info, session.set_cwd, models.list, provider.test, provider.set, settings.set
(§2c Stage split, §3 RPC table, §2e privileged ops, S11)."""
from __future__ import annotations

import os
import threading
import time

from helpers.app_driver import (
    InstantBridge,
    ScriptedLoop,
    call,
    error_code,
    make_token_app,
    result,
    send,
    start,
    state_of,
    tool_use,
    wait_idle,
)
from vmd_ai_runtime import provider_catalog, settings_store
from vmd_ai_runtime.claude_loop import LoopOptions
from vmd_ai_runtime.constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from vmd_ai_runtime.settings_store import SettingsStore

QWEN = {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "qwen3.8:27b",
        "options": {"num_ctx": 16384}}
INFO_KEYS = {"version", "protocol", "pid", "provider", "model", "agent_loop", "vision", "tools", "rag",
             "wiki", "max_turns", "log_path", "settings_source", "first_run"}


def _app(tmp_path, profile=QWEN):
    store = SettingsStore()
    if profile is not None:
        store.save_profile("qwen", profile, activate=True)
    return make_token_app(tmp_path, settings_store=store)


def test_runtime_info_shape(tmp_path):
    app = _app(tmp_path)
    session = start(app, tmp_path)
    info = result(call(app, "runtime.info", {}, session))
    assert set(info) == INFO_KEYS
    assert (info["version"], info["protocol"], info["pid"]) == (RUNTIME_VERSION, RUNTIME_PROTOCOL, os.getpid())
    assert (info["provider"], info["model"], info["agent_loop"]) == ("ollama", "qwen3.8:27b", True)
    assert info["tools"] == ["run_vmd_command", "capture_vmd_snapshot"]
    assert (info["rag"], info["wiki"], info["vision"], info["max_turns"]) == (False, False, False, 28)
    assert info["settings_source"] == "file" and info["first_run"] == {"servers": []}
    assert isinstance(info["log_path"], str) and info["log_path"]
    tokenless = start(app, tmp_path, token="")
    assert set(result(call(app, "runtime.info", {}, tokenless))) == INFO_KEYS
    assert error_code(call(app, "runtime.info", {})) == "INVALID_PARAMS"
    # No usable profile: a token session reports no provider, never the env/mock fallback (§2f).
    blank = make_token_app(tmp_path / "blank", settings_store=SettingsStore(home=str(tmp_path / "blank")))
    none = result(call(blank, "runtime.info", {}, start(blank, tmp_path / "blank")))
    assert (none["provider"], none["model"], none["agent_loop"], none["tools"]) == ("", "", False, [])


def test_active_request_reported(tmp_path):
    app = _app(tmp_path)
    app.tool_bridge = InstantBridge()
    gate = threading.Event()
    loop = ScriptedLoop([("", [tool_use("tc_0", "molinfo list")]), ("done", [])],
                        before_call=lambda number, messages: number == 2 and gate.wait(5),
                        options=LoopOptions())
    app.claude_loop = loop
    session = start(app, tmp_path)
    t0 = time.time()
    request_id = result(send(app, session, "list molecules"))["request_id"]
    try:
        deadline = time.monotonic() + 5
        while len(loop.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        active = result(call(app, "runtime.info", {}, session))["active_request"]
    finally:
        gate.set()
    assert active["request_id"] == request_id
    assert active["turn"] >= 1
    assert t0 - 1 <= active["started_at"] <= time.time()
    assert isinstance(active["last_seq"], int) and active["last_seq"] >= 1
    wait_idle(app, session)
    assert "active_request" not in result(call(app, "runtime.info", {}, session))


def test_first_run_servers_empty_once_settings_exist(tmp_path, monkeypatch):
    servers = [{"base_url": "http://127.0.0.1:11435", "version": "0.12.3", "models": []}]
    probes = []
    monkeypatch.setattr(settings_store, "probe_local_ollama", lambda *a, **k: probes.append(1) or servers)
    fresh = make_token_app(tmp_path, settings_store=SettingsStore())
    assert result(call(fresh, "runtime.info", {}, start(fresh, tmp_path)))["first_run"] == {"servers": servers}
    assert probes == [1]
    SettingsStore().save_profile("qwen", QWEN, activate=True)
    later = make_token_app(tmp_path, settings_store=SettingsStore())
    assert result(call(later, "runtime.info", {}, start(later, tmp_path)))["first_run"] == {"servers": []}
    assert probes == [1]


def test_set_cwd_requires_auth_and_dir(tmp_path):
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    target = tmp_path / "project"
    target.mkdir()
    assert error_code(call(app, "session.set_cwd", {"cwd": str(target)}, tokenless)) == "AUTH_REQUIRED"
    assert error_code(call(app, "session.set_cwd", {"cwd": str(tmp_path / "missing")}, token_session)) == "INVALID_PARAMS"
    assert error_code(call(app, "session.set_cwd", {}, token_session)) == "INVALID_PARAMS"
    reply = result(call(app, "session.set_cwd", {"cwd": str(target)}, token_session))
    assert reply == {"ok": True, "cwd": os.path.realpath(str(target))}
    assert state_of(app, token_session).cwd == os.path.realpath(str(target))


def test_models_list_base_url_requires_auth(tmp_path, monkeypatch):
    seen = []

    def fake_list(provider, base_url, api_key="", timeout=3.0):
        seen.append((provider, base_url, api_key))
        return {"models": [], "source": "server"}

    monkeypatch.setattr(provider_catalog, "list_models", fake_list)
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    remote = {"provider": "ollama", "base_url": "http://10.0.0.5:11434"}
    assert error_code(call(app, "models.list", remote, tokenless)) == "AUTH_REQUIRED"
    assert result(call(app, "models.list", {}, token_session)) == {"models": [], "source": "server"}
    result(call(app, "models.list", remote, token_session))
    result(call(app, "models.list", {"provider": "openai-compatible"}, tokenless))
    assert seen == [("ollama", "http://127.0.0.1:9", ""),
                    ("ollama", "http://10.0.0.5:11434", ""),
                    ("openai-compatible", "http://localhost:8000/v1", "EMPTY")]
    assert error_code(call(app, "models.list", {"base_url": "file:///etc/passwd"}, token_session)) == "INVALID_PARAMS"


def test_provider_test_base_url_requires_auth(tmp_path, monkeypatch):
    seen = []

    def fake_test(provider, base_url, model, api_key="", timeout=3.0):
        seen.append((provider, base_url, model))
        return {"ok": True}

    monkeypatch.setattr(provider_catalog, "test_provider", fake_test)
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    assert error_code(call(app, "provider.test", {"base_url": "http://10.0.0.5:11434"}, tokenless)) == "AUTH_REQUIRED"
    assert result(call(app, "provider.test", {}, token_session)) == {"ok": True}
    result(call(app, "provider.test", {"model": "llama3.1:8b"}, token_session))
    assert seen == [("ollama", "http://127.0.0.1:9", "qwen3.8:27b"), ("ollama", "http://127.0.0.1:9", "llama3.1:8b")]


def test_provider_set_persists_to_active_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_catalog, "ollama_show",
                        lambda base_url, model, timeout=3.0: {"capabilities": ["completion", "tools", "vision"]})
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    reply = result(call(app, "provider.set", {"provider": "ollama", "model": "qwen3.8:32b"}, token_session))
    assert reply["profile"] == "qwen" and reply["model"] == "qwen3.8:32b"
    assert reply["capabilities"] == {"tools": True, "vision": True, "thinking": False}
    stored = app.settings_store.get_profile("qwen")
    assert stored["model"] == "qwen3.8:32b" and stored["options"] == {"num_ctx": 16384}
    result(call(app, "provider.set", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5",
                                      "profile": "claude"}, token_session))
    assert app.settings_store.get_profile("claude") == {"provider": "anthropic-direct",
                                                        "model": "claude-sonnet-4-5", "options": {}}
    assert app.settings_store.active_profile()[0] == "qwen"
    privileged = ({"provider": "ollama", "base_url": "http://10.0.0.5:11434"},
                  {"provider": "ollama", "options": {"num_ctx": 8192}},
                  {"provider": "ollama", "profile": "qwen"})
    for params in privileged:
        assert error_code(call(app, "provider.set", params, tokenless)) == "AUTH_REQUIRED"
    assert app.settings_store.get_profile("qwen")["model"] == "qwen3.8:32b"


def test_provider_set_activates_when_none_is_active(tmp_path):
    """First run seeded `claude` from last_provider.txt but never activated it (§2f).
    Applying that provider in the M1 panel must make it the active profile, or
    the next chat.send would still return NO_MODEL."""
    store = SettingsStore()
    store.save_profile("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)
    reply = result(call(app, "provider.set", {"provider": "anthropic-direct", "model": "claude-sonnet-4-6"}, session))
    assert reply["profile"] == "claude"
    assert store.active_profile() == ("claude", {"provider": "anthropic-direct", "model": "claude-sonnet-4-6",
                                                 "options": {}})
    blank = SettingsStore(home=str(tmp_path / "blank"))
    other = make_token_app(tmp_path / "blank", settings_store=blank)
    made = result(call(other, "provider.set", {"provider": "openai-compatible", "model": "Qwen/Qwen3-8B"},
                       start(other, tmp_path / "blank")))
    assert (made["profile"], made["agent_loop"]) == ("openai-compatible", True)
    assert blank.active_profile() == ("openai-compatible", {
        "provider": "openai-compatible", "model": "Qwen/Qwen3-8B",
        "base_url": "http://localhost:8000/v1", "options": {}})


def test_settings_set_persisted_keys_require_auth(tmp_path):
    app = _app(tmp_path)
    token_session, tokenless = start(app, tmp_path), start(app, tmp_path, token="")
    for key, value in (("wiki_enabled", True), ("max_turns", 12), ("tool_exec_timeout_s", 60),
                       ("cancel_grace_s", 5), ("approval_mode", "auto")):
        assert error_code(call(app, "settings.set", {"patch": {key: value}}, tokenless)) == "AUTH_REQUIRED"
    per_session = result(call(app, "settings.set", {"patch": {"mode": "tutor", "reasoning_visible": False}}, tokenless))
    assert per_session["settings"]["mode"] == "tutor" and "persisted" not in per_session
    assert app.settings_store.load()["reasoning_visible"] is True
    reply = result(call(app, "settings.set", {"patch": {"max_turns": 12, "wiki_enabled": True}}, token_session))
    assert reply["persisted"]["max_turns"] == 12 and reply["persisted"]["wiki_enabled"] is True
    assert SettingsStore().load()["max_turns"] == 12


def test_approval_mode_only_auto(tmp_path):
    app = _app(tmp_path)
    session = start(app, tmp_path)
    assert error_code(call(app, "settings.set", {"patch": {"approval_mode": "ask"}}, session)) == "INVALID_PARAMS"
    reply = result(call(app, "settings.set", {"patch": {"approval_mode": "auto"}}, session))
    assert reply["persisted"]["approval_mode"] == "auto"


def test_read_only_settings_rejected_over_rpc(tmp_path):
    store = SettingsStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken")
    app = make_token_app(tmp_path, settings_store=store)
    session = start(app, tmp_path)
    envelope = call(app, "settings.set", {"patch": {"max_turns": 5}}, session)
    assert error_code(envelope) == "INVALID_PARAMS"
    assert envelope["error"]["data"] == {"reason": "read_only", "settings_source": "invalid"}
    assert result(call(app, "runtime.info", {}, session))["settings_source"] == "invalid"
    assert store.path.read_text() == "{broken"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_runtime_info_rpcs.py -q`
Expected: `11 failed` — `METHOD_NOT_FOUND` for `runtime.info`, `session.set_cwd`, `models.list` and `provider.test`; the settings.set tests fail on `assert "error" in envelope` (today's settings.set accepts any patch key from any session), and the two provider.set tests on `KeyError: 'profile'`.

- [ ] **Step 3: Request state and parameter validation**

In `runtime/vmd_ai_runtime/sessions.py`, replace:

```python
import threading
import uuid
```

with:

```python
import threading
import time
import uuid
```

and replace:

```python
@dataclass
class RequestState:
    request_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
```

with:

```python
@dataclass
class RequestState:
    request_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    turn: int = 0                                           # updated from turn.started
    started_at: float = field(default_factory=time.time)    # epoch seconds
```

In `runtime/vmd_ai_runtime/protocol.py`, replace:

```python
import re
from typing import Any, Dict, Optional
```

with:

```python
import re
import urllib.parse
from typing import Any, Dict, Optional
```

and replace:

```python
def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
```

with:

```python
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _as_base_url(value: Any) -> str:
    """'' when absent; otherwise an http(s) URL with a host, at most 512 characters."""
    text = _as_str(value, "base_url", required=False)
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    if (parts.scheme not in ("http", "https") or not parts.netloc or len(text) > 512
            or any(ch.isspace() for ch in text)):
        raise RpcError("INVALID_PARAMS", "base_url must be an http(s) URL", {"base_url": text[:80]})
    return text


def _as_optional_dict(value: Any, field: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RpcError("INVALID_PARAMS", f"{field} must be an object")
    return value


def _as_profile_name(value: Any) -> str:
    text = _as_str(value, "profile", required=False)
    if text and not _PROFILE_NAME_RE.match(text):
        raise RpcError("INVALID_PARAMS", "profile must be 1-64 letters, digits, '.', '_' or '-'")
    return text


def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
```

Replace the `provider.set` validator:

```python
    if method == "provider.set":
        # Posted by the Tcl UI when the user changes the provider
        # dropdown. The runtime rebuilds its provider + claude_loop in
        # place; model is optional and just updates settings.model.
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider":   _as_str(p.get("provider"), "provider"),
            "model":      _as_str(p.get("model") or "", "model", required=False),
        }
```

with:

```python
    if method == "provider.set":
        # {provider, model} is today's ui.tcl call; base_url, options and
        # profile need a token session (checked in app.py, §2e).
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider":   _as_str(p.get("provider"), "provider"),
            "model":      _as_str(p.get("model") or "", "model", required=False),
            "base_url":   _as_base_url(p.get("base_url")),
            "options":    _as_optional_dict(p.get("options"), "options"),
            "profile":    _as_profile_name(p.get("profile")),
        }
```

Replace the final line of `validate_method_params`:

```python
    raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")
```

with:

```python
    if method == "runtime.info":
        return {"session_id": _as_str(p.get("session_id"), "session_id")}

    if method == "session.set_cwd":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "cwd": _as_str(p.get("cwd"), "cwd"),
        }

    if method == "models.list":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider": _as_str(p.get("provider") or "", "provider", required=False),
            "base_url": _as_base_url(p.get("base_url")),
        }

    if method == "provider.test":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "provider": _as_str(p.get("provider") or "", "provider", required=False),
            "base_url": _as_base_url(p.get("base_url")),
            "model": _as_str(p.get("model") or "", "model", required=False),
        }

    raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")
```

- [ ] **Step 4: The RPC branches in app.py**

In `runtime/vmd_ai_runtime/app.py`, replace:

```python
import copy
import hmac
import json
import os
import threading
from typing import Any, Callable, Dict, List, Optional
```

with:

```python
import copy
import hmac
import json
import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
```

Replace:

```python
from . import conversation
from . import settings_store as settings_mod
```

with:

```python
from . import conversation
from . import provider_catalog
from . import settings_store as settings_mod
```

Replace `from .constants import CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_VERSION` with `from .constants import CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_PROTOCOL, RUNTIME_VERSION`, and `from .logging_utils import redact_sensitive` with `from .logging_utils import default_log_path, redact_sensitive`. Replace:

```python
from .settings_store import (
    DEFAULT_BASE_URLS,
    TOP_LEVEL_DEFAULTS,
    SettingsStore,
    normalize_provider,
    resolve_profile,
)
```

with:

```python
from .settings_store import (
    DEFAULT_BASE_URLS,
    DEFAULT_PROFILE_NAMES,
    TOP_LEVEL_DEFAULTS,
    SettingsError,
    SettingsStore,
    normalize_provider,
    resolve_profile,
)
```

Replace:

```python
class RuntimeApp:
    def __init__(
```

with:

```python
# settings.json keys settings.set may write (§2f Schema); they need a token session.
PERSISTED_SETTING_KEYS = tuple(TOP_LEVEL_DEFAULTS)


class RuntimeApp:
    def __init__(
```

Replace the whole `settings.set` branch:

```python
        if method == "settings.set":
            state = self._get_session(params["session_id"], session_token)
            patch = dict(params.get("patch") or {})
            for name in ("model", "mode", "conversation_mode", "reasoning_visible", "debug_mode"):
                if name in patch:
                    state.settings[name] = patch[name]
            return {"ok": True, "settings": dict(state.settings)}
```

with:

```python
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
```

At the top of the `provider.set` branch, replace:

```python
        if method == "provider.set":
            state = self._get_session(params["session_id"], session_token)
            requested = str(params["provider"] or "").strip().lower()
```

with (plan 02's code below stays and still serves tokenless sessions):

```python
        if method == "provider.set":
            state = self._get_session(params["session_id"], session_token)
            privileged = (bool(params.get("base_url")) or params.get("options") is not None
                          or bool(params.get("profile")))
            if privileged:
                self._require_auth(state)
            if state.authenticated and self.settings_store is not None:
                return self._provider_set_profile(state, params)
            requested = str(params["provider"] or "").strip().lower()
```

Replace the final line of `_dispatch`:

```python
        raise RpcError("METHOD_NOT_FOUND", f"Unknown method: {method}")
```

with:

```python
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
```

In `_run_claude_loop_response` (P03-T04), replace:

```python
        ctx = RunContext(request_id=request_id, chat_id=chat_id or "", on_event=None,
                         messages_out=messages_out)
```

with:

```python
        request = state.active_request
        if request is not None and request.request_id != request_id:
            request = None
        ctx = RunContext(request_id=request_id, chat_id=chat_id or "",
                         on_event=self._turn_tracker(request), messages_out=messages_out)
```

Add the RPC helpers after P03-T08's profile helpers. Replace:

```python
    # ------------------------------------------------------------------
    # RPC dispatch
    # ------------------------------------------------------------------
```

with:

```python
    # ------------------------------------------------------------------
    # M1 RPC helpers (§2c, §3)
    # ------------------------------------------------------------------

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

    @staticmethod
    def _vision_for(loop: Optional[ClaudeToolLoop]) -> bool:
        if loop is None:
            return False
        if loop.provider_name == "anthropic-direct":
            return True
        return getattr(getattr(loop, "options", None), "supports_vision", None) is True

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

    def _provider_set_profile(self, state, params: Dict[str, Any]) -> Dict[str, Any]:
        """provider.set for a token session: persist into the active or named profile.

        Applies to the next request. Without a profile name it edits the
        active profile in place (M1 ui.tcl Apply, §2f). With no active
        profile it edits (or creates) the provider's default-named profile and
        activates it: first run may have seeded ``claude``/``openrouter`` from
        last_provider.txt without activating it, and applying it is the
        user's explicit choice.
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
        try:
            active_name, _active = store.active_profile()
            if not name:
                name = active_name or DEFAULT_PROFILE_NAMES[provider_name]
            if store.get_profile(name) is None:
                profile: Dict[str, Any] = {"provider": provider_name, "model": model or "",
                                           "options": dict(options or {})}
                url = base_url or DEFAULT_BASE_URLS.get(provider_name)
                if url:
                    profile["base_url"] = url
                store.save_profile(name, profile, activate=active_name is None)
            else:
                store.update_profile(name, provider=provider_name, model=model, base_url=base_url, options=options)
                if active_name is None:
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_runtime_info_rpcs.py -q`
Expected: `11 passed`.

- [ ] **Step 6: Run the protocol, security and app suites, then everything**

Run: `python -m pytest tests/test_protocol.py tests/test_server_security.py tests/test_launch_token.py tests/test_loop_factory.py tests/test_memory_integration.py tests/test_profile_loop_factory.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+82 passed, 1 xfailed`.

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/protocol.py runtime/vmd_ai_runtime/sessions.py tests/test_runtime_info_rpcs.py
git commit -m "feat(runtime): runtime.info, set_cwd, models.list, provider.test, persisted settings (P03-T09)

runtime.info reports version/protocol, the effective model, tools, limits,
settings_source, first_run servers and the active request's turn and
last_seq. session.set_cwd, base_url probes, provider.set's new params and
persisted settings.set keys require a token session; provider.set writes
the active (or named) profile and returns capabilities.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P03-T10: In-run compaction (compact_in_run)

**Files:**
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports (add a `from .conversation import (...)` block after `from .recorder import RunRecorder`, 6f5f937 line 35); class attributes at the top of `ClaudeToolLoop` (next to `MAX_TURNS = 28`, 6f5f937 line 1365); `run()` right after `system_prompt = system_prompt + WIKI_SYSTEM_PROMPT_ADDENDUM` (6f5f937 line 1742) and at plan 02's single `self._call_turn(` site (it replaced the direct `self._call(` of 6f5f937 line 1764; Task 0 Step 4 confirms there is exactly one); a new method before plan 02's `_on_meta`
- Create: `tests/test_compact_in_run.py`

**Interfaces:**
- Consumes: stub_tool_result_text, compute_run_budget, context_tokens_for (P03-T02); plan-local `conversation.compact_tool_results`, `messages_chars`, `CONTEXT_WARN_FRACTION` (P03-T02); `LoopOptions.compact_in_run`, `ClaudeToolLoop._on_meta` (P02-T05); test helpers `ScriptedLoop`, `InstantBridge`, `tool_use` (P03-T04) and `helpers.conversation_data.*` (P03-T01)
- Produces:
  - ClaudeToolLoop._compact_for_call(messages: List[Dict]) -> Tuple[List[Dict], bool]
  - status phase 'context_near_full' (once per request)
  - ClaudeToolLoop.last_compactions: int
  - plan-local: `ClaudeToolLoop._run_budget: Optional[int]` (set at the start of each `run()` only when `options.compact_in_run`; `None` otherwise) and `_context_warned: bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compact_in_run.py`:

```python
"""P03-T10: in-run compaction behind LoopOptions.compact_in_run (§2b, C5)."""
from __future__ import annotations

import copy
import json
import math
import threading

from helpers.app_driver import InstantBridge, ScriptedLoop, tool_use
from helpers.conversation_data import (
    assistant_tools,
    image_block,
    snapshot_result,
    tiny_png,
    tool_results,
    user,
)
from vmd_ai_runtime import conversation
from vmd_ai_runtime.claude_loop import LoopOptions, RunContext, _vmd_tools

SYSTEM = "You are a test."
OUTPUT = "r" * 2000
NOTE = ("[output truncated: 9000 lines, 80 KB. Full text: /x/outputs/k2.txt. "
        "Don't print it again: read a slice of that file with Tcl.]")


def _script(rounds):
    return [("", [tool_use("tc_%d" % i, "measure rmsf %d" % i)]) for i in range(rounds)] + [("All done.", [])]


def _budgeted_loop(target_budget, rounds):
    """An Ollama-named ScriptedLoop whose run budget is about ``target_budget`` chars."""
    tools_chars = len(json.dumps(_vmd_tools(include_search_docs=False, include_wiki=False)))
    num_ctx = 4096 + math.ceil((target_budget + len(SYSTEM) + tools_chars) / conversation.CHARS_PER_TOKEN)
    return ScriptedLoop(_script(rounds), provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                        options=LoopOptions(num_ctx=num_ctx, compact_in_run=True))


def _run(loop):
    events, out = [], []
    loop.run(prompt="compute RMSF per residue", system_prompt=SYSTEM,
             tool_bridge=InstantBridge(lambda tool_input: OUTPUT), session_id="sess_t",
             session_queue=None, cancel_event=threading.Event(), on_chunk=lambda text: None,
             ctx=RunContext(request_id="req_t", chat_id="chat_000000000000",
                            on_event=events.append, messages_out=out))
    return events, out


def _near_full(events):
    return [e for e in events
            if (e.get("metadata") or {}).get("kind") == "status"
            and e["metadata"].get("phase") == "context_near_full"]


def _result_texts(messages):
    return [b["content"] for m in messages if isinstance(m.get("content"), list)
            for b in m["content"] if b.get("type") == "tool_result"]


def test_status_context_near_full_once_at_90():
    loop = _budgeted_loop(9000, rounds=8)
    events, _out = _run(loop)
    assert len(_near_full(events)) == 1
    assert loop.last_compactions >= 1
    loop.script = _script(8)                  # a second request warns again, once
    events, _out = _run(loop)
    assert len(_near_full(events)) == 1


def test_compacted_copy_at_100_keeps_last_two_rounds_and_newest_image():
    loop = ScriptedLoop([], provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                        options=LoopOptions(num_ctx=32768, compact_in_run=True))
    old_png, new_png = tiny_png(4, 4), tiny_png(5, 5)
    messages = [
        user("go"),
        assistant_tools("", ("k0", "capture_vmd_snapshot", {})), snapshot_result("k0", old_png),
        assistant_tools("", ("k1", "capture_vmd_snapshot", {})), snapshot_result("k1", new_png),
        assistant_tools("", ("k2", "run_vmd_command", {"command": "a"})), tool_results(("k2", True, "x" * 3000 + "\n" + NOTE)),
        assistant_tools("", ("k3", "run_vmd_command", {"command": "b"})), tool_results(("k3", True, "y" * 3000)),
        assistant_tools("", ("k4", "run_vmd_command", {"command": "c"})), tool_results(("k4", True, "z" * 3000)),
    ]
    frozen = copy.deepcopy(messages)
    loop._run_budget = 5000
    loop._context_warned = True               # no run() in progress, so no status event
    compacted, did_compact = loop._compact_for_call(messages)
    assert did_compact is True and loop.last_compactions == 1
    assert messages == frozen                 # the in-run list is never modified
    k0, k1, k2, k3, k4 = [b for m in compacted if isinstance(m.get("content"), list)
                          for b in m["content"] if b.get("type") == "tool_result"]
    assert k0["content"][1]["type"] == "text" and "earlier snapshot" in k0["content"][1]["text"]
    assert k1["content"][1] == image_block(new_png)            # the newest image stays
    assert k2["content"].startswith("x" * 300) and k2["content"].endswith("\n" + NOTE)
    assert len(k2["content"]) < 700                            # C5: the stub keeps output_path
    assert k3["content"] == "y" * 3000 and k4["content"] == "z" * 3000
    loop._run_budget = 10 ** 6
    same, did_compact = loop._compact_for_call(messages)
    assert same is messages and did_compact is False


def test_messages_and_messages_out_keep_full_bodies():
    loop = _budgeted_loop(9000, rounds=8)
    _events, out = _run(loop)
    stored = _result_texts(out)
    assert len(stored) == 8 and all(text == OUTPUT for text in stored)
    compacted = [i for i, call in enumerate(loop.calls) if any(len(t) < len(OUTPUT) for t in _result_texts(call))]
    assert compacted and loop.last_compactions == len(compacted)
    for call in loop.calls:
        assert all(text == OUTPUT for text in _result_texts(call)[-2:])
    assert all(text == OUTPUT for call in loop.calls[:compacted[0]] for text in _result_texts(call))


def test_off_when_options_none():
    loop = ScriptedLoop(_script(8), provider_name="ollama", api_key="http://127.0.0.1:9", model="m")
    events, _out = _run(loop)
    assert _near_full(events) == []
    assert loop.last_compactions == 0 and loop._run_budget is None
    assert all(text == OUTPUT for call in loop.calls for text in _result_texts(call))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_compact_in_run.py -q`
Expected: `4 failed` — `AttributeError: 'ScriptedLoop' object has no attribute '_compact_for_call'` (and `… 'last_compactions'`), and the run tests find no `context_near_full` status.

- [ ] **Step 3: Implement compaction in the loop**

In `runtime/vmd_ai_runtime/claude_loop.py`, replace:

```python
from .recorder import RunRecorder
```

with:

```python
from .recorder import RunRecorder
from .conversation import (
    CONTEXT_WARN_FRACTION,
    compact_tool_results,
    compute_run_budget,
    context_tokens_for,
    messages_chars,
)
```

(`conversation` imports nothing from `claude_loop` at module level; `legacy_prior` imports `events_to_messages` lazily, so there is no import cycle.)

In `class ClaudeToolLoop`, replace:

```python
    MAX_TURNS = 28  # raised from 16: multi-step analysis tasks (RMSD/Rg/contacts) need more turns
```

with:

```python
    MAX_TURNS = 28  # raised from 16: multi-step analysis tasks (RMSD/Rg/contacts) need more turns

    # In-run compaction state (§2b); reset at the start of every run().
    last_compactions = 0
    _run_budget: Optional[int] = None
    _context_warned = False
```

In `run()`, replace:

```python
        if self.wiki_store is not None:
            system_prompt = system_prompt + WIKI_SYSTEM_PROMPT_ADDENDUM
```

with:

```python
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
```

At plan 02's single model-call site in `run()`, replace:

```python
                    text, tool_blocks = self._call_turn(
                        messages, system_prompt, on_text, cancel_event,
                    )
```

with:

```python
                    # Only the per-call copy is compacted; ``messages`` (and
                    # therefore messages_out) keeps the full bodies.
                    call_messages = messages
                    if self._run_budget is not None:
                        call_messages, _compacted = self._compact_for_call(messages)
                    text, tool_blocks = self._call_turn(
                        call_messages, system_prompt, on_text, cancel_event,
                    )
```

(A `turn_retry` retry inside `_call_turn` resends the same compacted copy.) Add the method directly before plan 02's `_on_meta`. Replace:

```python
    def _on_meta(self, item: Dict[str, Any]) -> None:
```

with:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_compact_in_run.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Run the S7 guards and every suite**

Run: `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_hashes.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_retry_pin.py -q 2>&1 | tail -1`
Expected: `… passed`, no failures (with `options=None`, `_run_budget` stays `None` and `call_messages is messages`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `N+86 passed, 1 xfailed in T s` with T < 60.

Run: `python -m pytest vmdbench/tests -q 2>&1 | tail -1 && python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1`
Expected: `90 passed`, then `62 passed`.

Run: `python -m pytest tests/test_py39_compat.py -q`
Expected: `4 passed` (or `1 passed, 3 skipped`).

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/test_compact_in_run.py
git commit -m "feat(runtime): in-run compaction behind compact_in_run (P03-T10)

With options.compact_in_run the loop budgets each call: one
context_near_full status at 90% of run_budget, and at 100% a per-call copy
whose older tool results are 300-char stubs that keep the output path.
The last 2 tool rounds and the newest image stay intact; the in-run list
and messages_out keep full bodies. options=None is unchanged (S7).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Plan exit check

- [ ] **Run the exit commands**

```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
git log --oneline main..HEAD
```

Expected: the product suite reads `N+86 passed, 1 xfailed` (N from Task 0 Step 2) in under 60 s; `90 passed`; `62 passed`; ten `feat(runtime): … (P03-T01)` … `(P03-T10)` commits (plus the optional Task 0 conftest commit). Exit criteria covered: S1 pytest part (P03-T04 `test_followup_sees_prior_tool_blocks`); C7 runtime parts (P03-T02, T05, T06, T08); S11 privileged settings/provider/cwd RPCs (P03-T09); §2b memory and in-run compaction (P03-T01..T04, T10); §2f profiles and first run (P03-T05, T06, T08); §2c M1 RPCs (P03-T09).

**Planning-time check.** Every code block of this plan was applied in order to a scratch copy of 6f5f937 with plans 01 and 02 applied (their code blocks, plan 01's conftest and helpers, and plan 02's test modules). Each task's "run it to fail" and "run it to pass" expectations above were observed there; with all ten tasks applied, `tests/` passed (623 tests, without plan 01's own test modules), `integrations/explore_arm/tests integrations/scivisagentbench` gave `62 passed`, and every runtime module imported under `/usr/bin/python3` 3.9.6. Not exercised there, so the executor must watch them: plan 01's own test modules (the S7 golden-request, bridge-guard, hash and retry-pin tests, and `test_py39_compat.py` with its module-list check), which the steps above run explicitly; and two review-time additions to P03-T09 (the `test_provider_set_activates_when_none_is_active` test with its `store.activate(name)` fix, and the no-profile `runtime.info` assertion with its `fallback` fix). A later review pass changed P03-T01's `cap_output_section` (C3's failure lines are neither counted nor cut, pinned by three new assertions in `test_store_cap_output_section_only`) and gave `FakeOllamaServer` a 0.05 s poll interval (each server used to add 0.5 s at shutdown); it then re-extracted the code blocks of P03-T01..T03 and P03-T05..T07 from this file and ran their 50 tests (Python 3.12, with minimal stand-ins for plan 01's conftest and plan 02's `LoopOptions`): all passed in about 3 s, and the five modules imported under `/usr/bin/python3` 3.9.6. If a quoted "Replace" text does not match your tree, plan 01 or 02 was executed differently: reconcile before editing.

## Deviations from skeleton

1. **Extra test helpers.** `tests/helpers/conversation_data.py` (P03-T01), `tests/helpers/app_driver.py` (P03-T04) and `tests/helpers/fake_ollama.py` (P03-T06) are not in the skeleton's file lists. They keep the message builders, the session driver/`ScriptedLoop`/`InstantBridge`, and the Ollama stand-ins in one place each instead of copying them into several test modules. `app_driver` builds on plan 02's `runtime_fixture.make_app` and `rpc` and only adds a `Session` wrapper, the envelope helpers and the scripted loop. `ScriptedLoop` defaults its model to `DEFAULT_SETTINGS["model"]`, so plan 02's per-session model override never replaces an assigned scripted loop with a real one.
2. **P03-T01/T02 extra public names.** `conversation.split_output_section`, `TAIL_MARKERS`, `FAILURE_HEAD_PREFIX`, `OUTPUT_START_LINE`, `KNOWN_KINDS`, `STORE_WARN_BYTES`, `MESSAGES_FILE`, `ALL_EVENTS`, `STUB_HEAD_CHARS`, `CONTEXT_WARN_FRACTION`, `OLLAMA_LEGACY_NUM_CTX`, `DEFAULT_CONTEXT_TOKENS`, `messages_chars`, `repair_messages`, `compact_tool_results` and `import_legacy`. `compact_tool_results` is the stub routine that both `build_prior` (oversized latest exchange) and P03-T10 use, as §2b requires the same stubs in both places. `FAILURE_HEAD_PREFIX`/`OUTPUT_START_LINE` keep C3's failure lines out of the store cap (C5 Memory); they match the text plan 05's `_structured_summary` writes (`Failed at statement …` lines, then `Output before the error:` and the output), so a plan-05 change to that wording must change these constants too. `import_legacy` fixes a gap the skeleton leaves: without it, a resumed legacy chat's text history would disappear from the prior after its first full-memory send (the new `messages.jsonl` would hold only the new exchange). It seeds `messages.jsonl` once and never rewrites `events.jsonl`.
3. **`build_prior(chat_dir, budget_chars, max_images)` takes the run budget.** It keeps `PRIOR_FRACTION × budget_chars` itself, matching the skeleton's test name `test_keeps_whole_exchanges_newest_first_within_60_percent`.
4. **`context_tokens_for("ollama", LoopOptions())` is 8192**, not 32768: a `LoopOptions` without `num_ctx` sends today's 8192 (every field defaults to today's behaviour); `LoopOptions.product` always sets 32768 or the profile's value (C7).
5. **P03-T03:** `ChatStore.lock_root` (the default store shares `~/.vmdai/.store.lock` with settings.json; a custom `root_dir` keeps its own lock file) and `append_events`/`get_manifest` ignore a falsy `chat_id`, because token sessions have `chat_id: null` until their first `chat.send`.
6. **P03-T04 does not modify `protocol.py`.** The skeleton lists it, but the `chat.send` validator already checks `conversation_mode` against `CONVERSATION_MODES`, so adding `"full"` in constants.py is enough. P03-T04 also adds the private helpers listed in its Interfaces block, and it keeps plan 02's per-session model override in `_run_claude_loop_response` (plan 02's `test_per_request_loop_gets_wiki_store` depends on it); P03-T08 limits it to tokenless sessions. A token `chat.resume` still clears the queue (P07-T05 makes `seq` monotonic); its `last_seq` is taken after the clear and before the `chat_resumed` event, so polling from `last_seq` delivers that event.
7. **P03-T05/T06 extra names.** `normalize_provider`, `KNOWN_PROVIDERS`, `DEFAULT_BASE_URLS`, `DEFAULT_PROFILE_NAMES`, `DEFAULT_MODELS`, `DEFAULT_OLLAMA_NUM_CTX`, `default_settings`, `LOCAL_OLLAMA_PORTS`, `SHOW_TIMEOUT_S` and `context_length_from_show`. `context_length_from_show` lives in settings_store because P03-T06 needs it before provider_catalog exists; P03-T07 imports it. `update_profile` with a different provider resets `base_url` to that provider's default and clears `options` and `key_ref` (a stale tunnel URL must not follow a switch to anthropic-direct). `resolve_profile`'s third element is `cli | profile | none`; per the owner's decision (2026-09-25) `VMD_AI_PROVIDER` follows §7 "seed only": it is never used live and never written to settings.json, so a token session with no active profile gets NO_MODEL.
8. **P03-T07 extra names.** `classify_unreachable`, `NO_TOOLS_HINT`, `ANTHROPIC_STATIC_MODELS`, `CATALOG_TTL_S`, `VERSION_TTL_S`. `list_models` for openai-compatible/openrouter uses `GET <base>/models`; anthropic-direct returns a static two-model list (source `static`); an unreachable Ollama adds a `hint` next to `error`. `provider.test` puts the no-tools warning in `hint`.
9. **P03-T08.** Adds `provider.resolve_openai_compatible_api_key` with key env var `VMD_AI_OPENAI_API_KEY` (the hermetic conftest clears `VMD_AI_*`, but not `OPENAI_API_KEY`), `RuntimeApp.first_run_servers`, and a router that becomes plan 02's `_base_loop_factory` (only when a settings store is passed and no explicit `loop_factory` was given), so plan 02's `provider.set` reset keeps routing token sessions to the product loop (`test_provider_set_keeps_profile_routing`); the `claude_loop` setter still overrides it for tests. Only `profile_for_session` is replaced; plan 02's `has_agent_loop` already asks the factory about that profile. The per-session model override is limited to tokenless sessions, so a token request always runs its profile's model (`test_token_send_ignores_model` checks the model the loop really used). The first run happens synchronously in `RuntimeApp.__init__`; to keep plan 02's subprocess lifecycle tests off the real ports 11435/11434, P03-T08 edits their `_env` helper in `tests/test_main_lifecycle.py` (a file the skeleton does not list) to write an empty settings.json into the temp HOME. `main.py` also passes `provider_mode=normalize_provider(args.provider)` so tokenless dev sessions honour `--provider`. Interim until P04-T04: an `openai-compatible` profile's requests still take their URL from `VMD_AI_OPENAI_BASE_URL` (the `options=None` streamer path reads it); P04-T04 switches them to `opts.base_url`.
10. **P03-T09.** `runtime.info` requires a session (any session, no launch token). A token-authenticated runtime without a settings store keeps plan 02's `provider.set`. `reasoning_visible` from a tokenless `settings.set` stays per-session and needs no token, because it is one of today's per-session keys; the other persisted keys return `AUTH_REQUIRED`. A settings write against a `newer`/`invalid` file returns `INVALID_PARAMS` with `data {reason: "read_only", settings_source}`, since the RPC catalogue has no READ_ONLY code. `_turn_tracker` is the v1 `on_event` that keeps `RequestState.turn` current; P07-T01's `_make_on_event` must keep doing that.
11. **P03-T10 hooks into plan 02's `_call_turn` call.** The skeleton's wording follows the 6f5f937 code, where `run()` calls `self._call(` directly; after plan 02 the single call site is `self._call_turn(messages, …)`, so the per-call compacted copy is passed there (and a `turn_retry` retry resends the same copy). `_compact_for_call` goes before plan 02's `_on_meta`.
12. **Plan-02 names not in the skeleton** (checked in Task 0): see the last bullet of the plan-specific constraints; plus plan 01's probe stub tolerating a `settings_store` without `probe_local_ollama` (between P03-T05 and P03-T06).
13. **P03-T08 rescue opt-in notice (added by the cross-plan completeness pass).** §2f says rescue `all` "needs an explicit profile opt-in, and a notice explains it"; no skeleton task owned the notice. A token `chat.send` whose profile loop has `options.rescue == "all"` pushes one `system/message` with metadata `{notice: "rescue_all"}` and the text `RESCUE_ALL_NOTICE` (a new module constant in `app.py`), once per session (`SessionState.rescue_all_noticed`, set on the instance). The M1 `ui.tcl` prints it like the security note, and plan 08's view-model turns a `system/message` with text into `{notice info <text>}`. It is pinned by extra assertions in `test_token_send_ignores_model`, so the test counts of this plan are unchanged.
14. **P03-T07 `provider.test` reports `version` (added by the cross-plan completeness pass).** Part B V4 shows Test connection as `✓ Connected · 212 ms · Ollama 0.34.4`, but the §3 result fields carry no version, so the panel (P09-T04) had nothing to show. `test_provider` already reads `/api/version` for Ollama; it now returns that value as an additive `version` key (Ollama only, omitted when empty). `test_provider_test_warns_without_tools` asserts it; the test count is unchanged, and the `provider.test` RPC passes the dict through as before.
