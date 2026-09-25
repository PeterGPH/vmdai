# ChatVMD Round 1 — Plan 08: ChatVMD R1 — M2 view-model and panel components

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure view-model that turns v2 events into render ops (with op goldens), plus the Tk components that apply them: theme tokens and fonts, transcript, tool rows and cards, snapshot cards and viewer, composer, status bar, banner, toolbar, and the Tcl export ledger.

**Architecture:** `plugin/viewmodel.tcl` is pure Tcl: `::vmdai::vm::apply stateVar event` turns one decoded §2c envelope into a flat list of render ops (the §2h / Part B V4 vocabulary), so every panel behaviour is pinned first by op goldens replayed from plan 07's scenario fixtures. The Tk modules (`theme`, `transcript`, `viewer`, `composer`, `statusbar`, `banner`, `toolbar`) are one namespace each with a `create` proc and a few verbs; the transcript draws each op through a proc named `op_<op>`, and `tclexport.tcl` is a Tk-free ledger. Nothing is wired into VMD yet: plan 09 sources these modules from `init.tcl` and routes events through them.

**Tech Stack:** Tcl in the 8.5-safe subset, run under Tcl 8.6 (anaconda `tclsh8.6` 8.6.14 on the dev Mac) with VMD.app's Tk 8.6.12 loaded for the Tk tests; tcllib json 1.1.2 (vendored at `plugin/lib/json` by plan 06); tcltest 2; pytest wrappers built on `tests/helpers/tcl.py` (plan 01) and `tests/helpers/tk.py` (plan 06).

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — this plan implements §2h (the view-model contract and the viewmodel, transcript, composer, statusbar, toolbar, banner, tclexport, viewer and theme rows of the file table), §2c (Block boundaries, Sealing messages, Empty final turn, Rescued calls, Thumbnails: card, fallbacks and the 30-photo cap), §6 (tclsh view-model op goldens for the five scenario fixtures; Tk golden transcripts), Part B V1 (grafts and "Required fixes to native"), V2 (light tokens, named fonts), V4 (Toolbar, Status bar, Transcript blocks, Tool rows, Step detail, Snapshot card, Composer, Banner, Error cards, View-model ops), V5 (Scrolling, the right-click menus), V6 (row and run-header refit, narrow rules), V7 (the text card and the other 8.5 fallbacks), V8 (adopted and added visual tests), and the panel labels of Part C **C1, C3, C4, C5** (C7's hint is plan 09's). Part C wins where it conflicts with Parts A/B.

**Branch:** `chatvmd-r1-08-m2-panel-core`, created from `main` after plan 07 (and so plans 01–06) is merged.

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

- Nothing in this plan is reachable from VMD yet: `plugin/init.tcl` does not source the new modules until P09-T01, and `ui.tcl`, `bridge.tcl`, `executor.tcl` and every runtime file stay untouched. No new module runs code at source time beyond namespace initialisers, so sourcing them in any order is safe.
- The view-model is pure and deterministic: no Tk, no timers, no I/O, no clock in `apply`. Every time it reports comes from an event's `ts` (only `local_event`, the constructor the panel uses for its own events, defaults `ts` to `[clock seconds]`). The only clock it formats is the "Connection lost at …" note, so the tests run with `TZ=UTC`.
- Op argument lists follow §2h and Part B V4 exactly. This plan only appends optional trailing arguments, which the listed forms leave out: `block.open b role turn ?time?` (user blocks carry the message time), `tool.open k name command executor origin ?rationale?`, `run.close run status steps failed recovered duration_s final_text_empty ?max_turns?`, and `snapshot k thumb path w h saved_path sent_to_model ?renderer?`. The `detail` of `tool.close` is a dict that always has the keys `label error inline preview output output_path total applied failed_index failed_text late`.
- Op goldens are one op per line, written by `::vmdai::vm::format_op` (bare words, or double-quoted words using only the escapes `\\ \" \n \r \t`), and read back as Tcl lists. Tk goldens are `::vmdai::transcript::dump`: `images N`, then one line per displayed text line, `NNN <style tags> | <text>`, with per-item tags (anything containing `:`) left out, embedded windows shown as `<card>` or `<rule>`, and fully elided lines skipped.
- Tk tests put their widgets in the withdrawn root `.`. On aqua a withdrawn root still gets real geometry, while a withdrawn toplevel stays 1×1 (verified while planning). Tk drops generated events on unmapped windows (also verified), so tests call the procs that bindings call rather than `event generate`. Every Tk test file ends with `cleanupTests` and then `exit`: a tclsh with Tk loaded enters the Tk main loop at the end of its script and would otherwise hang until the timeout. Tests turn off what would map extra windows or animate: `::vmdai::toolbar::opt(tip_map) 0`, `::vmdai::viewer::opt(map) 0` and `::vmdai::transcript::opt(animate) 0`.
- Plugin modules never call `update` or `vwait`. Every timer goes through `::vmdai::sched::after` or `after_idle` (plan 06) and is cancelled through `::vmdai::sched::cancel`, so `sched::teardown` leaves `after info` empty (S4).
- The toolbar, status bar, banner and transcript take an optional callback (`-onaction`, or the `on_action` variable) that the tests use. Without it they call the procs plan 09 defines, by these exact names only: `::vmdai::panel::new_chat open_history copy_chat_tcl save_chat_tcl open_runs_folder set_expand_all collapse_older open_settings open_log quit_runtime choose_folder`, plus `::vmdai::runtime::retry_now`, `stop` and `ensure` (plan 06). A missing target is skipped, never an error. Plan 09's `test_component_targets_defined` checks every `::vmdai::panel|settings|history` name that a plugin file mentions, so no other such name may appear in these files, comments included. Optional calls between this plan's own modules are not panel targets; they too are looked up first and skipped when missing: the transcript calls `::vmdai::composer::set_text`/`focus`, `::vmdai::tclexport::run_tcl`/`save` and `::vmdai::viewer::*`; the composer calls `::vmdai::statusbar::flash`; the banner only reads `::vmdai::runtime::state info failure_reason pipe_tail backoff_ms` and `::vmdai::config::log_path` (plan 06), each under `catch`. Two calls are hard dependencies: the status bar calls `::vmdai::vm::status_text` and the transcript calls `::vmdai::vm::run_summary`, so `viewmodel.tcl` is sourced before either module draws (plan 09 sources every module, and the tests load it).
- `::vmdai::transcript::create path` returns the read-only text (`path.t`); `path` is the frame the caller grids. There is one transcript per interpreter, so a second `create` replaces the first. The status bar's `update` keys are the ones plan 09 sends: `connection provider model host folder runs busy activity t0`, plus the optional `retry_in` (whole seconds to the next reconnect attempt).
- No test waits longer than 0.7 s. The plan adds 103 pytest tests, which run in about 4 s on the dev Mac. CI has no GUI session, so the Tk modules skip there; the view-model and tclexport tests run in CI.

## Review Focus

1. A 10 KB one-line command at 380 px stays one display line and is never cut below 12 characters; its right-hand side stays inside the text. Owner P08-T06: `tests/tcl/test_tool_rows.tcl` test `fit-1` (pytest `tests/test_tk_tool_rows.py::test_adopted[fit-1]`).
2. `tool.finished` before `tool.started`, or with an unknown `call_key`, is ignored: no op, and the view-model state is unchanged. The transcript also ignores `tool.close`, `run.chip` and `snapshot` for a row it never opened. Owners P08-T02: `tests/test_tcl_viewmodel.py::test_unknown_call_key_ignored`; P08-T06: `test_unknown_call_key_noop`.
3. Non-BMP text (emoji) and a lone surrogate degrade without error in blocks, seals, notices and the dump. Owner P08-T05: `tests/test_tk_transcript.py::test_non_bmp`.
4. A thumbnail that is missing falls back to subsampling the full image; one that cannot be decoded gives a text card (file name, W × H, Open, Reveal) and loads no photo. Owner P08-T07: `tests/test_tk_snapshot_cards.py::test_tk85_1` (tcltests `tk85-1`, `thumb_fallback`).
5. The user has scrolled up: new output does not move the view, and the "↓ New output" pill shows; at the bottom, output follows and the pill hides. Owner P08-T05: `tests/test_tk_transcript.py::test_sticky_autoscroll`.

## File Structure

| Path | Task | Responsibility |
|---|---|---|
| `plugin/viewmodel.tcl` | T01 create; T02, T03 modify | events → ops; tool states and labels; local events; status texts and run summaries |
| `plugin/theme.tcl` | T04 create | light tokens, named fonts, paint registry, ChatVMD.* ttk styles, canvas and ellipsis helpers |
| `plugin/transcript.tcl` | T05 create; T06, T07 append | the read-only transcript: blocks, reasoning, notices, error cards, rows, step detail, run headers and footers, collapse, snapshot cards, the photo cap, context menus, dump |
| `plugin/viewer.tcl` | T07 create | full-size snapshot viewer |
| `plugin/composer.tcl` | T08 create | input, placeholder, Send/Stop, prompt history |
| `plugin/statusbar.tcl` | T09 create | connection or activity line, trust and folder segments, narrow drop order, flash |
| `plugin/banner.tcl` | T09 create | the one connection banner and its actions |
| `plugin/toolbar.tcl` | T10 create | icons, title, ⋯ menu, tooltips |
| `plugin/tclexport.tcl` | T11 create | the per-statement Tcl export ledger |
| `tests/helpers/panel_goldens.py` | T01 create; T05 append | tcltest pass lines, op-line parsing, golden compare, the S2 glue check |
| `tests/tcl/plugin_loader.tcl` | T05 create | `load_plugin module ...` for the Tcl/Tk tests |
| `tests/tcl/test_*.tcl`, `tests/test_tcl_*.py`, `tests/test_tk_*.py` | one pair per task | the tcltest files and their pytest wrappers |
| `tests/fixtures/ops/*.ops` | T01, T02 create; T03 regenerate `loop_guard.ops` | op goldens for the five scenarios |
| `tests/fixtures/tk/03_conversation.txt`, `reasoning_answer.txt` | T05 create; T06, T07 regenerate | Tk goldens (S2) |

---

### Task 0: Pre-flight — confirm plans 01–07 are merged and their interfaces exist

**Files:** none (read-only checks).

**Interfaces:**
- Consumes (from earlier plans, checked here):
  - `helpers.tcl.run_tcl(script, *, needs_http=False, needs_json=False, cwd=None, env=None, timeout=60)`, `helpers.tcl.run_tcltest(test_file, *, needs_http=False, needs_json=False, env=None, timeout=120, prelude='') -> TclTestResult`, `helpers.tcl.REPO`, `helpers.tcl.TclTestResult(passed, failed, skipped, output)` (P01-T03)
  - `helpers.tk.tk_skip_reason() -> Optional[str]; helpers.tk.tk_prelude() -> str; helpers.tk.run_tk_test(test_file, *, env=None, timeout=120) -> TclTestResult; helpers.tk.update_goldens() -> bool; helpers.tk.golden_path(name) -> Path` (P06-T10)
  - `::vmdai::sched::after ms script -> id; after_idle script; cancel id` (P06-T02)
  - `::vmdai::executor::split_statements script -> dict {statements tail}` (P06-T08)
  - `plugin/lib/json` provides json 1.1.2 (P06-T01); `tests/test_tcl_lint.py` (P06-T01)
  - the five fixtures `tests/fixtures/events/{03_conversation,11_dead_runtime,reasoning_answer,turn_retry,loop_guard}.jsonl`, and the plugin-local kinds `local.connection {state, detail, request_lost}`, `local.request_ended {request_id}`, `local.send_failed {code, message}` as `role: system, type: state` envelopes (P07-T08)
- Produces: the baseline pass count `B` used in the "Expected" lines below.

- [ ] **Step 1: Create the branch**

```bash
git checkout main
git log --oneline -1
git checkout -b chatvmd-r1-08-m2-panel-core
```

Expected: the last commit is plan 07's merge, and the new branch is checked out.

- [ ] **Step 2: Confirm the consumed files exist and this plan's files do not**

```bash
ls plugin/sched.tcl plugin/executor.tcl plugin/config.tcl plugin/net.tcl plugin/lib/json/pkgIndex.tcl \
   tests/helpers/tcl.py tests/helpers/tk.py tests/test_tcl_lint.py \
   tests/fixtures/events/03_conversation.jsonl tests/fixtures/events/11_dead_runtime.jsonl \
   tests/fixtures/events/reasoning_answer.jsonl tests/fixtures/events/turn_retry.jsonl \
   tests/fixtures/events/loop_guard.jsonl
ls plugin/viewmodel.tcl plugin/theme.tcl plugin/transcript.tcl plugin/viewer.tcl plugin/composer.tcl \
   plugin/statusbar.tcl plugin/banner.tcl plugin/toolbar.tcl plugin/tclexport.tcl 2>&1 | grep -c 'No such file'
```

Expected: the first `ls` lists all 13 paths with no error; the second command prints `9`.

- [ ] **Step 3: Confirm the consumed procs and helpers**

```bash
grep -n 'proc ::vmdai::sched::after \|proc ::vmdai::sched::after_idle \|proc ::vmdai::sched::cancel ' plugin/sched.tcl
grep -n 'proc ::vmdai::executor::split_statements ' plugin/executor.tcl
grep -n '^def \(tk_skip_reason\|tk_prelude\|run_tk_test\|update_goldens\|golden_path\)' tests/helpers/tk.py
grep -n '^def \(run_tcl\|run_tcltest\)\|^REPO = \|^class TclTestResult' tests/helpers/tcl.py
```

Expected: 3, 1, 5 and 4 matching lines.

- [ ] **Step 4: Check the splitter and the fixture contract**

Run:

```bash
python - <<'EOF'
import json, pathlib, sys
sys.path[:0] = ["tests"]
from helpers.tcl import run_tcl

proc = run_tcl(r'''
namespace eval ::vmdai {}
source [file join $env(VMDAI_PLUGIN_DIR) sched.tcl]
catch {source [file join $env(VMDAI_PLUGIN_DIR) config.tcl]}
catch {source [file join $env(VMDAI_PLUGIN_DIR) net.tcl]}
source [file join $env(VMDAI_PLUGIN_DIR) executor.tcl]
set d [::vmdai::executor::split_statements "mol new a.pdb\nset x \{\n 1\n\}\nbad \["]
puts [llength [dict get $d statements]]
puts [string trim [dict get $d tail]]
''')
print("splitter:", proc.returncode, proc.stdout.split(), proc.stderr[-300:])

REQUIRED = {
    ("user", "message", ""): {"request_id"},
    ("assistant", "chunk", ""): {"request_id", "turn"},
    ("assistant", "message", ""): {"request_id", "turn", "final"},
    ("reasoning", "chunk", ""): {"request_id", "turn"},
    ("reasoning", "message", ""): {"request_id", "turn"},
    ("system", "state", "request.started"): {"request_id", "model", "max_turns", "vision"},
    ("system", "state", "turn.started"): {"request_id", "turn"},
    ("system", "state", "turn.retry"): {"request_id", "turn"},
    ("system", "state", "tool.started"): {"request_id", "call_key", "tool_name", "executor", "origin", "input"},
    ("system", "state", "tool.finished"): {"call_key", "ok", "executed", "output", "error", "duration_ms",
                                           "statements", "blocked", "output_path", "image", "saved_path", "late"},
    ("system", "state", "status"): {"request_id", "phase"},
    ("system", "state", "request.finished"): {"request_id", "status", "tool_calls", "final_text_empty",
                                              "duration_ms", "wrapped_up", "error"},
    ("system", "state", "local.connection"): {"state", "request_lost"},
    ("system", "state", "local.send_failed"): {"code", "message"},
    ("system", "state", "local.request_ended"): {"request_id"},
}
problems = []
for path in sorted(pathlib.Path("tests/fixtures/events").glob("*.jsonl")):
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        md = e.get("metadata") or {}
        kind = md.get("kind", "")
        if str(kind).startswith("local.") and (e["role"], e["type"]) != ("system", "state"):
            problems.append("%s:%d local event as %s/%s" % (path.name, n, e["role"], e["type"]))
        missing = REQUIRED.get((e["role"], e["type"], kind), set()) - set(md)
        if missing:
            problems.append("%s:%d %s/%s/%s lacks %s" % (path.name, n, e["role"], e["type"], kind, sorted(missing)))
print("fixture contract OK" if not problems else "\n".join(problems))
EOF
```

Expected: `splitter: 0 ['2', 'bad', '['] …` and `fixture contract OK`. If the splitter line differs (another count, or an error), the executor's `split_statements` does not match the skeleton contract `dict {statements tail}`: stop and report it, because P08-T06 and P08-T11 build on it. If the fixture check prints problems, stop and report them to the plan 07 owner; the view-model reads exactly these keys.

- [ ] **Step 5: Confirm Tk loads and record the baseline**

```bash
python -c "import sys; sys.path[:0] = ['tests']; from helpers.tk import tk_skip_reason; print(tk_skip_reason())"
python -m pytest tests/test_tcl_lint.py -q 2>&1 | tail -1
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
```

Expected: `None` (run from the dev Mac's GUI session; over ssh the Tk tests of this plan skip, and their "Expected" lines below then read "skipped"), the lint tests pass, and the suite ends with `B passed` (write `B` down) and no failures, in under 60 s.

---

### Task 1: P08-T01 — View-model: blocks, sealing, reasoning, runs

**Files:**
- Create: `plugin/viewmodel.tcl`
- Create: `tests/helpers/panel_goldens.py`
- Create: `tests/tcl/test_viewmodel.tcl`
- Create: `tests/test_tcl_viewmodel.py`
- Create (generated in Step 7, then committed): `tests/fixtures/ops/03_conversation.ops`, `tests/fixtures/ops/reasoning_answer.ops`, `tests/fixtures/ops/turn_retry.ops`

**Interfaces:**
- Consumes: event fixtures (P07-T08); `helpers.tcl.run_tcl`, `run_tcltest`, `REPO`, `TclTestResult` (P01-T03); `helpers.tk.update_goldens` (P06-T10)
- Produces:
  - `::vmdai::vm::init stateVar ?options?; ::vmdai::vm::apply stateVar event -> ops`
  - ops: `{block.open b role turn} {block.append b text} {block.seal b canonical} {block.discard b} {reasoning.open b turn} {reasoning.append b text} {reasoning.seal b duration_s} {run.open run request_id model t0} {run.chip run call_key ok|err|running|notrun|warn} {run.close run status steps failed recovered duration_s final_text_empty} {tool.open call_key tool_name command executor origin} {tool.close call_key ok|err|notrun|unknown duration_text detail thumb} {snapshot call_key thumb_path path w h saved_path sent_to_model} {notice info|warn text ?action?} {rule run} {footer run applied usage_text} {error.card code title hint action} {status busy text t0} {status idle}`
  - (also) the optional trailing arguments listed under Plan-specific constraints; `::vmdai::vm::format_op op -> string` (one op per line); `::vmdai::vm::tool_state meta -> ok|err|notrun|unknown` (pinned by tests in P08-T02); the state dict key `trust_notice` (1 once the runtime's `tcl_trust_boundary` notice was seen; plan 09's empty state reads it)
  - (also) `helpers.panel_goldens`: `EVENTS_DIR`, `OPS_DIR`, `tcltest_passed(result, name) -> bool`, `assert_tcltests(result, names) -> None`, `parse_op_line(line) -> List[str]`, `parse_ops(text) -> List[List[str]]`, `compare_golden(actual, path) -> None`

How the view-model reads the §2c rules:
- A non-chunk event closes the open block; a chunk opens a new one whenever `role`, `request_id` or `turn` changes. Closing a reasoning block seals it (`reasoning.seal b secs`, secs from the chunk timestamps); closing a text block does not, so a later `assistant/message` for that request and turn still seals it in place, even after a `usage` event.
- An empty canonical text discards the streamed block (this hides JSON the rescue consumed). A `final: true` answer is emitted as `block.discard` of the streamed block, `rule run`, `block.open`, `block.seal`, so the rule precedes the answer and a replayed chat (no chunks) renders the same.
- `turn.retry` discards every block of that request and turn, reasoning included.
- `status` ops carry the phase text and, for timed phases, the phase's start in epoch seconds: `Thinking`, `Writing`, `Step N · running VMD command` (`rendering snapshot`, `searching docs`, `reading the wiki`), `Loading <model>`, `Writing a summary`; retries read `Retrying A/M in W s` with an empty t0.

- [ ] **Step 1: Create the test helper module**

Create `tests/helpers/panel_goldens.py`:

```python
"""Helpers for the M2 panel tests (plan 08): tcltest pass lines, op goldens.

* ``assert_tcltests(result, names)``: every named tcltest passed.
  The Tcl files run with ``-verbose {pass body error}``, so each pass is a
  ``++++ <name> PASSED`` line in ``result.output``.
* ``parse_op_line`` reads one line of ``tests/fixtures/ops/<name>.ops``
  (written by ``::vmdai::vm::format_op``: bare words and double-quoted words
  with the escapes \\\\ \\" \\n \\r \\t).
* ``compare_golden(actual, path)`` rewrites the golden only when
  CHATVMD_UPDATE_GOLDENS=1 and otherwise fails with a unified diff.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Iterable, List

from helpers.tcl import REPO, TclTestResult
from helpers.tk import update_goldens

EVENTS_DIR = REPO / "tests" / "fixtures" / "events"
OPS_DIR = REPO / "tests" / "fixtures" / "ops"

_WORD = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t"}


def tcltest_passed(result: TclTestResult, name: str) -> bool:
    pattern = rf"^\+\+\+\+ {re.escape(name)} PASSED$"
    return re.search(pattern, result.output, re.MULTILINE) is not None


def assert_tcltests(result: TclTestResult, names: Iterable[str]) -> None:
    missing = [n for n in names if not tcltest_passed(result, n)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def parse_op_line(line: str) -> List[str]:
    words = []
    for m in _WORD.finditer(line):
        if m.group(1) is not None:
            words.append(re.sub(r"\\(.)", lambda k: _ESCAPES.get(k.group(1), k.group(1)), m.group(1)))
        else:
            words.append(m.group(2))
    return words


def parse_ops(text: str) -> List[List[str]]:
    return [parse_op_line(line) for line in text.splitlines() if line.strip()]


def compare_golden(actual: str, path: Path) -> None:
    if update_goldens():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"missing golden {path}; run with CHATVMD_UPDATE_GOLDENS=1"
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(True), actual.splitlines(True), str(path), "actual"
            )
        )
        raise AssertionError(f"golden mismatch:\n{diff}")
```

- [ ] **Step 2: Write the failing tcltests**

Create `tests/tcl/test_viewmodel.tcl`:

```tcl
# View-model unit tests (P08-T01..T03). No Tk. Run by tests/test_tcl_viewmodel.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}

source [file join $env(VMDAI_PLUGIN_DIR) viewmodel.tcl]

# Build decoded envelopes the way json::json2dict returns them.
proc ev {role type text md {ts 100}} {
    return [dict create seq 0 ts $ts role $role type $type text $text metadata $md]
}
proc st {kind md {ts 100}} {
    return [ev system state "" [dict merge [dict create kind $kind] $md] $ts]
}
proc started {req {extra {}}} {
    return [st request.started [dict merge [dict create request_id $req chat_id chat_0123456789ab \
        provider ollama model qwen3.8:27b max_turns 28 vision true think true] $extra]]
}
proc tstart {req k {cmd "mol new 1hck.pdb"} {name run_vmd_command}} {
    return [st tool.started [dict create request_id $req turn 1 call_key $k tool_call_id call_$k \
        tool_name $name executor tcl origin model input [dict create command $cmd rationale "load it"]]]
}
proc tfin {req k {extra {}}} {
    return [st tool.finished [dict merge [dict create request_id $req call_key $k \
        tool_name run_vmd_command executor tcl ok true executed yes output "" error "" \
        truncated false duration_ms 412 statements null blocked null output_path null \
        output_bytes 0 image null saved_path null late false] $extra]]
}
# Apply events in order; return the concatenated ops.
proc feed {sv args} {
    upvar 1 $sv S
    set ops {}
    foreach e $args { lappend ops {*}[::vmdai::vm::apply S $e] }
    return $ops
}
# Only the ops whose name is in $names.
proc only {ops names} {
    set out {}
    foreach op $ops { if {[lindex $op 0] in $names} { lappend out $op } }
    return $out
}

# ---- P08-T01 ---------------------------------------------------------------

test user_block_ops {a user message is one block: open (with its time), then its text} -body {
    ::vmdai::vm::init S
    ::vmdai::vm::apply S [ev user message "Load 1HCK" {request_id req_a} 1727180000.7]
} -result {{block.open b1 user 0 1727180000} {block.append b1 {Load 1HCK}}}

test block_closes_on_role_request_turn_change {role, request and turn changes each open a new block} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "one " {request_id req_a turn 1}] \
        [ev assistant chunk "two" {request_id req_a turn 1}] \
        [ev reasoning chunk "hmm" {request_id req_a turn 1}] \
        [ev assistant chunk "three" {request_id req_a turn 1}] \
        [ev assistant chunk "four" {request_id req_a turn 2}] \
        [ev assistant chunk "five" {request_id req_b turn 2}]]
    only $ops {block.open block.append reasoning.open reasoning.append reasoning.seal run.open}
} -result {{run.open r1 req_a qwen3.8:27b 100} {block.open b1 assistant 1} {block.append b1 {one }} {block.append b1 two} {reasoning.open b2 1} {reasoning.append b2 hmm} {reasoning.seal b2 0} {block.open b3 assistant 1} {block.append b3 three} {block.open b4 assistant 2} {block.append b4 four} {run.open r2 req_b {} 100} {block.open b5 assistant 2} {block.append b5 five}}

test non_chunk_event_closes_block {any non-chunk event closes the open block} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "a" {request_id req_a turn 1}] \
        [st usage {request_id req_a turn 1 input_tokens_evaluated 10 output_tokens 2}] \
        [ev assistant chunk "b" {request_id req_a turn 1}]]
    only $ops {block.open block.append}
} -result {{block.open b1 assistant 1} {block.append b1 a} {block.open b2 assistant 1} {block.append b2 b}}

test seal_replaces_streamed_text {assistant/message seals the streamed block in place, even after usage closed it} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "I'll lo" {request_id req_a turn 1}] \
        [ev assistant chunk "ad it." {request_id req_a turn 1}] \
        [st usage {request_id req_a turn 1}] \
        [ev assistant message "I'll load it." {request_id req_a turn 1 final false}]]
    only $ops {block.open block.append block.seal block.discard rule}
} -result {{block.open b1 assistant 1} {block.append b1 {I'll lo}} {block.append b1 {ad it.}} {block.seal b1 {I'll load it.}}}

test seal_empty_discards {an empty canonical text discards the streamed block (rescued JSON)} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev assistant chunk "\{\"name\": \"run_vmd_command\"" {request_id req_a turn 1}] \
        [ev assistant message "" {request_id req_a turn 1 final false}]]
    only $ops {block.open block.seal block.discard}
} -result {{block.open b1 assistant 1} {block.discard b1}}

test final_answer_under_rule {a final answer is re-opened under the run's rule; replay renders the same} -body {
    ::vmdai::vm::init S
    set live [only [feed S [started req_a] \
        [ev assistant chunk "Done." {request_id req_a turn 2}] \
        [ev assistant message "Done." {request_id req_a turn 2 final true}]] \
        {block.open block.seal block.discard rule}]
    ::vmdai::vm::init R
    set replay [only [feed R [started req_a] \
        [ev assistant message "Done." {request_id req_a turn 2 final true}]] \
        {block.open block.seal block.discard rule}]
    list $live $replay
} -result {{{block.open b1 assistant 2} {block.discard b1} {rule r1} {block.open b2 assistant 2} {block.seal b2 Done.}} {{rule r1} {block.open b1 assistant 2} {block.seal b1 Done.}}}

test reasoning_seal_and_replay {reasoning seals once when the answer starts; a later reasoning/message is ignored; replay renders it} -body {
    ::vmdai::vm::init S
    set live [only [feed S [started req_a] \
        [ev reasoning chunk "think" {request_id req_a turn 1} 100] \
        [ev assistant chunk "Answer" {request_id req_a turn 1} 103] \
        [ev reasoning message "think" {request_id req_a turn 1} 104]] \
        {reasoning.open reasoning.append reasoning.seal}]
    ::vmdai::vm::init R
    set replay [only [feed R [started req_a] \
        [ev reasoning message "think" {request_id req_a turn 1 duration_ms 2600}]] \
        {reasoning.open reasoning.append reasoning.seal}]
    list $live $replay
} -result {{{reasoning.open b1 1} {reasoning.append b1 think} {reasoning.seal b1 3}} {{reasoning.open b1 1} {reasoning.append b1 think} {reasoning.seal b1 3}}}

test turn_retry_discards {turn.retry discards the dropped attempt's text and reasoning} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [ev reasoning chunk "r" {request_id req_a turn 1}] \
        [ev assistant chunk "Partial" {request_id req_a turn 1}] \
        [st turn.retry {request_id req_a turn 1 reason {stream dropped}}] \
        [ev assistant chunk "Again" {request_id req_a turn 1}]]
    only $ops {block.open block.discard reasoning.open}
} -result {{reasoning.open b1 1} {block.open b2 assistant 1} {block.discard b2} {block.discard b1} {block.open b3 assistant 1}}

test run_and_tool_ops {request.started opens a run; tools open, chip and close; request.finished closes the run} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] [tstart req_a k1] \
        [tfin req_a k1 {output 20.843129 statements {total 2 applied 2 failed null}}] \
        [st request.finished {request_id req_a status complete wrapped_up false turns 2 tool_calls 1 final_text_empty false duration_ms 1600}]]
    set close [lindex [only $ops tool.close] 0]
    list [only $ops {run.open run.chip run.close footer}] \
         [lrange $close 0 2] [dict get [lindex $close 4] inline] [lindex $close 5]
} -result {{{run.open r1 req_a qwen3.8:27b 100} {run.chip r1 k1 running} {run.chip r1 k1 ok} {footer r1 2 {}} {run.close r1 complete 1 0 0 2 0 28}} {tool.close k1 ok} 20.8431 {}}

test tool_open_args {tool.open carries the command, executor, origin and rationale} -body {
    ::vmdai::vm::init S
    only [feed S [started req_a] [tstart req_a k1 "mol new a.pdb\nmol delrep 0 top"]] tool.open
} -result {{tool.open k1 run_vmd_command {mol new a.pdb
mol delrep 0 top} tcl model {load it}}}

test status_ops_follow_phases {status ops change only with the phase} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a] \
        [st turn.started {request_id req_a turn 1}] \
        [ev assistant chunk "x" {request_id req_a turn 1}] \
        [ev assistant chunk "y" {request_id req_a turn 1}] \
        [tstart req_a k1] \
        [st status {request_id req_a phase retrying attempt 2 max_attempts 5 wait_s 8 http_status 429}] \
        [st status {request_id req_a phase loading_model}]]
    only $ops status
} -result {{status busy Thinking 100} {status busy Writing 100} {status busy {Step 1 · running VMD command} 100} {status busy {Retrying 2/5 in 8 s} {}} {status busy {Loading qwen3.8:27b} 100}}

test snapshot_op {a snapshot result emits tool.close with its thumb and a snapshot op} -body {
    ::vmdai::vm::init S
    set ops [feed S [started req_a {vision false}] \
        [tstart req_a k9 "" capture_vmd_snapshot] \
        [tfin req_a k9 {tool_name capture_vmd_snapshot saved_path /w/fig1.png image {path /c/k9.png thumb_path /c/k9_thumb.png width 1024 height 768 src_width 1280 src_height 1547 renderer TachyonInternal}}]]
    list [lindex [only $ops tool.close] 0 5] [only $ops snapshot]
} -result {/c/k9_thumb.png {{snapshot k9 /c/k9_thumb.png /c/k9.png 1280 1547 /w/fig1.png 0 TachyonInternal}}}

test format_op_round_trip {format_op writes one line that lindex parses back exactly} -body {
    set op [list block.seal b1 "a \"q\" \\ \$x \[y\] \{z\nnext\ttab"]
    set line [::vmdai::vm::format_op $op]
    list [string first "\n" $line] [expr {[lindex $line 2] eq [lindex $op 2]}] [llength $line]
} -result {-1 1 3}

test trust_notice_no_op {the runtime's security notice produces no op; it is routed to the empty state} -body {
    ::vmdai::vm::init S
    set ops [::vmdai::vm::apply S [ev system message "Security note: ..." {notice tcl_trust_boundary}]]
    list $ops [dict get $S trust_notice]
} -result {{} 1}

cleanupTests
```

- [ ] **Step 3: Write the pytest wrapper, with the op goldens and the scenario checks**

Create `tests/test_tcl_viewmodel.py`:

```python
"""View-model (plan 08, P08-T01..T03): tcltest units plus op goldens.

The op goldens replay the runtime-recorded scenario fixtures
(tests/fixtures/events/<name>.jsonl, plan 07) through ::vmdai::vm::apply
and compare the ops, one per line, with tests/fixtures/ops/<name>.ops.
Scenario checks derived from spec §6 run on every replay, so a regenerated
golden that loses the point of its scenario still fails.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

import pytest

from helpers.panel_goldens import (
    EVENTS_DIR,
    OPS_DIR,
    assert_tcltests,
    compare_golden,
    parse_ops,
)
from helpers.tcl import REPO, run_tcl, run_tcltest

TCL = REPO / "tests" / "tcl" / "test_viewmodel.tcl"

UNIT_TESTS = [
    "user_block_ops",
    "block_closes_on_role_request_turn_change",
    "non_chunk_event_closes_block",
    "seal_replaces_streamed_text",
    "seal_empty_discards",
    "final_answer_under_rule",
    "reasoning_seal_and_replay",
    "turn_retry_discards",
    "run_and_tool_ops",
    "tool_open_args",
    "status_ops_follow_phases",
    "snapshot_op",
    "format_op_round_trip",
    "trust_notice_no_op",
]

REPLAY = r"""
source [file join $env(VMDAI_PLUGIN_DIR) viewmodel.tcl]
set in [open $env(CHATVMD_EVENTS) r]
fconfigure $in -encoding utf-8
set out [open $env(CHATVMD_OPS_OUT) w]
fconfigure $out -encoding utf-8 -translation lf
::vmdai::vm::init S
while {[gets $in line] >= 0} {
    if {[string trim $line] eq ""} continue
    foreach op [::vmdai::vm::apply S [json::json2dict $line]] {
        puts $out [::vmdai::vm::format_op $op]
    }
}
close $in
close $out
"""


@pytest.fixture(scope="module")
def vm_result():
    return run_tcltest(str(TCL), env={"TZ": "UTC"})


@pytest.mark.parametrize("name", UNIT_TESTS)
def test_viewmodel_unit(vm_result, name):
    assert_tcltests(vm_result, [name])


def test_viewmodel_counts(vm_result):
    assert (vm_result.passed, vm_result.failed) == (len(UNIT_TESTS), 0), vm_result.output


def test_user_block_ops(vm_result):
    assert_tcltests(vm_result, ["user_block_ops"])


def test_block_closes_on_role_request_turn_change(vm_result):
    assert_tcltests(vm_result, ["block_closes_on_role_request_turn_change", "non_chunk_event_closes_block"])


def test_seal_replaces_streamed_text(vm_result):
    assert_tcltests(vm_result, ["seal_replaces_streamed_text", "seal_empty_discards", "final_answer_under_rule"])


def test_trust_notice_no_op(vm_result):
    assert_tcltests(vm_result, ["trust_notice_no_op"])


def replay_ops(name: str, tmp_path: Path) -> str:
    out = tmp_path / f"{name}.ops"
    proc = run_tcl(
        REPLAY,
        needs_json=True,
        env={
            "TZ": "UTC",
            "CHATVMD_EVENTS": str(EVENTS_DIR / f"{name}.jsonl"),
            "CHATVMD_OPS_OUT": str(out),
        },
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text(encoding="utf-8")


def check_block_lifecycle(ops: List[List[str]]) -> None:
    """Every block op names a block that is open; nothing follows a seal or discard."""
    state: Dict[str, str] = {}
    for op in ops:
        kind, args = op[0], op[1:]
        if kind in ("block.open", "reasoning.open"):
            assert args[0] not in state, op
            state[args[0]] = "open"
        elif kind in ("block.append", "reasoning.append"):
            assert state.get(args[0]) == "open", op
        elif kind in ("block.seal", "reasoning.seal"):
            assert state.get(args[0]) == "open", op
            state[args[0]] = "sealed"
        elif kind == "block.discard":
            assert state.get(args[0]) in ("open", "sealed"), op
            state[args[0]] = "discarded"


def check_tools(ops: List[List[str]]) -> None:
    """tool.close, snapshot and run.chip only name tools that tool.open announced once."""
    opened: List[str] = []
    for op in ops:
        if op[0] == "tool.open":
            assert op[1] not in opened, op
            opened.append(op[1])
        elif op[0] in ("tool.close", "snapshot"):
            assert op[1] in opened, op
        elif op[0] == "run.chip":
            assert op[2] in opened, op


SCENARIO_CHECKS: Dict[str, List[Callable[[List[List[str]]], None]]] = {}


def scenario(name: str):
    def register(fn):
        SCENARIO_CHECKS.setdefault(name, []).append(fn)
        return fn
    return register


@scenario("03_conversation")
def _two_requests_failure_recovered_snapshot(ops):
    assert len([op for op in ops if op[0] == "run.open"]) == 2
    states = [op[2] for op in ops if op[0] == "tool.close"]
    assert "err" in states and "ok" in states[states.index("err") + 1:], states
    assert any(op[0] == "tool.open" and op[2] == "capture_vmd_snapshot" for op in ops)
    assert any(op[0] == "rule" for op in ops)
    assert [op[2] for op in ops if op[0] == "run.close"] == ["complete", "complete"]
    assert ops[-1] == ["status", "idle"]


@scenario("reasoning_answer")
def _reasoning_then_answer(ops):
    reasoning = {op[1] for op in ops if op[0] == "reasoning.open"}
    answers = {op[1] for op in ops if op[0] == "block.open" and op[2] == "assistant"}
    assert reasoning and answers and not (reasoning & answers)
    last_seal = max(i for i, op in enumerate(ops) if op[0] == "reasoning.seal")
    assert any(op[0] == "block.seal" for op in ops[last_seal:])


@scenario("turn_retry")
def _retried_block_discarded(ops):
    # a discard not followed by the final answer's rule is the retry's discard
    retried = [
        op[1] for i, op in enumerate(ops[:-1])
        if op[0] == "block.discard" and ops[i + 1][0] not in ("rule", "block.discard")
    ]
    sealed = {op[1] for op in ops if op[0] == "block.seal"}
    assert retried and not (set(retried) & sealed), ops
    assert sealed


def run_scenario_checks(name: str, ops: List[List[str]]) -> None:
    check_block_lifecycle(ops)
    check_tools(ops)
    for check in SCENARIO_CHECKS[name]:
        check(ops)


@pytest.mark.parametrize("name", sorted(SCENARIO_CHECKS))
def test_ops_golden(name, tmp_path):
    text = replay_ops(name, tmp_path)
    run_scenario_checks(name, parse_ops(text))
    compare_golden(text, OPS_DIR / f"{name}.ops")
```

The golden list is `sorted(SCENARIO_CHECKS)`: registering a scenario check is what adds a fixture to the golden test (P08-T02 adds two).

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -3`
Expected: `22 failed`. The tcltest output quoted in each failure shows `couldn't read file ".../plugin/viewmodel.tcl": no such file or directory`; the three `test_ops_golden[…]` fail on `assert proc.returncode == 0` with the same message on stderr.

- [ ] **Step 5: Write the view-model**

Create `plugin/viewmodel.tcl`:

```tcl
# viewmodel.tcl -- ChatVMD view-model: v2 display events -> render ops.
#
# Pure Tcl, no Tk (spec §2h). The state lives in a dict held by the caller:
#
#   ::vmdai::vm::init  stateVar ?options?
#   ::vmdai::vm::apply stateVar event      -> list of ops
#
# An event is a decoded §2c envelope, {seq ts role type text metadata}, as
# json::json2dict returns it: JSON null is the string "null" and booleans
# are "true"/"false"; _get and _bool normalise both. The op vocabulary and
# argument lists are fixed by spec §2h and Part B V4 so that op goldens can
# be written before any widget exists. Optional trailing arguments added by
# this plan: block.open ?time?, tool.open ?rationale?, run.close ?max_turns?,
# snapshot ?renderer?.

namespace eval ::vmdai::vm {}

proc ::vmdai::vm::init {stateVar {options {}}} {
    upvar 1 $stateVar S
    set S [dict create \
        opts [dict merge {reasoning_visible 1} $options] \
        bseq 0 rseq 0 \
        open {} \
        texts {} \
        reasons {} \
        rsealed {} \
        runs {} \
        tools {} \
        warned {} \
        request "" \
        busy 0 phase "" phase_t0 "" stopping 0 \
        conn "" \
        trust_notice 0]
    return
}

# ---- small helpers ----------------------------------------------------------

proc ::vmdai::vm::_get {d key {default ""}} {
    if {[catch {dict exists $d $key} has] || !$has} { return $default }
    set v [dict get $d $key]
    if {$v eq "null"} { return $default }
    return $v
}

proc ::vmdai::vm::_bool {v} {
    if {[string is boolean -strict $v]} { return [expr {$v ? 1 : 0}] }
    return 0
}

proc ::vmdai::vm::_secs {ts} {
    if {![string is double -strict $ts]} { return 0 }
    return [expr {wide(floor($ts))}]
}

proc ::vmdai::vm::_first_line {s} {
    foreach line [split $s "\n"] {
        if {[string trim $line] ne ""} { return [string trim $line] }
    }
    return ""
}

proc ::vmdai::vm::_dur_text {ms} {
    if {![string is double -strict $ms]} { return "" }
    if {$ms < 10000} { return [format "%.1f s" [expr {$ms / 1000.0}]] }
    return [format "%d s" [expr {int(round($ms / 1000.0))}]]
}

proc ::vmdai::vm::_new_block {sv} {
    upvar 1 $sv S
    dict incr S bseq
    return b[dict get $S bseq]
}

# Encode one op as a single line that `lindex` parses back exactly
# (tests/fixtures/ops/<name>.ops holds one op per line).
proc ::vmdai::vm::format_op {op} {
    set words {}
    foreach w $op {
        if {$w ne "" && [regexp {^[A-Za-z0-9_.:/+@%,=-]+$} $w]} {
            lappend words $w
        } else {
            lappend words "\"[string map {\\ \\\\ \" \\\" \n \\n \r \\r \t \\t} $w]\""
        }
    }
    return [join $words " "]
}

# ---- runs, phases -----------------------------------------------------------

proc ::vmdai::vm::_ensure_run {sv req ts} {
    upvar 1 $sv S
    if {$req eq "" || [dict exists $S runs $req]} { return {} }
    return [_open_run S $req "" 28 1 $ts]
}

proc ::vmdai::vm::_open_run {sv req model max_turns vision ts} {
    upvar 1 $sv S
    dict incr S rseq
    set run r[dict get $S rseq]
    dict set S runs $req [dict create id $run model $model t0 [_secs $ts] \
        max_turns $max_turns vision $vision steps 0 failed 0 last_tcl "" \
        applied 0 status running]
    dict set S request $req
    return [list [list run.open $run $req $model [_secs $ts]]]
}

proc ::vmdai::vm::_run_id {sv req} {
    upvar 1 $sv S
    if {$req ne "" && [dict exists $S runs $req]} { return [dict get $S runs $req id] }
    return ""
}

# Set the busy phase; returns a status op only when the text changes.
proc ::vmdai::vm::_phase {sv text ts {timed 1}} {
    upvar 1 $sv S
    if {[dict get $S busy] && [dict get $S phase] eq $text} { return {} }
    dict set S busy 1
    dict set S phase $text
    dict set S phase_t0 [expr {$timed ? [_secs $ts] : ""}]
    return [list [list status busy $text [dict get $S phase_t0]]]
}

proc ::vmdai::vm::_tool_phase {name n} {
    switch -glob -- $name {
        run_vmd_command      { return "Step $n · running VMD command" }
        capture_vmd_snapshot { return "Step $n · rendering snapshot" }
        search_docs          { return "Step $n · searching docs" }
        wiki_*               { return "Step $n · reading the wiki" }
        default              { return "Step $n · running $name" }
    }
}

# ---- blocks -----------------------------------------------------------------

# Close the open block. A reasoning block is sealed here (the thinking is
# over once anything else arrives); a text block stays unsealed until its
# assistant/message.
proc ::vmdai::vm::_close_open {sv ts} {
    upvar 1 $sv S
    set open [dict get $S open]
    dict set S open {}
    if {$open eq "" || [dict get $open kind] ne "reasoning"} { return {} }
    return [_seal_reason S [dict get $open id] [expr {[_secs $ts] - [dict get $open t0]}]]
}

proc ::vmdai::vm::_seal_reason {sv b secs} {
    upvar 1 $sv S
    if {[lsearch -exact [dict get $S rsealed] $b] >= 0} { return {} }
    dict lappend S rsealed $b
    if {$secs < 0} { set secs 0 }
    return [list [list reasoning.seal $b $secs]]
}

proc ::vmdai::vm::_on_text_chunk {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set open [dict get $S open]
    if {$open ne "" && [dict get $open kind] eq "text"
            && [dict get $open request_id] eq $req && [dict get $open turn] eq $turn} {
        return [list [list block.append [dict get $open id] $text]]
    }
    set ops [_close_open S $ts]
    lappend ops {*}[_ensure_run S $req $ts]
    set b [_new_block S]
    dict set S open [dict create kind text id $b request_id $req turn $turn t0 [_secs $ts]]
    dict lappend S texts "$req|$turn" $b
    lappend ops [list block.open $b assistant $turn] [list block.append $b $text]
    if {$req ne ""} { lappend ops {*}[_phase S "Writing" $ts] }
    return $ops
}

proc ::vmdai::vm::_on_reason_chunk {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set open [dict get $S open]
    if {$open ne "" && [dict get $open kind] eq "reasoning"
            && [dict get $open request_id] eq $req && [dict get $open turn] eq $turn} {
        return [list [list reasoning.append [dict get $open id] $text]]
    }
    set ops [_close_open S $ts]
    lappend ops {*}[_ensure_run S $req $ts]
    set b [_new_block S]
    dict set S open [dict create kind reasoning id $b request_id $req turn $turn t0 [_secs $ts]]
    dict lappend S reasons "$req|$turn" $b
    lappend ops [list reasoning.open $b $turn] [list reasoning.append $b $text]
    if {$req ne ""} { lappend ops {*}[_phase S "Thinking" $ts] }
    return $ops
}

# The per-turn assistant/message replaces the streamed text (§2c Sealing).
# A final answer is re-opened under a rule so that live and replayed chats
# render the same (the rule separates the work log from the answer).
proc ::vmdai::vm::_on_assistant_message {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set final [_bool [_get $md final false]]
    set key "$req|$turn"
    set pending [_get [dict get $S texts] $key]
    dict unset S texts $key
    set ops [_ensure_run S $req $ts]
    if {[string trim $text] eq ""} {
        foreach b $pending { lappend ops [list block.discard $b] }
        return $ops
    }
    if {$final && $req ne ""} {
        foreach b $pending { lappend ops [list block.discard $b] }
        set b [_new_block S]
        lappend ops [list rule [_run_id S $req]] [list block.open $b assistant $turn] \
            [list block.seal $b $text]
        return $ops
    }
    if {[llength $pending]} {
        set b [lindex $pending 0]
        lappend ops [list block.seal $b $text]
        foreach extra [lrange $pending 1 end] { lappend ops [list block.discard $extra] }
        return $ops
    }
    set b [_new_block S]
    lappend ops [list block.open $b assistant $turn] [list block.seal $b $text]
    return $ops
}

# A sealed reasoning/message: seals the live block, or renders the whole
# block when replaying a stored chat (no chunks were seen).
proc ::vmdai::vm::_on_reasoning_message {sv md text ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    set turn [_get $md turn 0]
    set secs [_get $md duration_s ""]
    if {![string is double -strict $secs]} {
        set ms [_get $md duration_ms ""]
        set secs [expr {[string is double -strict $ms] ? $ms / 1000.0 : 0}]
    }
    set secs [expr {int(round($secs))}]
    set blocks [_get [dict get $S reasons] "$req|$turn"]
    if {[llength $blocks]} {
        return [_seal_reason S [lindex $blocks end] $secs]
    }
    if {[string trim $text] eq ""} { return {} }
    set ops [_ensure_run S $req $ts]
    set b [_new_block S]
    dict lappend S reasons "$req|$turn" $b
    lappend ops [list reasoning.open $b $turn] [list reasoning.append $b $text]
    lappend ops {*}[_seal_reason S $b $secs]
    return $ops
}

proc ::vmdai::vm::_on_user_message {sv text ts} {
    upvar 1 $sv S
    set b [_new_block S]
    return [list [list block.open $b user 0 [_secs $ts]] [list block.append $b $text]]
}

# turn.retry discards everything the dropped attempt of that turn showed.
proc ::vmdai::vm::_on_turn_retry {sv md} {
    upvar 1 $sv S
    set key "[_get $md request_id]|[_get $md turn 0]"
    set ops {}
    foreach b [_get [dict get $S texts] $key] { lappend ops [list block.discard $b] }
    foreach b [_get [dict get $S reasons] $key] { lappend ops [list block.discard $b] }
    dict unset S texts $key
    dict unset S reasons $key
    return $ops
}

# ---- tools ------------------------------------------------------------------

proc ::vmdai::vm::_tool_text {name input} {
    switch -glob -- $name {
        run_vmd_command      { return [_get $input command] }
        capture_vmd_snapshot { return [_get $input purpose] }
        search_docs          { return [_get $input query] }
        wiki_*               { return [_get $input page] }
        default              { return [_get $input command] }
    }
}

proc ::vmdai::vm::_on_tool_started {sv md ts} {
    upvar 1 $sv S
    set k [_get $md call_key]
    if {$k eq "" || [dict exists $S tools $k]} { return {} }
    set req [_get $md request_id]
    set ops [_ensure_run S $req $ts]
    set run [_run_id S $req]
    set n 1
    if {[dict exists $S runs $req]} {
        set n [expr {[dict get $S runs $req steps] + 1}]
        dict set S runs $req steps $n
    }
    set name [_get $md tool_name]
    set input [_get $md input]
    dict set S tools $k [dict create run $run request_id $req tool_name $name \
        executor [_get $md executor tcl] state running index $n finished 0]
    lappend ops [list tool.open $k $name [_tool_text $name $input] \
        [_get $md executor tcl] [_get $md origin model] [_get $input rationale]]
    if {$run ne ""} { lappend ops [list run.chip $run $k running] }
    lappend ops {*}[_phase S [_tool_phase $name $n] $ts]
    return $ops
}

proc ::vmdai::vm::tool_state {md} {
    switch -- [_get $md executed yes] {
        no      { return notrun }
        unknown { return unknown }
    }
    if {[_bool [_get $md ok false]]} { return ok }
    return err
}

# Inline result and preview lines for a tool's output (Part B V4 Results).
proc ::vmdai::vm::_result_view {output} {
    set o [string trim $output]
    if {$o eq "" || [regexp {^(0|1|atomselect[0-9]+)$} $o]} { return [list "" {}] }
    if {[string first "\n" $o] < 0 && [string length $o] <= 24} {
        if {[string is double -strict $o] && [regexp {[.eE]} $o]} {
            set o [format %.6g $o]
        }
        return [list $o {}]
    }
    set lines [split [string trimright $output "\n"] "\n"]
    if {[llength $lines] <= 4} { return [list "" $lines] }
    set more [expr {[llength $lines] - 3}]
    return [list "" [concat [lrange $lines 0 2] [list "… $more more lines"]]]
}

proc ::vmdai::vm::_tool_detail {md state} {
    set output [_get $md output]
    lassign [_result_view $output] inline preview
    set label ""
    set error ""
    switch -- $state {
        notrun  { set label "not run"; set inline ""; set preview {} }
        unknown { set label "stopped while running · outcome unknown" }
        err     { set error [_first_line [_get $md error]]; set inline "" }
    }
    set stmts [_get $md statements]
    set failed [_get $stmts failed]
    return [dict create label $label error $error inline $inline preview $preview \
        output $output output_path [_get $md output_path] \
        total [_get $stmts total] applied [_get $stmts applied] \
        failed_index [_get $failed index] failed_text [_get $failed text] \
        late 0]
}

proc ::vmdai::vm::_chip_state {state k warned} {
    if {$state eq "unknown"} { return warn }
    if {$state eq "ok" && [lsearch -exact $warned $k] >= 0} { return warn }
    return $state
}

proc ::vmdai::vm::_on_tool_finished {sv md ts} {
    upvar 1 $sv S
    set k [_get $md call_key]
    if {$k eq "" || ![dict exists $S tools $k]} { return {} }
    set tool [dict get $S tools $k]
    if {[dict get $tool finished]} { return {} }
    set state [tool_state $md]
    set was [dict get $tool state]
    dict set S tools $k state $state
    dict set S tools $k finished 1
    set run [dict get $tool run]
    set req [dict get $tool request_id]
    set image [_get $md image]
    set thumb [expr {$image eq "" ? "" : [_get $image thumb_path]}]
    set ops [list [list tool.close $k $state [_dur_text [_get $md duration_ms ""]] \
        [_tool_detail $md $state] $thumb]]
    if {$run ne ""} {
        lappend ops [list run.chip $run $k [_chip_state $state $k [dict get $S warned]]]
    }
    if {$image ne ""} {
        set vision 1
        if {[dict exists $S runs $req]} { set vision [dict get $S runs $req vision] }
        set w [_get $image src_width [_get $image width]]
        set h [_get $image src_height [_get $image height]]
        lappend ops [list snapshot $k $thumb [_get $image path] $w $h \
            [_get $md saved_path] $vision [_get $image renderer TachyonInternal]]
    }
    if {[dict exists $S runs $req] && [dict get $tool executor] eq "tcl"
            && [dict get $tool tool_name] eq "run_vmd_command"} {
        if {$state eq "err" && $was ne "err"} {
            dict set S runs $req failed [expr {[dict get $S runs $req failed] + 1}]
        }
        if {$state in {ok err}} { dict set S runs $req last_tcl $state }
        set stmts [_get $md statements]
        set applied [_get $stmts applied ""]
        if {![string is integer -strict $applied]} {
            set applied [expr {$state eq "ok" ? 1 : 0}]
        }
        dict set S runs $req applied [expr {[dict get $S runs $req applied] + $applied}]
    }
    if {[dict get $S request] eq $req && [dict get $S busy]} {
        lappend ops {*}[_phase S "Thinking" $ts]
    }
    return $ops
}

# ---- status, errors, request lifecycle ------------------------------------

proc ::vmdai::vm::_on_status {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    switch -- [_get $md phase] {
        retrying {
            set text "Retrying [_get $md attempt ?]/[_get $md max_attempts ?] in [_get $md wait_s ?] s"
            return [_phase S $text $ts 0]
        }
        loading_model {
            set model ""
            if {[dict exists $S runs $req]} { set model [dict get $S runs $req model] }
            return [_phase S [string trim "Loading $model"] $ts]
        }
        wrapping_up   { return [_phase S "Writing a summary" $ts] }
        loop_detected {
            set k [_get $md call_key]
            if {$k eq ""} { return {} }
            dict lappend S warned $k
            if {![dict exists $S tools $k]} { return {} }
            set run [dict get $S tools $k run]
            set state [dict get $S tools $k state]
            if {$run eq "" || $state eq "running"} { return {} }
            return [list [list run.chip $run $k [_chip_state $state $k [dict get $S warned]]]]
        }
        context_near_full {
            return [list [list notice info "Context is nearly full; older tool output is shortened"]]
        }
        turn_truncated {
            return [list [list notice info "The reply was cut off, so its tool calls were not run"]]
        }
        think_unsupported {
            return [list [list notice info "This model does not support thinking; continuing without it"]]
        }
    }
    return {}
}

proc ::vmdai::vm::_on_request_started {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    if {$req eq "" || [dict exists $S runs $req]} { return {} }
    set max_turns [_get $md max_turns 28]
    set ops [_open_run S $req [_get $md model] $max_turns [_bool [_get $md vision true]] $ts]
    dict set S stopping 0
    lappend ops {*}[_phase S "Thinking" $ts]
    return $ops
}

proc ::vmdai::vm::_on_turn_started {sv md ts} {
    upvar 1 $sv S
    if {[dict get $S request] ne [_get $md request_id]} { return {} }
    return [_phase S "Thinking" $ts]
}

proc ::vmdai::vm::_close_run {sv req status final_text_empty duration_s} {
    upvar 1 $sv S
    set run [dict get $S runs $req]
    dict set S runs $req status $status
    set failed [dict get $run failed]
    set recovered [expr {$failed > 0 && [dict get $run last_tcl] eq "ok" && $status ne "error"}]
    set ops {}
    if {[dict get $run applied] > 0} {
        lappend ops [list footer [dict get $run id] [dict get $run applied] ""]
    }
    lappend ops [list run.close [dict get $run id] $status [dict get $run steps] $failed \
        $recovered $duration_s $final_text_empty [dict get $run max_turns]]
    if {[dict get $S request] eq $req} {
        dict set S request ""
        dict set S busy 0
        dict set S phase ""
        dict set S phase_t0 ""
        dict set S stopping 0
        lappend ops [list status idle]
    }
    return $ops
}

proc ::vmdai::vm::_on_request_finished {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    if {$req eq "" || ![dict exists $S runs $req]} { return {} }
    if {[dict get $S runs $req status] ne "running"} { return {} }
    set status [_get $md status complete]
    set ms [_get $md duration_ms ""]
    if {[string is double -strict $ms]} {
        set secs [expr {int(round($ms / 1000.0))}]
    } else {
        set secs [expr {[_secs $ts] - [dict get $S runs $req t0]}]
    }
    set empty [_bool [_get $md final_text_empty false]]
    return [_close_run S $req $status $empty $secs]
}

# ---- entry point ------------------------------------------------------------

proc ::vmdai::vm::apply {stateVar event} {
    upvar 1 $stateVar S
    set role [_get $event role]
    set type [_get $event type]
    set text [_get $event text]
    set md [_get $event metadata]
    set ts [_get $event ts 0]
    if {$type eq "chunk"} {
        switch -- $role {
            assistant { return [_on_text_chunk S $md $text $ts] }
            reasoning { return [_on_reason_chunk S $md $text $ts] }
        }
        return {}
    }
    set ops [_close_open S $ts]
    set kind [_get $md kind]
    switch -- $role/$type {
        user/message      { lappend ops {*}[_on_user_message S $text $ts] }
        assistant/message { lappend ops {*}[_on_assistant_message S $md $text $ts] }
        reasoning/message { lappend ops {*}[_on_reasoning_message S $md $text $ts] }
        system/message {
            if {[_get $md notice] eq "tcl_trust_boundary"} {
                dict set S trust_notice 1
            } elseif {[string trim $text] ne ""} {
                lappend ops [list notice info $text]
            }
        }
        system/state {
            switch -glob -- $kind {
                request.started  { lappend ops {*}[_on_request_started S $md $ts] }
                request.finished { lappend ops {*}[_on_request_finished S $md $ts] }
                turn.started     { lappend ops {*}[_on_turn_started S $md $ts] }
                turn.retry       { lappend ops {*}[_on_turn_retry S $md] }
                tool.started     { lappend ops {*}[_on_tool_started S $md $ts] }
                tool.finished    { lappend ops {*}[_on_tool_finished S $md $ts] }
                status           { lappend ops {*}[_on_status S $md $ts] }
                usage            { }
            }
        }
    }
    return $ops
}
```

Note on names: `apply` is defined inside `::vmdai::vm`, so within this namespace it shadows Tcl's lambda `apply`. Nothing in this file uses lambdas; keep it that way.

- [ ] **Step 6: Run the tests (the goldens do not exist yet)**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -5`
Expected: `3 failed, 19 passed`; the failures are the three `test_ops_golden[…]`, each with `AssertionError: missing golden …/tests/fixtures/ops/<name>.ops; run with CHATVMD_UPDATE_GOLDENS=1`. The scenario checks ran first and passed.

- [ ] **Step 7: Generate the op goldens and review them**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tcl_viewmodel.py -q -k ops_golden 2>&1 | tail -1`
Expected: `3 passed, 19 deselected`.

Run:

```bash
grep -n '^run.open\|^run.close\|^rule\|^snapshot\|^tool.close [0-9]* [a-z]*' tests/fixtures/ops/03_conversation.ops | cut -c1-120
grep -n '^reasoning\.\(open\|seal\)\|^rule\|^block.seal' tests/fixtures/ops/reasoning_answer.ops | cut -c1-120
grep -n '^block.discard\|^rule\|^block.seal' tests/fixtures/ops/turn_retry.ops | cut -c1-120
```

Expected (plan 07's scenario scripts and its id, path and time normalisation make these exact; the model name is the fixture's `request.started.model`):
- `03_conversation.ops`: `run.open r1 req_000000000001 qwen3.8:27b …` and `run.open r2 req_000000000002 …`; five `tool.close` lines whose states read `ok`, `err`, `ok`, `ok`, `ok`; one line `snapshot 000000000004 @REPO@/docs/design/round1/assets/snap_1hck.png @REPO@/docs/design/round1/assets/snap_1hck.png 1280 1547 "" 1 TachyonInternal`; `rule r1` and `rule r2`; `run.close r1 complete 4 1 1 …` and `run.close r2 complete 1 0 0 …`.
- `reasoning_answer.ops`: two `reasoning.open`/`reasoning.seal` pairs (turns 1 and 2), then `rule r1` and one `block.seal … "1hck has 2442 atoms."`.
- `turn_retry.ops`: the first `block.discard` is not followed by `rule` (the dropped attempt); the file ends with `block.discard`, `rule r1`, `block.open`, `block.seal … "Done: 1hck is loaded."`.

Also read one golden end to end (`less tests/fixtures/ops/03_conversation.ops`) and check that no text appears twice and that every `status busy` line matches the phase that follows it.

- [ ] **Step 8: Run the tests and the suite**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -1`
Expected: `22 passed`.

Run: `python -m pytest tests/test_tcl_lint.py -q 2>&1 | tail -1 && env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: the lint passes (it now scans `plugin/viewmodel.tcl`), and the suite reports `B+22 passed`, 0 failed, under 60 s.

- [ ] **Step 9: Commit**

```bash
git add plugin/viewmodel.tcl tests/helpers/panel_goldens.py tests/tcl/test_viewmodel.tcl tests/test_tcl_viewmodel.py \
        tests/fixtures/ops/03_conversation.ops tests/fixtures/ops/reasoning_answer.ops tests/fixtures/ops/turn_retry.ops
git commit -F - <<'MSG'
feat(plugin): view-model for v2 events: blocks, sealing, reasoning, runs (P08-T01)

::vmdai::vm::apply turns one decoded §2c envelope into render ops. Blocks
close on role, request or turn changes and on every non-chunk event; the
per-turn assistant/message seals the streamed text; a final answer is
re-opened under the run's rule so live and replayed chats render alike;
turn.retry discards the dropped attempt. Op goldens replay plan 07's
scenario fixtures, with scenario checks that survive regeneration.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: P08-T02 — View-model: tool states, labels, late, errors, local events

**Files:**
- Modify: `plugin/viewmodel.tcl` (created in Task 1: procs `_tool_detail`, `_on_tool_finished` and `apply`; append new procs)
- Modify: `tests/tcl/test_viewmodel.tcl` (insert a block before the final `cleanupTests`)
- Modify: `tests/test_tcl_viewmodel.py` (three insertions, anchored below)
- Create (generated in Step 6, then committed): `tests/fixtures/ops/loop_guard.ops`, `tests/fixtures/ops/11_dead_runtime.ops`

**Interfaces:**
- Consumes: local kinds (P07-T08): `local.connection {state, detail, request_lost}`, `local.request_ended {request_id}`, `local.send_failed {code, message}` as `system/state` envelopes; `::vmdai::vm::tool_state` (Task 1)
- Produces:
  - `::vmdai::vm::tool_state meta -> ok|err|notrun|unknown`
  - `::vmdai::vm::notrun_label meta -> string`
  - `::vmdai::vm::local_event kind fields -> event`
  - (also) `local_event` takes an optional `ts` key in `fields` (the event time; default `[clock seconds]`) and returns `{seq 0 ts <ts> role system type state text "" metadata {kind <kind> …fields}}`; `error.card` actions default by code (`auth` → `open_settings`, `billing` → `switch_profile`, `model_not_found` → `choose_model`, `unreachable` → `test_connection`, `NO_MODEL` → `open_settings`, anything else → `open_log`); a lost or ended request is closed with `run.close` status `lost` or `ended`, which `::vmdai::vm::run_summary` (Task 3) knows

The labels (Part B V4, first match wins in C1–C4 order): `blocked` set → `not run · blocked: <word>` (C1); `statements.failed` set → `not run · incomplete Tcl` (C3); error `not executed: loop guard` → `not run · loop guard` (C4); error `cancelled` → `not run · stopped`; an error starting `VMD did not pick up the command` → that sentence; otherwise `not run · <first line of the error>` (covers C2's refusal), or `not run` without an error. A `late: true` result re-closes its row (state ok or err) with the label `(finished late)`, even after `request.finished` or the next `request.started`; a second non-late `tool.finished` is ignored.

- [ ] **Step 1: Add the failing tcltests**

In `tests/tcl/test_viewmodel.tcl`, insert this block, followed by one empty line, immediately before the final `cleanupTests` line:

```tcl
# ---- P08-T02 ---------------------------------------------------------------

test notrun_label_order {not-run labels: first match wins in C1-C4 order} -body {
    set all [dict create executed no ok false \
        blocked [list [dict create id cmd_exec word exec text {exec ls}]] \
        statements [dict create total 2 applied 0 failed [dict create index 2 text "x \{" error_info null]] \
        error cancelled]
    set r {}
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all blocked null
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all statements null
    dict set all error "not executed: loop guard"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error cancelled
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error "VMD did not pick up the command (45 s)"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error "This panel cannot ask for approval\nmore"
    lappend r [::vmdai::vm::notrun_label $all]
    dict set all error ""
    lappend r [::vmdai::vm::notrun_label $all]
} -result {{not run · blocked: exec} {not run · incomplete Tcl} {not run · loop guard} {not run · stopped} {VMD did not pick up the command} {not run · This panel cannot ask for approval} {not run}}

test tool_state_values {tool_state maps executed/ok to ok|err|notrun|unknown} -body {
    list [::vmdai::vm::tool_state {ok true executed yes}] \
         [::vmdai::vm::tool_state {ok false executed yes}] \
         [::vmdai::vm::tool_state {ok false executed no}] \
         [::vmdai::vm::tool_state {ok false executed unknown}] \
         [::vmdai::vm::tool_state {ok true}]
} -result {ok err notrun unknown ok}

test unknown_call_key_ignored {tool.finished before tool.started, or for an unknown call_key, does nothing} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tfin req_a k_nope] [tstart req_a k1] [tstart req_a k1]
    set before $S
    set ops [::vmdai::vm::apply S [tfin req_a k_other]]
    list $ops [expr {$S eq $before}] [llength [only [feed S [tstart req_a k1]] tool.open]]
} -result {{} 1 0}

test second_finished_ignored_unless_late {a repeated tool.finished is ignored unless late:true} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1] [tfin req_a k1 {ok false executed unknown}]
    set again [::vmdai::vm::apply S [tfin req_a k1 {ok true}]]
    set late [::vmdai::vm::apply S [tfin req_a k1 {ok true late true output 7.5}]]
    list $again [lrange [lindex $late 0] 0 2] [dict get [lindex $late 0 4] label] [lindex $late 1]
} -result {{} {tool.close k1 ok} {(finished late)} {run.chip r1 k1 ok}}

test late_updates_row_after_finished {a late result updates its row after request.finished and after the next request started} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1] [tfin req_a k1 {ok false executed unknown}] \
        [st request.finished {request_id req_a status cancelled tool_calls 1 final_text_empty false duration_ms 3000}] \
        [started req_b]
    set ops [::vmdai::vm::apply S [tfin req_a k1 {ok false late true error {boom}}]]
    list [lrange [lindex $ops 0] 0 1] [dict get [lindex $ops 0 4] error] [lindex $ops 1] [llength $ops]
} -result {{tool.close k1} boom {run.chip r1 k1 err} 2}

test error_card_actions_and_no_model {error events become cards with an action; NO_MODEL is a local card; truncation, context and thinking get a muted notice, never a card} -body {
    ::vmdai::vm::init S
    set r {}
    lappend r [::vmdai::vm::apply S [ev error message "Model not found: qwen3.8:27b" \
        {request_id req_a code model_not_found http_status 404 hint {ollama pull qwen3.8:27b} action choose_model}]]
    lappend r [::vmdai::vm::apply S [ev error message "Credit balance too low" {request_id req_a code billing}]]
    lappend r [::vmdai::vm::apply S [::vmdai::vm::local_event local.send_failed \
        {code NO_MODEL message {Set up a model in Settings.}}]]
    lappend r [only [feed S [st status {request_id req_a phase turn_truncated}] \
        [st status {request_id req_a phase context_near_full}] \
        [st status {request_id req_a phase think_unsupported}]] {notice error.card}]
} -result {{{error.card model_not_found {Model not found: qwen3.8:27b} {ollama pull qwen3.8:27b} choose_model}} {{error.card billing {Credit balance too low} {} switch_profile}} {{error.card NO_MODEL {No model configured} {Set up a model in Settings.} open_settings}} {{notice info {The reply was cut off, so its tool calls were not run}} {notice info {Context is nearly full; older tool output is shortened}} {notice info {This model does not support thinking; continuing without it}}}}

test local_connection_notices {one notice per connection state change; a lost request settles its rows} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1]
    set ops [feed S \
        [::vmdai::vm::local_event local.connection {state reconnecting detail 127.0.0.1:8765 request_lost false ts 1727180000}] \
        [::vmdai::vm::local_event local.connection {state down detail 127.0.0.1:8765 request_lost false ts 1727180001}] \
        [::vmdai::vm::local_event local.connection {state ready detail 127.0.0.1:8765 request_lost true ts 1727180002}]]
    list [only $ops notice] [lrange [lindex [only $ops tool.close] 0] 0 2] \
         [lrange [lindex [only $ops run.close] 0] 0 1] [lindex $ops end]
} -result {{{notice warn {Connection lost at 12:13 PM · your draft is kept}} {notice warn {Reconnected: request lost} retry}} {tool.close k1 unknown} {run.close r1} {status idle}}

test request_ended_local {local.request_ended ends a busy request with a note} -body {
    ::vmdai::vm::init S
    feed S [started req_a]
    set ops [::vmdai::vm::apply S [::vmdai::vm::local_event local.request_ended {request_id req_a}]]
    list [lindex $ops 0] [lrange [lindex [only $ops run.close] 0] 0 2] [lindex $ops end] [dict get $S busy]
} -result {{notice info {Request ended (details may be missing)}} {run.close r1 ended} {status idle} 0}
```

`tool_state_values` and `unknown_call_key_ignored` pin behaviour Task 1 already has (Task 1 needed `tool_state` to close rows), so they pass before Step 4. The last part of `error_card_actions_and_no_model` pins Part B V4's rule that a truncated turn, a nearly full context and unsupported thinking get only a muted notice, never a card; those notices come from Task 1's `_on_status`, and the case fails before Step 4 only because `local_event` does not exist yet.

- [ ] **Step 2: Extend the pytest wrapper**

In `tests/test_tcl_viewmodel.py`:

1. Directly after the `UNIT_TESTS = [ … ]` list (it ends with the lines `    "trust_notice_no_op",` and `]`), insert:

```python
UNIT_TESTS += [
    "notrun_label_order",
    "tool_state_values",
    "unknown_call_key_ignored",
    "second_finished_ignored_unless_late",
    "late_updates_row_after_finished",
    "error_card_actions_and_no_model",
    "local_connection_notices",
    "request_ended_local",
]
```

2. Immediately before the line `def replay_ops(name: str, tmp_path: Path) -> str:`, insert:

```python
def test_notrun_label_order(vm_result):
    assert_tcltests(vm_result, ["notrun_label_order", "tool_state_values"])


def test_unknown_call_key_ignored(vm_result):
    assert_tcltests(vm_result, ["unknown_call_key_ignored"])


def test_second_finished_ignored_unless_late(vm_result):
    assert_tcltests(vm_result, ["second_finished_ignored_unless_late"])


def test_late_updates_row_after_finished(vm_result):
    assert_tcltests(vm_result, ["late_updates_row_after_finished"])


def test_error_card_actions_and_no_model(vm_result):
    assert_tcltests(vm_result, ["error_card_actions_and_no_model"])


def test_local_events(vm_result):
    assert_tcltests(vm_result, ["local_connection_notices", "request_ended_local"])


```

3. Immediately before the line `def run_scenario_checks(name: str, ops: List[List[str]]) -> None:`, insert (this adds `loop_guard` and `11_dead_runtime` to `test_ops_golden`):

```python
@scenario("loop_guard")
def _stuck_run_ends_with_wrap_up(ops):
    assert [op[2] for op in ops if op[0] == "run.close"] == ["stuck"]
    last_rule = max(i for i, op in enumerate(ops) if op[0] == "rule")
    assert any(op[0] == "block.seal" for op in ops[last_rule:])
    assert ops[-1] == ["status", "idle"]


@scenario("11_dead_runtime")
def _lost_runtime_notices(ops):
    assert any(op[0] == "run.open" for op in ops)
    assert any(op[0] == "tool.open" for op in ops)
    assert not any(op[0] == "run.close" and op[2] == "complete" for op in ops)
    notices = [op[2] for op in ops if op[0] == "notice"]
    assert any(n.startswith("Connection lost at ") for n in notices), notices


```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -16`
Expected: `14 failed, 24 passed`. Failing: `test_viewmodel_unit[…]` for `notrun_label_order`, `second_finished_ignored_unless_late`, `late_updates_row_after_finished`, `error_card_actions_and_no_model`, `local_connection_notices` and `request_ended_local` (`invalid command name "::vmdai::vm::notrun_label"` / `…::local_event"`, or the wrong ops), `test_viewmodel_counts`, the five new named tests, `test_ops_golden[11_dead_runtime]` (the scenario check finds no "Connection lost at" notice) and `test_ops_golden[loop_guard]` (missing golden).

- [ ] **Step 4: Implement the labels, late results, error cards and local events**

In `plugin/viewmodel.tcl`:

1. Replace the whole proc `::vmdai::vm::_tool_detail {md state}` with:

```tcl
proc ::vmdai::vm::_tool_detail {md state late} {
    set output [_get $md output]
    lassign [_result_view $output] inline preview
    set label ""
    set error ""
    switch -- $state {
        notrun  { set label [notrun_label $md]; set inline ""; set preview {} }
        unknown { set label "stopped while running · outcome unknown" }
        err     { set error [_first_line [_get $md error]]; set inline "" }
    }
    if {$late} { set label [string trim "$label (finished late)"] }
    set stmts [_get $md statements]
    set failed [_get $stmts failed]
    return [dict create label $label error $error inline $inline preview $preview \
        output $output output_path [_get $md output_path] \
        total [_get $stmts total] applied [_get $stmts applied] \
        failed_index [_get $failed index] failed_text [_get $failed text] \
        late $late]
}
```

2. Replace the whole proc `::vmdai::vm::_on_tool_finished` with:

```tcl
proc ::vmdai::vm::_on_tool_finished {sv md ts} {
    upvar 1 $sv S
    set k [_get $md call_key]
    if {$k eq "" || ![dict exists $S tools $k]} { return {} }
    set late [_bool [_get $md late false]]
    set tool [dict get $S tools $k]
    if {[dict get $tool finished] && !$late} { return {} }
    set state [tool_state $md]
    if {$late && $state ni {ok err}} { return {} }
    set was [dict get $tool state]
    dict set S tools $k state $state
    dict set S tools $k finished 1
    set run [dict get $tool run]
    set req [dict get $tool request_id]
    set image [_get $md image]
    set thumb [expr {$image eq "" ? "" : [_get $image thumb_path]}]
    set ops [list [list tool.close $k $state [_dur_text [_get $md duration_ms ""]] \
        [_tool_detail $md $state $late] $thumb]]
    if {$run ne ""} {
        lappend ops [list run.chip $run $k [_chip_state $state $k [dict get $S warned]]]
    }
    if {$image ne ""} {
        set vision 1
        if {[dict exists $S runs $req]} { set vision [dict get $S runs $req vision] }
        set w [_get $image src_width [_get $image width]]
        set h [_get $image src_height [_get $image height]]
        lappend ops [list snapshot $k $thumb [_get $image path] $w $h \
            [_get $md saved_path] $vision [_get $image renderer TachyonInternal]]
    }
    if {[dict exists $S runs $req] && [dict get $tool executor] eq "tcl"
            && [dict get $tool tool_name] eq "run_vmd_command"} {
        if {$state eq "err" && $was ne "err"} {
            dict set S runs $req failed [expr {[dict get $S runs $req failed] + 1}]
        }
        if {$state in {ok err}} { dict set S runs $req last_tcl $state }
        set stmts [_get $md statements]
        set applied [_get $stmts applied ""]
        if {![string is integer -strict $applied]} {
            set applied [expr {$state eq "ok" ? 1 : 0}]
        }
        if {!$late || $was ni {ok err}} {
            dict set S runs $req applied [expr {[dict get $S runs $req applied] + $applied}]
        }
    }
    if {!$late && [dict get $S request] eq $req && [dict get $S busy]} {
        lappend ops {*}[_phase S "Thinking" $ts]
    }
    return $ops
}
```

3. In `proc ::vmdai::vm::apply`, replace

```tcl
        reasoning/message { lappend ops {*}[_on_reasoning_message S $md $text $ts] }
        system/message {
```

with

```tcl
        reasoning/message { lappend ops {*}[_on_reasoning_message S $md $text $ts] }
        error/message     { lappend ops {*}[_on_error $md $text] }
        system/message {
```

and replace

```tcl
                usage            { }
            }
```

with

```tcl
                usage            { }
                local.*          { lappend ops {*}[_on_local S $kind $md $ts] }
            }
```

4. Append to the end of the file (after one empty line):

```tcl
# First line wins, in C1-C4 order (Part B V4 "not run").
proc ::vmdai::vm::notrun_label {md} {
    set blocked [_get $md blocked]
    if {[llength $blocked]} {
        return "not run · blocked: [_get [lindex $blocked 0] word exec]"
    }
    set stmts [_get $md statements]
    if {$stmts ne "" && [_get $stmts failed] ne ""} { return "not run · incomplete Tcl" }
    set err [string trim [_get $md error]]
    if {$err eq "not executed: loop guard"} { return "not run · loop guard" }
    if {$err eq "cancelled"} { return "not run · stopped" }
    if {[string match "VMD did not pick up the command*" $err]} {
        return "VMD did not pick up the command"
    }
    set first [_first_line $err]
    if {$first eq ""} { return "not run" }
    return "not run · $first"
}

proc ::vmdai::vm::_default_action {code} {
    switch -- $code {
        auth            { return open_settings }
        billing         { return switch_profile }
        model_not_found { return choose_model }
        unreachable     { return test_connection }
        NO_MODEL        { return open_settings }
        default         { return open_log }
    }
}

proc ::vmdai::vm::_on_error {md text} {
    set code [_get $md code other]
    set action [_get $md action [_default_action $code]]
    return [list [list error.card $code $text [_get $md hint] $action]]
}

# ---- plugin-local events (P07-T08 kinds) -----------------------------------

proc ::vmdai::vm::local_event {kind fields} {
    set ts [clock seconds]
    if {[dict exists $fields ts]} {
        set ts [dict get $fields ts]
        dict unset fields ts
    }
    return [dict create seq 0 ts $ts role system type state text "" \
        metadata [dict merge [dict create kind $kind] $fields]]
}

proc ::vmdai::vm::_clock_text {secs} {
    return [string trimleft [clock format $secs -format "%I:%M %p"] 0]
}

# The request was lost (restart) or ended while we were away: settle every
# running row and close the run, so the panel never stays busy.
proc ::vmdai::vm::_lose_request {sv status ts} {
    upvar 1 $sv S
    set req [dict get $S request]
    if {$req eq "" || ![dict exists $S runs $req]} { return {} }
    set ops {}
    dict for {k tool} [dict get $S tools] {
        if {[dict get $tool request_id] ne $req || [dict get $tool state] ne "running"} continue
        dict set S tools $k state unknown
        dict set S tools $k finished 1
        set label [expr {$status eq "lost" ? "connection lost · outcome unknown" : "outcome unknown"}]
        lappend ops [list tool.close $k unknown "" [dict create label $label error "" \
            inline "" preview {} output "" output_path "" total "" applied "" \
            failed_index "" failed_text "" late 0] ""]
        lappend ops [list run.chip [dict get $tool run] $k warn]
    }
    lappend ops {*}[_close_run S $req $status 0 [expr {[_secs $ts] - [dict get $S runs $req t0]}]]
    return $ops
}

proc ::vmdai::vm::_on_local {sv kind md ts} {
    upvar 1 $sv S
    switch -- $kind {
        local.connection {
            set new [_get $md state]
            set old [dict get $S conn]
            dict set S conn $new
            if {$new eq $old} { return {} }
            switch -- $new {
                reconnecting - down {
                    if {$old in {reconnecting down}} { return {} }
                    return [list [list notice warn \
                        "Connection lost at [_clock_text [_secs $ts]] · your draft is kept"]]
                }
                ready {
                    if {$old ni {reconnecting down}} { return {} }
                    if {[_bool [_get $md request_lost false]]} {
                        set ops [list [list notice warn "Reconnected: request lost" retry]]
                        lappend ops {*}[_lose_request S lost $ts]
                        return $ops
                    }
                    return [list [list notice info "Reconnected"]]
                }
            }
            return {}
        }
        local.request_ended {
            set req [_get $md request_id]
            if {$req eq "" || $req ne [dict get $S request]} { return {} }
            set ops [list [list notice info "Request ended (details may be missing)"]]
            lappend ops {*}[_lose_request S ended $ts]
            return $ops
        }
        local.send_failed {
            set code [_get $md code other]
            if {$code eq "NO_MODEL"} {
                set ops [list [list error.card NO_MODEL "No model configured" \
                    [_get $md message] open_settings]]
            } else {
                set ops [list [list error.card $code "Message not sent" \
                    [_get $md message] [_default_action $code]]]
            }
            if {[dict get $S busy] && [dict get $S request] eq ""} {
                dict set S busy 0
                dict set S phase ""
                dict set S phase_t0 ""
                lappend ops [list status idle]
            }
            return $ops
        }
    }
    return {}
}
```

- [ ] **Step 5: Run the tests (the two new goldens do not exist yet)**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -4`
Expected: `2 failed, 36 passed`; the failures are `test_ops_golden[11_dead_runtime]` and `test_ops_golden[loop_guard]`, both `missing golden …`. The three Task 1 goldens still match: their fixtures hold no error events, local events, late results or not-run rows.

- [ ] **Step 6: Generate the two goldens and review them**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tcl_viewmodel.py -q -k "loop_guard or 11_dead_runtime" 2>&1 | tail -1 && git status --short tests/fixtures/ops`
Expected: `2 passed, 36 deselected`, and `git status` lists only `?? tests/fixtures/ops/11_dead_runtime.ops` and `?? tests/fixtures/ops/loop_guard.ops`.

Run: `tail -8 tests/fixtures/ops/11_dead_runtime.ops | cut -c1-110 && grep -n '^tool.close\|^rule\|^run.close\|Writing a summary' tests/fixtures/ops/loop_guard.ops | cut -c1-110`
Expected:
- `11_dead_runtime.ops` ends with `notice warn "Connection lost at 12:00 AM · your draft is kept"`, `error.card transport "Message not sent" "Runtime not reachable" open_log`, `notice warn "Reconnected: request lost" retry`, `tool.close 000000000001 unknown "" "label {connection lost · outcome unknown} …" ""`, `run.chip r1 000000000001 warn`, `run.close r1 lost 1 0 0 …` and `status idle`. Nothing follows: the fixture's final `local.request_ended` names a request that has already ended.
- `loop_guard.ops`: four `tool.close … err` lines, `status busy "Writing a summary" …`, `rule r1`, and `run.close r1 stuck 4 4 0 …`.

- [ ] **Step 7: Run the tests and the suite**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -1`
Expected: `38 passed`.

Run: `python -m pytest tests/test_tcl_lint.py -q 2>&1 | tail -1 && env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: the lint passes; `B+38 passed`, 0 failed, under 60 s.

- [ ] **Step 8: Commit**

```bash
git add plugin/viewmodel.tcl tests/tcl/test_viewmodel.tcl tests/test_tcl_viewmodel.py \
        tests/fixtures/ops/loop_guard.ops tests/fixtures/ops/11_dead_runtime.ops
git commit -F - <<'MSG'
feat(plugin): view-model tool states, not-run labels, late rows, error cards, local events (P08-T02)

Not-run rows get the C1-C4 labels, first match wins. A late tool.finished
re-closes its row even after request.finished; any other repeat, or an
unknown call_key, is ignored. Error events and NO_MODEL become error cards
with an action. local.connection gives one notice per state change and a
lost request settles its running rows and closes the run.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: P08-T03 — View-model: status texts, run summaries, timeline notes

**Files:**
- Modify: `plugin/viewmodel.tcl` (replace `_on_request_finished`; append new procs)
- Modify: `tests/tcl/test_viewmodel.tcl` (insert a block before the final `cleanupTests`)
- Modify: `tests/test_tcl_viewmodel.py` (three insertions)
- Modify (regenerated in Step 6): `tests/fixtures/ops/loop_guard.ops`

**Interfaces:**
- Consumes: request.started/finished (P07-T02): `request.started {max_turns}`, `request.finished {status, wrapped_up, tool_calls, final_text_empty, duration_ms, error}`
- Produces:
  - `::vmdai::vm::status_text stateVar now -> string`
  - `::vmdai::vm::run_summary status steps failed recovered duration_s max_turns -> string`
  - `::vmdai::vm::stop_requested stateVar -> ops`
  - (also) timeline notes emitted before `footer`/`run.close` when a run ends: `cancelled` → `{notice info Stopped}`; `stuck` → `{notice warn "Stopped: the model kept repeating the same step"}` (C4); `max_turns` → `{notice warn "Stopped after <request.started.max_turns> turns — reply 'continue'"}`; `complete` with `final_text_empty` → `{notice info "Finished after N steps"}` (N from `tool_calls`); a `stuck` or `max_turns` run whose wrap-up failed (`wrapped_up` false, `error` set) first gets `{notice info "The summary could not be written: <first error line>"}`, a muted note, never a card (C4)

Wording (Part B V4 "Step vs turn"): a step is one tool call; the turn limit counts model turns and always prints `request.started.max_turns`. `status_text` is the phase plus ` · MM:SS` since the phase started (`Step 1 · running VMD command · 00:12`); a phase without a start time (`Retrying 2/5 in 8 s`, `Stopping…`) is shown as is; idle is empty.

- [ ] **Step 1: Add the failing tcltests**

In `tests/tcl/test_viewmodel.tcl`, insert this block, followed by one empty line, immediately before the final `cleanupTests` line:

```tcl
# ---- P08-T03 ---------------------------------------------------------------

test status_text_phases {status_text: phase plus a timer; retry text has no timer; idle is empty} -body {
    ::vmdai::vm::init S
    set r [list [::vmdai::vm::status_text S 100]]
    feed S [started req_a]
    lappend r [::vmdai::vm::status_text S 105]
    feed S [tstart req_a k1]
    lappend r [::vmdai::vm::status_text S 112]
    feed S [st status {request_id req_a phase loading_model} 120]
    lappend r [::vmdai::vm::status_text S 141]
    feed S [st status {request_id req_a phase retrying attempt 2 max_attempts 5 wait_s 8}]
    lappend r [::vmdai::vm::status_text S 999]
    lappend r [::vmdai::vm::stop_requested S] [::vmdai::vm::status_text S 999] [::vmdai::vm::stop_requested S]
    feed S [st request.finished {request_id req_a status cancelled tool_calls 1 duration_ms 4000}]
    lappend r [::vmdai::vm::status_text S 1000]
} -result {{} {Thinking · 00:05} {Step 1 · running VMD command · 00:12} {Loading qwen3.8:27b · 00:21} {Retrying 2/5 in 8 s} {{status busy Stopping… {}}} Stopping… {} {}}

test run_summary_strings {run header summaries (Part B V4)} -body {
    list [::vmdai::vm::run_summary complete 5 0 0 16 28] \
         [::vmdai::vm::run_summary complete 1 0 0 3 28] \
         [::vmdai::vm::run_summary complete 5 1 1 16 28] \
         [::vmdai::vm::run_summary complete 5 1 0 16 28] \
         [::vmdai::vm::run_summary error 2 0 0 75 28] \
         [::vmdai::vm::run_summary cancelled 3 0 0 9 28] \
         [::vmdai::vm::run_summary stuck 4 3 0 8 28] \
         [::vmdai::vm::run_summary max_turns 28 0 0 300 28] \
         [::vmdai::vm::run_summary lost 1 0 0 0 28]
} -result {{5 steps · 16 s} {1 step · 3 s} {1 failed, recovered · 16 s} {1 failed · 16 s} {Error · 1 min 15 s} {Stopped · 3 steps} {Stopped (stuck) · 4 steps} {Stopped at 28 turns} {Connection lost · 1 step}}

test finished_after_n_steps {an empty final turn gets "Finished after N steps" from tool_calls} -body {
    ::vmdai::vm::init S
    feed S [started req_a] [tstart req_a k1] [tfin req_a k1]
    only [::vmdai::vm::apply S [st request.finished {request_id req_a status complete wrapped_up false turns 3 tool_calls 4 final_text_empty true duration_ms 5000}]] {notice run.close}
} -result {{notice info {Finished after 4 steps}} {run.close r1 complete 1 0 0 5 1 28}}

test max_turns_uses_request_started {the max-turns note and run.close use request.started.max_turns, never request.finished.turns} -body {
    ::vmdai::vm::init S
    feed S [started req_a {max_turns 12}]
    only [::vmdai::vm::apply S [st request.finished {request_id req_a status max_turns wrapped_up true turns 13 tool_calls 12 final_text_empty false duration_ms 60000}]] {notice run.close}
} -result {{notice warn {Stopped after 12 turns — reply 'continue'}} {run.close r1 max_turns 0 0 0 60 0 12}}

test stuck_notes {stuck: the stop note; a failed wrap-up adds a muted note, never a card} -body {
    ::vmdai::vm::init S
    feed S [started req_a]
    only [::vmdai::vm::apply S [st request.finished {request_id req_a status stuck wrapped_up false turns 5 tool_calls 4 final_text_empty true duration_ms 8000 error {HTTP 500: boom}}]] {notice error.card}
} -result {{notice info {The summary could not be written: HTTP 500: boom}} {notice warn {Stopped: the model kept repeating the same step}}}
```

- [ ] **Step 2: Extend the pytest wrapper**

In `tests/test_tcl_viewmodel.py`:

1. Directly after the `UNIT_TESTS += [ … ]` list that Task 2 added (it ends with the lines `    "request_ended_local",` and `]`), insert:

```python
UNIT_TESTS += [
    "status_text_phases",
    "run_summary_strings",
    "finished_after_n_steps",
    "max_turns_uses_request_started",
    "stuck_notes",
]
```

2. Immediately before the line `def replay_ops(name: str, tmp_path: Path) -> str:`, insert:

```python
def test_status_text_phases(vm_result):
    assert_tcltests(vm_result, ["status_text_phases"])


def test_run_summary_strings(vm_result):
    assert_tcltests(vm_result, ["run_summary_strings"])


def test_finished_after_n_steps(vm_result):
    assert_tcltests(vm_result, ["finished_after_n_steps", "stuck_notes"])


def test_max_turns_uses_request_started(vm_result):
    assert_tcltests(vm_result, ["max_turns_uses_request_started"])


```

3. Immediately before the line `def run_scenario_checks(name: str, ops: List[List[str]]) -> None:`, insert:

```python
@scenario("loop_guard")
def _stuck_note(ops):
    notes = [op[2] for op in ops if op[0] == "notice"]
    assert "Stopped: the model kept repeating the same step" in notes, notes
    note_at = max(i for i, op in enumerate(ops) if op[0] == "notice")
    close_at = max(i for i, op in enumerate(ops) if op[0] == "run.close")
    assert note_at < close_at


```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -10`
Expected: `11 failed, 36 passed`: the five new `test_viewmodel_unit[…]` (`invalid command name "::vmdai::vm::status_text"`, `…run_summary"`, or the missing notes), `test_viewmodel_counts`, the four new named tests, and `test_ops_golden[loop_guard]` (the new scenario check finds no stop note).

- [ ] **Step 4: Implement the notes, the status text and the summaries**

In `plugin/viewmodel.tcl`:

1. Replace the whole proc `::vmdai::vm::_on_request_finished` with:

```tcl
proc ::vmdai::vm::_on_request_finished {sv md ts} {
    upvar 1 $sv S
    set req [_get $md request_id]
    if {$req eq "" || ![dict exists $S runs $req]} { return {} }
    if {[dict get $S runs $req status] ne "running"} { return {} }
    set status [_get $md status complete]
    set ms [_get $md duration_ms ""]
    if {[string is double -strict $ms]} {
        set secs [expr {int(round($ms / 1000.0))}]
    } else {
        set secs [expr {[_secs $ts] - [dict get $S runs $req t0]}]
    }
    set empty [_bool [_get $md final_text_empty false]]
    set calls [_get $md tool_calls [dict get $S runs $req steps]]
    set ops [_finish_notes [dict get $S runs $req] $status $calls $empty \
        [_bool [_get $md wrapped_up false]] [_get $md error]]
    lappend ops {*}[_close_run S $req $status $empty $secs]
    return $ops
}
```

2. Append to the end of the file (after one empty line):

```tcl
proc ::vmdai::vm::_plural {n word} {
    if {$n == 1} { return "1 $word" }
    return "$n ${word}s"
}

proc ::vmdai::vm::_finish_notes {run status tool_calls final_text_empty wrapped_up error} {
    set ops {}
    if {$status in {stuck max_turns} && !$wrapped_up && [_first_line $error] ne ""} {
        lappend ops [list notice info "The summary could not be written: [_first_line $error]"]
    }
    switch -- $status {
        cancelled { lappend ops [list notice info "Stopped"] }
        stuck     { lappend ops [list notice warn "Stopped: the model kept repeating the same step"] }
        max_turns {
            lappend ops [list notice warn "Stopped after [dict get $run max_turns] turns — reply 'continue'"]
        }
        complete {
            if {$final_text_empty} {
                lappend ops [list notice info "Finished after [_plural $tool_calls step]"]
            }
        }
    }
    return $ops
}

# ---- texts for the status bar and run header (P08-T03) ---------------------

proc ::vmdai::vm::_mmss {secs} {
    if {$secs < 0} { set secs 0 }
    return [format "%02d:%02d" [expr {$secs / 60}] [expr {$secs % 60}]]
}

proc ::vmdai::vm::status_text {stateVar now} {
    upvar 1 $stateVar S
    if {![dict get $S busy]} { return "" }
    set t0 [dict get $S phase_t0]
    if {$t0 eq ""} { return [dict get $S phase] }
    return "[dict get $S phase] · [_mmss [expr {[_secs $now] - $t0}]]"
}

proc ::vmdai::vm::_duration_text {secs} {
    if {$secs < 60} { return "$secs s" }
    return [format "%d min %d s" [expr {$secs / 60}] [expr {$secs % 60}]]
}

proc ::vmdai::vm::run_summary {status steps failed recovered duration_s max_turns} {
    set dur [_duration_text $duration_s]
    switch -- $status {
        cancelled { return "Stopped · [_plural $steps step]" }
        stuck     { return "Stopped (stuck) · [_plural $steps step]" }
        max_turns { return "Stopped at $max_turns turns" }
        lost      { return "Connection lost · [_plural $steps step]" }
        ended     { return "Ended · [_plural $steps step]" }
        running   { return "" }
        error {
            if {$failed > 0} { return "$failed failed · $dur" }
            return "Error · $dur"
        }
    }
    if {$failed > 0 && $recovered} { return "$failed failed, recovered · $dur" }
    if {$failed > 0} { return "$failed failed · $dur" }
    return "[_plural $steps step] · $dur"
}

proc ::vmdai::vm::stop_requested {stateVar} {
    upvar 1 $stateVar S
    if {![dict get $S busy] || [dict get $S stopping]} { return {} }
    dict set S stopping 1
    dict set S phase "Stopping…"
    dict set S phase_t0 ""
    return [list [list status busy "Stopping…" ""]]
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -3`
Expected: `1 failed, 46 passed`; the failure is `test_ops_golden[loop_guard]` with `golden mismatch:` and a diff that adds exactly one line, `+notice warn "Stopped: the model kept repeating the same step"`, directly before `run.close r1 stuck …`. The other four goldens still match (their runs end `complete` with a final answer, or never end).

- [ ] **Step 6: Regenerate the loop_guard golden and check the diff**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tcl_viewmodel.py -q -k ops_golden 2>&1 | tail -1 && git diff --stat tests/fixtures/ops && git diff tests/fixtures/ops | grep '^[-+][^-+]'`
Expected: `5 passed, 42 deselected`; only `tests/fixtures/ops/loop_guard.ops` changed (`1 insertion(+)`), and the one added line is `+notice warn "Stopped: the model kept repeating the same step"`.

- [ ] **Step 7: Run the tests and the suite**

Run: `python -m pytest tests/test_tcl_viewmodel.py -q 2>&1 | tail -1`
Expected: `47 passed`.

Run: `python -m pytest tests/test_tcl_lint.py -q 2>&1 | tail -1 && env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: the lint passes; `B+47 passed`, 0 failed, under 60 s.

- [ ] **Step 8: Commit**

```bash
git add plugin/viewmodel.tcl tests/tcl/test_viewmodel.tcl tests/test_tcl_viewmodel.py tests/fixtures/ops/loop_guard.ops
git commit -F - <<'MSG'
feat(plugin): view-model status texts, run summaries and timeline notes (P08-T03)

status_text shows the phase and its timer; run_summary gives the V4 run
header strings; stop_requested switches the status to Stopping. Runs that
end cancelled, stuck, at max turns or with an empty final turn get their
timeline note, and max-turns wording always uses request.started.max_turns.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: P08-T04 — theme.tcl (light): named fonts, tokens, paint registry, styles

**Files:**
- Create: `plugin/theme.tcl`
- Create: `tests/tcl/test_theme.tcl`
- Create: `tests/test_tk_theme.py`

**Interfaces:**
- Consumes: helpers.tk (P06-T10): `run_tk_test(test_file, *, env=None, timeout=120) -> TclTestResult`; `helpers.panel_goldens.assert_tcltests` (Task 1)
- Produces:
  - `::vmdai::theme::init ?mode?; c token; paint w option token; repaint; mode; mono_family`
  - fonts `ChatBody ChatBodyBold ChatRole ChatMeta ChatMetaBold ChatH1 ChatH2 ChatCode ChatCodeSmall ChatHair`
  - (also) font `ChatBodyItal` (UI, base−1, italic: the reasoning line); `paint w opt token ?opt token ...?` takes several pairs; `::vmdai::theme::on_repaint cmd` (hooks run after every repaint, used by the transcript to recolour its tags, and by P10-T01's dark mode); `painted_count`; `mono_family ?families?` (an explicit family list for tests); canvas and text helpers `rrect c x0 y0 x1 y1 r ?options?`, `fit font px text ?min?` (binary-search end ellipsis, never below `min` characters), `fit_middle font px text`
  - tokens (Part B V2 light column) `chrome surface text text2 muted faint hairline accent ok err err_bg warn warn_bg warn_bd warn_fg code_bg icode_bg hover stop_bg stop_fg dot_ok dot_warn dot_off syn_cmd syn_var syn_str syn_num syn_brace syn_opt syn_cmt`, plus `sel field_bd focus_ring` for widgets; `chrome` and `sel` are the aqua system colours on aqua; `init dark` falls back to light until P10-T01

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_theme.tcl`:

```tcl
# theme.tcl (P08-T04): named fonts, tokens, paint registry, ChatVMD.* styles.
# Run by tests/test_tk_theme.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

set before_theme [ttk::style theme use]
set before_styles {}
foreach s {TFrame TLabel TButton TEntry Treeview} {
    lappend before_styles $s [ttk::style configure $s]
}
source [file join $env(VMDAI_PLUGIN_DIR) theme.tcl]
::vmdai::theme::init light

test test_fonts_defined {every named font exists and derives from TkDefaultFont} -body {
    set missing {}
    foreach f {ChatBody ChatBodyBold ChatBodyItal ChatRole ChatMeta ChatMetaBold ChatH1 ChatH2 ChatCode ChatCodeSmall ChatHair} {
        if {[lsearch -exact [font names] $f] < 0} { lappend missing $f }
    }
    set base [font actual TkDefaultFont -size]
    list $missing [expr {[font configure ChatRole -size] == $base - 1}] \
         [expr {[font configure ChatMeta -size] == $base - 2}] \
         [expr {[font configure ChatH1 -size] == $base + 7}] \
         [font configure ChatCode -family] [font configure ChatHair -size]
} -result [list {} 1 1 1 [::vmdai::theme::mono_family] 1]

test test_mono_family_fallback {SF Mono, then Menlo, then DejaVu Sans Mono, else TkFixedFont's family} -body {
    list [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono" Menlo "SF Mono"}] \
         [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono" Menlo}] \
         [::vmdai::theme::mono_family {Foo "DejaVu Sans Mono"}] \
         [expr {[::vmdai::theme::mono_family {Foo}] eq [font actual TkFixedFont -family]}]
} -result {{SF Mono} Menlo {DejaVu Sans Mono} 1}

test test_tokens {light tokens match Part B V2; chrome is the system colour on aqua} -body {
    list [::vmdai::theme::c surface] [::vmdai::theme::c text] [::vmdai::theme::c muted] \
         [::vmdai::theme::c accent] [::vmdai::theme::c err_bg] [::vmdai::theme::c stop_bg] \
         [expr {[tk windowingsystem] eq "aqua" ? [::vmdai::theme::c chrome] eq "systemWindowBackgroundColor" : [::vmdai::theme::c chrome] eq "#ececec"}]
} -result [list #ffffff #1d1d1f #636366 #0a66d8 #fdecec #1d1d1f 1]

test test_repaint_registry {repaint re-applies registered colours, runs hooks and prunes destroyed widgets} -body {
    label .a
    label .b
    ::vmdai::theme::paint .a -foreground text -background surface
    ::vmdai::theme::paint .b -foreground muted
    set ::hooked 0
    ::vmdai::theme::on_repaint {incr ::hooked}
    set n [::vmdai::theme::painted_count]
    set ::vmdai::theme::T(text) #123456
    destroy .b
    ::vmdai::theme::repaint
    set r [list [.a cget -foreground] [.a cget -background] [expr {$n - [::vmdai::theme::painted_count]}] $::hooked]
    destroy .a
    ::vmdai::theme::init light
    set r
} -result [list #123456 #ffffff 1 1]

test test_only_chatvmd_styles {only ChatVMD.* styles are configured; the ttk theme is never switched} -body {
    set after {}
    foreach s {TFrame TLabel TButton TEntry Treeview} { lappend after $s [ttk::style configure $s] }
    list [expr {[ttk::style theme use] eq $before_theme}] [expr {$after eq $before_styles}] \
         [expr {[ttk::style configure ChatVMD.TFrame -background] ne ""}]
} -result {1 1 1}

test fit_helpers {fit keeps at least min characters; fit_middle keeps both ends} -body {
    set long [string repeat x 200]
    set a [::vmdai::theme::fit ChatCodeSmall 30 $long 12]
    set b [::vmdai::theme::fit_middle ChatCodeSmall 120 "a_very_long_snapshot_file_name_for_testing.png"]
    list [string length $a] [string match "*…" $a] [string match "a_*…*.png" $b]
} -result {13 1 1}

cleanupTests
exit
```

(`[list #ffffff …]` is used for results that start with `#`: Tcl quotes such a first element as `{#ffffff}`, so a braced literal would never match.)

Create `tests/test_tk_theme.py`:

```python
"""theme.tcl (P08-T04): named fonts, light tokens, paint registry, ChatVMD.* styles."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_theme.tcl"
TESTS = [
    "test_fonts_defined",
    "test_mono_family_fallback",
    "test_tokens",
    "test_repaint_registry",
    "test_only_chatvmd_styles",
    "fit_helpers",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL))


def test_theme_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_fonts_defined(result):
    assert_tcltests(result, ["test_fonts_defined"])


def test_mono_family_fallback(result):
    assert_tcltests(result, ["test_mono_family_fallback"])


def test_repaint_registry(result):
    assert_tcltests(result, ["test_repaint_registry", "test_tokens"])


def test_only_chatvmd_styles(result):
    assert_tcltests(result, ["test_only_chatvmd_styles"])


def test_fit_helpers(result):
    assert_tcltests(result, ["fit_helpers"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_theme.py -q 2>&1 | tail -2`
Expected: `6 failed`; the tcltest output shows `couldn't read file ".../plugin/theme.tcl": no such file or directory`. (Without a GUI session: `6 skipped`; run from the dev Mac's GUI session.)

- [ ] **Step 3: Write the theme**

Create `plugin/theme.tcl`:

```tcl
# theme.tcl -- ChatVMD colour tokens, named fonts, paint registry, ttk styles.
#
#   ::vmdai::theme::init ?mode?        define fonts, load tokens, configure styles
#   ::vmdai::theme::c token            -> colour
#   ::vmdai::theme::paint w opt token ?opt token ...?   set and remember
#   ::vmdai::theme::on_repaint cmd     run cmd after every repaint
#   ::vmdai::theme::repaint            re-apply every registered colour
#   ::vmdai::theme::mode               -> light (dark lands in M3)
#   ::vmdai::theme::mono_family ?families?
#
# Part B V2. Only ChatVMD.* ttk styles are configured and the ttk theme is
# never switched (that would restyle QwikMD and every other VMD plugin).

namespace eval ::vmdai::theme {
    variable mode
    if {![info exists mode]} { set mode light }
    variable painted
    if {![info exists painted]} { set painted {} }
    variable hooks
    if {![info exists hooks]} { set hooks {} }
    variable T
}

# Light tokens (Part B V2); dark ones land in M3 (P10-T01).
proc ::vmdai::theme::_palettes {} {
    return {
        light {
            chrome    #ececec   surface   #ffffff   text      #1d1d1f
            text2     #3c3c43   muted     #636366   faint     #a1a1a6
            hairline  #d6d6da   accent    #0a66d8   ok        #1a7f37
            err       #c8262e   err_bg    #fdecec   warn      #835700
            warn_bg   #fff5df   warn_bd   #efd59b   warn_fg   #5c4300
            code_bg   #f4f4f6   icode_bg  #ececf0   hover     #f0f0f4
            stop_bg   #1d1d1f   stop_fg   #ffffff   dot_ok    #28c840
            dot_warn  #d88a00   dot_off   #ff5f57   sel       #b3d7ff
            field_bd  #c8c8cd   focus_ring #9ec1f5
            syn_cmd   #0550ae   syn_var   #953800   syn_str   #0a3069
            syn_num   #8250df   syn_brace #835700   syn_opt   #57606a
            syn_cmt   #636c76
        }
    }
}

proc ::vmdai::theme::aqua {} {
    return [expr {[tk windowingsystem] eq "aqua"}]
}

proc ::vmdai::theme::mode {} {
    variable mode
    return $mode
}

proc ::vmdai::theme::c {token} {
    variable T
    return $T($token)
}

proc ::vmdai::theme::mono_family {{families ""}} {
    if {$families eq ""} { set families [font families] }
    foreach pref {"SF Mono" Menlo "DejaVu Sans Mono"} {
        if {[lsearch -exact $families $pref] >= 0} { return $pref }
    }
    return [font actual TkFixedFont -family]
}

proc ::vmdai::theme::_fonts {} {
    set ui [font actual TkDefaultFont -family]
    set base [font actual TkDefaultFont -size]
    if {$base < 0} { set base [expr {-$base * 3 / 4}] }
    if {$base < 8} { set base 13 }
    set mono [mono_family]
    set spec [list \
        ChatBody      [list -family $ui -size $base] \
        ChatBodyBold  [list -family $ui -size $base -weight bold] \
        ChatBodyItal  [list -family $ui -size [expr {$base - 1}] -slant italic] \
        ChatRole      [list -family $ui -size [expr {$base - 1}] -weight bold] \
        ChatMeta      [list -family $ui -size [expr {$base - 2}]] \
        ChatMetaBold  [list -family $ui -size [expr {$base - 2}] -weight bold] \
        ChatH1        [list -family $ui -size [expr {$base + 7}] -weight bold] \
        ChatH2        [list -family $ui -size [expr {$base + 1}] -weight bold] \
        ChatCode      [list -family $mono -size [expr {$base - 1}]] \
        ChatCodeSmall [list -family $mono -size [expr {$base - 2}]] \
        ChatHair      [list -family $ui -size 1]]
    foreach {name opts} $spec {
        if {[lsearch -exact [font names] $name] >= 0} {
            font configure $name {*}$opts
        } else {
            font create $name {*}$opts
        }
    }
}

proc ::vmdai::theme::_styles {} {
    ttk::style configure ChatVMD.TFrame -background [c chrome]
    ttk::style configure ChatVMD.TLabel -background [c chrome] -foreground [c text] -font ChatBody
    ttk::style configure ChatVMD.Meta.TLabel -background [c chrome] -foreground [c muted] -font ChatMeta
    ttk::style configure ChatVMD.Title.TLabel -background [c chrome] -foreground [c text] -font ChatMetaBold
}

proc ::vmdai::theme::init {{m light}} {
    variable mode
    variable T
    set palettes [_palettes]
    if {![dict exists $palettes $m]} { set m light }
    set mode $m
    array unset T
    array set T [dict get $palettes $m]
    if {[aqua]} {
        set T(chrome) systemWindowBackgroundColor
        set T(sel) systemSelectedTextBackgroundColor
    }
    _fonts
    _styles
    repaint
    return $mode
}

proc ::vmdai::theme::_apply {w spec} {
    variable T
    set cfg {}
    foreach {opt tok} $spec { lappend cfg $opt $T($tok) }
    $w configure {*}$cfg
}

proc ::vmdai::theme::paint {w args} {
    variable painted
    lappend painted [list $w $args]
    _apply $w $args
    return $w
}

proc ::vmdai::theme::on_repaint {cmd} {
    variable hooks
    if {[lsearch -exact $hooks $cmd] < 0} { lappend hooks $cmd }
}

proc ::vmdai::theme::repaint {} {
    variable painted
    variable hooks
    set keep {}
    foreach p $painted {
        lassign $p w spec
        if {[winfo exists $w]} {
            _apply $w $spec
            lappend keep $p
        }
    }
    set painted $keep
    foreach cmd $hooks {
        if {[catch {uplevel #0 $cmd} err]} {
            catch {::vmdai::config::log "theme hook failed: $err"}
        }
    }
    _styles
}

proc ::vmdai::theme::painted_count {} {
    variable painted
    return [llength $painted]
}

# Canvas helpers shared by the toolbar, composer, banner and snapshot cards.
proc ::vmdai::theme::rrect {c x0 y0 x1 y1 r args} {
    set pts [list [expr {$x0+$r}] $y0 [expr {$x1-$r}] $y0 $x1 $y0 $x1 [expr {$y0+$r}] \
        $x1 [expr {$y1-$r}] $x1 $y1 [expr {$x1-$r}] $y1 [expr {$x0+$r}] $y1 \
        $x0 $y1 $x0 [expr {$y1-$r}] $x0 [expr {$y0+$r}] $x0 $y0]
    return [$c create polygon $pts -smooth 1 {*}$args]
}

# Truncate text to px with a trailing ellipsis (binary search, V1 fix).
proc ::vmdai::theme::fit {font px text {min 0}} {
    if {[font measure $font $text] <= $px} { return $text }
    set lo $min
    set hi [string length $text]
    while {$lo < $hi} {
        set mid [expr {($lo + $hi + 1) / 2}]
        if {[font measure $font "[string range $text 0 [expr {$mid - 1}]]…"] <= $px} {
            set lo $mid
        } else {
            set hi [expr {$mid - 1}]
        }
    }
    if {$lo < $min} { set lo $min }
    return "[string range $text 0 [expr {$lo - 1}]]…"
}

# Middle ellipsis for file names and chat titles.
proc ::vmdai::theme::fit_middle {font px text} {
    if {[font measure $font $text] <= $px} { return $text }
    set n [string length $text]
    for {set keep [expr {$n - 1}]} {$keep > 2} {incr keep -1} {
        set head [expr {($keep + 1) / 2}]
        set tail [expr {$keep - $head}]
        set s "[string range $text 0 [expr {$head - 1}]]…[string range $text end-[expr {$tail - 1}] end]"
        if {[font measure $font $s] <= $px} { return $s }
    }
    return "…"
}
```

The palette sits in a proc rather than a namespace variable so that re-sourcing picks up edits, and the namespace keeps only `info exists`-guarded state (the lint rule).

- [ ] **Step 4: Run the tests and the suite**

Run: `python -m pytest tests/test_tk_theme.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass (`6 passed` from the theme module plus the lint tests).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+53 passed`, 0 failed, under 60 s.

- [ ] **Step 5: Commit**

```bash
git add plugin/theme.tcl tests/tcl/test_theme.tcl tests/test_tk_theme.py
git commit -F - <<'MSG'
feat(plugin): theme.tcl with light tokens, named fonts and a paint registry (P08-T04)

Named fonts derive from TkDefaultFont and the first available of SF Mono,
Menlo and DejaVu Sans Mono. Every colour is a token; paint remembers which
widget option uses which token so repaint (and its hooks) can recolour
everything. Only ChatVMD.* ttk styles are configured.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: P08-T05 — transcript.tcl core: read-only proxy, blocks, reasoning, autoscroll

**Files:**
- Create: `plugin/transcript.tcl`
- Create: `tests/tcl/plugin_loader.tcl`
- Create: `tests/tcl/test_transcript.tcl`
- Create: `tests/test_tk_transcript.py`
- Modify: `tests/helpers/panel_goldens.py` (two import lines; append the Tk golden helpers)
- Create (generated in Step 7, then committed): `tests/fixtures/tk/03_conversation.txt`, `tests/fixtures/tk/reasoning_answer.txt`

**Interfaces:**
- Consumes: the ops of Tasks 1–3; theme (Task 4): `::vmdai::theme::init`, `c`, `paint`, `on_repaint`, `rrect`, the named fonts; `::vmdai::sched::after ms script`, `after_idle script`, `cancel id` (P06-T02); `helpers.tk.run_tk_test`, `tk_prelude`, `tk_skip_reason`, `golden_path`, `update_goldens` (P06-T10); `helpers.tcl.run_tcl` (P01-T03); the event fixtures (P07-T08)
- Produces:
  - `::vmdai::transcript::create path; apply_ops ops; dump -> string; clear; relayout; jump_to call_key`
  - (also) `create` returns `path.t`, a real `Text` whose command is a proxy: `insert`, `delete` and `replace` are dropped and every other subcommand (`tag`, `mark`, `peer`, `get`, `search`, `index`, `yview`, `see`, `cget`, `configure`) reaches the real widget, renamed to `::vmdai::transcript::_w` (namespace variable `W`, the writable command); the path variables `T` (text) and `F` (frame)
  - (also) `_wl -> {wl:$run}` or `{}`: the work-log tag of the run that `run.open` (Task 6) made current, and empty after that run's `rule` or a user block; Task 6 tags rows with it and plan 09 (P09-T08, its `pre-procs`) tags its reasoning lines with it
  - (also) `opt(animate)` (1; tests set 0: no spinner ticks, no 600 ms flash timer), `on_action` (a command prefix that receives `name ?arg ...?` for every link; empty means the default targets below), `pill_shown -> 0|1`, `toggle_think b`, `menu_items index -> {label command ...}`, and the state array `S` (`S(errors)` counts ops that raised; the golden replay fails on any)
  - (also) extension points that Tasks 6 and 7 fill in, each skipped while missing: `_tags_rows`, `_tags_snaps` (style tags, run on every repaint), `_relayout_rows cw narrow`, `_relayout_snaps cw narrow`, `_clear_rows`, `_clear_snaps`, `_row_menu k`, `_run_menu run`, `_snap_menu k` (right-click on `row:$k`, `hdr:$run`, `snap:$k`), `_collapse run on` (`jump_to` shows a collapsed run through it), and `_do_<name> args` (the default target of action `<name>`)
  - (also) `helpers.panel_goldens`: `GLUE_KINDS`, `REPLAY_TK`, `parse_dump(text) -> (images, [(number, tags, text)])`, `check_no_glue(text)` (S2), `replay_tk(name, tmp_path, geometry="560x780") -> str`
  - (also) `tests/tcl/plugin_loader.tcl`: `load_plugin module ?module ...?`

How the transcript draws (Part B V4 "Transcript blocks", V5 "Scrolling", V6):
- Everything is inserted at `end` and every element ends with its own newline, so prose, reasoning, notes, cards and rows never share a line (S2); `check_no_glue` verifies it on every golden.
- A block is its text plus a trailing newline, all tagged `blk:$b`, so it has a range even while empty. `block.append` inserts before that newline; `block.seal` deletes the streamed text and inserts the canonical text in one `$W insert $at $text $tags` statement (plan 10's anchor S5 replaces exactly that statement with the Markdown renderer); `block.discard` deletes the range. A user block is preceded by a `You⇥time` header (`role`, time in `rolemeta` on a right tab stop).
- Blocks and reasoning inside a run's work log also carry `wl:$run` (the run that Task 6's `run.open` makes current); the rule and the answer after it do not, and a user block ends the run. Task 6 collapses a run by eliding `wl:$run`.
- Reasoning (`think`, `think:$b`, body `thinkbody`/`tb:$b`, elided) reads `Thinking…` while it streams and `Thought for N s ▸` once sealed (N ≥ 1); a click on the line (`toggle_think`) shows the text. Plan 09 routes the live reasoning ops to its own ticking display (P09-T08); the transcript's own rendering is what `apply_ops` callers and the goldens see.
- Notes are centred `note` lines (`notewarn` for warn), an action shown as ` · Retry`. Error cards are `ecard` lines on `err_bg`: `✗ title`, the hint (for `model_not_found`, mono with a `Copy` link), then the action link: Open Settings (Set up a model for `NO_MODEL`), Switch profile, Choose model, Test connection or Open log.
- Links are `link` plus a unique `act:N` tag bound to `<ButtonRelease-1>` → `_action name args`. Without `on_action`, `open_settings`, `switch_profile`, `choose_model` and `test_connection` call `::vmdai::panel::open_settings`, `open_log` calls `::vmdai::panel::open_log`, `copy_text` fills the clipboard and `retry` puts the last prompt back in the composer (`::vmdai::composer::set_text`, never a send); any other name calls `::vmdai::transcript::_do_<name>`. A missing target is skipped.
- Sticky autoscroll: `apply_ops` reads `[lindex [$W yview] 1] >= 0.999` before drawing; at the bottom it runs `see end`, otherwise new output places the `↓ New output` pill (a canvas at the frame's bottom right). Clicking it, or scrolling back to the bottom, hides it.
- `<Configure>` is debounced with `sched::after_idle` and acts only when the width changes (V6). `relayout` sets `-padx` 20 (14 below 440 px), the right tab stops, the 680 px prose measure on wide windows and the rule widths, then calls the row and snapshot hooks.
- `dump`: `images N` (`N` = live photos, Task 7), then per displayed line `NNN <style tags> | <text>`: `NNN` is the text line number, style tags are the tags on the line without a `:` (sorted), tabs print as `⇥`, embedded windows as `<rule>` or `<card>`, and a line whose characters are all elided is skipped.

- [ ] **Step 1: Create the plugin loader for the Tcl/Tk tests**

Create `tests/tcl/plugin_loader.tcl`:

```tcl
# load_plugin module ?module ...?: source plugin/<module>.tcl in order, at
# global level. config and net are sourced under catch: the view tests only
# need executor::split_statements, and those two may need a live VMD or json.
proc load_plugin {args} {
    foreach m $args {
        set path [file join $::env(VMDAI_PLUGIN_DIR) $m.tcl]
        if {$m in {config net}} {
            catch {uplevel #0 [list source $path]}
        } else {
            uplevel #0 [list source $path]
        }
    }
}
```

- [ ] **Step 2: Write the failing tcltests**

Create `tests/tcl/test_transcript.tcl`:

```tcl
# transcript.tcl core (P08-T05): proxy, blocks, reasoning, notes, error
# cards, sticky autoscroll, dump. Run by tests/test_tk_transcript.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . 560x420
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]

proc fresh {} {
    set ::actions {}
    ::vmdai::transcript::clear
    update
}
proc ops {args} { ::vmdai::transcript::apply_ops $args }
proc shown {} { return [$::t get -displaychars 1.0 end] }
proc dumped {} { return [lrange [split [::vmdai::transcript::dump] "\n"] 1 end-1] }
# Run the <ButtonRelease-1> script of the link whose text starts at the last match.
proc click_link {label} {
    set at [$::t search -backwards -exact $label end 1.0]
    foreach tag [$::t tag names $at] {
        if {[string match act:* $tag]} { uplevel #0 [$::t tag bind $tag <ButtonRelease-1>] }
    }
}

test ro-1 {the proxy drops insert/delete/replace, passes tag, mark, peer and get, and takes focus} -body {
    fresh
    ops {block.open b1 user 0 1790208000} {block.append b1 "Load 1HCK"}
    set before [$t get 1.0 end]
    $t insert end INJECTED
    $t delete 1.0 end
    $t replace 1.0 2.0 X
    $t tag add probe 1.0
    $t mark set probe_mark 1.0
    $t peer create $t.__probe
    set r [list [string match .tx.t $t] [winfo class $t] [expr {[$t get 1.0 end] eq $before}] \
        [expr {"probe" in [$t tag names]}] [$t index probe_mark] [winfo class $t.__probe] \
        [$t cget -takefocus] [$t cget -state]]
    destroy $t.__probe
    set r
} -result {1 Text 1 1 1.0 Text 1 normal}

test blocks-seal {a user block shows You and the time; streamed text is sealed in place} -body {
    fresh
    ops {block.open b1 user 0 1790208000} {block.append b1 "load 1hck and show it as a cartoon"} \
        {block.open b2 assistant 1} {block.append b2 "I'll lo"} {block.append b2 "ad it."} \
        {notice info "a note after the block"} \
        {block.seal b2 "I'll load 1hck.\n"}
    dumped
} -result {{001 role rolemeta | You⇥12:00 AM} {002 user | load 1hck and show it as a cartoon} {003 prose | I'll load 1hck.} {004 note | a note after the block}}

test blocks-discard {a discarded block leaves nothing; a later seal of it is ignored} -body {
    fresh
    ops {block.open b1 assistant 1} [list block.append b1 "\{\"name\": \"run_vmd_command\""] \
        {block.discard b1} {block.seal b1 "late"} {rule r1} {block.open b2 assistant 2} {block.seal b2 Done.}
    dumped
} -result {{001 rule | <rule>} {002 prose | Done.}}

test unknown-op {an unknown op, or a bad argument list, is ignored and counted} -body {
    fresh
    ops {frobnicate 1 2} {block.open b1 assistant} {block.open b2 assistant 1} {block.append b2 ok}
    list [dumped] $::vmdai::transcript::S(errors)
} -result {{{001 prose | ok}} 1}

test reasoning-1 {Thinking… while streaming, then "Thought for N s ▸", which expands and collapses} -body {
    fresh
    ops {reasoning.open b1 1} {reasoning.append b1 "The user wants "} {reasoning.append b1 "the atom count."}
    set r [list [dumped]]
    ops {reasoning.seal b1 2.6} {block.open b2 assistant 1} {block.append b2 Answer}
    lappend r [dumped]
    ::vmdai::transcript::toggle_think b1
    lappend r [lrange [dumped] 0 1]
    ::vmdai::transcript::toggle_think b1
    lappend r [lindex [dumped] 0]
} -result {{{001 think | Thinking…}} {{001 think | Thought for 3 s ▸} {003 prose | Answer}} {{001 think | Thought for 3 s ▾} {002 thinkbody | The user wants the atom count.}} {001 think | Thought for 3 s ▸}}

test notice-1 {notes are centred lines; a notice action is a link that runs the action} -body {
    fresh
    ops {notice warn "Reconnected: request lost" retry} {notice info Stopped}
    click_link Retry
    list [dumped] $::actions
} -result {{{001 link note notewarn | Reconnected: request lost · Retry} {002 note | Stopped}} retry}

test error-card-1 {an error card: ✗ title, a copyable hint for model_not_found, the action link} -body {
    fresh
    ops {error.card model_not_found {Model not found: qwen3.8:27b} {ollama pull qwen3.8:27b} choose_model} \
        {error.card NO_MODEL {No model configured} {Set up a model in Settings.} open_settings}
    click_link Copy
    click_link "Choose model"
    click_link "Set up a model"
    list [dumped] $::actions
} -result {{{001 ecard ecard_t ecard_x | ✗ Model not found: qwen3.8:27b} {002 ecard ecard_c link | ollama pull qwen3.8:27b   Copy} {003 ecard ecard_a link | Choose model} {004 ecard ecard_t ecard_x | ✗ No model configured} {005 ecard ecard_h | Set up a model in Settings.} {006 ecard ecard_a link | Set up a model}} {{copy_text {ollama pull qwen3.8:27b}} choose_model open_settings}}

test sticky-autoscroll {scrolled up: no jump and the pill shows; at the bottom: follows, pill hides} -body {
    fresh
    for {set i 1} {$i <= 60} {incr i} {
        ops [list block.open u$i assistant 1] [list block.append u$i "line $i"]
    }
    update
    set r [list [expr {[lindex [$t yview] 1] >= 0.999}] [::vmdai::transcript::pill_shown]]
    $t yview moveto 0
    update
    ops {block.open x1 assistant 1} {block.append x1 "new output"}
    update
    lappend r [lindex [$t yview] 0] [::vmdai::transcript::pill_shown]
    $t yview moveto 1.0
    update
    lappend r [::vmdai::transcript::pill_shown]
    ops {block.open x2 assistant 1} {block.append x2 "more output"}
    update
    lappend r [expr {[lindex [$t yview] 1] >= 0.999}] [::vmdai::transcript::pill_shown]
} -result {1 0 0.0 1 0 1 0}

test non-bmp {emoji and a lone surrogate degrade without error in blocks, seals, notes and the dump} -body {
    fresh
    set emoji "DNA \U0001F9EC ok"
    set lone "x \uD800 y"
    ops [list block.open b1 user 0 1790208000] [list block.append b1 $emoji] \
        [list block.open b2 assistant 1] [list block.append b2 $lone] [list block.seal b2 "$emoji $lone"] \
        [list notice info $emoji] [list error.card other $emoji $lone open_log]
    set d [::vmdai::transcript::dump]
    list $::vmdai::transcript::S(errors) [regexp -all {DNA} $d] [string match "*x * y*" $d]
} -result {0 4 1}

test clear-1 {clear empties the text, drops per-item tags and state, and ids can be reused} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 one} {notice warn w retry}
    ::vmdai::transcript::clear
    set r [list [$t get 1.0 end-1c] [llength [lsearch -all [$t tag names] *:*]]]
    ops {block.open b1 assistant 1} {block.append b1 two}
    lappend r [dumped]
} -result {{} 0 {{001 prose | two}}}

test menu-prose {right-click on prose offers Copy and Select all} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 "some prose"}
    set items [::vmdai::transcript::menu_items 1.2]
    list [lindex $items 0] [lindex $items 2]
} -result {Copy {Select all}}

test wheel-embeds {embedded windows carry the ChatVMDScroll bindtag, so the wheel over them scrolls the transcript (V5)} -body {
    fresh
    for {set i 1} {$i <= 60} {incr i} {
        ops [list block.open u$i assistant 1] [list block.append u$i "line $i"]
    }
    ops {rule r1} {block.open b1 assistant 2} {block.seal b1 Done.}
    update
    set f [lindex $::vmdai::transcript::S(rules) 0]
    set before [lindex [$t yview] 0]
    ::vmdai::transcript::_wheel 120
    update
    list [lindex [bindtags $f] 0] [expr {[bind ChatVMDScroll <MouseWheel>] ne ""}] \
        [expr {[lindex [$t yview] 0] < $before}]
} -result {ChatVMDScroll 1 1}

test relayout-widths {-padx 14 below 440 px, else 20; prose stops at 680 px on a wide window (V2, V6)} -body {
    fresh
    ops {block.open b1 assistant 1} {block.append b1 "some prose"}
    set r {}
    foreach g {380x420 560x420 1000x420} {
        wm geometry . $g
        update
        ::vmdai::transcript::relayout
        set cw [::vmdai::transcript::_content_width]
        set rm [$t tag cget prose -rmargin]
        lappend r [$t cget -padx] [expr {$rm > 0}] [expr {$cw - $rm <= 680}]
    }
    wm geometry . 560x420
    update
    ::vmdai::transcript::relayout
    set r
} -result {14 0 1 20 0 1 20 1 1}

cleanupTests
exit
```

`ops` hands the ops to `apply_ops` in one batch, as the panel does; `click_link` runs the `<ButtonRelease-1>` script of a link, because Tk drops generated events on the withdrawn root. `wheel-embeds` (V5 "Embedded windows") and `relayout-widths` (V2 `-padx 20`/14, V6 "Wide") come last because they scroll and resize the shared root; `relayout-widths` puts it back to 560×420. Both are checked by pytest `test_clear_and_menu`, so the pytest count stays 10.

- [ ] **Step 3: Add the Tk golden helpers and the pytest wrapper**

In `tests/helpers/panel_goldens.py`:

1. Replace the line `from typing import Iterable, List` with:

```python
from typing import Iterable, List, Tuple

import pytest
```

2. Replace the two lines `from helpers.tcl import REPO, TclTestResult` and `from helpers.tk import update_goldens` with:

```python
from helpers.tcl import REPO, TclTestResult, run_tcl
from helpers.tk import tk_prelude, tk_skip_reason, update_goldens
```

3. Append to the end of the file:

```python


# ---- Tk goldens (P08-T05) ------------------------------------------------------
#
# ::vmdai::transcript::dump writes "images N", then one line per displayed
# text line: "NNN <style tags> | <text>", tabs shown as ⇥, per-item tags
# (anything with ":") left out, embedded windows as <card> or <rule>.

# The element kinds a style tag marks. S2: a displayed line holds one kind.
GLUE_KINDS = {
    "header": {"role", "runhdr"},
    "prose": {"prose", "user"},
    "reasoning": {"think", "thinkbody"},
    "row": {"row", "errline", "preview", "detail"},
    "note": {"note", "footer"},
    "card": {"ecard", "thumb"},
    "rule": {"rule"},
}

_DUMP_LINE = re.compile(r"(\d{3,}) ([^|]*)\| (.*)")

REPLAY_TK = r"""
wm withdraw .
source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . $env(CHATVMD_GEOMETRY)
::vmdai::transcript::create .tx
pack .tx -fill both -expand 1
update
::vmdai::vm::init S
set in [open $env(CHATVMD_EVENTS) r]
fconfigure $in -encoding utf-8
while {[gets $in line] >= 0} {
    if {[string trim $line] eq ""} continue
    set line [string map [list @REPO@ $env(VMDAI_REPO)] $line]
    ::vmdai::transcript::apply_ops [::vmdai::vm::apply S [json::json2dict $line]]
}
close $in
update
set out [open $env(CHATVMD_DUMP_OUT) w]
fconfigure $out -encoding utf-8 -translation lf
puts -nonewline $out [::vmdai::transcript::dump]
close $out
if {$::vmdai::transcript::S(errors)} {
    puts stderr "transcript op errors: $::vmdai::transcript::S(last_error)"
    exit 2
}
exit 0
"""


def parse_dump(text: str) -> Tuple[int, List[Tuple[int, List[str], str]]]:
    """(image count, [(line number, style tags, text)]) from a transcript dump."""
    lines = text.splitlines()
    head = re.fullmatch(r"images (\d+)", lines[0])
    assert head, f"bad dump header {lines[0]!r}"
    rows = []
    for line in lines[1:]:
        m = _DUMP_LINE.fullmatch(line)
        assert m, f"bad dump line {line!r}"
        rows.append((int(m.group(1)), m.group(2).split(), m.group(3)))
    return int(head.group(1)), rows


def check_no_glue(text: str) -> None:
    """S2: prose, reasoning, notes, cards and tool rows never share a line."""
    _images, rows = parse_dump(text)
    for number, tags, body in rows:
        kinds = sorted(k for k, names in GLUE_KINDS.items() if names & set(tags))
        assert len(kinds) <= 1, f"line {number} mixes {kinds}: {body!r}"


def replay_tk(name: str, tmp_path: Path, geometry: str = "560x780") -> str:
    """Replay tests/fixtures/events/<name>.jsonl through the view-model into a
    withdrawn transcript and return its dump. Skips without Tk."""
    reason = tk_skip_reason()
    if reason:
        pytest.skip(reason)
    out = tmp_path / f"{name}.dump"
    proc = run_tcl(
        tk_prelude() + REPLAY_TK,
        needs_json=True,
        env={
            "TZ": "UTC",
            "VMDAI_REPO": str(REPO),
            "CHATVMD_EVENTS": str(EVENTS_DIR / f"{name}.jsonl"),
            "CHATVMD_DUMP_OUT": str(out),
            "CHATVMD_GEOMETRY": geometry,
        },
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text(encoding="utf-8")
```

Create `tests/test_tk_transcript.py`:

```python
"""transcript.tcl core (P08-T05): read-only proxy, blocks, reasoning, notes,
error cards, sticky autoscroll, and the S2 Tk goldens."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests, check_no_glue, compare_golden, replay_tk
from helpers.tcl import REPO
from helpers.tk import golden_path, run_tk_test

TCL = REPO / "tests" / "tcl" / "test_transcript.tcl"
TESTS = [
    "ro-1",
    "blocks-seal",
    "blocks-discard",
    "unknown-op",
    "reasoning-1",
    "notice-1",
    "error-card-1",
    "sticky-autoscroll",
    "non-bmp",
    "clear-1",
    "menu-prose",
    "wheel-embeds",
    "relayout-widths",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


def test_transcript_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_ro_1(result):
    assert_tcltests(result, ["ro-1"])


def test_blocks_seal_and_discard(result):
    assert_tcltests(result, ["blocks-seal", "blocks-discard", "unknown-op"])


def test_reasoning(result):
    assert_tcltests(result, ["reasoning-1"])


def test_notes_and_error_cards(result):
    assert_tcltests(result, ["notice-1", "error-card-1"])


def test_sticky_autoscroll(result):
    assert_tcltests(result, ["sticky-autoscroll"])


def test_non_bmp(result):
    assert_tcltests(result, ["non-bmp"])


def test_clear_and_menu(result):
    assert_tcltests(result, ["clear-1", "menu-prose", "wheel-embeds", "relayout-widths"])


def check_golden(name, tmp_path):
    text = replay_tk(name, tmp_path)
    check_no_glue(text)
    compare_golden(text, golden_path(name))


def test_golden_03_conversation(tmp_path):
    check_golden("03_conversation", tmp_path)


def test_golden_reasoning_answer(tmp_path):
    check_golden("reasoning_answer", tmp_path)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_transcript.py -q 2>&1 | tail -2`
Expected: `10 failed`. The tcltest file stops at `load_plugin … transcript` (there is no `plugin/transcript.tcl`), so no case prints `PASSED` and `test_transcript_counts` sees one failure; both golden replays exit non-zero. (Without a GUI session: `10 skipped`; run from the dev Mac's GUI session.)

- [ ] **Step 5: Write the transcript core**

Create `plugin/transcript.tcl`:

```tcl
# transcript.tcl -- ChatVMD transcript: render ops -> one read-only text widget.
#
#   ::vmdai::transcript::create path     -> path.t, the read-only Text (path is
#                                           the frame the caller grids)
#   ::vmdai::transcript::apply_ops ops    draw each op with its op_<name> proc
#   ::vmdai::transcript::dump             -> "images N", then one line per
#                                           displayed text line (Tk goldens)
#   ::vmdai::transcript::clear            empty it and free every photo
#   ::vmdai::transcript::relayout         margins, tab stops, row refit
#   ::vmdai::transcript::jump_to call_key show, scroll to and flash a row
#
# Part B V4 "Transcript blocks", V5 "Scrolling", V6, S2. The real text
# command is renamed to ::vmdai::transcript::_w (the variable W); path.t
# becomes a proxy that drops insert, delete and replace and passes every
# other subcommand (tag, mark, peer, get, search, yview, see, ...). The
# transcript can take focus, select and copy, but no binding can edit it,
# and it is never -state disabled. Every element ends with its own newline,
# so prose, reasoning, notes and tool rows never share a line (S2).

namespace eval ::vmdai::transcript {
    variable W
    if {![info exists W]} { set W "" }
    variable T
    if {![info exists T]} { set T "" }
    variable F
    if {![info exists F]} { set F "" }
    variable opt
    if {![info exists opt]} { array set opt {animate 1} }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable S
    if {![info exists S]} { array set S {} }
    variable B
    if {![info exists B]} { array set B {} }
}

proc ::vmdai::transcript::_reset {} {
    variable S
    variable B
    array unset S
    array set S {cur_run "" answer 0 lastw 0 relayout "" link 0 rules {} photos {}
                 last_user "" flash "" tick "" errors 0 last_error ""}
    array unset B
    array set B {}
}

# ---- widget -------------------------------------------------------------------

proc ::vmdai::transcript::create {path} {
    variable W
    variable T
    variable F
    if {$F ne "" && [winfo exists $F]} { destroy $F }
    if {[winfo exists $path]} { destroy $path }
    catch {rename ::vmdai::transcript::_w {}}
    _reset
    set F $path
    frame $path -borderwidth 0 -highlightthickness 0
    set T $path.t
    text $T -wrap word -borderwidth 0 -highlightthickness 0 -padx 20 -pady 14 \
        -cursor arrow -exportselection 1 -undo 0 -takefocus 1 -insertwidth 0 \
        -width 10 -height 10 -font ChatBody \
        -yscrollcommand [list ::vmdai::transcript::_on_yview]
    ttk::scrollbar $path.sb -orient vertical -command [list $T yview]
    grid $T -row 0 -column 0 -sticky nsew
    grid $path.sb -row 0 -column 1 -sticky ns
    grid columnconfigure $path 0 -weight 1
    grid rowconfigure $path 0 -weight 1
    set W ::vmdai::transcript::_w
    rename ::$T $W
    proc ::$T {args} {
        if {[lindex $args 0] in {insert delete replace}} { return }
        uplevel 1 [list ::vmdai::transcript::_w {*}$args]
    }
    ::vmdai::theme::paint $path -background surface
    ::vmdai::theme::paint $T -background surface -foreground text \
        -selectbackground sel -inactiveselectbackground sel
    canvas $path.pill -highlightthickness 0 -borderwidth 0 -cursor hand2
    bind $path.pill <ButtonRelease-1> ::vmdai::transcript::_pill_clicked
    _tags
    ::vmdai::theme::on_repaint ::vmdai::transcript::_tags
    bind $T <1> {+focus %W}
    bind $T <Configure> [list ::vmdai::transcript::_on_configure %w]
    bind $T <Destroy> [list ::vmdai::transcript::_on_destroy %W]
    foreach seq [_menu_sequences] {
        bind $T $seq [list ::vmdai::transcript::_context %x %y %X %Y]
    }
    bind ChatVMDScroll <MouseWheel> {::vmdai::transcript::_wheel %D}
    return $T
}

proc ::vmdai::transcript::_on_destroy {w} {
    variable T
    variable S
    if {$w ne $T} { return }
    catch {rename ::$w {}}
    foreach key {relayout flash tick} {
        if {[info exists S($key)] && $S($key) ne ""} { ::vmdai::sched::cancel $S($key) }
    }
    if {[info exists S(photos)]} {
        foreach p $S(photos) { catch {image delete $p} }
        set S(photos) {}
    }
}

# Style tags (no ":" in the name) are what the Tk goldens show; per-item
# tags (row:$k, blk:$b, act:N, wl:$run, ...) carry state and bindings.
proc ::vmdai::transcript::_tags {} {
    variable W
    variable F
    if {$W eq "" || [info commands $W] eq ""} { return }
    set C ::vmdai::theme::c
    $W tag configure role -font ChatRole -foreground [$C text] -spacing1 20 -spacing3 4
    $W tag configure rolemeta -font ChatMeta -foreground [$C muted]
    $W tag configure user -font ChatBody -foreground [$C text] -spacing3 8
    $W tag configure prose -font ChatBody -foreground [$C text] -spacing3 8
    $W tag configure think -font ChatBodyItal -foreground [$C muted] -spacing1 4 -spacing3 4
    $W tag configure thinkbody -font ChatMeta -foreground [$C muted] \
        -lmargin1 24 -lmargin2 24 -spacing3 6
    $W tag configure note -font ChatMeta -foreground [$C muted] -justify center \
        -spacing1 12 -spacing3 4
    $W tag configure notewarn -foreground [$C warn]
    $W tag configure ecard -background [$C err_bg] -lmargin1 12 -lmargin2 12 -rmargin 12
    $W tag configure ecard_t -font ChatBodyBold -foreground [$C text] -spacing1 10
    $W tag configure ecard_x -foreground [$C err]
    $W tag configure ecard_h -font ChatMeta -foreground [$C muted] -spacing1 2
    $W tag configure ecard_c -font ChatCodeSmall -foreground [$C text] -spacing1 2
    $W tag configure ecard_a -font ChatMeta -spacing1 6 -spacing3 10
    $W tag configure rule -spacing1 8 -spacing3 8
    $W tag configure flash -background [$C hover]
    $W tag configure link -foreground [$C accent]
    catch {$W tag configure ecard -lmargincolor [$C err_bg] -rmargincolor [$C err_bg]}
    $W tag bind link <Enter> [list $W configure -cursor hand2]
    $W tag bind link <Leave> [list $W configure -cursor arrow]
    foreach extra {_tags_rows _tags_snaps} {
        if {[info commands ::vmdai::transcript::$extra] ne ""} { $extra }
    }
    $W tag raise sel
    _draw_pill
}

# ---- ops ------------------------------------------------------------------------

proc ::vmdai::transcript::apply_ops {ops} {
    variable W
    variable S
    if {$W eq "" || [info commands $W] eq ""} { return }
    set bottom [_at_bottom]
    set before [$W index "end -1c"]
    foreach op $ops {
        set name [lindex $op 0]
        if {[info commands ::vmdai::transcript::op_$name] eq ""} { continue }
        if {[catch {op_$name {*}[lrange $op 1 end]} err]} {
            incr S(errors)
            set S(last_error) "$name: $err"
            catch {::vmdai::config::log "transcript: $name failed: $err"}
        }
    }
    if {$bottom} {
        $W see end
        _pill 0
    } elseif {[$W compare "end -1c" != $before]} {
        _pill 1
    }
}

# Blocks inside a run's work log get wl:$run (collapse, P08-T06); the
# answer after the run's rule does not.
proc ::vmdai::transcript::_wl {} {
    variable S
    if {$S(cur_run) eq "" || $S(answer)} { return {} }
    return [list wl:$S(cur_run)]
}

proc ::vmdai::transcript::_clock {secs} {
    if {![string is wide -strict $secs] || $secs <= 0} { return "" }
    return [string trimleft [clock format $secs -format "%I:%M %p"] 0]
}

proc ::vmdai::transcript::op_block.open {b role turn {time ""}} {
    variable W
    variable B
    variable S
    if {[info exists B($b,tags)]} { return }
    if {$role eq "user"} {
        set S(cur_run) ""
        set S(answer) 0
        set S(last_user) ""
        $W insert end "You" role "\t" role [_clock $time] {role rolemeta} "\n" role
        set B($b,kind) user
        set B($b,tags) [list user blk:$b]
    } else {
        set B($b,kind) text
        set B($b,tags) [concat prose blk:$b [_wl]]
    }
    $W insert end "\n" $B($b,tags)
}

proc ::vmdai::transcript::op_block.append {b text} {
    variable W
    variable B
    variable S
    if {![info exists B($b,tags)]} { return }
    if {$B($b,kind) eq "user"} { append S(last_user) $text }
    set z [lindex [$W tag ranges blk:$b] end]
    $W insert "$z -1c" $text $B($b,tags)
}

# The canonical text replaces what was streamed, in place (§2c Sealing).
proc ::vmdai::transcript::op_block.seal {b canonical} {
    variable W
    variable B
    if {![info exists B($b,tags)]} { return }
    set r [$W tag ranges blk:$b]
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    set text [string trimright $canonical "\n"]
    set tags $B($b,tags)
    $W insert $at $text $tags
    set B($b,sealed) 1
}

proc ::vmdai::transcript::op_block.discard {b} {
    variable W
    variable B
    if {![info exists B($b,tags)]} { return }
    set r [$W tag ranges blk:$b]
    if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    array unset B $b,*
}

# Reasoning: one muted italic line, "Thinking…" while it streams and
# "Thought for N s ▸" once sealed; a click shows the text underneath.
proc ::vmdai::transcript::op_reasoning.open {b turn} {
    variable W
    variable B
    if {[info exists B($b,tags)]} { return }
    set wl [_wl]
    set B($b,kind) reasoning
    set B($b,tags) [concat think think:$b $wl]
    set B($b,body) [concat thinkbody tb:$b $wl]
    set B($b,sealed) 0
    set B($b,open) 0
    $W insert end "Thinking…" $B($b,tags) "\n" $B($b,tags) "\n" $B($b,body)
    $W tag configure tb:$b -elide 1
    $W tag bind think:$b <ButtonRelease-1> [list ::vmdai::transcript::toggle_think $b]
}

proc ::vmdai::transcript::op_reasoning.append {b text} {
    variable W
    variable B
    if {![info exists B($b,body)]} { return }
    set z [lindex [$W tag ranges tb:$b] end]
    $W insert "$z -1c" $text $B($b,body)
}

proc ::vmdai::transcript::op_reasoning.seal {b duration_s} {
    variable B
    if {![info exists B($b,body)]} { return }
    set secs 1
    if {[string is double -strict $duration_s] && $duration_s >= 1} {
        set secs [expr {int(round($duration_s))}]
    }
    set B($b,secs) $secs
    set B($b,sealed) 1
    _think_head $b
}

proc ::vmdai::transcript::_think_head {b} {
    variable W
    variable B
    set label "Thought for $B($b,secs) s [expr {$B($b,open) ? "▾" : "▸"}]"
    set r [$W tag ranges think:$b]
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    $W insert $at $label $B($b,tags)
}

proc ::vmdai::transcript::toggle_think {b} {
    variable W
    variable B
    if {![info exists B($b,sealed)] || !$B($b,sealed)} { return }
    set B($b,open) [expr {!$B($b,open)}]
    $W tag configure tb:$b -elide [expr {!$B($b,open)}]
    _think_head $b
}

# Timeline notes: centred, muted, one line each (Part B V4).
proc ::vmdai::transcript::op_notice {level text {action ""}} {
    variable W
    set tags [list note]
    if {$level eq "warn"} { lappend tags notewarn }
    $W insert end $text $tags
    if {$action ne ""} {
        $W insert end " · " $tags [_action_label $action ""] [concat $tags link [_link $action]]
    }
    $W insert end "\n" $tags
}

# One card per error: ✗ and the title, the hint (a copyable command for
# model_not_found), then the action link (Part B V4 "Error cards").
proc ::vmdai::transcript::op_error.card {code title hint action} {
    variable W
    set t [list ecard ecard_t]
    $W insert end "✗ " [concat $t ecard_x] $title $t "\n" $t
    if {$hint ne ""} {
        if {$code eq "model_not_found"} {
            set h [list ecard ecard_c]
            $W insert end $hint $h "   " $h "Copy" [concat $h link [_link copy_text $hint]] "\n" $h
        } else {
            $W insert end $hint {ecard ecard_h} "\n" {ecard ecard_h}
        }
    }
    set a [list ecard ecard_a]
    $W insert end [_action_label $action $code] [concat $a link [_link $action]] "\n" $a
}

# The hairline before a run's final answer; what follows is the answer.
proc ::vmdai::transcript::op_rule {run} {
    variable W
    variable T
    variable S
    set S(cur_run) $run
    set S(answer) 1
    set f $T.rule[llength $S(rules)]
    frame $f -height 1 -width [_content_width] -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $f -background hairline
    lappend S(rules) $f
    set at [$W index "end -1c"]
    $W window create $at -window [_embed $f] -align center
    $W insert end "\n" rule
    $W tag add rule $at
}

# ---- links and actions ------------------------------------------------------------

proc ::vmdai::transcript::_link {args} {
    variable W
    variable S
    set tag act:[incr S(link)]
    $W tag bind $tag <ButtonRelease-1> [list ::vmdai::transcript::_action {*}$args]
    return $tag
}

proc ::vmdai::transcript::_action_label {action code} {
    switch -- $action {
        open_settings   { return [expr {$code eq "NO_MODEL" ? "Set up a model" : "Open Settings"}] }
        switch_profile  { return "Switch profile" }
        choose_model    { return "Choose model" }
        test_connection { return "Test connection" }
        open_log        { return "Open log" }
        retry           { return "Retry" }
    }
    return [string totitle [string map {_ " "} $action]]
}

# Run an action: the on_action callback when set (tests), else the target.
# A target that does not exist (yet) is skipped, never an error.
proc ::vmdai::transcript::_action {name args} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name {*}$args]]
    }
    switch -- $name {
        open_settings - switch_profile - choose_model - test_connection {
            _call ::vmdai::panel::open_settings
        }
        open_log  { _call ::vmdai::panel::open_log }
        copy_text { _clipboard [lindex $args 0] }
        default   { _call ::vmdai::transcript::_do_$name {*}$args }
    }
}

proc ::vmdai::transcript::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::transcript::_clipboard {text} {
    clipboard clear
    clipboard append -- $text
}

# "Reconnected: request lost · Retry" puts the last prompt back in the
# composer; it never sends by itself.
proc ::vmdai::transcript::_do_retry {} {
    variable S
    _call ::vmdai::composer::set_text $S(last_user)
    _call ::vmdai::composer::focus
}

# ---- scrolling: sticky autoscroll and the "↓ New output" pill (V5) --------------

proc ::vmdai::transcript::_at_bottom {} {
    variable W
    return [expr {[lindex [$W yview] 1] >= 0.999}]
}

proc ::vmdai::transcript::_on_yview {first last} {
    variable F
    if {[winfo exists $F.sb]} { $F.sb set $first $last }
    if {$last >= 0.999} { _pill 0 }
}

proc ::vmdai::transcript::_draw_pill {} {
    variable F
    if {![winfo exists $F.pill]} { return }
    set c $F.pill
    $c delete all
    set text "↓ New output"
    set w [expr {[font measure ChatMetaBold $text] + 24}]
    set h [expr {[font metrics ChatMetaBold -linespace] + 10}]
    $c configure -width $w -height $h -background [::vmdai::theme::c surface]
    ::vmdai::theme::rrect $c 0 0 $w $h [expr {$h / 2}] -fill [::vmdai::theme::c accent] -outline ""
    $c create text [expr {$w / 2}] [expr {$h / 2}] -text $text -font ChatMetaBold \
        -fill [::vmdai::theme::c surface]
}

proc ::vmdai::transcript::_pill {on} {
    variable F
    if {![winfo exists $F.pill]} { return }
    if {$on} {
        place $F.pill -in $F -relx 1.0 -rely 1.0 -anchor se -x -28 -y -12
        raise $F.pill
    } else {
        place forget $F.pill
    }
}

proc ::vmdai::transcript::pill_shown {} {
    variable F
    return [expr {[winfo exists $F.pill] && [winfo manager $F.pill] eq "place"}]
}

proc ::vmdai::transcript::_pill_clicked {} {
    variable W
    $W yview moveto 1.0
    _pill 0
}

# Embedded windows get the ChatVMDScroll bindtag, so the wheel keeps
# scrolling the transcript over a card (V5, cards' CVScroll).
proc ::vmdai::transcript::_embed {w} {
    bindtags $w [concat ChatVMDScroll [bindtags $w]]
    return $w
}

proc ::vmdai::transcript::_wheel {delta} {
    variable W
    if {$W eq "" || [info commands $W] eq ""} { return }
    if {[tk windowingsystem] eq "aqua"} {
        $W yview scroll [expr {-$delta}] units
    } else {
        $W yview scroll [expr {-$delta / 120}] units
    }
}

# ---- layout (V6) ------------------------------------------------------------------

proc ::vmdai::transcript::_content_width {} {
    variable T
    set w [winfo width $T]
    if {$w < 100} { return 480 }
    return [expr {$w - 2 * [$T cget -padx] - 2}]
}

proc ::vmdai::transcript::_on_configure {width} {
    variable S
    if {$width == $S(lastw)} { return }
    set S(lastw) $width
    if {$S(relayout) ne ""} { ::vmdai::sched::cancel $S(relayout) }
    set S(relayout) [::vmdai::sched::after_idle ::vmdai::transcript::relayout]
}

proc ::vmdai::transcript::relayout {} {
    variable W
    variable T
    variable S
    set S(relayout) ""
    if {$W eq "" || ![winfo exists $T]} { return }
    set narrow [expr {[winfo width $T] > 1 && [winfo width $T] < 440}]
    $T configure -padx [expr {$narrow ? 14 : 20}]
    set cw [_content_width]
    $W tag configure role -tabs [list $cw right]
    set rm [expr {$cw > 680 ? $cw - 680 : 0}]
    foreach tag {prose user} { $W tag configure $tag -rmargin $rm }
    foreach f $S(rules) {
        if {[winfo exists $f]} { $f configure -width $cw }
    }
    foreach hook {_relayout_rows _relayout_snaps} {
        if {[info commands ::vmdai::transcript::$hook] ne ""} { $hook $cw $narrow }
    }
}

# ---- navigation ---------------------------------------------------------------------

# Show the row's run if it is collapsed, scroll to the row, flash it 600 ms.
proc ::vmdai::transcript::jump_to {k} {
    variable W
    set r [$W tag ranges row:$k]
    if {![llength $r]} { return 0 }
    foreach tag [$W tag names [lindex $r 0]] {
        if {[string match wl:* $tag]} { _show_run [string range $tag 3 end] }
    }
    $W see [lindex $r 0]
    _flash $r
    return 1
}

proc ::vmdai::transcript::_show_run {run} {
    variable W
    if {[info commands ::vmdai::transcript::_collapse] ne ""} {
        _collapse $run 0
    } else {
        $W tag configure wl:$run -elide 0
    }
}

proc ::vmdai::transcript::_flash {range} {
    variable W
    variable S
    variable opt
    if {$S(flash) ne ""} { ::vmdai::sched::cancel $S(flash) }
    $W tag remove flash 1.0 end
    $W tag add flash {*}$range
    set S(flash) ""
    if {$opt(animate)} {
        set S(flash) [::vmdai::sched::after 600 [list ::vmdai::transcript::_unflash]]
    }
}

proc ::vmdai::transcript::_unflash {} {
    variable W
    variable S
    set S(flash) ""
    if {$W ne "" && [info commands $W] ne ""} { $W tag remove flash 1.0 end }
}

# ---- context menus (V5) ----------------------------------------------------------

proc ::vmdai::transcript::_menu_sequences {} {
    if {[tk windowingsystem] eq "aqua"} { return {<Button-2> <Control-Button-1>} }
    return {<Button-3>}
}

# menu_items index -> {label command ...}: the item under index picks the
# menu (rows, run headers and snapshots add theirs in P08-T06/T07).
proc ::vmdai::transcript::menu_items {index} {
    variable W
    foreach tag [$W tag names $index] {
        foreach {pattern provider} {row:* _row_menu hdr:* _run_menu snap:* _snap_menu} {
            if {[string match $pattern $tag]
                    && [info commands ::vmdai::transcript::$provider] ne ""} {
                return [$provider [string range $tag [string first : $tag]+1 end]]
            }
        }
    }
    return [list Copy ::vmdai::transcript::_copy_selection \
                 "Select all" [list $W tag add sel 1.0 end]]
}

proc ::vmdai::transcript::_copy_selection {} {
    variable W
    if {[catch {$W get -displaychars sel.first sel.last} s]} { return }
    _clipboard [string map [list "\t" "  "] $s]
}

proc ::vmdai::transcript::_context {x y rx ry} {
    variable T
    set m $T.menu
    catch {destroy $m}
    menu $m -tearoff 0
    foreach {label cmd} [menu_items [$T index @$x,$y]] {
        $m add command -label $label -command $cmd
    }
    tk_popup $m $rx $ry
}

# ---- clear and dump ---------------------------------------------------------------

proc ::vmdai::transcript::clear {} {
    variable W
    variable T
    variable S
    if {$W eq "" || [info commands $W] eq ""} { return }
    foreach hook {_clear_rows _clear_snaps} {
        if {[info commands ::vmdai::transcript::$hook] ne ""} { $hook }
    }
    if {$S(flash) ne ""} { ::vmdai::sched::cancel $S(flash) }
    $W delete 1.0 end
    foreach tag [$W tag names] {
        if {[string first : $tag] >= 0} { $W tag delete $tag }
    }
    foreach mark [$W mark names] {
        if {$mark ni {insert current}} { $W mark unset $mark }
    }
    foreach f $S(rules) { catch {destroy $f} }
    foreach p $S(photos) { catch {image delete $p} }
    set lastw $S(lastw)
    set pending $S(relayout)
    _reset
    set S(lastw) $lastw
    set S(relayout) $pending
    _pill 0
}

# Is the character at index hidden? The highest-priority tag that sets
# -elide decides (count -displaychars does not see embedded windows).
proc ::vmdai::transcript::_elided {index} {
    variable W
    set hidden 0
    foreach tag [$W tag names $index] {
        set e [$W tag cget $tag -elide]
        if {$e ne ""} { set hidden [expr {$e ? 1 : 0}] }
    }
    return $hidden
}

proc ::vmdai::transcript::dump {} {
    variable W
    variable S
    set lines [list "images [llength $S(photos)]"]
    set last [$W index "end -1c"]
    set n [lindex [split $last .] 0]
    for {set i 1} {$i <= $n} {incr i} {
        if {[$W compare $i.0 == $last]} { break }
        if {[$W count -displaychars $i.0 "$i.0 +1 lines"] == 0} { continue }
        set text ""
        foreach {key value index} [$W dump -text -window $i.0 "$i.0 lineend"] {
            if {$key eq "text"} {
                append text [$W get -displaychars $index "$index + [string length $value] chars"]
            } elseif {![_elided $index]} {
                append text [expr {$value in $S(rules) ? "<rule>" : "<card>"}]
            }
        }
        set tags [$W tag names $i.0]
        foreach tag [$W tag names] {
            if {[llength [$W tag nextrange $tag "$i.0 +1c" "$i.0 +1 lines"]]} { lappend tags $tag }
        }
        set style {}
        foreach tag [lsort -unique $tags] {
            if {$tag ne "sel" && [string first : $tag] < 0} { lappend style $tag }
        }
        lappend lines [format "%03d %s | %s" $i [join $style] [string map [list "\t" "⇥"] $text]]
    }
    return "[join $lines \n]\n"
}
```

- [ ] **Step 6: Run the tests (the goldens do not exist yet)**

Run: `python -m pytest tests/test_tk_transcript.py -q 2>&1 | tail -3`
Expected: `2 failed, 8 passed`; the failures are `test_golden_03_conversation` and `test_golden_reasoning_answer`, each `AssertionError: missing golden …/tests/fixtures/tk/<name>.txt; run with CHATVMD_UPDATE_GOLDENS=1`. `check_no_glue` ran first and passed.

- [ ] **Step 7: Generate the Tk goldens and review them**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py -q -k golden 2>&1 | tail -1 && cat tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt`
Expected: `2 passed, 8 deselected`, then the text below (plan 07's scenario texts fix the prose; the model name, the `Thought for N s` values and the times come from the recorded fixture's `request.started.model`, timestamps and `duration_ms`, so a fixture recorded differently may change only those values; tool rows, run headers and the snapshot card are not drawn until Tasks 6 and 7):

```text
images 0
001 role rolemeta | You⇥12:00 AM
002 user | load 1hck and show it as a cartoon
003 prose | I'll load 1hck and show it as a cartoon.
004 prose | `display backgroundcolor` does not exist; the color command alone is enough.
005 rule | <rule>
006 prose | Loaded **1hck** as a cartoon on a white background.
007 role rolemeta | You⇥12:00 AM
008 user | what is its radius of gyration?
009 rule | <rule>
010 prose | The radius of gyration is 20.84 Å.
images 0
001 role rolemeta | You⇥12:00 AM
002 user | how many atoms does 1hck have?
003 think | Thought for 1 s ▸
005 think | Thought for 1 s ▸
007 rule | <rule>
008 prose | 1hck has 2442 atoms.
```

Check by eye: each prose line appears once (the streamed text was sealed in place, not appended again), the empty turns (the rescued tool calls) left no blank prose line, both answers sit directly under a `<rule>`, and the reasoning lines read `Thought for N s ▸` with the text hidden. N comes from the fixture's timestamps (1 s for plan 07's two-chunk turns).

- [ ] **Step 8: Run the tests, the lint and the suite**

Run: `python -m pytest tests/test_tk_transcript.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass (`10 passed` from the transcript module plus the lint tests, which now scan `plugin/transcript.tcl`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+63 passed`, 0 failed, under 60 s.

- [ ] **Step 9: Commit**

```bash
git add plugin/transcript.tcl tests/tcl/plugin_loader.tcl tests/tcl/test_transcript.tcl \
        tests/test_tk_transcript.py tests/helpers/panel_goldens.py \
        tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt
git commit -F - <<'MSG'
feat(plugin): transcript core with a read-only proxy, blocks, reasoning and sticky autoscroll (P08-T05)

One tk text, made read-only by renaming its widget command and proxying
everything but insert/delete/replace, so it still takes focus and copies.
apply_ops draws each view-model op with its op_<name> proc: blocks stream
and are sealed in place, reasoning becomes "Thought for N s", notes and
error cards get their action links, and new output only scrolls the view
when it was already at the bottom (otherwise a "New output" pill shows).
Tk goldens replay the 03_conversation and reasoning_answer fixtures and
check that no line mixes prose, reasoning, notes, cards or rows (S2).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 6: P08-T06 — Tool rows, step detail, chips, collapse, run header/footer

**Files:**
- Modify: `plugin/transcript.tcl` (append the rows section)
- Create: `tests/tcl/test_tool_rows.tcl`
- Create: `tests/test_tk_tool_rows.py`
- Modify (regenerated in Step 6): `tests/fixtures/tk/03_conversation.txt`, `tests/fixtures/tk/reasoning_answer.txt`

**Interfaces:**
- Consumes: `::vmdai::executor::split_statements script -> dict {statements tail}` (P06-T08); `::vmdai::vm::run_summary` (Task 3); the `tool.open`, `tool.close`, `run.open`, `run.chip`, `run.close` and `footer` ops (Tasks 1–3); Task 5's `_wl`, `_link`, `_action`, `_clipboard`, `_content_width`, `jump_to` and the extension points
- Produces:
  - row tags `row:$k glyph:$k detail:$k`; the left-gravity mark `rowend:$k` (see the note below)
  - `::vmdai::transcript::toggle_detail call_key -> 0|1; set_expand_all bool`
  - (also) `op_run.open run request_id model t0`, `op_run.chip run k state`, `op_run.close run status steps failed recovered duration_s final_text_empty ?max_turns?`, `op_footer run applied usage_text`, `op_tool.open k name command executor origin ?rationale?`, `op_tool.close k state duration_text detail thumb`; tags `hdr:$run`, `chip:$k`, `err:$k`, `prev:$k`, `wl:$run`; the arrays `RUN` and `ROW` (`ROW($k,run)`, `ROW($k,cmd)`, `ROW($k,state)`, …) and `run_order`; `_row_menu k`, `_run_menu run`, `_collapse run on`, `_do_copy_run_tcl request_id`, `_do_save_run_tcl request_id` (they call `::vmdai::tclexport::run_tcl` and `save`, P08-T11, when loaded), `_do_show_all k`; the namespace variable `expand_all` (0 or 1, the "Expand all steps" flag that `set_expand_all` sets; Task 10's toolbar copies it into its check item); `_row_press x y` and `_row_release k x y` (the row click bindings)
  - (also) the step detail is built by one proc, `_build_detail k`, which inserts every command line itself at the mark `dins:$k` (plan 10's anchor S4)

**The mark name.** The skeleton and Part B V4 call the row mark `$k.rowend`. Tk parses a mark name that starts with a digit as a `line.char` index, and call keys are 12 hex characters (`uuid4().hex[:12]`), so `77c0d2e9ab15.rowend -1c` fails with `bad text index` for most keys (verified while planning, and the fixtures' keys `000000000001` hit it on every row). The mark is therefore `rowend:$k`, with the same position and gravity; nothing outside `transcript.tcl` uses it. `status-1` keys a row `77c0d2e9ab15` to pin this.

How rows and runs are drawn (Part B V4 "Tool rows", "Step detail", "Run header", "Collapse"; V6):
- A row is one display line: the glyph (• running, ✓, ✗, – not run, ! unknown; animated ◐◓◑◒ when `opt(animate)`), a tab to 24 px, the command (`cmd`, ChatCodeSmall, text2; `Snapshot`, `Docs: …` and `Wiki: …` rows use `snapcmd`, ChatBody), muted extras (`+N lines`, the rationale or snapshot purpose, `(from text)` for rescued calls), a right tab, then the result or label, the duration and `▸`/`▾` (`meta`, `chev`, both muted). The row shows the failing statement for a failure (C3), `… <last statement>` next to an inline result, and otherwise the first line.
- `_row_fit` applies the V6 refit order against the content width: drop the rationale, drop `+N lines`, ellipsize the command with `theme::fit … 12` (never below 12 characters), drop the duration, and as a last resort ellipsize the label. `_render_row` redraws only when that fit changed, so `relayout` refits only rows whose fit changed.
- Under the row, in order: the error line (`errline`, `err:$k`) or the output preview (`preview`, `prev:$k`), the step detail (`detail`, `detail:$k`) and the snapshot card (Task 7). A multi-statement failure opens its detail at once; a late `tool.close` deletes and redraws the row's sections in place.
- The detail: the rationale (`dnote`), the exact command lines, each after a two-character gutter (`dgut`; `✗ ` in `dgutx` on the first line of the failing statement), the command text itself tagged `dcode` and, for a failure, `dfail` (`err_bg`) on the failing statement and `dmuted` on the statements after it, split with `executor::split_statements` (`_cmd_segments` locates each statement in the command, so the highlight covers exactly the bytes that ran); 10 lines then `Show all N lines` (a failure shows every line); the output (`→ `, 12 lines, then `… N more lines`); `Open full output · Reveal` when `output_path` is set (C5, actions `open_file`/`reveal_file`, Task 7's viewer); for a failure the export note ("Statements 1–2 ran and are kept in Save .tcl; the rest is commented out", or "Not in Save .tcl"); and `Copy`.
- The run header (`runhdr`, `hdr:$run`) reads `ChatVMD  <model>⇥<chips>  <summary>`: one chip per step (`chip`, `chip_<state>`, `chip:$k`, click → `jump_to`), counts (`✓14 ✗2`) past 12 steps; the summary is `vm::run_summary` once `run.close` arrives. When it does not fit: drop the model, shorten `N failed, recovered` to `N failed`, switch to counts.
- Collapse: `run.open` collapses every earlier run that ended `complete`, `cancelled` or `max_turns` without an unrecovered failure, by eliding `wl:$run`. Rows, previews, details, reasoning and work-log prose carry `wl:$run`; a failed row, its error line and its detail do not, nor do the header, the rule, the answer, notes and the footer. `set_expand_all 1` shows every run and opens every detail; `set_expand_all 0` closes every detail and collapses every eligible run except the newest.
- The footer (`footer`, right-aligned): `Copy Tcl · Save .tcl…` (actions `copy_run_tcl`/`save_run_tcl` with the run's request id), only when `applied ≥ 1`. The usage text is not printed in M2 (plan 10 adds it).

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_tool_rows.tcl`:

```tcl
# Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).
# Adopted from native's proto_test (glue-1, status-1, err-1, out-1, expand-1,
# fit-1) and cards' test_proto (group-1..3). Run by tests/test_tk_tool_rows.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
wm geometry . 560x780
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]

# Events, as in test_viewmodel.tcl, fed through the real view-model.
proc st {kind md {ts 1790208000}} {
    return [dict create seq 0 ts $ts role system type state text "" \
        metadata [dict merge [dict create kind $kind] $md]]
}
proc started {req {extra {}}} {
    return [st request.started [dict merge [dict create request_id $req model qwen3.8:27b \
        max_turns 28 vision true] $extra]]
}
proc tstart {req k cmd {why ""} {name run_vmd_command}} {
    set input [dict create command $cmd rationale $why]
    if {$name eq "capture_vmd_snapshot"} { set input [dict create purpose $why] }
    return [st tool.started [dict create request_id $req turn 1 call_key $k tool_name $name \
        executor tcl origin model input $input]]
}
proc tfin {req k {extra {}}} {
    return [st tool.finished [dict merge [dict create request_id $req call_key $k \
        tool_name run_vmd_command ok true executed yes output "" error "" duration_ms 412 \
        statements null blocked null output_path null image null saved_path null late false] $extra]]
}
proc finished {req status {extra {}}} {
    return [st request.finished [dict merge [dict create request_id $req status $status \
        wrapped_up false tool_calls 1 final_text_empty false duration_ms 16000] $extra] 1790208016]
}
proc feed {args} {
    foreach e $args { ::vmdai::transcript::apply_ops [::vmdai::vm::apply ::S $e] }
}
proc fresh {} {
    set ::actions {}
    ::vmdai::transcript::clear
    ::vmdai::transcript::set_expand_all 0
    ::vmdai::vm::init ::S
    wm geometry . 560x780
    update
    ::vmdai::transcript::relayout
}
proc rowtext {k} { return [$::t get "rowend:$k -1l linestart" "rowend:$k -1c"] }
proc glyph {k} { return [$::t get [lindex [$::t tag ranges glyph:$k] 0]] }
proc tagtext {tag} {
    set out {}
    foreach {a b} [$::t tag ranges $tag] { lappend out [$::t get $a $b] }
    return $out
}
proc shown {a b} { return [$::t count -displaychars $a $b] }
proc click_link {label} {
    set at [$::t search -backwards -exact $label end 1.0]
    foreach tag [$::t tag names $at] {
        if {[string match act:* $tag]} { uplevel #0 [$::t tag bind $tag <ButtonRelease-1>] }
    }
}

set CMD1 "mol new 1hck.pdb\nmol delrep 0 top\nmol representation NewCartoon\nmol addrep top"
set CMD2 "color Display Background white\ndisplay backgroundcolor white"
set CMD4 "set sel \[atomselect top protein\]\nmeasure rgyr \$sel"
set FAIL2 [dict create index 2 text "display backgroundcolor white" error_info x]

# The five-step run of native's demo: load, a failing line, the fix, a
# measurement with an inline result, a restyle; then the answer.
proc five_steps {} {
    feed [started req_1] \
        [tstart req_1 k1 $::CMD1 "Load the structure and draw it as a cartoon."] \
        [tfin req_1 k1 {statements {total 4 applied 4 failed null}}] \
        [tstart req_1 k2 $::CMD2 "Make the background white."] \
        [tfin req_1 k2 [dict create ok false error "display: invalid option \"backgroundcolor\"" \
            duration_ms 38 statements [dict create total 2 applied 1 failed $::FAIL2]]] \
        [tstart req_1 k3 "color Display Background white" "Set the background."] \
        [tfin req_1 k3 {duration_ms 12}] \
        [tstart req_1 k4 $::CMD4 "Radius of gyration."] \
        [tfin req_1 k4 {output 20.8431 duration_ms 25}] \
        [tstart req_1 k5 "mol modstyle 0 top NewCartoon 0.3 30 4.1" "Thicker cartoon."] \
        [tfin req_1 k5] \
        [dict create seq 0 ts 1790208015 role assistant type message text "Done." \
            metadata {request_id req_1 turn 6 final true}] \
        [finished req_1 complete {tool_calls 5}]
}

test glue-1 {every tool row starts on its own line} -body {
    fresh
    five_steps
    set bad 0
    foreach k {k1 k2 k3 k4 k5} {
        set a [lindex [$t tag ranges row:$k] 0]
        if {[$t compare $a != "$a linestart"]} { incr bad }
    }
    set bad
} -result 0

test status-1 {glyphs follow the tool state; running and not-run rows; a hex call key that starts with a digit} -body {
    fresh
    five_steps
    set r {}
    foreach k {k1 k2 k3 k4 k5} { lappend r [glyph $k] }
    feed [started req_2] [tstart req_2 77c0d2e9ab15 "mol new x.pdb"]
    lappend r [glyph 77c0d2e9ab15] [string match "*running…*" [rowtext 77c0d2e9ab15]]
    feed [tfin req_2 77c0d2e9ab15 {ok false executed no error {Not run: exec is never run by ChatVMD.} \
        blocked {{id cmd_exec word exec text {exec ls}}}}]
    lappend r [glyph 77c0d2e9ab15] [string match "*not run · blocked: exec*" [rowtext 77c0d2e9ab15]]
} -result {✓ ✗ ✓ ✓ ✓ • 1 – 1}

test err-1 {a failed call shows its error right under the row, and its failing statement in the row} -body {
    fresh
    five_steps
    list [string trim [$t get rowend:k2 "rowend:k2 lineend"]] \
        [string match "*display backgroundcolor white*" [rowtext k2]] \
        [string match "*color Display*" [rowtext k2]]
} -result {{display: invalid option "backgroundcolor"} 1 0}

test out-1 {informative output inline next to the last statement; trivial output hidden} -body {
    fresh
    five_steps
    list [string match "*… measure rgyr \$sel*→ 20.8431*" [rowtext k4]] [string match "*→*" [rowtext k1]]
} -result {1 0}

test expand-1 {a row expands to its exact command and collapses again} -body {
    fresh
    five_steps
    set open [::vmdai::transcript::toggle_detail k1]
    set lines [split [string trimright [$t get {*}[$t tag ranges detail:k1]] "\n"] "\n"]
    set code {}
    foreach l $lines { if {[string match "  mol *" $l]} { lappend code [string range $l 2 end] } }
    set r [list $open [llength $lines] [expr {[join $code "\n"] eq $::CMD1}] [lindex $lines 0] [lindex $lines end]]
    lappend r [::vmdai::transcript::toggle_detail k1] [llength [$t tag ranges detail:k1]]
} -result {1 6 1 {Load the structure and draw it as a cartoon.} Copy 0 0}

test fit-1 {at 380 px every row, even a 10 KB one-line command, stays one display line} -body {
    fresh
    five_steps
    set long "puts [string repeat {atomselect top "resid 1 to 99" } 330]"
    feed [started req_2] [tstart req_2 k9 $long "A very long command."] [tfin req_2 k9]
    ::vmdai::transcript::set_expand_all 1
    wm geometry . 380x700
    update
    ::vmdai::transcript::relayout
    update
    set wrapped 0
    set outside 0
    foreach k {k1 k2 k3 k4 k5 k9} {
        lassign [$t tag ranges row:$k] a b
        if {[$t count -update -displaylines $a "$b -1c"] > 0} { incr wrapped }
        $t see "$b -2c"
        update
        set box [$t bbox "$b -2c"]
        if {$box eq "" || [lindex $box 0] + [lindex $box 2] > [winfo width $t]} { incr outside }
    }
    set cmd [lindex [tagtext cmd] end]
    list $wrapped $outside [expr {[string length $cmd] >= 13}] [string match "*…" $cmd] \
        [expr {[string length $long] > 10000}]
} -result {0 0 1 1 1}

test group-1 {a finished run collapses when the next starts; chips and the failed row stay visible} -body {
    fresh
    five_steps
    feed [dict create seq 0 ts 1790208020 role user type message text "next" metadata {request_id req_2}] \
        [started req_2]
    lassign [$t tag ranges row:k1] a1 b1
    lassign [$t tag ranges row:k2] a2 b2
    set hdr [$t get {*}[$t tag ranges hdr:r1]]
    list [$t tag cget wl:r1 -elide] [shown $a1 $b1] [expr {[shown $a2 $b2] > 0}] \
        [expr {[shown rowend:k2 "rowend:k2 lineend"] > 0}] [string match "*✓ ✗ ✓ ✓ ✓*" $hdr] \
        [string match "*1 failed, recovered · 16 s*" $hdr]
} -result {1 0 1 1 1 1}

test group-2 {a run that ends on an unrecovered failure stays expanded} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 "nope" "Try it."] \
        [tfin req_1 k1 {ok false error {invalid command name "nope"}}] \
        [finished req_1 complete] [started req_2]
    list [$t tag cget wl:r1 -elide] [expr {[string first "1 failed · 16 s" [$t get {*}[$t tag ranges hdr:r1]]] >= 0}]
} -result {{} 1}

test group-3 {a late result updates its row in place, inside its own run, after the next run started} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 "mol new big.pdb"] \
        [tfin req_1 k1 {ok false executed unknown error {stopped while running}}] \
        [finished req_1 cancelled] [started req_2] [tstart req_2 k2 "mol list"]
    set before [glyph k1]
    feed [tfin req_1 k1 {ok true late true output 7.5}]
    lassign [$t tag ranges row:k1] a b
    list $before [glyph k1] [string match "*(finished late)*" [rowtext k1]] \
        [$t compare $a < [lindex [$t tag ranges hdr:r2] 0]] \
        [string match "*✓*" [$t get {*}[$t tag ranges hdr:r1]]]
} -result {! ✓ 1 1 1}

test highlight-split {the failing statement highlight matches executor::split_statements} -body {
    fresh
    set cmd "mol new a.pdb\nset x \{\n 1\n\}\nbad_cmd 1\nmol delrep 0 top"
    set stmts [dict get [::vmdai::executor::split_statements $cmd] statements]
    feed [started req_1] [tstart req_1 k1 $cmd "Four statements."] \
        [tfin req_1 k1 [dict create ok false error {invalid command name "bad_cmd"} \
            statements [dict create total 4 applied 2 failed [dict create index 3 text "bad_cmd 1"]]]]
    set lines {}
    foreach l [split [$t get {*}[$t tag ranges detail:k1]] "\n"] { lappend lines $l }
    set code {}
    foreach l [lrange $lines 1 6] { lappend code [string range $l 2 end] }
    list [expr {[string trim [join [tagtext dfail] ""]] eq [string trim [lindex $stmts 2]]}] \
        [expr {[string trim [join [tagtext dmuted] ""]] eq [string trim [lindex $stmts 3]]}] \
        [string trim [join [tagtext dgutx] ""]] [expr {[join $code "\n"] eq $cmd}] \
        [expr {"Statements 1–2 ran and are kept in Save .tcl; the rest is commented out" in $lines}]
} -result {1 1 ✗ 1 1}

test full-output-link {C5: output_path adds "Open full output · Reveal" to the detail} -body {
    fresh
    feed [started req_1] [tstart req_1 k1 {puts [$sel get {x y z}]}] \
        [tfin req_1 k1 {output "1 2 3\n4 5 6\n7 8 9\n10 11 12\n13 14 15" output_path /w/outputs/k1.txt}]
    ::vmdai::transcript::toggle_detail k1
    set detail [$t get {*}[$t tag ranges detail:k1]]
    click_link "Open full output"
    click_link "Reveal"
    list [string match "*→ 1 2 3\n4 5 6*Open full output · Reveal*" $detail] $::actions \
        [llength [split [string trimright [join [tagtext preview] ""] "\n"] "\n"]]
} -result {1 {{open_file /w/outputs/k1.txt} {reveal_file /w/outputs/k1.txt}} 4}

test chip-jump {clicking a chip expands the run, shows the row and flashes it} -body {
    fresh
    five_steps
    feed [started req_2]
    set was [$t tag cget wl:r1 -elide]
    set chip [lsearch -inline [$t tag names] chip:k3]
    uplevel #0 [$t tag bind $chip <ButtonRelease-1>]
    update
    lassign [$t tag ranges row:k3] a b
    list $was [$t tag cget wl:r1 -elide] [expr {[$t bbox $a] ne ""}] \
        [expr {[$t tag nextrange flash $a $b] ne ""}]
} -result {1 0 1 1}

test unknown-key {tool.close, run.chip and snapshot for a row never opened do nothing} -body {
    fresh
    five_steps
    set before [::vmdai::transcript::dump]
    ::vmdai::transcript::apply_ops [list \
        [list tool.close k_nope ok "0.1 s" [dict create label "" error "" inline 1.5 preview {} \
            output 1.5 output_path "" total 1 applied 1 failed_index "" failed_text "" late 0] ""] \
        {run.chip r1 k_nope ok} {run.chip r_nope k1 err} \
        {snapshot k_nope /x/t.png /x/p.png 10 10 "" 1 TachyonInternal}]
    list [expr {[::vmdai::transcript::dump] eq $before}] $::vmdai::transcript::S(errors)
} -result {1 0}

test header-footer {run header summary, counts past 12 steps, and the footer links} -body {
    fresh
    five_steps
    set hdr [string map {"\t" "⇥"} [$t get {*}[$t tag ranges hdr:r1]]]
    click_link "Copy Tcl"
    click_link "Save .tcl…"
    feed [started req_2]
    for {set i 1} {$i <= 13} {incr i} { feed [tstart req_2 m$i "mol list"] [tfin req_2 m$i] }
    feed [finished req_2 complete {tool_calls 13 duration_ms 3000}]
    set hdr2 [$t get {*}[$t tag ranges hdr:r2]]
    list $hdr $::actions [string match "*✓13*" $hdr2] [string match "*13 steps · 3 s*" $hdr2]
} -result {{ChatVMD  qwen3.8:27b⇥✓ ✗ ✓ ✓ ✓  1 failed, recovered · 16 s
} {{copy_run_tcl req_1} {save_run_tcl req_1}} 1 1}

test expand-all {expand all opens every run and detail; off re-collapses older runs and closes details} -body {
    fresh
    five_steps
    feed [started req_2] [tstart req_2 k7 "mol list"] [tfin req_2 k7]
    ::vmdai::transcript::set_expand_all 1
    set r [list [$t tag cget wl:r1 -elide] [llength [$t tag ranges detail:k1]] [llength [$t tag ranges detail:k7]]]
    ::vmdai::transcript::set_expand_all 0
    lappend r [$t tag cget wl:r1 -elide] [llength [$t tag ranges detail:k1]] [$t tag cget wl:r2 -elide]
} -result {0 2 2 1 0 0}

test menus {right-click menus for a row and a run header} -body {
    fresh
    five_steps
    set row [::vmdai::transcript::menu_items [lindex [$t tag ranges row:k2] 0]]
    set hdr [::vmdai::transcript::menu_items [lindex [$t tag ranges hdr:r1] 0]]
    set labels {}
    foreach {label cmd} [concat $row $hdr] { lappend labels $label }
    set labels
} -result {{Copy command} {Copy error} Collapse {Copy run Tcl} {Save run .tcl…} Collapse}

test row-labels {snapshot, docs and wiki rows name their tool; a rescued call says (from text); a detail shows 10 command lines, then Show all} -body {
    fresh
    feed [started req_1] [tstart req_1 s1 "" "check the cartoon" capture_vmd_snapshot] \
        [st tool.started [dict create request_id req_1 turn 1 call_key d1 tool_name search_docs \
            executor runtime origin model input [dict create query "mol modcolor methods"]]] \
        [st tool.started [dict create request_id req_1 turn 1 call_key w1 tool_name wiki_read \
            executor runtime origin model input [dict create page coloring]]] \
        [st tool.started [dict create request_id req_1 turn 1 call_key r1 tool_name run_vmd_command \
            executor tcl origin rescued input [dict create command "mol list"]]]
    set long {}
    for {set i 1} {$i <= 14} {incr i} { lappend long "mol list $i" }
    feed [tstart req_1 k1 [join $long "\n"]] [tfin req_1 k1]
    ::vmdai::transcript::toggle_detail k1
    set before [llength [lsearch -all [split [$t get {*}[$t tag ranges detail:k1]] "\n"] "  mol list *"]]
    click_link "Show all 14 lines"
    ::vmdai::transcript::_do_show_all k1
    set after [llength [lsearch -all [split [$t get {*}[$t tag ranges detail:k1]] "\n"] "  mol list *"]]
    list [string match "*Snapshot  check the cartoon*" [rowtext s1]] \
        [string match "*Docs: mol modcolor methods*" [rowtext d1]] \
        [string match "*Wiki: coloring*" [rowtext w1]] \
        [string match "*mol list  (from text)*" [rowtext r1]] $before $after $::actions
} -result {1 1 1 1 10 14 {{show_all k1}}}

test row-click {a click on a row toggles its detail; a drag of more than 3 px or a new selection does not} -body {
    fresh
    five_steps
    set r {}
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 12 11
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 30 10
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    $t tag add sel "rowend:k3 -1l linestart" "rowend:k3 -1c"
    ::vmdai::transcript::_row_release k1 10 10
    $t tag remove sel 1.0 end
    lappend r [llength [$t tag ranges detail:k1]]
    ::vmdai::transcript::_row_press 10 10
    ::vmdai::transcript::_row_release k1 10 10
    lappend r [llength [$t tag ranges detail:k1]]
} -result {2 2 2 0}

test refit-order {V6 row refit: drop the rationale, then +N lines, then ellipsize the command (never below 12 characters), then drop the duration} -body {
    fresh
    feed [started req_1] \
        [tstart req_1 k1 "mol representation NewCartoon 0.3 30 4.1\nmol addrep top" "Draw it as a thick cartoon."] \
        [tfin req_1 k1 {duration_ms 412}]
    set seen {}
    for {set cw 900} {$cw >= 60} {incr cw -4} {
        lassign [::vmdai::transcript::_row_fit k1 $cw] text style suffix right
        set state [list [expr {[string first "Draw it" $suffix] >= 0}] \
            [expr {[string first "+1 lines" $suffix] >= 0}] \
            [expr {[string index $text end] eq "…"}] [expr {[string first "0.4 s" $right] >= 0}]]
        if {$state ne [lindex $seen end]} { lappend seen $state }
    }
    list $seen [string length [lindex [::vmdai::transcript::_row_fit k1 60] 0]]
} -result {{{1 1 0 1} {0 1 0 1} {0 0 0 1} {0 0 1 1} {0 0 1 0}} 13}

cleanupTests
exit
```

The events go through the real view-model (`feed`), so the rows see exactly the `detail` dicts that `_tool_detail` builds. `fit-1` turns on "Expand all steps" before measuring, because the second request collapses the first run, and an elided row has no `bbox`. `row-labels` pins Part B V4's other row labels (`Snapshot` and the purpose, `Docs: …`, `Wiki: …`, `(from text)` for §2c's rescued calls) and the detail's 10-line limit with `Show all N lines`; `row-click` pins V5's rule that a click toggles the detail but a drag of more than 3 px or a new selection does not (it calls the procs the row bindings call). `refit-order` walks `_row_fit` from 900 px down to 60 px and pins V6's order: the rationale goes first, then `+N lines`, then the command is ellipsized (13 characters at the narrowest: 12 plus `…`), and the duration goes last. The three are checked by pytest `test_run_header_footer_expand_and_menus`, so the pytest count stays 15.

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tk_tool_rows.py`:

```python
"""Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).

The adopted cases come from the native prototype's proto_test (glue-1,
status-1, err-1, out-1, expand-1, fit-1) and the cards prototype's
test_proto (group-1..3), rewritten against the view-model ops."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_tool_rows.tcl"
ADOPTED = ["glue-1", "status-1", "err-1", "out-1", "expand-1", "fit-1", "group-1", "group-2", "group-3"]
TESTS = ADOPTED + [
    "highlight-split",
    "full-output-link",
    "chip-jump",
    "unknown-key",
    "header-footer",
    "expand-all",
    "menus",
    "row-labels",
    "row-click",
    "refit-order",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


def test_tool_rows_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


@pytest.mark.parametrize("name", ADOPTED)
def test_adopted(result, name):
    assert_tcltests(result, [name])


def test_failing_statement_highlight_matches_executor_split(result):
    assert_tcltests(result, ["highlight-split"])


def test_open_full_output_link(result):
    assert_tcltests(result, ["full-output-link"])


def test_chip_click_jumps(result):
    assert_tcltests(result, ["chip-jump"])


def test_unknown_call_key_noop(result):
    assert_tcltests(result, ["unknown-key"])


def test_run_header_footer_expand_and_menus(result):
    assert_tcltests(result, ["header-footer", "expand-all", "menus", "row-labels", "row-click", "refit-order"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_tool_rows.py -q 2>&1 | tail -2`
Expected: `15 failed`; every tcltest case errors in `fresh` with `invalid command name "::vmdai::transcript::set_expand_all"` (and Task 5's transcript ignores the row and run ops anyway).

- [ ] **Step 4: Append the rows section to the transcript**

Append to the end of `plugin/transcript.tcl`:

```tcl

# ===========================================================================
# Tool rows, step detail, run headers, chips, footers, collapse (P08-T06).
#
# Part B V4 "Tool rows", "Step detail", "Run header", "Collapse"; V6 row
# refit. A row is exactly one display line, keyed by call_key: the glyph
# (glyph:$k), a tab, the command, muted extras, a right tab, the result or
# label, the duration and a chevron, all tagged row:$k. The left-gravity
# mark rowend:$k sits at the start of the line after the row; below it come,
# in this order, the error line (err:$k) or output preview (prev:$k), the
# step detail (detail:$k) and the snapshot card (snap:$k, Task 7).
# ===========================================================================

namespace eval ::vmdai::transcript {
    variable RUN
    if {![info exists RUN]} { array set RUN {} }
    variable ROW
    if {![info exists ROW]} { array set ROW {} }
    variable run_order
    if {![info exists run_order]} { set run_order {} }
    variable expand_all
    if {![info exists expand_all]} { set expand_all 0 }
}

proc ::vmdai::transcript::_tags_rows {} {
    variable W
    set C ::vmdai::theme::c
    $W tag configure runhdr -font ChatRole -foreground [$C text] -spacing1 20 -spacing3 4
    $W tag configure runmodel -font ChatMeta -foreground [$C muted]
    $W tag configure runsum -font ChatMeta -foreground [$C muted]
    $W tag configure chip -font ChatMetaBold
    $W tag configure chip_ok -foreground [$C ok]
    $W tag configure chip_err -foreground [$C err]
    $W tag configure chip_warn -foreground [$C warn]
    $W tag configure chip_running -foreground [$C muted]
    $W tag configure chip_notrun -foreground [$C muted]
    $W tag configure row -spacing1 3 -spacing3 3 -lmargin1 0 -lmargin2 24
    $W tag configure cmd -font ChatCodeSmall -foreground [$C text2]
    $W tag configure snapcmd -font ChatBody -foreground [$C text]
    $W tag configure extra -font ChatMeta -foreground [$C muted]
    $W tag configure meta -font ChatMeta -foreground [$C muted]
    $W tag configure chev -font ChatMeta -foreground [$C muted]
    $W tag configure g_ok -font ChatMetaBold -foreground [$C ok]
    $W tag configure g_err -font ChatMetaBold -foreground [$C err]
    $W tag configure g_warn -font ChatMetaBold -foreground [$C warn]
    $W tag configure g_no -font ChatMetaBold -foreground [$C muted]
    $W tag configure g_run -font ChatMetaBold -foreground [$C muted]
    $W tag configure errline -font ChatCodeSmall -foreground [$C err] \
        -lmargin1 24 -lmargin2 24 -spacing3 4
    $W tag configure preview -font ChatCodeSmall -foreground [$C muted] -lmargin1 24 -lmargin2 24
    $W tag configure detail -font ChatCode -foreground [$C text] -background [$C code_bg] \
        -lmargin1 24 -lmargin2 36 -rmargin 8
    $W tag configure dnote -font ChatMeta -foreground [$C muted]
    $W tag configure dgut -foreground [$C faint]
    $W tag configure dgutx -foreground [$C err]
    $W tag configure dcode
    $W tag configure dfail -background [$C err_bg]
    $W tag configure dmuted -foreground [$C muted]
    $W tag configure dout -foreground [$C muted]
    $W tag configure dlink -font ChatMeta
    $W tag configure dfirst -spacing1 8
    $W tag configure dlast -spacing3 8
    $W tag configure footer -font ChatMeta -foreground [$C muted] -justify right \
        -spacing1 2 -spacing3 8
    catch {$W tag configure detail -lmargincolor [$C code_bg]}
    catch {$W tag configure dfail -lmargincolor [$C err_bg]}
    $W tag raise link
    $W tag raise flash
}

proc ::vmdai::transcript::_clear_rows {} {
    variable S
    variable RUN
    variable ROW
    variable run_order
    if {[info exists S(tick)] && $S(tick) ne ""} {
        ::vmdai::sched::cancel $S(tick)
        set S(tick) ""
    }
    array unset RUN
    array unset ROW
    set run_order {}
}

# ---- run header, chips, footer -------------------------------------------------

proc ::vmdai::transcript::op_run.open {run request_id model t0} {
    variable W
    variable S
    variable RUN
    variable run_order
    variable expand_all
    if {[info exists RUN($run,status)]} { return }
    # When a new run starts, earlier runs that ended without an unrecovered
    # failure hide their work log (Part B V4 "Collapse").
    if {!$expand_all} {
        foreach r $run_order {
            if {[_collapsible $r]} { _collapse $r 1 }
        }
    }
    lappend run_order $run
    array set RUN [list $run,req $request_id $run,model $model $run,t0 $t0 \
        $run,status running $run,chips {} $run,summary "" $run,collapsed 0 \
        $run,failed 0 $run,recovered 0 $run,snaps {}]
    set S(cur_run) $run
    set S(answer) 0
    $W insert end "\n" [list runhdr hdr:$run]
    _render_header $run
}

proc ::vmdai::transcript::op_run.chip {run k state} {
    variable RUN
    variable ROW
    if {![info exists RUN($run,status)] || ![info exists ROW($k,name)]} { return }
    dict set RUN($run,chips) $k $state
    if {$ROW($k,run) ne $run} {
        set ROW($k,run) $run
        _row_wl $k
    }
    _render_header $run
}

proc ::vmdai::transcript::op_run.close {run status steps failed recovered duration_s final_text_empty {max_turns 28}} {
    variable RUN
    if {![info exists RUN($run,status)]} { return }
    array set RUN [list $run,status $status $run,failed $failed $run,recovered $recovered \
        $run,summary [::vmdai::vm::run_summary $status $steps $failed $recovered $duration_s $max_turns]]
    _render_header $run
}

# The footer appears once a run applied at least one statement; M2 prints
# the links only (the usage line is plan 10's).
proc ::vmdai::transcript::op_footer {run applied usage_text} {
    variable W
    variable RUN
    if {![info exists RUN($run,req)] || ![string is integer -strict $applied] || $applied < 1} {
        return
    }
    set req $RUN($run,req)
    set tags [list footer]
    $W insert end "Copy Tcl" [concat $tags link [_link copy_run_tcl $req]] " · " $tags \
        "Save .tcl…" [concat $tags link [_link save_run_tcl $req]] "\n" $tags
}

# A run stays expanded while it runs, and when it ended with an error, stuck,
# lost, or with a failure it did not recover from.
proc ::vmdai::transcript::_collapsible {run} {
    variable RUN
    if {$RUN($run,status) in {running error stuck lost ended}} { return 0 }
    if {$RUN($run,failed) > 0 && !$RUN($run,recovered)} { return 0 }
    return 1
}

proc ::vmdai::transcript::_collapse {run on} {
    variable W
    variable RUN
    if {![info exists RUN($run,status)]} { return }
    set RUN($run,collapsed) [expr {$on ? 1 : 0}]
    $W tag configure wl:$run -elide $RUN($run,collapsed)
}

proc ::vmdai::transcript::_chip_glyph {state} {
    switch -- $state {
        ok      { return "✓" }
        err     { return "✗" }
        warn    { return "!" }
        notrun  { return "–" }
    }
    return "•"
}

# Chips as counts ("✓14 ✗2"), used past 12 steps or when the header is narrow.
proc ::vmdai::transcript::_chip_counts {chips} {
    set out {}
    foreach state {ok err warn notrun running} {
        set n 0
        dict for {k s} $chips { if {$s eq $state} { incr n } }
        if {$n} { lappend out $state "[_chip_glyph $state]$n" }
    }
    return $out
}

# Header refit (V6): drop the model name, then shorten "N failed, recovered"
# to "N failed", then switch the chips to counts.
proc ::vmdai::transcript::_header_fit {run cw} {
    variable RUN
    set chips $RUN($run,chips)
    set summary $RUN($run,summary)
    set model $RUN($run,model)
    set counts [expr {[dict size $chips] > 12}]
    foreach step {full nomodel short counts} {
        switch -- $step {
            nomodel { set model "" }
            short   { regsub {, recovered} $summary "" summary }
            counts  { set counts 1 }
        }
        if {$counts} {
            set chiptext [join [dict values [_chip_counts $chips]] " "]
        } else {
            set chiptext [string repeat "✓ " [dict size $chips]]
        }
        set left [font measure ChatRole "ChatVMD"]
        if {$model ne ""} { incr left [font measure ChatMeta "  $model"] }
        set right [expr {[font measure ChatMetaBold $chiptext] + [font measure ChatMeta "  $summary"]}]
        if {$left + $right + 16 <= $cw} { break }
    }
    return [list $model $summary $counts]
}

proc ::vmdai::transcript::_render_header {run} {
    variable W
    variable RUN
    set r [$W tag ranges hdr:$run]
    if {![llength $r]} { return }
    set at [lindex $r 0]
    $W delete $at "[lindex $r end] -1c"
    lassign [_header_fit $run [_content_width]] model summary counts
    set tags [list runhdr hdr:$run]
    set pieces [list "ChatVMD" $tags]
    if {$model ne ""} { lappend pieces "  $model" [concat $tags runmodel] }
    lappend pieces "\t" $tags
    set chips $RUN($run,chips)
    if {$counts} {
        foreach {state text} [_chip_counts $chips] {
            lappend pieces $text [concat $tags chip chip_$state] " " $tags
        }
    } else {
        dict for {k state} $chips {
            lappend pieces [_chip_glyph $state] [concat $tags chip chip_$state chip:$k] " " $tags
        }
    }
    if {$summary ne ""} { lappend pieces " $summary" [concat $tags runsum] }
    $W insert $at {*}$pieces
    dict for {k state} $chips {
        $W tag bind chip:$k <ButtonRelease-1> [list ::vmdai::transcript::jump_to $k]
    }
}

# ---- rows -----------------------------------------------------------------------

proc ::vmdai::transcript::op_tool.open {k name command executor origin {rationale ""}} {
    variable W
    variable S
    variable ROW
    variable opt
    variable expand_all
    if {[info exists ROW($k,name)]} { return }
    array set ROW [list $k,name $name $k,cmd $command $k,executor $executor \
        $k,origin $origin $k,rationale $rationale $k,state running $k,dur "" \
        $k,detail {} $k,open 0 $k,run $S(cur_run) $k,t0 [clock seconds] $k,frame 0 $k,fit ""]
    set tags [concat row row:$k [_wl]]
    $W insert end "•" [concat $tags glyph:$k g_run] "\n" $tags
    $W mark set rowend:$k "end -1c"
    $W mark gravity rowend:$k left
    _render_row $k
    $W tag bind row:$k <Enter> [list ::vmdai::transcript::_row_hover $k 1]
    $W tag bind row:$k <Leave> [list ::vmdai::transcript::_row_hover $k 0]
    $W tag bind row:$k <ButtonPress-1> [list ::vmdai::transcript::_row_press %x %y]
    $W tag bind row:$k <ButtonRelease-1> [list ::vmdai::transcript::_row_release $k %x %y]
    if {$expand_all} { _open_detail $k }
    if {$opt(animate) && $S(tick) eq ""} {
        set S(tick) [::vmdai::sched::after 1000 ::vmdai::transcript::_tick]
    }
}

proc ::vmdai::transcript::op_tool.close {k state duration_text detail thumb} {
    variable W
    variable ROW
    variable expand_all
    if {![info exists ROW($k,name)]} { return }
    array set ROW [list $k,state $state $k,dur $duration_text $k,detail $detail $k,fit ""]
    foreach section {err prev} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    }
    _set_glyph $k
    _row_wl $k
    set wl [_row_run_wl $k]
    if {$state eq "err" && [dict get $detail error] ne ""} {
        set tags [list errline err:$k]
        $W insert rowend:$k [dict get $detail error] $tags "\n" $tags
    } elseif {$state eq "ok"} {
        set tags [concat preview prev:$k $wl]
        set at rowend:$k
        foreach line [lreverse [dict get $detail preview]] {
            $W insert $at $line $tags "\n" $tags
        }
    }
    _render_row $k
    set total [dict get $detail total]
    if {$ROW($k,open)} {
        _close_detail $k
        _open_detail $k
    } elseif {$expand_all || ($state eq "err" && [string is integer -strict $total] && $total > 1)} {
        _open_detail $k
    }
}

# The work-log tag for what hangs under a row; a failed row's error line
# and detail stay visible when its run collapses.
proc ::vmdai::transcript::_row_run_wl {k} {
    variable ROW
    if {$ROW($k,run) eq "" || $ROW($k,state) eq "err"} { return {} }
    return [list wl:$ROW($k,run)]
}

# A failed row and its error line stay visible when the run collapses.
proc ::vmdai::transcript::_row_wl {k} {
    variable W
    variable ROW
    set r [$W tag ranges row:$k]
    if {![llength $r]} { return }
    foreach tag [$W tag names] {
        if {[string match wl:* $tag]} { $W tag remove $tag {*}$r }
    }
    if {$ROW($k,state) ne "err" && $ROW($k,run) ne ""} { $W tag add wl:$ROW($k,run) {*}$r }
}

proc ::vmdai::transcript::_set_glyph {k {char ""}} {
    variable W
    variable ROW
    switch -- $ROW($k,state) {
        ok      { set g "✓"; set style g_ok }
        err     { set g "✗"; set style g_err }
        notrun  { set g "–"; set style g_no }
        unknown { set g "!"; set style g_warn }
        default { set g "•"; set style g_run }
    }
    if {$char ne ""} { set g $char }
    set at [lindex [$W tag ranges glyph:$k] 0]
    set keep {}
    foreach tag [$W tag names $at] {
        if {$tag ni {g_ok g_err g_no g_warn g_run}} { lappend keep $tag }
    }
    $W delete $at
    $W insert $at $g [concat $keep $style]
}

# The command text a row shows (Part B V4 "Which command line is shown").
proc ::vmdai::transcript::_row_command {k} {
    variable ROW
    set cmd $ROW($k,cmd)
    set d $ROW($k,detail)
    set name $ROW($k,name)
    switch -glob -- $name {
        capture_vmd_snapshot { return [list "Snapshot" snapcmd] }
        search_docs          { return [list "Docs: [_first_line $cmd]" snapcmd] }
        wiki_*               { return [list "Wiki: [_first_line $cmd]" snapcmd] }
    }
    if {$ROW($k,state) eq "err" && [_dget $d failed_text] ne ""} {
        return [list [_first_line [_dget $d failed_text]] cmd]
    }
    if {$ROW($k,state) eq "ok" && [_dget $d inline] ne ""} {
        set stmts [_statements $cmd]
        if {[llength $stmts] > 1} {
            return [list "… [_first_line [lindex $stmts end]]" cmd]
        }
    }
    return [list [_first_line $cmd] cmd]
}

proc ::vmdai::transcript::_dget {d key} {
    if {[catch {dict get $d $key} v] || $v eq "null"} { return "" }
    return $v
}

proc ::vmdai::transcript::_first_line {s} {
    foreach line [split $s "\n"] {
        if {[string trim $line] ne ""} { return [string trim $line] }
    }
    return ""
}

# Statements as the executor splits them (C3); the whole text when the
# splitter is not loaded.
proc ::vmdai::transcript::_statements {cmd} {
    if {[catch {::vmdai::executor::split_statements $cmd} d]} { return [list $cmd] }
    set out [dict get $d statements]
    if {[string trim [dict get $d tail]] ne ""} { lappend out [dict get $d tail] }
    return $out
}

proc ::vmdai::transcript::_row_meta {k} {
    variable ROW
    set d $ROW($k,detail)
    set parts {}
    switch -- $ROW($k,state) {
        running {
            set secs [expr {[clock seconds] - $ROW($k,t0)}]
            lappend parts [expr {$secs >= 2 ? "running… $secs s" : "running…"}]
        }
        ok {
            if {[_dget $d inline] ne ""} { lappend parts "→ [_dget $d inline]" }
            lappend parts $ROW($k,dur)
        }
        err { lappend parts $ROW($k,dur) }
    }
    lappend parts [_dget $d label]
    set out {}
    foreach p $parts { if {$p ne ""} { lappend out $p } }
    return $out
}

# Fit a row into one display line (V6 refit order): drop the rationale,
# then "+N lines", then ellipsize the command (never below 12 characters),
# then drop the duration; a label that still does not fit is ellipsized.
proc ::vmdai::transcript::_row_fit {k cw} {
    variable ROW
    lassign [_row_command $k] text style
    set font [expr {$style eq "cmd" ? "ChatCodeSmall" : "ChatBody"}]
    set extras {}
    if {$ROW($k,name) eq "capture_vmd_snapshot"} {
        set why [_first_line $ROW($k,cmd)]
    } else {
        set why $ROW($k,rationale)
        set n [llength [split [string trimright $ROW($k,cmd) "\n"] "\n"]]
        if {$n > 1 && $style eq "cmd"} { lappend extras "+[expr {$n - 1}] lines" }
    }
    set from [expr {$ROW($k,origin) eq "rescued" ? "  (from text)" : ""}]
    set meta [_row_meta $k]
    set chev [expr {$ROW($k,open) ? "▾" : "▸"}]
    set room [expr {$cw - 24 - 12}]
    foreach step {full norationale noextras ellipsize noduration label} {
        switch -- $step {
            norationale { set why "" }
            noextras    { set extras {} }
            noduration  {
                if {$ROW($k,dur) ne ""} {
                    set i [lsearch -exact $meta $ROW($k,dur)]
                    if {$i >= 0} { set meta [lreplace $meta $i $i] }
                }
            }
        }
        set right "[join $meta "  "]  $chev"
        set avail [expr {$room - [font measure ChatMeta $right] - [font measure ChatMeta $from]}]
        set suffix ""
        foreach e $extras { append suffix "  $e" }
        if {$why ne ""} { append suffix "  $why" }
        if {$step in {ellipsize noduration label}} {
            set text [::vmdai::theme::fit $font [expr {$avail - [font measure ChatMeta $suffix]}] $text 12]
        }
        if {$step eq "label"} {
            set right "[::vmdai::theme::fit ChatMeta [expr {$room / 2}] [join $meta "  "] 8]  $chev"
        }
        if {[font measure $font $text] + [font measure ChatMeta $suffix] <= $avail} { break }
    }
    return [list $text $style "$suffix$from" $right]
}

proc ::vmdai::transcript::_render_row {k} {
    variable W
    variable ROW
    set fit [_row_fit $k [_content_width]]
    set g [$W tag ranges glyph:$k]
    if {![llength $g]} { return }
    set at [lindex $g 1]
    set line [$W get $at "rowend:$k -1c"]
    if {$fit eq $ROW($k,fit) && $line ne ""} { return }
    set ROW($k,fit) $fit
    lassign $fit text style suffix right
    set rt [concat row row:$k [lsearch -all -inline [$W tag names $at] wl:*]]
    $W delete $at "rowend:$k -1c"
    $W insert $at "\t" $rt $text [concat $rt $style] $suffix [concat $rt extra] "\t" $rt \
        [string range $right 0 end-1] [concat $rt meta] [string index $right end] [concat $rt chev]
}

proc ::vmdai::transcript::_relayout_rows {cw narrow} {
    variable W
    variable ROW
    variable RUN
    $W tag configure row -tabs [list 24 left [expr {$cw - 2}] right]
    $W tag configure runhdr -tabs [list $cw right]
    foreach key [array names ROW *,name] { _render_row [lindex [split $key ,] 0] }
    foreach key [array names RUN *,status] { _render_header [lindex [split $key ,] 0] }
}

# One shared 1 s ticker while any row runs: elapsed time and the spinner.
proc ::vmdai::transcript::_tick {} {
    variable S
    variable ROW
    variable W
    set S(tick) ""
    if {$W eq "" || [info commands $W] eq ""} { return }
    set frames [list "◐" "◓" "◑" "◒"]
    set running 0
    foreach key [array names ROW *,state] {
        set k [lindex [split $key ,] 0]
        if {$ROW($key) ne "running"} { continue }
        incr running
        set ROW($k,frame) [expr {($ROW($k,frame) + 1) % 4}]
        _set_glyph $k [lindex $frames $ROW($k,frame)]
        _render_row $k
    }
    if {$running} { set S(tick) [::vmdai::sched::after 1000 ::vmdai::transcript::_tick] }
}

proc ::vmdai::transcript::_row_hover {k on} {
    variable W
    set bg [expr {$on ? [::vmdai::theme::c hover] : ""}]
    $W tag configure row:$k -background $bg
    catch {$W tag configure row:$k -lmargincolor $bg}
    $W configure -cursor [expr {$on ? "hand2" : "arrow"}]
}

# A click toggles the detail, but not after a drag of more than 3 px or a
# new selection, so text in a row can still be selected (V5).
proc ::vmdai::transcript::_row_press {x y} {
    variable W
    variable S
    set S(press) [list $x $y [$W tag ranges sel]]
}

proc ::vmdai::transcript::_row_release {k x y} {
    variable W
    variable S
    if {![info exists S(press)]} { return }
    lassign $S(press) x0 y0 sel0
    unset S(press)
    if {abs($x - $x0) > 3 || abs($y - $y0) > 3 || [$W tag ranges sel] ne $sel0} { return }
    toggle_detail $k
}

# ---- step detail ----------------------------------------------------------------

proc ::vmdai::transcript::toggle_detail {k} {
    variable ROW
    if {![info exists ROW($k,name)]} { return 0 }
    if {$ROW($k,open)} { _close_detail $k } else { _open_detail $k }
    return $ROW($k,open)
}

proc ::vmdai::transcript::_close_detail {k} {
    variable W
    variable ROW
    set r [$W tag ranges detail:$k]
    if {[llength $r]} { $W delete [lindex $r 0] [lindex $r end] }
    set ROW($k,open) 0
    set ROW($k,fit) ""
    _render_row $k
}

proc ::vmdai::transcript::_open_detail {k} {
    variable W
    variable ROW
    if {$ROW($k,open)} { return }
    set ROW($k,open) 1
    set ROW($k,fit) ""
    _render_row $k
    set at rowend:$k
    foreach section {err prev} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { set at [lindex $r end] }
    }
    $W mark set dins:$k $at
    $W mark gravity dins:$k right
    _build_detail $k
    $W mark unset dins:$k
}

# Split cmd into {text class} segments that cover it byte for byte:
# statements before the failing one are "", the failing one "dfail", the
# rest "dmuted" (the executor's own splitter decides the boundaries).
proc ::vmdai::transcript::_cmd_segments {cmd failed_index} {
    if {![string is integer -strict $failed_index] || $failed_index < 1} {
        return [list $cmd ""]
    }
    set segs {}
    set pos 0
    set i 0
    foreach stmt [_statements $cmd] {
        incr i
        set s [string first $stmt $cmd $pos]
        if {$s < 0} { continue }
        set e [expr {$s + [string length $stmt]}]
        if {$s > $pos} { lappend segs [string range $cmd $pos [expr {$s - 1}]] "" }
        set class [expr {$i < $failed_index ? "" : ($i == $failed_index ? "dfail" : "dmuted")}]
        lappend segs [string range $cmd $s [expr {$e - 1}]] $class
        set pos $e
    }
    if {$pos < [string length $cmd]} { lappend segs [string range $cmd $pos end] "" }
    return $segs
}

# The command as display lines, each a flat list {text class ...}.
proc ::vmdai::transcript::_cmd_lines {cmd failed_index} {
    set lines {}
    set cur {}
    foreach {text class} [_cmd_segments $cmd $failed_index] {
        set parts [split $text "\n"]
        lappend cur [lindex $parts 0] $class
        foreach part [lrange $parts 1 end] {
            lappend lines $cur
            set cur [list $part $class]
        }
    }
    lappend lines $cur
    return $lines
}

proc ::vmdai::transcript::_export_note {total applied} {
    if {![string is integer -strict $applied] || $applied < 1} { return "Not in Save .tcl" }
    if {$applied == 1} {
        return "Statement 1 ran and is kept in Save .tcl; the rest is commented out"
    }
    return "Statements 1–$applied ran and are kept in Save .tcl; the rest is commented out"
}

# The step detail (Part B V4): the rationale, the exact command bytes (10
# lines, then "Show all N lines"; a failure shows every statement, the
# failing one on err_bg with a ✗ in the gutter and the rest muted), the
# output (12 lines), "Open full output · Reveal" when output_path is set
# (C5), the export note for a failure, and Copy. Inserted at mark dins:$k.
proc ::vmdai::transcript::_build_detail {k} {
    variable W
    variable ROW
    set d $ROW($k,detail)
    set cmd $ROW($k,cmd)
    set base [concat detail detail:$k [_row_run_wl $k]]
    set failed [_dget $d failed_index]
    set first [$W index dins:$k]
    if {$ROW($k,rationale) ne ""} {
        $W insert dins:$k $ROW($k,rationale) [concat $base dnote] "\n" $base
    }
    set total_lines [llength [split $cmd "\n"]]
    set limit [expr {$failed eq "" && ![info exists ROW($k,all)] ? 10 : $total_lines}]
    set marked 0
    set n 0
    foreach line [_cmd_lines $cmd $failed] {
        if {$n == $limit} { break }
        incr n
        set gutter [list "  " [concat $base dgut]]
        if {!$marked && [lsearch -exact $line dfail] >= 0} {
            set gutter [list "✗ " [concat $base dgut dgutx]]
            set marked 1
        }
        $W insert dins:$k {*}$gutter
        foreach {text class} $line {
            if {$text ne ""} { $W insert dins:$k $text [concat $base dcode $class] }
        }
        $W insert dins:$k "\n" $base
    }
    if {$total_lines > $limit} {
        $W insert dins:$k "Show all $total_lines lines" \
            [concat $base dlink link [_link show_all $k]] "\n" $base
    }
    set out [string trimright [_dget $d output] "\n"]
    if {$out ne ""} {
        set olines [split $out "\n"]
        set shown [lrange $olines 0 11]
        set shown [lreplace $shown 0 0 "→ [lindex $shown 0]"]
        foreach l $shown { $W insert dins:$k $l [concat $base dout] "\n" $base }
        if {[llength $olines] > 12} {
            $W insert dins:$k "… [expr {[llength $olines] - 12}] more lines" [concat $base dout] "\n" $base
        }
    }
    set path [_dget $d output_path]
    if {$path ne ""} {
        $W insert dins:$k "Open full output" [concat $base dlink link [_link open_file $path]] \
            " · " [concat $base dlink] "Reveal" [concat $base dlink link [_link reveal_file $path]] "\n" $base
    }
    if {$failed ne "" || $ROW($k,state) eq "err"} {
        $W insert dins:$k [_export_note [_dget $d total] [_dget $d applied]] [concat $base dnote] "\n" $base
    }
    $W insert dins:$k "Copy" [concat $base dlink link [_link copy_text $cmd]] "\n" $base
    $W tag add dfirst $first "$first lineend +1c"
    $W tag add dlast "dins:$k -1l linestart" dins:$k
}

proc ::vmdai::transcript::_do_show_all {k} {
    variable ROW
    if {![info exists ROW($k,name)]} { return }
    set ROW($k,all) 1
    _close_detail $k
    _open_detail $k
}

# ⌘E / "Expand all steps": every run shown and every detail open. Off: the
# collapse rule applies again (the newest run stays open) and details close.
proc ::vmdai::transcript::set_expand_all {on} {
    variable ROW
    variable RUN
    variable run_order
    variable expand_all
    variable W
    set expand_all [expr {$on ? 1 : 0}]
    if {$W eq "" || [info commands $W] eq ""} { return }
    foreach key [array names ROW *,name] {
        set k [lindex [split $key ,] 0]
        if {$expand_all} { _open_detail $k } elseif {$ROW($k,open)} { _close_detail $k }
    }
    foreach run $run_order {
        if {$expand_all} {
            _collapse $run 0
        } elseif {$run ne [lindex $run_order end] && [_collapsible $run]} {
            _collapse $run 1
        }
    }
}

# ---- right-click menus and actions ---------------------------------------------

proc ::vmdai::transcript::_row_menu {k} {
    variable ROW
    set d $ROW($k,detail)
    set items [list "Copy command" [list ::vmdai::transcript::_clipboard $ROW($k,cmd)]]
    if {[_dget $d output] ne ""} {
        lappend items "Copy output" [list ::vmdai::transcript::_clipboard [_dget $d output]]
    }
    if {[_dget $d error] ne ""} {
        lappend items "Copy error" [list ::vmdai::transcript::_clipboard [_dget $d error]]
    }
    lappend items [expr {$ROW($k,open) ? "Collapse" : "Expand"}] \
        [list ::vmdai::transcript::toggle_detail $k]
    return $items
}

proc ::vmdai::transcript::_run_menu {run} {
    variable RUN
    set req $RUN($run,req)
    return [list "Copy run Tcl" [list ::vmdai::transcript::_action copy_run_tcl $req] \
        "Save run .tcl…" [list ::vmdai::transcript::_action save_run_tcl $req] \
        [expr {$RUN($run,collapsed) ? "Expand" : "Collapse"}] \
        [list ::vmdai::transcript::_collapse $run [expr {!$RUN($run,collapsed)}]]]
}

proc ::vmdai::transcript::_do_copy_run_tcl {request_id} {
    if {[info commands ::vmdai::tclexport::run_tcl] eq ""} { return }
    _clipboard [::vmdai::tclexport::run_tcl $request_id]
}

proc ::vmdai::transcript::_do_save_run_tcl {request_id} {
    variable T
    if {[info commands ::vmdai::tclexport::run_tcl] eq ""} { return }
    set path [tk_getSaveFile -parent [winfo toplevel $T] -title "Save run .tcl" \
        -defaultextension .tcl -initialfile run.tcl]
    if {$path eq ""} { return }
    ::vmdai::tclexport::save $path [::vmdai::tclexport::run_tcl $request_id]
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_tk_tool_rows.py tests/test_tk_transcript.py -q 2>&1 | tail -4`
Expected: `2 failed, 23 passed`. The failures are `test_golden_03_conversation` and `test_golden_reasoning_answer` with `golden mismatch:`: the diffs add the run headers, the rows and the footers, and remove the first run's work-log prose from `03_conversation` (that run is collapsed once the second request starts).

- [ ] **Step 6: Regenerate the Tk goldens and review them**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py -q -k golden 2>&1 | tail -1 && cat tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt`
Expected: `2 passed, 8 deselected`, then:

```text
images 0
001 role rolemeta | You⇥12:00 AM
002 user | load 1hck and show it as a cartoon
003 chip chip_err chip_ok runhdr runmodel runsum | ChatVMD  qwen3.8:27b⇥✓ ✗ ✓ ✓  1 failed, recovered · 5 s
006 chev cmd extra g_err meta row | ✗⇥display backgroundcolor white  +1 lines  Make the background white.⇥0.5 s  ▾
007 errline | display: invalid option "backgroundcolor"
008 detail dfirst dnote | Make the background white.
009 dcode detail dgut |   color Display Background white
010 dcode detail dfail dgut dgutx | ✗ display backgroundcolor white
011 detail dnote | Statement 1 ran and is kept in Save .tcl; the rest is commented out
012 detail dlast dlink link | Copy
016 rule | <rule>
017 prose | Loaded **1hck** as a cartoon on a white background.
018 footer link | Copy Tcl · Save .tcl…
019 role rolemeta | You⇥12:00 AM
020 user | what is its radius of gyration?
021 chip chip_ok runhdr runmodel runsum | ChatVMD  qwen3.8:27b⇥✓  1 step · 5 s
022 chev cmd extra g_ok meta row | ✓⇥… measure rgyr $sel  +1 lines  Radius of gyration of the protein.⇥→ 20.8431  0.5 s  ▸
023 rule | <rule>
024 prose | The radius of gyration is 20.84 Å.
025 footer link | Copy Tcl · Save .tcl…
images 0
001 role rolemeta | You⇥12:00 AM
002 user | how many atoms does 1hck have?
003 chip chip_ok runhdr runmodel runsum | ChatVMD  qwen3.8:27b⇥✓  1 step · 5 s
004 think | Thought for 1 s ▸
006 chev cmd extra g_ok meta row | ✓⇥… $sel num  +1 lines  Count the atoms.⇥→ 2442  0.5 s  ▸
007 think | Thought for 1 s ▸
009 rule | <rule>
010 prose | 1hck has 2442 atoms.
011 footer link | Copy Tcl · Save .tcl…
```

Check by eye: the first run is collapsed but keeps its header with four chips (`✓ ✗ ✓ ✓`, the snapshot step included), `1 failed, recovered`, the failed row with the failing statement, its error line and its auto-opened detail (`✗` on `display backgroundcolor white`, the export note); the second run's row shows `… measure rgyr $sel` next to `→ 20.8431`; no line mixes kinds (S2). Row text depends on the dev Mac's fonts: a different machine may ellipsize differently, which is why these goldens are only compared where Tk loads. The model name, the durations (`0.5 s`, `5 s`) and `Thought for N s` come from the recorded fixture's `request.started.model`, `duration_ms` and timestamps, so a fixture recorded differently may change only those values.

- [ ] **Step 7: Run the lint and the suite**

Run: `python -m pytest tests/test_tk_tool_rows.py tests/test_tk_transcript.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+78 passed`, 0 failed, under 60 s.

- [ ] **Step 8: Commit**

```bash
git add plugin/transcript.tcl tests/tcl/test_tool_rows.tcl tests/test_tk_tool_rows.py \
        tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt
git commit -F - <<'MSG'
feat(plugin): tool rows, step detail, run headers, chips, collapse (P08-T06)

Each tool call is one display line that refits to the width (rationale,
then +N lines, then a binary-search ellipsis that keeps 12 characters,
then the duration). Failures pin their error line under the row and open
a detail that highlights the failing statement using the executor's own
splitter. Run headers carry step chips and the run summary; finished runs
collapse when the next one starts, keeping failed rows visible. The row
mark is rowend:$k because Tk reads a digit-leading mark as an index.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 7: P08-T07 — Snapshot cards, 30-photo cap, viewer

**Files:**
- Create: `plugin/viewer.tcl`
- Modify: `plugin/transcript.tcl` (append the snapshot section)
- Create: `tests/tcl/test_snapshot_cards.tcl`
- Create: `tests/test_tk_snapshot_cards.py`
- Modify (regenerated in Step 7): `tests/fixtures/tk/03_conversation.txt`

**Interfaces:**
- Consumes: the `snapshot` op (Task 1): `{snapshot k thumb_path path w h saved_path sent_to_model ?renderer?}`; Task 6's `ROW`, `RUN`, `rowend:$k`, `_row_run_wl`, `_first_line`; Task 5's `_embed`, `_action`, `_call`, `_menu_sequences`, `S(photos)`; theme (Task 4): `c`, `paint`, `fit_middle`
- Produces:
  - `::vmdai::viewer::open path -> window or ""; ::vmdai::viewer::close`
  - `::vmdai::transcript::loaded_image_count -> int`
  - (also) `::vmdai::viewer::open_external path`, `reveal path`, `save_copy path`, `opt(map)` (1; tests set 0: the viewer window is created but never mapped), `opt(external)` (a command prefix that receives `open|reveal path` instead of the desktop), the viewer window `.vmd_ai_viewer`
  - (also) `::vmdai::transcript::autocrop img ?step tol pad? -> {x0 y0 x1 y1}`, `thumb_photo src ?maxw maxh? -> photo`, `show_image call_key -> 0|1`, `card_texts call_key -> list`, `opt(max_photos)` (30), the array `SNAP` (`SNAP($k,card)` is the card canvas, `SNAP($k,mode)` is `image`, `unloaded` or `text`), tag `snap:$k`, and the default targets `_do_view_image`, `_do_open_file`, `_do_reveal_file`, `_do_save_png` (which also serve Task 6's `Open full output · Reveal`)

How the card works (Part B V4 "Snapshot card", §2c "Thumbnails", V7; console's `snap::autocrop/thumb/card`):
- The card is a canvas embedded on its own line (`thumb`, `snap:$k`) after the row's error line or preview and detail. `_snap_load` loads the runtime's `thumb_path`; when that file is missing it loads the full image instead ("copy -subsample" fallback). `thumb_photo` crops the uniform border (`autocrop`: every 12th pixel, a sum of RGB differences above 36 from the colour at (2,2) counts as content, the box padded by 26) and subsamples by one integer factor so the result fits 256×192; the image is never cropped to fill the box.
- Beside the image (below it when the transcript is narrower than 440 px): the purpose, `1280 × 1547 · TachyonInternal`, the file name (mono, `fit_middle`), `Saved to fig1.png` when `saved_path` is set, `Open · Reveal · Save PNG…`, and `✓ Sent to the model` or, in warn, `✗ Not sent — <model> is text-only` (the model from the run's `run.open`).
- A file Tk cannot decode (Tk 8.5 has no PNG photo; a corrupt file) gives a text card: `name · W × H` read from the IHDR with `binary scan`, then `Open · Reveal`; no photo is created.
- Clicking the image runs action `view_image` (default: `::vmdai::viewer::open`); right-click gives Open, Reveal, Save PNG…, Copy path. "Show image" is internal and calls `show_image` directly.
- At most `opt(max_photos)` (30) photos stay loaded: loading one more frees the oldest (`image delete`) and redraws its card as a `Show image` placeholder of the same size; clicking it reloads that card, which frees the next oldest. `clear` destroys the cards and frees every photo (Clear and New Chat, §2c).
- When a run collapses (Task 6), its newest card stays visible: each new card takes `wl:$run` off itself and puts it on the run's earlier cards.
- `viewer.tcl` shows one image at a time in `.vmd_ai_viewer`, whole, subsampled by an integer factor to fit 90% of the screen; Esc and the close button call `close`, which frees the photo. Inside `::vmdai::viewer` the procs `open` and `close` shadow Tcl's own; the module never needs the Tcl ones, and every caller uses the qualified names.

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_snapshot_cards.tcl`:

```tcl
# Snapshot cards, the 30-photo cap and the viewer (P08-T07).
# Run by tests/test_tk_snapshot_cards.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor theme viewmodel transcript viewer
::vmdai::theme::init light
set ::vmdai::transcript::opt(animate) 0
set ::vmdai::viewer::opt(map) 0
wm geometry . 560x780
set t [::vmdai::transcript::create .tx]
pack .tx -fill both -expand 1
update

set ::actions {}
set ::vmdai::transcript::on_action [list apply {{args} {lappend ::actions $args}}]
set SNAP [file join $env(VMDAI_REPO) docs design round1 assets snap_1hck.png]
set TMP [file join $env(HOME) cards]
file mkdir $TMP

proc fresh {{geometry 560x780}} {
    set ::actions {}
    ::vmdai::transcript::clear
    wm geometry . $geometry
    update
    ::vmdai::transcript::relayout
}
proc ops {args} { ::vmdai::transcript::apply_ops $args }
# A snapshot row plus its card, as the view-model emits them.
proc snap_row {run k thumb path {sent 1} {saved ""}} {
    ops [list tool.open $k capture_vmd_snapshot "check the cartoon" tcl model ""] \
        [list run.chip $run $k running] \
        [list tool.close $k ok "0.9 s" [dict create label "" error "" inline "" preview {} output "" \
            output_path "" total "" applied "" failed_index "" failed_text "" late 0] $thumb] \
        [list run.chip $run $k ok] \
        [list snapshot $k $thumb $path 1280 1547 $saved $sent TachyonInternal]
}
proc card {k} { return $::vmdai::transcript::SNAP($k,card) }
proc texts {k} { return [::vmdai::transcript::card_texts $k] }
# Write a photo made by script to a PNG under TMP.
proc png {name w h script} {
    set img [image create photo -width $w -height $h]
    $img put black -to 0 0 $w $h
    uplevel 1 [list set img $img]
    uplevel 1 $script
    set path [file join $::TMP $name]
    $img write $path -format png
    image delete $img
    return $path
}
proc mode {k} { return $::vmdai::transcript::SNAP($k,mode) }

test tk85-1 {an undecodable PNG gives a text card (name, W × H from the IHDR, Open, Reveal) and loads no photo} -body {
    fresh
    set bad [file join $TMP broken.png]
    set fh [open $bad wb]
    puts -nonewline $fh "\x89PNG\r\n\x1a\n[binary format I 13]IHDR[binary format II 1280 1547]\x08\x02\x00\x00\x00JUNKJUNK"
    close $fh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $bad $bad
    set tx [texts k1]
    list [mode k1] [::vmdai::transcript::loaded_image_count] [lindex $tx 0] \
        [expr {"Open" in $tx}] [expr {"Reveal" in $tx}] [expr {"Save PNG…" in $tx}] \
        [llength [[card k1] find withtag img]]
} -result {text 0 {broken.png · 1280 × 1547} 1 1 0 0}

test thumb_fallback {a missing thumbnail falls back to subsampling the full image} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 [file join $TMP missing_thumb.png] $SNAP
    set p $::vmdai::transcript::SNAP(k1,photo)
    list [mode k1] [::vmdai::transcript::loaded_image_count] \
        [expr {[image width $p] <= 256 && [image height $p] <= 192}] [expr {[image width $p] > 64}]
} -result {image 1 1 1}

test autocrop-1 {the uniform border is cropped (grid 12, tolerance 36, pad 26) before scaling} -body {
    set path [png framed.png 400 300 {$img put white -to 150 120 250 180}]
    set src [image create photo -file $path]
    set box [::vmdai::transcript::autocrop $src]
    set th [::vmdai::transcript::thumb_photo $src 256 192]
    set r [list $box [image width $th] [image height $th]]
    image delete $src $th
    set r
} -result {{130 94 266 194} 136 100}

test scale-fit {a wide image is scaled by one integer factor to fit 256×192, never cropped to fill} -body {
    set path [png wide.png 1100 300 {$img put white -to 10 10 1090 290}]
    set src [image create photo -file $path]
    set th [::vmdai::transcript::thumb_photo $src 256 192]
    set r [list [image width $th] [image height $th]]
    image delete $src $th
    set r
} -result {220 60}

test not-sent {the card says whether the model saw the snapshot} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP 1 /w/fig1.png
    snap_row r1 k2 $SNAP $SNAP 0
    set a [texts k1]
    set b [texts k2]
    list [expr {"✓ Sent to the model" in $a}] [expr {"Saved to fig1.png" in $a}] \
        [expr {"1280 × 1547 · TachyonInternal" in $a}] [expr {"check the cartoon" in $a}] \
        [expr {"✗ Not sent — qwen3.8:27b is text-only" in $b}] [expr {"✓ Sent to the model" in $b}]
} -result {1 1 1 1 1 0}

test max-30 {at most 30 photos stay loaded; older cards show "Show image", which reloads} -body {
    fresh
    set small [png small.png 64 48 {$img put white -to 8 8 56 40}]
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    for {set i 1} {$i <= 32} {incr i} { snap_row r1 s$i $small $small }
    set r [list [::vmdai::transcript::loaded_image_count] [mode s1] [mode s2] [mode s3] \
        [expr {"Show image" in [texts s1]}]]
    uplevel #0 [[card s1] bind lk_show <ButtonRelease-1>]
    lappend r [mode s1] [mode s3] [::vmdai::transcript::loaded_image_count]
    set before [llength [image names]]
    ::vmdai::transcript::clear
    lappend r [::vmdai::transcript::loaded_image_count] [expr {$before - [llength [image names]]}]
} -result {30 unloaded unloaded image 1 image unloaded 30 0 30}

test card-actions {image click opens the viewer; Open, Reveal, Save PNG… and the menu name the file} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    set c [card k1]
    foreach tag {img lk_open lk_reveal lk_save} { uplevel #0 [$c bind $tag <ButtonRelease-1>] }
    set labels {}
    foreach {label cmd} [::vmdai::transcript::menu_items [lindex [$t tag ranges snap:k1] 0]] {
        lappend labels $label
    }
    list [lsort -unique [lmap a $::actions {lindex $a 1}]] [lmap a $::actions {lindex $a 0}] $labels
} -result [list [list $SNAP] {view_image open_file reveal_file save_png} {Open Reveal {Save PNG…} {Copy path}}]

test last-card-visible {a collapsed run keeps its newest snapshot card visible} -body {
    fresh
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    snap_row r1 k2 $SNAP $SNAP
    ops {run.close r1 complete 2 0 0 3 0 28} {run.open r2 req_2 qwen3.8:27b 1790208010}
    set d [::vmdai::transcript::dump]
    list [$t tag cget wl:r1 -elide] [regexp -all {thumb \| <card>} $d] [lindex [split $d "\n"] 0]
} -result {1 1 {images 2}}

test stack-narrow {below 440 px the caption stacks under the image} -body {
    fresh 380x700
    ops {run.open r1 req_1 qwen3.8:27b 1790208000}
    snap_row r1 k1 $SNAP $SNAP
    set c [card k1]
    lassign [$c bbox img] ix0 iy0 ix1 iy1
    set first [lindex [$c find withtag lk_open] 0]
    lassign [$c bbox $first] lx0 ly0
    list [expr {$ly0 > $iy1}] [expr {[winfo reqwidth $c] <= [winfo width $t]}]
} -result {1 1}

test viewer-1 {the viewer shows the whole image, closes on Esc, and frees its photo} -body {
    set w [::vmdai::viewer::open $SNAP]
    set p $::vmdai::viewer::photo
    set r [list $w [wm state $w] [expr {[image width $p] <= [winfo screenwidth .]}] \
        [bind $w <Escape>] [::vmdai::viewer::open /nonexistent/x.png]]
    set w [::vmdai::viewer::open $SNAP]
    set p $::vmdai::viewer::photo
    uplevel #0 [bind $w <Escape>]
    lappend r [winfo exists $w] [expr {$p in [image names]}]
} -result {.vmd_ai_viewer withdrawn 1 ::vmdai::viewer::close {} 0 0}

cleanupTests
exit
```

`png` writes a synthetic photo to a PNG under the temp `HOME`, so `autocrop-1` and `scale-fit` have exact expected boxes: the white rectangle in `framed.png` is sampled at x 156…240 and y 120…168, which padded by 26 gives `{130 94 266 194}`, a 136×100 crop that already fits; `wide.png` keeps its whole 1100×300 frame and is subsampled by 5 to 220×60. `tk85-1` writes a PNG signature and a valid IHDR followed by junk, which `image create photo` rejects.

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tk_snapshot_cards.py`:

```python
"""Snapshot cards, the 30-photo cap and the full-size viewer (P08-T07)."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_snapshot_cards.tcl"
TESTS = [
    "tk85-1",
    "thumb_fallback",
    "autocrop-1",
    "scale-fit",
    "not-sent",
    "max-30",
    "card-actions",
    "last-card-visible",
    "stack-narrow",
    "viewer-1",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL), env={"TZ": "UTC"})


def test_snapshot_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_tk85_1(result):
    assert_tcltests(result, ["tk85-1", "thumb_fallback"])


def test_max_30_images(result):
    assert_tcltests(result, ["max-30"])


def test_not_sent_to_model_shown(result):
    assert_tcltests(result, ["not-sent"])


def test_autocrop_scale_fit(result):
    assert_tcltests(result, ["autocrop-1", "scale-fit"])


def test_card_actions_layout_and_viewer(result):
    assert_tcltests(result, ["card-actions", "last-card-visible", "stack-narrow", "viewer-1"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_snapshot_cards.py -q 2>&1 | tail -2`
Expected: `6 failed`; the tcltest file stops at `load_plugin … viewer` (there is no `plugin/viewer.tcl`), so no case prints `PASSED`.

- [ ] **Step 4: Write the viewer**

Create `plugin/viewer.tcl`:

```tcl
# viewer.tcl -- ChatVMD full-size snapshot viewer (Part B V4 "Snapshot card").
#
#   ::vmdai::viewer::open path    -> the viewer window, or "" if the image
#                                    cannot be decoded
#   ::vmdai::viewer::close        destroy it and free its photo
#   ::vmdai::viewer::open_external path, reveal path, save_copy path
#
# One viewer at a time: opening another image replaces the first. The image
# is shown whole, subsampled by an integer factor to fit 90% of the screen.
# Esc or the window's close button closes it. Tests set opt(map) 0 so the
# window is created but never mapped, and opt(external) to a command prefix
# that receives {open|reveal} path instead of the desktop.

namespace eval ::vmdai::viewer {
    variable opt
    if {![info exists opt]} { array set opt {map 1 external ""} }
    variable win
    if {![info exists win]} { set win .vmd_ai_viewer }
    variable photo
    if {![info exists photo]} { set photo "" }
}

proc ::vmdai::viewer::open {path} {
    variable opt
    variable win
    variable photo
    close
    if {[catch {image create photo -file $path} src]} { return "" }
    set w [image width $src]
    set h [image height $src]
    set maxw [expr {int([winfo screenwidth .] * 0.9)}]
    set maxh [expr {int([winfo screenheight .] * 0.9)}]
    set f [expr {max(1, int(ceil(max(double($w) / $maxw, double($h) / $maxh))))}]
    if {$f > 1} {
        set photo [image create photo]
        $photo copy $src -subsample $f $f
        image delete $src
    } else {
        set photo $src
    }
    toplevel $win
    wm withdraw $win
    wm title $win "ChatVMD — [file tail $path]"
    canvas $win.c -width [image width $photo] -height [image height $photo] \
        -highlightthickness 0 -borderwidth 0 -background [::vmdai::theme::c surface]
    $win.c create image 0 0 -anchor nw -image $photo
    pack $win.c -fill both -expand 1
    bind $win <Escape> ::vmdai::viewer::close
    wm protocol $win WM_DELETE_WINDOW ::vmdai::viewer::close
    if {$opt(map)} {
        wm deiconify $win
        raise $win
        focus $win.c
    }
    return $win
}

proc ::vmdai::viewer::close {} {
    variable win
    variable photo
    if {[winfo exists $win]} { destroy $win }
    if {$photo ne ""} {
        catch {image delete $photo}
        set photo ""
    }
}

proc ::vmdai::viewer::_desktop {how path} {
    variable opt
    if {$opt(external) ne ""} {
        return [uplevel #0 [list {*}$opt(external) $how $path]]
    }
    if {[tk windowingsystem] eq "aqua"} {
        set cmd [expr {$how eq "reveal" ? [list open -R $path] : [list open $path]}]
    } else {
        set target [expr {$how eq "reveal" ? [file dirname $path] : $path}]
        set cmd [list xdg-open $target]
    }
    if {[catch {exec {*}$cmd &} err]} {
        catch {::vmdai::config::log "viewer: $how $path failed: $err"}
    }
}

proc ::vmdai::viewer::open_external {path} { _desktop open $path }

proc ::vmdai::viewer::reveal {path} { _desktop reveal $path }

# "Save PNG…": copy the snapshot to a file the user picks.
proc ::vmdai::viewer::save_copy {path} {
    set dest [tk_getSaveFile -title "Save PNG" -defaultextension .png \
        -initialfile [file tail $path]]
    if {$dest eq ""} { return "" }
    file copy -force -- $path $dest
    return $dest
}
```

- [ ] **Step 5: Append the snapshot section to the transcript**

Append to the end of `plugin/transcript.tcl`:

```tcl

# ===========================================================================
# Snapshot cards, the 30-photo cap (P08-T07).
#
# Part B V4 "Snapshot card", §2c "Thumbnails", V7. A card is a canvas
# embedded on its own line (thumb, snap:$k) after the row's sections: the
# runtime's thumbnail with its uniform border cropped off (console's
# snap::autocrop: grid 12, tolerance 36, pad 26) and scaled down by an
# integer factor to fit 256×192, never cropped to fill; beside it (below it
# when narrow) the purpose, "W × H · renderer", the file name, "Saved to …",
# "Open · Reveal · Save PNG…" and whether the model saw it. At most
# opt(max_photos) photos stay loaded; older cards show "Show image". A PNG
# that cannot be decoded gives a text card and loads nothing.
# ===========================================================================

namespace eval ::vmdai::transcript {
    variable SNAP
    if {![info exists SNAP]} { array set SNAP {} }
    variable opt
    if {![info exists opt(max_photos)]} { set opt(max_photos) 30 }
}

proc ::vmdai::transcript::loaded_image_count {} {
    variable S
    return [llength $S(photos)]
}

proc ::vmdai::transcript::_tags_snaps {} {
    variable W
    variable SNAP
    $W tag configure thumb -lmargin1 24 -spacing1 6 -spacing3 10
    foreach key [array names SNAP *,card] { _draw_card [lindex [split $key ,] 0] }
}

proc ::vmdai::transcript::_clear_snaps {} {
    variable S
    variable SNAP
    foreach key [array names SNAP *,card] { catch {destroy $SNAP($key)} }
    foreach p $S(photos) { catch {image delete $p} }
    set S(photos) {}
    array unset SNAP
}

proc ::vmdai::transcript::_relayout_snaps {cw narrow} {
    variable SNAP
    foreach key [array names SNAP *,card] { _draw_card [lindex [split $key ,] 0] }
}

# Bounding box {x0 y0 x1 y1} of what differs from the corner colour, sampled
# on a grid and padded (console prototype, snap::autocrop).
proc ::vmdai::transcript::autocrop {img {step 12} {tol 36} {pad 26}} {
    set w [image width $img]
    set h [image height $img]
    lassign [$img get [expr {min(2, $w - 1)}] [expr {min(2, $h - 1)}]] br bg bb
    set x0 $w
    set y0 $h
    set x1 -1
    set y1 -1
    for {set y 0} {$y < $h} {incr y $step} {
        for {set x 0} {$x < $w} {incr x $step} {
            lassign [$img get $x $y] r g b
            if {abs($r - $br) + abs($g - $bg) + abs($b - $bb) > $tol} {
                if {$x < $x0} { set x0 $x }
                if {$x > $x1} { set x1 $x }
                if {$y < $y0} { set y0 $y }
                if {$y > $y1} { set y1 $y }
            }
        }
    }
    if {$x1 < 0} { return [list 0 0 $w $h] }
    return [list [expr {max(0, $x0 - $pad)}] [expr {max(0, $y0 - $pad)}] \
                 [expr {min($w, $x1 + $pad)}] [expr {min($h, $y1 + $pad)}]]
}

# A new photo: src autocropped, then subsampled by one integer factor so
# that it fits maxw×maxh with its aspect ratio kept.
proc ::vmdai::transcript::thumb_photo {src {maxw 256} {maxh 192}} {
    lassign [autocrop $src] x0 y0 x1 y1
    set cw [expr {$x1 - $x0}]
    set ch [expr {$y1 - $y0}]
    set f [expr {max(1, int(ceil(max(double($cw) / $maxw, double($ch) / $maxh))))}]
    set dst [image create photo]
    $dst copy $src -from $x0 $y0 $x1 $y1 -subsample $f $f
    return $dst
}

# Width and height from a PNG's IHDR (the text card; Tk 8.5 cannot decode PNG).
proc ::vmdai::transcript::_png_size {path} {
    set w ?
    set h ?
    catch {
        set fh [open $path rb]
        set head [read $fh 24]
        close $fh
        if {[string range $head 12 15] eq "IHDR"} {
            binary scan [string range $head 16 23] II w h
        }
    }
    return [list $w $h]
}

proc ::vmdai::transcript::op_snapshot {k thumb path w h saved_path sent_to_model {renderer TachyonInternal}} {
    variable W
    variable T
    variable S
    variable ROW
    variable RUN
    variable SNAP
    if {![info exists ROW($k,name)] || [info exists SNAP($k,card)]} { return }
    set run $ROW($k,run)
    set model ""
    if {$run ne "" && [info exists RUN($run,model)]} { set model $RUN($run,model) }
    array set SNAP [list $k,thumb $thumb $k,path $path $k,w $w $k,h $h $k,saved $saved_path \
        $k,sent $sent_to_model $k,renderer $renderer $k,run $run $k,model $model \
        $k,purpose [_first_line $ROW($k,cmd)] $k,photo "" $k,mode text $k,pw 0 $k,ph 0]
    set c $T.snap[incr S(link)]
    canvas $c -highlightthickness 0 -borderwidth 0 -width 10 -height 10
    ::vmdai::theme::paint $c -background surface
    _embed $c
    foreach seq [_menu_sequences] {
        bind $c $seq [list ::vmdai::transcript::_card_menu $k %X %Y]
    }
    set SNAP($k,card) $c
    _snap_load $k
    _draw_card $k
    set at rowend:$k
    foreach section {err prev detail} {
        set r [$W tag ranges $section:$k]
        if {[llength $r]} { set at [lindex $r end] }
    }
    set at [$W index $at]
    set tags [concat thumb snap:$k [_row_run_wl $k]]
    $W window create $at -window $c -align top
    $W insert "$at +1c" "\n" $tags
    foreach tag $tags { $W tag add $tag $at }
    # The run's newest card stays visible when the run collapses.
    if {$run ne "" && [info exists RUN($run,snaps)]} {
        foreach old $RUN($run,snaps) {
            set r [$W tag ranges snap:$old]
            if {[llength $r]} { $W tag add wl:$run {*}$r }
        }
        lappend RUN($run,snaps) $k
        set r [$W tag ranges snap:$k]
        $W tag remove wl:$run {*}$r
    }
}

# Load the card's photo: the thumbnail, or the full image subsampled when
# the thumbnail is missing (§2c fallbacks). An undecodable file leaves the
# card in text mode. Loading may free the oldest photo (the 30-photo cap).
proc ::vmdai::transcript::_snap_load {k} {
    variable S
    variable SNAP
    set file ""
    if {$SNAP($k,thumb) ne "" && [file readable $SNAP($k,thumb)]} {
        set file $SNAP($k,thumb)
    } elseif {[file readable $SNAP($k,path)]} {
        set file $SNAP($k,path)
    }
    if {$file eq "" || [catch {image create photo -file $file} src]} {
        set SNAP($k,mode) text
        return 0
    }
    set photo [thumb_photo $src 256 192]
    image delete $src
    array set SNAP [list $k,photo $photo $k,mode image \
        $k,pw [image width $photo] $k,ph [image height $photo]]
    lappend S(photos) $photo
    lappend S(photo_keys) $k
    _enforce_cap
    return 1
}

proc ::vmdai::transcript::_enforce_cap {} {
    variable S
    variable SNAP
    variable opt
    while {[llength $S(photos)] > $opt(max_photos)} {
        set p [lindex $S(photos) 0]
        set old [lindex $S(photo_keys) 0]
        set S(photos) [lrange $S(photos) 1 end]
        set S(photo_keys) [lrange $S(photo_keys) 1 end]
        catch {image delete $p}
        set SNAP($old,photo) ""
        set SNAP($old,mode) unloaded
        _draw_card $old
    }
}

# "Show image": reload a freed card; the oldest loaded one is freed instead.
proc ::vmdai::transcript::show_image {k} {
    variable SNAP
    if {![info exists SNAP($k,mode)] || $SNAP($k,mode) ne "unloaded"} { return 0 }
    _snap_load $k
    _draw_card $k
    return 1
}

proc ::vmdai::transcript::_narrow {} {
    variable T
    return [expr {[winfo width $T] > 1 && [winfo width $T] < 440}]
}

proc ::vmdai::transcript::_card_link {c x y text tag cmd} {
    set id [$c create text $x $y -anchor nw -text $text -font ChatMeta \
        -fill [::vmdai::theme::c accent] -tags [list link $tag]]
    $c bind $tag <ButtonRelease-1> $cmd
    return [lindex [$c bbox $id] 2]
}

proc ::vmdai::transcript::_draw_card {k} {
    variable SNAP
    set c $SNAP($k,card)
    if {![winfo exists $c]} { return }
    set C ::vmdai::theme::c
    $c delete all
    $c configure -background [$C surface]
    set path $SNAP($k,path)
    set mode $SNAP($k,mode)
    set iw 0
    set ih 0
    if {$mode eq "image"} {
        set iw [expr {$SNAP($k,pw) + 2}]
        set ih [expr {$SNAP($k,ph) + 2}]
        $c create rectangle 0 0 [expr {$iw - 1}] [expr {$ih - 1}] -outline [$C hairline] \
            -fill [$C surface] -tags img
        $c create image 1 1 -anchor nw -image $SNAP($k,photo) -tags img
        $c bind img <ButtonRelease-1> [list ::vmdai::transcript::_action view_image $path]
        $c bind img <Enter> [list $c configure -cursor hand2]
        $c bind img <Leave> [list $c configure -cursor arrow]
    } elseif {$mode eq "unloaded"} {
        set iw [expr {$SNAP($k,pw) + 2}]
        set ih [expr {$SNAP($k,ph) + 2}]
        $c create rectangle 0 0 [expr {$iw - 1}] [expr {$ih - 1}] -outline [$C hairline] \
            -fill [$C code_bg]
        set tw [font measure ChatMeta "Show image"]
        _card_link $c [expr {($iw - $tw) / 2}] [expr {$ih / 2 - 8}] "Show image" lk_show \
            [list ::vmdai::transcript::show_image $k]
    }
    set cw [_content_width]
    if {$mode eq "text" || [_narrow]} {
        set x 0
        set y [expr {$ih ? $ih + 8 : 0}]
    } else {
        set x [expr {$iw + 14}]
        set y 0
    }
    set capw [expr {max(120, $cw - 24 - $x)}]
    if {$mode ne "text" && ![_narrow] && $capw > 300} { set capw 300 }
    if {$mode eq "text"} {
        lassign [_png_size $path] pw ph
        set id [$c create text $x $y -anchor nw -width $capw -font ChatBody -fill [$C text] \
            -text "[file tail $path] · $pw × $ph"]
    } else {
        set id [$c create text $x $y -anchor nw -width $capw -font ChatBody -fill [$C text] \
            -text $SNAP($k,purpose)]
        set y [expr {[lindex [$c bbox $id] 3] + 2}]
        set id [$c create text $x $y -anchor nw -font ChatMeta -fill [$C muted] \
            -text "$SNAP($k,w) × $SNAP($k,h) · $SNAP($k,renderer)"]
        set y [expr {[lindex [$c bbox $id] 3] + 2}]
        set id [$c create text $x $y -anchor nw -font ChatCodeSmall -fill [$C text2] \
            -text [::vmdai::theme::fit_middle ChatCodeSmall $capw [file tail $path]]]
        if {$SNAP($k,saved) ne ""} {
            set y [expr {[lindex [$c bbox $id] 3] + 2}]
            set id [$c create text $x $y -anchor nw -font ChatMeta -fill [$C muted] \
                -text "Saved to [file tail $SNAP($k,saved)]"]
        }
    }
    set y [expr {[lindex [$c bbox $id] 3] + 6}]
    set lx [_card_link $c $x $y "Open" lk_open [list ::vmdai::transcript::_action open_file $path]]
    $c create text [expr {$lx + 4}] $y -anchor nw -text "·" -font ChatMeta -fill [$C muted]
    set lx [_card_link $c [expr {$lx + 14}] $y "Reveal" lk_reveal \
        [list ::vmdai::transcript::_action reveal_file $path]]
    if {$mode ne "text"} {
        $c create text [expr {$lx + 4}] $y -anchor nw -text "·" -font ChatMeta -fill [$C muted]
        _card_link $c [expr {$lx + 14}] $y "Save PNG…" lk_save \
            [list ::vmdai::transcript::_action save_png $path]
    }
    set y [expr {[lindex [$c bbox all] 3] + 4}]
    if {$SNAP($k,sent)} {
        $c create text $x $y -anchor nw -font ChatMeta -fill [$C ok] -text "✓ Sent to the model"
    } else {
        set who [expr {$SNAP($k,model) eq "" ? "this model" : $SNAP($k,model)}]
        $c create text $x $y -anchor nw -width $capw -font ChatMeta -fill [$C warn] \
            -text "✗ Not sent — $who is text-only"
    }
    $c bind link <Enter> [list $c configure -cursor hand2]
    $c bind link <Leave> [list $c configure -cursor arrow]
    lassign [$c bbox all] bx0 by0 bx1 by1
    $c configure -width [expr {$bx1 + 2}] -height [expr {max($ih, $by1) + 2}]
}

proc ::vmdai::transcript::card_texts {k} {
    variable SNAP
    set out {}
    set c $SNAP($k,card)
    foreach id [$c find all] {
        if {[$c type $id] eq "text"} { lappend out [$c itemcget $id -text] }
    }
    return $out
}

proc ::vmdai::transcript::_snap_menu {k} {
    variable SNAP
    set p $SNAP($k,path)
    return [list Open [list ::vmdai::transcript::_action open_file $p] \
        Reveal [list ::vmdai::transcript::_action reveal_file $p] \
        "Save PNG…" [list ::vmdai::transcript::_action save_png $p] \
        "Copy path" [list ::vmdai::transcript::_clipboard $p]]
}

proc ::vmdai::transcript::_card_menu {k rx ry} {
    variable T
    set m $T.menu
    catch {destroy $m}
    menu $m -tearoff 0
    foreach {label cmd} [_snap_menu $k] { $m add command -label $label -command $cmd }
    tk_popup $m $rx $ry
}

# Default targets of the file actions (the viewer module, P08-T07).
proc ::vmdai::transcript::_do_view_image {path} { _call ::vmdai::viewer::open $path }
proc ::vmdai::transcript::_do_open_file {path} { _call ::vmdai::viewer::open_external $path }
proc ::vmdai::transcript::_do_reveal_file {path} { _call ::vmdai::viewer::reveal $path }
proc ::vmdai::transcript::_do_save_png {path} { _call ::vmdai::viewer::save_copy $path }
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_tk_snapshot_cards.py tests/test_tk_tool_rows.py tests/test_tk_transcript.py -q 2>&1 | tail -3`
Expected: `1 failed, 30 passed`; the failure is `test_golden_03_conversation` with `golden mismatch:`: the diff changes `images 0` to `images 1` and adds one line, `thumb | <card>`, right after the first run's failed-row detail, renumbering the lines below it. `test_golden_reasoning_answer` still matches (that scenario has no snapshot).

- [ ] **Step 7: Regenerate the 03_conversation golden and review it**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py -q -k golden 2>&1 | tail -1 && git diff --stat tests/fixtures/tk && cat tests/fixtures/tk/03_conversation.txt`
Expected: `2 passed, 8 deselected`; only `03_conversation.txt` changed, and it now reads:

```text
images 1
001 role rolemeta | You⇥12:00 AM
002 user | load 1hck and show it as a cartoon
003 chip chip_err chip_ok runhdr runmodel runsum | ChatVMD  qwen3.8:27b⇥✓ ✗ ✓ ✓  1 failed, recovered · 5 s
006 chev cmd extra g_err meta row | ✗⇥display backgroundcolor white  +1 lines  Make the background white.⇥0.5 s  ▾
007 errline | display: invalid option "backgroundcolor"
008 detail dfirst dnote | Make the background white.
009 dcode detail dgut |   color Display Background white
010 dcode detail dfail dgut dgutx | ✗ display backgroundcolor white
011 detail dnote | Statement 1 ran and is kept in Save .tcl; the rest is commented out
012 detail dlast dlink link | Copy
016 thumb | <card>
017 rule | <rule>
018 prose | Loaded **1hck** as a cartoon on a white background.
019 footer link | Copy Tcl · Save .tcl…
020 role rolemeta | You⇥12:00 AM
021 user | what is its radius of gyration?
022 chip chip_ok runhdr runmodel runsum | ChatVMD  qwen3.8:27b⇥✓  1 step · 5 s
023 chev cmd extra g_ok meta row | ✓⇥… measure rgyr $sel  +1 lines  Radius of gyration of the protein.⇥→ 20.8431  0.5 s  ▸
024 rule | <rule>
025 prose | The radius of gyration is 20.84 Å.
026 footer link | Copy Tcl · Save .tcl…
```

The first run is collapsed, so its snapshot row is hidden but its newest (only) card is still shown, and exactly one photo is loaded (the thumbnail of `snap_1hck.png`, which the fixture names with `@REPO@`, replaced by the repository path during the replay).

- [ ] **Step 8: Run the lint and the suite**

Run: `python -m pytest tests/test_tk_snapshot_cards.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass (the lint now also scans `plugin/viewer.tcl`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+84 passed`, 0 failed, under 60 s.

- [ ] **Step 9: Commit**

```bash
git add plugin/viewer.tcl plugin/transcript.tcl tests/tcl/test_snapshot_cards.tcl \
        tests/test_tk_snapshot_cards.py tests/fixtures/tk/03_conversation.txt
git commit -F - <<'MSG'
feat(plugin): snapshot cards with a 30-photo cap, and the snapshot viewer (P08-T07)

A snapshot becomes a canvas card under its row: the runtime's thumbnail
with its uniform border cropped off and scaled by an integer factor to
fit 256x192, the size and renderer, the file, Open/Reveal/Save PNG and
whether the model saw it. A missing thumbnail falls back to the full
image; an undecodable one gives a text card read from the PNG header.
Only 30 photos stay loaded; older cards reload on "Show image". Clicking
the image opens a full-size viewer that Esc closes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 8: P08-T08 — composer.tcl

**Files:**
- Create: `plugin/composer.tcl`
- Create: `tests/tcl/test_composer.tcl`
- Create: `tests/test_tk_composer.py`

**Interfaces:**
- Consumes: theme (Task 4): `::vmdai::theme::c`, `paint`, `on_repaint`, `rrect`, the fonts `ChatBody` and `ChatMetaBold`, the tokens `chrome surface text muted sel accent field_bd focus_ring stop_bg stop_fg`; `tests/tcl/plugin_loader.tcl` (Task 5); `helpers.tk.run_tk_test` (P06-T10); `helpers.panel_goldens.assert_tcltests` (Task 1); `::vmdai::statusbar::flash text ms` (Task 9; called only when it exists, and stubbed in this task's test)
- Produces:
  - `::vmdai::composer::create path ?-onsend cmd? ?-onstop cmd? -> path; get_text; set_text s; set_mode idle|busy|stopping|nomodel|disabled; push_history s; focus`
  - (also) the input is `path.field.t`, a `Text` (namespace variable `T`); Send is the `TButton` `path.act.send`; Stop is the canvas pill `path.act.stop` (`-takefocus 1`, text item tagged `label`); the placeholder is the label `path.field.t.ph`; `placeholder_for mode -> string`
  - (also) `-onsend` gets the draft as its one argument and `-onstop` gets none; the caller clears the draft and sets the mode (plan 09's `on_send` and `on_stop` do both). The bindings call `_on_return` (Return, KP_Enter and Send), `_newline` (Shift-Return) and `_stop_clicked` (the Stop pill, and Esc in the input). `push_history` keeps the newest 50 prompts in the namespace list `history`, which nothing else in this file reads, so P09-T03 can replace both.

How the composer works (Part B V4 "Composer", V5):
- A borderless `text` sits on a rounded canvas plate (`field_bd` outline, `surface` fill) as a canvas window item. While it has focus, the outline turns `accent` and a 3 px `focus_ring` ring is drawn around it. It grows from 1 to 6 display lines: `count -update -displaylines` counts wrapped lines too, and the canvas is always the text's requested height plus 16.
- The placeholder is a label placed over the input's top-left corner, shown only while the draft is empty, so it never becomes part of the text. There is one text per mode: idle and disabled "Ask VMD to load, show or measure something…", busy and stopping "Reply once this run finishes — or press Esc to stop", nomodel "Set up a model to start — ⌘," (`Ctrl+,` off aqua).
- Send and Stop share one grid cell (`path.act`), and only one of them is managed at a time. Send is a `ttk::button -default active`. It is enabled only in `idle` with a non-blank draft; otherwise it is disabled and drops to `-default normal`, because a disabled blue default button is hard to read. In `busy` the cell holds the Stop pill (`stop_bg`, a drawn square, "Stop"); in `stopping` the pill reads "Stopping…" on `muted` and ignores clicks.
- Typing is always allowed: no mode touches `-state` or the draft, so the draft survives a disconnect (`disabled`) and Stop. Return sends only in `idle` with a non-blank draft. While a request runs it sends nothing and calls `::vmdai::statusbar::flash "Press Esc to stop" 2000` (V5). Shift-Return inserts a newline.
- There are no timers. Inside the namespace, `focus` is this module's proc, so the module calls Tk's as `::focus`.

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_composer.tcl`:

```tcl
# composer.tcl (P08-T08): Send and Stop in one cell, growth, placeholders,
# Return while busy, the draft. Adopts cards' composer-1.
# Run by tests/test_tk_composer.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme composer
::vmdai::theme::init light
wm geometry . 560x240

# The status bar is plan 08's T09 module; here a stub records flashes.
namespace eval ::vmdai::statusbar {}
proc ::vmdai::statusbar::flash {text ms} { lappend ::flashes [list $text $ms] }

set ::sent {}
set ::stops 0
set ::flashes {}
set C [::vmdai::composer::create .cb \
    -onsend [list apply {{s} {lappend ::sent $s}}] \
    -onstop [list apply {{} {incr ::stops; ::vmdai::composer::set_mode stopping}}]]
pack .cb -side bottom -fill x
update
set T $::vmdai::composer::T
set MOD [expr {[tk windowingsystem] eq "aqua" ? "⌘" : "Ctrl+"}]

proc fresh {{m idle}} {
    set ::sent {}
    set ::stops 0
    set ::flashes {}
    ::vmdai::composer::set_text ""
    ::vmdai::composer::set_mode $m
    update
}
proc managed {w} { return [expr {[winfo manager $w] ne ""}] }
proc ph_shown {} { return [expr {[winfo manager $::T.ph] eq "place"}] }

test composer-1 {Send becomes Stop while running; the placeholder explains queueing; Stop then reads Stopping…} -body {
    fresh idle
    set r [list [managed $C.act.send] [managed $C.act.stop]]
    ::vmdai::composer::set_mode busy
    update
    lappend r [managed $C.act.send] [managed $C.act.stop] \
        [string match "Reply once this run finishes*" [$T.ph cget -text]] [$C.act.stop cget -takefocus]
    ::vmdai::composer::_stop_clicked
    ::vmdai::composer::_stop_clicked
    lappend r $::stops [$C.act.stop itemcget label -text]
    ::vmdai::composer::set_mode idle
    update
    lappend r [managed $C.act.send] [managed $C.act.stop]
} -result {1 0 0 1 1 1 1 Stopping… 1 0}

test test_grows_1_to_6 {the input grows from 1 to 6 display lines, counting wrapped lines, and shrinks back} -body {
    fresh
    set r {}
    foreach n {1 2 3 6 9} {
        set lines {}
        for {set i 1} {$i <= $n} {incr i} { lappend lines "line $i" }
        ::vmdai::composer::set_text [join $lines "\n"]
        update
        lappend r [$T cget -height]
    }
    ::vmdai::composer::set_text [string repeat "wrap me " 40]
    update
    lappend r [expr {[$T cget -height] > 1}]
    ::vmdai::composer::set_text ""
    update
    lappend r [$T cget -height] [expr {[winfo reqheight $C.field] == [winfo reqheight $T] + 16}]
} -result {1 2 3 6 6 1 1 1}

test test_return_busy_noop {Return while busy sends nothing, keeps the draft and flashes "Press Esc to stop"; idle Return sends; blank never sends} -body {
    fresh busy
    ::vmdai::composer::set_text "follow-up"
    ::vmdai::composer::_on_return
    set r [list $::sent [::vmdai::composer::get_text] $::flashes]
    ::vmdai::composer::set_mode idle
    ::vmdai::composer::_newline
    lappend r [expr {[::vmdai::composer::get_text] eq "follow-up\n"}]
    ::vmdai::composer::_on_return
    lappend r [llength $::sent] [expr {[lindex $::sent 0] eq "follow-up\n"}]
    ::vmdai::composer::set_text "   "
    ::vmdai::composer::_on_return
    lappend r [llength $::sent] [$C.act.send instate disabled] [$C.act.send cget -default]
    ::vmdai::composer::set_text "go"
    lappend r [$C.act.send instate disabled] [$C.act.send cget -default]
} -result {{} follow-up {{{Press Esc to stop} 2000}} 1 1 1 1 1 normal 0 active}

test test_draft_survives {the draft survives busy, stopping, a disconnect and nomodel; the input stays editable; Send is off unless idle} -body {
    fresh
    ::vmdai::composer::set_text "half-typed prompt"
    set drafts {}
    set states {}
    set send {}
    foreach m {busy stopping disabled nomodel idle} {
        ::vmdai::composer::set_mode $m
        update
        lappend drafts [::vmdai::composer::get_text]
        lappend states [$T cget -state]
        if {[managed $C.act.send]} { lappend send $m [$C.act.send instate disabled] }
    }
    for {set i 0} {$i < 60} {incr i} { ::vmdai::composer::push_history "p$i" }
    list [lsort -unique $drafts] [lsort -unique $states] $send [::vmdai::composer::get_text] \
        [llength $::vmdai::composer::history] [lindex $::vmdai::composer::history 0]
} -result {{{half-typed prompt}} normal {disabled 1 nomodel 1 idle 0} {half-typed prompt} 50 p10}

test test_placeholders {one placeholder per mode, shown only while the draft is empty, never part of the text} -body {
    fresh
    set r {}
    foreach m {idle busy stopping nomodel disabled} {
        ::vmdai::composer::set_mode $m
        lappend r [$T.ph cget -text]
    }
    ::vmdai::composer::set_mode idle
    update
    lappend r [ph_shown] [::vmdai::composer::get_text]
    ::vmdai::composer::set_text "x"
    lappend r [ph_shown]
    ::vmdai::composer::set_text ""
    lappend r [ph_shown]
} -result [list "Ask VMD to load, show or measure something…" \
    "Reply once this run finishes — or press Esc to stop" \
    "Reply once this run finishes — or press Esc to stop" \
    "Set up a model to start — $MOD," \
    "Ask VMD to load, show or measure something…" 1 {} 0 1]

cleanupTests
exit
```

`composer-1` is cards' test of the same name, which checked that Send becomes Stop while a request runs and that the placeholder explains why a reply must wait. It adds the pill's `Stopping…` state and checks that a second click reaches `-onstop` only once. The `-onstop` callback here does what plan 09's `on_stop` does: it switches the mode to `stopping`.

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tk_composer.py`:

```python
"""composer.tcl (P08-T08): input, placeholders, Send/Stop in one cell, the draft."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_composer.tcl"
TESTS = [
    "composer-1",
    "test_grows_1_to_6",
    "test_return_busy_noop",
    "test_draft_survives",
    "test_placeholders",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL))


def test_composer_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_composer_1(result):
    assert_tcltests(result, ["composer-1"])


def test_grows_1_to_6(result):
    assert_tcltests(result, ["test_grows_1_to_6"])


def test_return_busy_noop(result):
    assert_tcltests(result, ["test_return_busy_noop"])


def test_draft_survives(result):
    assert_tcltests(result, ["test_draft_survives"])


def test_placeholders(result):
    assert_tcltests(result, ["test_placeholders"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_composer.py -q 2>&1 | tail -2`
Expected: `6 failed`. The tcltest file stops at `load_plugin … composer` with `couldn't read file ".../plugin/composer.tcl": no such file or directory`, so no case prints `PASSED`. (Without a GUI session: `6 skipped`; run from the dev Mac's GUI session.)

- [ ] **Step 4: Write the composer**

Create `plugin/composer.tcl`:

```tcl
# composer.tcl -- ChatVMD composer: the prompt input, its placeholder and
# the Send/Stop cell (Part B V4 "Composer", V5).
#
#   ::vmdai::composer::create path ?-onsend cmd? ?-onstop cmd?
#   ::vmdai::composer::get_text          -> the draft, exactly as typed
#   ::vmdai::composer::set_text s        replace the draft
#   ::vmdai::composer::set_mode m        idle | busy | stopping | nomodel | disabled
#   ::vmdai::composer::push_history s    remember a sent prompt (newest 50)
#   ::vmdai::composer::focus             focus the input
#
# The input is a borderless text on a rounded canvas plate with an accent
# focus ring, and grows from 1 to 6 display lines. Send (a ttk::button) and
# Stop (a canvas pill) share one grid cell. Typing is always allowed, so the
# draft survives disconnects and Stop. Return sends only when idle and the
# draft is not blank; while a request runs it flashes "Press Esc to stop" in
# the status bar. -onsend gets the draft as one argument and -onstop none;
# the caller clears the draft and sets the mode (plan 09's panel does both).
# Inside this namespace `focus` is this module's proc; Tk's is ::focus.

namespace eval ::vmdai::composer {
    variable F
    if {![info exists F]} { set F "" }
    variable T
    if {![info exists T]} { set T "" }
    variable mode
    if {![info exists mode]} { set mode idle }
    variable onsend
    if {![info exists onsend]} { set onsend "" }
    variable onstop
    if {![info exists onstop]} { set onstop "" }
    variable history
    if {![info exists history]} { set history {} }
    variable S
    if {![info exists S]} { array set S {lines 1 focused 0} }
}

proc ::vmdai::composer::create {path args} {
    variable F
    variable T
    variable onsend
    variable onstop
    variable mode
    variable S
    set onsend ""
    set onstop ""
    foreach {opt value} $args {
        switch -- $opt {
            -onsend { set onsend $value }
            -onstop { set onstop $value }
            default { error "unknown option \"$opt\": must be -onsend or -onstop" }
        }
    }
    if {[winfo exists $path]} { destroy $path }
    array set S {lines 1 focused 0}
    set mode idle
    set F $path
    frame $path -borderwidth 0 -highlightthickness 0
    canvas $path.field -height 34 -width 200 -borderwidth 0 -highlightthickness 0
    set T $path.field.t
    text $T -height 1 -width 10 -wrap word -borderwidth 0 -highlightthickness 0 \
        -font ChatBody -undo 1 -padx 0 -pady 0 -spacing2 3
    label $T.ph -font ChatBody -anchor w -borderwidth 0 -padx 0 -pady 0 -cursor xterm
    $path.field create window 12 8 -anchor nw -window $T -tags txt
    frame $path.act -borderwidth 0 -highlightthickness 0
    ttk::button $path.act.send -text Send -default active -command ::vmdai::composer::_on_return
    canvas $path.act.stop -height 26 -width 80 -borderwidth 0 -highlightthickness 0 \
        -takefocus 1 -cursor hand2
    grid $path.act.send -row 0 -column 0 -sticky se
    grid $path.act.stop -row 0 -column 0 -sticky se
    grid remove $path.act.stop
    grid $path.field -row 0 -column 0 -sticky ew -padx {12 0} -pady 8
    grid $path.act -row 0 -column 1 -sticky se -padx {10 12} -pady {8 12}
    grid columnconfigure $path 0 -weight 1
    ::vmdai::theme::paint $path -background chrome
    ::vmdai::theme::paint $path.field -background chrome
    ::vmdai::theme::paint $path.act -background chrome
    ::vmdai::theme::paint $path.act.stop -background chrome -highlightcolor focus_ring
    ::vmdai::theme::paint $T -background surface -foreground text -insertbackground text \
        -selectbackground sel
    ::vmdai::theme::paint $T.ph -background surface -foreground muted
    ::vmdai::theme::on_repaint ::vmdai::composer::_redraw
    bind $path.field <Configure> ::vmdai::composer::_draw_plate
    bind $T <<Modified>> ::vmdai::composer::_changed
    bind $T <FocusIn> {::vmdai::composer::_focus_changed 1}
    bind $T <FocusOut> {::vmdai::composer::_focus_changed 0}
    bind $T <Return> {::vmdai::composer::_on_return; break}
    bind $T <KP_Enter> {::vmdai::composer::_on_return; break}
    bind $T <Shift-Return> {::vmdai::composer::_newline; break}
    bind $T <Escape> ::vmdai::composer::_stop_clicked
    bind $T.ph <Button-1> [list ::focus $T]
    foreach seq {<ButtonRelease-1> <space> <Return> <KP_Enter>} {
        bind $path.act.stop $seq ::vmdai::composer::_stop_clicked
    }
    _changed
    _sync
    return $path
}

proc ::vmdai::composer::_live {} {
    variable T
    return [expr {$T ne "" && [winfo exists $T]}]
}

proc ::vmdai::composer::get_text {} {
    variable T
    if {![_live]} { return "" }
    return [$T get 1.0 "end -1c"]
}

proc ::vmdai::composer::set_text {s} {
    variable T
    if {![_live]} { return }
    $T delete 1.0 end
    $T insert 1.0 $s
    $T mark set insert "end -1c"
    $T edit reset
    _changed
}

proc ::vmdai::composer::focus {} {
    variable T
    if {[_live]} { ::focus $T }
}

# Kept for Up/Down recall (plan 09 replaces this proc with its recall list).
proc ::vmdai::composer::push_history {s} {
    variable history
    set s [string trim $s]
    if {$s eq ""} { return }
    lappend history $s
    if {[llength $history] > 50} { set history [lrange $history end-49 end] }
}

proc ::vmdai::composer::placeholder_for {m} {
    switch -- $m {
        busy - stopping { return "Reply once this run finishes — or press Esc to stop" }
        nomodel {
            set key [expr {[tk windowingsystem] eq "aqua" ? "⌘," : "Ctrl+,"}]
            return "Set up a model to start — $key"
        }
    }
    return "Ask VMD to load, show or measure something…"
}

proc ::vmdai::composer::set_mode {m} {
    variable mode
    if {$m ni {idle busy stopping nomodel disabled}} {
        error "bad mode \"$m\": must be idle, busy, stopping, nomodel or disabled"
    }
    set mode $m
    _sync
}

# Called on every edit: grow or shrink (1-6 display lines), placeholder, Send.
proc ::vmdai::composer::_changed {} {
    variable F
    variable T
    variable S
    if {![_live]} { return }
    $T edit modified 0
    set n 0
    catch {set n [$T count -update -displaylines 1.0 "end -1c"]}
    if {![string is integer -strict $n]} { set n 0 }
    set n [expr {$n + 1}]
    if {$n > 6} { set n 6 }
    if {$n != [$T cget -height]} {
        $T configure -height $n
    }
    set S(lines) $n
    $F.field configure -height [expr {[winfo reqheight $T] + 16}]
    _sync
}

proc ::vmdai::composer::_newline {} {
    variable T
    if {![_live]} { return }
    $T insert insert "\n"
    $T see insert
    _changed
}

proc ::vmdai::composer::_sync {} {
    variable F
    variable T
    variable mode
    if {![_live]} { return }
    $T.ph configure -text [placeholder_for $mode]
    if {[get_text] eq ""} {
        place $T.ph -x 0 -y 0
    } else {
        place forget $T.ph
    }
    if {$mode in {busy stopping}} {
        grid remove $F.act.send
        grid $F.act.stop
        _draw_stop
        return
    }
    grid remove $F.act.stop
    grid $F.act.send
    if {$mode eq "idle" && [string trim [get_text]] ne ""} {
        $F.act.send state !disabled
        $F.act.send configure -default active
    } else {
        $F.act.send state disabled
        $F.act.send configure -default normal
    }
}

proc ::vmdai::composer::_focus_changed {on} {
    variable S
    set S(focused) $on
    _draw_plate
}

proc ::vmdai::composer::_redraw {} {
    if {![_live]} { return }
    _draw_plate
    _draw_stop
}

# The rounded field: accent outline and a focus ring while focused.
proc ::vmdai::composer::_draw_plate {} {
    variable F
    variable S
    if {![_live]} { return }
    set c $F.field
    set w [winfo width $c]
    set h [winfo height $c]
    if {$w < 30 || $h < 20} { return }
    $c delete plate
    if {$S(focused)} {
        ::vmdai::theme::rrect $c 0.5 0.5 [expr {$w - 0.5}] [expr {$h - 0.5}] 11 -fill "" \
            -outline [::vmdai::theme::c focus_ring] -width 3 -tags plate
    }
    set edge [::vmdai::theme::c [expr {$S(focused) ? "accent" : "field_bd"}]]
    ::vmdai::theme::rrect $c 2 2 [expr {$w - 2}] [expr {$h - 2}] 9 \
        -fill [::vmdai::theme::c surface] -outline $edge -width 1 -tags plate
    $c lower plate
    $c coords txt 12 8
    $c itemconfigure txt -width [expr {$w - 24}] -height [expr {$h - 16}]
}

# The Stop pill: stop_bg, a drawn square and "Stop"; "Stopping…" once clicked.
proc ::vmdai::composer::_draw_stop {} {
    variable F
    variable mode
    if {![_live]} { return }
    set c $F.act.stop
    set label [expr {$mode eq "stopping" ? "Stopping…" : "Stop"}]
    set tw [font measure ChatMetaBold $label]
    set w [expr {$tw + 40}]
    set h 26
    $c configure -width $w -height $h
    $c delete all
    set fill [::vmdai::theme::c [expr {$mode eq "stopping" ? "muted" : "stop_bg"}]]
    set fg [::vmdai::theme::c stop_fg]
    ::vmdai::theme::rrect $c 1 1 [expr {$w - 1}] [expr {$h - 1}] 12 -fill $fill -outline "" -tags pill
    $c create rectangle 13 9 21 17 -fill $fg -outline "" -tags square
    $c create text 28 [expr {$h / 2}] -anchor w -text $label -font ChatMetaBold -fill $fg -tags label
    $c configure -cursor [expr {$mode eq "stopping" ? "arrow" : "hand2"}]
}

proc ::vmdai::composer::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

# Return, KP_Enter and the Send button.
proc ::vmdai::composer::_on_return {} {
    variable mode
    variable onsend
    switch -- $mode {
        idle {
            set draft [get_text]
            if {[string trim $draft] eq "" || $onsend eq ""} { return }
            uplevel #0 [list {*}$onsend $draft]
        }
        busy - stopping {
            _call ::vmdai::statusbar::flash "Press Esc to stop" 2000
        }
    }
}

# The Stop pill (click, Space, Return) and Esc in the input.
proc ::vmdai::composer::_stop_clicked {} {
    variable mode
    variable onstop
    if {$mode ne "busy" || $onstop eq ""} { return }
    uplevel #0 $onstop
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_tk_composer.py -q 2>&1 | tail -1`
Expected: `6 passed`.

- [ ] **Step 6: Run the lint and the suite**

Run: `python -m pytest tests/test_tk_composer.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass (the lint now also scans `plugin/composer.tcl`).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+90 passed`, 0 failed, under 60 s.

- [ ] **Step 7: Commit**

```bash
git add plugin/composer.tcl tests/tcl/test_composer.tcl tests/test_tk_composer.py
git commit -F - <<'MSG'
feat(plugin): composer with one Send/Stop cell, growth and placeholders (P08-T08)

A borderless text on a rounded plate with an accent focus ring grows from
1 to 6 display lines. The placeholder is an overlay per mode and never
part of the draft. Send and the Stop pill share one grid cell; Send is
enabled only when idle with a non-blank draft. Return while a request
runs sends nothing and flashes "Press Esc to stop". No mode touches the
draft, so it survives disconnects and Stop.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 9: P08-T09 — statusbar.tcl and banner.tcl

**Files:**
- Create: `plugin/statusbar.tcl`
- Create: `plugin/banner.tcl`
- Create: `tests/tcl/test_statusbar_banner.tcl`
- Create: `tests/test_tk_statusbar_banner.py`

**Interfaces:**
- Consumes: `::vmdai::vm::status_text stateVar now` (Task 3); theme (Task 4): `c`, `paint`, `on_repaint`, `rrect`, `fit`, the fonts `ChatMeta ChatMetaBold ChatBodyBold ChatCodeSmall`, the tokens `chrome text muted faint hairline accent dot_ok dot_warn dot_off warn warn_bg warn_bd warn_fg focus_ring`; the composer (Task 8, used by `offline-1`); `::vmdai::sched::after`, `cancel`, `pending` (P06-T02); `::vmdai::config::log_path` (P06-T02); `::vmdai::runtime::state`, `info`, `failure_reason`, `pipe_tail ?n?` (P06-T05), `backoff_ms attempt`, `retry_now` (P06-T06), `stop`, `ensure` (P06-T05). The banner reads each runtime fact under `catch` and does without it when it is missing. The test stubs these facts; the panel feeds `on_runtime_state` from `runtime::subscribe` (P09).
- Produces:
  - `::vmdai::statusbar::create path ?-onaction cmd? -> path; update dict; text -> {left right}; flash text ms`
  - `::vmdai::banner::create path ?-onaction cmd? -> path; show kind detail; hide; on_runtime_state old new detail; kind -> unreachable|didnt_start|too_old|""`
  - (also) status bar: `update` merges `connection provider model host folder runs busy activity t0` plus the optional `retry_in` (whole seconds to the next reconnect attempt) and ignores other keys. `_fit avail -> list` gives the segments dropped at a width; `_render` redraws; `_now` is the clock the timer reads (tests replace it); `_unflash`; the trust menu `path.trust.m` with its variable `trust_mode` (`auto`). Actions `open_settings`, `choose_folder` and `about_trust` go to `-onaction` when it is set, else to `::vmdai::panel::open_settings`, `::vmdai::panel::choose_folder` and a message box.
  - (also) banner: the pills are canvases `path.in.btns.<action>` with the text item tagged `label`. Actions `retry_now`, `retry`, `open_log`, `choose_python` and `restart` go to `-onaction` when it is set, else to `::vmdai::runtime::retry_now` (both retries), `::vmdai::panel::open_log`, `::vmdai::panel::open_settings panel`, and `::vmdai::runtime::stop` followed by `::vmdai::runtime::ensure`. Also `toggle_details`, `_tick` (the countdown step), `_relayout width`.

How the status bar works (Part B V4 "Status bar", V6; console's `ui::status_fit`):
- The left segment is a dot and one line, and a click opens Settings. The dot is `dot_ok` when the runtime is ready and a model is set, `faint` when no model is set, `dot_warn` while launching, connecting or reconnecting, and `dot_off` when down or stopped. The line depends on the state:
  - ready and idle: `Ollama · qwen3.8:27b · 127.0.0.1:11435`, which shows host:port and never the word "tunnel"; with no model set, `Ollama · no model · …`;
  - launching or connecting: `Starting the AI runtime…`;
  - reconnecting: `Runtime offline · reconnecting`, or `Runtime offline · retry in N s` when `retry_in` is given;
  - down: `Runtime offline`;
  - stopped: `Runtime stopped`.
- While a request runs (`busy` 1 and ready), the dot becomes a spinner. The line is `vm::status_text` of the phase (`activity`) and its `t0`, for example `Step 4 · running VMD command · 00:12`, or `Retrying 2/5 in 8 s` when `t0` is empty. The right segment is then `Esc to stop`. A 1 s timer, which goes through `sched`, advances the timer and the spinner, and it is cancelled as soon as the bar is idle again. `flash` replaces the left line for `ms`, for example "Press Esc to stop" for 2 s.
- The idle right segment reads `Auto-run Tcl ▾ │ ~/proj/cdk2 · 12 runs`. `$HOME` is shown as `~`, and both `$HOME` and its normalized path are tried, because on macOS `pwd` returns `/private/var/…` for a temp HOME under `/var`. The trust label posts a menu: `Auto-run` (selected), `Ask before running` (disabled), and `About Tcl trust…`. The folder label chooses another folder.
- The fit follows V6. `_fit` tries six levels against the bar's width less 28 px of padding: drop nothing; then host; then the run count; then the folder; then the provider; then shorten the Auto-run label to `Auto-run ▾`, which is never dropped. The left line is then cut with `theme::fit … 12`. Before the bar has been laid out (width 1), nothing is dropped; plan 09's pre-flight reads `text` in that state.

How the banner works (Part B V4 "Banner", §5):
- There is one frame, `path`, on `warn_bg`, with a `warn_bd` hairline at its bottom. The panel grids it in slot 2 and then runs `grid remove`. `show` rebuilds the content and runs `grid $path`, which restores the slot; `hide` runs `grid remove` again. Showing a second kind replaces the first, so there is only ever one banner.
- The content is a warning triangle, a bold title, a detail line, and then pill buttons. The first pill is filled `warn_fg`; the others are outlined in `warn_bd`. Below 440 px the pills move under the text.

  | kind | title | detail | pills |
  |---|---|---|---|
  | `unreachable` | Runtime not reachable | `127.0.0.1:8765 is not answering. Retrying in N s.` while reconnecting; otherwise the runtime's detail | Retry now · Open log |
  | `didnt_start` | Runtime didn't start | the runtime's detail (the last line it printed), then `Show details`: the last 12 pipe lines and `Log: <path>` in mono | Retry · Choose Python… · Open log |
  | `too_old` | This runtime is too old (protocol N) | owned: restart it; attached: restart `scripts/run_runtime.sh` on host:port, because ChatVMD never restarts a runtime it did not start | owned: Restart runtime; attached: none |

- `on_runtime_state old new detail` works as follows:
  - `reconnecting` shows `unreachable`;
  - `down` shows the kind from `runtime::failure_reason`, where anything other than `didnt_start` or `too_old` is `unreachable`;
  - `launching` and `connecting` keep a banner that is already shown and change its detail to "Starting the AI runtime…";
  - `ready` and `stopped` hide it.
- The runtime does not expose when it will probe next, so the countdown follows the runtime's own schedule, `runtime::backoff_ms attempt` (0.5, 1, 2, 4, then 8 s). It counts one second per `_tick` through `sched`. Retry now restarts it from the first attempt. The countdown runs only while the runtime state is `reconnecting`, and `hide` cancels it.
- Nothing in either module mentions a tunnel. The status bar and banner show only host:port (Part B V1 "Required fixes").

Tk does not deliver `<Configure>` to the children of a withdrawn root (verified while planning: the bar stayed at its 900 px fit after `wm geometry . 380x300; update`). The tests therefore call `_render` and `_relayout` directly, as Task 5's tests call `relayout`. In the mapped panel, the `<Configure>` bindings do this.

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_statusbar_banner.tcl`:

```tcl
# statusbar.tcl and banner.tcl (P08-T09). Adopts cards' offline-1.
# Run by tests/test_tk_statusbar_banner.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme viewmodel composer statusbar banner
::vmdai::theme::init light

# Plan 06's runtime and config, reduced to the facts the banner reads.
namespace eval ::vmdai::runtime {}
namespace eval ::vmdai::config {}
array set ::RT {state ready reason "" owned 1 protocol 2}
set ::RT(tail) {}
for {set i 1} {$i <= 20} {incr i} { lappend ::RT(tail) "pipe line $i" }
proc ::vmdai::runtime::state {} { return $::RT(state) }
proc ::vmdai::runtime::failure_reason {} { return $::RT(reason) }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 8765 pid 4242 version 0.9 \
        protocol $::RT(protocol) launch_token t owned $::RT(owned)]
}
proc ::vmdai::runtime::pipe_tail {{n 12}} { return [lrange $::RT(tail) end-[expr {$n - 1}] end] }
proc ::vmdai::runtime::backoff_ms {attempt} {
    if {$attempt >= 5} { return 8000 }
    return [expr {500 << ($attempt - 1)}]
}
proc ::vmdai::config::log_path {} { return /Users/me/.vmdai/logs/plugin.log }

set ::NOW 1790208000
proc ::vmdai::statusbar::_now {} { return $::NOW }
set ::actions {}
proc record {args} { lappend ::actions $args }

wm geometry . 900x300
::vmdai::banner::create .ban -onaction record
::vmdai::composer::create .cb
::vmdai::statusbar::create .sb -onaction record
grid .ban -row 0 -column 0 -sticky ew
grid remove .ban
grid .cb -row 1 -column 0 -sticky ew
grid .sb -row 2 -column 0 -sticky ew
grid columnconfigure . 0 -weight 1
update

proc sb {args} { ::vmdai::statusbar::update [dict create {*}$args] }
proc left {} { return [lindex [::vmdai::statusbar::text] 0] }
proc dot {} {
    set fill [.sb.dot itemcget dot -fill]
    foreach tok {dot_ok dot_warn dot_off faint} {
        if {$fill eq [::vmdai::theme::c $tok]} { return $tok }
    }
    return ?
}
proc fresh {} {
    set ::actions {}
    array set ::RT {state ready reason "" owned 1 protocol 2}
    ::vmdai::banner::hide
    ::vmdai::statusbar::_unflash
    sb connection ready provider Ollama model qwen3.8:27b host 127.0.0.1:11435 \
        folder [file join $::env(HOME) proj cdk2] runs 12 busy 0 activity "" t0 "" retry_in ""
    update
    ::vmdai::statusbar::_render
}
proc buttons {} {
    set out {}
    foreach b [winfo children .ban.in.btns] { lappend out [$b itemcget label -text] }
    return $out
}
proc click_all {} {
    foreach b [winfo children .ban.in.btns] { uplevel #0 [bind $b <ButtonRelease-1>] }
}

test status_texts {idle connection, the phase and its timer while busy, retries, flash, offline states} -body {
    fresh
    set r [list [::vmdai::statusbar::text] [dot]]
    sb model ""
    lappend r [left] [dot]
    sb model qwen3.8:27b busy 1 activity "Step 4 · running VMD command" t0 [expr {$::NOW - 12}]
    lappend r [::vmdai::statusbar::text]
    sb activity Thinking t0 [expr {$::NOW - 5}]
    lappend r [left]
    sb activity "Loading qwen3.8:27b" t0 [expr {$::NOW - 21}]
    lappend r [left]
    sb activity "Retrying 2/5 in 8 s" t0 ""
    lappend r [left]
    ::vmdai::statusbar::flash "Press Esc to stop" 2000
    lappend r [left]
    ::vmdai::statusbar::_unflash
    lappend r [left]
    sb busy 0 activity "" t0 ""
    foreach c {launching reconnecting down stopped} {
        sb connection $c
        lappend r [left] [dot]
    }
    sb connection reconnecting retry_in 8
    lappend r [left] [llength [::vmdai::sched::pending]]
} -result [list {{Ollama · qwen3.8:27b · 127.0.0.1:11435} {Auto-run Tcl ▾ │ ~/proj/cdk2 · 12 runs}} dot_ok \
    {Ollama · no model · 127.0.0.1:11435} faint \
    {{Step 4 · running VMD command · 00:12} {Esc to stop}} {Thinking · 00:05} {Loading qwen3.8:27b · 00:21} \
    {Retrying 2/5 in 8 s} {Press Esc to stop} {Retrying 2/5 in 8 s} \
    {Starting the AI runtime…} dot_warn {Runtime offline · reconnecting} dot_warn \
    {Runtime offline} dot_off {Runtime stopped} dot_off {Runtime offline · retry in 8 s} 0]

test status_clicks {the left segment opens Settings, the folder chooses another, the trust menu shows the mode} -body {
    fresh
    foreach w {.sb.left .sb.folder} { uplevel #0 [bind $w <ButtonRelease-1>] }
    set m .sb.trust.m
    set labels {}
    for {set i 0} {$i <= [$m index end]} {incr i} {
        if {[$m type $i] eq "separator"} { lappend labels - ; continue }
        lappend labels [$m entrycget $i -label] [$m entrycget $i -state]
    }
    $m invoke 3
    list $::actions $labels $::vmdai::statusbar::trust_mode
} -result {{open_settings choose_folder about_trust} {Auto-run normal {Ask before running} disabled - {About Tcl trust…} normal} auto}

test narrow_drop_order {segments drop in the order host, runs, folder, provider, then Auto-run shortens} -body {
    fresh
    set seen {}
    for {set w 900} {$w >= 40} {incr w -5} {
        set d [::vmdai::statusbar::_fit $w]
        if {$d ne [lindex $seen end] || $seen eq ""} { lappend seen $d }
    }
    wm geometry . 380x300
    update
    ::vmdai::statusbar::_render
    set narrow [::vmdai::statusbar::text]
    wm geometry . 900x300
    update
    ::vmdai::statusbar::_render
    list $seen [string match *127.0.0.1* [lindex $narrow 0]] [string match Auto-run* [lindex $narrow 1]] \
        [string match *127.0.0.1* [left]]
} -result {{{} host {host runs} {host runs folder} {host runs folder provider} {host runs folder provider trust}} 0 1 1}

test never_tunnel {no status bar or banner text says "tunnel"; ready shows host:port} -body {
    fresh
    set texts {}
    foreach c {stopped launching connecting ready reconnecting down} {
        foreach busy {0 1} {
            sb connection $c busy $busy activity "Thinking" t0 $::NOW retry_in 4
            lappend texts [::vmdai::statusbar::text]
        }
    }
    sb busy 0
    foreach {kind owned} {unreachable 1 didnt_start 1 too_old 1 too_old 0} {
        set ::RT(owned) $owned
        set ::RT(state) [expr {$kind eq "unreachable" ? "reconnecting" : "down"}]
        ::vmdai::banner::show $kind ""
        lappend texts [.ban.in.title cget -text] [.ban.in.detail cget -text] [buttons]
    }
    ::vmdai::banner::hide
    list [regexp -nocase {tunnel} $texts] [llength [lsearch -all $texts *127.0.0.1:11435*]]
} -result {0 1}

test offline-1 {offline shows exactly one banner and disables Send with the draft kept; ready hides it} -body {
    fresh
    ::vmdai::composer::set_text "draft"
    set ::RT(state) reconnecting
    ::vmdai::banner::on_runtime_state ready reconnecting "connection refused"
    ::vmdai::banner::on_runtime_state ready reconnecting "connection refused"
    sb connection reconnecting
    ::vmdai::composer::set_mode disabled
    set r [list [winfo manager .ban] [winfo children .ban] [.ban.in.title cget -text] [left] \
        [.cb.act.send instate disabled] [::vmdai::composer::get_text]]
    array set ::RT {state down reason didnt_start}
    ::vmdai::banner::on_runtime_state reconnecting down "ModuleNotFoundError: No module named 'x'"
    lappend r [::vmdai::banner::kind] [llength [winfo children .ban]]
    set ::RT(state) ready
    ::vmdai::banner::on_runtime_state down ready ""
    sb connection ready
    ::vmdai::composer::set_mode idle
    lappend r [winfo manager .ban] [::vmdai::banner::kind] [.cb.act.send instate disabled] \
        [::vmdai::composer::get_text] [llength [::vmdai::sched::pending]]
} -result {grid {.ban.line .ban.in} {Runtime not reachable} {Runtime offline · reconnecting} 1 draft didnt_start 2 {} {} 0 draft 0}

test banner_kinds_actions {each kind has its title, detail and actions; the countdown follows the backoff; details and narrow layout} -body {
    fresh
    set r {}
    set ::RT(state) reconnecting
    ::vmdai::banner::show unreachable ""
    lappend r [.ban.in.detail cget -text]
    ::vmdai::banner::_tick
    lappend r [.ban.in.detail cget -text]
    ::vmdai::banner::_tick
    ::vmdai::banner::_tick
    lappend r [.ban.in.detail cget -text]
    lappend r [buttons]
    click_all
    lappend r [.ban.in.detail cget -text]
    set ::RT(state) down
    set ::RT(reason) didnt_start
    ::vmdai::banner::show didnt_start "ModuleNotFoundError: No module named 'x'"
    lappend r [.ban.in.title cget -text] [.ban.in.detail cget -text] [buttons] [winfo manager .ban.in.tail]
    ::vmdai::banner::toggle_details
    set tail [split [.ban.in.tail cget -text] "\n"]
    lappend r [.ban.in.more cget -text] [lindex $tail 0] [lindex $tail 11] [lindex $tail end]
    click_all
    set ::RT(protocol) 1
    ::vmdai::banner::show too_old "This runtime is too old (protocol 1)."
    lappend r [.ban.in.title cget -text] [buttons]
    click_all
    set ::RT(owned) 0
    ::vmdai::banner::show too_old "This runtime is too old (protocol 1)."
    lappend r [buttons] [string match *scripts/run_runtime.sh* [.ban.in.detail cget -text]]
    set ::RT(owned) 1
    set ::RT(state) reconnecting
    ::vmdai::banner::show unreachable ""
    ::vmdai::banner::_relayout 380
    lappend r [dict get [grid info .ban.in.btns] -row]
    ::vmdai::banner::_relayout 600
    lappend r [dict get [grid info .ban.in.btns] -row] $::actions
    ::vmdai::banner::hide
    lappend r [llength [::vmdai::sched::pending]]
} -result {{127.0.0.1:8765 is not answering. Retrying in 1 s.} {127.0.0.1:8765 is not answering. Retrying now…} {127.0.0.1:8765 is not answering. Retrying now…} {{Retry now} {Open log}} {127.0.0.1:8765 is not answering. Retrying in 1 s.} {Runtime didn't start} {ModuleNotFoundError: No module named 'x'} {Retry {Choose Python…} {Open log}} {} {Hide details} {pipe line 9} {pipe line 20} {Log: /Users/me/.vmdai/logs/plugin.log} {This runtime is too old (protocol 1)} {{Restart runtime}} {} 1 4 0 {retry_now open_log retry choose_python open_log restart} 0}

cleanupTests
exit
```

`offline-1` is cards' test of the same name ("offline shows exactly one banner and disables send"). Here the composer's `disabled` mode stands in for the panel, which puts the composer in `disabled` whenever the runtime is not ready (P09 `_composer_mode`). `never_tunnel` covers every connection state, busy or idle, and every banner kind.

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tk_statusbar_banner.py`:

```python
"""statusbar.tcl and banner.tcl (P08-T09): status texts, narrow drops, the
one connection banner and its actions."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_statusbar_banner.tcl"
TESTS = [
    "status_texts",
    "status_clicks",
    "narrow_drop_order",
    "never_tunnel",
    "offline-1",
    "banner_kinds_actions",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL))


def test_statusbar_banner_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_status_texts(result):
    assert_tcltests(result, ["status_texts", "status_clicks"])


def test_offline_1(result):
    assert_tcltests(result, ["offline-1"])


def test_narrow_drop_order(result):
    assert_tcltests(result, ["narrow_drop_order"])


def test_never_tunnel(result):
    assert_tcltests(result, ["never_tunnel"])


def test_banner_kinds_actions(result):
    assert_tcltests(result, ["banner_kinds_actions"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_statusbar_banner.py -q 2>&1 | tail -2`
Expected: `6 failed`. The tcltest file stops at `load_plugin … statusbar` with `couldn't read file ".../plugin/statusbar.tcl": no such file or directory`. (Without a GUI session: `6 skipped`.)

- [ ] **Step 4: Write the status bar**

Create `plugin/statusbar.tcl`:

```tcl
# statusbar.tcl -- ChatVMD status bar (Part B V4 "Status bar", V6).
#
#   ::vmdai::statusbar::create path ?-onaction cmd?
#   ::vmdai::statusbar::update dict    merge any of: connection provider model
#                                      host folder runs busy activity t0 retry_in
#   ::vmdai::statusbar::text           -> {left right}, as displayed
#   ::vmdai::statusbar::flash text ms  show text on the left for ms
#
# Left: a dot and the connection ("Ollama · qwen3.8:27b · 127.0.0.1:11435":
# host:port, never the word "tunnel"), or, while a request runs, the phase
# and its timer ("Step 4 · running VMD command · 00:12"). Clicking it opens
# Settings. Right: "Auto-run Tcl ▾" (a menu with the trust mode) and the
# folder with its run count (clicking the folder chooses another); while a
# request runs, "Esc to stop". When the bar is too narrow, segments drop in
# the order host, run count, folder, provider; then "Auto-run Tcl ▾" shortens
# to "Auto-run ▾", which is never dropped. Inside this namespace `update`
# and `text` are this module's procs (Tk's text widget command is ::text).

namespace eval ::vmdai::statusbar {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable trust_mode
    if {![info exists trust_mode]} { set trust_mode auto }
    variable D
    if {![info exists D]} { array set D {} }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::statusbar::_reset {} {
    variable D
    variable S
    array unset D
    array set D {connection stopped provider "" model "" host "" folder "" runs ""
                 busy 0 activity "" t0 "" retry_in ""}
    array unset S
    array set S {flash "" flash_id "" tick "" spin 0}
}

proc ::vmdai::statusbar::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {$P ne "" && [winfo exists $P]} { _cancel_timers }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    canvas $path.dot -width 10 -height 10 -borderwidth 0 -highlightthickness 0
    label $path.left -font ChatMeta -anchor w -borderwidth 0 -padx 0 -cursor hand2
    label $path.trust -font ChatMeta -borderwidth 0 -padx 0 -cursor hand2
    label $path.sep -font ChatMeta -text "│" -borderwidth 0 -padx 6
    label $path.folder -font ChatMeta -borderwidth 0 -padx 0 -cursor hand2
    label $path.hint -font ChatMeta -text "Esc to stop" -borderwidth 0 -padx 0
    menu $path.trust.m -tearoff 0
    $path.trust.m add radiobutton -label "Auto-run" -value auto \
        -variable ::vmdai::statusbar::trust_mode
    $path.trust.m add radiobutton -label "Ask before running" -value ask \
        -variable ::vmdai::statusbar::trust_mode -state disabled
    $path.trust.m add separator
    $path.trust.m add command -label "About Tcl trust…" \
        -command [list ::vmdai::statusbar::_action about_trust]
    grid $path.dot -row 0 -column 0 -padx {14 6} -pady {2 5}
    grid $path.left -row 0 -column 1 -sticky w -pady {2 5}
    grid $path.trust -row 0 -column 3 -sticky e -pady {2 5}
    grid $path.sep -row 0 -column 4 -pady {2 5}
    grid $path.folder -row 0 -column 5 -sticky e -pady {2 5}
    grid $path.hint -row 0 -column 6 -sticky e -padx {0 14} -pady {2 5}
    grid columnconfigure $path 2 -weight 1
    grid columnconfigure $path 1 -weight 0
    foreach w [list $path $path.dot $path.left $path.trust $path.sep $path.folder $path.hint] {
        ::vmdai::theme::paint $w -background chrome
    }
    ::vmdai::theme::paint $path.left -foreground text
    foreach w [list $path.trust $path.folder $path.hint] {
        ::vmdai::theme::paint $w -foreground muted
    }
    ::vmdai::theme::paint $path.sep -foreground faint
    ::vmdai::theme::on_repaint ::vmdai::statusbar::_render
    bind $path.left <ButtonRelease-1> [list ::vmdai::statusbar::_action open_settings]
    bind $path.dot <ButtonRelease-1> [list ::vmdai::statusbar::_action open_settings]
    bind $path.folder <ButtonRelease-1> [list ::vmdai::statusbar::_action choose_folder]
    bind $path.trust <ButtonRelease-1> {::vmdai::statusbar::_post_trust %X %Y}
    bind $path <Configure> ::vmdai::statusbar::_render
    bind $path <Destroy> [list ::vmdai::statusbar::_on_destroy %W]
    _render
    return $path
}

proc ::vmdai::statusbar::_on_destroy {w} {
    variable P
    if {$w eq $P} { _cancel_timers }
}

proc ::vmdai::statusbar::_cancel_timers {} {
    variable S
    foreach key {flash_id tick} {
        if {[info exists S($key)] && $S($key) ne ""} {
            ::vmdai::sched::cancel $S($key)
            set S($key) ""
        }
    }
}

proc ::vmdai::statusbar::update {d} {
    variable D
    foreach key [dict keys $d] {
        if {$key in {connection provider model host folder runs busy activity t0 retry_in}} {
            set D($key) [dict get $d $key]
        }
    }
    set D(busy) [expr {[string is true -strict $D(busy)] ? 1 : 0}]
    _render
}

proc ::vmdai::statusbar::flash {text ms} {
    variable S
    if {$S(flash_id) ne ""} { ::vmdai::sched::cancel $S(flash_id) }
    set S(flash) $text
    set S(flash_id) [::vmdai::sched::after $ms ::vmdai::statusbar::_unflash]
    _render
}

proc ::vmdai::statusbar::_unflash {} {
    variable S
    if {$S(flash_id) ne ""} { ::vmdai::sched::cancel $S(flash_id) }
    set S(flash_id) ""
    set S(flash) ""
    _render
}

proc ::vmdai::statusbar::text {} {
    variable P
    if {$P eq "" || ![winfo exists $P]} { return [list "" ""] }
    set right [$P.trust cget -text]
    if {[winfo manager $P.hint] ne ""} {
        set right [$P.hint cget -text]
    } elseif {[winfo manager $P.folder] ne ""} {
        append right " │ " [$P.folder cget -text]
    }
    return [list [$P.left cget -text] $right]
}

# The clock the timer reads (tests replace it).
proc ::vmdai::statusbar::_now {} {
    return [clock seconds]
}

proc ::vmdai::statusbar::_folder_text {} {
    variable D
    set f $D(folder)
    if {$f eq ""} { return "" }
    set homes {}
    catch {lappend homes $::env(HOME) [file normalize $::env(HOME)]}
    foreach home $homes {
        if {$home ne "" && ($f eq $home || [string first "$home/" $f] == 0)} {
            return "~[string range $f [string length $home] end]"
        }
    }
    return $f
}

proc ::vmdai::statusbar::_runs_text {} {
    variable D
    if {![string is integer -strict $D(runs)]} { return "" }
    return [expr {$D(runs) == 1 ? "1 run" : "$D(runs) runs"}]
}

# Left text for the connection (idle), with the segments in $drop left out.
proc ::vmdai::statusbar::_connection_text {drop} {
    variable D
    switch -- $D(connection) {
        ready {
            set parts {}
            if {"provider" ni $drop && $D(provider) ne ""} { lappend parts $D(provider) }
            lappend parts [expr {$D(model) eq "" ? "no model" : $D(model)}]
            if {"host" ni $drop && $D(host) ne ""} { lappend parts $D(host) }
            return [join $parts " · "]
        }
        launching - connecting { return "Starting the AI runtime…" }
        reconnecting {
            if {[string is integer -strict $D(retry_in)]} {
                return "Runtime offline · retry in $D(retry_in) s"
            }
            return "Runtime offline · reconnecting"
        }
        down {
            if {[string is integer -strict $D(retry_in)]} {
                return "Runtime offline · retry in $D(retry_in) s"
            }
            return "Runtime offline"
        }
    }
    return "Runtime stopped"
}

proc ::vmdai::statusbar::_trust_text {drop} {
    return [expr {"trust" in $drop ? "Auto-run ▾" : "Auto-run Tcl ▾"}]
}

proc ::vmdai::statusbar::_folder_segment {drop} {
    set parts {}
    if {"folder" ni $drop} {
        set f [_folder_text]
        if {$f ne ""} { lappend parts $f }
        if {"runs" ni $drop && [_runs_text] ne ""} { lappend parts [_runs_text] }
    }
    return [join $parts " · "]
}

# The segments left out at a given width (V6): host, runs, folder, provider,
# then the short trust label. avail < 0 means "no limit" (not laid out yet).
proc ::vmdai::statusbar::_fit {avail} {
    set levels {{} {host} {host runs} {host runs folder} {host runs folder provider}
                {host runs folder provider trust}}
    if {$avail < 0} { return {} }
    foreach drop $levels {
        set need [expr {[font measure ChatMeta [_connection_text $drop]] + 16}]
        incr need [font measure ChatMeta [_trust_text $drop]]
        set seg [_folder_segment $drop]
        if {$seg ne ""} { incr need [expr {[font measure ChatMeta "│$seg"] + 12}] }
        if {$need <= $avail} { return $drop }
    }
    return [lindex $levels end]
}

proc ::vmdai::statusbar::_dot_token {} {
    variable D
    switch -- $D(connection) {
        ready { return [expr {$D(model) eq "" ? "faint" : "dot_ok"}] }
        launching - connecting - reconnecting { return dot_warn }
    }
    return dot_off
}

proc ::vmdai::statusbar::_render {} {
    variable P
    variable D
    variable S
    if {$P eq "" || ![winfo exists $P]} { return }
    set w [winfo width $P]
    set avail [expr {$w > 1 ? $w - 28 : -1}]
    set busy [expr {$D(busy) && $D(connection) eq "ready"}]
    set c $P.dot
    $c delete all
    if {$busy} {
        set start [expr {90 - 90 * ($S(spin) % 4)}]
        $c create oval 1 1 9 9 -outline [::vmdai::theme::c hairline] -width 2
        $c create arc 1 1 9 9 -start $start -extent 90 -style arc \
            -outline [::vmdai::theme::c accent] -width 2
    } else {
        $c create oval 1 1 9 9 -outline "" -fill [::vmdai::theme::c [_dot_token]] -tags dot
    }
    if {$busy} {
        set st [dict create busy 1 phase [expr {$D(activity) eq "" ? "Working…" : $D(activity)}] \
            phase_t0 $D(t0)]
        set left [::vmdai::vm::status_text st [_now]]
        grid remove $P.trust $P.sep $P.folder
        grid $P.hint
        _schedule_tick
    } else {
        set drop [_fit [expr {$avail < 0 ? -1 : $avail}]]
        set left [_connection_text $drop]
        $P.trust configure -text [_trust_text $drop]
        set seg [_folder_segment $drop]
        $P.folder configure -text $seg
        grid remove $P.hint
        grid $P.trust
        if {$seg eq ""} { grid remove $P.sep $P.folder } else { grid $P.sep $P.folder }
        if {$S(tick) ne ""} {
            ::vmdai::sched::cancel $S(tick)
            set S(tick) ""
        }
    }
    if {$S(flash) ne ""} { set left $S(flash) }
    if {$avail > 0} {
        if {$busy} {
            set room [expr {$avail - 16 - [winfo reqwidth $P.hint]}]
        } else {
            set room [expr {$avail - 16 - [winfo reqwidth $P.trust]}]
            if {[winfo manager $P.folder] ne ""} {
                incr room [expr {-[winfo reqwidth $P.sep] - [winfo reqwidth $P.folder]}]
            }
        }
        if {$room > 40} { set left [::vmdai::theme::fit ChatMeta $room $left 12] }
    }
    $P.left configure -text $left
}

# While busy, the timer and the spinner advance once a second.
proc ::vmdai::statusbar::_schedule_tick {} {
    variable S
    if {$S(tick) eq ""} {
        set S(tick) [::vmdai::sched::after 1000 ::vmdai::statusbar::_tick]
    }
}

proc ::vmdai::statusbar::_tick {} {
    variable S
    if {$S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    incr S(spin)
    _render
}

proc ::vmdai::statusbar::_post_trust {x y} {
    variable P
    tk_popup $P.trust.m $x $y
}

proc ::vmdai::statusbar::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

# Run an action: the on_action callback when set (tests), else its target.
proc ::vmdai::statusbar::_action {name} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name]]
    }
    switch -- $name {
        open_settings { _call ::vmdai::panel::open_settings }
        choose_folder { _call ::vmdai::panel::choose_folder }
        about_trust   { _about_trust }
    }
}

proc ::vmdai::statusbar::_about_trust {} {
    variable P
    tk_messageBox -parent [winfo toplevel $P] -icon info -title "Tcl trust" \
        -message "Model-written Tcl runs unsandboxed in this VMD session." \
        -detail "ChatVMD runs the model's Tcl automatically, with your permissions. Only load files you trust; asking before running arrives in a later version."
}
```

- [ ] **Step 5: Write the banner**

Create `plugin/banner.tcl`:

```tcl
# banner.tcl -- ChatVMD connection banner (Part B V4 "Banner", §5).
#
#   ::vmdai::banner::create path ?-onaction cmd?
#   ::vmdai::banner::show kind detail  kind: unreachable, didnt_start, too_old
#   ::vmdai::banner::hide
#   ::vmdai::banner::on_runtime_state old new detail   (a runtime::subscribe callback)
#   ::vmdai::banner::kind              -> the kind shown, or ""
#
# One banner at a time in grid slot 2: the panel grids path once and then
# `grid remove`s it; show re-grids it and hide removes it again. The look is
# warn_bg, a warning triangle, a bold title, a detail line (host:port and,
# while reconnecting, a countdown that follows the runtime's backoff), then
# pill buttons, which move under the text below 440 px. Actions go to the
# -onaction callback when set, else: Retry now / Retry -> runtime::retry_now,
# Open log -> panel::open_log, Choose Python… -> panel::open_settings panel,
# Restart runtime -> runtime::stop, then runtime::ensure.

namespace eval ::vmdai::banner {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::banner::_reset {} {
    variable S
    array unset S
    array set S {kind "" detail "" attempt 0 remaining 0 tick "" details 0 narrow 0 lastw 0}
}

proc ::vmdai::banner::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {$P ne "" && [winfo exists $P]} { _stop_countdown }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    frame $path.line -height 1 -borderwidth 0 -highlightthickness 0
    pack $path.line -side bottom -fill x
    ::vmdai::theme::paint $path -background warn_bg
    ::vmdai::theme::paint $path.line -background warn_bd
    ::vmdai::theme::on_repaint ::vmdai::banner::_rebuild
    bind $path <Configure> {::vmdai::banner::_relayout %w}
    bind $path <Destroy> [list ::vmdai::banner::_on_destroy %W]
    return $path
}

proc ::vmdai::banner::_on_destroy {w} {
    variable P
    if {$w eq $P} { _stop_countdown }
}

proc ::vmdai::banner::kind {} {
    variable S
    return $S(kind)
}

# ---- runtime facts (plan 06), each optional ----------------------------------

proc ::vmdai::banner::_rt {what args} {
    set cmd ::vmdai::runtime::$what
    if {[info commands $cmd] eq ""} { return "" }
    if {[catch {uplevel #0 [list $cmd {*}$args]} v]} { return "" }
    return $v
}

proc ::vmdai::banner::_hostport {} {
    set info [_rt info]
    if {[catch {set hp "[dict get $info host]:[dict get $info port]"}] || $hp eq ":"} {
        return "the AI runtime"
    }
    return $hp
}

proc ::vmdai::banner::_backoff_s {attempt} {
    set ms [_rt backoff_ms $attempt]
    if {![string is integer -strict $ms]} {
        set ms [expr {$attempt >= 5 ? 8000 : 500 << ($attempt - 1)}]
    }
    return [expr {int(ceil($ms / 1000.0))}]
}

# ---- content --------------------------------------------------------------------

proc ::vmdai::banner::_title {kind} {
    switch -- $kind {
        unreachable { return "Runtime not reachable" }
        didnt_start { return "Runtime didn't start" }
        too_old {
            set protocol 1
            catch {set protocol [dict get [_rt info] protocol]}
            if {![string is integer -strict $protocol]} { set protocol 1 }
            return "This runtime is too old (protocol $protocol)"
        }
    }
    return $kind
}

proc ::vmdai::banner::_owned {} {
    set owned 1
    catch {set owned [dict get [_rt info] owned]}
    return [expr {[string is true -strict $owned] ? 1 : 0}]
}

# {label action ...} for a kind (§5, Part B V4).
proc ::vmdai::banner::_buttons {kind} {
    switch -- $kind {
        unreachable { return {"Retry now" retry_now "Open log" open_log} }
        didnt_start { return {"Retry" retry "Choose Python…" choose_python "Open log" open_log} }
        too_old {
            if {[_owned]} { return {"Restart runtime" restart} }
            return {}
        }
    }
    return {}
}

proc ::vmdai::banner::_detail_text {} {
    variable S
    set hp [_hostport]
    switch -- $S(kind) {
        unreachable {
            if {$S(attempt) > 0} {
                if {$S(remaining) > 0} {
                    return "$hp is not answering. Retrying in $S(remaining) s."
                }
                return "$hp is not answering. Retrying now…"
            }
            if {$S(detail) ne ""} { return $S(detail) }
            return "Nothing answered on $hp."
        }
        didnt_start {
            if {$S(detail) ne ""} { return $S(detail) }
            return "The AI runtime exited before it was ready."
        }
        too_old {
            if {[_owned]} { return "Restart it to use the runtime that ships with this panel." }
            return "ChatVMD never restarts a runtime it did not start. Restart scripts/run_runtime.sh on $hp with this version, then reopen the panel."
        }
    }
    return $S(detail)
}

proc ::vmdai::banner::show {kind detail} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P]} { return }
    _stop_countdown
    set S(kind) $kind
    set S(detail) $detail
    set S(details) 0
    if {$kind eq "unreachable" && [_rt state] eq "reconnecting"} {
        _start_countdown 1
    }
    _rebuild
    grid $P
}

proc ::vmdai::banner::hide {} {
    variable P
    variable S
    _stop_countdown
    set S(kind) ""
    set S(detail) ""
    if {$P ne "" && [winfo exists $P]} { grid remove $P }
}

# The runtime state machine drives the banner (plan 06's subscribe).
proc ::vmdai::banner::on_runtime_state {old new detail} {
    variable S
    switch -- $new {
        ready - stopped { hide }
        reconnecting { show unreachable $detail }
        launching - connecting {
            if {$S(kind) ne ""} {
                _stop_countdown
                set S(detail) "Starting the AI runtime…"
                _set_detail [_detail_text]
            }
        }
        down {
            set reason [_rt failure_reason]
            if {$reason ni {didnt_start too_old}} { set reason unreachable }
            show $reason $detail
        }
    }
}

proc ::vmdai::banner::_set_detail {text} {
    variable P
    if {[winfo exists $P.in.detail]} { $P.in.detail configure -text $text }
}

proc ::vmdai::banner::_rebuild {} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P] || $S(kind) eq ""} { return }
    catch {destroy $P.in}
    set in [frame $P.in -borderwidth 0 -highlightthickness 0]
    ::vmdai::theme::paint $in -background warn_bg
    canvas $in.icon -width 20 -height 18 -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $in.icon -background warn_bg
    $in.icon create polygon 10 2 18 16 2 16 -fill [::vmdai::theme::c warn] \
        -outline [::vmdai::theme::c warn] -width 1.5 -joinstyle round
    $in.icon create line 10 7 10 11 -fill [::vmdai::theme::c warn_bg] -width 1.6 -capstyle round
    $in.icon create oval 9.1 13 10.9 14.8 -fill [::vmdai::theme::c warn_bg] -outline ""
    label $in.title -text [_title $S(kind)] -font ChatBodyBold -anchor w -borderwidth 0 -padx 0
    label $in.detail -text [_detail_text] -font ChatMeta -anchor w -justify left \
        -borderwidth 0 -padx 0 -wraplength 360
    foreach w [list $in.title $in.detail] {
        ::vmdai::theme::paint $w -background warn_bg -foreground warn_fg
    }
    grid $in.icon -row 0 -column 0 -rowspan 2 -sticky n -padx {0 8} -pady {1 0}
    grid $in.title -row 0 -column 1 -sticky w
    grid $in.detail -row 1 -column 1 -sticky w
    if {$S(kind) eq "didnt_start"} {
        label $in.more -text [expr {$S(details) ? "Hide details" : "Show details"}] \
            -font ChatMeta -cursor hand2 -borderwidth 0 -padx 0
        ::vmdai::theme::paint $in.more -background warn_bg -foreground accent
        bind $in.more <ButtonRelease-1> ::vmdai::banner::toggle_details
        grid $in.more -row 2 -column 1 -sticky w -pady {2 0}
        label $in.tail -text [_tail_text] -font ChatCodeSmall -anchor w -justify left \
            -borderwidth 0 -padx 0
        ::vmdai::theme::paint $in.tail -background warn_bg -foreground warn_fg
        grid $in.tail -row 3 -column 1 -sticky w -pady {4 0}
        if {!$S(details)} { grid remove $in.tail }
    }
    frame $in.btns -borderwidth 0 -highlightthickness 0
    ::vmdai::theme::paint $in.btns -background warn_bg
    set i 0
    foreach {label action} [_buttons $S(kind)] {
        _pill $in.btns.$action $label $action [expr {$i == 0}]
        pack $in.btns.$action -side left -padx {0 6}
        incr i
    }
    grid columnconfigure $in 1 -weight 1
    pack $in -side top -fill x -padx 16 -pady 10
    set S(lastw) 0
    _relayout [winfo width $P]
}

# Buttons beside the text, or under it below 440 px (V6 narrow rules).
proc ::vmdai::banner::_relayout {w} {
    variable P
    variable S
    if {![winfo exists $P.in.btns]} { return }
    if {$w <= 1} { set w 560 }
    set narrow [expr {$w < 440}]
    if {$narrow == $S(narrow) && $S(lastw) != 0} { return }
    set S(narrow) $narrow
    set S(lastw) $w
    grid forget $P.in.btns
    if {$narrow} {
        grid $P.in.btns -row 4 -column 1 -sticky w -pady {8 0}
    } else {
        grid $P.in.btns -row 0 -column 2 -rowspan 2 -sticky e -padx {12 0}
    }
    $P.in.detail configure -wraplength [expr {$narrow ? $w - 70 : max(200, $w - 300)}]
}

# A rounded pill on the tinted surface (native's pill): the first is filled.
proc ::vmdai::banner::_pill {w label action primary} {
    set tw [font measure ChatMetaBold $label]
    set width [expr {$tw + 22}]
    set height 24
    canvas $w -width $width -height $height -borderwidth 0 -highlightthickness 1 \
        -takefocus 1 -cursor hand2
    ::vmdai::theme::paint $w -background warn_bg -highlightbackground warn_bg \
        -highlightcolor focus_ring
    if {$primary} {
        set fill [::vmdai::theme::c warn_fg]
        set fg [::vmdai::theme::c warn_bg]
        set edge $fill
    } else {
        set fill [::vmdai::theme::c warn_bg]
        set fg [::vmdai::theme::c warn_fg]
        set edge [::vmdai::theme::c warn_bd]
    }
    ::vmdai::theme::rrect $w 1 1 [expr {$width - 1}] [expr {$height - 1}] 7 \
        -fill $fill -outline $edge -width 1
    $w create text [expr {$width / 2.0}] [expr {$height / 2.0}] -text $label \
        -font ChatMetaBold -fill $fg -tags label
    foreach seq {<ButtonRelease-1> <space> <Return>} {
        bind $w $seq [list ::vmdai::banner::_action $action]
    }
    return $w
}

proc ::vmdai::banner::_tail_text {} {
    set lines [_rt pipe_tail 12]
    set log ""
    if {[info commands ::vmdai::config::log_path] ne ""} {
        catch {set log [::vmdai::config::log_path]}
    }
    set out [join $lines "\n"]
    if {$out eq ""} { set out "(the runtime printed nothing)" }
    if {$log ne ""} { append out "\n\nLog: $log" }
    return $out
}

proc ::vmdai::banner::toggle_details {} {
    variable S
    set S(details) [expr {!$S(details)}]
    _rebuild
}

# ---- countdown while reconnecting ---------------------------------------------
#
# The runtime probes after runtime::backoff_ms attempt (0.5, 1, 2, 4, then 8 s);
# the banner counts the same schedule down, one second at a time.

proc ::vmdai::banner::_start_countdown {attempt} {
    variable S
    _stop_countdown
    set S(attempt) $attempt
    set S(remaining) [_backoff_s $attempt]
    set S(tick) [::vmdai::sched::after 1000 ::vmdai::banner::_tick]
}

proc ::vmdai::banner::_stop_countdown {} {
    variable S
    if {[info exists S(tick)] && $S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    set S(attempt) 0
    set S(remaining) 0
}

proc ::vmdai::banner::_tick {} {
    variable S
    if {$S(tick) ne ""} { ::vmdai::sched::cancel $S(tick) }
    set S(tick) ""
    if {$S(kind) ne "unreachable" || $S(attempt) == 0} { return }
    if {$S(remaining) > 0} {
        incr S(remaining) -1
    } else {
        incr S(attempt)
        set S(remaining) [_backoff_s $S(attempt)]
    }
    _set_detail [_detail_text]
    set S(tick) [::vmdai::sched::after 1000 ::vmdai::banner::_tick]
}

# ---- actions ----------------------------------------------------------------------

proc ::vmdai::banner::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::banner::_action {name} {
    variable on_action
    variable S
    if {$S(kind) eq "unreachable" && $S(attempt) > 0 && $name eq "retry_now"} {
        _start_countdown 1
        _set_detail [_detail_text]
    }
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name]]
    }
    switch -- $name {
        retry_now - retry { _call ::vmdai::runtime::retry_now }
        open_log { _call ::vmdai::panel::open_log }
        choose_python { _call ::vmdai::panel::open_settings panel }
        restart {
            _call ::vmdai::runtime::stop
            _call ::vmdai::runtime::ensure
        }
    }
}
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_tk_statusbar_banner.py -q 2>&1 | tail -1`
Expected: `6 passed`.

- [ ] **Step 7: Run the lint and the suite**

Run: `python -m pytest tests/test_tk_statusbar_banner.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass.

Run: `grep -on '::vmdai::panel::[a-z_]*\|::vmdai::runtime::[a-z_]*' plugin/statusbar.tcl plugin/banner.tcl | sort -t: -k3 -u`
Expected: seven lines, one per distinct name: `::vmdai::panel::choose_folder`, `open_log` and `open_settings`; `::vmdai::runtime::ensure`, `retry_now` and `stop`; and the bare `::vmdai::runtime::` from `_rt`, which builds the name of each runtime fact it reads (`state info failure_reason pipe_tail backoff_ms`). These are the only targets Plan-specific constraints allow.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+96 passed`, 0 failed, under 60 s.

- [ ] **Step 8: Commit**

```bash
git add plugin/statusbar.tcl plugin/banner.tcl tests/tcl/test_statusbar_banner.tcl \
        tests/test_tk_statusbar_banner.py
git commit -F - <<'MSG'
feat(plugin): status bar and connection banner (P08-T09)

The status bar shows the connection (host:port, never "tunnel"), or the
running phase with a timer, and the trust mode, folder and run count;
narrow widths drop host, runs, folder, then provider, and shorten the
Auto-run label last. The banner is one frame in grid slot 2 with a kind
per runtime failure (not reachable, didn't start, too old), a countdown
that follows the runtime's backoff, and pill actions that retry, open the
log, choose Python or restart an owned runtime.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 10: P08-T10 — toolbar.tcl

**Files:**
- Create: `plugin/toolbar.tcl`
- Create: `tests/tcl/test_toolbar.tcl`
- Create: `tests/test_tk_toolbar.py`

**Interfaces:**
- Consumes: theme (Task 4): `c`, `paint`, `on_repaint`, `rrect`, `fit`, the fonts `ChatMeta` and `ChatMetaBold`, the tokens `chrome text muted faint hover surface`; `::vmdai::transcript::expand_all` (Task 6's flag, which `_sync_menu` reads so the check item matches it); `::vmdai::sched::after`, `cancel`, `pending` (P06-T02); `helpers.tk.run_tk_test` (P06-T10); `helpers.panel_goldens.assert_tcltests` (Task 1)
- Produces:
  - `::vmdai::toolbar::create path ?-onaction cmd? -> path; set_title s; set_busy on; menu_items -> list; tooltip w text`
  - (also) `menu_items` lists the ⋯ menu as `{label action}` items, with `-` for a separator; `tip_shown -> widget or ""`; `opt(tip_map)` (1; tests set 0: the tooltip window `.vmd_ai_tip` is filled in but never mapped) and `opt(tip_delay)` (600); the icons `path.new path.hist path.more path.gear`, the title label `path.title`, the menu `path.more.m`, and the check variable `expand`
  - (also) actions go to `-onaction` when it is set (as `name ?arg?`), else to `::vmdai::panel::new_chat`, `open_history`, `copy_chat_tcl`, `save_chat_tcl`, `open_runs_folder`, `set_expand_all bool`, `collapse_older`, `open_settings`, `open_log` and `quit_runtime`, spelled out one by one so plan 09's `test_component_targets_defined` sees each name; a missing target is skipped

How the toolbar works (Part B V4 "Toolbar", V1 "Make tooltips work"):
- The layout is one grid row: the New chat and History icons, then the chat title (ChatMetaBold, centred, with a trailing ellipsis), then the ⋯ and Settings icons. The padding is 8/5.
- The icons are canvases, and their glyphs are native's `compose`, `history`, `more` and `gear`, drawn in `muted`. They take focus (`-takefocus 1`) and show a rounded `hover` plate on hover and on focus. Click, Space and Return activate them. While a request runs, New chat and History are drawn in `faint`, ignore activation, and are disabled in the menu.
- The ⋯ menu has: New chat (⌘N), History…; Copy chat Tcl, Save chat .tcl…; Open runs folder; Expand all steps (⌘E, a check item), Collapse older runs; Settings… (⌘,), Open runtime log, Quit AI runtime. The accelerators are written `Command-N` on aqua, which Tk shows as ⌘N, and `Control-N` elsewhere. Before the menu is posted, `-postcommand` applies the busy state and copies the transcript's `expand_all` into the check item.
- `tooltip w text` works on any widget. `<Enter>` schedules the tip for 600 ms later through `sched`; `<Leave>` and a button press cancel it and hide it. The tip is an override-redirect toplevel placed under the widget. Icon tooltips name their keys: "New chat (⌘N)" and "Settings (⌘,)".
- The title is fitted to the bar's width less the four 30 px icons and 32 px of padding, not to the title label's own width. The grid lays out a withdrawn root's children once, before `pack` widens the bar, and no `<Configure>` arrives afterwards, so in the tests the label stays 1 px wide while the bar's own width is right. `<Configure>` on the bar refits the title in the mapped panel.

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_toolbar.tcl`:

```tcl
# toolbar.tcl (P08-T10): icons, title, the ⋯ menu, tooltips, busy state.
# Run by tests/test_tk_toolbar.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}
wm withdraw .

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched theme toolbar
::vmdai::theme::init light
set ::vmdai::toolbar::opt(tip_map) 0
wm geometry . 560x120

set ::actions {}
proc record {args} { lappend ::actions $args }
::vmdai::toolbar::create .tb -onaction record
pack .tb -side top -fill x
update
set M .tb.more.m
set KEY [expr {[tk windowingsystem] eq "aqua" ? "⌘" : "Ctrl+"}]

proc fresh {} {
    set ::actions {}
    ::vmdai::toolbar::set_busy 0
    ::vmdai::toolbar::_tip_leave
    update
}
proc glyph_colour {w} { return [$w itemcget [lindex [$w find withtag glyph] 0] -fill] }

test test_menu_items {the ⋯ menu lists the V4 items in order; each runs its action; the check item toggles expand} -body {
    fresh
    set items [::vmdai::toolbar::menu_items]
    for {set i 0} {$i <= [$M index end]} {incr i} {
        if {[$M type $i] ne "separator"} { $M invoke $i }
    }
    namespace eval ::vmdai::transcript { variable expand_all 0 }
    ::vmdai::toolbar::_sync_menu
    $M invoke [$M index "Expand all steps"]
    list $items $::actions [$M entrycget [$M index "New chat"] -accelerator] [$M type [$M index "Expand all steps"]]
} -result [list {{{New chat} new_chat} {History… open_history} - {{Copy chat Tcl} copy_chat_tcl} {{Save chat .tcl…} save_chat_tcl} - {{Open runs folder} open_runs_folder} - {{Expand all steps} set_expand_all} {{Collapse older runs} collapse_older} - {Settings… open_settings} {{Open runtime log} open_log} {{Quit AI runtime} quit_runtime}} \
    {new_chat open_history copy_chat_tcl save_chat_tcl open_runs_folder {set_expand_all 1} collapse_older open_settings open_log quit_runtime {set_expand_all 1}} \
    [expr {[tk windowingsystem] eq "aqua" ? "Command-N" : "Control-N"}] checkbutton]

test icons-keys {icons take focus and run their action on click, Space and Return} -body {
    fresh
    set r {}
    foreach w {.tb.new .tb.hist .tb.gear .tb.more} { lappend r [$w cget -takefocus] }
    foreach w {.tb.new .tb.hist .tb.gear} {
        foreach seq {<ButtonRelease-1> <space> <Return>} { uplevel #0 [bind $w $seq] }
    }
    list $r [lsort -unique $::actions] [llength $::actions]
} -result {{1 1 1 1} {new_chat open_history open_settings} 9}

test test_tooltips_600ms {a tooltip shows 600 ms after the pointer enters, not before; leaving hides it} -body {
    fresh
    ::vmdai::toolbar::_tip_enter .tb.new
    after 450
    update
    set r [list [::vmdai::toolbar::tip_shown]]
    after 200
    update
    lappend r [::vmdai::toolbar::tip_shown] [.vmd_ai_tip.l cget -text] [wm state .vmd_ai_tip]
    ::vmdai::toolbar::_tip_leave
    lappend r [::vmdai::toolbar::tip_shown] [llength [::vmdai::sched::pending]]
    label .other
    ::vmdai::toolbar::tooltip .other "Anything"
    ::vmdai::toolbar::_tip_show .other
    lappend r [.vmd_ai_tip.l cget -text]
    destroy .other
    set r
} -result [list {} .tb.new "New chat (${KEY}N)" withdrawn {} 0 Anything]

test test_disabled_while_busy {while a request runs, New chat and History are dimmed, ignore clicks and are off in the menu} -body {
    fresh
    ::vmdai::toolbar::set_busy 1
    foreach w {.tb.new .tb.hist .tb.gear} { uplevel #0 [bind $w <ButtonRelease-1>] }
    set r [list $::actions [$M entrycget 0 -state] [$M entrycget 1 -state] \
        [expr {[glyph_colour .tb.new] eq [::vmdai::theme::c faint]}] \
        [expr {[glyph_colour .tb.more] eq [::vmdai::theme::c muted]}]]
    ::vmdai::toolbar::set_busy 0
    uplevel #0 [bind .tb.new <ButtonRelease-1>]
    lappend r $::actions [$M entrycget 0 -state] [expr {[glyph_colour .tb.new] eq [::vmdai::theme::c muted]}]
} -result {open_settings disabled disabled 1 1 {open_settings new_chat} normal 1}

test title-fit {the title is centred, ellipsized to fit, and a short one is left alone} -body {
    fresh
    ::vmdai::toolbar::set_title "Load 1HCK"
    set r [list [.tb.title cget -text]]
    ::vmdai::toolbar::set_title [string repeat "a very long chat title " 12]
    set shown [.tb.title cget -text]
    lappend r [string match *… $shown] [expr {[font measure ChatMetaBold $shown] <= [winfo width .tb] - 152}] \
        [.tb.title cget -anchor]
} -result {{Load 1HCK} 1 1 center}

cleanupTests
exit
```

The menu is driven with `menu invoke`, which runs an entry's command without posting the menu (posting would map a window). `-postcommand` does not run on `invoke`, so the tests call `_sync_menu` themselves. `test_tooltips_600ms` waits 450 ms and then 200 ms more (650 ms in all): the tip must not show at 450 ms and must show by 650 ms.

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tk_toolbar.py`:

```python
"""toolbar.tcl (P08-T10): icons, title, the ⋯ menu, 600 ms tooltips, busy state."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO
from helpers.tk import run_tk_test

TCL = REPO / "tests" / "tcl" / "test_toolbar.tcl"
TESTS = [
    "test_menu_items",
    "icons-keys",
    "test_tooltips_600ms",
    "test_disabled_while_busy",
    "title-fit",
]


@pytest.fixture(scope="module")
def result():
    return run_tk_test(str(TCL))


def test_toolbar_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_menu_items(result):
    assert_tcltests(result, ["test_menu_items", "icons-keys"])


def test_tooltips_600ms(result):
    assert_tcltests(result, ["test_tooltips_600ms"])


def test_disabled_while_busy(result):
    assert_tcltests(result, ["test_disabled_while_busy", "title-fit"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_toolbar.py -q 2>&1 | tail -2`
Expected: `4 failed`. The tcltest file stops at `load_plugin … toolbar` with `couldn't read file ".../plugin/toolbar.tcl": no such file or directory`. (Without a GUI session: `4 skipped`.)

- [ ] **Step 4: Write the toolbar**

Create `plugin/toolbar.tcl`:

```tcl
# toolbar.tcl -- ChatVMD toolbar (Part B V4 "Toolbar").
#
#   ::vmdai::toolbar::create path ?-onaction cmd?
#   ::vmdai::toolbar::set_title s     the chat title, centred and ellipsized
#   ::vmdai::toolbar::set_busy on     New chat and History are off while a request runs
#   ::vmdai::toolbar::menu_items      -> the ⋯ menu: {label action} items, "-" for separators
#   ::vmdai::toolbar::tooltip w text  show text under w after 600 ms (any widget)
#
# Canvas icons (New chat, History | title | ⋯, Settings) take focus, show a
# plate on hover and focus, and activate on click, Space or Return. Actions
# go to the -onaction callback when set, else to the panel procs of the same
# name (plan 09); a missing target is skipped. Tests set opt(tip_map) 0: the
# tooltip window is filled in but never mapped.

namespace eval ::vmdai::toolbar {
    variable P
    if {![info exists P]} { set P "" }
    variable on_action
    if {![info exists on_action]} { set on_action "" }
    variable opt
    if {![info exists opt]} { array set opt {tip_map 1 tip_delay 600} }
    variable tips
    if {![info exists tips]} { array set tips {} }
    variable expand
    if {![info exists expand]} { set expand 0 }
    variable S
    if {![info exists S]} { array set S {} }
}

proc ::vmdai::toolbar::_reset {} {
    variable S
    array unset S
    array set S {busy 0 title "" tip_id "" tip_for "" hover ""}
}

proc ::vmdai::toolbar::_mod {} {
    return [expr {[tk windowingsystem] eq "aqua" ? "Command" : "Control"}]
}

proc ::vmdai::toolbar::_key_hint {key} {
    return [expr {[tk windowingsystem] eq "aqua" ? "⌘$key" : "Ctrl+$key"}]
}

# The ⋯ menu (Part B V4): {kind label action ?accelerator-key?}.
proc ::vmdai::toolbar::_menu_spec {} {
    return {
        {command "New chat" new_chat N}
        {command "History…" open_history}
        {separator}
        {command "Copy chat Tcl" copy_chat_tcl}
        {command "Save chat .tcl…" save_chat_tcl}
        {separator}
        {command "Open runs folder" open_runs_folder}
        {separator}
        {check "Expand all steps" set_expand_all E}
        {command "Collapse older runs" collapse_older}
        {separator}
        {command "Settings…" open_settings ,}
        {command "Open runtime log" open_log}
        {command "Quit AI runtime" quit_runtime}
    }
}

proc ::vmdai::toolbar::create {path args} {
    variable P
    variable on_action
    set on_action ""
    foreach {opt value} $args {
        if {$opt ne "-onaction"} { error "unknown option \"$opt\": must be -onaction" }
        set on_action $value
    }
    if {[winfo exists $path]} { destroy $path }
    _reset
    set P $path
    frame $path -borderwidth 0 -highlightthickness 0
    _icon $path.new compose new_chat "New chat ([_key_hint N])"
    _icon $path.hist history open_history "History"
    label $path.title -font ChatMetaBold -anchor center -width 1 -borderwidth 0 -padx 0
    _icon $path.more more more "More"
    _icon $path.gear gear open_settings "Settings ([_key_hint ,])"
    grid $path.new -row 0 -column 0 -padx {8 0} -pady 5
    grid $path.hist -row 0 -column 1 -pady 5
    grid $path.title -row 0 -column 2 -sticky ew -padx 8
    grid $path.more -row 0 -column 3 -pady 5
    grid $path.gear -row 0 -column 4 -padx {0 8} -pady 5
    grid columnconfigure $path 2 -weight 1
    ::vmdai::theme::paint $path -background chrome
    ::vmdai::theme::paint $path.title -background chrome -foreground text
    menu $path.more.m -tearoff 0 -postcommand ::vmdai::toolbar::_sync_menu
    foreach item [_menu_spec] {
        lassign $item kind label action key
        set accel {}
        if {$key ne ""} { set accel [list -accelerator "[_mod]-$key"] }
        switch -- $kind {
            separator { $path.more.m add separator }
            check {
                $path.more.m add checkbutton -label $label {*}$accel \
                    -variable ::vmdai::toolbar::expand -command ::vmdai::toolbar::_toggle_expand
            }
            default {
                $path.more.m add command -label $label {*}$accel \
                    -command [list ::vmdai::toolbar::_action $action]
            }
        }
    }
    bind $path <Configure> ::vmdai::toolbar::_fit_title
    ::vmdai::theme::on_repaint ::vmdai::toolbar::_redraw
    return $path
}

# A borderless icon button: a rounded plate on hover and focus, like a
# macOS toolbar item. Click, Space and Return activate it.
proc ::vmdai::toolbar::_icon {w kind action tip} {
    canvas $w -width 30 -height 26 -borderwidth 0 -highlightthickness 0 -takefocus 1 -cursor hand2
    ::vmdai::theme::paint $w -background chrome
    set ::vmdai::toolbar::S(kind,$w) $kind
    set ::vmdai::toolbar::S(action,$w) $action
    _draw_icon $w
    bind $w <Enter> [list ::vmdai::toolbar::_hover $w 1]
    bind $w <Leave> [list ::vmdai::toolbar::_hover $w 0]
    bind $w <FocusIn> [list ::vmdai::toolbar::_draw_icon $w]
    bind $w <FocusOut> [list ::vmdai::toolbar::_draw_icon $w]
    foreach seq {<ButtonRelease-1> <space> <Return>} {
        bind $w $seq [list ::vmdai::toolbar::_activate $w]
    }
    tooltip $w $tip
    return $w
}

proc ::vmdai::toolbar::_enabled {w} {
    variable S
    return [expr {!($S(busy) && $S(action,$w) in {new_chat open_history})}]
}

proc ::vmdai::toolbar::_hover {w on} {
    variable S
    set S(hover) [expr {$on ? $w : ""}]
    _draw_icon $w
}

proc ::vmdai::toolbar::_draw_icon {w} {
    variable S
    if {![winfo exists $w]} { return }
    $w delete all
    set on [expr {[_enabled $w] && ($S(hover) eq $w || [::focus] eq $w)}]
    if {$on} {
        ::vmdai::theme::rrect $w 1 1 29 25 6 -fill [::vmdai::theme::c hover] -outline "" -tags plate
    }
    set col [::vmdai::theme::c [expr {[_enabled $w] ? "muted" : "faint"}]]
    $w configure -cursor [expr {[_enabled $w] ? "hand2" : "arrow"}]
    _glyph $w $S(kind,$w) 15 13 $col
}

# Native's icon glyphs (docs/design/round1/prototypes/native/proto.tcl).
proc ::vmdai::toolbar::_glyph {c kind cx cy col} {
    switch -- $kind {
        compose {
            $c create line [expr {$cx-2}] [expr {$cy-6}] [expr {$cx-6}] [expr {$cy-6}] \
                [expr {$cx-6}] [expr {$cy+6}] [expr {$cx+6}] [expr {$cy+6}] [expr {$cx+6}] [expr {$cy+1}] \
                -width 1.4 -fill $col -capstyle round -joinstyle round -tags glyph
            $c create line [expr {$cx-1}] [expr {$cy+2}] [expr {$cx+7}] [expr {$cy-6}] \
                -width 1.4 -fill $col -capstyle round -tags glyph
        }
        history {
            $c create oval [expr {$cx-7}] [expr {$cy-7}] [expr {$cx+7}] [expr {$cy+7}] \
                -width 1.4 -outline $col -tags glyph
            $c create line $cx [expr {$cy-4}] $cx $cy [expr {$cx+3}] [expr {$cy+2}] \
                -width 1.4 -fill $col -capstyle round -joinstyle round -tags glyph
        }
        more {
            foreach dx {-5 0 5} {
                $c create oval [expr {$cx+$dx-1.3}] [expr {$cy-1.3}] [expr {$cx+$dx+1.3}] \
                    [expr {$cy+1.3}] -fill $col -outline "" -tags glyph
            }
        }
        gear {
            set pts {}
            set n 8
            for {set i 0} {$i < $n * 4} {incr i} {
                set a [expr {($i / double($n * 4)) * 6.2831853 - 1.5707963 - 3.1415926 / ($n * 4)}]
                set r [expr {($i % 4) == 1 || ($i % 4) == 2 ? 7.4 : 5.5}]
                lappend pts [expr {$cx + $r * cos($a)}] [expr {$cy + $r * sin($a)}]
            }
            $c create polygon $pts -fill "" -outline $col -width 1.3 -joinstyle round -tags glyph
            $c create oval [expr {$cx-2.3}] [expr {$cy-2.3}] [expr {$cx+2.3}] [expr {$cy+2.3}] \
                -outline $col -width 1.3 -tags glyph
        }
    }
}

proc ::vmdai::toolbar::_redraw {} {
    variable P
    if {$P eq "" || ![winfo exists $P]} { return }
    foreach w [list $P.new $P.hist $P.more $P.gear] { _draw_icon $w }
}

proc ::vmdai::toolbar::_activate {w} {
    variable S
    if {![_enabled $w]} { return }
    _tip_leave
    if {$S(action,$w) eq "more"} {
        _post_menu
        return
    }
    _action $S(action,$w)
}

proc ::vmdai::toolbar::_post_menu {} {
    variable P
    set b $P.more
    tk_popup $P.more.m [winfo rootx $b] [expr {[winfo rooty $b] + [winfo height $b]}]
}

# Before the menu shows: the busy state and the transcript's expand flag.
proc ::vmdai::toolbar::_sync_menu {} {
    variable P
    variable S
    variable expand
    set state [expr {$S(busy) ? "disabled" : "normal"}]
    $P.more.m entryconfigure 0 -state $state
    $P.more.m entryconfigure 1 -state $state
    if {[info exists ::vmdai::transcript::expand_all]} {
        set expand $::vmdai::transcript::expand_all
    }
}

proc ::vmdai::toolbar::_toggle_expand {} {
    variable expand
    _action set_expand_all $expand
}

proc ::vmdai::toolbar::menu_items {} {
    variable P
    set m $P.more.m
    set out {}
    for {set i 0} {$i <= [$m index end]} {incr i} {
        if {[$m type $i] eq "separator"} {
            lappend out -
            continue
        }
        lappend out [list [$m entrycget $i -label] [lindex [lindex [_menu_spec] $i] 2]]
    }
    return $out
}

proc ::vmdai::toolbar::set_title {s} {
    variable S
    set S(title) $s
    _fit_title
}

# The room left between the icons: the bar's width minus four 30 px icons
# and the padding (8 + 8 at the edges, 8 + 8 around the title).
proc ::vmdai::toolbar::_title_room {} {
    variable P
    set w [winfo width $P]
    if {$w <= 1} { return -1 }
    return [expr {$w - 4 * 30 - 32}]
}

proc ::vmdai::toolbar::_fit_title {} {
    variable P
    variable S
    if {$P eq "" || ![winfo exists $P.title]} { return }
    set room [_title_room]
    set text $S(title)
    if {$room > 0} { set text [::vmdai::theme::fit ChatMetaBold $room $text] }
    $P.title configure -text $text
}

proc ::vmdai::toolbar::set_busy {on} {
    variable P
    variable S
    set S(busy) [expr {$on ? 1 : 0}]
    if {$P eq "" || ![winfo exists $P]} { return }
    _redraw
    _sync_menu
}

# ---- tooltips (600 ms; Part B V1 "Make tooltips work") ----------------------------

proc ::vmdai::toolbar::tooltip {w text} {
    variable tips
    set tips($w) $text
    bind $w <Enter> +[list ::vmdai::toolbar::_tip_enter $w]
    bind $w <Leave> +::vmdai::toolbar::_tip_leave
    bind $w <ButtonPress> +::vmdai::toolbar::_tip_leave
    bind $w <Destroy> +[list unset -nocomplain ::vmdai::toolbar::tips($w)]
}

proc ::vmdai::toolbar::_tip_enter {w} {
    variable S
    variable opt
    _tip_leave
    set S(tip_id) [::vmdai::sched::after $opt(tip_delay) [list ::vmdai::toolbar::_tip_show $w]]
}

proc ::vmdai::toolbar::_tip_show {w} {
    variable S
    variable opt
    variable tips
    set S(tip_id) ""
    if {![winfo exists $w] || ![info exists tips($w)]} { return }
    set tw .vmd_ai_tip
    if {![winfo exists $tw]} {
        toplevel $tw -borderwidth 0
        wm withdraw $tw
        wm overrideredirect $tw 1
        label $tw.l -font ChatMeta -borderwidth 1 -relief solid -padx 6 -pady 2
        pack $tw.l
    }
    $tw.l configure -text $tips($w) -background [::vmdai::theme::c surface] \
        -foreground [::vmdai::theme::c text]
    set S(tip_for) $w
    if {$opt(tip_map)} {
        wm geometry $tw +[winfo rootx $w]+[expr {[winfo rooty $w] + [winfo height $w] + 4}]
        wm deiconify $tw
        raise $tw
    }
}

proc ::vmdai::toolbar::_tip_leave {} {
    variable S
    if {$S(tip_id) ne ""} {
        ::vmdai::sched::cancel $S(tip_id)
        set S(tip_id) ""
    }
    set S(tip_for) ""
    if {[winfo exists .vmd_ai_tip]} { wm withdraw .vmd_ai_tip }
}

# The widget whose tooltip is showing, or "".
proc ::vmdai::toolbar::tip_shown {} {
    variable S
    return $S(tip_for)
}

# ---- actions ----------------------------------------------------------------------

proc ::vmdai::toolbar::_call {target args} {
    if {[info commands $target] eq ""} { return }
    uplevel #0 [list $target {*}$args]
}

proc ::vmdai::toolbar::_action {name args} {
    variable on_action
    if {$on_action ne ""} {
        return [uplevel #0 [list {*}$on_action $name {*}$args]]
    }
    switch -- $name {
        new_chat         { _call ::vmdai::panel::new_chat }
        open_history     { _call ::vmdai::panel::open_history }
        copy_chat_tcl    { _call ::vmdai::panel::copy_chat_tcl }
        save_chat_tcl    { _call ::vmdai::panel::save_chat_tcl }
        open_runs_folder { _call ::vmdai::panel::open_runs_folder }
        set_expand_all   { _call ::vmdai::panel::set_expand_all {*}$args }
        collapse_older   { _call ::vmdai::panel::collapse_older }
        open_settings    { _call ::vmdai::panel::open_settings }
        open_log         { _call ::vmdai::panel::open_log }
        quit_runtime     { _call ::vmdai::panel::quit_runtime }
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_tk_toolbar.py -q 2>&1 | tail -1`
Expected: `4 passed` (in about 1 s; the tooltip test waits 650 ms).

- [ ] **Step 6: Run the lint and the suite**

Run: `python -m pytest tests/test_tk_toolbar.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass.

Run: `grep -o '::vmdai::panel::[a-z_]*' plugin/toolbar.tcl | sort -u | tr '\n' ' '`
Expected: `::vmdai::panel::collapse_older ::vmdai::panel::copy_chat_tcl ::vmdai::panel::new_chat ::vmdai::panel::open_history ::vmdai::panel::open_log ::vmdai::panel::open_runs_folder ::vmdai::panel::open_settings ::vmdai::panel::quit_runtime ::vmdai::panel::save_chat_tcl ::vmdai::panel::set_expand_all` (ten names, all on the Plan-specific constraints list).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+100 passed`, 0 failed, under 60 s.

- [ ] **Step 7: Commit**

```bash
git add plugin/toolbar.tcl tests/tcl/test_toolbar.tcl tests/test_tk_toolbar.py
git commit -F - <<'MSG'
feat(plugin): toolbar with focusable canvas icons, the ... menu and tooltips (P08-T10)

New chat, History, ... and Settings are canvas icons that take focus and
activate on click, Space or Return; New chat and History are dimmed and
inert while a request runs. The ... menu carries the V4 items with their
accelerators and an Expand all steps check item that follows the
transcript. Tooltips appear 600 ms after the pointer enters. The chat
title is centred and ellipsized to the room between the icons.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 11: P08-T11 — tclexport.tcl ledger

**Files:**
- Create: `plugin/tclexport.tcl`
- Create: `tests/tcl/test_tclexport.tcl`
- Create: `tests/test_tcl_tclexport.py`

**Interfaces:**
- Consumes: `::vmdai::executor::split_statements script -> dict {statements tail}` (P06-T08); `tests/tcl/plugin_loader.tcl` (Task 5); `helpers.tcl.run_tcltest`, `REPO` (P01-T03); `helpers.panel_goldens.assert_tcltests` (Task 1)
- Produces:
  - `::vmdai::tclexport::record request_id call_key command applied failed_index; run_tcl request_id -> string; chat_tcl -> string; save path text -> path; reset`
  - (also) `record` takes `applied` as an integer (0 when unknown) and `failed_index` as an integer or `""`, exactly what plan 09's `_record_tcl` passes from `tool.finished.statements`. `run_tcl` and `chat_tcl` return `""` when nothing of a run or chat ran. `save` raises when it cannot write. These are also the targets of Task 6's `_do_copy_run_tcl` and `_do_save_run_tcl`.

How the ledger works (§2h `tclexport.tcl`, Part B V1 console graft, C3):
- It follows the same rule as the runtime's recorder (P05, `RunRecorder._format_partial_block`), so Save .tcl and `transcript.tcl` agree:
  - A command whose statements all ran is kept whole.
  - A command that failed after `applied` statements keeps the exact source text of statements 1…applied. Then comes `# statement F of T failed; statements F–T were not applied:` (`statement F was not applied:` when F = T), and then the rest, commented out line by line. With no `failed_index`, the comment reads `# statements A+1–T were not applied:`.
  - A call that applied nothing is left out. That covers a failure at statement 1, a C3 incomplete command, a C1 block, a call that was not run, and an unknown result.
- The recorder's comment also names the first error line. The ledger's `record` gets no error text, so its comment leaves that out.
- The statement boundaries come from the executor's own `split_statements`. The ledger finds each statement in the command with `string first` from the end of the previous one (as Task 6's `_cmd_segments` does), so the kept prefix is byte for byte what ran. An incomplete tail counts as the last statement, and without the splitter a command is one statement.
- A commented line that ends in an odd number of backslashes gets a trailing space (the recorder's fix). Otherwise the comment would continue onto, and swallow, the next kept command.
- The ledger keeps an ordered list of runs, an ordered list of calls per run, and one entry per `call_key`. Recording a `call_key` again, as a late `tool.finished` does, replaces the entry in place.
- `run_tcl` is the calls' kept text, with no header. `chat_tcl` is one comment line, then `# --- run N ---` and `run_tcl` for each run that kept something, numbered in order. `save` writes UTF-8 with LF line endings.
- It is Tk-free, so its test runs under `run_tcltest` and in CI.

- [ ] **Step 1: Write the failing tcltests**

Create `tests/tcl/test_tclexport.tcl`:

```tcl
# tclexport.tcl (P08-T11): the Copy/Save .tcl ledger. No Tk.
# Run by tests/test_tcl_tclexport.py.
package require tcltest 2
namespace import ::tcltest::*
::tcltest::configure -verbose {pass body error}

source [file join $env(VMDAI_REPO) tests tcl plugin_loader.tcl]
load_plugin sched config net executor tclexport

# Evaluate exported Tcl in a fresh interpreter whose VMD commands only
# record their arguments; return the recorded calls.
proc replay {script} {
    set i [interp create]
    interp eval $i {
        set ::CALLS {}
        foreach c {mol color display render measure} {
            proc $c {args} "lappend ::CALLS \[list $c {*}\$args\]"
        }
    }
    set rc [catch {interp eval $i $script} err]
    set calls [interp eval $i {set ::CALLS}]
    interp delete $i
    if {$rc} { return [list error $err] }
    return $calls
}

set CMD "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\ncolor Display Background white\ndisplay backgroundcolor white\nrender TachyonInternal a.tga"

test test_applied_kept_rest_commented {applied statements are kept byte for byte, the failed one and the rest are commented out, and a call that applied nothing is left out} -body {
    ::vmdai::tclexport::reset
    ::vmdai::tclexport::record req_1 k1 $CMD 3 4
    ::vmdai::tclexport::record req_1 k2 "bogus 1" 0 1
    ::vmdai::tclexport::record req_1 k3 "mol new a.pdb; set p C:\\dir\\" 1 2
    ::vmdai::tclexport::record req_1 k4 "measure rgyr top" 1 ""
    ::vmdai::tclexport::record req_1 k5 "mol delrep 0 top\nmol addrep top\nmol off 0" 1 ""
    set text [::vmdai::tclexport::run_tcl req_1]
    list $text [replay $text]
} -result [list "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\ncolor Display Background white\n# statement 4 of 5 failed; statements 4–5 were not applied:\n# display backgroundcolor white\n# render TachyonInternal a.tga\nmol new a.pdb\n# statement 2 of 2 failed; statement 2 was not applied:\n# set p C:\\dir\\ \nmeasure rgyr top\nmol delrep 0 top\n# statements 2–3 were not applied:\n# mol addrep top\n# mol off 0\n" \
    {{mol new 1hck.pdb} {mol modstyle 0 top NewCartoon} {color Display Background white} {mol new a.pdb} {measure rgyr top} {mol delrep 0 top}}]

test test_run_and_chat_tcl {runs keep their order, a late result replaces its entry in place, chat_tcl numbers the runs, save writes UTF-8, reset forgets} -body {
    ::vmdai::tclexport::reset
    ::vmdai::tclexport::record req_1 k1 "mol new 1hck.pdb" 1 ""
    ::vmdai::tclexport::record req_2 k3 "measure rgyr \[atomselect top protein\]" 1 ""
    ::vmdai::tclexport::record req_1 k2 "mol modstyle 0 top NewCartoon" 0 ""
    ::vmdai::tclexport::record req_3 k4 "bogus" 0 1
    ::vmdai::tclexport::record req_1 k2 "mol modstyle 0 top NewCartoon" 1 ""
    set chat [::vmdai::tclexport::chat_tcl]
    set dir [file join $env(HOME) "exports é"]
    file mkdir $dir
    set path [::vmdai::tclexport::save [file join $dir chat.tcl] "# résumé\n$chat"]
    set fh [open $path rb]
    set bytes [read $fh]
    close $fh
    set r [list [::vmdai::tclexport::run_tcl req_1] [::vmdai::tclexport::run_tcl req_3] \
        [::vmdai::tclexport::run_tcl nope] $chat \
        [expr {$bytes eq [encoding convertto utf-8 "# résumé\n$chat"]}] \
        [catch {::vmdai::tclexport::save [file join $env(HOME) missing dir x.tcl] x}]]
    ::vmdai::tclexport::reset
    lappend r [::vmdai::tclexport::chat_tcl] [::vmdai::tclexport::run_tcl req_1]
} -result [list "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n" {} {} \
    "# ChatVMD: the Tcl that ran in VMD, in order. Statements that did not run are commented out.\n\n# --- run 1 ---\nmol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n\n# --- run 2 ---\nmeasure rgyr \[atomselect top protein\]\n" \
    1 1 {} {}]

cleanupTests
```

`replay` evaluates the exported text in a fresh interpreter whose `mol`, `color`, `display`, `render` and `measure` only record their arguments. That proves the export is valid Tcl and that exactly the applied statements run. `k3`'s unapplied statement `set p C:\dir\` ends in a backslash and is the last commented line before `k4`. Without the trailing space, `# set p C:\dir\` would swallow `measure rgyr top` (verified while planning: the test fails if the fix is removed). The expected strings assume that each statement from the executor's splitter is its source text without the separator that ends it (Task 0 Step 4 prints two statements and the tail `bad [` for its sample).

- [ ] **Step 2: Write the pytest wrapper**

Create `tests/test_tcl_tclexport.py`:

```python
"""tclexport.tcl (P08-T11): the Copy/Save .tcl ledger. No Tk, so it runs in CI."""
from __future__ import annotations

import pytest

from helpers.panel_goldens import assert_tcltests
from helpers.tcl import REPO, run_tcltest

TCL = REPO / "tests" / "tcl" / "test_tclexport.tcl"
TESTS = ["test_applied_kept_rest_commented", "test_run_and_chat_tcl"]


@pytest.fixture(scope="module")
def result():
    return run_tcltest(str(TCL))


def test_tclexport_counts(result):
    assert (result.passed, result.failed) == (len(TESTS), 0), result.output


def test_applied_kept_rest_commented(result):
    assert_tcltests(result, ["test_applied_kept_rest_commented"])


def test_run_and_chat_tcl(result):
    assert_tcltests(result, ["test_run_and_chat_tcl"])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_tclexport.py -q 2>&1 | tail -2`
Expected: `3 failed`. The tcltest file stops at `load_plugin … tclexport` with `couldn't read file ".../plugin/tclexport.tcl": no such file or directory`.

- [ ] **Step 4: Write the ledger**

Create `plugin/tclexport.tcl`:

```tcl
# tclexport.tcl -- ChatVMD Tcl export ledger: Copy/Save run and chat .tcl
# (spec §2h, Part B V1 console graft, C3). No Tk.
#
#   ::vmdai::tclexport::record request_id call_key command applied failed_index
#   ::vmdai::tclexport::run_tcl request_id  -> the Tcl one run applied
#   ::vmdai::tclexport::chat_tcl            -> every run, in order ("" if none)
#   ::vmdai::tclexport::save path text      write text as UTF-8 with LF endings
#   ::vmdai::tclexport::reset               forget everything (New chat, resume)
#
# The same rule as the runtime's recorder (C3): a command whose statements
# all ran is kept whole; one that failed after `applied` statements keeps
# that exact source prefix, then a comment naming the failed statement, then
# the rest commented out line by line; a call that applied nothing is left
# out. Statement boundaries come from the executor's own splitter
# (executor::split_statements), so they match what actually ran. Recording
# a call_key again (a late result) replaces its entry in place.

namespace eval ::vmdai::tclexport {
    variable runs
    if {![info exists runs]} { set runs {} }
    variable calls
    if {![info exists calls]} { array set calls {} }
    variable entry
    if {![info exists entry]} { array set entry {} }
}

proc ::vmdai::tclexport::reset {} {
    variable runs
    variable calls
    variable entry
    set runs {}
    array unset calls
    array set calls {}
    array unset entry
    array set entry {}
}

proc ::vmdai::tclexport::record {request_id call_key command applied failed_index} {
    variable runs
    variable calls
    variable entry
    if {[info exists entry($call_key)]} {
        set request_id [lindex $entry($call_key) 0]
    } else {
        if {$request_id ni $runs} { lappend runs $request_id }
        lappend calls($request_id) $call_key
    }
    set entry($call_key) [list $request_id $command $applied $failed_index]
    return
}

# {start end} character ranges of the statements in cmd, end exclusive,
# found where the executor's splitter says they are. An incomplete tail
# counts as the last statement. Without the splitter: one statement.
proc ::vmdai::tclexport::_ranges {cmd} {
    if {[catch {::vmdai::executor::split_statements $cmd} d]} {
        return [list [list 0 [string length $cmd]]]
    }
    set stmts [dict get $d statements]
    if {[string trim [dict get $d tail]] ne ""} { lappend stmts [dict get $d tail] }
    set out {}
    set pos 0
    foreach stmt $stmts {
        set s [string first $stmt $cmd $pos]
        if {$s < 0} { continue }
        set pos [expr {$s + [string length $stmt]}]
        lappend out [list $s $pos]
    }
    if {$out eq ""} { return [list [list 0 [string length $cmd]]] }
    return $out
}

# "# text" for each line; a line ending in an odd number of backslashes gets
# a trailing space, so the comment cannot swallow the next line.
proc ::vmdai::tclexport::_commented {text} {
    set out ""
    foreach line [split [string trimright $text "\n"] "\n"] {
        set tail [expr {[string length $line] - [string length [string trimright $line "\\"]]}]
        if {$tail % 2 == 1} { append line " " }
        append out "# $line\n"
    }
    return $out
}

# The kept text of one recorded call ("" when nothing of it ran).
proc ::vmdai::tclexport::_call_tcl {call_key} {
    variable entry
    lassign $entry($call_key) request_id cmd applied failed_index
    if {![string is integer -strict $applied] || $applied < 1} { return "" }
    set ranges [_ranges $cmd]
    set total [llength $ranges]
    if {$applied >= $total} {
        return "[string trimright $cmd "\n"]\n"
    }
    set end [lindex $ranges [expr {$applied - 1}] 1]
    set kept [string trimright [string range $cmd 0 [expr {$end - 1}]] "\n"]
    set rest [string trimleft [string range $cmd $end end] " \t;\n"]
    set first [expr {$applied + 1}]
    if {[string is integer -strict $failed_index] && $failed_index > $applied} {
        set first $failed_index
        set head "# statement $failed_index of $total failed; "
    } else {
        set head "# "
    }
    if {$first < $total} {
        append head "statements $first–$total were not applied:"
    } else {
        append head "statement $first was not applied:"
    }
    return "$kept\n$head\n[_commented $rest]"
}

proc ::vmdai::tclexport::run_tcl {request_id} {
    variable calls
    if {![info exists calls($request_id)]} { return "" }
    set out ""
    foreach key $calls($request_id) { append out [_call_tcl $key] }
    return $out
}

proc ::vmdai::tclexport::chat_tcl {} {
    variable runs
    set out ""
    set n 0
    foreach request_id $runs {
        set body [run_tcl $request_id]
        if {$body eq ""} { continue }
        incr n
        append out "\n# --- run $n ---\n" $body
    }
    if {$n == 0} { return "" }
    return "# ChatVMD: the Tcl that ran in VMD, in order. Statements that did not run are commented out.\n$out"
}

proc ::vmdai::tclexport::save {path text} {
    set fh [open $path w]
    set rc [catch {
        fconfigure $fh -encoding utf-8 -translation lf
        puts -nonewline $fh $text
    } err]
    close $fh
    if {$rc} { return -code error $err }
    return $path
}
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_tcl_tclexport.py -q 2>&1 | tail -1`
Expected: `3 passed`. If only the expected strings differ, and only by a `;` or newline at the end of a kept prefix, the executor's statements carry their separator. In that case, fix `_ranges` so that each range ends before the separator; do not change the expected text. The rule is "the exact source of statements 1…applied".

- [ ] **Step 6: Run the lint, the whole plan's tests and the suite**

Run: `python -m pytest tests/test_tcl_tclexport.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass.

Run: `python -m pytest tests/test_tcl_viewmodel.py tests/test_tk_theme.py tests/test_tk_transcript.py tests/test_tk_tool_rows.py tests/test_tk_snapshot_cards.py tests/test_tk_composer.py tests/test_tk_statusbar_banner.py tests/test_tk_toolbar.py tests/test_tcl_tclexport.py -q 2>&1 | tail -1`
Expected: `103 passed`, in about 4 s. (Without a GUI session, only the view-model and tclexport tests run and the Tk modules skip, as in CI.)

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+103 passed`, 0 failed, under 60 s.

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tcl_viewmodel.py tests/test_tk_transcript.py -q -k golden 2>&1 | tail -1 && git status --short tests/fixtures`
Expected: every golden test passes and `git status` prints nothing, so no golden changed after Task 7.

- [ ] **Step 7: Commit**

```bash
git add plugin/tclexport.tcl tests/tcl/test_tclexport.tcl tests/test_tcl_tclexport.py
git commit -F - <<'MSG'
feat(plugin): Tcl export ledger for Copy/Save run and chat .tcl (P08-T11)

Each recorded call keeps what actually ran, by the executor's own
statement split: a full success whole, a partial failure as its exact
applied prefix plus a comment naming the failed statement and the rest
commented out, nothing for a call that applied nothing. It is the same
rule as the runtime recorder (C3). A late result replaces its entry;
chat_tcl numbers the runs; save writes UTF-8.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

## Deviations from skeleton

Each item below is a name or detail that differs from the plan skeleton or the spec's wording. Every other name matches the skeleton, and plan 09's "Consumed contract" table and its pre-flight (`pre-procs`, `pre-composer`, `pre-statusbar`, `pre-transcript`, `pre-theme`) check them.

1. **Row mark `rowend:$k`, not `$k.rowend`** (P08-T06). Tk parses a mark name that starts with a digit as a `line.char` index, and call keys are 12 hex characters, so most keys broke every row (the fixtures' `000000000001` did). The position and gravity are the same, and nothing outside `transcript.tcl` uses the mark. `status-1` pins a key that starts with a digit.
2. **`_show_run` also calls `_collapse`** (P08-T05, filled in by P08-T06), so a chip click on a collapsed run also clears the run's collapsed state.
3. **Optional trailing op arguments** (P08-T01): `block.open … ?time?`, `tool.open … ?rationale?`, `run.close … ?max_turns?` and `snapshot … ?renderer?`, and a `tool.close` detail dict with fixed keys (Plan-specific constraints). The listed forms of §2h and Part B V4 are unchanged.
4. **The Stop state belongs to the caller** (P08-T08). The composer's Stop click and Esc only call `-onstop`, and the caller switches the mode to `stopping` (plan 09's `on_stop` does, idempotently). If the composer did it itself, the pill could stay at "Stopping…" after a click that the panel ignored because no request was running.
5. **`composer::push_history` keeps its own list** (`history`, newest 50), and nothing else in plan 08 reads it. P09-T03 replaces the proc and the list with its Up/Down recall, as its plan says.
6. **The status bar's `update` keys**: plan 09's nine keys, plus `retry_in` (whole seconds to the next reconnect attempt, shown as `Runtime offline · retry in N s`). An earlier draft of the Plan-specific constraints also listed `status_var`, which nothing defined or sent; it is dropped. `text` returns a two-element list `{left right}`, which plan 09's `pre-statusbar` reads with `string match`.
7. **The banner's countdown is modelled on `runtime::backoff_ms`** (P08-T09). The runtime (P06-T06) exposes no "next probe at" value, so the banner counts down the same 0.5, 1, 2, 4, then 8 s schedule, one second per tick. A probe that takes time makes the count run slightly ahead of the real probes. The countdown runs only while `runtime::state` is `reconnecting`.
8. **Banner targets.** "Choose Python…" calls `::vmdai::panel::open_settings panel` (the Panel tab has "Python for the runtime"), and "Restart runtime" calls `::vmdai::runtime::stop` and then `ensure`. Both stay within the allowed target names. For an attached runtime that is too old, the banner gives instructions only (§5): it has no button, because ChatVMD never restarts a runtime it did not start.
9. **"About Tcl trust…"** in the status bar's trust menu opens a message box inside `statusbar.tcl`, because no panel target exists for it and plan 09's component guard allows no new `::vmdai::panel::` name.
10. **Extra verbs.** Tests and plan 09 use these beyond the skeleton: `banner::kind`, `banner::toggle_details`, `toolbar::tip_shown`, `toolbar::opt(tip_delay)`, `composer::placeholder_for`, and the `-onaction` option of the toolbar, status bar and banner (the transcript's equivalent is its `on_action` variable).
11. **Test names.** The skeleton's "status texts" is two tcltests, `status_texts` and `status_clicks`, both checked by pytest `test_status_texts`. The skeleton's `::test_*` names are pytest functions of the same name. `test_trust_notice_no_op`, which the skeleton lists under P08-T02, lands in P08-T01 together with the `trust_notice` state key it pins. Some pytest functions check more tcltests than their names say (for example `test_clear_and_menu` also checks `wheel-embeds` and `relayout-widths`, and `test_run_header_footer_expand_and_menus` also checks `row-labels`, `row-click` and `refit-order`), which keeps the spec coverage without new pytest functions. Every wrapper also has a `*_counts` test that fails on any case the named tests do not cover. That makes 103 pytest tests in all, not 100: 47 view-model, 6 theme, 10 transcript, 15 tool rows, 6 snapshot cards, 6 composer, 6 status bar and banner, 4 toolbar, and 3 tclexport. The Plan-specific constraints are updated to 103.
12. **`tclexport`'s partial-failure comment** leaves out the recorder's "(first error line)", because `record` receives no error text. The rest of the rule, including the backslash fix, is the recorder's. `run_tcl` has no header; `chat_tcl` numbers the runs and returns `""` when nothing ran.
13. **Configure in tests.** Tk does not deliver `<Configure>` to the children of the withdrawn test root, so the tests call `transcript::relayout`, `statusbar::_render` and `banner::_relayout` directly. The toolbar fits its title to the bar's width rather than the title label's.
14. **Review Focus 4 follows §2c's fallbacks.** The skeleton says a missing or undecodable thumbnail gives a text card. §2c says a missing thumbnail falls back to `copy -subsample` of the full image, and V7 gives the text card only to a file Tk cannot decode, so `tk85-1` pins the text card and `thumb_fallback` pins the subsampled full image; pytest `test_tk85_1` checks both.
