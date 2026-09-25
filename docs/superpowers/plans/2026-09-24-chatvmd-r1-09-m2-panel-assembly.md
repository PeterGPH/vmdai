# ChatVMD Round 1 — Plan 09: ChatVMD R1 — M2 panel assembly, settings, history, v2 switch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Assemble the panel (grid, empty state, keyboard map), build the settings dialog and the ttk history, show reasoning, and switch the plugin to event_protocol 2 with long-poll, retiring ui.tcl.

**Architecture:** A new `plugin/panel.tcl` owns the `.vmd_ai` toplevel: it grids plan 08's components (toolbar, banner, transcript, composer, status bar) in the Part B V3 order, owns the view-model state `::vmdai::panel::vm`, and is the single place where events become ops (`vm::apply` → `panel::render` → `transcript::apply_ops` / status bar / composer). `plugin/settings.tcl` and `plugin/history.tcl` are titled transient ttk dialogs that talk to the runtime only through `::vmdai::net::call`. The bridge negotiates `event_protocol 2`, long-polls, ends busy on `request.finished`, and replays `chat.history.get` through the panel on resume; `plugin/ui.tcl` shrinks to a forwarding shim for the names the M1 modules still call.

**Tech Stack:** Tcl/Tk 8.6 (VMD 1.9.4a57's Tk 8.6.12 loaded into tclsh 8.6.14), ttk widgets only (`ttk::notebook`, `ttk::treeview`, `ttk::combobox`), tcllib json 1.1.2 (vendored by P06-T01), tcltest 2 files under `tests/tcl/` wrapped by pytest; Python 3.9–3.12 pytest for the wrappers and the end-to-end test against plan 06's in-process scripted runtime.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — this plan implements Part B **V3** (Window), **V4** (Empty state, Settings, History, Reasoning, and the toolbar/⋯-menu actions the panel owns), **V5** (Keyboard and interaction map), **V6** (width classes); Part A **§2c** Stage split M2 (the plugin switches to `event_protocol: 2`), Persistence (replay through `vm::apply`), Busy state after a reconnect; **§2d** M2 long-poll, Working directory (Settings "Project folder"); **§2f** Where provider settings live, Schema (`settings.set` keys), Providers and keys (the Keys tab and the "No keychain backend" message), First run (the empty state's Model row and the Settings prefill); **§2g** Wiki off by default (the Settings toggle); **§2h** UI code structure (panel.tcl, settings.tcl, history.tcl; `ui.tcl` retired); **§6** Tk golden transcripts; **§8** M2 exit (S2, Tk goldens for the new panel); Part C **C7** Visibility (the `· ctx 32k (max 128k)` model hint and the low-context warning). Part C wins where it conflicts with Parts A/B.

**Branch:** `chatvmd-r1-09-m2-panel-assembly`, created from `main` after plan 08 (`chatvmd-r1-08-m2-panel-core`, which itself follows plans 01–07) is merged.

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

- This plan changes only `plugin/` and `tests/`. No runtime (Python) file changes: everything the panel needs already exists after plans 02–07 (`runtime.info`, `models.list`, `provider.test`, `profiles.*`, `settings.set`, `keys.test`/`keys.save`, `chat.history.*`, long-poll).
- Every non-ASCII character in plugin Tcl is written as a `\uXXXX` escape inside double quotes (VMD sources plugin files in the system encoding). Inside braces `\u` is not substituted, so strings that carry `\u` escapes are always built with `"…"` or `[list …]`.
- New Tk code uses plan 08's named fonts (`ChatBody`, `ChatBodyBold`, `ChatMeta`, `ChatMetaBold`, `ChatH1`, `ChatCode`) and theme tokens (`::vmdai::theme::c <token>`); it hard-codes no colour and no font family. The one derived font it creates is `ChatMetaItal` (from `ChatMeta`, `-slant italic`).
- Procs defined in the `::vmdai::panel`, `::vmdai::settings` and `::vmdai::history` namespaces never shadow a Tcl/Tk command they call: they call `::destroy` (not `destroy`), and no proc in these namespaces is named `destroy`, `open` (except `settings::open` and `history::open`, which never call channel `open`), `close` (except `settings::close`/`history::close`, which never call channel `close`), `update` or `focus`.
- Dialogs and the panel are mapped only through `::vmdai::panel::present w`, which does nothing while `::vmdai::panel::headless` is 1. Every Tk test sets it, so tests never map a window.
- Tk tests never use `event generate`: with VMD's Tk 8.6.12 on aqua it did not deliver key events to a withdrawn toplevel, and button and virtual events sent to children of a never-mapped toplevel were not reliably delivered (both checked during planning). Bindings are exercised with `::harness::fire w <Seq>`, which runs the bound scripts through the widget's bindtags exactly as Tk dispatches them, and text-tag bindings with `uplevel #0 [$t tag bind tag <Seq>]`. Unmapped text widgets are 1 px wide, so tests that depend on display lines place the insert mark explicitly.
- Tk tests replace `::vmdai::net::call` with the recording fake in `tests/tcl/panel_harness.tcl`; they open no sockets. Only Task P09-T09 talks to a real (in-process) runtime.
- Files created by plans 06–08 did not exist at 6f5f937, and plan 06 rewrites `plugin/bridge.tcl`, `plugin/init.tcl` and `plugin/ui.tcl`. Edits to those files are located by the quoted anchors that Task 0 prints, not by line numbers; the line counts at 6f5f937 are given only for orientation.

## Review Focus

1. Save in Settings while a request runs: the change is saved and applies from the next message; the running request is not cancelled, restarted or moved to a new chat. Owner P09-T05: `tests/test_tk_settings.py::test_save_while_busy`.
2. `models.list` times out or returns no models: the dialog stays usable (the Model field stays editable, Save stays enabled and saves a typed model name) and the hint says what happened. Owner P09-T04: `tests/test_tk_settings.py::test_models_timeout_hint`.
3. Resuming a `CHAT_LOCKED` chat shows "Open in another VMD window" inline and keeps the History dialog open. Owner P09-T06: `tests/test_tk_history.py::test_locked_inline`.
4. The runtime restarts while Settings is open: callbacks for the old runtime are dropped, the dialog reloads its profiles from the new runtime when the state returns to `ready`, and Save then works. Owner P09-T07: `tests/test_tcl_bridge_v2.py::test_settings_after_restart`.
5. The window is closed mid-request: it is only withdrawn; the request, its timers and the runtime keep running, and a withdrawn window's 1×1 geometry is never saved over the user's. Owner P09-T01: `tests/test_tk_panel.py::test_withdraw_keeps_request`.

## Consumed contract (plans 06–08)

The skeleton names the interfaces this plan consumes; the rows below also fix the few details the skeleton leaves open. Task 0 checks every row with an executable test. **If any Task 0 check fails, stop**: the plan-06/07/08 code differs from what this plan was written against, and the difference must be reconciled (and recorded in the PR description) before Task P09-T01.

| Interface (owner) | Detail this plan relies on | Task 0 check |
|---|---|---|
| `::vmdai::net::call method params callback ?-timeout ms?` (P06-T03) | `params` is a flat list of triples `name type value` (`s`, `i`, `b`, `j`); the callback runs with `ok result`, `rpc_error code message data` or `transport reason` appended | `pre-encode`, `pre-callbacks` |
| `::vmdai::net::encode_params pairs` (P06-T03) | returns one compact JSON object, keys in the given order, `b` as `true`/`false`, `j` verbatim | `pre-encode` |
| `::vmdai::sched::after ms script`, `after_idle script`, `cancel id`, `pending` (P06-T02) | `pending` returns the ids that `after`/`after_idle` returned and that have not fired or been cancelled | `pre-sched` |
| `::vmdai::config::load_plugin_settings`, `save_plugin_settings dict`, `plugin_json_path`, `log_path`, `log msg`, variables `poll_ms`, `request_timeout_ms` (P06-T02) | `load` returns a dict (defaults when the file is missing); `save` writes that dict to `$HOME/.vmdai/plugin.json` | `pre-config` |
| `::vmdai::runtime::state`, `info`, `subscribe cmd`, `ensure`, `stop`, `retry_now` (P06-T05/T06) | subscribers run as `{*}$cmd old new detail` | `pre-procs` |
| `::vmdai::bridge::state`, `send`, `cancel`, `new_chat`, `resume chat_id ?callback?`, `apply_workdir dir`, `start_session` (P06-T07) | `state` is built from namespace variables of the same names (`busy`, `request_id`, …); `event_protocol` is a namespace variable (1 in M1); `resume`'s callback gets the net callback forms | `pre-bridge-vars`, `pre-callbacks` |
| `::vmdai::vm::init stateVar ?options?`, `apply stateVar event`, `local_event kind fields`, `stop_requested stateVar` (P08-T01..T03) | `local_event` takes the full kind (`local.send_failed`) and returns a §2c envelope whose `metadata.kind` is that kind | `pre-local-event` |
| `::vmdai::transcript::create path`, `apply_ops ops`, `clear`, `dump`, `set_expand_all bool`, `_wl` (P08-T05/T06) | `create` returns the path of the read-only Text (`path` itself or a descendant); its proxy passes `tag`, `peer`, `get`, `search`, `yview`, `see`; `_wl` returns `wl:$run` for the run that `{run.open …}` made current (P09-T08 tags its reasoning lines with it) | `pre-transcript`, `pre-procs` |
| `::vmdai::composer::create path ?-onsend cmd? ?-onstop cmd?`, `get_text`, `set_text`, `set_mode`, `focus`, `push_history` (P08-T08) | the input is the first `Text` descendant of `path`; the Send button is a `TButton` descendant | `pre-composer` |
| `::vmdai::statusbar::create path`, `update dict`, `text`, `flash text ms` (P08-T09) | `update` merges keys `connection provider model host folder runs busy activity t0` into what it shows | `pre-statusbar` |
| `::vmdai::banner::create path`, `on_runtime_state old new detail` (P08-T09) | the banner shows and hides itself with `grid` / `grid remove` inside the slot the panel grids | `pre-procs` |
| `::vmdai::toolbar::create path`, `set_title s`, `set_busy on` (P08-T10) | its icons and ⋯ items call names in `::vmdai::panel::`, `::vmdai::settings::` or `::vmdai::history::` | `test_component_targets_defined` (P09-T01) |
| `::vmdai::tclexport::record request_id call_key command applied failed_index`, `chat_tcl`, `save path text`, `reset` (P08-T11) | as named; `record` is not called by any plan-08 module (P09-T07's panel feeds it from `tool.started`/`tool.finished`) | `pre-procs` |
| `::vmdai::theme::init ?mode?`, `c token`, `paint w option token` (P08-T04) | tokens `chrome surface text muted faint hairline accent ok err warn` exist | `pre-theme` |
| `helpers.tk` `tk_skip_reason`, `tk_prelude`, `run_tk_test(test_file, *, env=None, timeout=120)`, `update_goldens`, `golden_path(name)` (P06-T10) | `run_tk_test` exports `VMDAI_REPO`, `VMDAI_PLUGIN_DIR` and a temp `HOME` like `run_tcltest`, skips when Tk is unavailable, and `golden_path("x")` is `tests/fixtures/tk/x.txt` | `test_tk_helper_signatures` |
| `helpers.scripted_runtime.serve_runtime(home, loop_factory)`, `ScriptedLoopFactory(script)` (P06-T11) | script items are `(assistant_text, [tool_use dicts {id, name, input}])`, served in order across requests | docstring printed in Task 0 |
| session.start with `event_protocol: 2` (P07-T01/T06) | a token session gets `event_protocol: 2` and `capabilities.long_poll: true` | `test_v2_and_long_poll_negotiated` |

## File map

| Path | Action | Responsibility |
|---|---|---|
| `plugin/panel.tcl` | create (T01; modified T03, T07, T08) | the `.vmd_ai` window: grid, show/withdraw, geometry, width classes, keys, focus ring, event → ops routing, replay, runtime-state fan-out |
| `plugin/settings.tcl` | create (T04; modified T05, T08) | the Settings dialog: Model, Keys, Panel tabs; Save chain |
| `plugin/history.tcl` | create (T06) | the History picker (ttk::treeview) |
| `plugin/transcript.tcl` | modify (T02, T08) | empty-state overlay; reasoning display |
| `plugin/composer.tcl` | modify (T03) | prompt recall (Up/Down) |
| `plugin/bridge.tcl` | modify (T07) | event_protocol 2, long-poll, v2 busy tracking, send failures, history replay |
| `plugin/ui.tcl` | replace (T07) | forwarding shim for the names the M1 modules call |
| `plugin/init.tcl` | modify (T01, T04, T06) | source the M2 modules; `::vmdai::start` opens the panel |
| `tests/tcl/panel_harness.tcl` | create (T01) | shared Tk-test setup: modules, fake transport, `fire`, stubs |
| `tests/helpers/tk_cases.py` | create (T01) | run one Tk tcltest file per module, report per-case results |
| `tests/tcl/test_panel.tcl`, `tests/test_tk_panel.py` | create (T01) | panel tests + component-target guard |
| `tests/tcl/test_empty_state.tcl`, `tests/test_tk_empty_state.py` | create (T02) | empty-state tests |
| `tests/tcl/test_keymap.tcl`, `tests/test_tk_keymap.py` | create (T03) | keyboard-map tests |
| `tests/tcl/test_settings.tcl`, `tests/test_tk_settings.py` | create (T04; extended T05) | settings tests |
| `tests/tcl/test_history.tcl`, `tests/test_tk_history.py` | create (T06) | history tests |
| `tests/tcl/test_bridge_v2.tcl`, `tests/test_tcl_bridge_v2.py` | create (T07) | v2 switch tests + ui-shim guard |
| `tests/tcl/test_reasoning_display.tcl`, `tests/test_tk_reasoning_display.py` | create (T08) | reasoning display tests |
| `tests/tcl/panel_driver.tcl`, `tests/test_panel_integration.py`, `tests/fixtures/tk/panel_03_conversation.txt`, `tests/fixtures/tk/panel_resume_replay.txt` | create (T09) | end-to-end panel test and M2 goldens |

---

### Task 0: Pre-flight — confirm plans 06–08 are merged and the consumed contract holds

**Files:**
- Create (temporary, never committed): `tests/test_zz_preflight_09.py`, `tests/tcl/zz_preflight_09.tcl`

**Interfaces:**
- Consumes: every row of the "Consumed contract" table above.
- Produces: the baseline pass count `B` used by the "Expected" lines below, and the anchor listing used by Tasks P09-T01, T03 and T07.

- [ ] **Step 1: Cut the branch and record the baseline**

Run:
```bash
git switch main
git log --oneline -1
git switch -c chatvmd-r1-09-m2-panel-assembly
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -3
```
Expected: the last line reads `B passed, S skipped in …s` with **0 failed** (Tk tests skip only when no GUI session is available). Write `B` down; every later "Expected" suite line is relative to it. Run this plan's Tk tests from a GUI login session on the dev Mac, otherwise they skip.

- [ ] **Step 2: Confirm the files plans 06–08 created**

Run:
```bash
for f in config sched net runtime bridge executor ui init pkgIndex theme viewmodel transcript viewer composer statusbar banner toolbar tclexport; do
  test -f plugin/$f.tcl || echo "MISSING plugin/$f.tcl"; done
for f in plugin/lib/json/json.tcl tests/helpers/tcl.py tests/helpers/tk.py tests/helpers/scripted_runtime.py \
         tests/helpers/runtime_fixture.py tests/tcl/driver.tcl tests/fixtures/events/03_conversation.jsonl \
         tests/test_tcl_lint.py; do
  test -f $f || echo "MISSING $f"; done
```
Expected: no output.

- [ ] **Step 3: Write the Tcl contract check**

Create `tests/tcl/zz_preflight_09.tcl`:

```tcl
# Temporary pre-flight for plan 09 (never committed): the plan-06..08 details
# listed in the plan's "Consumed contract" table.
package require tcltest 2
namespace import -force ::tcltest::*
if {[info exists ::env(VMDAI_TCL_TM)] && $::env(VMDAI_TCL_TM) ne ""} {
    ::tcl::tm::path add $::env(VMDAI_TCL_TM)
}
lappend ::auto_path [file join $::env(VMDAI_PLUGIN_DIR) lib json]
package require -exact json 1.1.2
foreach m {config sched net runtime bridge executor theme viewmodel transcript viewer
           composer statusbar banner toolbar tclexport} {
    source [file join $::env(VMDAI_PLUGIN_DIR) $m.tcl]
}

test pre-procs {every consumed proc exists} -body {
    set missing {}
    foreach p {
        ::vmdai::net::call ::vmdai::net::encode_params ::vmdai::sched::after
        ::vmdai::sched::after_idle ::vmdai::sched::cancel ::vmdai::sched::pending
        ::vmdai::sched::teardown ::vmdai::config::load_plugin_settings
        ::vmdai::config::save_plugin_settings ::vmdai::config::plugin_json_path
        ::vmdai::config::log_path ::vmdai::config::log ::vmdai::runtime::state
        ::vmdai::runtime::info ::vmdai::runtime::subscribe ::vmdai::runtime::ensure
        ::vmdai::runtime::stop ::vmdai::runtime::retry_now ::vmdai::bridge::state
        ::vmdai::bridge::send ::vmdai::bridge::cancel ::vmdai::bridge::new_chat
        ::vmdai::bridge::resume ::vmdai::bridge::apply_workdir ::vmdai::bridge::start_session
        ::vmdai::vm::init ::vmdai::vm::apply ::vmdai::vm::local_event ::vmdai::vm::stop_requested
        ::vmdai::theme::init ::vmdai::theme::c ::vmdai::theme::paint
        ::vmdai::transcript::create ::vmdai::transcript::apply_ops ::vmdai::transcript::clear
        ::vmdai::transcript::dump ::vmdai::transcript::set_expand_all
        ::vmdai::composer::create ::vmdai::composer::get_text ::vmdai::composer::set_text
        ::vmdai::composer::set_mode ::vmdai::composer::focus ::vmdai::composer::push_history
        ::vmdai::statusbar::create ::vmdai::statusbar::update ::vmdai::statusbar::text
        ::vmdai::statusbar::flash ::vmdai::banner::create ::vmdai::banner::on_runtime_state
        ::vmdai::toolbar::create ::vmdai::toolbar::set_title ::vmdai::toolbar::set_busy
        ::vmdai::tclexport::record ::vmdai::tclexport::chat_tcl ::vmdai::tclexport::save
        ::vmdai::tclexport::reset ::vmdai::transcript::_wl
    } {
        if {[info commands $p] eq ""} { lappend missing $p }
    }
    set missing
} -result {}

test pre-encode {typed triples encode to one compact JSON object} -body {
    ::vmdai::net::encode_params [list a s x n i 3 f b 1 o j {{"k":1}}]
} -result {{"a":"x","n":3,"f":true,"o":{"k":1}}}

test pre-sched {pending lists live ids} -body {
    set id [::vmdai::sched::after 60000 {set ::never 1}]
    set live [expr {$id in [::vmdai::sched::pending]}]
    ::vmdai::sched::cancel $id
    list $live [expr {$id in [::vmdai::sched::pending]}]
} -result {1 0}

test pre-config {plugin.json round trip under the temp HOME} -body {
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 600x700+1+1]
    set path [::vmdai::config::plugin_json_path]
    list [dict get [::vmdai::config::load_plugin_settings] geometry] [file exists $path] \
         [file tail $path] [file tail [file dirname $path]]
} -result {600x700+1+1 1 plugin.json .vmdai}

test pre-bridge-vars {bridge state lives in namespace variables} -body {
    list [info exists ::vmdai::bridge::event_protocol] [info exists ::vmdai::bridge::busy] \
         [info exists ::vmdai::bridge::request_id] [lsort [dict keys [::vmdai::bridge::state]]]
} -result {1 1 1 {after_seq busy chat_id epoch request_id session_id}}

test pre-local-event {local events carry their full kind} -body {
    dict get [::vmdai::vm::local_event local.send_failed [dict create code NO_MODEL message m]] metadata kind
} -result local.send_failed

test pre-callbacks {bridge::resume hands back the net callback forms} -body {
    proc ::vmdai::net::call {method params callback args} {
        after 0 [list {*}$callback rpc_error CHAT_LOCKED locked {}]
    }
    set ::got {}
    set ::vmdai::bridge::session_id sess_preflight
    ::vmdai::bridge::resume chat_000000000001 [list apply {{args} {set ::got $args}}]
    set deadline [expr {[clock milliseconds] + 1000}]
    while {$::got eq "" && [clock milliseconds] < $deadline} { after 10; update }
    lrange $::got 0 1
} -result {rpc_error CHAT_LOCKED}

test pre-theme {tokens this plan uses exist} -body {
    ::vmdai::theme::init
    set missing {}
    foreach tok {chrome surface text muted faint hairline accent ok err warn} {
        if {[catch {::vmdai::theme::c $tok}]} { lappend missing $tok }
    }
    set missing
} -result {}

test pre-transcript {create returns the read-only Text} -body {
    toplevel .pf
    wm withdraw .pf
    set t [::vmdai::transcript::create .pf.tx]
    set before [$t get 1.0 end]
    $t insert end INJECTED
    $t peer create $t.__probe
    list [winfo class $t] [string match .pf.tx* $t] [expr {[$t get 1.0 end] eq $before}] \
         [winfo class $t.__probe]
} -result {Text 1 1 Text}

test pre-composer {the composer input is a Text descendant, Send a TButton} -body {
    ::vmdai::composer::create .pf.cb
    set classes {}
    set queue [list .pf.cb]
    while {[llength $queue]} {
        set queue [lassign $queue cur]
        foreach c [winfo children $cur] { lappend classes [winfo class $c]; lappend queue $c }
    }
    list [expr {"Text" in $classes}] [expr {"TButton" in $classes}]
} -result {1 1}

test pre-statusbar {update merges keys that reach the text} -body {
    ::vmdai::statusbar::create .pf.sb
    ::vmdai::statusbar::update [dict create connection ready provider Ollama model qwen-test \
        host 127.0.0.1:11435 folder /tmp runs 3 busy 0]
    ::vmdai::statusbar::update [dict create busy 0]
    set s [::vmdai::statusbar::text]
    list [string match *qwen-test* $s] [string match *127.0.0.1:11435* $s] [string match *tunnel* $s]
} -result {1 1 0}

cleanupTests
```

- [ ] **Step 4: Write the Python contract check**

Create `tests/test_zz_preflight_09.py`:

```python
"""Temporary pre-flight for plan 09 (never committed)."""
from __future__ import annotations

import inspect
from pathlib import Path

from helpers import tcl, tk
from helpers.runtime_fixture import make_app, start_token_session
from helpers.scripted_runtime import ScriptedLoopFactory, serve_runtime

REPO = Path(__file__).resolve().parents[1]
TOKEN = "ab" * 16


def test_tk_helper_signatures():
    params = inspect.signature(tk.run_tk_test).parameters
    assert list(params)[0] == "test_file" and "env" in params and "timeout" in params
    assert tk.golden_path("panel_03_conversation") == REPO / "tests" / "fixtures" / "tk" / "panel_03_conversation.txt"
    assert "Tk" in tk.tk_prelude()


def test_scripted_runtime_signatures():
    assert list(inspect.signature(serve_runtime).parameters)[:2] == ["home", "loop_factory"]
    print(inspect.getdoc(ScriptedLoopFactory))


def test_v2_and_long_poll_negotiated(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    started = start_token_session(app, TOKEN, event_protocol=2)
    assert started["event_protocol"] == 2
    assert started["capabilities"]["long_poll"] is True


def test_tcl_contract():
    result = tk.run_tk_test(str(REPO / "tests" / "tcl" / "zz_preflight_09.tcl"),
                            env={"VMDAI_TCL_TM": tcl.http_tm_dir() or ""})
    assert result.failed == 0 and result.passed == 11, result.output
```

- [ ] **Step 5: Run the contract checks**

Run: `python -m pytest tests/test_zz_preflight_09.py -q -s`
Expected: `4 passed`, and the printed docstring of `ScriptedLoopFactory` says the script is a list of `(text, tool_calls)` model turns served in order across requests, each tool call a dict with `id`, `name` and `input`. If a check fails or the docstring says otherwise, stop and reconcile (see "Consumed contract").

- [ ] **Step 6: Print the anchors later tasks edit**

Run:
```bash
grep -n 'event_protocol\|chat.events.poll\|session.start\|render_event\|set_busy\|details may be missing\|chat.send\|chat.resume\|poll_ms' plugin/bridge.tcl
grep -n 'source\|show_panel\|ui::win\|proc ::vmdai::' plugin/init.tcl
grep -rn '::vmdai::ui::' plugin --include=*.tcl | grep -v '^plugin/ui.tcl'
grep -n 'proc ::vmdai::composer::push_history' -A 12 plugin/composer.tcl
grep -n '::vmdai::\(panel\|settings\|history\)::' plugin/*.tcl
```
Expected: each command prints at least one line except the last, which may print nothing. Keep this output next to the plan: Tasks P09-T01 (init.tcl), P09-T03 (push_history) and P09-T07 (bridge.tcl, ui.tcl callers) quote these anchors.

- [ ] **Step 7: Remove the temporary files**

Run:
```bash
rm tests/test_zz_preflight_09.py tests/tcl/zz_preflight_09.tcl
git status --short
```
Expected: no output (nothing to commit).

---
### Task P09-T01: panel.tcl grid assembly

**Files:**
- Create: `plugin/panel.tcl`
- Create: `tests/tcl/panel_harness.tcl` (shared by every Tk test of this plan)
- Create: `tests/helpers/tk_cases.py`
- Create: `tests/tcl/test_panel.tcl`
- Modify: `plugin/init.tcl` (51 lines at 6f5f937; rewritten by P06-T07/T09 — edit at the anchors Task 0 Step 6 printed: the module `source` list, `::vmdai::start`, `::vmdai::stop`)
- Test: `tests/test_tk_panel.py`

**Interfaces:**
- Consumes: components (P08) — `::vmdai::theme::init`, `::vmdai::theme::c`, `::vmdai::theme::paint`, `::vmdai::toolbar::create/set_title/set_busy`, `::vmdai::banner::create`, `::vmdai::transcript::create/apply_ops/set_expand_all`, `::vmdai::composer::create/get_text/set_text/set_mode/push_history`, `::vmdai::statusbar::create/update`, `::vmdai::tclexport::chat_tcl/save`, `::vmdai::vm::init/stop_requested`; plugin.json (P06-T02) — `::vmdai::config::load_plugin_settings`, `save_plugin_settings`, `log_path`, `log`; `::vmdai::bridge::state/send/cancel/new_chat/apply_workdir`, `::vmdai::runtime::state/info/stop/ensure` (P06).
- Produces: `::vmdai::panel::build ?win? -> path; show; withdraw; width_class w`. Also (used by later tasks and by plan 08's toolbar/banner/status bar): `::vmdai::panel::win` (`.vmd_ai`), `text` (the transcript Text path), `headless`, `vm` (view-model state variable), `present w`, `dispose`, `set_title s`, `bridge_busy`, `set_busy on`, `render ops`, `on_send ?text?`, `on_stop`, `new_chat`, `open_settings ?tab? ?prefill?`, `open_history`, `choose_folder`, `toggle_expand`, `set_expand_all on`, `collapse_older`, `copy_chat_tcl`, `save_chat_tcl`, `open_runs_folder`, `open_log`, `quit_runtime`, `open_path path`, `_set_clipboard s`, `provider_label id`, `hostport url`, `run_count`, `initial_geometry`, `refresh_info` (a status-bar refresh that P09-T07 replaces). Test helpers: `tests/tcl/panel_harness.tcl` (`::fake::*`, `::harness::*`), `helpers.tk_cases.run_tk_file(name, env=None)`, `assert_case(result, case, total)`, `failed_cases(result)`.

- [ ] **Step 1: Write the shared Tk test harness**

Create `tests/tcl/panel_harness.tcl`:

```tcl
# tests/tcl/panel_harness.tcl - shared setup for the plan-09 Tk tests.
#
# Every tests/tcl/test_*.tcl file of plan 09 sources this first, after
# helpers.tk.run_tk_test has loaded VMD's Tk into tclsh 8.6 and withdrawn ".".
# It
#   * loads the vendored json 1.1.2 (and puts VMD's http 2.9.5 on the module
#     path in case net.tcl asks for it),
#   * sources the plugin modules the panel needs - not init.tcl, so nothing
#     launches or attaches to a runtime,
#   * keeps the panel and every dialog withdrawn (::vmdai::panel::headless),
#   * replaces ::vmdai::net::call with a recording fake (no sockets), and
#   * provides ::harness::fire: `event generate` does not reach widgets of
#     a never-mapped toplevel (VMD's Tk 8.6.12 on aqua), so bindings are run
#     through the widget's bindtags the way Tk dispatches them.
package require tcltest 2
namespace import -force ::tcltest::*

if {[info exists ::env(VMDAI_TCL_TM)] && $::env(VMDAI_TCL_TM) ne ""} {
    ::tcl::tm::path add $::env(VMDAI_TCL_TM)
}
lappend ::auto_path [file join $::env(VMDAI_PLUGIN_DIR) lib json]
package require -exact json 1.1.2

namespace eval ::harness {
    variable plugin $::env(VMDAI_PLUGIN_DIR)
    variable modules {config sched net runtime bridge executor theme viewmodel
        transcript viewer composer statusbar banner toolbar tclexport panel
        settings history}
    variable bridge_calls {}
    variable busy 0
    variable runtime_state ready
    variable resume_reply {ok {ok true chat_id chat_000000000001 title {Old chat}}}
    variable clipboard ""
    variable opened {}
    variable flashes {}
    variable settings_opened {}
}
foreach ::harness::module $::harness::modules {
    set ::harness::path [file join $::harness::plugin $::harness::module.tcl]
    if {[file exists $::harness::path]} { source $::harness::path }
}
# namespace eval, not `set`: before P09-T01 creates panel.tcl the namespace
# does not exist yet, and the fail-first run must reach the test bodies.
namespace eval ::vmdai::panel { variable headless 1 }

# ---- fake transport ------------------------------------------------------
namespace eval ::fake {
    variable calls {}
    variable held {}
    variable replies
    array set replies {}
}
proc ::fake::reset {} {
    variable calls {}
    variable held {}
    variable replies
    array unset replies
    array set replies {}
}
# ::fake::reply method form ?arg ...? sets how every later call of `method`
# answers, in the P06 callback forms:
#   ::fake::reply models.list ok {models {} source server}
#   ::fake::reply chat.resume rpc_error CHAT_LOCKED "locked" {}
#   ::fake::reply models.list transport timeout
#   ::fake::reply profiles.list hold   ;# keep the callback, never run it
# A method with no reply records the call and never answers.
proc ::fake::reply {method args} {
    variable replies
    set replies($method) $args
}
proc ::vmdai::net::call {method params callback args} {
    set timeout 3000
    foreach {opt value} $args {
        if {$opt eq "-timeout"} { set timeout $value }
    }
    lappend ::fake::calls [list $method $params $timeout]
    if {![info exists ::fake::replies($method)]} { return }
    set reply $::fake::replies($method)
    if {[lindex $reply 0] eq "hold"} {
        lappend ::fake::held [list $method $callback]
        return
    }
    after 0 [list ::fake::deliver $callback $reply]
}
proc ::fake::deliver {callback reply} {
    uplevel #0 [list {*}$callback {*}$reply]
}
proc ::fake::calls_of {method} {
    set out {}
    foreach call $::fake::calls {
        if {[lindex $call 0] eq $method} { lappend out [lindex $call 1] }
    }
    return $out
}
proc ::fake::count {method} { return [llength [::fake::calls_of $method]] }
proc ::fake::last {method} { return [lindex [::fake::calls_of $method] end] }
proc ::fake::timeout_of {method} {
    set timeout ""
    foreach call $::fake::calls {
        if {[lindex $call 0] eq $method} { set timeout [lindex $call 2] }
    }
    return $timeout
}
# The value of `name` in a typed parameter list {name type value ...}.
proc ::fake::param {params name} {
    foreach {n type value} $params {
        if {$n eq $name} { return $value }
    }
    return ""
}
proc ::fake::has_param {params name} {
    foreach {n type value} $params {
        if {$n eq $name} { return 1 }
    }
    return 0
}

# ---- event loop and bindings ---------------------------------------------
proc ::harness::settle {} {
    update
    update idletasks
}
proc ::harness::wait_until {script {ms 2000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        after 10
        update
    }
    return 1
}
# Run the bindings for `seq` on `w` through its bindtags, with %W
# substituted, stopping at `break`, as Tk does for a real event.
proc ::harness::fire {w seq} {
    foreach tag [bindtags $w] {
        set script [bind $tag $seq]
        if {$script eq ""} { continue }
        set script [string map [list %W $w %% %] $script]
        set code [catch {uplevel #0 $script} result]
        if {$code == 3} { break }
        if {$code == 1} { return -code error $result }
    }
    update idletasks
}
proc ::harness::descendants {w} {
    set out {}
    set queue [list $w]
    while {[llength $queue]} {
        set queue [lassign $queue current]
        foreach child [winfo children $current] {
            lappend out $child
            lappend queue $child
        }
    }
    return $out
}
proc ::harness::texts_under {w} {
    set out {}
    foreach child [::harness::descendants $w] {
        if {[winfo class $child] in {Label TLabel TButton Button TCheckbutton}} {
            lappend out [$child cget -text]
        }
    }
    return $out
}
proc ::harness::label_with_text {w text} {
    foreach child [::harness::descendants $w] {
        if {[winfo class $child] in {Label TLabel} && [$child cget -text] eq $text} { return $child }
    }
    return ""
}

# ---- panel and stubs -----------------------------------------------------
proc ::harness::fresh_panel {} {
    catch {::vmdai::panel::dispose}
    foreach top {.vmd_ai .vmd_ai_settings .vmd_ai_history} {
        if {[winfo exists $top]} { ::destroy $top }
    }
    ::fake::reset
    set ::harness::bridge_calls {}
    set ::harness::busy 0
    set ::vmdai::panel::title "New chat"
    set ::vmdai::panel::busy 0
    set ::vmdai::panel::stopping 0
    set ::vmdai::panel::nomodel 0
    return [::vmdai::panel::build]
}
proc ::harness::count_calls {name} {
    set n 0
    foreach call $::harness::bridge_calls {
        if {[lindex $call 0] eq $name} { incr n }
    }
    return $n
}
# Replace the bridge's user-facing procs with recorders; ::harness::busy
# drives the busy flag that ::vmdai::bridge::state reports.
proc ::harness::stub_bridge {} {
    proc ::vmdai::bridge::state {} {
        set rid [expr {$::harness::busy ? "req_harness" : ""}]
        return [dict create session_id sess_harness chat_id "" busy $::harness::busy \
            request_id $rid after_seq 0 epoch 1]
    }
    proc ::vmdai::bridge::send {text} { lappend ::harness::bridge_calls [list send $text] }
    proc ::vmdai::bridge::cancel {args} { lappend ::harness::bridge_calls [list cancel] }
    proc ::vmdai::bridge::new_chat {args} { lappend ::harness::bridge_calls [list new_chat] }
    proc ::vmdai::bridge::apply_workdir {dir} { lappend ::harness::bridge_calls [list apply_workdir $dir] }
    proc ::vmdai::bridge::resume {chat_id {callback ""}} {
        lappend ::harness::bridge_calls [list resume $chat_id]
        if {$callback ne ""} {
            after 0 [list uplevel #0 [list {*}$callback {*}$::harness::resume_reply]]
        }
    }
    proc ::vmdai::runtime::stop {args} { lappend ::harness::bridge_calls [list runtime_stop] }
    proc ::vmdai::runtime::state {} { return $::harness::runtime_state }
}
# Clipboard, desktop opener and status flashes, so tests touch nothing real.
proc ::harness::stub_desktop {} {
    proc ::vmdai::panel::_set_clipboard {s} { set ::harness::clipboard $s }
    # P08-T05's transcript links (Copy, Copy Tcl, Copy path) copy through
    # their own helper; keep them off the real system clipboard too.
    proc ::vmdai::transcript::_clipboard {text} { set ::harness::clipboard $text }
    proc ::vmdai::panel::open_path {path} { lappend ::harness::opened $path }
    proc ::vmdai::statusbar::flash {text args} { lappend ::harness::flashes $text }
}
proc ::harness::stub_settings_open {} {
    proc ::vmdai::panel::open_settings {{tab model} {prefill {}}} {
        lappend ::harness::settings_opened [list $tab $prefill]
    }
}
```

- [ ] **Step 2: Write the pytest helper that runs a Tk tcltest file once per module**

Create `tests/helpers/tk_cases.py`:

```python
"""Run one plan-09 Tk tcltest file and report its cases to pytest.

Each tests/test_tk_*.py module runs its tcltest file once (a module-scoped
fixture) and then has one pytest function per tcltest case, so a failure
names the case. The file skips as a whole when Tk is unavailable
(helpers.tk.run_tk_test calls pytest.skip).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Set

from helpers import tcl, tk
from helpers.tcl import TclTestResult

REPO = Path(__file__).resolve().parents[2]
TCL_DIR = REPO / "tests" / "tcl"
_FAILED_RE = re.compile(r"^==== (\S+) .*FAILED\s*$", re.MULTILINE)


def run_tk_file(name: str, env: Optional[Dict[str, str]] = None) -> TclTestResult:
    """Run tests/tcl/<name> under Tk with the harness environment."""
    merged = {"VMDAI_TCL_TM": tcl.http_tm_dir() or ""}
    if env:
        merged.update(env)
    return tk.run_tk_test(str(TCL_DIR / name), env=merged, timeout=120)


def failed_cases(result: TclTestResult) -> Set[str]:
    return set(_FAILED_RE.findall(result.output))


def assert_case(result: TclTestResult, case: str, total: int) -> None:
    """``case`` passed, and all ``total`` cases of the file ran."""
    assert case not in failed_cases(result), result.output
    ran = result.passed + result.failed
    assert ran == total, (
        f"expected {total} tcltest cases, got passed={result.passed} "
        f"failed={result.failed} skipped={result.skipped}\n{result.output}"
    )
```

- [ ] **Step 3: Write the failing tests**

Create `tests/tcl/test_panel.tcl`:

```tcl
# P09-T01: panel.tcl grid assembly (Part B V3, V6).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

test panel-grid_rows {one column: toolbar, hairline, banner slot, transcript, hairline, composer, status bar} -body {
    set w [::harness::fresh_panel]
    set rows {}
    foreach child {tb tbline tx cbline cb sb} {
        lappend rows $child [dict get [grid info $w.$child] -row]
    }
    set banner_hidden [expr {[winfo manager $w.banner] eq ""}]
    grid $w.banner
    set banner_row [dict get [grid info $w.banner] -row]
    grid remove $w.banner
    list $rows [grid rowconfigure $w 3 -weight] $banner_hidden $banner_row \
        [winfo class $::vmdai::panel::text] [string match $w.tx* $::vmdai::panel::text]
} -result {{tb 0 tbline 1 tx 3 cbline 4 cb 5 sb 6} 1 1 2 Text 1}

test panel-minsize_default_geometry {380x420 minimum; 560x780 unless plugin.json holds a sane geometry} -body {
    file delete -force [::vmdai::config::plugin_json_path]
    set w [::harness::fresh_panel]
    set r [list [wm minsize $w] [::vmdai::panel::initial_geometry] [wm title $w] [wm state $w] \
        [wm protocol $w WM_DELETE_WINDOW]]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 700x900+10+20]
    lappend r [::vmdai::panel::initial_geometry]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 200x100+0+0]
    lappend r [::vmdai::panel::initial_geometry]
} -result [list {380 420} 560x780 "ChatVMD \u2014 New chat" withdrawn ::vmdai::panel::withdraw \
    700x900+10+20 560x780]

test panel-withdraw_keeps_request {closing withdraws; the request, its timers and the runtime keep running} -body {
    set w [::harness::fresh_panel]
    set ::harness::busy 1
    ::vmdai::panel::set_busy 1
    set timer [::vmdai::sched::after 60000 {set ::harness::fired 1}]
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 640x800+5+5]
    uplevel #0 [wm protocol $w WM_DELETE_WINDOW]
    set r [list [wm state $w] [winfo exists $w] [::harness::count_calls cancel] \
        [::harness::count_calls runtime_stop] [expr {$timer in [::vmdai::sched::pending]}] \
        [dict get [::vmdai::bridge::state] busy] \
        [dict get [::vmdai::config::load_plugin_settings] geometry]]
    ::vmdai::sched::cancel $timer
    set ::harness::busy 0
    set r
} -result {withdrawn 1 0 0 1 1 640x800+5+5}

test panel-width_classes {narrow < 440 <= regular <= 720 < wide} -body {
    set out {}
    foreach width {300 439 440 560 720 721 900} {
        lappend out [::vmdai::panel::width_class $width]
    }
    set out
} -result {narrow narrow regular regular regular wide wide}

test panel-menu_actions {toolbar and menu actions reach the right modules} -body {
    ::harness::fresh_panel
    proc ::vmdai::tclexport::chat_tcl {} { return "mol new 1hck.pdb\n" }
    set ::harness::clipboard ""
    set ::harness::opened {}
    set ::vmdai::panel::expand_all 0
    ::vmdai::panel::copy_chat_tcl
    ::vmdai::panel::toggle_expand
    set expanded $::vmdai::panel::expand_all
    ::vmdai::panel::collapse_older
    ::vmdai::panel::open_runs_folder
    ::vmdai::panel::quit_runtime
    list $::harness::clipboard $expanded $::vmdai::panel::expand_all \
        [file tail [lindex $::harness::opened end]] [::harness::count_calls runtime_stop] \
        [::vmdai::panel::provider_label openai-compatible] \
        [::vmdai::panel::hostport http://127.0.0.1:11435/v1]
} -result [list "mol new 1hck.pdb\n" 1 0 .vmdai_runs 1 OpenAI-compatible 127.0.0.1:11435]

# Last: sourcing init.tcl re-sources every module, which replaces the fakes.
test panel-start_opens_panel {::vmdai::start opens the panel and returns its path} -body {
    ::harness::fresh_panel
    ::vmdai::panel::dispose
    source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]
    ::harness::stub_bridge
    proc ::vmdai::runtime::ensure {args} { lappend ::harness::bridge_calls [list ensure] }
    proc ::vmdai::bridge::start_session {args} { lappend ::harness::bridge_calls [list start_session] }
    set ::vmdai::panel::headless 1
    set w [::vmdai::start]
    list $w [winfo class $w] [expr {[::harness::count_calls ensure] >= 1}] [wm state $w]
} -result {.vmd_ai Toplevel 1 withdrawn}

cleanupTests
```

Create `tests/test_tk_panel.py`:

```python
"""P09-T01: panel.tcl grid assembly (Part B V3, V6) and the component-target guard."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set

import pytest

from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TOTAL = 6
TARGET_FILES = {"panel": "panel.tcl", "settings": "settings.tcl", "history": "history.tcl"}


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_panel.tcl")


def test_grid_rows(results):
    assert_case(results, "panel-grid_rows", TOTAL)


def test_minsize_default_geometry(results):
    assert_case(results, "panel-minsize_default_geometry", TOTAL)


def test_withdraw_keeps_request(results):
    assert_case(results, "panel-withdraw_keeps_request", TOTAL)


def test_width_classes(results):
    assert_case(results, "panel-width_classes", TOTAL)


def test_menu_actions(results):
    assert_case(results, "panel-menu_actions", TOTAL)


def test_start_opens_panel(results):
    assert_case(results, "panel-start_opens_panel", TOTAL)


def _defined(namespace: str) -> Set[str]:
    """Procs and namespace variables that ``namespace``'s file defines."""
    text = (PLUGIN / TARGET_FILES[namespace]).read_text(encoding="utf-8")
    procs = set(re.findall(r"^\s*proc\s+::vmdai::%s::(\w+)" % namespace, text, re.MULTILINE))
    variables = set(re.findall(r"\bvariable\s+(\w+)", text))
    return procs | variables


def test_component_targets_defined():
    """Every ::vmdai::panel|settings|history name a plugin file calls exists.

    Plan 08's toolbar, banner and status bar call these by name; so do this
    plan's own files. A target file that does not exist yet (settings.tcl
    before P09-T04, history.tcl before P09-T06) is skipped.
    """
    missing = []
    for path in sorted(PLUGIN.glob("*.tcl")):
        text = path.read_text(encoding="utf-8")
        for namespace, name in re.findall(r"(?<!\$)::vmdai::(panel|settings|history)::(\w+)", text):
            if not (PLUGIN / TARGET_FILES[namespace]).exists():
                continue
            if name not in _defined(namespace):
                missing.append(f"{path.name}: ::vmdai::{namespace}::{name}")
    assert sorted(set(missing)) == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_panel.py -q`
Expected: `6 failed, 1 passed` — the tcltest output shows `invalid command name "::vmdai::panel::build"` (panel.tcl does not exist, so the harness skipped it); `test_component_targets_defined` passes because no target file exists yet. (Without a GUI session: `6 skipped, 1 passed`; run from the dev Mac's GUI session.)

- [ ] **Step 5: Write `plugin/panel.tcl`**

Create `plugin/panel.tcl`:

```tcl
# panel.tcl - the ChatVMD window (Part B V3, V5, V6; plan 09).
#
# One grid column: toolbar, hairline, banner slot (hidden), transcript
# (weight 1), hairline, composer bar, status bar. Closing the window only
# withdraws it, so a request in progress keeps running. The panel owns the
# view-model state ::vmdai::panel::vm and is the one place that routes ops:
# `status` ops go to the status bar, everything else to the transcript.

namespace eval ::vmdai::panel {
    variable DEFAULT_GEOMETRY 560x780
    variable MIN_W 380
    variable MIN_H 420
    if {![info exists ::vmdai::panel::win]} { variable win .vmd_ai }
    if {![info exists ::vmdai::panel::text]} { variable text "" }
    if {![info exists ::vmdai::panel::title]} { variable title "New chat" }
    if {![info exists ::vmdai::panel::busy]} { variable busy 0 }
    if {![info exists ::vmdai::panel::stopping]} { variable stopping 0 }
    if {![info exists ::vmdai::panel::nomodel]} { variable nomodel 0 }
    if {![info exists ::vmdai::panel::expand_all]} { variable expand_all 0 }
    if {![info exists ::vmdai::panel::headless]} { variable headless 0 }
    if {![info exists ::vmdai::panel::last_sent]} { variable last_sent "" }
    if {![info exists ::vmdai::panel::rt_info]} { variable rt_info {} }
    if {![info exists ::vmdai::panel::server_host]} { variable server_host "" }
    # The view-model state; ::vmdai::vm::init fills it in build.
    if {![info exists ::vmdai::panel::vm]} { variable vm {} }
}

# ---- geometry ---------------------------------------------------------------

proc ::vmdai::panel::width_class {w} {
    if {$w < 440} { return narrow }
    if {$w > 720} { return wide }
    return regular
}

proc ::vmdai::panel::window_title {} {
    variable title
    return "ChatVMD \u2014 $title"
}

# plugin.json's geometry when it is at least the minimum size, else 560x780.
proc ::vmdai::panel::initial_geometry {} {
    variable DEFAULT_GEOMETRY
    variable MIN_W
    variable MIN_H
    set geom ""
    catch {set geom [dict get [::vmdai::config::load_plugin_settings] geometry]}
    if {[regexp {^(\d+)x(\d+)([+-]-?\d+[+-]-?\d+)?$} $geom -> w h] && $w >= $MIN_W && $h >= $MIN_H} {
        return $geom
    }
    return $DEFAULT_GEOMETRY
}

proc ::vmdai::panel::save_geometry {} {
    variable win
    variable MIN_W
    variable MIN_H
    if {![winfo exists $win]} { return }
    set geom [wm geometry $win]
    # A window that was never mapped reports 1x1; never save that.
    if {![regexp {^(\d+)x(\d+)} $geom -> w h] || $w < $MIN_W || $h < $MIN_H} { return }
    if {[catch {
        set settings [::vmdai::config::load_plugin_settings]
        dict set settings geometry $geom
        ::vmdai::config::save_plugin_settings $settings
    } err]} {
        ::vmdai::config::log "panel: could not save the window geometry: $err"
    }
}

# ---- window -----------------------------------------------------------------

proc ::vmdai::panel::_hairline {w} {
    frame $w -height 1 -borderwidth 0 -highlightthickness 0 \
        -background [::vmdai::theme::c hairline]
    ::vmdai::theme::paint $w -background hairline
    return $w
}

proc ::vmdai::panel::build {{w ""}} {
    variable win
    variable text
    variable expand_all
    variable MIN_W
    variable MIN_H
    if {$w ne ""} { set win $w }
    if {[winfo exists $win]} { return $win }
    ::vmdai::theme::init
    toplevel $win
    wm withdraw $win
    $win configure -background [::vmdai::theme::c chrome]
    wm title $win [window_title]
    wm minsize $win $MIN_W $MIN_H
    wm geometry $win [initial_geometry]
    wm protocol $win WM_DELETE_WINDOW ::vmdai::panel::withdraw
    grid columnconfigure $win 0 -weight 1
    # Created first, so default traversal also starts in the composer (V5 Tab).
    ::vmdai::composer::create $win.cb -onsend ::vmdai::panel::on_send -onstop ::vmdai::panel::on_stop
    ::vmdai::toolbar::create $win.tb
    set text [::vmdai::transcript::create $win.tx]
    ::vmdai::banner::create $win.banner
    ::vmdai::statusbar::create $win.sb
    _hairline $win.tbline
    _hairline $win.cbline
    grid $win.tb     -row 0 -column 0 -sticky ew
    grid $win.tbline -row 1 -column 0 -sticky ew
    grid $win.banner -row 2 -column 0 -sticky ew
    grid remove $win.banner
    grid $win.tx     -row 3 -column 0 -sticky nsew
    grid $win.cbline -row 4 -column 0 -sticky ew
    grid $win.cb     -row 5 -column 0 -sticky ew
    grid $win.sb     -row 6 -column 0 -sticky ew
    grid rowconfigure $win 3 -weight 1
    ::vmdai::vm::init ::vmdai::panel::vm
    catch {set expand_all [string is true -strict [dict get [::vmdai::config::load_plugin_settings] expand_steps]]}
    ::vmdai::transcript::set_expand_all $expand_all
    ::vmdai::toolbar::set_title [set ::vmdai::panel::title]
    _sync_composer
    _update_status
    return $win
}

# Map a window unless the panel runs headless (tests).
proc ::vmdai::panel::present {w} {
    variable headless
    if {$headless} { return }
    wm deiconify $w
    raise $w
}

proc ::vmdai::panel::show {} {
    variable win
    build
    present $win
    return $win
}

# Closing the window: withdraw only. Requests, timers and the runtime go on.
proc ::vmdai::panel::withdraw {} {
    variable win
    if {![winfo exists $win]} { return }
    save_geometry
    wm withdraw $win
}

proc ::vmdai::panel::dispose {} {
    variable win
    variable text
    foreach dialog {.vmd_ai_settings .vmd_ai_history} {
        if {[winfo exists $dialog]} { ::destroy $dialog }
    }
    if {![winfo exists $win]} { return }
    save_geometry
    ::destroy $win
    set text ""
}

proc ::vmdai::panel::set_title {s} {
    variable win
    variable title
    set title $s
    if {![winfo exists $win]} { return }
    wm title $win [window_title]
    ::vmdai::toolbar::set_title $s
}

proc ::vmdai::panel::_title_from {prompt} {
    set line [lindex [split [string trim $prompt] "\n"] 0]
    if {[string length $line] > 60} { set line "[string range $line 0 59]\u2026" }
    return $line
}

# ---- busy state -------------------------------------------------------------

# The bridge is the source of truth for "a request is running".
proc ::vmdai::panel::bridge_busy {} {
    set state [::vmdai::bridge::state]
    return [expr {[dict exists $state busy] && [string is true -strict [dict get $state busy]]}]
}

# Called by the bridge (through ui.tcl's shim) when a request starts or ends.
proc ::vmdai::panel::set_busy {on} {
    variable win
    variable busy
    variable stopping
    set busy [expr {$on ? 1 : 0}]
    if {!$busy} { set stopping 0 }
    if {![winfo exists $win]} { return }
    ::vmdai::toolbar::set_busy $busy
    ::vmdai::statusbar::update [dict create busy $busy]
    _sync_composer
}

proc ::vmdai::panel::_composer_mode {} {
    variable busy
    variable stopping
    variable nomodel
    if {$busy} { return [expr {$stopping ? "stopping" : "busy"}] }
    if {[::vmdai::runtime::state] ne "ready"} { return disabled }
    if {$nomodel} { return nomodel }
    return idle
}

proc ::vmdai::panel::_sync_composer {} {
    variable win
    if {![winfo exists $win]} { return }
    ::vmdai::composer::set_mode [_composer_mode]
}

# ---- ops --------------------------------------------------------------------

proc ::vmdai::panel::render {ops} {
    variable nomodel
    set batch {}
    foreach op $ops {
        switch -- [lindex $op 0] {
            status { _apply_status $op }
            error.card {
                lappend batch $op
                if {[lindex $op 1] eq "NO_MODEL"} {
                    set nomodel 1
                    _sync_composer
                }
            }
            default { lappend batch $op }
        }
    }
    if {[llength $batch]} { ::vmdai::transcript::apply_ops $batch }
}

# {status busy <text> <t0>} or {status idle}
proc ::vmdai::panel::_apply_status {op} {
    if {[lindex $op 1] eq "busy"} {
        ::vmdai::statusbar::update [dict create activity [lindex $op 2] t0 [lindex $op 3]]
    } else {
        ::vmdai::statusbar::update [dict create activity "" t0 ""]
    }
}

# ---- actions (composer, toolbar, ... menu, banner) -----------------------------

proc ::vmdai::panel::on_send {args} {
    variable title
    variable last_sent
    if {[llength $args]} { set prompt [lindex $args 0] } else { set prompt [::vmdai::composer::get_text] }
    set prompt [string trim $prompt]
    if {$prompt eq ""} { return }
    set last_sent $prompt
    ::vmdai::composer::push_history $prompt
    ::vmdai::composer::set_text ""
    if {$title eq "New chat"} { set_title [_title_from $prompt] }
    ::vmdai::bridge::send $prompt
}

# Idempotent: Esc on the composer can reach both the composer's own Stop
# binding and the panel's, and Stop shows "Stopping..." until the request ends.
proc ::vmdai::panel::on_stop {args} {
    variable stopping
    if {$stopping || ![bridge_busy]} { return }
    set stopping 1
    ::vmdai::bridge::cancel
    render [::vmdai::vm::stop_requested ::vmdai::panel::vm]
    _sync_composer
}

proc ::vmdai::panel::new_chat {} {
    if {[bridge_busy]} { return }
    ::vmdai::bridge::new_chat
}

proc ::vmdai::panel::open_settings {{tab model} {prefill {}}} {
    return [::vmdai::settings::open $tab $prefill]
}

proc ::vmdai::panel::open_history {} {
    return [::vmdai::history::open]
}

proc ::vmdai::panel::choose_folder {} {
    variable win
    set dir [tk_chooseDirectory -parent $win -title "Project folder" -initialdir [pwd] -mustexist 1]
    if {$dir eq ""} { return "" }
    ::vmdai::bridge::apply_workdir $dir
    _update_status
    return $dir
}

proc ::vmdai::panel::toggle_expand {} {
    variable expand_all
    set_expand_all [expr {!$expand_all}]
}

proc ::vmdai::panel::set_expand_all {on} {
    variable win
    variable expand_all
    set expand_all [expr {$on ? 1 : 0}]
    if {[winfo exists $win]} { ::vmdai::transcript::set_expand_all $expand_all }
}

proc ::vmdai::panel::collapse_older {} {
    set_expand_all 0
}

proc ::vmdai::panel::copy_chat_tcl {} {
    _set_clipboard [::vmdai::tclexport::chat_tcl]
}

proc ::vmdai::panel::save_chat_tcl {} {
    variable win
    set path [tk_getSaveFile -parent $win -title "Save chat .tcl" -defaultextension .tcl \
        -initialfile chat.tcl -initialdir [pwd]]
    if {$path eq ""} { return "" }
    ::vmdai::tclexport::save $path [::vmdai::tclexport::chat_tcl]
    return $path
}

proc ::vmdai::panel::open_runs_folder {} {
    open_path [file join [pwd] .vmdai_runs]
}

proc ::vmdai::panel::open_log {} {
    open_path [::vmdai::config::log_path]
}

proc ::vmdai::panel::quit_runtime {} {
    ::vmdai::runtime::stop
}

proc ::vmdai::panel::open_path {path} {
    if {[tk windowingsystem] eq "aqua"} { set opener open } else { set opener xdg-open }
    if {[catch {exec $opener $path &} err]} {
        ::vmdai::config::log "panel: could not open $path: $err"
    }
}

proc ::vmdai::panel::_set_clipboard {s} {
    variable win
    clipboard clear -displayof $win
    clipboard append -displayof $win -- $s
}

# ---- status bar data --------------------------------------------------------

proc ::vmdai::panel::provider_label {id} {
    switch -- $id {
        ollama { return Ollama }
        openai-compatible { return OpenAI-compatible }
        anthropic-direct { return Anthropic }
        openrouter { return OpenRouter }
        mock { return Mock }
    }
    return $id
}

# host:port of a URL (never the word "tunnel": Part B V1 required fixes).
proc ::vmdai::panel::hostport {url} {
    if {[regexp {^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]+)} $url -> hp]} { return $hp }
    return $url
}

proc ::vmdai::panel::run_count {} {
    return [llength [glob -nocomplain -types d -directory [file join [pwd] .vmdai_runs] *]]
}

proc ::vmdai::panel::_update_status {} {
    variable win
    variable rt_info
    variable server_host
    if {![winfo exists $win]} { return }
    set provider ""
    set model ""
    catch {set provider [dict get $rt_info provider]}
    catch {set model [dict get $rt_info model]}
    if {$model eq "null"} { set model "" }
    ::vmdai::statusbar::update [dict create connection [::vmdai::runtime::state] \
        provider [provider_label $provider] model $model host $server_host \
        folder [pwd] runs [run_count]]
}

# Called after Settings saves. P09-T07 replaces it with the version that
# re-reads runtime.info and profiles.list before updating the status bar.
proc ::vmdai::panel::refresh_info {} {
    _update_status
}
```

- [ ] **Step 6: Make `init.tcl` source the M2 modules and open the panel**

In `plugin/init.tcl` (anchors from Task 0 Step 6):

1. After the line that sources `executor.tcl` and before the one that sources `ui.tcl`, source the ten Tk modules, in this order, only when Tk is loaded — plan 06's tclsh bridge driver (`tests/tcl/driver.tcl`, no Tk) keeps sourcing the plugin:

```tcl
if {[info commands ::winfo] ne ""} {
    foreach ::vmdai::_m {theme viewmodel transcript viewer composer statusbar banner toolbar tclexport panel} {
        source [file join $::vmdai::config::plugin_dir $::vmdai::_m.tcl]
    }
    unset ::vmdai::_m
}
```

   (Use the directory variable init.tcl's neighbouring `source` lines use if it is not `::vmdai::config::plugin_dir`.)
2. In `proc ::vmdai::start`, replace the call that opens the M1 panel (`::vmdai::ui::show_panel`) with `set w [::vmdai::panel::show]`, keep the rest of the body (runtime launch/attach), and end the proc with `return $w`.
3. In `proc ::vmdai::stop`, replace the line that destroys the M1 window (it names `::vmdai::ui::win`) with `if {[info commands ::vmdai::panel::dispose] ne ""} { ::vmdai::panel::dispose }`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: `7 passed` from `test_tk_panel.py` plus every lint test passing (no banned construct in `plugin/panel.tcl`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+7 passed` (plus the unchanged skips), 0 failed.

- [ ] **Step 8: Commit**

```bash
git add plugin/panel.tcl plugin/init.tcl tests/tcl/panel_harness.tcl tests/helpers/tk_cases.py \
        tests/tcl/test_panel.tcl tests/test_tk_panel.py
git commit -m "feat(plugin): panel.tcl grid assembly; ::vmdai::start opens the panel (P09-T01)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T02: Empty state

**Files:**
- Modify: `plugin/transcript.tcl` (created by P08-T05; append a new section at the end of the file)
- Create: `tests/tcl/test_empty_state.tcl`
- Test: `tests/test_tk_empty_state.py`

**Interfaces:**
- Consumes: runtime.info first_run (P03-T09) — `first_run{servers:[{base_url, version, models[]}]}` with `models` a list of tag names; `::vmdai::panel::provider_label`, `hostport`, `open_settings ?tab? ?prefill?`, `choose_folder`, `text` (P09-T01); `::vmdai::composer::set_text`, `focus` (P08-T08); `::vmdai::sched::after_idle`, `cancel` (P06-T02); theme tokens and fonts (P08-T04).
- Produces: `::vmdai::transcript::show_empty_state info ?t?` (`t` defaults to `::vmdai::panel::text`). Also `::vmdai::transcript::hide_empty_state ?t?`, `empty_state_shown ?t?`, `layout_empty_state width ?t? -> pair|column`, `empty_rows info -> list of {state name text action_label action_cmd}`, `example_clicked index -> prompt`, `_key_hints`, and the constants `EMPTY_TITLE`, `EMPTY_LEAD`, `TRUST_TEXT`, `EXAMPLES`. `info` is a runtime.info result extended by the panel with `connected` (bool), `endpoint` (host:port of the runtime), `folder` and `runs`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_empty_state.tcl`:

```tcl
# P09-T02: the empty state (Part B V4 "Empty state").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop
::harness::stub_settings_open

set ::INFO [dict create connected 1 endpoint 127.0.0.1:8765 provider ollama model qwen3.8:27b \
    agent_loop true vision true tools {run_vmd_command capture_vmd_snapshot} \
    folder /tmp/proj runs 12 first_run [dict create servers {}]]

test empty-cards_2x2_or_column {four cards: 2x2 from 520 px, one column below} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set cards $t.empty.col.cards
    set r [list [::vmdai::transcript::layout_empty_state 560 $t]]
    foreach i {0 1 2 3} {
        lappend r [dict get [grid info $cards.c$i] -row] [dict get [grid info $cards.c$i] -column]
    }
    lappend r [::vmdai::transcript::layout_empty_state 480 $t]
    foreach i {0 1 2 3} {
        lappend r [dict get [grid info $cards.c$i] -row] [dict get [grid info $cards.c$i] -column]
    }
    lappend r [$cards.c0.title cget -text] [$cards.c3.title cget -text]
} -result {pair 0 0 0 1 1 0 1 1 column 0 0 1 0 2 0 3 0 {Load & style} {Trajectory RMSD}}

test empty-card_fills_composer_never_sends {a card fills the composer and never sends} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    ::harness::fire $t.empty.col.cards.c1.desc <ButtonRelease-1>
    ::harness::settle
    list [::vmdai::composer::get_text] [::harness::count_calls send] [::fake::count chat.send] \
        [winfo exists $t.empty]
} -result [list "Show residues within 5 \u00c5 of the ligand as Licorice" 0 0 1]

test empty-ready_group_first_run_servers {no model yet: the probe's servers are listed with Use...} -body {
    set info [dict create connected 1 endpoint 127.0.0.1:8765 provider "" model "" agent_loop false \
        folder /tmp/proj runs 1 first_run [dict create servers [list [dict create \
            base_url http://127.0.0.1:11435 version 0.12.3 models {qwen3.8:27b llama3.2:3b}]]]]
    set rows [::vmdai::transcript::empty_rows $info]
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $info $t
    set ::harness::settings_opened {}
    ::harness::fire [::harness::label_with_text $t.empty "Use\u2026"] <ButtonRelease-1>
    ::harness::settle
    list [lindex $rows 0 2] [lindex $rows 1 2] [lindex $rows 1 3] [lindex $rows 2 2] [lindex $rows 3 2] \
        [lindex $::harness::settings_opened end]
} -result [list "running \u00b7 127.0.0.1:8765" "No model configured" "Set up\u2026" \
    "Found Ollama 0.12.3 at 127.0.0.1:11435 \u00b7 2 models" "/tmp/proj \u00b7 1 run recorded" \
    [list model [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b]]]

test empty-trust_row {the trust notice, title and key hints are shown} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set texts [::harness::texts_under $t.empty]
    set rows [::vmdai::transcript::empty_rows $::INFO]
    list [expr {$::vmdai::transcript::TRUST_TEXT in $texts}] [lindex $rows end 0] \
        [expr {"What should VMD do?" in $texts}] [expr {[::vmdai::transcript::_key_hints] in $texts}] \
        [lindex $rows 1 2]
} -result [list 1 warn 1 1 "Ollama \u00b7 qwen3.8:27b \u00b7 tools, vision"]

test empty-hide {hide_empty_state removes the overlay} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::show_empty_state $::INFO $t
    set before [::vmdai::transcript::empty_state_shown $t]
    ::vmdai::transcript::hide_empty_state $t
    list $before [::vmdai::transcript::empty_state_shown $t] [winfo exists $t.empty]
} -result {1 0 0}

cleanupTests
```

Create `tests/test_tk_empty_state.py`:

```python
"""P09-T02: the empty state (Part B V4)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 5


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_empty_state.tcl")


def test_cards_2x2_or_column(results):
    assert_case(results, "empty-cards_2x2_or_column", TOTAL)


def test_card_fills_composer_never_sends(results):
    assert_case(results, "empty-card_fills_composer_never_sends", TOTAL)


def test_ready_group_first_run_servers(results):
    assert_case(results, "empty-ready_group_first_run_servers", TOTAL)


def test_trust_row(results):
    assert_case(results, "empty-trust_row", TOTAL)


def test_hide(results):
    assert_case(results, "empty-hide", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_empty_state.py -q`
Expected: `5 failed`; the tcltest output shows `invalid command name "::vmdai::transcript::show_empty_state"`.

- [ ] **Step 3: Append the empty state to `plugin/transcript.tcl`**

Append to the end of `plugin/transcript.tcl`:

```tcl
# ===========================================================================
# Empty state (Part B V4 "Empty state"; P09-T02).
#
# A frame placed over the transcript text: the mark, the title, a lead line,
# four example cards (2x2 from 520 px, else one column), the bordered Ready
# group (Runtime, Model, the first-run servers, Folder, the trust notice) and
# the key hints. It never inserts into the text, so the op goldens and the
# dump are unaffected; the panel removes it before the first op it applies.
# ===========================================================================
namespace eval ::vmdai::transcript {
    variable EMPTY_TITLE "What should VMD do?"
    variable EMPTY_LEAD "Describe a view, a measurement or an analysis. ChatVMD writes the Tcl, runs it in this VMD session and checks the result."
    variable TRUST_TEXT "Model-written Tcl runs unsandboxed in this VMD session. Only load files you trust."
    variable EXAMPLES [list \
        [list load    "Load & style"      "Load PDB 1HCK as NewCartoon colored by secondary structure"] \
        [list pocket  "Binding pocket"    "Show residues within 5 \u00c5 of the ligand as Licorice"] \
        [list bfactor "Color by B-factor" "Color the protein by B-factor and render a snapshot"] \
        [list rmsd    "Trajectory RMSD"   "Measure the backbone RMSD over the loaded trajectory"]]
    variable PAIR_MIN_WIDTH 520
    if {![info exists ::vmdai::transcript::empty_host]} { variable empty_host "" }
    if {![info exists ::vmdai::transcript::empty_after]} { variable empty_after "" }
}

proc ::vmdai::transcript::_empty_get {d key default} {
    if {![dict exists $d $key]} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::transcript::_empty_tilde {path} {
    set home ""
    catch {set home [file normalize ~]}
    if {$home ne "" && [string first $home $path] == 0} {
        return "~[string range $path [string length $home] end]"
    }
    return $path
}

proc ::vmdai::transcript::_key_hints {} {
    if {[tk windowingsystem] eq "aqua"} {
        return "\u23ce send \u00b7 \u21e7\u23ce newline \u00b7 \u2191 last prompt \u00b7 esc stop"
    }
    return "Return send \u00b7 Shift-Return newline \u00b7 Up last prompt \u00b7 Esc stop"
}

# The Ready group's rows: {state name text action_label action_cmd}, where
# state is ok|off|info|warn.
proc ::vmdai::transcript::empty_rows {info} {
    variable TRUST_TEXT
    set rows {}
    set endpoint [_empty_get $info endpoint ""]
    if {[string is true -strict [_empty_get $info connected false]]} {
        set text [expr {$endpoint eq "" ? "running" : "running \u00b7 $endpoint"}]
        lappend rows [list ok Runtime $text "" ""]
    } else {
        lappend rows [list off Runtime "not connected" "" ""]
    }
    set model [_empty_get $info model ""]
    set settings_cmd [list ::vmdai::panel::open_settings model]
    if {$model ne "" && [string is true -strict [_empty_get $info agent_loop false]]} {
        set text "[::vmdai::panel::provider_label [_empty_get $info provider ""]] \u00b7 $model"
        set caps {}
        if {[llength [_empty_get $info tools {}]]} { lappend caps tools }
        if {[string is true -strict [_empty_get $info vision false]]} { lappend caps vision }
        if {[llength $caps]} { append text " \u00b7 [join $caps {, }]" }
        lappend rows [list ok Model $text Change $settings_cmd]
    } else {
        lappend rows [list off Model "No model configured" "Set up\u2026" $settings_cmd]
    }
    set servers {}
    catch {set servers [dict get $info first_run servers]}
    foreach server $servers {
        set url [_empty_get $server base_url ""]
        set models [_empty_get $server models {}]
        set n [llength $models]
        set text "Found Ollama [_empty_get $server version ?] at [::vmdai::panel::hostport $url] \u00b7 $n model[expr {$n == 1 ? "" : "s"}]"
        set prefill [dict create provider ollama base_url $url model [lindex $models 0]]
        lappend rows [list info "" $text "Use\u2026" [list ::vmdai::panel::open_settings model $prefill]]
    }
    set folder [_empty_get $info folder ""]
    if {$folder ne ""} {
        set runs [_empty_get $info runs 0]
        set text "[_empty_tilde $folder] \u00b7 $runs run[expr {$runs == 1 ? "" : "s"}] recorded"
        lappend rows [list ok Folder $text Change [list ::vmdai::panel::choose_folder]]
    }
    lappend rows [list warn "" $TRUST_TEXT "" ""]
    return $rows
}

proc ::vmdai::transcript::_empty_path {t} {
    return $t.empty
}

proc ::vmdai::transcript::show_empty_state {info {t ""}} {
    variable empty_host
    variable EMPTY_TITLE
    variable EMPTY_LEAD
    variable EXAMPLES
    if {$t eq ""} { set t $::vmdai::panel::text }
    if {$t eq "" || ![winfo exists $t]} { return "" }
    hide_empty_state $t
    set empty_host $t
    set C ::vmdai::theme::c
    set bg [$C surface]
    set e [_empty_path $t]
    frame $e -background $bg -borderwidth 0 -highlightthickness 0
    frame $e.col -background $bg
    grid $e.col -row 0 -column 0
    grid rowconfigure $e 0 -weight 1
    grid columnconfigure $e 0 -weight 1
    set col $e.col
    _empty_mark $col.mark
    label $col.title -text $EMPTY_TITLE -font ChatH1 -foreground [$C text] -background $bg
    label $col.lead -text $EMPTY_LEAD -font ChatBody -foreground [$C muted] -background $bg \
        -justify center -wraplength 420
    frame $col.cards -background $bg
    set i 0
    foreach example $EXAMPLES {
        lassign $example key title prompt
        _empty_card $col.cards.c$i $i $key $title $prompt
        incr i
    }
    frame $col.ready -background $bg -highlightthickness 1 \
        -highlightbackground [$C hairline] -highlightcolor [$C hairline]
    _empty_ready $col.ready $info
    label $col.keys -text [_key_hints] -font ChatMeta -foreground [$C muted] -background $bg
    grid $col.mark  -row 0 -column 0 -pady {0 6}
    grid $col.title -row 1 -column 0
    grid $col.lead  -row 2 -column 0 -pady {4 16}
    grid $col.cards -row 3 -column 0 -sticky ew
    grid $col.ready -row 4 -column 0 -sticky ew -pady {16 0}
    grid $col.keys  -row 5 -column 0 -pady {12 0}
    place $e -in $t -x 0 -y 0 -relwidth 1 -relheight 1
    bind $e <Configure> [list ::vmdai::transcript::_empty_configure $t %w]
    layout_empty_state [winfo width $t] $t
    return $e
}

proc ::vmdai::transcript::hide_empty_state {{t ""}} {
    variable empty_host
    variable empty_after
    if {$t eq ""} { set t $empty_host }
    if {$t eq ""} { return }
    if {$empty_after ne ""} {
        ::vmdai::sched::cancel $empty_after
        set empty_after ""
    }
    set e [_empty_path $t]
    if {[winfo exists $e]} { ::destroy $e }
}

proc ::vmdai::transcript::empty_state_shown {{t ""}} {
    variable empty_host
    if {$t eq ""} { set t $empty_host }
    return [expr {$t ne "" && [winfo exists [_empty_path $t]]}]
}

# Two columns from PAIR_MIN_WIDTH px of transcript width, else one.
proc ::vmdai::transcript::layout_empty_state {width {t ""}} {
    variable PAIR_MIN_WIDTH
    if {$t eq ""} { set t $::vmdai::panel::text }
    set cards [_empty_path $t].col.cards
    if {![winfo exists $cards]} { return "" }
    set pair [expr {$width >= $PAIR_MIN_WIDTH}]
    set inner [expr {$width > 96 ? $width - 64 : 360}]
    set card_w [expr {$pair ? ($inner - 12) / 2 : $inner}]
    if {$card_w > 320} { set card_w 320 }
    if {$card_w < 160} { set card_w 160 }
    for {set i 0} {$i < 4} {incr i} {
        set c $cards.c$i
        if {$pair} {
            grid $c -row [expr {$i / 2}] -column [expr {$i % 2}] -sticky nsew -padx 6 -pady 6
        } else {
            grid $c -row $i -column 0 -sticky ew -padx 6 -pady 6
        }
        $c.desc configure -wraplength [expr {$card_w - 48}]
    }
    grid columnconfigure $cards 0 -weight 1 -uniform card
    if {$pair} {
        grid columnconfigure $cards 1 -weight 1 -uniform card
    } else {
        grid columnconfigure $cards 1 -weight 0 -uniform ""
    }
    [_empty_path $t].col.lead configure -wraplength [expr {$inner < 480 ? $inner : 480}]
    return [expr {$pair ? "pair" : "column"}]
}

proc ::vmdai::transcript::_empty_configure {t width} {
    variable empty_after
    if {$empty_after ne ""} { ::vmdai::sched::cancel $empty_after }
    set empty_after [::vmdai::sched::after_idle [list ::vmdai::transcript::_empty_relayout $t $width]]
}

proc ::vmdai::transcript::_empty_relayout {t width} {
    variable empty_after
    set empty_after ""
    layout_empty_state $width $t
}

proc ::vmdai::transcript::example_clicked {index} {
    variable EXAMPLES
    set prompt [lindex [lindex $EXAMPLES $index] 2]
    ::vmdai::composer::set_text $prompt
    ::vmdai::composer::focus
    return $prompt
}

proc ::vmdai::transcript::_empty_mark {c} {
    set C ::vmdai::theme::c
    canvas $c -width 64 -height 46 -highlightthickness 0 -borderwidth 0 -background [$C surface]
    $c create line 16 30 38 14 50 34 -width 3 -fill [$C faint] -capstyle round -joinstyle round
    $c create oval 8 22 24 38 -fill [$C accent] -outline ""
    $c create oval 29 5 47 23 -fill [$C accent] -outline ""
    $c create oval 43 27 57 41 -fill [$C accent] -outline ""
}

proc ::vmdai::transcript::_empty_icon {c key color} {
    switch -- $key {
        load {
            foreach y {6 11 16} {
                $c create line 4 $y 18 $y -fill $color -width 2 -capstyle round
            }
        }
        pocket {
            $c create oval 3 3 19 19 -outline $color -width 2
            $c create oval 9 9 13 13 -fill $color -outline $color
        }
        bfactor {
            set x 3
            foreach h {6 10 14} {
                $c create rectangle $x [expr {19 - $h}] [expr {$x + 4}] 19 -fill $color -outline ""
                incr x 6
            }
        }
        rmsd {
            $c create line 3 17 8 10 12 13 19 4 -fill $color -width 2 -capstyle round -joinstyle round
        }
    }
}

proc ::vmdai::transcript::_empty_card {c index key title prompt} {
    set C ::vmdai::theme::c
    set bg [$C surface]
    set hairline [$C hairline]
    set accent [$C accent]
    frame $c -background $bg -highlightthickness 1 -highlightbackground $hairline \
        -highlightcolor $hairline -cursor hand2
    canvas $c.icon -width 22 -height 22 -highlightthickness 0 -borderwidth 0 -background $bg
    _empty_icon $c.icon $key $accent
    label $c.title -text $title -font ChatBodyBold -foreground [$C text] -background $bg -anchor w
    label $c.desc -text $prompt -font ChatMeta -foreground [$C muted] -background $bg \
        -anchor w -justify left -wraplength 220
    grid $c.icon  -row 0 -column 0 -rowspan 2 -sticky n -padx {10 8} -pady 10
    grid $c.title -row 0 -column 1 -sticky w -pady {9 0} -padx {0 10}
    grid $c.desc  -row 1 -column 1 -sticky w -pady {1 10} -padx {0 10}
    grid columnconfigure $c 1 -weight 1
    foreach w [list $c $c.icon $c.title $c.desc] {
        bind $w <ButtonRelease-1> [list ::vmdai::transcript::example_clicked $index]
        bind $w <Enter> [list $c configure -highlightbackground $accent]
        bind $w <Leave> [list $c configure -highlightbackground $hairline]
    }
}

proc ::vmdai::transcript::_empty_ready {f info} {
    set C ::vmdai::theme::c
    set bg [$C surface]
    set r 0
    set i 0
    foreach row [empty_rows $info] {
        lassign $row state name text action cmd
        if {$i > 0} {
            frame $f.sep$i -height 1 -background [$C hairline]
            grid $f.sep$i -row $r -column 0 -columnspan 4 -sticky ew -padx {34 0}
            incr r
        }
        switch -- $state {
            ok      { set glyph "\u2713"; set colour [$C ok] }
            warn    { set glyph "!";      set colour [$C warn] }
            default { set glyph "\u2022"; set colour [$C muted] }
        }
        label $f.g$i -text $glyph -font ChatMetaBold -foreground $colour -background $bg -width 2
        label $f.n$i -text $name -font ChatBody -foreground [$C text] -background $bg -anchor w
        label $f.v$i -text $text -font ChatMeta -foreground [$C muted] -background $bg \
            -anchor w -justify left -wraplength 300
        grid $f.g$i -row $r -column 0 -sticky nw -padx {10 4} -pady 6
        grid $f.n$i -row $r -column 1 -sticky nw -pady 6
        grid $f.v$i -row $r -column 2 -sticky nw -padx {8 8} -pady 6
        if {$action ne ""} {
            label $f.a$i -text $action -font ChatMeta -foreground [$C accent] -background $bg -cursor hand2
            bind $f.a$i <ButtonRelease-1> $cmd
            grid $f.a$i -row $r -column 3 -sticky ne -padx {0 10} -pady 6
        }
        incr r
        incr i
    }
    grid columnconfigure $f 2 -weight 1
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_empty_state.py tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: all pass (`5 passed` from the empty-state file, `7 passed` from the panel file, the lint tests pass).

Run: `python -m pytest tests -q -k "transcript or viewmodel" 2>&1 | tail -2`
Expected: plan 08's transcript and view-model tests still pass (the overlay never touches the text).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+12 passed`, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add plugin/transcript.tcl tests/tcl/test_empty_state.tcl tests/test_tk_empty_state.py
git commit -m "feat(plugin): empty state with example cards, Ready group and trust row (P09-T02)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T03: Keyboard map (V5)

**Files:**
- Modify: `plugin/panel.tcl` (append the keyboard section; add one call at the end of `::vmdai::panel::build`)
- Modify: `plugin/composer.tcl` (created by P08-T08; replace its `push_history` proc — Task 0 Step 6 printed it — and append the recall section)
- Create: `tests/tcl/test_keymap.tcl`
- Test: `tests/test_tk_keymap.py`

**Interfaces:**
- Consumes: composer, transcript (P08) — `::vmdai::composer::get_text/set_text/focus`, `::vmdai::transcript::apply_ops`, `::vmdai::vm::init/apply`; `::vmdai::panel::on_stop`, `toggle_expand`, `new_chat`, `open_settings`, `text`, `win`, `bridge_busy`, `_set_clipboard` (P09-T01).
- Produces: `::vmdai::panel::bind_keys`. Also `::vmdai::panel::mod_key -> Command|Control`, `composer_text -> path`, `focus_ring -> list`, `focus_next w ?step? -> path`, `focus_prev w -> path`, `copy_selection -> string`, `scroll_transcript page|top|bottom ?n?`, `on_escape -> 0|1`; `::vmdai::composer::push_history s` (replaced: keeps the newest 50), `clear_history`, `recall_prev -> 0|1`, `recall_next -> 0|1`, `on_up w -> 0|1`, `on_down w -> 0|1`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_keymap.tcl`:

```tcl
# P09-T03: keyboard and interaction map (Part B V5).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

test keys-esc_stops {Esc stops a running request and does nothing when idle} -body {
    ::harness::fresh_panel
    set ct [::vmdai::panel::composer_text]
    ::harness::fire $ct <Escape>
    set idle [::harness::count_calls cancel]
    set ::harness::busy 1
    ::vmdai::panel::set_busy 1
    ::harness::fire $ct <Escape>
    set busy [::harness::count_calls cancel]
    set stopping $::vmdai::panel::stopping
    set ::harness::busy 0
    ::vmdai::panel::set_busy 0
    list $idle $busy $stopping
} -result {0 1 1}

test keys-mod_e_toggles {Mod-E toggles the global expand flag from anywhere in the panel} -body {
    ::harness::fresh_panel
    ::vmdai::panel::set_expand_all 0
    set mod [::vmdai::panel::mod_key]
    ::harness::fire [::vmdai::panel::composer_text] <$mod-e>
    set first $::vmdai::panel::expand_all
    ::harness::fire $::vmdai::panel::text <$mod-e>
    list $first $::vmdai::panel::expand_all
} -result {1 0}

test keys-copy_displaychars {<<Copy>> copies display chars: elided text skipped, tabs as two spaces} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::vm::init ::harness::vmstate
    set ev [dict create role user type message text "alpha\tbeta gamma" \
        metadata [dict create request_id req_1]]
    ::vmdai::transcript::apply_ops [::vmdai::vm::apply ::harness::vmstate $ev]
    set at [$t search -exact beta 1.0]
    $t tag configure hidden_for_test -elide 1
    $t tag add hidden_for_test $at "$at + 5 chars"
    $t tag add sel 1.0 end
    set ::harness::clipboard ""
    ::harness::fire $t <<Copy>>
    ::harness::settle
    list [string match "*alpha  gamma*" $::harness::clipboard] \
         [string match "*beta*" $::harness::clipboard] \
         [string match "*\t*" $::harness::clipboard]
} -result {1 0 0}

test keys-up_down_history {Up/Down on the first/last line walk this chat's prompts; Down past the newest restores the draft} -body {
    ::harness::fresh_panel
    ::vmdai::composer::clear_history
    ::vmdai::composer::push_history "one"
    ::vmdai::composer::push_history "two"
    ::vmdai::composer::set_text "draft"
    set ct [::vmdai::panel::composer_text]
    set seen {}
    foreach key {Up Up Up Down Down} {
        $ct mark set insert [expr {$key eq "Up" ? "1.0" : "end -1c"}]
        ::harness::fire $ct <$key>
        lappend seen [::vmdai::composer::get_text]
    }
    for {set i 0} {$i < 60} {incr i} { ::vmdai::composer::push_history "p$i" }
    lappend seen [llength $::vmdai::composer::recall] [lindex $::vmdai::composer::recall 0]
} -result {two one one two draft 50 p10}

test keys-tab_order {Tab: composer -> Send -> toolbar -> transcript, then back to the composer} -body {
    set w [::harness::fresh_panel]
    ::vmdai::panel::set_busy 0
    ::vmdai::composer::set_text "x"
    set ring [::vmdai::panel::focus_ring]
    set first [lindex $ring 0]
    list [winfo class $first] [string match $w.cb* $first] \
        [winfo class [lindex $ring 1]] [string match $w.cb* [lindex $ring 1]] \
        [expr {[llength [lsearch -all -glob $ring $w.tb*]] >= 1}] \
        [expr {[lindex $ring end] eq $::vmdai::panel::text}] \
        [expr {[::vmdai::panel::focus_next [lindex $ring end]] eq $first}] \
        [expr {[::vmdai::panel::focus_prev $first] eq [lindex $ring end]}] \
        [expr {[bind $first <Tab>] ne ""}]
} -result {Text 1 TButton 1 1 1 1 1 1}

cleanupTests
```

Create `tests/test_tk_keymap.py`:

```python
"""P09-T03: keyboard and interaction map (Part B V5)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 5


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_keymap.tcl")


def test_esc_stops(results):
    assert_case(results, "keys-esc_stops", TOTAL)


def test_mod_e_toggles(results):
    assert_case(results, "keys-mod_e_toggles", TOTAL)


def test_copy_displaychars(results):
    assert_case(results, "keys-copy_displaychars", TOTAL)


def test_up_down_history(results):
    assert_case(results, "keys-up_down_history", TOTAL)


def test_tab_order(results):
    assert_case(results, "keys-tab_order", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_keymap.py -q`
Expected: `5 failed`; the output shows `invalid command name "::vmdai::panel::composer_text"` (and `"::vmdai::composer::clear_history"`).

- [ ] **Step 3: Replace `push_history` and add prompt recall in `plugin/composer.tcl`**

Delete plan 08's `proc ::vmdai::composer::push_history` (and the namespace variable it stored prompts in, if no other composer proc reads it), then append:

```tcl
# ===========================================================================
# Prompt recall (Part B V5; P09-T03).
#
# Up on the first display line shows the previous prompt of this chat, Down
# on the last display line the next one; Down past the newest brings the
# draft back. The newest 50 prompts are kept; New chat clears them.
# ===========================================================================
namespace eval ::vmdai::composer {
    variable RECALL_MAX 50
    if {![info exists ::vmdai::composer::recall]} { variable recall {} }
    if {![info exists ::vmdai::composer::recall_pos]} { variable recall_pos -1 }
    if {![info exists ::vmdai::composer::recall_draft]} { variable recall_draft "" }
}

proc ::vmdai::composer::push_history {s} {
    variable recall
    variable recall_pos
    variable RECALL_MAX
    set s [string trim $s]
    if {$s eq ""} { return }
    if {[lindex $recall end] ne $s} { lappend recall $s }
    if {[llength $recall] > $RECALL_MAX} {
        set recall [lrange $recall end-[expr {$RECALL_MAX - 1}] end]
    }
    set recall_pos -1
}

proc ::vmdai::composer::clear_history {} {
    variable recall
    variable recall_pos
    variable recall_draft
    set recall {}
    set recall_pos -1
    set recall_draft ""
}

proc ::vmdai::composer::recall_prev {} {
    variable recall
    variable recall_pos
    variable recall_draft
    if {![llength $recall]} { return 0 }
    if {$recall_pos < 0} {
        set recall_draft [get_text]
        set recall_pos [llength $recall]
    }
    # Already at the oldest prompt: keep it and swallow the key.
    if {$recall_pos == 0} { return 1 }
    incr recall_pos -1
    set_text [lindex $recall $recall_pos]
    return 1
}

proc ::vmdai::composer::recall_next {} {
    variable recall
    variable recall_pos
    variable recall_draft
    if {$recall_pos < 0} { return 0 }
    incr recall_pos
    if {$recall_pos >= [llength $recall]} {
        set recall_pos -1
        set_text $recall_draft
        return 1
    }
    set_text [lindex $recall $recall_pos]
    return 1
}

# Bound to <Up>/<Down> on the input by ::vmdai::panel::bind_keys; returning 1
# makes the binding `break`, so the text class binding does not move the caret.
proc ::vmdai::composer::on_up {w} {
    set n [$w count -displaylines 1.0 insert]
    if {$n ne "" && $n > 0} { return 0 }
    return [recall_prev]
}

proc ::vmdai::composer::on_down {w} {
    set n [$w count -displaylines insert "end -1c"]
    if {$n ne "" && $n > 0} { return 0 }
    return [recall_next]
}
```

- [ ] **Step 4: Append the keyboard map to `plugin/panel.tcl`**

Append to `plugin/panel.tcl`:

```tcl
# ---- keyboard map (Part B V5; P09-T03) ----------------------------------------

# Mod means Command on aqua and Control elsewhere.
proc ::vmdai::panel::mod_key {} {
    if {[tk windowingsystem] eq "aqua"} { return Command }
    return Control
}

proc ::vmdai::panel::_first_of_class {w cls} {
    set queue [list $w]
    while {[llength $queue]} {
        set queue [lassign $queue current]
        foreach child [winfo children $current] {
            if {[winfo class $child] eq $cls} { return $child }
            lappend queue $child
        }
    }
    return ""
}

# The composer's input (plan 08 builds it as the first Text under $win.cb).
proc ::vmdai::panel::composer_text {} {
    variable win
    return [_first_of_class $win.cb Text]
}

# Focusable, managed descendants of w in stacking order. A disabled ttk
# button (Send with an empty composer) is skipped, as Tk's traversal does.
proc ::vmdai::panel::_focusables {w} {
    set out {}
    foreach child [winfo children $w] {
        if {[winfo manager $child] eq ""} { continue }
        set takefocus ""
        catch {set takefocus [$child cget -takefocus]}
        set cls [winfo class $child]
        set candidate [expr {$takefocus eq "1" || ($takefocus in {"" ttk::takefocus}
            && $cls in {Text TButton TEntry TCombobox TCheckbutton Button Entry})}]
        if {$candidate && ![catch {$child instate disabled} disabled] && $disabled} {
            set candidate 0
        }
        if {$candidate} { lappend out $child }
        set out [concat $out [_focusables $child]]
    }
    return $out
}

# V5 Tab order: composer -> Send/Stop -> toolbar -> transcript.
proc ::vmdai::panel::focus_ring {} {
    variable win
    variable text
    set ring [concat [_focusables $win.cb] [_focusables $win.tb]]
    if {$text ne ""} { lappend ring $text }
    return $ring
}

proc ::vmdai::panel::focus_next {w {step 1}} {
    set ring [focus_ring]
    if {![llength $ring]} { return "" }
    set i [lsearch -exact $ring $w]
    set j [expr {$i < 0 ? 0 : ($i + $step) % [llength $ring]}]
    set target [lindex $ring $j]
    focus $target
    return $target
}

proc ::vmdai::panel::focus_prev {w} {
    return [focus_next $w -1]
}

# <<Copy>>: display chars only (collapsed text is skipped), tabs as two spaces.
proc ::vmdai::panel::copy_selection {} {
    variable text
    if {[catch {$text get -displaychars sel.first sel.last} s]} { return "" }
    set s [string map [list "\t" "  "] $s]
    _set_clipboard $s
    return $s
}

proc ::vmdai::panel::scroll_transcript {how {n 1}} {
    variable text
    switch -- $how {
        page   { $text yview scroll $n pages }
        top    { $text yview moveto 0 }
        bottom { $text yview moveto 1 }
    }
}

proc ::vmdai::panel::on_escape {} {
    if {![bridge_busy]} { return 0 }
    on_stop
    return 1
}

proc ::vmdai::panel::bind_keys {} {
    variable win
    variable text
    set mod [mod_key]
    bind $win <Escape> {if {[::vmdai::panel::on_escape]} break}
    foreach key {e E} { bind $win <$mod-$key> {::vmdai::panel::toggle_expand; break} }
    foreach key {n N} { bind $win <$mod-$key> {::vmdai::panel::new_chat; break} }
    foreach key {l L} { bind $win <$mod-$key> {::vmdai::composer::focus; break} }
    bind $win <$mod-comma> {::vmdai::panel::open_settings; break}
    set input [composer_text]
    if {$input ne ""} {
        bind $input <Up>         {if {[::vmdai::composer::on_up %W]} break}
        bind $input <Down>       {if {[::vmdai::composer::on_down %W]} break}
        bind $input <Prior>      {::vmdai::panel::scroll_transcript page -1; break}
        bind $input <Next>       {::vmdai::panel::scroll_transcript page 1; break}
        bind $input <$mod-Up>    {::vmdai::panel::scroll_transcript top; break}
        bind $input <$mod-Down>  {::vmdai::panel::scroll_transcript bottom; break}
    }
    bind $text <<Copy>> {::vmdai::panel::copy_selection; break}
    foreach key {a A} { bind $text <$mod-$key> {%W tag add sel 1.0 end; break} }
    # Tab on the toplevel covers Send/Stop and the toolbar in any state (it
    # runs before the `all` traversal binding). The two Text widgets need
    # their own binding: the Text class binding for Tab inserts a tab and breaks.
    foreach w [list $win $input $text] {
        if {$w eq ""} { continue }
        bind $w <Tab> {::vmdai::panel::focus_next %W; break}
        bind $w <<PrevWindow>> {::vmdai::panel::focus_prev %W; break}
    }
}
```

In `proc ::vmdai::panel::build`, insert `bind_keys` on its own line directly before the final `return $win`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_keymap.py tests/test_tk_panel.py tests/test_tk_empty_state.py tests/test_tcl_lint.py -q`
Expected: all pass (`5 passed` from the keymap file).

Run: `python -m pytest tests -q -k composer 2>&1 | tail -2`
Expected: plan 08's composer tests still pass (the replaced `push_history` keeps its signature).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+17 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add plugin/panel.tcl plugin/composer.tcl tests/tcl/test_keymap.tcl tests/test_tk_keymap.py
git commit -m "feat(plugin): V5 keyboard map, focus ring and prompt recall (P09-T03)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T04: Settings: Model tab

**Files:**
- Create: `plugin/settings.tcl`
- Modify: `plugin/init.tcl` (add `settings` to P09-T01's Tk module list, directly after `panel`)
- Create: `tests/tcl/test_settings.tcl`
- Test: `tests/test_tk_settings.py`

**Interfaces:**
- Consumes: models.list, provider.test (P03-T09) — `models.list {provider?, base_url?} -> {models:[{id,label,size?,capabilities?,context_length?}], source, error?, hint?}`, `provider.test {provider?, base_url?, model?} -> {ok, reachable, latency_ms, model_present, loaded, capabilities, version?, error?, hint?}` (`version` for Ollama only), `provider.set {profile, provider, model?, base_url?, options?} -> {ok, …}` (merges `options` key by key); profiles.* (P07-T07) — `profiles.list -> {active, profiles, settings_source}`, `profiles.save {name, profile, activate?}`, `profiles.activate {name}`, `profiles.delete {name}` (`IN_USE` for the active profile); `::vmdai::net::call`, `encode_params` (P06-T03); `::vmdai::panel::present`, `provider_label`, `hostport`, `win` (P09-T01); `::vmdai::statusbar::flash` (P08-T09).
- Produces: `::vmdai::settings::open ?tab? ?prefill?; close; model_hint model_info num_ctx -> string; test_connection`. Also `::vmdai::settings::win` (`.vmd_ai_settings`), `tab name -> path`, `footer -> path`, `reload`, `reload_steps`, `save`, `save_steps`, `set_provider id`, `refresh_models`, `model_warnings model_info num_ctx -> list`, `connection_lines result model -> {icon line1 line2}`, `new_profile ?name?`, `delete_profile`, `_confirm message` (stubbed by tests), the form array `::vmdai::settings::v`, and the constants `LOW_CTX_WARNING`, `NO_TOOLS_WARNING`, `SAVED_TEXT`, `FOOTER_TEXT`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_settings.tcl`:

```tcl
# P09-T04/T05: the Settings dialog (Part B V4 "Settings"; C7 Visibility).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

set ::QWEN [dict create id qwen3.8:27b label qwen3.8:27b \
    capabilities [dict create tools true vision true thinking true] context_length 131072]
set ::LLAVA [dict create id llava:7b label llava:7b \
    capabilities [dict create tools false vision true thinking false] context_length 4096]
set ::MODELS [dict create models [list $::QWEN $::LLAVA] source server]
set ::PROFILES [dict create active qwen settings_source file profiles [dict create \
    qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
        options [dict create num_ctx 32768 think true]] \
    vllm [dict create provider openai-compatible base_url http://localhost:8000/v1 model m1 \
        options [dict create supports_vision false]]]]

namespace eval ::test {}
proc ::test::open_loaded {{which model}} {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply models.list ok $::MODELS
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    set w [::vmdai::settings::open $which]
    ::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"
        && [llength $::vmdai::settings::models] == 2}}
    return $w
}

test settings-provider_fields_change {the fields follow the provider} -body {
    ::test::open_loaded
    set m [::vmdai::settings::tab model]
    set r [list [winfo manager $m.server] [winfo manager $m.ctxf] [winfo manager $m.think]]
    ::vmdai::settings::set_provider anthropic-direct
    lappend r [winfo manager $m.server] [winfo manager $m.ctxf] [winfo manager $m.think] \
        [winfo manager $m.snap] $::vmdai::settings::v(provider_label)
    ::vmdai::settings::set_provider openai-compatible
    lappend r [winfo manager $m.server] [winfo manager $m.think] $::vmdai::settings::v(snapshots) \
        $::vmdai::settings::v(server)
    ::vmdai::settings::set_provider ollama
    lappend r $::vmdai::settings::v(server)
} -result [list grid grid grid {} {} {} grid Anthropic grid {} "Don't send" http://localhost:8000/v1 \
    http://127.0.0.1:11435]

test settings-model_hint_caps_and_ctx {the hint names the capabilities and the context (C7)} -body {
    set a [::vmdai::settings::model_hint $::QWEN 32768]
    set b [::vmdai::settings::model_hint [dict create id m] 16384]
    ::test::open_loaded
    list $a $b [expr {[[::vmdai::settings::tab model].model_hint cget -text] eq $a}]
} -result [list "qwen3.8:27b: tools \u2713 vision \u2713 thinking \u2713 \u00b7 ctx 32k (max 128k)" \
    "m \u00b7 ctx 16k" 1]

test settings-low_ctx_warning {num_ctx below 16384 and a model without tools are flagged} -body {
    set a [::vmdai::settings::model_warnings $::QWEN 8192]
    set b [::vmdai::settings::model_warnings $::QWEN 16384]
    set c [::vmdai::settings::model_warnings $::LLAVA 32768]
    ::test::open_loaded
    set ::vmdai::settings::v(ctx) 8192
    ::vmdai::settings::_refresh_model_hint
    set d [[::vmdai::settings::tab model].model_warn cget -text]
    list $a $b $c [expr {$d eq $::vmdai::settings::LOW_CTX_WARNING}]
} -result [list [list $::vmdai::settings::LOW_CTX_WARNING] {} [list $::vmdai::settings::NO_TOOLS_WARNING] 1]

test settings-models_timeout_hint {a models.list timeout or an empty list leaves the dialog usable} -body {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply models.list transport timeout
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    set w [::vmdai::settings::open]
    set m [::vmdai::settings::tab model]
    ::harness::wait_until {string match "Could not list models*" [[::vmdai::settings::tab model].model_hint cget -text]}
    set r [list [$m.model_hint cget -text] [$m.model instate disabled] \
        [[::vmdai::settings::footer].save instate disabled] [::fake::timeout_of models.list]]
    ::fake::reply models.list ok {models {} source server}
    ::vmdai::settings::refresh_models
    ::harness::wait_until {string match "No models*" [[::vmdai::settings::tab model].model_hint cget -text]}
    lappend r [$m.model_hint cget -text]
    set ::vmdai::settings::v(model) typed-model:1b
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    lappend r [::fake::param [::fake::last provider.set] model]
} -result [list "Could not list models (timeout). Type a model name, or use Test connection." 0 0 10000 \
    "No models found on this server. Type a model name." typed-model:1b]

test settings-test_connection_lines {Test connection shows an icon and two lines, never "tool call"} -body {
    set ok [dict create ok true reachable true latency_ms 212 model_present true loaded true \
        capabilities [dict create tools true vision true thinking true]]
    set down [dict create ok false reachable false latency_ms null model_present null loaded null \
        capabilities {} error refused hint "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"]
    set missing [dict create ok false reachable true latency_ms 40 model_present false loaded false \
        capabilities {} error "Model nope:1b is not on this server" hint "ollama pull nope:1b"]
    set r [list [::vmdai::settings::connection_lines $ok qwen3.8:27b] \
        [::vmdai::settings::connection_lines $down qwen3.8:27b] \
        [::vmdai::settings::connection_lines $missing nope:1b]]
    ::test::open_loaded
    ::fake::reply provider.test ok $ok
    ::vmdai::settings::test_connection
    set m [::vmdai::settings::tab model]
    ::harness::wait_until {string match Connected* [[::vmdai::settings::tab model].test.l1 cget -text]}
    lappend r [list [$m.test.icon cget -text] [$m.test.l1 cget -text] [$m.test.l2 cget -text]] \
        [::fake::timeout_of provider.test] [::fake::param [::fake::last provider.test] base_url] \
        [string match "*tool call*" [join [concat {*}$r]]]
} -result [list \
    [list "\u2713" "Connected \u00b7 212 ms" "qwen3.8:27b loaded \u00b7 tools \u2713 vision \u2713"] \
    [list "\u2717" "Not connected" "Nothing is listening on 127.0.0.1:11435. Is the SSH tunnel up?"] \
    [list "\u2717" "Connected \u00b7 40 ms" "ollama pull nope:1b"] \
    [list "\u2713" "Connected \u00b7 212 ms" "qwen3.8:27b loaded \u00b7 tools \u2713 vision \u2713"] \
    10000 http://127.0.0.1:11435 0]

test settings-new_delete_profile {New... adds an unsaved profile; the active profile cannot be deleted} -body {
    ::test::open_loaded
    ::vmdai::settings::new_profile lab-box
    set m [::vmdai::settings::tab model]
    set r [list $::vmdai::settings::v(profile) $::vmdai::settings::v(provider) \
        [expr {"lab-box" in [$m.profile cget -values]}]]
    ::vmdai::settings::new_profile qwen
    lappend r [[::vmdai::settings::footer].msg cget -text]
    ::vmdai::settings::delete_profile
    lappend r [::fake::count profiles.delete] $::vmdai::settings::v(profile)
    ::vmdai::settings::delete_profile
    lappend r [::fake::count profiles.delete] [[::vmdai::settings::footer].msg cget -text]
    proc ::vmdai::settings::_confirm {message} { return yes }
    ::vmdai::settings::_load_profile vllm
    ::fake::reply profiles.delete ok {ok true}
    ::vmdai::settings::delete_profile
    ::harness::wait_until {expr {![dict exists $::vmdai::settings::profiles vllm]}}
    lappend r [::fake::param [::fake::last profiles.delete] name] $::vmdai::settings::v(profile)
} -result [list lab-box ollama 1 "A profile named qwen already exists." 0 qwen 0 \
    "This is the active profile. Activate another profile before deleting it." vllm qwen]

cleanupTests
```

Create `tests/test_tk_settings.py`:

```python
"""P09-T04/T05: the Settings dialog (Part B V4; C7 Visibility)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 6


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_settings.tcl")


def test_provider_fields_change(results):
    assert_case(results, "settings-provider_fields_change", TOTAL)


def test_model_hint_caps_and_ctx(results):
    assert_case(results, "settings-model_hint_caps_and_ctx", TOTAL)


def test_low_ctx_warning(results):
    assert_case(results, "settings-low_ctx_warning", TOTAL)


def test_models_timeout_hint(results):
    assert_case(results, "settings-models_timeout_hint", TOTAL)


def test_test_connection_lines(results):
    assert_case(results, "settings-test_connection_lines", TOTAL)


def test_new_delete_profile(results):
    assert_case(results, "settings-new_delete_profile", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_settings.py -q`
Expected: `6 failed`; the output shows `invalid command name "::vmdai::settings::open"` (from `settings-provider_fields_change`) and `invalid command name "::vmdai::settings::model_hint"`, then `can't read "::vmdai::settings::LOW_CTX_WARNING"`: the `-result` of `settings-low_ctx_warning` reads that constant, so the file stops there without a tcltest summary and every pytest case reports the missing cases.

- [ ] **Step 3: Write `plugin/settings.tcl`**

Create `plugin/settings.tcl`:

```tcl
# settings.tcl - the ChatVMD Settings dialog (Part B V4 "Settings"; section 2f; C7).
#
# A titled, transient toplevel (at least 460 px wide) with three ttk::notebook
# tabs: Model, Keys, Panel. Its data comes from the runtime (profiles.list,
# models.list, provider.test, keys.test, settings.set) and from
# ~/.vmdai/plugin.json; nothing is written until Save. Return saves, Esc
# cancels. "Changes apply to the next message": Save never cancels or
# restarts a running request.

namespace eval ::vmdai::settings {
    variable win .vmd_ai_settings
    variable PROVIDERS {ollama Ollama openai-compatible OpenAI-compatible anthropic-direct Anthropic openrouter OpenRouter}
    variable DEFAULT_URLS {ollama http://127.0.0.1:11434 openai-compatible http://localhost:8000/v1 openrouter https://openrouter.ai/api/v1}
    variable CTX_VALUES {8192 16384 32768 65536}
    variable SNAPSHOT_VALUES [list Auto Send "Don't send"]
    variable SERVER_HINTS [dict create \
        ollama "This Mac's Ollama is :11434; for a remote server use your SSH tunnel's local port." \
        openai-compatible "The server's OpenAI-compatible base URL, for example http://localhost:8000/v1."]
    variable CTX_NOTE "changing it reloads the model on the server"
    variable THINK_HINT "More reliable multi-step tool use; roughly 2\u00d7 slower per turn."
    variable FOOTER_TEXT "Changes apply to the next message."
    variable LOW_CTX_WARNING "Context below 16k: long tool output is compacted early and the model forgets earlier steps."
    variable NO_TOOLS_WARNING "No tool support: ChatVMD cannot run VMD commands with this model."
    variable SAVED_TEXT "Settings saved \u00b7 they apply to your next message"
    variable ACTIVE_DELETE "This is the active profile. Activate another profile before deleting it."
    if {![array exists ::vmdai::settings::v]} {
        variable v
        array set v {}
    }
    if {![info exists ::vmdai::settings::profiles]} { variable profiles {} }
    if {![info exists ::vmdai::settings::local_new]} { variable local_new {} }
    if {![info exists ::vmdai::settings::active]} { variable active "" }
    if {![info exists ::vmdai::settings::models]} { variable models {} }
    if {![info exists ::vmdai::settings::models_gen]} { variable models_gen 0 }
    if {![info exists ::vmdai::settings::profiles_gen]} { variable profiles_gen 0 }
    if {![info exists ::vmdai::settings::test_gen]} { variable test_gen 0 }
    if {![info exists ::vmdai::settings::saving]} { variable saving 0 }
    if {![info exists ::vmdai::settings::prefill]} { variable prefill {} }
}

# ---- small helpers ------------------------------------------------------------

# dict get with a default; JSON null counts as missing.
proc ::vmdai::settings::_dget {d key default} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::settings::tab {name} {
    variable win
    return $win.bg.nb.$name
}

proc ::vmdai::settings::footer {} {
    variable win
    return $win.bg.foot
}

proc ::vmdai::settings::default_url {provider} {
    variable DEFAULT_URLS
    return [_dget $DEFAULT_URLS $provider ""]
}

proc ::vmdai::settings::_label_to_id {label} {
    variable PROVIDERS
    dict for {id name} $PROVIDERS {
        if {$name eq $label} { return $id }
    }
    return $label
}

proc ::vmdai::settings::_uses_server {{provider ""}} {
    variable v
    if {$provider eq ""} { set provider $v(provider) }
    return [expr {$provider in {ollama openai-compatible}}]
}

proc ::vmdai::settings::_k {n} {
    return "[expr {int(round($n / 1024.0))}]k"
}

proc ::vmdai::settings::_failure {prefix form rest} {
    if {$form eq "rpc_error"} { return "$prefix: [lindex $rest 1]" }
    if {$form eq "transport"} { return "$prefix: the runtime did not answer ([lindex $rest 0])." }
    return "$prefix."
}

proc ::vmdai::settings::_footer_msg {text {kind muted}} {
    set msg [footer].msg
    if {![winfo exists $msg]} { return }
    $msg configure -text $text -foreground [::vmdai::theme::c [expr {$kind eq "err" ? "err" : "muted"}]]
}

# ---- pure text builders (tested directly) ------------------------------------

# "qwen3.8:27b: tools ok vision ok thinking ok - ctx 32k (max 128k)" (C7).
proc ::vmdai::settings::model_hint {model_info num_ctx} {
    set id [_dget $model_info id ""]
    set head $id
    set caps [_dget $model_info capabilities {}]
    set flags {}
    foreach c {tools vision thinking} {
        if {[dict exists $caps $c]} {
            lappend flags "$c [expr {[string is true -strict [dict get $caps $c]] ? "\u2713" : "\u2717"}]"
        }
    }
    if {[llength $flags]} { set head "$id: [join $flags { }]" }
    set parts {}
    if {$head ne ""} { lappend parts $head }
    if {[string is integer -strict $num_ctx]} {
        set ctx "ctx [_k $num_ctx]"
        set max [_dget $model_info context_length ""]
        if {[string is integer -strict $max]} { append ctx " (max [_k $max])" }
        lappend parts $ctx
    }
    return [join $parts " \u00b7 "]
}

proc ::vmdai::settings::model_warnings {model_info num_ctx} {
    variable LOW_CTX_WARNING
    variable NO_TOOLS_WARNING
    set out {}
    set caps [_dget $model_info capabilities {}]
    if {[dict exists $caps tools] && ![string is true -strict [dict get $caps tools]]} {
        lappend out $NO_TOOLS_WARNING
    }
    if {[string is integer -strict $num_ctx] && $num_ctx < 16384} {
        lappend out $LOW_CTX_WARNING
    }
    return $out
}

# {icon line1 line2} for a provider.test result. The probes never call
# /api/chat, so nothing here claims the model "answered".
proc ::vmdai::settings::connection_lines {r model} {
    set ok [string is true -strict [_dget $r ok false]]
    set reachable [_dget $r reachable ""]
    set hint [_dget $r hint ""]
    set error [_dget $r error ""]
    set detail [expr {$hint ne "" ? $hint : $error}]
    if {$reachable eq ""} {
        # anthropic-direct: nothing to probe; the key decides.
        if {$ok} { return [list "\u2713" "API key found" "The model is reached on your next message."] }
        return [list "\u2717" [expr {$error ne "" ? $error : "Not ready"}] $hint]
    }
    if {![string is true -strict $reachable]} {
        return [list "\u2717" "Not connected" $detail]
    }
    set line1 "Connected"
    set latency [_dget $r latency_ms ""]
    if {$latency ne ""} { append line1 " \u00b7 $latency ms" }
    set version [_dget $r version ""]
    if {$version ne ""} { append line1 " \u00b7 Ollama $version" }
    set present [_dget $r model_present ""]
    if {$model eq "" || $present eq ""} {
        return [list [expr {$ok ? "\u2713" : "\u2717"}] $line1 $detail]
    }
    if {![string is true -strict $present]} {
        return [list "\u2717" $line1 [expr {$detail ne "" ? $detail : "$model is not on this server"}]]
    }
    set loaded [_dget $r loaded ""]
    if {$loaded eq ""} {
        set line2 "$model is served"
    } elseif {[string is true -strict $loaded]} {
        set line2 "$model loaded"
    } else {
        set line2 "$model available (not loaded yet)"
    }
    set caps [_dget $r capabilities {}]
    set flags {}
    foreach c {tools vision} {
        if {[dict exists $caps $c]} {
            lappend flags "$c [expr {[string is true -strict [dict get $caps $c]] ? "\u2713" : "\u2717"}]"
        }
    }
    if {[llength $flags]} { append line2 " \u00b7 [join $flags { }]" }
    set icon "\u2713"
    if {!$ok || ([dict exists $caps tools] && ![string is true -strict [dict get $caps tools]])} {
        set icon "!"
    }
    return [list $icon $line1 $line2]
}

# ---- the dialog ---------------------------------------------------------------

proc ::vmdai::settings::open {{which model} {prefill_dict {}}} {
    variable win
    variable prefill
    variable saving
    if {![winfo exists $win]} {
        set saving 0
        _defaults
        _build
    }
    select $which
    set prefill $prefill_dict
    reload
    ::vmdai::panel::present $win
    return $win
}

proc ::vmdai::settings::close {} {
    variable win
    variable saving
    variable v
    set saving 0
    # Typed API keys never outlive the dialog.
    array unset v key,*
    if {[winfo exists $win]} { ::destroy $win }
}

proc ::vmdai::settings::select {which} {
    if {$which in {model keys panel}} {
        [winfo parent [tab model]] select [tab $which]
    }
}

proc ::vmdai::settings::reload {} {
    variable win
    if {![winfo exists $win]} { return }
    foreach step [reload_steps] { ::vmdai::settings::$step }
}

proc ::vmdai::settings::reload_steps {} {
    return {_load_profiles}
}

# A fresh form: every field (typed keys included) is rebuilt from the
# runtime and plugin.json by reload.
proc ::vmdai::settings::_defaults {} {
    variable v
    array unset v
    array set v [list profile "" provider ollama provider_label Ollama \
        server [default_url ollama] model "" ctx 32768 think 1 think_supported 0 \
        snapshots Auto new_name ""]
}

proc ::vmdai::settings::_build {} {
    variable win
    variable FOOTER_TEXT
    set C ::vmdai::theme::c
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD Settings"
    if {[winfo exists $::vmdai::panel::win]} { wm transient $win $::vmdai::panel::win }
    wm minsize $win 460 1
    wm protocol $win WM_DELETE_WINDOW ::vmdai::settings::close
    ttk::frame $win.bg -padding {16 14 16 12}
    pack $win.bg -fill both -expand 1
    ttk::notebook $win.bg.nb
    foreach {name label} {model Model keys Keys panel Panel} {
        ttk::frame $win.bg.nb.$name -padding {14 12 14 10}
        $win.bg.nb add $win.bg.nb.$name -text $label
    }
    pack $win.bg.nb -fill both -expand 1
    _build_model [tab model]
    set f [footer]
    ttk::frame $f
    ttk::label $f.note -text $FOOTER_TEXT -font ChatMeta -foreground [$C muted]
    ttk::label $f.msg -text "" -font ChatMeta -foreground [$C muted] -wraplength 420 -justify left
    ttk::button $f.cancel -text Cancel -command ::vmdai::settings::close
    ttk::button $f.save -text Save -default active -command ::vmdai::settings::save
    grid $f.note -row 0 -column 0 -sticky w
    grid $f.cancel -row 0 -column 1 -padx {8 0}
    grid $f.save -row 0 -column 2 -padx {8 0}
    grid $f.msg -row 1 -column 0 -columnspan 3 -sticky w -pady {4 0}
    grid columnconfigure $f 0 -weight 1
    pack $f -fill x -pady {12 0}
}

proc ::vmdai::settings::_build_model {m} {
    variable PROVIDERS
    variable CTX_VALUES
    variable SNAPSHOT_VALUES
    variable CTX_NOTE
    variable THINK_HINT
    set C ::vmdai::theme::c
    set muted [$C muted]
    set labels {}
    dict for {id label} $PROVIDERS { lappend labels $label }
    ttk::label $m.profile_l -text Profile
    ttk::combobox $m.profile -state readonly -width 24 -textvariable ::vmdai::settings::v(profile)
    ttk::frame $m.profile_b
    ttk::button $m.profile_b.new -text "New\u2026" -command ::vmdai::settings::_show_new_row
    ttk::button $m.profile_b.del -text "Delete\u2026" -command ::vmdai::settings::delete_profile
    pack $m.profile_b.new $m.profile_b.del -side left -padx {6 0}
    ttk::frame $m.newf
    ttk::entry $m.newf.e -width 20 -textvariable ::vmdai::settings::v(new_name)
    ttk::button $m.newf.ok -text Create -command {::vmdai::settings::new_profile $::vmdai::settings::v(new_name)}
    ttk::button $m.newf.cancel -text Cancel -command {grid remove [::vmdai::settings::tab model].newf}
    pack $m.newf.e -side left
    pack $m.newf.ok $m.newf.cancel -side left -padx {6 0}
    bind $m.newf.e <Return> {::vmdai::settings::new_profile $::vmdai::settings::v(new_name); break}
    bind $m.newf.e <Escape> {grid remove [::vmdai::settings::tab model].newf; break}
    ttk::label $m.provider_l -text Provider
    ttk::combobox $m.provider -state readonly -width 24 -values $labels \
        -textvariable ::vmdai::settings::v(provider_label)
    ttk::label $m.server_l -text Server
    ttk::entry $m.server -font ChatCode -width 32 -textvariable ::vmdai::settings::v(server)
    ttk::label $m.server_hint -text "" -font ChatMeta -foreground $muted -wraplength 340 -justify left
    ttk::label $m.model_l -text Model
    ttk::combobox $m.model -width 30 -textvariable ::vmdai::settings::v(model)
    ttk::button $m.refresh -text Refresh -command ::vmdai::settings::refresh_models
    ttk::label $m.model_hint -text "" -font ChatMeta -foreground $muted -wraplength 340 -justify left
    ttk::label $m.model_warn -text "" -font ChatMeta -foreground [$C warn] -wraplength 340 -justify left
    ttk::label $m.ctx_l -text Context
    ttk::frame $m.ctxf
    ttk::combobox $m.ctxf.cb -width 8 -values $CTX_VALUES -textvariable ::vmdai::settings::v(ctx)
    ttk::label $m.ctxf.unit -text tokens -foreground $muted
    pack $m.ctxf.cb -side left
    pack $m.ctxf.unit -side left -padx {6 0}
    ttk::label $m.ctx_note -text $CTX_NOTE -font ChatMeta -foreground $muted
    ttk::checkbutton $m.think -text Thinking -variable ::vmdai::settings::v(think)
    ttk::label $m.think_hint -text $THINK_HINT -font ChatMeta -foreground $muted
    ttk::label $m.snap_l -text Snapshots
    ttk::combobox $m.snap -state readonly -width 12 -values $SNAPSHOT_VALUES \
        -textvariable ::vmdai::settings::v(snapshots)
    ttk::separator $m.sep
    ttk::frame $m.test
    ttk::button $m.test.b -text "Test connection" -command ::vmdai::settings::test_connection
    ttk::label $m.test.icon -text "" -font ChatBodyBold
    ttk::label $m.test.l1 -text "" -font ChatMeta
    ttk::label $m.test.l2 -text "" -font ChatMeta -foreground $muted -wraplength 300 -justify left
    grid $m.test.b    -row 0 -column 0 -rowspan 2 -sticky nw
    grid $m.test.icon -row 0 -column 1 -rowspan 2 -sticky nw -padx {10 4}
    grid $m.test.l1   -row 0 -column 2 -sticky w
    grid $m.test.l2   -row 1 -column 2 -sticky w
    # Right-aligned labels, one field column, hints under the fields.
    grid $m.profile_l   -row 0  -column 0 -sticky e -padx {0 10} -pady 3
    grid $m.profile     -row 0  -column 1 -sticky ew -pady 3
    grid $m.profile_b   -row 0  -column 2 -sticky w
    grid $m.newf        -row 1  -column 1 -columnspan 2 -sticky w -pady {0 4}
    grid $m.provider_l  -row 2  -column 0 -sticky e -padx {0 10} -pady 3
    grid $m.provider    -row 2  -column 1 -sticky ew -pady 3
    grid $m.server_l    -row 3  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.server      -row 3  -column 1 -columnspan 2 -sticky ew -pady {8 0}
    grid $m.server_hint -row 4  -column 1 -columnspan 2 -sticky w
    grid $m.model_l     -row 5  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.model       -row 5  -column 1 -sticky ew -pady {8 0}
    grid $m.refresh     -row 5  -column 2 -sticky w -padx {6 0} -pady {8 0}
    grid $m.model_hint  -row 6  -column 1 -columnspan 2 -sticky w
    grid $m.model_warn  -row 7  -column 1 -columnspan 2 -sticky w
    grid $m.ctx_l       -row 8  -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.ctxf        -row 8  -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $m.ctx_note    -row 9  -column 1 -columnspan 2 -sticky w
    grid $m.think       -row 10 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $m.think_hint  -row 11 -column 1 -columnspan 2 -sticky w -padx {22 0}
    grid $m.snap_l      -row 12 -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $m.snap        -row 12 -column 1 -sticky w -pady {8 0}
    grid $m.sep         -row 13 -column 0 -columnspan 3 -sticky ew -pady 10
    grid $m.test        -row 14 -column 0 -columnspan 3 -sticky w
    grid columnconfigure $m 1 -weight 1
    grid remove $m.newf
    bind $m.profile <<ComboboxSelected>> {::vmdai::settings::_load_profile $::vmdai::settings::v(profile)}
    bind $m.provider <<ComboboxSelected>> \
        {::vmdai::settings::set_provider [::vmdai::settings::_label_to_id $::vmdai::settings::v(provider_label)]}
    bind $m.model <<ComboboxSelected>> ::vmdai::settings::_refresh_model_hint
    bind $m.model <FocusOut> ::vmdai::settings::_refresh_model_hint
    bind $m.ctxf.cb <<ComboboxSelected>> ::vmdai::settings::_refresh_model_hint
    bind $m.ctxf.cb <FocusOut> ::vmdai::settings::_refresh_model_hint
    bind $m.server <FocusOut> ::vmdai::settings::refresh_models
}

# ---- rows that follow the provider --------------------------------------------

proc ::vmdai::settings::_rows {name} {
    set m [tab model]
    switch -- $name {
        server  { return [list $m.server_l $m.server $m.server_hint] }
        context { return [list $m.ctx_l $m.ctxf $m.ctx_note] }
        think   { return [list $m.think $m.think_hint] }
    }
    return {}
}

proc ::vmdai::settings::_show_rows {name on} {
    foreach w [_rows $name] {
        if {$on} { grid $w } else { grid remove $w }
    }
}

proc ::vmdai::settings::_layout_provider {} {
    variable v
    variable SERVER_HINTS
    variable win
    if {![winfo exists $win]} { return }
    set provider $v(provider)
    _show_rows server [_uses_server $provider]
    _show_rows context [_uses_server $provider]
    _show_rows think [expr {$provider eq "ollama" && $v(think_supported)}]
    [tab model].server_hint configure -text [_dget $SERVER_HINTS $provider ""]
}

proc ::vmdai::settings::_saved_profile {name} {
    variable profiles
    variable local_new
    if {[dict exists $profiles $name]} { return [dict get $profiles $name] }
    if {[dict exists $local_new $name]} { return [dict get $local_new $name] }
    return {}
}

# Switching provider restores the profile's saved server when it goes back
# to the saved provider, and uses the new provider's default otherwise.
proc ::vmdai::settings::set_provider {id} {
    variable v
    set saved [_saved_profile $v(profile)]
    set old $v(provider)
    set v(provider) $id
    set v(provider_label) [::vmdai::panel::provider_label $id]
    if {$id ne $old} {
        if {[_dget $saved provider ""] eq $id} {
            set v(server) [_dget $saved base_url [default_url $id]]
            set v(model) [_dget $saved model ""]
        } else {
            set v(server) [default_url $id]
            set v(model) ""
        }
        set v(snapshots) [expr {$id eq "openai-compatible" ? "Don't send" : "Auto"}]
        set v(think_supported) 0
    }
    _layout_provider
    refresh_models
}

# ---- profiles -----------------------------------------------------------------

proc ::vmdai::settings::_profile_names {} {
    variable profiles
    variable local_new
    return [lsort -dictionary [concat [dict keys $profiles] [dict keys $local_new]]]
}

proc ::vmdai::settings::_update_profile_values {} {
    variable win
    if {![winfo exists $win]} { return }
    [tab model].profile configure -values [_profile_names]
}

# Each load gets a generation: an answer to an older load (for example from
# a runtime that has since restarted) is dropped.
proc ::vmdai::settings::_load_profiles {} {
    variable profiles_gen
    incr profiles_gen
    ::vmdai::net::call profiles.list {} [list ::vmdai::settings::_on_profiles $profiles_gen]
}

proc ::vmdai::settings::_on_profiles {gen form args} {
    variable win
    variable profiles
    variable active
    variable local_new
    variable v
    variable prefill
    variable profiles_gen
    if {$gen != $profiles_gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        _footer_msg [_failure "Could not load the profiles" $form $args] err
        return
    }
    set r [lindex $args 0]
    set profiles [_dget $r profiles {}]
    set active [_dget $r active ""]
    _update_profile_values
    if {[dict size $prefill]} {
        set wanted $prefill
        set prefill {}
        _apply_prefill $wanted
        _footer_msg ""
        return
    }
    set name $v(profile)
    if {$name eq "" || !([dict exists $profiles $name] || [dict exists $local_new $name])} {
        set name $active
    }
    if {$name eq "" && [dict size $profiles]} { set name [lindex [_profile_names] 0] }
    if {$name ne ""} { _load_profile $name } else { _layout_provider }
    _footer_msg ""
}

# The empty state's "Use..." link: reuse a profile that points at the same
# server, else start an unsaved profile named <provider>-<port>.
proc ::vmdai::settings::_apply_prefill {pf} {
    variable profiles
    variable local_new
    variable v
    set url [_dget $pf base_url ""]
    set provider [_dget $pf provider ollama]
    set model [_dget $pf model ""]
    dict for {name p} $profiles {
        if {[_dget $p base_url ""] eq $url && [_dget $p provider ""] eq $provider} {
            _load_profile $name
            if {$v(model) eq ""} { set v(model) $model }
            return $name
        }
    }
    set base "$provider-[lindex [split [::vmdai::panel::hostport $url] :] end]"
    set name $base
    set n 2
    while {[dict exists $profiles $name] || [dict exists $local_new $name]} {
        set name "$base-$n"
        incr n
    }
    dict set local_new $name [dict create provider $provider base_url $url model $model options {}]
    _update_profile_values
    _load_profile $name
    return $name
}

proc ::vmdai::settings::_load_profile {name} {
    variable v
    set p [_saved_profile $name]
    set provider [_dget $p provider ollama]
    set opts [_dget $p options {}]
    set v(profile) $name
    set v(provider) $provider
    set v(provider_label) [::vmdai::panel::provider_label $provider]
    set v(server) [_dget $p base_url [default_url $provider]]
    set v(model) [_dget $p model ""]
    set ctx_key [expr {$provider eq "openai-compatible" ? "context_length" : "num_ctx"}]
    set v(ctx) [_dget $opts $ctx_key 32768]
    set v(think) [expr {[string is false -strict [_dget $opts think true]] ? 0 : 1}]
    set vision [_dget $opts supports_vision ""]
    if {[string is true -strict $vision]} {
        set v(snapshots) Send
    } elseif {[string is false -strict $vision]} {
        set v(snapshots) "Don't send"
    } elseif {$vision eq "" && $provider eq "openai-compatible"} {
        set v(snapshots) "Don't send"
    } else {
        set v(snapshots) Auto
    }
    set v(think_supported) 0
    _layout_provider
    refresh_models
}

proc ::vmdai::settings::_show_new_row {} {
    variable v
    set v(new_name) ""
    grid [tab model].newf
    focus [tab model].newf.e
}

proc ::vmdai::settings::new_profile {{name ""}} {
    variable profiles
    variable local_new
    set name [string trim $name]
    if {$name eq ""} {
        _show_new_row
        return ""
    }
    if {![regexp {^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$} $name]} {
        _footer_msg "Profile names use letters, digits, '.', '_' and '-' (at most 40)." err
        return ""
    }
    if {[dict exists $profiles $name] || [dict exists $local_new $name]} {
        _footer_msg "A profile named $name already exists." err
        return ""
    }
    dict set local_new $name [dict create provider ollama base_url [default_url ollama] model "" options {}]
    grid remove [tab model].newf
    _update_profile_values
    _load_profile $name
    _footer_msg ""
    return $name
}

proc ::vmdai::settings::_confirm {message} {
    variable win
    return [tk_messageBox -parent $win -type yesno -icon warning -title "ChatVMD Settings" -message $message]
}

proc ::vmdai::settings::delete_profile {} {
    variable v
    variable local_new
    variable active
    variable ACTIVE_DELETE
    set name $v(profile)
    if {$name eq ""} { return }
    if {[dict exists $local_new $name]} {
        dict unset local_new $name
        _update_profile_values
        _load_profile $active
        return
    }
    if {$name eq $active} {
        _footer_msg $ACTIVE_DELETE err
        return
    }
    if {[_confirm "Delete the profile \"$name\"?"] ne "yes"} { return }
    ::vmdai::net::call profiles.delete [list name s $name] [list ::vmdai::settings::_on_deleted $name]
}

proc ::vmdai::settings::_on_deleted {name form args} {
    variable profiles
    variable active
    variable win
    variable ACTIVE_DELETE
    if {![winfo exists $win]} { return }
    if {$form eq "rpc_error" && [lindex $args 0] eq "IN_USE"} {
        _footer_msg $ACTIVE_DELETE err
        return
    }
    if {$form ne "ok"} {
        _footer_msg [_failure "Could not delete the profile" $form $args] err
        return
    }
    dict unset profiles $name
    _update_profile_values
    _load_profile $active
    _footer_msg "Deleted $name."
}

# ---- models and the hint ------------------------------------------------------

proc ::vmdai::settings::refresh_models {} {
    variable v
    variable win
    variable models_gen
    if {![winfo exists $win]} { return }
    incr models_gen
    _set_model_hint "Loading models\u2026" {}
    set params [list provider s $v(provider)]
    if {[_uses_server] && [string trim $v(server)] ne ""} {
        lappend params base_url s [string trim $v(server)]
    }
    ::vmdai::net::call models.list $params [list ::vmdai::settings::_on_models $models_gen] -timeout 10000
}

proc ::vmdai::settings::_on_models {gen form args} {
    variable models_gen
    variable win
    variable models
    if {$gen != $models_gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        set models {}
        _update_model_values
        if {$form eq "transport"} {
            _set_model_hint "Could not list models ([lindex $args 0]). Type a model name, or use Test connection." {}
        } else {
            _set_model_hint "Could not list models: [lindex $args 1]" {}
        }
        return
    }
    set r [lindex $args 0]
    set models [_dget $r models {}]
    _update_model_values
    if {![llength $models]} {
        set message [_dget $r hint [_dget $r error ""]]
        if {$message eq ""} { set message "No models found on this server. Type a model name." }
        _set_model_hint $message {}
        return
    }
    _refresh_model_hint
}

proc ::vmdai::settings::_update_model_values {} {
    variable models
    set ids {}
    foreach model $models { lappend ids [_dget $model id ""] }
    [tab model].model configure -values $ids
}

proc ::vmdai::settings::_model_info {} {
    variable models
    variable v
    foreach model $models {
        if {[_dget $model id ""] eq [string trim $v(model)]} { return $model }
    }
    return [dict create id [string trim $v(model)]]
}

proc ::vmdai::settings::_refresh_model_hint {} {
    variable v
    variable win
    if {![winfo exists $win]} { return }
    set info [_model_info]
    set caps [_dget $info capabilities {}]
    set v(think_supported) [expr {[dict exists $caps thinking] && [string is true -strict [dict get $caps thinking]]}]
    set ctx [expr {[_uses_server] ? $v(ctx) : ""}]
    _set_model_hint [model_hint $info $ctx] [model_warnings $info $ctx]
    _layout_provider
}

proc ::vmdai::settings::_set_model_hint {hint warnings} {
    set m [tab model]
    $m.model_hint configure -text $hint
    $m.model_warn configure -text [join $warnings "\n"]
}

# ---- Test connection ------------------------------------------------------------

proc ::vmdai::settings::test_connection {} {
    variable v
    variable test_gen
    variable win
    if {![winfo exists $win]} { return }
    incr test_gen
    set m [tab model]
    $m.test.icon configure -text ""
    $m.test.l1 configure -text "Testing\u2026"
    $m.test.l2 configure -text ""
    set model [string trim $v(model)]
    set params [list provider s $v(provider)]
    if {[_uses_server] && [string trim $v(server)] ne ""} {
        lappend params base_url s [string trim $v(server)]
    }
    if {$model ne ""} { lappend params model s $model }
    ::vmdai::net::call provider.test $params [list ::vmdai::settings::_on_test $test_gen $model] -timeout 10000
}

proc ::vmdai::settings::_on_test {gen model form args} {
    variable test_gen
    variable win
    if {$gen != $test_gen || ![winfo exists $win]} { return }
    if {$form eq "ok"} {
        lassign [connection_lines [lindex $args 0] $model] icon line1 line2
    } else {
        set icon "\u2717"
        set line1 "Test failed"
        set line2 [_failure "The runtime could not run the test" $form $args]
    }
    set C ::vmdai::theme::c
    set colour [$C [expr {$icon eq "\u2713" ? "ok" : ($icon eq "!" ? "warn" : "err")}]]
    set m [tab model]
    $m.test.icon configure -text $icon -foreground $colour
    $m.test.l1 configure -text $line1
    $m.test.l2 configure -text $line2
}

# ---- Save -------------------------------------------------------------------

proc ::vmdai::settings::save {} {
    variable saving
    variable win
    if {$saving || ![winfo exists $win]} { return }
    set problem [_validate]
    if {$problem ne ""} {
        _footer_msg $problem err
        return
    }
    set saving 1
    _footer_msg "Saving\u2026"
    _next_step [save_steps]
}

proc ::vmdai::settings::save_steps {} {
    return {_save_profile _finish_save}
}

# Each step is called with a continuation; it calls {*}$k when done, or
# _fail to stop the chain and keep the dialog open. An error in a step
# also stops the chain, so the dialog never stays at "Saving...".
proc ::vmdai::settings::_next_step {steps} {
    variable win
    if {![winfo exists $win] || ![llength $steps]} { return }
    set k [list ::vmdai::settings::_next_step [lrange $steps 1 end]]
    if {[catch {::vmdai::settings::[lindex $steps 0] $k} err]} {
        ::vmdai::config::log "settings: save step [lindex $steps 0] failed: $err"
        _fail "Could not save: $err"
    }
}

proc ::vmdai::settings::_fail {message} {
    variable saving
    set saving 0
    _footer_msg $message err
}

proc ::vmdai::settings::_validate {} {
    variable v
    if {$v(profile) eq ""} { return "Choose or create a profile first." }
    if {[_uses_server]} {
        if {![regexp {^https?://[^/\s]+} [string trim $v(server)]]} {
            return "The server must start with http:// or https://."
        }
        if {![string is integer -strict $v(ctx)] || $v(ctx) < 2048 || $v(ctx) > 1048576} {
            return "Context must be a whole number of tokens between 2048 and 1048576."
        }
    }
    return ""
}

proc ::vmdai::settings::_option_pairs {} {
    variable v
    set pairs {}
    switch -- $v(provider) {
        ollama {
            lappend pairs num_ctx i $v(ctx)
            if {$v(think_supported)} { lappend pairs think b [expr {$v(think) ? 1 : 0}] }
        }
        openai-compatible {
            lappend pairs context_length i $v(ctx)
        }
    }
    switch -- $v(snapshots) {
        Send          { lappend pairs supports_vision b 1 }
        "Don't send"  { lappend pairs supports_vision b 0 }
        default       { lappend pairs supports_vision s auto }
    }
    return $pairs
}

# An existing profile goes through provider.set {profile, ...}, which merges
# options key by key, so option keys this dialog does not show survive (section 2f).
# A profile made with New... is created with profiles.save.
proc ::vmdai::settings::_save_profile {k} {
    variable v
    variable profiles
    set name $v(profile)
    set options [::vmdai::net::encode_params [_option_pairs]]
    set model [string trim $v(model)]
    if {![dict exists $profiles $name]} {
        set pairs [list provider s $v(provider) model s $model]
        if {[_uses_server]} {
            lappend pairs base_url s [string trim $v(server)]
        } elseif {[default_url $v(provider)] ne ""} {
            lappend pairs base_url s [default_url $v(provider)]
        }
        lappend pairs options j $options
        set profile [::vmdai::net::encode_params $pairs]
        ::vmdai::net::call profiles.save [list name s $name profile j $profile activate b 1] \
            [list ::vmdai::settings::_after_profile $k $name 1]
        return
    }
    set params [list profile s $name provider s $v(provider) model s $model]
    if {[_uses_server]} { lappend params base_url s [string trim $v(server)] }
    lappend params options j $options
    ::vmdai::net::call provider.set $params [list ::vmdai::settings::_after_profile $k $name 0]
}

proc ::vmdai::settings::_after_profile {k name activated form args} {
    variable active
    variable local_new
    if {$form ne "ok"} {
        _fail [_failure "Could not save the profile" $form $args]
        return
    }
    if {[dict exists $local_new $name]} { dict unset local_new $name }
    if {$activated || $name eq $active} {
        set active $name
        {*}$k
        return
    }
    ::vmdai::net::call profiles.activate [list name s $name] [list ::vmdai::settings::_after_activate $k $name]
}

proc ::vmdai::settings::_after_activate {k name form args} {
    variable active
    if {$form ne "ok"} {
        _fail [_failure "Could not activate the profile" $form $args]
        return
    }
    set active $name
    {*}$k
}

proc ::vmdai::settings::_finish_save {k} {
    variable saving
    variable SAVED_TEXT
    set saving 0
    close
    set panel $::vmdai::panel::win
    if {[winfo exists $panel]} {
        ::vmdai::statusbar::flash $SAVED_TEXT 4000
        # The status bar follows the saved profile (P09-T07 makes
        # refresh_info re-read runtime.info and profiles.list).
        ::vmdai::panel::refresh_info
    }
    {*}$k
}
```

In `plugin/init.tcl`, add `settings` to the Tk module list from P09-T01 Step 6, directly after `panel`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_settings.py tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: `6 passed` from the settings file, `7 passed` from the panel file (its `test_component_targets_defined` now also checks every `::vmdai::settings::` name the plugin calls), lint passes.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+23 passed`, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add plugin/settings.tcl plugin/init.tcl tests/tcl/test_settings.tcl tests/test_tk_settings.py
git commit -m "feat(plugin): Settings dialog Model tab with models.list, Test connection and the C7 hint (P09-T04)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T05: Settings: Keys and Panel tabs, Save

**Files:**
- Modify: `plugin/settings.tcl` (from P09-T04: `_build`, `reload_steps`, `save_steps`; append the Keys and Panel sections)
- Modify: `tests/tcl/test_settings.tcl` (insert four cases before `cleanupTests`)
- Modify: `tests/test_tk_settings.py`

**Interfaces:**
- Consumes: settings.set (P03-T09) — `settings.set {patch}`; an empty patch on a token session returns `{ok, settings, persisted}` without writing, and a patch with `wiki_enabled`/`reasoning_visible` persists them; profiles.save (P07-T07); `keys.test {provider} -> {ok, message, source}` and `keys.save {provider, key} -> {ok, source, message}` (today's runtime; "No keychain backend available" when keyring is missing); `::vmdai::config::load_plugin_settings`, `save_plugin_settings` (P06-T02); `::vmdai::bridge::apply_workdir` (P06-T07); `::vmdai::panel::set_expand_all`, `open_log`, `present` (P09-T01).
- Produces: Save sends profiles.save/activate (or provider.set for an existing profile) and settings.set, and writes plugin.json. Also `::vmdai::settings::save_keys`, `key_source_text id result -> string`, `appearance_values -> list`, `choose_folder`, `choose_python`, the constants `NO_KEYCHAIN`, `PERSISTED_FIELDS` (`{wiki_enabled wiki}`; P09-T08 adds `reasoning_visible reasoning`), and the variables `persisted` (the last `persisted` dict the runtime returned) and `nokeychain`.

- [ ] **Step 1: Write the failing tests**

In `tests/tcl/test_settings.tcl`, insert before the final `cleanupTests`:

```tcl
test settings-no_keychain_message {no keychain backend: the Keys tab shows the section 2f message instead of Save} -body {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply models.list ok $::MODELS
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply keys.test ok {ok false message {No keychain backend available} source none}
    ::vmdai::settings::open keys
    set k [::vmdai::settings::tab keys]
    ::harness::wait_until {expr {[winfo manager [::vmdai::settings::tab keys].nokey] ne ""}}
    set r [list [$k.nokey cget -text] [winfo manager $k.save] [$k.src_anthropic cget -text]]
    set ::vmdai::settings::v(key,anthropic) sk-ant-test
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    lappend r [::fake::count keys.save]
} -result [list "No keychain backend: set ANTHROPIC_API_KEY/OPENROUTER_API_KEY in the environment, or install `keyring`" \
    {} "Not set" 0]

test settings-panel_prefs_saved {Panel prefs go to plugin.json, persisted keys to settings.set} -body {
    ::test::open_loaded panel
    ::harness::wait_until {expr {[dict size $::vmdai::settings::persisted] > 0}}
    ::vmdai::panel::set_expand_all 0
    set ::vmdai::settings::v(appearance) dark
    set ::vmdai::settings::v(expand) 1
    set ::vmdai::settings::v(python) /opt/py/bin/python3
    set ::vmdai::settings::v(wiki) 1
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    set d [::vmdai::config::load_plugin_settings]
    list [dict get $d appearance] [string is true -strict [dict get $d expand_steps]] [dict get $d python] \
        [::fake::param [::fake::last settings.set] patch] $::vmdai::panel::expand_all \
        [::harness::count_calls apply_workdir]
} -result {dark 1 /opt/py/bin/python3 {{"wiki_enabled":true}} 1 0}

test settings-save_while_busy {Save during a request runs the whole chain for the next message and leaves the request alone} -body {
    ::test::open_loaded
    ::harness::wait_until {expr {[dict size $::vmdai::settings::persisted] > 0}}
    set ::harness::busy 1
    ::vmdai::panel::set_busy 1
    set ::harness::flashes {}
    set ::vmdai::settings::v(model) qwen3.8:30b
    set ::vmdai::settings::v(wiki) 1
    ::fake::reply provider.set ok {ok true provider ollama model qwen3.8:30b profile qwen agent_loop true capabilities {}}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    set p [::fake::last provider.set]
    set r [list [::fake::param $p profile] [::fake::param $p model] [::fake::param $p options] \
        [::fake::param [::fake::last settings.set] patch] \
        [::fake::count profiles.activate] [::harness::count_calls cancel] [::harness::count_calls new_chat] \
        [lindex $::harness::flashes end] [dict get [::vmdai::bridge::state] busy]]
    set ::harness::busy 0
    ::vmdai::panel::set_busy 0
    set r
} -result [list qwen qwen3.8:30b {{"num_ctx":32768,"think":true,"supports_vision":"auto"}} \
    {{"wiki_enabled":true}} 0 0 0 "Settings saved \u00b7 they apply to your next message" 1]

test settings-return_saves_esc_cancels {Return saves, Esc cancels without saving} -body {
    ::test::open_loaded
    ::fake::reply provider.set ok {ok true}
    set before [::fake::count provider.set]
    ::harness::fire [::vmdai::settings::tab model].server <Return>
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    set r [list [expr {[::fake::count provider.set] - $before}] [winfo exists .vmd_ai_settings]]
    ::test::open_loaded
    set before [::fake::count provider.set]
    ::harness::fire [::vmdai::settings::tab model].server <Escape>
    lappend r [winfo exists .vmd_ai_settings] [expr {[::fake::count provider.set] - $before}]
} -result {1 0 0 0}
```

In `tests/test_tk_settings.py`, change `TOTAL = 6` to `TOTAL = 10` and append:

```python
def test_no_keychain_message(results):
    assert_case(results, "settings-no_keychain_message", TOTAL)


def test_panel_prefs_saved(results):
    assert_case(results, "settings-panel_prefs_saved", TOTAL)


def test_save_while_busy(results):
    assert_case(results, "settings-save_while_busy", TOTAL)


def test_return_saves_esc_cancels(results):
    assert_case(results, "settings-return_saves_esc_cancels", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_settings.py -q`
Expected: `4 failed, 6 passed`; `settings-no_keychain_message` fails with `bad window path name ".vmd_ai_settings.bg.nb.keys.nokey"`, `settings-panel_prefs_saved` and `settings-save_while_busy` with `can't read "::vmdai::settings::persisted"`, and `settings-return_saves_esc_cancels` on its result (`0 1 1 0`: the dialog has no Return/Esc bindings yet, so the wait for the dialog to close times out after 2 s).

- [ ] **Step 3: Build the Keys and Panel tabs and extend the reload and save chains**

In `plugin/settings.tcl`, in `proc ::vmdai::settings::_build`, directly after the line `_build_model [tab model]`, add:

```tcl
    _build_keys [tab keys]
    _build_panel [tab panel]
```

and at the end of the same proc, directly after `pack $f -fill x -pady {12 0}`, add the dialog keys (Part B V4: Return saves, Esc cancels):

```tcl
    bind $win <Return> {::vmdai::settings::save; break}
    bind $win <KP_Enter> {::vmdai::settings::save; break}
    bind $win <Escape> {::vmdai::settings::close; break}
```

Replace the body of `proc ::vmdai::settings::reload_steps` with:

```tcl
proc ::vmdai::settings::reload_steps {} {
    return {_load_profiles _load_keys _load_persisted _load_panel_prefs}
}
```

Replace the body of `proc ::vmdai::settings::save_steps` with:

```tcl
proc ::vmdai::settings::save_steps {} {
    return {_save_profile _save_keys _save_persisted _save_plugin_prefs _finish_save}
}
```

Append to `plugin/settings.tcl`:

```tcl
# ---- Keys tab (section 2f Providers and keys) ----------------------------------------

namespace eval ::vmdai::settings {
    variable KEY_PROVIDERS {anthropic Anthropic ANTHROPIC_API_KEY openrouter OpenRouter OPENROUTER_API_KEY}
    variable NO_KEYCHAIN_MESSAGE "No keychain backend available"
    variable NO_KEYCHAIN "No keychain backend: set ANTHROPIC_API_KEY/OPENROUTER_API_KEY in the environment, or install `keyring`"
    if {![info exists ::vmdai::settings::nokeychain]} { variable nokeychain 0 }
}

proc ::vmdai::settings::_build_keys {k} {
    variable KEY_PROVIDERS
    variable NO_KEYCHAIN
    variable nokeychain
    set C ::vmdai::theme::c
    set nokeychain 0
    set r 0
    foreach {id label env} $KEY_PROVIDERS {
        ttk::label $k.l_$id -text $label
        ttk::entry $k.e_$id -width 30 -show "\u2022" -textvariable ::vmdai::settings::v(key,$id)
        ttk::button $k.s_$id -text Show -width 6 -command [list ::vmdai::settings::_toggle_show $id]
        ttk::label $k.src_$id -text "" -font ChatMeta -foreground [$C muted]
        grid $k.l_$id -row $r -column 0 -sticky e -padx {0 10} -pady {6 0}
        grid $k.e_$id -row $r -column 1 -sticky ew -pady {6 0}
        grid $k.s_$id -row $r -column 2 -sticky w -padx {6 0} -pady {6 0}
        incr r
        grid $k.src_$id -row $r -column 1 -columnspan 2 -sticky w
        incr r
    }
    ttk::button $k.save -text "Save keys" -command ::vmdai::settings::save_keys
    ttk::label $k.nokey -text $NO_KEYCHAIN -font ChatMeta -foreground [$C warn] -wraplength 360 -justify left
    grid $k.save -row $r -column 1 -sticky w -pady {12 0}
    grid $k.nokey -row [expr {$r + 1}] -column 0 -columnspan 3 -sticky w -pady {12 0}
    grid remove $k.nokey
    grid columnconfigure $k 1 -weight 1
}

proc ::vmdai::settings::_toggle_show {id} {
    set k [tab keys]
    if {[$k.e_$id cget -show] eq ""} {
        $k.e_$id configure -show "\u2022"
        $k.s_$id configure -text Show
    } else {
        $k.e_$id configure -show ""
        $k.s_$id configure -text Hide
    }
}

proc ::vmdai::settings::key_source_text {id r} {
    variable KEY_PROVIDERS
    set env ""
    foreach {pid label var} $KEY_PROVIDERS {
        if {$pid eq $id} { set env $var }
    }
    switch -- [_dget $r source none] {
        env     { return "From the environment ($env)" }
        keyring { return "Saved in the Keychain" }
    }
    return "Not set"
}

proc ::vmdai::settings::_set_nokeychain {on} {
    variable nokeychain
    variable win
    set nokeychain [expr {$on ? 1 : 0}]
    if {![winfo exists $win]} { return }
    set k [tab keys]
    if {$nokeychain} {
        grid remove $k.save
        grid $k.nokey
    } else {
        grid $k.save
        grid remove $k.nokey
    }
}

proc ::vmdai::settings::_load_keys {} {
    variable KEY_PROVIDERS
    foreach {id label env} $KEY_PROVIDERS {
        ::vmdai::net::call keys.test [list provider s $id] [list ::vmdai::settings::_on_key_test $id]
    }
}

proc ::vmdai::settings::_on_key_test {id form args} {
    variable win
    variable NO_KEYCHAIN_MESSAGE
    if {![winfo exists $win]} { return }
    set src [tab keys].src_$id
    if {$form ne "ok"} {
        $src configure -text "Unknown: the runtime did not answer"
        return
    }
    set r [lindex $args 0]
    if {[_dget $r message ""] eq $NO_KEYCHAIN_MESSAGE} { _set_nokeychain 1 }
    $src configure -text [key_source_text $id $r]
}

# The Keys tab's own button: save the typed keys now.
proc ::vmdai::settings::save_keys {} {
    _save_keys [list ::vmdai::settings::_footer_msg "Keys saved."]
}

proc ::vmdai::settings::_save_keys {k} {
    variable nokeychain
    variable v
    variable KEY_PROVIDERS
    if {$nokeychain} {
        {*}$k
        return
    }
    set todo {}
    foreach {id label env} $KEY_PROVIDERS {
        if {[info exists v(key,$id)] && [string trim $v(key,$id)] ne ""} { lappend todo $id }
    }
    _save_next_key $todo $k
}

proc ::vmdai::settings::_save_next_key {todo k} {
    variable v
    if {![llength $todo]} {
        {*}$k
        return
    }
    set id [lindex $todo 0]
    ::vmdai::net::call keys.save [list provider s $id key s [string trim $v(key,$id)]] \
        [list ::vmdai::settings::_after_key $id [lrange $todo 1 end] $k]
}

proc ::vmdai::settings::_after_key {id rest k form args} {
    variable v
    variable win
    variable NO_KEYCHAIN_MESSAGE
    if {$form ne "ok"} {
        _fail [_failure "Could not save the $id key" $form $args]
        return
    }
    set r [lindex $args 0]
    if {![string is true -strict [_dget $r ok false]]} {
        if {[_dget $r message ""] eq $NO_KEYCHAIN_MESSAGE} {
            _set_nokeychain 1
            {*}$k
            return
        }
        _fail "Could not save the $id key: [_dget $r message {}]"
        return
    }
    set v(key,$id) ""
    if {[winfo exists $win]} { [tab keys].src_$id configure -text "Saved in the Keychain" }
    _save_next_key $rest $k
}

# ---- Panel tab ----------------------------------------------------------------

namespace eval ::vmdai::settings {
    # settings.json key -> form field, for the persisted toggles.
    variable PERSISTED_FIELDS {wiki_enabled wiki}
    if {![info exists ::vmdai::settings::persisted]} { variable persisted {} }
}

# System needs MacWindowStyle (Tk 8.6 on aqua); elsewhere only Light and Dark (V7).
proc ::vmdai::settings::appearance_values {} {
    if {[tk windowingsystem] eq "aqua" && ![catch {::tk::unsupported::MacWindowStyle isdark .}]} {
        return {System Light Dark}
    }
    return {Light Dark}
}

proc ::vmdai::settings::_build_panel {p} {
    set C ::vmdai::theme::c
    set muted [$C muted]
    ttk::label $p.appearance_l -text Appearance
    ttk::combobox $p.appearance -state readonly -width 10 -values [appearance_values] \
        -textvariable ::vmdai::settings::v(appearance_label)
    ttk::checkbutton $p.expand -text "Expand steps by default" -variable ::vmdai::settings::v(expand)
    ttk::label $p.folder_l -text "Project folder"
    ttk::entry $p.folder -state readonly -width 30 -textvariable ::vmdai::settings::v(folder)
    ttk::button $p.folder_b -text "Choose\u2026" -command ::vmdai::settings::choose_folder
    ttk::label $p.python_l -text "Python for the runtime"
    ttk::entry $p.python -font ChatCode -width 30 -textvariable ::vmdai::settings::v(python)
    ttk::button $p.python_b -text "Choose\u2026" -command ::vmdai::settings::choose_python
    ttk::label $p.python_hint -font ChatMeta -foreground $muted -wraplength 340 -justify left \
        -text "Empty: VMD_AI_PYTHON, then python3 on PATH. Used the next time the runtime starts."
    ttk::checkbutton $p.wiki -text "Use project wiki (slower)" -variable ::vmdai::settings::v(wiki)
    ttk::label $p.wiki_hint -text "Adds about 17 s to every request." -font ChatMeta -foreground $muted
    ttk::label $p.tcl_l -text "Tcl execution"
    ttk::label $p.tcl -text "Auto-run (model-written Tcl runs without asking)" -foreground $muted
    ttk::button $p.log -text "Open log" -command ::vmdai::panel::open_log
    # Row 1 is left for "Show model reasoning" (P09-T08).
    grid $p.appearance_l -row 0 -column 0 -sticky e -padx {0 10} -pady 4
    grid $p.appearance   -row 0 -column 1 -sticky w -pady 4
    grid $p.expand       -row 2 -column 1 -columnspan 2 -sticky w -pady 4
    grid $p.folder_l     -row 3 -column 0 -sticky e -padx {0 10} -pady 4
    grid $p.folder       -row 3 -column 1 -sticky ew -pady 4
    grid $p.folder_b     -row 3 -column 2 -sticky w -padx {6 0} -pady 4
    grid $p.python_l     -row 4 -column 0 -sticky e -padx {0 10} -pady {4 0}
    grid $p.python       -row 4 -column 1 -sticky ew -pady {4 0}
    grid $p.python_b     -row 4 -column 2 -sticky w -padx {6 0} -pady {4 0}
    grid $p.python_hint  -row 5 -column 1 -columnspan 2 -sticky w
    grid $p.wiki         -row 6 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $p.wiki_hint    -row 7 -column 1 -columnspan 2 -sticky w -padx {22 0}
    grid $p.tcl_l        -row 8 -column 0 -sticky e -padx {0 10} -pady {8 0}
    grid $p.tcl          -row 8 -column 1 -columnspan 2 -sticky w -pady {8 0}
    grid $p.log          -row 9 -column 1 -sticky w -pady {10 0}
    grid columnconfigure $p 1 -weight 1
    bind $p.appearance <<ComboboxSelected>> \
        {set ::vmdai::settings::v(appearance) [string tolower $::vmdai::settings::v(appearance_label)]}
}

proc ::vmdai::settings::choose_folder {} {
    variable v
    variable win
    set dir [tk_chooseDirectory -parent $win -title "Project folder" -initialdir $v(folder) -mustexist 1]
    if {$dir ne ""} { set v(folder) $dir }
    return $dir
}

proc ::vmdai::settings::choose_python {} {
    variable v
    variable win
    set path [tk_getOpenFile -parent $win -title "Python for the runtime"]
    if {$path ne ""} { set v(python) $path }
    return $path
}

proc ::vmdai::settings::_load_panel_prefs {} {
    variable v
    set d {}
    catch {set d [::vmdai::config::load_plugin_settings]}
    set v(appearance) [_dget $d appearance system]
    if {$v(appearance) ni {system light dark}} { set v(appearance) system }
    set v(appearance_label) [string totitle $v(appearance)]
    set v(expand) [string is true -strict [_dget $d expand_steps false]]
    set v(expand_loaded) $v(expand)
    set v(python) [_dget $d python ""]
    set v(folder) [pwd]
}

# An empty patch reads the persisted top-level settings without writing them.
proc ::vmdai::settings::_load_persisted {} {
    ::vmdai::net::call settings.set [list patch j "{}"] [list ::vmdai::settings::_on_persisted]
}

proc ::vmdai::settings::_on_persisted {form args} {
    variable persisted
    variable v
    variable win
    variable PERSISTED_FIELDS
    if {$form ne "ok" || ![winfo exists $win]} { return }
    set persisted {}
    catch {set persisted [dict get [lindex $args 0] persisted]}
    foreach {key field} $PERSISTED_FIELDS {
        if {[dict exists $persisted $key]} {
            set v($field) [string is true -strict [dict get $persisted $key]]
        }
    }
}

# Only keys the runtime reported and the user changed; nothing when the
# settings could not be read (a tokenless session, or a failed read).
proc ::vmdai::settings::_persisted_pairs {} {
    variable persisted
    variable v
    variable PERSISTED_FIELDS
    set pairs {}
    foreach {key field} $PERSISTED_FIELDS {
        if {![dict exists $persisted $key] || ![info exists v($field)]} { continue }
        set old [string is true -strict [dict get $persisted $key]]
        set new [expr {$v($field) ? 1 : 0}]
        if {$old != $new} { lappend pairs $key b $new }
    }
    return $pairs
}

proc ::vmdai::settings::_save_persisted {k} {
    set pairs [_persisted_pairs]
    if {![llength $pairs]} {
        {*}$k
        return
    }
    ::vmdai::net::call settings.set [list patch j [::vmdai::net::encode_params $pairs]] \
        [list ::vmdai::settings::_after_persisted $k]
}

proc ::vmdai::settings::_after_persisted {k form args} {
    variable persisted
    if {$form ne "ok"} {
        _fail [_failure "Could not save the panel settings" $form $args]
        return
    }
    catch {set persisted [dict get [lindex $args 0] persisted]}
    {*}$k
}

proc ::vmdai::settings::_save_plugin_prefs {k} {
    variable v
    set d {}
    catch {set d [::vmdai::config::load_plugin_settings]}
    dict set d version 1
    dict set d appearance $v(appearance)
    dict set d expand_steps [expr {$v(expand) ? 1 : 0}]
    dict set d python [string trim $v(python)]
    if {[catch {::vmdai::config::save_plugin_settings $d} err]} {
        _fail "Could not write plugin.json: $err"
        return
    }
    if {$v(expand) != $v(expand_loaded)} { ::vmdai::panel::set_expand_all $v(expand) }
    if {$v(folder) ne "" && $v(folder) ne [pwd]} { ::vmdai::bridge::apply_workdir $v(folder) }
    {*}$k
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_settings.py tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: `10 passed` from the settings file; the panel file and lint pass.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+27 passed`, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add plugin/settings.tcl tests/tcl/test_settings.tcl tests/test_tk_settings.py
git commit -m "feat(plugin): Settings Keys and Panel tabs; Save writes profiles, settings.set and plugin.json (P09-T05)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T06: history.tcl (ttk)

**Files:**
- Create: `plugin/history.tcl`
- Modify: `plugin/init.tcl` (add `history` to the Tk module list, directly after `settings`)
- Create: `tests/tcl/test_history.tcl`
- Test: `tests/test_tk_history.py`

**Interfaces:**
- Consumes: bridge::resume (P06-T07) — `::vmdai::bridge::resume chat_id ?callback?`, whose callback gets `ok result`, `rpc_error code message data` (`CHAT_LOCKED`, `REQUEST_CONFLICT`, `NOT_FOUND`) or `transport reason`; `chat.history.list {offset, limit} -> {items:[{chat_id, title, updated_at, message_count}]}` through `::vmdai::net::call` (today's runtime; `updated_at` is `YYYY-MM-DDTHH:MM:SSZ`); `::vmdai::panel::bridge_busy`, `present`, `win` (P09-T01); `::vmdai::statusbar::flash` (P08-T09).
- Produces: `::vmdai::history::open; format_updated iso now -> string`. Also `::vmdai::history::win` (`.vmd_ai_history`), `close`, `tree -> path`, `fetch`, `resume_selected`, `message -> string`, `ellipsize_middle s font px -> string`, constants `LIMIT` (50), `LOCKED_TEXT`, `BUSY_TEXT`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_history.tcl`:

```tcl
# P09-T06: the History picker (Part B V4 "History").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop
set ::env(TZ) :UTC

namespace eval ::test {}
# n chats, oldest first on the wire (the dialog sorts them).
proc ::test::items {n} {
    set items {}
    for {set i 0} {$i < $n} {incr i} {
        set ts [clock format [expr {1790000000 + $i * 60}] -format {%Y-%m-%dT%H:%M:%SZ} -timezone :UTC]
        lappend items [dict create chat_id [format chat_%012x $i] title "Chat $i" \
            updated_at $ts message_count $i]
    }
    return $items
}

test history-columns_newest_50 {Title, Updated, Messages; the newest 50; the first row selected} -body {
    ::harness::fresh_panel
    ::fake::reply chat.history.list ok [dict create items [::test::items 60]]
    set w [::vmdai::history::open]
    ::harness::wait_until {expr {[llength [[::vmdai::history::tree] children {}]] > 0}}
    set tv [::vmdai::history::tree]
    set first [lindex [$tv children {}] 0]
    list [llength [$tv children {}]] [lindex [$tv item $first -values] 0] \
        [lindex [$tv item $first -values] 2] [$tv selection] [$tv cget -columns] \
        [::fake::param [::fake::last chat.history.list] limit] [wm title $w]
} -result {50 {Chat 59} 59 row0 {title updated messages} 50 {ChatVMD History}}

test history-format_updated {Today / Yesterday / weekday / month day / full date} -body {
    set now [clock scan "2026-09-24 15:00:00" -format "%Y-%m-%d %H:%M:%S" -timezone :UTC]
    list [::vmdai::history::format_updated 2026-09-24T14:32:05Z $now] \
         [::vmdai::history::format_updated 2026-09-23T09:10:00Z $now] \
         [::vmdai::history::format_updated 2026-09-21T08:00:00Z $now] \
         [::vmdai::history::format_updated 2026-09-03T08:00:00Z $now] \
         [::vmdai::history::format_updated 2025-12-31T08:00:00Z $now] \
         [::vmdai::history::format_updated garbage $now]
} -result {{Today 14:32} {Yesterday 09:10} {Mon 08:00} {Sep 3} 2025-12-31 garbage}

test history-locked_inline {CHAT_LOCKED shows inline and the dialog stays open} -body {
    ::harness::fresh_panel
    ::fake::reply chat.history.list ok [dict create items [::test::items 3]]
    set ::harness::resume_reply [list rpc_error CHAT_LOCKED "chat is open in another runtime" {}]
    set w [::vmdai::history::open]
    ::harness::wait_until {expr {[llength [[::vmdai::history::tree] children {}]] == 3}}
    ::harness::fire [::vmdai::history::tree] <Return>
    ::harness::wait_until {expr {[::vmdai::history::message] ne ""}}
    set r [list [::vmdai::history::message] [winfo exists $w] [lindex $::harness::bridge_calls end]]
    ::harness::fire [::vmdai::history::tree] <Double-1>
    ::harness::settle
    set ::harness::resume_reply {ok {ok true chat_id chat_000000000002 title {Chat 2}}}
    lappend r [::harness::count_calls resume]
} -result [list "Open in another VMD window" 1 [list resume chat_000000000002] 2]

test history-disabled_while_busy {History is unavailable while a request is running} -body {
    ::harness::fresh_panel
    set ::harness::busy 1
    set ::harness::flashes {}
    set r [list [::vmdai::history::open] [winfo exists .vmd_ai_history] [lindex $::harness::flashes end] \
        [::fake::count chat.history.list]]
    set ::harness::busy 0
    set r
} -result [list "" 0 "History is unavailable while a request is running" 0]

cleanupTests
```

Create `tests/test_tk_history.py`:

```python
"""P09-T06: the History picker (Part B V4)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 4


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_history.tcl")


def test_columns_newest_50(results):
    assert_case(results, "history-columns_newest_50", TOTAL)


def test_format_updated(results):
    assert_case(results, "history-format_updated", TOTAL)


def test_locked_inline(results):
    assert_case(results, "history-locked_inline", TOTAL)


def test_disabled_while_busy(results):
    assert_case(results, "history-disabled_while_busy", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_history.py -q`
Expected: `4 failed`; the output shows `invalid command name "::vmdai::history::open"` and `"::vmdai::history::format_updated"`.

- [ ] **Step 3: Write `plugin/history.tcl`**

Create `plugin/history.tcl`:

```tcl
# history.tcl - the History picker (Part B V4 "History"), ported to ttk.
#
# A titled transient dialog, 560x400, with a ttk::treeview of the newest 50
# chats (Title, Updated, Messages; the first row selected). Return or a
# double-click resumes, Esc cancels. A chat that another VMD window holds
# (CHAT_LOCKED) is reported inline and the dialog stays open. History is
# unavailable while a request runs.

namespace eval ::vmdai::history {
    variable win .vmd_ai_history
    variable LIMIT 50
    variable LOCKED_TEXT "Open in another VMD window"
    variable BUSY_TEXT "History is unavailable while a request is running"
    if {![info exists ::vmdai::history::rows]} { variable rows {} }
    if {![info exists ::vmdai::history::gen]} { variable gen 0 }
}

proc ::vmdai::history::_dget {d key default} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set value [dict get $d $key]
    if {$value eq "null"} { return $default }
    return $value
}

proc ::vmdai::history::tree {} {
    variable win
    return $win.bg.tv
}

proc ::vmdai::history::message {} {
    variable win
    if {![winfo exists $win.bg.msg]} { return "" }
    return [$win.bg.msg cget -text]
}

proc ::vmdai::history::_message {text} {
    variable win
    if {[winfo exists $win.bg.msg]} { $win.bg.msg configure -text $text }
}

proc ::vmdai::history::open {} {
    variable win
    variable BUSY_TEXT
    if {[::vmdai::panel::bridge_busy]} {
        if {[winfo exists $::vmdai::panel::win]} { ::vmdai::statusbar::flash $BUSY_TEXT 3000 }
        return ""
    }
    if {![winfo exists $win]} { _build }
    _message ""
    fetch
    ::vmdai::panel::present $win
    return $win
}

proc ::vmdai::history::close {} {
    variable win
    if {[winfo exists $win]} { ::destroy $win }
}

proc ::vmdai::history::_build {} {
    variable win
    set C ::vmdai::theme::c
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD History"
    if {[winfo exists $::vmdai::panel::win]} { wm transient $win $::vmdai::panel::win }
    wm geometry $win 560x400
    wm minsize $win 380 240
    wm protocol $win WM_DELETE_WINDOW ::vmdai::history::close
    set f $win.bg
    ttk::frame $f -padding {12 12 12 10}
    pack $f -fill both -expand 1
    ttk::treeview $f.tv -columns {title updated messages} -show headings -selectmode browse
    $f.tv heading title -text Title -anchor w
    $f.tv heading updated -text Updated -anchor w
    $f.tv heading messages -text Messages -anchor e
    $f.tv column title -width 300 -stretch 1 -anchor w
    $f.tv column updated -width 120 -stretch 0 -anchor w
    $f.tv column messages -width 80 -stretch 0 -anchor e
    ttk::scrollbar $f.sb -orient vertical -command [list $f.tv yview]
    $f.tv configure -yscrollcommand [list $f.sb set]
    ttk::label $f.msg -text "" -font ChatMeta -foreground [$C warn]
    ttk::frame $f.foot
    ttk::button $f.foot.cancel -text Cancel -command ::vmdai::history::close
    ttk::button $f.foot.open -text Open -default active -command ::vmdai::history::resume_selected
    pack $f.foot.open $f.foot.cancel -side right -padx {8 0}
    grid $f.tv   -row 0 -column 0 -sticky nsew
    grid $f.sb   -row 0 -column 1 -sticky ns
    grid $f.msg  -row 1 -column 0 -columnspan 2 -sticky w -pady {6 0}
    grid $f.foot -row 2 -column 0 -columnspan 2 -sticky ew -pady {8 0}
    grid rowconfigure $f 0 -weight 1
    grid columnconfigure $f 0 -weight 1
    bind $f.tv <Double-1> {::vmdai::history::resume_selected; break}
    bind $win <Return> {::vmdai::history::resume_selected; break}
    bind $win <KP_Enter> {::vmdai::history::resume_selected; break}
    bind $win <Escape> {::vmdai::history::close; break}
}

proc ::vmdai::history::fetch {} {
    variable LIMIT
    variable gen
    incr gen
    ::vmdai::net::call chat.history.list [list offset i 0 limit i $LIMIT] \
        [list ::vmdai::history::_on_list $gen]
}

proc ::vmdai::history::_newer {a b} {
    return [string compare [_dget $b updated_at ""] [_dget $a updated_at ""]]
}

proc ::vmdai::history::_on_list {g form args} {
    variable gen
    variable win
    variable rows
    variable LIMIT
    if {$g != $gen || ![winfo exists $win]} { return }
    if {$form ne "ok"} {
        if {$form eq "rpc_error"} {
            _message "Could not list chats: [lindex $args 1]"
        } else {
            _message "Could not list chats: the runtime did not answer ([lindex $args 0])."
        }
        return
    }
    set items {}
    catch {set items [dict get [lindex $args 0] items]}
    set items [lsort -command ::vmdai::history::_newer $items]
    set rows [lrange $items 0 [expr {$LIMIT - 1}]]
    set tv [tree]
    $tv delete [$tv children {}]
    set now [clock seconds]
    set i 0
    foreach item $rows {
        set title [_dget $item title "New Chat"]
        $tv insert {} end -id row$i -values [list [ellipsize_middle $title TkDefaultFont 290] \
            [format_updated [_dget $item updated_at ""] $now] [_dget $item message_count 0]]
        incr i
    }
    if {[llength $rows]} {
        $tv selection set row0
        $tv focus row0
    } else {
        _message "No chats yet."
    }
}

# "Today 14:32", "Yesterday 09:10", "Mon 08:00" (within 6 days), "Sep 3"
# (this year) or "2025-12-31"; anything unparseable is shown as-is.
proc ::vmdai::history::format_updated {iso now} {
    if {[catch {clock scan $iso -format {%Y-%m-%dT%H:%M:%SZ} -timezone :UTC} t]} { return $iso }
    set day [clock format $t -format %Y-%m-%d]
    set hm [clock format $t -format %H:%M]
    if {$day eq [clock format $now -format %Y-%m-%d]} { return "Today $hm" }
    if {$day eq [clock format [clock add $now -1 day] -format %Y-%m-%d]} { return "Yesterday $hm" }
    if {$t <= $now && $now - $t < 6 * 86400} { return "[clock format $t -format %a] $hm" }
    if {[clock format $t -format %Y] eq [clock format $now -format %Y]} {
        set md [clock format $t -format "%b %d"]
        regsub { 0([0-9])$} $md { \1} md
        return $md
    }
    return $day
}

# Middle ellipsis by binary search, so both ends of a long title stay visible.
proc ::vmdai::history::ellipsize_middle {s font px} {
    if {[font measure $font $s] <= $px} { return $s }
    set lo 1
    set hi [expr {[string length $s] - 1}]
    set best "\u2026"
    while {$lo <= $hi} {
        set keep [expr {($lo + $hi) / 2}]
        set head [expr {($keep + 1) / 2}]
        set tail [expr {$keep - $head}]
        set candidate "[string range $s 0 [expr {$head - 1}]]\u2026"
        if {$tail > 0} { append candidate [string range $s end-[expr {$tail - 1}] end] }
        if {[font measure $font $candidate] <= $px} {
            set best $candidate
            set lo [expr {$keep + 1}]
        } else {
            set hi [expr {$keep - 1}]
        }
    }
    return $best
}

proc ::vmdai::history::resume_selected {} {
    variable rows
    variable win
    if {![winfo exists $win]} { return }
    set selected [lindex [[tree] selection] 0]
    if {$selected eq ""} { return }
    set chat_id [_dget [lindex $rows [string range $selected 3 end]] chat_id ""]
    if {$chat_id eq ""} { return }
    _message ""
    ::vmdai::bridge::resume $chat_id [list ::vmdai::history::_on_resume $chat_id]
}

proc ::vmdai::history::_on_resume {chat_id form args} {
    variable win
    variable LOCKED_TEXT
    if {![winfo exists $win]} { return }
    if {$form eq "ok"} {
        close
        return
    }
    if {$form eq "rpc_error"} {
        switch -- [lindex $args 0] {
            CHAT_LOCKED      { _message $LOCKED_TEXT }
            REQUEST_CONFLICT { _message "A request is running; stop it before opening another chat." }
            NOT_FOUND        { _message "This chat no longer exists." }
            default          { _message "Could not open this chat: [lindex $args 1]" }
        }
        return
    }
    _message "Could not open this chat: the runtime did not answer ([lindex $args 0])."
}
```

In `plugin/init.tcl`, add `history` to the Tk module list, directly after `settings`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_history.py tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: `4 passed` from the history file; the panel file (its guard now also checks every `::vmdai::history::` name the plugin calls) and lint pass.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+31 passed`, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add plugin/history.tcl plugin/init.tcl tests/tcl/test_history.tcl tests/test_tk_history.py
git commit -m "feat(plugin): History picker in ttk with the newest 50 chats and inline CHAT_LOCKED (P09-T06)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T07: Switch to v2 + long-poll; wire the view-model; retire ui.tcl

**Files:**
- Modify: `plugin/bridge.tcl` (788 lines at 6f5f937; rewritten by P06-T07 — edit at the anchors Task 0 Step 6 printed: the `event_protocol` initialiser, the `session.start` success branch, the `chat.events.poll` call and its re-arm delay, the per-event dispatch, the `chat.send` error branch, the reconcile path that reports "details may be missing", the `chat.resume` success branch; append new procs)
- Replace: `plugin/ui.tcl` (828 lines at 6f5f937; P06-T10's M1 version) with the shim below
- Delete: `tests/tcl/test_ui_min.tcl` and `tests/test_tk_ui_min.py` (P06-T10's six pytest tests: four behaviour tests of the retired M1 ui.tcl, `test_counts`, and `test_tk_helper_contract`; the behaviours' M2 successors are P08's `test_block_closes_on_role_request_turn_change`, P08-T09's status-bar folder segment, this plan's Settings dialog and `v2-runtime_state_to_banner_and_local_events`)
- Create: `tests/test_tk_helper.py` (keeps P06-T10's `test_tk_helper_contract`, the only direct test of the P06-T10 Tk helper module, alive after its file is deleted)
- Modify: `plugin/panel.tcl` (replace `render`, `new_chat` and `refresh_info`; add one line in `build`; append the wiring section)
- Create: `tests/tcl/test_bridge_v2.tcl`
- Test: `tests/test_tcl_bridge_v2.py`

**Interfaces:**
- Consumes: long-poll (P07-T06) — `chat.events.poll {…, wait_ms ≤ 2000}` and `session.start` → `capabilities.long_poll: true`; v2 events (P07-T01..T05) — `request.finished {request_id, status, …}`, per-turn `assistant/message {request_id, turn, final}`, `chat.history.get {chat_id, limit} -> {chat_id, manifest, events}` (the display log); vm, transcript, statusbar, banner (P08) — `::vmdai::vm::apply/init/local_event`, `::vmdai::transcript::apply_ops/clear/show_empty_state/hide_empty_state`, `::vmdai::statusbar::update`, `::vmdai::banner::on_runtime_state`, `::vmdai::tclexport::record request_id call_key command applied failed_index` and `reset` (P08-T11; nothing else feeds the ledger, so the panel does); `::vmdai::runtime::subscribe/state/info` (P06-T05); `::vmdai::config::poll_ms`, `request_timeout_ms`, `log` (P06-T02); `::vmdai::settings::reload`, `win` (P09-T04); `::vmdai::composer::clear_history` (P09-T03).
- Produces: `::vmdai::bridge::event_protocol = 2`; ui.tcl reduced to a shim: `show_panel` alias; `notify` becomes a VM local event. Also `::vmdai::bridge::negotiated` (the `event_protocol` the runtime granted), `long_poll`, `note_session result`, `poll_extra_params -> typed pairs`, `poll_timeout_ms`, `poll_delay_ms`, `route_display_event ev`, `send_failed code message`, `replay_history chat_id ?title?`, `_end_request request_id`; `::vmdai::panel::on_event ev`, `render ops` (now also hides the empty state and suppresses status ops during replay), `reset_view`, `_record_tcl ev` (with the array `commands`), `replay chat_id events ?title?`, `replaying`, `replayed`, `replay_synthetic`, `has_content`, `on_session_started result`, `refresh_info` (replaces P09-T01's), `on_runtime_state old new detail`, `empty_info`; `::vmdai::ui::seen_ready`, `::vmdai::ui::session_started result`, `::vmdai::ui::replay chat_id events title`, `::vmdai::ui::local_event kind fields`, `::vmdai::ui::_panel_ready`. `bridge.tcl` builds no view-model event itself: `viewmodel.tcl` is sourced only with Tk (P09-T01), and plan 06's tclsh tests source the bridge without it, so plugin-local events go through `::vmdai::ui::local_event`, a no-op without a panel.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_bridge_v2.tcl`:

```tcl
# P09-T07: event_protocol 2, long-poll, runtime-state wiring, NO_MODEL,
# history replay and a runtime restart while Settings is open. Runs under Tk
# because the wiring under test ends in the panel's Tk components; the
# transport is the harness's recording fake.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_PLUGIN_DIR) ui.tcl]
::harness::stub_desktop
proc ::vmdai::runtime::state {} { return $::harness::runtime_state }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 18765 pid 4242 version 0.3.0 protocol 2 \
        launch_token feedfacefeedfacefeedfacefeedface owned 0]
}

namespace eval ::test {
    variable ops {}
    variable modes {}
    variable status {}
    variable banner {}
}
# Record what reaches the components without replacing them.
proc ::test::record_ops {cmd op} { lappend ::test::ops {*}[lindex $cmd 1] }
proc ::test::record_mode {cmd op} { lappend ::test::modes [lindex $cmd 1] }
proc ::test::record_status {cmd op} { lappend ::test::status [lindex $cmd 1] }
trace add execution ::vmdai::transcript::apply_ops enter ::test::record_ops
trace add execution ::vmdai::composer::set_mode enter ::test::record_mode
trace add execution ::vmdai::statusbar::update enter ::test::record_status
proc ::vmdai::banner::on_runtime_state {old new detail} {
    lappend ::test::banner [list $old $new $detail]
}
proc ::test::kinds {} {
    set out {}
    foreach op $::test::ops { lappend out [lindex $op 0] }
    return $out
}

set ::SESSION [dict create session_id sess_1 session_token tok_1 event_protocol 2 \
    capabilities [dict create long_poll true] chat_id null defaults {} provider ollama \
    agent_loop true runtime [dict create version 0.3.0 pid 4242] \
    profile [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]
set ::INFO [dict create version 0.3.0 protocol 2 pid 4242 provider ollama model qwen3.8:27b \
    agent_loop true vision true tools {run_vmd_command capture_vmd_snapshot} rag false wiki false \
    max_turns 28 log_path /tmp/runtime.log settings_source file first_run [dict create servers {}]]
set ::PROFILES [dict create active qwen settings_source file profiles [dict create \
    qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]]

proc ::test::reset {} {
    ::vmdai::sched::teardown
    set ::harness::runtime_state ready
    ::harness::fresh_panel
    ::fake::reply chat.events.poll hold
    ::fake::reply runtime.info ok $::INFO
    ::fake::reply profiles.list ok $::PROFILES
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply session.set_cwd ok [dict create ok true cwd [pwd]]
    set ::test::ops {}
    set ::test::modes {}
    set ::test::status {}
    set ::test::banner {}
}
proc ::test::start {session} {
    ::test::reset
    ::fake::reply session.start ok $session
    ::vmdai::bridge::start_session
    ::harness::wait_until {expr {[::fake::count chat.events.poll] > 0}} 3000
}
proc ::test::event {role type text metadata} {
    return [dict create seq 1 ts 1790000000 role $role type $type text $text metadata $metadata]
}

test v2-event_protocol_2_negotiated {session.start asks for event_protocol 2 with the launch token} -body {
    ::test::start $::SESSION
    set p [lindex [::fake::calls_of session.start] 0]
    list [::fake::param $p event_protocol] [expr {[::fake::param $p launch_token] ne ""}] \
        [::fake::has_param $p vmd_env] $::vmdai::bridge::event_protocol $::vmdai::bridge::negotiated
} -result {2 1 1 2 2}

test v2-long_poll_used {with long_poll the poll waits up to 2000 ms; without, the M1 short-poll stays} -body {
    ::test::start $::SESSION
    set p [::fake::last chat.events.poll]
    set r [list [::fake::param $p wait_ms] [::fake::timeout_of chat.events.poll] [::vmdai::bridge::poll_delay_ms]]
    ::test::start [dict replace $::SESSION capabilities {}]
    set p [::fake::last chat.events.poll]
    lappend r [::fake::has_param $p wait_ms] [::fake::timeout_of chat.events.poll] \
        [expr {[::vmdai::bridge::poll_delay_ms] == $::vmdai::config::poll_ms}]
} -result {2000 5000 20 0 3000 1}

test v2-runtime_state_to_banner_and_local_events {runtime states drive the banner, the status bar and one local event per notice} -body {
    ::test::reset
    # The state machine updates its state before it tells subscribers.
    set ::harness::runtime_state reconnecting
    ::vmdai::panel::on_runtime_state ready reconnecting "Nothing answered on 127.0.0.1:18765"
    set ::vmdai::ui::seen_ready 1
    ::vmdai::ui::notify warn "Connection lost"
    set ::harness::runtime_state ready
    set connection {}
    foreach d $::test::status {
        if {[dict exists $d connection]} { lappend connection [dict get $d connection] }
    }
    list [lindex $::test::banner end] [expr {"reconnecting" in $connection}] \
        [expr {"notice" in [::test::kinds]}] [lindex $::test::modes end]
} -result [list [list ready reconnecting "Nothing answered on 127.0.0.1:18765"] 1 1 disabled]

test v2-no_model_card {chat.send NO_MODEL shows the card, keeps the draft and never goes busy} -body {
    ::test::start $::SESSION
    set ::test::ops {}
    ::fake::reply chat.send rpc_error NO_MODEL "No model configured" {}
    ::vmdai::composer::set_text "hello"
    ::vmdai::panel::on_send
    ::harness::wait_until {expr {"error.card" in [::test::kinds]}}
    set card [lindex $::test::ops [lsearch -index 0 $::test::ops error.card]]
    list [lindex $card 1] [lindex $::test::modes end] [dict get [::vmdai::bridge::state] busy] \
        [::vmdai::composer::get_text]
} -result {NO_MODEL nomodel 0 hello}

test v2-request_finished_ends_busy {only request.finished ends a v2 request; per-turn messages do not} -body {
    ::test::start $::SESSION
    set ::vmdai::bridge::busy 1
    set ::vmdai::bridge::request_id req_abc
    ::vmdai::panel::set_busy 1
    ::vmdai::bridge::route_display_event [::test::event assistant message "Loaded." \
        [dict create v 2 request_id req_abc turn 1 final false]]
    set mid [dict get [::vmdai::bridge::state] busy]
    ::vmdai::bridge::route_display_event [::test::event system state "" [dict create v 2 \
        kind request.finished request_id req_abc status complete wrapped_up false turns 1 \
        tool_calls 0 final_text_empty false duration_ms 900 usage {} error null run_dir ""]]
    list $mid [dict get [::vmdai::bridge::state] busy] [dict get [::vmdai::bridge::state] request_id] \
        [lindex $::test::modes end]
} -result {1 0 {} idle}

test v2-resume_replays_history {New chat shows the empty state; resume replays the display log, closes an unfinished request and rebuilds recall and the .tcl ledger} -body {
    ::test::start $::SESSION
    ::vmdai::panel::on_event [::test::event user message "Hello" [dict create request_id req_0]]
    set before_new [::vmdai::transcript::empty_state_shown]
    # The bridge's own new_chat is plan 06's and not under test here.
    proc ::vmdai::bridge::new_chat {args} {}
    ::vmdai::panel::new_chat
    set after_new [::vmdai::transcript::empty_state_shown]
    set events [list \
        [::test::event user message "Load 1hck" [dict create request_id req_1]] \
        [::test::event system state "" [dict create v 2 kind request.started request_id req_1 \
            chat_id chat_000000000001 provider ollama model qwen3.8:27b max_turns 28 vision true think true]] \
        [::test::event system state "" [dict create v 2 kind tool.started request_id req_1 turn 1 \
            call_key 0123456789ab tool_call_id call_1 tool_name run_vmd_command executor tcl origin model \
            input [dict create command "mol new 1hck.pdb" rationale "Load it"]]] \
        [::test::event system state "" [dict create v 2 kind tool.finished request_id req_1 \
            call_key 0123456789ab tool_name run_vmd_command executor tcl ok true executed yes output 0 \
            error "" truncated false duration_ms 40 statements [dict create total 1 applied 1 failed null] \
            blocked null output_path null output_bytes 1 image null saved_path null late false]] \
        [::test::event assistant message "Loaded 1hck." [dict create v 2 request_id req_1 turn 1 final true]] \
        [::test::event system state "" [dict create v 2 kind request.finished request_id req_1 \
            status complete wrapped_up false turns 2 tool_calls 1 final_text_empty false \
            duration_ms 3000 usage {} error null run_dir ""]] \
        [::test::event user message "Now color it" [dict create request_id req_2]] \
        [::test::event system state "" [dict create v 2 kind request.started request_id req_2 \
            chat_id chat_000000000001 provider ollama model qwen3.8:27b max_turns 28 vision true think true]]]
    ::fake::reply chat.history.get ok [dict create chat_id chat_000000000001 \
        manifest [dict create title "CDK2 view"] events $events]
    ::vmdai::bridge::replay_history chat_000000000001
    ::harness::wait_until {expr {$::vmdai::panel::replayed eq "chat_000000000001"}}
    set text [$::vmdai::panel::text get 1.0 end]
    list $before_new $after_new [string match "*Load 1hck*" $text] [string match "*Loaded 1hck.*" $text] \
        [string match "*Now color it*" $text] [string match "*Hello*" $text] $::vmdai::panel::title \
        [::fake::param [::fake::last chat.history.get] chat_id] $::vmdai::panel::replay_synthetic \
        $::vmdai::panel::replaying [::vmdai::transcript::empty_state_shown] $::vmdai::composer::recall \
        [string match "*mol new 1hck.pdb*" [::vmdai::tclexport::chat_tcl]]
} -result {0 1 1 1 1 0 {CDK2 view} chat_000000000001 local.request_ended 0 0 {{Load 1hck} {Now color it}} 1}

test v2-settings_after_restart {Settings reloads from the new runtime after a restart and Save works} -body {
    ::test::reset
    ::fake::reply profiles.list hold
    ::fake::reply models.list ok {models {} source server}
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::vmdai::settings::open
    ::harness::settle
    set held [llength $::fake::held]
    ::fake::reply profiles.list ok $::PROFILES
    ::vmdai::panel::on_runtime_state reconnecting ready ""
    set loaded [::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"}}]
    # The old runtime's profiles.list answer arrives late: it is dropped.
    lassign [lindex $::fake::held 0] method callback
    uplevel #0 [list {*}$callback ok [dict create active old settings_source file profiles \
        [dict create old [dict create provider ollama base_url http://127.0.0.1:1 model x options {}]]]]
    set kept [list $::vmdai::settings::v(profile) [dict exists $::vmdai::settings::profiles old]]
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    list $held $loaded $kept [::fake::param [::fake::last provider.set] profile]
} -result {1 1 {qwen 0} qwen}

cleanupTests
```

Create `tests/test_tcl_bridge_v2.py`:

```python
"""P09-T07: the v2 switch, long-poll, view-model wiring and the ui.tcl shim."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TOTAL = 7


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_bridge_v2.tcl")


def test_event_protocol_2_negotiated(results):
    assert_case(results, "v2-event_protocol_2_negotiated", TOTAL)


def test_long_poll_used(results):
    assert_case(results, "v2-long_poll_used", TOTAL)


def test_runtime_state_to_banner_and_local_events(results):
    assert_case(results, "v2-runtime_state_to_banner_and_local_events", TOTAL)


def test_no_model_card(results):
    assert_case(results, "v2-no_model_card", TOTAL)


def test_request_finished_ends_busy(results):
    assert_case(results, "v2-request_finished_ends_busy", TOTAL)


def test_resume_replays_history(results):
    assert_case(results, "v2-resume_replays_history", TOTAL)


def test_settings_after_restart(results):
    assert_case(results, "v2-settings_after_restart", TOTAL)


def test_ui_shim_covers_callers():
    """ui.tcl is a small shim that still defines every ::vmdai::ui:: name used elsewhere."""
    shim = (PLUGIN / "ui.tcl").read_text(encoding="utf-8")
    defined = set(re.findall(r"^proc\s+::vmdai::ui::(\w+)", shim, re.MULTILINE))
    defined |= set(re.findall(r"\bvariable\s+(\w+)", shim))
    used = set()
    for path in PLUGIN.glob("*.tcl"):
        if path.name != "ui.tcl":
            used |= set(re.findall(r"::vmdai::ui::(\w+)", path.read_text(encoding="utf-8")))
    assert sorted(used - defined) == []
    assert len(shim.splitlines()) < 80
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_bridge_v2.py -q`
Expected: `8 failed` — the tcltest output shows `2` expected but `1` for `event_protocol`, `can't read "::vmdai::bridge::negotiated"`, `invalid command name "::vmdai::panel::on_runtime_state"`, `"::vmdai::panel::on_event"`, `"::vmdai::bridge::route_display_event"`; `test_ui_shim_covers_callers` fails on the 80-line limit (the M1 ui.tcl is several hundred lines).

- [ ] **Step 3: Switch the bridge to v2 and long-poll**

In `plugin/bridge.tcl`:

1. Replace the `event_protocol` initialiser (P06: `variable event_protocol 1`, possibly inside an `if {![info exists …]}`) with this block inside `namespace eval ::vmdai::bridge`:

```tcl
    # M2 asks for the display events (section 2c). A constant: re-sourcing resets it.
    variable event_protocol 2
    if {![info exists ::vmdai::bridge::negotiated]} { variable negotiated 1 }
    if {![info exists ::vmdai::bridge::long_poll]} { variable long_poll 0 }
```

2. In the success branch of the `session.start` callback (the code that stores `session_id`/`session_token` from the result), add `::vmdai::bridge::note_session $result` as its first statement and `::vmdai::ui::session_started $result` as its last statement (use the callback's own name for the result dict if it is not `result`). bridge.tcl reaches the panel only through `::vmdai::ui::*`, so it still runs under tclsh without Tk.

3. Where the pump calls `::vmdai::net::call chat.events.poll`: append `{*}[::vmdai::bridge::poll_extra_params]` to its parameter list, replace its `-timeout` value with `[::vmdai::bridge::poll_timeout_ms]` (add `-timeout [::vmdai::bridge::poll_timeout_ms]` if the call has none), and replace the delay that re-arms the next poll when there is no `has_more` (`$::vmdai::config::poll_ms` in P06) with `[::vmdai::bridge::poll_delay_ms]`.

4. In the per-event dispatch, replace the call that hands non-`tool_start` events to `::vmdai::ui::render_event $ev` with `::vmdai::bridge::route_display_event $ev` (use the dispatch loop's own variable name), and delete P06's v1 end-of-request detection next to it (the code that marks the request idle on a final `assistant/message`, a `cancelled` lifecycle event or an `error` event): `route_display_event` now owns it. Leave the `tool_start` branch and its deferral while `::vmdai::executor::executing` is set untouched.

5. In the `rpc_error` branch of the `chat.send` callback, add `::vmdai::bridge::send_failed $code $message` (with the branch's own names for the code and message).

6. In the reconcile path that reports "Request ended (details may be missing)" when `runtime.info` shows no active request, replace that `::vmdai::ui::notify …` call with
   `::vmdai::ui::local_event local.request_ended [dict create request_id $rid]`, where `$rid` is the request id being ended (keep the code that marks the bridge idle; the view-model's `local.request_ended` prints the same note).

7. In the success branch of `::vmdai::bridge::resume` (after P06 has switched `chat_id` and `after_seq`, before it runs the caller's callback), add `::vmdai::bridge::replay_history $chat_id $title` with the resumed chat id and the result's `title` (empty string if the result has none). Only a user-chosen resume replays: `::vmdai::bridge::recover` (P06-T06: `session.start` + `chat.resume` of the same chat after a new pid or `AUTH_FAILED`) must not, because the transcript already shows that chat and its connection notes (S3). If P06's `recover` calls `::vmdai::bridge::resume`, give `resume` an optional trailing argument `{replay 1}`, pass `0` from `recover`, and guard the call with `if {$replay}`.

8. Append:

```tcl
# ===========================================================================
# M2: event_protocol 2, long-poll, v2 request tracking, replay (P09-T07).
# ===========================================================================

# Record what the runtime granted in session.start.
proc ::vmdai::bridge::note_session {result} {
    variable negotiated
    variable long_poll
    set negotiated 1
    catch {set negotiated [dict get $result event_protocol]}
    set long_poll 0
    if {[dict exists $result capabilities long_poll]} {
        set long_poll [string is true -strict [dict get $result capabilities long_poll]]
    }
}

proc ::vmdai::bridge::poll_extra_params {} {
    variable long_poll
    if {$long_poll} { return [list wait_ms i 2000] }
    return {}
}

# chat.events.poll: wait_ms + 3000 with long-poll, else the default timeout.
proc ::vmdai::bridge::poll_timeout_ms {} {
    variable long_poll
    if {$long_poll} { return 5000 }
    return $::vmdai::config::request_timeout_ms
}

# With long-poll the runtime blocks up to 2 s, so the next poll goes out
# almost at once (20 ms keeps a misbehaving server from spinning us).
proc ::vmdai::bridge::poll_delay_ms {} {
    variable long_poll
    if {$long_poll} { return 20 }
    return $::vmdai::config::poll_ms
}

# Every event except tool_start goes to the panel; a v2 request ends only on
# its request.finished (per-turn assistant/message events do not end it).
proc ::vmdai::bridge::route_display_event {ev} {
    variable negotiated
    variable request_id
    set role ""
    set type ""
    set text ""
    set md {}
    catch {set role [dict get $ev role]}
    catch {set type [dict get $ev type]}
    catch {set text [dict get $ev text]}
    catch {set md [dict get $ev metadata]}
    set rid ""
    set kind ""
    catch {set rid [dict get $md request_id]}
    catch {set kind [dict get $md kind]}
    if {$negotiated >= 2} {
        set ends [expr {$kind eq "request.finished"}]
    } else {
        set ends [expr {($role eq "assistant" && $type eq "message") || $role eq "error"
            || ($role eq "system" && $type eq "lifecycle" && $text eq "cancelled")}]
    }
    ::vmdai::ui::render_event $ev
    if {$ends && $request_id ne "" && ($rid eq "" || $rid eq $request_id)} {
        _end_request $request_id
    }
}

proc ::vmdai::bridge::_end_request {rid} {
    variable busy
    variable request_id
    if {$request_id ne $rid} { return }
    set busy 0
    set request_id ""
    ::vmdai::ui::set_busy 0
}

# chat.send failed before a request existed (NO_MODEL, REQUEST_CONFLICT, ...).
proc ::vmdai::bridge::send_failed {code message} {
    ::vmdai::ui::local_event local.send_failed [dict create code $code message $message]
}

# Resume shows the same rows as the live chat: the display log goes through
# the view-model again (section 2c Persistence). It is never routed to the executor.
proc ::vmdai::bridge::replay_history {chat_id {title ""}} {
    ::vmdai::net::call chat.history.get [list chat_id s $chat_id limit i 5000] \
        [list ::vmdai::bridge::_on_history $chat_id $title]
}

proc ::vmdai::bridge::_on_history {chat_id title form args} {
    if {$form ne "ok"} {
        ::vmdai::ui::status "Could not load this chat's history."
        return
    }
    set result [lindex $args 0]
    set events {}
    catch {set events [dict get $result events]}
    if {$title eq ""} { catch {set title [dict get $result manifest title]} }
    ::vmdai::ui::replay $chat_id $events $title
}
```

- [ ] **Step 4: Replace `plugin/ui.tcl` with the shim**

Replace the whole of `plugin/ui.tcl` with:

```tcl
# ui.tcl - M2 compatibility shim (section 2h). The M1 panel is retired: panel.tcl
# and the plan-08 components draw everything. These names stay because
# bridge.tcl, runtime.tcl and executor.tcl call them; without Tk or without
# a panel window (the tclsh bridge driver) they do nothing.
namespace eval ::vmdai::ui {
    if {![info exists ::vmdai::ui::seen_ready]} { variable seen_ready 0 }
}

proc ::vmdai::ui::_panel_ready {} {
    return [expr {[info commands ::winfo] ne "" && [info commands ::vmdai::panel::on_event] ne ""
        && [winfo exists $::vmdai::panel::win]}]
}

proc ::vmdai::ui::show_panel {} {
    return [::vmdai::panel::show]
}

proc ::vmdai::ui::render_event {event} {
    if {[_panel_ready]} { ::vmdai::panel::on_event $event }
}

proc ::vmdai::ui::session_started {result} {
    if {[_panel_ready]} { ::vmdai::panel::on_session_started $result }
}

proc ::vmdai::ui::replay {chat_id events title} {
    if {[_panel_ready]} { ::vmdai::panel::replay $chat_id $events $title }
}

# A plugin-local event (local.send_failed, local.request_ended). The
# view-model builds it, so nothing happens without a panel.
proc ::vmdai::ui::local_event {kind fields} {
    if {[_panel_ready]} { ::vmdai::panel::on_event [::vmdai::vm::local_event $kind $fields] }
}

# The connection state machine's one-notice-per-transition sink (S3). It
# becomes a local.connection event for the view-model; the first connect
# after launch is not a notice.
proc ::vmdai::ui::notify {level text} {
    variable seen_ready
    if {![_panel_ready]} { return }
    set state [::vmdai::runtime::state]
    if {!$seen_ready} {
        if {$state eq "ready"} { set seen_ready 1 }
        if {$state ne "down"} { return }
    }
    set lost [expr {$state eq "ready" && [::vmdai::panel::bridge_busy]}]
    ::vmdai::panel::on_event [::vmdai::vm::local_event local.connection \
        [dict create state $state detail $text request_lost $lost]]
}

proc ::vmdai::ui::set_busy {on} {
    if {[_panel_ready]} { ::vmdai::panel::set_busy $on }
}

proc ::vmdai::ui::status {text} {
    if {[_panel_ready]} { ::vmdai::statusbar::flash $text 3000 }
}
```

If Task 0 Step 6 listed another `::vmdai::ui::` name used outside ui.tcl, add a forwarding proc for it here; `test_ui_shim_covers_callers` fails until every name is covered.

- [ ] **Step 5: Wire the view-model in `plugin/panel.tcl`**

Replace `proc ::vmdai::panel::render` with:

```tcl
proc ::vmdai::panel::render {ops} {
    variable nomodel
    variable replaying
    set batch {}
    foreach op $ops {
        switch -- [lindex $op 0] {
            status {
                if {!$replaying} { _apply_status $op }
            }
            error.card {
                lappend batch $op
                if {[lindex $op 1] eq "NO_MODEL"} {
                    set nomodel 1
                    _sync_composer
                }
            }
            default { lappend batch $op }
        }
    }
    if {[llength $batch]} { _apply_transcript $batch }
}
```

Replace `proc ::vmdai::panel::new_chat` with:

```tcl
# A new chat is empty, so it shows the empty state again once the runtime
# has answered runtime.info.
proc ::vmdai::panel::new_chat {} {
    variable rt_info
    variable text
    if {[bridge_busy]} { return }
    reset_view
    ::vmdai::bridge::new_chat
    if {[dict size $rt_info]} { ::vmdai::transcript::show_empty_state [empty_info] $text }
}
```

Replace `proc ::vmdai::panel::refresh_info` (P09-T01's status-bar-only version) with:

```tcl
proc ::vmdai::panel::refresh_info {} {
    ::vmdai::net::call runtime.info {} [list ::vmdai::panel::_on_info]
    ::vmdai::net::call profiles.list {} [list ::vmdai::panel::_on_profiles]
}
```

In `proc ::vmdai::panel::build`, insert directly before `bind_keys`:

```tcl
    ::vmdai::runtime::subscribe ::vmdai::panel::on_runtime_state
```

Append:

```tcl
# ---- view-model wiring (P09-T07) -------------------------------------------------

namespace eval ::vmdai::panel {
    if {![info exists ::vmdai::panel::replaying]} { variable replaying 0 }
    if {![info exists ::vmdai::panel::replayed]} { variable replayed "" }
    if {![info exists ::vmdai::panel::replay_synthetic]} { variable replay_synthetic {} }
    if {![info exists ::vmdai::panel::has_content]} { variable has_content 0 }
    # call_key -> {request_id command} of the Tcl commands this view has seen.
    if {![array exists ::vmdai::panel::commands]} {
        variable commands
        array set commands {}
    }
}

# Every display event (live, local or replayed) enters here.
proc ::vmdai::panel::on_event {ev} {
    variable win
    variable last_sent
    if {![winfo exists $win]} { return }
    render [::vmdai::vm::apply ::vmdai::panel::vm $ev]
    _record_tcl $ev
    set kind ""
    catch {set kind [dict get $ev metadata kind]}
    if {$kind eq "local.send_failed" && $last_sent ne "" && [::vmdai::composer::get_text] eq ""} {
        ::vmdai::composer::set_text $last_sent
    }
}

# Feed the Copy/Save .tcl ledger (P08-T11) from the display events: the
# command comes from tool.started, the statement counts from tool.finished
# (a late tool.finished records again, so the ledger follows the late result).
# Replay goes through here too, so a resumed chat's ledger is rebuilt.
proc ::vmdai::panel::_record_tcl {ev} {
    variable commands
    set md {}
    set kind ""
    set key ""
    catch {set md [dict get $ev metadata]}
    catch {set kind [dict get $md kind]}
    catch {set key [dict get $md call_key]}
    if {$key eq "" || $kind ni {tool.started tool.finished}} { return }
    if {$kind eq "tool.started"} {
        set command ""
        set executor tcl
        catch {set command [dict get $md input command]}
        catch {set executor [dict get $md executor]}
        if {$command ne "" && $executor eq "tcl"} {
            set rid ""
            catch {set rid [dict get $md request_id]}
            set commands($key) [list $rid $command]
        }
        return
    }
    if {![info exists commands($key)]} { return }
    lassign $commands($key) rid command
    set applied 0
    set failed_index ""
    catch {set applied [dict get $md statements applied]}
    catch {set failed_index [dict get $md statements failed index]}
    if {![string is integer -strict $applied]} { set applied 0 }
    if {![string is integer -strict $failed_index]} { set failed_index "" }
    if {[catch {::vmdai::tclexport::record $rid $key $command $applied $failed_index} err]} {
        ::vmdai::config::log "panel: tclexport::record failed for $key: $err"
    }
}

proc ::vmdai::panel::_apply_transcript {ops} {
    variable has_content
    set has_content 1
    ::vmdai::transcript::hide_empty_state
    ::vmdai::transcript::apply_ops $ops
}

# A fresh view: New chat, and before a resumed chat is replayed.
proc ::vmdai::panel::reset_view {} {
    variable has_content
    variable nomodel
    variable stopping
    set has_content 0
    set nomodel 0
    set stopping 0
    ::vmdai::transcript::hide_empty_state
    ::vmdai::transcript::clear
    ::vmdai::vm::init ::vmdai::panel::vm
    ::vmdai::tclexport::reset
    array unset ::vmdai::panel::commands
    ::vmdai::composer::clear_history
    set_title "New chat"
    _sync_composer
}

# Replay a chat's display log. A request with request.started but no
# request.finished (the runtime died) is closed with local.request_ended.
# The chat's own prompts go back into Up/Down recall (V5 "in this chat").
proc ::vmdai::panel::replay {chat_id events {title ""}} {
    variable replaying
    variable replayed
    variable replay_synthetic
    reset_view
    set replaying 1
    set replay_synthetic {}
    set open ""
    foreach ev $events {
        set kind ""
        set rid ""
        set role ""
        catch {set kind [dict get $ev metadata kind]}
        catch {set rid [dict get $ev metadata request_id]}
        catch {set role [dict get $ev role]}
        if {$role eq "user" && [dict exists $ev text]} {
            ::vmdai::composer::push_history [dict get $ev text]
        }
        if {$kind eq "request.started"} { set open $rid }
        if {$kind eq "request.finished" && $rid eq $open} { set open "" }
        if {[catch {on_event $ev} err]} {
            ::vmdai::config::log "panel: replay skipped an event: $err"
        }
    }
    if {$open ne ""} {
        lappend replay_synthetic local.request_ended
        on_event [::vmdai::vm::local_event local.request_ended [dict create request_id $open]]
    }
    set replaying 0
    if {$title ne ""} { set_title $title }
    set replayed $chat_id
}

proc ::vmdai::panel::on_session_started {result} {
    variable win
    if {![winfo exists $win]} { return }
    refresh_info
}

proc ::vmdai::panel::_on_info {form args} {
    variable win
    variable rt_info
    variable has_content
    variable nomodel
    variable text
    if {$form ne "ok" || ![winfo exists $win]} { return }
    set rt_info [lindex $args 0]
    set model ""
    set loop 0
    catch {set model [dict get $rt_info model]}
    catch {set loop [string is true -strict [dict get $rt_info agent_loop]]}
    set nomodel [expr {$model eq "" || $model eq "null" || !$loop}]
    _sync_composer
    _update_status
    if {!$has_content} { ::vmdai::transcript::show_empty_state [empty_info] $text }
}

proc ::vmdai::panel::_on_profiles {form args} {
    variable server_host
    if {$form ne "ok"} { return }
    set r [lindex $args 0]
    set active ""
    set url ""
    catch {set active [dict get $r active]}
    catch {set url [dict get $r profiles $active base_url]}
    set server_host [expr {$url eq "" || $url eq "null" ? "" : [hostport $url]}]
    _update_status
}

# runtime.info plus what the empty state's Ready group shows.
proc ::vmdai::panel::empty_info {} {
    variable rt_info
    set info $rt_info
    set endpoint ""
    catch {
        set rt [::vmdai::runtime::info]
        set endpoint "[dict get $rt host]:[dict get $rt port]"
    }
    dict set info connected [expr {[::vmdai::runtime::state] eq "ready"}]
    dict set info endpoint $endpoint
    dict set info folder [pwd]
    dict set info runs [run_count]
    return $info
}

# runtime::subscribe callback: banner, status bar, composer, and a reload of
# an open Settings dialog once a (possibly new) runtime is ready again.
proc ::vmdai::panel::on_runtime_state {old new detail} {
    variable win
    if {![winfo exists $win]} { return }
    ::vmdai::banner::on_runtime_state $old $new $detail
    _sync_composer
    _update_status
    if {$new eq "ready" && $old ne "ready" && [winfo exists $::vmdai::settings::win]} {
        ::vmdai::settings::reload
    }
}
```

- [ ] **Step 6: Move the Tk helper contract test, then run the tests to verify they pass**

`tests/test_tk_ui_min.py` is deleted in Step 7, and its `test_tk_helper_contract` is the only direct test of `tests/helpers/tk.py` (P06-T10). Create `tests/test_tk_helper.py` with that test, unchanged apart from its imports:

```python
"""Direct contract test of tests/helpers/tk.py (moved from P06-T10's
tests/test_tk_ui_min.py when P09-T07 retired the M1 ui.tcl)."""
from __future__ import annotations

from helpers import tk
from helpers.tcl import REPO


def test_tk_helper_contract(monkeypatch):
    assert tk.golden_path("x") == REPO / "tests" / "fixtures" / "tk" / "x.txt"
    assert "load " in tk.tk_prelude() and " Tk\n" in tk.tk_prelude()
    assert tk.tk_prelude().endswith("wm withdraw .\n")
    monkeypatch.setenv("CHATVMD_UPDATE_GOLDENS", "1")
    assert tk.update_goldens() is True
    monkeypatch.delenv("CHATVMD_UPDATE_GOLDENS")
    assert tk.update_goldens() is False
```

Run: `python -m pytest tests/test_tk_helper.py -q`
Expected: `1 passed` (it needs no Tk session, so it also passes in CI).

Run: `python -m pytest tests/test_tcl_bridge_v2.py tests/test_tk_panel.py tests/test_tk_keymap.py tests/test_tk_settings.py tests/test_tk_history.py tests/test_tk_empty_state.py tests/test_tcl_lint.py -q`
Expected: all pass (`8 passed` from `test_tcl_bridge_v2.py`).

Run: `python -m pytest tests -q -k "bridge or runtime or state_machine or executor or net" 2>&1 | tail -3`
Expected: plan 06's tclsh bridge, runtime, state-machine, executor and net tests still pass. If a P06 bridge test asserted `event_protocol 1` in the session.start body, update that one expectation to `2` (M2 sends 2 by design, §2c Stage split) in the same commit. If a P06 tclsh test counted notices through state that the M1 `ui.tcl` kept (the shim keeps none and is a no-op without a panel), count calls instead with `trace add execution ::vmdai::ui::notify enter <recorder>` and commit that file too; the S3 rule (one notice per transition) is unchanged.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+34 passed`, 0 failed (+8 from `test_tcl_bridge_v2.py`, +1 for the moved `test_tk_helper.py`, −6 for the deleted `test_tk_ui_min.py`: its four behaviour tests, `test_counts` and `test_tk_helper_contract`). If `test_tk_ui_min.py` was skipping because no Tk session was available, the deletion removes 5 skips and 1 pass instead; the pass count is then 5 lower than with Tk, as for every Tk test in this plan.

- [ ] **Step 7: Commit**

```bash
git rm tests/tcl/test_ui_min.tcl tests/test_tk_ui_min.py
git add plugin/bridge.tcl plugin/ui.tcl plugin/panel.tcl tests/tcl/test_bridge_v2.tcl tests/test_tcl_bridge_v2.py tests/test_tk_helper.py
git commit -m "feat(plugin): event_protocol 2 with long-poll, v2 request tracking and history replay; ui.tcl becomes a shim (P09-T07)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

If Step 6 required updating a plan-06 test (the `event_protocol` expectation or a notice count), add that test file to the `git add` line.

---

### Task P09-T08: Reasoning display and wiki toggle

**Files:**
- Modify: `plugin/transcript.tcl` (append the reasoning section)
- Modify: `plugin/panel.tcl` (replace `render` and `on_session_started`; add one line to `reset_view`; append the reasoning section)
- Modify: `plugin/settings.tcl` (`PERSISTED_FIELDS`, `_build_panel`, `_after_persisted`)
- Create: `tests/tcl/test_reasoning_display.tcl`
- Test: `tests/test_tk_reasoning_display.py`

**Interfaces:**
- Consumes: reasoning ops (P08-T01) — `{reasoning.open b turn}`, `{reasoning.append b text}`, `{reasoning.seal b duration_s}`; the work-log tag helper `::vmdai::transcript::_wl` (P08-T05: `wl:$run` of the run that `{run.open …}` made current, P08-T06); reasoning_visible (P03-T09) — `settings.set {patch:{reasoning_visible}}` persists it and the empty patch reads it; the wiki toggle and the `PERSISTED_FIELDS` mechanism (P09-T05); `::vmdai::sched::after`, `cancel`, `pending` (P06-T02); `::vmdai::panel::render`, `reset_view`, `replaying`, `has_content`, `on_session_started` (P09-T07).
- Produces: reasoning visibility follows the reasoning_visible setting. Also `::vmdai::transcript::reasoning_open t b turn ?live?`, `reasoning_append t b text`, `reasoning_seal t b duration_s`, `reasoning_tick t b ?now?`, `reasoning_toggle t b`, `set_reasoning_visible t on`, `reasoning_reset ?t?`, the array `::vmdai::transcript::R` and the font `ChatMetaItal`; `::vmdai::panel::set_reasoning_visible on`, `reasoning_visible`, `_load_persisted`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_reasoning_display.tcl`:

```tcl
# P09-T08: reasoning display (Part B V4 "Reasoning") and its Settings toggle.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::test {}
proc ::test::fresh {} {
    ::harness::fresh_panel
    ::vmdai::transcript::reasoning_reset $::vmdai::panel::text
    ::vmdai::panel::set_reasoning_visible 1
    return $::vmdai::panel::text
}
proc ::test::head {t b} {
    return [string trimright [$t get {*}[$t tag ranges rhead:$b]] "\n"]
}
proc ::test::shown {t} {
    return [$t get -displaychars 1.0 end]
}

test reasoning-thinking_timer {streaming reasoning is one line that counts seconds} -body {
    set t [::test::fresh]
    ::vmdai::transcript::reasoning_open $t b1 1
    set t0 $::vmdai::transcript::R(b1,t0)
    set r [list [::test::head $t b1] [expr {$::vmdai::transcript::R(b1,timer) in [::vmdai::sched::pending]}]]
    ::vmdai::transcript::reasoning_tick $t b1 [expr {$t0 + 3}]
    lappend r [::test::head $t b1]
    ::vmdai::transcript::reasoning_tick $t b1 [expr {$t0 + 75}]
    lappend r [::test::head $t b1] [string match "*Thinking*" [::test::shown $t]]
} -result [list "Thinking\u2026 00:00" 1 "Thinking\u2026 00:03" "Thinking\u2026 01:15" 1]

test reasoning-thought_for_expand {sealed: "Thought for N s" expands to the text and collapses again} -body {
    set t [::test::fresh]
    ::vmdai::transcript::reasoning_open $t b1 1
    ::vmdai::transcript::reasoning_append $t b1 "Check the selection first."
    set timer $::vmdai::transcript::R(b1,timer)
    ::vmdai::transcript::reasoning_seal $t b1 3.4
    set r [list [::test::head $t b1] [$t tag cget rbody:b1 -elide] \
        [string match "*Check the selection*" [::test::shown $t]] \
        [expr {$timer in [::vmdai::sched::pending]}]]
    uplevel #0 [$t tag bind rhead:b1 <ButtonRelease-1>]
    lappend r [::test::head $t b1] [string match "*Check the selection*" [::test::shown $t]]
    uplevel #0 [$t tag bind rhead:b1 <ButtonRelease-1>]
    lappend r [::test::head $t b1]
} -result [list "Thought for 3 s \u25b8" 1 0 0 "Thought for 3 s \u25be" 1 "Thought for 3 s \u25b8"]

test reasoning-hidden_when_off {reasoning_visible off hides every reasoning line, old and new; lines join their run's work log} -body {
    set t [::test::fresh]
    ::vmdai::panel::render [list {run.open r1 req_1 qwen3.8:27b 0} {reasoning.open b1 1} \
        {reasoning.append b1 "hidden thoughts"} {reasoning.seal b1 2}]
    set r [list [string match "*Thought for 2 s*" [::test::shown $t]]]
    ::vmdai::panel::set_reasoning_visible 0
    lappend r [string match "*Thought for*" [::test::shown $t]]
    ::vmdai::panel::render [list {reasoning.open b2 2}]
    lappend r [string match "*Thinking*" [::test::shown $t]]
    ::vmdai::panel::set_reasoning_visible 1
    lappend r [string match "*Thought for 2 s*" [::test::shown $t]] \
        [string match "*hidden thoughts*" [::test::shown $t]] [string match "*Thinking*" [::test::shown $t]] \
        [expr {"wl:r1" in [$t tag names [lindex [$t tag ranges rhead:b1] 0]]}] \
        [expr {"wl:r1" in [$t tag names [lindex [$t tag ranges rbody:b1] 0]]}]
} -result {1 0 0 1 0 1 1 1}

test reasoning-setting_saved {"Show model reasoning" is persisted and applied at once} -body {
    ::harness::fresh_panel
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b options {}]]]
    ::fake::reply models.list ok {models {} source server}
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply provider.set ok {ok true}
    ::vmdai::panel::set_reasoning_visible 1
    ::vmdai::settings::open panel
    ::harness::wait_until {expr {[dict size $::vmdai::settings::persisted] > 0
        && $::vmdai::settings::v(profile) eq "qwen"}}
    set r [list $::vmdai::settings::v(reasoning) [winfo manager [::vmdai::settings::tab panel].reasoning]]
    set ::vmdai::settings::v(reasoning) 0
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    lappend r [::fake::param [::fake::last settings.set] patch] $::vmdai::panel::reasoning_visible
} -result {1 grid {{"reasoning_visible":false}} 0}

cleanupTests
```

Create `tests/test_tk_reasoning_display.py`:

```python
"""P09-T08: reasoning display (Part B V4) and the Settings toggle."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 4


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_reasoning_display.tcl")


def test_thinking_timer(results):
    assert_case(results, "reasoning-thinking_timer", TOTAL)


def test_thought_for_expand(results):
    assert_case(results, "reasoning-thought_for_expand", TOTAL)


def test_hidden_when_off(results):
    assert_case(results, "reasoning-hidden_when_off", TOTAL)


def test_setting_saved(results):
    assert_case(results, "reasoning-setting_saved", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_reasoning_display.py -q`
Expected: `4 failed`; the output shows `invalid command name "::vmdai::transcript::reasoning_reset"`.

- [ ] **Step 3: Append the reasoning display to `plugin/transcript.tcl`**

Append to `plugin/transcript.tcl`:

```tcl
# ===========================================================================
# Reasoning display (Part B V4 "Reasoning"; P09-T08).
#
# While a turn streams, its reasoning is one muted italic line
# "Thinking... 00:03" that ticks every second; the text itself is collected,
# hidden, underneath. Sealed, the line becomes "Thought for 3 s >" and a
# click expands the muted, indented text. Reasoning is always its own
# lines, so it never shares a block with the answer. The tag `reasoning`
# covers every reasoning line, so set_reasoning_visible hides them all.
#
# Writes go through a hidden peer of the transcript text: the read-only
# proxy (Part B V4) rejects insert/delete but passes `peer`, and a peer
# shares the text, tags and marks.
# ===========================================================================
namespace eval ::vmdai::transcript {
    if {![array exists ::vmdai::transcript::R]} {
        variable R
        array set R {}
    }
    if {![info exists ::vmdai::transcript::reasoning_hidden]} { variable reasoning_hidden 0 }
}

proc ::vmdai::transcript::_rw {t} {
    set peer $t.__rw
    if {![winfo exists $peer]} { $t peer create $peer }
    return $peer
}

proc ::vmdai::transcript::_reasoning_tags {t} {
    set C ::vmdai::theme::c
    if {[lsearch -exact [font names] ChatMetaItal] < 0} {
        font create ChatMetaItal {*}[font actual ChatMeta] -slant italic
    }
    $t tag configure rhead -font ChatMetaItal -foreground [$C muted] -spacing1 6 -spacing3 4
    $t tag configure rbody -font ChatMeta -foreground [$C muted] -lmargin1 24 -lmargin2 24 -spacing3 6
}

proc ::vmdai::transcript::reasoning_open {t b turn {live 1}} {
    variable R
    variable reasoning_hidden
    _reasoning_tags $t
    set w [_rw $t]
    set bottom [expr {[lindex [$t yview] 1] >= 0.999}]
    if {[$w index "end -1c"] ne "1.0" && [$w get "end -2c"] ne "\n"} { $w insert end "\n" }
    set start [$w index "end -1c"]
    # Inside a run's work log the lines also carry wl:$run (plan 08's
    # _wl), so the run's collapse hides its reasoning with its rows.
    set wl {}
    catch {set wl [_wl]}
    set head_tags [concat reasoning rhead rhead:$b $wl]
    set body_tags [concat reasoning rbody rbody:$b $wl]
    $w insert end "Thinking\u2026 00:00" $head_tags "\n" $head_tags
    $w mark set rs:$b $start
    $w mark gravity rs:$b left
    $w mark set re:$b "$start lineend"
    $w mark gravity re:$b right
    set body [$w index "end -1c"]
    $w insert end "\n" $body_tags
    $w mark set rb:$b $body
    $w mark gravity rb:$b right
    $t tag configure rbody:$b -elide 1
    $t tag bind rhead:$b <ButtonRelease-1> [list ::vmdai::transcript::reasoning_toggle $t $b]
    $t tag bind rhead:$b <Enter> [list $t configure -cursor hand2]
    $t tag bind rhead:$b <Leave> [list $t configure -cursor arrow]
    array set R [list $b,t0 [clock seconds] $b,sealed 0 $b,open 0 $b,secs 0 $b,timer "" \
        $b,head $head_tags $b,body $body_tags]
    if {$live} {
        set R($b,timer) [::vmdai::sched::after 1000 [list ::vmdai::transcript::reasoning_tick $t $b]]
    }
    if {$reasoning_hidden} { $t tag raise reasoning }
    if {$bottom} { $t see end }
}

proc ::vmdai::transcript::reasoning_append {t b chunk} {
    variable R
    if {![info exists R($b,t0)]} { return }
    [_rw $t] insert rb:$b $chunk $R($b,body)
}

proc ::vmdai::transcript::reasoning_seal {t b duration_s} {
    variable R
    if {![info exists R($b,t0)]} { return }
    if {$R($b,timer) ne ""} {
        ::vmdai::sched::cancel $R($b,timer)
        set R($b,timer) ""
    }
    set secs 1
    if {[string is double -strict $duration_s]} { set secs [expr {int(round($duration_s))}] }
    if {$secs < 1} { set secs 1 }
    set R($b,secs) $secs
    set R($b,sealed) 1
    _set_head $t $b [_sealed_head $b]
}

proc ::vmdai::transcript::reasoning_tick {t b {now ""}} {
    variable R
    if {![info exists R($b,t0)] || $R($b,sealed) || ![winfo exists $t]} { return }
    if {$R($b,timer) ne ""} { ::vmdai::sched::cancel $R($b,timer) }
    if {$now eq ""} { set now [clock seconds] }
    set s [expr {$now - $R($b,t0)}]
    if {$s < 0} { set s 0 }
    _set_head $t $b [format "Thinking\u2026 %02d:%02d" [expr {$s / 60}] [expr {$s % 60}]]
    set R($b,timer) [::vmdai::sched::after 1000 [list ::vmdai::transcript::reasoning_tick $t $b]]
}

proc ::vmdai::transcript::reasoning_toggle {t b} {
    variable R
    if {![info exists R($b,sealed)] || !$R($b,sealed)} { return }
    set R($b,open) [expr {!$R($b,open)}]
    # Open: stop specifying -elide (not 0), so a collapsed run's wl:$run still hides it.
    $t tag configure rbody:$b -elide [expr {$R($b,open) ? "" : 1}]
    _set_head $t $b [_sealed_head $b]
}

proc ::vmdai::transcript::_sealed_head {b} {
    variable R
    return "Thought for $R($b,secs) s [expr {$R($b,open) ? "\u25be" : "\u25b8"}]"
}

proc ::vmdai::transcript::_set_head {t b label} {
    variable R
    set w [_rw $t]
    $w delete rs:$b re:$b
    $w insert rs:$b $label $R($b,head)
}

# Hidden: `reasoning` elides and outranks the per-block tags. Shown: it
# stops specifying -elide, so each block's own collapsed/expanded state holds.
proc ::vmdai::transcript::set_reasoning_visible {t on} {
    variable reasoning_hidden
    set reasoning_hidden [expr {$on ? 0 : 1}]
    if {$on} {
        $t tag configure reasoning -elide ""
    } else {
        $t tag configure reasoning -elide 1
        $t tag raise reasoning
    }
}

proc ::vmdai::transcript::reasoning_reset {{t ""}} {
    variable R
    foreach key [array names R *,timer] {
        if {$R($key) ne ""} { ::vmdai::sched::cancel $R($key) }
    }
    array unset R
    array set R {}
}
```

- [ ] **Step 4: Route reasoning ops and follow the setting in `plugin/panel.tcl`**

Replace `proc ::vmdai::panel::render` with:

```tcl
proc ::vmdai::panel::render {ops} {
    variable nomodel
    variable replaying
    set batch {}
    foreach op $ops {
        switch -- [lindex $op 0] {
            status {
                if {!$replaying} { _apply_status $op }
            }
            error.card {
                lappend batch $op
                if {[lindex $op 1] eq "NO_MODEL"} {
                    set nomodel 1
                    _sync_composer
                }
            }
            reasoning.open - reasoning.append - reasoning.seal {
                if {[llength $batch]} {
                    _apply_transcript $batch
                    set batch {}
                }
                _apply_reasoning $op
            }
            default { lappend batch $op }
        }
    }
    if {[llength $batch]} { _apply_transcript $batch }
}
```

Replace `proc ::vmdai::panel::on_session_started` with:

```tcl
proc ::vmdai::panel::on_session_started {result} {
    variable win
    if {![winfo exists $win]} { return }
    refresh_info
    _load_persisted
}
```

In `proc ::vmdai::panel::reset_view`, directly after the line `::vmdai::transcript::clear`, add:

```tcl
    ::vmdai::transcript::reasoning_reset $::vmdai::panel::text
```

Append:

```tcl
# ---- reasoning (P09-T08) --------------------------------------------------------

namespace eval ::vmdai::panel {
    if {![info exists ::vmdai::panel::reasoning_visible]} { variable reasoning_visible 1 }
}

proc ::vmdai::panel::_apply_reasoning {op} {
    variable text
    variable has_content
    variable replaying
    set has_content 1
    ::vmdai::transcript::hide_empty_state
    lassign $op name b arg
    switch -- $name {
        reasoning.open   { ::vmdai::transcript::reasoning_open $text $b $arg [expr {!$replaying}] }
        reasoning.append { ::vmdai::transcript::reasoning_append $text $b $arg }
        reasoning.seal   { ::vmdai::transcript::reasoning_seal $text $b $arg }
    }
}

proc ::vmdai::panel::set_reasoning_visible {on} {
    variable reasoning_visible
    variable text
    set reasoning_visible [expr {$on ? 1 : 0}]
    if {$text ne "" && [winfo exists $text]} {
        ::vmdai::transcript::set_reasoning_visible $text $reasoning_visible
    }
}

# An empty settings.set patch returns the persisted settings without writing.
proc ::vmdai::panel::_load_persisted {} {
    ::vmdai::net::call settings.set [list patch j "{}"] [list ::vmdai::panel::_on_persisted]
}

proc ::vmdai::panel::_on_persisted {form args} {
    if {$form ne "ok"} { return }
    set persisted {}
    catch {set persisted [dict get [lindex $args 0] persisted]}
    if {[dict exists $persisted reasoning_visible]} {
        set_reasoning_visible [string is true -strict [dict get $persisted reasoning_visible]]
    }
}
```

- [ ] **Step 5: Add "Show model reasoning" to the Settings Panel tab**

In `plugin/settings.tcl`:

1. Change `variable PERSISTED_FIELDS {wiki_enabled wiki}` to `variable PERSISTED_FIELDS {wiki_enabled wiki reasoning_visible reasoning}`.
2. In `proc ::vmdai::settings::_build_panel`, replace the comment line `# Row 1 is left for "Show model reasoning" (P09-T08).` with:

```tcl
    ttk::checkbutton $p.reasoning -text "Show model reasoning" -variable ::vmdai::settings::v(reasoning)
    grid $p.reasoning -row 1 -column 1 -columnspan 2 -sticky w -pady 4
```

3. In `proc ::vmdai::settings::_after_persisted`, insert directly before its final `{*}$k`:

```tcl
    variable v
    if {[info exists v(reasoning)]} { ::vmdai::panel::set_reasoning_visible $v(reasoning) }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_reasoning_display.py tests/test_tcl_bridge_v2.py tests/test_tk_settings.py tests/test_tk_panel.py tests/test_tcl_lint.py -q`
Expected: all pass (`4 passed` from the reasoning file).

Run: `python -m pytest tests -q -k "transcript or viewmodel" 2>&1 | tail -2`
Expected: plan 08's transcript and view-model tests (including the `reasoning_answer` golden) still pass: this task changes only what the panel routes, not `transcript::apply_ops`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+38 passed`, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add plugin/transcript.tcl plugin/panel.tcl plugin/settings.tcl \
        tests/tcl/test_reasoning_display.tcl tests/test_tk_reasoning_display.py
git commit -m "feat(plugin): reasoning line with timer, Thought-for expand, and the reasoning_visible toggle (P09-T08)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P09-T09: End-to-end panel test and M2 goldens

**Files:**
- Create: `tests/tcl/panel_driver.tcl`
- Create: `tests/test_panel_integration.py`
- Create: `tests/fixtures/tk/panel_03_conversation.txt` (generated in Step 4)
- Create: `tests/fixtures/tk/panel_resume_replay.txt` (generated in Step 4)

**Interfaces:**
- Consumes: serve_runtime (P06-T11) — `helpers.scripted_runtime.serve_runtime(home, loop_factory)` returning an object with `.port` and `.stop()`, and `ScriptedLoopFactory(script)`; `helpers.tcl.run_tcl(script, *, needs_http, needs_json, env, timeout)` and `tcl_skip_reason` (P01-T03); `helpers.tk.tk_prelude()`, `tk_skip_reason()`, `update_goldens()`, `golden_path(name)` (P06-T10); the whole plugin as assembled by P09-T01..T08 (`::vmdai::start`, `::vmdai::panel::on_send`, `reset_view`, `new_chat`, `bridge_busy`, `replayed`, `rt_info`, `::vmdai::bridge::state`, `resume`, `::vmdai::transcript::dump`, `::vmdai::stop`).
- Produces: M2 panel goldens `tests/fixtures/tk/panel_03_conversation.txt` and `tests/fixtures/tk/panel_resume_replay.txt`.

- [ ] **Step 1: Write the driver and the test**

Create `tests/tcl/panel_driver.tcl`:

```tcl
# tests/tcl/panel_driver.tcl - P09-T09 end-to-end driver (not a tcltest file).
#
# tests/test_panel_integration.py runs this under tclsh 8.6 with VMD's Tk
# (helpers.tk.tk_prelude), http 2.9.5 and json 1.1.2 already loaded. It
# sources the real plugin, attaches to the in-process scripted runtime named
# by VMD_AI_ATTACH (token file under $HOME/.vmdai/run), sends two prompts
# through the panel, then opens a new chat and resumes the first one into a
# fresh view. It writes
#   $PANEL_OUT/live.txt    the transcript dump after both requests
#   $PANEL_OUT/replay.txt  the transcript dump after New chat + resume
#   $PANEL_OUT/error.txt   only on failure
# Tk on macOS swallows stdout, so everything goes to files.
set ::out $env(PANEL_OUT)
file mkdir $::out

proc ::driver_fail {message} {
    set fh [open [file join $::out error.txt] w]
    puts $fh $message
    close $fh
    exit 3
}
proc bgerror {message} { ::driver_fail "background error: $message\n$::errorInfo" }

proc ::driver_wait {script ms what} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { ::driver_fail "timed out waiting for $what" }
        after 20 {set ::driver_tick 1}
        vwait ::driver_tick
    }
}

proc ::driver_dump {name} {
    set fh [open [file join $::out $name] w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::transcript::dump]
    close $fh
}

# VMD commands the executor calls. This is tclsh, not VMD.
proc ::display {args} { return "" }
proc ::mol {args} { return 0 }
proc ::vmdinfo {what} { return driver }
# render TachyonInternal <path>: an 8x6 uncompressed 24-bit TGA gradient.
proc ::render {renderer path args} {
    set fh [open $path w]
    fconfigure $fh -translation binary
    puts -nonewline $fh [binary format cccsscsssscc 0 0 2 0 0 0 0 0 8 6 24 0]
    for {set y 0} {$y < 6} {incr y} {
        for {set x 0} {$x < 8} {incr x} {
            puts -nonewline $fh [binary format ccc [expr {$x * 30}] [expr {$y * 40}] 200]
        }
    }
    close $fh
    return ""
}

# Count request.finished events without replacing panel::on_event.
set ::driver_finished 0
proc ::driver_count {cmd op} {
    set ev [lindex $cmd 1]
    if {![catch {dict get $ev metadata kind} kind] && $kind eq "request.finished"} {
        incr ::driver_finished
    }
}

if {[catch {
    cd $env(PANEL_WORKDIR)
    source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]
    set ::vmdai::panel::headless 1
    trace add execution ::vmdai::panel::on_event enter ::driver_count
    ::vmdai::start
    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne ""}} 20000 "the session"
    ::driver_wait {expr {$::vmdai::panel::rt_info ne ""}} 5000 "runtime.info"
    # Startup may add connection notes; the goldens cover the conversation.
    ::vmdai::panel::reset_view
    set n 0
    foreach prompt [list $env(PANEL_PROMPT_1) $env(PANEL_PROMPT_2)] {
        incr n
        ::vmdai::composer::set_text $prompt
        ::vmdai::panel::on_send
        ::driver_wait [list expr "\$::driver_finished >= $n"] 30000 "request $n"
        ::driver_wait {expr {![::vmdai::panel::bridge_busy]}} 5000 "idle after request $n"
    }
    update idletasks
    ::driver_dump live.txt
    set ::chat [dict get [::vmdai::bridge::state] chat_id]
    ::vmdai::panel::new_chat
    ::driver_wait {expr {[dict get [::vmdai::bridge::state] session_id] ne ""
        && [dict get [::vmdai::bridge::state] chat_id] ne $::chat}} 10000 "the new chat"
    ::vmdai::bridge::resume $::chat
    ::driver_wait {expr {$::vmdai::panel::replayed eq $::chat}} 10000 "the replay"
    update idletasks
    ::driver_dump replay.txt
    ::vmdai::stop
} err]} {
    ::driver_fail "$err\n$::errorInfo"
}
exit 0
```

Create `tests/test_panel_integration.py`:

```python
"""P09-T09: the real plugin, attached to a scripted runtime, driven through the panel.

Closes M2 (§8): S2 on the assembled panel, and Tk goldens for it. The driver
(tests/tcl/panel_driver.tcl) sends two prompts through the composer, then
opens a new chat and resumes the first one; the resumed view must equal the
live one (§2c Persistence: replay through vm::apply).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

from helpers import tcl, tk
from helpers.scripted_runtime import ScriptedLoopFactory, serve_runtime

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "tcl" / "panel_driver.tcl"
PROMPT_1 = "Load the demo structure and tell me how many atoms it has"
PROMPT_2 = "Set a white background and take a snapshot"
ANSWER_1 = "The structure has 42 atoms."
ANSWER_2 = "Done: the background command failed once, then the snapshot was taken."


def _tool(call_id: str, name: str, **tool_input: str) -> Dict[str, object]:
    return {"id": call_id, "name": name, "input": tool_input}


# One entry per model turn, served in order across both requests (03_conversation
# shape: prose, a command that succeeds, a failing then recovered command, a
# snapshot and a final answer). `color` is not a command in tclsh, so tc_2 fails.
SCRIPT = [
    ("I'll count the atoms.", [_tool("tc_1", "run_vmd_command", command='set n 42\nputs "atoms: $n"',
                                     rationale="Count atoms")]),
    (ANSWER_1, []),
    ("", [_tool("tc_2", "run_vmd_command", command="color Display Background white",
                rationale="White background")]),
    ("That command is not available here; retrying.",
     [_tool("tc_3", "run_vmd_command", command="puts recovered", rationale="Retry")]),
    ("", [_tool("tc_4", "capture_vmd_snapshot", purpose="Check the view")]),
    (ANSWER_2, []),
]

_CACHE: Dict[str, Dict[str, str]] = {}


def _numbered(pattern: str, label: str, text: str) -> str:
    seen: Dict[str, str] = {}
    return re.sub(pattern, lambda m: seen.setdefault(m.group(0), f"<{label}{len(seen) + 1}>"), text)


def normalise(text: str, tmp: Path) -> str:
    """Replace what differs between runs: paths, ids, call keys, widget and image names, times."""
    for root in {str(tmp.resolve()), str(tmp)}:
        text = text.replace(root, "<TMP>")
    text = _numbered(r"chat_[0-9a-f]{12}", "CHAT", text)
    text = _numbered(r"req_[0-9a-f]+", "REQ", text)
    text = _numbered(r"\b[0-9a-f]{12}\b", "KEY", text)
    text = re.sub(r"\.vmd_ai[\w.]*", "<W>", text)
    text = re.sub(r"\bimage\d+\b", "<IMG>", text)
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AP]M)?\b", "<TIME>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s?(?:ms|s)\b", "<DUR>", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\s?(?:KB|MB)\b", "<SIZE>", text)
    return text


def _run(tmp: Path) -> Dict[str, str]:
    reason = tk.tk_skip_reason() or tcl.tcl_skip_reason(needs_http=True, needs_json=True)
    if reason:
        pytest.skip(reason)
    home = tmp / "home"
    work = tmp / "proj"
    out = tmp / "out"
    home.mkdir()
    work.mkdir()
    runtime = serve_runtime(home, ScriptedLoopFactory(SCRIPT))
    try:
        env = {
            "HOME": str(home),
            "VMD_AI_ATTACH": f"127.0.0.1:{runtime.port}",
            "PANEL_OUT": str(out),
            "PANEL_WORKDIR": str(work),
            "PANEL_PROMPT_1": PROMPT_1,
            "PANEL_PROMPT_2": PROMPT_2,
        }
        proc = tcl.run_tcl(tk.tk_prelude() + DRIVER.read_text(encoding="utf-8"),
                           needs_http=True, needs_json=True, env=env, timeout=120)
    finally:
        runtime.stop()
    error = out / "error.txt"
    assert not error.exists(), error.read_text(encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return {name: normalise((out / f"{name}.txt").read_text(encoding="utf-8"), tmp)
            for name in ("live", "replay")}


@pytest.fixture
def dumps(tmp_path):
    # Function scope keeps the hermetic conftest (HOME, keyring) active;
    # the driver runs once per session.
    if "dumps" not in _CACHE:
        _CACHE["dumps"] = _run(tmp_path)
    return _CACHE["dumps"]


def _check_golden(name: str, text: str) -> None:
    path = tk.golden_path(name)
    if tk.update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    assert path.exists(), f"{path} is missing: run with CHATVMD_UPDATE_GOLDENS=1 and review it"
    assert text == path.read_text(encoding="utf-8")


def test_live_equals_golden(dumps):
    live = dumps["live"]
    for expected in (PROMPT_1, PROMPT_2, ANSWER_1, ANSWER_2, "recovered"):
        assert expected in live
    assert live.count(PROMPT_1) == 1 and live.count(ANSWER_2) == 1
    assert "tunnel" not in live
    _check_golden("panel_03_conversation", live)


def test_resume_replay_matches_live(dumps):
    assert dumps["replay"] == dumps["live"]
    _check_golden("panel_resume_replay", dumps["replay"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_panel_integration.py -q`
Expected: `2 failed`, each with `tests/fixtures/tk/panel_03_conversation.txt is missing: run with CHATVMD_UPDATE_GOLDENS=1 and review it` (or `…panel_resume_replay.txt is missing…`). If instead the driver reports an error (the assertion prints `error.txt`: for example `timed out waiting for request 1`), the assembled panel is broken: fix the cause in the plugin before generating goldens.

- [ ] **Step 3: Check that the live and replayed views agree before recording**

Run: `python -m pytest tests/test_panel_integration.py -q -k resume`
Expected: the only failure is the missing golden (`assert path.exists()`), which proves `dumps["replay"] == dumps["live"]` already held. If the equality assertion fails, the diff shows which rows differ between the live and the replayed chat; fix the replay path (P09-T07 `::vmdai::panel::replay` or `::vmdai::bridge::replay_history`) and rerun.

- [ ] **Step 4: Record the goldens and review them**

Run:
```bash
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_panel_integration.py -q
grep -c "Load the demo structure" tests/fixtures/tk/panel_03_conversation.txt
grep -c "The structure has 42 atoms." tests/fixtures/tk/panel_03_conversation.txt
cmp tests/fixtures/tk/panel_03_conversation.txt tests/fixtures/tk/panel_resume_replay.txt && echo same
```
Expected: `2 passed`; the two `grep -c` lines print `1` each; `cmp` prints `same`. Read `tests/fixtures/tk/panel_03_conversation.txt` once: it must show, in order, the first user block, run 1 with one ✓ row and its answer, the second user block, run 2 with a ✗ row (the `color` error line under it), a ✓ `puts recovered` row, a snapshot row with its card, and the final answer — and no line that glues a tool row or reasoning onto prose (S2).

- [ ] **Step 5: Run the tests without the update flag**

Run: `python -m pytest tests/test_panel_integration.py -q`
Expected: `2 passed`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+40 passed`, 0 failed, in under 60 s (S9).

Run: `python -m pytest vmdbench/tests -q 2>&1 | tail -1` and `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1`
Expected: `90 passed` and `62 passed` (this plan touches neither).

- [ ] **Step 6: Commit**

```bash
git add tests/tcl/panel_driver.tcl tests/test_panel_integration.py \
        tests/fixtures/tk/panel_03_conversation.txt tests/fixtures/tk/panel_resume_replay.txt
git commit -m "test(plugin): end-to-end panel test against a scripted runtime and the M2 panel goldens (P09-T09)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Plan exit check

- [ ] `env -u VMD_AI_PROVIDER python -m pytest tests -q` — `B+40 passed`, 0 failed, under 60 s; run from a GUI login session on the dev Mac so the Tk tests run instead of skipping.
- [ ] `python -m pytest tests/test_tcl_lint.py -q` — passes for `plugin/panel.tcl`, `plugin/settings.tcl`, `plugin/history.tcl` and the edited `transcript.tcl`, `composer.tcl`, `bridge.tcl`, `ui.tcl`.
- [ ] `python -m pytest vmdbench/tests -q` — 90 passed; `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q` — 62 passed.
- [ ] `git diff main --stat -- runtime/` prints nothing (no runtime change in this plan).
- [ ] Manual smoke in VMD 1.9.4a57 (`VMD_AI_VMD_BIN` machine): Extensions → VMD AI opens the 560×780 panel titled "ChatVMD — New chat" with the empty state; ⌘, opens Settings, Test connection against the qwen tunnel shows two lines; a prompt streams, rows and the answer never share a line; closing the window mid-request and reopening it shows the finished run; History lists chats and resumes one with the same rows.

## Deviations from skeleton

1. **Two extra shared test helpers (P09-T01).** `tests/tcl/panel_harness.tcl` (modules, fake transport, `::harness::fire`, stubs) and `tests/helpers/tk_cases.py` (one tcltest run per module, per-case pytest results) are created so the seven Tk test files do not repeat that setup.
2. **Extra guard and cases in P09-T01.** `tests/test_tk_panel.py::test_component_targets_defined` checks that every `::vmdai::panel|settings|history::` name any plugin file calls exists (plan 08's toolbar, banner and status bar call the panel by name). `panel-menu_actions` and `panel-start_opens_panel` pin the menu actions and "::vmdai::start now opens this panel".
3. **Empty state as an overlay (P09-T02).** It is a frame placed over the transcript text, not text inserted into it, so plan 08's op goldens and `dump` are unaffected. `show_empty_state info` gains an optional text path (`show_empty_state info ?t?`), and the task adds `hide_empty_state`, `empty_state_shown`, `layout_empty_state`, `empty_rows` and `example_clicked` (plus the `empty-hide` case).
4. **Prompt recall lives in composer.tcl (P09-T03).** P08's `push_history` is replaced by one that keeps the newest 50 and feeds `on_up`/`on_down`; the task adds `clear_history`, `recall_prev`, `recall_next`. The panel adds `focus_ring`/`focus_next`/`focus_prev` so V5's Tab order is explicit and testable while withdrawn.
5. **Settings save path (P09-T04/T05).** `settings::open` takes `?tab? ?prefill?` (the empty state's "Use…" prefill). An existing profile is saved with `provider.set {profile, …}`, which merges `options` key by key, so option keys the dialog does not show (for example a vLLM profile's `extra_body`) survive (§2f "unknown keys are kept"); `profiles.save` is used for profiles created with New…, and `profiles.activate` when the saved profile is not the active one. The "no keychain" state is detected from `keys.test`, so no runtime change is needed. P09-T04 and P09-T06 each add one module to `plugin/init.tcl`.
6. **Wiki toggle in P09-T05.** "Use project wiki (slower)" lands with the rest of the Panel tab because it is the key that exercises T05's `settings.set` step; P09-T08 adds "Show model reasoning" through the same `PERSISTED_FIELDS` list.
7. **History talks to the runtime directly (P09-T06).** It calls `chat.history.list {offset 0, limit 50}` through `::vmdai::net::call` instead of `::vmdai::bridge::history_list callback`, whose limit the skeleton does not fix (the runtime's default is 20); it still resumes through `::vmdai::bridge::resume`. The task adds `history-format_updated`.
8. **P09-T07 scope.** Its test file runs under Tk (the wiring under test ends in Tk components), and it also edits `plugin/panel.tcl` (event routing, replay, runtime-state fan-out, `new_chat` re-showing the empty state, Up/Down recall refilled on resume, and `_record_tcl`, which feeds P08-T11's `tclexport::record` from `tool.started`/`tool.finished` because no plan-08 module calls it and Copy/Save chat .tcl would otherwise stay empty). It does not edit `plugin/viewmodel.tcl`: the wiring needs only `vm::init`, `vm::apply` and `vm::local_event`. It does not edit `plugin/init.tcl` either: P09-T01 already switched `::vmdai::start`/`::vmdai::stop` to the panel, and the shim keeps every name init.tcl calls. It adds `v2-request_finished_ends_busy`, `v2-resume_replays_history` and `test_ui_shim_covers_callers`. Retiring ui.tcl also deletes P06-T10's `tests/tcl/test_ui_min.tcl` and `tests/test_tk_ui_min.py`, which test the M1 panel (their behaviours moved to plan 08's view-model and components and to this plan). The shim gains `session_started`, `replay` and `local_event`, so `bridge.tcl` reaches the panel (and the view-model) only through `::vmdai::ui::*`, and every shim proc is a no-op without Tk or a panel window.
9. **Reasoning rendering (P09-T08).** The panel routes the three reasoning ops to new transcript procs that write through a hidden peer of the read-only text (the proxy passes `peer`), instead of editing plan 08's `apply_ops`; plan 08's `reasoning_answer` Tk golden, which drives `apply_ops` directly, is unchanged. The task also edits `plugin/panel.tcl` and adds `reasoning-setting_saved`.
10. **P09-T09 driver.** It resets the view before the first prompt so the goldens hold the conversation rather than startup connection notes, and it runs through `helpers.tcl.run_tcl` with `helpers.tk.tk_prelude()` because it is a driver, not a tcltest file.
11. **Tk modules are sourced only when Tk is loaded (P09-T01).** `plugin/init.tcl` wraps the M2 module list in `if {[info commands ::winfo] ne ""}` so plan 06's tclsh bridge driver keeps sourcing the plugin, and `::vmdai::stop` calls `::vmdai::panel::dispose` only when it exists.
12. **`plugin/config.tcl` unchanged.** The file map lists plan 09 as modifying it; no task needs to, because plugin.json is read and written through plan 06's `load_plugin_settings`/`save_plugin_settings`.
13. **Cross-plan fixes (completeness pass).** (a) P09-T07 moves P06-T10's `test_tk_helper_contract` into `tests/test_tk_helper.py` before deleting `tests/test_tk_ui_min.py` (six pytest tests, not four), so `helpers/tk.py` keeps a direct test; the running totals from P09-T07 on are one lower than before (`B+34`, `B+38`, `B+40`). (b) `::harness::stub_desktop` also stubs P08-T05's `::vmdai::transcript::_clipboard`, so transcript Copy links in the panel tests never touch the real system clipboard. (c) `provider.test` now returns `version` for Ollama (P03-T07), so Test connection shows `Connected · N ms · Ollama <version>` as Part B V4 specifies; `connection_lines` already reads the field when present.
