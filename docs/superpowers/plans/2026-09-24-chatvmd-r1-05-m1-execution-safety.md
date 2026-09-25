# ChatVMD Round 1 — Plan 05: ChatVMD R1 — M1 execution and safety (C1–C6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the product bridge honest and safe: ack with state, deadlines, cancel and late results; runtime-owned snapshots with image/thumbnail files and save_path; the critical-Tcl guard; structured partial failures; the loop guard with wrap-up; full output on disk; run provenance.

**Architecture:** The product `VmdToolBridge` becomes a call registry keyed by `call_key` for token-authenticated sessions (ack with state, pickup and exec deadlines, cancel grace, dedupe, late results). It owns the snapshot files and the C5 output cut, and it refuses critical Tcl through the new stdlib module `tcl_policy` before anything is queued; tokenless sessions keep today's `tool_call_id` path. `ClaudeToolLoop` only gains behaviour that sits behind `LoopOptions` or `ctx` (structured failure text, the `loop_guard` detector plus one tool-less wrap-up call through `tool_mode="none"`, recorder provenance), so requests with `options=None` and `ctx=None` stay byte-identical (S7), and `RunRecorder` learns partial-failure writes, TachyonInternal replay lines and an opt-in provenance manifest.

**Tech Stack:** Python 3.9–3.12 standard library only (`threading`, `dataclasses`, `json`, `hashlib`, `urllib.parse`), optional Pillow through plan 04's `image_scale`, pytest; Tcl 8.6 only through `tests/helpers/tcl.py` for one transcript-parse check.

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — this plan implements §2d (Deadlines, Cancel semantics, Post, Snapshot), §2b (Late results, Repairing unanswered tool calls), §2c (Thumbnails; the runtime side of the `tool.finished` fields), §3 (`tool_bridge.py`, `tcl_policy.py`, `loop_guard.py`, `recorder/run.py`, `protocol.py`; RPC rows `tool.ack` and `tool.command_result`), §5 (rows: no ack within 45 s, Stop not acked / running, critical Tcl word, incomplete Tcl, loop detected, max turns) and Part C **C1, C2, C3 (runtime), C4 (runtime), C5 (runtime), C6**. Part C wins where it conflicts with Parts A/B.

**Branch:** `chatvmd-r1-05-m1-execution-safety`, created from `main` after plans 01–04 are merged.

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

- The product result dict returned by `VmdToolBridge` for token sessions always has exactly these keys: `ok, output, error, executed ('yes'|'no'|'unknown'), truncated, duration_ms, statements ({total, applied, failed|null} or null), blocked (list or null), output_path, output_bytes, image (dict or null), saved_path, applied_text`, plus `image_b64`/`image_mime` for a snapshot with an image (the loop's existing contract).
- The tokenless (legacy) path keeps today's `tool_start` metadata keys `{tool_call_id, tool_name, tool_input, session_id}`, its single `timeout` wait, `resolve()` and its cancel result `{"ok": False, "output": "", "error": "cancelled"}`. It gains only C1 blocking, the `/tmp/vmdai_snap_<tool_call_id>.tga` snapshot restriction (§2d) and the C5 cut when the session's chat directory is known.
- `SubprocessVmdBridge`, every file under `integrations/`, `VMD_TOOLS` and `image_utils.py` stay untouched. `tcl_policy.check` is called only by `VmdToolBridge`.
- Bridge tests drive `execute_tool` on a worker thread through `tests/helpers/bridge_harness.py` with sub-second timeouts; no test in this plan sleeps longer than 0.6 s.
- Line numbers under **Files** are from commit 6f5f937. Plans 01–04 shift them; locate each edit by the quoted anchor text, which Task 0 prints.

## Review Focus

1. Stop lands between the ack and the result: the executed status stays consistent (a result inside the grace window is reported as `yes`; after it, `unknown`) and the late result is stored as a `late_result` line. Owner P05-T02: `tests/test_tool_bridge_results.py::test_stop_between_ack_and_result` and `::test_late_result_stored_as_late_result_line`.
2. False positives: `puts "exit code"` and `atomselect top "resname EXE"` (and the other seven C1 allowed cases) must not be blocked. Owner P05-T04: `tests/test_tcl_policy.py::test_allowed_cases`.
3. `save_path` in a missing directory, or a `../` path, gives `ok:false` with a message, writes nothing and never crashes; the render itself still reaches the model. Owner P05-T03: `tests/test_snapshot_files.py::test_save_path_bad_dir`.
4. A 200 KB single-line output, or text carrying undecodable characters, is cut safely: head and tail kept, within 6000 characters plus the note, the saved file written, the model's copy valid UTF-8. Owner P05-T07: `tests/test_tool_output_disk.py::test_200kb_single_line`.
5. Calls that differ only in `rationale` or whitespace count as the same signature. Owner P05-T08: `tests/test_loop_guard.py::test_signature_ignores_rationale_whitespace`.

---

### Task 0: Pre-flight — confirm plans 01–04 are merged and their interfaces exist

**Files:**
- Create (temporary, never committed): `tests/test_zz_preflight_05.py`

**Interfaces:**
- Consumes: every interface listed under "Consumes" in Tasks 1–10 (plans 01–04).
- Produces: the baseline pass count `B` used by the "Expected" lines below, and the value of `STUB_KEEPS_NOTE` used by Task 7.

- [ ] **Step 1: Cut the branch and record the baseline**

Run:
```bash
git switch main
git log --oneline -1
git switch -c chatvmd-r1-05-m1-execution-safety
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -3
```
Expected: the last line reads `B passed` (plus possibly `S skipped`) with **0 failed** and no `xfailed` for `test_unreachable_host_raises_with_hint` (plan 04 removed the mark). Write `B` down; every later "Expected" line is relative to it.

- [ ] **Step 2: Write the interface check**

Create `tests/test_zz_preflight_05.py` (it runs under the hermetic conftest, so HOME, keyring and the first-run probe are isolated):

```python
"""Plan 05 pre-flight: the interfaces plans 01-04 must have produced. Not committed."""
from __future__ import annotations

import inspect
import threading
from unittest import mock

from helpers.runtime_fixture import make_app, start_token_session
from helpers.tcl import requires_tcl, run_tcl  # noqa: F401
from test_py39_compat import RUNTIME_MODULES
from vmd_ai_runtime import claude_loop as cl
from vmd_ai_runtime import conversation, image_scale, prompts, provider_catalog
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunCancelled, RunContext  # noqa: F401
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.sessions import SessionState
from vmd_ai_runtime.settings_store import SettingsStore
from vmd_ai_runtime.store import ChatStore

TOKEN = "0123456789abcdef0123456789abcdef"


class _MetaBridge:
    supports_call_meta = True

    def __init__(self):
        self.kw = []

    def execute_tool(self, **kw):
        self.kw.append(kw)
        return {"ok": False, "output": "", "error": "Not run", "executed": "no",
                "blocked": [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]}


def test_plan05_preflight(tmp_path):
    for fn in (cl._stream_anthropic_direct, cl._stream_openrouter, cl._stream_ollama):
        assert "tool_mode" in inspect.signature(fn).parameters, fn.__name__
    for name in ("_emit", "_on_meta", "_compact_for_call", "_call_turn", "_run_tool_block",
                 "_finish_text_turn", "_vision_enabled"):
        assert hasattr(ClaudeToolLoop, name), name
    assert callable(cl._mint_call_key) and callable(cl._tool_finished_meta)
    assert "search_docs" in cl._RUNTIME_TOOLS
    assert "ctx" in inspect.signature(ClaudeToolLoop.run).parameters
    opts = LoopOptions(loop_guard=True)
    assert opts.loop_guard is True and opts.result_format == "legacy"
    prod = LoopOptions.product({"provider": "ollama", "base_url": "http://127.0.0.1:11435", "model": "m"})
    assert prod.result_format == "structured" and prod.loop_guard is True
    assert "base_url" in prod.to_dict()
    assert {"authenticated", "vmd_env", "event_protocol"} <= set(SessionState.__dataclass_fields__)
    assert hasattr(ChatStore, "chat_dir")
    params = set(inspect.signature(conversation.Appender.append_late_result).parameters)
    assert {"call_key", "ok", "executed", "output", "error"} <= params
    for name in ("png_size", "make_thumbnail", "to_jpeg"):
        assert hasattr(image_scale, name), name
    assert hasattr(provider_catalog, "cached_tag_digest") and hasattr(provider_catalog, "clear_caches")
    assert callable(prompts.chatvmd_system_prompt)
    assert isinstance(RUNTIME_MODULES, list)

    # make_app builds no SettingsStore by itself (plan 03: only main.py
    # passes one), so the tests that need settings pass their own.
    app = make_app(tmp_path, launch_token=TOKEN, settings_store=SettingsStore())
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    assert sess["session_id"] and sess["session_token"]
    assert app.sessions.get(sess["session_id"]).authenticated is True
    assert app.settings_store.load()["tool_exec_timeout_s"] == 900
    assert make_app(tmp_path / "bare").settings_store is None

    # Behaviour: call_key reaches supports_call_meta bridges, and tool.finished
    # carries executed/blocked straight from the bridge result.
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command", "input": {"command": "exec ls"}}]),
        ("done", []),
    ])
    events = []
    bridge = _MetaBridge()
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://x", model="m", options=LoopOptions())
    with mock.patch.object(ClaudeToolLoop, "_call", new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="p", system_prompt="s", tool_bridge=bridge, session_id="s",
                 session_queue=EventQueue(), cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                                on_event=events.append))
    assert "call_key" in bridge.kw[0] and bridge.kw[0]["request_id"] == "req_000000000001"
    finished = [e for e in events if (e.get("metadata") or {}).get("kind") == "tool.finished"]
    assert finished and finished[0]["metadata"]["executed"] == "no"
    assert finished[0]["metadata"]["blocked"][0]["id"] == "cmd_exec"

    note = ("[output truncated: 20000 lines, 391 KB. Full text: /c/outputs/k.txt. Don't print it "
            "again: compute what you need (measure, a narrower selection), or read a slice of that "
            "file with Tcl.]")
    stub = conversation.stub_tool_result_text("h" * 3000 + "\n" + note + "\n" + "t" * 2500)
    print("STUB_KEEPS_NOTE", "Full text: /c/outputs/k.txt" in stub.rstrip().splitlines()[-1])
```

- [ ] **Step 3: Run it and print the edit anchors**

Run:
```bash
env -u VMD_AI_PROVIDER python -m pytest tests/test_zz_preflight_05.py -q -s 2>&1 | tail -4
grep -n "_mint_call_key()\|tool_bridge.execute_tool(\|_build_tool_result_block(\|end_status = \|self._recorder_end_task(\|for turn in range(\|def _on_meta\|def _emit\|self._ctx = \|text, tool_blocks = self._call_turn(\|result = self._run_tool_block(\|def _run_tool_block\|def _finish_text_turn\|self._out(_canonical_message(messages\[-1\], result_keys))\|req = urllib.request.Request(\|rescue_mode != \"off\"" runtime/vmd_ai_runtime/claude_loop.py
grep -n "self.tool_bridge = VmdToolBridge\|if method == \"session.stop\"\|if method == \"tool.command_result\"\|def _build_recorder_for_session\|loop.recorder = self._build_recorder_for_session(state" runtime/vmd_ai_runtime/app.py
grep -rn "VmdToolBridge, \"execute_tool\"" tests/
```
Expected: `STUB_KEEPS_NOTE True` (or `False`; Task 7 Step 5 handles both), then `1 passed`. Every grep pattern matches at least one line: `run()` calls `self._call_turn(...)` (plan 02, wrapped by plan 03's compaction lines) and `self._run_tool_block(...)` per tool, `_stream_ollama`'s rescue condition contains `rescue_mode != "off"` (plan 02), and `_run_claude_loop_response` sets `loop.recorder = self._build_recorder_for_session(state)` (plan 03). Tasks 9 and 10 edit exactly these lines. The last grep lists every test that patches a stub onto `VmdToolBridge.execute_tool`; note each stub whose signature lacks `**kw` (Task 1 Step 7 fixes them).

If any assertion fails, stop: the named interface from plans 01–04 is missing or differs, and it must be fixed there before this plan starts.

- [ ] **Step 4: Delete the check (it is never committed)**

Run: `rm tests/test_zz_preflight_05.py && git status --short`
Expected: no output.

---

### Task 1: P05-T01 — Call registry, supports_call_meta, tool.ack with state (C2), deadlines

**Files:**
- Create: `tests/helpers/bridge_harness.py`
- Create: `tests/test_tool_bridge_ack.py`
- Modify: `runtime/vmd_ai_runtime/tool_bridge.py:1-190` (whole file replaced)
- Modify: `runtime/vmd_ai_runtime/app.py:13-15` (imports), `:34` (bridge import), `:56` (`self.tool_bridge = VmdToolBridge()`), `:461-463` (new `tool.ack` branch before `if method == "tool.command_result":`), new helper methods after `_build_recorder_for_session`
- Modify: `runtime/vmd_ai_runtime/protocol.py:147` (new `tool.ack` validator before the `tool.command_result` block)
- Modify: `tests/test_recorder_integration.py:70-72` (`_stub_bridge_execute` gains `**kw`)

**Interfaces:**
- Consumes: call_key/request_id passing (P02-T08); SessionState.authenticated (P02-T02); `helpers.runtime_fixture.make_app(tmp_path, **kw)`, `start_token_session(app, token, *, event_protocol=1, cwd=None, vmd_env=None) -> Dict` (P02-T02); `ChatStore.chat_dir(chat_id: str) -> Path` (P03-T03); `SettingsStore.load()`, `.patch(patch)` (P03-T05).
- Produces:
  - `VmdToolBridge.supports_call_meta = True`
  - `VmdToolBridge(pickup_timeout_s: float = 45.0, exec_timeout_s: float = 900.0, cancel_grace_s: float = 30.0, session_lookup: Optional[Callable[[str], Optional[BridgeSession]]] = None)`
  - `@dataclass BridgeSession(chat_dir: Optional[Path], cwd: str, authenticated: bool, snapshot_dir: Path)` — plus two optional fields `exec_timeout_s: Optional[float] = None`, `cancel_grace_s: Optional[float] = None` (per-call settings; see Deviations)
  - `execute_tool(..., timeout=45, call_key: Optional[str] = None, request_id: Optional[str] = None)`
  - `VmdToolBridge.ack(session_id: str, call_key: str, state: str = 'running') -> Dict[str, Any]` (`{proceed, reason?}`; raises `ValueError` for an unknown state)
  - `VmdToolBridge.get_call_session(call_key: str) -> Optional[str]`
  - RPC `tool.ack {call_key, state?} -> {proceed, reason?}`
  - `tool_start` metadata for token sessions adds `{call_key, request_id, approval:'auto', snapshot_path}` (`snapshot_path` is `<snapshot_dir>/vmdai_snap_<call_key>.tga` for `capture_vmd_snapshot`, else `""`)
  - `RuntimeApp._bridge_session(session_id: str) -> Optional[BridgeSession]`, `RuntimeApp._snapshot_dir_for(session_id: str) -> Path`, `RuntimeApp._tool_timeouts() -> Tuple[Optional[float], Optional[float]]`
  - `tests/helpers/bridge_harness.py`: `SESSION_ID`, `CHAT_ID`, `make_session(tmp_path, *, authenticated=True, with_chat=True) -> BridgeSession`, `make_bridge(session, **kw) -> VmdToolBridge`, `write_tga(path, width=64, height=48) -> Path`, `class BridgeCall(bridge, *, tool_name='run_vmd_command', tool_input=None, call_key='k00000000001', request_id='req_000000000001', tool_call_id='tc_1', session_id=SESSION_ID, timeout=45)` with `.tool_start(wait=2.0)`, `.join(wait=3.0)`, `.alive()`, `.elapsed`, `.queue`, `.cancel`, `.call_key`

- [ ] **Step 1: Write the test harness**

Create `tests/helpers/bridge_harness.py`:

```python
"""Drive VmdToolBridge.execute_tool on a worker thread (plan 05 tests)."""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.tool_bridge import BridgeSession, VmdToolBridge

SESSION_ID = "sess_0123456789ab"
CHAT_ID = "chat_0123456789ab"


def make_session(tmp_path: Path, *, authenticated: bool = True, with_chat: bool = True) -> BridgeSession:
    """A BridgeSession rooted in ``tmp_path`` (chat dir, cwd and snapshot dir)."""
    chat_dir = tmp_path / "chats" / CHAT_ID
    if with_chat:
        chat_dir.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    snap = tmp_path / "snap"
    snap.mkdir(exist_ok=True)
    return BridgeSession(
        chat_dir=chat_dir if with_chat else None,
        cwd=str(work),
        authenticated=authenticated,
        snapshot_dir=snap,
    )


def make_bridge(session: Optional[BridgeSession], **kw: Any) -> VmdToolBridge:
    """A VmdToolBridge whose session_lookup knows only SESSION_ID."""
    return VmdToolBridge(
        session_lookup=lambda sid: session if sid == SESSION_ID else None, **kw
    )


def write_tga(path: Path, width: int = 64, height: int = 48) -> Path:
    """Write an uncompressed 24-bit TGA (what VMD's renderers produce)."""
    header = bytearray(18)
    header[2] = 2
    struct.pack_into("<H", header, 12, width)
    struct.pack_into("<H", header, 14, height)
    header[16] = 24
    pixels = bytes([30, 60, 90]) * (width * height)
    path.write_bytes(bytes(header) + pixels)
    return path


class BridgeCall:
    """One execute_tool call running on a daemon thread."""

    def __init__(
        self,
        bridge: VmdToolBridge,
        *,
        tool_name: str = "run_vmd_command",
        tool_input: Optional[Dict[str, Any]] = None,
        call_key: Optional[str] = "k00000000001",
        request_id: Optional[str] = "req_000000000001",
        tool_call_id: str = "tc_1",
        session_id: str = SESSION_ID,
        timeout: float = 45,
    ):
        self.bridge = bridge
        self.queue = EventQueue()
        self.cancel = threading.Event()
        self.call_key = call_key
        self.result: Optional[Dict[str, Any]] = None
        self.returned_at: Optional[float] = None
        self.started_at = time.monotonic()
        kwargs = dict(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=dict(tool_input if tool_input is not None else {"command": "mol list"}),
            session_queue=self.queue,
            cancel_event=self.cancel,
            timeout=timeout,
            call_key=call_key,
            request_id=request_id,
        )

        def _run() -> None:
            self.result = bridge.execute_tool(**kwargs)
            self.returned_at = time.monotonic()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def tool_start(self, wait: float = 2.0) -> Dict[str, Any]:
        """The pushed tool_start event (waits for it)."""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            events = [e for e in self.queue.poll(0, 50)["events"] if e["role"] == "tool_start"]
            if events:
                return events[0]
            time.sleep(0.01)
        raise AssertionError("no tool_start event was pushed")

    def join(self, wait: float = 3.0) -> Dict[str, Any]:
        self.thread.join(timeout=wait)
        assert not self.thread.is_alive(), "execute_tool did not return"
        assert self.result is not None
        return self.result

    def alive(self) -> bool:
        return self.thread.is_alive()

    @property
    def elapsed(self) -> float:
        end = self.returned_at if self.returned_at is not None else time.monotonic()
        return end - self.started_at
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_tool_bridge_ack.py`:

```python
"""C2 / spec 2d: tool.ack with state, pickup and exec deadlines (VmdToolBridge)."""
from __future__ import annotations

import os
import time

import pytest

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime.settings_store import SettingsStore
from vmd_ai_runtime.tool_bridge import VmdToolBridge

TOKEN = "0123456789abcdef0123456789abcdef"


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def test_supports_call_meta_is_a_class_attribute():
    assert VmdToolBridge.__dict__["supports_call_meta"] is True


def test_token_tool_start_metadata(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, call_key="k0000000000a", request_id="req_aaaaaaaaaaaa")
    meta = call.tool_start()["metadata"]
    assert meta["call_key"] == "k0000000000a"
    assert meta["request_id"] == "req_aaaaaaaaaaaa"
    assert meta["approval"] == "auto"
    assert meta["snapshot_path"] == ""
    assert meta["tool_call_id"] == "tc_1" and meta["session_id"] == SESSION_ID
    call.cancel.set()
    call.join()


def test_tokenless_tool_start_metadata_unchanged(tmp_path):
    bridge = make_bridge(make_session(tmp_path, authenticated=False))
    call = BridgeCall(bridge, timeout=2)
    meta = call.tool_start()["metadata"]
    assert set(meta) == {"tool_call_id", "tool_name", "tool_input", "session_id"}
    assert bridge.resolve("tc_1", {"ok": True, "output": "0", "error": ""})
    assert call.join()["output"] == "0"


def test_pickup_timeout_message(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2)
    call = BridgeCall(bridge)
    result = call.join()
    assert result["ok"] is False
    assert result["executed"] == "no"
    assert result["error"] == "VMD did not pick up the command (no reply within 0.2 s)."
    assert 0.2 <= call.elapsed < 1.5
    assert bridge.ack(SESSION_ID, call.call_key, "running") == {"proceed": False, "reason": "cancelled"}


def test_awaiting_user_ack_no_pickup_timeout(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2, exec_timeout_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key, "awaiting_user") == {"proceed": True}
    time.sleep(0.6)
    assert call.alive(), "an awaiting_user ack must stop the pickup deadline"
    call.cancel.set()
    assert call.join()["executed"] == "no"


def test_stop_during_awaiting_user_executed_no_and_later_ack_refused(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key, "awaiting_user")["proceed"] is True
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 < 0.5, "no grace wait: nothing is running yet"
    assert (result["ok"], result["error"], result["executed"]) == (False, "cancelled", "no")
    assert bridge.ack(SESSION_ID, call.call_key, "running")["proceed"] is False


def test_running_ack_starts_exec_deadline(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.2, exec_timeout_s=0.5)
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack(SESSION_ID, call.call_key) == {"proceed": True}
    result = call.join()
    assert result["executed"] == "unknown"
    assert result["error"] == "VMD did not finish the command within 0.5 s; outcome unknown."
    assert call.elapsed >= 0.5


def test_ack_unknown_call_and_foreign_session(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    assert bridge.ack(SESSION_ID, "nope00000000") == {"proceed": False, "reason": "unknown call"}
    call = BridgeCall(bridge)
    call.tool_start()
    assert bridge.ack("sess_other000000", call.call_key)["proceed"] is False
    with pytest.raises(ValueError):
        bridge.ack(SESSION_ID, call.call_key, "bogus")
    call.cancel.set()
    call.join()


def test_token_call_resolvable_by_tool_call_id(tmp_path):
    # Compat: a client that posts by tool_call_id still resolves a token call.
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_call_id="tc_compat")
    call.tool_start()
    assert bridge.get_pending_session("tc_compat") == SESSION_ID
    assert bridge.resolve("tc_compat", {"ok": True, "output": "3", "error": ""}) is True
    result = call.join()
    assert (result["ok"], result["output"], result["executed"]) == (True, "3", "yes")
    assert bridge.get_pending_session("tc_compat") is None
    assert bridge.get_call_session(call.call_key) == SESSION_ID


def test_unknown_state_invalid_params(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN)
    resp = _rpc(app, "tool.ack", {"call_key": "k00000000001", "state": "bogus"}, sess)
    assert resp["error"]["code"] == "INVALID_PARAMS"
    assert resp["error"]["data"]["allowed"] == ["running", "awaiting_user"]


def test_rpc_tool_ack_round_trip(tmp_path, monkeypatch):
    app = make_app(tmp_path, launch_token=TOKEN)
    monkeypatch.setattr(app, "_tool_timeouts", lambda: (None, 0.1))
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"])
    meta = call.tool_start()["metadata"]
    assert meta["call_key"] == call.call_key, "token sessions take the call_key path"
    assert _rpc(app, "tool.ack", {"call_key": call.call_key, "state": "awaiting_user"}, sess)["result"] == {"proceed": True}
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, sess)["result"] == {"proceed": True}
    other = start_token_session(app, TOKEN)
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, other)["error"]["code"] == "AUTH_FAILED"
    assert _rpc(app, "tool.ack", {"call_key": "zz0000000000"}, sess)["result"] == {
        "proceed": False, "reason": "unknown call"}
    call.cancel.set()
    assert call.join()["executed"] == "unknown"


def test_bridge_session_for_token_session(tmp_path):
    # make_app builds no SettingsStore (plan 03: only main.py passes one).
    app = make_app(tmp_path, launch_token=TOKEN, settings_store=SettingsStore())
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    app.settings_store.patch({"tool_exec_timeout_s": 120, "cancel_grace_s": 5})
    bs = app._bridge_session(sess["session_id"])
    assert bs.authenticated is True
    assert bs.cwd == os.path.realpath(str(tmp_path))
    assert bs.chat_dir is None, "token sessions create their chat on the first chat.send"
    assert bs.snapshot_dir.is_dir()
    assert bs.snapshot_dir.stat().st_mode & 0o777 == 0o700
    assert (bs.exec_timeout_s, bs.cancel_grace_s) == (120.0, 5.0)
    app.settings_store.patch({"cancel_grace_s": 0})
    assert app._bridge_session(sess["session_id"]).cancel_grace_s == 0.0, "0 means: do not wait"
    assert app._bridge_session("sess_unknown00000") is None
    bare = make_app(tmp_path / "bare", launch_token=TOKEN)
    bare_sess = start_token_session(bare, TOKEN)
    bs_bare = bare._bridge_session(bare_sess["session_id"])
    assert (bs_bare.exec_timeout_s, bs_bare.cancel_grace_s) == (None, None), "no store: bridge defaults"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_bridge_ack.py -q`
Expected: collection error `ImportError while importing test module ... cannot import name 'BridgeSession' from 'vmd_ai_runtime.tool_bridge'`.

- [ ] **Step 4: Replace `runtime/vmd_ai_runtime/tool_bridge.py`**

Write the whole file:

```python
"""
tool_bridge.py - Manages async VMD tool execution between Python and Tcl.

Architecture:
  1. Claude loop calls execute_tool() with a tool name + args
  2. execute_tool() pushes a 'tool_start' event onto the session's EventQueue
  3. The Tcl bridge polls that queue, sees the event, runs the VMD command
  4. The Tcl bridge POSTs tool.command_result back to the Python RPC server
  5. The RPC handler resolves the pending call, which unblocks execute_tool()
  6. execute_tool() returns the result dict to the Claude loop

Two paths share this class:
  * Token-authenticated sessions (the M1 plugin) use the call registry keyed
    by ``call_key``: ``tool.ack {call_key, state}`` answers ``proceed``
    atomically against cancellation; a pickup deadline (45 s) runs until the
    first ack; a ``running`` ack starts the exec deadline (900 s); Stop waits
    ``cancel_grace_s`` for a running command (spec 2d, C2).
  * Tokenless sessions (old plugins) keep today's protocol: ``tool_call_id``,
    one 45 s timeout, ``resolve()``.
"""
from __future__ import annotations

import base64
import collections
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Optional

from .image_utils import read_image_as_png_bytes

logger = logging.getLogger("vmdai.tool_bridge")

# How long (seconds) to wait for Tcl to execute a tool and post the result.
TOOL_TIMEOUT_SEC = 45

ACK_STATES = ("running", "awaiting_user")
_POLL_S = 0.05
_KEEP_FINISHED = 512


@dataclass
class BridgeSession:
    """What the bridge needs to know about the session that owns a call."""
    chat_dir: Optional[Path]
    cwd: str
    authenticated: bool
    snapshot_dir: Path
    exec_timeout_s: Optional[float] = None
    cancel_grace_s: Optional[float] = None


@dataclass
class _PendingCall:
    tool_call_id: str
    tool_name: str
    session_id: str = ""
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None
    # --- token-session fields (unused on the legacy path) ---
    call_key: str = ""
    request_id: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    chat_dir: Optional[Path] = None
    cwd: str = ""
    snapshot_path: str = ""
    exec_timeout_s: float = 900.0
    started: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "pending"              # pending | awaiting_user | running
    exec_deadline: Optional[float] = None
    cancelled: bool = False
    finished: bool = False              # execute_tool has returned
    raw: Optional[Dict[str, Any]] = None
    late: bool = False


class VmdToolBridge:
    """
    Thread-safe registry of in-flight VMD tool calls.

    One instance lives on RuntimeApp and is shared across all sessions.
    """

    # The loop passes call_key= and request_id= only to bridges whose CLASS
    # declares this (spec 2a); wrappers that delegate via __getattr__ never
    # opt in by accident.
    supports_call_meta = True

    def __init__(
        self,
        pickup_timeout_s: float = 45.0,
        exec_timeout_s: float = 900.0,
        cancel_grace_s: float = 30.0,
        session_lookup: Optional[Callable[[str], Optional[BridgeSession]]] = None,
    ):
        self._lock = threading.Lock()
        self._pending: Dict[str, _PendingCall] = {}
        self._calls: Dict[str, _PendingCall] = {}
        self._finished_order: Deque[str] = collections.deque()
        self.pickup_timeout_s = float(pickup_timeout_s)
        self.exec_timeout_s = float(exec_timeout_s)
        self.cancel_grace_s = float(cancel_grace_s)
        self.session_lookup = session_lookup

    def get_pending_session(self, tool_call_id: str) -> Optional[str]:
        """Return the session_id that owns a pending call, or None if unknown.

        Used by the RPC handler to verify that a tool.command_result POST
        belongs to the session that originated the tool call.
        """
        tcid = str(tool_call_id or "")
        with self._lock:
            pending = self._pending.get(tcid)
        if pending is None:
            pending = self._token_call_by_tool_call_id(tcid)
        return pending.session_id if pending else None

    def get_call_session(self, call_key: str) -> Optional[str]:
        """Return the session_id that owns ``call_key`` (pending or finished)."""
        with self._lock:
            pending = self._calls.get(str(call_key or ""))
        return pending.session_id if pending else None

    # ------------------------------------------------------------------
    # Called by the Claude loop (background thread)
    # ------------------------------------------------------------------

    def execute_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        session_queue,          # EventQueue from sessions.py
        cancel_event: threading.Event,
        timeout: float = TOOL_TIMEOUT_SEC,
        call_key: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one VMD tool call through the plugin and return its result dict."""
        sess = self._lookup(session_id)
        if call_key and sess is not None and sess.authenticated:
            return self._execute_token(
                sess,
                session_id=str(session_id or ""),
                tool_call_id=str(tool_call_id or ""),
                tool_name=tool_name,
                tool_input=dict(tool_input or {}),
                session_queue=session_queue,
                cancel_event=cancel_event,
                call_key=str(call_key),
                request_id=str(request_id or ""),
            )
        return self._execute_legacy(
            sess,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            session_queue=session_queue,
            cancel_event=cancel_event,
            timeout=timeout,
            call_key=call_key,
        )

    def _lookup(self, session_id: str) -> Optional[BridgeSession]:
        if self.session_lookup is None:
            return None
        try:
            return self.session_lookup(str(session_id or ""))
        except Exception:
            logger.warning("session_lookup failed for %s", session_id, exc_info=True)
            return None

    # ---- legacy (tokenless) path ----------------------------------------

    def _execute_legacy(self, sess: Optional[BridgeSession], *, session_id, tool_call_id,
                        tool_name, tool_input, session_queue, cancel_event, timeout, call_key):
        pending = _PendingCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            session_id=str(session_id or ""),
        )
        with self._lock:
            self._pending[tool_call_id] = pending

        try:
            session_queue.push(
                "tool_start",
                "message",
                _format_tool_label(tool_name, tool_input),
                {
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "session_id": session_id,
                },
            )
            logger.debug("tool_start pushed tool=%s id=%s", tool_name, tool_call_id)

            deadline = timeout
            poll_interval = 0.1
            while deadline > 0:
                if cancel_event.is_set():
                    return {"ok": False, "output": "", "error": "cancelled"}
                if pending.done.wait(timeout=poll_interval):
                    break
                deadline -= poll_interval
            else:
                logger.warning("tool timed out tool=%s id=%s", tool_name, tool_call_id)
                return {
                    "ok": False,
                    "output": "",
                    "error": f"VMD tool timed out after {TOOL_TIMEOUT_SEC}s",
                }

            result = pending.result or {}

            # For snapshot tool: read the rendered file and base64-encode it.
            if tool_name == "capture_vmd_snapshot" and result.get("ok"):
                snap_file = str(result.get("snapshot_file") or "")
                if snap_file and os.path.isfile(snap_file):
                    png_bytes = read_image_as_png_bytes(snap_file)
                    if png_bytes:
                        result["image_b64"] = base64.b64encode(png_bytes).decode()
                        result["image_mime"] = "image/png"
                    try:
                        os.unlink(snap_file)
                    except Exception:
                        pass

            return result

        finally:
            with self._lock:
                self._pending.pop(tool_call_id, None)

    # ---- token path ------------------------------------------------------

    def _execute_token(self, sess: BridgeSession, *, session_id, tool_call_id, tool_name,
                       tool_input, session_queue, cancel_event, call_key, request_id):
        exec_s = sess.exec_timeout_s if sess.exec_timeout_s is not None else self.exec_timeout_s
        grace_s = sess.cancel_grace_s if sess.cancel_grace_s is not None else self.cancel_grace_s
        snapshot_path = ""
        if tool_name == "capture_vmd_snapshot":
            snapshot_path = str(Path(sess.snapshot_dir) / ("vmdai_snap_%s.tga" % call_key))
        pending = _PendingCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            session_id=session_id,
            call_key=call_key,
            request_id=request_id,
            tool_input=tool_input,
            chat_dir=sess.chat_dir,
            cwd=sess.cwd,
            snapshot_path=snapshot_path,
            exec_timeout_s=float(exec_s),
        )
        with self._lock:
            self._calls[call_key] = pending

        session_queue.push(
            "tool_start",
            "message",
            _format_tool_label(tool_name, tool_input),
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "session_id": session_id,
                "call_key": call_key,
                "request_id": request_id,
                "approval": "auto",
                "snapshot_path": snapshot_path,
            },
        )
        pickup_deadline = time.monotonic() + self.pickup_timeout_s

        while not pending.done.is_set():
            if cancel_event.is_set():
                return self._cancel(pending, grace_s)
            now = time.monotonic()
            with pending.lock:
                state = pending.state
                exec_deadline = pending.exec_deadline
            if state == "pending" and now >= pickup_deadline:
                out = self._give_up(
                    pending, "no",
                    "VMD did not pick up the command (no reply within %g s)." % self.pickup_timeout_s,
                )
                if out is not None:
                    return out
                continue
            if state == "running" and exec_deadline is not None and now >= exec_deadline:
                out = self._give_up(
                    pending, "unknown",
                    "VMD did not finish the command within %g s; outcome unknown." % exec_s,
                )
                if out is not None:
                    return out
                continue
            pending.done.wait(timeout=_POLL_S)
        return self._take_result(pending)

    def _cancel(self, pending: _PendingCall, grace_s: float) -> Dict[str, Any]:
        """Stop (spec 2d): not acked or awaiting_user -> 'no' at once; running -> grace."""
        with pending.lock:
            if not pending.done.is_set() and pending.state != "running":
                pending.cancelled = True
                return self._finish_without_result(pending, "no", "cancelled")
        if pending.done.wait(timeout=max(0.0, grace_s)):
            return self._take_result(pending)
        out = self._give_up(pending, "unknown", "stopped while running; outcome unknown")
        return out if out is not None else self._take_result(pending)

    def _give_up(self, pending: _PendingCall, executed: str, error: str) -> Optional[Dict[str, Any]]:
        """Stop waiting. Returns None if a result slipped in first."""
        with pending.lock:
            if pending.done.is_set():
                return None
            pending.cancelled = True
            return self._finish_without_result(pending, executed, error)

    def _finish_without_result(self, pending: _PendingCall, executed: str,
                               error: str) -> Dict[str, Any]:
        """Caller holds ``pending.lock``."""
        pending.finished = True
        self._retire(pending.call_key)
        result = _empty_result()
        result.update({
            "ok": False,
            "executed": executed,
            "error": error,
            "duration_ms": int((time.monotonic() - pending.started) * 1000),
        })
        return result

    def _take_result(self, pending: _PendingCall) -> Dict[str, Any]:
        with pending.lock:
            pending.finished = True
        self._retire(pending.call_key)
        return self._finalize(pending)

    def _retire(self, call_key: str) -> None:
        """Keep finished calls (dedupe, late results), bounded."""
        with self._lock:
            self._finished_order.append(call_key)
            while len(self._finished_order) > _KEEP_FINISHED:
                self._calls.pop(self._finished_order.popleft(), None)

    def _finalize(self, pending: _PendingCall) -> Dict[str, Any]:
        """Turn the posted result into the product result dict."""
        raw = dict(pending.raw or {})
        executed = "no" if str(raw.get("executed") or "yes") == "no" else "yes"
        ok = bool(raw.get("ok", False)) and executed == "yes"
        error = str(raw.get("error") or "")
        if executed == "no" and not error:
            error = "not executed"
        result = _empty_result()
        result.update({
            "ok": ok,
            "output": str(raw.get("output") or ""),
            "error": error,
            "executed": executed,
            "duration_ms": int((time.monotonic() - pending.started) * 1000),
        })
        return result

    def _token_call_by_tool_call_id(self, tool_call_id: str) -> Optional[_PendingCall]:
        """Compat: an unresolved token call that a client names by tool_call_id."""
        with self._lock:
            for pending in reversed(list(self._calls.values())):
                if (pending.tool_call_id == tool_call_id and not pending.finished
                        and pending.raw is None):
                    return pending
        return None

    # ------------------------------------------------------------------
    # Called by the RPC handler
    # ------------------------------------------------------------------

    def ack(self, session_id: str, call_key: str, state: str = "running") -> Dict[str, Any]:
        """``tool.ack``: answer ``proceed`` atomically against cancellation (C2).

        Any ack stops the pickup deadline. ``running`` starts the exec
        deadline; ``awaiting_user`` starts none.
        """
        if state not in ACK_STATES:
            raise ValueError("state must be one of %s" % (ACK_STATES,))
        with self._lock:
            pending = self._calls.get(str(call_key or ""))
        if pending is None or pending.session_id != str(session_id or ""):
            return {"proceed": False, "reason": "unknown call"}
        with pending.lock:
            if pending.cancelled or pending.finished:
                return {"proceed": False, "reason": "cancelled"}
            if pending.done.is_set():
                return {"proceed": False, "reason": "already resolved"}
            if state == "running":
                pending.state = "running"
                pending.exec_deadline = time.monotonic() + pending.exec_timeout_s
            else:
                pending.state = "awaiting_user"
        return {"proceed": True}

    def resolve(self, tool_call_id: str, result: Dict[str, Any]) -> bool:
        """
        Called when the Tcl bridge POSTs tool.command_result by tool_call_id.
        Unblocks the waiting execute_tool() call.
        Returns True if the call was found, False if it was already gone/timed-out.
        """
        with self._lock:
            pending = self._pending.get(tool_call_id)
        if pending is None:
            token_call = self._token_call_by_tool_call_id(str(tool_call_id or ""))
            if token_call is not None:
                with token_call.lock:
                    if token_call.raw is None and not token_call.finished:
                        token_call.raw = dict(result)
                        token_call.done.set()
                        return True
            logger.warning("resolve: unknown tool_call_id=%s (timed out?)", tool_call_id)
            return False
        pending.result = result
        pending.done.set()
        logger.debug("tool resolved id=%s ok=%s", tool_call_id, result.get("ok"))
        return True


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _empty_result() -> Dict[str, Any]:
    """The product result dict with every key present (plan-specific constraint)."""
    return {
        "ok": False, "output": "", "error": "", "executed": "yes",
        "truncated": False, "duration_ms": 0, "statements": None, "blocked": None,
        "output_path": None, "output_bytes": 0, "image": None, "saved_path": None,
        "applied_text": "",
    }


def _format_tool_label(tool_name: str, tool_input: Dict[str, Any]) -> str:
    """Human-readable summary for the tool_start transcript event."""
    if tool_name == "run_vmd_command":
        cmd = str(tool_input.get("command") or "").strip()
        preview = cmd[:80] + "…" if len(cmd) > 80 else cmd
        return f"[VMD] {preview}"
    if tool_name == "capture_vmd_snapshot":
        purpose = str(tool_input.get("purpose") or "inspect viewport").strip()
        return f"[Snapshot] {purpose}"
    return f"[{tool_name}]"
```

- [ ] **Step 5: Add the `tool.ack` validator to `runtime/vmd_ai_runtime/protocol.py`**

Insert immediately before the line `    if method == "tool.command_result":`:

```python
    if method == "tool.ack":
        # Posted by the M1 executor before it runs a tool_start (C2).
        state = _as_str(p.get("state") or "running", "state", required=False)
        if state not in ("running", "awaiting_user"):
            raise RpcError(
                "INVALID_PARAMS",
                "state must be 'running' or 'awaiting_user'",
                {"allowed": ["running", "awaiting_user"]},
            )
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "call_key": _as_str(p.get("call_key"), "call_key"),
            "state": state,
        }

```

- [ ] **Step 6: Wire the bridge into `runtime/vmd_ai_runtime/app.py`**

(a) In the imports: make sure `import tempfile` is present next to `import os` and `import threading`, that the typing import includes `Optional` and `Tuple` (for example `from typing import Any, Dict, Optional, Tuple`), and replace `from .tool_bridge import VmdToolBridge` with:

```python
from .tool_bridge import BridgeSession, VmdToolBridge
```

(b) In `RuntimeApp.__init__`, replace the line `self.tool_bridge = VmdToolBridge()` with:

```python
        self._snapshot_lock = threading.Lock()
        self._snapshot_dirs: Dict[str, str] = {}
        self.tool_bridge = VmdToolBridge(session_lookup=self._bridge_session)
```

(c) In `_dispatch`, insert immediately before `        if method == "tool.command_result":`:

```python
        if method == "tool.ack":
            # C2: the executor acks before running a tool_start. Any ack stops
            # the pickup deadline; the answer is atomic against Stop.
            state = self._get_session(params["session_id"], session_token)
            owner = self.tool_bridge.get_call_session(params["call_key"])
            if owner is None:
                return {"proceed": False, "reason": "unknown call"}
            if owner != state.session_id:
                raise RpcError(
                    "AUTH_FAILED",
                    "call_key does not belong to this session",
                    {"call_key": params["call_key"]},
                )
            return self.tool_bridge.ack(state.session_id, params["call_key"], params["state"])

```

(d) Add these methods to `RuntimeApp`, directly after `_build_recorder_for_session`:

```python
    # ------------------------------------------------------------------
    # Product bridge support (plan 05)
    # ------------------------------------------------------------------

    def _bridge_session(self, session_id: str) -> Optional[BridgeSession]:
        """What VmdToolBridge needs to know about ``session_id`` (None if unknown)."""
        state = self.sessions.get(session_id)
        if state is None:
            return None
        chat_dir = None
        if state.chat_id:
            try:
                chat_dir = Path(self.store.chat_dir(state.chat_id))
            except Exception:
                chat_dir = None
        exec_s, grace_s = self._tool_timeouts()
        return BridgeSession(
            chat_dir=chat_dir,
            cwd=str(state.cwd or ""),
            authenticated=bool(getattr(state, "authenticated", False)),
            snapshot_dir=self._snapshot_dir_for(state.session_id),
            exec_timeout_s=exec_s,
            cancel_grace_s=grace_s,
        )

    def _snapshot_dir_for(self, session_id: str) -> Path:
        """Per-session 0700 temp dir where the plugin renders snapshots (spec 2d)."""
        with self._snapshot_lock:
            path = self._snapshot_dirs.get(session_id)
            if path is None or not os.path.isdir(path):
                path = tempfile.mkdtemp(prefix="vmdai_snap_")
                self._snapshot_dirs[session_id] = path
        return Path(path)

    def _tool_timeouts(self) -> Tuple[Optional[float], Optional[float]]:
        """(tool_exec_timeout_s, cancel_grace_s) from settings.json; None = bridge default.

        Read on every tool call, so a changed setting applies to the next
        call. settings_store validates exec >= 1 and grace >= 0 (0 = do not
        wait for a running command after Stop).
        """
        store = getattr(self, "settings_store", None)
        if store is None:
            return None, None
        try:
            data = store.load()
        except Exception:
            return None, None
        if not isinstance(data, dict):
            return None, None

        def _number(key: str, minimum: float) -> Optional[float]:
            try:
                value = float(data.get(key))
            except (TypeError, ValueError):
                return None
            return value if value >= minimum else None

        return _number("tool_exec_timeout_s", 1.0), _number("cancel_grace_s", 0.0)
```

- [ ] **Step 7: Let every stub patched onto `VmdToolBridge.execute_tool` accept the call metadata**

In `tests/test_recorder_integration.py` replace lines 70-72:

```python
def _stub_bridge_execute(self_bridge, *, session_id, tool_call_id,
                         tool_name, tool_input, session_queue,
                         cancel_event):
```

with:

```python
def _stub_bridge_execute(self_bridge, *, session_id, tool_call_id,
                         tool_name, tool_input, session_queue,
                         cancel_event, **kw):
```

Apply the same `, **kw` addition to any other stub that the last grep of Task 0 Step 3 listed without `**kw` (spec §2a: once `VmdToolBridge.supports_call_meta` is true, a stub patched onto it receives `call_key=` and `request_id=`).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_bridge_ack.py tests/test_tool_bridge.py tests/test_tool_command_result_auth.py tests/test_recorder_integration.py tests/test_agent_integration.py -q`
Expected: all passed (`12 passed` from the new file plus the existing ones), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+12 passed`, 0 failed.

- [ ] **Step 9: Commit**

```bash
git add runtime/vmd_ai_runtime/tool_bridge.py runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/protocol.py tests/helpers/bridge_harness.py tests/test_tool_bridge_ack.py tests/test_recorder_integration.py
git add -u tests/
git commit -m "feat(bridge): call_key registry, tool.ack with state, pickup/exec deadlines (C2)

VmdToolBridge declares supports_call_meta. Token sessions get the call_key
registry: any ack stops the 45 s pickup deadline, a running ack starts the
exec deadline, Stop before a running ack returns executed 'no' at once and
Stop after it waits cancel_grace_s. Tokenless sessions keep tool_call_id.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 2: P05-T02 — tool.command_result by call_key: executed, grace, dedupe, late

**Files:**
- Create: `tests/test_tool_bridge_results.py`
- Modify: `runtime/vmd_ai_runtime/tool_bridge.py` (the `__init__`, `_finalize` and `ack` written in Task 1; new helper `_statements_from` after `_empty_result`)
- Modify: `runtime/vmd_ai_runtime/protocol.py:1-3` (typing import), `:15-35` (new helpers after `_as_int`), `:147-159` (`tool.command_result` validator)
- Modify: `runtime/vmd_ai_runtime/app.py:463-470` (call_key branch at the top of `if method == "tool.command_result":`), `RuntimeApp.__init__` (wire `on_late_result`), new method `_on_late_result`

**Interfaces:**
- Consumes: `Appender.append_late_result` (P03-T01) as `conversation.Appender(chat_dir: Path, request_id: str).append_late_result(call_key, ok, executed, output, error)`; `conversation.read_lines(chat_dir) -> List[Dict]` (P03-T01); ack registry (P05-T01).
- Produces:
  - `VmdToolBridge.post_result(session_id: str, params: Dict[str, Any]) -> Dict[str, bool]` (`{accepted, late, duplicate}`; `accepted` is False for an unknown call_key or a call owned by another session)
  - `VmdToolBridge.on_late_result: Optional[Callable[[str, str, Dict[str, Any]], None]]`, called as `on_late_result(session_id, call_key, info)` where `info` is the full result dict (below) plus `late: True`, `request_id`, `tool_name` and `chat_dir` (str or None)
  - result dict `{ok, output, error, executed, truncated, duration_ms, statements{total, applied, failed|null}, blocked, output_path, output_bytes, image, saved_path}` (+ `applied_text`, see Global Constraints)
  - protocol `tool.command_result` params: `call_key`, `executed` (`'yes'|'no'`), `statements_total`, `statements_applied`, `failed_index`, `failed_statement`, `error_info`, `applied_text`, `duration_ms`, `truncated` (`tool_call_id` becomes optional when `call_key` is given)
  - `RuntimeApp._on_late_result(session_id: str, call_key: str, info: Dict[str, Any]) -> None` (writes the `late_result` line; P07-T03 extends it with the late `tool.finished`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_bridge_results.py`:

```python
"""spec 2d Post/Cancel, 2b Late results, C2, C3: tool.command_result by call_key."""
from __future__ import annotations

import time

import pytest

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime import conversation
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.protocol import validate_method_params
from vmd_ai_runtime.tool_bridge import BridgeSession

TOKEN = "0123456789abcdef0123456789abcdef"


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def _post(bridge, call, **fields):
    params = {"call_key": call.call_key, "ok": True, "output": "", "error": ""}
    params.update(fields)
    return bridge.post_result(SESSION_ID, params)


def test_not_acked_cancel_immediate(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=5)
    call = BridgeCall(bridge)
    call.tool_start()
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 < 0.5
    assert (result["ok"], result["executed"], result["error"]) == (False, "no", "cancelled")
    assert bridge.ack(SESSION_ID, call.call_key)["proceed"] is False


def test_running_cancel_waits_grace_then_unknown(tmp_path):
    bridge = make_bridge(make_session(tmp_path), cancel_grace_s=0.3)
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    t0 = time.monotonic()
    call.cancel.set()
    result = call.join()
    assert time.monotonic() - t0 >= 0.3
    assert result["executed"] == "unknown"
    assert result["error"] == "stopped while running; outcome unknown"


def test_stop_between_ack_and_result(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=1.0)
    late_calls = []
    bridge.on_late_result = lambda sid, key, info: late_calls.append((sid, key, info))

    # (1) The result arrives inside the grace window: a consistent "yes".
    call = BridgeCall(bridge, call_key="k0000000000b")
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    call.cancel.set()
    time.sleep(0.1)
    assert _post(bridge, call, output="done") == {"accepted": True, "late": False, "duplicate": False}
    result = call.join()
    assert (result["ok"], result["executed"], result["output"]) == (True, "yes", "done")

    # (2) The result arrives after the grace window: "unknown" now, stored as late.
    bridge.cancel_grace_s = 0.2
    call2 = BridgeCall(bridge, call_key="k0000000000c", request_id="req_bbbbbbbbbbbb")
    call2.tool_start()
    bridge.ack(SESSION_ID, call2.call_key)
    call2.cancel.set()
    assert call2.join()["executed"] == "unknown"
    reply = _post(bridge, call2, output="late output")
    assert reply == {"accepted": True, "late": True, "duplicate": False}
    assert len(late_calls) == 1
    sid, key, info = late_calls[0]
    assert (sid, key) == (SESSION_ID, "k0000000000c")
    assert info["late"] is True and info["executed"] == "yes" and info["output"] == "late output"
    assert info["request_id"] == "req_bbbbbbbbbbbb"
    assert info["tool_name"] == "run_vmd_command"
    assert info["chat_dir"] == str(session.chat_dir)
    assert _post(bridge, call2, output="late output") == {"accepted": True, "late": True, "duplicate": True}
    assert len(late_calls) == 1


def test_posted_executed_no_overrides(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    _post(bridge, call, ok=True, executed="no",
          error="Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)")
    result = call.join()
    assert (result["ok"], result["executed"]) == (False, "no")
    assert result["error"].startswith("Nothing was run")


def test_unacked_result_accepted_as_pickup(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=2.0)
    call = BridgeCall(bridge)
    call.tool_start()
    reply = _post(bridge, call, ok=False, executed="no", error="This panel cannot ask for approval")
    assert reply["accepted"] is True
    result = call.join(wait=1.0)
    assert call.elapsed < 1.0, "the refusal must stop the pickup deadline"
    assert (result["executed"], result["error"]) == ("no", "This panel cannot ask for approval")


def test_duplicate(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    assert _post(bridge, call, output="a") == {"accepted": True, "late": False, "duplicate": False}
    assert call.join()["output"] == "a"
    assert _post(bridge, call, output="a") == {"accepted": True, "late": False, "duplicate": True}
    assert bridge.post_result(SESSION_ID, {"call_key": "zzz000000000"}) == {
        "accepted": False, "late": False, "duplicate": False}
    assert bridge.post_result("sess_other000000", {"call_key": call.call_key})["accepted"] is False


def test_statements_mapping(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_input={"command": "mol new a.pdb\nmol delrep 0 top\nbogus\nputs x"})
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    _post(bridge, call, ok=False, error='invalid command name "bogus"',
          statements_total=4, statements_applied=2, failed_index=3, failed_statement="bogus",
          error_info='invalid command name "bogus"\n    while executing\n"bogus"',
          applied_text="mol new a.pdb\nmol delrep 0 top\n", duration_ms=41)
    result = call.join()
    assert result["statements"] == {
        "total": 4, "applied": 2,
        "failed": {"index": 3, "text": "bogus",
                   "error_info": 'invalid command name "bogus"\n    while executing\n"bogus"'},
    }
    assert result["applied_text"] == "mol new a.pdb\nmol delrep 0 top\n"
    assert result["duration_ms"] == 41
    ok_call = BridgeCall(bridge, call_key="k0000000000d")
    ok_call.tool_start()
    bridge.ack(SESSION_ID, ok_call.call_key)
    bridge.post_result(SESSION_ID, {"call_key": "k0000000000d", "ok": True, "output": "",
                                     "statements_total": 1, "statements_applied": 1})
    assert ok_call.join()["statements"] == {"total": 1, "applied": 1, "failed": None}


def test_late_result_stored_as_late_result_line(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    chat_dir = tmp_path / "chat_for_late"
    chat_dir.mkdir()
    snap = tmp_path / "snap"
    snap.mkdir()
    app.tool_bridge.session_lookup = lambda sid: BridgeSession(
        chat_dir=chat_dir, cwd=str(tmp_path), authenticated=True, snapshot_dir=snap,
        cancel_grace_s=0.1)
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"], request_id="req_cccccccccccc")
    call.tool_start()
    assert _rpc(app, "tool.ack", {"call_key": call.call_key}, sess)["result"]["proceed"] is True
    call.cancel.set()
    assert call.join()["executed"] == "unknown"
    resp = _rpc(app, "tool.command_result",
                {"call_key": call.call_key, "ok": True, "output": "3 atoms"}, sess)
    assert resp["result"] == {"accepted": True, "late": True, "duplicate": False}
    lines = [line for line in conversation.read_lines(chat_dir) if line.get("kind") == "late_result"]
    assert len(lines) == 1
    line = lines[0]
    assert (line["call_key"], line["request_id"], line["ok"], line["executed"], line["output"]) == (
        call.call_key, "req_cccccccccccc", True, "yes", "3 atoms")


def test_rpc_command_result_by_call_key(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    call = BridgeCall(app.tool_bridge, session_id=sess["session_id"])
    call.tool_start()
    other = start_token_session(app, TOKEN)
    params = {"call_key": call.call_key, "ok": True, "output": "x",
              "statements_total": 1, "statements_applied": 1}
    assert _rpc(app, "tool.command_result", params, other)["error"]["code"] == "AUTH_FAILED"
    unknown = _rpc(app, "tool.command_result", dict(params, call_key="zz0000000000"), sess)
    assert unknown["error"]["code"] == "TOOL_CALL_UNKNOWN"
    assert _rpc(app, "tool.command_result", params, sess)["result"] == {
        "accepted": True, "late": False, "duplicate": False}
    result = call.join()
    assert (result["ok"], result["output"], result["statements"]) == (
        True, "x", {"total": 1, "applied": 1, "failed": None})
    assert _rpc(app, "tool.command_result", params, sess)["result"]["duplicate"] is True
    events = _rpc(app, "chat.events.poll", {"after_seq": 0, "limit": 200}, sess)["result"]["events"]
    posted = [e for e in events if e["role"] == "tool_result"]
    assert len(posted) == 1 and posted[0]["metadata"]["call_key"] == call.call_key


def test_protocol_command_result_fields():
    p = validate_method_params("tool.command_result", {
        "session_id": "s", "call_key": "k1", "ok": False, "output": "  out  ",
        "executed": "no", "statements_total": 4, "statements_applied": 2, "failed_index": 3,
        "failed_statement": "x" * 300, "error_info": "l1\nl2\nl3\nl4", "applied_text": "a\n b \n",
        "duration_ms": 12, "truncated": True})
    assert p["tool_call_id"] == ""
    assert p["applied_text"] == "a\n b \n", "applied_text is an exact source prefix"
    assert len(p["failed_statement"]) == 200
    assert p["error_info"] == "l1\nl2\nl3"
    assert (p["statements_total"], p["statements_applied"], p["failed_index"], p["duration_ms"]) == (4, 2, 3, 12)
    assert p["executed"] == "no" and p["truncated"] is True
    legacy = validate_method_params("tool.command_result", {"session_id": "s", "tool_call_id": "tc", "ok": True})
    assert legacy["call_key"] == "" and legacy["executed"] == "yes" and legacy["statements_total"] is None
    with pytest.raises(RpcError) as bad_executed:
        validate_method_params("tool.command_result", {"session_id": "s", "call_key": "k", "executed": "maybe"})
    assert bad_executed.value.code == "INVALID_PARAMS"
    with pytest.raises(RpcError) as no_id:
        validate_method_params("tool.command_result", {"session_id": "s", "ok": True})
    assert no_id.value.code == "INVALID_PARAMS"
    with pytest.raises(RpcError):
        validate_method_params("tool.command_result", {"session_id": "s", "call_key": "k", "statements_total": -1})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_bridge_results.py -q`
Expected: `8 failed, 2 passed` — failures such as `AttributeError: 'VmdToolBridge' object has no attribute 'post_result'` and, for the protocol and RPC tests, `RpcError: INVALID_PARAMS: tool_call_id is required`; only `test_not_acked_cancel_immediate` and `test_running_cancel_waits_grace_then_unknown` pass (Task 1 already implements them).

- [ ] **Step 3: Add results, dedupe and late results to `runtime/vmd_ai_runtime/tool_bridge.py`**

(a) In `VmdToolBridge.__init__`, after `self.session_lookup = session_lookup`, add:

```python
        self.on_late_result: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
```

(b) Replace the whole `_finalize` method with:

```python
    def _finalize(self, pending: _PendingCall) -> Dict[str, Any]:
        """Turn the posted result into the product result dict (C2, C3).

        A posted ``executed: "no"`` always wins over the ack-derived status
        (C2 refusal, C3 pre-check), and such a call is never ``ok``.
        """
        raw = dict(pending.raw or {})
        executed = "no" if str(raw.get("executed") or "yes") == "no" else "yes"
        ok = bool(raw.get("ok", False)) and executed == "yes"
        output = str(raw.get("output") or "")
        error = str(raw.get("error") or "")
        if executed == "no" and not error:
            error = "not executed"
        duration = raw.get("duration_ms")
        if duration is None:
            duration = int((time.monotonic() - pending.started) * 1000)
        result = _empty_result()
        result.update({
            "ok": ok,
            "output": output,
            "error": error,
            "executed": executed,
            "truncated": bool(raw.get("truncated", False)),
            "duration_ms": int(duration),
            "statements": _statements_from(raw, ok),
            "output_bytes": len(output.encode("utf-8", "replace")),
            "applied_text": str(raw.get("applied_text") or ""),
        })
        return result
```

(c) Add this method directly after `ack`:

```python
    def post_result(self, session_id: str, params: Dict[str, Any]) -> Dict[str, bool]:
        """``tool.command_result`` by call_key. Returns {accepted, late, duplicate}.

        * The first result for a waiting call resolves it, acked or not: an
          un-acked result (a C2 refusal) counts as pickup.
        * A repeat of an accepted result is a duplicate (the plugin's result
          queue retries until it sees ``accepted``).
        * A result for a call execute_tool already gave up on is accepted as
          late: it is finalised the same way and handed to ``on_late_result``.
        """
        call_key = str(params.get("call_key") or "")
        with self._lock:
            pending = self._calls.get(call_key)
        if pending is None or pending.session_id != str(session_id or ""):
            return {"accepted": False, "late": False, "duplicate": False}
        with pending.lock:
            if pending.raw is not None:
                return {"accepted": True, "late": pending.late, "duplicate": True}
            pending.raw = dict(params)
            if not pending.finished:
                pending.done.set()
                return {"accepted": True, "late": False, "duplicate": False}
            pending.late = True
        late = self._finalize(pending)
        late.update({
            "late": True,
            "request_id": pending.request_id,
            "tool_name": pending.tool_name,
            "chat_dir": str(pending.chat_dir) if pending.chat_dir is not None else None,
        })
        callback = self.on_late_result
        if callback is not None:
            try:
                callback(pending.session_id, call_key, late)
            except Exception:
                logger.warning("on_late_result failed for %s", call_key, exc_info=True)
        return {"accepted": True, "late": True, "duplicate": False}
```

(d) Add this helper directly after `_empty_result`:

```python
def _statements_from(raw: Dict[str, Any], ok: bool) -> Optional[Dict[str, Any]]:
    """C3: {total, applied, failed} from the posted statement fields, or None."""
    total = raw.get("statements_total")
    if total is None:
        return None
    failed = None
    if not ok and raw.get("failed_index"):
        failed = {
            "index": int(raw["failed_index"]),
            "text": str(raw.get("failed_statement") or ""),
            "error_info": str(raw.get("error_info") or ""),
        }
    return {
        "total": int(total),
        "applied": int(raw.get("statements_applied") or 0),
        "failed": failed,
    }
```

- [ ] **Step 4: Whitelist the new `tool.command_result` params in `runtime/vmd_ai_runtime/protocol.py`**

(a) Change `from typing import Any, Dict` to `from typing import Any, Dict, Optional`.

(b) Add after `_as_int`:

```python
def _as_opt_int(value: Any, field: str) -> Optional[int]:
    """An optional non-negative int: None when absent."""
    if value is None or value == "":
        return None
    return _as_int(value, field, minimum=0)


def _as_raw_str(value: Any) -> str:
    """Exact text, not stripped: applied_text must be a source prefix (C3)."""
    return "" if value is None else str(value)


def _first_lines(text: str, lines: int, limit: int) -> str:
    """The first ``lines`` lines of ``text``, at most ``limit`` characters."""
    return "\n".join(text.splitlines()[:lines])[:limit]
```

(c) Replace the whole `if method == "tool.command_result":` block with:

```python
    if method == "tool.command_result":
        # Posted by the Tcl bridge after executing a VMD tool call. Token
        # sessions name the call by call_key (spec 2d, C2, C3); tokenless
        # sessions keep tool_call_id, which must match a pending call.
        call_key = _as_str(p.get("call_key") or "", "call_key", required=False)
        executed = _as_str(p.get("executed") or "yes", "executed", required=False)
        if executed not in ("yes", "no"):
            raise RpcError("INVALID_PARAMS", "executed must be 'yes' or 'no'",
                           {"allowed": ["yes", "no"]})
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "tool_call_id": _as_str(p.get("tool_call_id"), "tool_call_id", required=not call_key),
            "ok": bool(p.get("ok", False)),
            "output": _as_str(p.get("output") or "", "output", required=False),
            "error": _as_str(p.get("error") or "", "error", required=False),
            # snapshot_file: local path written by VMD's render command. The
            # runtime reads and deletes it only if it is the path it chose.
            "snapshot_file": _as_str(p.get("snapshot_file") or "", "snapshot_file", required=False),
            "call_key": call_key,
            "executed": executed,
            "statements_total": _as_opt_int(p.get("statements_total"), "statements_total"),
            "statements_applied": _as_opt_int(p.get("statements_applied"), "statements_applied"),
            "failed_index": _as_opt_int(p.get("failed_index"), "failed_index"),
            "failed_statement": _as_str(
                p.get("failed_statement") or "", "failed_statement", required=False)[:200],
            "error_info": _first_lines(_as_raw_str(p.get("error_info")), 3, 500),
            "applied_text": _as_raw_str(p.get("applied_text")),
            "duration_ms": _as_opt_int(p.get("duration_ms"), "duration_ms"),
            "truncated": bool(p.get("truncated", False)),
        }
```

- [ ] **Step 5: Route call_key results and store late results in `runtime/vmd_ai_runtime/app.py`**

(a) Make sure the conversation Appender is imported (plan 03 may already import it):

```python
from .conversation import Appender
```

(b) In `RuntimeApp.__init__`, directly after `self.tool_bridge = VmdToolBridge(session_lookup=self._bridge_session)`, add:

```python
        self.tool_bridge.on_late_result = self._on_late_result
```

(c) In `_dispatch`, inside `if method == "tool.command_result":`, insert directly after the line `state = self._get_session(params["session_id"], session_token)` (the existing tool_call_id code below it stays unchanged):

```python
            call_key = params.get("call_key") or ""
            if call_key:
                owner = self.tool_bridge.get_call_session(call_key)
                if owner is None:
                    raise RpcError(
                        "TOOL_CALL_UNKNOWN",
                        "call_key is not known (never issued or long expired)",
                        {"call_key": call_key},
                    )
                if owner != state.session_id:
                    raise RpcError(
                        "AUTH_FAILED",
                        "call_key does not belong to this session",
                        {"call_key": call_key},
                    )
                reply = self.tool_bridge.post_result(state.session_id, params)
                if reply.get("accepted") and not reply.get("duplicate"):
                    # v1 transcript entry, as for tool_call_id results.
                    ok = bool(params["ok"]) and params.get("executed") != "no"
                    label = (
                        params.get("output", "")[:120]
                        if ok
                        else f"Error: {params.get('error', '')[:120]}"
                    )
                    result_event = state.queue.push(
                        "tool_result",
                        "message",
                        label,
                        {
                            "tool_call_id": params.get("tool_call_id") or "",
                            "call_key": call_key,
                            "ok": ok,
                            "late": bool(reply.get("late")),
                        },
                    )
                    if state.chat_id:
                        self.store.append_events(state.chat_id, [result_event])
                return dict(reply)

```

(d) Add this method after `_tool_timeouts`:

```python
    def _on_late_result(self, session_id: str, call_key: str, info: Dict[str, Any]) -> None:
        """A tool result arrived after its request gave up (spec 2b Late results).

        Stored as a ``late_result`` line in the chat the call belonged to, so
        build_prior can note it before the next prompt.
        """
        chat_dir = info.get("chat_dir")
        if not chat_dir:
            return
        try:
            Appender(Path(chat_dir), str(info.get("request_id") or "")).append_late_result(
                call_key,
                bool(info.get("ok", False)),
                str(info.get("executed") or "yes"),
                str(info.get("output") or ""),
                str(info.get("error") or ""),
            )
        except Exception:
            if self.logger:
                self.logger.warning("could not store late result %s", call_key, exc_info=True)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_bridge_results.py tests/test_tool_bridge_ack.py tests/test_tool_command_result_auth.py tests/test_agent_integration.py tests/test_protocol.py -q`
Expected: all passed (`10 passed` from the new file plus the others), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+22 passed`, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/tool_bridge.py runtime/vmd_ai_runtime/protocol.py runtime/vmd_ai_runtime/app.py tests/test_tool_bridge_results.py
git commit -m "feat(bridge): tool.command_result by call_key with dedupe and late results (C2, C3)

A posted executed 'no' overrides the ack-derived status, an un-acked
result counts as pickup, repeats are duplicates, and results after the
bridge gave up are accepted as late and stored as late_result lines.
Whitelists the C3 statement fields.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: P05-T03 — Snapshot path, image and thumbnail files, save_path

**Files:**
- Create: `tests/test_snapshot_files.py`
- Modify: `runtime/vmd_ai_runtime/tool_bridge.py` (imports; `_finalize`; new `_attach_snapshot`; the snapshot block in `_execute_legacy`; new helpers `_legacy_snapshot_allowed`, `_write_save_path`)
- Modify: `runtime/vmd_ai_runtime/app.py:13` (`import shutil`), `:222-226` (`session.stop` removes the snapshot dir), new method `_drop_snapshot_dir`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py:1907-1956` (`_recorder_record`)
- Modify: `runtime/vmd_ai_runtime/recorder/run.py:250-293` (`record_snapshot`), `:320-340` (`_format_snapshot_block`)
- Modify: `tests/test_tool_bridge.py:219-223` and `:267` (tokenless snapshot tests use the one path §2d still allows)

**Interfaces:**
- Consumes: `image_scale.make_thumbnail(png, box_w=256, box_h=192) -> Tuple[bytes, int, int]`, `image_scale.to_jpeg(png, quality=90) -> Optional[bytes]`, `image_scale.png_size(png) -> Tuple[int, int]` (P04-T05); `BridgeSession` (P05-T01).
- Produces:
  - `snapshot_path = <snapshot_dir>/vmdai_snap_<call_key>.tga` (sent in `tool_start` since Task 1; the runtime reads and deletes only this path)
  - result `image {path, thumb_path, width, height, src_width, src_height, renderer:'TachyonInternal'}`; `saved_path`
  - `RunRecorder.record_snapshot(..., renderer: str = 'snapshot', saved_path: Optional[str] = None)`
  - `RuntimeApp._drop_snapshot_dir(session_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_snapshot_files.py`:

```python
"""spec 2d Snapshot, 2c Thumbnails, S10, S11: runtime-owned snapshot files."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session, write_tga
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime import tool_bridge as tb
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.recorder import RunRecorder

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
TOKEN = "0123456789abcdef0123456789abcdef"


def _snapshot_call(bridge, tool_input=None, call_key="k5a5a5a5a5a5"):
    call = BridgeCall(bridge, tool_name="capture_vmd_snapshot",
                      tool_input=tool_input if tool_input is not None else {"purpose": "check"},
                      call_key=call_key)
    meta = call.tool_start()["metadata"]
    bridge.ack(SESSION_ID, call_key)
    return call, meta["snapshot_path"]


def _post(bridge, call_key, snapshot_file, ok=True):
    return bridge.post_result(SESSION_ID, {"call_key": call_key, "ok": ok, "output": "rendered",
                                           "error": "", "snapshot_file": snapshot_file})


def test_snapshot_path_is_chosen_by_runtime(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=0.1)
    call, snap = _snapshot_call(bridge)
    assert snap == str(session.snapshot_dir / "vmdai_snap_k5a5a5a5a5a5.tga")
    call.cancel.set()
    call.join()


def test_foreign_snapshot_file_rejected_not_deleted(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call, snap = _snapshot_call(bridge)
    foreign = write_tga(tmp_path / "precious.tga")
    _post(bridge, call.call_key, str(foreign))
    result = call.join()
    assert result["ok"] is False
    assert result["error"] == "snapshot file rejected: not the path the runtime chose"
    assert foreign.exists(), "the runtime must never delete a path it did not choose"
    assert "image_b64" not in result


def test_tokenless_tmp_path_accepted_after_realpath(tmp_path):
    bridge = make_bridge(make_session(tmp_path, authenticated=False))
    tcid = "tc_snapT1"
    legacy = Path("/tmp/vmdai_snap_%s.tga" % tcid)
    write_tga(legacy)
    try:
        call = BridgeCall(bridge, tool_name="capture_vmd_snapshot", tool_input={"purpose": "x"},
                          tool_call_id=tcid, timeout=3)
        call.tool_start()
        bridge.resolve(tcid, {"ok": True, "output": "ok", "error": "",
                              "snapshot_file": os.path.realpath(str(legacy))})
        result = call.join()
        assert result["ok"] is True and result["image_mime"] == "image/png"
        assert not legacy.exists()
    finally:
        if legacy.exists():
            legacy.unlink()

    fd, other = tempfile.mkstemp(suffix=".tga")
    os.close(fd)
    write_tga(Path(other))
    try:
        call = BridgeCall(bridge, tool_name="capture_vmd_snapshot", tool_input={"purpose": "x"},
                          tool_call_id="tc_snapT2", timeout=3)
        call.tool_start()
        bridge.resolve("tc_snapT2", {"ok": True, "output": "ok", "error": "", "snapshot_file": other})
        result = call.join()
        assert result["ok"] is False and "rejected" in result["error"]
        assert os.path.exists(other)
    finally:
        os.unlink(other)


def test_legacy_id_with_path_characters_rejected():
    assert tb._legacy_snapshot_allowed("/tmp/x.tga", "../../x") is False
    assert tb._legacy_snapshot_allowed("/tmp/vmdai_snap_ok_1.tga", "ok_1") is True
    assert tb._legacy_snapshot_allowed("/tmp/vmdai_snap_functions.run:0.tga", "functions.run:0") is True


def test_image_and_thumb_written(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge)
    write_tga(Path(snap), 640, 480)
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is True, result
    images = session.chat_dir / "images"
    full = images / "k5a5a5a5a5a5.png"
    thumb = images / "k5a5a5a5a5a5_thumb.png"
    assert full.read_bytes().startswith(PNG_MAGIC)
    assert thumb.read_bytes().startswith(PNG_MAGIC)
    img = result["image"]
    assert img["path"] == str(full) and img["thumb_path"] == str(thumb)
    assert (img["width"], img["height"], img["src_width"], img["src_height"]) == (640, 480, 640, 480)
    assert img["renderer"] == "TachyonInternal"
    assert result["image_b64"] and result["image_mime"] == "image/png"
    assert result["output"] == "Snapshot rendered (640×480)."
    assert not Path(snap).exists(), "the temp TGA is deleted"


def test_save_path_relative_to_session_cwd(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"purpose": "figure", "save_path": "fig1.png"})
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    target = Path(session.cwd) / "fig1.png"
    assert result["ok"] is True
    assert target.read_bytes().startswith(PNG_MAGIC)
    assert result["saved_path"] == str(target)
    assert result["output"].endswith("Saved to %s." % target)


def test_save_path_jpg_without_pillow_png_note(tmp_path, monkeypatch):
    monkeypatch.setattr(tb, "to_jpeg", lambda png, quality=90: None)
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"save_path": "fig.jpg"})
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    png_target = Path(session.cwd) / "fig.png"
    assert result["ok"] is True
    assert result["saved_path"] == str(png_target)
    assert png_target.read_bytes().startswith(PNG_MAGIC)
    assert not (Path(session.cwd) / "fig.jpg").exists()
    assert "JPEG needs Pillow; saved as PNG instead." in result["output"]


def test_save_path_bad_dir(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    call, snap = _snapshot_call(bridge, {"save_path": "missing_dir/fig.png"}, call_key="k5a5a5a5a5b1")
    write_tga(Path(snap))
    _post(bridge, call.call_key, snap)
    result = call.join()
    assert result["ok"] is False
    assert result["error"].startswith("save_path directory does not exist: ")
    assert result["image_b64"], "the render itself still reaches the model"
    assert not (Path(session.cwd) / "missing_dir").exists()

    call2, snap2 = _snapshot_call(bridge, {"save_path": "../escape.png"}, call_key="k5a5a5a5a5b2")
    write_tga(Path(snap2))
    _post(bridge, call2.call_key, snap2)
    result2 = call2.join()
    assert result2["ok"] is False
    assert result2["error"] == "save_path must not contain '..': ../escape.png"
    assert not (tmp_path / "escape.png").exists()


def test_recorder_logs_render_tachyon_for_save_path(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("figure")
    rec.record_snapshot(ok=True, purpose="fig", image_bytes=PNG_MAGIC,
                        renderer="TachyonInternal", saved_path="/work/fig 1.png")
    rec.record_snapshot(ok=True, purpose="plain", image_bytes=PNG_MAGIC)
    rec.end_task()
    text = rec.read_transcript(tid)
    assert "render TachyonInternal snapshots/turn_001.png" in text
    assert "render TachyonInternal {/work/fig 1.png}" in text
    assert "# save_path : /work/fig 1.png" in text
    assert "render snapshot snapshots/turn_002.png" in text


def test_loop_records_snapshot_with_renderer(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("fig")
    png = PNG_MAGIC + b"\0" * 16
    loop._recorder_record(
        tool_name="capture_vmd_snapshot",
        tool_input={"purpose": "fig", "save_path": "fig1.png"},
        result={"ok": True, "output": "", "error": "",
                "image_b64": base64.b64encode(png).decode("ascii"), "image_mime": "image/png",
                "image": {"renderer": "TachyonInternal"}, "saved_path": "/w/fig1.png"},
        duration_ms=3.0,
    )
    text = loop.recorder.read_transcript(tid)
    assert "render TachyonInternal snapshots/turn_001.png" in text
    assert "render TachyonInternal {/w/fig1.png}" in text


def test_session_stop_removes_snapshot_dir(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    snap_dir = app._snapshot_dir_for(sess["session_id"])
    assert snap_dir.is_dir()
    resp = app.handle_rpc({"jsonrpc": "2.0", "id": "s", "method": "session.stop",
                           "params": {"session_id": sess["session_id"]}},
                          session_token=sess["session_token"])
    assert resp["result"]["ok"] is True
    assert not snap_dir.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_snapshot_files.py -q`
Expected: `10 failed, 1 passed` — e.g. `AttributeError: module 'vmd_ai_runtime.tool_bridge' has no attribute '_legacy_snapshot_allowed'`, `FileNotFoundError: ... images/k5a5a5a5a5a5.png`, `TypeError: RunRecorder.record_snapshot() got an unexpected keyword argument 'renderer'`; only `test_snapshot_path_is_chosen_by_runtime` passes.

- [ ] **Step 3: Own the snapshot files in `runtime/vmd_ai_runtime/tool_bridge.py`**

(a) Add to the imports, after `from .image_utils import read_image_as_png_bytes`:

```python
from .image_scale import make_thumbnail, png_size, to_jpeg
```

(b) In `_finalize`, replace the final `        return result` with:

```python
        if pending.tool_name == "capture_vmd_snapshot":
            self._attach_snapshot(pending, raw, result)
        return result
```

(c) Add this method directly after `_finalize`:

```python
    def _attach_snapshot(self, pending: _PendingCall, raw: Dict[str, Any],
                         result: Dict[str, Any]) -> None:
        """Read the render the runtime asked for, write image + thumbnail files,
        honour save_path, and delete the temp TGA (spec 2d Snapshot, 2c).

        The runtime reads and deletes ONLY ``pending.snapshot_path``; a posted
        ``snapshot_file`` naming any other path is rejected and left alone (S11).
        """
        expected = pending.snapshot_path
        posted = str(raw.get("snapshot_file") or "")
        try:
            if posted and os.path.realpath(posted) != os.path.realpath(expected):
                logger.warning("rejected snapshot_file %r (expected %r)", posted, expected)
                result["ok"] = False
                result["error"] = "snapshot file rejected: not the path the runtime chose"
                return
            if not result["ok"]:
                return
            png = read_image_as_png_bytes(expected) if os.path.isfile(expected) else None
            if not png:
                result["ok"] = False
                result["error"] = "Snapshot file missing or unreadable: %s" % expected
                return
            width, height = png_size(png)
            result["image_b64"] = base64.b64encode(png).decode("ascii")
            result["image_mime"] = "image/png"
            image: Dict[str, Any] = {
                "path": None,
                "thumb_path": None,
                "width": width,
                "height": height,
                "src_width": width,
                "src_height": height,
                "renderer": "TachyonInternal",
            }
            if pending.chat_dir is not None:
                images = Path(pending.chat_dir) / "images"
                images.mkdir(parents=True, exist_ok=True)
                full = images / ("%s.png" % pending.call_key)
                thumb = images / ("%s_thumb.png" % pending.call_key)
                full.write_bytes(png)
                thumb_png, _thumb_w, _thumb_h = make_thumbnail(png, 256, 192)
                thumb.write_bytes(thumb_png)
                image["path"] = str(full)
                image["thumb_path"] = str(thumb)
            result["image"] = image
            note = "Snapshot rendered (%d×%d)." % (width, height)
            save_path = str(pending.tool_input.get("save_path") or "").strip()
            if save_path:
                saved, message = _write_save_path(png, save_path, pending.cwd)
                if saved is None:
                    result["ok"] = False
                    result["error"] = message
                else:
                    result["saved_path"] = saved
                    note += " " + message
            result["output"] = note
        finally:
            try:
                if expected and os.path.isfile(expected):
                    os.unlink(expected)
            except OSError:
                pass
```

(d) In `_execute_legacy`, replace the block that starts with the comment `# For snapshot tool: read the rendered file and base64-encode it.` and ends before `return result` with:

```python
            # For snapshot tool: read the rendered file and base64-encode it.
            # Old plugins may only use /tmp/vmdai_snap_<tool_call_id>.tga
            # (spec 2d); any other path is rejected, never read or deleted.
            if tool_name == "capture_vmd_snapshot" and result.get("ok"):
                snap_file = str(result.get("snapshot_file") or "")
                if snap_file and _legacy_snapshot_allowed(snap_file, tool_call_id):
                    if os.path.isfile(snap_file):
                        png_bytes = read_image_as_png_bytes(snap_file)
                        if png_bytes:
                            result["image_b64"] = base64.b64encode(png_bytes).decode()
                            result["image_mime"] = "image/png"
                        try:
                            os.unlink(snap_file)
                        except Exception:
                            pass
                elif snap_file:
                    logger.warning("rejected snapshot_file %r for %s", snap_file, tool_call_id)
                    result["ok"] = False
                    result["error"] = ("snapshot file rejected: the plugin may only use "
                                       "/tmp/vmdai_snap_<tool_call_id>.tga")

```

(e) Add these helpers after `_statements_from`:

```python
def _legacy_snapshot_allowed(path: str, tool_call_id: str) -> bool:
    """Old plugins may only post /tmp/vmdai_snap_<tool_call_id>.tga (compared after realpath)."""
    tcid = str(tool_call_id or "")
    if not tcid or any(ch in tcid for ch in "/\\\x00"):
        return False
    allowed = "/tmp/vmdai_snap_%s.tga" % tcid
    return os.path.realpath(path) == os.path.realpath(allowed)


def _write_save_path(png: bytes, save_path: str, cwd: str):
    """Write the save_path deliverable (S10). Returns (absolute path, note) or (None, error).

    Relative paths resolve against the session cwd. JPEG needs Pillow;
    without it the image is written as .png and the note says so. A missing
    directory or a '..' component is refused; nothing is ever deleted.
    """
    raw = os.path.expanduser(save_path)
    if ".." in Path(raw).parts:
        return None, "save_path must not contain '..': %s" % save_path
    dest = raw if os.path.isabs(raw) else os.path.join(cwd or os.getcwd(), raw)
    dest = os.path.normpath(dest)
    parent = os.path.dirname(dest) or "."
    if not os.path.isdir(parent):
        return None, "save_path directory does not exist: %s" % parent
    ext = os.path.splitext(dest)[1].lower()
    note = ""
    data = png
    if ext in (".jpg", ".jpeg"):
        jpeg = to_jpeg(png)
        if jpeg is None:
            dest = os.path.splitext(dest)[0] + ".png"
            note = " (JPEG needs Pillow; saved as PNG instead.)"
        else:
            data = jpeg
    try:
        with open(dest, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        return None, "could not write save_path %s: %s" % (dest, exc)
    return dest, "Saved to %s.%s" % (dest, note)
```

- [ ] **Step 4: Replay lines in `runtime/vmd_ai_runtime/recorder/run.py`**

(a) Replace the whole `record_snapshot` method with:

```python
    def record_snapshot(
        self,
        *,
        ok: bool,
        purpose: str = "",
        image_bytes: Optional[bytes] = None,
        image_ext: str = "png",
        duration_ms: float = 0.0,
        renderer: str = "snapshot",
        saved_path: Optional[str] = None,
    ) -> Optional[int]:
        """Record one ``capture_vmd_snapshot`` tool call.

        On success: save image_bytes to ``snapshots/turn_NNN.<ext>`` and
        emit a ``render <renderer> snapshots/turn_NNN.<ext>`` line to
        ``transcript.tcl`` so replay reproduces the image file. When the
        runtime also wrote a ``save_path`` deliverable, replay re-renders it
        with ``render <renderer> {<saved_path>}``. Returns the turn number.

        On failure: count it and return None.
        """
        if self._current is None:
            return None
        self._current.turn_count += 1
        turn_n = self._current.turn_count
        self._current.last_activity_at = time.time()

        if not ok:
            self._current.failed_count += 1
            self._flush_manifest(status="active")
            return None

        ext = (image_ext or "png").lower().lstrip(".")
        if ext not in _SAFE_EXT:
            ext = "png"
        snap_name = f"turn_{turn_n:03d}.{ext}"

        if image_bytes is not None:
            (self._current.dir / "snapshots" / snap_name).write_bytes(image_bytes)

        self._current.successful_count += 1
        self._current.snapshot_count += 1
        block = self._format_snapshot_block(
            turn_n, snap_name, purpose, duration_ms,
            renderer=renderer, saved_path=saved_path,
        )
        with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
            f.write(block)
        self._flush_manifest(status="active")
        return turn_n
```

(b) Replace the whole `_format_snapshot_block` method with:

```python
    def _format_snapshot_block(
        self,
        turn_n: int,
        snap_name: str,
        purpose: str,
        duration_ms: float,
        renderer: str = "snapshot",
        saved_path: Optional[str] = None,
    ) -> str:
        ts = _utc_iso(time.time())
        out: list[str] = []
        out.append("")
        out.append(
            f"# --- turn {turn_n:02d} | {ts} | {duration_ms:.0f}ms | snapshot ---"
        )
        if purpose:
            for p_line in purpose.splitlines():
                out.append(f"# purpose   : {p_line}")
        out.append(f"# saved to  : snapshots/{snap_name}")
        if saved_path:
            out.append(f"# save_path : {saved_path}")
        out.append("")
        out.append(f"render {renderer} snapshots/{snap_name}")
        if saved_path:
            out.append(f"render {renderer} {{{saved_path}}}")
        out.append("")
        return "\n".join(out)
```

- [ ] **Step 5: Pass the renderer and saved path from the loop — `runtime/vmd_ai_runtime/claude_loop.py`**

Replace the whole `_recorder_record` method with:

```python
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
```

- [ ] **Step 6: Remove a session's snapshot dir on `session.stop` — `runtime/vmd_ai_runtime/app.py`**

(a) Add `import shutil` next to `import os`.

(b) In the `session.stop` branch, directly after `self.sessions.remove(state.session_id)`, add:

```python
            self._drop_snapshot_dir(state.session_id)
```

(c) Add this method after `_snapshot_dir_for`:

```python
    def _drop_snapshot_dir(self, session_id: str) -> None:
        """Delete the per-session snapshot temp dir (it only ever holds renders)."""
        with self._snapshot_lock:
            path = self._snapshot_dirs.pop(session_id, None)
        if path:
            shutil.rmtree(path, ignore_errors=True)
```

- [ ] **Step 7: Move the two tokenless snapshot tests onto the path §2d allows — `tests/test_tool_bridge.py`**

(a) In `test_snapshot_reads_tga_file_and_produces_b64_png`, replace:

```python
        tga_data = _make_tga_1x1()
        with tempfile.NamedTemporaryFile(suffix=".tga", delete=False) as f:
            f.write(tga_data)
            tga_path = f.name
```

with:

```python
        tga_data = _make_tga_1x1()
        # Tokenless sessions may only use the path the old plugin builds
        # (spec 2d Snapshot): /tmp/vmdai_snap_<tool_call_id>.tga
        tga_path = "/tmp/vmdai_snap_tc_snap.tga"
        with open(tga_path, "wb") as f:
            f.write(tga_data)
```

(b) In `test_snapshot_missing_file_no_image`, replace `"snapshot_file": "/tmp/does_not_exist_vmdai_test.tga",` with:

```python
                "snapshot_file": "/tmp/vmdai_snap_tc_snap2.tga",
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_snapshot_files.py tests/test_tool_bridge.py tests/test_recorder.py tests/test_claude_loop_recorder.py tests/test_recorder_integration.py -q`
Expected: all passed (`11 passed` from the new file plus the existing ones), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+33 passed`, 0 failed.

- [ ] **Step 9: Commit**

```bash
git add runtime/vmd_ai_runtime/tool_bridge.py runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/claude_loop.py runtime/vmd_ai_runtime/recorder/run.py tests/test_snapshot_files.py tests/test_tool_bridge.py
git commit -m "feat(bridge): runtime-owned snapshot path, image and thumbnail files, save_path (S10, S11)

The runtime reads and deletes only the snapshot path it chose; foreign
paths are rejected. Snapshots are written to chats/<id>/images with a
256x192 thumbnail, save_path resolves against the session cwd, and the
recorder replays with render TachyonInternal.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 4: P05-T04 — tcl_policy module (C1)

**Files:**
- Create: `runtime/vmd_ai_runtime/tcl_policy.py`
- Create: `tests/test_tcl_policy.py`
- Modify: `tests/test_py39_compat.py` (append one entry to `RUNTIME_MODULES`)

**Interfaces:**
- Consumes: `tests/test_py39_compat.py RUNTIME_MODULES: List[str]` (P01-T09).
- Produces:
  - `@dataclass(frozen=True) tcl_policy.Finding(id: str, word: str, statement_index: int, text: str)` — `statement_index` is 1-based over `split_statements`; `text` is the offending command (≤ 200 chars) or, for `protected_path`, the literal path
  - `tcl_policy.check(command: str, *, checkout_root: Optional[str] = None, home: Optional[str] = None) -> List[Finding]` (defaults: the checkout this module runs from, and `~`)
  - `tcl_policy.FINDING_IDS` = `("cmd_exec", "cmd_socket", "cmd_load", "cmd_quit", "cmd_rename", "interp_unsafe", "open_pipe", "protected_path", "too_deep")`
  - `tcl_policy.message_for(finding: Finding) -> str`
  - `tcl_policy.split_statements(script: str) -> List[str]` (the executor's `info complete` line grouping; `a; b` on one line is one statement; a comment ending in a backslash swallows the next line)
  - `tcl_policy.is_protected_path(path: str, *, checkout_root: Optional[str] = None, home: Optional[str] = None) -> bool` (addition, see Deviations)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tcl_policy.py`:

```python
"""C1: the critical-Tcl accident guard (runtime/vmd_ai_runtime/tcl_policy.py)."""
from __future__ import annotations

import glob
from pathlib import Path

import pytest

from vmd_ai_runtime import tcl_policy

REPO = Path(__file__).resolve().parents[1]
HOME = "/Users/tester"
ROOT = "/opt/vmdai-checkout"


def ids(command):
    return [f.id for f in tcl_policy.check(command, checkout_root=ROOT, home=HOME)]


BLOCKED = [
    ("exec ls", "cmd_exec"),
    ("set x [exec ls]", "cmd_exec"),
    ("after 0 {exec ls}", "cmd_exec"),
    ("if {1} {exec ls}", "cmd_exec"),
    ("catch {exec ls}", "cmd_exec"),
    ('puts [open "|ls"]', "open_pipe"),
    ("quit", "cmd_quit"),
    ("mol new a.pdb; exit", "cmd_quit"),
    ("file delete ~/.vmdrc", "protected_path"),
    ("source ~/.vmdai/x.tcl", "protected_path"),
    ("interp create", "interp_unsafe"),
    ('puts "[exec ls]"', "cmd_exec"),
    ("file delete -force -- ~/.ssh/x", "protected_path"),
]

ALLOWED = [
    "mol rename $m x",
    'puts "exit code"',
    "set fh [open $path w]",
    "open out.dat w",
    "interp create -safe",
    "namespace eval vmdai {}",
    'atomselect top "resname EXE"',
    "# exec ls",
    "# note \\\nexec ls",
]


@pytest.mark.parametrize("command,finding_id", BLOCKED)
def test_blocked_cases(command, finding_id):
    assert finding_id in ids(command), command


@pytest.mark.parametrize("command", ALLOWED)
def test_allowed_cases(command):
    assert ids(command) == [], command


def test_pinned_gaps():
    # Known, documented limits of a static check (spec C1): no finding.
    assert ids("set c exec; $c ls") == []
    assert ids('eval "exec ls"') == []


def test_too_deep():
    deep = "if {1} {" * 17 + "puts x" + "}" * 17
    assert "too_deep" in ids(deep)
    shallow = "if {1} {" * 15 + "puts x" + "}" * 15
    assert ids(shallow) == []
    brackets = "set x " + "[" * 18 + "list 1" + "]" * 18
    assert "too_deep" in ids(brackets)


def test_more_protected_paths():
    assert ids("file mkdir $env(HOME)/.vmdai/x") == ["protected_path"]
    assert ids("set f [open ~/Library/LaunchAgents/x.plist w]") == ["protected_path"]
    assert ids("file copy notes.txt /") == ["protected_path"]
    assert ids("file delete " + ROOT + "/runtime/main.py") == ["protected_path"]
    assert ids("file delete ~") == ["protected_path"]
    assert ids("file delete /tmp/scratch.dat") == []
    assert ids("open ~/.vmdrc r") == []


def test_finding_fields_and_statement_index():
    found = tcl_policy.check("mol new a.pdb\nset x [exec ls]\n", checkout_root=ROOT, home=HOME)
    assert len(found) == 1
    f = found[0]
    assert (f.id, f.word, f.statement_index, f.text) == ("cmd_exec", "exec", 2, "exec ls")
    assert f.id in tcl_policy.FINDING_IDS
    pf = tcl_policy.check("file delete -force ~/.ssh/id_rsa", checkout_root=ROOT, home=HOME)[0]
    assert (pf.word, pf.text) == ("file delete", "~/.ssh/id_rsa")


def test_messages():
    exec_f = tcl_policy.check("exec curl -O x", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(exec_f) == (
        "Not run: `exec` is never run by ChatVMD. If the user needs it, show the "
        "command in a tcl code block so they can copy it and run it in the VMD "
        "console themselves."
    )
    quit_f = tcl_policy.check("exit", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(quit_f) == "Not run: this would close the user's VMD session."
    sock_f = tcl_policy.check("socket localhost 80", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(sock_f).startswith("Not run: `socket` is never run by ChatVMD.")
    path_f = tcl_policy.check("source ~/.vmdai/x.tcl", checkout_root=ROOT, home=HOME)[0]
    assert tcl_policy.message_for(path_f) == "Not run: ChatVMD never writes, deletes or sources ~/.vmdai/x.tcl."


def test_split_statements_matches_executor_grouping():
    script = "mol new a.pdb\n\n# comment\nforeach i {1 2} {\n  puts $i\n}\nset a 1; set b 2\nset x {"
    assert tcl_policy.split_statements(script) == [
        "mol new a.pdb",
        "foreach i {1 2} {\n  puts $i\n}",
        "set a 1; set b 2",
        "set x {",
    ]
    assert tcl_policy.split_statements("# a \\\nexec ls\nputs ok") == ["puts ok"]


def test_never_raises_on_garbage():
    for text in ["{", "}", "[", "]", '"', "\\", "{*}", "set x [", 'puts "[exec', "{" * 500, "[" * 500]:
        tcl_policy.check(text, checkout_root=ROOT, home=HOME)


def test_corpus_zero_findings():
    files = sorted(glob.glob(str(REPO / "vmdbench" / "oracles" / "**" / "*.tcl"), recursive=True))
    files += sorted(glob.glob(str(REPO / "skills" / "*" / "scripts" / "*.tcl")))
    assert len(files) == 54, files
    offenders = {}
    for path in files:
        text = Path(path).read_text(encoding="utf-8")
        found = tcl_policy.check(text, checkout_root=str(REPO), home=HOME)
        if found:
            offenders[path] = found
    assert offenders == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tcl_policy.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'vmd_ai_runtime.tcl_policy'`.

- [ ] **Step 3: Write `runtime/vmd_ai_runtime/tcl_policy.py`**

```python
"""
tcl_policy.py - the critical-Tcl accident guard (spec Part C, C1).

``check(command)`` statically scans model-written Tcl for words that must
never run inside the user's VMD session: shell commands, sockets, binary
extensions, quitting VMD, renaming commands, unsafe interpreters, pipes,
and writes/deletes/sources of protected paths.

This is an ACCIDENT GUARD FOR MODEL MISTAKES, not a sandbox. Tcl can build
a command name at run time (``set c exec; $c ls``) or evaluate a quoted
string (``eval "exec ls"``); a static check cannot see either, and the
tests pin both as known gaps.

Parsing follows Tcl's rules closely enough for that purpose:
  * statements end at a newline or ``;`` outside braces, quotes and brackets;
  * ``#`` in command position starts a comment that runs to the next newline
    not preceded by a backslash;
  * the first word of every statement is checked at top level, inside every
    ``[...]`` (also inside double-quoted words) and inside every braced word:
    every brace body is scanned as a script, an over-approximation that covers
    if/for/foreach/while/proc/after/catch/eval/namespace eval without a
    per-command table;
  * ``{*}`` is stripped; nesting deeper than 16 is itself a finding.

Stdlib-only and Python 3.9-compatible.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set, Tuple

MAX_DEPTH = 16
_PARSE_LIMIT = 48  # parser recursion cap; deeper brackets are skipped flat

FINDING_IDS = (
    "cmd_exec",
    "cmd_socket",
    "cmd_load",
    "cmd_quit",
    "cmd_rename",
    "interp_unsafe",
    "open_pipe",
    "protected_path",
    "too_deep",
)

_COMMAND_IDS = {
    "exec": "cmd_exec",
    "socket": "cmd_socket",
    "load": "cmd_load",
    "quit": "cmd_quit",
    "exit": "cmd_quit",
    "rename": "cmd_rename",
}

_FILE_WRITE_SUBCOMMANDS = ("delete", "rename", "copy", "link", "mkdir")
_OPEN_WRITE_MODES = ("w", "a", "w+", "a+")
_PROTECTED_UNDER_HOME = (".vmdai", ".vmdrc", ".ssh", os.path.join("Library", "LaunchAgents"))
_HOME_VARS = ("$env(HOME)", "$::env(HOME)", "${env(HOME)}", "${::env(HOME)}")

_WS = " \t\r\f\v"


@dataclass(frozen=True)
class Finding:
    id: str
    word: str
    statement_index: int
    text: str


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------

@dataclass
class _Word:
    kind: str                 # "brace" | "quote" | "bare"
    text: str                 # literal content (without braces/quotes)
    subs: List[str]           # scripts of [...] substitutions (quote/bare words)


@dataclass
class _Command:
    start: int
    end: int
    words: List[_Word]


def _skip_backslash(s: str, i: int) -> int:
    """``s[i]`` is a backslash: return the index after the escaped char."""
    return min(i + 2, len(s))


def _skip_bracket_flat(s: str, i: int) -> Tuple[str, int, bool]:
    """Find the ``]`` matching ``s[i] == "["`` by counting (no recursion)."""
    depth = 0
    j = i
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\":
            j = _skip_backslash(s, j)
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1, True
        j += 1
    return s[i + 1:], n, False


def _parse_bracket(s: str, i: int, level: int) -> Tuple[str, int, bool]:
    """``s[i]`` is ``[``. Return (inner script, index after ``]``, complete)."""
    if level > _PARSE_LIMIT:
        return _skip_bracket_flat(s, i)
    _cmds, end, complete = _parse_script(s, i + 1, in_bracket=True, level=level + 1)
    if complete and end < len(s) and s[end] == "]":
        return s[i + 1:end], end + 1, True
    return s[i + 1:end], end, False


def _parse_word(s: str, i: int, in_bracket: bool, level: int) -> Tuple[_Word, int, bool]:
    n = len(s)
    if s.startswith("{*}", i) and i + 3 < n and s[i + 3] not in _WS + "\n;":
        i += 3
    c = s[i]
    if c == "{":
        depth = 1
        j = i + 1
        while j < n and depth:
            ch = s[j]
            if ch == "\\":
                j = _skip_backslash(s, j)
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        if depth:
            return _Word("brace", s[i + 1:], []), n, False
        word = _Word("brace", s[i + 1:j - 1], [])
        # Tcl rejects "extra characters after close-brace"; we just stop here.
        return word, j, True
    if c == '"':
        j = i + 1
        subs: List[str] = []
        while j < n:
            ch = s[j]
            if ch == "\\":
                j = _skip_backslash(s, j)
                continue
            if ch == "[":
                inner, j, ok = _parse_bracket(s, j, level)
                subs.append(inner)
                if not ok:
                    return _Word("quote", s[i + 1:j], subs), j, False
                continue
            if ch == '"':
                return _Word("quote", s[i + 1:j], subs), j + 1, True
            j += 1
        return _Word("quote", s[i + 1:], subs), n, False
    j = i
    subs = []
    while j < n:
        ch = s[j]
        if ch == "\\":
            if j + 1 < n and s[j + 1] == "\n":
                break
            j = _skip_backslash(s, j)
            continue
        if ch in _WS or ch in "\n;":
            break
        if in_bracket and ch == "]":
            break
        if ch == "[":
            inner, j, ok = _parse_bracket(s, j, level)
            subs.append(inner)
            if not ok:
                return _Word("bare", s[i:j], subs), j, False
            continue
        j += 1
    return _Word("bare", s[i:j], subs), j, True


def _parse_script(s: str, i: int = 0, in_bracket: bool = False,
                  level: int = 0,
                  newlines: Optional[Set[int]] = None) -> Tuple[List[_Command], int, bool]:
    """Parse commands from ``s[i:]``. Returns (commands, end index, complete).

    In bracket mode parsing stops at the unmatched ``]`` (not consumed).
    ``complete`` is False when a brace, quote or bracket is left open.
    When ``newlines`` is given, the index of every newline that ends a line
    at top level (between commands, ending a command, ending a comment) is
    added to it. Never raises.
    """
    n = len(s)
    cmds: List[_Command] = []
    while i < n:
        while i < n:
            ch = s[i]
            if ch in _WS or ch in "\n;":
                if ch == "\n" and newlines is not None:
                    newlines.add(i)
                i += 1
            elif ch == "\\" and i + 1 < n and s[i + 1] == "\n":
                i += 2
            else:
                break
        if i >= n:
            break
        if in_bracket and s[i] == "]":
            return cmds, i, True
        if s[i] == "#":
            while i < n:
                if s[i] == "\\":
                    i = _skip_backslash(s, i)
                    continue
                if s[i] == "\n":
                    if newlines is not None:
                        newlines.add(i)
                    break
                i += 1
            continue
        start = i
        words: List[_Word] = []
        while i < n:
            while i < n:
                ch = s[i]
                if ch in _WS:
                    i += 1
                elif ch == "\\" and i + 1 < n and s[i + 1] == "\n":
                    i += 2
                else:
                    break
            if i >= n or s[i] in "\n;":
                break
            if in_bracket and s[i] == "]":
                break
            word, i, ok = _parse_word(s, i, in_bracket, level)
            words.append(word)
            if not ok:
                cmds.append(_Command(start, i, words))
                return cmds, i, False
        cmds.append(_Command(start, i, words))
        if in_bracket and i < n and s[i] == "]":
            return cmds, i, True
    return cmds, i, not in_bracket


# ----------------------------------------------------------------------
# Statement split (same grouping as the executor's info-complete split)
# ----------------------------------------------------------------------

def split_statements(script: str) -> List[str]:
    """Split ``script`` the way executor.tcl does before running it.

    Lines are accumulated until the buffer is a complete Tcl script
    (``info complete``). Blank lines and full-line comments between
    statements are skipped; a comment line ending in a backslash also
    swallows the next line, as Tcl does. ``a; b`` on one line is one
    statement. An incomplete tail is returned as the last element.

    One linear parse finds the newlines that end a line at top level; a
    buffer is complete exactly when its last newline is one of them.
    """
    text = script or ""
    top: Set[int] = set()
    _parse_script(text, newlines=top)
    out: List[str] = []
    buf_start: Optional[int] = None
    in_comment = False
    pos = 0
    n = len(text)
    while pos <= n:
        nl = text.find("\n", pos)
        end = n if nl < 0 else nl
        at_top = nl < 0 or end in top
        if buf_start is None:
            line = text[pos:end]
            if in_comment:
                in_comment = not at_top
            elif line.strip() and line.strip().startswith("#"):
                in_comment = not at_top
            elif line.strip():
                buf_start = pos
        if buf_start is not None and at_top:
            stmt = text[buf_start:end].strip()
            if stmt:
                out.append(stmt)
            buf_start = None
        if nl < 0:
            break
        pos = nl + 1
    if buf_start is not None and text[buf_start:].strip():
        out.append(text[buf_start:].strip())
    return out


# ----------------------------------------------------------------------
# Path protection
# ----------------------------------------------------------------------

def _default_checkout_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def _expand(path: str, home: str) -> Optional[str]:
    """Expand ``~`` and ``$env(HOME)`` in a literal path; None if not literal."""
    p = path
    for var in _HOME_VARS:
        if p == var or p.startswith(var + "/"):
            p = home + p[len(var):]
            break
    if p == "~" or p.startswith("~/"):
        p = home + p[1:]
    if "$" in p or "[" in p:
        return None
    return p


def is_protected_path(path: str, *, checkout_root: Optional[str] = None,
                      home: Optional[str] = None) -> bool:
    """True when the literal ``path`` is ``~``, ``/``, or under a protected tree."""
    home_dir = os.path.normpath(home or os.path.expanduser("~"))
    root = os.path.normpath(checkout_root or _default_checkout_root())
    expanded = _expand(path.strip(), home_dir)
    if expanded is None or not os.path.isabs(expanded):
        return False
    p = os.path.normpath(expanded)
    if p in ("/", home_dir):
        return True
    trees = [os.path.join(home_dir, sub) for sub in _PROTECTED_UNDER_HOME] + [root]
    for tree in trees:
        if p == tree or p.startswith(tree.rstrip("/") + "/"):
            return True
    return False


# ----------------------------------------------------------------------
# Scanner
# ----------------------------------------------------------------------

def _literal(word: _Word) -> Optional[str]:
    """The word's literal value, or None when it depends on substitution."""
    if word.subs:
        return None
    if word.kind == "brace":
        return word.text
    if "$" in word.text and word.text not in _HOME_VARS and not any(
            word.text.startswith(v + "/") for v in _HOME_VARS):
        return None
    return word.text


def _command_findings(words: List[_Word], text: str, index: int,
                      checkout_root: str, home: str) -> List[Finding]:
    if not words:
        return []
    name = _literal(words[0])
    if name is None:
        return []
    name = name.lstrip(":")
    args = [_literal(w) for w in words[1:]]
    preview = " ".join(text.split())[:200]
    found: List[Finding] = []

    def protected(p: Optional[str]) -> bool:
        return p is not None and is_protected_path(p, checkout_root=checkout_root, home=home)

    if name in _COMMAND_IDS:
        found.append(Finding(_COMMAND_IDS[name], name, index, preview))
    elif name == "interp":
        if args and args[0] == "create" and "-safe" not in args[1:]:
            found.append(Finding("interp_unsafe", "interp create", index, preview))
    elif name == "open":
        target = args[0] if args else None
        if target is not None and target.startswith("|"):
            found.append(Finding("open_pipe", "open |", index, preview))
        elif len(args) >= 2 and args[1] in _OPEN_WRITE_MODES and protected(target):
            found.append(Finding("protected_path", "open", index, str(target)))
    elif name == "file":
        if args and args[0] in _FILE_WRITE_SUBCOMMANDS:
            rest = args[1:]
            while rest and rest[0] is not None and rest[0].startswith("-"):
                done = rest[0] == "--"
                rest = rest[1:]
                if done:
                    break
            hits = [p for p in rest if protected(p)]
            if hits:
                found.append(Finding("protected_path", "file " + str(args[0]), index, str(hits[0])))
    elif name == "source":
        if args and protected(args[-1]):
            found.append(Finding("protected_path", "source", index, str(args[-1])))
    return found


def _scan(script: str, depth: int, index: int, findings: List[Finding],
          checkout_root: str, home: str) -> None:
    if depth > MAX_DEPTH:
        if not any(f.id == "too_deep" for f in findings):
            findings.append(Finding("too_deep", "", index, "nesting deeper than %d" % MAX_DEPTH))
        return
    cmds, _end, _complete = _parse_script(script)
    for cmd in cmds:
        text = script[cmd.start:cmd.end]
        findings.extend(_command_findings(cmd.words, text, index, checkout_root, home))
        for word in cmd.words:
            if word.kind == "brace":
                _scan(word.text, depth + 1, index, findings, checkout_root, home)
            for sub in word.subs:
                _scan(sub, depth + 1, index, findings, checkout_root, home)


def check(command: str, *, checkout_root: Optional[str] = None,
          home: Optional[str] = None) -> List[Finding]:
    """Return the critical findings in ``command`` (empty list = allowed)."""
    root = checkout_root or _default_checkout_root()
    home_dir = home or os.path.expanduser("~")
    findings: List[Finding] = []
    for idx, stmt in enumerate(split_statements(command or ""), start=1):
        _scan(stmt, 0, idx, findings, root, home_dir)
    return findings


_EXEC_STYLE = (
    "Not run: `{word}` is never run by ChatVMD. If the user needs it, show the "
    "command in a tcl code block so they can copy it and run it in the VMD "
    "console themselves."
)


def message_for(finding: Finding) -> str:
    """The model-facing error text for one finding (spec C1 wording)."""
    if finding.id == "cmd_quit":
        return "Not run: this would close the user's VMD session."
    if finding.id == "protected_path":
        return "Not run: ChatVMD never writes, deletes or sources %s." % finding.text
    if finding.id == "too_deep":
        return ("Not run: the command nests brackets or braces more than %d levels "
                "deep, too deep to check. Split it into smaller commands." % MAX_DEPTH)
    return _EXEC_STYLE.format(word=finding.word or finding.id)
```

- [ ] **Step 4: Add the module to the Python 3.9 import check**

In `tests/test_py39_compat.py`, add this entry inside the `RUNTIME_MODULES` list literal, in its alphabetical position (plan 01's `test_runtime_module_list_is_complete` fails until every runtime module is listed):

```python
    "vmd_ai_runtime.tcl_policy",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tcl_policy.py tests/test_py39_compat.py -q`
Expected: `30 passed` for `test_tcl_policy.py` (13 blocked + 9 allowed + 8 others) and the 3.9 import check passes (or skips when `/usr/bin/python3` is not 3.9), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+63 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/tcl_policy.py tests/test_tcl_policy.py tests/test_py39_compat.py
git commit -m "feat(policy): tcl_policy critical-Tcl accident guard (C1)

Static scan of every statement, every [...] (also inside quotes) and every
brace body for exec, socket, load, quit/exit, rename, unsafe interp, open
pipes and writes to protected paths. Pins the known gaps and a zero-finding
corpus of the 50 oracles and 4 skill scripts.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: P05-T05 — Enforce tcl_policy in the product bridge

**Files:**
- Create: `tests/test_tcl_policy_bridge.py`
- Modify: `runtime/vmd_ai_runtime/tool_bridge.py` (imports, module constant `_CHECKOUT_ROOT`, `execute_tool`, new `_policy_block`)
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` (`_recorder_record`, the version written in Task 3)

**Interfaces:**
- Consumes: `tcl_policy.check`, `tcl_policy.message_for` (P05-T04); `ClaudeToolLoop(..., options=LoopOptions(...))`, `RunContext(request_id, chat_id, on_event=None, messages_out=None)` (P02-T05); `tool.started`/`tool.finished` emission (P02-T08).
- Produces:
  - blocked result `{ok:false, executed:'no', blocked:[{id, word, text}], error}` (with every other key of the product result dict), returned before anything is pushed, for token and tokenless sessions alike
  - `_recorder_record` returns early when `result.get('blocked')`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tcl_policy_bridge.py`:

```python
"""C1 enforcement in the product bridge (runtime/vmd_ai_runtime/tool_bridge.py)."""
from __future__ import annotations

import threading
from unittest import mock

from helpers.bridge_harness import SESSION_ID, BridgeCall, make_bridge, make_session
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.recorder import RunRecorder

EXEC_MESSAGE = (
    "Not run: `exec` is never run by ChatVMD. If the user needs it, show the command in a "
    "tcl code block so they can copy it and run it in the VMD console themselves."
)


def test_blocked_never_queued(tmp_path):
    for authenticated in (True, False):
        bridge = make_bridge(make_session(tmp_path, authenticated=authenticated), pickup_timeout_s=0.3)
        call = BridgeCall(bridge, tool_input={"command": "set x [exec ls]"}, timeout=0.3)
        result = call.join(wait=2.0)
        assert call.queue.poll(0, 50)["events"] == [], "a blocked call must never reach VMD"
        assert result["executed"] == "no"
        assert result["blocked"][0]["id"] == "cmd_exec"


def test_blocked_result_shape(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.3)
    result = BridgeCall(bridge, tool_input={"command": "mol new a.pdb; exit"}).join()
    assert result["ok"] is False
    assert result["executed"] == "no"
    assert result["blocked"] == [{"id": "cmd_quit", "word": "exit", "text": "exit"}]
    assert result["error"] == "Not run: this would close the user's VMD session."
    exec_result = BridgeCall(bridge, tool_input={"command": "exec curl -O x.pdb"},
                             call_key="k0000000000e").join()
    assert exec_result["error"] == EXEC_MESSAGE
    assert exec_result["blocked"] == [{"id": "cmd_exec", "word": "exec", "text": "exec curl -O x.pdb"}]


def test_allowed_command_not_blocked(tmp_path):
    bridge = make_bridge(make_session(tmp_path))
    call = BridgeCall(bridge, tool_input={"command": 'puts "exit code"'})
    assert call.tool_start()["metadata"]["tool_input"]["command"] == 'puts "exit code"'
    call.cancel.set()
    assert call.join()["blocked"] is None


def test_recorder_untouched_when_blocked(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("blocked")
    blocked = {"ok": False, "output": "", "executed": "no", "error": EXEC_MESSAGE,
               "blocked": [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]}
    loop._recorder_record(tool_name="run_vmd_command", tool_input={"command": "exec ls"},
                          result=blocked, duration_ms=0.0)
    manifest = loop.recorder.read_manifest(tid)
    assert (manifest["turn_count"], manifest["failed_count"], manifest["successful_count"]) == (0, 0, 0)
    assert "exec ls" not in loop.recorder.read_transcript(tid)


def test_tool_started_and_finished_still_emitted(tmp_path):
    bridge = make_bridge(make_session(tmp_path), pickup_timeout_s=0.3)
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command", "input": {"command": "exec ls"}}]),
        ("I cannot run shell commands.", []),
    ])
    events, out = [], []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(result_format="structured"))
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="list files", system_prompt="s", tool_bridge=bridge, session_id=SESSION_ID,
                 session_queue=EventQueue(), cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                                on_event=events.append, messages_out=out))
    kinds = [(e.get("metadata") or {}).get("kind") for e in events]
    assert "tool.started" in kinds and "tool.finished" in kinds
    finished = [e for e in events if (e.get("metadata") or {}).get("kind") == "tool.finished"][0]["metadata"]
    assert finished["executed"] == "no"
    assert finished["blocked"] == [{"id": "cmd_exec", "word": "exec", "text": "exec ls"}]
    results = [b for msg in out if msg["role"] == "user" and isinstance(msg["content"], list)
               for b in msg["content"] if b.get("type") == "tool_result"]
    assert results and EXEC_MESSAGE in str(results[0]["content"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tcl_policy_bridge.py -q`
Expected: `4 failed, 1 passed` — `AssertionError: a blocked call must never reach VMD`, `assert 'VMD did not pick up the command (no reply within 0.3 s).' == "Not run: this would close the user's VMD session."`, `assert (1, 1, 0) == (0, 0, 0)` and a `tool.finished` with `blocked` None; `test_allowed_command_not_blocked` passes.

- [ ] **Step 3: Block before queueing — `runtime/vmd_ai_runtime/tool_bridge.py`**

(a) Add to the imports, before `from .image_scale import ...`:

```python
from . import tcl_policy
```

(b) Add after `_KEEP_FINISHED = 512`:

```python
_CHECKOUT_ROOT = str(Path(__file__).resolve().parents[2])
```

(c) Replace the whole `execute_tool` method with:

```python
    def execute_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        session_queue,          # EventQueue from sessions.py
        cancel_event: threading.Event,
        timeout: float = TOOL_TIMEOUT_SEC,
        call_key: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one VMD tool call through the plugin and return its result dict.

        C1: run_vmd_command is checked by tcl_policy first, for every session;
        a finding returns executed "no" and nothing is ever pushed to VMD.
        """
        sess = self._lookup(session_id)
        if tool_name == "run_vmd_command":
            blocked = self._policy_block(tool_input)
            if blocked is not None:
                return blocked
        if call_key and sess is not None and sess.authenticated:
            return self._execute_token(
                sess,
                session_id=str(session_id or ""),
                tool_call_id=str(tool_call_id or ""),
                tool_name=tool_name,
                tool_input=dict(tool_input or {}),
                session_queue=session_queue,
                cancel_event=cancel_event,
                call_key=str(call_key),
                request_id=str(request_id or ""),
            )
        return self._execute_legacy(
            sess,
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_input=tool_input,
            session_queue=session_queue,
            cancel_event=cancel_event,
            timeout=timeout,
            call_key=call_key,
        )
```

(d) Add this method directly after `_lookup`:

```python
    def _policy_block(self, tool_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """C1: the blocked result for a critical command, or None when allowed."""
        command = str((tool_input or {}).get("command") or "")
        findings = tcl_policy.check(command, checkout_root=_CHECKOUT_ROOT)
        if not findings:
            return None
        blocked = [{"id": f.id, "word": f.word, "text": f.text} for f in findings]
        logger.info("tcl_policy blocked %s", ",".join(b["id"] for b in blocked))
        result = _empty_result()
        result.update({
            "ok": False,
            "executed": "no",
            "error": tcl_policy.message_for(findings[0]),
            "blocked": blocked,
        })
        return result
```

- [ ] **Step 4: Keep blocked calls out of the recorder — `runtime/vmd_ai_runtime/claude_loop.py`**

In `_recorder_record`, directly after:

```python
        if self.recorder is None:
            return
```

insert:

```python
        if result.get("blocked"):
            # C1: a blocked call never reached VMD; it changes neither
            # transcript.tcl nor the manifest counts.
            return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tcl_policy_bridge.py tests/test_tool_bridge_ack.py tests/test_tool_bridge.py tests/test_benchmark_bridge_guard.py -q`
Expected: all passed (`5 passed` from the new file), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+68 passed`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/tool_bridge.py runtime/vmd_ai_runtime/claude_loop.py tests/test_tcl_policy_bridge.py
git commit -m "feat(bridge): enforce tcl_policy before queueing run_vmd_command (C1)

A finding returns executed 'no' with blocked [{id, word, text}] and the C1
message, for token and tokenless sessions; nothing reaches VMD and the
recorder ignores the call. Benchmark bridges never call tcl_policy.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 6: P05-T06 — Structured failure text and recorder applied prefix (C3)

**Files:**
- Create: `tests/test_result_format.py`
- Create: `tests/test_recorder_partial.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py:1304-1356` (`_build_tool_result_block` and a new `_structured_summary` above it), the `_build_tool_result_block(` call inside `run()` (today at 1860-1866), a new method `ClaudeToolLoop._result_format`, and `_recorder_record` (the Task 5 version)
- Modify: `runtime/vmd_ai_runtime/recorder/run.py:214-244` (`record_vmd_command`), new method `_format_partial_block`

**Interfaces:**
- Consumes: statements mapping (P05-T02) — the result dict's `statements {total, applied, failed{index, text, error_info}}`, `applied_text`, `executed`; `LoopOptions.result_format` (P02-T05); `helpers.tcl.requires_tcl`, `helpers.tcl.run_tcl` (P01-T03).
- Produces:
  - `_build_tool_result_block(tool_use_id, result, include_image, result_format: str = 'legacy')` (the new keyword is the last parameter)
  - `_structured_summary(result: Dict[str, Any]) -> str`
  - `ClaudeToolLoop._result_format() -> str` (`options.result_format`, or `'legacy'` when options is None)
  - `RunRecorder.record_vmd_command(command, *, ok, rationale='', duration_ms=0.0, applied_text=None, failed_index=None, total=None, error=None)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_result_format.py`:

```python
"""C3: structured model-facing failure text (result_format) and executed status."""
from __future__ import annotations

import threading
from unittest import mock

from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext, _build_tool_result_block
from vmd_ai_runtime.events import EventQueue

ERROR_INFO = 'invalid command name "bogus"\n    while executing\n"bogus"'
FAILED = {
    "ok": False, "output": "", "executed": "yes", "error": 'invalid command name "bogus"',
    "statements": {"total": 4, "applied": 2,
                   "failed": {"index": 3, "text": "bogus", "error_info": ERROR_INFO}},
}
PRECHECK = {
    "ok": False, "output": "", "executed": "no",
    "error": "Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)",
    "statements": {"total": 2, "applied": 0,
                   "failed": {"index": 2, "text": "foreach a {1 2} {", "error_info": ""}},
}


def _text(result, fmt="structured"):
    return _build_tool_result_block("call_k1", result, False, result_format=fmt)["content"]


def test_structured_runtime_error_text():
    block = _build_tool_result_block("call_k1", FAILED, False, result_format="structured")
    assert block["is_error"] is True
    assert block["content"] == (
        "Failed at statement 3 of 4: `bogus`\n"
        'Error: invalid command name "bogus"\n'
        + ERROR_INFO + "\n"
        "Statements 1–2 were applied and are still in effect; do not re-run them."
    )


def test_structured_applied_counts_wording():
    one = dict(FAILED, statements={"total": 3, "applied": 1,
                                   "failed": {"index": 2, "text": "bogus", "error_info": ""}})
    assert _text(one).endswith("Statement 1 was applied and is still in effect; do not re-run it.")
    none = dict(FAILED, statements={"total": 2, "applied": 0,
                                    "failed": {"index": 1, "text": "bogus", "error_info": ""}})
    assert _text(none).endswith("No statements were applied.")
    assert "Output before the error:\n12 atoms" in _text(dict(FAILED, output="12 atoms"))


def test_precheck_text():
    block = _build_tool_result_block("call_k2", PRECHECK, False, result_format="structured")
    assert block["content"] == (
        "Nothing was run: statement 2 of 2 is incomplete (unbalanced braces, brackets or quotes)\n"
        "Incomplete statement: `foreach a {1 2} {`"
    )
    assert block["is_error"] is True


def test_not_executed_texts():
    assert _text({"ok": False, "executed": "no", "error": "cancelled"}) == "not executed: request stopped"
    assert _text({"ok": False, "executed": "no", "error": "not executed: loop guard"}) == "not executed: loop guard"
    assert _text({"ok": False, "executed": "no",
                  "error": "VMD did not pick up the command (no reply within 45 s)."}) == (
        "not executed: VMD did not pick up the command (no reply within 45 s).")
    assert _text({"ok": False, "executed": "unknown",
                  "error": "stopped while running; outcome unknown"}) == "stopped while running; outcome unknown"
    blocked = {"ok": False, "executed": "no", "error": "Not run: this would close the user's VMD session.",
               "blocked": [{"id": "cmd_quit", "word": "exit", "text": "exit"}]}
    assert _text(blocked) == "Not run: this would close the user's VMD session."


def test_legacy_unchanged():
    assert _text(FAILED, "legacy") == 'Error: invalid command name "bogus"'
    assert _build_tool_result_block("c", FAILED, False)["content"] == 'Error: invalid command name "bogus"'
    assert _build_tool_result_block("c", {"ok": True, "output": ""}, False)["content"] == "Command executed successfully."
    assert _build_tool_result_block("c", {"ok": False}, False)["content"] == "Command failed with unknown error."
    assert _build_tool_result_block("c", {"ok": False, "executed": "no", "error": "cancelled"}, False)["content"] == "Error: cancelled"


def test_structured_success_same_as_legacy():
    ok = {"ok": True, "output": "0 1 2", "executed": "yes",
          "statements": {"total": 1, "applied": 1, "failed": None}}
    assert _build_tool_result_block("c", ok, False, result_format="structured") == _build_tool_result_block("c", ok, False)


class _PrecheckBridge:
    """Strict six keywords; returns the executor's C3 pre-check refusal."""

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        return dict(PRECHECK)


def test_executed_no_survives_to_tool_result_and_finished():
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command",
               "input": {"command": "mol list\nforeach a {1 2} {"}}]),
        ("I will fix the braces.", []),
    ])
    events, out = [], []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(result_format="structured"))
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="loop", system_prompt="s", tool_bridge=_PrecheckBridge(), session_id="s",
                 session_queue=EventQueue(), cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                                on_event=events.append, messages_out=out))
    finished = [e for e in events if (e.get("metadata") or {}).get("kind") == "tool.finished"]
    assert finished[0]["metadata"]["executed"] == "no"
    results = [b for msg in out if msg["role"] == "user" and isinstance(msg["content"], list)
               for b in msg["content"] if b.get("type") == "tool_result"]
    assert results[0]["content"].startswith("Nothing was run: statement 2 of 2 is incomplete")
    assert "Incomplete statement: `foreach a {1 2} {`" in results[0]["content"]
```

Create `tests/test_recorder_partial.py`:

```python
"""C3: the recorder writes the applied prefix and comments out the rest."""
from __future__ import annotations

from helpers.tcl import requires_tcl, run_tcl
from vmd_ai_runtime.claude_loop import ClaudeToolLoop
from vmd_ai_runtime.recorder import RunRecorder

COMMAND = "mol new a.pdb\nmol delrep 0 top\nmol_color x {\n}\nputs done \\"
APPLIED = "mol new a.pdb\nmol delrep 0 top\n"
ERROR = 'invalid command name "mol_color"\n    while executing\n"mol_color x {\n}"'


def _partial(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("partial")
    rec.record_vmd_command(COMMAND, ok=False, rationale="r", duration_ms=5,
                           applied_text=APPLIED, failed_index=3, total=4, error=ERROR)
    rec.end_task()
    return rec, tid


def test_recorder_prefix_and_commented_rest(tmp_path):
    rec, tid = _partial(tmp_path)
    text = rec.read_transcript(tid)
    assert (
        "\nmol new a.pdb\nmol delrep 0 top\n"
        "# statement 3 of 4 failed (invalid command name \"mol_color\"); "
        "statements 3–4 were not applied:\n"
        "# mol_color x {\n# }\n# puts done \\ \n"
    ) in text
    manifest = rec.read_manifest(tid)
    assert (manifest["failed_count"], manifest["successful_count"], manifest["turn_count"]) == (1, 0, 1)


@requires_tcl()
def test_partial_transcript_parses_in_tclsh(tmp_path):
    rec, tid = _partial(tmp_path)
    transcript = rec.runs_root / tid / "transcript.tcl"
    proc = run_tcl(
        "set CALLS {}\n"
        "proc mol {args} {global CALLS; lappend CALLS $args}\n"
        "proc unknown {args} {error \"unexpected: $args\"}\n"
        "source {%s}\n"
        "puts $CALLS\n" % transcript.as_posix()
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "{new a.pdb} {delrep 0 top}"


def test_failed_without_applied_text_writes_nothing(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("f")
    rec.record_vmd_command("bogus", ok=False)
    rec.record_vmd_command("mol new a.pdb\nbogus", ok=False, applied_text="",
                           failed_index=1, total=2, error="x")
    rec.end_task()
    text = rec.read_transcript(tid)
    assert "bogus" not in text and "mol new a.pdb" not in text
    assert rec.read_manifest(tid)["failed_count"] == 2


def test_loop_maps_statements_to_recorder(tmp_path):
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    loop.recorder = RunRecorder.for_cwd(tmp_path)
    tid = loop.recorder.start_task("partial")
    loop._recorder_record(
        tool_name="run_vmd_command",
        tool_input={"command": COMMAND, "rationale": "r"},
        result={"ok": False, "output": "", "error": ERROR, "executed": "yes",
                "statements": {"total": 4, "applied": 2,
                               "failed": {"index": 3, "text": "mol_color x {\n}", "error_info": ERROR}},
                "applied_text": APPLIED},
        duration_ms=5.0,
    )
    text = loop.recorder.read_transcript(tid)
    assert "\nmol delrep 0 top\n# statement 3 of 4 failed" in text
    assert "# mol_color x {" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_result_format.py tests/test_recorder_partial.py -q`
Expected: `11 failed` (`10 failed, 1 skipped` without an 8.6 tclsh) — `TypeError: _build_tool_result_block() got an unexpected keyword argument 'result_format'` (also in `test_legacy_unchanged`, whose first assertion passes `result_format="legacy"`), `TypeError: RunRecorder.record_vmd_command() got an unexpected keyword argument 'applied_text'`, `test_loop_maps_statements_to_recorder` fails because today's `_recorder_record` writes nothing for a failed call, and `test_executed_no_survives_to_tool_result_and_finished` fails on `assert 'Error: Nothing was run: …'.startswith('Nothing was run: …')`.

- [ ] **Step 3: Structured text in `runtime/vmd_ai_runtime/claude_loop.py`**

(a) Add this function directly above `def _build_tool_result_block(`:

```python
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
```

(b) In `_build_tool_result_block`, add `result_format: str = "legacy",` as the last parameter of the signature, and replace:

```python
    if ok:
        summary = output if output else "Command executed successfully."
    else:
        summary = f"Error: {error}" if error else "Command failed with unknown error."
```

with:

```python
    if result_format == "structured":
        summary = _structured_summary(result)
    elif ok:
        summary = output if output else "Command executed successfully."
    else:
        summary = f"Error: {error}" if error else "Command failed with unknown error."
```

(c) Add this method to `ClaudeToolLoop`, directly after `_tools_for_turn`:

```python
    def _result_format(self) -> str:
        """C3: "structured" for product runs, "legacy" (today's text) otherwise."""
        options = getattr(self, "options", None)
        if options is None:
            return "legacy"
        return str(getattr(options, "result_format", "legacy") or "legacy")
```

(d) In `run()`, add the keyword argument `result_format=self._result_format(),` to the `_build_tool_result_block(` call (keep its other arguments exactly as they are).

(e) In `_recorder_record`, replace the `run_vmd_command` branch:

```python
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
```

with:

```python
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
```

- [ ] **Step 4: Partial writes in `runtime/vmd_ai_runtime/recorder/run.py`**

(a) Replace the whole `record_vmd_command` method with:

```python
    def record_vmd_command(
        self,
        command: str,
        *,
        ok: bool,
        rationale: str = "",
        duration_ms: float = 0.0,
        applied_text: Optional[str] = None,
        failed_index: Optional[int] = None,
        total: Optional[int] = None,
        error: Optional[str] = None,
    ) -> Optional[int]:
        """Record one ``run_vmd_command`` tool call.

        Returns the 1-based turn number on success, ``None`` if no task
        is active or the call failed (failed commands are counted in
        the manifest and never written as runnable Tcl).

        A partial failure (C3: ``ok=False`` with a non-empty
        ``applied_text``, the exact source of statements 1..applied)
        writes that applied prefix, which is still in effect in VMD,
        followed by a comment naming the failed statement and the
        unapplied rest commented out line by line. Without
        ``applied_text`` a failed call writes nothing, as before.
        """
        if self._current is None:
            return None
        self._current.turn_count += 1
        turn_n = self._current.turn_count
        self._current.last_activity_at = time.time()

        if not ok:
            self._current.failed_count += 1
            if applied_text:
                block = self._format_partial_block(
                    turn_n, command, rationale, duration_ms,
                    applied_text, failed_index, total, error,
                )
                with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
                    f.write(block)
            self._flush_manifest(status="active")
            return None

        self._current.successful_count += 1
        block = self._format_command_block(turn_n, command, rationale, duration_ms)
        with (self._current.dir / "transcript.tcl").open("a", encoding="utf-8") as f:
            f.write(block)
        self._flush_manifest(status="active")
        return turn_n
```

(b) Add this method directly before `_format_snapshot_block`:

```python
    def _format_partial_block(
        self,
        turn_n: int,
        command: str,
        rationale: str,
        duration_ms: float,
        applied_text: str,
        failed_index: Optional[int],
        total: Optional[int],
        error: Optional[str],
    ) -> str:
        """C3: the applied prefix, then the failed/unapplied rest as comments
        (the same rule as the panel's Save .tcl export)."""
        ts = _utc_iso(time.time())
        first_error = (str(error or "").strip().splitlines() or ["error"])[0]
        idx = int(failed_index or 0)
        tot = int(total or 0)
        if idx and tot and idx < tot:
            span = f"statements {idx}–{tot} were not applied"
        elif idx:
            span = f"statement {idx} was not applied"
        else:
            span = "the rest was not applied"
        out: list[str] = []
        out.append("")
        out.append(f"# --- turn {turn_n:02d} | {ts} | {duration_ms:.0f}ms | partial ---")
        if rationale:
            for r_line in rationale.splitlines():
                out.append(f"# rationale : {r_line}")
        out.append("")
        out.append(applied_text.rstrip())
        out.append(f"# statement {idx} of {tot} failed ({first_error}); {span}:")
        rest = command[len(applied_text):] if command.startswith(applied_text) else command
        for r_line in rest.strip("\n").splitlines():
            # A trailing odd backslash would continue the comment onto the
            # next line; a following space stops that.
            if (len(r_line) - len(r_line.rstrip("\\"))) % 2 == 1:
                r_line += " "
            out.append(f"# {r_line}")
        out.append("")
        return "\n".join(out)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_result_format.py tests/test_recorder_partial.py tests/test_recorder.py tests/test_claude_loop_recorder.py tests/test_benchmark_golden_requests.py -q`
Expected: all passed (`7 passed` + `4 passed` from the new files; `test_partial_transcript_parses_in_tclsh` may show as skipped without an 8.6 tclsh), 0 failed; the S7 goldens are unchanged.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+79 passed` (or one fewer plus `1 skipped` without Tcl 8.6), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py runtime/vmd_ai_runtime/recorder/run.py tests/test_result_format.py tests/test_recorder_partial.py
git commit -m "feat(loop): structured failure text and recorder applied prefix (C3)

result_format 'structured' (product only) tells the model which statement
failed and which ones are already applied, or that nothing ran; 'legacy'
keeps today's text for options=None. The recorder writes the applied
prefix and comments out the unapplied rest.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: P05-T07 — Full output on disk and the model-facing cut (C5)

**Files:**
- Create: `tests/test_tool_output_disk.py`
- Modify: `runtime/vmd_ai_runtime/tool_bridge.py` (imports; constants after `_CHECKOUT_ROOT`; `_finalize`; the end of the `try` block in `_execute_legacy`; new helpers after `_write_save_path`)
- Modify (only if Task 0 printed `STUB_KEEPS_NOTE False`): `runtime/vmd_ai_runtime/conversation.py` (append a wrapper; see Step 5)

**Interfaces:**
- Consumes: `conversation.stub_tool_result_text(text: str, head: int = 300) -> str` (P03-T02); `post_result`/`on_late_result` (P05-T02); `tool.finished` copying `output`, `truncated`, `output_path` and `output_bytes` from the result dict (P02-T08 `_tool_finished_meta`); `ClaudeToolLoop(..., options=LoopOptions())`, `RunContext` (P02-T05).
- Produces:
  - `tool_bridge.MODEL_OUTPUT_CAP = 6000; MODEL_HEAD_CHARS = 3000; MODEL_TAIL_CHARS = 2500`
  - `tool_bridge.cut_for_model(text: str, *, head: int = 3000, tail: int = 2500) -> str` — with one added keyword `note: str = ""`, the line placed between head and tail (see Deviations)
  - `tool_bridge.truncation_note(n_lines: int, n_bytes: int, path: str, executor_cut: bool) -> str`
  - result keys `output_path` (absolute path or None), `output_bytes` (size of the full text), `truncated` (True whenever the model's text was cut or the executor cut it), for every session whose chat directory is known; late results are cut the same way

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_output_disk.py`:

```python
"""C5: full tool output on disk, head/tail cut for the model."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest import mock

from helpers.bridge_harness import CHAT_ID, SESSION_ID, BridgeCall, make_bridge, make_session
from vmd_ai_runtime import tool_bridge as tb
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.conversation import stub_tool_result_text
from vmd_ai_runtime.events import EventQueue


def _run(bridge, output, **extra):
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    params = {"call_key": call.call_key, "ok": True, "output": output, "error": ""}
    params.update(extra)
    bridge.post_result(SESSION_ID, params)
    return call.join()


def test_20000_lines_saved_and_cut(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    full = "\n".join("residue %05d rmsf %.3f" % (i, i * 0.001) for i in range(20000))
    result = _run(bridge, full)
    path = session.chat_dir / "outputs" / "k00000000001.txt"
    assert path.read_bytes() == full.encode("utf-8")
    assert result["output_path"] == str(path)
    assert result["output_bytes"] == len(full.encode("utf-8"))
    assert result["truncated"] is True
    text = result["output"]
    note = tb.truncation_note(20000, len(full.encode("utf-8")), str(path), False)
    assert note in text
    assert len(text) <= tb.MODEL_OUTPUT_CAP + len(note) + 2
    assert text.startswith("residue 00000 rmsf 0.000\n")
    assert text.endswith("residue 19999 rmsf 19.999")
    assert note.startswith("[output truncated: 20000 lines, ")
    assert ("Full text: %s. Don't print it again: compute what you need (measure, a narrower "
            "selection), or read a slice of that file with Tcl.]" % path) in note


def test_under_6000_no_file(tmp_path):
    session = make_session(tmp_path)
    result = _run(make_bridge(session), "y" * 6000)
    assert result["output"] == "y" * 6000
    assert result["output_path"] is None
    assert result["output_bytes"] == 6000
    assert result["truncated"] is False
    assert not (session.chat_dir / "outputs").exists()


def test_200kb_single_line(tmp_path):
    session = make_session(tmp_path)
    one_line = "{1.0 2.0 3.0}" * 16000
    result = _run(make_bridge(session), one_line)
    note = tb.truncation_note(1, len(one_line.encode("utf-8")), result["output_path"], False)
    assert note in result["output"]
    assert len(result["output"]) <= tb.MODEL_OUTPUT_CAP + len(note) + 2
    assert result["output"].startswith("{1.0 2.0 3.0}")
    assert result["output"].endswith("3.0}")
    assert Path(result["output_path"]).read_text() == one_line
    nospace = "x" * 200_000
    assert tb.cut_for_model(nospace, note="NOTE") == "x" * 3000 + "\nNOTE\n" + "x" * 2500
    undecodable = "a\udc80" * 5000
    bad = _run(make_bridge(make_session(tmp_path / "b")), undecodable)
    assert Path(bad["output_path"]).read_bytes().count(b"?") == 5000
    bad["output"].encode("utf-8")  # the model's copy is valid UTF-8


def test_cut_for_model_boundaries():
    text = "\n".join("line %04d" % i for i in range(2000))
    cut = tb.cut_for_model(text, note="N")
    head, tail = cut.split("\nN\n")
    assert len(head) <= 3000 and len(tail) <= 2500
    assert text.startswith(head) and text.endswith(tail)
    assert head.endswith(tuple("0123456789")) and tail.startswith("line ")
    assert tb.cut_for_model("short", note="N") == "short"


def test_executor_truncated_note(tmp_path):
    session = make_session(tmp_path)
    posted = "z" * 1_048_576 + "\n[executor limit: output cut at 1 MB]"
    result = _run(make_bridge(session), posted, truncated=True)
    path = session.chat_dir / "outputs" / "k00000000001.txt"
    assert "Saved text (cut at 1 MB in VMD): %s." % path in result["output"]
    assert "Full text:" not in result["output"]
    assert result["truncated"] is True


def test_late_results_cut_too(tmp_path):
    session = make_session(tmp_path)
    bridge = make_bridge(session, cancel_grace_s=0.1)
    seen = []
    bridge.on_late_result = lambda sid, key, info: seen.append(info)
    call = BridgeCall(bridge)
    call.tool_start()
    bridge.ack(SESSION_ID, call.call_key)
    call.cancel.set()
    assert call.join()["executed"] == "unknown"
    big = "\n".join(str(i) for i in range(20000))
    bridge.post_result(SESSION_ID, {"call_key": call.call_key, "ok": True, "output": big, "error": ""})
    assert len(seen) == 1
    info = seen[0]
    assert info["output_path"] == str(session.chat_dir / "outputs" / "k00000000001.txt")
    assert len(info["output"]) < 7000 and info["truncated"] is True


def test_tokenless_output_cut_when_chat_known(tmp_path):
    session = make_session(tmp_path, authenticated=False)
    bridge = make_bridge(session)
    call = BridgeCall(bridge, timeout=3)
    call.tool_start()
    bridge.resolve("tc_1", {"ok": True, "output": "w\n" * 5000, "error": ""})
    result = call.join()
    assert result["output_path"] == str(session.chat_dir / "outputs" / "k00000000001.txt")
    assert result["truncated"] is True


def test_compaction_stub_keeps_path(tmp_path):
    session = make_session(tmp_path)
    full = "\n".join("frame %d rmsd %.2f" % (i, i / 100.0) for i in range(20000))
    result = _run(make_bridge(session), full)
    stub = stub_tool_result_text(result["output"])
    assert result["output_path"] in stub.rstrip().splitlines()[-1]
    assert len(stub) < 1000


def test_tool_finished_carries_output_path(tmp_path):
    # C5 test: tool.finished carries output_path and output_bytes (plan 02's
    # _tool_finished_meta copies them from the bridge result).
    session = make_session(tmp_path)
    bridge = make_bridge(session)
    queue = EventQueue()
    full = "\n".join("residue %05d" % i for i in range(20000))

    def _plugin():
        # Stand-in executor: pick up the tool_start, ack it, post the output.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            starts = [e for e in queue.poll(0, 50)["events"] if e["role"] == "tool_start"]
            if starts:
                key = starts[0]["metadata"]["call_key"]
                bridge.ack(SESSION_ID, key)
                bridge.post_result(SESSION_ID, {"call_key": key, "ok": True, "output": full, "error": ""})
                return
            time.sleep(0.01)

    threading.Thread(target=_plugin, daemon=True).start()
    turns = iter([
        ("", [{"type": "tool_use", "id": "t1", "name": "run_vmd_command",
               "input": {"command": "puts $rmsf"}}]),
        ("done", []),
    ])
    events = []
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions())
    with mock.patch.object(ClaudeToolLoop, "_call",
                           new=lambda self, m, s, on_text, should_cancel: next(turns)):
        loop.run(prompt="p", system_prompt="s", tool_bridge=bridge, session_id=SESSION_ID,
                 session_queue=queue, cancel_event=threading.Event(), on_chunk=lambda t: None,
                 ctx=RunContext(request_id="req_000000000001", chat_id=CHAT_ID,
                                on_event=events.append))
    finished = [e["metadata"] for e in events
                if (e.get("metadata") or {}).get("kind") == "tool.finished"][0]
    path = session.chat_dir / "outputs" / ("%s.txt" % finished["call_key"])
    assert finished["output_path"] == str(path)
    assert finished["output_bytes"] == len(full.encode("utf-8"))
    assert finished["truncated"] is True
    assert "Full text: %s." % path in finished["output"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_output_disk.py -q`
Expected: `8 failed, 1 passed` — `FileNotFoundError: ... outputs/k00000000001.txt`, `AttributeError: module 'vmd_ai_runtime.tool_bridge' has no attribute 'truncation_note'`, `AttributeError: ... 'cut_for_model'`, `KeyError: 'output_path'` (tokenless result dict) and `output_path` `None` in `tool.finished`; only `test_under_6000_no_file` passes (Task 2's `_finalize` already fills `output_bytes`, `output_path: None` and `truncated: False`).

- [ ] **Step 3: Save and cut in `runtime/vmd_ai_runtime/tool_bridge.py`**

(a) Add `import re` to the imports (next to `import os`).

(b) Add after `_CHECKOUT_ROOT = ...`:

```python
MODEL_OUTPUT_CAP = 6000
MODEL_HEAD_CHARS = 3000
MODEL_TAIL_CHARS = 2500
```

(c) In `_finalize`, directly after:

```python
        if pending.tool_name == "capture_vmd_snapshot":
            self._attach_snapshot(pending, raw, result)
```

insert:

```python
        if pending.chat_dir is not None:
            _cut_output_in_place(result, pending.chat_dir, pending.call_key)
```

(d) In `_execute_legacy`, directly before the `return result` that ends the `try:` block (right after the snapshot block), insert:

```python
            if sess is not None and sess.chat_dir is not None:
                # C5: the model sees head + note + tail; the full text is saved.
                _cut_output_in_place(result, sess.chat_dir, str(call_key or tool_call_id))
```

(e) Add these helpers directly after `_write_save_path`:

```python
def truncation_note(n_lines: int, n_bytes: int, path: str, executor_cut: bool) -> str:
    """The C5 line that joins head and tail (names the saved file)."""
    kb = max(1, int(round(n_bytes / 1024.0)))
    where = ("Saved text (cut at 1 MB in VMD): %s" % path) if executor_cut else ("Full text: %s" % path)
    return (
        "[output truncated: %d lines, %d KB. %s. Don't print it again: compute what you "
        "need (measure, a narrower selection), or read a slice of that file with Tcl.]"
        % (n_lines, kb, where)
    )


def _cut_head(window: str) -> str:
    """Cut the head window at its last newline, else last whitespace, else exactly."""
    pos = window.rfind("\n")
    if pos <= 0:
        pos = max(window.rfind(" "), window.rfind("\t"))
    return window[:pos] if pos > 0 else window


def _cut_tail(window: str) -> str:
    """Start the tail window after its first newline, else first whitespace, else exactly."""
    pos = window.find("\n")
    if 0 <= pos < len(window) - 1:
        return window[pos + 1:]
    candidates = [p for p in (window.find(" "), window.find("\t")) if p >= 0]
    if candidates and min(candidates) < len(window) - 1:
        return window[min(candidates) + 1:]
    return window


def cut_for_model(text: str, *, head: int = MODEL_HEAD_CHARS, tail: int = MODEL_TAIL_CHARS,
                  note: str = "") -> str:
    """Keep the first ``head`` and last ``tail`` characters, each cut at a line
    (else word) boundary inside its window, joined by ``note`` (C5)."""
    if len(text) <= head + tail:
        return text
    head_part = _cut_head(text[:head])
    tail_part = _cut_tail(text[-tail:])
    return head_part + "\n" + note + "\n" + tail_part


def _cut_output_in_place(result: Dict[str, Any], chat_dir: Path, call_key: str) -> None:
    """C5: save output over 6000 chars to outputs/<call_key>.txt and cut the
    model's copy to head + note + tail. Lone surrogates (undecodable text that
    reached the JSON) become '?' so the text is always valid UTF-8."""
    data = str(result.get("output") or "").encode("utf-8", "replace")
    output = data.decode("utf-8")
    result["output"] = output
    result["output_bytes"] = len(data)
    if len(output) <= MODEL_OUTPUT_CAP:
        return
    safe_key = re.sub(r"[^A-Za-z0-9_\-]", "_", str(call_key or "call"))
    outputs = Path(chat_dir) / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / ("%s.txt" % safe_key)
    path.write_bytes(data)
    executor_cut = bool(result.get("truncated"))
    note = truncation_note(output.count("\n") + 1, len(data), str(path), executor_cut)
    result["output"] = cut_for_model(output, note=note)
    result["output_path"] = str(path)
    result["truncated"] = True
```

- [ ] **Step 4: Run the tests**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_output_disk.py -q`
Expected: `9 passed`. If only `test_compaction_stub_keeps_path` fails (Task 0 printed `STUB_KEEPS_NOTE False`), do Step 5; otherwise skip it.

- [ ] **Step 5 (only if `test_compaction_stub_keeps_path` failed): keep the note in compaction stubs**

Plan 03's draft `stub_tool_result_text` already keeps the note: its `split_output_section` starts the tail at the first line beginning with a `TAIL_MARKERS` prefix (`[output truncated:` is one), which is exactly where C5 puts the note, so Task 0 is expected to print `STUB_KEEPS_NOTE True` and this step is skipped. It is the fallback for a merged plan 03 whose builder only looks at the end of the text. In that case append this to the end of `runtime/vmd_ai_runtime/conversation.py` (and add `import re` to its imports if it is missing):

```python
# --- C5 (plan 05): an in-run compaction stub keeps the output-path note as its
# last line, wherever the note sits in the cut text (between head and tail). ---
_OUTPUT_NOTE_RE = re.compile(r"^\[output truncated: .*\]$", re.MULTILINE)
_stub_without_note = stub_tool_result_text


def stub_tool_result_text(text: str, head: int = 300) -> str:  # noqa: F811
    stub = _stub_without_note(text, head)
    match = _OUTPUT_NOTE_RE.search(text or "")
    if match and not stub.rstrip().endswith(match.group(0)):
        stub = stub.rstrip("\n") + "\n" + match.group(0)
    return stub
```

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_tool_output_disk.py tests/test_conversation_prior.py tests/test_compact_in_run.py -q`
Expected: all passed.

- [ ] **Step 6: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+88 passed` (one fewer plus `1 skipped` without Tcl 8.6), 0 failed.

- [ ] **Step 7: Commit**

```bash
git add runtime/vmd_ai_runtime/tool_bridge.py tests/test_tool_output_disk.py
git add -u runtime/vmd_ai_runtime/conversation.py
git commit -m "feat(bridge): keep full tool output on disk, cut the model's copy (C5)

Output over 6000 characters is saved to chats/<id>/outputs/<call_key>.txt
and the model gets the first 3000 and last 2500 characters joined by a note
naming the file. Late results are cut the same way; undecodable text is
made valid UTF-8. SubprocessVmdBridge is untouched.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 8: P05-T08 — loop_guard detector (C4)

**Files:**
- Create: `runtime/vmd_ai_runtime/loop_guard.py`
- Create: `tests/test_loop_guard.py`
- Modify: `tests/test_py39_compat.py` (append one entry to `RUNTIME_MODULES`)

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `class loop_guard.LoopGuard()` with `.observe(tool_name: str, tool_input: Dict[str, Any], result: Dict[str, Any]) -> Optional[str]` (`None|'nudge'|'stop'`) and `.streak -> int`
  - `loop_guard.signature(tool_name, tool_input, result) -> Tuple` = `(tool name, json.dumps(input without rationale, command whitespace collapsed, sort_keys=True), ok, error[:200])`
  - `loop_guard.NUDGE_TEXT_TEMPLATE` (a `str.format` template with `{n}`)
  - constants `FAILURE_LIMIT = 3`, `SUCCESS_LIMIT = 4`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_loop_guard.py`:

```python
"""C4: the repeat detector (runtime/vmd_ai_runtime/loop_guard.py)."""
from __future__ import annotations

from vmd_ai_runtime.loop_guard import NUDGE_TEXT_TEMPLATE, LoopGuard, signature

FAIL = {"ok": False, "output": "", "error": "invalid command name \"mol_color\""}
OK = {"ok": True, "output": "0 1 2", "error": ""}


def cmd(text, rationale="r"):
    return {"command": text, "rationale": rationale}


def test_three_different_mol_never_trigger():
    g = LoopGuard()
    for text in ("mol new a.pdb", "mol delrep 0 top", "mol addrep top"):
        assert g.observe("run_vmd_command", cmd(text), FAIL) is None
    assert g.streak == 1


def test_three_identical_failures_nudge_fourth_stops():
    g = LoopGuard()
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "nudge"
    assert g.streak == 3
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "stop"


def test_four_identical_successes_nudge():
    g = LoopGuard()
    verdicts = [g.observe("run_vmd_command", cmd("molinfo list"), OK) for _ in range(5)]
    assert verdicts == [None, None, None, "nudge", "stop"]


def test_snapshot_exempt_from_b():
    g = LoopGuard()
    snap = {"ok": True, "output": "Snapshot rendered", "error": ""}
    verdicts = [g.observe("capture_vmd_snapshot", {"purpose": "check"}, snap) for _ in range(6)]
    assert verdicts == [None] * 6
    bad = {"ok": False, "output": "", "error": "render failed"}
    verdicts = [g.observe("capture_vmd_snapshot", {"purpose": "check"}, bad) for _ in range(3)]
    assert verdicts == [None, None, "nudge"]


def test_different_call_resets():
    g = LoopGuard()
    g.observe("run_vmd_command", cmd("mol_color x"), FAIL)
    g.observe("run_vmd_command", cmd("mol_color x"), FAIL)
    assert g.observe("run_vmd_command", cmd("mol new a.pdb"), OK) is None
    assert g.streak == 1
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) is None
    assert g.observe("run_vmd_command", cmd("mol_color x"), FAIL) == "nudge"


def test_same_command_different_output_resets_b():
    g = LoopGuard()
    for _ in range(3):
        g.observe("run_vmd_command", cmd("molinfo top"), OK)
    other = {"ok": True, "output": "3", "error": ""}
    assert g.observe("run_vmd_command", cmd("molinfo top"), other) is None
    assert g.streak == 1


def test_blocked_exec_curl_triggers_a():
    blocked = {
        "ok": False, "output": "", "executed": "no",
        "error": "Not run: `exec` is never run by ChatVMD. If the user needs it, show the "
                 "command in a tcl code block so they can copy it and run it in the VMD "
                 "console themselves.",
        "blocked": [{"id": "cmd_exec", "word": "exec", "text": "exec curl -O x"}],
    }
    g = LoopGuard()
    got = [g.observe("run_vmd_command",
                     cmd("exec curl -O https://files.rcsb.org/download/1hck.pdb"), blocked)
           for _ in range(3)]
    assert got == [None, None, "nudge"]


def test_signature_ignores_rationale_whitespace():
    a = signature("run_vmd_command",
                  {"command": "mol new  a.pdb\n\tmol delrep 0 top", "rationale": "x"}, FAIL)
    b = signature("run_vmd_command",
                  {"command": "mol new a.pdb mol delrep 0 top ", "rationale": "other"}, FAIL)
    assert a == b
    g = LoopGuard()
    g.observe("run_vmd_command", {"command": "mol_color  x", "rationale": "one"}, FAIL)
    g.observe("run_vmd_command", {"command": "mol_color x\n", "rationale": "two"}, FAIL)
    assert g.observe("run_vmd_command", {"command": " mol_color x"}, FAIL) == "nudge"


def test_signature_uses_first_200_error_chars():
    e1 = dict(FAIL, error="E" * 200 + "tail-one")
    e2 = dict(FAIL, error="E" * 200 + "tail-two")
    assert signature("t", {}, e1) == signature("t", {}, e2)


def test_nudge_text():
    assert NUDGE_TEXT_TEMPLATE.format(n=3) == (
        "Loop check: this exact call has now run 3 times with the same result. "
        "Do not repeat it; change the command, or stop and explain the problem to the user."
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_loop_guard.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'vmd_ai_runtime.loop_guard'`.

- [ ] **Step 3: Write `runtime/vmd_ai_runtime/loop_guard.py`**

```python
"""
loop_guard.py - stop a request when the model repeats one call (spec C4).

Adapted (not ported) from PyMolAI's ``modules/pymol/ai/doom_loop_detector.py``.
That file's command-family rule keys on the tool name for every tool except
``run_pymol_command``, so it would fire after any three ``run_vmd_command``
calls; round 1 keeps only the exact-repeat triggers:

  (a) the same signature with ``ok: false`` 3 times in a row;
  (b) the same signature with ``ok: true`` and the same first 200 characters
      of output 4 times in a row (``capture_vmd_snapshot`` is exempt from b).

The first trigger returns ``"nudge"``; the streak is NOT reset, so the next
identical call returns ``"stop"``. A call with a different signature resets
the streak. Stdlib-only and Python 3.9-compatible.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

FAILURE_LIMIT = 3
SUCCESS_LIMIT = 4
SNAPSHOT_TOOL = "capture_vmd_snapshot"

NUDGE_TEXT_TEMPLATE = (
    "Loop check: this exact call has now run {n} times with the same result. "
    "Do not repeat it; change the command, or stop and explain the problem to the user."
)

_WS_RUN = re.compile(r"\s+")


def signature(tool_name: str, tool_input: Dict[str, Any],
              result: Dict[str, Any]) -> Tuple[str, str, bool, str]:
    """(tool name, canonical input without rationale, ok, first 200 chars of error)."""
    data = dict(tool_input or {})
    data.pop("rationale", None)
    command = data.get("command")
    if isinstance(command, str):
        data["command"] = _WS_RUN.sub(" ", command).strip()
    canonical = json.dumps(data, sort_keys=True, default=str)
    ok = bool((result or {}).get("ok", False))
    error = str((result or {}).get("error") or "")[:200]
    return (str(tool_name or ""), canonical, ok, error)


class LoopGuard:
    """Observe every tool result of one request; say when to nudge or stop."""

    def __init__(self) -> None:
        self._last: Optional[Tuple[Tuple[str, str, bool, str], str]] = None
        self._streak = 0
        self._nudged = False

    @property
    def streak(self) -> int:
        return self._streak

    def observe(self, tool_name: str, tool_input: Dict[str, Any],
                result: Dict[str, Any]) -> Optional[str]:
        """Record one result. Returns None, ``"nudge"`` or ``"stop"``."""
        sig = signature(tool_name, tool_input, result)
        output = str((result or {}).get("output") or "")[:200] if sig[2] else ""
        key = (sig, output)
        if key == self._last:
            self._streak += 1
        else:
            self._last = key
            self._streak = 1
            self._nudged = False
        if sig[2]:
            if sig[0] == SNAPSHOT_TOOL:
                return None
            limit = SUCCESS_LIMIT
        else:
            limit = FAILURE_LIMIT
        if self._streak < limit:
            return None
        if not self._nudged:
            self._nudged = True
            return "nudge"
        return "stop"
```

- [ ] **Step 4: Add the module to the Python 3.9 import check**

In `tests/test_py39_compat.py`, add this entry inside the `RUNTIME_MODULES` list literal, in its alphabetical position:

```python
    "vmd_ai_runtime.loop_guard",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_loop_guard.py tests/test_py39_compat.py -q`
Expected: `10 passed` for `test_loop_guard.py`; the 3.9 import check passes (or skips), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+98 passed` (one fewer plus `1 skipped` without Tcl 8.6), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/loop_guard.py tests/test_loop_guard.py tests/test_py39_compat.py
git commit -m "feat(loop): loop_guard repeat detector (C4)

Exact-repeat triggers only: the same failing call 3 times, or the same
successful call with the same output 4 times (snapshots exempt). The first
trigger nudges, the next identical call stops. Rationale and whitespace do
not change the signature.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: P05-T09 — Loop guard integration and wrap-up turn (C4)

**Files:**
- Create: `tests/helpers/fake_http.py`
- Create: `tests/test_loop_guard_integration.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports; new module-level `WRAP_UP_INSTRUCTION`, `LOOP_GUARD_SKIP_RESULT`, `_apply_tool_mode`, `_append_to_tool_result` after `_build_tool_result_block`; one line before `req = urllib.request.Request(` in `_stream_anthropic_direct` (564 at 6f5f937), `_stream_openrouter` (663) and `_stream_ollama` (1111); the rescue condition in `_stream_ollama` (1190 at 6f5f937; plan 02 added `rescue_mode != "off"` to it); new methods `_loop_guard_enabled`, `_guard_after_result`, `_skip_tool_block`, `_run_wrap_up`; five edits inside plan 02's `run()` (its tool loop calls `self._run_tool_block(...)` per tool)

**Interfaces:**
- Consumes: `LoopGuard`, `NUDGE_TEXT_TEMPLATE` (P05-T08); the `tool_mode` keyword of the three streamers and `self._tool_mode` (P02-T05); `ClaudeToolLoop._compact_for_call(messages) -> Tuple[List[Dict], bool]` (P03-T10); `_emit`, `self._ctx`, `self._turn`, `self._turn_meta` (P02-T05/T07); `last_status`, `last_turns`, `last_final_text_empty`, `_call_turn` (P02-T07); `_mint_call_key`, the per-tool `call_key` in `run()`, `_run_tool_block`, `_finish_text_turn`, `_tool_finished_meta`, `_RUNTIME_TOOLS` (P02-T08); `rescue_mode` in `_stream_ollama` (P02-T09); `LoopOptions(loop_guard=..., max_turns=..., base_url=...)` (P02-T05); `_vision_enabled()` (P04-T05, the `include_image=` argument in `run()`).
- Produces:
  - `WRAP_UP_INSTRUCTION` = "Stop using tools. In a few lines, say what you changed in the VMD scene, what you measured (with values), what failed, and what the user could try next."
  - `ClaudeToolLoop.last_wrapped_up: bool`; `ClaudeToolLoop.last_wrap_up_error: Optional[str]` (addition; the message for `request.finished.error`, P07-T02); `last_status` `'stuck'`; status phases `'loop_detected'` (with `call_key`, `stop`, `message`) and `'wrapping_up'` (with `message`); `last_turns` counts the wrap-up call; a successful wrap-up sets `last_final_text_empty` from its text
  - `LOOP_GUARD_SKIP_RESULT` (`{ok: False, output: "", error: "not executed: loop guard", executed: "no"}`), `_apply_tool_mode(body, flavor, tool_mode) -> Dict` (flavor `'ollama'|'anthropic'|'openai'`), `_append_to_tool_result(block, text) -> None`
  - `ClaudeToolLoop._skip_tool_block(block, call_key, origin) -> Dict[str, Any]` (a call left in the turn after the guard's stop: emits `tool.started`/`tool.finished` with `executed: "no"`, never dispatched, never recorded)
  - `tests/helpers/fake_http.py`: `FakeHTTP(chat, *, ps=None, version='0.12.3', on_chat=None)` with `.bodies`, `.urls`; builders `ollama_tool_call`, `ollama_tool_calls`, `ollama_text`, `anthropic_tool_call`, `anthropic_text`, `openai_tool_call`, `openai_text`, `http_error`

- [ ] **Step 1: Write the fake HTTP helper**

Create `tests/helpers/fake_http.py`:

```python
"""A scripted urllib.request.urlopen for loop tests (plan 05).

Routes by URL path: /api/version and /api/ps (Ollama preflight) and
/api/show answer from fixed JSON; the chat endpoints (/api/chat,
/v1/messages, /chat/completions) pop the next scripted body, or raise it
when it is an exception. Any other path fails the test.
"""
from __future__ import annotations

import email.message
import io
import json
import urllib.error
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Union

CHAT_PATHS = ("/api/chat", "/v1/messages", "/chat/completions")


class FakeResponse(io.BytesIO):
    status = 200

    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers: Dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def getcode(self) -> int:
        return 200

    def getheader(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return default


class FakeHTTP:
    def __init__(
        self,
        chat: List[Union[bytes, BaseException]],
        *,
        ps: Optional[Dict[str, Any]] = None,
        version: str = "0.12.3",
        on_chat: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.chat = list(chat)
        self.ps = ps if ps is not None else {"models": []}
        self.version = version
        self.on_chat = on_chat
        self.bodies: List[Dict[str, Any]] = []
        self.urls: List[str] = []

    def __call__(self, req: Any, timeout: Optional[float] = None, *args: Any, **kwargs: Any) -> FakeResponse:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        path = urllib.parse.urlsplit(url).path
        if path.endswith("/api/version"):
            return FakeResponse(json.dumps({"version": self.version}).encode("utf-8"))
        if path.endswith("/api/ps"):
            return FakeResponse(json.dumps(self.ps).encode("utf-8"))
        if path.endswith("/api/show"):
            return FakeResponse(json.dumps({"capabilities": ["completion", "tools"],
                                            "model_info": {}}).encode("utf-8"))
        if path.endswith(CHAT_PATHS):
            data = getattr(req, "data", None) or b"{}"
            body = json.loads(data.decode("utf-8"))
            self.bodies.append(body)
            if self.on_chat is not None:
                self.on_chat(body)
            if not self.chat:
                raise AssertionError("unexpected extra chat request to " + url)
            item = self.chat.pop(0)
            if isinstance(item, BaseException):
                raise item
            return FakeResponse(item)
        raise AssertionError("unexpected request: " + url)


def _ndjson(events: List[Dict[str, Any]]) -> bytes:
    return "".join(json.dumps(e) + "\n" for e in events).encode("utf-8")


def _sse(events: List[Any]) -> bytes:
    out = []
    for event in events:
        if event == "[DONE]":
            out.append("data: [DONE]\n\n")
        else:
            out.append("data: " + json.dumps(event) + "\n\n")
    return "".join(out).encode("utf-8")


def ollama_tool_call(command: str, call_id: Optional[str] = None) -> bytes:
    return ollama_tool_calls(command)


def ollama_tool_calls(*commands: str) -> bytes:
    """One Ollama turn that calls run_vmd_command once per command."""
    return _ndjson([{
        "model": "m",
        "message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_vmd_command", "arguments": {"command": command}}}
            for command in commands]},
        "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5,
    }])


def ollama_text(text: str) -> bytes:
    return _ndjson([{
        "model": "m", "message": {"role": "assistant", "content": text},
        "done": True, "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5,
    }])


def anthropic_tool_call(command: str, call_id: str = "toolu_01") -> bytes:
    return _sse([
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": call_id, "name": "run_vmd_command", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": json.dumps({"command": command})}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ])


def anthropic_text(text: str) -> bytes:
    return _sse([
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
        {"type": "message_stop"},
    ])


def openai_tool_call(command: str, call_id: str = "call_1") -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": call_id, "type": "function",
             "function": {"name": "run_vmd_command", "arguments": json.dumps({"command": command})}}]},
            "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        "[DONE]",
    ])


def openai_text(text: str) -> bytes:
    return _sse([
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        "[DONE]",
    ])


def http_error(url: str, code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", email.message.Message(), io.BytesIO(body))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_loop_guard_integration.py`:

```python
"""C4: loop guard in the loop — nudge, stop, and the tool-less wrap-up call."""
from __future__ import annotations

import json
import threading
from unittest import mock

import pytest

from helpers.fake_http import (
    FakeHTTP, anthropic_text, anthropic_tool_call, http_error,
    ollama_text, ollama_tool_call, ollama_tool_calls, openai_text, openai_tool_call,
)
from vmd_ai_runtime.claude_loop import (
    WRAP_UP_INSTRUCTION, ClaudeToolLoop, LoopOptions, RunContext, _apply_tool_mode,
)
from vmd_ai_runtime.events import EventQueue

FAIL = {"ok": False, "output": "", "error": 'invalid command name "mol_color"'}

PROVIDERS = {
    "ollama": dict(api_key="http://ollama.test", base_url="http://ollama.test",
                   tool=ollama_tool_call, text=ollama_text),
    "anthropic-direct": dict(api_key="sk-ant-test", base_url=None,
                             tool=anthropic_tool_call, text=anthropic_text),
    "openrouter": dict(api_key="sk-or-test", base_url="https://openrouter.ai/api/v1",
                       tool=openai_tool_call, text=openai_text),
    "openai-compatible": dict(api_key="EMPTY", base_url="http://vllm.test/v1",
                              tool=openai_tool_call, text=openai_text),
}


class ScriptBridge:
    """Strict six keywords (no supports_call_meta); returns scripted results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        self.calls.append(dict(tool_input))
        return dict(self.results[min(len(self.calls), len(self.results)) - 1])


def make_loop(provider, **opts):
    p = PROVIDERS[provider]
    options = LoopOptions(loop_guard=True, base_url=p["base_url"], **opts)
    return ClaudeToolLoop(provider_name=provider, api_key=p["api_key"],
                          model="qwen3.8:27b", options=options)


def run_loop(loop, fake, bridge, *, cancel=None, events=None, out=None):
    cancel = cancel or threading.Event()
    ctx = RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab",
                     on_event=events.append if events is not None else None, messages_out=out)
    with mock.patch("urllib.request.urlopen", fake):
        return loop.run(prompt="color the protein red", system_prompt="You are ChatVMD.",
                        tool_bridge=bridge, session_id="sess_0123456789ab",
                        session_queue=EventQueue(), cancel_event=cancel,
                        on_chunk=lambda t: None, ctx=ctx)


def stuck_script(provider, wrap):
    p = PROVIDERS[provider]
    return [p["tool"]("mol_color x", "id_%d" % i) for i in range(4)] + [wrap]


def _meta(event):
    return event.get("metadata") or {}


def test_nudge_once_in_next_body():
    fake = FakeHTTP(stuck_script("ollama", ollama_text("Summary: nothing changed.")))
    bridge = ScriptBridge([FAIL])
    text = run_loop(make_loop("ollama"), fake, bridge)
    assert len(fake.bodies) == 5
    assert json.dumps(fake.bodies[2]).count("Loop check:") == 0
    assert json.dumps(fake.bodies[3]).count("Loop check: this exact call has now run 3 times") == 1
    assert len(bridge.calls) == 4
    assert text == "Summary: nothing changed."


def test_wrapup_ollama_no_tools():
    fake = FakeHTTP(stuck_script("ollama", ollama_text("Summary.")))
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]))
    wrap = fake.bodies[4]
    assert "tools" not in wrap
    assert "tools" in fake.bodies[3]
    assert wrap["messages"][-1] == {"role": "user", "content": WRAP_UP_INSTRUCTION}
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


@pytest.mark.parametrize("provider", ["anthropic-direct", "openrouter", "openai-compatible"])
def test_wrapup_tool_choice_none_anthropic_openrouter_openai(provider):
    fake = FakeHTTP(stuck_script(provider, PROVIDERS[provider]["text"]("Summary.")))
    loop = make_loop(provider)
    run_loop(loop, fake, ScriptBridge([FAIL]))
    wrap = fake.bodies[4]
    expected = {"type": "none"} if provider == "anthropic-direct" else "none"
    assert wrap["tool_choice"] == expected
    assert "tools" in wrap
    assert "tool_choice" not in fake.bodies[3]
    assert WRAP_UP_INSTRUCTION in json.dumps(wrap)
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


def test_status_stuck_wrapped_up():
    events, out = [], []
    summary = "Summary: mol_color is not a VMD command."
    loop = make_loop("ollama")
    run_loop(loop, FakeHTTP(stuck_script("ollama", ollama_text(summary))), ScriptBridge([FAIL]),
             events=events, out=out)
    phases = [_meta(e).get("phase") for e in events if _meta(e).get("kind") == "status"]
    assert phases.count("loop_detected") == 2
    assert phases.count("wrapping_up") == 1
    stops = [_meta(e) for e in events if _meta(e).get("phase") == "loop_detected"]
    assert [m.get("stop") for m in stops] == [False, True]
    finals = [e for e in events
              if e["role"] == "assistant" and e["type"] == "message" and _meta(e).get("final")]
    assert finals[-1]["text"] == summary
    assert out[-1] == {"role": "assistant", "content": [{"type": "text", "text": summary}]}
    assert WRAP_UP_INSTRUCTION not in json.dumps(out)
    assert loop.last_status == "stuck"
    assert loop.last_wrapped_up is True
    assert loop.last_turns == 5
    assert loop.last_final_text_empty is False


def test_calls_after_stop_not_run():
    # C4: tool calls left in the turn after the stop are not run; each gets
    # executed "no" and "not executed: loop guard", and still has a row.
    events = []
    script = [ollama_tool_call("mol_color x") for _ in range(3)]
    script += [ollama_tool_calls("mol_color x", "mol new a.pdb"), ollama_text("Summary.")]
    fake = FakeHTTP(script)
    bridge = ScriptBridge([FAIL])
    loop = make_loop("ollama")
    run_loop(loop, fake, bridge, events=events)
    assert [c["command"] for c in bridge.calls] == ["mol_color x"] * 4
    finished = [_meta(e) for e in events if _meta(e).get("kind") == "tool.finished"]
    assert len(finished) == 5
    assert (finished[-1]["executed"], finished[-1]["error"]) == ("no", "not executed: loop guard")
    assert "not executed: loop guard" in json.dumps(fake.bodies[4])
    assert loop.last_status == "stuck" and loop.last_wrapped_up is True


def test_max_turns_wrapup():
    fake = FakeHTTP([ollama_tool_call("mol new a.pdb"), ollama_tool_call("mol new b.pdb"),
                     ollama_text("Summary: loaded a and b.")])
    loop = make_loop("ollama", max_turns=2)
    text = run_loop(loop, fake, ScriptBridge([{"ok": True, "output": "0", "error": ""},
                                              {"ok": True, "output": "1", "error": ""}]))
    assert len(fake.bodies) == 3
    assert "tools" not in fake.bodies[2]
    assert loop.last_status == "max_turns"
    assert loop.last_wrapped_up is True
    assert text == "Summary: loaded a and b."
    assert loop.last_turns == 3


def test_stop_during_wrapup_cancelled():
    cancel = threading.Event()

    def on_chat(body):
        if WRAP_UP_INSTRUCTION in json.dumps(body):
            cancel.set()

    fake = FakeHTTP(stuck_script("ollama", ollama_text("half a summ")), on_chat=on_chat)
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]), cancel=cancel)
    assert loop.last_status == "cancelled"
    assert loop.last_wrapped_up is False


def test_wrapup_error_is_notice_not_raise():
    events = []
    fake = FakeHTTP(stuck_script("ollama", http_error("http://ollama.test/api/chat", 400, b'{"error":"boom"}')))
    loop = make_loop("ollama")
    run_loop(loop, fake, ScriptBridge([FAIL]), events=events)  # must not raise
    assert loop.last_status == "stuck"
    assert loop.last_wrapped_up is False
    assert "400" in (loop.last_wrap_up_error or "")
    notes = [_meta(e) for e in events if _meta(e).get("phase") == "wrapping_up"]
    assert notes[-1]["message"].startswith("Summary failed:")
    assert not [e for e in events if e["role"] == "error"]


def test_guard_off_without_options():
    fake = FakeHTTP([ollama_tool_call("mol_color x")] * 4 + [ollama_text("gave up")])
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m")
    with mock.patch("urllib.request.urlopen", fake):
        text = loop.run(prompt="p", system_prompt="s", tool_bridge=ScriptBridge([FAIL]),
                        session_id="s", session_queue=EventQueue(),
                        cancel_event=threading.Event(), on_chunk=lambda t: None)
    assert len(fake.bodies) == 5
    assert all("tools" in body for body in fake.bodies)
    assert "Loop check" not in json.dumps(fake.bodies)
    assert text == "gave up"


def test_apply_tool_mode_unit():
    body = {"tools": [1]}
    _apply_tool_mode(body, "ollama", "none")
    assert "tools" not in body
    body = {"tools": [1]}
    _apply_tool_mode(body, "anthropic", "none")
    assert body["tool_choice"] == {"type": "none"}
    body = {"tools": [1]}
    _apply_tool_mode(body, "openai", "none")
    assert body["tool_choice"] == "none"
    for mode in (None, "auto"):
        body = {"tools": [1]}
        _apply_tool_mode(body, "anthropic", mode)
        assert body == {"tools": [1]}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_loop_guard_integration.py -q`
Expected: collection error `ImportError: cannot import name 'WRAP_UP_INSTRUCTION' from 'vmd_ai_runtime.claude_loop'`.

- [ ] **Step 4: Module-level pieces in `runtime/vmd_ai_runtime/claude_loop.py`**

(a) Next to the other relative imports at the top of the module, add:

```python
from .loop_guard import NUDGE_TEXT_TEMPLATE, LoopGuard
```

(b) Add directly after the end of `_build_tool_result_block`:

```python
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
```

(c) In `_stream_anthropic_direct`, directly before its `req = urllib.request.Request(` line, add:

```python
    _apply_tool_mode(body, "anthropic", tool_mode)
```

In `_stream_openrouter`, directly before its `req = urllib.request.Request(` line, add:

```python
    _apply_tool_mode(body, "openai", tool_mode)
```

In `_stream_ollama`, directly before its `req = urllib.request.Request(` line (the `/api/chat` request, not a preflight request), add:

```python
    _apply_tool_mode(body, "ollama", tool_mode)
```

(d) In `_stream_ollama`, add `and tool_mode != "none"` to the condition of the JSON-in-content rescue block (the `if` that calls `_rescue_json_tool_calls(text, allowed, mode=rescue_mode)`), so a wrap-up reply is never turned back into tool calls. After plan 02 (P02-T09) that line reads `if not final_tool_blocks and text and rescue_mode != "off":`; it becomes:

```python
    if not final_tool_blocks and text and rescue_mode != "off" and tool_mode != "none":
```

- [ ] **Step 5: Guard and wrap-up methods on `ClaudeToolLoop`**

Add these methods directly after `_result_format` (Task 6):

```python
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
```

- [ ] **Step 6: Wire the guard into `run()`**

Make these five edits inside `ClaudeToolLoop.run` as plan 02 (P02-T07/T08) left it; Task 0 Step 3 printed the anchor lines. The names below are plan 02's: `turn`, `tool_blocks`, `call_keys`, `block`, `call_key`, `tool_id`, `rescued_ids`, `truncated`, `result`, `tool_result_blocks`, `result_keys`, `end_status`, `final_text`, `messages`, and `on_text = self._text_sink(on_chunk)`.

(1) Directly after the line `self._ctx = ctx`, add:

```python
        self.last_wrapped_up = False
        self.last_wrap_up_error = None
```

(2) Directly before the `for turn in range(max_turns):` line (inside the outer `try:`), add:

```python
            guard = LoopGuard() if self._loop_guard_enabled() else None
            guard_stop = False
```

(3) + (4) In the per-tool loop `for block, call_key in zip(tool_blocks, call_keys):`, replace everything from `result = self._run_tool_block(` through the end of the `tool_result_blocks.append(_build_tool_result_block(...))` statement (the `if cancel_event.is_set(): ... break`, the `tool_id = ...` line before it and the `result_keys.append(call_key)` line after it stay) with the block below. Keep the `include_image=` expression that is already there (plan 04 made it `self._vision_enabled()`) and Task 6's `result_format=self._result_format()`:

```python
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
```

(5a) As the last statements of the turn body — directly after plan 02's `if tool_result_blocks:` block (which appends the tool-results message to `messages` and `self._out(_canonical_message(messages[-1], result_keys))`), at the same indentation as that `if` — add:

```python
                if guard_stop and end_status != "cancelled":
                    end_status = "stuck"
                    logger.info("loop guard stopped the run after turn %d", turn + 1)
                    break
```

(5b) Directly after the `for ... else:` block ends (its `else:` sets `end_status = "max_turns"`), still inside the outer `try:` and before plan 02's `except RunCancelled:`, add:

```python
            if (guard is not None and end_status in ("stuck", "max_turns")
                    and not cancel_event.is_set()):
                wrap_text, wrap_cancelled = self._run_wrap_up(
                    messages, system_prompt, on_text, cancel_event, self.last_turns + 1
                )
                if wrap_cancelled:
                    end_status = "cancelled"
                elif wrap_text:
                    final_text = wrap_text
```

`self.last_turns` is set at the start of every turn (plan 02), so `self.last_turns + 1` numbers the wrap-up call and `_run_wrap_up` stores it back into `last_turns` (C4: "`turns` counts the wrap-up call"). Plan 02's `finally:` only copies `end_status` into `last_status`, so `stuck` reaches both `last_status` and the recorder's `end_task`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_loop_guard_integration.py -q`
Expected: `12 passed`.

Run the S7 guards and the loop suites:
`env -u VMD_AI_PROVIDER python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_hashes.py tests/test_benchmark_retry_pin.py tests/test_loop_flags.py tests/test_loop_events.py tests/test_rescue_modes.py tests/test_compact_in_run.py tests/test_claude_loop.py -q`
Expected: all passed; the golden requests are byte-identical (with `options=None`, `tool_mode` is `None`, so `_apply_tool_mode` never touches a body and the rescue condition is unchanged).

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+110 passed` (one fewer plus `1 skipped` without Tcl 8.6), 0 failed.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/helpers/fake_http.py tests/test_loop_guard_integration.py
git commit -m "feat(loop): loop guard nudge/stop and the tool-less wrap-up turn (C4)

With options.loop_guard the loop appends a nudge to the first repeated
result, stops at the next identical call (status stuck) and, after a stop
or max_turns, makes one extra call with tool_mode none that summarises the
run. options=None keeps no detector and no extra call (S7 goldens unchanged).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 10: P05-T10 — Run provenance: recorder meta and update_meta (C6)

**Files:**
- Create: `tests/test_run_provenance_manifest.py`
- Modify: `runtime/vmd_ai_runtime/recorder/run.py:27` (typing import), `:42-43` (new constants), `:118-128` (`__init__`, `for_cwd`, new `update_meta`), `:342-360` (`_write_tcl_header` + new `_provenance_header`), `:366-389` (`_flush_manifest`)
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — `run()` (counter reset after `self._ctx = ctx`; one call after the turn's `_call_turn`; one call at the top of `finally:`), `_on_meta` (first lines), `_recorder_record` (first lines), new methods `_recorder_update_meta`, `_provenance_digest`
- Modify: `runtime/vmd_ai_runtime/app.py:524-551` (`_build_recorder_for_session`), `:610-613` at 6f5f937 (the recorder built in `_run_claude_loop_response`; after plan 03 it is the single line `loop.recorder = self._build_recorder_for_session(state)`), imports, new module functions `_canonical_sha256` and `_tools_as_sent`, new method `_recorder_meta`
- Modify: `runtime/vmd_ai_runtime/provider_catalog.py` (new `strip_url_secrets`)

**Interfaces:**
- Consumes: `last_model_digest` (P04-T01); `cached_tag_digest` (P03-T07); `SessionState.vmd_env` (P02-T02); `chatvmd_system_prompt` and, in the hash test, `RuntimeApp._system_prompt_for_request(state, loop)` (P04-T06); `ClaudeToolLoop.last_usage` (P04-T03); `last_compactions` (P03-T10); on_meta items `{kind:'rescued', ids}` and `{kind:'stop_reason', value}` (P02-T07/T08); `LoopOptions.to_dict()` (P02-T05); `ClaudeToolLoop._vision_enabled()` (P04-T05); `constants.RUNTIME_VERSION` (P02-T01); `SettingsStore()`, `.active_profile()`, `.save_profile(name, profile, activate=False)` (P03-T05) with `RuntimeApp(settings_store=...)` (P03-T08; `make_app` builds no store by itself); `_call_turn` (P02-T07); `_ollama_tools`, `_openrouter_tools` (claude_loop, unchanged since 6f5f937); `FakeHTTP` and builders (P05-T09).
- Produces:
  - `RunRecorder(runs_root=None, meta: Optional[Dict[str, Any]] = None)`; `RunRecorder.for_cwd(cwd=None, meta=None)`; `RunRecorder.update_meta(**fields) -> None` (`usage=`/`counts=` merge into those keys, every other field goes into `provenance`; no-op without `meta`)
  - manifest keys `provenance {request_id, profile, provider, base_url, model, model_digest, runtime_version, vmd_env, options, system_prompt_sha256, tools_sha256}`, `usage {input_tokens_evaluated, output_tokens}`, `counts {tool_calls, rescued_calls, truncated_turns, compactions}` — only when `meta` was given
  - transcript header lines `# provider   :`, `# runtime    :`, `# vmd        :`, `# provenance : see manifest.json` — only when `meta` was given
  - `provider_catalog.strip_url_secrets(url: str) -> str`
  - `RuntimeApp._build_recorder_for_session(state, meta: Optional[Dict[str, Any]] = None)`; `RuntimeApp._recorder_meta(state, loop, request_id: str) -> Dict[str, Any]`; app-level `_canonical_sha256(obj) -> str` and `_tools_as_sent(loop) -> List[Dict[str, Any]]` (the turn-1 `tools` in the provider's body shape: Anthropic as is, Ollama via `_ollama_tools`, OpenRouter/OpenAI-compatible via `_openrouter_tools`)
  - `ClaudeToolLoop._recorder_update_meta() -> None` (no-op unless a recorder and `self._ctx` are set)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_provenance_manifest.py`:

```python
"""C6: product run provenance in the recorder manifest."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from helpers.fake_http import FakeHTTP, anthropic_text, ollama_text, openai_text
from helpers.runtime_fixture import make_app, start_token_session
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext
from vmd_ai_runtime.constants import RUNTIME_VERSION
from vmd_ai_runtime.events import EventQueue
from vmd_ai_runtime.provider_catalog import strip_url_secrets
from vmd_ai_runtime.recorder import RunRecorder
from vmd_ai_runtime.settings_store import SettingsStore

TOKEN = "0123456789abcdef0123456789abcdef"
LEGACY_KEYS = {
    "task_id", "status", "prompt", "chat_id", "model", "cwd", "started_at",
    "last_activity_at", "turn_count", "successful_count", "failed_count",
    "snapshot_count", "ended_at",
}
VMD_ENV = {"vmd_version": "1.9.4a57", "arch": "MACOSXARM64",
           "tcl_patchlevel": "8.6.12", "tk_patchlevel": "8.6.12"}


class NullBridge:
    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input, session_queue, cancel_event):
        return {"ok": True, "output": "", "error": ""}


def _manifest(root: Path) -> dict:
    found = list((root / ".vmdai_runs").glob("*/manifest.json"))
    assert len(found) == 1, found
    return json.loads(found[0].read_text())


def _run(loop, fake, root, meta):
    loop.recorder = RunRecorder.for_cwd(root, meta=meta)
    ctx = RunContext(request_id="req_000000000001", chat_id="chat_0123456789ab")
    with mock.patch("urllib.request.urlopen", fake):
        loop.run(prompt="hi", system_prompt="s", tool_bridge=NullBridge(),
                 session_id="sess_0123456789ab", session_queue=EventQueue(),
                 cancel_event=threading.Event(), on_chunk=lambda t: None, ctx=ctx)
    return _manifest(root)


def _rpc(app, method, params, sess):
    body = {"jsonrpc": "2.0", "id": "t", "method": method,
            "params": dict(params, session_id=sess["session_id"])}
    return app.handle_rpc(body, session_token=sess["session_token"])


def _wait_idle(app, session_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = app.sessions.get(session_id)
        if state is not None and state.active_request is None:
            return
        time.sleep(0.02)
    raise AssertionError("request did not finish")


def test_existing_keys_unchanged_without_meta(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path)
    tid = rec.start_task("x", chat_id="c", model="m", cwd="/w")
    rec.update_meta(model_digest="sha256:x", usage={"output_tokens": 1})
    rec.end_task()
    assert set(rec.read_manifest(tid)) == LEGACY_KEYS
    assert "# provider" not in rec.read_transcript(tid)


def test_digest_from_ps(tmp_path):
    ps = {"models": [{"name": "qwen3.8:27b", "model": "qwen3.8:27b", "digest": "c0ffee1234", "size": 1}]}
    fake = FakeHTTP([ollama_text("done")], ps=ps)
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="qwen3.8:27b",
                          options=LoopOptions(preflight=True, base_url="http://ollama.test"))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["provenance"]["model_digest"] == "c0ffee1234"
    assert m["usage"] == {"input_tokens_evaluated": 10, "output_tokens": 5}
    assert m["counts"] == {"tool_calls": 0, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}
    assert m["status"] == "complete"
    assert any(u.endswith("/api/ps") for u in fake.urls)


def test_digest_null_when_absent(tmp_path):
    fake = FakeHTTP([ollama_text("done")], ps={"models": []})
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="qwen3.8:27b",
                          options=LoopOptions(preflight=True, base_url="http://ollama.test"))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["provenance"]["model_digest"] is None


def test_usage_null_include_usage_off(tmp_path):
    fake = FakeHTTP([openai_text("done")])
    loop = ClaudeToolLoop(provider_name="openai-compatible", api_key="EMPTY", model="m",
                          options=LoopOptions(base_url="http://vllm.test/v1", include_usage=False))
    m = _run(loop, fake, tmp_path, {"request_id": "req_000000000001"})
    assert m["usage"] == {"input_tokens_evaluated": None, "output_tokens": None}
    assert m["provenance"]["model_digest"] is None
    assert "stream_options" not in fake.bodies[0]


@pytest.mark.parametrize("provider,api_key,model,reply", [
    ("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5", anthropic_text),
    ("ollama", "http://ollama.test", "qwen3.8:27b", ollama_text),
])
def test_tools_sha256_matches_first_request(tmp_path, provider, api_key, model, reply):
    # The hash covers the tools list exactly as the provider's body carries it.
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    state = app.sessions.get(sess["session_id"])
    loop = ClaudeToolLoop(provider_name=provider, api_key=api_key, model=model,
                          options=LoopOptions())
    meta = app._recorder_meta(state, loop, "req_000000000001")
    fake = FakeHTTP([reply("done")])
    m = _run(loop, fake, tmp_path / "w", meta)
    first_tools = fake.bodies[0]["tools"]
    canonical = hashlib.sha256(
        json.dumps(first_tools, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert m["provenance"]["tools_sha256"] == canonical


def test_system_prompt_sha_cwd_independent_wiki_dependent(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    other = tmp_path / "other"
    other.mkdir()
    a = start_token_session(app, TOKEN, cwd=str(tmp_path))
    b = start_token_session(app, TOKEN, cwd=str(other))
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://ollama.test", model="m",
                          options=LoopOptions(base_url="http://ollama.test"))
    sha_a = app._recorder_meta(app.sessions.get(a["session_id"]), loop, "req_a")["system_prompt_sha256"]
    sha_b = app._recorder_meta(app.sessions.get(b["session_id"]), loop, "req_b")["system_prompt_sha256"]
    assert sha_a == sha_b and len(sha_a) == 64
    # C6: the hash covers exactly the prompt the request sends before its
    # <session> block (P04-T06), mode line included.
    full = app._system_prompt_for_request(app.sessions.get(a["session_id"]), loop)
    before_session = full[: full.index("\n\n<session>\n")]
    assert sha_a == hashlib.sha256(before_session.encode("utf-8")).hexdigest()
    loop.wiki_store = object()
    sha_wiki = app._recorder_meta(app.sessions.get(a["session_id"]), loop, "req_c")["system_prompt_sha256"]
    assert sha_wiki != sha_a


def test_base_url_secrets_stripped(tmp_path):
    assert strip_url_secrets("http://user:pw@127.0.0.1:11435/v1?key=x#frag") == "http://127.0.0.1:11435/v1"
    assert strip_url_secrets("https://openrouter.ai/api/v1") == "https://openrouter.ai/api/v1"
    assert strip_url_secrets("") == ""
    app = make_app(tmp_path, launch_token=TOKEN)
    sess = start_token_session(app, TOKEN, cwd=str(tmp_path))
    secret = "http://user:pw@127.0.0.1:11435?key=x"
    loop = ClaudeToolLoop(provider_name="ollama", api_key=secret, model="m",
                          options=LoopOptions(base_url=secret))
    meta = app._recorder_meta(app.sessions.get(sess["session_id"]), loop, "req_1")
    dumped = json.dumps(meta)
    assert "pw@" not in dumped and "key=x" not in dumped
    assert meta["base_url"] == "http://127.0.0.1:11435"
    assert meta["options"]["base_url"] == "http://127.0.0.1:11435"


def test_header_comment_lines(tmp_path):
    meta = {"request_id": "req_1", "profile": "qwen", "provider": "ollama",
            "base_url": "http://127.0.0.1:11435", "model": "qwen3.8:27b", "model_digest": None,
            "runtime_version": "0.3.0", "vmd_env": VMD_ENV, "options": {"num_ctx": 32768},
            "system_prompt_sha256": "a" * 64, "tools_sha256": "b" * 64}
    rec = RunRecorder.for_cwd(tmp_path, meta=meta)
    tid = rec.start_task("x")
    rec.update_meta(model_digest="sha256:abc")
    rec.end_task()
    head = rec.read_transcript(tid)
    assert "# provider   : ollama http://127.0.0.1:11435\n" in head
    assert "# runtime    : vmd_ai_runtime 0.3.0\n" in head
    assert "# vmd        : 1.9.4a57 MACOSXARM64 (Tcl 8.6.12, Tk 8.6.12)\n" in head
    assert "# provenance : see manifest.json\n" in head
    assert "sha256:abc" not in head, "the digest lives only in the manifest"


def test_update_meta_merges_and_mirrors_status(tmp_path):
    rec = RunRecorder.for_cwd(tmp_path, meta={"request_id": "req_1", "model_digest": None})
    tid = rec.start_task("x")
    rec.update_meta(model_digest="sha256:abc", usage={"output_tokens": 5}, counts={"tool_calls": 2})
    m = rec.read_manifest(tid)
    assert m["status"] == "active"
    assert m["provenance"] == {"request_id": "req_1", "model_digest": "sha256:abc"}
    assert m["usage"] == {"input_tokens_evaluated": None, "output_tokens": 5}
    assert m["counts"] == {"tool_calls": 2, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}
    rec.end_task("stuck")
    assert rec.read_manifest(tid)["status"] == "stuck"


def test_product_run_manifest_has_provenance(tmp_path):
    # make_app builds no SettingsStore (plan 03: only main.py passes one).
    app = make_app(tmp_path, launch_token=TOKEN, settings_store=SettingsStore())
    work = tmp_path / "work"
    work.mkdir()
    sess = start_token_session(app, TOKEN, cwd=str(work), vmd_env=VMD_ENV)
    app.settings_store.save_profile(
        "local", {"provider": "ollama", "base_url": "http://127.0.0.1:9", "model": "m"}, activate=True)
    secret = "http://user:pw@127.0.0.1:9?key=x"
    loop = ClaudeToolLoop(provider_name="ollama", api_key="http://127.0.0.1:9", model="m",
                          options=LoopOptions(base_url=secret))
    app.claude_loop = loop

    def fake_call(self, messages, system_prompt, on_text, should_cancel):
        on_text("done")
        return "done", []

    with mock.patch.object(ClaudeToolLoop, "_call", new=fake_call):
        resp = _rpc(app, "chat.send", {"text": "hello", "conversation_mode": "full"}, sess)
        assert "result" in resp, resp
        _wait_idle(app, sess["session_id"])
    m = _manifest(work)
    p = m["provenance"]
    assert p["request_id"] == resp["result"]["request_id"]
    assert p["profile"] == "local"
    assert (p["provider"], p["model"]) == ("ollama", "m")
    assert p["runtime_version"] == RUNTIME_VERSION
    assert p["vmd_env"] == VMD_ENV
    assert p["base_url"] == "http://127.0.0.1:9"
    assert len(p["system_prompt_sha256"]) == 64 and len(p["tools_sha256"]) == 64
    assert "pw@" not in json.dumps(m) and "key=x" not in json.dumps(m)
    assert m["status"] == "complete"
    transcript = next((work / ".vmdai_runs").glob("*/transcript.tcl")).read_text()
    assert "# provenance : see manifest.json" in transcript
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_run_provenance_manifest.py -q`
Expected: collection error `ImportError: cannot import name 'strip_url_secrets' from 'vmd_ai_runtime.provider_catalog'`.

- [ ] **Step 3: Provenance in `runtime/vmd_ai_runtime/recorder/run.py`**

(a) Change `from typing import Optional` to `from typing import Any, Dict, Optional`.

(b) After `_SAFE_EXT = ("png", "tga", "jpg", "jpeg")` add:

```python
_EMPTY_USAGE = {"input_tokens_evaluated": None, "output_tokens": None}
_EMPTY_COUNTS = {"tool_calls": 0, "rescued_calls": 0, "truncated_turns": 0, "compactions": 0}
```

(c) Replace `__init__` and `for_cwd` (the whole "Construction" section) with:

```python
    def __init__(
        self,
        runs_root: Optional[Path | str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.runs_root: Optional[Path] = (
            Path(runs_root) if runs_root is not None else None
        )
        self._current: Optional[_TaskState] = None
        # C6 product-run provenance. None keeps today's manifest exactly.
        self._meta: Optional[Dict[str, Any]] = None
        if meta is not None:
            self._meta = {
                "provenance": dict(meta),
                "usage": dict(_EMPTY_USAGE),
                "counts": dict(_EMPTY_COUNTS),
            }

    @classmethod
    def for_cwd(
        cls,
        cwd: Optional[str | Path] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> "RunRecorder":
        """Build a recorder rooted at ``<cwd>/.vmdai_runs/``."""
        base = Path(cwd) if cwd is not None else Path(os.getcwd())
        return cls(base / cls.DEFAULT_DIR_NAME, meta=meta)

    def update_meta(self, **fields: Any) -> None:
        """Merge provenance fields; ``usage`` and ``counts`` update their keys.

        No-op when the recorder was built without ``meta``. Rewrites the
        manifest when a task is active, so a crash leaves the values of the
        last completed turn on disk.
        """
        if self._meta is None:
            return
        for key, value in fields.items():
            if key in ("usage", "counts"):
                merged = dict(self._meta[key])
                merged.update(dict(value or {}))
                self._meta[key] = merged
            else:
                self._meta["provenance"][key] = value
        if self._current is not None:
            self._flush_manifest(status="active")
```

(d) In `_write_tcl_header`, replace:

```python
            f"# prompt     : {prompt_one_line}\n"
            f"#\n"
```

with:

```python
            f"# prompt     : {prompt_one_line}\n"
            f"{self._provenance_header()}"
            f"#\n"
```

and add this method directly after `_write_tcl_header`:

```python
    def _provenance_header(self) -> str:
        """C6 header lines; empty without meta. The digest lives only in the
        manifest, because it may be unknown when the header is written."""
        if self._meta is None:
            return ""
        p = self._meta["provenance"]
        env = p.get("vmd_env") or {}
        vmd = " ".join(
            str(x) for x in (env.get("vmd_version"), env.get("arch")) if x
        ) or "unknown"
        tcl_tk = []
        if env.get("tcl_patchlevel"):
            tcl_tk.append(f"Tcl {env['tcl_patchlevel']}")
        if env.get("tk_patchlevel"):
            tcl_tk.append(f"Tk {env['tk_patchlevel']}")
        if tcl_tk:
            vmd += " (" + ", ".join(tcl_tk) + ")"
        provider = str(p.get("provider") or "")
        if p.get("base_url"):
            provider += f" {p['base_url']}"
        return (
            f"# provider   : {provider}\n"
            f"# runtime    : vmd_ai_runtime {p.get('runtime_version') or 'unknown'}\n"
            f"# vmd        : {vmd}\n"
            f"# provenance : see manifest.json\n"
        )
```

(e) In `_flush_manifest`, replace:

```python
        if ended:
            manifest["ended_at"] = _utc_iso(time.time())
```

with:

```python
        if ended:
            manifest["ended_at"] = _utc_iso(time.time())
        if self._meta is not None:
            manifest["provenance"] = dict(self._meta["provenance"])
            manifest["usage"] = dict(self._meta["usage"])
            manifest["counts"] = dict(self._meta["counts"])
```

- [ ] **Step 4: `strip_url_secrets` in `runtime/vmd_ai_runtime/provider_catalog.py`**

Make sure `import urllib.parse` is among the imports (next to `import urllib.request`), then add at module level:

```python
def strip_url_secrets(url: str) -> str:
    """Drop userinfo, query and fragment from ``url`` (C6 provenance)."""
    text = str(url or "")
    if not text:
        return text
    parts = urllib.parse.urlsplit(text)
    host = parts.netloc.rpartition("@")[2]
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", ""))
```

- [ ] **Step 5: Loop updates — `runtime/vmd_ai_runtime/claude_loop.py`**

(a) In `run()`, directly after the two lines added in Task 9 Step 6 (1) (after `self._ctx = ctx`), add:

```python
        self._prov_tool_calls = 0
        self._prov_rescued = 0
        self._prov_truncated = 0
```

(b) In `run()`, directly after the `try:`/`except` block that obtains `text, tool_blocks = self._call_turn(...)` for the turn (plan 02; plan 03's compaction lines sit inside the same `try:`), and before `if text:`, add at the indentation of that `try:`:

```python
                self._recorder_update_meta()
```

(c) In `run()`, make this the first statement of the outer `finally:` block (before `self._recorder_end_task(end_status)` and before plan 02 clears `self._ctx`):

```python
            self._recorder_update_meta()
```

(d) In `_on_meta`, insert as the first statements of the method body:

```python
        kind = item.get("kind") if isinstance(item, dict) else None
        if kind == "rescued":
            self._prov_rescued = getattr(self, "_prov_rescued", 0) + len(item.get("ids") or [])
        elif kind == "stop_reason" and item.get("value") in ("max_tokens", "length"):
            self._prov_truncated = getattr(self, "_prov_truncated", 0) + 1
```

(e) In `_recorder_record`, directly after:

```python
        if self.recorder is None:
            return
```

insert (before the Task 5 `blocked` check, so blocked calls still count as tool calls):

```python
        self._prov_tool_calls = getattr(self, "_prov_tool_calls", 0) + 1
```

(f) Add these methods directly after `_recorder_record`:

```python
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
```

- [ ] **Step 6: Static provenance and the product recorder — `runtime/vmd_ai_runtime/app.py`**

(a) Make sure these imports are present (add the missing ones):

```python
import hashlib
import json

from .claude_loop import WIKI_SYSTEM_PROMPT_ADDENDUM, _ollama_tools, _openrouter_tools
from .constants import RUNTIME_VERSION
from .prompts import chatvmd_system_prompt
from .provider_catalog import strip_url_secrets
```

and make sure the `typing` import includes `List` (for example `from typing import Any, Dict, List, Optional, Tuple`).

(b) Add these module-level functions directly above `class RuntimeApp:`:

```python
def _canonical_sha256(obj: Any) -> str:
    """SHA-256 of canonical JSON (sorted keys, compact separators): C6 tools_sha256."""
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _tools_as_sent(loop) -> List[Dict[str, Any]]:
    """The ``tools`` list a turn-1 request body carries (C6: after
    tool_overrides, in the provider's own shape)."""
    tools = loop._tools_for_turn()
    if getattr(loop, "_is_anthropic_direct", False):
        return list(tools)
    if getattr(loop, "_is_ollama", False):
        return _ollama_tools(tools)
    return _openrouter_tools(tools)
```

(c) Replace the whole `_build_recorder_for_session` method with:

```python
    def _build_recorder_for_session(self, state, meta: Optional[Dict[str, Any]] = None) -> RunRecorder | None:
        """Build a RunRecorder for this chat.send, or None.

        Resolution rules:
          1. ``VMD_AI_RECORDER=off`` → no recorder, return None.
          2. ``state.cwd`` is a real directory → ``<cwd>/.vmdai_runs/``.
          3. Otherwise fall back to ``~/.vmdai/runs/`` so we never
             silently drop the artifact (option (c) in the plan).

        ``meta`` (C6, product runs only) adds the provenance/usage/counts
        manifest keys and the provenance header lines.

        Returns None on any construction failure — the recorder is a
        side-channel; failing to build one must never break chat.send.
        """
        if os.getenv("VMD_AI_RECORDER", "on").lower() == "off":
            return None
        try:
            cwd = (state.cwd or "").strip()
            if cwd and os.path.isdir(cwd):
                return RunRecorder.for_cwd(cwd, meta=meta)
            # Centralized fallback so we don't pollute the home dir
            # directly — everything lives under ~/.vmdai/runs/<task_id>/.
            fallback = Path(os.path.expanduser("~/.vmdai")) / "runs"
            return RunRecorder(runs_root=fallback, meta=meta)
        except Exception:
            if self.logger:
                self.logger.warning(
                    "recorder construction failed", exc_info=True,
                )
            return None

    def _recorder_meta(self, state, loop, request_id: str) -> Dict[str, Any]:
        """C6 static provenance for a product run's recorder manifest."""
        options = getattr(loop, "options", None)
        base_url = ""
        if options is not None and getattr(options, "base_url", None):
            base_url = str(options.base_url)
        elif getattr(loop, "_is_ollama", False):
            base_url = str(loop.api_key or "")
        opts = None
        if options is not None:
            opts = options.to_dict()
            if opts.get("base_url"):
                opts["base_url"] = strip_url_secrets(str(opts["base_url"]))
        try:
            vision = bool(loop._vision_enabled())
        except Exception:
            vision = False
        # The prompt before the per-request <session> block (the variant plus
        # today's mode line, exactly as P04-T06's _system_prompt_for_request
        # builds it), plus the wiki addendum run() appends when wiki is on
        # (C6 Hashes).
        mode = str(state.settings.get("mode") or "work")
        prompt = chatvmd_system_prompt(vision) + f"\n\nMode: {mode}."
        if getattr(loop, "wiki_store", None) is not None:
            prompt += WIKI_SYSTEM_PROMPT_ADDENDUM
        profile_name = None
        store = getattr(self, "settings_store", None)
        if store is not None:
            try:
                profile_name = store.active_profile()[0]
            except Exception:
                profile_name = None
        return {
            "request_id": request_id,
            "profile": profile_name,
            "provider": loop.provider_name,
            "base_url": strip_url_secrets(base_url) if base_url else None,
            "model": loop.model,
            "model_digest": None,
            "runtime_version": RUNTIME_VERSION,
            "vmd_env": getattr(state, "vmd_env", None),
            "options": opts,
            "system_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "tools_sha256": _canonical_sha256(_tools_as_sent(loop)),
        }
```

(d) In `_run_claude_loop_response`, replace the line `loop.recorder = self._build_recorder_for_session(state)` (plan 03 P03-T04 wrote it directly after `prev_recorder = loop.recorder`; `loop` is never None there, the method returns earlier) with:

```python
        meta = None
        if getattr(state, "authenticated", False):
            try:
                meta = self._recorder_meta(state, loop, request_id)
            except Exception:
                meta = None
                if self.logger:
                    self.logger.warning("recorder provenance failed", exc_info=True)
        loop.recorder = self._build_recorder_for_session(state, meta)
```

Tokenless sessions get `meta=None`, so their manifests keep exactly today's keys.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests/test_run_provenance_manifest.py tests/test_recorder.py tests/test_recorder_integration.py tests/test_claude_loop_recorder.py -q`
Expected: all passed (`11 passed` from the new file), 0 failed.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2`
Expected: `B+121 passed` (one fewer plus `1 skipped` without Tcl 8.6), 0 failed, in under 60 s.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/recorder/run.py runtime/vmd_ai_runtime/claude_loop.py runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/provider_catalog.py tests/test_run_provenance_manifest.py
git commit -m "feat(recorder): product run provenance in the manifest (C6)

RunRecorder(meta=...) adds provenance, usage and counts to manifest.json
and provider/runtime/vmd header lines to transcript.tcl; the loop updates
digest, usage and counts after each turn and at the end. Secrets are
stripped from base_url. Recorders built without meta are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Plan exit check

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything above.
- Produces: the evidence for this plan's exit criteria (S10 save_path file, S11 snapshot-path rejection, C1, C2, C3 runtime, C4 runtime, C5 runtime, C6).

- [ ] **Step 1: Run every suite**

Run:
```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -2
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
```
Expected: `B+121 passed` (plus the usual skips) with 0 failed in under 60 s; `90 passed`; `62 passed`.

- [ ] **Step 2: Confirm the benchmark-facing files are untouched**

Run: `git diff main --stat -- integrations/ runtime/vmd_ai_runtime/image_utils.py vmdbench/`
Expected: no output.

Run: `/usr/bin/python3 -c "import sys; sys.path.insert(0, 'runtime'); import vmd_ai_runtime.app, vmd_ai_runtime.tool_bridge, vmd_ai_runtime.tcl_policy, vmd_ai_runtime.loop_guard; print('ok')"`
Expected: `ok` (Python 3.9 imports every module this plan touched).

---

## Deviations from skeleton

1. **Task 0 (pre-flight) added.** It checks the plan 01–04 interfaces behaviourally in a throwaway pytest file (so the hermetic conftest applies) and prints the edit anchors, because this plan edits code that plans 02–04 rewrite.
2. **New test helpers** not in the skeleton's file list: `tests/helpers/bridge_harness.py` (Task 1; used by Tasks 1, 2, 3, 5, 7) and `tests/helpers/fake_http.py` (Task 9; used by Tasks 9, 10). They avoid repeating the thread/fake-urlopen plumbing in six test files.
3. **`tests/test_tool_bridge.py` is modified in Task 3.** Two existing tokenless snapshot tests posted an arbitrary temp path; §2d now allows a tokenless session only `/tmp/vmdai_snap_<tool_call_id>.tga`, so they move to that path. Task 1 Step 7 also adds `**kw` to any other stub patched onto `VmdToolBridge.execute_tool` that Task 0 finds (the skeleton names only `tests/test_recorder_integration.py`; plans 02–04 may have added more).
4. **`BridgeSession` gains two optional fields** `exec_timeout_s` and `cancel_grace_s` (default None). `RuntimeApp._bridge_session` fills them from `settings.json` on every call, so a changed `tool_exec_timeout_s`/`cancel_grace_s` applies to the next tool call without a restart; the four skeleton fields are unchanged.
5. **Task 1 already sends `snapshot_path` and creates the per-session snapshot dir** (`RuntimeApp._snapshot_dir_for`), because `BridgeSession.snapshot_dir` is a Task 1 interface and the skeleton's Task 1 `tool_start` metadata includes `snapshot_path`. Task 3's `app.py` change is therefore the cleanup on `session.stop` (`_drop_snapshot_dir`); Task 3 owns reading, converting and deleting the file.
6. **Extra produced helpers:** `VmdToolBridge.get_call_session(call_key)`; a compat path where `resolve(tool_call_id)`/`get_pending_session(tool_call_id)` also find an unresolved token-session call (a client that posts by `tool_call_id` still works; Task 1 test `test_token_call_resolvable_by_tool_call_id`); `tcl_policy.is_protected_path`; `ClaudeToolLoop._result_format`, `_loop_guard_enabled`, `_guard_after_result`, `_skip_tool_block`, `_run_wrap_up`, `_recorder_update_meta`, `_provenance_digest`; module-level `_structured_summary`, `_apply_tool_mode`, `_append_to_tool_result`, `LOOP_GUARD_SKIP_RESULT`; `RuntimeApp._bridge_session`, `_snapshot_dir_for`, `_tool_timeouts`, `_on_late_result`, `_drop_snapshot_dir`, `_recorder_meta`; app-level `_canonical_sha256`, `_tools_as_sent`; test builder `fake_http.ollama_tool_calls`.
7. **The result dict carries `applied_text`** (and `image_b64`/`image_mime` for snapshots) in addition to the skeleton's keys: C3 requires `_recorder_record` to read the applied prefix from the product bridge's result, and the loop's image contract is unchanged.
8. **`cut_for_model` gains a keyword `note: str = ""`** (the line between head and tail). The skeleton signature has no way to place the C5 note; existing positional use is unaffected. The tail window is cut at its *first* newline (the boundary nearest its start), the head window at its last, so both halves start and end on line boundaries.
9. **`ClaudeToolLoop.last_wrap_up_error: Optional[str]`** is added so P07-T02 can put the wrap-up failure message into `request.finished.error` (C4: "`request.finished.error` holds the message").
10. **`on_late_result` payload** is specified: `on_late_result(session_id, call_key, info)` where `info` is the full result dict plus `late`, `request_id`, `tool_name` and `chat_dir` (P07-T03 needs these to push the late `tool.finished`).
11. **Task 7 may modify `runtime/vmd_ai_runtime/conversation.py`** (Step 5, only if Task 0 printed `STUB_KEEPS_NOTE False`): C5 joins head and tail *with* the note, so a compaction stub must find the note anywhere in the text, not only at its end.
12. **Counts in the C6 manifest** use the loop's own counters (tool calls counted in `_recorder_record`, rescued and truncated turns counted from `on_meta`), so they are correct after every turn rather than only once plan 02's `last_*` values are final.
13. **Task 11 (exit check) added** as a verification-only task.
14. **Note for plan 06 (executor.tcl):** `tcl_policy.split_statements` treats a full-line comment that ends in a backslash as swallowing the next line, exactly as Tcl does. The P06 executor's `info complete` split must do the same; a split that skips only the comment line would run `exec ls` from `# note \` + newline + `exec ls`, which C1 lists as allowed precisely because Tcl treats it as a comment.
15. **Review fixes (plan review, 2026-09-24).**
    - Tests that need `settings.json` (`test_bridge_session_for_token_session`, `test_product_run_manifest_has_provenance`, the Task 0 check) build the app with `make_app(..., settings_store=SettingsStore())`: plan 03 keeps `RuntimeApp` from building a store by itself (only `main.py` passes one), so `make_app(...)` alone has `settings_store is None`. `_tool_timeouts` accepts `cancel_grace_s: 0` (settings_store allows it; it means "do not wait") and returns `(None, None)` without a store.
    - Task 9's `run()` edits are written against plan 02's loop (`self._call_turn(...)`, `self._run_tool_block(...)`, `_finish_text_turn`), not today's inline dispatch chain, which plan 02 removed. Calls left in a turn after the guard's stop go through the new `_skip_tool_block`, so they keep their `tool.started`/`tool.finished` pair and tool_result without reaching the bridge, the recorder or the guard (new test `test_calls_after_stop_not_run`). The wrap-up seals through `_finish_text_turn` (sets `last_final_text_empty`, never appends an empty text block), numbers itself `last_turns + 1`, and gets plan 02's `on_text` sink so its chunks reach `on_event` too. The rescue-condition edit keeps plan 02's `rescue_mode != "off"`.
    - Task 10 anchors to plan 03's `loop.recorder = self._build_recorder_for_session(state)` line and to `_call_turn`. `tools_sha256` hashes the `tools` list in the provider's body shape (`_tools_as_sent`), so the C6 test "equals the hash of the first captured request's `tools`" holds for Ollama and OpenAI-compatible bodies too; the test is parametrised over anthropic-direct and ollama.
    - Task 7 gains `test_tool_finished_carries_output_path` (C5 test bullet: `tool.finished` carries `output_path` and `output_bytes`), driven through the real loop and bridge.
16. **Cross-plan fix (completeness pass): `system_prompt_sha256` includes the mode line.** P04-T06's `_system_prompt_for_request` sends `chatvmd_system_prompt(vision) + "\n\nMode: <mode>."` before the `<session>` block, and C6 says the hash covers "the prompt before the per-request `<session>` block". `_recorder_meta` therefore hashes the variant plus that mode line (plus the wiki addendum when wiki is on), and `test_system_prompt_sha_cwd_independent_wiki_dependent` also asserts that the hash equals the SHA-256 of the text `_system_prompt_for_request` produces before `"\n\n<session>\n"`. The test count is unchanged.
