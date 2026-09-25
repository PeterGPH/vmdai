# ChatVMD Round 1 — Plan 06: M1 plugin core in Tcl

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the plugin's transport and execution layer as testable Tcl modules: config, sched, net (async plus result queue), runtime (launch/attach and the state machine), bridge and executor (ack, pre-check, puts capture). Install through pkgIndex and ~/.vmdrc, and keep ui.tcl with minimal fixes.

**Architecture:** Today's `bridge.tcl` mixes a blocking `http::geturl`, regex JSON parsing, `exec … &` launch and tool execution in one file. This plan splits it into small no-Tk modules loaded in order: `config.tcl` (paths, Python resolution, attach target, `~/.vmdai/plugin.json`, the plugin log), `sched.tcl` (a registry of every `after`, fileevent and http token, so `teardown` can cancel all of them), `net.tcl` (an ASCII JSON encoder, the vendored tcllib json 1.1.2 decoder, `http::geturl -command` calls whose callbacks only capture, clean up and hand off with an `after 0` through `sched`, an epoch that drops stale replies, and the tool-result queue), and `runtime.tcl` (a non-blocking `open |… 2>@1` launch that reads the `VMDAI_READY` line, attach through the token file, shutdown escalation, and the connection state machine with backoff, respawns and one notice per transition). The second half of the plan (P06-T07…T12) rewrites `bridge.tcl` (session, poll pump, routing, working directory) and adds `executor.tcl`, which runs the model's Tcl in the user's own VMD session as the spec designs it (§2d, §2e): the runtime's C1 accident guard, the C2 ack, the C3 whole-command pre-check and stdout capture, so `puts` output reaches the model. The installer adds one line block to the user's own `~/.vmdrc` with their consent, idempotently, with an uninstall path. Every module runs under plain `tclsh` 8.6 with VMD commands stubbed; `tcltest` files in `tests/tcl/` are driven by pytest wrappers through plan 01's `helpers.tcl.run_tcltest`, against a small Python JSON-RPC server (`tests/helpers/fake_rpc_server.py`) and stub runtime processes.

**Tech Stack:** Tcl 8.6 (written to the 8.5-safe subset), `tcltest` 2, VMD 1.9.4a57's `http` 2.9.5, tcllib `json` 1.1.2 (vendored in `plugin/lib/json`); Python 3.9–3.12 standard library + pytest for the wrappers, the fake server and the stub runtimes.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — §2c (Busy state after a reconnect; Wire encoding, "name the cause"), §2d (Callback rule, Registry and teardown, Encoding and decoding, Epoch, Poll pump, Non-blocking launch, Python resolution, Attach mode, Connection state machine, Shutdown, Executor, Snapshot, Working directory), §2e (launch token, token file, attach re-reads it), §2h (Tcl 8.5 lint, the module table, "Stage M1 keeps the existing ui.tcl", Entry points, Menu and install), §3 (Tcl interfaces; RPC rows session.start, tool.ack, tool.command_result, runtime.info, session.set_cwd, runtime.shutdown), §5 (rows: runtime won't start, dies mid-session, restarted or AUTH_FAILED, transport blip, stale runtime, incomplete Tcl, result post fails, Tcl error in the executor, undecodable poll body), §6 (tclsh tests, bridge integration, launch test, Tk golden transcripts, live tests), Part C C2, C3, C5, C6; success criteria S3, S4, S8, S10 and the M1 exit row of §8. Part C wins over Parts A/B where they differ.

**Branch:** `chatvmd-r1-06-m1-plugin-core`, created from `main` after plan 05 (`chatvmd-r1-05-m1-execution-safety`) is merged; plans 01–04 are merged before it.

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

**Plan-specific constraints (Plan 06, Tcl):**

- New plugin files (`plugin/*.tcl` outside `plugin/lib/`) are ASCII only, because VMD `source`s them in the system encoding. Tcl tests build non-ASCII text with `[format %c 0xc5]` rather than literal characters; Python tests use `chr(0xC5)`.
- Namespace state is declared with `variable v` followed by `if {![info exists v]} {…}`, so re-sourcing (`::vmdai::reload`) keeps live state and never orphans a timer. `runtime.tcl` defines `::vmdai::runtime::info`, so inside that namespace every built-in call is spelled `::info`.
- Plugin code never calls a bare `after` with a script, `fileevent` or keeps an http token outside `::vmdai::sched`. The one exception is the blocking sleep `::after 50` (no script, so no timer) inside `runtime::stop -sync`.
- No nested event loops in plugin code: no `vwait`, `update` or synchronous `http::geturl`, except `net::call_sync`, which exists only for the VMD console and tests (§2d). The executor's single `update idletasks` (P06-T08) paints only and runs no scripts from the event queue.
- An `http::geturl -command` callback only captures status, code and body, calls `http::cleanup`, and schedules delivery with `::vmdai::sched::after 0`. Every user callback runs through `net::deliver`, which wraps it in `catch` and logs failures to `~/.vmdai/logs/plugin.log`.
- Each Tcl test file under `tests/tcl/` starts with `::tcltest::configure -verbose {pass body error}`, so every pass prints `++++ <name> PASSED`. Its pytest wrapper runs the file once in a module-scoped fixture through `helpers.tcl.run_tcltest`, checks the totals, and maps each skeleton test name to the tcltest cases it covers with a four-line local `_assert_passed(result, names)`.
- Tests never bind a fixed port: `FakeRpcServer` and the stub runtimes use port 0. Every child process a Tcl test starts is logged and killed by its wrapper, even when the test fails.
- Until P06-T07 and P06-T10 rewrite them, today's `bridge.tcl` and `ui.tcl` keep working: `config.tcl` keeps the legacy names `host`, `port`, `poll_limit`, `runtime_log`, `python_exec` and `runtime_url`, and the new modules are not sourced by `init.tcl` until P06-T07.
- The model's Tcl runs in the user's own VMD session by design (§2d, §2e). This plan adds no new guard of its own: C1 (`tcl_policy`) runs in the runtime (plan 05), and the plugin's part is the C2 ack, the C3 pre-check and output capture (P06-T08).

## Review Focus

- Warnings or tracebacks on the pipe before READY: the READY line must still be found. Owner P06-T05: test_ready_after_noise.
- `puts -nonewline`, `puts stdout` and `puts $fh` to a file channel must pass through correctly. Owner P06-T08: test_puts_variants.
- Model Tcl that calls update or vwait while executing: tool_start is deferred and runs later. Owner P06-T07: test_tool_start_deferred_while_executing.
- reload twice and close/reopen: no orphan timers and no duplicate polls. Owner P06-T09: test_reload_twice_after_info_empty.
- HOME or the Python path contains spaces. Owner P06-T05: test_paths_with_spaces.

---

## File map

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `plugin/lib/json/json.tcl`, `pkgIndex.tcl`, `license.terms` | create | T01 | Vendored tcllib json 1.1.2 |
| `tests/test_tcl_lint.py` | create | T01 | 8.5-safe lint of `plugin/**/*.tcl` (not `lib/`); vendored json check |
| `plugin/config.tcl` | replace (T02), modify (T07) | T02, T07 | Paths, timeouts, Python resolution, attach target, plugin.json, plugin log (T07 drops the legacy names) |
| `plugin/sched.tcl` | create | T02 | Timer/fileevent/http-token registry; `teardown` |
| `tests/tcl/test_sched.tcl`, `tests/test_tcl_sched.py` | create | T02 | sched and config tests (S4) |
| `plugin/net.tcl` | create (T03), modify (T04) | T03, T04 | JSON encode/decode, async transport, `after 0` delivery, epoch, result queue |
| `tests/helpers/fake_rpc_server.py` | create | T03 | Python JSON-RPC server for the Tcl tests |
| `tests/tcl/test_net.tcl`, `tests/test_tcl_net.py` | create | T03 | net tests, S8 |
| `tests/tcl/test_result_queue.tcl`, `tests/test_tcl_result_queue.py` | create | T04 | Result-queue tests |
| `plugin/runtime.tcl` | create (T05), modify (T06) | T05, T06 | Launch, READY, attach, stop; state machine and notices |
| `tests/fixtures/stub_runtime/ready_runtime.py`, `fail_runtime.py` | create | T05 | Stub runtimes for the launch tests |
| `tests/tcl/test_runtime_launch.tcl`, `tests/test_tcl_runtime_launch.py` | create | T05 | Launch tests against real stub processes |
| `tests/tcl/test_state_machine.tcl`, `tests/test_tcl_state_machine.py` | create | T06 | State machine with a fake scheduler (S3) |
| `plugin/bridge.tcl` | replace | T07 | Session, poll pump, routing, working directory |
| `plugin/init.tcl` | modify (T07, T08), replace (T09) | T07–T09 | Sourcing order (T07, T08); package, entry points, menu (T09) |
| `tests/tcl/test_bridge_unit.tcl`, `tests/test_tcl_bridge_unit.py` | create | T07 | Bridge unit tests |
| `plugin/executor.tcl`, `tests/tcl/test_executor.tcl`, `tests/test_tcl_executor.py` | create | T08 | Approve, ack, pre-check, `puts` capture, post (C2, C3, C5) |
| `plugin/pkgIndex.tcl`, `scripts/install_plugin.tcl`, `tests/tcl/test_init.tcl`, `tests/test_tcl_install.py` | create | T09 | Package, entry points, menu, installer |
| `tests/helpers/tk.py`, `tests/tcl/test_ui_min.tcl`, `tests/test_tk_ui_min.py`; `plugin/ui.tcl` | create; replace | T10 | Tk helper; M1 `ui.tcl` fixes and the notice sink |
| `tests/helpers/scripted_runtime.py`, `tests/tcl/driver.tcl`, `tests/tcl/t_race.tcl`, `tests/test_bridge_integration.py` | create | T11 | Bridge integration against a scripted runtime |
| `tests/test_live_vmd.py`, `docs/design/round1/garbling-root-cause.md` | create | T12 | Real-VMD checks (gated on `VMD_AI_VMD_BIN`), the garbling root cause and the `auto` renderer gate |

## How to apply the steps

- "Create" steps give the whole file. "Replace" steps quote the text to find (or name a whole `proc`, from its `proc` line to its closing `}` at column 0) and the new text; apply them with the Edit tool.
- Commands run from `/Users/pinhaogu/Documents/GitHub/vmdai`. `SUITE` means `env -u VMD_AI_PROVIDER python -m pytest tests -q` (expected: `0 failed`, under 60 s). `B` is the passed count Task 0 records; the "Expected" suite lines say `B+n passed`, with the same skipped and xfailed counts as Task 0.
- The Tcl wrappers need a Tcl 8.6 `tclsh` (plan 01's `helpers.tcl` rules). Without one they skip with the reason `no Tcl 8.6 interpreter: …`; the S8 case also needs VMD.app's http 2.9.5. Run this plan on the dev Mac, where both exist.
- Some code blocks contain literal backslash escapes such as `[^\u0000-\u007f]`, `"\\u%04x"` and `{"t\u0009n\u000ar\u000d"}`. Copy them as the ASCII characters shown (backslash, `u`, four hex digits); an editor or tool that turns `\uXXXX` into the character itself breaks the escaper and its tests. After each step that creates or replaces a plugin file, `LC_ALL=C grep -n '[^ -~]' <that file>` must print nothing (today's `bridge.tcl`, `init.tcl` and `ui.tcl` still hold non-ASCII text until P06-T07, T09 and T10 replace them; P06-T10 Step 5 then checks all of `plugin/*.tcl`).

---

### Task 0: Pre-flight — confirm plans 01–05 are merged and their interfaces exist

**Files:** none (read-only checks; nothing is committed).

**Interfaces:**
- Consumes: from plan 01: `helpers.tcl.run_tcl`, `run_tcltest`, `tcl_word`, `json_pkg_dir`, `PLUGIN_JSON_DIR`, `VMD_JSON_DIR`, `REPO`, `TclTestResult` (P01-T03); the hermetic `tests/conftest.py` (P01-T01). From plan 02: `launch.READY_PREFIX`, `token_file_path`, `write_token_file`, `format_ready_line` (P02-T02); `main.py --port 0 --announce --watch-stdin` (P02-T04); ASCII JSON and `/health {ok, pid, version, protocol}` (P02-T01); `RUNTIME_PROTOCOL = 2`. From plan 03: `runtime.info`, `session.set_cwd` (P03-T09). From plan 05: `tool.ack {call_key, state?} -> {proceed, reason?}` (P05-T01), `tool.command_result` by `call_key` answering `{accepted, late, duplicate}` or `TOOL_CALL_UNKNOWN` (P05-T02), `tool_start.metadata.snapshot_path` (P05-T01/T03).
- Produces: branch `chatvmd-r1-06-m1-plugin-core`; the baseline pass count `B`.

- [ ] **Step 1: Cut the branch from an up-to-date main**

```bash
git switch main
git pull --ff-only
git log --oneline -1
git switch -c chatvmd-r1-06-m1-plugin-core
```

Expected: the last command prints `Switched to a new branch 'chatvmd-r1-06-m1-plugin-core'`.

- [ ] **Step 2: Confirm the files and names this plan consumes**

```bash
grep -n "^def run_tcl(\|^def run_tcltest(\|^def tcl_word(\|^def json_pkg_dir(\|^PLUGIN_JSON_DIR = " tests/helpers/tcl.py
grep -n "^READY_PREFIX = \|^def token_file_path(\|^def write_token_file(\|^def format_ready_line(" runtime/vmd_ai_runtime/launch.py
grep -n "ensure_ascii=True" runtime/vmd_ai_runtime/server.py
grep -n "^RUNTIME_PROTOCOL = 2" runtime/vmd_ai_runtime/constants.py
grep -n '"--announce", action="store_true"\|"--watch-stdin", action="store_true"' runtime/main.py
grep -o '"runtime\.info"\|"session\.set_cwd"\|"tool\.ack"\|"runtime\.shutdown"\|"tool\.command_result"' runtime/vmd_ai_runtime/protocol.py | sort -u
grep -n "supports_call_meta = True\|    def ack(self, session_id\|    def post_result(self, session_id" runtime/vmd_ai_runtime/tool_bridge.py
grep -c "TOOL_CALL_UNKNOWN" runtime/vmd_ai_runtime/app.py
grep -c "vmdai_snap_" runtime/vmd_ai_runtime/tool_bridge.py
```

Expected: 5 lines from `tcl.py`; 4 lines from `launch.py`; 1 line each from `server.py` and `constants.py`; 2 lines from `main.py`; the five quoted method names `"runtime.info"`, `"runtime.shutdown"`, `"session.set_cwd"`, `"tool.ack"`, `"tool.command_result"`; 3 lines from `tool_bridge.py`; then two counts of at least `1`. If anything is missing, stop: an earlier plan is not merged.

- [ ] **Step 3: Confirm the READY contract with the real runtime**

The plugin reads exactly this line, so check it once against the merged `main.py` (temp `HOME`, so nothing touches the real `~/.vmdai`):

```bash
HOME="$(mktemp -d)" PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring python - <<'EOF'
import json, subprocess, sys
p = subprocess.Popen([sys.executable, "-u", "runtime/main.py", "--port", "0", "--announce", "--watch-stdin"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
line = p.stdout.readline()
prefix, payload = line.split(" ", 1)
print(prefix, sorted(json.loads(payload)), json.loads(payload)["protocol"])
p.stdin.close()
print("exit", p.wait(timeout=5))
EOF
```

Expected:

```
VMDAI_READY ['launch_token', 'pid', 'port', 'protocol', 'version'] 2
exit 0
```

(`exit 0` within 5 s shows `--watch-stdin` ends the runtime when the plugin's pipe closes.)

- [ ] **Step 4: Confirm the Tcl harness and record the baseline**

```bash
python -m pytest tests/test_tcl_harness.py -q 2>&1 | tail -1
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -1
```

Expected: `7 passed` for the harness (tclsh 8.6.14 and VMD.app's http 2.9.5 found), then a line such as `N passed, S skipped in …s` with `0 failed`, under 60 s. Write `N` down as `B`.

---

### Task 1: P06-T01 — Vendor tcllib json 1.1.2 and the Tcl 8.5 lint

**Files:**
- Create: `plugin/lib/json/json.tcl` (a byte copy of VMD's), `plugin/lib/json/pkgIndex.tcl`, `plugin/lib/json/license.terms`
- Test: `tests/test_tcl_lint.py`

**Interfaces:**
- Consumes: `helpers.tcl.run_tcl(script, *, needs_http=False, needs_json=False, cwd=None, env=None, timeout=60)`, `tcl_word(value)`, `json_pkg_dir()`, `VMD_JSON_DIR` (P01-T03).
- Produces:
  - `plugin/lib/json` provides `json 1.1.2` (only `json`; VMD's `json::write` is not vendored). `helpers.tcl.json_pkg_dir()` now returns it, so every later Tcl test and CI load this copy.
  - `tests/test_tcl_lint.py`: `BANNED: Dict[str, Pattern[str]]` (the eleven spec §2h constructs), `lint_text(text) -> List[Tuple[int, str]]`, `plugin_tcl_files() -> List[Path]` (every `plugin/**/*.tcl` except `plugin/lib/`). Later tasks' new plugin files are linted automatically.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tcl_lint.py`:

```python
"""Tcl 8.5-safe lint for the plugin (spec §2h) and the vendored json 1.1.2 (§2d)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Pattern, Tuple

from helpers import tcl

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
VENDORED = PLUGIN / "lib" / "json"
VMD_JSON_TCL = Path(tcl.VMD_JSON_DIR) / "json.tcl"

# Command-position words: start of a line, or after `;`, `[` or `{`.
_CMD = r"(?:^|[;\[{])\s*"

BANNED: Dict[str, Pattern[str]] = {
    "try": re.compile(_CMD + r"try\s+\{", re.MULTILINE),
    "lmap": re.compile(_CMD + r"lmap\s", re.MULTILINE),
    "string cat": re.compile(r"\bstring\s+cat\b"),
    "dict map": re.compile(r"\bdict\s+map\b"),
    "tailcall": re.compile(r"\btailcall\b"),
    "coroutine": re.compile(r"\bcoroutine\b"),
    "oo::": re.compile(r"\boo::"),
    "zlib": re.compile(r"\bzlib\b"),
    "binary encode|decode": re.compile(r"\bbinary\s+(?:encode|decode)\b"),
    "lsort -stride": re.compile(r"\blsort\b[^\n]*\s-stride\b"),
    "chan pipe": re.compile(r"\bchan\s+pipe\b"),
}


def _code_lines(text: str) -> str:
    """The file with whole-line comments blanked (line numbers are kept)."""
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def lint_text(text: str) -> List[Tuple[int, str]]:
    """(line number, banned name) for every banned construct in ``text``."""
    code = _code_lines(text)
    hits = []
    for name, pattern in BANNED.items():
        for match in pattern.finditer(code):
            hits.append((code.count("\n", 0, match.start()) + 1, name))
    return sorted(hits)


def plugin_tcl_files() -> List[Path]:
    return sorted(p for p in PLUGIN.rglob("*.tcl") if VENDORED not in p.parents)


def test_lint_patterns_catch_examples():
    bad = {
        "try {set x 1} on error {e} {}": "try",
        "set l [lmap x $xs {incr x}]": "lmap",
        "set s [string cat a b]": "string cat",
        "dict map {k v} $d {set v}": "dict map",
        "proc f {} { tailcall g }": "tailcall",
        "coroutine c body": "coroutine",
        "oo::class create Foo": "oo::",
        "zlib deflate $data": "zlib",
        "binary encode base64 $data": "binary encode|decode",
        "lsort -stride 2 $pairs": "lsort -stride",
        "chan pipe": "chan pipe",
    }
    for text, name in bad.items():
        assert [n for _, n in lint_text(text)] == [name], text
    good = [
        'puts "please try again"',
        "set retry 1",
        "# coroutine and zlib in a comment",
        "    # try { } in an indented comment",
        "lsort -unique $xs",
        "string map {a b} $s",
        "dict for {k v} $d {}",
        "binary format a2 xy",
        "set entry [lindex $row 0]",
    ]
    for text in good:
        assert lint_text(text) == [], text


def test_no_banned_constructs():
    files = plugin_tcl_files()
    assert files, "no plugin Tcl files found"
    assert all("lib" not in p.relative_to(PLUGIN).parts[:1] for p in files)
    problems = []
    for path in files:
        for line, name in lint_text(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(REPO)}:{line}: {name}")
    assert problems == []


def test_vendored_json_loads_exact_112():
    assert (VENDORED / "json.tcl").is_file()
    assert (VENDORED / "pkgIndex.tcl").is_file()
    terms = (VENDORED / "license.terms").read_text(encoding="utf-8")
    assert "tcllib" in terms and "hereby grant permission" in terms
    assert tcl.json_pkg_dir() == str(VENDORED)
    proc = tcl.run_tcl(
        f"lappend auto_path {tcl.tcl_word(str(VENDORED))}\n"
        "puts [package require -exact json 1.1.2]\n"
        "puts [package ifneeded json 1.1.2]\n"
        'set d [json::json2dict {{"t": "\\u00c5\\u2192\\u00b0", "n": [1, 2]}}]\n'
        'puts [list [expr {[dict get $d t] eq "\\u00c5\\u2192\\u00b0"}] [dict get $d n]]\n'
    )
    assert proc.returncode == 0, proc.stderr
    version, ifneeded, decoded = proc.stdout.splitlines()
    assert version == "1.1.2"
    assert str(VENDORED / "json.tcl") in ifneeded
    assert decoded == "1 {1 2}"
    if VMD_JSON_TCL.is_file():
        vendored = hashlib.sha256((VENDORED / "json.tcl").read_bytes()).hexdigest()
        assert vendored == hashlib.sha256(VMD_JSON_TCL.read_bytes()).hexdigest()
```

The patterns look for command position (start of a line, or after `;`, `[` or `{`) where a word is also common English (`try`, `lmap`), and whole-line comments are blanked first, so `puts "please try again"` and `# coroutine note` pass. `test_lint_patterns_catch_examples` pins both directions.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_lint.py -q`
Expected: `1 failed, 2 passed`; the failure is `test_vendored_json_loads_exact_112` at `assert (VENDORED / "json.tcl").is_file()`. (The lint already passes on today's four plugin files.)

- [ ] **Step 3: Copy VMD's json.tcl unchanged**

```bash
mkdir -p plugin/lib/json
cp /Applications/VMD.app/Contents/vmd/plugins/noarch/tcl/json1.0/json.tcl plugin/lib/json/json.tcl
shasum -a 256 plugin/lib/json/json.tcl
```

Expected: `cd4353839ce2b237aee7486bb5123ed1fc3ea3a6306e1089451d81b0da18cc35  plugin/lib/json/json.tcl` (320 lines, `package provide json 1.1.2`).

- [ ] **Step 4: Create `plugin/lib/json/pkgIndex.tcl`**

```tcl
# Vendored tcllib json 1.1.2 (ChatVMD, plugin/lib/json). Only json itself is
# vendored; VMD's json::write 1.0.2 is not needed by the plugin.
if {![package vsatisfies [package provide Tcl] 8.4]} {return}
package ifneeded json 1.1.2 [list source [file join $dir json.tcl]]
```

- [ ] **Step 5: Create `plugin/lib/json/license.terms`**

The provenance note, then the BSD-style Tcl license verbatim (the same text as `VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/license.terms`):

```text
plugin/lib/json: tcllib's json package, version 1.1.2
======================================================

json.tcl is an unmodified copy of the file VMD 1.9.4a57 ships as
VMD.app/Contents/vmd/plugins/noarch/tcl/json1.0/json.tcl (tcllib json 1.1.2).
pkgIndex.tcl is ChatVMD's own and declares only `json 1.1.2`.

tcllib is distributed under the BSD-style Tcl license. tcllib's own
license.terms names "Ajuba Solutions and other parties" as the copyright
holders; the terms are those of Tcl, reproduced verbatim below from
VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/license.terms.

------------------------------------------------------------------------

This software is copyrighted by the Regents of the University of
California, Sun Microsystems, Inc., Scriptics Corporation, ActiveState
Corporation and other parties.  The following terms apply to all files
associated with the software unless explicitly disclaimed in
individual files.

The authors hereby grant permission to use, copy, modify, distribute,
and license this software and its documentation for any purpose, provided
that existing copyright notices are retained in all copies and that this
notice is included verbatim in any distributions. No written agreement,
license, or royalty fee is required for any of the authorized uses.
Modifications to this software may be copyrighted by their authors
and need not follow the licensing terms described here, provided that
the new terms are clearly indicated on the first page of each file where
they apply.

IN NO EVENT SHALL THE AUTHORS OR DISTRIBUTORS BE LIABLE TO ANY PARTY
FOR DIRECT, INDIRECT, SPECIAL, INCIDENTAL, OR CONSEQUENTIAL DAMAGES
ARISING OUT OF THE USE OF THIS SOFTWARE, ITS DOCUMENTATION, OR ANY
DERIVATIVES THEREOF, EVEN IF THE AUTHORS HAVE BEEN ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

THE AUTHORS AND DISTRIBUTORS SPECIFICALLY DISCLAIM ANY WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.  THIS SOFTWARE
IS PROVIDED ON AN "AS IS" BASIS, AND THE AUTHORS AND DISTRIBUTORS HAVE
NO OBLIGATION TO PROVIDE MAINTENANCE, SUPPORT, UPDATES, ENHANCEMENTS, OR
MODIFICATIONS.

GOVERNMENT USE: If you are acquiring this software on behalf of the
U.S. government, the Government shall have only "Restricted Rights"
in the software and related documentation as defined in the Federal
Acquisition Regulations (FARs) in Clause 52.227.19 (c) (2).  If you
are acquiring the software on behalf of the Department of Defense, the
software shall be classified as "Commercial Computer Software" and the
Government shall have only "Restricted Rights" as defined in Clause
252.227-7014 (b) (3) of DFARs.  Notwithstanding the foregoing, the
authors grant the U.S. Government and others acting in its behalf
permission to use and distribute the software in accordance with the
terms specified in this license.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_lint.py tests/test_tcl_harness.py -q`
Expected: `10 passed` (the harness's `test_json_112_loads` now loads the vendored copy).

- [ ] **Step 7: Run the suite**

Run: `SUITE`
Expected: `B+3 passed`, `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add plugin/lib/json/json.tcl plugin/lib/json/pkgIndex.tcl plugin/lib/json/license.terms tests/test_tcl_lint.py
git commit -F - <<'MSG'
feat(plugin): vendor tcllib json 1.1.2 and add the Tcl 8.5 lint

plugin/lib/json is a byte copy of the json.tcl VMD 1.9.4a57 ships, with
its own pkgIndex and the BSD-style license. test_tcl_lint.py bans the
8.6-only constructs from spec 2h in plugin/**/*.tcl outside lib/.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 2: P06-T02 — config.tcl and sched.tcl

**Files:**
- Modify (replace whole file): `plugin/config.tcl`
- Create: `plugin/sched.tcl`
- Test: `tests/tcl/test_sched.tcl`, `tests/test_tcl_sched.py`

**Interfaces:**
- Consumes: `helpers.tcl.run_tcltest(test_file, *, needs_http=False, needs_json=False, env=None, timeout=120, prelude='') -> TclTestResult`, `REPO`, `TclTestResult(passed, failed, skipped, output)` (P01-T03); `plugin/lib/json` (P06-T01).
- Produces (`::vmdai::config`):
  - variables `plugin_dir` (absolute, from `info script`), `runtime_main` (`<plugin_dir>/../runtime/main.py`, normalised), `request_timeout_ms 3000`, `poll_ms 250`, `ready_timeout_ms 20000`, `shutdown_kill_ms 1500`, `plugin_defaults` (the plugin.json defaults dict)
  - `home -> path` (normalised `$env(HOME)`); `plugin_json_path`; `log_path` (`~/.vmdai/logs/runtime.log`, the runtime's log for "Open log"); `plugin_log_path` (`~/.vmdai/logs/plugin.log`); `token_file_path port` (`~/.vmdai/run/runtime-<port>.json`)
  - `log msg` — appends `YYYY-MM-DD HH:MM:SS msg` to the plugin log, rotates at 1 MB to `plugin.log.1`, never throws
  - `load_plugin_settings -> dict` — defaults `version 1 python "" appearance system expand_steps 0 geometry ""`, overlaid with every key of `~/.vmdai/plugin.json`; an unreadable file logs and returns the defaults. JSON `true`/`false` come back as the strings `true`/`false`.
  - `save_plugin_settings dict -> path` — writes ASCII JSON atomically (temp file + rename); `version` as an integer, `expand_steps` as a JSON boolean, every other key as a string; errors propagate
  - `resolve_python -> path|""` — `VMD_AI_PYTHON`, else plugin.json `python`, else `auto_execok python3`; a bare name goes through `auto_execok`, a path is `file normalize`d (a missing file is still returned, so the launch fails visibly)
  - `attach_target -> ""|{host port}` — from `VMD_AI_ATTACH=host:port`, or `host` with the port from `VMD_AI_PORT` (else 8765); host must be `127.0.0.1` or `localhost` (lower-cased); errors `VMD_AI_ATTACH …` on a malformed value
  - `require_json -> version` — loads json 1.1.2 from `<plugin_dir>/lib/json` unless a json package is already present
  - `_json_quote s` — one ASCII JSON string literal (same escaping as `net::json_string`, P06-T03; config loads before net)
  - legacy names kept for today's `bridge.tcl` until P06-T07: `host`, `port`, `poll_limit`, `runtime_log`, `python_exec`, `runtime_url`
- Produces (`::vmdai::sched`):
  - `after ms script -> id`, `after_idle script -> id` (ids look like `vmdai_sched#12`; the script runs at global level, and an error in it is logged, not raised); `cancel id` (unknown or empty ids are ignored); `pending -> ids` (sorted; ids that have neither fired nor been cancelled)
  - `fileevent chan event script` (an empty script unregisters); `track_http token`; `untrack_http token`
  - `teardown` — resets every tracked http token (its `-command` callback runs; any `sched::after` it makes while teardown runs returns `""`), removes every fileevent, cancels every timer. Afterwards `after info` is empty when the plugin made every timer through sched (S4).

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_sched.tcl`:

```tcl
# tests/tcl/test_sched.tcl - sched registry and config (P06-T02, S4).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}
package require http

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]

proc wait_for {script {ms 3000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 10 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

# A listener that accepts and never answers, so http tokens stay open.
proc silent_server {} {
    set srv [socket -server {apply {{ch addr port} {lappend ::held $ch}}} -myaddr 127.0.0.1 0]
    return [list $srv [lindex [fconfigure $srv -sockname] 2]]
}

test sched-teardown-1 {teardown cancels timers, idle callbacks, fileevents and http tokens} -body {
    set ::held {}
    lassign [silent_server] srv port
    set ::cb_calls 0
    set tok [http::geturl http://127.0.0.1:$port/x -timeout 60000 \
        -command {apply {{t} {incr ::cb_calls; ::vmdai::sched::after 0 {set ::never 5}; http::cleanup $t}}}]
    ::vmdai::sched::track_http $tok
    wait_for {expr {[llength $::held] == 1}}
    ::vmdai::sched::after 60000 {set ::never 1}
    ::vmdai::sched::after 30000 {set ::never 2}
    ::vmdai::sched::after_idle {set ::never 3}
    lassign [chan pipe] rd wr
    ::vmdai::sched::fileevent $rd readable {set ::never 4}
    set before [list [llength [after info]] [llength [::vmdai::sched::pending]]]
    ::vmdai::sched::teardown
    set after_td [list [after info] [::vmdai::sched::pending] [fileevent $rd readable] \
        [info exists $tok] $::cb_calls]
    close $rd; close $wr; close $srv
    foreach ch $::held { close $ch }
    list $before $after_td [info exists ::never]
} -result {{4 3} {{} {} {} 0 1} 0}

test sched-teardown-2 {re-sourcing keeps the registry, so teardown after a reload still cancels} -body {
    set id [::vmdai::sched::after 60000 {set ::never 6}]
    source [file join $plugin sched.tcl]
    set kept [expr {$id in [::vmdai::sched::pending]}]
    ::vmdai::sched::teardown
    list $kept [after info] [::vmdai::sched::pending]
} -result {1 {} {}}

test sched-fire-1 {a fired timer runs at global level and leaves pending} -body {
    set ::fired {}
    set id [::vmdai::sched::after 10 {lappend ::fired [info level]}]
    set live [expr {$id in [::vmdai::sched::pending]}]
    wait_for {expr {$::fired ne ""}}
    list $live $::fired [::vmdai::sched::pending] [after info]
} -result {1 0 {} {}}

test sched-cancel-1 {cancel removes a timer; unknown and empty ids are ignored} -body {
    set id [::vmdai::sched::after 60000 {set ::never 7}]
    ::vmdai::sched::cancel $id
    ::vmdai::sched::cancel $id
    ::vmdai::sched::cancel ""
    ::vmdai::sched::cancel vmdai_sched#999999
    list [::vmdai::sched::pending] [after info]
} -result {{} {}}

test sched-throw-1 {a failing timer is logged, not raised, and later timers still run} -body {
    set ::ran 0
    ::vmdai::sched::after 0 {error "boom from a timer"}
    ::vmdai::sched::after 20 {set ::ran 1}
    wait_for {expr {$::ran == 1}}
    list $::ran [string match "*boom from a timer*" [plugin_log]] [::vmdai::sched::pending]
} -result {1 1 {}}

test sched-closing-1 {nothing can be scheduled while teardown runs} -body {
    set ::inner none
    set ::held {}
    lassign [silent_server] srv port
    set tok [http::geturl http://127.0.0.1:$port/y -timeout 60000 \
        -command {apply {{t} {set ::inner [::vmdai::sched::after 0 {set ::never 8}]; http::cleanup $t}}}]
    ::vmdai::sched::track_http $tok
    wait_for {expr {[llength $::held] == 1}}
    ::vmdai::sched::teardown
    close $srv
    foreach ch $::held { close $ch }
    list $::inner [after info] [expr {[::vmdai::sched::after 0 {set ::ok 1}] ne ""}]
} -cleanup {::vmdai::sched::teardown} -result {{} {} 1}

test sched-fileevent-1 {an empty script unregisters a fileevent} -body {
    lassign [chan pipe] rd wr
    ::vmdai::sched::fileevent $rd readable {set ::never 9}
    set on [fileevent $rd readable]
    ::vmdai::sched::fileevent $rd readable {}
    set r [list $on [fileevent $rd readable] [array names ::vmdai::sched::fevents]]
    close $rd; close $wr
    set r
} -result {{set ::never 9} {} {}}

test config-python-1 {VMD_AI_PYTHON wins, then plugin.json, then python3 on PATH} -setup {
    set saved_path $::env(PATH)
    set bin [file join $::env(HOME) "bin dir"]
    file mkdir $bin
    foreach name {python3 envpy} {
        set fh [open [file join $bin $name] w]; puts $fh "#!/bin/sh"; close $fh
        file attributes [file join $bin $name] -permissions 0755
    }
    set ::env(PATH) "$bin:/usr/bin:/bin"
    unset -nocomplain ::auto_execs
    unset -nocomplain ::env(VMD_AI_PYTHON)
    file delete -force [::vmdai::config::plugin_json_path]
} -body {
    set r {}
    lappend r [expr {[::vmdai::config::resolve_python] eq [file normalize [file join $bin python3]]}]
    ::vmdai::config::save_plugin_settings [dict create version 1 python /opt/json/python3]
    lappend r [::vmdai::config::resolve_python]
    set ::env(VMD_AI_PYTHON) /opt/env/python3
    lappend r [::vmdai::config::resolve_python]
    set ::env(VMD_AI_PYTHON) envpy
    lappend r [expr {[::vmdai::config::resolve_python] eq [file normalize [file join $bin envpy]]}]
    set r
} -cleanup {
    set ::env(PATH) $saved_path
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
    file delete -force [::vmdai::config::plugin_json_path]
} -result {1 /opt/json/python3 /opt/env/python3 1}

test config-python-2 {a relative path is made absolute; nothing found gives ""} -setup {
    set saved_path $::env(PATH)
    set saved_pwd [pwd]
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
} -body {
    cd $::env(HOME)
    set ::env(VMD_AI_PYTHON) ./venv/bin/python
    set rel [::vmdai::config::resolve_python]
    unset ::env(VMD_AI_PYTHON)
    set ::env(PATH) [file join $::env(HOME) empty]
    unset -nocomplain ::auto_execs
    list [expr {$rel eq [file join [file normalize $::env(HOME)] venv bin python]}] \
        [::vmdai::config::resolve_python]
} -cleanup {
    cd $saved_pwd
    set ::env(PATH) $saved_path
    unset -nocomplain ::auto_execs ::env(VMD_AI_PYTHON)
} -result {1 {}}

test config-attach-1 {VMD_AI_ATTACH host:port, bare host with VMD_AI_PORT, unset} -body {
    set r {}
    unset -nocomplain ::env(VMD_AI_ATTACH) ::env(VMD_AI_PORT)
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) 127.0.0.1:8765
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) LOCALHOST:09001
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_ATTACH) localhost
    lappend r [::vmdai::config::attach_target]
    set ::env(VMD_AI_PORT) 18765
    lappend r [::vmdai::config::attach_target]
    set r
} -cleanup {unset -nocomplain ::env(VMD_AI_ATTACH) ::env(VMD_AI_PORT)} \
  -result {{} {127.0.0.1 8765} {localhost 9001} {localhost 8765} {localhost 18765}}

test config-attach-2 {malformed or non-loopback VMD_AI_ATTACH is an error} -body {
    set r {}
    foreach value {127.0.0.1:abc 10.0.0.2:8765 attacker.example:8765 127.0.0.1:0 127.0.0.1:70000 :8765} {
        set ::env(VMD_AI_ATTACH) $value
        lappend r [catch {::vmdai::config::attach_target} msg] [string match VMD_AI_ATTACH* $msg]
    }
    set r
} -cleanup {unset -nocomplain ::env(VMD_AI_ATTACH)} -result {1 1 1 1 1 1 1 1 1 1 1 1}

test config-json-1 {plugin.json: defaults, round trip, ASCII on disk, broken file} -body {
    file delete -force [::vmdai::config::plugin_json_path]
    set defaults [::vmdai::config::load_plugin_settings]
    ::vmdai::config::save_plugin_settings [dict create version 1 \
        python "/Users/a b/[format %c 0xc5]/py\"thon" appearance dark expand_steps 1 geometry 600x700+1+1]
    set fh [open [::vmdai::config::plugin_json_path] rb]; set raw [read $fh]; close $fh
    set back [::vmdai::config::load_plugin_settings]
    set fh [open [::vmdai::config::plugin_json_path] w]; puts $fh "\{not json"; close $fh
    set broken [::vmdai::config::load_plugin_settings]
    list $defaults [regexp {^[\x20-\x7e]*$} $raw] \
        [expr {[dict get $back python] eq "/Users/a b/[format %c 0xc5]/py\"thon"}] \
        [dict get $back expand_steps] [dict get $back geometry] [dict get $broken appearance]
} -cleanup {file delete -force [::vmdai::config::plugin_json_path]} \
  -result {{version 1 python {} appearance system expand_steps 0 geometry {}} 1 1 true 600x700+1+1 system}

cleanupTests
```

Create `tests/test_tcl_sched.py`:

```python
"""sched.tcl registry and config.tcl (P06-T02; spec §2d, S4). Runs tests/tcl/test_sched.tcl."""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_sched.tcl"
TOTAL = 12


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_teardown_empties_after_info(result):
    _assert_passed(result, ["sched-teardown-1", "sched-teardown-2"])


def test_resource_no_orphans(result):
    _assert_passed(result, ["sched-fire-1", "sched-cancel-1", "sched-throw-1",
                            "sched-closing-1", "sched-fileevent-1"])


def test_resolve_python_order(result):
    _assert_passed(result, ["config-python-1", "config-python-2"])


def test_attach_target_parse(result):
    _assert_passed(result, ["config-attach-1", "config-attach-2"])


def test_plugin_json_round_trip(result):
    _assert_passed(result, ["config-json-1"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_sched.py -q`
Expected: `6 failed`; the output shows `couldn't read file ".../plugin/sched.tcl": no such file or directory` and `assert (0, 1) == (12, 0)` (run_tcltest counts a file that dies before its summary as one failure).

- [ ] **Step 3: Replace `plugin/config.tcl`**

Replace the whole file with:

```tcl
# config.tcl - paths, Python resolution, attach target, plugin.json, logs
# (spec 2d, 2h). No Tk. Loaded first; the other modules call into it.

namespace eval ::vmdai::config {
    variable plugin_dir [file dirname [file normalize [info script]]]
    variable runtime_main [file normalize [file join $plugin_dir .. runtime main.py]]

    # Timeouts and intervals (ms).
    variable request_timeout_ms 3000
    variable poll_ms 250
    variable ready_timeout_ms 20000
    variable shutdown_kill_ms 1500

    # plugin.json defaults (spec 2f Files).
    variable plugin_defaults [dict create version 1 python "" appearance system \
        expand_steps 0 geometry ""]

    # Legacy names read by the M1 bridge.tcl until P06-T07 rewrites it.
    variable host "127.0.0.1"
    variable port 8765
    variable poll_limit 80
    variable runtime_log [file normalize [file join $plugin_dir .. runtime runtime.log]]
    if {[info exists ::env(VMD_AI_PYTHON)]} {
        variable python_exec $::env(VMD_AI_PYTHON)
    } else {
        variable python_exec "python3"
    }
}

proc ::vmdai::config::runtime_url {} {
    variable host
    variable port
    return "http://${host}:${port}"
}

proc ::vmdai::config::home {} {
    if {[info exists ::env(HOME)] && $::env(HOME) ne ""} {
        return [file normalize $::env(HOME)]
    }
    return [file normalize ~]
}

proc ::vmdai::config::plugin_json_path {} {
    return [file join [home] .vmdai plugin.json]
}

proc ::vmdai::config::log_path {} {
    return [file join [home] .vmdai logs runtime.log]
}

proc ::vmdai::config::plugin_log_path {} {
    return [file join [home] .vmdai logs plugin.log]
}

proc ::vmdai::config::token_file_path {port} {
    return [file join [home] .vmdai run runtime-$port.json]
}

# Append one timestamped line to ~/.vmdai/logs/plugin.log. Never throws.
proc ::vmdai::config::log {msg} {
    catch {
        set path [plugin_log_path]
        file mkdir [file dirname $path]
        if {[file exists $path] && [file size $path] > 1048576} {
            file rename -force $path $path.1
        }
        set fh [open $path a]
        fconfigure $fh -encoding utf-8 -translation lf
        puts $fh "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $msg"
        close $fh
    }
    return
}

# Load json 1.1.2 from plugin/lib/json unless some json is already loaded.
proc ::vmdai::config::require_json {} {
    variable plugin_dir
    if {![catch {package present json} version]} {
        return $version
    }
    set dir [file join $plugin_dir lib json]
    if {[lsearch -exact $::auto_path $dir] < 0} {
        lappend ::auto_path $dir
    }
    return [package require -exact json 1.1.2]
}

# One JSON string literal, ASCII only. Same escaping as net::json_string
# (P06-T03); kept here because config.tcl loads before net.tcl.
proc ::vmdai::config::_json_quote {s} {
    set map [list "\\" "\\\\" "\"" "\\\""]
    for {set i 0} {$i < 32} {incr i} {
        lappend map [format %c $i] [format "\\u%04x" $i]
    }
    set s [string map $map $s]
    if {[regexp {[^\u0000-\u007f]} $s]} {
        set wide {}
        foreach ch [lsort -unique [regexp -all -inline {[^\u0000-\u007f]} $s]] {
            lappend wide $ch [format "\\u%04x" [scan $ch %c]]
        }
        set s [string map $wide $s]
    }
    return "\"$s\""
}

proc ::vmdai::config::load_plugin_settings {} {
    variable plugin_defaults
    set settings $plugin_defaults
    set path [plugin_json_path]
    if {![file exists $path]} {
        return $settings
    }
    if {[catch {
        set fh [open $path r]
        fconfigure $fh -encoding utf-8
        set text [read $fh]
        close $fh
        require_json
        set decoded [::json::json2dict $text]
        dict size $decoded
    } err]} {
        log "plugin.json unreadable, using defaults: $err"
        return $settings
    }
    dict for {key value} $decoded {
        dict set settings $key $value
    }
    return $settings
}

proc ::vmdai::config::save_plugin_settings {settings} {
    set parts {}
    dict for {key value} $settings {
        switch -- $key {
            version {
                if {![string is integer -strict $value]} { set value 1 }
                set json $value
            }
            expand_steps {
                set json [expr {[string is true -strict $value] ? "true" : "false"}]
            }
            default {
                set json [_json_quote $value]
            }
        }
        lappend parts "[_json_quote $key]:$json"
    }
    set path [plugin_json_path]
    file mkdir [file dirname $path]
    set tmp "$path.[pid].tmp"
    set fh [open $tmp w]
    fconfigure $fh -encoding ascii -translation lf
    puts -nonewline $fh "\{[join $parts ,]\}"
    close $fh
    file rename -force $tmp $path
    return $path
}

# Python for the owned runtime: VMD_AI_PYTHON, then plugin.json python, then
# `auto_execok python3`; returned absolute, or "" when none is found.
proc ::vmdai::config::resolve_python {} {
    set candidates {}
    if {[info exists ::env(VMD_AI_PYTHON)] && [string trim $::env(VMD_AI_PYTHON)] ne ""} {
        lappend candidates [string trim $::env(VMD_AI_PYTHON)]
    } else {
        set configured ""
        catch {set configured [string trim [dict get [load_plugin_settings] python]]}
        if {$configured ne ""} {
            lappend candidates $configured
        }
    }
    lappend candidates python3
    foreach candidate $candidates {
        if {[file pathtype $candidate] eq "relative" && [llength [file split $candidate]] == 1} {
            set found [auto_execok $candidate]
            if {$found ne ""} {
                return [file normalize [lindex $found 0]]
            }
            continue
        }
        return [file normalize $candidate]
    }
    return ""
}

# VMD_AI_ATTACH=host:port (or host, with the port from VMD_AI_PORT, else 8765).
# Returns "" when unset, else {host port}; errors on a malformed value.
proc ::vmdai::config::attach_target {} {
    if {![info exists ::env(VMD_AI_ATTACH)] || [string trim $::env(VMD_AI_ATTACH)] eq ""} {
        return ""
    }
    set value [string trim $::env(VMD_AI_ATTACH)]
    if {[regexp {^([^:]+):([0-9]+)$} $value -> host port]} {
        # explicit port
    } elseif {[regexp {^[^:]+$} $value]} {
        set host $value
        set port 8765
        if {[info exists ::env(VMD_AI_PORT)] && [string is integer -strict $::env(VMD_AI_PORT)]} {
            set port $::env(VMD_AI_PORT)
        }
    } else {
        error "VMD_AI_ATTACH must be host:port (got \"$value\")"
    }
    set host [string tolower $host]
    if {$host ni {127.0.0.1 localhost}} {
        error "VMD_AI_ATTACH must name 127.0.0.1 or localhost (got \"$value\")"
    }
    scan $port %d port
    if {$port < 1 || $port > 65535} {
        error "VMD_AI_ATTACH port out of range (got \"$value\")"
    }
    return [list $host $port]
}
```

- [ ] **Step 4: Create `plugin/sched.tcl`**

```tcl
# sched.tcl - registry of every timer, fileevent and http token the plugin
# creates, so teardown can cancel all of them (spec 2d, S4). No Tk.

namespace eval ::vmdai::sched {
    variable seq
    if {![info exists seq]} { set seq 0 }
    # timers(<id>) = {<Tcl after id> <script>}
    variable timers
    if {![info exists timers]} { array set timers {} }
    # fevents(<chan>,<event>) = {<chan> <event>}
    variable fevents
    if {![info exists fevents]} { array set fevents {} }
    # tokens(<http token>) = 1
    variable tokens
    if {![info exists tokens]} { array set tokens {} }
    # Set while teardown runs: new timers are refused.
    variable closing
    if {![info exists closing]} { set closing 0 }
}

proc ::vmdai::sched::_log {msg} {
    catch {::vmdai::config::log "sched: $msg"}
}

proc ::vmdai::sched::_add {when script} {
    variable seq
    variable timers
    variable closing
    if {$closing} {
        return ""
    }
    set id "vmdai_sched#[incr seq]"
    set tcl_id [::after {*}$when [list ::vmdai::sched::_fire $id]]
    set timers($id) [list $tcl_id $script]
    return $id
}

# Run $script at global level after $ms; returns an id for cancel/pending.
proc ::vmdai::sched::after {ms script} {
    return [_add [list $ms] $script]
}

proc ::vmdai::sched::after_idle {script} {
    return [_add [list idle] $script]
}

proc ::vmdai::sched::_fire {id} {
    variable timers
    if {![info exists timers($id)]} {
        return
    }
    set script [lindex $timers($id) 1]
    unset timers($id)
    if {[catch {uplevel #0 $script} err]} {
        _log "timer $id failed: $err\n$::errorInfo"
    }
}

proc ::vmdai::sched::cancel {id} {
    variable timers
    if {$id eq "" || ![info exists timers($id)]} {
        return
    }
    catch {::after cancel [lindex $timers($id) 0]}
    unset timers($id)
}

# Ids from after/after_idle that have neither fired nor been cancelled.
proc ::vmdai::sched::pending {} {
    variable timers
    return [lsort -dictionary [array names timers]]
}

# Register (or, with an empty script, remove) a fileevent handler.
proc ::vmdai::sched::fileevent {chan event script} {
    variable fevents
    ::fileevent $chan $event $script
    if {$script eq ""} {
        unset -nocomplain fevents($chan,$event)
    } else {
        set fevents($chan,$event) [list $chan $event]
    }
    return
}

proc ::vmdai::sched::track_http {token} {
    variable tokens
    set tokens($token) 1
    return
}

proc ::vmdai::sched::untrack_http {token} {
    variable tokens
    unset -nocomplain tokens($token)
    return
}

# Cancel every registered resource. `stop` and `reload` call this.
proc ::vmdai::sched::teardown {} {
    variable timers
    variable fevents
    variable tokens
    variable closing
    set closing 1
    foreach token [array names tokens] {
        unset -nocomplain tokens($token)
        # reset runs the token's -command callback, which may try to
        # schedule a delivery; `closing` makes that a no-op.
        catch {::http::reset $token}
        catch {::http::cleanup $token}
    }
    foreach key [array names fevents] {
        foreach {chan event} $fevents($key) break
        catch {::fileevent $chan $event {}}
        unset fevents($key)
    }
    foreach id [array names timers] {
        catch {::after cancel [lindex $timers($id) 0]}
        unset timers($id)
    }
    set closing 0
    return
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_sched.py tests/test_tcl_lint.py -q`
Expected: `9 passed`.

- [ ] **Step 6: Check that today's bridge still finds its config names**

```bash
TCLSH="$(PYTHONPATH=tests python -c 'from helpers.tcl import find_tclsh; print(find_tclsh())')"
printf 'source plugin/config.tcl\nputs [::vmdai::config::runtime_url]\nputs $::vmdai::config::poll_limit\nputs [file tail $::vmdai::config::runtime_main]\n' | "$TCLSH"
```

Expected:

```
http://127.0.0.1:8765
80
main.py
```

- [ ] **Step 7: Run the suite**

Run: `SUITE`
Expected: `B+9 passed`, `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add plugin/config.tcl plugin/sched.tcl tests/tcl/test_sched.tcl tests/test_tcl_sched.py
git commit -F - <<'MSG'
feat(plugin): config.tcl paths/python/attach/plugin.json and the sched registry

config.tcl resolves Python (VMD_AI_PYTHON, plugin.json, python3 on PATH),
parses VMD_AI_ATTACH, reads and writes ~/.vmdai/plugin.json and logs to
~/.vmdai/logs/plugin.log. sched.tcl records every timer, fileevent and
http token so teardown leaves `after info` empty (S4). Legacy config
names stay until the bridge rewrite.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 3: P06-T03 — net.tcl: ASCII escaper, async call, after-0 delivery, epoch

**Files:**
- Create: `plugin/net.tcl`
- Create: `tests/helpers/fake_rpc_server.py`
- Test: `tests/tcl/test_net.tcl`, `tests/test_tcl_net.py`

**Interfaces:**
- Consumes: `::vmdai::sched::after`, `track_http`, `untrack_http`, `pending`, `teardown`; `::vmdai::config::require_json`, `log`, `request_timeout_ms`, `_json_quote` (P06-T02); `plugin/lib/json` (P06-T01); the runtime's ASCII JSON replies (P02-T01); `helpers.tcl.run_tcl`, `run_tcltest`, `tcl_word` (P01-T03).
- Produces (`::vmdai::net`):
  - `configure ?-base_url u? ?-session_id id? ?-session_token t?` — with no arguments returns `{-base_url … -session_id … -session_token …}`
  - `json_string s` — one ASCII JSON string literal (`\uXXXX` for control and non-ASCII characters)
  - `encode_params pairs` — `pairs` is a flat list of triples `name type value`, type `s` string, `i` integer (`^-?(0|[1-9][0-9]*)$`), `b` boolean (`true`/`false`), `j` JSON text inserted verbatim; returns one compact object with keys in order, e.g. `[list a s x n i 3 f b 1 o j {{"k":1}}]` gives `{"a":"x","n":3,"f":true,"o":{"k":1}}`; errors on a bad value, an unknown type or a list whose length is not a multiple of 3
  - `decode body -> dict` — errors unless the body is one JSON object
  - `call method params callback ?-timeout ms? ?-session bool? -> request id` — POST `<base_url>/rpc`. `-session` defaults to 1 for every method except `session.start`; with a configured session it prepends `session_id s <id>` and sends `X-Session-Token`. Default timeouts: 3000 ms; `chat.events.poll` `wait_ms`+3000; `models.list`, `provider.test` 10000; `runtime.shutdown` 1500. The callback runs later (never inside `call`) as `{*}$callback ok $result`, `{*}$callback rpc_error $code $message $data` or `{*}$callback transport $reason`. An HTTP 403 with a JSON error body is `rpc_error FORBIDDEN …`; an undecodable body is `transport "undecodable response: …"`.
  - `call_sync method params ?-timeout ms? ?-session bool? -> result` — for the console and tests only; raises with `-errorcode {VMDAI RPC <code>}` or `{VMDAI TRANSPORT}`
  - `http_get path callback ?-timeout ms?` — GET `<base_url><path>`; `ok <decoded body dict>` or `rpc_error …`/`transport …`. Health probes belong to the runtime, not to a session, so the epoch never drops them.
  - `deliver callback args` — runs `{*}$callback {*}$args` at global level in `catch`; a failure goes to the plugin log
  - `epoch -> int`; `bump_epoch -> int` (new session, resume and shutdown call it; replies to calls made under an older epoch are dropped after their token is cleaned up)
- Produces (Python): `helpers.fake_rpc_server.FakeRpcServer(handler=None, *, ensure_ascii=True, health=None)` — a context manager serving `POST /rpc` and `GET /health` on 127.0.0.1:<ephemeral>; `.port`, `.base_url`, `.requests: List[Recorded]`, `.calls(method)`, settable `.health` (dict, `Reply` or callable). `handler(method, params, headers)` returns `{"result": …}` / `{"error": {...}}` (wrapped in a JSON-RPC envelope) or a raw `Reply(body: bytes, status=200, content_type="application/json; charset=utf-8", delay_s=0.0)`. `Recorded(path, method, params, headers, body)`. `default_health()` returns the runtime's `/health` shape.

- [ ] **Step 1: Create the fake JSON-RPC server helper**

Create `tests/helpers/fake_rpc_server.py`:

```python
"""A small JSON-RPC server for the Tcl transport tests (P06-T03).

``FakeRpcServer(handler)`` serves ``POST /rpc`` and ``GET /health`` on
127.0.0.1:<ephemeral> in a thread and records every request. The handler is
called as ``handler(method, params, headers)`` and returns either a dict with
a ``result`` or an ``error`` key (wrapped in a JSON-RPC envelope) or a
``Reply`` that is sent as-is. ``health`` is a dict, a ``Reply`` or a callable
returning either. ``ensure_ascii=False`` sends raw UTF-8 JSON, like a runtime
without §2c's ASCII-only wire.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Reply:
    body: bytes = b""
    status: int = 200
    content_type: str = "application/json; charset=utf-8"
    delay_s: float = 0.0


@dataclass
class Recorded:
    path: str
    method: str
    params: Dict[str, Any]
    headers: Dict[str, str]
    body: bytes


Handler = Callable[[str, Dict[str, Any], Dict[str, str]], Any]


def default_health() -> Dict[str, Any]:
    return {"ok": True, "pid": os.getpid(), "version": "0.3.0", "protocol": 2}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False


class FakeRpcServer:
    def __init__(self, handler: Optional[Handler] = None, *, ensure_ascii: bool = True,
                 health: Any = None) -> None:
        self.handler = handler or (lambda method, params, headers: {"result": {}})
        self.ensure_ascii = ensure_ascii
        self.health = health if health is not None else default_health()
        self.requests: List[Recorded] = []
        self._lock = threading.Lock()
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        assert self._server is not None
        return int(self._server.server_port)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def calls(self, method: str) -> List[Recorded]:
        with self._lock:
            return [r for r in self.requests if r.method == method]

    def _encode(self, payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=self.ensure_ascii).encode("utf-8")

    def _make_handler(self):
        fake = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _send(self, reply: Reply) -> None:
                if reply.delay_s:
                    time.sleep(reply.delay_s)
                try:
                    self.send_response(reply.status)
                    self.send_header("Content-Type", reply.content_type)
                    self.send_header("Content-Length", str(len(reply.body)))
                    self.end_headers()
                    self.wfile.write(reply.body)
                except OSError:
                    pass  # the client gave up (timeout test)

            def _record(self, method: str, params: Dict[str, Any], body: bytes) -> None:
                with fake._lock:
                    fake.requests.append(Recorded(self.path, method, params,
                                                  dict(self.headers.items()), body))

            def do_GET(self):
                self._record("", {}, b"")
                health = fake.health() if callable(fake.health) else fake.health
                if not isinstance(health, Reply):
                    health = Reply(fake._encode(health))
                self._send(health)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except ValueError:
                    payload = {}
                method = str(payload.get("method", ""))
                params = payload.get("params") or {}
                self._record(method, params, body)
                answer = fake.handler(method, params, dict(self.headers.items()))
                if not isinstance(answer, Reply):
                    envelope = {"jsonrpc": "2.0", "id": payload.get("id")}
                    envelope.update(answer)
                    answer = Reply(fake._encode(envelope))
                self._send(answer)

            def log_message(self, format, *args):
                return

        return _Handler

    def __enter__(self) -> "FakeRpcServer":
        self._server = _Server(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/tcl/test_net.tcl`:

```tcl
# tests/tcl/test_net.tcl - net.tcl transport (P06-T03). The pytest wrapper
# serves tests/helpers/fake_rpc_server.py at $env(VMDAI_FAKE_URL) (ASCII JSON)
# and $env(VMDAI_FAKE_UTF8_URL) (raw UTF-8 JSON).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]
source [file join $plugin net.tcl]
testConstraint http295 [expr {[package present http] eq "2.9.5"}]

proc wait_for {script {ms 3000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 10 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

# Collects callback outcomes: ::got(<tag>) = the appended words.
proc collect {tag args} { set ::got($tag) $args }

proc reset_net {{url ""}} {
    if {$url eq ""} { set url $::env(VMDAI_FAKE_URL) }
    array unset ::got
    ::vmdai::net::configure -base_url $url -session_id "" -session_token ""
}

proc http_tokens {} { llength [info vars ::http::\[0-9\]*] }

test net-escape-1 {json_string escapes quotes, backslashes, controls and non-ASCII} -body {
    set r {}
    set arrow [format %c%c%c 0xc5 0x2192 0xb0]
    foreach s [list "" "plain" "a\"b\\c" "t\tn\nr\r" "\x01\x1f\x7f" $arrow "\[x\] \$y \{z\}"] {
        set out [::vmdai::net::json_string $s]
        lappend r $out [expr {$out eq [::vmdai::config::_json_quote $s]}]
    }
    set r
} -result [list {""} 1 {"plain"} 1 {"a\"b\\c"} 1 {"t\u0009n\u000ar\u000d"} 1 \
    "\"\\u0001\\u001f\x7f\"" 1 "\"\\u00c5\\u2192\\u00b0\"" 1 {"[x] $y {z}"} 1]

test net-escape-2 {1 MB of text encodes quickly} -body {
    set big [string repeat "abc\tdef\"ghi[format %c 0xe9] " 70000]
    set us [lindex [time {::vmdai::net::json_string $big}] 0]
    expr {$us < 1000000}
} -result 1

test net-typed-1 {typed params encode in order; s, i, b, j} -body {
    ::vmdai::net::encode_params [list a s x n i 3 f b 1 g b no o j {{"k":1}} neg i -42]
} -result {{"a":"x","n":3,"f":true,"g":false,"o":{"k":1},"neg":-42}}

test net-typed-2 {bad typed params are errors} -body {
    set r {}
    foreach pairs [list {n i 3.5} {n i 08} {n i x} {f b maybe} {o j {}} {x q 1} {a s}] {
        lappend r [catch {::vmdai::net::encode_params $pairs}]
    }
    set r
} -result {1 1 1 1 1 1 1}

test net-typed-3 {default timeouts per method} -body {
    list [::vmdai::net::_default_timeout chat.send {}] \
        [::vmdai::net::_default_timeout chat.events.poll {after_seq i 0 wait_ms i 2000}] \
        [::vmdai::net::_default_timeout chat.events.poll {after_seq i 0}] \
        [::vmdai::net::_default_timeout models.list {}] \
        [::vmdai::net::_default_timeout provider.test {}] \
        [::vmdai::net::_default_timeout runtime.shutdown {}]
} -result {3000 5000 3000 10000 10000 1500}

test net-call-1 {an ok reply is delivered later, never inside net::call} -body {
    reset_net
    ::vmdai::net::configure -session_id sess_typed -session_token tok_typed
    ::vmdai::net::call echo [list name s "a\"b\\c\n" n i 42 flag b yes obj j {{"k":[1,2]}}] {collect typed}
    set sync [info exists ::got(typed)]
    wait_for {info exists ::got(typed)}
    lassign $::got(typed) kind result
    list $sync $kind [dict get $result session_id] [expr {[dict get $result name] eq "a\"b\\c\n"}] \
        [dict get $result n] [dict get $result flag] [dict get $result obj]
} -result {0 ok sess_typed 1 42 true {k {1 2}}}

test net-call-2 {session.start and -session 0 carry no session} -body {
    reset_net
    ::vmdai::net::configure -session_id sess_x -session_token tok_x
    ::vmdai::net::call session.start {cwd s /tmp} {collect start}
    ::vmdai::net::call echo {tag s nosession} {collect plain} -session 0
    wait_for {expr {[info exists ::got(start)] && [info exists ::got(plain)]}}
    list [dict exists [lindex $::got(start) 1] session_id] [dict exists [lindex $::got(plain) 1] session_id]
} -result {0 0}

test net-call-3 {rpc errors: JSON-RPC error body and HTTP 403 FORBIDDEN} -body {
    reset_net
    ::vmdai::net::call fail.rpc {} {collect rpc}
    ::vmdai::net::call fail.403 {} {collect forbidden}
    wait_for {expr {[info exists ::got(rpc)] && [info exists ::got(forbidden)]}}
    list $::got(rpc) [lrange $::got(forbidden) 0 1]
} -result {{rpc_error NO_MODEL {No model configured} {action open_settings}} {rpc_error FORBIDDEN}}

test net-call-4 {transport errors: undecodable body, timeout, refused port, no address} -body {
    reset_net
    ::vmdai::net::call fail.garbage {} {collect garbage}
    ::vmdai::net::call slow {} {collect timeout} -timeout 200
    wait_for {expr {[info exists ::got(garbage)] && [info exists ::got(timeout)]}}
    set srv [socket -server {apply {{c a p} {close $c}}} -myaddr 127.0.0.1 0]
    set dead [lindex [fconfigure $srv -sockname] 2]
    close $srv
    ::vmdai::net::configure -base_url http://127.0.0.1:$dead
    ::vmdai::net::call echo {} {collect refused}
    ::vmdai::net::configure -base_url ""
    ::vmdai::net::call echo {} {collect noaddr}
    wait_for {expr {[info exists ::got(refused)] && [info exists ::got(noaddr)]}}
    list $::got(garbage) $::got(timeout) [lindex $::got(refused) 0] $::got(noaddr) \
        [::vmdai::sched::pending] [http_tokens]
} -result {{transport {undecodable response: not a JSON object}} {transport timeout} transport {transport {no runtime address}} {} 0}

test net-epoch-1 {a reply from an older epoch is dropped and its token cleaned up} -body {
    reset_net
    ::vmdai::net::call slow.short {} {collect stale}
    set before [::vmdai::net::epoch]
    ::vmdai::net::bump_epoch
    wait_for {expr {[http_tokens] == 0}} 3000
    set ::after_wait 0
    after 200 {set ::after_wait 1}
    vwait ::after_wait
    list [expr {[::vmdai::net::epoch] == $before + 1}] [info exists ::got(stale)] \
        [http_tokens] [array size ::vmdai::sched::tokens] [::vmdai::sched::pending] \
        [string match "*dropped a reply from epoch*" [plugin_log]]
} -result {1 0 0 0 {} 1}

test net-deliver-1 {a throwing handler is logged and later replies still arrive} -body {
    reset_net
    ::vmdai::net::call echo {n i 1} {apply {{args} {error "boom-handler"}}}
    ::vmdai::net::call echo {n i 2} {collect second}
    wait_for {info exists ::got(second)}
    list [lindex $::got(second) 0] [string match "*boom-handler*" [plugin_log]]
} -result {ok 1}

test net-sync-1 {call_sync returns the result or raises with an errorcode} -body {
    reset_net
    set ok [::vmdai::net::call_sync echo {n i 7}]
    set code [catch {::vmdai::net::call_sync fail.rpc {}} msg opts]
    list [dict get $ok n] $code [dict get $opts -errorcode] $msg
} -result {7 1 {VMDAI RPC NO_MODEL} {NO_MODEL: No model configured}}

test net-get-1 {http_get delivers the decoded /health body} -body {
    reset_net
    ::vmdai::net::http_get /health {collect health}
    wait_for {info exists ::got(health)}
    lassign $::got(health) kind body
    list $kind [dict get $body ok] [dict get $body protocol]
} -result {ok true 2}

test net-get-2 {health probes are never dropped by an epoch change} -body {
    reset_net
    ::vmdai::net::http_get /health {collect health2}
    ::vmdai::net::bump_epoch
    wait_for {info exists ::got(health2)}
    lindex $::got(health2) 0
} -result ok

test net-s8-1 {S8: Unicode round-trips through ASCII and UTF-8 replies with http 2.9.5} -constraints http295 -body {
    set text [format %c%c%c 0xc5 0x2192 0xb0]
    set r {}
    foreach url [list $::env(VMDAI_FAKE_URL) $::env(VMDAI_FAKE_UTF8_URL)] {
        reset_net $url
        ::vmdai::net::call echo [list text s $text] {collect s8}
        wait_for {info exists ::got(s8)}
        lappend r [lindex $::got(s8) 0] [expr {[dict get [lindex $::got(s8) 1] text] eq $text}]
    }
    set r
} -result {ok 1 ok 1}

cleanupTests
```

Create `tests/test_tcl_net.py`:

```python
"""net.tcl: escaper, typed params, async call, after-0 delivery, epoch, S8 (P06-T03).

Runs tests/tcl/test_net.tcl against two FakeRpcServers (ASCII and UTF-8
replies) and checks the request bytes on the Python side.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded, Reply
from helpers.tcl import REPO, TclTestResult, run_tcl, run_tcltest, tcl_word

TCL_FILE = REPO / "tests" / "tcl" / "test_net.tcl"
TOTAL = 14  # every case except the http 2.9.5-only net-s8-1
ARROW = "".join(map(chr, (0xC5, 0x2192, 0xB0)))  # the S8 text


def handler(method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
    if method in ("echo", "session.start"):
        return {"result": params}
    if method == "fail.rpc":
        return {"error": {"code": "NO_MODEL", "message": "No model configured",
                          "data": {"action": "open_settings"}}}
    if method == "fail.403":
        body = json.dumps({"jsonrpc": "2.0", "id": None,
                           "error": {"code": "FORBIDDEN", "message": "forbidden", "data": {}}})
        return Reply(body.encode("ascii"), status=403)
    if method == "fail.garbage":
        return Reply(b"<html>not json</html>", content_type="text/html")
    if method == "slow":
        return Reply(b'{"jsonrpc":"2.0","id":"x","result":{}}', delay_s=1.5)
    if method == "slow.short":
        return Reply(b'{"jsonrpc":"2.0","id":"x","result":{}}', delay_s=0.3)
    return {"error": {"code": "METHOD_NOT_FOUND", "message": method, "data": {}}}


@dataclass
class NetRun:
    result: TclTestResult
    ascii_requests: List[Recorded]
    utf8_requests: List[Recorded]


def _run(**kw: Any) -> NetRun:
    with FakeRpcServer(handler) as plain, FakeRpcServer(handler, ensure_ascii=False) as utf8:
        env = {"VMDAI_FAKE_URL": plain.base_url, "VMDAI_FAKE_UTF8_URL": utf8.base_url}
        result = run_tcltest(str(TCL_FILE), env=env, **kw)
        return NetRun(result, list(plain.requests), list(utf8.requests))


@pytest.fixture(scope="module")
def net_run() -> NetRun:
    return _run()


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(net_run):
    assert (net_run.result.passed, net_run.result.failed) == (TOTAL, 0), net_run.result.output


ROUND_TRIP = [
    "",
    "plain ascii",
    'quote " backslash \\ slash /',
    "".join(chr(i) for i in range(32)) + "\x7f",
    "".join(map(chr, (0xC5, 0x2192, 0xB0, 0x20, 0x2014, 0x20, 0x63, 0x61, 0x66, 0xE9))),
    "".join(map(chr, (0x2028, 0x2029, 0xFEFF))),
    "{braces} [brackets] $dollar",
    "\\u0041 is not an escape here",
    "x" * 5000 + chr(0xE9),
]


def _tcl_literal(s: str) -> str:
    return '"' + "".join(f"\\u{ord(c):04x}" for c in s) + '"'


def test_escaper_round_trip_python_json():
    lines = [
        f"source {tcl_word(str(REPO / 'plugin' / 'config.tcl'))}",
        f"source {tcl_word(str(REPO / 'plugin' / 'sched.tcl'))}",
        f"source {tcl_word(str(REPO / 'plugin' / 'net.tcl'))}",
    ]
    for s in ROUND_TRIP:
        lit = _tcl_literal(s)
        lines.append(f"puts [::vmdai::net::json_string {lit}]")
        lines.append(f"puts [::vmdai::config::_json_quote {lit}]")
    proc = run_tcl("\n".join(lines) + "\n")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.splitlines()
    assert len(out) == 2 * len(ROUND_TRIP)
    for i, s in enumerate(ROUND_TRIP):
        net_line, config_line = out[2 * i], out[2 * i + 1]
        assert net_line.isascii(), net_line[:80]
        assert json.loads(net_line) == s
        assert config_line == net_line


def test_typed_params(net_run):
    _assert_passed(net_run.result, ["net-typed-1", "net-typed-2", "net-typed-3",
                                    "net-call-1", "net-call-2"])
    typed = [r for r in net_run.ascii_requests if r.params.get("session_id") == "sess_typed"]
    assert len(typed) == 1
    request = typed[0]
    assert request.params == {"session_id": "sess_typed", "name": 'a"b\\c\n', "n": 42,
                              "flag": True, "obj": {"k": [1, 2]}}
    assert request.body.isascii()
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert headers["x-session-token"] == "tok_typed"
    assert headers["content-type"] == "application/json"
    assert re.fullmatch(r"127\.0\.0\.1:\d+", headers["host"])
    assert "origin" not in headers
    start = [r for r in net_run.ascii_requests if r.method == "session.start"]
    assert len(start) == 1 and "session_id" not in start[0].params
    assert "x-session-token" not in {k.lower() for k in start[0].headers}


def test_reply_forms(net_run):
    _assert_passed(net_run.result, ["net-call-3", "net-call-4", "net-sync-1", "net-get-1", "net-get-2"])


def test_stale_epoch_dropped_token_cleaned(net_run):
    _assert_passed(net_run.result, ["net-epoch-1"])


def test_throwing_handler_logged_pump_continues(net_run):
    _assert_passed(net_run.result, ["net-deliver-1"])


def test_escaper_speed(net_run):
    _assert_passed(net_run.result, ["net-escape-1", "net-escape-2"])


def test_s8_unicode_round_trip_http_295():
    prelude = "package require tcltest 2\n::tcltest::configure -match net-s8-*\n"
    run = _run(needs_http=True, prelude=prelude)
    assert (run.result.passed, run.result.failed) == (1, 0), run.result.output
    for request in run.ascii_requests + run.utf8_requests:
        assert request.body.isascii()
        assert request.params == {"text": ARROW}
```

The main run loads whatever `http` the test tclsh has (so CI runs these cases too); `net-s8-1` is constrained to http 2.9.5 and runs only in `test_s8_unicode_round_trip_http_295`, which loads VMD's 2.9.5 through `needs_http=True` and skips when it is absent (§6). The S8 case covers both an ASCII reply (§2c) and a raw UTF-8 reply with `charset=utf-8`, the path the garbling report is about (P06-T12 names the cause).

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_net.py -q`
Expected: `8 failed`; the output shows `couldn't read file ".../plugin/net.tcl": no such file or directory`.

- [ ] **Step 4: Create `plugin/net.tcl`**

```tcl
# net.tcl - JSON encoding and decoding, the async JSON-RPC transport, after-0
# delivery and the epoch (spec 2d, 3 Tcl interfaces). No Tk.
#
# Callback forms (the callback is a command prefix; these words are appended):
#   ok <result>
#   rpc_error <code> <message> <data>
#   transport <reason>
# Callbacks always run later, from the event loop, never inside net::call.

package require http 2
::vmdai::config::require_json

namespace eval ::vmdai::net {
    variable base_url
    if {![info exists base_url]} { set base_url "" }
    variable session_id
    if {![info exists session_id]} { set session_id "" }
    variable session_token
    if {![info exists session_token]} { set session_token "" }
    variable epoch
    if {![info exists epoch]} { set epoch 0 }
    variable seq
    if {![info exists seq]} { set seq 0 }
    # inflight(<rid>) = 1 until the http callback for that request ran.
    variable inflight
    if {![info exists inflight]} { array set inflight {} }

    # Control characters, backslash and quote -> JSON escapes.
    variable escape_map [list "\\" "\\\\" "\"" "\\\""]
    for {set i 0} {$i < 32} {incr i} {
        lappend escape_map [format %c $i] [format "\\u%04x" $i]
    }
    unset i
}

proc ::vmdai::net::_log {msg} {
    catch {::vmdai::config::log "net: $msg"}
}

# One JSON string literal, ASCII only (non-ASCII becomes \uXXXX).
proc ::vmdai::net::json_string {s} {
    variable escape_map
    set s [string map $escape_map $s]
    if {[regexp {[^\u0000-\u007f]} $s]} {
        set wide {}
        foreach ch [lsort -unique [regexp -all -inline {[^\u0000-\u007f]} $s]] {
            lappend wide $ch [format "\\u%04x" [scan $ch %c]]
        }
        set s [string map $wide $s]
    }
    return "\"$s\""
}

# Typed params: a flat list {name type value ...}; type is s (string),
# i (integer), b (boolean) or j (JSON text, inserted verbatim).
proc ::vmdai::net::encode_params {pairs} {
    if {[llength $pairs] % 3 != 0} {
        error "encode_params: expected name type value triples, got [llength $pairs] words"
    }
    set parts {}
    foreach {name type value} $pairs {
        switch -- $type {
            s { set json [json_string $value] }
            i {
                if {![regexp {^-?(0|[1-9][0-9]*)$} $value]} {
                    error "encode_params: $name is not an integer: \"$value\""
                }
                set json $value
            }
            b {
                if {![string is boolean -strict $value]} {
                    error "encode_params: $name is not a boolean: \"$value\""
                }
                set json [expr {[string is true -strict $value] ? "true" : "false"}]
            }
            j {
                if {[string trim $value] eq ""} {
                    error "encode_params: $name has empty JSON"
                }
                set json $value
            }
            default { error "encode_params: unknown type \"$type\" for $name" }
        }
        lappend parts "[json_string $name]:$json"
    }
    return "\{[join $parts ,]\}"
}

# Decode a JSON object into a dict; errors when the body is not one.
proc ::vmdai::net::decode {body} {
    set text [string trim $body]
    if {[string index $text 0] ne "\{" || [string index $text end] ne "\}"} {
        error "not a JSON object"
    }
    set value [::json::json2dict $text]
    if {[catch {dict size $value}]} {
        error "not a JSON object"
    }
    return $value
}

proc ::vmdai::net::configure {args} {
    variable base_url
    variable session_id
    variable session_token
    if {[llength $args] == 0} {
        return [list -base_url $base_url -session_id $session_id -session_token $session_token]
    }
    if {[llength $args] % 2 != 0} {
        error "net::configure: expected option value pairs"
    }
    foreach {option value} $args {
        switch -- $option {
            -base_url { set base_url [string trimright $value /] }
            -session_id { set session_id $value }
            -session_token { set session_token $value }
            default { error "net::configure: unknown option $option" }
        }
    }
    return
}

proc ::vmdai::net::epoch {} {
    variable epoch
    return $epoch
}

# New session, resume and shutdown bump the epoch: replies issued under an
# older epoch are dropped (their http tokens are still cleaned up).
proc ::vmdai::net::bump_epoch {} {
    variable epoch
    incr epoch
    return $epoch
}

proc ::vmdai::net::_default_timeout {method pairs} {
    switch -- $method {
        models.list - provider.test { return 10000 }
        runtime.shutdown { return 1500 }
        chat.events.poll {
            foreach {name type value} $pairs {
                if {$name eq "wait_ms" && [string is integer -strict $value]} {
                    return [expr {$value + 3000}]
                }
            }
        }
    }
    return $::vmdai::config::request_timeout_ms
}

# Build {url body headers timeout id} for one RPC.
proc ::vmdai::net::_prepare {method params options} {
    variable base_url
    variable session_id
    variable session_token
    variable seq
    set timeout ""
    set use_session [expr {$method ne "session.start"}]
    foreach {option value} $options {
        switch -- $option {
            -timeout { set timeout $value }
            -session { set use_session [string is true -strict $value] }
            default { error "net::call: unknown option $option" }
        }
    }
    if {$timeout eq ""} {
        set timeout [_default_timeout $method $params]
    }
    set headers {}
    if {$use_session && $session_id ne ""} {
        set params [linsert $params 0 session_id s $session_id]
        if {$session_token ne ""} {
            lappend headers X-Session-Token $session_token
        }
    }
    set id "tcl_[format %06d [incr seq]]"
    set body "\{\"jsonrpc\":\"2.0\",\"id\":[json_string $id],\"method\":[json_string $method],\"params\":[encode_params $params]\}"
    return [list "$base_url/rpc" $body $headers $timeout $id]
}

# One outcome list (ok ... | rpc_error ... | transport ...) from an http reply.
proc ::vmdai::net::_classify {status ncode body err} {
    if {$status ne "ok"} {
        if {$err ne ""} {
            return [list transport "$status: $err"]
        }
        return [list transport $status]
    }
    if {[catch {decode $body} decoded]} {
        if {$ncode ne "200"} {
            return [list transport "HTTP $ncode"]
        }
        return [list transport "undecodable response: $decoded"]
    }
    if {[dict exists $decoded error]} {
        set e [dict get $decoded error]
        if {[catch {dict exists $e code} has] || !$has} {
            return [list rpc_error ERROR $e {}]
        }
        set message ""
        set data {}
        catch {set message [dict get $e message]}
        catch {set data [dict get $e data]}
        return [list rpc_error [dict get $e code] $message $data]
    }
    if {$ncode ne "200"} {
        return [list transport "HTTP $ncode"]
    }
    if {[dict exists $decoded result]} {
        return [list ok [dict get $decoded result]]
    }
    return [list transport "response has neither result nor error"]
}

# Run a callback with its outcome words; failures go to the plugin log.
proc ::vmdai::net::deliver {callback args} {
    if {[catch {uplevel #0 [list {*}$callback {*}$args]} err]} {
        _log "callback failed ($callback [lindex $args 0]): $::errorInfo"
    }
    return
}

# call_epoch "" (health probes) is never stale.
proc ::vmdai::net::_deliver_if_current {call_epoch callback args} {
    variable epoch
    if {$call_epoch ne "" && $call_epoch != $epoch} {
        _log "dropped a reply from epoch $call_epoch (now $epoch)"
        return
    }
    deliver $callback {*}$args
}

proc ::vmdai::net::_later {call_epoch callback outcome} {
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current $call_epoch $callback {*}$outcome]
}

# http -command callback: capture, clean up, then hand off with after 0.
# http runs this inside `catch`, so it must not rely on errors surfacing.
proc ::vmdai::net::_http_done {rid call_epoch callback kind token} {
    variable inflight
    variable epoch
    unset -nocomplain inflight($rid)
    ::vmdai::sched::untrack_http $token
    set status error
    set ncode ""
    set body ""
    set err ""
    catch {set status [::http::status $token]}
    catch {set ncode [::http::ncode $token]}
    catch {set body [::http::data $token]}
    catch {set err [::http::error $token]}
    catch {::http::cleanup $token}
    if {$call_epoch ne "" && $call_epoch != $epoch} {
        _log "dropped a reply from epoch $call_epoch (now $epoch)"
        return
    }
    if {$kind eq "get"} {
        set outcome [_classify_get $status $ncode $body $err]
    } else {
        set outcome [_classify $status $ncode $body $err]
    }
    _later $call_epoch $callback $outcome
}

proc ::vmdai::net::_geturl {rid callback kind call_epoch url args} {
    variable inflight
    set inflight($rid) 1
    set cmd [list ::vmdai::net::_http_done $rid $call_epoch $callback $kind]
    if {[catch {::http::geturl $url {*}$args -command $cmd} token]} {
        unset -nocomplain inflight($rid)
        _later $call_epoch $callback [list transport "connect failed: $token"]
        return $rid
    }
    if {[info exists inflight($rid)]} {
        ::vmdai::sched::track_http $token
    }
    return $rid
}

# Asynchronous JSON-RPC call. Returns a request id.
proc ::vmdai::net::call {method params callback args} {
    variable base_url
    variable epoch
    lassign [_prepare $method $params $args] url body headers timeout id
    set rid "rpc#$id"
    if {$base_url eq ""} {
        _later $epoch $callback [list transport "no runtime address"]
        return $rid
    }
    return [_geturl $rid $callback rpc $epoch $url -query $body -type application/json \
        -headers $headers -timeout $timeout -keepalive 0]
}

# Synchronous call for the console and tests only (it nests the event loop).
# Returns the result; errors carry -errorcode {VMDAI RPC code} or {VMDAI TRANSPORT}.
proc ::vmdai::net::call_sync {method params args} {
    lassign [_prepare $method $params $args] url body headers timeout id
    if {[catch {::http::geturl $url -query $body -type application/json \
            -headers $headers -timeout $timeout -keepalive 0} token]} {
        return -code error -errorcode {VMDAI TRANSPORT} "connect failed: $token"
    }
    set outcome [_classify [::http::status $token] [::http::ncode $token] \
        [::http::data $token] [::http::error $token]]
    ::http::cleanup $token
    switch -- [lindex $outcome 0] {
        ok { return [lindex $outcome 1] }
        rpc_error {
            return -code error -errorcode [list VMDAI RPC [lindex $outcome 1]] \
                "[lindex $outcome 1]: [lindex $outcome 2]"
        }
        default {
            return -code error -errorcode {VMDAI TRANSPORT} [lindex $outcome 1]
        }
    }
}

proc ::vmdai::net::_classify_get {status ncode body err} {
    if {$status ne "ok"} {
        if {$err ne ""} {
            return [list transport "$status: $err"]
        }
        return [list transport $status]
    }
    if {[catch {decode $body} decoded]} {
        return [list transport "HTTP $ncode, undecodable body"]
    }
    if {$ncode ne "200"} {
        return [_classify $status $ncode $body $err]
    }
    return [list ok $decoded]
}

# GET <base_url><path> (e.g. /health); the callback gets `ok <dict>` with the
# whole decoded body, or `rpc_error ...` / `transport ...`. Health probes
# belong to the runtime, not to a session, so the epoch never drops them.
proc ::vmdai::net::http_get {path callback args} {
    variable base_url
    variable seq
    set timeout $::vmdai::config::request_timeout_ms
    foreach {option value} $args {
        switch -- $option {
            -timeout { set timeout $value }
            default { error "net::http_get: unknown option $option" }
        }
    }
    set rid "get#[incr seq]"
    if {$base_url eq ""} {
        _later "" $callback [list transport "no runtime address"]
        return $rid
    }
    return [_geturl $rid $callback get "" "$base_url$path" -timeout $timeout -keepalive 0]
}
```

Notes for the reviewer:
- `json_string` is the §2d `string map` escaper: one pass for backslash, quote and the 32 control characters, then a map built only from the non-ASCII characters actually present, so an ASCII megabyte costs one `regexp` scan. It never uses `subst`, which would run `[...]` found in the text.
- `_geturl` marks the request in flight before calling `http::geturl`, so a callback that runs synchronously inside `geturl` (an immediate failure) is not tracked afterwards as a live token.
- Delivery goes through `::vmdai::sched::after 0`, so `sched::teardown` cancels a delivery that has not run yet.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_net.py tests/test_tcl_lint.py -q`
Expected: `11 passed` (on a machine without VMD.app, `test_s8_unicode_round_trip_http_295` is skipped with `http 2.9.5 not found: …`).

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+17 passed`, `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add plugin/net.tcl tests/helpers/fake_rpc_server.py tests/tcl/test_net.tcl tests/test_tcl_net.py
git commit -F - <<'MSG'
feat(plugin): net.tcl async JSON-RPC transport with after-0 delivery and epoch

Typed params are encoded to ASCII-only JSON; replies are decoded with the
vendored json 1.1.2 (no regex parsing). http -command callbacks only
capture and clean up, then deliver through sched with `after 0`; handler
errors are logged. Replies from an older epoch are dropped. S8 round-trip
checked with VMD's http 2.9.5 against ASCII and UTF-8 replies.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 4: P06-T04 — net.tcl result queue

**Files:**
- Modify: `plugin/net.tcl` (`bump_epoch`; append the result-queue section)
- Test: `tests/tcl/test_result_queue.tcl`, `tests/test_tcl_result_queue.py`

**Interfaces:**
- Consumes: `::vmdai::net::call`, `bump_epoch`, `epoch` (P06-T03); `::vmdai::sched::after`, `cancel` (P06-T02); the runtime's `tool.command_result` by `call_key`, answering `{accepted, late, duplicate}` (`accepted` false for a call owned by another session) or the RPC error `TOOL_CALL_UNKNOWN` (P05-T02); `FakeRpcServer`, `Reply`, `Recorded` (P06-T03).
- Produces:
  - `::vmdai::net::post_result call_key result_pairs` — `result_pairs` are the typed `tool.command_result` params without `call_key` (P06-T08 sends `ok b`, `output s`, `error s`, `executed s`, `statements_total i`, `statements_applied i`, `failed_index i`, `failed_statement s`, `error_info s`, `applied_text s`, `duration_ms i`, `truncated b`, `snapshot_file s` as they apply). The post is retried after 250, 500, 1000, 2000, 2000 … ms until the runtime answers `ok` (accepted, or a duplicate, which counts as accepted), until a permanent error (`TOOL_CALL_UNKNOWN`, `INVALID_PARAMS`, `METHOD_NOT_FOUND`: dropped and logged), or until the epoch changes. Other RPC errors (for example `AUTH_FAILED` after a runtime restart) and transport errors retry. A second `post_result` for a `call_key` that is still queued is ignored.
  - `::vmdai::net::result_queue_size -> int`
  - `bump_epoch` now also drops queued results of older epochs and cancels their retry timers
  - (internal) `::vmdai::net::queue(<call_key>)` = dict `{pairs epoch delay timer attempts}`; `retry_min_ms 250`, `retry_max_ms 2000`

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_result_queue.tcl`:

```tcl
# tests/tcl/test_result_queue.tcl - net::post_result retries (P06-T04). The
# pytest wrapper serves a FakeRpcServer at $env(VMDAI_FAKE_URL) whose reply
# depends on the call_key (see tests/test_tcl_result_queue.py).
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
source [file join $plugin config.tcl]
source [file join $plugin sched.tcl]
source [file join $plugin net.tcl]
::vmdai::net::configure -base_url $::env(VMDAI_FAKE_URL) -session_id sess_rq -session_token tok_rq

proc wait_for {script {ms 3000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 10 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc sleep_ms {ms} {
    set ::_slept 0
    after $ms {set ::_slept 1}
    vwait ::_slept
}

proc plugin_log {} {
    set path [::vmdai::config::plugin_log_path]
    if {![file exists $path]} { return "" }
    set fh [open $path r]
    set text [read $fh]
    close $fh
    return $text
}

proc queued {call_key} { info exists ::vmdai::net::queue($call_key) }

set result_pairs {ok b 1 output s done executed s yes statements_total i 1 statements_applied i 1}

test rq-retry-1 {transport failures are retried with backoff until accepted} -body {
    set t0 [clock milliseconds]
    ::vmdai::net::post_result k_retry $result_pairs
    set waited [wait_for {expr {![queued k_retry]}} 4000]
    set elapsed [expr {[clock milliseconds] - $t0}]
    list $waited [expr {$elapsed >= 700 && $elapsed < 3000}] [::vmdai::net::result_queue_size] \
        [::vmdai::sched::pending]
} -result {1 1 0 {}}

test rq-dup-1 {a duplicate reply counts as accepted} -body {
    ::vmdai::net::post_result k_dup $result_pairs
    wait_for {expr {![queued k_dup]}}
    list [queued k_dup] [::vmdai::sched::pending]
} -result {0 {}}

test rq-unknown-1 {a permanent RPC error drops the result and logs it} -body {
    ::vmdai::net::post_result k_unknown $result_pairs
    wait_for {expr {![queued k_unknown]}}
    list [queued k_unknown] [::vmdai::sched::pending] \
        [string match "*dropped the result for k_unknown: TOOL_CALL_UNKNOWN*" [plugin_log]]
} -result {0 {} 1}

test rq-once-1 {posting a queued call_key again is ignored} -body {
    ::vmdai::net::post_result k_never $result_pairs
    ::vmdai::net::post_result k_never $result_pairs
    set size [::vmdai::net::result_queue_size]
    wait_for {expr {[dict get $::vmdai::net::queue(k_never) timer] ne ""}}
    list $size [dict get $::vmdai::net::queue(k_never) attempts]
} -result {1 1}

test rq-epoch-1 {an epoch change drops queued results and their timers} -body {
    ::vmdai::net::post_result k_auth $result_pairs
    wait_for {expr {[dict get $::vmdai::net::queue(k_auth) attempts] >= 2}} 3000
    ::vmdai::net::bump_epoch
    set right_after [list [::vmdai::net::result_queue_size] [::vmdai::sched::pending]]
    sleep_ms 1200
    list $right_after [::vmdai::net::result_queue_size] [::vmdai::sched::pending]
} -result {{0 {}} 0 {}}

cleanupTests
```

Create `tests/test_tcl_result_queue.py`:

```python
"""net::post_result: retry until accepted, epoch change, duplicates (P06-T04; §2d, §5)."""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded, Reply
from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_result_queue.tcl"
TOTAL = 5

ACCEPTED = {"accepted": True, "late": False, "duplicate": False}
UNAVAILABLE = Reply(b"Service Unavailable", status=503, content_type="text/plain")


class QueueHandler:
    """Replies by call_key: k_retry fails twice, k_dup is a duplicate,
    k_unknown is TOOL_CALL_UNKNOWN, k_auth is AUTH_FAILED, k_never always 503."""

    def __init__(self) -> None:
        self.seen: Dict[str, int] = {}
        self.lock = threading.Lock()

    def __call__(self, method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
        key = str(params.get("call_key", ""))
        with self.lock:
            self.seen[key] = self.seen.get(key, 0) + 1
            count = self.seen[key]
        if method != "tool.command_result":
            return {"error": {"code": "METHOD_NOT_FOUND", "message": method, "data": {}}}
        if key == "k_retry":
            return UNAVAILABLE if count <= 2 else {"result": ACCEPTED}
        if key == "k_dup":
            return {"result": {"accepted": True, "late": False, "duplicate": True}}
        if key == "k_unknown":
            return {"error": {"code": "TOOL_CALL_UNKNOWN", "message": "unknown call_key", "data": {}}}
        if key == "k_auth":
            return {"error": {"code": "AUTH_FAILED", "message": "session token mismatch", "data": {}}}
        return UNAVAILABLE


@dataclass
class QueueRun:
    result: TclTestResult
    requests: List[Recorded]
    seen: Dict[str, int]


@pytest.fixture(scope="module")
def queue_run() -> QueueRun:
    handler = QueueHandler()
    with FakeRpcServer(handler) as server:
        result = run_tcltest(str(TCL_FILE), env={"VMDAI_FAKE_URL": server.base_url})
        return QueueRun(result, list(server.requests), dict(handler.seen))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(queue_run):
    assert (queue_run.result.passed, queue_run.result.failed) == (TOTAL, 0), queue_run.result.output


def test_retries_until_accepted(queue_run):
    _assert_passed(queue_run.result, ["rq-retry-1"])
    assert queue_run.seen["k_retry"] == 3
    posted = [r for r in queue_run.requests if r.params.get("call_key") == "k_retry"]
    assert posted[0].params == {"session_id": "sess_rq", "call_key": "k_retry", "ok": True,
                                "output": "done", "executed": "yes",
                                "statements_total": 1, "statements_applied": 1}
    assert len({json.loads(r.body)["id"] for r in posted}) == 3  # a fresh JSON-RPC id per attempt


def test_epoch_change_stops(queue_run):
    _assert_passed(queue_run.result, ["rq-once-1", "rq-epoch-1"])
    assert queue_run.seen["k_auth"] == 2


def test_duplicate_counts_as_accepted(queue_run):
    _assert_passed(queue_run.result, ["rq-dup-1"])
    assert queue_run.seen["k_dup"] == 1


def test_permanent_error_dropped(queue_run):
    _assert_passed(queue_run.result, ["rq-unknown-1"])
    assert queue_run.seen["k_unknown"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_result_queue.py -q`
Expected: `5 failed`; the tcltest output shows `invalid command name "::vmdai::net::post_result"`.

- [ ] **Step 3: Drop stale queued results when the epoch changes**

In `plugin/net.tcl`, replace:

```tcl
proc ::vmdai::net::bump_epoch {} {
    variable epoch
    incr epoch
    return $epoch
}
```

with:

```tcl
proc ::vmdai::net::bump_epoch {} {
    variable epoch
    incr epoch
    _queue_drop_stale
    return $epoch
}
```

- [ ] **Step 4: Append the result queue**

Append to the end of `plugin/net.tcl`, after one blank line:

```tcl
# --- Result queue (spec 2d Post, 5 "Result post fails") -------------------
# tool.command_result posts are retried (0.25 s doubling to 2 s) until the
# runtime accepts them or the epoch changes. The runtime dedupes by call_key
# and answers {accepted, late, duplicate}; a duplicate counts as accepted.

namespace eval ::vmdai::net {
    # queue(<call_key>) = dict {pairs epoch delay timer attempts}
    variable queue
    if {![info exists queue]} { array set queue {} }
    variable retry_min_ms 250
    variable retry_max_ms 2000
}

# result_pairs: typed pairs for tool.command_result, without call_key.
proc ::vmdai::net::post_result {call_key result_pairs} {
    variable queue
    variable epoch
    variable retry_min_ms
    if {[info exists queue($call_key)]} {
        _log "result for $call_key is already queued"
        return
    }
    set queue($call_key) [dict create pairs [linsert $result_pairs 0 call_key s $call_key] \
        epoch $epoch delay $retry_min_ms timer "" attempts 0]
    _queue_send $call_key
}

proc ::vmdai::net::result_queue_size {} {
    variable queue
    return [array size queue]
}

proc ::vmdai::net::_queue_send {call_key} {
    variable queue
    variable epoch
    if {![info exists queue($call_key)]} {
        return
    }
    set entry $queue($call_key)
    if {[dict get $entry epoch] != $epoch} {
        unset queue($call_key)
        return
    }
    dict set entry timer ""
    dict incr entry attempts
    set queue($call_key) $entry
    call tool.command_result [dict get $entry pairs] [list ::vmdai::net::_queue_reply $call_key]
}

proc ::vmdai::net::_queue_reply {call_key kind args} {
    variable queue
    if {![info exists queue($call_key)]} {
        return
    }
    switch -- $kind {
        ok {
            set reply [lindex $args 0]
            set accepted 0
            set duplicate 0
            catch {set accepted [string is true -strict [dict get $reply accepted]]}
            catch {set duplicate [string is true -strict [dict get $reply duplicate]]}
            if {!$accepted && !$duplicate} {
                _log "runtime did not accept the result for $call_key: $reply"
            }
            unset queue($call_key)
        }
        rpc_error {
            lassign $args code message
            if {$code in {TOOL_CALL_UNKNOWN INVALID_PARAMS METHOD_NOT_FOUND}} {
                _log "dropped the result for $call_key: $code $message"
                unset queue($call_key)
                return
            }
            _queue_retry $call_key "$code: $message"
        }
        default {
            _queue_retry $call_key [lindex $args 0]
        }
    }
}

proc ::vmdai::net::_queue_retry {call_key reason} {
    variable queue
    variable retry_max_ms
    set entry $queue($call_key)
    set delay [dict get $entry delay]
    _log "result for $call_key not delivered ($reason); retrying in $delay ms"
    dict set entry delay [expr {min($delay * 2, $retry_max_ms)}]
    dict set entry timer [::vmdai::sched::after $delay [list ::vmdai::net::_queue_send $call_key]]
    set queue($call_key) $entry
}

proc ::vmdai::net::_queue_drop_stale {} {
    variable queue
    variable epoch
    foreach call_key [array names queue] {
        if {[dict get $queue($call_key) epoch] != $epoch} {
            ::vmdai::sched::cancel [dict get $queue($call_key) timer]
            unset queue($call_key)
        }
    }
}
```

`expr {min(...)}` is Tcl 8.5 (`min`/`max` math functions arrived in 8.5), so the lint is unaffected.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_result_queue.py tests/test_tcl_net.py tests/test_tcl_lint.py -q`
Expected: `16 passed` (`rq-retry-1` takes about 0.75 s: two failures, then 250 + 500 ms of backoff).

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+22 passed`, `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add plugin/net.tcl tests/tcl/test_result_queue.tcl tests/test_tcl_result_queue.py
git commit -F - <<'MSG'
feat(plugin): result queue retries tool.command_result until accepted

post_result retries 0.25 s doubling to 2 s until the runtime accepts the
result (a duplicate counts as accepted), a permanent error drops it, or
the epoch changes, which also cancels its retry timer (spec 2d, 5).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 5: P06-T05 — runtime.tcl: launch, READY, attach, stop

**Files:**
- Create: `plugin/runtime.tcl`
- Create: `tests/fixtures/stub_runtime/fail_runtime.py`, `tests/fixtures/stub_runtime/ready_runtime.py`
- Test: `tests/tcl/test_runtime_launch.tcl`, `tests/test_tcl_runtime_launch.py`

**Interfaces:**
- Consumes: the READY line `VMDAI_READY {"port":…,"pid":…,"version":…,"protocol":2,"launch_token":…}` printed by `main.py --port 0 --announce --watch-stdin` (P02-T02 `format_ready_line`, P02-T04); the token file `~/.vmdai/run/runtime-<port>.json {port, pid, token, protocol}` and `vmd_ai_runtime.launch.write_token_file(port, pid, token, protocol=2, home=None)` (P02-T02); `GET /health -> {ok, pid, version, protocol}` (P02-T01); RPC `runtime.shutdown {launch_token} -> {ok}` (P02-T02); `::vmdai::config::resolve_python`, `attach_target`, `token_file_path`, `runtime_main`, `ready_timeout_ms`, `shutdown_kill_ms`, `log` and `::vmdai::sched::after`, `cancel`, `fileevent` (P06-T02); `::vmdai::net::configure`, `decode`, `http_get`, `call`, `bump_epoch` (P06-T03); `FakeRpcServer` (P06-T03).
- Produces (`::vmdai::runtime`):
  - `ensure -> state` — from `stopped` or `down`: attach when `VMD_AI_ATTACH` is set, else launch; otherwise a no-op
  - `stop ?-sync?` — always bumps the net epoch and cancels the READY timer. Owned runtime: `runtime.shutdown {launch_token}` (async form only), close the pipe (stdin EOF, which `--watch-stdin` obeys), `kill` (TERM), then `kill -9` after `shutdown_kill_ms` if it is still alive; `-sync` does the wait as a blocking sleep with no event loop and returns once the process is gone, for `reload`/`cleanup`, which tear the registry down right after (P06-T09). Attached runtime: disconnect only, never signalled, no `runtime.shutdown`. Ends in `stopped`.
  - `state -> stopped|launching|connecting|ready|reconnecting|down`
  - `subscribe cmd` — each change of state runs `{*}$cmd old new detail` at global level (errors logged); a command is added once. `detail` is a short human sentence for `down` (for example `Nothing answered on 127.0.0.1:8765.`, `This runtime is too old (protocol 1).`, the last line the runtime printed), else usually empty.
  - `info -> dict {host port pid version protocol launch_token owned}` (every key always present; `owned` 1 for a launched runtime)
  - `pipe_tail ?n? -> list` — the last `n` (default 12) of the 50 kept lines the runtime printed (stdout and stderr merged by `2>@1`)
  - `launch_command python main -> list` = `[list $python -u $main --port 0 --announce --watch-stdin 2>@1]`
  - `failure_reason -> didnt_start|too_old|unreachable|""`
  - seams that P06-T06's tests replace: `_spawn cmd gen -> {chan pid}` (opens `|$cmd` `r+`, non-blocking, line-buffered, and registers the readable fileevent through sched), `_close_pipe`, `_probe callback` (`net::http_get /health … -timeout 1500`), `_signal pid sig`, `_alive pid`; internal entry points `_pipe_line gen line`, `_pipe_eof gen`, `_process_exited`, `_became_ready`, `_fail reason detail`, `_set_state new ?detail?`, `_read_token port`, `_terminate pid sync`, and the variables `gen`, `chan`, `child_pid`

- [ ] **Step 1: Create the stub runtimes**

Create `tests/fixtures/stub_runtime/fail_runtime.py`:

```python
"""Stub runtime that dies at import time, like a missing module (P06-T05).

It writes a traceback to stderr and exits 1 without a READY line, so the
plugin must show "Runtime didn't start" with this text in the pipe tail.
"""
import sys

sys.stderr.write("Traceback (most recent call last):\n")
sys.stderr.write('  File "runtime/main.py", line 12, in <module>\n')
sys.stderr.write("    import vmd_ai_runtime_missing\n")
sys.stderr.write("ModuleNotFoundError: No module named 'vmd_ai_runtime_missing'\n")
sys.stderr.flush()
sys.exit(1)
```

Create `tests/fixtures/stub_runtime/ready_runtime.py`:

```python
"""Stub runtime for the plugin launch tests (P06-T05).

Takes main.py's flags (--port 0 --announce --watch-stdin), serves GET /health
and the runtime.shutdown RPC on 127.0.0.1:<ephemeral>, and prints the
VMDAI_READY line. Switches (environment variables):

  STUB_NOISE=1        60 warning lines on stderr, then a partial line, then READY
  STUB_NO_READY=1     never print READY
  STUB_PROTOCOL=<n>   protocol in READY and /health (default 2)
  STUB_IGNORE_TERM=1  ignore SIGTERM, stdin EOF and runtime.shutdown
"""
import argparse
import json
import os
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--announce", action="store_true")
    parser.add_argument("--watch-stdin", action="store_true")
    args, _unknown = parser.parse_known_args()
    protocol = int(os.environ.get("STUB_PROTOCOL", "2"))
    stubborn = os.environ.get("STUB_IGNORE_TERM") == "1"
    token = secrets.token_hex(16)
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, payload, status=200):
            raw = json.dumps(payload).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/health":
                self._json({"ok": True, "pid": os.getpid(), "version": "0.3.0-stub",
                            "protocol": protocol})
            else:
                self._json({"ok": False}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            params = body.get("params") or {}
            if body.get("method") == "runtime.shutdown" and params.get("launch_token") == token:
                self._json({"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}})
                if not stubborn:
                    done.set()
                return
            self._json({"jsonrpc": "2.0", "id": body.get("id"),
                        "error": {"code": "METHOD_NOT_FOUND", "message": "stub", "data": {}}})

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if stubborn:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, lambda *_: done.set())
        if args.watch_stdin:
            def watch() -> None:
                sys.stdin.read()
                done.set()
            threading.Thread(target=watch, daemon=True).start()
    if os.environ.get("STUB_NOISE") == "1":
        for i in range(60):
            print(f"DeprecationWarning: noise line {i}", file=sys.stderr, flush=True)
        sys.stderr.write("UserWarning: a partial line with no newline ")
        sys.stderr.flush()
    if os.environ.get("STUB_NO_READY") != "1":
        ready = {"port": server.server_port, "pid": os.getpid(), "version": "0.3.0-stub",
                 "protocol": protocol, "launch_token": token}
        print("VMDAI_READY " + json.dumps(ready, separators=(",", ":")), flush=True)
    done.wait()
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing tests**

Create `tests/tcl/test_runtime_launch.tcl`:

```tcl
# tests/tcl/test_runtime_launch.tcl - runtime.tcl launch, READY, attach and
# stop against real stub processes (P06-T05). Environment from the wrapper:
#   VMD_AI_PYTHON     a python3 wrapper in a directory whose name has a space
#   VMDAI_STUB_DIR    a copy of tests/fixtures/stub_runtime in a spaced path
#   VMDAI_ATTACH_PORT FakeRpcServer with a token file (token VMDAI_TOKEN,
#                     /health pid VMDAI_SLEEPER_PID)
#   VMDAI_OLD_PORT    FakeRpcServer whose /health is {"ok": true} (protocol 1)
#   VMDAI_PID_LOG     every child pid is appended here; the wrapper kills leftovers
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime} { source [file join $plugin $m.tcl] }

proc wait_for {script {ms 5000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 20 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}

proc sleep_ms {ms} {
    set ::_slept 0
    after $ms {set ::_slept 1}
    vwait ::_slept
}

proc alive {pid} { expr {$pid ne "" && ![catch {exec kill -0 $pid}]} }

proc log_pid {} {
    set pid $::vmdai::runtime::child_pid
    if {$pid ne ""} {
        set fh [open $::env(VMDAI_PID_LOG) a]; puts $fh $pid; close $fh
    }
    return $pid
}

set ::transitions {}
set ::last_detail ""
proc record {old new detail} {
    lappend ::transitions "$old>$new"
    set ::last_detail $detail
}
::vmdai::runtime::subscribe record

proc use_stub {name} {
    set ::vmdai::config::runtime_main [file join $::env(VMDAI_STUB_DIR) $name]
}

proc fresh {} {
    ::vmdai::runtime::stop -sync
    ::vmdai::sched::teardown
    set ::transitions {}
    foreach v {STUB_NOISE STUB_NO_READY STUB_PROTOCOL STUB_IGNORE_TERM VMD_AI_ATTACH} {
        unset -nocomplain ::env($v)
    }
    set ::vmdai::config::ready_timeout_ms 20000
    set ::vmdai::config::shutdown_kill_ms 1500
}

test rt-ready-1 {launch parses READY, checks /health and reaches ready} -setup fresh -body {
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    set started [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set i [::vmdai::runtime::info]
    list [::vmdai::runtime::state] $::transitions [dict get $i owned] [dict get $i protocol] \
        [dict get $i version] [regexp {^[0-9a-f]{32}$} [dict get $i launch_token]] \
        [expr {[dict get $i pid] == $started}] \
        [expr {[dict get [::vmdai::net::configure] -base_url] eq "http://127.0.0.1:[dict get $i port]"}] \
        [::vmdai::runtime::failure_reason]
} -cleanup fresh -result {ready {stopped>launching launching>connecting connecting>ready} 1 2 0.3.0-stub 1 1 1 {}}

test rt-noise-1 {READY is found after 60 noise lines and a partial stderr line} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_NOISE) 1
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set all [::vmdai::runtime::pipe_tail 50]
    list [::vmdai::runtime::state] [llength $all] [llength [::vmdai::runtime::pipe_tail]] \
        [string match "UserWarning: a partial line*VMDAI_READY*" [lindex $all end]] \
        [lindex [::vmdai::runtime::pipe_tail 2] 0]
} -cleanup fresh -result {ready 50 12 1 {DeprecationWarning: noise line 59}}

test rt-fail-1 {stderr then exit: didnt_start, the traceback in the tail, nothing left running} -setup fresh -body {
    use_stub fail_runtime.py
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] \
        [lindex [::vmdai::runtime::pipe_tail] end] $::vmdai::runtime::chan \
        [::vmdai::sched::pending] [lindex $::transitions end]
} -cleanup fresh -result {down didnt_start {ModuleNotFoundError: No module named 'vmd_ai_runtime_missing'} {} {} launching>down}

test rt-fail-2 {a Python that cannot run is didnt_start with the error in the tail} -setup fresh -body {
    set saved $::env(VMD_AI_PYTHON)
    set ::env(VMD_AI_PYTHON) [file join $::env(HOME) "no such dir" python3]
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    set ::env(VMD_AI_PYTHON) $saved
    list [::vmdai::runtime::failure_reason] [expr {[llength [::vmdai::runtime::pipe_tail]] > 0}]
} -cleanup fresh -result {didnt_start 1}

test rt-timeout-1 {no READY within the timeout: didnt_start and the process is stopped} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_NO_READY) 1
    set ::vmdai::config::ready_timeout_ms 600
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    wait_for {expr {![alive $pid]}} 3000
    list [::vmdai::runtime::failure_reason] [string match "*READY*" $::last_detail] [alive $pid]
} -cleanup fresh -result {didnt_start 1 0}

test rt-old-1 {an owned runtime that reports protocol 1 is too_old and is stopped} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_PROTOCOL) 1
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    wait_for {expr {![alive $pid]}} 3000
    list [::vmdai::runtime::failure_reason] [alive $pid]
} -cleanup fresh -result {too_old 0}

test rt-old-2 {an attached runtime whose /health has no protocol is too_old} -setup fresh -body {
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$::env(VMDAI_OLD_PORT).json] w]
    puts $fh "{\"port\": $::env(VMDAI_OLD_PORT), \"pid\": 1, \"token\": \"[string repeat 0 32]\", \"protocol\": 1}"
    close $fh
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_OLD_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list [::vmdai::runtime::failure_reason] $::last_detail [dict get [::vmdai::runtime::info] owned]
} -cleanup fresh -result {too_old {This runtime is too old (protocol 1).} 0}

test rt-attach-1 {attach reads the token file and never launches} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set i [::vmdai::runtime::info]
    list [::vmdai::runtime::state] [dict get $i owned] \
        [expr {[dict get $i launch_token] eq $::env(VMDAI_TOKEN)}] \
        [expr {[dict get $i pid] == $::env(VMDAI_SLEEPER_PID)}] $::vmdai::runtime::chan
} -cleanup fresh -result {ready 0 1 1 {}}

test rt-attach-2 {attach without a token file, or to a closed port, is unreachable} -setup fresh -body {
    set srv [socket -server {apply {{c a p} {close $c}}} -myaddr 127.0.0.1 0]
    set dead [lindex [fconfigure $srv -sockname] 2]
    close $srv
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$dead
    ::vmdai::runtime::ensure
    set no_token [list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason]]
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$dead.json] w]
    puts $fh "{\"port\": $dead, \"pid\": 1, \"token\": \"[string repeat a 32]\", \"protocol\": 2}"
    close $fh
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "down"}}
    list $no_token [::vmdai::runtime::failure_reason] [lindex $::transitions end]
} -cleanup fresh -result {{down unreachable} unreachable connecting>down}

test rt-attach-3 {a malformed VMD_AI_ATTACH is unreachable with the reason} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 10.1.2.3:8765
    ::vmdai::runtime::ensure
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason]
} -cleanup fresh -result {down unreachable}

test rt-stop-1 {stop escalates to SIGKILL for an owned runtime that ignores SIGTERM} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_IGNORE_TERM) 1
    set ::vmdai::config::shutdown_kill_ms 300
    ::vmdai::runtime::ensure
    set pid [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    set t0 [clock milliseconds]
    ::vmdai::runtime::stop
    set right_after [alive $pid]
    wait_for {expr {![alive $pid]}} 3000
    list $right_after [alive $pid] [expr {[clock milliseconds] - $t0 < 2000}] \
        [::vmdai::runtime::state] [::vmdai::sched::pending]
} -cleanup fresh -result {1 0 1 stopped {}}

test rt-stop-2 {stop -sync waits, then kills; the plain runtime exits on its own} -setup fresh -body {
    use_stub "ready runtime.py"
    set ::env(STUB_IGNORE_TERM) 1
    set ::vmdai::config::shutdown_kill_ms 300
    ::vmdai::runtime::ensure
    set stubborn [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop -sync
    set stubborn_alive [alive $stubborn]
    unset ::env(STUB_IGNORE_TERM)
    ::vmdai::runtime::ensure
    set plain [log_pid]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop
    wait_for {expr {![alive $plain]}} 2000
    list $stubborn_alive [alive $plain] [::vmdai::runtime::state]
} -cleanup fresh -result {0 0 stopped}

test rt-stop-3 {stop never kills or shuts down an attached runtime} -setup fresh -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    ::vmdai::runtime::stop
    sleep_ms 300
    list [::vmdai::runtime::state] [alive $::env(VMDAI_SLEEPER_PID)]
} -cleanup fresh -result {stopped 1}

test rt-spaces-1 {HOME, the Python wrapper and the runtime path all contain spaces} -setup fresh -body {
    use_stub "ready runtime.py"
    ::vmdai::runtime::ensure
    log_pid
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    list [string match "* *" $::env(HOME)] [string match "* *" $::env(VMD_AI_PYTHON)] \
        [string match "* *" $::vmdai::config::runtime_main] [::vmdai::runtime::state] \
        [file exists [::vmdai::config::plugin_log_path]]
} -cleanup fresh -result {1 1 1 ready 1}

cleanupTests
```

Create `tests/test_tcl_runtime_launch.py`:

```python
"""runtime.tcl: launch, READY, attach and stop against stub processes (P06-T05).

Runs tests/tcl/test_runtime_launch.tcl once with HOME, the Python wrapper and
the stub runtime all under paths that contain spaces.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import List

import pytest

from helpers.fake_rpc_server import FakeRpcServer, Recorded
from helpers.tcl import REPO, TclTestResult, run_tcltest
from vmd_ai_runtime.launch import write_token_file

TCL_FILE = REPO / "tests" / "tcl" / "test_runtime_launch.tcl"
STUBS = REPO / "tests" / "fixtures" / "stub_runtime"
TOTAL = 14
TOKEN = "0123456789abcdef0123456789abcdef"


@dataclass
class LaunchRun:
    result: TclTestResult
    attach_requests: List[Recorded]
    sleeper_alive_after: bool


def _kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


@pytest.fixture(scope="module")
def launch_run(tmp_path_factory) -> LaunchRun:
    base = tmp_path_factory.mktemp("launch")
    home = base / "home dir"
    home.mkdir()
    py_dir = base / "py dir"
    py_dir.mkdir()
    python = py_dir / "python3"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    stub_dir = base / "stub dir"
    stub_dir.mkdir()
    shutil.copy(STUBS / "ready_runtime.py", stub_dir / "ready runtime.py")
    shutil.copy(STUBS / "fail_runtime.py", stub_dir / "fail_runtime.py")
    pid_log = base / "pids.txt"
    pid_log.write_text("")
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    health = {"ok": True, "pid": sleeper.pid, "version": "0.3.0", "protocol": 2}
    try:
        with FakeRpcServer(health=health) as attach, FakeRpcServer(health={"ok": True}) as old:
            write_token_file(attach.port, sleeper.pid, TOKEN, 2, home=str(home))
            env = {
                "HOME": str(home),
                "VMD_AI_PYTHON": str(python),
                "VMDAI_STUB_DIR": str(stub_dir),
                "VMDAI_ATTACH_PORT": str(attach.port),
                "VMDAI_OLD_PORT": str(old.port),
                "VMDAI_TOKEN": TOKEN,
                "VMDAI_SLEEPER_PID": str(sleeper.pid),
                "VMDAI_PID_LOG": str(pid_log),
            }
            result = run_tcltest(str(TCL_FILE), env=env, timeout=120)
            requests = list(attach.requests)
        return LaunchRun(result, requests, sleeper.poll() is None)
    finally:
        for line in pid_log.read_text().split():
            _kill_quietly(int(line))
        sleeper.kill()
        sleeper.wait()


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(launch_run):
    assert (launch_run.result.passed, launch_run.result.failed) == (TOTAL, 0), launch_run.result.output


def test_ready_parsed(launch_run):
    _assert_passed(launch_run.result, ["rt-ready-1"])


def test_ready_after_noise(launch_run):
    _assert_passed(launch_run.result, ["rt-noise-1"])


def test_stderr_then_exit_didnt_start_with_tail(launch_run):
    _assert_passed(launch_run.result, ["rt-fail-1", "rt-fail-2"])


def test_ready_timeout(launch_run):
    _assert_passed(launch_run.result, ["rt-timeout-1"])


def test_attach_reads_token_file(launch_run):
    _assert_passed(launch_run.result, ["rt-attach-1", "rt-attach-2", "rt-attach-3"])


def test_too_old_protocol(launch_run):
    _assert_passed(launch_run.result, ["rt-old-1", "rt-old-2"])


def test_stop_owned_escalates_never_attached(launch_run):
    _assert_passed(launch_run.result, ["rt-stop-1", "rt-stop-2", "rt-stop-3"])
    assert [r for r in launch_run.attach_requests if r.method == "runtime.shutdown"] == []
    assert launch_run.sleeper_alive_after


def test_paths_with_spaces(launch_run):
    _assert_passed(launch_run.result, ["rt-spaces-1"])
```

The whole file runs once with `HOME`, the Python wrapper and the stub runtime under paths that contain spaces, so every launch in it also exercises `test_paths_with_spaces`. The wrapper kills every pid the Tcl side logged, so a failing test leaves no stub running.

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_runtime_launch.py -q`
Expected: `9 failed`; the output shows `couldn't read file ".../plugin/runtime.tcl": no such file or directory`.

- [ ] **Step 4: Create `plugin/runtime.tcl`**

```tcl
# runtime.tcl - launch, attach and stop the AI runtime, and the connection
# state machine (spec 2d, 5). No Tk.
#
# States: stopped -> launching -> connecting -> ready <-> reconnecting -> down.
# Subscribers run as {*}$cmd old new detail on every change of state.

namespace eval ::vmdai::runtime {
    variable state
    if {![::info exists state]} { set state stopped }
    variable info
    if {![::info exists info]} {
        set info [dict create host "" port "" pid "" version "" protocol "" launch_token "" owned 0]
    }
    # Owned runtime: the pipe channel and the child's pid.
    variable chan
    if {![::info exists chan]} { set chan "" }
    variable child_pid
    if {![::info exists child_pid]} { set child_pid "" }
    # Last 50 lines the runtime wrote before and after READY.
    variable tail
    if {![::info exists tail]} { set tail {} }
    variable failure
    if {![::info exists failure]} { set failure "" }
    variable subscribers
    if {![::info exists subscribers]} { set subscribers {} }
    # Bumped on every launch, attach and stop; stale callbacks compare it.
    variable gen
    if {![::info exists gen]} { set gen 0 }
    variable ready_timer
    if {![::info exists ready_timer]} { set ready_timer "" }
    variable tail_max 50
}

proc ::vmdai::runtime::_log {msg} {
    catch {::vmdai::config::log "runtime: $msg"}
}

proc ::vmdai::runtime::state {} {
    variable state
    return $state
}

proc ::vmdai::runtime::info {} {
    variable info
    return $info
}

proc ::vmdai::runtime::failure_reason {} {
    variable failure
    return $failure
}

proc ::vmdai::runtime::pipe_tail {{n 12}} {
    variable tail
    if {$n <= 0} {
        return {}
    }
    return [lrange $tail end-[expr {$n - 1}] end]
}

proc ::vmdai::runtime::subscribe {cmd} {
    variable subscribers
    if {[lsearch -exact $subscribers $cmd] < 0} {
        lappend subscribers $cmd
    }
    return
}

proc ::vmdai::runtime::launch_command {python main} {
    return [list $python -u $main --port 0 --announce --watch-stdin 2>@1]
}

proc ::vmdai::runtime::_set_state {new {detail ""}} {
    variable state
    variable subscribers
    set old $state
    if {$old eq $new} {
        return
    }
    set state $new
    _log "$old -> $new $detail"
    foreach cmd $subscribers {
        if {[catch {uplevel #0 [list {*}$cmd $old $new $detail]} err]} {
            _log "subscriber $cmd failed: $err"
        }
    }
}

proc ::vmdai::runtime::_tail_add {line} {
    variable tail
    variable tail_max
    lappend tail [string trimright $line "\r"]
    if {[llength $tail] > $tail_max} {
        set tail [lrange $tail end-[expr {$tail_max - 1}] end]
    }
}

# --- seams (tests replace these) -------------------------------------------

# Start the runtime pipeline; returns {chan pid}.
proc ::vmdai::runtime::_spawn {cmd g} {
    set ch [open "|$cmd" r+]
    fconfigure $ch -blocking 0 -buffering line -translation auto -encoding utf-8
    ::vmdai::sched::fileevent $ch readable [list ::vmdai::runtime::_on_readable $g $ch]
    return [list $ch [lindex [pid $ch] 0]]
}

proc ::vmdai::runtime::_close_pipe {} {
    variable chan
    if {$chan eq ""} {
        return
    }
    catch {::vmdai::sched::fileevent $chan readable {}}
    # Non-blocking, so close never waits for the child.
    catch {fconfigure $chan -blocking 0}
    catch {close $chan}
    set chan ""
}

proc ::vmdai::runtime::_probe {callback} {
    ::vmdai::net::http_get /health $callback -timeout 1500
}

proc ::vmdai::runtime::_signal {pid sig} {
    if {$pid ne ""} {
        catch {exec kill -$sig $pid}
    }
}

proc ::vmdai::runtime::_alive {pid} {
    if {$pid eq ""} {
        return 0
    }
    return [expr {![catch {exec kill -0 $pid}]}]
}

# --- launch -----------------------------------------------------------------

proc ::vmdai::runtime::ensure {} {
    variable state
    if {$state ni {stopped down}} {
        return $state
    }
    if {[catch {::vmdai::config::attach_target} target]} {
        _fail unreachable $target
        return [state]
    }
    if {$target ne ""} {
        _attach [lindex $target 0] [lindex $target 1]
    } else {
        _launch
    }
    return [state]
}

proc ::vmdai::runtime::_reset_info {owned} {
    variable info
    set info [dict create host 127.0.0.1 port "" pid "" version "" protocol "" \
        launch_token "" owned $owned]
}

proc ::vmdai::runtime::_launch {} {
    variable gen
    variable tail
    variable chan
    variable child_pid
    variable failure
    variable ready_timer
    set g [incr gen]
    set failure ""
    set tail {}
    _reset_info 1
    set python [::vmdai::config::resolve_python]
    if {$python eq ""} {
        _fail didnt_start "No Python 3 found. Set VMD_AI_PYTHON or choose Python in Settings."
        return
    }
    set cmd [launch_command $python $::vmdai::config::runtime_main]
    _set_state launching
    if {[catch {_spawn $cmd $g} spawned]} {
        _tail_add $spawned
        _fail didnt_start $spawned
        return
    }
    lassign $spawned chan child_pid
    set ready_timer [::vmdai::sched::after $::vmdai::config::ready_timeout_ms \
        [list ::vmdai::runtime::_ready_timeout $g]]
}

proc ::vmdai::runtime::_on_readable {g ch} {
    variable gen
    variable chan
    while {$g == $gen && $ch eq $chan && [gets $ch line] >= 0} {
        _pipe_line $g $line
    }
    if {$g == $gen && $ch eq $chan && [eof $ch]} {
        _pipe_eof $g
    }
}

proc ::vmdai::runtime::_pipe_line {g line} {
    variable state
    _tail_add $line
    set at [string first "VMDAI_READY \{" $line]
    if {$at >= 0 && $state eq "launching"} {
        _on_ready $g [string range $line [expr {$at + 12}] end]
    }
}

proc ::vmdai::runtime::_on_ready {g payload} {
    variable info
    variable ready_timer
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    if {[catch {::vmdai::net::decode $payload} ready]
            || ![dict exists $ready port] || ![dict exists $ready launch_token]} {
        _fail didnt_start "The runtime printed a malformed READY line."
        return
    }
    foreach key {port pid version protocol launch_token} {
        if {[dict exists $ready $key]} {
            dict set info $key [dict get $ready $key]
        }
    }
    if {![string is integer -strict [dict get $info protocol]] || [dict get $info protocol] < 2} {
        _too_old [dict get $info protocol]
        return
    }
    ::vmdai::net::configure -base_url "http://127.0.0.1:[dict get $info port]"
    _set_state connecting
    _probe [list ::vmdai::runtime::_on_health $g connect]
}

proc ::vmdai::runtime::_pipe_eof {g} {
    variable state
    variable tail
    _close_pipe
    if {$state in {launching connecting}} {
        set last "The runtime exited before it was ready."
        for {set i [expr {[llength $tail] - 1}]} {$i >= 0} {incr i -1} {
            if {[string trim [lindex $tail $i]] ne ""} {
                set last [string trim [lindex $tail $i]]
                break
            }
        }
        _fail didnt_start $last
        return
    }
    _process_exited
}

# An owned runtime's pipe hit EOF after it was ready.
proc ::vmdai::runtime::_process_exited {} {
    _fail unreachable "The AI runtime exited."
}

proc ::vmdai::runtime::_ready_timeout {g} {
    variable gen
    variable state
    if {$g != $gen || $state ne "launching"} {
        return
    }
    _fail didnt_start "The runtime printed no READY line within [expr {$::vmdai::config::ready_timeout_ms / 1000}] s."
}

proc ::vmdai::runtime::_too_old {protocol} {
    if {$protocol eq ""} {
        set protocol 1
    }
    _fail too_old "This runtime is too old (protocol $protocol)."
}

# Go to `down`, stopping an owned process that is still running.
proc ::vmdai::runtime::_fail {reason detail} {
    variable failure
    variable info
    variable child_pid
    variable ready_timer
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    set failure $reason
    if {[dict get $info owned]} {
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid 0
        }
    }
    _set_state down $detail
}

proc ::vmdai::runtime::_on_health {g purpose kind args} {
    variable gen
    variable info
    if {$g != $gen} {
        return
    }
    if {$kind ne "ok"} {
        _fail unreachable "Nothing answered on [dict get $info host]:[dict get $info port]."
        return
    }
    set body [lindex $args 0]
    set protocol 1
    catch {set protocol [dict get $body protocol]}
    if {![string is integer -strict $protocol] || $protocol < 2} {
        _too_old $protocol
        return
    }
    catch {dict set info pid [dict get $body pid]}
    catch {dict set info version [dict get $body version]}
    dict set info protocol $protocol
    _became_ready
}

proc ::vmdai::runtime::_became_ready {} {
    _set_state ready
}

# --- attach -----------------------------------------------------------------

proc ::vmdai::runtime::_read_token {port} {
    set path [::vmdai::config::token_file_path $port]
    if {[catch {
        set fh [open $path r]
        set text [read $fh]
        close $fh
        set token [dict get [::vmdai::net::decode $text] token]
    }]} {
        return ""
    }
    return $token
}

proc ::vmdai::runtime::_attach {host port} {
    variable gen
    variable info
    variable failure
    set g [incr gen]
    set failure ""
    _reset_info 0
    dict set info host $host
    dict set info port $port
    set token [_read_token $port]
    if {$token eq ""} {
        _fail unreachable "No token file at [::vmdai::config::token_file_path $port]. Start the runtime with scripts/run_runtime.sh."
        return
    }
    dict set info launch_token $token
    ::vmdai::net::configure -base_url "http://$host:$port"
    _set_state connecting
    _probe [list ::vmdai::runtime::_on_health $g attach]
}

# --- stop -------------------------------------------------------------------

# TERM now; KILL after shutdown_kill_ms if it is still alive. With sync=1 the
# wait is a blocking sleep (no event loop), for reload/cleanup.
proc ::vmdai::runtime::_terminate {pid sync} {
    _signal $pid TERM
    set ms $::vmdai::config::shutdown_kill_ms
    if {!$sync} {
        ::vmdai::sched::after $ms [list ::vmdai::runtime::_kill_if_alive $pid]
        return
    }
    set deadline [expr {[clock milliseconds] + $ms}]
    while {[_alive $pid] && [clock milliseconds] < $deadline} {
        ::after 50
    }
    _kill_if_alive $pid
    # Give SIGKILL a moment; each `exec kill -0` also reaps the exited child.
    set deadline [expr {[clock milliseconds] + 500}]
    while {[_alive $pid] && [clock milliseconds] < $deadline} {
        ::after 20
    }
}

proc ::vmdai::runtime::_kill_if_alive {pid} {
    if {[_alive $pid]} {
        _log "pid $pid ignored SIGTERM; sending SIGKILL"
        _signal $pid KILL
    }
}

# Stop the runtime. An owned runtime gets runtime.shutdown, stdin EOF, TERM,
# then KILL; an attached runtime is only disconnected, never killed.
proc ::vmdai::runtime::stop {args} {
    variable gen
    variable info
    variable child_pid
    variable failure
    variable ready_timer
    set sync [expr {[lsearch -exact $args -sync] >= 0}]
    incr gen
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    catch {::vmdai::net::bump_epoch}
    if {[dict get $info owned]} {
        set token [dict get $info launch_token]
        if {$token ne "" && [dict get $info port] ne "" && !$sync} {
            catch {::vmdai::net::call runtime.shutdown [list launch_token s $token] \
                ::vmdai::runtime::_ignore -session 0}
        }
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid $sync
        }
    }
    set child_pid ""
    set failure ""
    _reset_info 0
    dict set info host ""
    _set_state stopped
    return
}

proc ::vmdai::runtime::_ignore {args} {}
```

Notes for the reviewer:
- The pipe is drained by a fileevent for the life of the process, so a chatty runtime never blocks on a full pipe, and every line lands in the 50-line tail for the "Runtime didn't start" banner (§5).
- READY is searched anywhere in a line (`string first "VMDAI_READY \{"`), because a partial stderr line without a newline can share a line with it on the merged pipe (`test_ready_after_noise`).
- Every `close` is wrapped in `catch` and done in non-blocking mode, so closing never waits for the child. `gen` makes callbacks from an older launch, attach or stop no-ops.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_runtime_launch.py tests/test_tcl_lint.py -q`
Expected: `12 passed` in about 6 s.

Run: `pgrep -f "ready runtime.py" | wc -l`
Expected: `0` (no stub left running).

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+31 passed`, `0 failed`, still under 60 s.

- [ ] **Step 7: Commit**

```bash
git add plugin/runtime.tcl tests/fixtures/stub_runtime/fail_runtime.py tests/fixtures/stub_runtime/ready_runtime.py tests/tcl/test_runtime_launch.tcl tests/test_tcl_runtime_launch.py
git commit -F - <<'MSG'
feat(plugin): runtime.tcl non-blocking launch, READY, attach and stop

The runtime starts as `open |[list $python -u main.py --port 0 --announce
--watch-stdin 2>@1] r+`; a fileevent drains the pipe for its lifetime and
keeps a 50-line tail. EOF or 20 s without READY is didnt_start; protocol
< 2 is too_old. Attach reads ~/.vmdai/run/runtime-<port>.json. stop sends
runtime.shutdown, closes stdin, TERM, then KILL after 1.5 s, and never
signals an attached runtime.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 6: P06-T06 — Connection state machine and notices (S3)

**Files:**
- Modify: `plugin/runtime.tcl` (namespace block; six procs replaced whole; the state-machine section appended)
- Test: `tests/tcl/test_state_machine.tcl`, `tests/test_tcl_state_machine.py`

**Interfaces:**
- Consumes: `::vmdai::runtime::*` and its seams `_spawn`, `_close_pipe`, `_probe`, `_signal`, `_alive`, plus `_pipe_line`, `_pipe_eof`, `_launch`, `_read_token`, `_terminate`, `gen`, `chan`, `child_pid` (P06-T05); `::vmdai::sched::after`, `cancel` (P06-T02).
- Produces (`::vmdai::runtime`):
  - `on_transport_error reason` — in `ready`: go to `reconnecting` and probe `/health` after `backoff_ms 1`; in any other state a no-op (so an error flood gives one notice)
  - `on_transport_ok` — in `reconnecting`: cancel the pending probe and probe at once; else a no-op
  - `on_auth_failed` (plan addition) — in `ready`: for an attached runtime re-read the token file (a restarted runtime has a new token), then call `::vmdai::bridge::recover`; else a no-op
  - `retry_now -> state` — from `down` or `stopped`: reset the respawn budget and `ensure`; in `reconnecting`: reset the backoff and probe now
  - `backoff_ms attempt -> ms` — 500, 1000, 2000, 4000, then 8000 (spec: 0.5–8 s)
  - Reconnect rules. An owned runtime whose pipe hits EOF after `ready` goes to `reconnecting`; the next tick respawns it (at most 3 respawns; `retry_now` and `stop` reset the count). A respawn that fails to start goes back to `reconnecting` until the budget is spent, then `down` with the last reason. An owned runtime that is alive but fails 5 probes in a row is terminated (TERM, KILL after `shutdown_kill_ms`) and respawned. An attached runtime is never respawned: it is probed with the backoff (capped at 8 s, so it is back within 10 s of a restart, S3) and its token file is re-read on every successful probe. A `/health` protocol below 2 is `down`/`too_old`.
  - Notices: `::vmdai::ui::notify level text` once per transition, when the proc exists: `ready -> reconnecting` warn "Lost the connection to the AI runtime; reconnecting."; `reconnecting -> launching` warn "The AI runtime stopped; restarting it (N of 3)."; `-> ready` after a reconnect or respawn info "Reconnected to the AI runtime."; `-> down` error "The AI runtime didn't start: <detail>" / "<detail>" for too_old / "Can't reach the AI runtime: <detail>". The first start and `stop` give no notice (the status bar shows them). Every notice is also written to the plugin log.
  - `::vmdai::bridge::recover` (when the proc exists) is called once when the runtime becomes `ready` with a pid different from the previous `ready` pid, and from `on_auth_failed`. The first `ready` after `ensure` or `stop` calls only the subscribers.
  - Contract for the bridge (P06-T07): call `on_transport_error` on a `transport` reply of any session RPC, `on_transport_ok` on an `ok` or `rpc_error` reply, and `on_auth_failed` on `AUTH_FAILED` from any RPC except `session.start` itself; start the first session from a `subscribe` callback on the first `ready`; keep the poll pump idle while the state is not `ready`; `recover` bumps the epoch, runs `session.start` and `chat.resume` for the current chat, and reports the lost request (§2d, §5).

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_state_machine.tcl`:

```tcl
# tests/tcl/test_state_machine.tcl - connection state machine (P06-T06, S3).
# Deterministic: the scheduler, the process seams and /health are faked, and
# the tests fire timers by hand.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime} { source [file join $plugin $m.tcl] }

# --- fakes --------------------------------------------------------------------
# Timers: ::timers is a list of {id ms script}; fire_probe runs the first
# reconnect timer (kill timers from _terminate are left alone).
set ::timer_seq 0
set ::timers {}
proc ::vmdai::sched::after {ms script} {
    set id fake#[incr ::timer_seq]
    lappend ::timers [list $id $ms $script]
    return $id
}
proc ::vmdai::sched::cancel {id} {
    set keep {}
    foreach t $::timers { if {[lindex $t 0] ne $id} { lappend keep $t } }
    set ::timers $keep
}
proc fire_probe {} {
    set i [lsearch -glob $::timers {* *_reconnect_tick *}]
    set t [lindex $::timers $i]
    set ::timers [lreplace $::timers $i $i]
    uplevel #0 [lindex $t 2]
    return [lindex $t 1]
}
proc probe_ms {} {
    set r {}
    foreach t $::timers {
        if {[string match *_reconnect_tick* [lindex $t 2]]} { lappend r [lindex $t 1] }
    }
    return $r
}

# Processes: _spawn hands out fake pids 9001, 9002, ...; ::alive holds live pids.
set ::spawned {}
set ::alive {}
set ::signals {}
proc ::vmdai::config::resolve_python {} { return /fake/python3 }
proc ::vmdai::runtime::_spawn {cmd g} {
    set pid [expr {9001 + [llength $::spawned]}]
    lappend ::spawned $pid
    lappend ::alive $pid
    return [list fakechan$pid $pid]
}
proc ::vmdai::runtime::_close_pipe {} { set ::vmdai::runtime::chan "" }
proc ::vmdai::runtime::_alive {pid} { expr {$pid in $::alive} }
proc ::vmdai::runtime::_signal {pid sig} {
    lappend ::signals "$sig $pid"
    set i [lsearch -exact $::alive $pid]
    if {$i >= 0} { set ::alive [lreplace $::alive $i $i] }
}
# /health: ::health is a list of replies, e.g. {ok {pid 9001 protocol 2}} or
# {transport refused}; the last one repeats.
set ::health {}
set ::probes 0
proc ::vmdai::runtime::_probe {callback} {
    incr ::probes
    set reply [lindex $::health 0]
    if {[llength $::health] > 1} { set ::health [lrange $::health 1 end] }
    uplevel #0 [list {*}$callback {*}$reply]
}
# Sinks.
namespace eval ::vmdai::ui {}
namespace eval ::vmdai::bridge {}
set ::notices {}
proc ::vmdai::ui::notify {level text} { lappend ::notices [list $level $text] }
set ::recovers 0
proc ::vmdai::bridge::recover {} { incr ::recovers }
set ::transitions {}
proc record {old new detail} { lappend ::transitions "$old>$new" }
::vmdai::runtime::subscribe record

proc current_gen {} { return $::vmdai::runtime::gen }
proc ready_line {pid} {
    return "VMDAI_READY \{\"port\":40001,\"pid\":$pid,\"version\":\"0.3.0\",\"protocol\":2,\"launch_token\":\"[string repeat a 32]\"\}"
}
# Launch an owned runtime and bring it to ready.
proc start_owned {} {
    ::vmdai::runtime::ensure
    set pid [lindex $::spawned end]
    set ::health [list [list ok [list pid $pid protocol 2 version 0.3.0]]]
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line $pid]
    return $pid
}
proc reset_all {} {
    ::vmdai::runtime::stop -sync
    unset -nocomplain ::env(VMD_AI_ATTACH)
    set ::timers {}
    set ::spawned {}
    set ::alive {}
    set ::signals {}
    set ::health {}
    set ::probes 0
    set ::notices {}
    set ::recovers 0
    set ::transitions {}
}
proc write_token {port token} {
    set dir [file join $::env(HOME) .vmdai run]
    file mkdir $dir
    set fh [open [file join $dir runtime-$port.json] w]
    puts $fh "{\"port\": $port, \"pid\": 1, \"token\": \"$token\", \"protocol\": 2}"
    close $fh
}

# --- tests --------------------------------------------------------------------

test sm-backoff-1 {backoff_ms doubles from 0.5 s and caps at 8 s} -body {
    set r {}
    foreach a {1 2 3 4 5 6 7} { lappend r [::vmdai::runtime::backoff_ms $a] }
    set r
} -result {500 1000 2000 4000 8000 8000 8000}

test sm-notice-1 {one notice per transition; repeated errors add none} -setup reset_all -body {
    set pid [start_owned]
    set first_start [list [::vmdai::runtime::state] $::notices]
    foreach i {1 2 3 4 5} { ::vmdai::runtime::on_transport_error "connection refused" }
    set lost [list [::vmdai::runtime::state] [llength $::notices] [probe_ms]]
    set ::health [list [list ok [list pid $pid protocol 2]]]
    fire_probe
    list $first_start $lost [::vmdai::runtime::state] $::notices $::recovers \
        [lrange $::transitions end-1 end]
} -cleanup reset_all -result {{ready {}} {reconnecting 1 500} ready {{warn {Lost the connection to the AI runtime; reconnecting.}} {info {Reconnected to the AI runtime.}}} 0 {ready>reconnecting reconnecting>ready}}

test sm-backoff-2 {an attached runtime that stays away is probed at 0.5, 1, 2, 4, 8, 8 s} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40002
    write_token 40002 [string repeat b 32]
    set ::health [list [list ok {pid 500 protocol 2}]]
    ::vmdai::runtime::ensure
    set ::health [list {transport refused}]
    ::vmdai::runtime::on_transport_error "connection refused"
    set delays {}
    foreach i {1 2 3 4 5 6} { lappend delays [fire_probe] }
    list $delays [::vmdai::runtime::state] [llength $::notices] [probe_ms] $::spawned
} -cleanup reset_all -result {{500 1000 2000 4000 8000 8000} reconnecting 1 8000 {}}

test sm-respawn-1 {an owned runtime that keeps dying is respawned at most 3 times} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    foreach i {1 2 3} {
        fire_probe
        ::vmdai::runtime::_pipe_eof [current_gen]
    }
    set levels {}
    foreach n $::notices { lappend levels [lindex $n 0] }
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] [llength $::spawned] \
        $levels [lindex $::notices 1 1] [probe_ms]
} -cleanup reset_all -result {down didnt_start 4 {warn warn warn warn error} {The AI runtime stopped; restarting it (1 of 3).} {}}

test sm-respawn-2 {a respawn that reaches ready recovers the session once} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    fire_probe
    set new [lindex $::spawned end]
    set ::health [list [list ok [list pid $new protocol 2]]]
    ::vmdai::runtime::_pipe_line [current_gen] [ready_line $new]
    list [::vmdai::runtime::state] $::recovers [lindex $::notices end] $::vmdai::runtime::respawns
} -cleanup reset_all -result {ready 1 {info {Reconnected to the AI runtime.}} 1}

test sm-respawn-3 {after 3 respawns, a runtime that dies once more ends down/unreachable} -setup reset_all -body {
    start_owned
    foreach i {1 2 3} {
        set ::alive {}
        ::vmdai::runtime::_pipe_eof [current_gen]
        fire_probe
        set new [lindex $::spawned end]
        set ::health [list [list ok [list pid $new protocol 2]]]
        ::vmdai::runtime::_pipe_line [current_gen] [ready_line $new]
    }
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    fire_probe
    list [::vmdai::runtime::state] [::vmdai::runtime::failure_reason] [llength $::spawned] $::recovers
} -cleanup reset_all -result {down unreachable 4 3}

test sm-retry-1 {retry_now from down starts again with a fresh respawn budget} -setup reset_all -body {
    set pid [start_owned]
    set ::alive {}
    ::vmdai::runtime::_pipe_eof [current_gen]
    foreach i {1 2 3} { fire_probe; ::vmdai::runtime::_pipe_eof [current_gen] }
    set before [::vmdai::runtime::state]
    ::vmdai::runtime::retry_now
    list $before [::vmdai::runtime::state] [llength $::spawned] $::vmdai::runtime::respawns
} -cleanup reset_all -result {down launching 5 0}

test sm-newpid-1 {an attached runtime back with a new pid: new token, one recover} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40003
    write_token 40003 [string repeat c 32]
    set ::health [list [list ok {pid 100 protocol 2}]]
    ::vmdai::runtime::ensure
    set before [list [::vmdai::runtime::state] $::recovers]
    ::vmdai::runtime::on_transport_error "connection reset"
    write_token 40003 [string repeat d 32]
    set ::health [list [list ok {pid 200 protocol 2}]]
    fire_probe
    list $before [::vmdai::runtime::state] $::recovers \
        [dict get [::vmdai::runtime::info] pid] [dict get [::vmdai::runtime::info] launch_token]
} -cleanup reset_all -result [list {ready 0} ready 1 200 [string repeat d 32]]

test sm-auth-1 {AUTH_FAILED re-reads the attach token and recovers} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40004
    write_token 40004 [string repeat e 32]
    set ::health [list [list ok {pid 300 protocol 2}]]
    ::vmdai::runtime::ensure
    write_token 40004 [string repeat f 32]
    ::vmdai::runtime::on_auth_failed
    list [::vmdai::runtime::state] $::recovers [dict get [::vmdai::runtime::info] launch_token]
} -cleanup reset_all -result [list ready 1 [string repeat f 32]]

test sm-ok-1 {a successful RPC while reconnecting probes at once} -setup reset_all -body {
    set pid [start_owned]
    ::vmdai::runtime::on_transport_error "timeout"
    set probes_before $::probes
    set ::health [list [list ok [list pid $pid protocol 2]]]
    ::vmdai::runtime::on_transport_ok
    list [expr {$::probes - $probes_before}] [::vmdai::runtime::state] [probe_ms]
} -cleanup reset_all -result {1 ready {}}

test sm-hung-1 {an owned runtime that stops answering is killed and respawned} -setup reset_all -body {
    set pid [start_owned]
    set ::health [list {transport timeout}]
    ::vmdai::runtime::on_transport_error "timeout"
    foreach i {1 2 3 4 5} { fire_probe }
    list [lindex $::signals 0] [::vmdai::runtime::state] [llength $::spawned] $::vmdai::runtime::respawns
} -cleanup reset_all -result {{TERM 9001} launching 2 1}

test sm-stop-1 {stop while reconnecting cancels the probe timer} -setup reset_all -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:40005
    write_token 40005 [string repeat 1 32]
    set ::health [list [list ok {pid 400 protocol 2}]]
    ::vmdai::runtime::ensure
    set ::health [list {transport refused}]
    ::vmdai::runtime::on_transport_error "refused"
    set armed [llength $::timers]
    ::vmdai::runtime::stop
    list $armed $::timers [::vmdai::runtime::state] $::signals
} -cleanup reset_all -result {1 {} stopped {}}

cleanupTests
```

Create `tests/test_tcl_state_machine.py`:

```python
"""Connection state machine and notices (P06-T06; spec §2d, S3).

Runs tests/tcl/test_state_machine.tcl, which fakes the scheduler, the process
seams and /health so every transition is driven by hand.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_state_machine.tcl"
TOTAL = 12


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_one_notice_per_transition(result):
    _assert_passed(result, ["sm-notice-1", "sm-ok-1", "sm-stop-1"])


def test_backoff_sequence(result):
    _assert_passed(result, ["sm-backoff-1", "sm-backoff-2"])


def test_respawn_cap_3(result):
    _assert_passed(result, ["sm-respawn-1", "sm-respawn-2", "sm-respawn-3", "sm-retry-1", "sm-hung-1"])


def test_new_pid_triggers_recover(result):
    _assert_passed(result, ["sm-newpid-1", "sm-auth-1"])
```

Everything is driven by hand: `::vmdai::sched::after` records `{id ms script}` and `fire_probe` runs the next reconnect timer, `_spawn` hands out fake pids, and `_probe` answers from the `::health` script, so the whole file runs in well under a second.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_state_machine.py -q`
Expected: `5 failed`; the tcltest output shows `invalid command name "::vmdai::runtime::on_transport_error"` (and `backoff_ms`, `retry_now`, `on_auth_failed`), `Total 12 Passed 0`.

- [ ] **Step 3: Add the state-machine variables**

In `plugin/runtime.tcl`, replace:

```tcl
    variable tail_max 50
}
```

with:

```tcl
    variable tail_max 50
    # Connection state machine (P06-T06).
    variable probe_timer
    if {![::info exists probe_timer]} { set probe_timer "" }
    variable attempt
    if {![::info exists attempt]} { set attempt 0 }
    variable probe_failures
    if {![::info exists probe_failures]} { set probe_failures 0 }
    variable respawns
    if {![::info exists respawns]} { set respawns 0 }
    variable respawning
    if {![::info exists respawning]} { set respawning 0 }
    variable last_ready_pid
    if {![::info exists last_ready_pid]} { set last_ready_pid "" }
    # Set while the transition to `ready` ends a reconnect or a respawn.
    variable recovering
    if {![::info exists recovering]} { set recovering 0 }
    variable max_respawns 3
    variable hung_probe_limit 5
}
```

- [ ] **Step 4: Replace six procs whole**

In `plugin/runtime.tcl`, replace each proc below, from its `proc` line to its closing `}`, with the new version.

`_set_state` (adds the notice):

```tcl
proc ::vmdai::runtime::_set_state {new {detail ""}} {
    variable state
    variable subscribers
    set old $state
    if {$old eq $new} {
        return
    }
    set state $new
    _log "$old -> $new $detail"
    foreach cmd $subscribers {
        if {[catch {uplevel #0 [list {*}$cmd $old $new $detail]} err]} {
            _log "subscriber $cmd failed: $err"
        }
    }
    _notice $old $new $detail
}
```

`_process_exited` (reconnect instead of `down`):

```tcl
proc ::vmdai::runtime::_process_exited {} {
    variable state
    if {$state eq "ready"} {
        _enter_reconnecting "The AI runtime exited."
    }
}
```

`_fail` (a failed respawn returns to `reconnecting` while the budget lasts):

```tcl
proc ::vmdai::runtime::_fail {reason detail} {
    variable failure
    variable info
    variable child_pid
    variable ready_timer
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    variable respawning
    variable respawns
    variable max_respawns
    if {[dict get $info owned]} {
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid 0
        }
    }
    if {$respawning && $reason eq "didnt_start" && $respawns < $max_respawns} {
        _set_state reconnecting $detail
        _schedule_probe
        return
    }
    set respawning 0
    set failure $reason
    _set_state down $detail
}
```

`_on_health` (probe failures back off; an attached runtime's token is re-read):

```tcl
proc ::vmdai::runtime::_on_health {g purpose kind args} {
    variable gen
    variable info
    if {$g != $gen} {
        return
    }
    if {$kind ne "ok" && $purpose eq "probe"} {
        _probe_failed
        return
    }
    if {$kind ne "ok"} {
        _fail unreachable "Nothing answered on [dict get $info host]:[dict get $info port]."
        return
    }
    set body [lindex $args 0]
    set protocol 1
    catch {set protocol [dict get $body protocol]}
    if {![string is integer -strict $protocol] || $protocol < 2} {
        _too_old $protocol
        return
    }
    catch {dict set info pid [dict get $body pid]}
    catch {dict set info version [dict get $body version]}
    dict set info protocol $protocol
    if {$purpose eq "probe" && ![dict get $info owned]} {
        # An attached runtime restarted on the same port has a new token.
        set token [_read_token [dict get $info port]]
        if {$token ne ""} {
            dict set info launch_token $token
        }
    }
    _became_ready
}
```

`_became_ready` (resets the backoff, marks a recovery, calls `recover` on a new pid):

```tcl
proc ::vmdai::runtime::_became_ready {} {
    variable info
    variable attempt
    variable probe_failures
    variable probe_timer
    variable respawning
    variable last_ready_pid
    variable recovering
    variable state
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    set attempt 0
    set probe_failures 0
    set recovering [expr {$respawning || $state eq "reconnecting"}]
    set respawning 0
    set previous $last_ready_pid
    set last_ready_pid [dict get $info pid]
    _set_state ready
    set recovering 0
    if {$previous ne "" && $previous ne $last_ready_pid} {
        _recover "new runtime pid $last_ready_pid (was $previous)"
    }
}
```

`stop` (also cancels the probe timer and resets the respawn budget):

```tcl
proc ::vmdai::runtime::stop {args} {
    variable gen
    variable info
    variable child_pid
    variable failure
    variable ready_timer
    variable probe_timer
    variable respawns
    variable respawning
    variable last_ready_pid
    set sync [expr {[lsearch -exact $args -sync] >= 0}]
    incr gen
    ::vmdai::sched::cancel $ready_timer
    set ready_timer ""
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    set respawns 0
    set respawning 0
    set last_ready_pid ""
    catch {::vmdai::net::bump_epoch}
    if {[dict get $info owned]} {
        set token [dict get $info launch_token]
        if {$token ne "" && [dict get $info port] ne "" && !$sync} {
            catch {::vmdai::net::call runtime.shutdown [list launch_token s $token] \
                ::vmdai::runtime::_ignore -session 0}
        }
        _close_pipe
        if {[_alive $child_pid]} {
            _terminate $child_pid $sync
        }
    }
    set child_pid ""
    set failure ""
    _reset_info 0
    dict set info host ""
    _set_state stopped
    return
}
```

- [ ] **Step 5: Append the state machine**

Append to the end of `plugin/runtime.tcl`, after one blank line:

```tcl
# --- connection state machine (spec 2d, 5, S3) ----------------------------

# 500, 1000, 2000, 4000, 8000, 8000, ... ms for attempt 1, 2, 3, ...
proc ::vmdai::runtime::backoff_ms {attempt} {
    if {$attempt >= 5} {
        return 8000
    }
    return [expr {500 << ($attempt - 1)}]
}

# The bridge calls this when an RPC fails at the transport level.
proc ::vmdai::runtime::on_transport_error {reason} {
    variable state
    if {$state eq "ready"} {
        _enter_reconnecting $reason
    }
}

# The bridge calls this after any RPC that reached the runtime.
proc ::vmdai::runtime::on_transport_ok {} {
    variable state
    variable gen
    variable probe_timer
    if {$state ne "reconnecting"} {
        return
    }
    ::vmdai::sched::cancel $probe_timer
    set probe_timer ""
    _reconnect_tick $gen
}

# The bridge calls this when a session RPC answers AUTH_FAILED: the runtime
# restarted behind the same port (attach) or lost the session.
proc ::vmdai::runtime::on_auth_failed {} {
    variable state
    variable info
    if {$state ne "ready"} {
        return
    }
    if {![dict get $info owned]} {
        set token [_read_token [dict get $info port]]
        if {$token ne ""} {
            dict set info launch_token $token
        }
    }
    _recover "AUTH_FAILED"
}

# Banner "Retry": start over from down/stopped, or probe now while reconnecting.
proc ::vmdai::runtime::retry_now {} {
    variable state
    variable gen
    variable attempt
    variable probe_timer
    variable respawns
    switch -- $state {
        down - stopped {
            set respawns 0
            ensure
        }
        reconnecting {
            set attempt 0
            ::vmdai::sched::cancel $probe_timer
            set probe_timer ""
            _reconnect_tick $gen
        }
    }
    return [state]
}

proc ::vmdai::runtime::_enter_reconnecting {detail} {
    variable attempt
    variable probe_failures
    set attempt 0
    set probe_failures 0
    _set_state reconnecting $detail
    _schedule_probe
}

proc ::vmdai::runtime::_schedule_probe {} {
    variable gen
    variable attempt
    variable probe_timer
    incr attempt
    ::vmdai::sched::cancel $probe_timer
    set probe_timer [::vmdai::sched::after [backoff_ms $attempt] \
        [list ::vmdai::runtime::_reconnect_tick $gen]]
}

proc ::vmdai::runtime::_reconnect_tick {g} {
    variable gen
    variable state
    variable info
    variable chan
    variable child_pid
    variable probe_timer
    set probe_timer ""
    if {$g != $gen || $state ne "reconnecting"} {
        return
    }
    if {[dict get $info owned] && ($chan eq "" || ![_alive $child_pid])} {
        _respawn
        return
    }
    _probe [list ::vmdai::runtime::_on_health $g probe]
}

proc ::vmdai::runtime::_probe_failed {} {
    variable info
    variable probe_failures
    variable hung_probe_limit
    variable child_pid
    incr probe_failures
    if {[dict get $info owned] && $probe_failures >= $hung_probe_limit} {
        _log "owned runtime pid $child_pid is not answering; restarting it"
        _close_pipe
        _terminate $child_pid 0
        _respawn
        return
    }
    _schedule_probe
}

proc ::vmdai::runtime::_respawn {} {
    variable respawns
    variable respawning
    variable max_respawns
    if {$respawns >= $max_respawns} {
        set respawning 0
        _fail unreachable "The AI runtime stopped and did not come back after $max_respawns restarts."
        return
    }
    incr respawns
    set respawning 1
    _launch
}

proc ::vmdai::runtime::_recover {why} {
    _log "recover: $why"
    if {[llength [::info commands ::vmdai::bridge::recover]]} {
        if {[catch {::vmdai::bridge::recover} err]} {
            _log "bridge::recover failed: $err"
        }
    }
}

# One transcript notice per state change (S3); the status bar shows the rest.
proc ::vmdai::runtime::_notice {old new detail} {
    variable failure
    variable respawns
    variable max_respawns
    variable recovering
    set level ""
    switch -- $new {
        reconnecting {
            if {$old eq "ready"} {
                set level warn
                set text "Lost the connection to the AI runtime; reconnecting."
            }
        }
        launching {
            if {$old eq "reconnecting"} {
                set level warn
                set text "The AI runtime stopped; restarting it ($respawns of $max_respawns)."
            }
        }
        ready {
            if {$recovering} {
                set level info
                set text "Reconnected to the AI runtime."
            }
        }
        down {
            set level error
            switch -- $failure {
                didnt_start { set text "The AI runtime didn't start: $detail" }
                too_old { set text $detail }
                default { set text "Can't reach the AI runtime: $detail" }
            }
        }
    }
    if {$level eq ""} {
        return
    }
    _log "notice $level: $text"
    if {[llength [::info commands ::vmdai::ui::notify]]} {
        if {[catch {::vmdai::ui::notify $level $text} err]} {
            _log "ui::notify failed: $err"
        }
    }
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_state_machine.py tests/test_tcl_runtime_launch.py tests/test_tcl_lint.py -q`
Expected: `17 passed` (the launch tests still pass: a first start gives no notice and `stop` resets the new state).

- [ ] **Step 7: Run the suite**

Run: `SUITE`
Expected: `B+36 passed`, `0 failed`, under 60 s.

- [ ] **Step 8: Commit**

```bash
git add plugin/runtime.tcl tests/tcl/test_state_machine.tcl tests/test_tcl_state_machine.py
git commit -F - <<'MSG'
feat(plugin): connection state machine with backoff, respawns and one notice per transition

ready <-> reconnecting with 0.5-8 s backoff; an owned runtime is respawned
at most 3 times, an attached one is only probed and its token re-read.
A new pid or AUTH_FAILED calls bridge::recover once. ui::notify gets at
most one notice per state change, so a lost runtime no longer floods the
transcript (S3).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 7: P06-T07 — bridge.tcl rewrite: session, poll pump, routing, workdir

**Files:**
- Modify (replace whole file): `plugin/bridge.tcl`
- Modify: `plugin/init.tcl` (the three module `source` lines), `plugin/config.tcl` (drop the legacy names kept for today's bridge)
- Test: `tests/tcl/test_bridge_unit.tcl`, `tests/test_tcl_bridge_unit.py`

**Interfaces:**
- Consumes: `::vmdai::net::call method params callback ?-timeout ms? ?-session bool?`, `configure`, `encode_params`, `decode`, `json_string`, `epoch`, `bump_epoch`, `deliver`, and (tests only) `_deliver_if_current call_epoch callback args` (P06-T03); `::vmdai::sched::after`, `cancel`, `teardown` (P06-T02); `::vmdai::config::home`, `log`, `poll_ms`, `request_timeout_ms` (P06-T02); `::vmdai::runtime::state`, `info` (its `launch_token`), `subscribe`, `on_transport_error reason`, `on_transport_ok`, `on_auth_failed` and the contract in P06-T06's Produces block. At run time only, each guarded by `catch` or `info commands`: `::vmdai::executor::run event`, `executing`, `reset`, `note_cancelled request_id` (P06-T08) and `::vmdai::ui::render_event event`, `notify level text`, `set_busy on`, `status text` (P06-T10).
- Consumes (RPCs): `session.start {cwd, ui_mode, client_version, platform, event_protocol, vmd_env, launch_token} -> {session_id, session_token, chat_id, event_protocol, runtime}` where a token session's `chat_id` is JSON `null` until its first `chat.send` (P02-T02, P03-T04); `chat.send {text, conversation_mode:"full", chat_id?} -> {request_id, chat_id}` (P03-T04; a token `chat.send` ignores `model`, so the bridge never sends one); `chat.events.poll {after_seq, limit} -> {events, last_seq, has_more}`; `chat.cancel {request_id}`; `session.stop`; `chat.resume {chat_id} -> {chat_id, title, last_seq}` or the errors `REQUEST_CONFLICT`, `CHAT_LOCKED`, `NOT_FOUND` (P03-T04); `runtime.info -> {…, active_request: {request_id, turn, started_at, last_seq} | null}` and `session.set_cwd {cwd} -> {ok, cwd}` (P03-T09); `chat.history.list {offset, limit}`, `chat.history.get {chat_id, limit}`, `provider.set {provider, model}` (today's runtime). JSON `null` decodes to the string `null`; the bridge treats it as empty.
- Produces (`::vmdai::bridge`):
  - namespace variables, initialised once so re-sourcing keeps them: `event_protocol` (the constant `1`; P09-T07 makes it `2`), `session_id`, `session_token`, `chat_id`, `after_seq`, `busy`, `request_id`, `workdir`, `poll_timer`, `polling`, `deferred`, `op_busy`, `op_queue`, `recovering`, `finished`; `poll_limit 80`
  - `state -> dict {session_id chat_id busy request_id after_seq epoch}` (exactly these six keys)
  - `start_session ?callback?` — one session change at a time (`op_busy`/`op_queue`): bumps the net epoch, clears net's session, sends `session.start` with the launch token from `runtime::info`, `event_protocol` and `vmd_env`; on success configures net's session, keeps the chat id of a recovered session (else takes the result's, `null` → ""), sets `after_seq 0` and starts the pump; on failure one `notify error "Could not start a chat session: <message>"`. The callback gets the net forms.
  - `send text -> 1|0` — issues `chat.send {text, conversation_mode full, chat_id?}` and returns 1; returns 0 with one `notify warn` when there is no session, a session change is running, the runtime is not `ready`, or a request is busy. `busy` becomes 1 (and `ui::set_busy 1`) only when the runtime answered with a `request_id`, and not if that request already ended; an `rpc_error` gives `notify error "Could not send: <message>"` and `ui::set_busy 0`
  - `cancel -> 1|0` — `chat.cancel {request_id}` for the busy request, and `executor::note_cancelled`; the request ends when its `cancelled` lifecycle event arrives
  - `new_chat` — cancels a busy request, sends `session.stop` (releasing the old session's chat lock), then `start_session`; `chat_id` becomes ""
  - `resume chat_id ?callback?` — `chat.resume`; on success bumps the epoch, sets `chat_id`, `after_seq` = the result's `last_seq` (0 when absent), ends a busy request and sends `session.set_cwd`; failures give one `notify error` (`CHAT_LOCKED` "This chat is open in another VMD window.", `REQUEST_CONFLICT` "Stop the running request before switching chats.", `NOT_FOUND` "That chat no longer exists."); without a session the callback gets `rpc_error NOT_CONNECTED …`. The callback gets the net forms.
  - `recover` — for `runtime.tcl` (new pid or `AUTH_FAILED`): ends a busy request with `ui::status "The request in progress was lost when the AI runtime restarted."`, starts a new session and resumes the current chat (its own callback path, `_on_recover_resume`, so P09-T07's replay in `resume`'s success branch never runs for it). Repeated calls while one runs are ignored.
  - `apply_workdir dir -> 1|0` — `cd` VMD there, write `~/.vmdai/last_workdir.txt`, send `session.set_cwd {cwd}`; `_load_workdir` (used by `start_session` and the M1 panel) restores the remembered folder or takes `[pwd]`
  - `poll_now`; `vmd_env_json -> JSON object text` (`vmd_version`, `arch`, `tcl_patchlevel`, `tk_patchlevel`, each from `vmdinfo`/`info patchlevel`/`package present Tk` in `catch`, left out when unavailable)
  - `set_provider provider model ?callback?`; `history_list callback` (plan addition: `history_get chat_id callback`)
  - plan additions: `shutdown` (sends `session.stop` without waiting, then forgets the session; `::vmdai::stop` and `::vmdai::cleanup` call it) and `note_outcome method kind args` (the state-machine feed: `transport` → `runtime::on_transport_error`; any answer → `on_transport_ok`; `AUTH_FAILED` from any method but `session.start` → `on_auth_failed`; the executor uses it for `tool.ack`)
  - Routing (P09-T07 edits these anchors): the pump calls `::vmdai::net::call chat.events.poll [list after_seq i … limit i …] … -timeout $::vmdai::config::request_timeout_ms` with one poll outstanding, advances `after_seq` per event before dispatch, wraps each dispatch in `catch`, re-polls at once on `has_more` and otherwise after `$::vmdai::config::poll_ms`. `_dispatch` sends `tool_start` to `::vmdai::executor::run` (held in `deferred` while `::vmdai::executor::executing` is 1 or earlier ones are still held; a 20 ms sched timer drains them) and every other event to `::vmdai::ui::render_event $ev`, followed by `_check_end $ev`, the v1 end-of-request detection (final `assistant/message`, an `error` event, or the `cancelled` lifecycle event). An undecodable or malformed poll reply is a transport error and `after_seq` stays.
  - Runtime states (a `subscribe` callback, `_on_runtime_state`): `ready` → after 0 ms, start the first session, or restart the pump and, when busy, reconcile once the backlog is drained (`runtime.info` without that `active_request` → idle plus `notify info "Request ended (details may be missing)."`); `stopped` → forget the session; any other state → pause the pump.

Until P06-T10 rewires `ui.tcl`, the M1 panel's buttons still call names this task removes (`ensure_runtime`, `send_chat`, `show_history`, …). The tests do not touch the panel; do not use the branch in VMD before P06-T10.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_bridge_unit.tcl`:

```tcl
# tests/tcl/test_bridge_unit.tcl - bridge.tcl (P06-T07): session.start,
# the poll pump, routing, request state, resume/recover and the working
# directory. net::call is faked: it records {method params} and answers from
# ::replies(<method>) through net's own epoch check, one outcome per call
# (the last repeats); "hold" keeps a call in flight until `release`.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime bridge} { source [file join $plugin $m.tcl] }
set ::vmdai::config::poll_ms 400

# --- fakes --------------------------------------------------------------------
set ::calls {}
array set ::replies {}
array set ::held {}
proc ::vmdai::net::call {method params callback args} {
    lappend ::calls [list $method $params]
    set outcome [list ok {}]
    if {[info exists ::replies($method)] && [llength $::replies($method)]} {
        set outcome [lindex $::replies($method) 0]
        if {[llength $::replies($method)] > 1} {
            set ::replies($method) [lrange $::replies($method) 1 end]
        }
    }
    if {$outcome eq "hold"} {
        lappend ::held($method) [list [::vmdai::net::epoch] $callback]
        return rpc#fake
    }
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback {*}$outcome]
    return rpc#fake
}
proc release {method outcome} {
    set item [lindex $::held($method) 0]
    set ::held($method) [lrange $::held($method) 1 end]
    lassign $item epoch callback
    ::vmdai::net::_deliver_if_current $epoch $callback {*}$outcome
}
proc calls {method} {
    set out {}
    foreach c $::calls { if {[lindex $c 0] eq $method} { lappend out [lindex $c 1] } }
    return $out
}
proc param {params name} {
    foreach {n t v} $params { if {$n eq $name} { return $v } }
    return "<none>"
}

set ::rt_state ready
set ::token [string repeat a 32]
proc ::vmdai::runtime::state {} { return $::rt_state }
proc ::vmdai::runtime::info {} {
    return [dict create host 127.0.0.1 port 1 pid 7 version 0.3.0 protocol 2 \
        launch_token $::token owned 0]
}
proc ::vmdai::runtime::on_transport_error {reason} { lappend ::transport_errors $reason }
proc ::vmdai::runtime::on_transport_ok {} { incr ::oks }
proc ::vmdai::runtime::on_auth_failed {} { incr ::auth_failed }

namespace eval ::vmdai::ui {}
proc ::vmdai::ui::render_event {ev} { lappend ::rendered [dict get $ev seq] }
proc ::vmdai::ui::notify {level text} { lappend ::notices [list $level $text] }
proc ::vmdai::ui::set_busy {on} { lappend ::busy_calls $on }
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
namespace eval ::vmdai::executor { variable executing 0 }
proc ::vmdai::executor::run {ev} { lappend ::executed [dict get $ev metadata call_key] }
proc ::vmdai::executor::reset {} {}
proc ::vmdai::executor::note_cancelled {rid} { lappend ::cancelled $rid }

proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
}
proc fresh {} {
    ::vmdai::bridge::_reset_session
    ::vmdai::sched::teardown
    set ::vmdai::bridge::workdir ""
    set ::vmdai::bridge::finished {}
    set ::vmdai::executor::executing 0
    set ::rt_state ready
    foreach v {calls transport_errors rendered notices busy_calls statuses executed cancelled} {
        set ::$v {}
    }
    set ::oks 0
    set ::auth_failed 0
    array unset ::replies
    array unset ::held
    set ::replies(chat.events.poll) [list [list ok {events {} last_seq 0 has_more false}]]
}
# Start session sess_1 (chat null, as a token session gets it).
proc started {} {
    set ::replies(session.start) [list [list ok [dict create session_id sess_1 \
        session_token tok_1 chat_id null event_protocol 1]]]
    ::vmdai::bridge::start_session
    settle
}
proc ev {seq role type {text x} {md {}}} {
    return [dict create seq $seq role $role type $type text $text metadata $md]
}
proc st {key} { dict get [::vmdai::bridge::state] $key }

# --- tests --------------------------------------------------------------------

test bridge-start-1 {session.start carries the launch token, event_protocol 1 and vmd_env (C6)} -setup fresh -body {
    proc ::vmdinfo {what} {
        switch -- $what { version { return 1.9.4a57 } arch { return MACOSXARM64 } }
    }
    started
    rename ::vmdinfo {}
    set body [::vmdai::net::decode [::vmdai::net::encode_params [lindex [calls session.start] 0]]]
    list [dict get $body launch_token] [dict get $body event_protocol] \
        [dict exists $body session_id] [dict get $body vmd_env vmd_version] \
        [dict get $body vmd_env arch] \
        [expr {[dict get $body vmd_env tcl_patchlevel] eq [info patchlevel]}] \
        [dict exists $body vmd_env tk_patchlevel] [st session_id] [st chat_id] \
        [::vmdai::net::configure]
} -cleanup fresh -result [list [string repeat a 32] 1 0 1.9.4a57 MACOSXARM64 1 0 sess_1 {} \
    {-base_url {} -session_id sess_1 -session_token tok_1}]

test bridge-poll-bad-1 {an undecodable or malformed poll reply is a transport error; after_seq stays} -setup fresh -body {
    set ::replies(chat.events.poll) [list \
        [list ok [dict create events [list [ev 1 assistant chunk]] has_more true]] \
        {transport {undecodable response: unexpected character}} \
        {ok {has_more false}}]
    started
    set first [list [st after_seq] $::transport_errors]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle
    list $first [st after_seq] $::transport_errors $::rendered
} -cleanup fresh -result {{1 {{undecodable response: unexpected character}}} 1 {{undecodable response: unexpected character} {malformed poll result}} 1}

test bridge-poll-more-1 {has_more re-polls at once; after_seq advances per event} -setup fresh -body {
    set a {}
    for {set s 1} {$s <= 80} {incr s} { lappend a [ev $s assistant chunk] }
    set b {}
    for {set s 81} {$s <= 100} {incr s} { lappend b [ev $s assistant chunk] }
    set ::replies(chat.events.poll) [list [list ok [dict create events $a has_more true]] \
        [list ok [dict create events $b has_more false]] {ok {events {} has_more false}}]
    started
    settle 100
    set seqs {}
    foreach p [calls chat.events.poll] { lappend seqs [param $p after_seq] }
    list $seqs [llength $::rendered] [st after_seq] [param [lindex [calls chat.events.poll] 0] limit]
} -cleanup fresh -result {{0 80} 100 100 80}

test bridge-defer-1 {tool_start waits while the executor runs model Tcl, then runs once} -setup fresh -body {
    set ::vmdai::executor::executing 1
    set ::replies(chat.events.poll) [list [list ok [dict create has_more false events [list \
        [ev 1 assistant chunk] [ev 2 tool_start message x {call_key k1 request_id req_1}] \
        [ev 3 assistant chunk]]]] {ok {events {} has_more false}}]
    started
    settle 60
    set during [list $::executed $::rendered]
    set ::vmdai::executor::executing 0
    settle 60
    list $during $::executed $::rendered
} -cleanup fresh -result {{{} {1 3}} k1 {1 3}}

test bridge-busy-1 {busy starts only after chat.send answers; a failed send never goes busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list hold]
    set issued [::vmdai::bridge::send "now color it red"]
    set before [list [st busy] $::busy_calls]
    release chat.send {ok {request_id req_1 chat_id chat_0123456789ab}}
    set after [list [st busy] $::busy_calls [st request_id] [st chat_id]]
    set sent [lindex [calls chat.send] 0]
    set ::vmdai::bridge::busy 0
    set ::vmdai::bridge::request_id ""
    set ::busy_calls {}
    set ::replies(chat.send) [list {rpc_error NO_MODEL {No model configured.} {}}]
    ::vmdai::bridge::send "hello"
    settle
    list $issued $before $after [param $sent text] [param $sent conversation_mode] \
        [param $sent model] [st busy] $::busy_calls [lindex $::notices end]
} -cleanup fresh -result {1 {0 {}} {1 1 req_1 chat_0123456789ab} {now color it red} full <none> 0 0 {error {Could not send: No model configured.}}}

test bridge-busy-2 {a request that ended before chat.send answered does not leave the panel busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list hold]
    ::vmdai::bridge::send "hi"
    ::vmdai::bridge::_dispatch [ev 9 assistant message done {request_id req_7}]
    release chat.send {ok {request_id req_7}}
    list [st busy] $::busy_calls
} -cleanup fresh -result {0 {}}

test bridge-end-1 {v1 ends a request on the final message, an error or a cancelled lifecycle} -setup fresh -body {
    set r {}
    foreach e [list [ev 1 assistant chunk x {request_id req_1}] \
            [ev 2 assistant message x {request_id req_1}] [ev 3 error message x {}] \
            [ev 4 system lifecycle cancelled {request_id req_1}] \
            [ev 5 system lifecycle chat_resumed {request_id req_1}]] {
        set ::vmdai::bridge::busy 1
        set ::vmdai::bridge::request_id req_1
        ::vmdai::bridge::_dispatch $e
        lappend r [st busy]
    }
    set r
} -cleanup fresh -result {1 0 0 0 1}

test bridge-reconcile-1 {after a reconnect, busy with no active request goes idle with one note} -setup fresh -body {
    started
    set ::replies(chat.send) [list {ok {request_id req_1}}]
    ::vmdai::bridge::send "long job"
    settle
    set ::replies(runtime.info) [list {ok {version 0.3.0 active_request null}}]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle 60
    list [st busy] [llength [calls runtime.info]] $::notices [lindex $::busy_calls end]
} -cleanup fresh -result {0 1 {{info {Request ended (details may be missing).}}} 0}

test bridge-reconcile-2 {a request the runtime still runs stays busy} -setup fresh -body {
    started
    set ::replies(chat.send) [list {ok {request_id req_1}}]
    ::vmdai::bridge::send "long job"
    settle
    set ::replies(runtime.info) [list {ok {active_request {request_id req_1 turn 2}}}]
    ::vmdai::bridge::_on_runtime_state reconnecting ready ""
    settle 60
    list [st busy] [llength [calls runtime.info]] $::notices
} -cleanup fresh -result {1 1 {}}

test bridge-workdir-1 {apply_workdir cds VMD, remembers the folder and sends session.set_cwd} -setup fresh -body {
    started
    set dir [file join $::env(HOME) "my project"]
    file mkdir $dir
    set ok [::vmdai::bridge::apply_workdir $dir]
    settle
    set fh [open [file join $::env(HOME) .vmdai last_workdir.txt]]
    set saved [read $fh]
    close $fh
    set bad [::vmdai::bridge::apply_workdir [file join $::env(HOME) missing]]
    list $ok [expr {[pwd] eq [file normalize $dir]}] [expr {$saved eq [file normalize $dir]}] \
        [expr {[param [lindex [calls session.set_cwd] 0] cwd] eq [file normalize $dir]}] \
        $bad [lindex $::notices end 0]
} -cleanup fresh -result {1 1 1 1 0 error}

test bridge-race-1 {New Chat drops the old session's in-flight poll; after_seq restarts at 0} -setup fresh -body {
    set ::replies(chat.events.poll) [list hold]
    started
    set ::replies(session.start) [list [list ok [dict create session_id sess_2 \
        session_token tok_2 chat_id null]]]
    set ::replies(chat.events.poll) [list hold]
    ::vmdai::bridge::new_chat
    settle
    release chat.events.poll [list ok [dict create has_more false \
        events [list [ev 5 assistant chunk] [ev 6 assistant chunk]]]]
    settle
    list [st session_id] [st after_seq] $::rendered [llength [calls session.stop]] \
        [llength [calls chat.events.poll]]
} -cleanup fresh -result {sess_2 0 {} 1 2}

test bridge-resume-1 {resume: callback gets the net forms; success switches chat and after_seq} -setup fresh -body {
    started
    set ::replies(chat.resume) [list {rpc_error CHAT_LOCKED {chat is locked} {}} \
        {ok {chat_id chat_00000000000a last_seq 42}}]
    set ::got {}
    ::vmdai::bridge::resume chat_00000000000a [list apply {{args} {lappend ::got $args}}]
    settle
    ::vmdai::bridge::resume chat_00000000000a [list apply {{args} {lappend ::got [lindex $args 0]}}]
    settle
    list [lrange [lindex $::got 0] 0 1] [lindex $::got 1] [lindex $::notices 0] \
        [st chat_id] [st after_seq] [llength [calls session.set_cwd]]
} -cleanup fresh -result {{rpc_error CHAT_LOCKED} ok {error {This chat is open in another VMD window.}} chat_00000000000a 42 1}

test bridge-recover-1 {recover: new session with the token, chat.resume, the lost request reported} -setup fresh -body {
    started
    set ::vmdai::bridge::chat_id chat_00000000000b
    set ::vmdai::bridge::busy 1
    set ::vmdai::bridge::request_id req_9
    set ::replies(session.start) [list [list ok [dict create session_id sess_3 \
        session_token tok_3 chat_id null]]]
    set ::replies(chat.resume) [list {ok {chat_id chat_00000000000b last_seq 12}}]
    ::vmdai::bridge::recover
    settle 60
    list [st session_id] [st chat_id] [st after_seq] [st busy] $::statuses \
        [param [lindex [calls chat.resume] 0] chat_id] [llength [calls session.start]]
} -cleanup fresh -result {sess_3 chat_00000000000b 12 0 {{The request in progress was lost when the AI runtime restarted.}} chat_00000000000b 2}

test bridge-auth-1 {AUTH_FAILED on a poll asks the runtime to recover and stops the pump} -setup fresh -body {
    set ::replies(chat.events.poll) [list {rpc_error AUTH_FAILED {invalid session or token} {}}]
    started
    settle 100
    list $::auth_failed [llength [calls chat.events.poll]] $::vmdai::bridge::poll_timer
} -cleanup fresh -result {1 1 {}}

cleanupTests
```

Create `tests/test_tcl_bridge_unit.py`:

```python
"""bridge.tcl: session, poll pump, routing, request state, workdir (P06-T07).

Runs tests/tcl/test_bridge_unit.tcl, which fakes net::call, the runtime state
machine, the executor and the panel, so every reply is scripted.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_bridge_unit.tcl"
TOTAL = 14


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_session_start_body_has_vmd_env(result):
    _assert_passed(result, ["bridge-start-1"])


def test_undecodable_poll_is_transport_error_after_seq_kept(result):
    _assert_passed(result, ["bridge-poll-bad-1"])


def test_has_more_drains(result):
    _assert_passed(result, ["bridge-poll-more-1"])


def test_tool_start_deferred_while_executing(result):
    _assert_passed(result, ["bridge-defer-1"])


def test_busy_only_after_send_ok(result):
    _assert_passed(result, ["bridge-busy-1", "bridge-busy-2", "bridge-end-1"])


def test_reconcile_idle_when_no_active_request(result):
    _assert_passed(result, ["bridge-reconcile-1", "bridge-reconcile-2"])


def test_apply_workdir_cd_and_set_cwd(result):
    _assert_passed(result, ["bridge-workdir-1"])


def test_session_changes_drop_stale_replies(result):
    _assert_passed(result, ["bridge-race-1", "bridge-resume-1", "bridge-recover-1", "bridge-auth-1"])
```

`net::call` is replaced by a recorder that answers through net's own `_deliver_if_current`, so stale-epoch drops work exactly as in production; "hold" keeps a call in flight until `release`, which is how `bridge-race-1` keeps an old poll outstanding across New Chat.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_bridge_unit.py -q`
Expected: `9 failed`; the tcltest output shows `invalid command name "::vmdai::bridge::_reset_session"` (today's bridge has none of the new procs).

- [ ] **Step 3: Replace `plugin/bridge.tcl`**

Replace the whole file with:

```tcl
# bridge.tcl - session, poll pump, request state, routing and the working
# directory (spec 2c, 2d, 3). No Tk, no nested event loops.
#
# The panel is reached only through ::vmdai::ui::render_event, notify,
# set_busy and status; the executor through ::vmdai::executor::run. Every
# RPC outcome is fed to the connection state machine (P06-T06 contract).

namespace eval ::vmdai::bridge {
    # The display events this plugin asks for (spec 2c). M1 renders v1.
    variable event_protocol 1
    variable session_id
    if {![info exists session_id]} { set session_id "" }
    variable session_token
    if {![info exists session_token]} { set session_token "" }
    variable chat_id
    if {![info exists chat_id]} { set chat_id "" }
    variable after_seq
    if {![info exists after_seq]} { set after_seq 0 }
    variable busy
    if {![info exists busy]} { set busy 0 }
    variable request_id
    if {![info exists request_id]} { set request_id "" }
    variable workdir
    if {![info exists workdir]} { set workdir "" }
    # Poll pump: one timer and at most one poll outstanding.
    variable poll_timer
    if {![info exists poll_timer]} { set poll_timer "" }
    variable polling
    if {![info exists polling]} { set polling 0 }
    # tool_start events held back while the executor runs model Tcl.
    variable deferred
    if {![info exists deferred]} { set deferred {} }
    variable drain_timer
    if {![info exists drain_timer]} { set drain_timer "" }
    # Session changes (start, new chat, resume, recover) run one at a time.
    variable op_busy
    if {![info exists op_busy]} { set op_busy 0 }
    variable op_queue
    if {![info exists op_queue]} { set op_queue {} }
    variable recovering
    if {![info exists recovering]} { set recovering 0 }
    # Set after a reconnect while busy: check runtime.info once drained.
    variable reconcile_pending
    if {![info exists reconcile_pending]} { set reconcile_pending 0 }
    # Requests whose end event arrived before chat.send answered.
    variable finished
    if {![info exists finished]} { set finished {} }
    variable ready_timer
    if {![info exists ready_timer]} { set ready_timer "" }
    variable poll_limit 80
    variable client_version "vmd_ai 2.0"
}

proc ::vmdai::bridge::_log {msg} {
    catch {::vmdai::config::log "bridge: $msg"}
}

proc ::vmdai::bridge::_ignore {args} {}

proc ::vmdai::bridge::_dget {d key default} {
    if {[catch {dict get $d $key} value] || $value eq "null"} {
        return $default
    }
    return $value
}

proc ::vmdai::bridge::state {} {
    variable session_id
    variable chat_id
    variable busy
    variable request_id
    variable after_seq
    return [dict create session_id $session_id chat_id $chat_id busy $busy \
        request_id $request_id after_seq $after_seq epoch [::vmdai::net::epoch]]
}

# Feed one RPC outcome to the connection state machine: a transport error
# may start a reconnect, any answer ends one, and AUTH_FAILED (except from
# session.start itself) makes the runtime recover the session.
proc ::vmdai::bridge::note_outcome {method kind args} {
    if {![llength [info commands ::vmdai::runtime::on_transport_ok]]} {
        return
    }
    switch -- $kind {
        transport {
            ::vmdai::runtime::on_transport_error [lindex $args 0]
        }
        rpc_error {
            ::vmdai::runtime::on_transport_ok
            if {[lindex $args 0] eq "AUTH_FAILED" && $method ne "session.start"} {
                ::vmdai::runtime::on_auth_failed
            }
        }
        default {
            ::vmdai::runtime::on_transport_ok
        }
    }
}

# Note the outcome, then hand it to the caller's callback (net forms).
proc ::vmdai::bridge::_relay {method callback kind args} {
    note_outcome $method $kind {*}$args
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

proc ::vmdai::bridge::_runtime_ready {} {
    if {![llength [info commands ::vmdai::runtime::state]]} {
        return 1
    }
    return [expr {[::vmdai::runtime::state] eq "ready"}]
}

# C6: {vmd_version, arch, tcl_patchlevel, tk_patchlevel}, each in catch.
proc ::vmdai::bridge::vmd_env_json {} {
    set parts {}
    foreach {key script} {
        vmd_version {vmdinfo version}
        arch {vmdinfo arch}
        tcl_patchlevel {info patchlevel}
        tk_patchlevel {package present Tk}
    } {
        if {![catch {uplevel #0 $script} value] && $value ne ""} {
            lappend parts "[::vmdai::net::json_string $key]:[::vmdai::net::json_string $value]"
        }
    }
    return "\{[join $parts ,]\}"
}

# --- one session change at a time -----------------------------------------

proc ::vmdai::bridge::_op {script} {
    variable op_busy
    variable op_queue
    if {$op_busy} {
        lappend op_queue $script
        return
    }
    set op_busy 1
    if {[catch {uplevel #0 $script} err]} {
        _log "operation failed: $::errorInfo"
        _op_done
    }
}

proc ::vmdai::bridge::_op_done {} {
    variable op_busy
    variable op_queue
    set op_busy 0
    if {[llength $op_queue]} {
        set next [lindex $op_queue 0]
        set op_queue [lrange $op_queue 1 end]
        ::vmdai::sched::after 0 [list ::vmdai::bridge::_op $next]
        return
    }
    _schedule_poll 0
}

# --- session ------------------------------------------------------------------

proc ::vmdai::bridge::start_session {{callback ""}} {
    _op [list ::vmdai::bridge::_start_session $callback]
}

proc ::vmdai::bridge::_start_session {callback} {
    variable event_protocol
    variable workdir
    variable client_version
    variable polling
    variable session_id
    variable session_token
    variable after_seq
    variable deferred
    _stop_pump
    ::vmdai::net::bump_epoch
    set polling 0
    set deferred {}
    catch {::vmdai::executor::reset}
    set session_id ""
    set session_token ""
    set after_seq 0
    ::vmdai::net::configure -session_id "" -session_token ""
    if {$workdir eq ""} {
        _load_workdir
    }
    set params [list cwd s $workdir ui_mode s tk client_version s $client_version \
        platform s $::tcl_platform(os) event_protocol i $event_protocol \
        vmd_env j [vmd_env_json]]
    set token ""
    catch {set token [dict get [::vmdai::runtime::info] launch_token]}
    if {$token ne ""} {
        lappend params launch_token s $token
    }
    ::vmdai::net::call session.start $params \
        [list ::vmdai::bridge::_on_session_started $callback]
}

proc ::vmdai::bridge::_on_session_started {callback kind args} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq
    variable recovering
    note_outcome session.start $kind {*}$args
    if {$kind eq "ok"} {
        set result [lindex $args 0]
        set session_id [_dget $result session_id ""]
        set session_token [_dget $result session_token ""]
        ::vmdai::net::configure -session_id $session_id -session_token $session_token
        # A new chat takes the runtime's chat id (null until the first send
        # for a token session); a recovered session keeps its chat.
        if {$chat_id eq ""} {
            set chat_id [_dget $result chat_id ""]
        }
        set after_seq 0
    } else {
        set recovering 0
        set message [lindex $args [expr {$kind eq "rpc_error" ? 1 : 0}]]
        if {[catch {::vmdai::ui::notify error "Could not start a chat session: $message"} err]} {
            _log "ui: $err"
        }
    }
    _op_done
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

# The runtime came back with a new pid or answered AUTH_FAILED (P06-T06):
# start a new session, resume the current chat, and report a lost request.
proc ::vmdai::bridge::recover {} {
    variable recovering
    variable busy
    variable request_id
    if {$recovering} {
        return
    }
    set recovering 1
    if {$busy} {
        _request_ended $request_id
        if {[catch {::vmdai::ui::status "The request in progress was lost when the AI runtime restarted."} err]} {
            _log "ui: $err"
        }
    }
    _op [list ::vmdai::bridge::_start_session ::vmdai::bridge::_recovered]
}

proc ::vmdai::bridge::_recovered {kind args} {
    variable recovering
    variable chat_id
    if {$kind ne "ok" || $chat_id eq ""} {
        set recovering 0
        return
    }
    _op [list ::vmdai::bridge::_resume $chat_id "" ::vmdai::bridge::_on_recover_resume]
}

proc ::vmdai::bridge::_on_recover_resume {target callback kind args} {
    variable recovering
    variable chat_id
    note_outcome chat.resume $kind {*}$args
    set recovering 0
    if {$kind eq "ok"} {
        _resumed $target [lindex $args 0]
    } else {
        # The chat stays on disk; this session starts a new one.
        _log "recover: chat.resume $target failed: $args"
        set chat_id ""
    }
    _op_done
}

# New Chat: cancel a running request, stop the old session (which releases
# its chat lock), then start a new session with no chat.
proc ::vmdai::bridge::new_chat {} {
    _op ::vmdai::bridge::_new_chat
}

proc ::vmdai::bridge::_new_chat {} {
    variable session_id
    variable busy
    variable request_id
    variable chat_id
    if {$busy && $request_id ne ""} {
        catch {::vmdai::executor::note_cancelled $request_id}
        ::vmdai::net::call chat.cancel [list request_id s $request_id] ::vmdai::bridge::_ignore
    }
    _request_ended $request_id
    set chat_id ""
    if {$session_id eq ""} {
        _start_session ""
        return
    }
    _stop_pump
    ::vmdai::net::call session.stop {} ::vmdai::bridge::_on_session_stopped
}

proc ::vmdai::bridge::_on_session_stopped {kind args} {
    # The old session is gone either way; only a transport error says
    # something about the runtime.
    if {$kind eq "transport"} {
        note_outcome session.stop $kind {*}$args
    }
    _start_session ""
}

# Resume a stored chat in this session. The callback gets the net forms:
# ok <result> | rpc_error <code> <message> <data> | transport <reason>.
proc ::vmdai::bridge::resume {target {callback ""}} {
    _op [list ::vmdai::bridge::_resume $target $callback ::vmdai::bridge::_on_resume]
}

proc ::vmdai::bridge::_resume {target callback handler} {
    variable session_id
    if {$session_id eq ""} {
        ::vmdai::sched::after 0 [list $handler $target $callback \
            rpc_error NOT_CONNECTED "Not connected to the AI runtime yet." {}]
        return
    }
    _stop_pump
    ::vmdai::net::call chat.resume [list chat_id s $target] [list $handler $target $callback]
}

proc ::vmdai::bridge::_on_resume {target callback kind args} {
    note_outcome chat.resume $kind {*}$args
    if {$kind eq "ok"} {
        _resumed $target [lindex $args 0]
    } else {
        _resume_failed $kind {*}$args
    }
    _op_done
    if {$callback ne ""} {
        ::vmdai::net::deliver $callback $kind {*}$args
    }
}

# chat.resume succeeded: switch chat_id and after_seq (the runtime's
# last_seq; older runtimes restart at 0), drop replies meant for the old
# chat, and apply the folder again.
proc ::vmdai::bridge::_resumed {target result} {
    variable chat_id
    variable after_seq
    variable polling
    variable deferred
    variable request_id
    ::vmdai::net::bump_epoch
    set polling 0
    set deferred {}
    _request_ended $request_id
    set chat_id $target
    set after_seq [_dget $result last_seq 0]
    if {![string is integer -strict $after_seq]} {
        set after_seq 0
    }
    _send_cwd
}

proc ::vmdai::bridge::_resume_failed {kind args} {
    if {$kind eq "transport"} {
        set text "Could not resume the chat: the AI runtime did not answer."
    } else {
        lassign $args code message
        switch -- $code {
            CHAT_LOCKED { set text "This chat is open in another VMD window." }
            REQUEST_CONFLICT { set text "Stop the running request before switching chats." }
            NOT_FOUND { set text "That chat no longer exists." }
            default { set text "Could not resume the chat: $message" }
        }
    }
    if {[catch {::vmdai::ui::notify error $text} err]} {
        _log "ui: $err"
    }
}

# --- requests -----------------------------------------------------------------

# Send a prompt. Returns 1 when chat.send was issued. The panel turns busy
# only after the runtime accepted the request (spec 2h, 4).
proc ::vmdai::bridge::send {text} {
    variable session_id
    variable busy
    variable chat_id
    variable op_busy
    if {$session_id eq "" || $op_busy || ![_runtime_ready]} {
        set why "Not connected to the AI runtime yet; try again in a moment."
    } elseif {$busy} {
        set why "A request is still running; stop it first."
    } else {
        set params [list text s $text conversation_mode s full]
        if {$chat_id ne ""} {
            lappend params chat_id s $chat_id
        }
        ::vmdai::net::call chat.send $params ::vmdai::bridge::_on_send
        return 1
    }
    if {[catch {::vmdai::ui::notify warn $why} err]} {
        _log "ui: $err"
    }
    return 0
}

proc ::vmdai::bridge::_on_send {kind args} {
    variable busy
    variable request_id
    variable chat_id
    variable finished
    note_outcome chat.send $kind {*}$args
    switch -- $kind {
        ok {
            set result [lindex $args 0]
            set rid [_dget $result request_id ""]
            set cid [_dget $result chat_id ""]
            if {$cid ne ""} {
                set chat_id $cid
            }
            if {$rid ne "" && [lsearch -exact $finished $rid] < 0} {
                set request_id $rid
                set busy 1
                if {[catch {::vmdai::ui::set_busy 1} err]} {
                    _log "ui: $err"
                }
            }
            _schedule_poll 0
        }
        rpc_error {
            lassign $args code message
            if {[catch {::vmdai::ui::notify error "Could not send: $message"} err]} {
                _log "ui: $err"
            }
            catch {::vmdai::ui::set_busy 0}
        }
        default {
            if {[catch {::vmdai::ui::notify error "Could not send: the AI runtime did not answer."} err]} {
                _log "ui: $err"
            }
            catch {::vmdai::ui::set_busy 0}
        }
    }
}

proc ::vmdai::bridge::cancel {} {
    variable busy
    variable request_id
    if {!$busy || $request_id eq ""} {
        return 0
    }
    catch {::vmdai::executor::note_cancelled $request_id}
    ::vmdai::net::call chat.cancel [list request_id s $request_id] \
        [list ::vmdai::bridge::_relay chat.cancel ""]
    return 1
}

proc ::vmdai::bridge::_request_ended {rid} {
    variable busy
    variable request_id
    variable finished
    if {$rid ne ""} {
        lappend finished $rid
        set finished [lrange $finished end-19 end]
    }
    if {$rid ne $request_id || $request_id eq ""} {
        return
    }
    set busy 0
    set request_id ""
    if {[catch {::vmdai::ui::set_busy 0} err]} {
        _log "ui: $err"
    }
}

# --- poll pump (spec 2d) ------------------------------------------------------

proc ::vmdai::bridge::_schedule_poll {ms} {
    variable poll_timer
    ::vmdai::sched::cancel $poll_timer
    set poll_timer [::vmdai::sched::after $ms ::vmdai::bridge::_poll]
}

proc ::vmdai::bridge::_stop_pump {} {
    variable poll_timer
    ::vmdai::sched::cancel $poll_timer
    set poll_timer ""
}

proc ::vmdai::bridge::poll_now {} {
    _schedule_poll 0
}

proc ::vmdai::bridge::_poll {} {
    variable poll_timer
    variable polling
    variable session_id
    variable after_seq
    variable poll_limit
    variable op_busy
    set poll_timer ""
    if {$polling || $session_id eq "" || $op_busy || ![_runtime_ready]} {
        return
    }
    set polling 1
    ::vmdai::net::call chat.events.poll [list after_seq i $after_seq limit i $poll_limit] \
        [list ::vmdai::bridge::_on_poll $session_id] -timeout $::vmdai::config::request_timeout_ms
}

proc ::vmdai::bridge::_on_poll {sid kind args} {
    variable polling
    variable session_id
    variable after_seq
    variable op_busy
    variable reconcile_pending
    set polling 0
    if {$sid ne $session_id} {
        return
    }
    note_outcome chat.events.poll $kind {*}$args
    if {$kind eq "transport"} {
        # The state machine reconnects; _after_ready restarts the pump.
        return
    }
    if {$kind eq "rpc_error"} {
        if {[lindex $args 0] ne "AUTH_FAILED"} {
            _log "poll: [lindex $args 0] [lindex $args 1]"
            _schedule_poll $::vmdai::config::poll_ms
        }
        return
    }
    set result [lindex $args 0]
    if {[catch {dict get $result events} events] || [catch {llength $events}]} {
        # Undecodable poll body: a transport error; after_seq stays (spec 5).
        catch {::vmdai::runtime::on_transport_error "malformed poll result"}
        return
    }
    foreach ev $events {
        set seq ""
        catch {set seq [dict get $ev seq]}
        if {![string is integer -strict $seq] || $seq <= $after_seq} {
            continue
        }
        set after_seq $seq
        if {[catch {_dispatch $ev} err]} {
            _log "dispatch of seq $seq failed: $::errorInfo"
        }
        if {$sid ne $session_id} {
            return
        }
    }
    set more 0
    catch {set more [string is true -strict [dict get $result has_more]]}
    if {!$more && $reconcile_pending} {
        set reconcile_pending 0
        _reconcile
    }
    if {$op_busy} {
        return
    }
    _schedule_poll [expr {$more ? 0 : $::vmdai::config::poll_ms}]
}

proc ::vmdai::bridge::_executing {} {
    return [expr {[info exists ::vmdai::executor::executing] && $::vmdai::executor::executing}]
}

# One event: tool_start goes to the executor (held back while model Tcl is
# running, e.g. when it calls update or vwait); everything else to the panel.
proc ::vmdai::bridge::_dispatch {ev} {
    variable deferred
    set role ""
    catch {set role [dict get $ev role]}
    if {$role eq "tool_start"} {
        if {[_executing] || [llength $deferred]} {
            _defer $ev
            return
        }
        ::vmdai::executor::run $ev
        return
    }
    if {[catch {::vmdai::ui::render_event $ev} err]} {
        _log "render_event: $err"
    }
    _check_end $ev
}

proc ::vmdai::bridge::_defer {ev} {
    variable deferred
    variable drain_timer
    lappend deferred $ev
    if {$drain_timer eq ""} {
        set drain_timer [::vmdai::sched::after 20 ::vmdai::bridge::_drain]
    }
}

proc ::vmdai::bridge::_drain {} {
    variable deferred
    variable drain_timer
    set drain_timer ""
    if {[_executing]} {
        set drain_timer [::vmdai::sched::after 20 ::vmdai::bridge::_drain]
        return
    }
    set batch $deferred
    set deferred {}
    foreach ev $batch {
        if {[catch {::vmdai::executor::run $ev} err]} {
            _log "executor::run failed: $::errorInfo"
        }
    }
}

# v1 end of a request: the final assistant/message, an error event, or the
# `cancelled` lifecycle event.
proc ::vmdai::bridge::_check_end {ev} {
    variable request_id
    set role [_dget $ev role ""]
    set type [_dget $ev type ""]
    set text [_dget $ev text ""]
    set rid ""
    catch {set rid [dict get $ev metadata request_id]}
    set ends [expr {($role eq "assistant" && $type eq "message") || $role eq "error"
        || ($role eq "system" && $type eq "lifecycle" && $text eq "cancelled")}]
    if {!$ends} {
        return
    }
    if {$rid eq "" || $rid eq "null"} {
        set rid $request_id
    }
    _request_ended $rid
}

# --- connection state (P06-T06 contract) --------------------------------------

proc ::vmdai::bridge::_on_runtime_state {old new detail} {
    variable ready_timer
    switch -- $new {
        ready {
            ::vmdai::sched::cancel $ready_timer
            set ready_timer [::vmdai::sched::after 0 ::vmdai::bridge::_after_ready]
        }
        stopped {
            _reset_session
        }
        default {
            _stop_pump
        }
    }
}

# Runs after the state machine finished its transition (and any recover).
proc ::vmdai::bridge::_after_ready {} {
    variable ready_timer
    variable session_id
    variable op_busy
    variable busy
    variable reconcile_pending
    set ready_timer ""
    if {![_runtime_ready] || $op_busy} {
        return
    }
    if {$session_id eq ""} {
        start_session
        return
    }
    if {$busy} {
        set reconcile_pending 1
    }
    _schedule_poll 0
}

# Busy after a reconnect (spec 2c): once the events are drained, a request
# the runtime no longer runs is ended locally.
proc ::vmdai::bridge::_reconcile {} {
    variable busy
    variable request_id
    if {!$busy} {
        return
    }
    ::vmdai::net::call runtime.info {} [list ::vmdai::bridge::_on_info $request_id]
}

proc ::vmdai::bridge::_on_info {rid kind args} {
    variable busy
    variable request_id
    note_outcome runtime.info $kind {*}$args
    if {$kind ne "ok" || !$busy || $request_id ne $rid} {
        return
    }
    set active ""
    catch {set active [dict get [lindex $args 0] active_request request_id]}
    if {$active eq $rid} {
        return
    }
    _request_ended $rid
    if {[catch {::vmdai::ui::notify info "Request ended (details may be missing)."} err]} {
        _log "ui: $err"
    }
}

proc ::vmdai::bridge::_reset_session {} {
    variable session_id
    variable session_token
    variable chat_id
    variable after_seq
    variable polling
    variable deferred
    variable drain_timer
    variable op_busy
    variable op_queue
    variable recovering
    variable reconcile_pending
    variable request_id
    variable ready_timer
    _stop_pump
    ::vmdai::sched::cancel $drain_timer
    ::vmdai::sched::cancel $ready_timer
    _request_ended $request_id
    set drain_timer ""
    set ready_timer ""
    set session_id ""
    set session_token ""
    set chat_id ""
    set after_seq 0
    set polling 0
    set deferred {}
    set op_busy 0
    set op_queue {}
    set recovering 0
    set reconcile_pending 0
    catch {::vmdai::net::configure -session_id "" -session_token ""}
}

# ::vmdai::stop: end the session (an attached runtime keeps running and must
# release the chat lock), then forget it.
proc ::vmdai::bridge::shutdown {} {
    variable session_id
    if {$session_id ne ""} {
        catch {::vmdai::net::call session.stop {} ::vmdai::bridge::_ignore}
    }
    _reset_session
}

# --- working directory (spec 2d) ----------------------------------------------

proc ::vmdai::bridge::_workdir_file {} {
    return [file join [::vmdai::config::home] .vmdai last_workdir.txt]
}

# The folder from last time, else VMD's current directory.
proc ::vmdai::bridge::_load_workdir {} {
    variable workdir
    set dir ""
    catch {
        set fh [open [_workdir_file] r]
        fconfigure $fh -encoding utf-8
        set dir [string trim [read $fh]]
        close $fh
    }
    if {$dir ne "" && [file isdirectory $dir] && ![catch {cd $dir}]} {
        set workdir [file normalize $dir]
        return
    }
    set workdir [pwd]
}

# Apply a folder: cd VMD there (model Tcl resolves relative paths against
# VMD's cwd), remember it, and tell the runtime (save_path resolves against
# the session cwd). Returns 1 on success.
proc ::vmdai::bridge::apply_workdir {dir} {
    variable workdir
    set dir [file normalize $dir]
    if {![file isdirectory $dir] || [catch {cd $dir} err]} {
        if {[catch {::vmdai::ui::notify error "Can't use the folder $dir."} err]} {
            _log "ui: $err"
        }
        return 0
    }
    set workdir $dir
    catch {
        set path [_workdir_file]
        file mkdir [file dirname $path]
        set fh [open $path w]
        fconfigure $fh -encoding utf-8
        puts -nonewline $fh $dir
        close $fh
    }
    _send_cwd
    return 1
}

proc ::vmdai::bridge::_send_cwd {} {
    variable session_id
    variable workdir
    if {$session_id eq "" || $workdir eq ""} {
        return
    }
    ::vmdai::net::call session.set_cwd [list cwd s $workdir] \
        [list ::vmdai::bridge::_relay session.set_cwd ""]
}

# --- other RPCs the M1 panel uses ----------------------------------------------

proc ::vmdai::bridge::history_list {callback} {
    ::vmdai::net::call chat.history.list [list offset i 0 limit i 50] \
        [list ::vmdai::bridge::_relay chat.history.list $callback]
}

proc ::vmdai::bridge::history_get {target callback} {
    ::vmdai::net::call chat.history.get [list chat_id s $target limit i 200] \
        [list ::vmdai::bridge::_relay chat.history.get $callback]
}

# M1 Apply: provider.set {provider, model}, no profile (spec 2h).
proc ::vmdai::bridge::set_provider {provider model {callback ""}} {
    ::vmdai::net::call provider.set [list provider s $provider model s $model] \
        [list ::vmdai::bridge::_relay provider.set $callback]
}

if {[llength [info commands ::vmdai::runtime::subscribe]]} {
    ::vmdai::runtime::subscribe ::vmdai::bridge::_on_runtime_state
}
```

- [ ] **Step 4: Source the new modules from `plugin/init.tcl`**

In `plugin/init.tcl`, replace:

```tcl
set _vmdai_here [file dirname [info script]]
source [file join $_vmdai_here config.tcl]
source [file join $_vmdai_here ui.tcl]
source [file join $_vmdai_here bridge.tcl]
```

with:

```tcl
set _vmdai_here [file dirname [info script]]
foreach _vmdai_m {config sched net runtime bridge ui} {
    source [file join $_vmdai_here $_vmdai_m.tcl]
}
```

(P06-T09 replaces `init.tcl` as a whole; this keeps it loadable meanwhile.)

- [ ] **Step 5: Drop the legacy names from `plugin/config.tcl`**

No module reads them any more. In `plugin/config.tcl`, replace:

```tcl
    variable plugin_defaults [dict create version 1 python "" appearance system \
        expand_steps 0 geometry ""]

    # Legacy names read by the M1 bridge.tcl until P06-T07 rewrites it.
    variable host "127.0.0.1"
    variable port 8765
    variable poll_limit 80
    variable runtime_log [file normalize [file join $plugin_dir .. runtime runtime.log]]
    if {[info exists ::env(VMD_AI_PYTHON)]} {
        variable python_exec $::env(VMD_AI_PYTHON)
    } else {
        variable python_exec "python3"
    }
}

proc ::vmdai::config::runtime_url {} {
    variable host
    variable port
    return "http://${host}:${port}"
}
```

with:

```tcl
    variable plugin_defaults [dict create version 1 python "" appearance system \
        expand_steps 0 geometry ""]
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_bridge_unit.py tests/test_tcl_lint.py tests/test_tcl_sched.py -q`
Expected: `18 passed` (9 bridge, 3 lint, 6 sched). Then check that nothing in `plugin/` still names a removed config variable, and that the regex JSON parsing §2d deletes is gone with the old bridge (`_response_error`, `_extract_string`/`_extract_int`, `_parse_events_fallback`, the `_parse_history_items` fallback and the `regexp {"cancelled"}` busy check):

```bash
grep -n "python_exec\|runtime_url\|runtime_log\|config::host\|config::port" plugin/*.tcl
grep -n "_response_error\|_extract_string\|_extract_int\|_parse_events_fallback\|_parse_history_items\|regexp.*cancelled" plugin/*.tcl
```

Expected: no output from either command.

- [ ] **Step 7: Run the suite**

Run: `SUITE`
Expected: `B+45 passed`, `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add plugin/bridge.tcl plugin/init.tcl plugin/config.tcl tests/tcl/test_bridge_unit.tcl tests/test_tcl_bridge_unit.py
git commit -F - <<'MSG'
feat(plugin): async bridge with session changes in order, a poll pump and routing

bridge.tcl now talks only through net::call: one poll outstanding,
after_seq advanced per event, has_more drained at once, tool_start held
while model Tcl runs, and busy set only after chat.send answered. New
Chat, Resume and recovery run one at a time and bump the epoch, so a
stale poll can no longer overwrite after_seq. session.start carries the
launch token, event_protocol 1 and vmd_env (C6); apply_workdir cds VMD
and sends session.set_cwd. Every RPC outcome feeds the connection state
machine, and a reconnect reconciles the busy state via runtime.info.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 8: P06-T08 — executor.tcl: approve, ack, pre-check, puts capture, post (C2/C3/C5)

**Files:**
- Create: `plugin/executor.tcl`
- Modify: `plugin/init.tcl` (add `executor` to the module list)
- Test: `tests/tcl/test_executor.tcl`, `tests/test_tcl_executor.py`

**Interfaces:**
- Consumes: `tool_start` events `{seq, role: "tool_start", type, text, metadata: {tool_call_id, tool_name, tool_input, session_id, call_key, request_id, approval: "auto", snapshot_path}}`, where `snapshot_path` is `<snapshot_dir>/vmdai_snap_<call_key>.tga` for `capture_vmd_snapshot` and `""` otherwise (P05-T01, P05-T03); RPC `tool.ack {call_key, state?} -> {proceed, reason?}` (P05-T01; a cancelled, finished or unknown call answers `proceed: false`); `tool.command_result` params `call_key`, `tool_call_id`, `ok`, `executed` (`yes`|`no`), `output`, `error`, `statements_total`, `statements_applied`, `failed_index`, `failed_statement`, `error_info`, `applied_text`, `duration_ms`, `truncated`, `snapshot_file` (P05-T02; the runtime reads and deletes only the `snapshot_path` it chose); `::vmdai::net::call`, `epoch`, `bump_epoch` (P06-T03) and `::vmdai::net::post_result call_key result_pairs` (P06-T04); `::vmdai::sched::after` (P06-T02); at run time, when present, `::vmdai::bridge::note_outcome` (P06-T07) and `::vmdai::ui::status` (P06-T10, in `catch`).
- Produces (`::vmdai::executor`):
  - `run event` — queues one `tool_start` and runs queued events one at a time, in order. For each: skip it if its `call_key` already ran (the last 1000 are remembered) or its request was cancelled; `approve`; a refused call is posted `{ok false, executed no, error "This panel cannot ask for approval"}` without an ack (C2); otherwise `tool.ack {call_key, state running}`, and only `proceed: true` under the same net epoch runs it. Nothing is posted after `proceed: false`. A call whose ack reply was dropped by an epoch change (net drops replies of an older epoch, e.g. after `resume`) is abandoned when the next `tool_start` arrives, so the queue never stalls.
  - `approve meta -> run|refuse` — `run` for `approval` `auto` (or absent: a runtime without the field predates approval), `refuse` for anything else
  - `split_statements script -> dict {statements tail}` — the complete top-level statements, trimmed, split at newlines and `;` with `info complete` (backslash-newline continues a line; `#` comments are skipped as Tcl skips them), and the trimmed incomplete remainder or `""`. `"mol new a.pdb\nset x {\n 1\n}\nbad ["` gives two statements and the tail `bad [` (P08 relies on this).
  - `exec_command command -> dict {ok executed output error truncated duration_ms statements_total statements_applied failed_index failed_statement error_info applied_text}` — C3 pre-check first: an incomplete tail runs nothing and returns `executed no`, `statements_total N`, `statements_applied 0`, `failed_index N`, `failed_statement <tail>`, `error "Nothing was run: statement N of N is incomplete (unbalanced braces, brackets or quotes)"`; an empty command returns `executed no`, `error "Empty command"`. Otherwise every statement runs with `uplevel #0`; catch codes 0 and 2 count as applied, and each non-empty result is added to the output after that statement's `puts` text. The first failure stops the run: `error` is the Tcl message, `failed_index` is applied+1, `failed_statement` at most 200 characters, `error_info` the first 3 lines of `$::errorInfo` (at most 500 characters), and `applied_text` the exact source text of statements 1..applied including their separators (only when 0 < applied). Output past `output_ceiling` characters is cut and ends with `"\n[executor limit: output cut at 1 MB]"`, with `truncated 1` (C5).
  - `puts` capture — while the command runs, `::puts` is an alias to `_puts`: `puts ?-nonewline? ?stdout|stderr? text` is captured; any other channel (a file the model opened) and any other argument form go to the real `puts`. The real command is renamed back after every run, whatever the model's Tcl did to the name.
  - `capture_snapshot input snapshot_path -> dict {ok executed output error duration_ms snapshot_file}` — deletes a stale file, runs `display update`, then `render TachyonInternal $snapshot_path` (no `render snapshot` fallback, §2d); `ok 1` only when the file exists afterwards; an empty `snapshot_path` returns `executed no`
  - `executing` — 1 while a command or a render runs (the bridge holds `tool_start` back meanwhile); `output_ceiling 1048576`
  - results are queued with `net::post_result call_key pairs`: `tool_call_id s`, `ok b`, `executed s`, `output s`, `error s`, then `statements_total i`, `statements_applied i`, `failed_index i`, `failed_statement s`, `error_info s`, `applied_text s`, `duration_ms i`, `snapshot_file s` when they have a value, and `truncated b 1` when cut. A result finished after the net epoch changed (a new session) is dropped.
  - `reset` (forget queued events, remembered call_keys and cancel notes; put `::puts` back unless a command is running); plan additions: `note_cancelled request_id` (the bridge calls it on Stop and New Chat), `ledger -> list of dicts {ts kind command}` and `clear_ledger` (the commands that ran, for the M1 panel's Save Tcl: a partly applied command contributes its `applied_text`)
  - Running a command paints `ui::status "Running: <first line of the command>"` (with ` ...` for more lines) and, when Tk is loaded, one `update idletasks` — only after the C3 pre-check passed (§2d steps 4 and 5), so an incomplete command never shows "Running".

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_executor.tcl`:

```tcl
# tests/tcl/test_executor.tcl - executor.tcl (P06-T08; spec 2d, C2, C3, C5,
# S10). VMD's mol, display and render are stubbed; net::call answers
# tool.ack from ::ack_reply and net::post_result records what is posted.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net executor} { source [file join $plugin $m.tcl] }

# --- fakes --------------------------------------------------------------------
proc ::mol {args} { lappend ::vmd_calls [concat mol $args]; return 0 }
proc ::display {args} { lappend ::vmd_calls [concat display $args]; return "" }
proc ::render {renderer path args} {
    lappend ::vmd_calls [list render $renderer $path]
    set fh [open $path w]
    puts -nonewline $fh [string repeat x 2048]
    close $fh
    return ""
}
proc ::vmdai::net::call {method params callback args} {
    lappend ::rpc [list $method $params]
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback {*}$::ack_reply]
    return rpc#fake
}
namespace eval ::vmdai::ui {}
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
# Posted params, decoded from the JSON the real encoder builds.
proc ::vmdai::net::post_result {call_key pairs} {
    lappend ::posts [list $call_key [::vmdai::net::decode [::vmdai::net::encode_params $pairs]]]
}
proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
}
proc fresh {} {
    ::vmdai::executor::reset
    ::vmdai::executor::clear_ledger
    ::vmdai::sched::teardown
    set ::vmd_calls {}
    set ::rpc {}
    set ::posts {}
    set ::statuses {}
    set ::ack_reply {ok {proceed true}}
}
proc tool_start {key command args} {
    set md [dict create call_key $key request_id req_1 tool_call_id tc_$key \
        tool_name run_vmd_command tool_input [dict create command $command] \
        approval auto snapshot_path ""]
    foreach {k v} $args { dict set md $k $v }
    return [dict create seq 1 role tool_start type message text "\[VMD\] x" metadata $md]
}
# Run one command through the whole pipeline; returns the posted dict.
proc run_cmd {command} {
    ::vmdai::executor::run [tool_start k[incr ::key_seq] $command]
    settle
    return [lindex $::posts end 1]
}
proc pick {d args} {
    set out {}
    foreach k $args { lappend out [expr {[dict exists $d $k] ? [dict get $d $k] : "-"}] }
    return $out
}
set ::key_seq 0

# --- tests --------------------------------------------------------------------

test exec-split-1 {split_statements: complete statements and the incomplete tail} -body {
    set d [::vmdai::executor::split_statements "mol new a.pdb\nset x \{\n 1\n\}\nbad \["]
    set e [::vmdai::executor::split_statements "# note \{\nputs a; # b ; c\nputs \"x;y\"\nputs z\\\n w"]
    list [llength [dict get $d statements]] [dict get $d tail] [dict get $e statements] [dict get $e tail]
} -result [list 2 {bad [} [list {puts a} {puts "x;y"} "puts z\\\n w"] {}]

test exec-puts-1 {puts output and statement results reach the posted output (S10)} -setup fresh -body {
    set r [run_cmd "puts hello\nset n 42"]
    list [pick $r ok executed output statements_total statements_applied] \
        [lindex $::rpc 0] [lindex $::posts 0 0] $::statuses
} -result {{true yes {hello
42
} 2 2} {tool.ack {call_key s k1 state s running}} k1 {{Running: puts hello ...}}}

test exec-puts-2 {puts -nonewline, puts stdout/stderr are captured; puts $fh writes the file; puts is restored} -setup fresh -body {
    set path [file join $::env(HOME) out.txt]
    set ::fh [open $path w]
    set r [run_cmd "puts -nonewline a\nputs stdout b\nputs -nonewline stderr c\nputs \$::fh file-line"]
    close $::fh
    set fh [open $path]
    set file [read $fh]
    close $fh
    set bad [run_cmd "puts x\nerror boom"]
    list [dict get $r output] $file [dict get $bad output] \
        [info commands ::vmdai::executor::_real_puts] [expr {[info commands ::puts] eq "::puts"}]
} -result {{ab
c} {file-line
} {x
} {} 1}

test exec-puts-3 {puts is restored even when the model's Tcl renames it} -setup fresh -body {
    set r [run_cmd "rename puts gone"]
    list [dict get $r ok] [expr {[info commands ::puts] eq "::puts"}] \
        [info commands ::vmdai::executor::_real_puts]
} -cleanup { catch {rename ::gone {}} } -result {true 1 {}}

test exec-code2-1 {catch codes 0 and 2 count as success} -setup fresh -body {
    set r [run_cmd "set a 1\nreturn 7\nset b 2"]
    set brk [run_cmd "break"]
    list [pick $r ok output statements_applied] [pick $brk ok error failed_index]
} -result {{true {1
7
2
} 3} {false {invoked "break" outside of a loop} 1}}

test exec-partial-1 {an error in statement 3 of 4: failed_index, applied_text, error_info (C3)} -setup fresh -body {
    proc ::fails_inside {} { error "no such molecule" }
    set cmd "mol new a.pdb\nmol delrep 0 top\nfails_inside\nmol addrep 0"
    set r [run_cmd $cmd]
    list [pick $r ok executed statements_total statements_applied failed_index failed_statement error] \
        [expr {[dict get $r applied_text] eq "mol new a.pdb\nmol delrep 0 top\n"}] \
        [llength [split [dict get $r error_info] "\n"]] [dict get $r output] [llength $::vmd_calls]
} -cleanup { rename ::fails_inside {} } -result {{false yes 4 2 3 fails_inside {no such molecule}} 1 3 {0
0
} 2}

test exec-precheck-1 {an incomplete tail runs nothing and posts executed no (C3)} -setup fresh -body {
    set r [run_cmd "mol new a.pdb\nmol modstyle 0 0 NewCartoon\nmol modcolor 0 0 \{Name"]
    list [pick $r ok executed statements_total statements_applied failed_index error] \
        [expr {[dict get $r failed_statement] eq "mol modcolor 0 0 \{Name"}] $::vmd_calls [llength $::rpc] \
        $::statuses
} -result {{false no 3 0 3 {Nothing was run: statement 3 of 3 is incomplete (unbalanced braces, brackets or quotes)}} 1 {} 1 {}}

test exec-ceiling-1 {output past 1 MB is cut with a note and truncated true (C5)} -setup fresh -body {
    set r [run_cmd "puts \[string repeat x 2000000\]"]
    set out [dict get $r output]
    set note "\n\[executor limit: output cut at 1 MB\]"
    list [expr {[string length $out] == 1048576 + [string length $note]}] \
        [expr {[string range $out 1048576 end] eq $note}] [string range $out 0 2] \
        [dict get $r truncated] $::vmdai::executor::output_ceiling
} -result {1 1 xxx true 1048576}

test exec-ack-1 {ack proceed false: nothing runs and nothing is posted} -setup fresh -body {
    set ::ack_reply {ok {proceed false reason cancelled}}
    ::vmdai::executor::run [tool_start k100 "mol new a.pdb"]
    settle
    list $::vmd_calls $::posts [llength $::rpc]
} -result {{} {} 1}

test exec-dup-1 {a call_key that already ran is skipped} -setup fresh -body {
    ::vmdai::executor::run [tool_start k200 "mol new a.pdb"]
    ::vmdai::executor::run [tool_start k200 "mol new a.pdb"]
    settle
    list [llength $::rpc] [llength $::posts] [llength $::vmd_calls]
} -result {1 1 1}

test exec-cancel-1 {a tool_start of a cancelled request is skipped} -setup fresh -body {
    ::vmdai::executor::note_cancelled req_1
    ::vmdai::executor::run [tool_start k300 "mol new a.pdb"]
    settle
    list [llength $::rpc] $::posts $::vmd_calls
} -result {0 {} {}}

test exec-approval-1 {approval ask: not acked, not run, posts executed no (C2)} -setup fresh -body {
    ::vmdai::executor::run [tool_start k400 "mol new a.pdb" approval ask]
    settle
    list [llength $::rpc] $::vmd_calls [pick [lindex $::posts 0 1] ok executed error]
} -result {0 {} {false no {This panel cannot ask for approval}}}

test exec-epoch-1 {a session change before the ack answer: nothing runs; the next call still runs} -setup fresh -body {
    ::vmdai::executor::run [tool_start k500 "mol new a.pdb"]
    ::vmdai::net::bump_epoch
    settle
    set stale [list $::vmd_calls $::posts]
    ::vmdai::executor::run [tool_start k501 "mol new b.pdb"]
    settle
    list $stale $::vmd_calls [lindex $::posts 0 0]
} -result {{{} {}} {{mol new b.pdb}} k501}

test exec-snap-1 {capture_vmd_snapshot: display update, render TachyonInternal to snapshot_path} -setup fresh -body {
    set path [file join $::env(HOME) vmdai_snap_k600.tga]
    ::vmdai::executor::run [tool_start k600 "" tool_name capture_vmd_snapshot \
        tool_input {purpose check} snapshot_path $path]
    settle
    set r [lindex $::posts 0 1]
    list $::vmd_calls [pick $r ok executed snapshot_file] [file size $path] \
        [dict get [lindex [::vmdai::executor::ledger] end] command]
} -result [list [list {display update} [list render TachyonInternal [file join $::env(HOME) vmdai_snap_k600.tga]]] \
    [list true yes [file join $::env(HOME) vmdai_snap_k600.tga]] 2048 \
    "render TachyonInternal [file join $::env(HOME) vmdai_snap_k600.tga]"]

test exec-snap-2 {a render error posts ok false with the message} -setup fresh -body {
    rename ::render ::render_ok
    proc ::render {args} { error "Tachyon failed" }
    ::vmdai::executor::run [tool_start k700 "" tool_name capture_vmd_snapshot \
        snapshot_path [file join $::env(HOME) snap2.tga]]
    settle
    pick [lindex $::posts 0 1] ok error
} -cleanup { rename ::render {}; rename ::render_ok ::render } -result {false {Snapshot failed: Tachyon failed}}

cleanupTests
```

Create `tests/test_tcl_executor.py`:

```python
"""executor.tcl: approve, ack, pre-check, puts capture, post (P06-T08; C2, C3, C5, S10).

Runs tests/tcl/test_executor.tcl with VMD's mol, display and render stubbed.
"""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers.tcl import REPO, TclTestResult, run_tcltest

TCL_FILE = REPO / "tests" / "tcl" / "test_executor.tcl"
TOTAL = 15


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return run_tcltest(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_puts_captured(result):
    _assert_passed(result, ["exec-puts-1"])


def test_puts_variants(result):
    _assert_passed(result, ["exec-puts-2", "exec-puts-3"])


def test_code_2_is_success(result):
    _assert_passed(result, ["exec-code2-1"])


def test_partial_failed_index_applied_text_error_info(result):
    _assert_passed(result, ["exec-split-1", "exec-partial-1"])


def test_incomplete_tail_runs_nothing(result):
    _assert_passed(result, ["exec-precheck-1"])


def test_1mb_ceiling_truncated(result):
    _assert_passed(result, ["exec-ceiling-1"])


def test_ack_proceed_false_skips(result):
    _assert_passed(result, ["exec-ack-1", "exec-epoch-1"])


def test_duplicate_call_key_skipped(result):
    _assert_passed(result, ["exec-dup-1", "exec-cancel-1"])


def test_approval_ask_posts_no_without_ack(result):
    _assert_passed(result, ["exec-approval-1"])


def test_snapshot_tachyon_to_snapshot_path(result):
    _assert_passed(result, ["exec-snap-1", "exec-snap-2"])
```

`net::post_result` is replaced by a recorder that decodes the JSON the real `encode_params` builds, so the posted types (`true`/`false`, integers) are checked as the runtime will see them.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_executor.py -q`
Expected: `11 failed`, with `couldn't read file ".../plugin/executor.tcl": no such file or directory`.

- [ ] **Step 3: Create `plugin/executor.tcl`**

```tcl
# executor.tcl - runs the model's Tcl in this VMD session (spec 2d Executor,
# Part C C2, C3, C5). No Tk needed; VMD's mol/render/display are called at
# global level. For each tool_start: skip checks, approve, tool.ack, the
# whole-command pre-check, the run with stdout captured, then the result is
# queued with net::post_result.

namespace eval ::vmdai::executor {
    # 1 while model Tcl runs; the bridge holds tool_start events back.
    variable executing
    if {![info exists executing]} { set executing 0 }
    # Output posted to the runtime is cut here (C5); the runtime saves it.
    variable output_ceiling 1048576
    # tool_start events waiting their turn: each item is {epoch event}.
    variable queue
    if {![info exists queue]} { set queue {} }
    variable current
    if {![info exists current]} { set current "" }
    # The net epoch the current call's tool.ack was sent under.
    variable current_epoch
    if {![info exists current_epoch]} { set current_epoch "" }
    # call_keys that already ran (or were refused) and cancelled requests.
    variable ran
    if {![info exists ran]} { array set ran {} }
    variable ran_order
    if {![info exists ran_order]} { set ran_order {} }
    variable cancelled
    if {![info exists cancelled]} { array set cancelled {} }
    # Commands that ran, for the M1 panel's "Save Tcl...".
    variable ledger
    if {![info exists ledger]} { set ledger {} }
    # stdout/stderr captured while model Tcl runs.
    variable capture
    if {![info exists capture]} { set capture "" }
    variable capture_full
    if {![info exists capture_full]} { set capture_full 0 }
}

proc ::vmdai::executor::_log {msg} {
    catch {::vmdai::config::log "executor: $msg"}
}

proc ::vmdai::executor::_dget {d key default} {
    if {[catch {dict get $d $key} value] || $value eq "null"} {
        return $default
    }
    return $value
}

# --- statements (C3) ------------------------------------------------------------

# Scan a script into complete statements. Returns {spans tail_start}: each
# span is {first last next}, the index of the statement's first and last
# character and of the first character after its separator; tail_start is
# the index where an incomplete statement begins, or -1. Comment lines are
# skipped, as Tcl does.
proc ::vmdai::executor::_scan {script} {
    set spans {}
    set n [string length $script]
    set i 0
    while {$i < $n} {
        # Skip separators and blank space between statements.
        while {$i < $n && [string is space [string index $script $i]] || \
                ($i < $n && [string index $script $i] eq ";")} {
            incr i
        }
        if {$i >= $n} {
            break
        }
        set start $i
        if {[string index $script $i] eq "#"} {
            # A comment runs to the next newline not escaped by a backslash.
            while {$i < $n} {
                set ch [string index $script $i]
                if {$ch eq "\\"} {
                    incr i 2
                    continue
                }
                incr i
                if {$ch eq "\n"} {
                    break
                }
            }
            continue
        }
        set end -1
        set j $i
        while {$j < $n} {
            set ch [string index $script $j]
            if {$ch eq "\\"} {
                incr j 2
                continue
            }
            if {($ch eq "\n" || $ch eq ";")
                    && [info complete [string range $script $start [expr {$j - 1}]]]} {
                set end $j
                break
            }
            incr j
        }
        if {$end < 0} {
            if {![info complete [string range $script $start end]]} {
                return [list $spans $start]
            }
            set end $n
        }
        set text [string range $script $start [expr {$end - 1}]]
        set last [expr {$start + [string length [string trimright $text]] - 1}]
        lappend spans [list $start $last [expr {min($end + 1, $n)}]]
        set i [expr {$end + 1}]
    }
    return [list $spans -1]
}

# split_statements script -> dict {statements tail}: the complete statements
# (trimmed) and the incomplete remainder ("" when there is none).
proc ::vmdai::executor::split_statements {script} {
    lassign [_scan $script] spans tail_start
    set statements {}
    foreach span $spans {
        lappend statements [string range $script [lindex $span 0] [lindex $span 1]]
    }
    set tail ""
    if {$tail_start >= 0} {
        set tail [string trim [string range $script $tail_start end]]
    }
    return [dict create statements $statements tail $tail]
}

proc ::vmdai::executor::_clip {text limit} {
    if {[string length $text] <= $limit} {
        return $text
    }
    return "[string range $text 0 [expr {$limit - 4}]]..."
}

# --- stdout capture -------------------------------------------------------------

proc ::vmdai::executor::_capture_append {text} {
    variable capture
    variable capture_full
    variable output_ceiling
    if {$capture_full} {
        return
    }
    append capture $text
    if {[string length $capture] > $output_ceiling} {
        set capture_full 1
    }
}

# Stands in for ::puts while model Tcl runs: stdout and stderr are captured,
# any other channel (a file the model opened) is written as usual.
proc ::vmdai::executor::_puts {args} {
    set words $args
    set newline 1
    if {[lindex $words 0] eq "-nonewline"} {
        set newline 0
        set words [lrange $words 1 end]
    }
    switch -- [llength $words] {
        1 {
            set chan stdout
            set text [lindex $words 0]
        }
        2 {
            lassign $words chan text
        }
        default {
            return [uplevel 1 [list ::vmdai::executor::_real_puts {*}$args]]
        }
    }
    if {$chan ne "stdout" && $chan ne "stderr"} {
        return [uplevel 1 [list ::vmdai::executor::_real_puts {*}$args]]
    }
    _capture_append [expr {$newline ? "$text\n" : $text}]
    return
}

proc ::vmdai::executor::_install_puts {} {
    variable capture
    variable capture_full
    set capture ""
    set capture_full 0
    if {[llength [info commands ::vmdai::executor::_real_puts]]} {
        return
    }
    rename ::puts ::vmdai::executor::_real_puts
    interp alias {} ::puts {} ::vmdai::executor::_puts
}

# Puts back the real ::puts, whatever the model's Tcl did to the name.
proc ::vmdai::executor::_restore_puts {} {
    if {![llength [info commands ::vmdai::executor::_real_puts]]} {
        return
    }
    catch {rename ::puts {}}
    rename ::vmdai::executor::_real_puts ::puts
}

# --- running one command ----------------------------------------------------------

# Paint "Running..." before the model's Tcl blocks the event loop. With Tk
# loaded this is one `update idletasks` (redraws only).
proc ::vmdai::executor::_paint {text} {
    catch {::vmdai::ui::status $text}
    if {[llength [info commands ::winfo]]} {
        catch {update idletasks}
    }
}

# exec_command command -> dict {ok executed output error truncated
# duration_ms statements_total statements_applied failed_index
# failed_statement error_info applied_text}. The whole command is split
# first (C3): an incomplete tail runs nothing.
proc ::vmdai::executor::exec_command {command} {
    variable executing
    variable capture
    variable output_ceiling
    lassign [_scan $command] spans tail_start
    set total [llength $spans]
    set result [dict create ok 0 executed no output "" error "" truncated 0 duration_ms 0 \
        statements_total $total statements_applied 0 failed_index "" failed_statement "" \
        error_info "" applied_text ""]
    if {$tail_start >= 0} {
        incr total
        dict set result statements_total $total
        dict set result failed_index $total
        dict set result failed_statement [_clip [string trim [string range $command $tail_start end]] 200]
        dict set result error "Nothing was run: statement $total of $total is incomplete (unbalanced braces, brackets or quotes)"
        return $result
    }
    if {$total == 0} {
        dict set result error "Empty command"
        return $result
    }
    set t0 [clock milliseconds]
    set applied 0
    set failed ""
    set executing 1
    _install_puts
    set rc [catch {
        foreach span $spans {
            set statement [string range $command [lindex $span 0] [lindex $span 1]]
            set code [catch {uplevel #0 $statement} value]
            if {$code == 0 || $code == 2} {
                incr applied
                if {$value ne ""} {
                    _capture_append "$value\n"
                }
                continue
            }
            set einfo ""
            if {$code == 1} {
                set einfo [join [lrange [split $::errorInfo "\n"] 0 2] "\n"]
            } elseif {$code == 3} {
                set value "invoked \"break\" outside of a loop"
            } elseif {$code == 4} {
                set value "invoked \"continue\" outside of a loop"
            }
            set failed [list $statement $value $einfo]
            break
        }
    } err]
    _restore_puts
    set executing 0
    if {$rc} {
        set failed [list "" $err ""]
    }
    set output $capture
    set capture ""
    if {[string length $output] > $output_ceiling} {
        set output "[string range $output 0 [expr {$output_ceiling - 1}]]\n\[executor limit: output cut at 1 MB\]"
        dict set result truncated 1
    }
    dict set result output $output
    dict set result executed yes
    dict set result statements_applied $applied
    dict set result duration_ms [expr {[clock milliseconds] - $t0}]
    if {$failed eq ""} {
        dict set result ok 1
        return $result
    }
    lassign $failed statement message einfo
    dict set result error $message
    dict set result failed_index [expr {$applied + 1}]
    dict set result failed_statement [_clip $statement 200]
    dict set result error_info [_clip $einfo 500]
    if {$applied > 0} {
        set next [lindex [lindex $spans [expr {$applied - 1}]] 2]
        dict set result applied_text [string range $command 0 [expr {$next - 1}]]
    }
    return $result
}

# capture_snapshot input snapshot_path -> dict: `display update`, then
# `render TachyonInternal` to the path the runtime chose (spec 2d Snapshot).
proc ::vmdai::executor::capture_snapshot {input snapshot_path} {
    variable executing
    set result [dict create ok 0 executed yes output "" error "" duration_ms 0 \
        snapshot_file $snapshot_path]
    if {$snapshot_path eq ""} {
        dict set result executed no
        dict set result error "The runtime did not choose a snapshot path."
        return $result
    }
    set t0 [clock milliseconds]
    set executing 1
    catch {file delete $snapshot_path}
    catch {uplevel #0 [list display update]}
    set rc [catch {uplevel #0 [list render TachyonInternal $snapshot_path]} err]
    set executing 0
    dict set result duration_ms [expr {[clock milliseconds] - $t0}]
    if {$rc} {
        dict set result error "Snapshot failed: $err"
    } elseif {![file exists $snapshot_path]} {
        dict set result error "Snapshot failed: the renderer wrote no file."
    } else {
        dict set result ok 1
        dict set result output "Snapshot written to $snapshot_path"
    }
    return $result
}

# --- the tool_start pipeline ------------------------------------------------------

# approve meta -> run|refuse. Round 1 runs only `approval: auto` (C2); a
# runtime without the field predates approval and means auto.
proc ::vmdai::executor::approve {meta} {
    set approval [_dget $meta approval auto]
    if {$approval eq "auto"} {
        return run
    }
    return refuse
}

proc ::vmdai::executor::note_cancelled {request_id} {
    variable cancelled
    if {$request_id ne ""} {
        set cancelled($request_id) 1
    }
}

# Queue one tool_start event (the bridge calls this); they run in order.
proc ::vmdai::executor::run {event} {
    variable queue
    lappend queue [list [::vmdai::net::epoch] $event]
    _pump
}

proc ::vmdai::executor::_pump {} {
    variable queue
    variable current
    variable current_epoch
    variable executing
    if {$current ne "" && !$executing && $current_epoch != [::vmdai::net::epoch]} {
        # The session changed while this call waited for its ack: net drops
        # replies of an older epoch, so _on_ack never runs for it.
        _log "call $current abandoned after a session change"
        set current ""
    }
    if {$current ne "" || ![llength $queue]} {
        return
    }
    set item [lindex $queue 0]
    set queue [lrange $queue 1 end]
    lassign $item epoch event
    set current_epoch [::vmdai::net::epoch]
    set meta [_dget $event metadata {}]
    set current [_dget $meta call_key ""]
    if {$current eq ""} {
        _log "tool_start without a call_key ignored"
        _finish
        return
    }
    if {[catch {_start $epoch $meta} err]} {
        _log "tool_start $current failed: $::errorInfo"
        _finish
    }
}

proc ::vmdai::executor::_finish {} {
    variable current
    variable queue
    set current ""
    if {[llength $queue]} {
        ::vmdai::sched::after 0 ::vmdai::executor::_pump
    }
}

proc ::vmdai::executor::_start {epoch meta} {
    variable ran
    variable ran_order
    variable cancelled
    set key [dict get $meta call_key]
    set rid [_dget $meta request_id ""]
    if {[info exists ran($key)]} {
        _log "call $key already ran; skipped"
        _finish
        return
    }
    set ran($key) 1
    lappend ran_order $key
    if {[llength $ran_order] > 1000} {
        unset -nocomplain ran([lindex $ran_order 0])
        set ran_order [lrange $ran_order 1 end]
    }
    if {$rid ne "" && [info exists cancelled($rid)]} {
        _log "call $key belongs to cancelled request $rid; skipped"
        _finish
        return
    }
    if {[approve $meta] ne "run"} {
        # C2: not acked; the runtime treats this result as pickup.
        _post $epoch $meta [dict create ok 0 executed no \
            error "This panel cannot ask for approval"]
        _finish
        return
    }
    ::vmdai::net::call tool.ack [list call_key s $key state s running] \
        [list ::vmdai::executor::_on_ack $epoch $meta]
}

proc ::vmdai::executor::_on_ack {epoch meta kind args} {
    if {[llength [info commands ::vmdai::bridge::note_outcome]]} {
        catch {::vmdai::bridge::note_outcome tool.ack $kind {*}$args}
    }
    set key [dict get $meta call_key]
    set proceed 0
    if {$kind eq "ok"} {
        catch {set proceed [string is true -strict [dict get [lindex $args 0] proceed]]}
    }
    if {!$proceed || $epoch != [::vmdai::net::epoch]} {
        _log "call $key not run: ack $kind $args"
        _finish
        return
    }
    if {[catch {_execute $epoch $meta} err]} {
        _log "call $key failed in the executor: $::errorInfo"
        _post $epoch $meta [dict create ok 0 executed yes error "Executor error: $err"]
    }
    _finish
}

proc ::vmdai::executor::_execute {epoch meta} {
    variable ledger
    set name [_dget $meta tool_name ""]
    set input [_dget $meta tool_input {}]
    switch -- $name {
        run_vmd_command {
            set command [_dget $input command ""]
            # C3: paint "Running" only for a command the pre-check passes.
            if {[string trim $command] ne "" && [dict get [split_statements $command] tail] eq ""} {
                set lines [split [string trim $command] "\n"]
                set label [_clip [lindex $lines 0] 80]
                if {[llength $lines] > 1} {
                    append label " ..."
                }
                _paint "Running: $label"
            }
            set result [exec_command $command]
            if {[dict get $result ok]} {
                lappend ledger [dict create ts [clock seconds] kind command command $command]
            } elseif {[dict get $result applied_text] ne ""} {
                lappend ledger [dict create ts [clock seconds] kind command \
                    command [dict get $result applied_text]]
            }
        }
        capture_vmd_snapshot {
            set path [_dget $meta snapshot_path ""]
            _paint "Rendering a snapshot..."
            set result [capture_snapshot $input $path]
            if {[dict get $result ok]} {
                lappend ledger [dict create ts [clock seconds] kind snapshot \
                    command "render TachyonInternal $path"]
            }
        }
        default {
            set result [dict create ok 0 executed no error "Unknown tool: $name"]
        }
    }
    _post $epoch $meta $result
}

# Queue the result (net::post_result retries it). A result from before a
# session change is dropped: that session is gone.
proc ::vmdai::executor::_post {epoch meta result} {
    set key [dict get $meta call_key]
    if {$epoch != [::vmdai::net::epoch]} {
        _log "call $key finished after the session changed; result dropped"
        return
    }
    set pairs [list tool_call_id s [_dget $meta tool_call_id ""] \
        ok b [dict get $result ok] executed s [_dget $result executed yes] \
        output s [_dget $result output ""] error s [_dget $result error ""]]
    foreach {name type} {statements_total i statements_applied i failed_index i
            failed_statement s error_info s applied_text s duration_ms i
            snapshot_file s} {
        set value [_dget $result $name ""]
        if {$value ne ""} {
            lappend pairs $name $type $value
        }
    }
    if {[_dget $result truncated 0]} {
        lappend pairs truncated b 1
    }
    ::vmdai::net::post_result $key $pairs
}

# Forget queued events and past call_keys (new session, stop, tests). A
# command that is running finishes; the real ::puts is back afterwards.
proc ::vmdai::executor::reset {} {
    variable queue
    variable current
    variable ran
    variable ran_order
    variable cancelled
    variable executing
    set queue {}
    set current ""
    set current_epoch ""
    array unset ran
    set ran_order {}
    array unset cancelled
    if {!$executing} {
        _restore_puts
    }
}

proc ::vmdai::executor::ledger {} {
    variable ledger
    return $ledger
}

proc ::vmdai::executor::clear_ledger {} {
    variable ledger
    set ledger {}
}
```

- [ ] **Step 4: Load it from `plugin/init.tcl`**

In `plugin/init.tcl`, replace:

```tcl
foreach _vmdai_m {config sched net runtime bridge ui} {
```

with:

```tcl
foreach _vmdai_m {config sched net runtime bridge executor ui} {
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_executor.py tests/test_tcl_bridge_unit.py tests/test_tcl_lint.py -q`
Expected: `23 passed` (11 executor, 9 bridge, 3 lint).

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+56 passed`, `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add plugin/executor.tcl plugin/init.tcl tests/tcl/test_executor.tcl tests/test_tcl_executor.py
git commit -F - <<'MSG'
feat(plugin): executor with ack, whole-command pre-check and puts capture

Each tool_start is skipped if its call_key already ran or its request was
cancelled, refused without an ack unless approval is auto (C2), acked,
split with info complete so an incomplete tail runs nothing (C3), then
run statement by statement with stdout/stderr captured and the real puts
restored on every path (S10). Failures report failed_index,
failed_statement, error_info and the exact applied_text; output is cut
at 1 MB with truncated true (C5). Snapshots render with TachyonInternal
to the runtime's snapshot_path.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 9: P06-T09 — pkgIndex, entry points, menu, installer

**Files:**
- Create: `plugin/pkgIndex.tcl`, `scripts/install_plugin.tcl`
- Modify (replace whole file): `plugin/init.tcl`
- Test: `tests/tcl/test_init.tcl`, `tests/test_tcl_install.py`

**Interfaces:**
- Consumes: `::vmdai::sched::teardown`, `pending` and the `timers` array (tests) (P06-T02); `::vmdai::runtime::ensure`, `stop ?-sync?`, `state`, `info` (P06-T05); `::vmdai::bridge::shutdown`, `state`, `op_busy` (P06-T07); `::vmdai::executor::reset` (P06-T08); `::vmdai::ui::show_panel -> window path` and `::vmdai::ui::win` (today's `ui.tcl`; P06-T10 keeps both names); `FakeRpcServer` (P06-T03); `vmd_ai_runtime.launch.write_token_file(port, pid, token, protocol=2, home=None)` (P02-T02); `helpers.tcl.run_tcl`, `run_tcltest`, `find_tclsh`, `tcl_skip_reason`, `tcl_word` (P01-T03). In VMD: `vmd_install_extension name command menupath` and `play file` (VMD 1.9.4a57 has no `vmd_remove_extension`; it is called only when present).
- Produces:
  - `package vmd_ai 2.0`: `plugin/pkgIndex.tcl` declares `package ifneeded vmd_ai 2.0 [list source [file join $dir init.tcl]]`
  - `plugin/init.tcl` (replaced): `package provide vmd_ai 2.0`; one `source` line per module in the order config, sched, net, runtime, bridge, executor, ui (the first through the script's own directory, the rest through `$::vmdai::config::plugin_dir`; P09-T01 inserts the Tk modules between the executor and ui lines). Loading needs no Tk and starts nothing.
  - `::vmdai::start -> window path` — `::vmdai::ui::show_panel`, then `::vmdai::runtime::ensure` (launch, or attach with `VMD_AI_ATTACH`); VMD's extension menu calls it
  - `::vmdai::stop ?-sync?` — destroys `$::vmdai::ui::win` when Tk is loaded (the only line in `init.tcl` naming `::vmdai::ui::win`; P09-T01 replaces it), `bridge::shutdown`, `runtime::stop` (`-sync` waits for an owned runtime to exit; an attached runtime keeps running), `executor::reset`
  - `::vmdai::cleanup` — `stop -sync`, then `sched::teardown`; afterwards `after info` is empty (S4). The synchronous stop comes first because teardown would cancel the kill -9 timer of an asynchronous one.
  - `::vmdai::reload -> window path or ""` — `cleanup`, re-sources `init.tcl` from `config::plugin_dir`, then, when Tk is loaded, `::vmdai::start` again, as today's reload does; `""` without Tk
  - `::vmdai::register_extension -> 1|0` — Extensions > "VMD AI" runs `::vmdai::start`; 0 outside VMD. `init.tcl` calls it once per load.
  - `scripts/install_plugin.tcl ?--yes? ?--dry-run? ?--uninstall? ?--vmdrc PATH? ?--plugin-dir DIR?` (Tcl 8.5 or later): shows the block and asks `[y/N]` unless `--yes`; exit 0 on success or "nothing changed", 1 when declined or on an error, 2 on bad usage. The block sits between `# >>> vmdai >>>` and `# <<< vmdai <<<` and holds one functional line, `if {[catch {lappend auto_path <plugin dir>; package require vmd_ai 2.0} vmdai_err]} { puts "ChatVMD did not load: $vmdai_err" }; unset vmdai_err`. When `~/.vmdrc` does not exist yet, the block also starts with a line that plays `$env(VMDDIR)/.vmdrc`, because VMD reads only the first `.vmdrc` it finds and a new `~/.vmdrc` would otherwise hide VMD's default menus and lights. Re-running replaces the block in place (idempotent); the rest of the file is kept byte for byte, and the first change saves `.vmdrc.vmdai-backup`. `--uninstall` removes the block (and the blank line the installer put before it) and deletes the file when nothing else is left.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_init.tcl`:

```tcl
# tests/tcl/test_init.tcl - package, entry points, menu and reload (P06-T09,
# S4). The pytest wrapper serves a FakeRpcServer (a protocol-2 /health, a
# session.start that hands out sessions, empty polls) and writes its token
# file under $HOME; VMDAI_ATTACH_PORT names it. No Tk: the panel is stubbed.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set ::menu {}
proc ::vmd_install_extension {name cmd path} { lappend ::menu [list $name $cmd $path] }

proc wait_for {script {ms 5000}} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { return 0 }
        set ::_tick 0
        after 20 {set ::_tick 1}
        vwait ::_tick
    }
    return 1
}
proc sleep_ms {ms} {
    set ::_slept 0
    after $ms {set ::_slept 1}
    vwait ::_slept
}
# The panel needs Tk; these tests only need its names.
proc stub_panel {} {
    proc ::vmdai::ui::show_panel {} { return .vmd_ai }
    foreach p {notify render_event set_busy status} { proc ::vmdai::ui::$p {args} {} }
}
# Attach to the fake runtime and wait for a session and a running pump.
proc attach_and_poll {} {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    ::vmdai::start
    wait_for {expr {[dict get [::vmdai::bridge::state] session_id] ne ""}}
    sleep_ms 300
}
# Timers whose script is the bridge's poll pump.
proc poll_timers {} {
    set n 0
    foreach id [::vmdai::sched::pending] {
        if {[string match *_poll* [lindex $::vmdai::sched::timers($id) 1]]} { incr n }
    }
    return $n
}

test init-pkg-1 {package require vmd_ai loads 2.0 and defines the entry points} -body {
    lappend ::auto_path $::env(VMDAI_PLUGIN_DIR)
    set v [package require vmd_ai]
    stub_panel
    set missing {}
    foreach p {::vmdai::start ::vmdai::stop ::vmdai::cleanup ::vmdai::reload
               ::vmdai::register_extension ::vmdai::ui::show_panel} {
        if {[info commands $p] eq ""} { lappend missing $p }
    }
    list $v [package present vmd_ai] $missing [::vmdai::runtime::state] [after info]
} -result {2.0 2.0 {} stopped {}}

test init-menu-1 {the menu entry is Extensions > VMD AI and runs ::vmdai::start} -body {
    set first $::menu
    ::vmdai::register_extension
    list $first [llength $::menu]
} -result {{{vmd_ai ::vmdai::start {VMD AI}}} 2}

test init-start-1 {::vmdai::start returns the window path and attaches} -body {
    set ::env(VMD_AI_ATTACH) 127.0.0.1:$::env(VMDAI_ATTACH_PORT)
    set w [::vmdai::start]
    wait_for {expr {[::vmdai::runtime::state] eq "ready"}}
    list $w [::vmdai::runtime::state] [dict get [::vmdai::runtime::info] owned]
} -cleanup { ::vmdai::cleanup } -result {.vmd_ai ready 0}

test init-reload-1 {reload twice: nothing left in after info; one poll pump afterwards (S4)} -body {
    set r {}
    foreach round {1 2} {
        attach_and_poll
        set before [expr {[poll_timers] <= 1}]
        ::vmdai::reload
        stub_panel
        lappend r [list $before [after info] [::vmdai::sched::pending] [::vmdai::runtime::state] \
            [llength $::menu]]
    }
    attach_and_poll
    set ::polls 0
    trace add execution ::vmdai::net::call enter {apply {{cmd op} {
        if {[lindex $cmd 1] eq "chat.events.poll"} { incr ::polls }
    }}}
    sleep_ms 1000
    set steady [list [expr {[poll_timers] <= 1}] [expr {$::polls >= 2 && $::polls <= 5}]]
    ::vmdai::cleanup
    list $r $steady [after info] [::vmdai::runtime::state]
} -result {{{1 {} {} stopped 3} {1 {} {} stopped 4}} {1 1} {} stopped}

test init-stop-1 {::vmdai::stop leaves an attached runtime alone and ends the session} -body {
    attach_and_poll
    ::vmdai::stop
    set r [list [::vmdai::runtime::state] [dict get [::vmdai::bridge::state] session_id]]
    ::vmdai::cleanup
    lappend r [after info]
} -result {stopped {} {}}

cleanupTests
```

Create `tests/test_tcl_install.py`:

```python
"""pkgIndex, entry points, menu, reload (S4) and the ~/.vmdrc installer (P06-T09)."""
from __future__ import annotations

import itertools
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from helpers.fake_rpc_server import FakeRpcServer
from helpers.tcl import REPO, TclTestResult, find_tclsh, run_tcl, run_tcltest, tcl_skip_reason, tcl_word
from vmd_ai_runtime.launch import write_token_file

TCL_FILE = REPO / "tests" / "tcl" / "test_init.tcl"
INSTALLER = REPO / "scripts" / "install_plugin.tcl"
PLUGIN = REPO / "plugin"
TOTAL = 5
TOKEN = "fedcba9876543210fedcba9876543210"
BEGIN = "# >>> vmdai >>>"
END = "# <<< vmdai <<<"


def _handler():
    numbers = itertools.count(1)

    def handler(method: str, params: Dict[str, Any], headers: Dict[str, str]) -> Any:
        if method == "session.start":
            n = next(numbers)
            return {"result": {"session_id": f"sess_{n}", "session_token": f"tok_{n}",
                               "chat_id": None, "event_protocol": 1}}
        if method == "chat.events.poll":
            return {"result": {"events": [], "last_seq": 0, "has_more": False}}
        return {"result": {"ok": True}}

    return handler


@pytest.fixture(scope="module")
def init_run(tmp_path_factory) -> TclTestResult:
    home = tmp_path_factory.mktemp("init") / "home"
    home.mkdir()
    with FakeRpcServer(_handler()) as fake:
        write_token_file(fake.port, 4242, TOKEN, 2, home=str(home))
        return run_tcltest(str(TCL_FILE), env={"HOME": str(home),
                                               "VMDAI_ATTACH_PORT": str(fake.port)})


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_counts(init_run):
    assert (init_run.passed, init_run.failed) == (TOTAL, 0), init_run.output


def test_package_provide_2_0(init_run):
    _assert_passed(init_run, ["init-pkg-1", "init-start-1"])


def test_menu_path_vmd_ai(init_run):
    _assert_passed(init_run, ["init-menu-1"])


def test_reload_twice_after_info_empty(init_run):
    _assert_passed(init_run, ["init-reload-1", "init-stop-1"])


# --- installer ------------------------------------------------------------------

def _install(vmdrc: Path, *args: str, answer: str = "") -> subprocess.CompletedProcess:
    reason = tcl_skip_reason()
    if reason:
        pytest.skip(reason)
    return subprocess.run([find_tclsh(), str(INSTALLER), "--vmdrc", str(vmdrc), *args],
                          input=answer, capture_output=True, text=True, timeout=30)


def test_installer_idempotent(tmp_path):
    vmdrc = tmp_path / "home dir" / ".vmdrc"
    vmdrc.parent.mkdir()
    original = "# my VMD settings\ncolor Display Background white\n"
    vmdrc.write_text(original, encoding="utf-8")

    first = _install(vmdrc, "--yes")
    assert first.returncode == 0, first.stderr
    installed = vmdrc.read_text(encoding="utf-8")
    assert installed.startswith(original + "\n" + BEGIN + "\n")
    assert installed.endswith(END + "\n")
    assert installed.count(BEGIN) == 1
    assert f"lappend auto_path {tcl_word(str(PLUGIN))}; package require vmd_ai 2.0" in installed
    assert "play [file join $env(VMDDIR) .vmdrc]" not in installed  # the user's file stays in charge
    assert (tmp_path / "home dir" / ".vmdrc.vmdai-backup").read_text(encoding="utf-8") == original

    again = _install(vmdrc, "--yes")
    assert again.returncode == 0 and "already installed" in again.stdout
    assert vmdrc.read_text(encoding="utf-8") == installed

    # An older block (another plugin path) is replaced in place.
    moved = installed.replace(tcl_word(str(PLUGIN)), "/old/place/plugin")
    vmdrc.write_text(moved, encoding="utf-8")
    assert _install(vmdrc, "--yes").returncode == 0
    assert vmdrc.read_text(encoding="utf-8") == installed

    removed = _install(vmdrc, "--uninstall", "--yes")
    assert removed.returncode == 0, removed.stderr
    assert vmdrc.read_text(encoding="utf-8") == original


def test_installer_new_file_keeps_vmd_defaults_and_uninstall_deletes(tmp_path):
    vmdrc = tmp_path / ".vmdrc"
    assert _install(vmdrc, "--yes").returncode == 0
    text = vmdrc.read_text(encoding="utf-8")
    assert text.startswith(BEGIN + "\n") and "play [file join $env(VMDDIR) .vmdrc]" in text
    assert not (tmp_path / ".vmdrc.vmdai-backup").exists()
    assert _install(vmdrc, "--yes").returncode == 0
    assert vmdrc.read_text(encoding="utf-8") == text
    assert _install(vmdrc, "--uninstall", "--yes").returncode == 0
    assert not vmdrc.exists()


def test_installer_asks_first(tmp_path):
    vmdrc = tmp_path / ".vmdrc"
    vmdrc.write_text("menu main on\n", encoding="utf-8")
    declined = _install(vmdrc, answer="n\n")
    assert declined.returncode == 1 and "Nothing changed." in declined.stdout
    assert BEGIN in declined.stdout  # the block was shown before asking
    assert vmdrc.read_text(encoding="utf-8") == "menu main on\n"
    dry = _install(vmdrc, "--dry-run")
    assert dry.returncode == 0 and vmdrc.read_text(encoding="utf-8") == "menu main on\n"
    accepted = _install(vmdrc, answer="y\n")
    assert accepted.returncode == 0 and BEGIN in vmdrc.read_text(encoding="utf-8")


def test_vmdrc_block_loads_the_plugin(tmp_path):
    """Played by VMD at start: the block puts plugin/ on auto_path and loads vmd_ai 2.0."""
    vmdrc = tmp_path / ".vmdrc"
    assert _install(vmdrc, "--yes").returncode == 0
    proc = run_tcl(
        "set ::played {}\n"
        "proc play {path} { lappend ::played [file tail $path] }\n"
        "set ::menu {}\n"
        "proc vmd_install_extension {args} { lappend ::menu $args }\n"
        "set env(VMDDIR) [file join $env(HOME) vmddir]\n"
        "file mkdir $env(VMDDIR)\n"
        "close [open [file join $env(VMDDIR) .vmdrc] w]\n"
        f"source {tcl_word(str(vmdrc))}\n"
        "puts [list [package present vmd_ai] $::menu $::played [info exists vmdai_err]]\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "2.0 {{vmd_ai ::vmdai::start {VMD AI}}} .vmdrc 0"
```

`init-reload-1` is the S4 check: after each reload `after info` and `sched::pending` are empty and the runtime is `stopped`; after the last start at most one poll timer exists at any moment and a one-second window sees 2–5 polls (one pump at 250 ms, not two). The installer tests run the script as a subprocess, and `test_vmdrc_block_loads_the_plugin` sources the file it wrote with `play` and `vmd_install_extension` stubbed, as VMD would play it.

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_install.py -q`
Expected: `8 failed`; the tcltest output shows `can't find package vmd_ai`, and the installer tests fail because `scripts/install_plugin.tcl` does not exist (`couldn't read file`).

- [ ] **Step 3: Create `plugin/pkgIndex.tcl`**

```tcl
# pkgIndex.tcl - `package require vmd_ai` loads ChatVMD (spec 2h). The line
# scripts/install_plugin.tcl adds to ~/.vmdrc puts this directory on auto_path.
if {![package vsatisfies [package provide Tcl] 8.5]} {return}
package ifneeded vmd_ai 2.0 [list source [file join $dir init.tcl]]
```

- [ ] **Step 4: Replace `plugin/init.tcl`**

```tcl
# init.tcl - ChatVMD entry points, module loading and the VMD menu (spec 2h).
# Loaded by `package require vmd_ai` (pkgIndex.tcl, which the installer's
# ~/.vmdrc line puts on auto_path) or sourced directly. Loading needs no Tk
# and starts nothing: the runtime starts when the panel is opened.

namespace eval ::vmdai {}
package provide vmd_ai 2.0

source [file join [file dirname [file normalize [info script]]] config.tcl]
source [file join $::vmdai::config::plugin_dir sched.tcl]
source [file join $::vmdai::config::plugin_dir net.tcl]
source [file join $::vmdai::config::plugin_dir runtime.tcl]
source [file join $::vmdai::config::plugin_dir bridge.tcl]
source [file join $::vmdai::config::plugin_dir executor.tcl]
source [file join $::vmdai::config::plugin_dir ui.tcl]

# Open the panel and make sure the runtime is up (launch, or attach with
# VMD_AI_ATTACH). Returns the panel's window path, as VMD's menu expects.
proc ::vmdai::start {} {
    set w [::vmdai::ui::show_panel]
    ::vmdai::runtime::ensure
    return $w
}

# Close the panel and stop the runtime. An owned runtime is shut down; an
# attached one keeps running (spec 2d). With -sync, wait (without an event
# loop) until an owned runtime has exited.
proc ::vmdai::stop {args} {
    if {[llength [info commands ::winfo]]} {
        catch {destroy $::vmdai::ui::win}
    }
    ::vmdai::bridge::shutdown
    if {[lsearch -exact $args -sync] >= 0} {
        ::vmdai::runtime::stop -sync
    } else {
        ::vmdai::runtime::stop
    }
    ::vmdai::executor::reset
}

# Stop everything, then cancel every timer, fileevent and http token the
# plugin registered (S4). The runtime is stopped with -sync first, because
# teardown would cancel the timer that escalates to kill -9.
proc ::vmdai::cleanup {} {
    catch {::vmdai::stop -sync}
    ::vmdai::sched::teardown
}

# Development helper: tear everything down, re-source the plugin from
# config::plugin_dir and, when Tk is loaded, open the panel again. Returns
# the window path, or "" without Tk.
proc ::vmdai::reload {} {
    ::vmdai::cleanup
    source [file join $::vmdai::config::plugin_dir init.tcl]
    if {[llength [info commands ::winfo]]} {
        return [::vmdai::start]
    }
    return ""
}

# Extensions > VMD AI. Outside VMD (tclsh tests) there is no menu.
proc ::vmdai::register_extension {} {
    if {![llength [info commands ::vmd_install_extension]]} {
        return 0
    }
    if {[llength [info commands ::vmd_remove_extension]]} {
        catch {::vmd_remove_extension vmd_ai}
    }
    if {[catch {::vmd_install_extension vmd_ai ::vmdai::start "VMD AI"} err]} {
        ::vmdai::config::log "menu registration failed: $err"
        return 0
    }
    return 1
}

::vmdai::register_extension
```

- [ ] **Step 5: Create `scripts/install_plugin.tcl`**

```tcl
# scripts/install_plugin.tcl - load ChatVMD when VMD starts, by adding one
# marked block to your own VMD startup file, ~/.vmdrc (spec 2h).
#
#   tclsh scripts/install_plugin.tcl               show the block, ask, add it
#   tclsh scripts/install_plugin.tcl --yes         add it without asking
#   tclsh scripts/install_plugin.tcl --dry-run     only show what would change
#   tclsh scripts/install_plugin.tcl --uninstall   remove the block again
#   options: --vmdrc PATH (another startup file), --plugin-dir DIR
#
# The block sits between "# >>> vmdai >>>" and "# <<< vmdai <<<". Running the
# installer again replaces it in place, so repeating it is safe. The rest of
# the file is kept byte for byte, and the first change saves a copy next to
# it as .vmdrc.vmdai-backup. VMD reads only the first .vmdrc it finds (./,
# then ~, then $VMDDIR), so when ~/.vmdrc does not exist yet the block also
# plays VMD's own default startup file, keeping VMD's usual menus and lights.
# Works with Tcl 8.5 and later.

namespace eval ::installer {
    variable begin "# >>> vmdai >>>"
    variable end "# <<< vmdai <<<"
    variable defaults_line {if {[info exists env(VMDDIR)] && [file readable [file join $env(VMDDIR) .vmdrc]]} { play [file join $env(VMDDIR) .vmdrc] }}
}

proc ::installer::usage {} {
    puts stderr "usage: tclsh install_plugin.tcl ?--yes? ?--dry-run? ?--uninstall? ?--vmdrc PATH? ?--plugin-dir DIR?"
    exit 2
}

# The file's bytes (the empty string when it does not exist).
proc ::installer::read_bytes {path} {
    if {![file exists $path]} {
        return ""
    }
    set fh [open $path r]
    fconfigure $fh -translation binary
    set data [read $fh]
    close $fh
    return $data
}

# Write bytes through a temporary file and a rename, keeping permissions.
proc ::installer::write_bytes {path data} {
    set tmp "$path.vmdai-tmp"
    set fh [open $tmp w]
    fconfigure $fh -translation binary
    puts -nonewline $fh $data
    close $fh
    if {[file exists $path] && $::tcl_platform(platform) eq "unix"} {
        catch {file attributes $tmp -permissions [file attributes $path -permissions]}
    }
    file rename -force $tmp $path
}

# The block, as UTF-8 bytes. The plugin path is quoted as one Tcl word.
proc ::installer::block {plugin_dir with_defaults} {
    variable begin
    variable end
    variable defaults_line
    set lines [list $begin \
        "# ChatVMD (Extensions > VMD AI). Added by scripts/install_plugin.tcl;" \
        "# remove it with: tclsh scripts/install_plugin.tcl --uninstall"]
    if {$with_defaults} {
        lappend lines $defaults_line
    }
    lappend lines "if \{\[catch \{lappend auto_path [list $plugin_dir]; package require vmd_ai 2.0\} vmdai_err\]\} \{ puts \"ChatVMD did not load: \$vmdai_err\" \}; unset vmdai_err"
    lappend lines $end
    return [encoding convertto utf-8 "[join $lines \n]\n"]
}

# {first last}: byte range of the block including its final newline, or
# {-1 -1} when the file has none.
proc ::installer::find_block {data} {
    variable begin
    variable end
    set first [string first $begin $data]
    if {$first < 0} {
        return {-1 -1}
    }
    set stop [string first $end $data $first]
    if {$stop < 0} {
        error "found \"$begin\" without \"$end\"; fix the file by hand"
    }
    set last [expr {$stop + [string length $end] - 1}]
    if {[string index $data [expr {$last + 1}]] eq "\n"} {
        incr last
    }
    return [list $first $last]
}

proc ::installer::confirm {question} {
    puts -nonewline "$question \[y/N\] "
    flush stdout
    if {[gets stdin answer] < 0} {
        return 0
    }
    return [expr {[string tolower [string trim $answer]] in {y yes}}]
}

proc ::installer::main {argv} {
    variable defaults_line
    set yes 0
    set dry 0
    set uninstall 0
    set vmdrc [file join $::env(HOME) .vmdrc]
    set here [file dirname [file normalize [info script]]]
    set plugin_dir [file normalize [file join $here .. plugin]]
    while {[llength $argv]} {
        set argv [lassign $argv arg]
        switch -- $arg {
            --yes { set yes 1 }
            --dry-run { set dry 1 }
            --uninstall { set uninstall 1 }
            --vmdrc {
                if {![llength $argv]} { usage }
                set argv [lassign $argv vmdrc]
            }
            --plugin-dir {
                if {![llength $argv]} { usage }
                set argv [lassign $argv plugin_dir]
                set plugin_dir [file normalize $plugin_dir]
            }
            default { usage }
        }
    }
    set vmdrc [file normalize $vmdrc]
    set old [read_bytes $vmdrc]
    lassign [find_block $old] first last
    if {$uninstall} {
        if {$first < 0} {
            puts "ChatVMD is not installed in $vmdrc; nothing changed."
            return 0
        }
        set before [string range $old 0 [expr {$first - 1}]]
        # Drop the blank line the installer put in front of the block.
        if {[string range $before end-1 end] eq "\n\n"} {
            set before [string range $before 0 end-1]
        }
        set new "$before[string range $old [expr {$last + 1}] end]"
        puts "ChatVMD will remove its block from $vmdrc."
        if {$dry} {
            return 0
        }
        if {!$yes && ![confirm "Remove it?"]} {
            puts "Nothing changed."
            return 1
        }
        if {[string trim $new] eq ""} {
            file delete $vmdrc
            puts "Removed ChatVMD from $vmdrc (the file only held ChatVMD, so it was deleted)."
        } else {
            write_bytes $vmdrc $new
            puts "Removed ChatVMD from $vmdrc."
        }
        return 0
    }
    if {![file exists [file join $plugin_dir pkgIndex.tcl]]} {
        puts stderr "No pkgIndex.tcl in $plugin_dir; pass --plugin-dir with the ChatVMD plugin folder."
        return 1
    }
    set exists [file exists $vmdrc]
    if {$first >= 0} {
        set current [string range $old $first $last]
        set with_defaults [expr {[string first $defaults_line $current] >= 0}]
        set block [block $plugin_dir $with_defaults]
        if {$current eq $block} {
            puts "ChatVMD is already installed in $vmdrc; nothing changed."
            return 0
        }
        set new "[string range $old 0 [expr {$first - 1}]]$block[string range $old [expr {$last + 1}] end]"
    } else {
        set block [block $plugin_dir [expr {!$exists}]]
        if {$old eq ""} {
            set sep ""
        } elseif {[string index $old end] eq "\n"} {
            set sep "\n"
        } else {
            set sep "\n\n"
        }
        set new "$old$sep$block"
    }
    puts "ChatVMD will add these lines to $vmdrc:\n"
    puts [encoding convertfrom utf-8 $block]
    if {$dry} {
        return 0
    }
    if {!$yes && ![confirm "Add them?"]} {
        puts "Nothing changed."
        return 1
    }
    if {$exists && ![file exists "$vmdrc.vmdai-backup"]} {
        file copy $vmdrc "$vmdrc.vmdai-backup"
    }
    write_bytes $vmdrc $new
    puts "Installed ChatVMD in $vmdrc. Start VMD and open Extensions > VMD AI."
    return 0
}

if {[info exists ::argv0] && [file normalize $::argv0] eq [file normalize [info script]]} {
    if {[catch {::installer::main $::argv} code]} {
        puts stderr "install_plugin: $code"
        exit 1
    }
    exit $code
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_install.py tests/test_tcl_bridge_unit.py tests/test_tcl_executor.py -q`
Expected: `28 passed` (8 install, 9 bridge, 11 executor).

- [ ] **Step 7: Try the installer by hand**

```bash
T="$(mktemp -d)"
TCLSH="$(PYTHONPATH=tests python -c 'from helpers.tcl import find_tclsh; print(find_tclsh())')"
"$TCLSH" scripts/install_plugin.tcl --vmdrc "$T/.vmdrc" --dry-run
/usr/bin/tclsh scripts/install_plugin.tcl --vmdrc "$T/.vmdrc" --yes
"$TCLSH" scripts/install_plugin.tcl --vmdrc "$T/.vmdrc" --yes
"$TCLSH" scripts/install_plugin.tcl --vmdrc "$T/.vmdrc" --uninstall --yes
ls -A "$T"
```

Expected: the dry run prints `ChatVMD will add these lines to …/.vmdrc:` and the six-line block (markers, two comment lines, the `play [file join $env(VMDDIR) .vmdrc]` line because the file does not exist yet, and the `package require vmd_ai 2.0` line); the Tcl 8.5 run (`/usr/bin/tclsh` 8.5.9) ends with `Installed ChatVMD in …/.vmdrc. Start VMD and open Extensions > VMD AI.`; the second run prints `ChatVMD is already installed in …/.vmdrc; nothing changed.`; the uninstall prints `ChatVMD will remove its block from …` and `Removed ChatVMD from …/.vmdrc (the file only held ChatVMD, so it was deleted).`; `ls -A` prints nothing.

- [ ] **Step 8: Run the suite**

Run: `SUITE`
Expected: `B+64 passed`, `0 failed`.

- [ ] **Step 9: Commit**

```bash
git add plugin/pkgIndex.tcl plugin/init.tcl scripts/install_plugin.tcl tests/tcl/test_init.tcl tests/test_tcl_install.py
git commit -F - <<'MSG'
feat(plugin): package vmd_ai 2.0, entry points, VMD AI menu and ~/.vmdrc installer

pkgIndex.tcl provides vmd_ai 2.0 and init.tcl loads the modules in
order without Tk. ::vmdai::start opens the panel and ensures the
runtime, stop leaves an attached runtime running, cleanup waits for an
owned one and tears down every timer (S4), and reload re-sources from
config::plugin_dir. scripts/install_plugin.tcl asks before adding one
marked block to ~/.vmdrc, is idempotent, keeps VMD's default startup
file in play when it creates ~/.vmdrc, and has --uninstall.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 10: P06-T10 — ui.tcl minimal fixes, notify sink, Tk test helper

**Files:**
- Create: `tests/helpers/tk.py`
- Modify (replace whole file): `plugin/ui.tcl`
- Test: `tests/tcl/test_ui_min.tcl`, `tests/test_tk_ui_min.py`

**Interfaces:**
- Consumes: `::vmdai::bridge::send`, `cancel`, `new_chat`, `resume chat_id ?callback?`, `history_list callback`, `history_get chat_id callback`, `set_provider provider model ?callback?`, `apply_workdir dir`, `_load_workdir` and the variable `workdir` (P06-T07); `::vmdai::executor::ledger`, `clear_ledger` (P06-T08); `::vmdai::sched::after`, `cancel`, `pending` (P06-T02); `::vmdai::config::home` (P06-T02); `helpers.tcl.run_tcltest(test_file, *, env=None, timeout=120, prelude='')`, `find_tclsh`, `tcl_skip_reason`, `tcl_word`, `REPO`, `TclTestResult` (P01-T03); `helpers.live.LIVE_ENV` (P01-T01).
- Produces (`::vmdai::ui`, the M1 panel; each of the first five does nothing without Tk or without the window):
  - `notify level text` — the connection state machine's sink (S3): exactly one transcript line, tagged `notice_info`, `notice_warn` or `notice_error` (any other level counts as `info`; newlines become spaces); an open streamed block is closed first
  - `render_event event` — v1 events: chunks stream into one block per role and request; a change of role or request, and every non-chunk event, closes the open block first (fix 2); the final `assistant/message` only ends the block; the `cancelled` lifecycle event prints `Stopped.`; other lifecycle events print nothing; user events are skipped (`on_send` shows them)
  - `set_busy on` — the bridge calls it once `chat.send` succeeded and when the request ends: Stop enabled, Send disabled and a "Thinking" line only in between (fix 1)
  - `status text` — one `SYSTEM:` line (the executor's `Running: …`)
  - `show_panel -> window path` (`.vmd_ai`): builds the window, or deiconifies and raises it; it never starts the runtime (`::vmdai::start` does). Closing the window withdraws it (spec §2d Shutdown).
  - The provider dropdown only refills the model entry; `chat.send` never carries a model (fix 3), and Apply sends `provider.set {provider, model}` with no profile. The folder row shows the bridge's folder (at most 60 characters, a long path starts with `...`); Choose… calls `bridge::apply_workdir`. History uses `bridge::history_list`, `resume` and `history_get`; Save Tcl… writes `executor::ledger`. The mono font is the first available of SF Mono, Menlo and DejaVu Sans Mono. Its two timers (Thinking dots, runs count) go through `sched`. The file stays ASCII.
- Produces (`tests/helpers/tk.py`): `tk_skip_reason() -> Optional[str]`, `tk_prelude() -> str`, `run_tk_test(test_file, *, env=None, timeout=120) -> TclTestResult`, `update_goldens() -> bool` (true only when `CHATVMD_UPDATE_GOLDENS=1`), `golden_path(name) -> Path` (`tests/fixtures/tk/<name>.txt`). The prelude sets `::tk_library` to VMD.app's `Tk.framework/Versions/8.6/Resources/Scripts`, loads that framework's `Tk` binary and ends with `wm withdraw .`; `VMD_AI_TK_LIB` (from `live_env`'s snapshot, `helpers.live.LIVE_ENV`) names another Tk shared library to load instead. The skip probe is a subprocess that must load Tk and exit within 10 s. `run_tk_test` exports `VMDAI_REPO`, `VMDAI_PLUGIN_DIR` and a temp `HOME` like `run_tcltest`.

- [ ] **Step 1: Create the Tk helper**

Create `tests/helpers/tk.py`:

```python
"""Tk tests under tclsh 8.6 with VMD.app's Tk (spec §6 "Tk golden transcripts").

The prelude loads Tk the way docs/design/round1/tools/vmdtk_run.tcl does:
``set ::tk_library …/Tk.framework/Versions/8.6/Resources/Scripts`` and then
``load …/Tk.framework/Versions/8.6/Tk Tk``. ``VMD_AI_TK_LIB`` (from the
live_env snapshot) names another Tk shared library to load instead; Tk then
finds its own script library. Aqua has no DISPLAY, so whether Tk works is
decided by a probe subprocess that must load Tk and exit within 10 s; without
a GUI login session (ssh, launchd, CI) it fails and every Tk test skips.
Tests take no screenshots. Goldens live in tests/fixtures/tk/<name>.txt and
are rewritten only when CHATVMD_UPDATE_GOLDENS=1.
"""
from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, Optional

import pytest

from helpers.live import LIVE_ENV
from helpers.tcl import REPO, TclTestResult, find_tclsh, run_tcltest, tcl_skip_reason, tcl_word

VMD_TK_FRAMEWORK = "/Applications/VMD.app/Contents/Frameworks/Tk.framework/Versions/8.6"
GOLDEN_DIR = REPO / "tests" / "fixtures" / "tk"
PROBE_TIMEOUT_S = 10


def tk_prelude() -> str:
    """Tcl that loads Tk into a plain tclsh and hides the root window."""
    override = LIVE_ENV.get("VMD_AI_TK_LIB")
    if override:
        lines = [f"load {tcl_word(override)} Tk"]
    else:
        lines = [
            f"set ::tk_library {tcl_word(VMD_TK_FRAMEWORK + '/Resources/Scripts')}",
            f"load {tcl_word(VMD_TK_FRAMEWORK + '/Tk')} Tk",
        ]
    lines.append("wm withdraw .")
    return "".join(line + "\n" for line in lines)


@functools.lru_cache(maxsize=None)
def tk_skip_reason() -> Optional[str]:
    """Why Tk tests can't run here, or None when they can."""
    reason = tcl_skip_reason()
    if reason is not None:
        return reason
    library = LIVE_ENV.get("VMD_AI_TK_LIB") or VMD_TK_FRAMEWORK + "/Tk"
    if not Path(library).exists():
        return f"no Tk library at {library}: install VMD.app or set VMD_AI_TK_LIB"
    with tempfile.TemporaryDirectory(prefix="vmdai_tk_") as tmp:
        probe = os.path.join(tmp, "probe.tcl")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(tk_prelude() + "exit 0\n")
        try:
            proc = subprocess.run([find_tclsh(), probe], capture_output=True, text=True,
                                  timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return f"Tk did not load within {PROBE_TIMEOUT_S} s (no GUI session?)"
    if proc.returncode != 0:
        return f"Tk could not be loaded (no GUI session?): {proc.stderr.strip()[-200:]}"
    return None


def run_tk_test(test_file: str, *, env: Optional[Dict[str, str]] = None,
                timeout: int = 120) -> TclTestResult:
    """run_tcltest with Tk loaded first; skips when Tk is unavailable."""
    reason = tk_skip_reason()
    if reason is not None:
        pytest.skip(reason)
    return run_tcltest(test_file, env=env, timeout=timeout, prelude=tk_prelude())


def update_goldens() -> bool:
    return os.environ.get("CHATVMD_UPDATE_GOLDENS") == "1"


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.txt"
```

Check it on the dev Mac (logged in to the GUI):

```bash
python -c "import sys; sys.path[:0] = ['tests']; from helpers.tk import tk_skip_reason; print(tk_skip_reason())"
```

Expected: `None` (over ssh or without a GUI session it prints the reason, and the Tk tests will skip).

- [ ] **Step 2: Write the failing tests**

Create `tests/tcl/test_ui_min.tcl`:

```tcl
# tests/tcl/test_ui_min.tcl - the M1 ui.tcl fixes (P06-T10). Runs under Tk
# (helpers.tk prelude). net::call is faked and records every call; the
# runtime is reported ready and the bridge has a session.
package require tcltest 2
namespace import -force ::tcltest::*
::tcltest::configure -verbose {pass body error}

set plugin $::env(VMDAI_PLUGIN_DIR)
foreach m {config sched net runtime bridge executor ui} { source [file join $plugin $m.tcl] }

set ::calls {}
proc ::vmdai::net::call {method params callback args} {
    lappend ::calls [list $method $params]
    set result {}
    if {$method eq "chat.send"} { set result {request_id req_1} }
    ::vmdai::sched::after 0 [list ::vmdai::net::_deliver_if_current \
        [::vmdai::net::epoch] $callback ok $result]
    return rpc#fake
}
proc ::vmdai::runtime::state {} { return ready }
proc settle {{ms 30}} {
    set ::_settled 0
    after $ms {set ::_settled 1}
    vwait ::_settled
}
proc param {params name} {
    foreach {n t v} $params { if {$n eq $name} { return $v } }
    return "<none>"
}
proc lines {} {
    set t $::vmdai::ui::transcript
    return [split [string trimright [$t get 1.0 end] "\n"] "\n"]
}
proc fresh {} {
    catch {destroy $::vmdai::ui::win}
    set ::vmdai::ui::stream_role ""
    set ::vmdai::ui::stream_request_id ""
    set ::vmdai::bridge::session_id sess_1
    set ::vmdai::bridge::busy 0
    set ::vmdai::bridge::request_id ""
    set ::calls {}
    ::vmdai::ui::show_panel
    ::vmdai::ui::_clear_transcript
}
proc ev {role type text {rid req_1}} {
    return [dict create seq 1 role $role type $type text $text metadata [dict create request_id $rid]]
}

test ui-block-1 {a block closes on every role change: no glued lines} -setup fresh -body {
    foreach e [list [ev assistant chunk "Loading "] [ev assistant chunk "the file."] \
            [ev tool_result message "ok: 1 molecule"] [ev assistant chunk "Done"] \
            [ev reasoning chunk "thinking"] [ev assistant message "Done" req_1]] {
        ::vmdai::ui::render_event $e
    }
    ::vmdai::ui::notify warn "Lost the connection to the AI runtime; reconnecting."
    lines
} -result {{ASSISTANT: Loading the file.} {TOOL_RESULT: ok: 1 molecule} {ASSISTANT: Done} {REASONING: thinking} {Lost the connection to the AI runtime; reconnecting.}}

test ui-notify-1 {notify adds exactly one line, even for multi-line text} -setup fresh -body {
    set before [llength [lines]]
    ::vmdai::ui::notify error "The AI runtime didn't start:\nTraceback (most recent call last)"
    ::vmdai::ui::notify bogus "Reconnected to the AI runtime."
    set t $::vmdai::ui::transcript
    list [expr {[llength [lines]] - $before}] [lindex [lines] end-1] \
        [lsearch -inline [$t tag names end-2c] notice_*]
} -result {2 {The AI runtime didn't start: Traceback (most recent call last)} notice_info}

test ui-folder-1 {the folder label shows the folder the bridge applied} -setup fresh -body {
    set dir [file join $::env(HOME) "a project folder"]
    file mkdir $dir
    proc ::tk_chooseDirectory {args} [list return $dir]
    ::vmdai::ui::on_choose_folder
    set shown [$::vmdai::ui::workdir_label cget -text]
    set deep [file join $::env(HOME) [string repeat d 40] [string repeat e 40]]
    file mkdir $deep
    proc ::tk_chooseDirectory {args} [list return $deep]
    ::vmdai::ui::on_choose_folder
    set long [$::vmdai::ui::workdir_label cget -text]
    list [string match "*a project folder" $shown] [string range $long 0 2] \
        [string length $long] [string match *[string repeat e 40] $long] \
        [expr {[pwd] eq [file normalize $deep]}] [llength [lsearch -all -index 0 $::calls session.set_cwd]]
} -cleanup { rename ::tk_chooseDirectory {} } -result {1 ... 59 1 1 2}

test ui-dropdown-1 {the dropdown never feeds chat.send; Apply sends provider.set without a profile} -setup fresh -body {
    set ::vmdai::ui::provider ollama
    set picked $::vmdai::ui::model_name
    $::vmdai::ui::input insert 0 "color it red"
    ::vmdai::ui::on_send
    settle
    set send [lindex [lsearch -inline -index 0 $::calls chat.send] 1]
    ::vmdai::ui::on_apply_provider
    settle
    set apply [lindex [lsearch -inline -index 0 $::calls provider.set] 1]
    list $picked [param $send text] [param $send model] $apply [lindex [lines] 0]
} -result {llama3.1:8b {color it red} <none> {provider s ollama model s llama3.1:8b} {USER: color it red}}

test ui-busy-1 {Stop is enabled and Thinking shows only while the bridge says busy} -setup fresh -body {
    set w $::vmdai::ui::win
    set idle [list [$w.header.stop cget -state] [$w.input_row.send cget -state]]
    ::vmdai::ui::set_busy 1
    set busy [list [$w.header.stop cget -state] [$w.input_row.send cget -state] [lindex [lines] end]]
    ::vmdai::ui::set_busy 0
    set ticking 0
    foreach id [::vmdai::sched::pending] {
        if {[string match *_thinking_tick* [lindex $::vmdai::sched::timers($id) 1]]} { incr ticking }
    }
    list $idle $busy [lines] $ticking
} -result {{disabled normal} {normal disabled Thinking} {} 0}

test ui-close-1 {closing withdraws the window; show_panel brings the same one back} -setup fresh -body {
    ::vmdai::ui::on_close
    set hidden [list [winfo exists $::vmdai::ui::win] [wm state $::vmdai::ui::win]]
    set again [::vmdai::ui::show_panel]
    list $hidden $again [wm state $::vmdai::ui::win]
} -result {{1 withdrawn} .vmd_ai normal}

cleanupTests
```

Create `tests/test_tk_ui_min.py`:

```python
"""The M1 ui.tcl fixes under Tk (P06-T10; spec §2h "Stage M1 keeps ui.tcl")."""
from __future__ import annotations

import re
from typing import List

import pytest

from helpers import tk
from helpers.tcl import REPO, TclTestResult

TCL_FILE = REPO / "tests" / "tcl" / "test_ui_min.tcl"
TOTAL = 6


@pytest.fixture(scope="module")
def result() -> TclTestResult:
    return tk.run_tk_test(str(TCL_FILE))


def _assert_passed(result: TclTestResult, names: List[str]) -> None:
    missing = [n for n in names
               if not re.search(rf"^\+\+\+\+ {re.escape(n)} PASSED$", result.output, re.MULTILINE)]
    assert missing == [], f"did not pass: {missing}\n{result.output}"


def test_tk_helper_contract(monkeypatch):
    assert tk.golden_path("x") == REPO / "tests" / "fixtures" / "tk" / "x.txt"
    assert "load " in tk.tk_prelude() and " Tk\n" in tk.tk_prelude()
    assert tk.tk_prelude().endswith("wm withdraw .\n")
    monkeypatch.setenv("CHATVMD_UPDATE_GOLDENS", "1")
    assert tk.update_goldens() is True
    monkeypatch.delenv("CHATVMD_UPDATE_GOLDENS")
    assert tk.update_goldens() is False


def test_counts(result):
    assert (result.passed, result.failed) == (TOTAL, 0), result.output


def test_role_change_closes_block(result):
    _assert_passed(result, ["ui-block-1"])


def test_folder_label_shows_dir(result):
    _assert_passed(result, ["ui-folder-1"])


def test_dropdown_does_not_feed_send_model(result):
    _assert_passed(result, ["ui-dropdown-1"])


def test_notify_one_line(result):
    _assert_passed(result, ["ui-notify-1", "ui-busy-1", "ui-close-1"])
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_tk_ui_min.py -q`
Expected: `5 failed, 1 passed` (the helper contract passes); every Tk case fails in its setup with `invalid command name "::vmdai::bridge::ensure_runtime"`, which today's `show_panel` still calls.

- [ ] **Step 4: Replace `plugin/ui.tcl`**

```tcl
# ui.tcl - the M1 panel (spec 2h "Stage M1 keeps the existing ui.tcl"). It
# talks only to ::vmdai::bridge, and the bridge, runtime and executor reach
# it only through notify, render_event, set_busy and status. Without Tk (a
# tclsh driver) or without an open window those four do nothing. Plan 09
# replaces this file with a shim over the M2 panel.

namespace eval ::vmdai::ui {
    variable win ".vmd_ai"
    # Widget paths and stream/indicator state; kept when reload re-sources.
    foreach {name value} {
        transcript "" input "" stream_request_id "" stream_role ""
        thinking_after_id "" thinking_tag "" thinking_dots 0
        workdir_label "" runs_label "" runs_count_after_id ""
    } {
        variable $name
        if {![info exists $name]} { set $name $value }
    }
    unset name value
    # Provider picker state. Apply sends provider.set {provider, model};
    # chat.send never carries the model (a token session runs its profile).
    variable provider
    if {![info exists provider]} { set provider "openrouter" }
    variable model_name
    if {![info exists model_name]} { set model_name "anthropic/claude-sonnet-4.6" }
}

# Sensible default model strings per provider, for the model entry only.
proc ::vmdai::ui::_default_model_for_provider {prov} {
    switch -- $prov {
        "openrouter"       { return "anthropic/claude-sonnet-4.6" }
        "anthropic-direct" { return "claude-sonnet-4-5" }
        "ollama"           { return "llama3.1:8b" }
        default            { return "anthropic/claude-sonnet-4.6" }
    }
}

proc ::vmdai::ui::_dict_get_or {d key default} {
    if {[dict exists $d $key]} {
        return [dict get $d $key]
    }
    return $default
}

# True when Tk is loaded and the panel window exists.
proc ::vmdai::ui::_have_panel {} {
    variable win
    return [expr {[llength [info commands ::winfo]] && [winfo exists $win]}]
}

# First available of SF Mono, Menlo and DejaVu Sans Mono (never a fixed Menlo).
proc ::vmdai::ui::_mono {} {
    set families [font families]
    foreach family {"SF Mono" Menlo "DejaVu Sans Mono"} {
        if {[lsearch -exact $families $family] >= 0} {
            return $family
        }
    }
    return [font actual TkFixedFont -family]
}

# Build the panel (or show it again) and return its window path.
proc ::vmdai::ui::show_panel {} {
    variable win
    variable transcript
    variable input
    variable workdir_label
    variable runs_label

    if {[winfo exists $win]} {
        wm deiconify $win
        raise $win
        focus $input
        return $win
    }
    set mono [_mono]

    toplevel $win
    wm title $win "VMD AI"
    wm geometry $win "540x640"

    frame $win.header
    pack $win.header -side top -fill x -padx 8 -pady 8

    button $win.header.history -text "History" -command {::vmdai::ui::on_history}
    button $win.header.new -text "New Chat" -command {::vmdai::ui::on_new_chat}
    button $win.header.clear -text "Clear" -command {::vmdai::ui::on_clear}
    button $win.header.stop -text "Stop" -command {::vmdai::ui::on_stop} -state disabled

    pack $win.header.history -side left -padx 4
    pack $win.header.new -side left -padx 4
    pack $win.header.stop -side right -padx 4
    pack $win.header.clear -side right -padx 4

    # ----- Workdir row -----
    frame $win.folder_row
    pack $win.folder_row -side top -fill x -padx 8 -pady {0 6}

    label $win.folder_row.fixed -text "Folder:" -font [list $mono 11 bold]
    label $win.folder_row.path -text "(none)" -font [list $mono 11] \
        -foreground "#0055aa" -anchor w
    label $win.folder_row.runs -text "" -font [list $mono 10] \
        -foreground "#777777"
    button $win.folder_row.choose -text "Choose..." \
        -command {::vmdai::ui::on_choose_folder}
    button $win.folder_row.runs_btn -text "Runs..." \
        -command {::vmdai::ui::on_reveal_runs}
    button $win.folder_row.save -text "Save Tcl..." \
        -command {::vmdai::ui::on_save_tcl}

    pack $win.folder_row.fixed -side left -padx {0 4}
    pack $win.folder_row.path -side left -fill x -expand 1
    pack $win.folder_row.runs -side left -padx {6 0}
    pack $win.folder_row.save -side right -padx 4
    pack $win.folder_row.runs_btn -side right -padx 4
    pack $win.folder_row.choose -side right -padx 4

    set workdir_label $win.folder_row.path
    set runs_label $win.folder_row.runs
    # The bridge applies the remembered folder when the session starts.
    if {$::vmdai::bridge::workdir eq ""} {
        ::vmdai::bridge::_load_workdir
    }
    _refresh_workdir_label
    _refresh_runs_count
    _schedule_runs_count_refresh

    # ----- Provider row -----
    _load_persisted_provider

    frame $win.provider_row
    pack $win.provider_row -side top -fill x -padx 8 -pady {0 6}

    label $win.provider_row.fixed -text "Provider:" -font [list $mono 11 bold]
    tk_optionMenu $win.provider_row.menu ::vmdai::ui::provider \
        openrouter anthropic-direct ollama
    label $win.provider_row.model_label -text "Model:" -font [list $mono 11 bold]
    entry $win.provider_row.model_entry -width 28 \
        -textvariable ::vmdai::ui::model_name
    button $win.provider_row.apply -text "Apply" \
        -command {::vmdai::ui::on_apply_provider}

    pack $win.provider_row.fixed -side left -padx {0 4}
    pack $win.provider_row.menu  -side left -padx {0 8}
    pack $win.provider_row.model_label -side left -padx {0 4}
    pack $win.provider_row.model_entry -side left -fill x -expand 1 -padx {0 4}
    pack $win.provider_row.apply -side right -padx 4

    # The dropdown only refills the model entry; nothing reaches chat.send
    # until Apply. Remove any prior trace first (reload re-sources this file).
    catch {trace remove variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed}
    trace add variable ::vmdai::ui::provider write \
        ::vmdai::ui::_on_provider_changed

    text $win.transcript -height 28 -wrap word -state disabled \
        -font [list $mono 12 bold] -background "#ffffff"
    set transcript $win.transcript
    pack $win.transcript -side top -fill both -expand 1 -padx 8 -pady 8

    $win.transcript tag configure role_user -foreground "#0055aa"
    $win.transcript tag configure role_assistant -foreground "#1a1a1a"
    $win.transcript tag configure role_system -foreground "#555555"
    $win.transcript tag configure role_error -foreground "#cc2233"
    $win.transcript tag configure role_tool_result -foreground "#0077aa"
    $win.transcript tag configure role_reasoning -foreground "#666666"
    $win.transcript tag configure notice_info -foreground "#555555"
    $win.transcript tag configure notice_warn -foreground "#a05a00"
    $win.transcript tag configure notice_error -foreground "#cc2233"
    $win.transcript tag configure thinking -foreground "#888888" \
        -font [list $mono 11 italic]

    frame $win.input_row
    pack $win.input_row -side bottom -fill x -padx 8 -pady 8

    entry $win.input_row.input
    set input $win.input_row.input
    button $win.input_row.send -text "Send" -command {::vmdai::ui::on_send}

    pack $win.input_row.input -side left -fill x -expand 1 -padx 4
    pack $win.input_row.send -side right -padx 4

    bind $win.input_row.input <Return> {::vmdai::ui::on_send}
    wm protocol $win WM_DELETE_WINDOW {::vmdai::ui::on_close}

    append_message system "VMD AI panel ready."
    focus $input
    return $win
}

# ----------------------------------------------------------------------
# Provider picker - persistence + dropdown handlers
# ----------------------------------------------------------------------

proc ::vmdai::ui::_persisted_provider_path {} {
    return [file join [::vmdai::config::home] .vmdai last_provider.txt]
}

proc ::vmdai::ui::_load_persisted_provider {} {
    variable provider
    variable model_name
    set path [_persisted_provider_path]
    if {![file readable $path]} { return }
    if {[catch {set fh [open $path r]}]} { return }
    set line [string trim [read $fh]]
    catch {close $fh}
    if {$line eq ""} { return }
    set parts [split $line "\t"]
    set prov [lindex $parts 0]
    set mdl  [lindex $parts 1]
    if {$prov ne ""} { set provider $prov }
    if {$mdl  ne ""} { set model_name $mdl }
}

proc ::vmdai::ui::_save_persisted_provider {prov mdl} {
    set path [_persisted_provider_path]
    catch {file mkdir [file dirname $path]}
    if {[catch {
        set fh [open $path w]
        puts -nonewline $fh "$prov\t$mdl"
        close $fh
    } err]} {
        append_message error "could not persist provider: $err"
    }
}

# Trace on the dropdown: refill the model entry for the new provider.
proc ::vmdai::ui::_on_provider_changed {args} {
    variable provider
    variable model_name
    set model_name [_default_model_for_provider $provider]
}

proc ::vmdai::ui::on_apply_provider {} {
    variable provider
    variable model_name
    set mdl [string trim $model_name]
    if {$mdl eq ""} {
        set mdl [_default_model_for_provider $provider]
        set model_name $mdl
    }
    _save_persisted_provider $provider $mdl
    ::vmdai::bridge::set_provider $provider $mdl \
        [list ::vmdai::ui::_on_provider_set $provider $mdl]
}

proc ::vmdai::ui::_on_provider_set {provider mdl kind args} {
    if {$kind eq "ok"} {
        append_message system "Provider set: $provider (model: $mdl)"
    } elseif {$kind eq "rpc_error"} {
        notify error "Could not set the provider: [lindex $args 1]"
    } else {
        notify error "Could not set the provider: the AI runtime did not answer."
    }
}

# Closing the window only hides it; the runtime and any request keep going
# (spec 2d Shutdown). ::vmdai::stop ends them.
proc ::vmdai::ui::on_close {} {
    variable win
    catch {wm withdraw $win}
}

# ----------------------------------------------------------------------
# Transcript
# ----------------------------------------------------------------------

proc ::vmdai::ui::_insert {text tags} {
    variable transcript
    $transcript configure -state normal
    $transcript insert end $text $tags
    $transcript configure -state disabled
    $transcript see end
}

# End the open streamed block, so the next role starts on its own line.
proc ::vmdai::ui::_close_block {} {
    variable stream_request_id
    variable stream_role
    if {$stream_role eq ""} {
        return
    }
    _insert "\n" {}
    set stream_request_id ""
    set stream_role ""
}

proc ::vmdai::ui::append_message {role text} {
    variable transcript
    if {![_have_panel]} {
        return
    }
    set clean [string trim [string map [list "\r" ""] $text]]
    if {$clean eq ""} {
        return
    }
    _close_block
    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_system"
    }
    _insert "[string toupper $role]: $clean\n" $tag
}

proc ::vmdai::ui::append_stream_chunk {role request_id chunk} {
    variable transcript
    variable stream_request_id
    variable stream_role
    if {![_have_panel]} {
        return
    }
    set tag "role_${role}"
    if {[lsearch -exact [$transcript tag names] $tag] < 0} {
        set tag "role_assistant"
    }
    if {$stream_request_id ne $request_id || $stream_role ne $role} {
        _thinking_stop
        _close_block
        set stream_request_id $request_id
        set stream_role $role
        _insert "[string toupper $role]: " $tag
    }
    _insert $chunk $tag
}

proc ::vmdai::ui::close_stream {request_id} {
    variable stream_request_id
    if {$request_id ne "" && $stream_request_id eq $request_id} {
        _close_block
    }
}

# The connection state machine's sink (S3): one line per call.
proc ::vmdai::ui::notify {level text} {
    if {![_have_panel]} {
        return
    }
    _close_block
    set text [string trim [string map [list "\r" "" "\n" " "] $text]]
    if {$level ni {info warn error}} {
        set level info
    }
    _insert "$text\n" [list notice_$level]
}

# Busy is set by the bridge once chat.send succeeded, and cleared when the
# request ends: Stop is enabled and "Thinking" shows only in between.
proc ::vmdai::ui::set_busy {on} {
    variable win
    if {![_have_panel]} {
        return
    }
    if {$on} {
        $win.header.stop configure -state normal
        $win.input_row.send configure -state disabled
        _thinking_start
    } else {
        $win.header.stop configure -state disabled
        $win.input_row.send configure -state normal
        _thinking_stop
    }
}

# A short progress line (e.g. "Running: mol new ...").
proc ::vmdai::ui::status {text} {
    append_message system $text
}

# ----------------------------------------------------------------------
# Thinking indicator ("Thinking" plus animated dots while busy)
# ----------------------------------------------------------------------

proc ::vmdai::ui::_thinking_start {} {
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    if {![_have_panel]} {
        return
    }
    _thinking_stop
    _close_block
    set thinking_tag "thinking_[clock microseconds]"
    set thinking_dots 0
    _insert "Thinking\n" [list thinking $thinking_tag]
    set thinking_after_id [::vmdai::sched::after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_tick {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    variable thinking_dots
    set thinking_after_id ""
    if {$thinking_tag eq "" || ![_have_panel]} {
        return
    }
    set thinking_dots [expr {($thinking_dots + 1) % 4}]
    set ranges [$transcript tag ranges $thinking_tag]
    if {[llength $ranges] >= 2} {
        $transcript configure -state normal
        $transcript delete [lindex $ranges 0] [lindex $ranges 1]
        $transcript insert [lindex $ranges 0] "Thinking[string repeat . $thinking_dots]\n" \
            [list thinking $thinking_tag]
        $transcript configure -state disabled
    }
    set thinking_after_id [::vmdai::sched::after 400 ::vmdai::ui::_thinking_tick]
}

proc ::vmdai::ui::_thinking_stop {} {
    variable transcript
    variable thinking_after_id
    variable thinking_tag
    ::vmdai::sched::cancel $thinking_after_id
    set thinking_after_id ""
    catch {
        if {$thinking_tag ne "" && [_have_panel]} {
            set ranges [$transcript tag ranges $thinking_tag]
            if {[llength $ranges] >= 2} {
                $transcript configure -state normal
                $transcript delete [lindex $ranges 0] [lindex $ranges 1]
                $transcript configure -state disabled
            }
        }
    }
    set thinking_tag ""
}

# ----------------------------------------------------------------------
# Workdir (project folder). ::vmdai::bridge::apply_workdir cds VMD there,
# remembers it in ~/.vmdai/last_workdir.txt and sends session.set_cwd.
# ----------------------------------------------------------------------

proc ::vmdai::ui::_workdir {} {
    if {$::vmdai::bridge::workdir ne ""} {
        return $::vmdai::bridge::workdir
    }
    return [pwd]
}

proc ::vmdai::ui::_truncate_path {path max_len} {
    if {[string length $path] <= $max_len} { return $path }
    set tail [string range $path [expr {[string length $path] - $max_len + 4}] end]
    return "...$tail"
}

proc ::vmdai::ui::_refresh_workdir_label {} {
    variable workdir_label
    if {$workdir_label eq "" || ![winfo exists $workdir_label]} {
        return
    }
    $workdir_label configure -text [_truncate_path [_workdir] 60]
}

proc ::vmdai::ui::on_choose_folder {} {
    set initial [_workdir]
    if {![file isdirectory $initial]} {
        set initial [pwd]
    }
    set chosen [tk_chooseDirectory -title "VMD AI - pick project folder" \
        -initialdir $initial -mustexist 1]
    if {$chosen eq ""} { return }
    if {![::vmdai::bridge::apply_workdir $chosen]} {
        return
    }
    _refresh_workdir_label
    _refresh_runs_count
    append_message system "Project folder set: $::vmdai::bridge::workdir"
}

# ----------------------------------------------------------------------
# Recorder dir surface - show run count + open in Finder
# ----------------------------------------------------------------------

proc ::vmdai::ui::_runs_dir {} {
    return [file join [_workdir] ".vmdai_runs"]
}

proc ::vmdai::ui::_refresh_runs_count {} {
    variable runs_label
    if {$runs_label eq "" || ![winfo exists $runs_label]} { return }
    set dir [_runs_dir]
    set count 0
    if {[file isdirectory $dir]} {
        catch {set count [llength [glob -nocomplain -directory $dir -type d *]]}
    }
    if {$count == 0} {
        $runs_label configure -text ""
    } elseif {$count == 1} {
        $runs_label configure -text "(1 run)"
    } else {
        $runs_label configure -text "($count runs)"
    }
}

proc ::vmdai::ui::_schedule_runs_count_refresh {} {
    variable runs_count_after_id
    ::vmdai::sched::cancel $runs_count_after_id
    set runs_count_after_id [::vmdai::sched::after 3000 ::vmdai::ui::_runs_count_tick]
}

proc ::vmdai::ui::_runs_count_tick {} {
    variable runs_count_after_id
    set runs_count_after_id ""
    if {![_have_panel]} {
        return
    }
    _refresh_runs_count
    _schedule_runs_count_refresh
}

proc ::vmdai::ui::on_reveal_runs {} {
    set dir [_runs_dir]
    if {![file isdirectory $dir]} {
        append_message system "No runs yet - $dir will be created on the first request."
        return
    }
    set platform [tk windowingsystem]
    if {$platform eq "aqua"} {
        catch {exec open $dir &}
    } elseif {$platform eq "x11"} {
        catch {exec xdg-open $dir &}
    } else {
        append_message system "Runs directory: $dir"
    }
}

# ----------------------------------------------------------------------
# Save Tcl: the commands the executor ran in this chat (its ledger).
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_save_tcl {} {
    set entries [::vmdai::executor::ledger]
    if {[llength $entries] == 0} {
        append_message system "Nothing to save yet - no VMD commands have run in this chat."
        return
    }
    set initial [_workdir]
    set default_name "vmd_ai_session_[clock format [clock seconds] -format %Y%m%dT%H%M%S].tcl"
    set chosen [tk_getSaveFile -title "Save VMD AI session as Tcl script" \
        -initialdir $initial -initialfile $default_name \
        -defaultextension .tcl -filetypes {{Tcl {.tcl}} {All *}}]
    if {$chosen eq ""} { return }
    if {[catch {
        set fh [open $chosen w]
        fconfigure $fh -encoding utf-8
        puts -nonewline $fh [_render_session_tcl $entries]
        close $fh
    } err]} {
        append_message error "save failed: $err"
        return
    }
    append_message system "Saved [llength $entries] commands to $chosen"
}

proc ::vmdai::ui::_render_session_tcl {entries} {
    set saved_at [clock format [clock seconds] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
    set out ""
    append out "# VMD AI session transcript\n"
    append out "# saved_at : $saved_at\n"
    append out "# workdir  : [_workdir]\n"
    append out "# turns    : [llength $entries]\n\n"
    set turn 0
    foreach entry $entries {
        incr turn
        set ts [clock format [dict get $entry ts] -format "%Y-%m-%dT%H:%M:%SZ" -gmt 1]
        append out "# --- turn [format %02d $turn] | $ts | [dict get $entry kind] ---\n"
        append out [string trimright [dict get $entry command]] "\n\n"
    }
    return $out
}

# ----------------------------------------------------------------------
# Events from the bridge (v1, spec 2c)
# ----------------------------------------------------------------------

proc ::vmdai::ui::render_event {event} {
    if {![_have_panel]} {
        return
    }
    if {[catch {_render_event_impl $event} err]} {
        catch {_thinking_stop}
        catch {append_message error "render_event: $err"}
    }
}

proc ::vmdai::ui::_render_event_impl {event} {
    set role [_dict_get_or $event role system]
    set etype [_dict_get_or $event type message]
    set text [_dict_get_or $event text ""]
    set metadata [_dict_get_or $event metadata [dict create]]
    set request_id [_dict_get_or $metadata request_id ""]
    if {$role eq "user"} {
        # Already shown by on_send.
        return
    }
    if {$etype eq "chunk"} {
        append_stream_chunk $role $request_id $text
        return
    }
    _thinking_stop
    if {$role eq "assistant" && $etype eq "message" && $request_id ne ""} {
        # The final message repeats the streamed text; just end the block.
        close_stream $request_id
        return
    }
    if {$etype eq "lifecycle"} {
        close_stream $request_id
        if {$text eq "cancelled"} {
            append_message system "Stopped."
        }
        return
    }
    append_message $role $text
}

# ----------------------------------------------------------------------
# Buttons
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_send {} {
    variable input
    if {$input eq "" || ![winfo exists $input]} {
        return
    }
    set text [string trim [$input get]]
    if {$text eq ""} {
        return
    }
    if {[::vmdai::bridge::send $text]} {
        $input delete 0 end
        append_message user $text
    }
}

proc ::vmdai::ui::on_stop {} {
    ::vmdai::bridge::cancel
}

proc ::vmdai::ui::_clear_transcript {} {
    variable transcript
    if {![_have_panel]} {
        return
    }
    _thinking_stop
    set ::vmdai::ui::stream_request_id ""
    set ::vmdai::ui::stream_role ""
    $transcript configure -state normal
    $transcript delete 1.0 end
    $transcript configure -state disabled
}

proc ::vmdai::ui::on_clear {} {
    _clear_transcript
    ::vmdai::executor::clear_ledger
    ::vmdai::bridge::new_chat
}

proc ::vmdai::ui::on_new_chat {} {
    ::vmdai::executor::clear_ledger
    ::vmdai::bridge::new_chat
    append_message system "Started a new chat."
}

# ----------------------------------------------------------------------
# History
# ----------------------------------------------------------------------

proc ::vmdai::ui::on_history {} {
    ::vmdai::bridge::history_list ::vmdai::ui::_on_history_list
}

proc ::vmdai::ui::_on_history_list {kind args} {
    if {$kind ne "ok"} {
        notify error "Could not load the chat history."
        return
    }
    set items {}
    catch {set items [dict get [lindex $args 0] items]}
    show_history_picker $items
}

proc ::vmdai::ui::show_history_picker {items} {
    variable win
    set dlg "${win}.history_dlg"
    catch {destroy $dlg}

    toplevel $dlg
    wm title $dlg "Chat History"
    wm geometry $dlg "420x360"
    wm transient $dlg $win

    label $dlg.label -text "Select a conversation to resume:" -anchor w
    pack $dlg.label -side top -fill x -padx 10 -pady {10 4}

    frame $dlg.list_frame
    pack $dlg.list_frame -side top -fill both -expand 1 -padx 10 -pady 4

    listbox $dlg.list_frame.lb -font [list [_mono] 11] -selectmode single \
        -activestyle dotbox -height 12 -width 50 \
        -yscrollcommand [list $dlg.list_frame.sb set]
    scrollbar $dlg.list_frame.sb -command [list $dlg.list_frame.lb yview]
    pack $dlg.list_frame.sb -side right -fill y
    pack $dlg.list_frame.lb -side left -fill both -expand 1

    set chat_ids [list]
    if {[llength $items] == 0} {
        $dlg.list_frame.lb insert end "(no previous chats)"
    } else {
        foreach item $items {
            set cid [_dict_get_or $item chat_id ""]
            set title [_dict_get_or $item title "Untitled"]
            set mc [_dict_get_or $item message_count 0]
            set updated [_dict_get_or $item updated_at ""]
            $dlg.list_frame.lb insert end "$title  ($mc msgs)  [string range $updated 0 9]"
            lappend chat_ids $cid
        }
    }

    frame $dlg.buttons
    pack $dlg.buttons -side bottom -fill x -padx 10 -pady 10
    button $dlg.buttons.resume -text "Resume" \
        -command [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
    button $dlg.buttons.cancel -text "Cancel" -command [list destroy $dlg]
    pack $dlg.buttons.cancel -side right -padx 4
    pack $dlg.buttons.resume -side right -padx 4
    bind $dlg.list_frame.lb <Double-1> [list ::vmdai::ui::_on_history_resume $dlg $chat_ids]
}

proc ::vmdai::ui::_on_history_resume {dlg chat_ids} {
    set sel [$dlg.list_frame.lb curselection]
    if {[llength $sel] == 0} {
        return
    }
    set target [lindex $chat_ids [lindex $sel 0]]
    if {$target eq ""} {
        return
    }
    destroy $dlg
    ::vmdai::bridge::resume $target [list ::vmdai::ui::_on_resumed $target]
}

# chat.resume answered; the bridge already reported a failure.
proc ::vmdai::ui::_on_resumed {target kind args} {
    if {$kind ne "ok"} {
        return
    }
    _clear_transcript
    ::vmdai::executor::clear_ledger
    append_message system "Resumed chat."
    ::vmdai::bridge::history_get $target ::vmdai::ui::_on_history_get
}

proc ::vmdai::ui::_on_history_get {kind args} {
    if {$kind ne "ok"} {
        notify error "Could not load this chat's messages."
        return
    }
    set events {}
    catch {set events [dict get [lindex $args 0] events]}
    foreach ev $events {
        set role [_dict_get_or $ev role ""]
        set etype [_dict_get_or $ev type ""]
        set text [_dict_get_or $ev text ""]
        if {($role eq "user" || $role eq "assistant") && $etype eq "message" && $text ne ""} {
            append_message $role $text
        }
    }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_ui_min.py tests/test_tcl_install.py tests/test_tcl_lint.py -q`
Expected: `17 passed` (6 ui, 8 install, 3 lint). Then confirm the plugin files stay ASCII and use no bare timers:

```bash
LC_ALL=C grep -n '[^ -~]' plugin/*.tcl
grep -n '^\s*after \|\[after [0-9]\|after cancel' plugin/ui.tcl plugin/bridge.tcl plugin/executor.tcl plugin/init.tcl
```

Expected: no output from either command.

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+70 passed`, `0 failed` on the dev Mac (without a GUI session the five Tk cases skip: `B+65 passed` and five more skipped).

- [ ] **Step 7: Commit**

```bash
git add tests/helpers/tk.py plugin/ui.tcl tests/tcl/test_ui_min.tcl tests/test_tk_ui_min.py
git commit -F - <<'MSG'
feat(plugin): M1 ui.tcl on the new bridge, notify sink and Tk test helper

The M1 panel now talks only to bridge:: and gives the bridge, runtime
and executor four sinks: notify (one line per call, S3), render_event,
set_busy and status. Busy starts only after chat.send succeeded, a
block closes on every role change, and the provider dropdown no longer
feeds chat.send (Apply sends provider.set without a profile). Closing
the window withdraws it; its timers go through sched. helpers/tk.py
loads VMD.app's Tk into tclsh and skips when no GUI session exists.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 11: P06-T11 — Bridge integration against a scripted runtime

**Files:**
- Create: `tests/helpers/scripted_runtime.py`, `tests/tcl/driver.tcl`, `tests/tcl/t_race.tcl`
- Test: `tests/test_bridge_integration.py`

**Interfaces:**
- Consumes: `helpers.runtime_fixture.make_app(tmp_path, **kw) -> RuntimeApp` (P02-T02: chats under `tmp_path/chats`, mock provider, no RAG or wiki); `RuntimeApp(..., launch_token=, allow_tokenless_v1=, loop_factory=)` and the factory contract (P02-T02, P02-T10: the factory is called per `chat.send` and by `has_agent_loop`, so building a loop must not consume the script); `vmd_ai_runtime.server.create_server(app, host, port)`; `launch.generate_launch_token()`, `write_token_file(port, pid, token, protocol=2, home=None)` (P02-T02); `ClaudeToolLoop._call(messages, system_prompt, on_text, should_cancel) -> (text, tool_blocks)` (unchanged, S7) and `constants.DEFAULT_SETTINGS`; `RuntimeApp._cancel_active_request(state)` (today's app) and `RuntimeApp._release_chat_lock(state)` (P03-T04, called when present); the product `VmdToolBridge` with `tool.ack`, results by `call_key` and snapshot files (P05-T01..T03), token `chat.resume` returning `last_seq` (P03-T04), `runtime.info` and `session.set_cwd` (P03-T09); the whole plugin (P06-T02..T10); `helpers.tcl.run_tcl`, `tcl_skip_reason` (P01-T03).
- Produces:
  - `helpers.scripted_runtime.ScriptedLoopFactory(script: List[Tuple[str, List[Dict]]])` — a `loop_factory`; the script's `(text, tool_calls)` model turns (tool calls as `{id, name, input}`) are served in order across requests, then `("Done.", [])`; a turn's text is streamed a word at a time; `.calls` holds a deep copy of the messages of every model call; `.next_turn()`. `ScriptedLoop(factory)` is the `ClaudeToolLoop` it builds (model `DEFAULT_SETTINGS["model"]`).
  - `helpers.scripted_runtime.serve_runtime(home: Path, loop_factory) -> RunningRuntime` with `.port`, `.token`, `.token_file`, `.app`, `.apps` (every app served so far), `.stop()` (closes the port, cancels requests and releases chat locks, as a crash would) and `.restart_same_port()` (a new token-only RuntimeApp on the same port with a new token file, sharing the chat store). The app accepts no tokenless sessions (like `main.py --announce`) and keeps its chats in `home/.vmdai/chats`.
  - `tests/tcl/driver.tcl` — sources `plugin/init.tcl` under tclsh (no Tk), stubs `mol`, `display`, `render` (an 8×6 TGA), `vmdinfo` and the four panel sinks, attaches through `VMD_AI_ATTACH`, runs `VMDAI_SCENARIO` (`round_trip`, `cancel_before_ack`, `cancel_after_ack`, `has_more`, `restart`, `race`) and writes its findings as JSON to `VMDAI_OUT`; marker files in `VMDAI_SYNC` (`ready_for_restart`, `restarted`) coordinate restarts. P09-T09 reuses `serve_runtime` and `ScriptedLoopFactory` with its own Tk driver.
  - `tests/tcl/t_race.tcl` — the New Chat/Resume race scenario, sourced by the driver.

This task adds no product code: it checks P06-T02…T10 together against the real runtime from plans 02–05, so the tests pass as soon as they are written. A failing scenario writes the wait that timed out and the notices into the pytest message; the plugin log is `~/.vmdai/logs/plugin.log` under the scenario's temporary `rt_home`.

- [ ] **Step 1: Create the scripted runtime helper**

Create `tests/helpers/scripted_runtime.py`:

```python
"""A real RuntimeApp with a scripted model, served over HTTP (P06-T11; spec §6).

``ScriptedLoopFactory(script)`` is a ``loop_factory``: the script is a list of
``(text, tool_calls)`` model turns, served in order across requests; each
tool call is a dict with ``id``, ``name`` and ``input`` (the loop adds
``type: tool_use``). A turn's text is streamed a word at a time, as a real
provider streams it, so a long text gives many chunk events. Once the script
is used up every turn answers ``("Done.", [])``. Building a loop consumes
nothing (plan 02's factory contract); turns are taken when the loop runs.
``factory.calls`` holds a deep copy of the messages of every model call, so a
test can check what the model saw (S10).

``serve_runtime(home, loop_factory)`` builds a token-only RuntimeApp (like
``main.py --announce``: no tokenless sessions) with its chats under
``home/.vmdai/chats``, serves it on 127.0.0.1:<ephemeral> and writes the
attach token file ``home/.vmdai/run/runtime-<port>.json``. ``stop()`` takes
it down as a crash would (the port closes; chat locks and requests die with
it). ``restart_same_port()`` then starts a new RuntimeApp on the same port
with a new token and token file, sharing the chat store, like a runtime
restarted by ``scripts/run_runtime.sh``. The pid in ``/health`` stays the
pytest process's, so the plugin notices the restart through AUTH_FAILED.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from helpers.runtime_fixture import make_app
from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.constants import DEFAULT_SETTINGS
from vmd_ai_runtime.launch import generate_launch_token, write_token_file
from vmd_ai_runtime.server import create_server

Turn = Tuple[str, List[Dict[str, Any]]]


class ScriptedLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose model turns come from its factory's script."""

    def __init__(self, factory: "ScriptedLoopFactory") -> None:
        super().__init__(provider_name="anthropic-direct", api_key="sk-test",
                         model=DEFAULT_SETTINGS["model"])
        self._factory = factory

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self._factory.calls.append(copy.deepcopy(messages))
        text, tool_calls = self._factory.next_turn()
        for piece in re.findall(r"\S+\s*", text):
            if should_cancel():
                break
            on_text(piece)
        blocks = [dict(copy.deepcopy(call), type="tool_use") for call in tool_calls]
        return text, blocks


class ScriptedLoopFactory:
    """loop_factory(profile) -> ScriptedLoop, all loops sharing one script."""

    def __init__(self, script: List[Turn]) -> None:
        self.script: List[Turn] = list(script)
        self.calls: List[List[Dict[str, Any]]] = []
        self._lock = threading.Lock()

    def __call__(self, profile: Optional[Dict[str, Any]]) -> ScriptedLoop:
        return ScriptedLoop(self)

    def next_turn(self) -> Turn:
        with self._lock:
            return self.script.pop(0) if self.script else ("Done.", [])


@dataclass
class RunningRuntime:
    home: Path
    loop_factory: Callable[[Optional[Dict[str, Any]]], Optional[ClaudeToolLoop]]
    port: int = 0
    token: str = ""
    token_file: Optional[Path] = None
    app: Optional[RuntimeApp] = None
    _server: Any = None
    _thread: Optional[threading.Thread] = None
    apps: List[RuntimeApp] = field(default_factory=list)

    def _start(self, port: int) -> None:
        self.token = generate_launch_token()
        self.app = make_app(self.home / ".vmdai", launch_token=self.token,
                            allow_tokenless_v1=False, loop_factory=self.loop_factory)
        self.apps.append(self.app)
        self._server = create_server(self.app, host="127.0.0.1", port=port)
        self.port = int(self._server.server_port)
        self.token_file = write_token_file(self.port, os.getpid(), self.token, 2, home=str(self.home))
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Close the port and end every session's request and chat lock."""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        app = self.app
        if app is not None:
            for state in list(getattr(app.sessions, "_sessions", {}).values()):
                try:
                    app._cancel_active_request(state)
                except Exception:
                    pass
                release = getattr(app, "_release_chat_lock", None)
                if release is not None:
                    release(state)

    def restart_same_port(self) -> None:
        """A new RuntimeApp (new token and token file) on the same port."""
        self.stop()
        self._start(self.port)


def serve_runtime(home: Path, loop_factory) -> RunningRuntime:
    runtime = RunningRuntime(home=Path(home), loop_factory=loop_factory)
    runtime._start(0)
    return runtime
```

- [ ] **Step 2: Create the tclsh driver and the race scenario**

Create `tests/tcl/driver.tcl`:

```tcl
# tests/tcl/driver.tcl - the real plugin under tclsh, attached to the runtime
# tests/test_bridge_integration.py serves (P06-T11; spec 6 Bridge
# integration). Not a tcltest file. Environment:
#   VMD_AI_ATTACH   127.0.0.1:<port>; the token file is under $HOME/.vmdai/run
#   VMDAI_SCENARIO  round_trip | cancel_before_ack | cancel_after_ack |
#                   has_more | restart | race (sources t_race.tcl)
#   VMDAI_OUT       the driver writes its findings here as one JSON object
#   VMDAI_SYNC      a directory for marker files shared with pytest
# The plugin's Tk panel is not loaded: its four sinks are recorded instead.

source [file join $env(VMDAI_PLUGIN_DIR) init.tcl]

# --- VMD stand-ins (this is tclsh, not VMD) -----------------------------------
set ::vmd_calls {}
proc ::mol {args} { lappend ::vmd_calls [concat mol $args]; return 0 }
proc ::display {args} { lappend ::vmd_calls [concat display $args]; return "" }
proc ::vmdinfo {what} { return driver-$what }
# render TachyonInternal <path>: an 8x6 uncompressed 24-bit TGA.
proc ::render {renderer path args} {
    lappend ::vmd_calls [list render $renderer]
    set fh [open $path w]
    fconfigure $fh -translation binary
    puts -nonewline $fh [binary format cccsscsssscc 0 0 2 0 0 0 0 0 8 6 24 0]
    for {set i 0} {$i < 48} {incr i} { puts -nonewline $fh [binary format ccc 40 80 200] }
    close $fh
    return ""
}

# --- panel sinks ----------------------------------------------------------------
set ::notices {}
set ::events {}
set ::statuses {}
set ::transitions {}
proc ::vmdai::ui::notify {level text} {
    lappend ::notices [list [clock milliseconds] $level $text [::vmdai::runtime::state]]
}
proc ::vmdai::ui::render_event {ev} { lappend ::events $ev }
proc ::vmdai::ui::set_busy {on} {}
proc ::vmdai::ui::status {text} { lappend ::statuses $text }
proc ::record_state {old new detail} {
    lappend ::transitions [list [clock milliseconds] $old $new]
}
::vmdai::runtime::subscribe ::record_state
# Count RPCs by method.
array set ::rpc_count {}
proc ::count_rpc {cmd op} {
    set m [lindex $cmd 1]
    if {![info exists ::rpc_count($m)]} { set ::rpc_count($m) 0 }
    incr ::rpc_count($m)
}
trace add execution ::vmdai::net::call enter ::count_rpc

# --- helpers --------------------------------------------------------------------
proc jstr {s} { return [::vmdai::net::json_string $s] }
proc jlist {items} {
    set out {}
    foreach item $items { lappend out [jstr $item] }
    return "\[[join $out ,]\]"
}
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    fconfigure $fh -encoding utf-8
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
proc fail {message} {
    write_out [list error s "$message\n$::errorInfo" notices j [jlist $::notices]]
    exit 3
}
proc bgerror {message} { fail "background error: $message" }
proc wait_for {script ms what} {
    set deadline [expr {[clock milliseconds] + $ms}]
    while {![uplevel #0 $script]} {
        if {[clock milliseconds] > $deadline} { fail "timed out waiting for $what" }
        set ::_tick 0
        after 20 {set ::_tick 1}
        vwait ::_tick
    }
}
proc marker {name} { file join $::env(VMDAI_SYNC) $name }
proc touch {name} { close [open [marker $name] w] }
proc bstate {key} { dict get [::vmdai::bridge::state] $key }
# Events that end a v1 request (final message, error, cancelled lifecycle).
proc ends {} {
    set n 0
    foreach ev $::events {
        set role [dict get $ev role]
        set type [dict get $ev type]
        if {($role eq "assistant" && $type eq "message") || $role eq "error"
                || ($type eq "lifecycle" && [dict get $ev text] eq "cancelled")} { incr n }
    }
    return $n
}
proc connect {} {
    ::vmdai::runtime::ensure
    wait_for {expr {[::vmdai::runtime::state] eq "ready" && [bstate session_id] ne ""
        && !$::vmdai::bridge::op_busy}} 10000 "the session"
}
# Send a prompt and wait until its request ended and the panel is idle.
proc ask {text {ms 15000}} {
    set before [ends]
    if {![::vmdai::bridge::send $text]} { fail "send refused: [lindex $::notices end]" }
    wait_for [list expr "\[ends\] > $before && !\[bstate busy\]"] $ms "the answer to: $text"
}
proc chunks_text {} {
    set text ""
    foreach ev $::events {
        if {[dict get $ev type] eq "chunk"} { append text [dict get $ev text] }
    }
    return $text
}
proc roles {} {
    set out {}
    foreach ev $::events { lappend out "[dict get $ev role]/[dict get $ev type]" }
    return $out
}
proc record_acks {} {
    set ::acks {}
    trace add execution ::vmdai::executor::_on_ack enter {apply {{cmd op} {
        lappend ::acks "[lindex $cmd 3] [lindex $cmd 4]"
    }}}
}
proc common_out {} {
    set notes {}
    foreach n $::notices { lappend notes "[lindex $n 1] [lindex $n 2]" }
    set moves {}
    foreach t $::transitions { lappend moves "[lindex $t 1]>[lindex $t 2]" }
    return [list roles j [jlist [roles]] vmd_calls j [jlist $::vmd_calls] \
        notices j [jlist $notes] transitions j [jlist $moves] statuses j [jlist $::statuses] \
        queue i [::vmdai::net::result_queue_size] chat_id s [bstate chat_id] \
        session_starts i [expr {[info exists ::rpc_count(session.start)] ? $::rpc_count(session.start) : 0}]]
}

# --- scenarios --------------------------------------------------------------------

# One request with a Tcl command and a snapshot: ack, run, puts captured, post.
proc scenario_round_trip {} {
    record_acks
    connect
    ask "Load 1abc and take a snapshot"
    write_out [concat [common_out] [list acks j [jlist $::acks] text s [chunks_text] \
        ledger i [llength [::vmdai::executor::ledger]]]]
}

# Stop before the executor acked: the late ack gets proceed false, nothing runs.
proc scenario_cancel_before_ack {} {
    connect
    rename ::vmdai::executor::run ::real_executor_run
    set ::held {}
    proc ::vmdai::executor::run {ev} { lappend ::held $ev }
    set before [ends]
    ::vmdai::bridge::send "Load 1abc"
    wait_for {expr {[llength $::held] == 1}} 10000 "the tool_start"
    set cancel_sent [::vmdai::bridge::cancel]
    wait_for [list expr "\[ends\] > $before && !\[bstate busy\]"] 10000 "the stopped request"
    rename ::vmdai::executor::run {}
    rename ::real_executor_run ::vmdai::executor::run
    # Forget the local cancel note so the ack really goes to the runtime.
    ::vmdai::executor::reset
    record_acks
    ::vmdai::executor::run [lindex $::held 0]
    wait_for {expr {[llength $::acks] == 1}} 5000 "the late ack"
    write_out [concat [common_out] [list cancel_sent b $cancel_sent acks j [jlist $::acks]]]
}

# Stop while the command runs (it waits 800 ms in vwait): the result still
# arrives within the grace period and the request ends as stopped.
proc scenario_cancel_after_ack {} {
    set ::ran 0
    record_acks
    trace add execution ::vmdai::executor::exec_command enter {apply {{cmd op} {
        after 200 ::vmdai::bridge::cancel
    }}}
    connect
    set t0 [clock milliseconds]
    ask "Run the slow command" 20000
    write_out [concat [common_out] [list ran i $::ran acks j [jlist $::acks] \
        elapsed_ms i [expr {[clock milliseconds] - $t0}]]]
}

# A long answer: has_more is drained with back-to-back polls.
proc scenario_has_more {} {
    connect
    ask "Tell me a long story"
    set chunk_ms {}
    foreach t $::chunk_times { lappend chunk_ms $t }
    write_out [concat [common_out] [list text s [chunks_text] \
        polls i $::rpc_count(chat.events.poll) after_seq i [bstate after_seq] \
        drain_ms i [expr {[lindex $chunk_ms end] - [lindex $chunk_ms 0]}]]]
}

# S3: pytest kills the runtime and restarts it on the same port with a new
# token. The plugin reconnects, starts a new session, resumes the chat, and
# the next chat.send works within 10 s of the restart.
proc scenario_restart {} {
    connect
    ask "Load 1abc"
    set chat [bstate chat_id]
    set old [bstate session_id]
    set ::notices {}
    set ::transitions {}
    touch ready_for_restart
    wait_for {file exists [marker restarted]} 20000 "pytest to restart the runtime"
    set t0 [clock milliseconds]
    wait_for [list expr "\[bstate session_id\] ne {$old} && \[bstate session_id\] ne {}
        && !\$::vmdai::bridge::op_busy"] 15000 "the recovered session"
    ask "Now color it red" 15000
    write_out [concat [common_out] [list chat_before s $chat \
        elapsed_ms i [expr {[clock milliseconds] - $t0}]]]
}

set ::chunk_times {}
rename ::vmdai::ui::render_event ::record_event
proc ::vmdai::ui::render_event {ev} {
    if {[dict get $ev type] eq "chunk"} { lappend ::chunk_times [clock milliseconds] }
    ::record_event $ev
}

set scenario $::env(VMDAI_SCENARIO)
if {$scenario eq "race"} {
    source [file join $::env(VMDAI_REPO) tests tcl t_race.tcl]
}
if {[catch {scenario_$scenario} err]} {
    fail $err
}
::vmdai::cleanup
exit 0
```

Create `tests/tcl/t_race.tcl`:

```tcl
# tests/tcl/t_race.tcl - the New Chat / Resume race (P06-T11; spec 2d Epoch,
# 6 Bridge integration). Sourced by driver.tcl for VMDAI_SCENARIO=race.
#
# Today's bridge nests vwait inside every RPC, so a poll that fires during
# New Chat writes the old session's after_seq over the new one. Here New
# Chat and Resume are issued back to back while a poll is due: they must run
# one after the other, replies of the old session must be dropped, and the
# next request must arrive whole, with no event seen twice.

proc scenario_race {} {
    connect
    ask "First question"
    set chat_a [bstate chat_id]
    set first_session [bstate session_id]
    ::vmdai::bridge::poll_now
    ::vmdai::bridge::new_chat
    ::vmdai::bridge::resume $chat_a
    wait_for [list expr "!\$::vmdai::bridge::op_busy && \[llength \$::vmdai::bridge::op_queue\] == 0
        && \[bstate chat_id\] eq {$chat_a} && \[bstate session_id\] ne {$first_session}"] \
        10000 "New Chat then Resume"
    set mark [llength $::events]
    ask "Second question"
    set seqs {}
    set text ""
    foreach ev [lrange $::events $mark end] {
        lappend seqs [dict get $ev seq]
        if {[dict get $ev type] eq "chunk"} { append text [dict get $ev text] }
    }
    set ordered [expr {$seqs eq [lsort -integer -unique $seqs]}]
    write_out [concat [common_out] [list chat_a s $chat_a second_text s $text \
        seqs_ordered b $ordered stops i $::rpc_count(session.stop) \
        resumes i $::rpc_count(chat.resume) after_seq i [bstate after_seq]]]
}
```

- [ ] **Step 3: Write the integration tests**

Create `tests/test_bridge_integration.py`:

```python
"""The real plugin in tclsh against a real RuntimeApp with a scripted model (P06-T11).

Spec §6 "Bridge integration", S3 and S10. pytest serves RuntimeApp with
ScriptedLoopFactory on port 0; tests/tcl/driver.tcl sources plugin/init.tcl,
attaches with VMD_AI_ATTACH and the token file, runs one scenario and writes
what it saw as JSON. The restart scenarios coordinate through marker files.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pytest

from helpers import tcl
from helpers.scripted_runtime import RunningRuntime, ScriptedLoopFactory, serve_runtime

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "tests" / "tcl" / "driver.tcl"
LONG = " ".join(f"word{i}" for i in range(250))


def _tool(call_id: str, name: str, **tool_input: str) -> Dict[str, Any]:
    return {"id": call_id, "name": name, "input": tool_input}


SCRIPTS = {
    "round_trip": [
        ("Loading.", [_tool("tc_1", "run_vmd_command",
                            command='mol new 1abc.pdb\nputs "atoms: 42"', rationale="Load")]),
        ("", [_tool("tc_2", "capture_vmd_snapshot", purpose="Check the view")]),
        ("Loaded 42 atoms.", []),
    ],
    "cancel_before_ack": [("", [_tool("tc_1", "run_vmd_command", command="mol new 1abc.pdb")])],
    "cancel_after_ack": [("Running.", [_tool("tc_1", "run_vmd_command",
                                             command="set ::t 0\nafter 800 {set ::t 1}\nvwait ::t\nset ::ran 1")])],
    "has_more": [(LONG, [])],
    "restart": [("Loaded.", []), ("Colored.", [])],
    "race": [("First answer here.", []), ("Second answer with several words in it.", [])],
}

Run = Tuple[Dict[str, Any], ScriptedLoopFactory, RunningRuntime]
_CACHE: Dict[str, Run] = {}


def _drive(tmp_path: Path, scenario: str,
           on_restart: Optional[Callable[[RunningRuntime], None]] = None) -> Run:
    reason = tcl.tcl_skip_reason(needs_http=True, needs_json=True)
    if reason:
        pytest.skip(reason)
    home, sync, out = tmp_path / "rt_home", tmp_path / "sync", tmp_path / "out.json"
    home.mkdir()
    sync.mkdir()
    factory = ScriptedLoopFactory(SCRIPTS["restart" if on_restart else scenario])
    runtime = serve_runtime(home, factory)
    env = {"HOME": str(home), "VMD_AI_ATTACH": f"127.0.0.1:{runtime.port}",
           "VMDAI_SCENARIO": scenario, "VMDAI_OUT": str(out), "VMDAI_SYNC": str(sync)}
    done: Dict[str, Any] = {}

    def run() -> None:
        done["proc"] = tcl.run_tcl(DRIVER.read_text(encoding="utf-8"), needs_http=True,
                                   needs_json=True, env=env, timeout=90)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        if on_restart is not None:
            deadline = time.monotonic() + 30
            while not (sync / "ready_for_restart").exists():
                assert worker.is_alive() and time.monotonic() < deadline, done
                time.sleep(0.02)
            on_restart(runtime)
            (sync / "restarted").touch()
        worker.join(timeout=100)
    finally:
        runtime.stop()
    proc = done["proc"]
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    assert "error" not in data, data.get("error")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return data, factory, runtime


def _cached(key: str, tmp_path: Path, scenario: str, on_restart=None) -> Run:
    # Function scope keeps the hermetic conftest active; each scenario runs once.
    if key not in _CACHE:
        _CACHE[key] = _drive(tmp_path, scenario, on_restart)
    return _CACHE[key]


def test_tool_round_trip_with_ack(tmp_path):
    data, factory, _ = _cached("round_trip", tmp_path, "round_trip")
    assert data["acks"] == ["ok proceed true", "ok proceed true"]
    assert data["vmd_calls"] == ["mol new 1abc.pdb", "display update", "render TachyonInternal"]
    assert data["roles"].count("tool_result/message") == 2
    assert data["roles"][-1] == "assistant/message"
    assert data["text"].endswith("Loaded 42 atoms.")
    assert data["queue"] == 0 and data["ledger"] == 2
    assert len(factory.calls) == 3


def test_puts_output_reaches_model(tmp_path):
    """S10: what the command printed is in the tool result of the next model call."""
    _, factory, _ = _cached("round_trip", tmp_path, "round_trip")
    after_command = json.dumps(factory.calls[1][-1])
    assert "atoms: 42" in after_command
    assert "tool_result" in after_command


def test_cancel_before_ack(tmp_path):
    data, _, _ = _cached("cancel_before_ack", tmp_path, "cancel_before_ack")
    assert data["cancel_sent"] is True
    assert data["acks"] == ["ok proceed false reason cancelled"]
    assert data["vmd_calls"] == []
    assert "system/lifecycle" in data["roles"]


def test_cancel_after_ack(tmp_path):
    data, _, _ = _cached("cancel_after_ack", tmp_path, "cancel_after_ack")
    assert data["ran"] == 1 and data["acks"] == ["ok proceed true"]
    assert data["queue"] == 0
    assert data["roles"][-1] == "system/lifecycle"
    assert data["elapsed_ms"] < 10000  # the result came back inside the grace period


def test_new_chat_resume_race(tmp_path):
    data, _, _ = _cached("race", tmp_path, "race")
    assert data["chat_id"] == data["chat_a"]
    assert data["second_text"] == "Second answer with several words in it."
    assert data["seqs_ordered"] is True
    assert data["session_starts"] == 2 and data["stops"] == 1 and data["resumes"] == 1


def test_has_more_draining_200(tmp_path):
    data, _, _ = _cached("has_more", tmp_path, "has_more")
    assert data["text"] == LONG
    assert data["roles"].count("assistant/chunk") == 250
    assert data["polls"] >= 4
    assert data["drain_ms"] < 600  # three has_more re-polls at once, not 3 x 250 ms


def _kill_then_restart(runtime: RunningRuntime) -> None:
    runtime.stop()
    time.sleep(1.0)
    runtime.restart_same_port()


def test_kill_restart_one_notice_send_within_10s(tmp_path):
    """S3: one notice per state change, recovery and a working chat.send within 10 s."""
    data, _, runtime = _cached("kill", tmp_path, "restart", _kill_then_restart)
    assert data["transitions"] == ["ready>reconnecting", "reconnecting>ready"]
    assert data["notices"] == ["warn Lost the connection to the AI runtime; reconnecting.",
                               "info Reconnected to the AI runtime."]
    assert data["elapsed_ms"] < 10000
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(runtime.apps) == 2


def test_auth_failed_recovery(tmp_path):
    """A restart with no downtime is seen as AUTH_FAILED: new session, same chat."""
    data, _, runtime = _cached("auth", tmp_path, "restart", lambda rt: rt.restart_same_port())
    assert data["chat_id"] == data["chat_before"]
    assert data["session_starts"] == 2
    assert len(data["notices"]) <= len(data["transitions"])
    assert data["statuses"] == []  # idle when it happened: no request was lost
    assert len(runtime.apps) == 2
```

What each scenario pins: `round_trip` — both tools are acked with `proceed true`, VMD sees `mol new`, `display update` and `render TachyonInternal`, both results are accepted (the queue is empty) and the model's next call carries `atoms: 42` from `puts` (S10). `cancel_before_ack` — the late ack answers `proceed false reason cancelled` and nothing runs. `cancel_after_ack` — Stop during a command that waits 800 ms in `vwait`: the command finishes, its result is accepted within the 30 s grace and the request ends with the `cancelled` lifecycle event. `has_more` — 250 chunk events arrive whole, drained by back-to-back polls in under 600 ms. `restart` with a 1 s outage — exactly two transitions, one notice each, and a working `chat.send` within 10 s of the restart (S3). `restart` with no outage — the next poll's `AUTH_FAILED` leads to a new session in the same chat. `race` — New Chat then Resume in the same tick: two sessions, one stop, one resume, and the next answer arrives whole with increasing `seq` numbers.

- [ ] **Step 4: Run them**

Run: `python -m pytest tests/test_bridge_integration.py -q`
Expected: `8 passed` in under 10 s.

- [ ] **Step 5: Check they are stable**

Run: `for i in 1 2 3; do python -m pytest tests/test_bridge_integration.py -q 2>&1 | tail -1; done`
Expected: three lines `8 passed …`.

- [ ] **Step 6: Run the suite**

Run: `SUITE`
Expected: `B+78 passed`, `0 failed`, still under 60 s.

- [ ] **Step 7: Commit**

```bash
git add tests/helpers/scripted_runtime.py tests/tcl/driver.tcl tests/tcl/t_race.tcl tests/test_bridge_integration.py
git commit -F - <<'MSG'
test(plugin): bridge integration against a real runtime with a scripted model

tests/tcl/driver.tcl runs the real plugin under tclsh in attach mode
against RuntimeApp(loop_factory=ScriptedLoopFactory) served on port 0:
tool round trip with ack and puts reaching the model (S10), Stop before
and after the ack, has_more draining, a killed and restarted runtime
with one notice per transition and a chat.send within 10 s (S3),
AUTH_FAILED recovery into the same chat, and the New Chat/Resume race.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task 12: P06-T12 — Real-VMD checks: garbling root cause, TachyonInternal render, M1 smoke

**Files:**
- Create: `tests/test_live_vmd.py`, `docs/design/round1/garbling-root-cause.md`

**Interfaces:**
- Consumes: the `live_env` fixture and the `VMD_AI_VMD_BIN` gate (P01-T01); `helpers.tcl.REPO`, `find_tclsh` (P01-T03); `FakeRpcServer` (P06-T03); `::vmdai::executor::exec_command`, `capture_snapshot` (P06-T08); `::vmdai::net::call`, `configure`, `encode_params` (P06-T03); `scripts/install_plugin.tcl` (P06-T09); `vmdbench/fixtures/1crn.pdb` (crambin, 327 atoms; public PDB data, not ATLAS); the tag `baseline-2026-09-24` (P01-T01) for the pre-M1 plugin files.
- Produces:
  - `tests/test_live_vmd.py` (skipped unless `VMD_AI_VMD_BIN` is set): `test_live_headless_tachyon_render_over_1kb` (the executor runs `mol new` + `puts` in real VMD and `render TachyonInternal` writes a TGA over 1 KB with a real size), `test_live_unicode_round_trip_inside_vmd` (S8 inside VMD's own Tcl and http: ASCII replies always intact; raw UTF-8 replies intact with http 2.9 or later), `test_live_vmdrc_block_loads_plugin` (the installer's block loads `vmd_ai 2.0` when VMD starts, without Tk)
  - `docs/design/round1/garbling-root-cause.md`: what is ruled out (measured 2026-09-25), the GUI reproduction, the decision table, the named cause, and the decision on the `auto` renderer gate (M1 renders with TachyonInternal only; `render snapshot` must pass the GUI check recorded there before any `auto` renderer is built)
  - M1 exit: S1, S3, S4, S5, S6, S8, S10, S11, S12 green, and the garbling root cause named

- [ ] **Step 1: Write the live tests**

Create `tests/test_live_vmd.py`:

```python
"""Real-VMD checks (P06-T12; spec §2c Wire encoding, §2d Snapshot, §6 Live tests).

Opt-in: set VMD_AI_VMD_BIN to a VMD binary (read through the live_env
fixture), e.g. /Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64. Each test
runs ``vmd -dispdev text -e <script>`` in a temp directory with a temp HOME;
the script writes its findings to $VMDAI_OUT as JSON and quits.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from helpers.fake_rpc_server import FakeRpcServer
from helpers.tcl import REPO, find_tclsh

PLUGIN = REPO / "plugin"
PDB = REPO / "vmdbench" / "fixtures" / "1crn.pdb"
ARROW = "".join(map(chr, (0xC5, 0x2192, 0xB0)))

# Loads the plugin's no-Tk modules and gives the script a JSON writer.
PRELUDE = """
set plugin $env(VMDAI_PLUGIN_DIR)
foreach m {config sched net executor} { source [file join $plugin $m.tcl] }
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
"""


def _vmd(live_env: Dict[str, str]) -> str:
    vmd = live_env.get("VMD_AI_VMD_BIN")
    if not vmd:
        pytest.skip("set VMD_AI_VMD_BIN to run the real-VMD checks")
    return vmd


def _run_vmd(vmd: str, body: str, tmp_path: Path, home: Optional[Path] = None,
             env: Optional[Dict[str, str]] = None, prelude: bool = True) -> Dict[str, Any]:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    out = tmp_path / "out.json"
    script = tmp_path / "check.tcl"
    script.write_text((PRELUDE if prelude else "") + body + "\nquit\n", encoding="utf-8")
    run_env = dict(os.environ, VMDAI_OUT=str(out), VMDAI_PLUGIN_DIR=str(PLUGIN),
                   HOME=str(home or tmp_path / "vmd_home"))
    Path(run_env["HOME"]).mkdir(exist_ok=True)
    run_env.update(env or {})
    proc = subprocess.run([vmd, "-dispdev", "text", "-e", str(script)], cwd=work, env=run_env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          errors="replace", timeout=120)
    assert out.exists(), (proc.stdout + proc.stderr)[-3000:]
    return json.loads(out.read_text(encoding="utf-8"))


def test_live_headless_tachyon_render_over_1kb(live_env, tmp_path):
    """§2d Snapshot: the executor's render TachyonInternal writes a real image in real VMD."""
    vmd = _vmd(live_env)
    data = _run_vmd(vmd, f"""
set r [::vmdai::executor::exec_command "mol new {{{PDB}}} waitfor all\\nmol modstyle 0 top NewCartoon\\nputs \\"atoms: \\[molinfo top get numatoms\\]\\""]
set path [file join [pwd] snap.tga]
set s [::vmdai::executor::capture_snapshot {{}} $path]
write_out [list ok b [dict get $r ok] output s [dict get $r output] applied i [dict get $r statements_applied] \\
    snap_ok b [dict get $s ok] snap_error s [dict get $s error] path s $path]
""", tmp_path)
    assert data["ok"] is True and data["applied"] == 3
    assert "atoms: 327" in data["output"]
    assert data["snap_ok"] is True, data["snap_error"]
    tga = Path(data["path"]).read_bytes()
    assert len(tga) > 1024
    width, height = struct.unpack("<HH", tga[12:16])
    assert width > 0 and height > 0


def test_live_unicode_round_trip_inside_vmd(live_env, tmp_path):
    """S8 inside VMD's own Tcl and http: ASCII replies always; raw UTF-8 with http >= 2.9."""
    vmd = _vmd(live_env)

    def echo(method, params, headers):
        return {"result": params}

    with FakeRpcServer(echo) as plain, FakeRpcServer(echo, ensure_ascii=False) as utf8:
        data = _run_vmd(vmd, """
set text [format %c%c%c 0xc5 0x2192 0xb0]
proc got {tag args} { set ::got($tag) $args }
foreach tag {ascii utf8} url [list $env(FAKE_ASCII) $env(FAKE_UTF8)] {
    ::vmdai::net::configure -base_url $url
    ::vmdai::net::call echo [list text s $text] [list got $tag]
    vwait ::got($tag)
}
set a [dict get [lindex $::got(ascii) 1] text]
set u [dict get [lindex $::got(utf8) 1] text]
write_out [list http s [package present http] encoding s [encoding system] \\
    ascii_intact b [expr {$a eq $text}] utf8_intact b [expr {$u eq $text}] \\
    utf8_hex s [binary scan [encoding convertto utf-8 $u] H* hex; set hex]]
""", tmp_path, env={"FAKE_ASCII": plain.base_url, "FAKE_UTF8": utf8.base_url})
        requests = plain.calls("echo") + utf8.calls("echo")
    assert all(r.body.isascii() and r.params["text"] == ARROW for r in requests)
    assert data["ascii_intact"] is True
    major_minor = tuple(int(x) for x in data["http"].split(".")[:2])
    if major_minor >= (2, 9):
        assert data["utf8_intact"] is True, data


def test_live_vmdrc_block_loads_plugin(live_env, tmp_path):
    """The installer's ~/.vmdrc block loads vmd_ai 2.0 when VMD starts (no Tk needed)."""
    vmd = _vmd(live_env)
    home = tmp_path / "vmd_home"
    home.mkdir()
    tclsh = find_tclsh()
    if tclsh is None:
        pytest.skip("no Tcl 8.6 tclsh to run the installer")
    subprocess.run([tclsh, str(REPO / "scripts" / "install_plugin.tcl"), "--vmdrc",
                    str(home / ".vmdrc"), "--yes"], check=True, capture_output=True)
    data = _run_vmd(vmd, """
proc write_out {pairs} {
    set fh [open $::env(VMDAI_OUT) w]
    puts -nonewline $fh [::vmdai::net::encode_params $pairs]
    close $fh
}
write_out [list vmd_ai s [package present vmd_ai] start s [info commands ::vmdai::start] \\
    state s [::vmdai::runtime::state] leftover b [info exists vmdai_err]]
""", tmp_path, home=home, prelude=False)
    assert data == {"vmd_ai": "2.0", "start": "::vmdai::start", "state": "stopped",
                    "leftover": False}
```

- [ ] **Step 2: Check they skip without the gate**

Run: `python -m pytest tests/test_live_vmd.py -q -rs`
Expected: `3 skipped`, each with `set VMD_AI_VMD_BIN to run the real-VMD checks`.

- [ ] **Step 3: Run them against VMD 1.9.4a57**

Run: `VMD_AI_VMD_BIN=/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 python -m pytest tests/test_live_vmd.py -q`
Expected: `3 passed` (a few seconds). A render failure shows the renderer's error as the assertion message; TachyonInternal must work under `-dispdev text` (vmdbench relies on it too). When a script dies before writing its JSON, the assertion shows the end of VMD's output.

- [ ] **Step 4: Repeat the headless evidence**

The scan counts only; it prints no chat text:

```bash
cd ~/.vmdai/chats && python3 - <<'EOF'
import glob, json, re
bad = re.compile("\u00c3[\u0080-\u00bf]|\u00e2\u0080|\u00e2\u0086|\u00c2\u00b0|\ufffd")
good = re.compile("[\u00c5\u2192\u2014\u00b0]")
n_bad = n_good = 0
for path in glob.glob("*/events.jsonl"):
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            text = str(json.loads(line).get("text", ""))
        except ValueError:
            continue
        n_bad += bool(bad.search(text))
        n_good += bool(good.search(text))
print("events with intact characters:", n_good, "with mojibake:", n_bad)
EOF
cd -
```

Expected on the dev Mac: `events with intact characters: 125 with mojibake: 0` (more intact events if chats were added since 2026-09-25; the point is `with mojibake: 0`).

Then run the headless probe: save the baseline files, start the fake runtimes and save `/tmp/garble_probe.tcl` exactly as steps 1–3 of "How to reproduce in the GUI" in the note's text (Step 7) show, run it with `vmd -dispdev text`, and compare `/tmp/garble_probe.txt` with the output printed there (every code point line equal to `sent`, `http 2.9.5`, `encoding utf-8`).

- [ ] **Step 5: Reproduce in the GUI (manual)**

On the dev Mac, logged in: keep the fake runtimes of Step 4 running (start them again if their 600 s ran out), start VMD from the Dock, open Extensions > Tk Console, run `source /tmp/garble_probe.tcl`, look at the small window it opens (does it show Å→°—é?), and keep the output of `cat /tmp/garble_probe.txt`.

- [ ] **Step 6: Check `render snapshot` in the GUI (manual)**

In the same VMD console:

```tcl
mol new /Users/pinhaogu/Documents/GitHub/vmdai/vmdbench/fixtures/1crn.pdb
mol modstyle 0 top NewCartoon
display update
render snapshot /tmp/gui_snapshot.tga
render TachyonInternal /tmp/gui_tachyon.tga
```

Then run the measuring snippet from the doc's last section and keep its two lines. `render snapshot` counts as verified when its image has the window's size and a variance above 0.

- [ ] **Step 7: Write the note**

Create `docs/design/round1/garbling-root-cause.md` with this text:

````markdown
# Non-ASCII text in the panel: where the garbling comes from

Spec §2c "Wire encoding" asks that, before M1 closes, the garbling of non-ASCII text (Å, →, —) is reproduced inside real VMD and its cause named. This note records what was checked, how to repeat it, and the result. It closes with the decision on the `auto` snapshot renderer (§2d Snapshot).

## What is ruled out (checked 2026-09-25 on the dev Mac, VMD 1.9.4a57)

1. **The runtime and the model streams.** A count-only scan of the 80 stored chats in `~/.vmdai/chats` found Å, →, — or ° in 125 events of 13 chats (101 assistant chunks, 24 assistant messages) and no UTF-8-read-as-Latin-1 sequence (`Ã` plus a continuation character, `â€`, `â†`, `Â°`) or U+FFFD anywhere. The text leaves the runtime intact, so the loss happens after it, in VMD. Re-run the scan with:

   ```bash
   cd ~/.vmdai/chats && python3 - <<'EOF'
   import glob, json, re
   bad = re.compile("\u00c3[\u0080-\u00bf]|\u00e2\u0080|\u00e2\u0086|\u00c2\u00b0|\ufffd")
   good = re.compile("[\u00c5\u2192\u2014\u00b0]")
   n_bad = n_good = 0
   for path in glob.glob("*/events.jsonl"):
       for line in open(path, encoding="utf-8", errors="replace"):
           try:
               text = str(json.loads(line).get("text", ""))
           except ValueError:
               continue
           n_bad += bool(bad.search(text))
           n_good += bool(good.search(text))
   print("events with intact characters:", n_good, "with mojibake:", n_bad)
   EOF
   ```

2. **VMD's Tcl encoding.** Inside `vmd -dispdev text`, `encoding system` is `utf-8` both with `LANG=en_US.UTF-8` and with `LANG`, `LC_ALL` and `LC_CTYPE` unset (as for an app started from the Dock), and `source` of a UTF-8 file gives the code points `00c5,2192,00b0`.

3. **VMD's http and the baseline plugin's decode path.** Inside `vmd -dispdev text`, `package present http` is 2.9.5, VMD's module path does not contain `vmd/scripts/tcl8/8.6` (where the unused `http-2.9.0.tm` lives), and http 2.9.5 decodes `application/json; charset=utf-8` as text (`http::IsBinaryContentType`, http-2.9.5.tm:3051-3061). The baseline `bridge.tcl` (`_rpc` then `_parse_events`, with VMD's json 1.1.2) received `Å→° — café` as `00c5,2192,00b0,0020,2014,0020,0063,0061,0066,00e9` both from a server answering raw UTF-8 JSON, as `server.py` does before M1, and from one answering ASCII-only JSON.

4. **The M1 path.** `tests/test_live_vmd.py::test_live_unicode_round_trip_inside_vmd` sends Å→° through `net::call` inside real VMD to an ASCII server and a raw-UTF-8 server and gets it back intact from both (with http 2.9 or later).

So the garbling is not made by the runtime, by the storage, by VMD's system encoding, or by http/json decoding in headless VMD 1.9.4a57. What remains is what only the GUI panel does, or another VMD build.

## How to reproduce in the GUI

1. From the repo root, save the baseline plugin files and start two fake runtimes (raw UTF-8 JSON and ASCII JSON) that answer every poll with `Å→°—é`:

   ```bash
   git show baseline-2026-09-24:plugin/bridge.tcl > /tmp/baseline_bridge.tcl
   git show baseline-2026-09-24:plugin/config.tcl > /tmp/baseline_config.tcl
   python - 600 <<'EOF' &
   import sys, time
   sys.path[:0] = ["tests"]
   from helpers.fake_rpc_server import FakeRpcServer
   TEXT = "".join(map(chr, (0xC5, 0x2192, 0xB0, 0x2014, 0xE9)))
   def handler(method, params, headers):
       return {"result": {"events": [{"seq": 1, "role": "assistant", "type": "message",
                                      "text": TEXT, "metadata": {}}],
                          "last_seq": 1, "has_more": False}}
   with FakeRpcServer(handler) as a, FakeRpcServer(handler, ensure_ascii=False) as u:
       open("/tmp/garble_ports.txt", "w").write(f"{a.port} {u.port}\n")
       time.sleep(float(sys.argv[1]))
   EOF
   ```

2. Save this probe as `/tmp/garble_probe.tcl`:

   ```tcl
   # Where does non-ASCII text change on its way to the panel? Writes
   # /tmp/garble_probe.txt. Headless runs quit at the end; GUI runs keep a
   # small window showing the text in the M1 panel's font.
   set text [format %c%c%c%c%c 0xc5 0x2192 0xb0 0x2014 0xe9]
   proc codes {s} {
       set out {}
       foreach ch [split $s ""] { lappend out [format %04x [scan $ch %c]] }
       return [join $out ,]
   }
   set out [open /tmp/garble_probe.txt w]
   fconfigure $out -encoding utf-8
   puts $out "sent        [codes $text]"
   puts $out "encoding    [encoding system]"
   puts $out "tcl         [info patchlevel] tk=[expr {[catch {package present Tk} v] ? "none" : $v}]"
   puts $out "http        [package require http]"
   puts $out "tm_vmd      [lsearch -inline -all [::tcl::tm::path list] *vmd/scripts*]"
   namespace eval ::vmdai {}
   source /tmp/baseline_config.tcl
   source /tmp/baseline_bridge.tcl
   set fh [open /tmp/garble_ports.txt]
   lassign [split [string trim [read $fh]]] ascii_port utf8_port
   close $fh
   foreach {name port} [list utf8_reply $utf8_port ascii_reply $ascii_port] {
       set ::vmdai::config::port $port
       set body [::vmdai::bridge::_rpc chat.events.poll "{}"]
       set got [dict get [lindex [::vmdai::bridge::_parse_events $body] 0] text]
       puts $out "[format %-11s $name] [codes $got]"
   }
   set fh [open /tmp/garble_literal.tcl w]
   fconfigure $fh -translation binary
   puts -nonewline $fh "set literal \"[encoding convertto utf-8 $text]\""
   close $fh
   source /tmp/garble_literal.tcl
   puts $out "source      [codes $literal]"
   if {[llength [info commands toplevel]]} {
       catch {destroy .garble}
       toplevel .garble
       text .garble.t -font {{Menlo} 12 bold} -height 3 -width 30
       pack .garble.t
       .garble.t insert end "$got\n"
       puts $out "tk_text     [codes [.garble.t get 1.0 {end - 2c}]]"
       puts $out "font        [font actual {{Menlo} 12 bold}]"
   }
   close $out
   if {![llength [info commands toplevel]]} { quit }
   ```

3. Headless first: `/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 -dispdev text -e /tmp/garble_probe.tcl`, then `cat /tmp/garble_probe.txt`. On the dev Mac this printed:

   ```text
   sent        00c5,2192,00b0,2014,00e9
   encoding    utf-8
   tcl         8.6.12 tk=none
   http        2.9.5
   tm_vmd
   utf8_reply  00c5,2192,00b0,2014,00e9
   ascii_reply 00c5,2192,00b0,2014,00e9
   source      00c5,2192,00b0,2014,00e9
   ```

4. Then in the GUI: start VMD from the Dock (the way the owner starts it), open Extensions > Tk Console, run `source /tmp/garble_probe.tcl`, look at the small window it opens, and `cat /tmp/garble_probe.txt`.

## Reading the result

Compare every line with `sent`; the first layer that differs is the cause. Copy the matching row into "Result" below.

| What the GUI probe shows | Cause | Status in M1 |
|---|---|---|
| `utf8_reply` differs, `ascii_reply` matches | VMD's http reads the raw UTF-8 JSON that `server.py` sent before M1 with the wrong charset (the `http` line names the version). | Fixed: the runtime sends ASCII-only JSON (`ensure_ascii=True`, P02-T01), which every http version decodes the same way. |
| `source` differs | VMD sources plugin files in the system encoding shown on the `encoding` line, not UTF-8, so the non-ASCII characters written in the pre-M1 `ui.tcl` (…, —) are misread. | Fixed: plugin files outside `plugin/lib` are ASCII-only (plan 06). |
| all code points match, but the `.garble` window shows wrong glyphs | Display only: the font on the `font` line lacks the glyphs, so Tk substitutes others. | The M1 panel uses the first available of SF Mono, Menlo and DejaVu Sans Mono (P06-T10); M2 names its fonts (P08). |
| everything matches and looks right | Not reproducible with VMD 1.9.4a57 on this Mac. Run `VMD_AI_VMD_BIN=<the other VMD the owner uses, e.g. /software/vmd-1.9.3/bin/vmd> python -m pytest tests/test_live_vmd.py -q -k unicode` there: with http older than 2.9 (Tcl 8.5) `application/json` is read as binary, so raw UTF-8 replies arrive as ISO-8859-1 mojibake. | Fixed by ASCII-only JSON if that run shows `utf8_intact` false; otherwise the pre-M1 path is the remaining explanation and M1 removes both of its risky layers (raw UTF-8 on the wire, non-ASCII plugin source). |

## The `auto` snapshot renderer

M1 renders every snapshot with `render TachyonInternal` (P06-T08). `render snapshot` reads the OpenGL window and is a broken stub under `-dispdev text`. An `auto` renderer (snapshot when it works, checked by pixel variance on a strided sample, since file size cannot catch a black image) is not built in round 1. The GUI check below is the gate a later change must cite. To run it, load a structure in the GUI (`mol new <repo>/vmdbench/fixtures/1crn.pdb`, `mol modstyle 0 top NewCartoon`, `display update`), render both ways (`render snapshot /tmp/gui_snapshot.tga`, `render TachyonInternal /tmp/gui_tachyon.tga`), and measure:

```bash
python - <<'EOF'
import struct
for path in ("/tmp/gui_snapshot.tga", "/tmp/gui_tachyon.tga"):
    data = open(path, "rb").read()
    width, height = struct.unpack("<HH", data[12:16])
    pixels = data[18 + data[0]:]
    sample = pixels[::max(1, len(pixels) // 4096)]
    mean = sum(sample) / len(sample)
    print(path, "type", data[2], width, "x", height,
          "variance", round(sum((x - mean) ** 2 for x in sample) / len(sample), 1))
EOF
```

`render snapshot` counts as verified when its image has the window's size and a variance above 0.
````

Then append, with the measurements of Steps 5 and 6 filled in from what you recorded:

````markdown

## Result

GUI probe, <date>, VMD 1.9.4a57 started from the Dock:

```text
<the contents of /tmp/garble_probe.txt from Step 5>
```

Cause: <the Cause cell of the row that matches, copied verbatim>

Status: <the Status in M1 cell of that row, copied verbatim>

`render snapshot` in the GUI: <the two lines the measuring snippet printed in Step 6>. Verified: <yes or no, by the rule above>. M1 keeps TachyonInternal either way; an `auto` renderer may be built only after a "yes" here.
````

The angle brackets are the measurements to copy in; nothing else in the note changes.

- [ ] **Step 8: M1 smoke with the local model (manual, S1 and S5)**

1. `tclsh scripts/install_plugin.tcl` and answer `y`.
2. Make sure Ollama serves `qwen3.8:27b` (the tunnel on 127.0.0.1:11435, or 11434) so the first-run probe (P03-T06) creates the profile, or pick Provider `ollama`, Model `qwen3.8:27b` and press Apply.
3. Start VMD from the Dock and choose Extensions > VMD AI. Expected: the panel opens with `VMD AI panel ready.` and, within 20 s, no error notice (the runtime was launched and connected).
4. Send `Load /Users/pinhaogu/Documents/GitHub/vmdai/vmdbench/fixtures/1crn.pdb and show it as cartoon`. Expected: a `SYSTEM: Running: mol new …` line, then the answer, and crambin in the VMD window.
5. Send `Now color it red`. Expected: a `Running: mol modcolor …` (or `color …`) line on the same molecule and no second `mol new`: the follow-up saw turn 1's tool calls (S1).
6. Close the panel and reopen it from the menu: the same transcript comes back and no second runtime starts (`pgrep -f runtime/main.py | wc -l` prints `1`).
7. In the Tk console: `::vmdai::reload`, again `::vmdai::reload`, then `::vmdai::cleanup; ::vmdai::sched::pending`. Expected: the panel reopens after each reload, and the last command closes it and prints nothing: no ChatVMD timer is left (S4; VMD's own scripts may keep other `after` timers, so the tclsh test in P06-T09 is the one that checks `after info`). Reopen the panel from the menu before the next step.
8. Quit VMD. Expected: `pgrep -f runtime/main.py` prints nothing (`--watch-stdin`).
9. S5 and S6 live tests from plans 03–04: `VMD_AI_LIVE_OLLAMA=http://127.0.0.1:11435 VMD_AI_LIVE_MODEL=qwen3.8:27b env -u VMD_AI_PROVIDER python -m pytest tests -q -k live`. Expected: `0 failed`.

- [ ] **Step 9: M1 exit check**

```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -1
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
VMD_AI_VMD_BIN=/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64 python -m pytest tests/test_live_vmd.py tests/test_tcl_net.py -q 2>&1 | tail -1
```

Expected: `B+78 passed` with 3 more skipped (the live tests) and `0 failed`, under 60 s; `90 passed`; `62 passed`; and the last line `0 failed`. Together with plans 01–05 this is the M1 exit of spec §8: S1 (plan 03's prior-context tests and Step 8), S3 (P06-T11 `test_kill_restart_one_notice_send_within_10s`), S4 (P06-T02, P06-T09 `test_reload_twice_after_info_empty`, plan 02's SIGTERM test), S5 and S6 (Step 8.9 and plans 03–04), S8 (P06-T03 `test_s8_unicode_round_trip_http_295`, this task's `test_live_unicode_round_trip_inside_vmd`), S10 (P06-T08 `test_puts_captured`, P06-T11 `test_puts_output_reaches_model`, plan 05's `save_path` tests), S11 and S12 (plan 02), and the named garbling cause in the note of Step 7.

- [ ] **Step 10: Commit**

```bash
git add tests/test_live_vmd.py docs/design/round1/garbling-root-cause.md
git commit -F - <<'MSG'
test(plugin): real-VMD checks and the named garbling cause; closes M1

tests/test_live_vmd.py (gated on VMD_AI_VMD_BIN) renders crambin with
TachyonInternal through the executor in headless VMD, round-trips
non-ASCII text through net::call inside VMD's own Tcl and http, and
checks that the installer's ~/.vmdrc block loads vmd_ai 2.0.
docs/design/round1/garbling-root-cause.md records what was ruled out,
the GUI reproduction and the named cause, and keeps the auto snapshot
renderer gated on a verified render snapshot.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

## Deviations from skeleton

Every task keeps the skeleton's id, files and test names; the points below are where the plan adds to or refines the skeleton, so plans 07–10 can check them against what they consume.

1. **`net::post_result call_key result_pairs` takes typed pairs, not a dict** (P06-T04). The executor builds the pairs (`tool_call_id s`, `ok b`, `executed s`, `output s`, `error s`, then the C3/C5 fields that have a value, `truncated b 1` when cut).
2. **Bridge additions** (P06-T07): `shutdown`, `note_outcome method kind args` (the single feed into the connection state machine, also used by the executor for `tool.ack`), `history_get chat_id callback`, and `_load_workdir`, which the M1 panel calls. `recover` resumes the chat through its own callback (`_on_recover_resume`), not through `resume`, so P09-T07's replay in `resume`'s success branch needs no extra argument. `resume` without a session answers its callback with the local code `rpc_error NOT_CONNECTED …`. Session changes (start, New Chat, Resume, recover) are serialised through `op_busy`/`op_queue`, and the pump does not poll while one runs.
3. **P06-T07 also edits `plugin/config.tcl`**: the legacy names kept for today's bridge (`host`, `port`, `poll_limit`, `runtime_log`, `python_exec`, `runtime_url`) are removed once nothing reads them. The poll limit (80) moves to `::vmdai::bridge::poll_limit`.
4. **Executor additions** (P06-T08): `note_cancelled request_id`, `ledger` and `clear_ledger` (the M1 panel's Save Tcl); `approve` treats a `tool_start` without `approval` as `auto`; a result that finishes after the net epoch changed is dropped instead of being posted to the new session; a `tool.ack` lost to a transport error is not retried (the runtime's 45 s pickup deadline reports it). Tool events run one at a time through the executor's own queue, in addition to the bridge holding `tool_start` back while `executing` is 1; a call whose ack reply an epoch change dropped (e.g. `resume` while an ack is in flight) is abandoned when the next `tool_start` arrives, so the queue cannot stall (`exec-epoch-1`). "Running: …" is painted only after the C3 pre-check passed (`exec-precheck-1` checks that an incomplete command paints nothing). P06-T08 also edits `plugin/init.tcl` (adds `executor` to the module list), which the skeleton's `files_modify` for P06-T08 leaves out.
5. **Between P06-T07 and P06-T10 the M1 panel does not work in VMD**: its buttons call bridge procs that P06-T07 removes. No test uses the panel before P06-T10; do not use the branch in VMD in between.
6. **P06-T09 tests**: `tests/tcl/test_init.tcl` (package, menu, start, S4 reload, stop) is wrapped by `tests/test_tcl_install.py`, which also holds the installer tests. `test_package_provide_2_0`, `test_menu_path_vmd_ai` and `test_reload_twice_after_info_empty` map to tcltest cases as listed there; `test_installer_idempotent` is joined by three installer tests (new file, consent, the block loading the plugin).
7. **Installer details the skeleton leaves open** (P06-T09): it asks for consent unless `--yes`, has `--dry-run` and `--uninstall`, backs the file up once, runs on Tcl 8.5, and, when it creates `~/.vmdrc`, starts the block with a line that plays `$env(VMDDIR)/.vmdrc`, because VMD reads only the first `.vmdrc` it finds (VMD user guide §14.3.3) and a new file would otherwise drop VMD's default menus and lights. The block's functional line is one `package require vmd_ai 2.0` guarded by `catch`.
8. **`plugin/ui.tcl` is replaced as a whole** (P06-T10) because the rewiring touches most of its procs; the layout, names and behaviour otherwise stay as today. It keeps the `-state disabled` transcript and today's widgets: the renamed-widget-command transcript, the 560×780 geometry and the other Panel rules of the global constraints describe the M2 panel that replaces this file in P09-T07. The mono-font rule is applied (first available of SF Mono, Menlo, DejaVu Sans Mono). `::vmdai::ui::win`, `show_panel`, `notify`, `render_event`, `set_busy` and `status` are the names plans 06 and 09 rely on; the other modules call no other `::vmdai::ui::` names.
9. **`helpers.tk`** (P06-T10): `VMD_AI_TK_LIB` names the Tk shared library to load instead of VMD.app's; Tk then finds its own script library. The prelude ends with `wm withdraw .`.
10. **P06-T11 is test-only and passes as written**: it checks P06-T02…T10 together against the real runtime. `ScriptedLoop` streams a turn's text a word at a time (so `has_more` can be exercised with a real queue). `serve_runtime(...).stop()` cancels requests and calls `_release_chat_lock` when present, reading `SessionManager._sessions`; the restarted runtime is the same process with the same pid, so the S3 test exercises recovery through `AUTH_FAILED` (P06-T06's `sm-newpid-1` covers the new-pid path). The driver runs under `helpers.tcl.run_tcl` with http 2.9.5 and json 1.1.2 loaded.
11. **P06-T12 adds `test_live_vmdrc_block_loads_plugin`** (the installer's block loading `vmd_ai 2.0` in real VMD) to the two skeleton live tests. The garbling note records evidence measured headless on 2026-09-25 (stored events intact, VMD's encoding, http and decode path intact) and turns the GUI reproduction into a decision table, so the named cause is the row the GUI probe selects. The `auto` renderer decision: M1 renders with TachyonInternal only, and `render snapshot` must pass the recorded GUI check before any `auto` renderer is built.
12. **First-half additions** (recorded here for plans 07–10): `::vmdai::runtime::stop ?-sync?` (blocking wait for `reload`/`cleanup`), `::vmdai::runtime::on_auth_failed`, `net::http_get` ignoring the epoch so health probes are never dropped, `runtime::backoff_ms`, `config::require_json`, `config::_json_quote`, `config::plugin_defaults`, and `FakeRpcServer`'s `Reply`, `Recorded`, `ensure_ascii` and `health`. `runtime.tcl` defines `::vmdai::runtime::info`, so code in that namespace calls `::info`. When the third and last respawn fails to start, the state ends as `down` with reason `didnt_start` (not `unreachable`), so the "Runtime didn't start" banner can show the pipe tail.
13. **Suite time**: plan 06 adds about 22 s to `SUITE` on the dev Mac (T01–T06 about 10 s, T07–T11 about 12 s, T12 skips without its gate).

