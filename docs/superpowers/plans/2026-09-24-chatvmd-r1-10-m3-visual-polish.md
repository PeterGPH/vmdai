# ChatVMD Round 1 — Plan 10: ChatVMD R1 — M3 visual polish

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dark mode and appearance events, Tcl syntax colours, minimal markdown, the usage display, final Tk goldens, and a visual review against the Native screenshots A–G.

**Architecture:** Everything lands in the plugin (Tcl/Tk) and its tests; the runtime is untouched. `theme.tcl` gains the full light/dark palette, an Appearance setting (`system|light|dark`) and a retint pass that swaps every token colour already drawn in ChatVMD's own windows (widgets, text tags, canvas items, `ChatVMD.*` styles) and follows `<<LightAqua>>`/`<<DarkAqua>>`/`<<AppearanceChanged>>`. Two new pure-Tcl modules, `syntax.tcl` (Tcl tokens) and `markdown.tcl` (the V4 subset → spans, plus a Tk renderer), are wired into the transcript at two seams: the step detail's command bytes and the `block.seal` op. The view-model fills the run footer's `usage_text`, and new Tk goldens plus a capture tool close round 1 with a recorded visual review.

**Tech Stack:** Tcl 8.6 (8.5-safe subset, lint-checked), Tk 8.6.12 from VMD.app loaded into tclsh 8.6, tcltest 2, VMD's http 2.9.5 and the vendored json 1.1.2; Python 3.9/3.12 + pytest for the wrappers; `screencapture`/`sips` (macOS) for the manual review only.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — this plan implements Part B **V1** (the console `syntax::tokens` graft, the cards `md::inline` NBSP graft, the reference screenshots), **V2** (Tokens: the dark column, System/forced appearance, contrast), **V4** (Markdown; Step detail syntax colours; Run footer usage line), **V7** (Appearance without MacWindowStyle), **V8** (Visual tests: md-1/2, theme-1 and the "Add" list); Part A **§2c** Usage semantics (never "context used"), **§2h** (theme.tcl M3 row, markdown.tcl), **§6** Tk golden transcripts, **§8** M3 row and exit (visual review against `docs/design/round1/screenshots/native/` states A–G with the grafts), **Success** (S1–S12 plus the visual review). Part C wins where it conflicts with Parts A/B (no Part C item changes M3).

**Branch:** `chatvmd-r1-10-m3-visual-polish`, created from `main` after plan 09 (`chatvmd-r1-09-m2-panel-assembly`) is merged.

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

**Plan-specific constraints (Plan 10):**

- M3 touches only `plugin/`, `tests/` and `docs/design/round1/`. `git diff main -- runtime/ integrations/ vmdbench/ scripts/` is empty at the end of the plan.
- Every non-ASCII character in new plugin Tcl is written as a `\uXXXX` escape (the files stay ASCII, whatever encoding VMD sources them with). New plugin files pass `tests/test_tcl_lint.py`.
- A theme switch changes only ChatVMD's own toplevels: `.vmd_ai*` / `.vmdai*` windows, windows registered with `::vmdai::theme::own`, and windows whose widgets use a `Chat*` named font or a `ChatVMD.*` style. VMD's windows and other plugins (QwikMD) keep their colours (P10-T01 `dark-other_windows_untouched`).
- No test reads or changes the real OS appearance: `tests/tcl/panel_harness.tcl` and P09's end-to-end `tests/tcl/panel_driver.tcl` point `::vmdai::theme::macstyle` at a command that does not exist, and M3 tests that need MacWindowStyle install the recording stand-in `::m3::mws`.
- Tk tests stay headless (`::vmdai::panel::headless 1`, windows withdrawn) and take no screenshots. Only the P10-T07 capture tool maps a window and runs `screencapture`, and only through `docs/design/round1/tools/capture_locked.sh`.
- Geometry-sensitive Tk checks (wrapping, right tab stops) use a Text packed into the withdrawn root window `.`: on aqua only `.` gets its real size while withdrawn; a withdrawn child toplevel stays 1×1 (measured with VMD's Tk 8.6.12 while planning).
- Each golden regeneration step names the files it may change and what may change in them; review `git diff` against that list before committing.
- Test code also runs on Python 3.9 (CI's 3.9 job): no `X | Y` evaluated at run time, no `match`; keep `from __future__ import annotations`.

## Review Focus

These five inputs are the most likely to bite a user; each is pinned by a test in its owning task.

1. The appearance changes while Settings is open: both windows repaint. Owner P10-T01: `tests/test_tk_dark.py::test_appearance_event_repaints_dialogs` (tcltest `dark-events_repaint_dialogs`).
2. An unclosed ``` or ** stays literal text and raises nothing. Owner P10-T03: `tests/test_tcl_markdown.py::test_unclosed_markers_literal` (tcltest `md-literal-1..4`).
3. Inline code never wraps in a narrow window. Owner P10-T04: `tests/test_tk_markdown_render.py::test_inline_code_never_wraps` (tcltest `md-inline-nowrap`, a 380 px window, the code span swept across every wrap position).
4. A null usage omits the line rather than showing '0 out'. Owner P10-T05: `tests/test_tk_usage_footer.py::test_null_usage_omitted`.
5. On Tk 8.5 / X11 (no MacWindowStyle) only Light and Dark are offered, with no errors. Owner P10-T01: `tests/test_tk_dark.py::test_no_macwindowstyle` (tcltest `dark-no_macwindowstyle`).

## Consumed contract (plans 06–09)

The skeleton names the interfaces this plan consumes; the rows below also fix the details it relies on. Task 0 checks every row. **If a Task 0 check fails, stop**: the plan-06..09 code differs from what this plan was written against, and the difference must be reconciled (and recorded in the PR description) before Task P10-T01. Rows marked *anchor* are edited in place by a later task; Task 0 Step 6 prints them.

| Interface (owner) | Detail this plan relies on | Task 0 check |
|---|---|---|
| `::vmdai::theme::init ?mode?`, `c token`, `paint w option token`, `repaint`, `mode`, `mono_family` (P08-T04) | `init` fills the namespace array `::vmdai::theme::T` (token → colour) and sets the namespace variable `::vmdai::theme::mode`; `c` reads `T`; `mode` returns that variable; named fonts `ChatBody ChatBodyBold ChatMeta ChatH2 ChatCode` exist after `init`. Only `_set_token`/`_set_mode` (P10-T01) write this storage. M2 also defines `_apply w spec` (the helper `paint`/`repaint` call), so M3 never reuses that name (P10-T01's mode switch is `_apply_mode`). | `pre-theme-storage` |
| `::vmdai::transcript::create path` (P08-T05; P09 contract row) | returns the read-only Text; its proxy refuses `insert`/`delete`/`replace` and passes every other subcommand (`tag`, `mark`, `index`, `get`, `cget`, `configure`, `search`) | `pre-proxy` |
| `::vmdai::transcript::apply_ops`, `dump`, `clear`, `relayout`, `toggle_detail call_key`, `set_expand_all bool` (P08-T05/T06) | `dump` takes no argument and returns the current transcript as text | `pre-procs` |
| *anchor S5* — the `block.seal` op handler `op_block.seal b canonical` in `plugin/transcript.tcl` (P08-T05) | exactly one statement, `$W insert $at $text $tags`, writes the sealed text; `$W` is the writable widget command (the real widget renamed to `::vmdai::transcript::_w`) | `pre-seal` + Step 6 |
| *anchor S4* — the step-detail builder `_build_detail k` in `plugin/transcript.tcl` (P08-T06) | the one proc that inserts `detail:$k`, at the mark `dins:$k`; each command segment from `_cmd_lines` (the executor's `split_statements`) is written by `$W insert dins:$k $text [concat $base dcode $class]` | Step 6 |
| *anchor S6* — `::vmdai::vm::_close_run` (P08-T01), called by `_on_request_finished` (P08-T03), and `::vmdai::transcript::op_footer run applied usage_text` (P08-T06) | `_close_run` appends `[list footer <run> <applied> ""]` only when `applied > 0`; `op_footer` returns early when `applied < 1` and ignores `usage_text` (`pre-footer` prints both facts) | `pre-footer` + Step 6 |
| `::vmdai::vm::init stateVar ?options?`, `apply stateVar event`, `local_event kind fields` (P08-T01..T03) | `apply` takes a §2c envelope decoded with `json::json2dict` (metadata a nested dict) | `pre-seal` |
| *anchor S3* — `::vmdai::panel::build` (P09-T01) | calls `::vmdai::theme::init` on one line before creating the toplevel; `render ops`, `text`, `win` (`.vmd_ai`), `headless`, `vm`, `open_settings ?tab? ?prefill?`, `set_title`, `set_busy`, `show` | `pre-procs` + Step 6 |
| *anchor S8* — `::vmdai::panel::copy_selection` (P09-T03) | builds the clipboard text with `set s [string map [list "\t" "  "] $s]` and hands it to `_set_clipboard` (P09-T01; the harness's `stub_desktop` records it in `::harness::clipboard`) | Step 6 |
| *anchor S7* — `plugin/settings.tcl` (P09-T04/T05) | dialog `.vmd_ai_settings`; `tab panel` → the Panel tab frame; its combobox `$p.appearance` shows `v(appearance_label)` from `appearance_values`; `_load_panel_prefs` sets `v(appearance)`/`v(appearance_label)`; `save_steps` returns a list ending in `_finish_save`; `_save_plugin_prefs` writes `appearance` to plugin.json | `pre-procs` + Step 6 |
| `tests/tcl/panel_harness.tcl`, `tests/helpers/tk_cases.py` (P09-T01) | `::harness::fresh_panel`, `settle`, `stub_bridge`, `stub_desktop`, `::fake::*`, `::harness::busy`, `::harness::runtime_state`, `::harness::clipboard`; `run_tk_file(name, env=None)`, `assert_case(result, case, total)`, `failed_cases(result)` | `pre-harness` |
| `helpers.tk` `update_goldens()`, `golden_path(name)` (P06-T10); `helpers.tcl` `run_tcl`, `run_tcltest`, `tcl_word` (P01-T03) | `golden_path("x")` is `tests/fixtures/tk/x.txt` | `test_helpers_present` |
| `tests/fixtures/events/*.jsonl` (P07-T08) | five scenarios; one `json.dumps(event, sort_keys=True, ensure_ascii=True)` envelope per line; `@REPO@`/`@WORK@` placeholders; 03_conversation's first request has four tool calls (the fourth a snapshot) and its first final answer is `Loaded **1hck** as a cartoon on a white background.` | `pre-fixtures` |
| `::vmdai::config::load_plugin_settings`, `save_plugin_settings dict`, `log msg`; `::vmdai::sched::after_idle script` (P06-T02) | `load` returns a dict | `pre-procs` |

## File map

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `plugin/theme.tcl` | modify (append) | T01, T02 | dark palette, Appearance, retint, system events; `syntax_tags` |
| `plugin/settings.tcl` | modify | T01 | Appearance choices from the theme; apply on Save |
| `plugin/panel.tcl` | modify | T01, T04 | apply the saved appearance at build; NBSP-free copy |
| `tests/tcl/panel_harness.tcl`, `tests/tcl/panel_driver.tcl` | modify | T01 | never read the real OS appearance |
| `tests/tcl/m3_helpers.tcl` | create | T01 (extended T06) | `::m3::*`: MacWindowStyle stand-in, fixture replay, colour census, dumps; T06 adds portable dumps, plugin.json appearance, a root-window transcript |
| `tests/tcl/test_dark.tcl`, `tests/test_tk_dark.py` | create | T01 | dark mode and appearance events |
| `tests/test_theme_contrast.py` | create | T01 | exact V2 values and contrast ratios (pure Python) |
| `plugin/syntax.tcl` | create | T02 | `::vmdai::syntax::tokens`, `highlight`, `highlight_tag` (pure Tcl) |
| `plugin/transcript.tcl` | modify | T02, T04, T05 | source syntax/markdown; step-detail colours; render on seal; `op_footer` with the usage line |
| `tests/tcl/test_syntax.tcl`, `tests/tcl/test_syntax_detail.tcl`, `tests/test_tcl_syntax.py` | create | T02 | tokens (tclsh) and step-detail colours (Tk) |
| `plugin/markdown.tcl` | create (T03), extend (T04) | T03, T04 | `::vmdai::md::spans` (pure); `render_into`, `copy_at`, `plain_text` (Tk) |
| `tests/tcl/test_markdown.tcl`, `tests/test_tcl_markdown.py` | create | T03 | spans (tclsh) |
| `tests/tcl/test_markdown_render.tcl`, `tests/test_tk_markdown_render.py` | create | T04 | rendering (Tk) |
| `plugin/viewmodel.tcl` | modify | T05 | `::vmdai::vm::usage_text`; `_close_run`'s footer op carries it |
| `tests/tcl/test_usage_footer.tcl`, `tests/test_tk_usage_footer.py` | create | T05 | usage line |
| `tests/fixtures/tk/03_conversation.txt`, `reasoning_answer.txt`, `panel_03_conversation.txt`, `panel_resume_replay.txt` | regenerate | T02 (`03_conversation.txt` only), T04, T05 | step-detail syntax tags; sealed prose rendered; usage lines |
| `tests/fixtures/ops/*.ops` | regenerate | T05 | footer ops carry `usage_text` |
| `tests/tcl/test_v8_additions.tcl`, `tests/test_tk_v8_additions.py` | create | T06 | V8 add list, golden replay |
| `tests/fixtures/tk/03_conversation_dark.txt`, `loop_guard.txt`, `turn_retry.txt`, `11_dead_runtime.txt` | create | T06 | final goldens |
| `docs/design/round1/tools/capture_panel.tcl` | create | T07 | the real panel in states A–G, screenshotted |
| `docs/design/round1/screenshots/panel/{A_light,B_dark,C_midrun,D_empty,E_settings,F_narrow,G_disconnected}.png` | create | T07 | the review captures |
| `docs/design/round1/visual-review.md` | create | T07 | the review record |

Expected `tests/` totals on the dev Mac (GUI session, so Tk tests run), relative to the baseline `B` recorded in Task 0: T01 `B+23`, T02 `B+27`, T03 `B+29`, T04 `B+37`, T05 `B+43`, T06 `B+55`, T07 `B+55`. Without a GUI session the Tk-backed tests skip and only the pure ones count (`B+15`, `B+16`, `B+18`, `B+18`, `B+22`, `B+24`, `B+24`).

---

### Task 0: Pre-flight — confirm plans 06–09 are merged and the consumed contract holds

**Files:**
- Create (temporary, never committed): `tests/tcl/zz_preflight_10.tcl`, `tests/test_zz_preflight_10.py`

**Interfaces:**
- Consumes: every row of the "Consumed contract" table.
- Produces: the baseline pass count `B`, the `footer_usage_rendered` / `footer_links_when_zero` values P10-T05 Step 5 checks (plan 08 as written gives `0` and `0`), and the anchor listing (S3–S8) that Tasks P10-T01, T02, T04 and T05 edit.

- [ ] **Step 1: Cut the branch and record the baseline**

Run:
```bash
git switch main
git log --oneline -3
git switch -c chatvmd-r1-10-m3-visual-polish
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -3
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
```
Expected: the log shows plan 09's merge on top; the `tests` line reads `B passed, S skipped in …s` with **0 failed** and a time under 60 s (write `B` and the time down); `90 passed`; `62 passed`. Run this plan from a GUI login session on the dev Mac, otherwise every Tk test skips.

- [ ] **Step 2: Confirm the files plans 06–09 created**

Run:
```bash
for f in config sched net runtime bridge executor theme viewmodel transcript viewer composer statusbar banner toolbar tclexport panel settings history ui init; do
  test -f plugin/$f.tcl || echo "MISSING plugin/$f.tcl"; done
for f in plugin/lib/json/json.tcl tests/helpers/tcl.py tests/helpers/tk.py tests/helpers/tk_cases.py \
         tests/tcl/panel_harness.tcl tests/tcl/panel_driver.tcl tests/test_tcl_lint.py tests/test_tcl_viewmodel.py \
         tests/test_tk_transcript.py tests/test_panel_integration.py \
         tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt \
         tests/fixtures/tk/panel_03_conversation.txt tests/fixtures/tk/panel_resume_replay.txt; do
  test -f $f || echo "MISSING $f"; done
for s in 03_conversation 11_dead_runtime reasoning_answer turn_retry loop_guard; do
  test -f tests/fixtures/events/$s.jsonl || echo "MISSING events/$s"
  test -f tests/fixtures/ops/$s.ops || echo "MISSING ops/$s"; done
test ! -e plugin/syntax.tcl && test ! -e plugin/markdown.tcl || echo "UNEXPECTED syntax/markdown already present"
```
Expected: no output.

- [ ] **Step 3: Write the Tcl contract check**

Create `tests/tcl/zz_preflight_10.tcl`:

```tcl
# Temporary pre-flight for plan 10 (never committed): the plan-06..09 details
# listed in the plan's "Consumed contract" table.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::pf {}
proc ::pf::ev {role type text meta} {
    return [dict create seq 0 ts 1790208000.0 role $role type $type text $text \
        metadata [dict merge [dict create v 2] $meta]]
}

test pre-procs {every consumed proc exists} -body {
    set missing {}
    foreach p {
        ::vmdai::theme::init ::vmdai::theme::c ::vmdai::theme::paint ::vmdai::theme::repaint
        ::vmdai::theme::mode ::vmdai::theme::mono_family
        ::vmdai::transcript::create ::vmdai::transcript::apply_ops ::vmdai::transcript::dump
        ::vmdai::transcript::clear ::vmdai::transcript::relayout ::vmdai::transcript::toggle_detail
        ::vmdai::transcript::set_expand_all ::vmdai::transcript::show_empty_state
        ::vmdai::vm::init ::vmdai::vm::apply ::vmdai::vm::local_event
        ::vmdai::panel::build ::vmdai::panel::render ::vmdai::panel::show ::vmdai::panel::set_title
        ::vmdai::panel::set_busy ::vmdai::panel::open_settings ::vmdai::panel::copy_selection
        ::vmdai::settings::open ::vmdai::settings::tab ::vmdai::settings::appearance_values
        ::vmdai::settings::save_steps ::vmdai::settings::_load_panel_prefs
        ::vmdai::settings::_save_plugin_prefs ::vmdai::settings::_finish_save
        ::vmdai::composer::set_text ::vmdai::statusbar::update ::vmdai::banner::on_runtime_state
        ::vmdai::config::load_plugin_settings ::vmdai::config::save_plugin_settings
        ::vmdai::config::log ::vmdai::sched::after_idle
    } {
        if {[info commands $p] eq ""} { lappend missing $p }
    }
    set missing
} -result {}

test pre-theme-storage {init fills ::vmdai::theme::T and ::vmdai::theme::mode} -body {
    ::vmdai::theme::init light
    set r [list [array exists ::vmdai::theme::T] \
        [expr {[::vmdai::theme::c surface] eq $::vmdai::theme::T(surface)}] \
        [expr {[::vmdai::theme::mode] eq $::vmdai::theme::mode}] [::vmdai::theme::mode]]
    foreach f {ChatBody ChatBodyBold ChatMeta ChatH2 ChatCode} {
        lappend r [expr {$f in [font names]}]
    }
    set r
} -result {1 1 1 light 1 1 1 1 1}

test pre-proxy {the transcript proxy refuses edits and passes tag/mark/index} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    set before [$t get 1.0 end]
    $t insert end INJECTED
    $t mark set pf_probe 1.0
    $t tag add pf_tag 1.0
    list [expr {[$t get 1.0 end] eq $before}] [expr {"pf_probe" in [$t mark names]}] \
        [$t index pf_probe] [expr {"pf_tag" in [$t tag names]}] [winfo class $t]
} -result {1 1 1.0 1 Text}

test pre-seal {a chunk then its assistant/message leaves the canonical text once} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    set rid req_000000000077
    foreach ev [list \
        [::pf::ev system state "" [dict create kind request.started request_id $rid \
            chat_id chat_000000000077 provider ollama model qwen3.8:27b max_turns 28 vision true think false]] \
        [::pf::ev assistant chunk "draft words" [dict create request_id $rid turn 1]] \
        [::pf::ev assistant message "Final **text** here." [dict create request_id $rid turn 1 final true]]] {
        ::vmdai::panel::render [::vmdai::vm::apply ::vmdai::panel::vm $ev]
    }
    set all [$t get 1.0 end]
    list [llength [regexp -all -inline {Final \*\*text\*\* here\.} $all]] [string first "draft" $all]
} -result {1 -1}

test pre-footer {report whether the M2 transcript prints usage_text and links for applied 0} -body {
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    ::vmdai::transcript::apply_ops [list \
        [list run.open r_pf req_000000000078 qwen3.8:27b 1790208000] \
        [list run.close r_pf complete 0 0 0 1 false] \
        [list footer r_pf 0 "7 evaluated"]]
    set all [$t get 1.0 end]
    set usage [expr {[string first "7 evaluated" $all] >= 0}]
    set links [expr {[string first "Copy Tcl" $all] >= 0}]
    puts [::tcltest::outputChannel] "PF footer_usage_rendered=$usage footer_links_when_zero=$links"
    list [string is boolean $usage] [string is boolean $links]
} -result {1 1}

test pre-fixtures {03_conversation has the content later tasks rely on} -body {
    set fh [open [file join $env(VMDAI_REPO) tests fixtures events 03_conversation.jsonl] r]
    set text [read $fh]
    close $fh
    list [expr {[string first {Loaded **1hck** as a cartoon on a white background.} $text] >= 0}] \
         [regexp -all {"kind": "tool.started"} $text] [regexp -all {"kind": "request.finished"} $text]
} -result {1 5 2}

test pre-harness {the plan-09 harness pieces this plan uses} -body {
    set missing {}
    foreach p {::harness::fresh_panel ::harness::settle ::harness::stub_bridge ::harness::stub_desktop
               ::fake::reply ::fake::calls_of ::fake::param} {
        if {[info commands $p] eq ""} { lappend missing $p }
    }
    list $missing [info exists ::harness::busy] [info exists ::harness::runtime_state] \
        [info exists ::harness::clipboard] $::vmdai::panel::headless
} -result {{} 1 1 1 1}

cleanupTests
```

- [ ] **Step 4: Write the Python contract check**

Create `tests/test_zz_preflight_10.py`:

```python
"""Temporary pre-flight for plan 10 (never committed)."""
from __future__ import annotations

import re
from pathlib import Path

from helpers import tcl, tk
from helpers.tk_cases import run_tk_file

REPO = Path(__file__).resolve().parents[1]


def test_helpers_present():
    assert tk.golden_path("x") == REPO / "tests" / "fixtures" / "tk" / "x.txt"
    assert callable(tk.update_goldens)
    assert callable(tcl.run_tcl) and callable(tcl.run_tcltest) and callable(tcl.tcl_word)


def test_tcl_contract():
    result = run_tk_file("zz_preflight_10.tcl")
    print(re.findall(r"PF \S+ \S+", result.output))
    assert result.failed == 0 and result.passed == 7, result.output
```

- [ ] **Step 5: Run the contract checks**

Run: `python -m pytest tests/test_zz_preflight_10.py -q -s`
Expected: `2 passed`, and the printed list holds one string `PF footer_usage_rendered=<0|1> footer_links_when_zero=<0|1>`. Write both values down: plan 08 as written gives `0` and `0` (its `op_footer` returns early when `applied < 1` and ignores `usage_text`), which is what P10-T05 Step 5 is written for; other values mean plan 08's footer changed, and Step 5 says how to adapt. If any case fails, stop and reconcile (see "Consumed contract").

- [ ] **Step 6: Print the anchors later tasks edit**

Run:
```bash
echo "== S1 theme storage";   grep -n 'variable T\b\|variable mode\b\|array set T\|proc ::vmdai::theme::' plugin/theme.tcl
echo "== S3 panel build";     grep -n '::vmdai::theme::init' plugin/panel.tcl
echo "== S4 step detail";     grep -n 'detail:\|_build_detail\|dcode' plugin/transcript.tcl
echo "== S5 seal";            grep -n 'block.seal' plugin/transcript.tcl
echo "== S6 footer";          grep -n 'footer\|_close_run' plugin/viewmodel.tcl plugin/transcript.tcl
echo "== S7 settings";        grep -n 'proc ::vmdai::settings::appearance_values\|appearance_label) \[string totitle\|proc ::vmdai::settings::save_steps' -A 3 plugin/settings.tcl
echo "== S8 copy";            grep -n 'proc ::vmdai::panel::copy_selection' -A 7 plugin/panel.tcl
echo "== module sourcing";    grep -n 'transcript' plugin/init.tcl tests/tcl/*.tcl | grep -i source
```
Expected: every section prints at least one line. Keep the output next to the plan: P10-T01 (S3, S7), P10-T02 (S4), P10-T04 (S5, S8) and P10-T05 (S6) quote these anchors. In S5, find the one `insert` statement in `op_block.seal` that writes the canonical text (`$W insert $at $text $tags` in plan 08); in S4, `_build_detail` and its `dcode` segment insert; in S6, `_close_run`'s `footer` op and `op_footer`. When a listing differs from the statement the task quotes, the task's fallback sentence says how to apply the same change.

- [ ] **Step 7: Remove the temporary files**

Run:
```bash
rm tests/test_zz_preflight_10.py tests/tcl/zz_preflight_10.tcl
git status --short
```
Expected: no output (nothing to commit).

---

### Task P10-T01: Dark tokens and appearance events

**Files:**
- Modify: `plugin/theme.tcl` (append the M3 section at the end of the file; M2's procs are not edited)
- Modify: `plugin/settings.tcl` (anchor S7: the body of `appearance_values`, one `if` in `_load_panel_prefs`, the list `save_steps` returns; append `_apply_appearance`)
- Modify: `plugin/panel.tcl` (anchor S3: one line after `::vmdai::theme::init` in `build`)
- Modify: `tests/tcl/panel_harness.tcl` (one line after the module `source` loop)
- Modify: `tests/tcl/panel_driver.tcl` (one line after it sources `init.tcl`)
- Create: `tests/tcl/m3_helpers.tcl`
- Create: `tests/tcl/test_dark.tcl`
- Create: `tests/test_theme_contrast.py`
- Test: `tests/test_tk_dark.py`

**Interfaces:**
- Consumes: paint registry (P08-T04) — `::vmdai::theme::init ?mode?`, `c token`, `repaint`, `mode`, storage `::vmdai::theme::T` / `::vmdai::theme::mode`; `::vmdai::config::load_plugin_settings`, `log` and `::vmdai::sched::after_idle` (P06-T02); `::vmdai::panel::build`, `render`, `text`, `vm` and the Settings chain `appearance_values`, `_load_panel_prefs`, `save_steps`, `_fail`, `v(appearance)` (P09-T01/T05); `::harness::*`, `::fake::*`, `run_tk_file`, `assert_case` (P09-T01); the event fixtures (P07-T08).
- Produces: `::vmdai::theme::set_appearance system|light|dark` (any case; returns the mode now in effect; errors on anything else). Also `::vmdai::theme::PALETTE` (dict `light`/`dark` → token → `#rrggbb`), `palette mode -> dict`, `appearance -> system|light|dark`, `appearance_choices -> {System Light Dark}|{Light Dark}`, `has_macwindowstyle -> 0|1`, `system_is_dark -> 0|1`, `effective setting -> light|dark`, `saved_appearance -> system|light|dark`, `own toplevel`, `owned_toplevels -> list`, `bind_system_events`, `on_system_event hint`, the variable `::vmdai::theme::macstyle` (command prefix, default `::tk::unsupported::MacWindowStyle`); `::vmdai::settings::_apply_appearance k`. Test helpers in `tests/tcl/m3_helpers.tcl`: `::m3::mws`, `use_mws`, `os_dark`, `mws_calls`, `m2_tokens`, `events name`, `render ev`, `replay name ?upto?`, `ev role type text meta`, `call_key_of name n`, `root_text ?geom?`, `ranges_text t tag`, `colours roots`, `light_only`, `repaint_report before after`, `colour_section t`, `write_dump name text`.

- [ ] **Step 1: Write the shared M3 test helpers**

Create `tests/tcl/m3_helpers.tcl`:

```tcl
# tests/tcl/m3_helpers.tcl - shared helpers for the plan-10 (M3) Tk tests and
# the P10-T07 capture tool.  Source it after tests/tcl/panel_harness.tcl.
#
#   ::m3::mws args            recording stand-in for MacWindowStyle
#   ::m3::use_mws             install it; "isdark" answers $::m3::os_dark
#   ::m3::events name         envelopes of tests/fixtures/events/<name>.jsonl
#   ::m3::replay name ?upto?  fresh headless panel, events 0..upto rendered
#   ::m3::ev ... / render ev  one synthetic §2c event through the panel
#   ::m3::call_key_of name n  call_key of the n-th tool.started of a fixture
#   ::m3::root_text ?geom?    a Text packed in "." (real size while withdrawn)
#   ::m3::colours roots       every #rrggbb on widgets, tags, items, styles
#   ::m3::colour_section t / write_dump name text   golden dumps

namespace eval ::m3 {
    variable os_dark 0
    variable mws_calls {}
    variable m2_tokens {}
}

proc ::m3::mws {args} {
    variable mws_calls
    variable os_dark
    lappend mws_calls $args
    if {[lindex $args 0] eq "isdark"} {
        return $os_dark
    }
    return ""
}

proc ::m3::use_mws {} {
    set ::m3::os_dark 0
    set ::m3::mws_calls {}
    set ::vmdai::theme::macstyle ::m3::mws
}

# The fixture's @REPO@/@WORK@ placeholders become this checkout and $HOME.
proc ::m3::events {name} {
    set esc [list "\\" "\\\\" "\"" "\\\""]
    set repo [string map $esc $::env(VMDAI_REPO)]
    set work [string map $esc $::env(HOME)]
    set fh [open [file join $::env(VMDAI_REPO) tests fixtures events $name.jsonl] r]
    fconfigure $fh -encoding utf-8
    set out {}
    while {[gets $fh line] >= 0} {
        if {[string trim $line] eq ""} {
            continue
        }
        lappend out [::json::json2dict [string map [list @REPO@ $repo @WORK@ $work] $line]]
    }
    close $fh
    return $out
}

proc ::m3::render {ev} {
    ::vmdai::panel::render [::vmdai::vm::apply ::vmdai::panel::vm $ev]
}

proc ::m3::replay {name {upto end}} {
    ::harness::fresh_panel
    foreach ev [lrange [events $name] 0 $upto] {
        render $ev
    }
    ::harness::settle
    return $::vmdai::panel::text
}

proc ::m3::ev {role type text meta} {
    return [dict create seq 0 ts 1790208000.0 role $role type $type text $text \
        metadata [dict merge [dict create v 2] $meta]]
}

proc ::m3::call_key_of {name n} {
    set i 0
    foreach ev [events $name] {
        set meta [dict get $ev metadata]
        if {[dict exists $meta kind] && [dict get $meta kind] eq "tool.started" && [incr i] == $n} {
            return [dict get $meta call_key]
        }
    }
    error "$name has fewer than $n tool.started events"
}

# Only "." gets its real size while withdrawn (a withdrawn child toplevel
# stays 1x1 on aqua), so wrapping and tab-stop checks use a Text in ".".
proc ::m3::root_text {{geom 560x780}} {
    foreach w [winfo children .] {
        if {[winfo toplevel $w] eq "."} {
            destroy $w
        }
    }
    wm geometry . $geom
    text .m3md -wrap word -font ChatBody -padx 20 -pady 14 -width 10 -height 10 \
        -background [::vmdai::theme::c surface] -foreground [::vmdai::theme::c text]
    pack .m3md -fill both -expand 1
    update idletasks
    update
    return .m3md
}

proc ::m3::ranges_text {t tag} {
    set out {}
    foreach {a b} [$t tag ranges $tag] {
        lappend out [$t get $a $b]
    }
    return $out
}

proc ::m3::_colour_entries {where specs} {
    set out {}
    foreach s $specs {
        if {[llength $s] == 5 && [regexp {^#[0-9a-fA-F]{6}$} [lindex $s 4]]} {
            lappend out [list "$where [lindex $s 0]" [string tolower [lindex $s 4]]]
        }
    }
    return $out
}

# colours roots -> {where value} for every #rrggbb on the widgets, text tags,
# canvas items and ChatVMD.* styles of the toplevels in roots.
proc ::m3::colours {roots} {
    set out {}
    set styles {}
    foreach top $roots {
        foreach w [::vmdai::theme::_subtree $top] {
            if {![catch {$w configure} specs]} {
                set out [concat $out [_colour_entries $w $specs]]
            }
            switch -- [winfo class $w] {
                Text {
                    foreach tag [$w tag names] {
                        set out [concat $out [_colour_entries "$w tag:$tag" [$w tag configure $tag]]]
                    }
                }
                Canvas {
                    foreach id [$w find all] {
                        set out [concat $out [_colour_entries "$w item:$id" [$w itemconfigure $id]]]
                    }
                }
            }
            if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]
                    && [lsearch -exact $styles $st] < 0} {
                lappend styles $st
            }
        }
    }
    foreach st $styles {
        foreach {opt val} [ttk::style configure $st] {
            if {[regexp {^#[0-9a-fA-F]{6}$} $val]} {
                lappend out [list "style:$st $opt" [string tolower $val]]
            }
        }
    }
    return $out
}

# Light values that differ from their dark value and are no dark value at all.
proc ::m3::light_only {} {
    set p $::vmdai::theme::PALETTE
    set darkvals [dict values [dict get $p dark]]
    set out {}
    dict for {tok v} [dict get $p light] {
        if {$v ne [dict get $p dark $tok] && [lsearch -exact $darkvals $v] < 0} {
            lappend out $v
        }
    }
    return [lsort -unique $out]
}

# repaint_report before after -> {moved left notdark}: how many light-only
# colours `before` had, the places still light-only after, and the moved
# places whose new value is not a dark palette colour.
proc ::m3::repaint_report {before after} {
    set lo [light_only]
    set dv [lsort -unique [dict values [dict get $::vmdai::theme::PALETTE dark]]]
    set moved {}
    foreach e $before {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend moved [lindex $e 0]
        }
    }
    set left {}
    foreach e $after {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend left [lindex $e 0]
        }
    }
    set notdark {}
    foreach k $moved {
        set i [lsearch -exact -index 0 $after $k]
        if {$i < 0 || [lsearch -exact $dv [lindex $after $i 1]] < 0} {
            lappend notdark $k
        }
    }
    return [list [llength $moved] $left $notdark]
}

proc ::m3::colour_section {t} {
    set lines {}
    foreach tag [lsort [$t tag names]] {
        if {$tag eq "sel"} {
            continue
        }
        foreach opt {-foreground -background -lmargincolor -rmargincolor} {
            if {[catch {$t tag cget $tag $opt} v] || $v eq ""} {
                continue
            }
            lappend lines "$tag $opt $v"
        }
    }
    return "# tag colours\n[join $lines \n]\n"
}

proc ::m3::write_dump {name text} {
    set fh [open [file join $::env(M3_OUT) $name.txt] w]
    fconfigure $fh -encoding utf-8 -translation lf
    puts -nonewline $fh $text
    close $fh
}

# The tokens M2's theme defines, before any set_appearance adds M3's.
if {![llength $::m3::m2_tokens]} {
    ::vmdai::theme::init light
    set ::m3::m2_tokens [lsort [array names ::vmdai::theme::T]]
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/tcl/test_dark.tcl`:

```tcl
# P10-T01: dark tokens and appearance events (Part B V2, V7).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop
testConstraint aquaWs [expr {[tk windowingsystem] eq "aqua"}]

test theme-1 {dark palette swaps tokens; every item re-renders without error} -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
} -body {
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    set r [list [::vmdai::theme::mode] [::vmdai::theme::c surface] [$t cget -background]]
    ::vmdai::theme::set_appearance light
    ::vmdai::transcript::relayout
    ::harness::settle
    lappend r [::vmdai::theme::mode] [$t cget -background]
} -result {dark #1e1e1e #1e1e1e light #ffffff}

test dark-events_repaint_dialogs {an appearance event while Settings is open repaints the panel and the dialog} -constraints aquaWs -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
    ::vmdai::theme::set_appearance system
    set dlg [::vmdai::settings::open model]
    ::harness::settle
    set roots [list $::vmdai::panel::win $dlg]
    set before [::m3::colours $roots]
} -body {
    set ::m3::os_dark 1
    event generate $dlg <<DarkAqua>> -when tail
    ::harness::settle
    set report [::m3::repaint_report $before [::m3::colours $roots]]
    list [::vmdai::theme::mode] [expr {[lindex $report 0] > 0}] [lindex $report 1] [lindex $report 2] \
        [expr {$dlg in [::vmdai::theme::owned_toplevels]}]
} -cleanup {
    ::vmdai::settings::close
    set ::m3::os_dark 0
    ::vmdai::theme::set_appearance light
} -result {dark 1 {} {} 1}

test dark-no_macwindowstyle {without MacWindowStyle only Light and Dark are offered, with no errors} -setup {
    set ::vmdai::theme::macstyle ::m3::no_such_command
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance system \
        expand_steps 0 geometry 560x780]
} -body {
    set r [list [::vmdai::theme::appearance_choices] [::vmdai::theme::set_appearance system] \
        [::vmdai::theme::set_appearance Dark] [::vmdai::theme::set_appearance light]]
    ::harness::fresh_panel
    ::vmdai::settings::open panel
    ::harness::settle
    set p [::vmdai::settings::tab panel]
    lappend r [$p.appearance cget -values] [$p.appearance get] \
        [catch {::vmdai::theme::set_appearance bogus}]
} -cleanup {
    ::vmdai::settings::close
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
} -result {{Light Dark} light dark light {Light Dark} Light 1}

test dark-forced_sets_window_appearance {Light/Dark set the window's MacWindowStyle appearance; System gives it back} -constraints aquaWs -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::harness::settle
} -body {
    set ::m3::mws_calls {}
    ::vmdai::theme::set_appearance dark
    set dark [lsearch -all -inline $::m3::mws_calls {appearance .vmd_ai *}]
    set ::m3::mws_calls {}
    ::vmdai::theme::set_appearance system
    set sys [lsearch -all -inline $::m3::mws_calls {appearance .vmd_ai *}]
    list $dark $sys
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {{{appearance .vmd_ai darkaqua}} {{appearance .vmd_ai auto}}}

test dark-dialog_opened_later {a dialog opened after the switch is drawn dark} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::vmdai::theme::set_appearance dark
} -body {
    set dlg [::vmdai::settings::open model]
    ::harness::settle
    set lo [::m3::light_only]
    set left {}
    foreach e [::m3::colours [list $dlg]] {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} { lappend left [lindex $e 0] }
    }
    set left
} -cleanup {
    ::vmdai::settings::close
    ::vmdai::theme::set_appearance light
} -result {}

test dark-save_applies {Save in Settings applies the chosen appearance at once} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
            options [dict create num_ctx 32768]]]]
    ::fake::reply models.list ok [dict create models {} source server]
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::fake::reply settings.set ok {ok true settings {} persisted {reasoning_visible true wiki_enabled false}}
    ::fake::reply provider.set ok {ok true}
    ::vmdai::settings::open panel
    ::harness::wait_until {expr {$::vmdai::settings::v(profile) eq "qwen"}}
} -body {
    set ::vmdai::settings::v(appearance) dark
    set ::vmdai::settings::v(appearance_label) Dark
    ::vmdai::settings::save
    ::harness::wait_until {expr {![winfo exists .vmd_ai_settings]}}
    list [::vmdai::theme::mode] [::vmdai::theme::appearance] \
        [dict get [::vmdai::config::load_plugin_settings] appearance]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {dark dark dark}

test dark-every_m2_token {every token M2's theme defines has a light and a dark value} -body {
    set missing {}
    foreach tok $::m3::m2_tokens {
        foreach m {light dark} {
            if {![dict exists [dict get $::vmdai::theme::PALETTE $m] $tok]} { lappend missing $m:$tok }
        }
    }
    set missing
} -result {}

test dark-other_windows_untouched {windows that are not ChatVMD's keep their colours} -setup {
    ::m3::use_mws
    toplevel .m3other
    wm withdraw .m3other
    label .m3other.l -text other -foreground #636366 -background #ffffff
} -body {
    ::vmdai::theme::set_appearance dark
    list [.m3other.l cget -foreground] [.m3other.l cget -background] \
        [expr {".m3other" in [::vmdai::theme::owned_toplevels]}]
} -cleanup {
    destroy .m3other
    ::vmdai::theme::set_appearance light
} -result [list #636366 #ffffff 0]

cleanupTests
```

(`dark-other_windows_untouched` writes its result as `[list #636366 …]`: Tcl braces a first list element that starts with `#`, so `list #636366 #ffffff 0` is `{#636366} #ffffff 0` and a braced literal would never match.)

Create `tests/test_tk_dark.py`:

```python
"""P10-T01: dark tokens and appearance events (Part B V2, V7)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 8


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_dark.tcl")


def test_theme_1(results):
    assert_case(results, "theme-1", TOTAL)


def test_appearance_event_repaints_dialogs(results):
    assert_case(results, "dark-events_repaint_dialogs", TOTAL)


def test_no_macwindowstyle(results):
    assert_case(results, "dark-no_macwindowstyle", TOTAL)


def test_forced_appearance_sets_window_style(results):
    assert_case(results, "dark-forced_sets_window_appearance", TOTAL)


def test_dialog_opened_later_is_dark(results):
    assert_case(results, "dark-dialog_opened_later", TOTAL)


def test_save_applies_appearance(results):
    assert_case(results, "dark-save_applies", TOTAL)


def test_every_m2_token_has_a_dark_value(results):
    assert_case(results, "dark-every_m2_token", TOTAL)


def test_other_windows_untouched(results):
    assert_case(results, "dark-other_windows_untouched", TOTAL)
```

Create `tests/test_theme_contrast.py`:

```python
"""Dark and light tokens (Part B V2): exact values and contrast ratios.

Parses the PALETTE block of plugin/theme.tcl, so it needs no Tcl or Tk and
CI checks it on every push.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

import pytest

REPO = Path(__file__).resolve().parents[1]
THEME = REPO / "plugin" / "theme.tcl"

# Part B V2, token table (light, dark).
SPEC: Dict[str, Dict[str, str]] = {
    "light": {
        "chrome": "#ececec", "surface": "#ffffff", "text": "#1d1d1f",
        "text2": "#3c3c43", "muted": "#636366", "faint": "#a1a1a6",
        "hairline": "#d6d6da", "accent": "#0a66d8", "ok": "#1a7f37",
        "err": "#c8262e", "err_bg": "#fdecec", "warn": "#835700",
        "warn_bg": "#fff5df", "warn_bd": "#efd59b", "warn_fg": "#5c4300",
        "code_bg": "#f4f4f6", "icode_bg": "#ececf0", "hover": "#f0f0f4",
        "stop_bg": "#1d1d1f", "stop_fg": "#ffffff", "dot_ok": "#28c840",
        "dot_warn": "#d88a00", "dot_off": "#ff5f57", "syn_cmd": "#0550ae",
        "syn_var": "#953800", "syn_str": "#0a3069", "syn_num": "#8250df",
        "syn_brace": "#835700", "syn_opt": "#57606a", "syn_cmt": "#636c76",
    },
    "dark": {
        "chrome": "#2c2c2e", "surface": "#1e1e1e", "text": "#e6e6eb",
        "text2": "#c9c9ce", "muted": "#9a9aa1", "faint": "#5f5f65",
        "hairline": "#0c0c0d", "accent": "#4ea1ff", "ok": "#3bd16f",
        "err": "#ff6b64", "err_bg": "#3a1f1e", "warn": "#e6aa3f",
        "warn_bg": "#3a2f16", "warn_bd": "#5a4820", "warn_fg": "#f6d58f",
        "code_bg": "#28282b", "icode_bg": "#313135", "hover": "#29292c",
        "stop_bg": "#e6e6eb", "stop_fg": "#1e1e1e", "dot_ok": "#32d74b",
        "dot_warn": "#ffb340", "dot_off": "#ff453a", "syn_cmd": "#79c0ff",
        "syn_var": "#ffa657", "syn_str": "#a5d6ff", "syn_num": "#d2a8ff",
        "syn_brace": "#e3b341", "syn_opt": "#c3cad3", "syn_cmt": "#8b949e",
    },
}

# (foreground, background, light minimum, dark minimum), V2's figures. Ratios
# are compared after rounding to one decimal, the way the spec quotes them
# (dark muted on chrome measures 4.98, which the spec states as >= 5.0).
CONTRAST = [
    ("text", "surface", 16.8, 13.4),
    ("muted", "surface", 6.0, 6.0),
    ("muted", "chrome", 5.0, 5.0),
    ("accent", "surface", 5.4, 6.2),
    ("ok", "surface", 5.1, 8.4),
    ("warn_fg", "warn_bg", 8.6, 8.6),
] + [("syn_%s" % c, "code_bg", 4.5, 4.5) for c in ("cmd", "var", "str", "num", "brace", "opt", "cmt")]


def load_palettes() -> Dict[str, Dict[str, str]]:
    lines = THEME.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "set PALETTE {")
    palettes: Dict[str, Dict[str, str]] = {}
    mode = None
    for line in lines[start + 1:]:
        s = line.strip()
        header = re.fullmatch(r"(light|dark) \{", s)
        if header:
            mode = header.group(1)
            palettes[mode] = {}
            continue
        if s == "}":
            if mode is None:
                break
            mode = None
            continue
        pair = re.fullmatch(r"([a-z0-9_]+)\s+(#[0-9a-f]{6})", s)
        if pair and mode is not None:
            palettes[mode][pair.group(1)] = pair.group(2)
    return palettes


def _luminance(colour: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_palette_matches_spec_table():
    palettes = load_palettes()
    for mode in ("light", "dark"):
        for token, value in SPEC[mode].items():
            assert palettes[mode].get(token) == value, (mode, token)


def test_light_and_dark_define_the_same_tokens():
    palettes = load_palettes()
    assert sorted(palettes["light"]) == sorted(palettes["dark"])


@pytest.mark.parametrize("fg,bg,light_min,dark_min", CONTRAST)
def test_contrast_ratios(fg, bg, light_min, dark_min):
    palettes = load_palettes()
    for mode, minimum in (("light", light_min), ("dark", dark_min)):
        ratio = contrast(palettes[mode][fg], palettes[mode][bg])
        assert round(ratio, 1) >= minimum, "%s %s on %s: %.2f < %s" % (mode, fg, bg, ratio, minimum)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_dark.py tests/test_theme_contrast.py -q`
Expected: `23 failed`. The Tk cases fail with `invalid command name "::vmdai::theme::set_appearance"` (`dark-every_m2_token` with `can't read "::vmdai::theme::PALETTE": no such variable`); every contrast test fails with `StopIteration` from `load_palettes` (no `set PALETTE {` line yet).

- [ ] **Step 4: Append the M3 section to `plugin/theme.tcl`**

Append to the end of `plugin/theme.tcl` (after all of M2's code):

```tcl

# ============================================================================
# M3 (plan 10): dark palette, the Appearance setting and system appearance
# events.  Spec Part B V2 and V7.  This section only adds to the M2 theme
# above; M2's init, c, paint, repaint, mode and mono_family keep their meaning.
# ============================================================================
namespace eval ::vmdai::theme {
    # token -> colour for both modes (Part B V2).  tests/test_theme_contrast.py
    # parses these blocks: keep exactly one "token #rrggbb" pair per line.
    # sel, field_bd, focus_ring, spin_hi and spin_lo are the native
    # prototype's extra tokens, kept so an M2 widget that uses them retints.
    # PALETTE is a constant table, not state, so it is set on every source
    # (a reload picks up edits); every stateful variable below is guarded.
    variable PALETTE
    set PALETTE {
        light {
            chrome     #ececec
            surface    #ffffff
            text       #1d1d1f
            text2      #3c3c43
            muted      #636366
            faint      #a1a1a6
            hairline   #d6d6da
            accent     #0a66d8
            ok         #1a7f37
            err        #c8262e
            err_bg     #fdecec
            warn       #835700
            warn_bg    #fff5df
            warn_bd    #efd59b
            warn_fg    #5c4300
            code_bg    #f4f4f6
            icode_bg   #ececf0
            hover      #f0f0f4
            stop_bg    #1d1d1f
            stop_fg    #ffffff
            dot_ok     #28c840
            dot_warn   #d88a00
            dot_off    #ff5f57
            syn_cmd    #0550ae
            syn_var    #953800
            syn_str    #0a3069
            syn_num    #8250df
            syn_brace  #835700
            syn_opt    #57606a
            syn_cmt    #636c76
            sel        #b3d7ff
            field_bd   #c8c8cd
            focus_ring #9ec1f5
            spin_hi    #3a3a3c
            spin_lo    #d8d8dc
        }
        dark {
            chrome     #2c2c2e
            surface    #1e1e1e
            text       #e6e6eb
            text2      #c9c9ce
            muted      #9a9aa1
            faint      #5f5f65
            hairline   #0c0c0d
            accent     #4ea1ff
            ok         #3bd16f
            err        #ff6b64
            err_bg     #3a1f1e
            warn       #e6aa3f
            warn_bg    #3a2f16
            warn_bd    #5a4820
            warn_fg    #f6d58f
            code_bg    #28282b
            icode_bg   #313135
            hover      #29292c
            stop_bg    #e6e6eb
            stop_fg    #1e1e1e
            dot_ok     #32d74b
            dot_warn   #ffb340
            dot_off    #ff453a
            syn_cmd    #79c0ff
            syn_var    #ffa657
            syn_str    #a5d6ff
            syn_num    #d2a8ff
            syn_brace  #e3b341
            syn_opt    #c3cad3
            syn_cmt    #8b949e
            sel        #3f638b
            field_bd   #48484c
            focus_ring #2f5f9f
            spin_hi    #e6e6eb
            spin_lo    #48484c
        }
    }
    if {![info exists ::vmdai::theme::HERE]} {
        set ::vmdai::theme::HERE [file dirname [file normalize [info script]]]
    }
    if {![info exists ::vmdai::theme::appearance]} { set ::vmdai::theme::appearance system }
    if {![info exists ::vmdai::theme::owned]} { set ::vmdai::theme::owned {} }
    if {![info exists ::vmdai::theme::system_pending]} { set ::vmdai::theme::system_pending 0 }
    if {![info exists ::vmdai::theme::known_styles]} { set ::vmdai::theme::known_styles {} }
    # Command prefix for ::tk::unsupported::MacWindowStyle; tests swap it.
    if {![info exists ::vmdai::theme::macstyle]} {
        set ::vmdai::theme::macstyle ::tk::unsupported::MacWindowStyle
    }
}

# The two places this section writes M2's storage (plan 10, contract row 1).
proc ::vmdai::theme::_set_token {tok value} {
    variable T
    set T($tok) $value
}
proc ::vmdai::theme::_set_mode {m} {
    variable mode
    set mode $m
}

# palette m -> token dict for light|dark.  On aqua, chrome and sel are the
# dynamic system colours, which follow each window's appearance.
proc ::vmdai::theme::palette {m} {
    variable PALETTE
    if {![dict exists $PALETTE $m]} {
        error "unknown mode \"$m\": must be light or dark"
    }
    set p [dict get $PALETTE $m]
    if {![catch {tk windowingsystem} ws] && $ws eq "aqua"} {
        dict set p chrome systemWindowBackgroundColor
        dict set p sel systemSelectedTextBackgroundColor
    }
    return $p
}

proc ::vmdai::theme::has_macwindowstyle {} {
    variable macstyle
    if {[catch {tk windowingsystem} ws] || $ws ne "aqua"} {
        return 0
    }
    return [expr {[llength [info commands $macstyle]] > 0}]
}

# The Appearance values Settings offers (V7: no System without MacWindowStyle).
proc ::vmdai::theme::appearance_choices {} {
    if {[has_macwindowstyle]} {
        return {System Light Dark}
    }
    return {Light Dark}
}

# The current setting: system, light or dark.
proc ::vmdai::theme::appearance {} {
    variable appearance
    return $appearance
}

proc ::vmdai::theme::system_is_dark {} {
    variable macstyle
    if {![has_macwindowstyle]} {
        return 0
    }
    if {[catch {{*}$macstyle isdark .} d]} {
        return 0
    }
    return [expr {[string is true -strict $d] ? 1 : 0}]
}

# effective setting -> light|dark
proc ::vmdai::theme::effective {setting} {
    switch -- $setting {
        light - dark {
            return $setting
        }
    }
    if {[system_is_dark]} {
        return dark
    }
    return light
}

# set_appearance system|light|dark (any case) -> the mode now in effect.
proc ::vmdai::theme::set_appearance {setting} {
    variable appearance
    variable system_pending
    set s [string tolower $setting]
    if {[lsearch -exact {system light dark} $s] < 0} {
        error "bad appearance \"$setting\": must be system, light or dark"
    }
    set appearance $s
    # A reload's sched::teardown may have cancelled a pending switch.
    set system_pending 0
    bind_system_events
    set eff [effective $s]
    _apply_mode $eff
    _force_windows
    return $eff
}

# saved_appearance -> plugin.json's appearance, or system.
proc ::vmdai::theme::saved_appearance {} {
    if {[catch {::vmdai::config::load_plugin_settings} s]} {
        return system
    }
    if {[catch {dict get $s appearance} a]} {
        return system
    }
    set a [string tolower $a]
    if {[lsearch -exact {system light dark} $a] < 0} {
        return system
    }
    return $a
}

# own w: count toplevel w as a ChatVMD window even if it uses no Chat* font.
proc ::vmdai::theme::own {w} {
    variable owned
    if {[lsearch -exact $owned $w] < 0} {
        lappend owned $w
    }
}

# Toplevels (including ".") whose widgets belong to ChatVMD: registered with
# own, named .vmd_ai* / .vmdai*, or using a Chat* named font or a ChatVMD.*
# ttk style.  Other plugins' windows (QwikMD, VMD's own) are never touched.
proc ::vmdai::theme::owned_toplevels {} {
    variable owned
    set out {}
    foreach w $owned {
        if {[winfo exists $w]} {
            lappend out $w
        }
    }
    foreach top [_toplevels .] {
        if {[lsearch -exact $out $top] >= 0} {
            continue
        }
        if {[_ours $top]} {
            lappend out $top
        }
    }
    return $out
}

proc ::vmdai::theme::_ours {top} {
    return [expr {[string match .vmd_ai* $top] || [string match .vmdai* $top]
        || [_uses_chat_look $top]}]
}

proc ::vmdai::theme::_toplevels {w} {
    set out {}
    if {[winfo toplevel $w] eq $w} {
        lappend out $w
    }
    foreach c [winfo children $w] {
        set out [concat $out [_toplevels $c]]
    }
    return $out
}

# _subtree top -> top and every descendant in the same toplevel.
proc ::vmdai::theme::_subtree {top} {
    set out [list $top]
    set queue [list $top]
    while {[llength $queue]} {
        set w [lindex $queue 0]
        set queue [lrange $queue 1 end]
        foreach c [winfo children $w] {
            if {[winfo toplevel $c] ne $top} {
                continue
            }
            lappend out $c
            lappend queue $c
        }
    }
    return $out
}

proc ::vmdai::theme::_uses_chat_look {top} {
    foreach w [_subtree $top] {
        if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]} {
            return 1
        }
        if {![catch {$w cget -font} f] && [string match Chat* $f]} {
            return 1
        }
    }
    return 0
}

# _apply_mode m: make m the active palette and retint everything already
# drawn.  (Not "_apply": M2's _apply w spec is the paint helper.)
proc ::vmdai::theme::_apply_mode {m} {
    set new [palette $m]
    set old [dict create]
    dict for {tok val} $new {
        if {![catch {c $tok} cur]} {
            dict set old $tok $cur
        }
    }
    dict for {tok val} $new {
        _set_token $tok $val
    }
    _set_mode $m
    if {[catch {repaint} err]} {
        catch {::vmdai::config::log "theme repaint failed: $err"}
    }
    _retint $old $new
}

# _retint old new: M2 configured widgets, text tags, canvas items and ChatVMD.*
# styles with token values; swap each old value for the new one.  A colour two
# tokens share (warn and syn_brace are both #835700 in light) maps by the
# first token in PALETTE order, except that a text tag named after a token
# (syn_brace) maps by that token.
proc ::vmdai::theme::_retint {old new} {
    set vmap [dict create]
    dict for {tok val} $old {
        set lv [string tolower $val]
        set nv [dict get $new $tok]
        if {$lv eq [string tolower $nv] || [dict exists $vmap $lv]} {
            continue
        }
        dict set vmap $lv $nv
    }
    if {[dict size $vmap] == 0} {
        return
    }
    variable known_styles
    foreach top [owned_toplevels] {
        foreach w [_subtree $top] {
            _retint_options $w $vmap
            switch -- [winfo class $w] {
                Text {
                    _retint_tags $w $vmap $old $new
                }
                Canvas {
                    _retint_items $w $vmap
                }
            }
            if {![catch {$w cget -style} st] && [string match ChatVMD.* $st]
                    && [lsearch -exact $known_styles $st] < 0} {
                lappend known_styles $st
            }
        }
    }
    foreach st [_style_names] {
        _retint_style $st $vmap
    }
}

# Every ChatVMD.* style named in the plugin's sources, plus any seen on a
# widget, so styles of dialogs that are not open yet retint too.
proc ::vmdai::theme::_style_names {} {
    variable HERE
    variable known_styles
    set names $known_styles
    foreach f [glob -nocomplain -directory $HERE *.tcl] {
        if {[catch {open $f r} fh]} {
            continue
        }
        set src [read $fh]
        close $fh
        foreach st [regexp -all -inline {ChatVMD\.[A-Za-z0-9_.]*[A-Za-z0-9_]} $src] {
            if {[lsearch -exact $names $st] < 0} {
                lappend names $st
            }
        }
    }
    return $names
}

proc ::vmdai::theme::_retint_options {w vmap} {
    if {[catch {$w configure} specs]} {
        return
    }
    foreach spec $specs {
        if {[llength $spec] != 5} {
            continue
        }
        set cur [string tolower [lindex $spec 4]]
        if {[dict exists $vmap $cur]} {
            catch {$w configure [lindex $spec 0] [dict get $vmap $cur]}
        }
    }
}

proc ::vmdai::theme::_retint_tags {t vmap old new} {
    foreach tag [$t tag names] {
        if {[catch {$t tag configure $tag} specs]} {
            continue
        }
        foreach spec $specs {
            set cur [string tolower [lindex $spec 4]]
            if {$cur eq ""} {
                continue
            }
            set nv ""
            if {[dict exists $old $tag] && [string tolower [dict get $old $tag]] eq $cur} {
                set nv [dict get $new $tag]
            } elseif {[dict exists $vmap $cur]} {
                set nv [dict get $vmap $cur]
            }
            if {$nv ne ""} {
                catch {$t tag configure $tag [lindex $spec 0] $nv}
            }
        }
    }
}

proc ::vmdai::theme::_retint_items {c vmap} {
    foreach id [$c find all] {
        if {[catch {$c itemconfigure $id} specs]} {
            continue
        }
        foreach spec $specs {
            set cur [string tolower [lindex $spec 4]]
            if {$cur ne "" && [dict exists $vmap $cur]} {
                catch {$c itemconfigure $id [lindex $spec 0] [dict get $vmap $cur]}
            }
        }
    }
}

proc ::vmdai::theme::_retint_style {st vmap} {
    if {[catch {ttk::style configure $st} cfg]} {
        return
    }
    set changes {}
    foreach {opt val} $cfg {
        set lc [string tolower $val]
        if {[dict exists $vmap $lc]} {
            lappend changes $opt [dict get $vmap $lc]
        }
    }
    if {[llength $changes]} {
        catch {ttk::style configure $st {*}$changes}
    }
    if {[catch {ttk::style map $st} mp]} {
        return
    }
    set mchanges {}
    foreach {opt spec} $mp {
        set nspec {}
        set changed 0
        foreach {state val} $spec {
            set lc [string tolower $val]
            if {[dict exists $vmap $lc]} {
                set val [dict get $vmap $lc]
                set changed 1
            }
            lappend nspec $state $val
        }
        if {$changed} {
            lappend mchanges $opt $nspec
        }
    }
    if {[llength $mchanges]} {
        catch {ttk::style map $st {*}$mchanges}
    }
}

# Forced Light/Dark also sets each ChatVMD window's MacWindowStyle appearance
# so native controls match; System hands the window back to the OS (auto).
proc ::vmdai::theme::_force_windows {} {
    if {![has_macwindowstyle]} {
        return
    }
    foreach top [owned_toplevels] {
        _force_one $top
    }
}

proc ::vmdai::theme::_force_one {top} {
    variable appearance
    variable macstyle
    switch -- $appearance {
        light { set v aqua }
        dark { set v darkaqua }
        default { set v auto }
    }
    catch {{*}$macstyle appearance $top $v}
}

# A ChatVMD toplevel mapped after the switch (Settings, History, viewer).
proc ::vmdai::theme::_on_map {w} {
    variable appearance
    if {$appearance eq "system" || ![has_macwindowstyle]} {
        return
    }
    if {[catch {winfo toplevel $w} top] || $top ne $w} {
        return
    }
    if {[_ours $w]} {
        _force_one $w
    }
}

# Follow the OS while the setting is System.  Idempotent across reloads;
# each binding is wrapped in catch (V2).
proc ::vmdai::theme::bind_system_events {} {
    foreach {ev hint} {<<LightAqua>> light <<DarkAqua>> dark <<AppearanceChanged>> probe} {
        catch {
            if {[string first ::vmdai::theme::on_system_event [bind all $ev]] < 0} {
                bind all $ev [list +::vmdai::theme::on_system_event $hint]
            }
        }
    }
    catch {
        if {[string first ::vmdai::theme::_on_map [bind Toplevel <Map>]] < 0} {
            bind Toplevel <Map> {+::vmdai::theme::_on_map %W}
        }
    }
}

# The OS sends these events to every toplevel, and Tk also sends them when a
# window is first realized, so the event name is only a trigger: the switch
# runs once, when idle, and asks MacWindowStyle isdark for the real state.
proc ::vmdai::theme::on_system_event {hint} {
    variable appearance
    variable system_pending
    if {$appearance ne "system" || $system_pending} {
        return
    }
    set system_pending 1
    if {[llength [info commands ::vmdai::sched::after_idle]]} {
        ::vmdai::sched::after_idle ::vmdai::theme::_system_changed
    } else {
        after idle ::vmdai::theme::_system_changed
    }
}

proc ::vmdai::theme::_system_changed {} {
    variable appearance
    variable system_pending
    set system_pending 0
    if {$appearance ne "system"} {
        return
    }
    set eff [effective system]
    if {$eff ne [mode]} {
        _apply_mode $eff
    }
}
```

The mode switch is named `_apply_mode` on purpose: P08-T04's `theme.tcl` already defines `::vmdai::theme::_apply w spec`, the helper `paint` and `repaint` call, and an M3 proc with that name would replace it (`paint` then fails with `wrong # args: should be "_apply m"`; checked while reviewing this plan by sourcing P08-T04's file with this section appended). `tests/test_tk_theme.py` in Step 6 guards it.

Two measured facts behind this code (VMD's Tk 8.6.12, tclsh 8.6.14, during planning): `ttk::style theme styles` does not exist in 8.6.12, so styles are found by name in the sources and on live widgets; and Tk itself sends `<<LightAqua>>`/`<<AppearanceChanged>>` to each new toplevel when it is first realized, so an event is only a trigger and `isdark` decides.

- [ ] **Step 5: Wire the setting into Settings, the panel and the test harness**

In `plugin/settings.tcl` (anchor S7):

1. Replace the whole `proc ::vmdai::settings::appearance_values` (P09-T05) with:

```tcl
# System needs MacWindowStyle (Tk 8.6 on aqua); elsewhere only Light and Dark (V7).
proc ::vmdai::settings::appearance_values {} {
    return [::vmdai::theme::appearance_choices]
}
```

2. In `proc ::vmdai::settings::_load_panel_prefs`, directly after the line `set v(appearance_label) [string totitle $v(appearance)]`, add:

```tcl
    if {[lsearch -exact [appearance_values] $v(appearance_label)] < 0} {
        set v(appearance) light
        set v(appearance_label) Light
    }
```

3. In `proc ::vmdai::settings::save_steps`, insert `_apply_appearance` directly before `_finish_save` in the returned list (after P09-T05 the body reads `return {_save_profile _save_keys _save_persisted _save_plugin_prefs _apply_appearance _finish_save}`).

4. Append to `plugin/settings.tcl`:

```tcl
# ---- M3 (plan 10, P10-T01): apply the Appearance on Save --------------------
# Runs after plugin.json is written, so the panel and every open ChatVMD
# window switch at once ("Changes apply to the next message" is about the
# model; the look changes immediately).
proc ::vmdai::settings::_apply_appearance {k} {
    variable v
    if {[catch {::vmdai::theme::set_appearance $v(appearance)} err]} {
        _fail "Could not apply the appearance: $err"
        return
    }
    {*}$k
}
```

In `plugin/panel.tcl` (anchor S3), in `proc ::vmdai::panel::build`, directly after the line `::vmdai::theme::init`, add:

```tcl
    ::vmdai::theme::set_appearance [::vmdai::theme::saved_appearance]
```

In `tests/tcl/panel_harness.tcl`, directly after the `foreach ::harness::module ...` loop that sources the modules (before `set ::vmdai::panel::headless 1`), add:

```tcl
# M3 (plan 10): no test reads the real OS appearance. With a MacWindowStyle
# command that does not exist, System resolves to light and Settings offers
# only Light and Dark; M3 tests install ::m3::mws when they need one.
set ::vmdai::theme::macstyle ::harness::no_macwindowstyle
```

In `tests/tcl/panel_driver.tcl` (P09-T09's end-to-end driver, which sources `init.tcl` rather than the harness), directly after the line `    set ::vmdai::panel::headless 1` that follows `source ... init.tcl`, add:

```tcl
    # M3 (plan 10): never read the real OS appearance (the build calls
    # set_appearance); theme.tcl keeps this value when init.tcl re-sources it.
    set ::vmdai::theme::macstyle ::driver_no_macwindowstyle
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tk_dark.py tests/test_theme_contrast.py tests/test_tcl_lint.py -q`
Expected: `23 passed` from the two new files (8 Tk cases, 15 contrast/palette tests) and every lint test passing.

Run: `python -m pytest tests/test_tk_theme.py tests/test_tk_settings.py tests/test_tk_panel.py tests/test_tk_empty_state.py tests/test_tk_keymap.py tests/test_panel_integration.py -q`
Expected: every test passes, as before this task. `test_tk_theme.py` (P08-T04) proves M2's `paint`/`repaint` still work with the M3 section appended; plan 09's `settings-panel_prefs_saved` now also switches the theme on Save, and its assertions are unchanged.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+23 passed` (plus the unchanged skips), 0 failed, under 60 s.

- [ ] **Step 7: Commit**

```bash
git add plugin/theme.tcl plugin/settings.tcl plugin/panel.tcl tests/tcl/panel_harness.tcl \
        tests/tcl/panel_driver.tcl tests/tcl/m3_helpers.tcl tests/tcl/test_dark.tcl \
        tests/test_tk_dark.py tests/test_theme_contrast.py
git commit -m "feat(plugin): dark palette, Appearance setting and system appearance events (P10-T01)

theme.tcl gains the V2 light/dark palettes, set_appearance system|light|dark,
a retint pass over ChatVMD's own windows (widgets, text tags, canvas items,
ChatVMD.* styles) and <<LightAqua>>/<<DarkAqua>>/<<AppearanceChanged>>
handling. Settings offers System only with MacWindowStyle (V7) and applies
the choice on Save; the panel applies plugin.json's appearance at build.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T02: Tcl syntax colours

**Files:**
- Create: `plugin/syntax.tcl`
- Modify: `plugin/theme.tcl` (append `syntax_tags` to the M3 section)
- Modify: `plugin/transcript.tcl` (one `source` line near the top; anchor S4: the step-detail builder `_build_detail`)
- Modify (regenerate): `tests/fixtures/tk/03_conversation.txt` (its auto-opened failed step detail now carries `syn_*` tags)
- Create: `tests/tcl/test_syntax.tcl` (tclsh, no Tk)
- Create: `tests/tcl/test_syntax_detail.tcl` (Tk)
- Test: `tests/test_tcl_syntax.py`

**Interfaces:**
- Consumes: step detail (P08-T06) — `::vmdai::transcript::toggle_detail call_key`, the `detail:$k` tag and the builder's command `insert`s (anchor S4); `::vmdai::theme::c` and the `syn_*` tokens (P10-T01); `::m3::*` helpers (P10-T01); `helpers.tcl.run_tcltest` (P01-T03).
- Produces: `::vmdai::syntax::tokens code -> list {start end class}` — 0-based character offsets into `code` (end exclusive, counted across lines, "\n" is one character), classes `cmd var str num brace opt cmt`, plain words and whitespace omitted. Also `::vmdai::syntax::highlight t start code` (tags the tokens of `code`, already inserted at `start`, with `syn_<class>`), `::vmdai::syntax::highlight_tag t tag` (highlights every range of `tag`), `::vmdai::theme::syntax_tags t` (configures `syn_*` from the tokens; muted/faint tags keep priority over them), and the step-detail tag `dcmd:<call_key>` on the command bytes.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_syntax.tcl`:

```tcl
# P10-T02: Tcl syntax tokens.  Pure Tcl: runs under tclsh 8.6 (and in CI).
package require tcltest 2
namespace import ::tcltest::*
source [file join $env(VMDAI_PLUGIN_DIR) syntax.tcl]

test syntax-1 {commands, brackets, variables and numbers} -body {
    list [::vmdai::syntax::tokens {set sel [atomselect top protein]}] \
         [::vmdai::syntax::tokens {mol delrep 0 $molid}]
} -result {{{0 3 cmd} {8 9 brace} {9 19 cmd} {31 32 brace}} {{0 3 cmd} {11 12 num} {13 19 var}}}

test syntax-2 {comments, strings, options} -body {
    list [::vmdai::syntax::tokens {# load it}] \
         [::vmdai::syntax::tokens {puts "rgyr: $r"}] \
         [::vmdai::syntax::tokens {mol representation Licorice -radius 0.3 12}]
} -result {{{0 9 cmt}} {{0 4 cmd} {5 15 str}} {{0 3 cmd} {28 35 opt} {36 39 num} {40 42 num}}}

test syntax-3 {offsets run across lines; every line starts a command} -body {
    ::vmdai::syntax::tokens "mol new 1hck.pdb\nmol delrep 0 top"
} -result {{0 3 cmd} {17 20 cmd} {28 29 num}}

test syntax-4 {semicolons and brackets start commands; offsets count characters} -body {
    list [::vmdai::syntax::tokens {set s [measure rgyr $sel]; puts $s}] \
         [::vmdai::syntax::tokens "puts \u00c5; set a(1) 2"]
} -result {{{0 3 cmd} {6 7 brace} {7 14 cmd} {20 24 var} {24 25 brace} {27 31 cmd} {32 34 var}} {{0 4 cmd} {8 11 cmd} {17 18 num}}}

test syntax-5 {braced bodies and namespaced variables} -body {
    ::vmdai::syntax::tokens {if {$x > 2} { puts $::env(HOME) }}
} -result {{0 2 cmd} {3 4 brace} {4 6 var} {9 10 num} {10 11 brace} {12 13 brace} {19 31 var} {32 33 brace}}

test syntax-6 {every class is one of the seven syn tokens; empty input has none} -body {
    set classes {}
    foreach tok [::vmdai::syntax::tokens "# c\nset x \"s\" -o 1 \$v \[y\]"] {
        lappend classes [lindex $tok 2]
    }
    list [lsort -unique $classes] [::vmdai::syntax::tokens ""]
} -result {{brace cmd cmt num opt str var} {}}

cleanupTests
```

Create `tests/tcl/test_syntax_detail.tcl`:

```tcl
# P10-T02: Tcl syntax colours in the step detail (Part B V4 "Step detail").
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

# 03_conversation's first call runs "mol new 1hck.pdb\nmol delrep 0 top\n..."
test syntax-detail-colours {an open step detail colours its command} -setup {
    ::m3::use_mws
    set t [::m3::replay 03_conversation]
    set k [::m3::call_key_of 03_conversation 1]
    ::vmdai::transcript::toggle_detail $k
    ::harness::settle
} -body {
    list [lrange [::m3::ranges_text $t syn_cmd] 0 1] [expr {[llength [$t tag ranges dcmd:$k]] > 0}] \
        [$t tag cget syn_cmd -foreground]
} -result {{mol mol} 1 #0550ae}

# The failed call 2 has its detail open too (a multi-statement failure opens
# by itself), so a syn_* range may sit in any step's dcmd:<call_key>.
test syntax-detail-only-command {syntax tags stay inside the command bytes} -body {
    set outside {}
    foreach cls {cmd var str num brace opt cmt} {
        foreach {a b} [$t tag ranges syn_$cls] {
            if {[lsearch -glob [$t tag names $a] dcmd:*] < 0} { lappend outside $cls@$a }
        }
    }
    set outside
} -result {}

test syntax-dim-wins {text dimmed with muted keeps its colour over the syntax colours} -body {
    set w [::m3::root_text]
    $w tag configure m3dim -foreground [::vmdai::theme::c muted]
    $w insert end "mol new x.pdb" m3dim
    ::vmdai::syntax::highlight $w 1.0 "mol new x.pdb"
    ::vmdai::theme::syntax_tags $w
    set names [$w tag names 1.0]
    list [expr {[lsearch $names m3dim] > [lsearch $names syn_cmd]}] [$w tag cget syn_cmd -foreground]
} -result {1 #0550ae}

cleanupTests
```

Create `tests/test_tcl_syntax.py`:

```python
"""P10-T02: Tcl syntax tokens (pure Tcl) and step-detail colours (Tk)."""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import tcl
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
TOKENS_FILE = REPO / "tests" / "tcl" / "test_syntax.tcl"
TOKENS_TOTAL = 6
DETAIL_TOTAL = 3


@pytest.fixture(scope="module")
def tokens():
    return tcl.run_tcltest(str(TOKENS_FILE))


@pytest.fixture(scope="module")
def detail():
    return run_tk_file("test_syntax_detail.tcl")


def test_tokens_classes(tokens):
    assert (tokens.passed, tokens.failed) == (TOKENS_TOTAL, 0), tokens.output


def test_detail_is_coloured(detail):
    assert_case(detail, "syntax-detail-colours", DETAIL_TOTAL)


def test_syntax_stays_in_the_command(detail):
    assert_case(detail, "syntax-detail-only-command", DETAIL_TOTAL)


def test_dimmed_text_stays_dim(detail):
    assert_case(detail, "syntax-dim-wins", DETAIL_TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_syntax.py -q`
Expected: `4 failed`. `test_tokens_classes` shows `(0, 1) != (6, 0)` and `couldn't read file ".../plugin/syntax.tcl": no such file or directory`; the Tk cases fail with `tag "syn_cmd" isn't defined` and `invalid command name "::vmdai::syntax::highlight"`.

- [ ] **Step 3: Write `plugin/syntax.tcl`**

Create `plugin/syntax.tcl`:

```tcl
# syntax.tcl - Tcl syntax tokens for the step detail and ```tcl blocks.
# ChatVMD round 1, M3 (plan 10, P10-T02).  Pure Tcl: nothing here needs Tk at
# source time, so tclsh tests and CI can load it.  Adapted from the console
# prototype's syntax::tokens (docs/design/round1/prototypes/console/proto.tcl).

namespace eval ::vmdai::syntax {
    if {![info exists ::vmdai::syntax::CLASSES]} {
        set ::vmdai::syntax::CLASSES {cmd var str num brace opt cmt}
    }
}

# tokens code -> list of {start end class}, in order.  start/end are 0-based
# character offsets into code (end exclusive), counted across lines ("\n" is
# one character), so "$index + $start chars" addresses a token in a text
# widget.  Whitespace and plain arguments are not returned.  Every line starts
# in command position; "[" and ";" start a new command.
proc ::vmdai::syntax::tokens {code} {
    set out {}
    set base 0
    foreach line [split $code "\n"] {
        set len [string length $line]
        set pos 0
        set cmdpos 1
        while {$pos < $len} {
            set rest [string range $line $pos end]
            set cls ""
            if {[regexp {^[ \t]+} $rest m]} {
                # whitespace
            } elseif {$cmdpos && [regexp {^#.*} $rest m]} {
                set cls cmt
            } elseif {[regexp {^\$(\{[^\}]*\}|[A-Za-z0-9_:]+(\([^\)]*\))?)} $rest m]} {
                set cls var
                set cmdpos 0
            } elseif {[regexp {^\[} $rest m]} {
                set cls brace
                set cmdpos 1
            } elseif {[regexp {^[\]\{\}]} $rest m]} {
                set cls brace
                set cmdpos 0
            } elseif {[regexp {^;} $rest m]} {
                set cmdpos 1
            } elseif {[regexp {^"(?:[^"\\]|\\.)*"?} $rest m]} {
                set cls str
                set cmdpos 0
            } elseif {!$cmdpos && [regexp {^-?[0-9]+(?:\.[0-9]+)?(?=[\s\]\};]|$)} $rest m]} {
                set cls num
            } elseif {!$cmdpos && [regexp {^-[A-Za-z][A-Za-z0-9_]*} $rest m]} {
                set cls opt
            } elseif {[regexp {^[^\s\[\]\{\}\$;"]+} $rest m]} {
                if {$cmdpos} {
                    set cls cmd
                }
                set cmdpos 0
            } else {
                set m [string index $rest 0]
                set cmdpos 0
            }
            set n [string length $m]
            if {$cls ne ""} {
                lappend out [list [expr {$base + $pos}] [expr {$base + $pos + $n}] $cls]
            }
            incr pos $n
        }
        incr base [expr {$len + 1}]
    }
    return $out
}

# highlight t start code: tag the tokens of code, which the caller has just
# inserted into text widget t at index start, with syn_<class>.  Colours come
# from ::vmdai::theme::syntax_tags.
proc ::vmdai::syntax::highlight {t start code} {
    set start [$t index $start]
    foreach tok [tokens $code] {
        foreach {s e cls} $tok break
        $t tag add syn_$cls "$start + $s chars" "$start + $e chars"
    }
}

# highlight_tag t tag: highlight every range of tag (the step detail tags its
# command bytes dcmd:<call_key>).  Works through the read-only proxy.
proc ::vmdai::syntax::highlight_tag {t tag} {
    foreach {a b} [$t tag ranges $tag] {
        highlight $t $a [$t get $a $b]
    }
    catch {::vmdai::theme::syntax_tags $t}
}
```

- [ ] **Step 4: Add the colours and wire the step detail**

Append to the end of `plugin/theme.tcl`:

```tcl

# syntax_tags t: the syn_* tags of text widget t, from the syn_* tokens (V2).
# A tag that dims text with muted or faint (the statements after a failure,
# V4 "Step detail") is raised above them, so dimmed code stays dimmed.
proc ::vmdai::theme::syntax_tags {t} {
    foreach cls {cmd var str num brace opt cmt} {
        $t tag configure syn_$cls -foreground [c syn_$cls]
        $t tag raise syn_$cls
    }
    set dim [list [string tolower [c muted]] [string tolower [c faint]]]
    foreach tag [$t tag names] {
        if {[string match syn_* $tag] || [catch {$t tag cget $tag -foreground} fg]} {
            continue
        }
        if {[lsearch -exact $dim [string tolower $fg]] >= 0} {
            $t tag raise $tag
        }
    }
    catch {$t tag raise sel}
}
```

In `plugin/transcript.tcl`, directly after the file's opening comment block (before its first `namespace eval`), add:

```tcl
# M3 (plan 10): the step detail colours its command with syntax.tcl.  Sourced
# here so every file that sources transcript.tcl gets it; syntax.tcl is safe
# to source again.
source [file join [file dirname [info script]] syntax.tcl]
```

In `plugin/transcript.tcl` (anchor S4), in `proc ::vmdai::transcript::_build_detail {k}` (P08-T06, the one proc that inserts the step detail at the mark `dins:$k`):

1. In the loop over `[_cmd_lines $cmd $failed]`, replace the statement that writes each command segment

```tcl
            if {$text ne ""} { $W insert dins:$k $text [concat $base dcode $class] }
```

with

```tcl
            if {$text ne ""} { $W insert dins:$k $text [concat $base dcode $class dcmd:$k] }
```

Only the command bytes get `dcmd:$k`: the two-character gutter, the line-ending `"\n" $base`, the rationale, the `→` output, `Show all N lines`, `Open full output · Reveal`, the export note and `Copy` stay untagged. Each display line is therefore its own `dcmd:$k` range, which matches the tokenizer's rule that every line starts in command position.

2. After the proc's last statement (`$W tag add dlast "dins:$k -1l linestart" dins:$k`), add:

```tcl
    ::vmdai::syntax::highlight_tag $W dcmd:$k
```

If Task 0 Step 6's S4 listing shows a different builder, make the same two changes there: add `dcmd:$k` to exactly the inserts that write command text, and call `highlight_tag` once after the last insert. The spec asks for the executor's own splitter so the failing-statement highlight matches what ran; `dcmd:$k` only marks the same bytes, so plan 08's `highlight-split` / `test_failing_statement_highlight_matches_executor_split` is unaffected. The tool-row tests compare text, not the dump's tag column, so they are unaffected too; the Tk golden that shows an open step detail is not (Step 6).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_syntax.py tests/test_tk_tool_rows.py tests/test_tcl_lint.py -q`
Expected: `4 passed` from `test_tcl_syntax.py`; plan 08's tool-row tests (`glue-1`, `status-1`, `err-1`, `out-1`, `expand-1`, `fit-1`, `group-1..3`, the failing-statement highlight) still pass; lint passes (`plugin/syntax.tcl` has no banned construct).

Run: `python -m pytest tests/test_tk_transcript.py -q -k golden 2>&1 | tail -3`
Expected: `test_golden_03_conversation` fails with `golden mismatch`, and the diff shows only step-detail command lines (their tag column holds `dcode`) gaining `syn_*` names; `test_golden_reasoning_answer` passes (none of its step details is open). 03_conversation's failed call 2 is a two-statement failure, so its detail opens by itself (P08-T06) and now carries syntax tags; the dump lists every tag name without a `:`.

- [ ] **Step 6: Regenerate the Tk golden that shows an open step detail**

Run:
```bash
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py tests/test_panel_integration.py -q 2>&1 | tail -1
git diff --stat tests/fixtures/
git diff -U0 tests/fixtures/tk/ | grep '^[-+][0-9]' | grep -v ' dcode '
```
Expected: the tests pass; `tests/fixtures/tk/03_conversation.txt` changes, and the two panel goldens do not (P09-T09's scripted conversation fails with a single statement, whose detail stays closed; if one of them does change, it may change only the same way). The last command prints nothing: every changed line is a detail command line (`dcode`), and in each the only change is new `syn_cmd`/`syn_var`/`syn_str`/`syn_num`/`syn_brace`/`syn_opt`/`syn_cmt` names in the tag column; the line numbers and the text after `|` are identical. Anything else is a bug in the S4 edit. Then run without the variable:

Run: `python -m pytest tests/test_tk_transcript.py tests/test_panel_integration.py -q`
Expected: all pass.

- [ ] **Step 7: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+27 passed`, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add plugin/syntax.tcl plugin/theme.tcl plugin/transcript.tcl \
        tests/tcl/test_syntax.tcl tests/tcl/test_syntax_detail.tcl tests/test_tcl_syntax.py \
        tests/fixtures/tk/03_conversation.txt
git commit -m "feat(plugin): Tcl syntax colours in the step detail (P10-T02)

syntax.tcl ports the console prototype's tokenizer to {start end class}
offsets; the step detail tags its command bytes dcmd:<call_key> and colours
them with the syn_* tokens; muted statements stay muted.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T03: markdown.tcl subset

**Files:**
- Create: `plugin/markdown.tcl`
- Create: `tests/tcl/test_markdown.tcl` (tclsh, no Tk)
- Test: `tests/test_tcl_markdown.py`

**Interfaces:**
- Consumes: nothing from earlier plans (pure Tcl); `helpers.tcl.run_tcltest`, `helpers.tk_cases.failed_cases` for the wrapper.
- Produces: `::vmdai::md::spans text -> list of {kind text attrs}` — block spans in document order:
  - `{para <raw> {inline <inl>}}` — consecutive lines joined with one space;
  - `{item <raw> {marker <m> inline <inl>}}` — `-`/`*` items (`<m>` is `•`) and `1.`/`1)` items (`<m>` is `<n>.`);
  - `{heading <raw> {level 1|2 inline <inl>}}` — `#` and `##` only;
  - `{code <body> {lang <lang>}}` — a fenced block, body byte-exact, `lang` `""` when absent;
  - where `<inl>` is a list of `{text <s> {}}`, `{bold <s> {}}`, `{code <s> {}}`.
  An unclosed ``` or `**`/backtick, `###`, links, italics and tables stay literal text. Also `::vmdai::md::inline s -> <inl>`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_markdown.tcl`:

```tcl
# P10-T03: the Markdown subset -> spans (Part B V4 "Markdown").  Pure Tcl.
package require tcltest 2
namespace import ::tcltest::*
source [file join $env(VMDAI_PLUGIN_DIR) markdown.tcl]

set FINAL "- **Protein** — NewCartoon\n- **ATP** — Licorice\n\nThe radius of gyration is **20.84 Å**. Run `measure rgyr`:\n\n```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"

test md-subset-1 {items, bold, inline code and a fenced block} -body {
    ::vmdai::md::spans $FINAL
} -result [list \
    [list item "**Protein** — NewCartoon" [list marker \u2022 inline [list {bold Protein {}} [list text " — NewCartoon" {}]]]] \
    [list item "**ATP** — Licorice" [list marker \u2022 inline [list {bold ATP {}} [list text " — Licorice" {}]]]] \
    [list para "The radius of gyration is **20.84 Å**. Run `measure rgyr`:" [list inline [list {text {The radius of gyration is } {}} [list bold "20.84 Å" {}] {text {. Run } {}} {code {measure rgyr} {}} {text : {}}]]] \
    [list code "set sel \[atomselect top protein\]\nmeasure rgyr \$sel" {lang tcl}]]

test md-subset-2 {# and ## headings; ### is literal; numbered and * items} -body {
    ::vmdai::md::spans "# Title\n## Sub **b**\n### not a heading\n1. one\n2) two\n* star"
} -result [list \
    {heading Title {level 1 inline {{text Title {}}}}} \
    {heading {Sub **b**} {level 2 inline {{text {Sub } {}} {bold b {}}}}} \
    {para {### not a heading} {inline {{text {### not a heading} {}}}}} \
    {item one {marker 1. inline {{text one {}}}}} \
    {item two {marker 2. inline {{text two {}}}}} \
    [list item star [list marker \u2022 inline {{text star {}}}]]]

test md-subset-3 {paragraph lines join with one space; a blank line ends a paragraph} -body {
    ::vmdai::md::spans "line one\nline two\n\nnext"
} -result {{para {line one line two} {inline {{text {line one line two} {}}}}} {para next {inline {{text next {}}}}}}

test md-subset-4 {a fenced block keeps its bytes; no language is ""} -body {
    ::vmdai::md::spans "```\n  keep  spacing\n\n```"
} -result [list [list code "  keep  spacing\n" {lang {}}]]

test md-subset-5 {links, italics and tables stay literal text} -body {
    ::vmdai::md::spans {see [docs](http://x) and *this* | a | b |}
} -result {{para {see [docs](http://x) and *this* | a | b |} {inline {{text {see [docs](http://x) and *this* | a | b |} {}}}}}}

test md-literal-1 {an unclosed ** stays literal} -body {
    ::vmdai::md::spans "Use **bold without end"
} -result {{para {Use **bold without end} {inline {{text {Use **bold without end} {}}}}}}

test md-literal-2 {an unclosed ``` stays literal and the rest still parses} -body {
    ::vmdai::md::spans "```tcl\nset a 1\n\n- item **b**"
} -result [list \
    {para {```tcl set a 1} {inline {{text {```tcl set a 1} {}}}}} \
    [list item "item **b**" [list marker \u2022 inline {{text {item } {}} {bold b {}}}]]]

test md-literal-3 {an unclosed backtick and a lone ** stay literal} -body {
    ::vmdai::md::spans "`code without end and ** alone"
} -result {{para {`code without end and ** alone} {inline {{text {`code without end and ** alone} {}}}}}}

test md-literal-4 {empty and blank input give no spans and no error} -body {
    list [::vmdai::md::spans ""] [::vmdai::md::spans "  \n\n  "]
} -result {{} {}}

cleanupTests
```

Create `tests/test_tcl_markdown.py`:

```python
"""P10-T03: the Markdown subset -> spans (pure Tcl, runs in CI)."""
from __future__ import annotations

from pathlib import Path

import pytest

from helpers import tcl
from helpers.tk_cases import failed_cases

REPO = Path(__file__).resolve().parents[1]
TEST_FILE = REPO / "tests" / "tcl" / "test_markdown.tcl"
SUBSET = ["md-subset-%d" % i for i in range(1, 6)]
LITERAL = ["md-literal-%d" % i for i in range(1, 5)]


@pytest.fixture(scope="module")
def results():
    return tcl.run_tcltest(str(TEST_FILE))


def _check(results, cases):
    assert results.passed + results.failed == len(SUBSET) + len(LITERAL), results.output
    assert sorted(failed_cases(results) & set(cases)) == [], results.output


def test_subset(results):
    _check(results, SUBSET)


def test_unclosed_markers_literal(results):
    _check(results, LITERAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tcl_markdown.py -q`
Expected: `2 failed`; the output says `couldn't read file ".../plugin/markdown.tcl": no such file or directory` and the count check fails (`1 != 9`).

- [ ] **Step 3: Write `plugin/markdown.tcl`**

Create `plugin/markdown.tcl`:

```tcl
# markdown.tcl - the minimal Markdown subset of Part B V4, rendered only when
# a block is sealed.  ChatVMD round 1, M3 (plan 10, P10-T03 and P10-T04).
#
#   ::vmdai::md::spans text                            block spans (no Tk)
#   ::vmdai::md::render_into t index text ?basetags?   Tk rendering (P10-T04)
#
# Supported: **bold**, `code`, "- " / "* " / "1. " list items, "# " / "## "
# headings and ``` fenced code blocks.  Everything else, including an
# unclosed ``` or **, stays literal text.  Sourcing this file needs no Tk.

namespace eval ::vmdai::md {
    if {![info exists ::vmdai::md::seq]} { set ::vmdai::md::seq 0 }
}

# inline s -> list of {kind text {}} with kind text|bold|code.
proc ::vmdai::md::inline {s} {
    set out {}
    while {[regexp -indices {\*\*([^*]+)\*\*|`([^`]+)`} $s all b c]} {
        foreach {a0 a1} $all break
        if {$a0 > 0} {
            lappend out [list text [string range $s 0 [expr {$a0 - 1}]] {}]
        }
        if {[lindex $b 0] >= 0} {
            lappend out [list bold [string range $s [lindex $b 0] [lindex $b 1]] {}]
        } else {
            lappend out [list code [string range $s [lindex $c 0] [lindex $c 1]] {}]
        }
        set s [string range $s [expr {$a1 + 1}] end]
    }
    if {$s ne ""} {
        lappend out [list text $s {}]
    }
    return $out
}

# spans text -> list of block spans {kind text attrs}, in document order:
#   {para    <raw> {inline <inl>}}               lines joined with one space
#   {item    <raw> {marker <m> inline <inl>}}    <m> is \u2022 or "<n>."
#   {heading <raw> {level 1|2 inline <inl>}}
#   {code    <body> {lang <lang>}}               body is byte-exact
# where <inl> is the list [inline <raw>] returns.
proc ::vmdai::md::spans {text} {
    set lines [split [string map [list "\r\n" "\n"] $text] "\n"]
    set n [llength $lines]
    set out {}
    set para {}
    for {set i 0} {$i < $n} {incr i} {
        set line [lindex $lines $i]
        if {[regexp {^\s*```\s*([A-Za-z0-9_+-]*)\s*$} $line -> lang]} {
            set close -1
            for {set j [expr {$i + 1}]} {$j < $n} {incr j} {
                if {[regexp {^\s*```\s*$} [lindex $lines $j]]} {
                    set close $j
                    break
                }
            }
            if {$close >= 0} {
                _flush out para
                set body [join [lrange $lines [expr {$i + 1}] [expr {$close - 1}]] "\n"]
                lappend out [list code $body [list lang $lang]]
                set i $close
                continue
            }
            # An unclosed fence is not a code block: the line stays literal.
        }
        if {[regexp {^(#{1,2})\s+(.*)$} $line -> hashes head]} {
            _flush out para
            lappend out [list heading $head \
                [list level [string length $hashes] inline [inline $head]]]
            continue
        }
        if {[regexp {^\s*[-*]\s+(.*)$} $line -> item]} {
            _flush out para
            lappend out [list item $item [list marker "\u2022" inline [inline $item]]]
            continue
        }
        if {[regexp {^\s*([0-9]+)[.)]\s+(.*)$} $line -> num item]} {
            _flush out para
            lappend out [list item $item [list marker "$num." inline [inline $item]]]
            continue
        }
        if {[string trim $line] eq ""} {
            _flush out para
            continue
        }
        lappend para [string trim $line]
    }
    _flush out para
    return $out
}

proc ::vmdai::md::_flush {outVar paraVar} {
    upvar 1 $outVar out $paraVar para
    if {[llength $para] == 0} {
        return
    }
    set raw [join $para " "]
    lappend out [list para $raw [list inline [inline $raw]]]
    set para {}
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_tcl_markdown.py tests/test_tcl_lint.py -q`
Expected: `2 passed` from the markdown file (all 9 tcltest cases pass) and every lint test passing. The same file also passes under an 8.5 interpreter (checked while planning with `/usr/bin/tclsh` 8.5.9), which is the lint's point.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+29 passed`, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add plugin/markdown.tcl tests/tcl/test_markdown.tcl tests/test_tcl_markdown.py
git commit -m "feat(plugin): markdown.tcl, the V4 Markdown subset as spans (P10-T03)

Bold, inline code, - * 1. lists, # and ## headings and fenced blocks;
everything else, including an unclosed fence or **, stays literal.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T04: Render markdown on seal

**Files:**
- Modify: `plugin/markdown.tcl` (append the Tk rendering section)
- Modify: `plugin/transcript.tcl` (one `source` line next to T02's; anchor S5: the `block.seal` handler's canonical insert)
- Modify: `plugin/panel.tcl` (anchor S8: one line of `copy_selection`)
- Modify (regenerate): `tests/fixtures/tk/03_conversation.txt`, `tests/fixtures/tk/reasoning_answer.txt`, `tests/fixtures/tk/panel_03_conversation.txt`, `tests/fixtures/tk/panel_resume_replay.txt`
- Create: `tests/tcl/test_markdown_render.tcl`
- Test: `tests/test_tk_markdown_render.py`

**Interfaces:**
- Consumes: `::vmdai::md::spans`, `inline` (P10-T03); `::vmdai::syntax::highlight`, `::vmdai::theme::syntax_tags` (P10-T02); theme tokens `muted accent code_bg icode_bg` and fonts `ChatBodyBold ChatMeta ChatH2 ChatCode` (P08-T04); the `block.seal` handler (anchor S5, P08-T05); `::vmdai::panel::copy_selection` (P09-T03) and `_set_clipboard` (P09-T01; the harness's `stub_desktop` replaces it with a recorder); `::m3::*` (P10-T01).
- Produces: `::vmdai::md::render_into t index text ?basetags?` — inserts the rendering of `text` into the writable text widget command `t` at `index`, adds `basetags` to every inserted character, adds no trailing newline (so it can replace `$t insert $index $text $basetags`) and returns the index after the insertion. Also `::vmdai::md::configure_tags t`, `retab w`, `copy_at w index`, `copy code`, `plain_text s` (NBSP → space), and the tags `md_p md_li md_marker md_h1 md_h2 md_b md_code md_codehdr md_copy md_pre md_pretail`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_markdown_render.tcl`:

```tcl
# P10-T04: Markdown rendered on seal (Part B V4 "Markdown"; V1 NBSP; V8 md-1/2).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

set FINAL "- **Protein** — NewCartoon, colored by secondary structure\n- **ATP** — Licorice, colored by element\n\nThe radius of gyration is **20.84 Å**. To reproduce it, run `measure rgyr` on a protein selection:\n\n```tcl\nset sel \[atomselect top protein\]\nmeasure rgyr \$sel\n```"

test md-1 {markdown is rendered, not shown raw} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    set all [$w get 1.0 end]
    list [string first "**" $all] [string first "```" $all] [lindex [::m3::ranges_text $w md_b] end]
} -result [list -1 -1 "20.84 Å"]

test md-2 {fenced block lines are tagged code} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    llength [lsearch -all [split [join [::m3::ranges_text $w md_pre] \n] \n] *measure*]
} -result 1

test md-inline-nowrap {inline code never wraps, wherever it falls on a 380 px line} -body {
    set w [::m3::root_text 380x700]
    set wrapped {}
    for {set n 0} {$n <= 30} {incr n} {
        $w delete 1.0 end
        ::vmdai::md::render_into $w end "[string repeat {word } $n]`measure rgyr \$sel` tail"
        update idletasks
        foreach {a b} [$w tag ranges md_code] {
            if {[$w count -update -displaylines $a $b] != 0} { lappend wrapped $n }
        }
    }
    list [winfo width $w] $wrapped [string first " " [lindex [::m3::ranges_text $w md_code] 0]]
} -result {380 {} -1}

test md-codehdr {a fenced block gets a "tcl ... Copy" header whose Copy copies the exact code} -body {
    set w [::m3::root_text]
    ::vmdai::md::render_into $w end $FINAL
    set ::harness::clipboard ""
    ::vmdai::md::copy_at $w [lindex [$w tag ranges md_copy] 0]
    list [::m3::ranges_text $w md_codehdr] [::m3::ranges_text $w md_copy] $::harness::clipboard \
        [::m3::ranges_text $w syn_cmd] [lindex [$w tag cget md_codehdr -tabs] 1]
} -result [list [list "tcl\tCopy\n"] Copy "set sel \[atomselect top protein\]\nmeasure rgyr \$sel" \
    {set atomselect measure} right]

test md-basetags {every inserted character carries basetags; no trailing newline} -body {
    set w [::m3::root_text]
    $w insert end "before\n"
    set end [::vmdai::md::render_into $w end "A **b**\n\n- c" {prose wl:r1}]
    $w insert end "|after"
    list [$w get 2.0 "end - 1c"] [$w tag ranges wl:r1] $end
} -result [list "A b\n\u2022\tc|after" {2.0 3.3} 3.3]

test md-proxy {a renamed widget behind a read-only proxy renders and right-aligns Copy} -body {
    set w [::m3::root_text 600x700]
    rename $w ::m3::real_md
    proc ::$w {args} {
        if {[lindex $args 0] in {insert delete replace}} { return }
        uplevel 1 [list ::m3::real_md {*}$args]
    }
    ::vmdai::md::render_into ::m3::real_md end "```tcl\nputs hi\n```"
    set r [list [::vmdai::md::_window_of ::m3::real_md] [lindex [$w tag cget md_codehdr -tabs] 0]]
    rename ::$w {}
    rename ::m3::real_md {}
    destroy $w
    set r
} -result {.m3md 546}

test md-seal {streamed text stays raw; the sealed block is rendered} -setup {
    ::m3::use_mws
    ::harness::fresh_panel
    set t $::vmdai::panel::text
    set rid req_000000000088
    ::m3::render [::m3::ev system state "" [dict create kind request.started request_id $rid \
        chat_id chat_000000000088 provider ollama model qwen3.8:27b max_turns 28 vision true think false]]
    ::m3::render [::m3::ev assistant chunk "Loaded **1hck** with `mol new`" [dict create request_id $rid turn 1]]
    ::harness::settle
} -body {
    set streaming [expr {[string first "**1hck**" [$t get 1.0 end]] >= 0}]
    ::m3::render [::m3::ev assistant message "Loaded **1hck** with `mol new`." \
        [dict create request_id $rid turn 1 final true]]
    ::harness::settle
    set all [$t get 1.0 end]
    list $streaming [string first "**" $all] [::m3::ranges_text $t md_b] [::m3::ranges_text $t md_code]
} -result [list 1 -1 1hck "mol\u00a0new"]

test md-copy-plain {copying rendered inline code gives plain spaces} -body {
    $t tag remove sel 1.0 end
    $t tag add sel {*}[$t tag ranges md_code]
    set ::harness::clipboard ""
    ::vmdai::panel::copy_selection
    set ::harness::clipboard
} -result {mol new}

cleanupTests
```

Create `tests/test_tk_markdown_render.py`:

```python
"""P10-T04: Markdown rendered on seal (Part B V4 Markdown; V8 md-1, md-2, inline code)."""
from __future__ import annotations

import pytest

from helpers.tk_cases import assert_case, run_tk_file

TOTAL = 8


@pytest.fixture(scope="module")
def results():
    return run_tk_file("test_markdown_render.tcl")


def test_md_1(results):
    assert_case(results, "md-1", TOTAL)


def test_md_2(results):
    assert_case(results, "md-2", TOTAL)


def test_inline_code_never_wraps(results):
    assert_case(results, "md-inline-nowrap", TOTAL)


def test_code_block_copy_header(results):
    assert_case(results, "md-codehdr", TOTAL)


def test_render_keeps_basetags(results):
    assert_case(results, "md-basetags", TOTAL)


def test_render_through_proxy(results):
    assert_case(results, "md-proxy", TOTAL)


def test_only_sealed_blocks_rendered(results):
    assert_case(results, "md-seal", TOTAL)


def test_copy_gives_plain_spaces(results):
    assert_case(results, "md-copy-plain", TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_markdown_render.py -q`
Expected: `8 failed`. Most cases fail with `invalid command name "::vmdai::md::render_into"`; `md-seal` fails on the result (the sealed text still contains `**`), and `md-copy-plain` fails because there is no `md_code` range to select.

- [ ] **Step 3: Append the Tk renderer to `plugin/markdown.tcl`**

Append to the end of `plugin/markdown.tcl`:

```tcl

# ---- Tk rendering (P10-T04) --------------------------------------------------
# t is a writable text widget command.  In the transcript that is the real
# widget behind the read-only proxy (a renamed command, not a window path);
# _window_of finds the window for the width and the <Configure> binding.

# configure_tags t: the md_* tags on text widget t (idempotent).  Colours are
# theme tokens, so a dark/light switch retints them with everything else.
proc ::vmdai::md::configure_tags {t} {
    set C ::vmdai::theme::c
    $t tag configure md_p -spacing3 8
    $t tag configure md_li -lmargin1 0 -lmargin2 18 -tabs {18 left} -spacing3 4
    $t tag configure md_marker -foreground [$C muted]
    $t tag configure md_h1 -font ChatH2 -spacing1 12 -spacing3 6
    $t tag configure md_h2 -font ChatH2 -spacing1 8 -spacing3 4
    $t tag configure md_b -font ChatBodyBold
    $t tag configure md_code -font ChatCode -background [$C icode_bg]
    $t tag configure md_codehdr -font ChatMeta -foreground [$C muted] \
        -background [$C code_bg] -lmargin1 12 -lmargin2 12 -spacing1 8 -spacing3 2
    $t tag configure md_copy -foreground [$C accent]
    $t tag configure md_pre -font ChatCode -background [$C code_bg] \
        -lmargin1 12 -lmargin2 12 -rmargin 12
    $t tag configure md_pretail -background [$C code_bg] -spacing3 8
    catch {
        foreach tag {md_codehdr md_pre md_pretail} {
            $t tag configure $tag -lmargincolor [$C code_bg] -rmargincolor [$C code_bg]
        }
    }
    foreach tag {md_code md_b md_h1 md_h2 md_marker md_copy} {
        $t tag raise $tag
    }
    catch {$t tag raise sel}
    $t tag bind md_copy <Enter> {%W configure -cursor hand2}
    $t tag bind md_copy <Leave> {%W configure -cursor {}}
    $t tag bind md_copy <1> {::vmdai::md::copy_at %W @%x,%y}
    set w [_window_of $t]
    if {$w ne ""} {
        if {[string first ::vmdai::md::retab [bind $w <Configure>]] < 0} {
            bind $w <Configure> {+::vmdai::md::retab %W}
        }
        retab $w
    }
}

# retab w: right-align each code header's "Copy" at the content edge of
# text window w (a window path; tag configure passes through the proxy).
proc ::vmdai::md::retab {w} {
    if {[catch {winfo width $w} px]} {
        return
    }
    set px [expr {$px - 2 * [$w cget -padx] - 2}]
    if {$px < 100} {
        set px 480
    }
    $w tag configure md_codehdr -tabs [list [expr {$px - 12}] right]
}

# _window_of t -> the window path of text widget command t, or "".  A
# renamed widget command is matched to its window by a probe mark, which the
# window path (the read-only proxy passes "mark names" through) also sees.
proc ::vmdai::md::_window_of {t} {
    variable win
    if {[winfo exists $t]} {
        return $t
    }
    if {[info exists win($t)] && [winfo exists $win($t)]} {
        return $win($t)
    }
    set probe md_probe[incr ::vmdai::md::seq]
    if {[catch {$t mark set $probe 1.0}]} {
        return ""
    }
    set found ""
    foreach w [_text_windows .] {
        if {![catch {$w mark names} marks] && [lsearch -exact $marks $probe] >= 0} {
            set found $w
            break
        }
    }
    $t mark unset $probe
    set win($t) $found
    return $found
}

proc ::vmdai::md::_text_windows {w} {
    set out {}
    if {[winfo class $w] eq "Text"} {
        lappend out $w
    }
    foreach c [winfo children $w] {
        set out [concat $out [_text_windows $c]]
    }
    return $out
}

# render_into t index text ?basetags?: insert the Markdown rendering of text
# into writable text widget command t at index.  Every inserted character also
# carries basetags.  Adds no trailing newline, so it can replace a plain
# "$t insert $index $text $basetags".  Returns the index after the insertion.
proc ::vmdai::md::render_into {t index text {basetags {}}} {
    configure_tags $t
    # A mark at "end" would sit after the widget's final newline; insert
    # before it instead, as "$t insert end" does.
    set index [$t index $index]
    if {[$t compare $index > "end - 1c"]} {
        set index [$t index "end - 1c"]
    }
    set mark md_ins[incr ::vmdai::md::seq]
    $t mark set $mark $index
    $t mark gravity $mark right
    set prev ""
    foreach span [spans $text] {
        foreach {kind body attrs} $span break
        if {$prev eq "code"} {
            # The newline after a code block carries its tint to the edge.
            $t insert $mark "\n" [concat $basetags md_pretail]
        } elseif {$prev ne ""} {
            $t insert $mark "\n" $basetags
        }
        set prev $kind
        set lstart [$t index "$mark linestart"]
        switch -- $kind {
            para {
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_p $lstart $mark
            }
            heading {
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_h[dict get $attrs level] $lstart $mark
            }
            item {
                $t insert $mark "[dict get $attrs marker]\t" [concat $basetags md_marker]
                _inline $t $mark [dict get $attrs inline] $basetags
                $t tag add md_li $lstart $mark
            }
            code {
                _code_block $t $mark $body [dict get $attrs lang] $basetags
            }
        }
    }
    set end [$t index $mark]
    $t mark unset $mark
    if {$prev eq "code" && [$t get $end] eq "\n"} {
        $t tag add md_pretail $end "$end + 1c"
    }
    return $end
}

proc ::vmdai::md::_inline {t mark inl tags} {
    foreach sp $inl {
        foreach {k s} $sp break
        switch -- $k {
            bold {
                $t insert $mark $s [concat $tags md_b]
            }
            code {
                # NBSP: Tk never wraps at U+00A0, so the span stays on one
                # display line (Part B V1, prototypes/lead/nbsp.tcl).
                $t insert $mark [string map [list " " "\u00a0"] $s] [concat $tags md_code]
            }
            default {
                $t insert $mark $s $tags
            }
        }
    }
}

proc ::vmdai::md::_code_block {t mark body lang tags} {
    set label [expr {$lang eq "" ? "code" : $lang}]
    set hdr [concat $tags md_codehdr]
    $t insert $mark $label $hdr "\t" $hdr "Copy" [concat $hdr md_copy] "\n" $hdr
    set start [$t index $mark]
    $t insert $mark $body [concat $tags md_pre]
    if {[string tolower $lang] eq "tcl"} {
        ::vmdai::syntax::highlight $t $start $body
        ::vmdai::theme::syntax_tags $t
    }
}

# copy_at w index: copy the code block whose header line holds index.
proc ::vmdai::md::copy_at {w index} {
    set next [$w index "$index linestart + 1 line"]
    set r [$w tag nextrange md_pre $next]
    if {$r eq "" || [$w compare [lindex $r 0] != $next]} {
        return
    }
    copy [$w get [lindex $r 0] [lindex $r 1]]
}

# copy code: put code on the clipboard, through the panel's clipboard seam
# when it is loaded (the Tk tests stub it, so they never touch the real
# pasteboard); plain Tk clipboard otherwise.
proc ::vmdai::md::copy {code} {
    if {[llength [info commands ::vmdai::panel::_set_clipboard]]
            && ![catch {::vmdai::panel::_set_clipboard $code}]} {
        return
    }
    clipboard clear
    clipboard append -- $code
}

# plain_text s -> s with the NBSPs of rendered inline code turned back into
# spaces, for anything that copies transcript text to the clipboard.
proc ::vmdai::md::plain_text {s} {
    return [string map [list "\u00a0" " "] $s]
}
```

Notes on this code: the `Copy` link carries no per-block tag (so no counter ever reaches a golden); the click finds its block from the header line. Only `tcl` blocks get syntax colours (V9: no other languages in round 1).

- [ ] **Step 4: Render sealed blocks and copy plain spaces**

In `plugin/transcript.tcl`, directly after the `source ... syntax.tcl` line P10-T02 added, add:

```tcl
source [file join [file dirname [info script]] markdown.tcl]
```

In `plugin/transcript.tcl` (anchor S5), in the `block.seal` branch, replace the one statement that inserts the canonical text, `<W> insert <index> <canonical> <tags>`, by the same arguments passed to the renderer:

```tcl
::vmdai::md::render_into <W> <index> <canonical> <tags>
```

keeping that branch's own variable names for `<W>`, `<index>`, `<canonical>` and `<tags>` (for example `$W insert $at $text $tags` becomes `::vmdai::md::render_into $W $at $text $tags`). If the statement inserts more strings after the canonical text (for example a trailing `"\n" $tags`), split it: `set at2 [::vmdai::md::render_into $W $at $text $tags]` followed by `$W insert $at2 "\n" $tags`. Streaming chunks (`block.append`) are not touched: only sealed blocks are rendered.

In `plugin/panel.tcl` (anchor S8), in `proc ::vmdai::panel::copy_selection`, replace

```tcl
    set s [string map [list "\t" "  "] $s]
```

with

```tcl
    set s [::vmdai::md::plain_text [string map [list "\t" "  "] $s]]
```

so copied inline code pastes into VMD's console with real spaces.

- [ ] **Step 5: Run the new tests**

Run: `python -m pytest tests/test_tk_markdown_render.py tests/test_tcl_markdown.py tests/test_tcl_lint.py -q`
Expected: `8 passed` from the render file, `2 passed` from the spans file, lint passes.

- [ ] **Step 6: Regenerate the Tk goldens that contain sealed prose**

Run:
```bash
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py tests/test_panel_integration.py -q
git diff --stat tests/fixtures/
```
Expected: the tests pass, and exactly these four files change: `tests/fixtures/tk/03_conversation.txt`, `tests/fixtures/tk/reasoning_answer.txt`, `tests/fixtures/tk/panel_03_conversation.txt`, `tests/fixtures/tk/panel_resume_replay.txt`.

Review `git diff tests/fixtures/tk/` against this list; only sealed assistant text may change:
- `Loaded **1hck** as a cartoon on a white background.` loses its `**` and `1hck` gains `md_b`;
- `` `display backgroundcolor` does not exist; the color command alone is enough. `` loses its backticks, the code span's space becomes U+00A0 and it gains `md_code`;
- the other sealed lines (`The radius of gyration is 20.84 Å.`, `1hck has 2442 atoms.`, `I'll load 1hck and show it as a cartoon.`) only gain `md_p`;
- in `panel_03_conversation.txt` and `panel_resume_replay.txt` (P09-T09's scripted conversation), each sealed assistant line (`I'll count the atoms.`, `The structure has 42 atoms.`, `That command is not available here; retrying.`, `Done: the background command failed once, then the snapshot was taken.`) only gains `md_p`, and the two files stay identical;
- nothing in tool rows, run headers and chips, reasoning, notices, snapshot cards or the image count changes.

Anything else is a bug in the S5 edit (usually a lost base tag or an extra newline): fix it and regenerate. Then run without the variable:

Run: `python -m pytest tests/test_tk_transcript.py tests/test_panel_integration.py -q`
Expected: all pass.

- [ ] **Step 7: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+37 passed`, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add plugin/markdown.tcl plugin/transcript.tcl plugin/panel.tcl \
        tests/tcl/test_markdown_render.tcl tests/test_tk_markdown_render.py \
        tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt \
        tests/fixtures/tk/panel_03_conversation.txt tests/fixtures/tk/panel_resume_replay.txt
git commit -m "feat(plugin): render sealed blocks as Markdown (P10-T04)

block.seal now goes through ::vmdai::md::render_into: bold, NBSP inline
code on icode_bg, lists, headings and tinted code blocks with a Copy header
(tcl blocks syntax-coloured). Streaming text stays raw. Copy maps the NBSPs
back to spaces. Tk goldens regenerated for the rendered prose.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T05: Usage display

**Files:**
- Modify: `plugin/viewmodel.tcl` (append `usage_text` and `_count`; anchor S6: `_close_run`, which builds the `footer` op, gains an optional `usage_text` argument that `_on_request_finished` passes)
- Modify: `plugin/transcript.tcl` (append `usage_line`; anchor S6: replace `op_footer`, which in M2 draws nothing when `applied < 1`)
- Modify (regenerate): `tests/fixtures/ops/03_conversation.ops`, `reasoning_answer.ops`, `turn_retry.ops`, `loop_guard.ops`; `tests/fixtures/tk/03_conversation.txt`, `reasoning_answer.txt`, `panel_03_conversation.txt`, `panel_resume_replay.txt`
- Create: `tests/tcl/test_usage_footer.tcl`
- Test: `tests/test_tk_usage_footer.py`

**Interfaces:**
- Consumes: request.finished.usage (P07-T02) — `{input_tokens_evaluated, output_tokens}`, `null` for any value the provider did not report, summed over the request's turns (P04-T03 `last_usage`); the `footer` op `{footer <run> <applied_statements> <usage_text>}` (P08-T01, spec V4 View-model ops), built in `::vmdai::vm::_close_run sv req status final_text_empty duration_s` (P08-T01) and called by `_on_request_finished sv md ts` (P08-T03) and `_lose_request` (P08-T02); `::vmdai::vm::_get d key ?default?` (null → default); `::vmdai::transcript::op_footer run applied usage_text`, `_link`, the `footer` tag (P08-T06); `helpers.tcl.run_tcl`, `tcl_word` (P01-T03); `::m3::*` (P10-T01).
- Produces: `::vmdai::vm::usage_text usage -> string` — `"20.1k evaluated · 640 out"`; an unreported (null, missing, non-integer or negative) figure is left out; `""` when nothing is reported, which means "no usage line"; never mentions context. Also `::vmdai::vm::_count n -> string` (`640`, `5k`, `20.1k`, `1.2M`) and `::vmdai::transcript::usage_line W at run text` (a muted, right-aligned line tagged `usage usage:<run>`); replaced: `::vmdai::vm::_close_run … ?usage_text?` and `::vmdai::transcript::op_footer run applied usage_text` (same signatures, plus the optional argument). The view-model emits a `footer` op when the run applied a statement **or** reported usage; the Copy/Save links still need `applied > 0`.

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_usage_footer.tcl`:

```tcl
# P10-T05: the run footer's usage line (Part B V4 "Run footer"; spec 2c Usage).
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::usage_test {}
# One request with no tool calls that answers "Done." and reports `usage`.
proc ::usage_test::run {rid usage} {
    ::m3::use_mws
    ::harness::fresh_panel
    ::m3::render [::m3::ev system state "" [dict create kind request.started request_id $rid \
        chat_id chat_000000000092 provider ollama model qwen3.8:27b max_turns 28 vision true think false]]
    ::m3::render [::m3::ev assistant chunk "Done." [dict create request_id $rid turn 1]]
    ::m3::render [::m3::ev assistant message "Done." [dict create request_id $rid turn 1 final true]]
    ::m3::render [::m3::ev system state "" [dict create kind request.finished request_id $rid \
        status complete wrapped_up false turns 1 tool_calls 0 final_text_empty false duration_ms 1200 \
        usage $usage error null run_dir null]]
    ::harness::settle
    return $::vmdai::panel::text
}

test usage-line {the footer shows the usage line in muted text; no links without applied Tcl} -body {
    set t [::usage_test::run req_000000000092 [dict create input_tokens_evaluated 20100 output_tokens 640]]
    set idx [$t search -exact "20.1k evaluated \u00b7 640 out" 1.0 end]
    set muted 0
    foreach tag [$t tag names $idx] {
        if {![catch {$t tag cget $tag -foreground} fg] && $fg eq [::vmdai::theme::c muted]} { set muted 1 }
    }
    list [expr {$idx ne ""}] $muted [string first "Copy Tcl" [$t get 1.0 end]] \
        [string match -nocase "*context*" [$t get "$idx linestart" "$idx lineend"]]
} -result {1 1 -1 0}

test usage-null-no-line {a null usage prints no usage line and never "0 out"} -body {
    set t [::usage_test::run req_000000000093 [dict create input_tokens_evaluated null output_tokens null]]
    set all [$t get 1.0 end]
    list [string first "evaluated" $all] [string first " out" $all] [string first "0 out" $all]
} -result {-1 -1 -1}

cleanupTests
```

Create `tests/test_tk_usage_footer.py`:

```python
"""P10-T05: the run footer's usage line (Part B V4 Run footer; spec 2c Usage)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pytest

from helpers import tcl
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
TK_TOTAL = 2
DOT = "·"

# Pure Tcl, like plan 08's view-model tests: config.tcl and viewmodel.tcl only.
VM_PRELUDE = (
    "fconfigure stdout -encoding utf-8\n"
    "source %s\n" % tcl.tcl_word(str(PLUGIN / "config.tcl"))
    + "source %s\n" % tcl.tcl_word(str(PLUGIN / "viewmodel.tcl"))
    + "proc ev {role type text meta} {\n"
    "    dict create seq 0 ts 1790208000.0 role $role type $type text $text \\\n"
    "        metadata [dict merge [dict create v 2] $meta]\n"
    "}\n"
    "proc finished_ops {rid usage} {\n"
    "    ::vmdai::vm::init st\n"
    "    set ops {}\n"
    "    foreach e [list \\\n"
    "        [ev system state {} [dict create kind request.started request_id $rid \\\n"
    "            chat_id chat_000000000091 provider ollama model qwen3.8:27b max_turns 28 \\\n"
    "            vision true think false]] \\\n"
    "        [ev system state {} [dict create kind request.finished request_id $rid \\\n"
    "            status complete wrapped_up false turns 1 tool_calls 0 final_text_empty false \\\n"
    "            duration_ms 1200 usage $usage error null run_dir null]]] {\n"
    "        set ops [concat $ops [::vmdai::vm::apply st $e]]\n"
    "    }\n"
    "    return $ops\n"
    "}\n"
    "proc footers {ops} {\n"
    "    set out {}\n"
    "    foreach op $ops { if {[lindex $op 0] eq \"footer\"} { lappend out $op } }\n"
    "    return $out\n"
    "}\n"
)

USAGE_CASES = [
    ("input_tokens_evaluated 20100 output_tokens 640", "20.1k evaluated %s 640 out" % DOT),
    ("input_tokens_evaluated 5120 output_tokens null", "5.1k evaluated"),
    ("input_tokens_evaluated null output_tokens 211", "211 out"),
    ("output_tokens 0", "0 out"),
    ("input_tokens_evaluated 999 output_tokens 1000", "999 evaluated %s 1k out" % DOT),
    ("input_tokens_evaluated 999949 output_tokens 999950", "999.9k evaluated %s 1M out" % DOT),
    ("input_tokens_evaluated 1234567 output_tokens 5000", "1.2M evaluated %s 5k out" % DOT),
    ("input_tokens_evaluated {} output_tokens -3", ""),
]


def _tcl_lines(script: str) -> List[str]:
    proc = tcl.run_tcl(VM_PRELUDE + script)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


@pytest.fixture(scope="module")
def tk_results():
    return run_tk_file("test_usage_footer.tcl")


def test_usage_text():
    script = "".join("puts [::vmdai::vm::usage_text {%s}]\n" % usage for usage, _ in USAGE_CASES)
    assert _tcl_lines(script) == [text for _, text in USAGE_CASES]


def test_null_usage_omitted():
    lines = _tcl_lines(
        "puts [::vmdai::vm::usage_text {input_tokens_evaluated null output_tokens null}]\n"
        "puts [::vmdai::vm::usage_text {}]\n"
        "puts [::vmdai::vm::usage_text null]\n"
        "set ops [finished_ops req_000000000091 {input_tokens_evaluated null output_tokens null}]\n"
        "set texts {}\n"
        "foreach f [footers $ops] { lappend texts [lindex $f 3] }\n"
        "puts [llength [lsearch -all -inline -not -exact $texts {}]]\n"
        "puts [expr {[string first \"0 out\" $ops] >= 0 || [string first evaluated $ops] >= 0}]\n"
        "set ops [finished_ops req_000000000094 {input_tokens_evaluated 5120 output_tokens null}]\n"
        "puts [lindex [footers $ops] 0 3]\n"
    )
    assert lines == ["", "", "", "0", "0", "5.1k evaluated"]


def test_footer_without_statements():
    lines = _tcl_lines(
        "set f [footers [finished_ops req_000000000095 {input_tokens_evaluated 20100 output_tokens 640}]]\n"
        "puts [llength $f]\n"
        "puts [lindex $f 0 2]\n"
        "puts [lindex $f 0 3]\n"
    )
    assert lines == ["1", "0", "20.1k evaluated %s 640 out" % DOT]


def test_never_context_used():
    offenders = [p.name for p in sorted(PLUGIN.glob("*.tcl"))
                 if re.search(r"context\s+used", p.read_text(encoding="utf-8"), re.IGNORECASE)]
    assert offenders == []
    lines = _tcl_lines("puts [::vmdai::vm::usage_text {input_tokens_evaluated 20100 output_tokens 640}]\n")
    assert "context" not in lines[0].lower()


def test_usage_line_rendered(tk_results):
    assert_case(tk_results, "usage-line", TK_TOTAL)


def test_no_usage_line_when_null(tk_results):
    assert_case(tk_results, "usage-null-no-line", TK_TOTAL)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_usage_footer.py -q`
Expected: `5 failed, 1 passed`. `test_usage_text`, `test_null_usage_omitted` and `test_never_context_used` fail with `invalid command name "::vmdai::vm::usage_text"` in the Tcl stderr; `test_footer_without_statements` fails on its assertion (`['0', '', '']`: M2 emits no footer op for a run that applied nothing); `usage-line` fails (no usage text in the transcript); `test_no_usage_line_when_null` passes already (M2 prints no usage at all).

- [ ] **Step 3: Add `usage_text` to the view-model and fill the footer op**

Append to the end of `plugin/viewmodel.tcl`:

```tcl

# ---- M3 (plan 10, P10-T05): the run footer's usage line ----------------------
# usage_text usage -> "20.1k evaluated \u00b7 640 out" (Part B V4 Run footer).
# usage is request.finished.usage: a dict whose values may be null (json
# "null") or missing, or null/absent as a whole.  An unreported figure is left
# out, never shown as 0; "" means "no usage line".  The input figure is
# Ollama's prompt_eval_count, which leaves out the cached prefix, so the line
# says "evaluated" and is never labelled as the context (spec 2c).
proc ::vmdai::vm::usage_text {usage} {
    set parts {}
    foreach {key label} {input_tokens_evaluated evaluated output_tokens out} {
        if {[catch {dict get $usage $key} v]} {
            continue
        }
        if {![string is wideinteger -strict $v] || $v < 0} {
            continue
        }
        lappend parts "[_count $v] $label"
    }
    return [join $parts " \u00b7 "]
}

# _count n -> 640, 5k, 20.1k, 1.2M
proc ::vmdai::vm::_count {n} {
    if {$n < 1000} {
        return $n
    }
    if {$n < 999950} {
        set s [format %.1f [expr {$n / 1000.0}]]
        set unit k
    } else {
        set s [format %.1f [expr {$n / 1000000.0}]]
        set unit M
    }
    regsub {\.0$} $s {} s
    return $s$unit
}
```

Then, in `plugin/viewmodel.tcl` (anchor S6), thread the usage into the one place that builds the `footer` op:

1. In `proc ::vmdai::vm::_close_run` (P08-T01), change the argument list from `{sv req status final_text_empty duration_s}` to

```tcl
proc ::vmdai::vm::_close_run {sv req status final_text_empty duration_s {usage_text ""}} {
```

and replace

```tcl
    if {[dict get $run applied] > 0} {
        lappend ops [list footer [dict get $run id] [dict get $run applied] ""]
    }
```

with

```tcl
    if {[dict get $run applied] > 0 || $usage_text ne ""} {
        lappend ops [list footer [dict get $run id] [dict get $run applied] $usage_text]
    }
```

2. In `proc ::vmdai::vm::_on_request_finished` (the P08-T03 version), replace its last-but-one statement

```tcl
    lappend ops {*}[_close_run S $req $status $empty $secs]
```

with

```tcl
    lappend ops {*}[_close_run S $req $status $empty $secs [usage_text [_get $md usage]]]
```

`_get` returns `""` for a missing or `null` usage, which `usage_text` turns into `""`. `_lose_request` (a lost or ended request, P08-T02) keeps calling `_close_run` with five arguments, so it never shows usage. A footer now appears when the run applied a statement or reported usage; every M2 footer stays (the links' condition is unchanged). If Task 0 Step 6's S6 listing shows the footer op built somewhere else, make the same change there: pass `[usage_text <request.finished usage>]` as the fourth element and emit the op when `applied > 0` or that text is not empty.

- [ ] **Step 4: Run the pure tests**

Run: `python -m pytest tests/test_tk_usage_footer.py -q -k "usage_text or null_usage or without_statements or context"`
Expected: `4 passed`.

- [ ] **Step 5: Show the usage line in the transcript**

Plan 08's `op_footer` (P08-T06) returns before drawing anything when `applied < 1` and never prints its `usage_text`, so Task 0 Step 5 printed `footer_usage_rendered=0 footer_links_when_zero=0`. If it printed other values, plan 08's footer changed after this plan was written: apply the two rules below (links only when `applied >= 1`; the usage line whenever `usage_text` is not empty, after the links and outside their condition) to its footer branch instead of replacing the proc wholesale.

Append to the end of `plugin/transcript.tcl`:

```tcl

# ---- M3 (plan 10, P10-T05): the run footer's usage line ----------------------
# usage_line W at run text: a muted, right-aligned "20.1k evaluated \u00b7 640 out"
# line under the run footer (Part B V4); "" inserts nothing.  W is the
# writable widget command the footer branch inserts with.
proc ::vmdai::transcript::usage_line {W at run text} {
    if {$text eq ""} {
        return
    }
    $W tag configure usage -font ChatMeta -foreground [::vmdai::theme::c muted] \
        -justify right -spacing1 2 -spacing3 8
    set tags [list usage usage:$run]
    $W insert $at $text $tags "\n" $tags
}
```

Then replace the whole `proc ::vmdai::transcript::op_footer` (P08-T06, anchor S6) with:

```tcl
# The footer (Part B V4): "Copy Tcl . Save .tcl..." once the run applied at
# least one statement, then (M3) the muted usage line whenever the run
# reported usage, even when it applied nothing (loop_guard's stuck run).
proc ::vmdai::transcript::op_footer {run applied usage_text} {
    variable W
    variable RUN
    if {![info exists RUN($run,req)]} { return }
    if {[string is integer -strict $applied] && $applied >= 1} {
        set req $RUN($run,req)
        set tags [list footer]
        $W insert end "Copy Tcl" [concat $tags link [_link copy_run_tcl $req]] " \u00b7 " $tags \
            "Save .tcl\u2026" [concat $tags link [_link save_run_tcl $req]] "\n" $tags
    }
    usage_line $W end $run $usage_text
}
```

The link line is P08-T06's, byte for byte (its `·` and `…` written as `\u` escapes, the plan-10 rule for plugin code), so the existing footers in the goldens do not change.

- [ ] **Step 6: Run the Tk tests**

Run: `python -m pytest tests/test_tk_usage_footer.py tests/test_tcl_lint.py -q`
Expected: `6 passed` from the usage file, lint passes.

- [ ] **Step 7: Regenerate the op goldens, then the Tk goldens**

Run:
```bash
python - <<'PY'
import json, pathlib
def count(n):
    if n < 1000:
        return str(n)
    s, unit = ("%.1f" % (n / 1000.0), "k") if n < 999950 else ("%.1f" % (n / 1e6), "M")
    return (s[:-2] if s.endswith(".0") else s) + unit
for name in ("03_conversation", "reasoning_answer", "turn_retry", "loop_guard", "11_dead_runtime"):
    for line in pathlib.Path("tests/fixtures/events/%s.jsonl" % name).read_text().splitlines():
        meta = json.loads(line).get("metadata") or {}
        if meta.get("kind") == "request.finished":
            usage = meta.get("usage") or {}
            parts = ["%s %s" % (count(usage[k]), label) for k, label in
                     (("input_tokens_evaluated", "evaluated"), ("output_tokens", "out"))
                     if isinstance(usage.get(k), int)]
            print(name, "|", " · ".join(parts))
PY
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tcl_viewmodel.py -q
git diff --stat tests/fixtures/ops/
git diff -U0 tests/fixtures/ops/ | grep '^[-+][^-+]' | grep -v '^[-+]{\?footer '
```
Expected: the Python snippet prints one `<scenario> | <usage text>` line per `request.finished` (two for `03_conversation`, one each for `reasoning_answer`, `turn_retry` and `loop_guard`, none for `11_dead_runtime`); the view-model tests pass; exactly `03_conversation.ops`, `reasoning_answer.ops`, `turn_retry.ops` and `loop_guard.ops` change; the last command prints nothing (only `footer` lines change). Each changed or added `footer` line ends with the usage text the snippet printed for that request; `loop_guard.ops` gains a `footer` line with `0` applied statements (its run applied nothing but reported usage).

Run:
```bash
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_transcript.py tests/test_panel_integration.py -q
git diff --stat tests/fixtures/tk/
```
Expected: the tests pass; `03_conversation.txt` and `reasoning_answer.txt` change, and in each the only change is one new `usage` line per finished request (the text the snippet printed), directly under that run's footer. The two panel goldens (`panel_03_conversation.txt`, `panel_resume_replay.txt`) stay unchanged: P09-T09 serves them through P06-T11's `ScriptedLoop`, which overrides `_call` and never reaches a streamer's `on_meta`, so no `usage` event is emitted and `request.finished.usage` is `{"input_tokens_evaluated": null, "output_tokens": null}` (P07-T02), for which `usage_text` returns `""` and no usage line is drawn. If either panel golden does change, stop: the scripted runtime started reporting usage, and the change must be reviewed line by line before it is committed. No other golden and no other line may change. Then run without the variable:

Run: `python -m pytest tests/test_tcl_viewmodel.py tests/test_tk_transcript.py tests/test_panel_integration.py -q`
Expected: all pass.

- [ ] **Step 8: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+43 passed`, 0 failed.

- [ ] **Step 9: Commit**

```bash
git add plugin/viewmodel.tcl plugin/transcript.tcl \
        tests/tcl/test_usage_footer.tcl tests/test_tk_usage_footer.py \
        tests/fixtures/ops/03_conversation.ops tests/fixtures/ops/reasoning_answer.ops \
        tests/fixtures/ops/turn_retry.ops tests/fixtures/ops/loop_guard.ops \
        tests/fixtures/tk/03_conversation.txt tests/fixtures/tk/reasoning_answer.txt \
        tests/fixtures/tk/panel_03_conversation.txt tests/fixtures/tk/panel_resume_replay.txt
git commit -m "feat(plugin): usage line in the run footer (P10-T05)

::vmdai::vm::usage_text formats request.finished.usage as
'20.1k evaluated · 640 out', leaves out unreported (null) figures and
returns '' when there is nothing to show; the footer op carries it and the
transcript prints it muted and right-aligned. Op and Tk goldens regenerated.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T06: Final Tk goldens and the V8 additions

**Files:**
- Modify: `tests/tcl/m3_helpers.tcl` (append the T06 helpers at the end)
- Create: `tests/tcl/test_v8_additions.tcl` (Tk)
- Create: `tests/test_tk_v8_additions.py`
- Create (generated in Step 7): `tests/fixtures/tk/loop_guard.txt`, `tests/fixtures/tk/turn_retry.txt`, `tests/fixtures/tk/11_dead_runtime.txt`, `tests/fixtures/tk/03_conversation_dark.txt`

**Interfaces:**
- Consumes: every panel module as assembled by plan 09 and extended by P10-T01..T05 — `::vmdai::panel::render`, `text`, `win`; `::vmdai::transcript::create path`, `apply_ops`, `dump`, `relayout`, `toggle_detail`, `loaded_image_count` (P08-T05..T07); `::vmdai::vm::init`, `apply` (P08-T01); `::vmdai::executor::split_statements script -> dict {statements tail}` (P06-T08); `::vmdai::theme::set_appearance`, `mode`, `c`, `PALETTE` (P10-T01); the `syn_*` and `dcmd:<call_key>` tags (P10-T02); `::vmdai::md::plain_text` and the `md_*` tags (P10-T04); the usage line (P10-T05); `::m3::*` (P10-T01); `::harness::*` (P09-T01); `helpers.tk_cases.run_tk_file`, `assert_case` (P09-T01); `helpers.panel_goldens.compare_golden(actual, path)`, `EVENTS_DIR` (P08-T01); `helpers.tk.golden_path(name)` (P06-T10); the five event fixtures (P07-T08).
- Produces: the final Tk goldens `tests/fixtures/tk/{loop_guard,turn_retry,11_dead_runtime,03_conversation_dark}.txt` (a portable `::vmdai::transcript::dump`; the dark one followed by `::m3::colour_section`). Test helpers appended to `tests/tcl/m3_helpers.tcl` (P10-T07's capture tool also uses `save_appearance` and `index_of`): `::m3::save_appearance a ?geom?` (writes plugin.json), `::m3::index_of events kind n -> index`, `::m3::portable text -> text` (this checkout → `@REPO@`, `$HOME` → `@WORK@`), `::m3::with_colours dump colours -> text`, `::m3::line_diff a b -> list`, `::m3::light_left roots -> list`, `::m3::root_transcript ?geom? -> text path`, `::m3::feed events`.

Every Tk golden now exists for every scenario fixture: plan 08 wrote `03_conversation` and `reasoning_answer` from op scripts (P10-T04/T05 regenerated them); this task adds the other three plus `03_conversation_dark`, replayed through the assembled panel (`::m3::replay`, the same path the product takes: `vm::apply` → `panel::render`). The V8 "Add" list is owned by earlier tasks (plan 08 and P10-T04); this task pins that each item has an owner, and re-runs five of them on the finished M3 panel, where markdown, syntax colours, the usage line and dark mode now interact with them.

- [ ] **Step 1: Confirm the V8 owners exist**

Run:
```bash
grep -nE '^test (glue-1|status-1|err-1|out-1|expand-1|fit-1|group-1|group-2|group-3) ' tests/tcl/test_tool_rows.tcl
grep -nE '^test (md-1|md-2) ' tests/tcl/test_markdown_render.tcl
grep -nE '^test tk85-1 ' tests/tcl/test_snapshot_cards.tcl
grep -nE '^test offline-1 ' tests/tcl/test_statusbar_banner.tcl
grep -nE '^test composer-1 ' tests/tcl/test_composer.tcl
grep -nE '^test theme-1 ' tests/tcl/test_dark.tcl
grep -nE '^def (test_ro_1|test_sticky_autoscroll)\(' tests/test_tk_transcript.py
grep -nE '^def (test_failing_statement_highlight_matches_executor_split|test_chip_click_jumps)\(' tests/test_tk_tool_rows.py
grep -nE '^def (test_not_sent_to_model_shown|test_max_30_images)\(' tests/test_tk_snapshot_cards.py
grep -nE '^def test_unknown_call_key_ignored\(' tests/test_tcl_viewmodel.py
grep -nE '^def test_inline_code_never_wraps\(' tests/test_tk_markdown_render.py
```
Expected: 9 + 2 + 1 + 1 + 1 + 1 + 2 + 2 + 2 + 1 + 1 = 23 matching lines, one per name. A name that does not match is a naming difference in plan 08's tests (for example cases created in a loop, `test group-$n`): find the case or pytest function that runs it, use that file and name in `V8_OWNERS` in Step 3 (a tcltest name for a `.tcl` file, a `def` name for a `.py` file), and record the change in the PR description.

- [ ] **Step 2: Write the failing Tk test file**

Create `tests/tcl/test_v8_additions.tcl`:

```tcl
# P10-T06: final Tk goldens and the V8 additions (Part B V8; Part A section 6
# "Tk golden transcripts").  Dumps are written to $M3_OUT; the pytest wrapper
# tests/test_tk_v8_additions.py compares them with tests/fixtures/tk/.
source [file join $env(VMDAI_REPO) tests tcl panel_harness.tcl]
source [file join $env(VMDAI_REPO) tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop

namespace eval ::v8 {
    variable dark_dump ""
    variable dark_colours ""
}

# with ev key value -> ev with metadata.key set to value.
proc ::v8::with {ev key value} {
    dict set ev metadata $key $value
    return $ev
}

# first name kind -> the first event of fixture name whose metadata.kind is kind.
proc ::v8::first {name kind} {
    foreach ev [::m3::events $name] {
        if {![catch {dict get $ev metadata kind} k] && $k eq $kind} {
            return $ev
        }
    }
    error "$name has no $kind event"
}

# last_final evs -> the index of the last assistant message with final true.
proc ::v8::last_final {evs} {
    set last -1
    set i 0
    foreach ev $evs {
        if {[dict get $ev role] eq "assistant" && [dict get $ev type] eq "message"
                && ![catch {dict get $ev metadata final} f] && [string is true -strict $f]} {
            set last $i
        }
        incr i
    }
    return $last
}

# replay_03 -> 03_conversation through the panel with step 1's detail open,
# so a dump holds rendered Markdown, the usage lines and syntax colours.
proc ::v8::replay_03 {} {
    set t [::m3::replay 03_conversation]
    ::vmdai::transcript::toggle_detail [::m3::call_key_of 03_conversation 1]
    ::harness::settle
    return $t
}

# golden name -> replay fixture name in Light and write its portable dump.
proc ::v8::golden {name} {
    ::m3::use_mws
    ::m3::save_appearance light
    ::m3::replay $name
    set d [::m3::portable [::vmdai::transcript::dump]]
    ::m3::write_dump $name $d
    return [list [::vmdai::theme::mode] [regexp {^images [0-9]+\n} $d]]
}

# snapshot_request n png -> one request with n snapshot steps, cloned from
# 03_conversation's first request and its snapshot (call 4); every image
# (path and thumbnail) is png.
proc ::v8::snapshot_request {n png} {
    set k [::m3::call_key_of 03_conversation 4]
    set rid req_000000000555
    foreach ev [::m3::events 03_conversation] {
        if {[catch {dict get $ev metadata kind} kind]} {
            continue
        }
        if {$kind in {request.started request.finished} && ![info exists got($kind)]} {
            set got($kind) [with $ev request_id $rid]
        } elseif {$kind in {tool.started tool.finished} && [dict get $ev metadata call_key] eq $k} {
            set got($kind) [with $ev request_id $rid]
        }
    }
    dict set got(tool.finished) metadata image path $png
    dict set got(tool.finished) metadata image thumb_path $png
    set out [list $got(request.started)]
    for {set i 1} {$i <= $n} {incr i} {
        set key [format 9%011d $i]
        lappend out [with $got(tool.started) call_key $key] [with $got(tool.finished) call_key $key]
    }
    lappend out $got(request.finished)
    return $out
}

# ---- goldens for the three scenarios plan 08 left without one --------------

test v8-golden-loop_guard {loop_guard through the panel: nudge, stop, wrap-up, usage line} -body {
    ::v8::golden loop_guard
} -result {light 1}

test v8-golden-turn_retry {turn_retry through the panel: the retried partial block is gone} -body {
    ::v8::golden turn_retry
} -result {light 1}

test v8-golden-11_dead_runtime {11_dead_runtime through the panel: connection notices, no footer} -body {
    ::v8::golden 11_dead_runtime
} -result {light 1}

# ---- 03_conversation in Dark --------------------------------------------------

test v8-dark-fresh {03_conversation opened with Appearance Dark: dark tokens everywhere} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
} -body {
    set t [::v8::replay_03]
    set ::v8::dark_dump [::m3::portable [::vmdai::transcript::dump]]
    set ::v8::dark_colours [::m3::colour_section $t]
    ::m3::write_dump 03_conversation_dark [::m3::with_colours $::v8::dark_dump $::v8::dark_colours]
    list [::vmdai::theme::mode] [$t cget -background] [$t tag cget syn_cmd -foreground] \
        [$t tag cget md_code -background] [::m3::light_left [list $::vmdai::panel::win]]
} -cleanup {
    ::m3::save_appearance light
} -result {dark #1e1e1e #79c0ff #313135 {}}

test v8-dark-same_text {Dark changes colours only: the Light dump is the same text} -setup {
    ::m3::use_mws
    ::m3::save_appearance light
} -body {
    ::v8::replay_03
    list [::vmdai::theme::mode] [::m3::line_diff [::m3::portable [::vmdai::transcript::dump]] $::v8::dark_dump]
} -result {light {}}

# Continues from the Light panel v8-dark-same_text left open.
test v8-dark-switch_matches_fresh {switching that Light panel to Dark gives exactly the fresh Dark tags and text} -body {
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    list [::m3::line_diff [::m3::colour_section $::vmdai::panel::text] $::v8::dark_colours] \
        [::m3::line_diff [::m3::portable [::vmdai::transcript::dump]] $::v8::dark_dump]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {{} {}}

# ---- the V8 "Add" list, re-run on the finished M3 panel -----------------------

test v8-add-unknown_call_key {V8 add: an unknown call_key, a repeated tool.started and a second tool.finished change nothing} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
    ::v8::replay_03
    set before [::vmdai::transcript::dump]
} -body {
    set errs {}
    foreach ev [list \
            [::v8::with [::v8::first 03_conversation tool.finished] call_key ffffffffffff] \
            [::v8::first 03_conversation tool.started] \
            [::v8::first 03_conversation tool.finished]] {
        if {[catch {::m3::render $ev} err]} {
            lappend errs $err
        }
    }
    ::harness::settle
    list $errs [expr {[::vmdai::transcript::dump] eq $before}] [::vmdai::theme::mode]
} -cleanup {
    ::m3::save_appearance light
} -result {{} 1 dark}

test v8-add-failing_statement_dark {V8 add: in Dark, err_bg marks the executor's failing statement, under syntax colours} -setup {
    ::m3::use_mws
    ::m3::save_appearance dark
    set t [::v8::replay_03]
    set k [::m3::call_key_of 03_conversation 2]
    # A failed multi-statement step opens by itself (V4); open it if a
    # collapse closed it.
    if {![llength [$t tag ranges detail:$k]]} {
        ::vmdai::transcript::toggle_detail $k
        ::harness::settle
    }
} -body {
    set stmts [dict get [::vmdai::executor::split_statements \
        "color Display Background white\ndisplay backgroundcolor white"] statements]
    set err ""
    foreach tag [$t tag names] {
        if {[catch {$t tag cget $tag -background} bg] || $bg ne [::vmdai::theme::c err_bg]} {
            continue
        }
        foreach {a b} [$t tag ranges $tag] {
            if {"detail:$k" in [$t tag names $a]} {
                append err [$t get $a $b]
            }
        }
    }
    set syn {}
    foreach {a b} [$t tag ranges syn_cmd] {
        if {"dcmd:$k" in [$t tag names $a]} {
            lappend syn [$t get $a $b]
        }
    }
    list [expr {[string first [string trim [lindex $stmts 1]] $err] >= 0}] \
        [expr {[string first [string trim [lindex $stmts 0]] $err] < 0}] $syn [::vmdai::theme::c err_bg]
} -cleanup {
    ::m3::save_appearance light
} -result {1 1 {color display} #3a1f1e}

test v8-add-photo_cap_after_switch {V8 add: at most 30 images stay loaded, also after a Dark switch and a relayout} -setup {
    ::m3::use_mws
    ::m3::save_appearance light
    ::harness::fresh_panel
    set png [file join $::env(HOME) v8_thumb.png]
    set img [image create photo -width 64 -height 48]
    $img put #336699 -to 0 0 64 48
    $img put #ffcc00 -to 16 12 48 36
    $img write $png -format png
    image delete $img
} -body {
    foreach ev [::v8::snapshot_request 32 $png] {
        ::m3::render $ev
    }
    ::harness::settle
    set n1 [::vmdai::transcript::loaded_image_count]
    ::vmdai::theme::set_appearance dark
    ::vmdai::transcript::relayout
    ::harness::settle
    set n2 [::vmdai::transcript::loaded_image_count]
    list [expr {$n1 > 0 && $n1 <= 30}] [expr {$n2 > 0 && $n2 <= 30}]
} -cleanup {
    ::vmdai::theme::set_appearance light
} -result {1 1}

# The last two cases need real geometry, so the transcript is created in the
# withdrawn root window (plan constraint) and fed by its own view-model.
test v8-add-sticky_on_seal {V8 add: a scrolled-up view stays put while the final answer is sealed and rendered} -setup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
    set t [::m3::root_transcript 560x240]
    set evs [::m3::events 03_conversation]
    set last [::v8::last_final $evs]
    ::m3::feed [lrange $evs 0 [expr {$last - 1}]]
    ::harness::settle
    $t yview moveto 0.0
    ::harness::settle
    set before [$t yview]
} -body {
    ::m3::feed [lrange $evs $last end]
    ::harness::settle
    list [lindex $before 0] [expr {[lindex $before 1] < 1.0}] [lindex [$t yview] 0] \
        [string match {*20.84*} [lindex [::m3::ranges_text $t md_p] end]]
} -cleanup {
    ::harness::settle
    destroy .m3tx
} -result {0.0 1 0.0 1}

test v8-add-inline_code_nowrap {V8 add: the inline code in loop_guard's wrap-up never wraps, 380 to 560 px} -setup {
    ::m3::use_mws
    ::vmdai::theme::set_appearance light
    set t [::m3::root_transcript 380x700]
    ::m3::feed [::m3::events loop_guard]
    ::harness::settle
} -body {
    set spans {}
    set wrapped {}
    set para_wraps 0
    for {set w 380} {$w <= 560} {incr w 20} {
        wm geometry . ${w}x700
        update
        ::vmdai::transcript::relayout
        ::harness::settle
        foreach {a b} [$t tag ranges md_code] {
            set s [::vmdai::md::plain_text [$t get $a $b]]
            lappend spans $s
            if {[$t count -update -displaylines $a "$b - 1c"] != 0} {
                lappend wrapped $w:$s
            }
        }
        if {$w == 380} {
            # The paragraph itself wraps at 380 px, so the sweep moves the
            # spans across line ends.
            set first [lindex [$t tag ranges md_code] 0]
            set para_wraps [expr {[$t count -update -displaylines "$first linestart" "$first lineend"] > 0}]
        }
    }
    list [lsort -unique $spans] $wrapped $para_wraps
} -cleanup {
    ::harness::settle
    destroy .m3tx
} -result {{ResType {mol modcolor 0 top ResType} {mol modcolor 0 top ResidueType}} {} 1}

cleanupTests
```

The three spans are the backticked parts of the fixture's wrap-up answer (`LOOP_GUARD_WRAP_UP`, P07-T08); `lsort` puts `ResType` first because upper case sorts before lower case.

- [ ] **Step 3: Write the pytest wrapper and the two pure checks**

Create `tests/test_tk_v8_additions.py`:

```python
"""P10-T06: final Tk goldens and the V8 additions (Part B V8; Part A section 6).

tests/tcl/test_v8_additions.tcl replays fixtures through the assembled panel
and writes portable dumps to $M3_OUT; this module compares them with
tests/fixtures/tk/ (rewritten only when CHATVMD_UPDATE_GOLDENS=1). The last
two tests need no Tcl or Tk and run in CI: every test V8 lists has an owner,
and every event fixture has a Tk golden.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from helpers import tk
from helpers.panel_goldens import EVENTS_DIR, compare_golden
from helpers.tk_cases import assert_case, run_tk_file

REPO = Path(__file__).resolve().parents[1]
TOTAL = 11
NEW_GOLDENS = ("loop_guard", "turn_retry", "11_dead_runtime")
V8_FILE = "tests/tcl/test_v8_additions.tcl"

# What each new golden must hold and must not hold (V4 Run footer and
# Timeline notes, C4 Panel, section 2c Block boundaries). Commands are matched
# by their first words only: the withdrawn panel is 1 px wide, so rows are
# ellipsized (never below 12 characters, V6).
CONTENT: Dict[str, Tuple[List[str], List[str]]] = {
    "loop_guard": (["color the protein by residue type", "Coloring by residue type.",
                    "Stopped: the model kept repeating the same step", "ResType", "evaluated"],
                   ["`", "Copy Tcl"]),
    "turn_retry": (["load 1hck", "Loading 1hck now.", "Done: 1hck is loaded.", "evaluated"],
                   ["Loading 1hLoading"]),
    "11_dead_runtime": (["load 1hck", "mol new", "Connection lost at"],
                        ["evaluated"]),
}

# Part B V8, every test it lists.
NATIVE = ["glue-1", "status-1", "err-1", "out-1", "md-1", "md-2", "expand-1", "fit-1", "tk85-1"]
CARDS = ["ro-1", "group-1", "group-2", "group-3", "offline-1", "composer-1", "theme-1"]
ADD = [
    "inline code never wraps",
    "the failing-statement highlight matches the executor's split",
    '"Not sent to the model" is shown',
    "sticky autoscroll leaves a scrolled-up view alone",
    "an unknown call_key does nothing",
    "no more than 30 images stay loaded",
    "clicking a chip jumps to its step",
]

# (V8 test, owner file, tcltest case in a .tcl file or pytest function in a
# .py file). An added item may have two owners: its component test and the
# re-run on the finished M3 panel in this task.
V8_OWNERS: List[Tuple[str, str, str]] = [
    ("glue-1", "tests/tcl/test_tool_rows.tcl", "glue-1"),
    ("status-1", "tests/tcl/test_tool_rows.tcl", "status-1"),
    ("err-1", "tests/tcl/test_tool_rows.tcl", "err-1"),
    ("out-1", "tests/tcl/test_tool_rows.tcl", "out-1"),
    ("md-1", "tests/tcl/test_markdown_render.tcl", "md-1"),
    ("md-2", "tests/tcl/test_markdown_render.tcl", "md-2"),
    ("expand-1", "tests/tcl/test_tool_rows.tcl", "expand-1"),
    ("fit-1", "tests/tcl/test_tool_rows.tcl", "fit-1"),
    ("tk85-1", "tests/tcl/test_snapshot_cards.tcl", "tk85-1"),
    ("ro-1", "tests/test_tk_transcript.py", "test_ro_1"),
    ("group-1", "tests/tcl/test_tool_rows.tcl", "group-1"),
    ("group-2", "tests/tcl/test_tool_rows.tcl", "group-2"),
    ("group-3", "tests/tcl/test_tool_rows.tcl", "group-3"),
    ("offline-1", "tests/tcl/test_statusbar_banner.tcl", "offline-1"),
    ("composer-1", "tests/tcl/test_composer.tcl", "composer-1"),
    ("theme-1", "tests/tcl/test_dark.tcl", "theme-1"),
    (ADD[0], "tests/test_tk_markdown_render.py", "test_inline_code_never_wraps"),
    (ADD[0], V8_FILE, "v8-add-inline_code_nowrap"),
    (ADD[1], "tests/test_tk_tool_rows.py", "test_failing_statement_highlight_matches_executor_split"),
    (ADD[1], V8_FILE, "v8-add-failing_statement_dark"),
    (ADD[2], "tests/test_tk_snapshot_cards.py", "test_not_sent_to_model_shown"),
    (ADD[3], "tests/test_tk_transcript.py", "test_sticky_autoscroll"),
    (ADD[3], V8_FILE, "v8-add-sticky_on_seal"),
    (ADD[4], "tests/test_tcl_viewmodel.py", "test_unknown_call_key_ignored"),
    (ADD[4], V8_FILE, "v8-add-unknown_call_key"),
    (ADD[5], "tests/test_tk_snapshot_cards.py", "test_max_30_images"),
    (ADD[5], V8_FILE, "v8-add-photo_cap_after_switch"),
    (ADD[6], "tests/test_tk_tool_rows.py", "test_chip_click_jumps"),
]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("m3_out")
    # TZ=UTC: "Connection lost at <time>" in 11_dead_runtime (plan 08's rule).
    result = run_tk_file("test_v8_additions.tcl", env={"M3_OUT": str(out), "TZ": "UTC"})
    return result, out


def _dump(run, name: str) -> str:
    result, out = run
    path = out / ("%s.txt" % name)
    assert path.is_file(), "no dump for %s\n%s" % (name, result.output)
    return path.read_text(encoding="utf-8")


def _assert_portable(text: str) -> None:
    assert str(REPO) not in text, "the checkout path leaked into the dump"
    for temp in ("/var/folders/", "/private/tmp/", "/tmp/pytest-"):
        assert temp not in text, "a temp path leaked into the dump"


@pytest.mark.parametrize("name", NEW_GOLDENS)
def test_golden_replay(run, name):
    assert_case(run[0], "v8-golden-%s" % name, TOTAL)
    text = _dump(run, name)
    present, absent = CONTENT[name]
    assert [s for s in present if s not in text] == [], text
    assert [s for s in absent if s in text] == [], text
    _assert_portable(text)
    compare_golden(text, tk.golden_path(name))


def test_golden_03_conversation_dark(run):
    assert_case(run[0], "v8-dark-fresh", TOTAL)
    assert_case(run[0], "v8-dark-same_text", TOTAL)
    text = _dump(run, "03_conversation_dark")
    body, marker, colours = text.partition("# tag colours\n")
    assert marker, text
    assert "**" not in body and "evaluated" in body
    assert re.search(r"^syn_cmd -foreground #79c0ff$", colours, re.MULTILINE), colours
    assert re.search(r"^md_code -background #313135$", colours, re.MULTILINE), colours
    _assert_portable(text)
    compare_golden(text, tk.golden_path("03_conversation_dark"))


def test_dark_switch_matches_fresh(run):
    assert_case(run[0], "v8-dark-switch_matches_fresh", TOTAL)


def test_unknown_call_key_noop_in_panel(run):
    assert_case(run[0], "v8-add-unknown_call_key", TOTAL)


def test_failing_statement_highlight_in_dark(run):
    assert_case(run[0], "v8-add-failing_statement_dark", TOTAL)


def test_photo_cap_survives_theme_switch(run):
    assert_case(run[0], "v8-add-photo_cap_after_switch", TOTAL)


def test_sticky_autoscroll_on_markdown_seal(run):
    assert_case(run[0], "v8-add-sticky_on_seal", TOTAL)


def test_inline_code_never_wraps_in_transcript(run):
    assert_case(run[0], "v8-add-inline_code_nowrap", TOTAL)


def _defined(rel: str, name: str) -> bool:
    path = REPO / rel
    if not path.is_file():
        return False
    if rel.endswith(".tcl"):
        pattern = r"^test\s+%s\s" % re.escape(name)
    else:
        pattern = r"^def %s\(" % re.escape(name)
    return re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE) is not None


def test_v8_list_complete():
    assert {item for item, _, _ in V8_OWNERS} == set(NATIVE + CARDS + ADD)
    missing = ["%s: %s in %s" % (item, name, rel) for item, rel, name in V8_OWNERS
               if not _defined(rel, name)]
    assert missing == []


def test_every_fixture_has_a_tk_golden():
    fixtures = sorted(p.stem for p in EVENTS_DIR.glob("*.jsonl"))
    assert fixtures == ["03_conversation", "11_dead_runtime", "loop_guard", "reasoning_answer", "turn_retry"]
    missing = [n for n in fixtures + ["03_conversation_dark"] if not tk.golden_path(n).is_file()]
    assert missing == []
```

`test_every_fixture_has_a_tk_golden` is the module's last test, so a `CHATVMD_UPDATE_GOLDENS=1` run writes the goldens before it checks them.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_tk_v8_additions.py -q 2>&1 | tail -3`
Expected: `11 failed, 1 passed`. The ten Tk-backed tests fail because every tcltest case errors with `invalid command name "::m3::…"` (`save_appearance`, `line_diff` or `root_transcript`: the T06 helpers do not exist yet), so no dump is written; `test_every_fixture_has_a_tk_golden` fails with `missing == ['11_dead_runtime', 'loop_guard', 'turn_retry', '03_conversation_dark']`; `test_v8_list_complete` passes already (it pins the owners Step 1 found).

- [ ] **Step 5: Append the T06 helpers to `tests/tcl/m3_helpers.tcl`**

Append to the end of `tests/tcl/m3_helpers.tcl`:

```tcl

# ---- P10-T06 (also used by docs/design/round1/tools/capture_panel.tcl) --------

# save_appearance a ?geom?: plugin.json with Appearance a, read by the next
# ::vmdai::panel::build (P10-T01 applies it there).
proc ::m3::save_appearance {a {geom 560x780}} {
    ::vmdai::config::save_plugin_settings [dict create version 1 python "" appearance $a \
        expand_steps 0 geometry $geom]
}

# index_of events kind n -> the index of the n-th event whose metadata.kind is kind.
proc ::m3::index_of {events kind n} {
    set i 0
    set seen 0
    foreach ev $events {
        if {![catch {dict get $ev metadata kind} k] && $k eq $kind && [incr seen] == $n} {
            return $i
        }
        incr i
    }
    error "fewer than $n $kind events"
}

# portable text -> text with this checkout and $HOME written as the fixture
# placeholders @REPO@ and @WORK@ (::m3::events did the reverse), longest
# path first, so goldens do not depend on temp directories.
proc ::m3::portable {text} {
    set pairs {}
    foreach {path ph} [list $::env(VMDAI_REPO) @REPO@ $::env(HOME) @WORK@] {
        foreach p [lsort -unique [list $path [file normalize $path]]] {
            lappend pairs [list $p $ph]
        }
    }
    set map {}
    foreach pair [lsort -decreasing -command ::m3::_by_length $pairs] {
        lappend map {*}$pair
    }
    return [string map $map $text]
}

proc ::m3::_by_length {a b} {
    return [expr {[string length [lindex $a 0]] - [string length [lindex $b 0]]}]
}

# with_colours dump colours -> the dump, a newline if it lacks one, then colours.
proc ::m3::with_colours {dump colours} {
    if {$dump ne "" && [string index $dump end] ne "\n"} {
        append dump "\n"
    }
    return $dump$colours
}

# line_diff a b -> {} when a eq b, else up to five "line N: <a> | <b>".
proc ::m3::line_diff {a b} {
    set la [split $a "\n"]
    set lb [split $b "\n"]
    set n [expr {max([llength $la], [llength $lb])}]
    set out {}
    for {set i 0} {$i < $n && [llength $out] < 5} {incr i} {
        if {[lindex $la $i] ne [lindex $lb $i]} {
            lappend out "line [expr {$i + 1}]: [lindex $la $i] | [lindex $lb $i]"
        }
    }
    return $out
}

# light_left roots -> the places under roots that still hold a light-only colour.
proc ::m3::light_left {roots} {
    set lo [light_only]
    set left {}
    foreach e [colours $roots] {
        if {[lsearch -exact $lo [lindex $e 1]] >= 0} {
            lappend left [lindex $e 0]
        }
    }
    return $left
}

# root_transcript ?geom? -> the Text of a transcript created in the withdrawn
# root window "." (real size while withdrawn, unlike the panel's toplevel),
# with a fresh view-model ::m3::vm for ::m3::feed.  It replaces the panel's
# transcript (one per interpreter), so the next ::m3::replay rebuilds it.
proc ::m3::root_transcript {{geom 560x780}} {
    foreach w [winfo children .] {
        if {[winfo toplevel $w] eq "."} {
            destroy $w
        }
    }
    wm geometry . $geom
    set t [::vmdai::transcript::create .m3tx]
    pack .m3tx -fill both -expand 1
    ::vmdai::vm::init ::m3::vm
    update idletasks
    update
    ::vmdai::transcript::relayout
    update
    return $t
}

# feed events: events through ::m3::vm into the root transcript.  Status ops
# go to the status bar in the panel, so they are dropped here.
proc ::m3::feed {events} {
    foreach ev $events {
        set ops {}
        foreach op [::vmdai::vm::apply ::m3::vm $ev] {
            if {[lindex $op 0] ne "status"} {
                lappend ops $op
            }
        }
        if {[llength $ops]} {
            ::vmdai::transcript::apply_ops $ops
        }
    }
}
```

- [ ] **Step 6: Run the tests; only the missing goldens fail**

Run: `python -m pytest tests/test_tk_v8_additions.py -q 2>&1 | tail -3`
Expected: `5 failed, 7 passed`. The failures are the three `test_golden_replay[…]` and `test_golden_03_conversation_dark`, each with `missing golden …/tests/fixtures/tk/<name>.txt; run with CHATVMD_UPDATE_GOLDENS=1`, and `test_every_fixture_has_a_tk_golden` with the same four names. All eleven tcltest cases pass.

If a tcltest case fails instead, the M3 code has a real defect; fix it in the plugin (not in the test) and rerun:
- `v8-dark-fresh` lists places in its last element: those widgets, tags or items keep a Light colour when the panel is built in Dark, because they were configured with a literal colour instead of `::vmdai::theme::c <token>`. Configure them from the token in the module that creates them.
- `v8-dark-switch_matches_fresh` prints `line N: <switched> | <fresh>` for `# tag colours` lines: that tag's colour does not retint to what a fresh Dark render gives. Either it is not a token colour (configure it from its token), or its Light value is shared by two tokens and the tag is not named after either; P10-T01's `_retint_tags` maps a tag named after a token by that token, so use the token's name for the tag.
- `v8-add-sticky_on_seal` shows a third element other than `0.0`: sealing moved a scrolled-up view. The P10-T04 S5 edit must insert at the block's own index, and the transcript's sticky rule (autoscroll only when the view was at the bottom) must also run after a seal.
- `v8-add-inline_code_nowrap` lists `<width>:<span>` pairs: those spans broke across lines. Check that `::vmdai::md::_inline` still maps each space to U+00A0 (written as a Tcl `\u` escape) and that no tag on the span sets `-wrap char`.
- `v8-add-photo_cap_after_switch` shows `0` second: the theme switch or the relayout reloaded card images past the cap; reloads must go through plan 08's photo cap.
- `v8-add-failing_statement_dark` shows `0` first or second: the `err_bg` tag no longer covers exactly the failing statement in the step detail, or a raised tag hides its background.

- [ ] **Step 7: Record the new goldens and review them**

Run:
```bash
CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_tk_v8_additions.py -q 2>&1 | tail -1
git status --short tests/fixtures/
```
Expected: `12 passed`, and `git status` prints exactly these four lines and no ` M` line (no existing golden changes in this task):
```
?? tests/fixtures/tk/03_conversation_dark.txt
?? tests/fixtures/tk/11_dead_runtime.txt
?? tests/fixtures/tk/loop_guard.txt
?? tests/fixtures/tk/turn_retry.txt
```

Read each new file once. Every one starts with `images N`, uses only `@REPO@`/`@WORK@` for paths, and has no line that glues a tool row or a notice onto prose (S2). Then check:
- `loop_guard.txt` (`images 0`): the user block `color the protein by residue type`; `Coloring by residue type.`; four ✗ rows for the `mol modcolor …` command (rows are ellipsized in the 1 px wide withdrawn panel), each with its error line directly under it; the note `Stopped: the model kept repeating the same step`; the wrap-up answer with its three code spans on `md_code` and no backticks (the spaces inside the spans are U+00A0 in the file); one usage line, the text P10-T05 Step 7 printed for `loop_guard`; no `Copy Tcl` line (the run applied nothing).
- `turn_retry.txt` (`images 0`): `load 1hck`; `Loading 1hck now.` once and no `Loading 1hLoading`; the ✓ row for `mol new …`; the rule, then `Done: 1hck is loaded.`; the footer with `Copy Tcl` and the usage line P10-T05 Step 7 printed for `turn_retry`.
- `11_dead_runtime.txt` (`images 0`): `load 1hck`; the row for `mol new …`; the connection notes, among them `Connection lost at <time>` with the time taken from the fixture (UTC); no usage line and no footer (the request never finished).
- `03_conversation_dark.txt`: the same text as the Light panel replay (`v8-dark-same_text` checks it), with step 1's detail open, `1hck` and the inline code rendered, and two usage lines; then `# tag colours`, where every value comes from the dark column of V2 (for example `md_code -background #313135`, `syn_cmd -foreground #79c0ff`, `usage -foreground #9a9aa1`).

Anything else (a temp path, a raw `**`, a glued line, a Light colour in the dark file) is a defect: fix the plugin and regenerate.

- [ ] **Step 8: Prove every golden is final, then run the suites**

Run: `python -m pytest tests/test_tk_v8_additions.py tests/test_tcl_lint.py -q 2>&1 | tail -1`
Expected: all pass (`12 passed` from the new file).

Run every golden writer at once with the update flag; nothing tracked may change:
```bash
CHATVMD_UPDATE_GOLDENS=1 env -u VMD_AI_PROVIDER python -m pytest tests/test_event_fixtures.py \
    tests/test_tcl_viewmodel.py tests/test_tk_transcript.py tests/test_panel_integration.py \
    tests/test_tk_v8_additions.py -q 2>&1 | tail -1
git status --short tests/fixtures/
```
Expected: all pass, and `git status` prints the same four `??` lines as in Step 7 and nothing else: the event fixtures, the op goldens and every Tk golden are exactly what the finished M3 code produces.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+55 passed` (plus the unchanged skips), 0 failed, under 60 s. Without a GUI session: `B+24`.

- [ ] **Step 9: Commit**

```bash
git add tests/tcl/m3_helpers.tcl tests/tcl/test_v8_additions.tcl tests/test_tk_v8_additions.py \
        tests/fixtures/tk/loop_guard.txt tests/fixtures/tk/turn_retry.txt \
        tests/fixtures/tk/11_dead_runtime.txt tests/fixtures/tk/03_conversation_dark.txt
git commit -m "test(plugin): final Tk goldens and the V8 additions (P10-T06)

Tk goldens for loop_guard, turn_retry and 11_dead_runtime replayed through
the assembled panel, and 03_conversation in Dark with its tag colours, so
every scenario fixture has one. A registry test pins an owner for every
test Part B V8 lists; five V8 additions re-run on the finished M3 panel
(dark failing-statement highlight, unknown call_key, photo cap across a
theme switch, sticky autoscroll on a Markdown seal, inline code at 380-560 px).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task P10-T07: Visual review against the Native screenshots A–G

**Files:**
- Create: `docs/design/round1/tools/capture_panel.tcl`
- Create (captured in Step 3): `docs/design/round1/screenshots/panel/A_light.png`, `B_dark.png`, `C_midrun.png`, `D_empty.png`, `E_settings.png`, `F_narrow.png`, `G_disconnected.png`
- Create: `docs/design/round1/visual-review.md`

**Interfaces:**
- Consumes: `docs/design/round1/tools/capture_locked.sh <script> [args…]` and `tools/vmdtk_run.tcl` (they load VMD.app's Tk into `/opt/anaconda3/bin/tclsh8.6`, hold the screen lock at `/tmp/chatvmd_design_screen.lock`, and kill the script after 25 s); the reference renders `docs/design/round1/screenshots/native/{A_light,B_dark,C_midrun,D_empty,E_settings,G_disconnected}.png` (560×808) and `F_narrow.png` (466×808), each a window plus its 28 pt title bar; `tests/tcl/panel_harness.tcl` (`::harness::fresh_panel`, `settle`, `wait_until`, `stub_bridge`, `stub_desktop`, `busy`, `runtime_state`, `::fake::reply`) (P09-T01); `::m3::events`, `call_key_of`, `save_appearance`, `index_of` (P10-T01, P10-T06); `::vmdai::panel::show`, `on_event`, `refresh_info`, `rt_info`, `set_title`, `open_settings`, `on_runtime_state`, `text`, `win`, `headless` (P09); `::vmdai::vm::local_event` (P08-T02); `::vmdai::composer::set_text`, `focus` (P08-T08); `::vmdai::transcript::toggle_detail`, `relayout` (P08); `::vmdai::theme::macstyle`, `mode` (P10-T01).
- Produces: `capture_panel.tcl <A..G> </abs/out.png|-> ?WxH?` (exit 0 done, 2 usage, 3 error, 4 timeout; one log line per run in `$CAPTURE_LOG`, default `$TMPDIR/chatvmd_capture.log`), the seven captures, and the review record `docs/design/round1/visual-review.md`, which closes round 1 (§8 M3 exit, Success).

No automated test is added: the captures need a mapped window and the screen, which every test avoids. Step 2's dry run exercises the whole tool without mapping anything.

- [ ] **Step 1: Write the capture tool**

Create `docs/design/round1/tools/capture_panel.tcl`:

```tcl
# capture_panel.tcl - screenshot the real ChatVMD panel in the review states
# A-G of screenshots/native/ (spec Part A section 8, M3 exit; Part B V1).
#
#   docs/design/round1/tools/capture_locked.sh \
#       docs/design/round1/tools/capture_panel.tcl <A..G> </abs/out.png | -> [WxH]
#
# capture_locked.sh loads VMD.app's Tk 8.6 into tclsh (vmdtk_run.tcl) and
# holds the global screen lock.  The panel is the real plugin on the Tk test
# harness's fake transport (tests/tcl/panel_harness.tcl): no runtime, no
# network, and a temporary HOME, so ~/.vmdai is never read or written.  The
# conversation is tests/fixtures/events/03_conversation.jsonl, replayed
# through ::vmdai::panel::on_event with its times moved to "now".
#
#   A  Light: the conversation and a follow-up draft in the composer
#   B  A with Appearance Dark (MacWindowStyle sets this window to darkaqua)
#   C  mid-run: request 1 up to its third tool.started, step 1 expanded
#   D  the empty state (New chat)
#   E  A with Settings open on the Model tab
#   F  A at 466x780, the size of screenshots/native/F_narrow.png
#   G  A after the runtime went away: banner, timeline note, reconnecting
#
# out "-" builds the state withdrawn, logs one line and exits 0 without a
# screenshot, so it needs no screen lock.  Exit codes: 0 done, 2 usage,
# 3 error, 4 timeout.  Tk swallows stdout on macOS, so every run appends one
# line to $CAPTURE_LOG (default $TMPDIR/chatvmd_capture.log).

namespace eval ::cap {
    variable here [file dirname [file normalize [info script]]]
    variable repo [file normalize [file join $here .. .. .. ..]]
    variable follow "Now zoom on the binding pocket\nand make the protein transparent"
    variable title "CDK2 with ATP (1HCK)"
    variable tmp /tmp
    if {[info exists ::env(TMPDIR)] && $::env(TMPDIR) ne ""} {
        set tmp $::env(TMPDIR)
    }
    variable logfile [file join $tmp chatvmd_capture.log]
    if {[info exists ::env(CAPTURE_LOG)] && $::env(CAPTURE_LOG) ne ""} {
        set logfile $::env(CAPTURE_LOG)
    }
    variable home [file join $tmp chatvmd_capture_[pid]]
    variable state [lindex $::argv 0]
    variable out [lindex $::argv 1]
    variable geom [lindex $::argv 2]
}

proc ::cap::log {msg} {
    variable logfile
    variable state
    if {![catch {open $logfile a} fh]} {
        puts $fh "[clock format [clock seconds] -format %H:%M:%S] $state $msg"
        close $fh
    }
}

proc ::cap::finish {code} {
    variable home
    catch {file delete -force $home}
    exit $code
}

proc ::bgerror {msg} {
    ::cap::log "error: $msg | $::errorInfo"
    ::cap::finish 3
}

# vmdtk_run.tcl maps "." when it loads Tk; the panel is its own toplevel.
wm withdraw .
if {[lsearch -exact {A B C D E F G} $::cap::state] < 0 || $::cap::out eq ""} {
    ::cap::log "usage: capture_panel.tcl A..G /abs/out.png|- ?WxH?"
    ::cap::finish 2
}
if {$::cap::geom eq ""} {
    set ::cap::geom [expr {$::cap::state eq "F" ? "466x780" : "560x780"}]
}
after 14000 {::cap::log timeout; ::cap::finish 4}

# The harness expects the test environment; point it at this checkout.
set ::env(VMDAI_REPO) $::cap::repo
set ::env(VMDAI_PLUGIN_DIR) [file join $::cap::repo plugin]
if {![info exists ::env(VMDAI_TCL_TM)]} {
    set ::env(VMDAI_TCL_TM) /Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6
}
file mkdir [file join $::cap::home proj cdk2]
set ::env(HOME) $::cap::home
cd [file join $::cap::home proj cdk2]
source [file join $::cap::repo tests tcl panel_harness.tcl]
source [file join $::cap::repo tests tcl m3_helpers.tcl]
::harness::stub_bridge
::harness::stub_desktop
# Tests never touch the real MacWindowStyle; captures want it, so a forced
# Light or Dark also sets this window's title bar and native controls.
set ::vmdai::theme::macstyle ::tk::unsupported::MacWindowStyle
set ::vmdai::panel::headless [expr {$::cap::out eq "-"}]

# events upto -> 03_conversation's events 0..upto, moved so the last one
# happened 12 s ago (C's status timer then reads 00:12, as in C_midrun.png).
proc ::cap::events {upto} {
    set evs [lrange [::m3::events 03_conversation] 0 $upto]
    set shift [expr {[clock seconds] - 12 - [dict get [lindex $evs end] ts]}]
    set out {}
    foreach ev $evs {
        dict set ev ts [expr {[dict get $ev ts] + $shift}]
        lappend out $ev
    }
    return $out
}

# open_panel appearance: a fresh panel at the capture size (mapped unless
# dry), with the runtime.info and profile the status bar and empty state show.
proc ::cap::open_panel {appearance} {
    variable geom
    ::m3::save_appearance $appearance $geom
    ::harness::fresh_panel
    ::fake::reply runtime.info ok [dict create provider ollama model qwen3.8:27b agent_loop true \
        protocol 2 settings_source file]
    ::fake::reply profiles.list ok [dict create active qwen settings_source file profiles [dict create \
        qwen [dict create provider ollama base_url http://127.0.0.1:11435 model qwen3.8:27b \
            options [dict create num_ctx 32768]]]]
    ::fake::reply models.list ok [dict create models {} source server]
    ::fake::reply keys.test ok {ok false message {key missing} source none}
    ::vmdai::panel::show
    wm geometry $::vmdai::panel::win +80+70
    ::harness::settle
    ::vmdai::panel::refresh_info
    ::harness::wait_until {expr {$::vmdai::panel::rt_info ne ""}} 3000
    ::harness::settle
}

proc ::cap::conversation {upto} {
    variable title
    foreach ev [events $upto] {
        ::vmdai::panel::on_event $ev
    }
    ::vmdai::panel::set_title $title
    ::harness::settle
}

# draft text: text in the composer (focused), transcript scrolled to the end.
proc ::cap::draft {text} {
    ::vmdai::composer::set_text $text
    catch {::vmdai::composer::focus}
    ::vmdai::transcript::relayout
    ::harness::settle
    $::vmdai::panel::text yview moveto 1.0
}

proc ::cap::build {st} {
    variable follow
    set evs [::m3::events 03_conversation]
    set last [expr {[llength $evs] - 1}]
    switch -- $st {
        A - F {
            open_panel light
            conversation $last
            draft $follow
        }
        B {
            open_panel dark
            conversation $last
            draft $follow
        }
        C {
            open_panel light
            set ::harness::busy 1
            conversation [::m3::index_of $evs tool.started 3]
            ::vmdai::transcript::toggle_detail [::m3::call_key_of 03_conversation 1]
            draft ""
        }
        D {
            open_panel light
        }
        E {
            open_panel light
            conversation $last
            draft $follow
            ::vmdai::panel::open_settings model
            ::harness::wait_until {expr {[info exists ::vmdai::settings::v(profile)]
                && $::vmdai::settings::v(profile) eq "qwen"}} 3000
            set win $::vmdai::panel::win
            if {[winfo exists .vmd_ai_settings]} {
                wm geometry .vmd_ai_settings \
                    +[expr {[winfo rootx $win] + 30}]+[expr {[winfo rooty $win] + 40}]
            }
        }
        G {
            open_panel light
            conversation $last
            draft $follow
            set ::harness::runtime_state reconnecting
            ::vmdai::panel::on_runtime_state ready reconnecting \
                "Nothing answered on 127.0.0.1:8765. Retrying in 8 s."
            ::vmdai::panel::on_event [::vmdai::vm::local_event local.connection \
                [dict create state reconnecting detail "Runtime not reachable" request_lost 0]]
            ::harness::settle
            $::vmdai::panel::text yview moveto 1.0
        }
    }
    ::harness::settle
}

# shoot: the panel's region plus its 28 pt title bar, like screenshots/native;
# a dialog over the panel (E) is on screen there, so it is in the picture.
proc ::cap::shoot {} {
    variable out
    set top $::vmdai::panel::win
    raise $top
    if {[winfo exists .vmd_ai_settings] && [winfo ismapped .vmd_ai_settings]} {
        raise .vmd_ai_settings
    }
    update
    after 250
    update
    set x [winfo rootx $top]
    set y [winfo rooty $top]
    set w [winfo width $top]
    set h [winfo height $top]
    exec /usr/sbin/screencapture -x -o -R$x,[expr {$y - 28}],$w,[expr {$h + 28}] $out
    # Retina captures are 2x; the native renders are 1x ("half size").
    exec /usr/bin/sips --resampleWidth $w $out >/dev/null 2>/dev/null
    log "captured $out ${w}x[expr {$h + 28}] mode=[::vmdai::theme::mode]"
    finish 0
}

proc ::cap::dry {} {
    set t $::vmdai::panel::text
    set banner [expr {[winfo manager $::vmdai::panel::win.banner] ne ""}]
    log "dry ok mode=[::vmdai::theme::mode] lines=[lindex [split [$t index end] .] 0]\
        settings=[winfo exists .vmd_ai_settings] banner=$banner busy=$::harness::busy"
    finish 0
}

if {[catch {::cap::build $::cap::state} err]} {
    ::cap::log "error: $err | $::errorInfo"
    ::cap::finish 3
}
if {$::cap::out eq "-"} {
    after 300 ::cap::dry
} else {
    after 1500 ::cap::shoot
}
```

- [ ] **Step 2: Dry-run every state**

Run (no window is mapped, so the screen lock is not needed):
```bash
rm -f /tmp/chatvmd_capture.log
for s in A B C D E F G; do
  CAPTURE_LOG=/tmp/chatvmd_capture.log perl -e 'alarm 60; exec @ARGV' -- \
    /opt/anaconda3/bin/tclsh8.6 docs/design/round1/tools/vmdtk_run.tcl \
    docs/design/round1/tools/capture_panel.tcl "$s" -
  echo "$s exit=$?"
done
cat /tmp/chatvmd_capture.log
```
Expected: `A exit=0` through `G exit=0`, and seven `dry ok` log lines: `mode=dark` only for B, `settings=1` only for E, `banner=1` only for G, `busy=1` only for C, and `lines=2` for D (the empty state is an overlay; the transcript is empty). An `error:` line names the failing call and its stack: fix the tool (or, if the panel itself raises, the plugin) and rerun.

- [ ] **Step 3: Capture the seven states**

Preconditions: a GUI login session on the dev Mac with the screen awake and unlocked, and Screen Recording allowed for the terminal that runs the commands (System Settings → Privacy & Security; without it every capture shows only the desktop). The system appearance does not matter: every state forces Light or Dark on its own window.

Run:
```bash
mkdir -p docs/design/round1/screenshots/panel
for s in A_light B_dark C_midrun D_empty E_settings F_narrow G_disconnected; do
  CAPTURE_LOG=/tmp/chatvmd_capture.log perl -e 'alarm 150; exec @ARGV' -- \
    docs/design/round1/tools/capture_locked.sh docs/design/round1/tools/capture_panel.tcl \
    "${s%%_*}" "$PWD/docs/design/round1/screenshots/panel/$s.png"
done
tail -7 /tmp/chatvmd_capture.log
for f in docs/design/round1/screenshots/panel/*.png; do
  sips -g pixelWidth -g pixelHeight "$f" | tail -2 | tr '\n' ' '; echo "$f"; done
```
Expected: `capture_locked.sh` prints `exit=0` seven times; the log ends with seven `captured …` lines (B with `mode=dark`); every PNG is `pixelWidth: 560 pixelHeight: 808` except `F_narrow.png`, which is `466` × `808`, the sizes of the reference renders. If a capture shows another window or the desktop, close what covers the panel's position (+80+70) or grant Screen Recording, and rerun that state alone.

- [ ] **Step 4: Write the review record**

Create `docs/design/round1/visual-review.md`:

````markdown
# ChatVMD round 1 — visual review (M3 exit)

The M3 exit criterion (spec Part A §8) is a visual review of the real panel against the Native prototype screenshots in `docs/design/round1/screenshots/native/` (states A–G), with the Part B grafts applied. This file is that review's record, and it closes round 1 (§1 Success).

- **Reference:** `screenshots/native/<state>.png`, the judged Native renders (half size).
- **Capture:** `screenshots/panel/<state>.png`, the real plugin, made with `tools/capture_locked.sh tools/capture_panel.tcl <A..G> <absolute out.png>` (paths under `docs/design/round1/`).
- **Content:** the captures replay `tests/fixtures/events/03_conversation.jsonl` (load 1hck as a cartoon, a failed then recovered background command, a snapshot, then the radius of gyration). The prototype shows its own scripted conversation, so the words and step counts differ. The review compares layout, type, colour and behaviour, not wording.

| Field | Value |
|---|---|
| Plugin commit | pending |
| Captured on | pending |
| macOS and Tk | pending |
| System appearance while capturing | pending |

Each **Result** cell and header value starts unfilled and is filled with what was observed: `pass`, or `fixed in <commit>: <what changed>`. The review is complete when no cell is left unfilled.

## Expected differences from the Native screenshots

The Native prototype predates the grafts and the spec's required fixes (Part B V1), and round 1 leaves some of its features out (V9). These differences are by design, not defects:

1. **No "tunnel" in the status bar.** The left segment reads `Ollama · qwen3.8:27b · 127.0.0.1:11435`, not `… tunnel 127.0.0.1:11435` (V1 required fixes, V4 Status bar).
2. **No "Run in VMD" link.** A code block's header and the step detail offer `Copy` only (V4 "Run in VMD… / Run again…", V9).
3. **Step chips and a run summary** on each run header, such as `1 failed, recovered · N s` (cards graft, V4 Run header).
4. **A run footer:** `Copy Tcl · Save .tcl…` once the run applied a statement, and a muted usage line `N evaluated · M out` (console graft, M3).
5. **Collapse.** When run 2 starts, run 1 hides its work log; its header and chips, the failed row with its error line, the last snapshot card and the answer stay (cards graft, V4 Collapse).
6. **Tcl syntax colours** in the step detail (console graft, V4 Step detail).
7. **The console snapshot card:** purpose, `1280 × 1547 · TachyonInternal`, the file name, `Open · Reveal · Save PNG…` and `✓ Sent to the model` (V4 Snapshot card).
8. **Stop** is a pill with `stop_bg` in the Send cell while a request runs (cards graft, V4 Composer).
9. **The empty state** has four bordered example cards (2×2 at 520 px and wider), the Ready group with its trust row, and the key hints row (cards graft, V4 Empty state); Native D has a one-column "Try" list.
10. **Settings is a titled window** ("ChatVMD Settings", ttk notebook Model / Keys / Panel), not the override-redirect sheet (V1 "Not carried over").
11. **Chevrons** (▸) are `muted`, not `faint` (V1 required fixes).
12. **Window title** `ChatVMD — <chat title>`; the toolbar shows the chat title.

## A — Light (`A_light.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| A1 | 560 × 780; toolbar with New chat and History icons on the left, the title centred in ChatMetaBold, ⋯ and the gear on the right; a hairline under it | V3, V4 Toolbar | pending |
| A2 | "You" in ChatRole with the time right-aligned on the same line; the prompt in ChatBody | V4 Transcript blocks | pending |
| A3 | Each tool row is one line: glyph, command (mono, `text2`), muted suffix, duration, ▸ | V4 Tool rows | pending |
| A4 | The failed row's error line sits directly under it in `err`, visible without a click, also in the collapsed run 1 | V1, V4 Collapse | pending |
| A5 | Sealed prose is Markdown: `1hck` bold, `display backgroundcolor` as tinted inline code on one line; no `**` and no backticks | V4 Markdown | pending |
| A6 | The snapshot thumbnail is cropped of its border, fits 256 × 192 and is not cropped to fill; the caption is difference 7 | V4 Snapshot card | pending |
| A7 | A hairline rule before each final answer; footer and usage line right-aligned and muted | V4 Prose, Run footer | pending |
| A8 | Composer: rounded field, accent focus ring, the two-line draft; Send is the default button | V4 Composer | pending |
| A9 | Status bar: `●` in `ok`, provider · model · host:port on the left; `Auto-run Tcl ▾ │ ~/proj/cdk2 · N runs` on the right | V4 Status bar | pending |
| A10 | Chrome, surface, hairline and accent match `A_light.png` region by region | V2 | pending |

## B — Dark (`B_dark.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| B1 | Surface `#1e1e1e`, text `#e6e6eb`, the dark window background as chrome, hairlines `#0c0c0d` | V2 | pending |
| B2 | Title bar, scrollbar and Send button are dark (this window's MacWindowStyle appearance is `darkaqua`) | V2 System appearance | pending |
| B3 | Accent `#4ea1ff`, ok `#3bd16f`, err `#ff6b64`: glyphs and the error line read clearly | V2 | pending |
| B4 | Inline code on `#313135`; code blocks and step details on `#28282b` with the dark syntax colours | V2 | pending |
| B5 | Nothing is left in a Light colour (compare every region with `A_light.png`) | V2, P10-T06 | pending |
| B6 | Muted text (times, suffixes, the usage line) is readable on surface and chrome | V2 contrast | pending |

## C — Mid-run (`C_midrun.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| C1 | Status bar: a spinner, `Step 3 · running VMD command · 00:1x`, and `Esc to stop` on the right | V4 Status bar | pending |
| C2 | The running row shows the spinner and `running…` | V4 Tool rows | pending |
| C3 | Step 1's detail: a `code_bg` block indented 24 with `-lmargincolor`; the rationale muted; the exact command bytes with syntax colours; the `→` output; `Copy` | V4 Step detail | pending |
| C4 | Composer: the busy placeholder "Reply once this run finishes — or press Esc to stop" and the Stop pill in the Send cell | V4 Composer | pending |
| C5 | New chat and History are disabled | V4 Toolbar | pending |
| C6 | The run header's chips show the steps so far (`✓ ✗ •`) | V4 Run header | pending |

## D — Empty state (`D_empty.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| D1 | Visually centred: the mark, "What should VMD do?", the muted lead line | V4 Empty state | pending |
| D2 | Four bordered example cards in 2 × 2: Load & style, Binding pocket, Color by B-factor, Trajectory RMSD | V4 Empty state | pending |
| D3 | The Ready group with row dividers: Runtime, Model (Change), Folder (Change), and the trust row "Model-written Tcl runs unsandboxed in this VMD session. Only load files you trust." | V4 Empty state | pending |
| D4 | The key hints row `⏎ send · ⇧⏎ newline · ↑ last prompt · esc stop` | V4 Empty state | pending |
| D5 | Composer placeholder "Ask VMD to load, show or measure something…"; toolbar title "New chat" | V4 Composer | pending |
| D6 | In column mode (transcript < 520 px, e.g. a 420 px window) and in pair mode below about 650 px of height, the Ready group, trust row and key hints stay reachable (the overlay scrolls or the cards compact); parked from plan 09 T02 | V4 Empty state | pending |

## E — Settings (`E_settings.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| E1 | Settings is a titled transient window, "ChatVMD Settings", at least 460 px wide | V4 Settings | pending |
| E2 | ttk notebook tabs Model, Keys, Panel; the Model tab shows Profile, Provider, Server (mono) with its hint, Model with Refresh, Context, Snapshots, Test connection | V4 Settings | pending |
| E3 | Right-aligned regular-weight labels, one field column, hints under the fields | V4 Settings | pending |
| E4 | The footer "Changes apply to the next message." with Cancel and Save | V4 Settings | pending |
| E5 | The panel behind the dialog looks as in A | — | pending |

## F — Narrow, 466 px (`F_narrow.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| F1 | Narrow class: `-padx 14`, prose wraps, nothing scrolls sideways | V6 | pending |
| F2 | Rows stay one line; long commands end in an ellipsis and never drop below 12 characters | V6 Row refit | pending |
| F3 | The run header drops the model name first; the chips stay | V6 Run header | pending |
| F4 | The snapshot caption stacks under the image | V4 Snapshot card, V6 | pending |
| F5 | Status segments drop in the order host, run count, folder, provider; `Auto-run ▾` stays | V4 Status bar | pending |
| F6 | Inline code never breaks across lines | V4 Markdown, V8 | pending |

## G — Disconnected (`G_disconnected.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| G1 | The banner in slot 2: `warn_bg`, the warning triangle, bold "Runtime not reachable", a detail line with host:port and a countdown, pill buttons Retry now and Open log | V4 Banner | pending |
| G2 | One timeline note "Connection lost at … · your draft is kept", centred and muted | V4 Timeline notes | pending |
| G3 | The status bar shows the reconnecting state with the dot in `warn`, and no "tunnel" | V4 Status bar | pending |
| G4 | Send is disabled while the banner shows; the draft is kept | V4 Banner | pending |

## Grafts (Part B V1)

| Graft | Seen in | Result |
|---|---|---|
| Paint registry (console `theme::paint/repaint`) | B: every colour switched, including the native controls | pending |
| Tcl syntax colours (console `syntax::tokens`) | C: step 1's detail; B: the same in dark | pending |
| Snapshot card (console `snap::autocrop/thumb/card`) | A, F | pending |
| Status bar fitting (console `ui::status_fit`) | F | pending |
| Width classes (console `wide`/`narrow` elide tags) | F | pending |
| Read-only transcript (cards proxy) | A: the transcript takes focus and selects text; `ro-1` covers the behaviour | pending |
| Inline code with NBSP (cards `md::inline`) | A, F | pending |
| Collapse (cards group `-elide`) | A: run 1 collapsed | pending |
| Empty state (cards `welcome` cards) | D | pending |

## Round 1 exit (§1 Success, §8)

| # | Criterion | Measured by | Result |
|---|---|---|---|
| S1 | A follow-up sees prior turns, tool blocks included | pytest (the 2nd `chat.send`'s prior) in `tests` | pending |
| S2 | No transcript glue | Tk goldens `03_conversation`, `reasoning_answer` and the P10-T06 goldens | pending |
| S3 | Kill or restart: at most 1 notice per state change, recovery within 10 s | tclsh bridge test in `tests` | pending |
| S4 | Close/reopen and reload repeat cleanly; SIGTERM exit within 2 s | pytest SIGTERM test and tclsh registry test in `tests` | pending |
| S5 | Ollama `qwen3.8:27b` sees snapshots | `tests/test_live_ollama.py` against the live server | pending |
| S6 | An unreachable Ollama fails within 3 s with the right hint | socket tests in `tests` | pending |
| S7 | No benchmark-visible change with `options=None` | golden requests, retry pin, bridge guard, hashes in `tests` | pending |
| S8 | Å, → and ° round-trip | tclsh 8.6 with http 2.9.5 in `tests` | pending |
| S9 | Suite green, hermetic, under 60 s | `env -u VMD_AI_PROVIDER python -m pytest tests -q` | pending |
| S10 | `save_path` writes a real file; `puts` output reaches the model | executor tests in `tests` | pending |
| S11 | Foreign Host or Origin rejected; privileged RPCs need the token | security tests in `tests` | pending |
| S12 | A ```` ```tcl ```` block in prose runs nothing | pytest (no `tool_start`) in `tests` | pending |
| V | Visual review A–G with the grafts | this file | pending |
| — | `vmdbench` 90 passed; `explore_arm` + `scivisagentbench` 62 passed; no runtime, integrations, vmdbench or scripts change in M3 | the Step 6 commands | pending |
````

- [ ] **Step 5: Compare each pair and fill in the record**

For each state, view `docs/design/round1/screenshots/native/<state>.png` and `docs/design/round1/screenshots/panel/<state>.png` side by side (the Read tool shows PNGs; on the Mac, `open` both in Preview). Work through that state's table: replace `pending` with `pass` when the capture shows what the check says (the expected differences are not defects), and fill in the four header fields (`git rev-parse --short HEAD`, the date, `sw_vers -productVersion` and Tk `8.6.12`, and the system appearance).

A check that fails is a defect. Fix it in the plugin in its own commit, `fix(plugin): <what> (P10-T07 visual review)`, with a test in the owning task's test file when the defect is testable headlessly (a colour, a tag, a string, a count); rerun that file and `env -u VMD_AI_PROVIDER python -m pytest tests -q`. If the fix changes a Tk golden on purpose, regenerate only that golden with `CHATVMD_UPDATE_GOLDENS=1` on its test file, check with `git diff tests/fixtures/` that only the intended lines changed, and say so in the commit message. Recapture the affected states (Step 3 for those names only) and record the check as `fixed in <short sha>: <what changed>`.

Run: `grep -c pending docs/design/round1/visual-review.md`
Expected: `14` (it was `69` when the file was created): only the round-1 exit table is left, for Step 6. Every header field, A–G row and graft row is filled.

- [ ] **Step 6: Run the round-1 exit checks and fill in the exit table**

Run:
```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
git diff main --stat -- runtime/ integrations/ vmdbench/ scripts/
perl -ne 'print "$ARGV:$.: $_" if /[^\x00-\x7F]/' plugin/syntax.tcl plugin/markdown.tcl
```
Expected: `B+55 passed` (plus the unchanged skips), 0 failed, under 60 s (plus one per visual-review fix test added in Step 5); `90 passed`; `62 passed`; the `git diff` and the `perl` scan print nothing.

S5 needs the live model. Run: `curl -s --max-time 3 http://127.0.0.1:11435/api/version`. If it prints nothing, stop and ask the owner to bring the tunnel up; S5 is met only by a passing live run (as in plan 04). Then run:
`VMD_AI_LIVE_OLLAMA=http://127.0.0.1:11435 VMD_AI_LIVE_MODEL=qwen3.8:27b env -u VMD_AI_PROVIDER python -m pytest tests/test_live_ollama.py -q`
Expected: `2 passed` (each can take a minute or two on the 27B model).

Fill in the round-1 exit table: `pass (tests: <N> passed in <T> s)` for S1–S4 and S6–S12, `pass (tests/test_live_ollama.py: 2 passed, <date>)` for S5, `pass` for V (every A–G and graft row is `pass` or `fixed in …`), and `pass (90 / 62 / no diff)` for the last row.

Run: `grep -c pending docs/design/round1/visual-review.md`
Expected: `0`.

- [ ] **Step 7: Commit**

```bash
git add docs/design/round1/tools/capture_panel.tcl docs/design/round1/screenshots/panel/*.png \
        docs/design/round1/visual-review.md
git commit -m "docs(design): visual review of the real panel against Native A-G (P10-T07)

capture_panel.tcl drives the real plugin on the test harness's fake
transport through states A-G and screenshots it under capture_locked.sh;
the captures sit next to screenshots/native. visual-review.md records the
comparison (expected differences from the grafts and required fixes,
every check A1-G4, the grafts) and the round-1 exit: S1-S12 and the suites.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Plan exit check

- [ ] `env -u VMD_AI_PROVIDER python -m pytest tests -q` — `B+55 passed` (plus one per Step-5 fix test), 0 failed, under 60 s, from a GUI login session on the dev Mac; CI (no Tk) counts `B+24` and stays green on Python 3.9 and 3.12.
- [ ] `python -m pytest tests/test_tcl_lint.py -q` passes for `plugin/syntax.tcl`, `plugin/markdown.tcl` and the edited `theme.tcl`, `settings.tcl`, `panel.tcl`, `transcript.tcl`, `viewmodel.tcl`; the P10-T07 Step 6 `perl` scan prints nothing.
- [ ] `python -m pytest vmdbench/tests -q` — 90 passed; `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q` — 62 passed; `git diff main --stat -- runtime/ integrations/ vmdbench/ scripts/` prints nothing.
- [ ] Rerunning the P10-T06 Step 8 golden sweep after the last commit leaves `git status --short tests/fixtures/` empty.
- [ ] `grep -c pending docs/design/round1/visual-review.md` prints `0`, and `docs/design/round1/screenshots/panel/` holds the seven captures.
- [ ] Manual smoke in VMD 1.9.4a57: Extensions → VMD AI; Settings → Panel → Appearance Dark → Save turns the panel dark at once; with Appearance System and Settings open, switching macOS to Dark in System Settings repaints both windows; an answer with `**bold**`, inline code and a fenced tcl block renders when it seals, and the block's `Copy` puts the exact code on the clipboard; each finished run's footer shows `N evaluated · M out`.

## Deviations from skeleton

1. **Task 0 (pre-flight).** Not in the skeleton. It checks every row of the "Consumed contract" table against the merged plans 06–09, records the baseline `B`, the two footer facts P10-T05 Step 5 checks, and the anchors S3–S8 later tasks edit.
2. **P10-T01 scope.** Besides `theme.tcl` and `settings.tcl`, it edits `plugin/panel.tcl` (the saved appearance is applied at build), `tests/tcl/panel_harness.tcl` and `tests/tcl/panel_driver.tcl` (tests never read the real OS appearance), and creates `tests/tcl/m3_helpers.tcl`, shared by every later task and by the capture tool. The palette keeps five extra native-prototype tokens (`sel`, `field_bd`, `focus_ring`, `spin_hi`, `spin_lo`). The internal mode switch is `_apply_mode`, because M2's `theme.tcl` already owns `_apply w spec`. Besides `set_appearance` it produces `PALETTE`, `palette`, `appearance`, `appearance_choices`, `has_macwindowstyle`, `system_is_dark`, `effective`, `saved_appearance`, `own`, `owned_toplevels`, `bind_system_events`, `on_system_event`, `macstyle` and `settings::_apply_appearance`, with five tcltest cases beyond the skeleton's (`dark-forced_sets_window_appearance`, `dark-dialog_opened_later`, `dark-save_applies`, `dark-every_m2_token`, `dark-other_windows_untouched`).
3. **P10-T02 files.** It creates `plugin/syntax.tcl` (the skeleton names only the interface) and a Tk file, `tests/tcl/test_syntax_detail.tcl`, with three cases; it adds `::vmdai::syntax::highlight`, `highlight_tag`, `::vmdai::theme::syntax_tags` and the `dcmd:<call_key>` tag. It also regenerates `tests/fixtures/tk/03_conversation.txt`: that golden shows the auto-opened detail of the failed two-statement call, whose command lines now carry `syn_*` tags (the skeleton lists no golden for this task).
4. **P10-T04 interface and files.** `render_into t index text ?basetags?` takes optional base tags and returns the index after the insertion, so it can replace the seal's one `insert`. The task also appends to `plugin/markdown.tcl`, edits `plugin/panel.tcl` (copy maps NBSP back to spaces) and regenerates `panel_03_conversation.txt` and `panel_resume_replay.txt`, which also contain sealed prose. Extra cases: `md-inline-nowrap`, `md-codehdr`, `md-basetags`, `md-proxy`, `md-seal`, `md-copy-plain`.
5. **P10-T05 behaviour and files.** The view-model now emits a `footer` op when a run applied nothing but reported usage (so `loop_guard.ops` gains one); the Copy/Save links still need an applied statement. It adds `::vmdai::vm::_count` and `::vmdai::transcript::usage_line`, gives P08's `_close_run` an optional `usage_text` argument (passed by `_on_request_finished` only), and replaces P08's `op_footer`, which drew nothing for `applied < 1`, so the links keep their condition and the usage line gets its own. It regenerates four op goldens and two Tk goldens (the two panel goldens too if P06-T11's scripted runtime reports usage).
6. **P10-T06 method.** The new goldens are replayed from the event fixtures through the assembled panel (`vm::apply` → `panel::render`), not from op scripts like plan 08's, and `03_conversation_dark.txt` adds a `# tag colours` section. "V8 add list complete" is a pure registry test that runs in CI (every V8 test has an owner that exists), and five add items are re-run on the finished M3 panel; `test_every_fixture_has_a_tk_golden` is added. The task extends `tests/tcl/m3_helpers.tcl`.
7. **P10-T07 files and scope.** It also creates the seven captures in `docs/design/round1/screenshots/panel/`. The capture tool runs the real plugin on the Tk test harness's fake transport (no runtime, a temporary HOME). The review record also carries the round-1 exit table (S1–S12, the suites), which closes round 1.
8. **Editorial fixes made while completing this plan.** Literal non-ASCII characters in the plugin code of P10-T03..T05 (the list bullet, the NBSP in `_inline` and `plain_text`, the middle dot of the usage line) were replaced by Tcl `\u` escapes, as the plan-specific constraints require; a pasted NBSP is invisible, and losing it would silently turn the inline-code mapping into a no-op. The expected totals line now matches the tasks (P10-T05 is `B+43`, as its Step 8 says; P10-T06 adds 12 tests, 2 of them pure), and the file-map row for `m3_helpers.tcl` names only the tasks that extend it (T01, T06).
9. **Review fixes (checked against plans 08 and 09 as written, and by running the code from scratch copies).** P10-T01's `_apply` was renamed `_apply_mode` (the old name replaced M2's paint helper and broke `paint`), `dark-other_windows_untouched` states its `#`-first result with `[list …]`, and `HERE` is guarded. P10-T02's S4 edit names `_build_detail`'s segment insert, `syntax-detail-only-command` accepts any step's `dcmd:*` (call 2's detail opens by itself), and a golden step was added. P10-T04's `md::copy` goes through `::vmdai::panel::_set_clipboard` when loaded, so `md-codehdr` reads the harness's recorder instead of the real pasteboard. P10-T05's S6 edits name `_close_run`/`_on_request_finished` and replace `op_footer`: the earlier "insert after the Copy Tcl line" wording could never show the usage line of a run that applied nothing. Non-ASCII literals that tests compare with plugin output (the bullet, `Å`, the NBSP, the middle dot) are `\u` escapes, so the result does not depend on the encoding `source` uses.
