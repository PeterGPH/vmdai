# ChatVMD Round 1 — Plan 02: ChatVMD R1 — M1 runtime foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the runtime an authenticated lifecycle (Host/Origin checks, launch token, announce, watch-stdin, a shutdown that does not deadlock, file logging) and add the loop integration surface: LoopOptions/RunContext, error classes, gated flags, events, canonical messages_out, rescue modes and a per-request loop_factory. S7 goldens stay unchanged.

**Architecture:** The runtime half (`server.py`, `launch.py`, `logging_utils.py`, `main.py`, `app.py`, `protocol.py`, `sessions.py`) gains the §2e security model: loopback Host/Origin checks, a 128-bit launch token printed in `VMDAI_READY` or written to a 0600 token file, token-authenticated sessions, `runtime.shutdown`, and a shutdown that runs `server.shutdown()` on its own thread. The loop half (`claude_loop.py`) gains the §2a surface: `ClaudeToolLoop(options=LoopOptions | None)` and `run(ctx=RunContext | None)`; every behaviour change is a `LoopOptions` field whose default is today's behaviour, streamers get `on_meta`/`opts`/`tool_mode` only when options are set, and the loop emits `on_event` items and canonical `messages_out` copies only when a ctx asks for them. `RuntimeApp` builds a fresh loop per request through `loop_factory`, so nothing is shared between requests.

**Tech Stack:** Python 3.9–3.12 standard library only (`http.server`, `urllib`, `logging.handlers`, `secrets`, `hmac`, `dataclasses`, `select`); pytest (plain functions, plan 01's `tests/conftest.py` fixtures).

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — §2a (Recommendation B, behaviour-flag inventory rows connect_retries, classify_errors, cancellable_backoff, first_byte_timeout_s, report_cancelled, turn_retry, raise_stream_errors, guard_truncation, rescue, max_turns; error classification; call_key; on_event; legacy callbacks; recorder chat_id), §2b (writes are incremental, canonical copies), §2c (wire encoding, rescued calls, tool.finished shape), §2d (shutdown, non-blocking launch, logging), §2e (Host and Origin checks, launch token, compatibility, input validation), §2f (rescue), §3 (server.py, main.py, app.py, protocol.py rows; RPC rows session.start and runtime.shutdown), §5 (429/5xx, 401/403, billing, 404, stream drop, SSE error, truncated turn, stop during backoff), §7 (logs), C6 (session.start `vmd_env`, `LoopOptions` asdict), C7 (product `num_ctx` default), S4, S7, S11, S12.

**Branch:** `chatvmd-r1-02-m1-runtime-foundation`, created from `main` after plan 01 (`chatvmd-r1-01-m0-guard-rails`) is merged.

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

- Every task ends with the S7 guard files green and untouched: `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_retry_pin.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_hashes.py -q`. If any golden differs, the change is wrong; never regenerate a golden.
- New test modules are plain pytest functions. They rely on plan 01's conftest (the `_hermetic` autouse fixture, `sleep_calls`) and on `pytest.ini` (`pythonpath = runtime tests`), so they import `vmd_ai_runtime.*` and `helpers.*` directly with no `sys.path` edits.
- Tests that fake a provider patch `urllib.request.urlopen` with `tests/helpers/fake_provider.FakeUrlopen`. It answers the Ollama probe paths itself, so plan 04's preflight (`/api/version`, `/api/ps`) does not break these tests.
- Tests that start `runtime/main.py` as a subprocess inherit the hermetic env (temp HOME), add `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, pass `--port 0`, `--store-dir` and `--log-file` under `tmp_path`, and never bind a fixed port.
- `integrations/scivisagentbench/vmd_ai_agent.py` is not edited by this plan.

## Review Focus

- A Host header that is missing or upper-case ('LOCALHOST:<port>'): the missing one gets 403, the upper-case one is accepted. Owner P02-T01: `test_missing_host_rejected` (and `test_localhost_host_accepted_case_insensitive`).
- SIGTERM while a worker thread is blocked in urlopen or a tool wait must still exit within 2 s. Owner P02-T04: `test_sigterm_during_active_request_exits_within_2s` (worker blocked in urlopen) and `test_sigterm_during_tool_wait_exits_within_2s` (worker blocked in `VmdToolBridge.execute_tool` waiting for VMD).
- A startup traceback before logging is configured must reach the merged pipe, with no READY line. Owner P02-T04: `test_startup_traceback_reaches_merged_pipe`.
- Stop during a 60 s Retry-After backoff must end the run at once with status cancelled. Owner P02-T06: `test_cancel_during_backoff_raises_quickly`.
- A test assigns app.claude_loop, then provider.set runs: the shared loop must not be reinstalled and the recorder must not leak across requests. Owner P02-T10: `test_provider_set_does_not_assign_loop`.

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `runtime/vmd_ai_runtime/server.py` | modify | Host/Origin 403, `/health` payload, ASCII JSON, daemon request threads |
| `runtime/vmd_ai_runtime/constants.py` | modify | `RUNTIME_PROTOCOL = 2`, `RUNTIME_VERSION = "0.3.0"` |
| `runtime/pyproject.toml` | modify | version 0.3.0 |
| `runtime/vmd_ai_runtime/launch.py` | create | launch token, token file, READY line |
| `runtime/vmd_ai_runtime/sessions.py` | modify | `authenticated`, `event_protocol`, `vmd_env`, `lock` on `SessionState` |
| `runtime/vmd_ai_runtime/protocol.py` | modify | `CHAT_ID_RE`, session.start params, `_sanitize_vmd_env`, `runtime.shutdown` |
| `runtime/vmd_ai_runtime/app.py` | modify | token auth, `_require_auth`, `runtime.shutdown`, loop factory, session lock, `RunContext` |
| `runtime/vmd_ai_runtime/logging_utils.py` | modify | root-logger rotating file handler, optional stderr |
| `runtime/main.py` | modify | `--port 0`, `--announce`, `--watch-stdin`, `--log-file`, shutdown thread, token file |
| `scripts/run_runtime.sh`, `scripts/dev_smoke.sh` | modify | print the token-file path; honour `VMD_AI_PYTHON`, `VMD_AI_PORT` and `VMD_AI_ATTACH` (§7) |
| `runtime/vmd_ai_runtime/claude_loop.py` | modify | `LoopOptions`, `RunContext`, error classes, transport and loop flags, events, `messages_out`, rescue modes |
| `tests/helpers/runtime_fixture.py` | create | in-process app, RPC and serve helpers (used by plans 03–07) |
| `tests/helpers/fake_provider.py` | create | routing fake `urlopen`, SSE/NDJSON builders, scripted `_call`, spy bridge, stub recorder |
| `tests/test_server_security.py`, `tests/test_launch_token.py`, `tests/test_logging_setup.py`, `tests/test_main_lifecycle.py`, `tests/test_loop_options.py`, `tests/test_stream_request_flags.py`, `tests/test_loop_flags.py`, `tests/test_loop_events.py`, `tests/test_rescue_modes.py`, `tests/test_loop_factory.py` | create | one module per task |
| `tests/test_benchmark_bridge_guard.py` | modify | product-options variant and call-meta tests (P02-T08) |
| `tests/test_py39_compat.py` | modify | add `vmd_ai_runtime.launch` to `RUNTIME_MODULES` |

## How to apply the edit steps

- "Replace" steps quote the exact current text (as it stands after the previous task) and the new text; apply them with the Edit tool using the quoted text as `old_string`. Every quoted block is unique in its file unless the step says "replace all".
- Line numbers refer to commit 6f5f937. Plan 01 adds the `_sleep = time.sleep` hook to `claude_loop.py`, which shifts later lines by a few; locate code by the quoted anchor text.
- Commands run from `/Users/pinhaogu/Documents/GitHub/vmdai`. `SUITE` below means `env -u VMD_AI_PROVIDER python -m pytest tests -q` (expected: `0 failed`, `1 xfailed`, under 60 s; the passed count grows with each task). `GUARDS` means `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_retry_pin.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_hashes.py -q` (expected: all passed).

---

### Task 0: Pre-flight

**Files:** none (read-only checks).

**Interfaces:**
- Consumes: from plan 01: tag `baseline-2026-09-24`; `pytest.ini` (`pythonpath = runtime tests`); `tests/conftest.py` autouse `_hermetic` and fixtures `sleep_calls`, `live_env`; `vmd_ai_runtime.claude_loop._sleep`; `tests/test_benchmark_bridge_guard.py` names `LEGACY_KWARGS`, `spy_bridge`, `run_guard`, `STRICT_BRIDGES`; `tests/test_py39_compat.py` `RUNTIME_MODULES`; `tests/test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint` marked `xfail(strict=True)`.
- Produces: branch `chatvmd-r1-02-m1-runtime-foundation`.

- [ ] **Step 1: Cut the branch from an up-to-date main**

```bash
git checkout main
git pull --ff-only
git tag -l baseline-2026-09-24
git checkout -b chatvmd-r1-02-m1-runtime-foundation
```

Expected: the tag line prints `baseline-2026-09-24`; the last command prints `Switched to a new branch 'chatvmd-r1-02-m1-runtime-foundation'`.

- [ ] **Step 2: Confirm the plan 01 interfaces this plan consumes**

```bash
grep -n "pythonpath" pytest.ini
grep -n "^_sleep = time.sleep" runtime/vmd_ai_runtime/claude_loop.py
grep -c "_sleep(wait)" runtime/vmd_ai_runtime/claude_loop.py
grep -n "def _hermetic\|def sleep_calls\|def live_env" tests/conftest.py
grep -n "^LEGACY_KWARGS\|^def spy_bridge\|^def run_guard\|^STRICT_BRIDGES" tests/test_benchmark_bridge_guard.py
grep -n "RUNTIME_MODULES" tests/test_py39_compat.py
python -m pytest tests/test_ollama_loop.py -q -rx -k test_unreachable_host_raises_with_hint
```

Expected: `pythonpath = runtime tests`; one `_sleep = time.sleep` line; `2`; three fixture lines (`live_env`, `_hermetic`, `sleep_calls`); four bridge-guard lines; at least one `RUNTIME_MODULES` line; and the pytest run ends with `47 deselected, 1 xfailed`, its `XFAIL tests/test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint - known Ollama bug …` line naming P04-T01. (The `xfail` decorator spans eight lines, so a `grep -B2` on the `def` line would not see it; ask pytest instead.) If anything is missing, stop: plan 01 is not merged.

- [ ] **Step 3: Read `run_guard` to confirm its contract**

```bash
sed -n '/^def run_guard/,/^    return calls/p' tests/test_benchmark_bridge_guard.py
```

Expected: the 19-line function `run_guard(loop: ClaudeToolLoop, bridge: Any, *, requests_out=None)`. It spies the bridge, serves `scripted_responses(_GOLDEN_PROVIDER[loop.provider_name])` through a `RecordingUrlopen` patched over `urllib.request.urlopen`, calls `loop.run(...)` without `ctx`, asserts `recorder.unconsumed == 0`, and returns one kwargs dict per `execute_tool` call (P01-T06 contract). P02-T08 calls it with an `openrouter` loop that has product options, so the three scripted OpenAI-style turns (finish reasons `tool_calls`, `tool_calls`, `stop`) must all be consumed.

- [ ] **Step 4: Record the baselines**

```bash
env -u VMD_AI_PROVIDER python -m pytest tests -q 2>&1 | tail -1
python -m pytest vmdbench/tests -q 2>&1 | tail -1
python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q 2>&1 | tail -1
```

Expected: `N passed, 1 xfailed, 10 subtests passed` (write N down as BASELINE; no failures, under 60 s). On the dev Mac with all of plan 01 merged N is 555, plan 01's own exit total (its P01-T10 step); elsewhere some Tcl tests skip, so use whatever N the run prints. Then `90 passed` (plus one warning and 5 subtests) and `62 passed` (plus 3 warnings).

No commit for this task.

---

### Task 1: P02-T01 — Host/Origin checks, /health payload, ASCII JSON

**Files:**
- Create: `tests/test_server_security.py`
- Modify: `runtime/vmd_ai_runtime/server.py:1-69` (whole file)
- Modify: `runtime/vmd_ai_runtime/constants.py:36` (append after the last line)
- Modify: `runtime/pyproject.toml:7`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `constants.RUNTIME_PROTOCOL = 2`
  - `constants.RUNTIME_VERSION = '0.3.0'`
  - server returns HTTP 403 with JSON-RPC error code FORBIDDEN for a bad Host or any Origin
  - GET /health -> {ok, pid, version, protocol}
  - _send_json uses ensure_ascii=True
  - (plan addition) `RpcHTTPServer.daemon_threads = True`, `RpcHTTPServer.block_on_close = False`, so request threads never delay exit (S4, used by P02-T04)

- [ ] **Step 1: Write the failing test**

Create `tests/test_server_security.py`:

```python
"""P02-T01: loopback Host/Origin checks, the /health payload and ASCII-only JSON (§2e, §2c, S11)."""
from __future__ import annotations

import json
import os
import socket
import threading
import urllib.request

import pytest

from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.server import RpcHTTPServer, create_server

START = {"jsonrpc": "2.0", "id": "1", "method": "session.start", "params": {"cwd": "."}}


@pytest.fixture
def port(tmp_path):
    app = RuntimeApp(store_dir=str(tmp_path / "chats"), provider_mode="mock",
                     enable_rag=False, enable_wiki=False)
    server = create_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield int(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _raw(port, request):
    """Send one raw HTTP request and return (status, body bytes)."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body


def _get(port, host, extra=""):
    request = f"GET /health HTTP/1.1\r\nHost: {host}\r\n{extra}Connection: close\r\n\r\n"
    return _raw(port, request.encode("ascii"))


def _post(port, host, payload, extra=""):
    body = json.dumps(payload).encode("ascii")
    head = (f"POST /rpc HTTP/1.1\r\nHost: {host}\r\n{extra}"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n")
    return _raw(port, head.encode("ascii") + body)


def _assert_forbidden(status, body):
    assert status == 403
    assert json.loads(body)["error"]["code"] == "FORBIDDEN"


def test_foreign_host_rejected(port):
    _assert_forbidden(*_get(port, f"192.168.1.20:{port}"))
    _assert_forbidden(*_get(port, f"127.0.0.1:{port + 1}"))
    _assert_forbidden(*_post(port, f"10.0.0.1:{port}", START))


def test_dns_rebinding_host_rejected(port):
    # A rebinding page makes attacker.example resolve to 127.0.0.1, but the
    # browser still sends its own host name in Host.
    _assert_forbidden(*_get(port, f"attacker.example:{port}"))
    _assert_forbidden(*_post(port, f"attacker.example:{port}", START))


def test_origin_header_rejected(port):
    good = f"127.0.0.1:{port}"
    _assert_forbidden(*_post(port, good, START, extra="Origin: http://evil.example\r\n"))
    _assert_forbidden(*_post(port, good, START, extra="Origin: null\r\n"))
    _assert_forbidden(*_get(port, good, extra="Origin: http://127.0.0.1\r\n"))


def test_missing_host_rejected(port):
    # HTTP/1.0 allows a request with no Host header; the runtime must not.
    _assert_forbidden(*_raw(port, b"GET /health HTTP/1.0\r\n\r\n"))
    _assert_forbidden(*_raw(port, b"POST /rpc HTTP/1.0\r\nContent-Length: 2\r\n\r\n{}"))


def test_localhost_host_accepted_case_insensitive(port):
    for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"LOCALHOST:{port}"):
        status, body = _get(port, host)
        assert status == 200, host
        assert json.loads(body)["ok"] is True
    status, body = _post(port, f"Localhost:{port}", START)
    assert status == 200
    assert "session_id" in json.loads(body)["result"]


def test_health_payload(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
        assert resp.headers["Content-Type"] == "application/json; charset=utf-8"
        payload = json.loads(resp.read())
    assert payload == {"ok": True, "pid": os.getpid(), "version": "0.3.0", "protocol": 2}


def test_ascii_wire(port):
    status, body = _post(port, f"127.0.0.1:{port}",
                         {"jsonrpc": "2.0", "id": "u", "method": "Å→°", "params": {}})
    assert status == 200
    assert all(byte < 0x80 for byte in body), body
    assert json.loads(body.decode("ascii"))["error"]["message"].endswith("Å→°")


def test_request_threads_do_not_block_exit():
    assert RpcHTTPServer.daemon_threads is True
    assert RpcHTTPServer.block_on_close is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_server_security.py -q`
Expected: `7 failed, 1 passed` — `test_foreign_host_rejected`, `test_dns_rebinding_host_rejected`, `test_origin_header_rejected` and `test_missing_host_rejected` fail with `assert 200 == 403`; `test_health_payload` fails on the dict (`{'ok': True} == {...}`); `test_ascii_wire` fails on `all(byte < 0x80 ...)`; `test_request_threads_do_not_block_exit` fails with `assert True is False` on `block_on_close` (`ThreadingHTTPServer` already sets `daemon_threads = True`). Only `test_localhost_host_accepted_case_insensitive` passes.

- [ ] **Step 3: Add the protocol constants**

Append to `runtime/vmd_ai_runtime/constants.py` (after `CONVERSATION_MODES = ...`):

```python

# Runtime RPC/auth protocol, reported in the READY line, /health and
# runtime.info (§2c). 2 = launch token + tool.ack. It is separate from the
# per-session event_protocol that session.start negotiates.
RUNTIME_PROTOCOL = 2
RUNTIME_VERSION = "0.3.0"
```

In `runtime/pyproject.toml` replace `version = "0.2.0"` with `version = "0.3.0"`.

- [ ] **Step 4: Rewrite `server.py`**

Replace the whole content of `runtime/vmd_ai_runtime/server.py` with:

```python
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Tuple

from .constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from .errors import RpcError


class RpcHTTPServer(ThreadingHTTPServer):
    # Request threads never keep the process alive and server_close() never
    # waits for them, so SIGTERM exits within 2 s while a handler is busy (S4).
    daemon_threads = True
    block_on_close = False

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass, app):
        super().__init__(server_address, RequestHandlerClass)
        self.app = app


# HTTP 403 body for a bad Host or any Origin header (§2e).
_FORBIDDEN = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {
        "code": "FORBIDDEN",
        "message": "forbidden: requests must use Host 127.0.0.1:<port> or localhost:<port> and carry no Origin header",
        "data": {},
    },
}


class RpcRequestHandler(BaseHTTPRequestHandler):
    server: RpcHTTPServer

    def _send_json(self, payload: Any, status: int = 200) -> None:
        # ASCII-only JSON: every non-ASCII character travels as a \uXXXX
        # escape, so a client that decodes the body with the wrong charset
        # still gets the right text (defence in depth, §2c Wire encoding).
        raw = json.dumps(payload, ensure_ascii=True).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _request_allowed(self) -> bool:
        """Host/Origin check against DNS rebinding and cross-site POSTs (§2e).

        Host must be 127.0.0.1:<port> or localhost:<port> (case-insensitive),
        and there must be no Origin header at all: browsers send Origin on
        POST, while Tcl's http package and urllib never do.
        """
        if self.headers.get("Origin") is not None:
            return False
        host = str(self.headers.get("Host") or "").strip().lower()
        port = int(self.server.server_port)
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self._request_allowed():
            self._send_json(_FORBIDDEN, status=403)
            return
        if self.path == "/health":
            self._send_json({
                "ok": True,
                "pid": os.getpid(),
                "version": RUNTIME_VERSION,
                "protocol": RUNTIME_PROTOCOL,
            })
            return
        self._send_json({"ok": False, "error": "not_found"}, status=404)

    def do_POST(self):
        if not self._request_allowed():
            self._send_json(_FORBIDDEN, status=403)
            return
        if self.path != "/rpc":
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": "INVALID_JSON",
                        "message": "invalid JSON request",
                        "data": {},
                    },
                },
                status=400,
            )
            return

        session_token = self.headers.get("X-Session-Token", "")
        result = self.server.app.handle_rpc(body, session_token=session_token)
        self._send_json(result, status=200)

    def log_message(self, format, *args):
        return


def create_server(app, host: str = "127.0.0.1", port: int = 8765) -> RpcHTTPServer:
    normalized = str(host or "127.0.0.1").strip().lower()
    if normalized not in ("127.0.0.1", "localhost"):
        raise RpcError("BIND_FORBIDDEN", "Runtime may only bind to loopback addresses", {"host": host})
    bind_host = "127.0.0.1"
    return RpcHTTPServer((bind_host, int(port)), RpcRequestHandler, app)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_server_security.py tests/test_runtime_integration.py tests/test_security_notice.py -q`
Expected: all passed (8 in the new module; the in-process `RuntimeHarness` uses `http://127.0.0.1:<port>`, so urllib's Host header passes the check).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed.

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/server.py runtime/vmd_ai_runtime/constants.py runtime/pyproject.toml tests/test_server_security.py
git commit -m "feat(runtime): Host/Origin checks, /health protocol payload, ASCII-only JSON

Refuse any request whose Host is not 127.0.0.1:<port>/localhost:<port> or
that carries an Origin header (HTTP 403, code FORBIDDEN). /health reports
pid, version 0.3.0 and runtime protocol 2. Responses are ASCII-only JSON.
Request threads are daemons so shutdown never waits for them.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: P02-T02 — Launch token module and authenticated sessions

**Files:**
- Create: `runtime/vmd_ai_runtime/launch.py`
- Create: `tests/helpers/runtime_fixture.py`
- Create: `tests/test_launch_token.py`
- Modify: `runtime/vmd_ai_runtime/app.py:13-35` (imports), `:38-50` (constructor head), `:187-220` (`_dispatch` head and `session.start`)
- Modify: `runtime/vmd_ai_runtime/sessions.py:20-43`
- Modify: `runtime/vmd_ai_runtime/protocol.py:1-6`, `:38`, `:49-55`, `:66`, `:93-104`
- Modify: `tests/test_py39_compat.py` (`RUNTIME_MODULES`)

**Interfaces:**
- Consumes: `constants.RUNTIME_PROTOCOL, RUNTIME_VERSION` (P02-T01)
- Produces:
  - `launch.generate_launch_token() -> str` (32 hex chars)
  - `launch.token_file_path(port: int, home: Optional[str] = None) -> Path`
  - `launch.write_token_file(port: int, pid: int, token: str, protocol: int = 2, home: Optional[str] = None) -> Path`
  - `launch.read_token_file(path: Path) -> Dict[str, Any]`
  - `launch.remove_token_file(path: Path) -> None`
  - `launch.format_ready_line(port: int, pid: int, version: str, protocol: int, launch_token: str) -> str`
  - `RuntimeApp(..., launch_token: Optional[str] = None, allow_tokenless_v1: bool = True, on_shutdown: Optional[Callable[[], None]] = None)`
  - `SessionState.authenticated: bool; SessionState.event_protocol: int = 1; SessionState.vmd_env: Optional[Dict[str, str]]`
  - `RuntimeApp._require_auth(state) -> None` (raises AUTH_REQUIRED)
  - token session.start result adds `event_protocol` and `runtime{version,pid}`
  - RPC `runtime.shutdown {launch_token} -> {ok}`
  - `protocol.CHAT_ID_RE`; `protocol._sanitize_vmd_env(value) -> Optional[Dict[str, str]]` (vmd_version, arch, tcl_patchlevel, tk_patchlevel; ≤ 64 chars each)
  - `helpers.runtime_fixture.make_app(tmp_path, **kw) -> RuntimeApp; start_token_session(app, token, *, event_protocol=1, cwd=None, vmd_env=None) -> Dict; rpc(app, method, params, session=None) -> Dict; serve_app(app) -> ContextManager[int]`
  - (plan additions) `helpers.runtime_fixture.start_tokenless_session(app, *, cwd=None) -> Dict`; `helpers.runtime_fixture.wait_idle(app, session_id, timeout=5.0) -> None`; `SessionManager.create_session(cwd, chat_id, *, authenticated=False, event_protocol=1, vmd_env=None)`; `protocol.EVENT_PROTOCOLS = (1, 2)`

- [ ] **Step 1: Write the test helper**

Create `tests/helpers/runtime_fixture.py`:

```python
"""In-process runtime helpers (plan 02, P02-T02).

Build a RuntimeApp against temp dirs, start tokenless or token sessions,
call RPCs without HTTP, wait for a request to finish, and serve the app on
an ephemeral port. Plans 03-07 build on these.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from vmd_ai_runtime.app import RuntimeApp
from vmd_ai_runtime.server import create_server


def make_app(tmp_path: Path, **kw: Any) -> RuntimeApp:
    """RuntimeApp with its chat store under ``tmp_path`` (mock provider, no RAG, no wiki by default)."""
    kw.setdefault("store_dir", str(Path(tmp_path) / "chats"))
    kw.setdefault("provider_mode", "mock")
    kw.setdefault("enable_rag", False)
    kw.setdefault("enable_wiki", False)
    return RuntimeApp(**kw)


def rpc(app: RuntimeApp, method: str, params: Optional[Dict[str, Any]] = None,
        session: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dispatch one JSON-RPC call in process; returns the whole response ({result} or {error})."""
    body = dict(params or {})
    token = ""
    if session is not None:
        body.setdefault("session_id", session["session_id"])
        token = session["session_token"]
    payload = {"jsonrpc": "2.0", "id": "t", "method": method, "params": body}
    return app.handle_rpc(payload, session_token=token)


def _default_cwd() -> str:
    # The hermetic conftest points HOME at a temp dir, so the recorder's
    # <cwd>/.vmdai_runs never lands in the checkout.
    return os.path.expanduser("~")


def start_tokenless_session(app: RuntimeApp, *, cwd: Optional[str] = None) -> Dict[str, Any]:
    resp = rpc(app, "session.start", {"cwd": cwd or _default_cwd()})
    if "result" not in resp:
        raise AssertionError(f"session.start failed: {resp}")
    return resp["result"]


def start_token_session(app: RuntimeApp, token: str, *, event_protocol: int = 1,
                        cwd: Optional[str] = None,
                        vmd_env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "cwd": cwd or _default_cwd(),
        "ui_mode": "panel",
        "client_version": "test",
        "platform": "test",
        "launch_token": token,
        "event_protocol": event_protocol,
    }
    if vmd_env is not None:
        params["vmd_env"] = vmd_env
    resp = rpc(app, "session.start", params)
    if "result" not in resp:
        raise AssertionError(f"session.start failed: {resp}")
    return resp["result"]


def wait_idle(app: RuntimeApp, session_id: str, timeout: float = 5.0) -> None:
    """Block until the session has no active request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = app.sessions.get(session_id)
        if state is None or state.active_request is None:
            return
        time.sleep(0.02)
    raise AssertionError(f"request in {session_id} did not finish within {timeout} s")


@contextlib.contextmanager
def serve_app(app: RuntimeApp) -> Iterator[int]:
    """Serve ``app`` on 127.0.0.1:<ephemeral>; yields the port."""
    server = create_server(app, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield int(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_launch_token.py`:

```python
"""P02-T02: launch token, token file, READY line and authenticated sessions (§2e, C6, S11)."""
from __future__ import annotations

import json
import os
import stat

import pytest

from helpers.runtime_fixture import make_app, rpc, start_token_session, start_tokenless_session
from vmd_ai_runtime.errors import RpcError
from vmd_ai_runtime.launch import (
    format_ready_line,
    generate_launch_token,
    read_token_file,
    remove_token_file,
    token_file_path,
    write_token_file,
)
from vmd_ai_runtime.protocol import CHAT_ID_RE, validate_method_params

TOKEN = "0123456789abcdef0123456789abcdef"
TODAY_START_KEYS = {"session_id", "session_token", "capabilities", "defaults",
                    "chat_id", "provider", "agent_loop"}


def _code(resp):
    assert "error" in resp, resp
    return resp["error"]["code"]


def test_generate_token_128_bits():
    first, second = generate_launch_token(), generate_launch_token()
    assert len(first) == 32
    assert first == first.lower() and int(first, 16) >= 0
    assert first != second


def test_token_file_mode_0600_and_fields(tmp_path):
    home = str(tmp_path)
    path = token_file_path(8765, home)
    assert path == tmp_path / ".vmdai" / "run" / "runtime-8765.json"
    path.parent.mkdir(parents=True)
    path.write_text("stale")
    os.chmod(path, 0o644)
    assert write_token_file(8765, 4321, TOKEN, 2, home=home) == path
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert read_token_file(path) == {"port": 8765, "pid": 4321, "token": TOKEN, "protocol": 2}
    assert list(path.parent.glob("*.tmp")) == []
    remove_token_file(path)
    assert not path.exists()
    remove_token_file(path)  # a second remove is a no-op


def test_ready_line_format():
    line = format_ready_line(51234, 4321, "0.3.0", 2, TOKEN)
    assert line == ('VMDAI_READY {"port":51234,"pid":4321,"version":"0.3.0",'
                    '"protocol":2,"launch_token":"' + TOKEN + '"}')
    assert json.loads(line.split(" ", 1)[1])["launch_token"] == TOKEN


def test_tokenless_start_rejected_when_announced(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN, allow_tokenless_v1=False)
    assert _code(rpc(app, "session.start", {"cwd": str(tmp_path)})) == "AUTH_REQUIRED"
    assert app.store.list_chats() == []  # a refused start creates no chat


def test_tokenless_start_accepted_without_announce(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    result = start_tokenless_session(app, cwd=str(tmp_path))
    assert set(result) == TODAY_START_KEYS  # exactly today's fields
    state = app.sessions.get(result["session_id"])
    assert state.authenticated is False
    assert state.event_protocol == 1


def test_wrong_launch_token_auth_failed(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN, allow_tokenless_v1=False)
    resp = rpc(app, "session.start", {"cwd": str(tmp_path), "launch_token": "f" * 32})
    assert _code(resp) == "AUTH_FAILED"
    no_token = make_app(tmp_path / "other")
    resp = rpc(no_token, "session.start", {"cwd": str(tmp_path), "launch_token": TOKEN})
    assert _code(resp) == "AUTH_FAILED"


def test_vmd_env_sanitised_and_kept_only_for_token_sessions(tmp_path):
    env = {"vmd_version": "1.9.4a57", "arch": "MACOSXARM64", "tcl_patchlevel": "8.6.12",
           "tk_patchlevel": "x" * 100, "evil": "rm -rf ~", "nested": {"a": 1}}
    app = make_app(tmp_path, launch_token=TOKEN)
    token_session = start_token_session(app, TOKEN, cwd=str(tmp_path), vmd_env=env)
    assert app.sessions.get(token_session["session_id"]).vmd_env == {
        "vmd_version": "1.9.4a57", "arch": "MACOSXARM64",
        "tcl_patchlevel": "8.6.12", "tk_patchlevel": "x" * 64,
    }
    plain = rpc(app, "session.start", {"cwd": str(tmp_path), "vmd_env": env})["result"]
    assert app.sessions.get(plain["session_id"]).vmd_env is None
    assert "vmd_env" not in validate_method_params("session.start", {"vmd_env": "text"})


def test_runtime_shutdown_requires_launch_token(tmp_path):
    calls = []
    app = make_app(tmp_path, launch_token=TOKEN, on_shutdown=lambda: calls.append("stop"))
    assert _code(rpc(app, "runtime.shutdown", {})) == "INVALID_PARAMS"
    assert _code(rpc(app, "runtime.shutdown", {"launch_token": "0" * 32})) == "AUTH_FAILED"
    assert calls == []
    assert rpc(app, "runtime.shutdown", {"launch_token": TOKEN})["result"] == {"ok": True}
    assert calls == ["stop"]
    no_token = make_app(tmp_path / "other")
    assert _code(rpc(no_token, "runtime.shutdown", {"launch_token": TOKEN})) == "AUTH_FAILED"


def test_chat_id_validation():
    good = "chat_0123456789ab"
    assert CHAT_ID_RE.fullmatch(good)
    assert validate_method_params("chat.resume", {"session_id": "s", "chat_id": good})["chat_id"] == good
    assert validate_method_params("chat.send", {"session_id": "s", "text": "hi", "chat_id": ""})["chat_id"] == ""
    for bad in ("../etc", "chat_../../x1", "chat_ABCDEF012345", "chat_0123",
                "chat_0123456789abc", "x"):
        for method, params in (
            ("chat.resume", {"session_id": "s", "chat_id": bad}),
            ("chat.history.get", {"session_id": "s", "chat_id": bad}),
            ("chat.send", {"session_id": "s", "text": "hi", "chat_id": bad}),
        ):
            with pytest.raises(RpcError) as info:
                validate_method_params(method, params)
            assert info.value.code == "INVALID_PARAMS", (method, bad)


def test_event_protocol_values(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    one = start_token_session(app, TOKEN, event_protocol=1, cwd=str(tmp_path))
    assert one["event_protocol"] == 1
    assert one["runtime"] == {"version": "0.3.0", "pid": os.getpid()}
    assert TODAY_START_KEYS <= set(one)
    # The M1 runtime speaks display protocol 1 only; plan 07 negotiates 2.
    two = start_token_session(app, TOKEN, event_protocol=2, cwd=str(tmp_path))
    assert two["event_protocol"] == 1
    assert app.sessions.get(two["session_id"]).authenticated is True
    for bad in (3, 0, "abc"):
        resp = rpc(app, "session.start",
                   {"cwd": str(tmp_path), "launch_token": TOKEN, "event_protocol": bad})
        assert _code(resp) == "INVALID_PARAMS", bad


def test_require_auth_raises_for_tokenless(tmp_path):
    app = make_app(tmp_path, launch_token=TOKEN)
    plain = start_tokenless_session(app, cwd=str(tmp_path))
    with pytest.raises(RpcError) as info:
        app._require_auth(app.sessions.get(plain["session_id"]))
    assert info.value.code == "AUTH_REQUIRED"
    token_session = start_token_session(app, TOKEN, cwd=str(tmp_path))
    app._require_auth(app.sessions.get(token_session["session_id"]))  # no raise
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_launch_token.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'vmd_ai_runtime.launch'`.

- [ ] **Step 4: Create `launch.py`**

Create `runtime/vmd_ai_runtime/launch.py`:

```python
"""launch.py - launch token, token file and READY line (§2e, §2d).

The runtime makes a 128-bit launch token at start. Under --announce it is
printed once, in the READY line on stdout. Otherwise (attach mode) it is
written to ~/.vmdai/run/runtime-<port>.json with mode 0600 and removed on a
clean exit. Stdlib only; imports on Python 3.9.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any, Dict, Optional

READY_PREFIX = "VMDAI_READY "


def generate_launch_token() -> str:
    """128 random bits as 32 lowercase hex characters."""
    return secrets.token_hex(16)


def token_file_path(port: int, home: Optional[str] = None) -> Path:
    base = Path(home) if home is not None else Path(os.path.expanduser("~"))
    return base / ".vmdai" / "run" / f"runtime-{int(port)}.json"


def write_token_file(
    port: int,
    pid: int,
    token: str,
    protocol: int = 2,
    home: Optional[str] = None,
) -> Path:
    """Write {port, pid, token, protocol} with mode 0600, atomically."""
    path = token_file_path(port, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(path.parent), 0o700)
    except OSError:
        pass
    payload = json.dumps({
        "port": int(port),
        "pid": int(pid),
        "token": str(token),
        "protocol": int(protocol),
    })
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # the umask may have narrowed it; never widen past 0600
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(payload)
    os.replace(str(tmp), str(path))
    return path


def read_token_file(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="ascii"))


def remove_token_file(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def format_ready_line(port: int, pid: int, version: str, protocol: int, launch_token: str) -> str:
    """VMDAI_READY {"port":…,"pid":…,"version":…,"protocol":2,"launch_token":…}"""
    payload = {
        "port": int(port),
        "pid": int(pid),
        "version": str(version),
        "protocol": int(protocol),
        "launch_token": str(launch_token),
    }
    return READY_PREFIX + json.dumps(payload, separators=(",", ":"))
```

- [ ] **Step 5: Add the session fields**

In `runtime/vmd_ai_runtime/sessions.py` replace:

```python
    queue: EventQueue = field(default_factory=EventQueue)
    active_request: Optional[RequestState] = None
```

with:

```python
    queue: EventQueue = field(default_factory=EventQueue)
    active_request: Optional[RequestState] = None
    # True when session.start carried the runtime's launch token (§2e).
    # Tokenless sessions keep today's methods and fields; privileged calls
    # check this flag through RuntimeApp._require_auth.
    authenticated: bool = False
    # Negotiated display-event protocol (§2c). The M1 runtime answers 1.
    event_protocol: int = 1
    # Sanitised VMD/Tcl versions from session.start (C6); token sessions only.
    vmd_env: Optional[Dict[str, str]] = None
```

and replace:

```python
    def create_session(self, cwd: str, chat_id: str) -> SessionState:
        root = os.path.realpath(cwd or os.getcwd())
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        token = uuid.uuid4().hex
        state = SessionState(session_id=sid, session_token=token, cwd=root, chat_id=chat_id)
```

with:

```python
    def create_session(
        self,
        cwd: str,
        chat_id: str,
        *,
        authenticated: bool = False,
        event_protocol: int = 1,
        vmd_env: Optional[Dict[str, str]] = None,
    ) -> SessionState:
        root = os.path.realpath(cwd or os.getcwd())
        sid = f"sess_{uuid.uuid4().hex[:12]}"
        token = uuid.uuid4().hex
        state = SessionState(
            session_id=sid,
            session_token=token,
            cwd=root,
            chat_id=chat_id,
            authenticated=bool(authenticated),
            event_protocol=int(event_protocol),
            vmd_env=dict(vmd_env) if vmd_env else None,
        )
```

- [ ] **Step 6: Validate the new params in `protocol.py`**

Replace the module head:

```python
from __future__ import annotations

from typing import Any, Dict

from .constants import CONVERSATION_MODES
from .errors import RpcError
```

with:

```python
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .constants import CONVERSATION_MODES
from .errors import RpcError

# Chat ids are minted as chat_<12 hex> (store.py). Anything else is refused
# before it can reach a filesystem path (§2e Input validation).
CHAT_ID_RE = re.compile(r"chat_[0-9a-f]{12}")

# Display-event protocols a client may ask for in session.start (§2c).
EVENT_PROTOCOLS = (1, 2)

# session.start vmd_env (C6): at most these four string fields, 64 chars each.
VMD_ENV_KEYS = ("vmd_version", "arch", "tcl_patchlevel", "tk_patchlevel")
VMD_ENV_MAX_CHARS = 64
```

Replace `def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:` with:

```python
def _as_chat_id(value: Any, field: str = "chat_id", required: bool = True) -> str:
    text = _as_str(value, field, required=required)
    if text and CHAT_ID_RE.fullmatch(text) is None:
        raise RpcError(
            "INVALID_PARAMS",
            f"{field} is invalid",
            {"pattern": "^chat_[0-9a-f]{12}$"},
        )
    return text


def _sanitize_vmd_env(value: Any) -> Optional[Dict[str, str]]:
    """Keep the four known vmd_env fields as strings of at most 64 chars (C6)."""
    if not isinstance(value, dict):
        return None
    out: Dict[str, str] = {}
    for key in VMD_ENV_KEYS:
        raw = value.get(key)
        if raw is None or isinstance(raw, (dict, list, tuple, bool)):
            continue
        text = str(raw).strip()[:VMD_ENV_MAX_CHARS]
        if text:
            out[key] = text
    return out or None


def validate_rpc_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
```

Replace the `session.start` branch:

```python
    if method == "session.start":
        return {
            "cwd": _as_str(p.get("cwd") or ".", "cwd", required=False) or ".",
            "ui_mode": _as_str(p.get("ui_mode") or "qt", "ui_mode", required=False) or "qt",
            "client_version": _as_str(p.get("client_version") or "dev", "client_version", required=False) or "dev",
            "platform": _as_str(p.get("platform") or "unknown", "platform", required=False) or "unknown",
        }
```

with:

```python
    if method == "session.start":
        out = {
            "cwd": _as_str(p.get("cwd") or ".", "cwd", required=False) or ".",
            "ui_mode": _as_str(p.get("ui_mode") or "qt", "ui_mode", required=False) or "qt",
            "client_version": _as_str(p.get("client_version") or "dev", "client_version", required=False) or "dev",
            "platform": _as_str(p.get("platform") or "unknown", "platform", required=False) or "unknown",
        }
        # New params are passed through only when present, so a tokenless
        # client gets exactly today's dict.
        if p.get("launch_token") not in (None, ""):
            out["launch_token"] = _as_str(p.get("launch_token"), "launch_token")
        if p.get("event_protocol") is not None:
            event_protocol = _as_int(p.get("event_protocol"), "event_protocol", minimum=1)
            if event_protocol not in EVENT_PROTOCOLS:
                raise RpcError(
                    "INVALID_PARAMS",
                    "event_protocol must be 1 or 2",
                    {"allowed": list(EVENT_PROTOCOLS)},
                )
            out["event_protocol"] = event_protocol
        vmd_env = _sanitize_vmd_env(p.get("vmd_env"))
        if vmd_env is not None:
            out["vmd_env"] = vmd_env
        return out

    if method == "runtime.shutdown":
        return {"launch_token": _as_str(p.get("launch_token"), "launch_token")}
```

In the `chat.send` branch replace:

```python
            "chat_id": _as_str(p.get("chat_id"), "chat_id", required=False),
```

with:

```python
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id", required=False),
```

Replace the `chat.history.get` and `chat.resume` branches' chat_id line. Replace:

```python
    if method == "chat.history.get":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_str(p.get("chat_id"), "chat_id"),
```

with:

```python
    if method == "chat.history.get":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id"),
```

and replace:

```python
    if method == "chat.resume":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_str(p.get("chat_id"), "chat_id"),
        }
```

with:

```python
    if method == "chat.resume":
        return {
            "session_id": _as_str(p.get("session_id"), "session_id"),
            "chat_id": _as_chat_id(p.get("chat_id"), "chat_id"),
        }
```

- [ ] **Step 7: Authenticate sessions in `app.py`**

Replace the imports:

```python
import os
import threading
from typing import Any, Dict
```

with:

```python
import hmac
import os
import threading
from typing import Any, Callable, Dict, Optional
```

Replace `from .constants import CAPABILITIES, DEFAULT_SETTINGS` with `from .constants import CAPABILITIES, DEFAULT_SETTINGS, RUNTIME_VERSION`, and `from .sessions import RequestState, SessionManager` with `from .sessions import RequestState, SessionManager, SessionState`.

Replace the constructor head:

```python
        enable_wiki: bool = True,
    ):
        self.sessions = SessionManager()
```

with:

```python
        enable_wiki: bool = True,
        launch_token: Optional[str] = None,
        allow_tokenless_v1: bool = True,
        on_shutdown: Optional[Callable[[], None]] = None,
    ):
        self.sessions = SessionManager()
        # Launch token (§2e). main.py generates it; None (in-process tests)
        # means no session can authenticate and runtime.shutdown is refused.
        # allow_tokenless_v1 is False under --announce, so a tokenless
        # session.start is accepted only from old plugins and dev scripts.
        self.launch_token: Optional[str] = str(launch_token) if launch_token else None
        self.allow_tokenless_v1 = bool(allow_tokenless_v1)
        self._on_shutdown = on_shutdown
```

Replace the head of `_dispatch` through the `create_session` call:

```python
    def _dispatch(self, method: str, params: Dict[str, Any], session_token: str) -> Dict[str, Any]:

        # ---- Session lifecycle ----

        if method == "session.start":
            chat_id = self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(cwd=params["cwd"], chat_id=chat_id)
```

with:

```python
    def _token_matches(self, candidate: str) -> bool:
        if not self.launch_token or not candidate:
            return False
        return hmac.compare_digest(
            str(candidate).encode("utf-8"), self.launch_token.encode("utf-8")
        )

    def _require_auth(self, state: SessionState) -> None:
        """Raise AUTH_REQUIRED unless ``state`` was started with the launch token.

        Privileged calls (§2e) check this: provider.set with base_url,
        options or profile; settings.json writes; session.set_cwd; and
        models.list/provider.test with an arbitrary base_url.
        """
        if not getattr(state, "authenticated", False):
            raise RpcError(
                "AUTH_REQUIRED",
                "this call needs a session started with the launch token",
            )

    def _dispatch(self, method: str, params: Dict[str, Any], session_token: str) -> Dict[str, Any]:

        # ---- Runtime lifecycle ----

        if method == "runtime.shutdown":
            if not self._token_matches(params["launch_token"]):
                raise RpcError("AUTH_FAILED", "invalid launch token")
            if self.logger:
                self.logger.info("runtime.shutdown requested over RPC")
            if self._on_shutdown is not None:
                self._on_shutdown()
            return {"ok": True}

        # ---- Session lifecycle ----

        if method == "session.start":
            launch_token = str(params.get("launch_token") or "")
            authenticated = False
            if launch_token:
                if not self._token_matches(launch_token):
                    raise RpcError("AUTH_FAILED", "invalid launch token")
                authenticated = True
            elif not self.allow_tokenless_v1:
                raise RpcError(
                    "AUTH_REQUIRED",
                    "this runtime was started with --announce; "
                    "session.start needs the launch token",
                )
            chat_id = self.store.create_chat(title_hint="VMD AI Chat")
            state = self.sessions.create_session(
                cwd=params["cwd"],
                chat_id=chat_id,
                authenticated=authenticated,
                # M1 speaks display protocol 1 only; plan 07 negotiates 2.
                event_protocol=1,
                vmd_env=params.get("vmd_env") if authenticated else None,
            )
```

Replace the `session.start` return:

```python
            return {
                "session_id": state.session_id,
                "session_token": state.session_token,
                "capabilities": CAPABILITIES,
                "defaults": dict(state.settings),
                "chat_id": chat_id,
                "provider": self.provider_name,
                "agent_loop": self.claude_loop is not None,
            }
```

with:

```python
            result = {
                "session_id": state.session_id,
                "session_token": state.session_token,
                "capabilities": CAPABILITIES,
                "defaults": dict(state.settings),
                "chat_id": chat_id,
                "provider": self.provider_name,
                "agent_loop": self.claude_loop is not None,
            }
            if authenticated:
                result["event_protocol"] = state.event_protocol
                result["runtime"] = {"version": RUNTIME_VERSION, "pid": os.getpid()}
            return result
```

- [ ] **Step 8: Register the new module for the 3.9 import check**

In `tests/test_py39_compat.py`, add the line `    "vmd_ai_runtime.launch",` as the last element of the `RUNTIME_MODULES = [` list.

Run: `grep -n '"vmd_ai_runtime.launch"' tests/test_py39_compat.py`
Expected: one line.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_launch_token.py tests/test_protocol.py tests/test_py39_compat.py -q`
Expected: all passed (11 in `test_launch_token.py`; `test_py39_compat.py` passes on the dev Mac, where `/usr/bin/python3` is 3.9.6, and skips elsewhere).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed.

- [ ] **Step 10: Commit**

```bash
git add runtime/vmd_ai_runtime/launch.py runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/sessions.py runtime/vmd_ai_runtime/protocol.py tests/helpers/runtime_fixture.py tests/test_launch_token.py tests/test_py39_compat.py
git commit -m "feat(runtime): launch token, token-authenticated sessions, runtime.shutdown

launch.py makes the 128-bit token, the 0600 token file and the READY line.
session.start with launch_token authenticates the session (event_protocol,
runtime{version,pid} in the result); a tokenless start is refused when the
runtime runs under --announce. vmd_env is sanitised and kept for token
sessions only. chat_id must match ^chat_[0-9a-f]{12}$. runtime.shutdown
needs the launch token. tests/helpers/runtime_fixture.py builds apps.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 3: P02-T03 — Rotating file logging; no stderr under announce

**Files:**
- Create: `tests/test_logging_setup.py`
- Modify: `runtime/vmd_ai_runtime/logging_utils.py:1-33` (whole file)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `configure_logging(level: str = 'INFO', *, log_path: Optional[str] = None, stderr: bool = True) -> logging.Logger`
  - `default_log_path(home: Optional[str] = None) -> str` (~/.vmdai/logs/runtime.log)
  - (plan additions) `logging_utils.LOG_MAX_BYTES = 2 * 1024 * 1024`, `logging_utils.LOG_BACKUP_COUNT = 3`; installed handlers carry the attribute `_vmdai_handler = True`

- [ ] **Step 1: Write the failing test**

Create `tests/test_logging_setup.py`:

```python
"""P02-T03: rotating file logging on the root logger; no stderr under --announce (§2d, §7)."""
from __future__ import annotations

import logging
import logging.handlers
import subprocess
import sys
from pathlib import Path

import pytest

from vmd_ai_runtime.logging_utils import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    configure_logging,
    default_log_path,
)

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


@pytest.fixture(autouse=True)
def _restore_root_logging():
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    for handler in list(root.handlers):
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def _installed():
    return [h for h in logging.getLogger().handlers if getattr(h, "_vmdai_handler", False)]


def _flush():
    for handler in _installed():
        handler.flush()


def test_file_handler_on_root_captures_vmdai_loggers(tmp_path):
    log = tmp_path / "logs" / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=False)
    logging.getLogger("vmdai.claude_loop").warning("loop-warning")
    logging.getLogger("vmdai.tool_bridge").info("bridge-info")
    logging.getLogger("vmd_ai_runtime").info("runtime-info")
    _flush()
    text = log.read_text(encoding="utf-8")
    for needle in ("loop-warning", "bridge-info", "runtime-info", "vmdai.claude_loop"):
        assert needle in text
    assert default_log_path(str(tmp_path)) == str(tmp_path / ".vmdai" / "logs" / "runtime.log")


def test_no_stderr_output_when_disabled(tmp_path):
    log = tmp_path / "runtime.log"
    code = "\n".join([
        "import logging, sys",
        f"sys.path.insert(0, {str(RUNTIME)!r})",
        "from vmd_ai_runtime.logging_utils import configure_logging",
        f"configure_logging('INFO', log_path={str(log)!r}, stderr=False)",
        "logging.getLogger('vmdai.claude_loop').warning('vmdai-warning')",
        "logging.getLogger('vmd_ai_runtime').error('runtime-error')",
    ])
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert proc.stderr == ""
    text = log.read_text(encoding="utf-8")
    assert "vmdai-warning" in text and "runtime-error" in text


def test_rotating_handler_limits(tmp_path):
    log = tmp_path / "deep" / "dir" / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=False)
    rotating = [h for h in _installed() if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == LOG_MAX_BYTES == 2 * 1024 * 1024
    assert rotating[0].backupCount == LOG_BACKUP_COUNT == 3
    assert log.parent.is_dir()


def test_idempotent(tmp_path):
    log = tmp_path / "runtime.log"
    configure_logging("INFO", log_path=str(log), stderr=True)
    logger = configure_logging("DEBUG", log_path=str(log), stderr=True)
    assert logger.name == "vmd_ai_runtime"
    assert logger.handlers == []  # records propagate to root, so no duplicate lines
    assert sorted(type(h).__name__ for h in _installed()) == ["RotatingFileHandler", "StreamHandler"]
    assert logging.getLogger().level == logging.DEBUG
    logging.getLogger("vmdai.claude_loop").warning("exactly-once")
    _flush()
    assert log.read_text(encoding="utf-8").count("exactly-once") == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_logging_setup.py -q`
Expected: collection error `ImportError: cannot import name 'LOG_BACKUP_COUNT' from 'vmd_ai_runtime.logging_utils'`.

- [ ] **Step 3: Rewrite `logging_utils.py`**

Replace the whole content of `runtime/vmd_ai_runtime/logging_utils.py` with:

```python
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from typing import Any, Optional

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([^\s,;]+)"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)(session[_-]?token\s*[=:]\s*)([^\s,;]+)"),
]

# ~/.vmdai/logs/runtime.log rotates at 2 MiB and keeps three old files (§7 Logs).
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
_FILE_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_STDERR_FORMAT = "[vmd_ai_runtime] %(levelname)s %(message)s"
_MARK = "_vmdai_handler"  # set on the handlers configure_logging installs


def redact_sensitive(value: Any) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def default_log_path(home: Optional[str] = None) -> str:
    """~/.vmdai/logs/runtime.log (or under ``home``)."""
    base = home if home is not None else os.path.expanduser("~")
    return os.path.join(base, ".vmdai", "logs", "runtime.log")


def configure_logging(
    level: str = "INFO",
    *,
    log_path: Optional[str] = None,
    stderr: bool = True,
) -> logging.Logger:
    """Configure logging for the runtime process and return its logger.

    The handlers go on the root logger, so records from ``vmd_ai_runtime``
    and from ``vmdai.*`` (claude_loop, tool_bridge, wiki_store) all reach
    them and none falls through to ``logging.lastResort``, which would
    print onto the plugin's READY pipe (§2d). ``stderr=False`` (used under
    --announce) installs no stream handler at all. Calling this again
    replaces the handlers an earlier call installed.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()

    installed = []
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        installed.append(file_handler)
    if stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(logging.Formatter(_STDERR_FORMAT))
        installed.append(stream_handler)
    if not installed:
        # A handler must exist, or warnings would reach lastResort (stderr).
        installed.append(logging.NullHandler())
    for handler in installed:
        setattr(handler, _MARK, True)
        root.addHandler(handler)

    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger = logging.getLogger("vmd_ai_runtime")
    logger.setLevel(logging.NOTSET)  # inherit the root level
    return logger


def env_or_default(name: str, default: str) -> str:
    return os.getenv(name, default)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_logging_setup.py tests/test_redaction.py -q`
Expected: all passed (4 new; `test_redaction.py` still uses `redact_sensitive`).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/vmd_ai_runtime/logging_utils.py tests/test_logging_setup.py
git commit -m "feat(runtime): rotating file log on the root logger, optional stderr

configure_logging(level, *, log_path, stderr) puts a 2 MiB x3 rotating
file handler on the root logger, so vmdai.* records no longer fall
through logging.lastResort onto the READY pipe. stderr=False installs no
stream handler. default_log_path() is ~/.vmdai/logs/runtime.log.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: P02-T04 — main.py lifecycle: --port 0, --announce, --watch-stdin, shutdown thread

**Files:**
- Create: `tests/test_main_lifecycle.py`
- Modify: `runtime/main.py:1-70` (whole file)
- Modify: `scripts/run_runtime.sh:1-9` (whole file)
- Modify: `scripts/dev_smoke.sh:5-27`

**Interfaces:**
- Consumes: `launch.*` (P02-T02); `configure_logging, default_log_path` (P02-T03); `RuntimeApp(launch_token, allow_tokenless_v1, on_shutdown)` (P02-T02); `RpcHTTPServer.daemon_threads` (P02-T01)
- Produces:
  - main.py flags `--port` (0 = ephemeral), `--announce`, `--watch-stdin`, `--log-file`
  - `main(argv=None) -> int`
  - `_start_shutdown(server) -> threading.Thread`
  - scripts/run_runtime.sh and dev_smoke.sh print the token-file path
  - (plan addition) both scripts take the port from `VMD_AI_PORT`, else from the port of `VMD_AI_ATTACH=host:port`, else 8765, and the Python from `VMD_AI_PYTHON` (§7)
  - (plan addition) `tests/test_main_lifecycle.py` helpers `_env(extra=None)` (plan 03 edits it), `_spawn`, `_ready`, `_rpc`, `_exit_seconds`, `_wait_token_file(proc, timeout=20.0)` (fails at once when the runtime has already exited)

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_lifecycle.py`:

```python
"""P02-T04: main.py lifecycle: --port 0, --announce, --watch-stdin, shutdown thread (§2d, §2e, S4)."""
from __future__ import annotations

import http.server
import json
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "runtime" / "main.py"
READY = "VMDAI_READY "


def _env(extra=None):
    # The hermetic conftest already cleared VMD_AI_*/ANTHROPIC_*/... and set a temp HOME.
    env = dict(os.environ)
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env.update(extra or {})
    return env


def _cmd(tmp_path, *args, store=None, log=None):
    return [sys.executable, "-u", str(MAIN), "--port", "0",
            "--store-dir", str(store or tmp_path / "chats"),
            "--log-file", str(log or tmp_path / "logs" / "runtime.log"),
            "--disable-wiki", *args]


def _spawn(tmp_path, *args, env_extra=None, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE):
    return subprocess.Popen(_cmd(tmp_path, *args), stdin=stdin, stdout=subprocess.PIPE,
                            stderr=stderr, env=_env(env_extra), cwd=str(tmp_path))


def _readline(proc, timeout=20.0):
    """One stdout line, read straight from the fd (so communicate() still works later)."""
    fd = proc.stdout.fileno()
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        char = os.read(fd, 1)
        if not char:
            break
        buf += char
        if char == b"\n":
            break
    return buf.decode("utf-8", "replace")


def _ready(proc):
    line = _readline(proc)
    assert line.startswith(READY), f"expected the READY line, got {line!r}"
    return json.loads(line[len(READY):])


def _rpc(port, method, params, token=""):
    body = json.dumps({"jsonrpc": "2.0", "id": "1", "method": method, "params": params}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/rpc", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Session-Token": token},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def _exit_seconds(proc, sig=signal.SIGTERM):
    started = time.monotonic()
    proc.send_signal(sig)
    proc.wait(timeout=10)
    return time.monotonic() - started


def _stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=5)


def _token_files():
    return sorted((Path(os.environ["HOME"]) / ".vmdai" / "run").glob("runtime-*.json"))


def _wait_token_file(proc, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = _token_files()
        if files:
            return files[0]
        if proc.poll() is not None:
            raise AssertionError(f"the runtime exited with code {proc.returncode} before writing its token file")
        time.sleep(0.05)
    raise AssertionError("the token file never appeared")


def test_help_exits_zero():
    proc = subprocess.run([sys.executable, str(MAIN), "--help"], capture_output=True,
                          text=True, env=_env(), timeout=30)
    assert proc.returncode == 0
    for flag in ("--port", "--announce", "--watch-stdin", "--log-file"):
        assert flag in proc.stdout


def test_announce_prints_ready_first_line(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        assert set(info) == {"port", "pid", "version", "protocol", "launch_token"}
        assert info["pid"] == proc.pid and info["port"] > 0
        assert info["version"] == "0.3.0" and info["protocol"] == 2
        assert len(info["launch_token"]) == 32 and int(info["launch_token"], 16) >= 0
        assert _token_files() == []  # under --announce the token is only in READY
    finally:
        _stop(proc)


def test_health_after_ready(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=5) as resp:
            assert json.loads(resp.read()) == {"ok": True, "pid": proc.pid,
                                               "version": "0.3.0", "protocol": 2}
        refused = _rpc(info["port"], "session.start", {"cwd": str(tmp_path)})
        assert refused["error"]["code"] == "AUTH_REQUIRED"
        started = _rpc(info["port"], "session.start",
                       {"cwd": str(tmp_path), "launch_token": info["launch_token"]})
        assert started["result"]["event_protocol"] == 1
    finally:
        _stop(proc)


def test_runtime_shutdown_rpc_exits_within_2s(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        started = time.monotonic()
        reply = _rpc(info["port"], "runtime.shutdown", {"launch_token": info["launch_token"]})
        assert reply["result"] == {"ok": True}
        proc.wait(timeout=10)
        assert time.monotonic() - started < 2.0
        assert proc.returncode == 0
    finally:
        _stop(proc)


def test_sigterm_exits_within_2s(tmp_path):
    """S4: SIGTERM exits within 2 s (the old handler deadlocked)."""
    proc = _spawn(tmp_path, "--announce")
    try:
        _ready(proc)
        assert _exit_seconds(proc) < 2.0
        assert proc.returncode == 0
    finally:
        _stop(proc)


def test_sigterm_during_active_request_exits_within_2s(tmp_path):
    # A listener that accepts and never answers: the worker blocks in urlopen.
    silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    silent.bind(("127.0.0.1", 0))
    silent.listen(4)
    accepted = threading.Event()
    held = []

    def _accept():
        try:
            conn, _ = silent.accept()
        except OSError:
            return
        held.append(conn)
        accepted.set()

    threading.Thread(target=_accept, daemon=True).start()
    host = f"http://127.0.0.1:{silent.getsockname()[1]}"
    # Without --announce a tokenless session may use the env provider.
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL, env_extra={
        "VMD_AI_PROVIDER": "ollama",
        "VMD_AI_OLLAMA_MODEL": "qwen3.8:27b",
        "VMD_AI_OLLAMA_HOST": host,
    })
    try:
        port = json.loads(_wait_token_file(proc).read_text())["port"]
        start = _rpc(port, "session.start", {"cwd": str(tmp_path)})["result"]
        assert start["agent_loop"] is True
        sent = _rpc(port, "chat.send", {"session_id": start["session_id"], "text": "hi"},
                    token=start["session_token"])
        assert "request_id" in sent["result"]
        assert accepted.wait(5), "the worker never reached the provider"
        assert _exit_seconds(proc) < 2.0
    finally:
        _stop(proc)
        for conn in held:
            conn.close()
        silent.close()


class _OllamaToolCall(http.server.BaseHTTPRequestHandler):
    """A fake Ollama whose /api/chat answers with one run_vmd_command call."""

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        call = {"function": {"name": "run_vmd_command", "arguments": {"command": "puts hi"}}}
        lines = [
            {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"},
        ]
        body = b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def test_sigterm_during_tool_wait_exits_within_2s(tmp_path):
    # The model asks for a VMD command and no plugin ever answers, so the
    # worker blocks in VmdToolBridge.execute_tool (the 45 s pickup wait).
    fake = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _OllamaToolCall)
    threading.Thread(target=fake.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL, env_extra={
        "VMD_AI_PROVIDER": "ollama",
        "VMD_AI_OLLAMA_MODEL": "qwen3.8:27b",
        "VMD_AI_OLLAMA_HOST": f"http://127.0.0.1:{fake.server_port}",
    })
    try:
        port = json.loads(_wait_token_file(proc).read_text())["port"]
        start = _rpc(port, "session.start", {"cwd": str(tmp_path)})["result"]
        sid, token = start["session_id"], start["session_token"]
        sent = _rpc(port, "chat.send", {"session_id": sid, "text": "hi"}, token=token)
        assert "request_id" in sent["result"]
        roles, deadline = [], time.monotonic() + 5
        while "tool_start" not in roles and time.monotonic() < deadline:
            polled = _rpc(port, "chat.events.poll", {"session_id": sid, "after_seq": 0}, token=token)
            roles = [event["role"] for event in polled["result"]["events"]]
            time.sleep(0.05)
        assert "tool_start" in roles, "the worker never reached the tool wait"
        assert _exit_seconds(proc) < 2.0
    finally:
        _stop(proc)
        fake.shutdown()
        fake.server_close()


def test_stdin_eof_exits_within_2s(tmp_path):
    proc = _spawn(tmp_path, "--announce", "--watch-stdin", stdin=subprocess.PIPE)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = _spawn(other_dir, "--announce", stdin=subprocess.PIPE)
    try:
        _ready(proc)
        _ready(other)
        started = time.monotonic()
        proc.stdin.close()
        proc.wait(timeout=10)
        assert time.monotonic() - started < 2.0
        assert proc.returncode == 0
        other.stdin.close()  # without --watch-stdin, EOF on stdin is ignored
        time.sleep(0.5)
        assert other.poll() is None
    finally:
        _stop(proc)
        _stop(other)


def test_no_announce_writes_token_file_0600_and_removes_on_exit(tmp_path):
    proc = _spawn(tmp_path, stderr=subprocess.DEVNULL)
    try:
        path = _wait_token_file(proc)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        data = json.loads(path.read_text())
        assert set(data) == {"port", "pid", "token", "protocol"}
        assert data["pid"] == proc.pid and data["protocol"] == 2 and len(data["token"]) == 32
        assert path.name == f"runtime-{data['port']}.json"
        assert _readline(proc, timeout=0.5) == ""  # no READY line without --announce
        started = _rpc(data["port"], "session.start", {"cwd": str(tmp_path)})
        assert "session_id" in started["result"]  # tokenless is fine without --announce
        assert _exit_seconds(proc) < 2.0
        assert not path.exists()
    finally:
        _stop(proc)


def test_announce_keeps_stderr_clean(tmp_path):
    proc = _spawn(tmp_path, "--announce")
    try:
        info = _ready(proc)
        bad = _rpc(info["port"], "no.such.method", {})
        assert bad["error"]["code"] == "METHOD_NOT_FOUND"  # the app logs a warning
        _exit_seconds(proc)
        rest, err = proc.communicate(timeout=5)
    finally:
        _stop(proc)
    assert rest == b""
    assert err == b""
    log = (tmp_path / "logs" / "runtime.log").read_text(encoding="utf-8")
    assert "rpc error method=no.such.method" in log
    assert "runtime stopped" in log


def test_startup_traceback_reaches_merged_pipe(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    cases = (
        # Fails after logging is configured: the store dir cannot be created.
        _cmd(tmp_path, "--announce", store=blocker / "chats"),
        # Fails before logging is configured: the log dir cannot be created.
        _cmd(tmp_path, "--announce", log=blocker / "logs" / "runtime.log"),
    )
    for cmd in cases:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, env=_env(), timeout=30)
        out = proc.stdout.decode("utf-8", "replace")
        assert proc.returncode != 0
        assert "Traceback (most recent call last)" in out
        assert "VMDAI_READY" not in out
    assert "runtime failed to start" in (tmp_path / "logs" / "runtime.log").read_text()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_main_lifecycle.py -q`
Expected: `11 failed in about 1 s`. Today's `main.py` rejects the new flags (`error: unrecognized arguments: --log-file ... --announce`) and exits with code 2 at once, so the READY tests fail with `expected the READY line, got ''`, the three token-file tests fail with `the runtime exited with code 2 before writing its token file`, `test_help_exits_zero` fails on `assert '--announce' in ...`, and `test_startup_traceback_reaches_merged_pipe` fails on the `Traceback` assertion (argparse exits 2 with a usage message, not a traceback).

- [ ] **Step 3: Rewrite `main.py`**

Replace the whole content of `runtime/main.py` with:

```python
from __future__ import annotations

import argparse
import os
import signal
import sys
import threading

from vmd_ai_runtime import RuntimeApp, create_server
from vmd_ai_runtime.constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from vmd_ai_runtime.launch import (
    format_ready_line,
    generate_launch_token,
    remove_token_file,
    write_token_file,
)
from vmd_ai_runtime.logging_utils import configure_logging, default_log_path

_SHUTDOWN_LOCK = threading.Lock()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ChatVMD runtime: JSON-RPC over loopback HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=8765,
        help="TCP port on 127.0.0.1; 0 picks a free ephemeral port",
    )
    parser.add_argument("--store-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--log-file", default=None,
        help="Rotating log file. Default: ~/.vmdai/logs/runtime.log",
    )
    parser.add_argument(
        "--announce", action="store_true",
        help="Print one VMDAI_READY line (with the launch token) on stdout, "
             "log only to the file, and refuse tokenless sessions.",
    )
    parser.add_argument(
        "--watch-stdin", action="store_true",
        help="Exit when stdin reaches EOF (the plugin's pipe was closed).",
    )
    # LLM Wiki flags. Defaults live in RuntimeApp; CLI overrides win.
    parser.add_argument(
        "--wiki-root",
        default=None,
        help="Directory where the LLM-maintained wiki lives. "
             "Default: ~/.vmdai/wiki/",
    )
    parser.add_argument(
        "--wiki-raw-root",
        default=None,
        help="Directory containing immutable raw sources for the wiki to "
             "pin. Default: ~/.vmdai/raw/",
    )
    parser.add_argument(
        "--disable-wiki",
        action="store_true",
        help="Run without the wiki tools (e.g. for the no-wiki arm of "
             "an A/B experiment).",
    )
    return parser.parse_args(argv)


def _start_shutdown(server) -> threading.Thread:
    """Run server.shutdown() on its own thread and return that thread.

    shutdown() blocks until serve_forever() returns, so calling it from a
    signal handler on the serving thread deadlocks (the old SIGTERM bug).
    Repeated calls return the thread the first call started.
    """
    with _SHUTDOWN_LOCK:
        thread = getattr(server, "_vmdai_shutdown_thread", None)
        if thread is None:
            thread = threading.Thread(target=server.shutdown, name="vmdai-shutdown", daemon=True)
            server._vmdai_shutdown_thread = thread
            thread.start()
    return thread


def _watch_stdin(server, logger) -> threading.Thread:
    """Shut down when stdin reaches EOF, so a VMD crash leaves no orphan."""
    def _run():
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        reader = getattr(stream, "read1", stream.read)
        try:
            while reader(65536):
                pass
        except Exception:
            pass
        logger.info("stdin closed; shutting down")
        _start_shutdown(server)

    thread = threading.Thread(target=_run, name="vmdai-stdin-watch", daemon=True)
    thread.start()
    return thread


def _serve(args, logger, log_path) -> int:
    token = generate_launch_token()
    holder = {}

    def _request_shutdown():
        server = holder.get("server")
        if server is not None:
            _start_shutdown(server)

    app = RuntimeApp(
        store_dir=args.store_dir,
        logger=logger,
        wiki_root=args.wiki_root,
        wiki_raw_root=args.wiki_raw_root,
        enable_wiki=not args.disable_wiki,
        launch_token=token,
        allow_tokenless_v1=not args.announce,
        on_shutdown=_request_shutdown,
    )
    server = create_server(app, host=args.host, port=args.port)
    holder["server"] = server
    port = int(server.server_port)
    pid = os.getpid()

    def _handle_signal(_signum, _frame):
        _start_shutdown(server)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    token_file = None
    if args.announce:
        # The launch token appears here and nowhere else (§2e).
        sys.stdout.write(format_ready_line(port, pid, RUNTIME_VERSION, RUNTIME_PROTOCOL, token) + "\n")
        sys.stdout.flush()
    else:
        token_file = write_token_file(port, pid, token, RUNTIME_PROTOCOL)
        logger.info("launch token file: %s", token_file)
    if args.watch_stdin:
        _watch_stdin(server, logger)

    logger.info("runtime listening on http://127.0.0.1:%s (log: %s)", port, log_path)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if token_file is not None:
            remove_token_file(token_file)
        logger.info("runtime stopped")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    log_path = args.log_file or default_log_path()
    # A failure before this line (bad Python, ImportError, unwritable log
    # dir) prints its traceback to stderr, which the plugin merges into the
    # pipe with 2>@1 and shows in the "Runtime didn't start" banner.
    logger = configure_logging(args.log_level, log_path=log_path, stderr=not args.announce)
    try:
        return _serve(args, logger, log_path)
    except Exception:
        logger.exception("runtime failed to start or crashed")
        raise


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Print the token-file path from the attach scripts**

Replace the whole content of `scripts/run_runtime.sh` with:

```bash
#!/usr/bin/env bash
# Start the runtime in attach mode (no --announce): it accepts tokenless
# sessions and writes its launch token to ~/.vmdai/run/runtime-<port>.json
# (mode 0600) for a plugin started with VMD_AI_ATTACH=127.0.0.1:<port>.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${VMD_AI_PYTHON:-${PYTHON:-python3}}"
# The port: VMD_AI_PORT, else the port of VMD_AI_ATTACH=host:port (the
# address the plugin attaches to), else 8765.
ATTACH_PORT=""
if [ -n "${VMD_AI_ATTACH:-}" ]; then
  ATTACH_PORT="${VMD_AI_ATTACH##*:}"
fi
PORT="${VMD_AI_PORT:-${ATTACH_PORT:-8765}}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats}"
TOKEN_FILE="$HOME/.vmdai/run/runtime-${PORT}.json"

echo "[vmdai] runtime on 127.0.0.1:${PORT}; attach with VMD_AI_ATTACH=127.0.0.1:${PORT}" >&2
echo "[vmdai] launch token file: ${TOKEN_FILE}" >&2
exec "$PYTHON_BIN" "$ROOT_DIR/runtime/main.py" --host 127.0.0.1 --port "$PORT" --store-dir "$STORE_DIR"
```

In `scripts/dev_smoke.sh` replace:

```bash
PYTHON_BIN="${PYTHON:-python3}"
PORT="${VMD_AI_PORT:-8765}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats_smoke}"
```

with:

```bash
PYTHON_BIN="${VMD_AI_PYTHON:-${PYTHON:-python3}}"
# The port: VMD_AI_PORT, else the port of VMD_AI_ATTACH=host:port (the
# address the plugin attaches to), else 8765.
ATTACH_PORT=""
if [ -n "${VMD_AI_ATTACH:-}" ]; then
  ATTACH_PORT="${VMD_AI_ATTACH##*:}"
fi
PORT="${VMD_AI_PORT:-${ATTACH_PORT:-8765}}"
STORE_DIR="${VMD_AI_STORE_DIR:-$HOME/.vmdai/chats_smoke}"
TOKEN_FILE="$HOME/.vmdai/run/runtime-${PORT}.json"
```

and replace:

```bash
for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

PYTHONPATH="$ROOT_DIR/runtime:${PYTHONPATH:-}" "$PYTHON_BIN" - <<'PY'
import time
from vmd_ai_runtime.client import RuntimeClient

client = RuntimeClient(port=8765)
```

with:

```bash
for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

echo "[smoke] launch token file: ${TOKEN_FILE}"
test -f "$TOKEN_FILE" || { echo "[smoke] token file missing" >&2; exit 1; }

VMD_AI_PORT="$PORT" PYTHONPATH="$ROOT_DIR/runtime:${PYTHONPATH:-}" "$PYTHON_BIN" - <<'PY'
import os
import time
from vmd_ai_runtime.client import RuntimeClient

client = RuntimeClient(port=int(os.environ.get("VMD_AI_PORT", "8765")))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main_lifecycle.py -v`
Expected: 11 passed in about 5 s.

Run: `bash -n scripts/run_runtime.sh scripts/dev_smoke.sh && echo ok`
Expected: `ok`.

Run (manual smoke with a throwaway HOME and port):
`HOME=$(mktemp -d) VMD_AI_PORT=18765 PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring bash scripts/dev_smoke.sh 2>&1 | tail -3`
Expected: the last line is `[smoke] ok`, preceded by `[smoke] events seen: …` and `[smoke] session.stop: …`.

Run (the port taken from `VMD_AI_ATTACH`):
`HOME=$(mktemp -d) VMD_AI_ATTACH=127.0.0.1:18766 PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring bash scripts/dev_smoke.sh 2>&1 | grep -E 'token file|smoke\] ok'`
Expected: `[smoke] launch token file: /…/.vmdai/run/runtime-18766.json`, then `[smoke] ok`.

Run: `SUITE` then `GUARDS`, and `python -m pytest tests/test_py39_compat.py -q`.
Expected: `0 failed`, `1 xfailed`; guards all passed; the 3.9 check passes (`main.py --help` runs under /usr/bin/python3).

- [ ] **Step 6: Commit**

```bash
git add runtime/main.py scripts/run_runtime.sh scripts/dev_smoke.sh tests/test_main_lifecycle.py
git commit -m "feat(runtime): --port 0, --announce READY line, --watch-stdin, safe shutdown

SIGTERM, runtime.shutdown and stdin EOF call server.shutdown() on its own
thread, which fixes the deadlock (exit < 2 s, S4). --announce prints one
VMDAI_READY line with the launch token, logs only to the rotating file and
refuses tokenless sessions; without it the runtime writes the 0600 token
file and removes it on exit. Startup failures keep their traceback on
stderr. The attach scripts print the token-file path and take the port
from VMD_AI_PORT or VMD_AI_ATTACH.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: P02-T05 — LoopOptions, RunContext, error classes, options plumbing

**Files:**
- Create: `tests/helpers/fake_provider.py`
- Create: `tests/test_loop_options.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports (`:17-26`), new section after `logger = ...` (`:44`), streamer signatures (`:533-549`, `:634-644`, `:1053-1063`), `ClaudeLoopError` (`:1296-1297`), constructor (`:1367-1397`), `_call` (`:1654-1703`), `run` (`:1705-1883`: signature, docstring, start, per-turn, finally)

**Interfaces:**
- Consumes: `claude_loop._sleep` (P01-T02)
- Produces:
  - `@dataclass LoopOptions` fields: num_ctx, think, keep_alive, extra_body, include_usage=False, base_url, temperature, seed, context_length, connect_retries=None, classify_unreachable=False, classify_errors=False, preflight=False, first_byte_timeout_s=None, cancellable_backoff=False, report_cancelled=False, turn_retry=0, raise_stream_errors=False, guard_truncation=False, compact_in_run=False, rescue='all', tool_overrides=None, supports_vision=None, image_max_edge=None, ollama_tool_name=False, max_turns=28, loop_guard=False, result_format='legacy'
  - `LoopOptions.product(profile: Dict[str, Any], *, max_turns: int = 28) -> LoopOptions`
  - `LoopOptions.from_dict(d: Dict[str, Any]) -> LoopOptions; LoopOptions.to_dict() -> Dict[str, Any]`
  - `@dataclass RunContext(request_id: str, chat_id: str, on_event: Optional[Callable[[Dict[str, Any]], None]] = None, messages_out: Optional[Any] = None)`
  - `ClaudeLoopError.code = 'other', .hint = '', .http_status; __init__(message, *, hint='', http_status=None)`
  - `ProviderUnreachableError (unreachable), ProviderAuthError (auth), ProviderBillingError (billing), ModelNotFoundError (model_not_found)`
  - `ClaudeToolLoop(..., options: Optional[LoopOptions] = None); run(..., prior_messages=None, ctx: Optional[RunContext] = None); self._ctx; self._tool_mode: Optional[str]`
  - streamers gain keyword-only `on_meta=None, opts=None, tool_mode=None`; `_call` passes them only when options is not None
  - `ClaudeToolLoop._on_meta(item: Dict[str, Any]) -> None; ClaudeToolLoop._emit(role: str, type: str, text: str = '', metadata: Optional[Dict[str, Any]] = None) -> None`
  - (plan additions) `claude_loop._LOOP_ONLY_META = frozenset({"stop_reason", "rescued", "model_digest"})` — `_on_meta` stores these in `self._turn_meta[kind]` for the current turn instead of forwarding them (plan 04 reads `self._turn_meta.get("model_digest")`); `self._turn` (1-based turn); constants `PRODUCT_OLLAMA_NUM_CTX = 32768`, `PRODUCT_FIRST_BYTE_TIMEOUT_S = 120.0`, `LOCAL_IMAGE_MAX_EDGE = 1024`, `ANTHROPIC_IMAGE_MAX_EDGE = 1568`
  - (plan addition) `tests/helpers/fake_provider.py`: `FakeUrlopen(chat, *, model='qwen3.8:27b')` with `.requests` / `.chat_requests` (each `{url, path, method, timeout, probe, body}`); `FakeResponse`; `ndjson`, `ollama_text`, `ollama_tool_call`, `sse`, `anthropic_text`, `anthropic_tool_use`, `anthropic_error`, `http_error`; `tool_use(tool_id, name, **input)`; `scripted_call(turns, seen=None)`; `SpyBridge(results=None)` with `.calls`; `StatusRecorder` with `.chat_id`, `.status`; `run_loop(loop, *, prompt='hello', bridge=None, cancel_event=None, ctx=None, chunks=None) -> str`; `event_kinds(events)`

- [ ] **Step 1: Write the shared test helper**

Create `tests/helpers/fake_provider.py`:

```python
"""Fakes for driving ClaudeToolLoop with no network (plan 02).

FakeUrlopen stands in for urllib.request.urlopen. It answers the Ollama
probe paths (/api/version, /api/ps, /api/tags, /api/show) with canned JSON,
so these tests keep passing when plan 04 adds the preflight calls, and it
serves every other request (the model call) from a scripted list whose
items are response bodies (bytes) or exceptions to raise.
"""
from __future__ import annotations

import copy
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

PROBE_PATHS = ("/api/version", "/api/ps", "/api/tags", "/api/show")
DIGEST = "sha256:" + "0" * 64

Scripted = Union[bytes, BaseException]


class FakeResponse:
    """Enough of http.client.HTTPResponse for the three streamers."""

    def __init__(self, body: bytes, status: int = 200):
        self._buf = io.BytesIO(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._buf.close()
        return False

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def readline(self) -> bytes:
        return self._buf.readline()

    def __iter__(self):
        return iter(self._buf.readlines())

    def close(self) -> None:
        self._buf.close()


def _probe_body(path: str, model: str) -> Dict[str, Any]:
    if path == "/api/version":
        return {"version": "0.12.3"}
    if path in ("/api/ps", "/api/tags"):
        return {"models": [{"name": model, "model": model, "digest": DIGEST, "size": 1}]}
    return {
        "capabilities": ["completion", "tools", "vision", "thinking"],
        "model_info": {"general.architecture": "qwen3", "qwen3.context_length": 131072},
    }


class FakeUrlopen:
    """Callable replacement for urllib.request.urlopen that records every request."""

    def __init__(self, chat: Sequence[Scripted], *, model: str = "qwen3.8:27b"):
        self.chat: List[Scripted] = list(chat)
        self.model = model
        self.requests: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def chat_requests(self) -> List[Dict[str, Any]]:
        """The model calls only (probe requests left out)."""
        return [r for r in self.requests if not r["probe"]]

    def __call__(self, req, timeout=None, *args, **kwargs):
        if isinstance(req, urllib.request.Request):
            url, data, method = req.full_url, req.data, req.get_method()
        else:
            url, data, method = str(req), None, "GET"
        path = urllib.parse.urlsplit(url).path
        probe = path in PROBE_PATHS
        record = {
            "url": url,
            "path": path,
            "method": method,
            "timeout": timeout,
            "probe": probe,
            "body": json.loads(data) if data else None,
        }
        with self._lock:
            self.requests.append(record)
            if probe:
                return FakeResponse(json.dumps(_probe_body(path, self.model)).encode("utf-8"))
            if not self.chat:
                raise AssertionError(f"unexpected extra request: {method} {url}")
            item = self.chat.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)


# --- response bodies -------------------------------------------------------

def ndjson(*events: Dict[str, Any]) -> bytes:
    return b"".join(json.dumps(e).encode("utf-8") + b"\n" for e in events)


def ollama_text(text: str, *, done_reason: str = "stop") -> bytes:
    return ndjson(
        {"message": {"role": "assistant", "content": text}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason},
    )


def ollama_tool_call(name: str, arguments: Dict[str, Any], *, text: str = "",
                     done_reason: str = "stop") -> bytes:
    call = {"function": {"name": name, "arguments": arguments}}
    return ndjson(
        {"message": {"role": "assistant", "content": text, "tool_calls": [call]}, "done": False},
        {"message": {"role": "assistant", "content": ""}, "done": True, "done_reason": done_reason},
    )


def sse(*events: Dict[str, Any]) -> bytes:
    return b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)


_MESSAGE_START = {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 1}}}


def anthropic_text(text: str, *, stop_reason: str = "end_turn") -> bytes:
    return sse(
        _MESSAGE_START,
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    )


def anthropic_tool_use(tool_id: str, name: str, partial_json: str, *,
                       stop_reason: str = "tool_use") -> bytes:
    return sse(
        _MESSAGE_START,
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": tool_id, "name": name}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": partial_json}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 50}},
        {"type": "message_stop"},
    )


def anthropic_error(error_type: str, message: str) -> bytes:
    return sse(_MESSAGE_START, {"type": "error", "error": {"type": error_type, "message": message}})


def http_error(url: str, code: int, body: Any,
               headers: Optional[Dict[str, str]] = None) -> urllib.error.HTTPError:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(url, code, "error", dict(headers or {}), io.BytesIO(raw))


# --- loop drivers ----------------------------------------------------------

def tool_use(tool_id: str, name: str, **tool_input: Any) -> Dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": dict(tool_input)}


def scripted_call(turns: Sequence[Any], seen: Optional[List[Any]] = None) -> Callable[..., Tuple[str, List[Dict[str, Any]]]]:
    """A 4-argument stand-in for ClaudeToolLoop._call, set on an instance.

    Each item of ``turns`` is ``(text, tool_blocks)`` or an exception to
    raise. After the script ends every call returns ``("", [])``. ``seen``
    collects a deep copy of the messages each call received.
    """
    items = iter(list(turns))

    def _call(messages, system_prompt, on_text, should_cancel):
        if seen is not None:
            seen.append(copy.deepcopy(messages))
        item = next(items, ("", []))
        if isinstance(item, BaseException):
            raise item
        text, blocks = item
        if text:
            on_text(text)
        return text, [dict(b) for b in blocks]

    return _call


class SpyBridge:
    """A strict six-keyword bridge (like the benchmark's) that records calls."""

    def __init__(self, results: Optional[Sequence[Dict[str, Any]]] = None):
        self.calls: List[Dict[str, Any]] = []
        self._results = list(results or [])

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event):
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name,
                           "tool_input": tool_input})
        if self._results:
            return self._results.pop(0)
        return {"ok": True, "output": "ok", "error": ""}


class StatusRecorder:
    """Duck-typed RunRecorder that remembers the chat id and end status."""

    runs_root = None

    def __init__(self):
        self.chat_id: Optional[str] = None
        self.status: Optional[str] = None
        self.commands: List[str] = []

    def start_task(self, prompt, *, chat_id="", model="", cwd=None):
        self.chat_id = chat_id
        return "task"

    def record_vmd_command(self, command, **kwargs):
        self.commands.append(command)

    def record_snapshot(self, **kwargs):
        return None

    def end_task(self, status="complete"):
        self.status = status
        return "task"


def run_loop(loop, *, prompt: str = "hello", bridge: Any = None,
             cancel_event: Optional[threading.Event] = None, ctx: Any = None,
             chunks: Optional[List[str]] = None) -> str:
    """Call loop.run with test defaults; ``chunks`` collects on_chunk text."""
    return loop.run(
        prompt=prompt,
        system_prompt="SYS",
        tool_bridge=bridge if bridge is not None else SpyBridge(),
        session_id="sess_test",
        session_queue=None,
        cancel_event=cancel_event if cancel_event is not None else threading.Event(),
        on_chunk=chunks.append if chunks is not None else (lambda _chunk: None),
        ctx=ctx,
    )


def event_kinds(events: List[Dict[str, Any]]) -> List[Tuple[str, str, Optional[str]]]:
    """(role, type, metadata.kind) for each on_event item."""
    return [(e["role"], e["type"], (e.get("metadata") or {}).get("kind")) for e in events]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_loop_options.py`:

```python
"""P02-T05: LoopOptions, RunContext, error classes and options plumbing (§2a, C6, C7)."""
from __future__ import annotations

import dataclasses
import json
from unittest import mock

import pytest

from helpers.fake_provider import run_loop, scripted_call
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    ProviderAuthError,
    ProviderBillingError,
    ProviderUnreachableError,
    RunContext,
)

FIELD_ORDER = [
    "num_ctx", "think", "keep_alive", "extra_body", "include_usage", "base_url",
    "temperature", "seed", "context_length", "connect_retries", "classify_unreachable",
    "classify_errors", "preflight", "first_byte_timeout_s", "cancellable_backoff",
    "report_cancelled", "turn_retry", "raise_stream_errors", "guard_truncation",
    "compact_in_run", "rescue", "tool_overrides", "supports_vision", "image_max_edge",
    "ollama_tool_name", "max_turns", "loop_guard", "result_format",
]
BOOL_FLAGS = ("include_usage", "classify_unreachable", "classify_errors", "preflight",
              "cancellable_backoff", "report_cancelled", "raise_stream_errors",
              "guard_truncation", "compact_in_run", "ollama_tool_name", "loop_guard")
NONE_FIELDS = ("num_ctx", "think", "keep_alive", "extra_body", "base_url", "temperature",
               "seed", "context_length", "connect_retries", "first_byte_timeout_s",
               "tool_overrides", "supports_vision", "image_max_edge")
STREAMER_KWARGS = {"messages", "model", "system_prompt", "timeout", "on_text",
                   "should_cancel", "tools"}
CHAT_ID = "chat_0123456789ab"


def test_defaults_match_today():
    assert [f.name for f in dataclasses.fields(LoopOptions)] == FIELD_ORDER
    opts = LoopOptions()
    for name in BOOL_FLAGS:
        assert getattr(opts, name) is False, name
    for name in NONE_FIELDS:
        assert getattr(opts, name) is None, name
    assert opts.turn_retry == 0
    assert opts.rescue == "all"
    assert opts.result_format == "legacy"
    assert opts.max_turns == ClaudeToolLoop.MAX_TURNS == 28
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m")
    assert loop.options is None and loop._ctx is None and loop._tool_mode is None


def test_product_ollama_preset():
    opts = LoopOptions.product({"provider": "ollama", "model": "qwen3.8:27b",
                                "base_url": "http://127.0.0.1:11435"})
    assert opts.num_ctx == 32768  # C7: the profile set no num_ctx
    assert opts.connect_retries == 0
    assert opts.preflight is True
    assert opts.first_byte_timeout_s == 120
    assert opts.image_max_edge == 1024
    assert opts.ollama_tool_name is True
    assert opts.rescue == "json"
    assert opts.result_format == "structured"
    assert opts.loop_guard is True
    assert opts.turn_retry == 1
    for name in ("classify_unreachable", "classify_errors", "cancellable_backoff",
                 "report_cancelled", "raise_stream_errors", "guard_truncation",
                 "compact_in_run"):
        assert getattr(opts, name) is True, name
    assert opts.supports_vision == "auto"
    assert opts.base_url == "http://127.0.0.1:11435"
    assert opts.max_turns == 28
    assert LoopOptions.product({"provider": "ollama"}, max_turns=12).max_turns == 12


def test_product_profile_options_override():
    profile = {"provider": "ollama", "model": "m",
               "options": {"num_ctx": 16384, "rescue": "all", "loop_guard": False,
                           "think": True, "bogus_key": 1, "max_turns": 5}}
    opts = LoopOptions.product(profile, max_turns=20)
    assert opts.num_ctx == 16384
    assert opts.rescue == "all"
    assert opts.loop_guard is False
    assert opts.think is True
    assert not hasattr(opts, "bogus_key")
    assert opts.max_turns == 20  # the max_turns setting wins over a profile key
    assert LoopOptions.product({"provider": "ollama", "options": {"num_ctx": None}}).num_ctx == 32768


def test_product_non_ollama():
    claude = LoopOptions.product({"provider": "anthropic-direct", "model": "claude-sonnet-4-5"})
    assert claude.connect_retries == 1
    assert claude.preflight is False
    assert claude.num_ctx is None
    assert claude.first_byte_timeout_s is None
    assert claude.ollama_tool_name is False
    assert claude.image_max_edge == 1568
    assert claude.rescue == "json"
    assert claude.supports_vision == "auto"
    vllm = LoopOptions.product({"provider": "openai-compatible", "model": "m",
                                "base_url": "http://localhost:8000/v1"})
    assert vllm.supports_vision is False  # manual toggle, off by default (§2f)
    assert vllm.image_max_edge == 1024
    assert vllm.base_url == "http://localhost:8000/v1"
    assert vllm.connect_retries == 1


def test_asdict_json_serialisable():
    opts = LoopOptions.product({"provider": "ollama", "model": "m",
                                "options": {"extra_body": {"a": [1, 2]}, "keep_alive": "30m"}})
    data = opts.to_dict()
    assert data == dataclasses.asdict(opts)
    json.dumps(data)
    assert LoopOptions.from_dict(data) == opts
    assert LoopOptions.from_dict({"rescue": "off", "unknown": 1}) == LoopOptions(rescue="off")
    assert LoopOptions.from_dict(None) == LoopOptions()


def test_error_subclasses():
    cases = [(ClaudeLoopError, "other"), (ProviderUnreachableError, "unreachable"),
             (ProviderAuthError, "auth"), (ProviderBillingError, "billing"),
             (ModelNotFoundError, "model_not_found")]
    for cls, code in cases:
        exc = cls("API error HTTP 401: bad key", hint="Check the key", http_status=401)
        assert isinstance(exc, ClaudeLoopError) and isinstance(exc, RuntimeError)
        assert exc.code == code
        assert exc.hint == "Check the key"
        assert exc.http_status == 401
        assert str(exc) == "API error HTTP 401: bad key"
    plain = ClaudeLoopError("network error: refused")
    assert (plain.code, plain.hint, plain.http_status) == ("other", "", None)
    assert str(plain) == "network error: refused"


def _loops():
    return [
        ("_stream_anthropic_direct", ClaudeToolLoop("anthropic-direct", "sk-ant-x", "claude-sonnet-4-5"), "api_key"),
        ("_stream_ollama", ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b"), "base_url"),
        ("_stream_openrouter", ClaudeToolLoop("openrouter", "sk-or-x", "anthropic/claude-sonnet-4.6"), "api_key"),
    ]


def _call_once(target, loop):
    with mock.patch(f"vmd_ai_runtime.claude_loop.{target}", return_value=("t", [])) as fake:
        loop._call([{"role": "user", "content": "hi"}], "sys",
                   on_text=lambda chunk: None, should_cancel=lambda: False)
    return fake.call_args


def test_options_none_streamer_kwargs_exact():
    for target, loop, key_kw in _loops():
        call = _call_once(target, loop)
        assert call.args == ()
        assert set(call.kwargs) == STREAMER_KWARGS | {key_kw}, target


def test_options_set_streamer_kwargs():
    for target, loop, key_kw in _loops():
        loop.options = LoopOptions()
        call = _call_once(target, loop)
        assert set(call.kwargs) == STREAMER_KWARGS | {key_kw, "on_meta", "opts", "tool_mode"}, target
        assert call.kwargs["opts"] is loop.options
        assert call.kwargs["on_meta"] == loop._on_meta
        assert call.kwargs["tool_mode"] is None


def test_on_meta_enriches_and_forwards():
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m", options=LoopOptions())
    events = []
    loop._ctx = RunContext("req_9", CHAT_ID, on_event=events.append)
    loop._turn = 3
    loop._on_meta({"kind": "status", "phase": "retrying", "attempt": 1})
    loop._on_meta({"kind": "reasoning", "text": "hmm"})
    loop._on_meta({"kind": "stop_reason", "value": "max_tokens"})
    assert events == [
        {"role": "system", "type": "state", "text": "",
         "metadata": {"kind": "status", "phase": "retrying", "attempt": 1,
                      "request_id": "req_9", "turn": 3}},
        {"role": "reasoning", "type": "chunk", "text": "hmm",
         "metadata": {"request_id": "req_9", "turn": 3}},
    ]
    assert loop._turn_meta["stop_reason"] == {"kind": "stop_reason", "value": "max_tokens"}


def test_ctx_cleared_after_run_even_on_error():
    ctx = RunContext(request_id="req_1", chat_id=CHAT_ID)
    assert ctx.on_event is None and ctx.messages_out is None
    loop = ClaudeToolLoop("openrouter", "sk-or-x", "m", options=LoopOptions())
    seen = []

    def boom(messages, system_prompt, on_text, should_cancel):
        seen.append(loop._ctx)
        raise ClaudeLoopError("boom")

    loop._call = boom
    with pytest.raises(ClaudeLoopError, match="boom"):
        run_loop(loop, ctx=ctx)
    assert seen == [ctx]
    assert loop._ctx is None
    loop._call = scripted_call([("fine", [])])
    assert run_loop(loop, ctx=ctx) == "fine"
    assert loop._ctx is None
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python -m pytest tests/test_loop_options.py -q`
Expected: collection error `ImportError: cannot import name 'LoopOptions' from 'vmd_ai_runtime.claude_loop'`.

- [ ] **Step 4: Add the imports**

In `runtime/vmd_ai_runtime/claude_loop.py` replace:

```python
import base64
import json
```

with:

```python
import base64
import dataclasses
import json
```

and replace:

```python
from typing import Any, Callable, Dict, List, Optional, Tuple
```

with:

```python
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
```

- [ ] **Step 5: Add `LoopOptions`, `RunContext` and `_LOOP_ONLY_META`**

Replace the line:

```python
logger = logging.getLogger("vmdai.claude_loop")
```

with:

```python
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
                preset[key] = value
        preset["max_turns"] = int(max_turns)
        return cls(**preset)


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
```

- [ ] **Step 6: Give the three streamers the keyword-only parameters**

Replace:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from Anthropic Messages API; return (text, tool_blocks).
```

with:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from Anthropic Messages API; return (text, tool_blocks).
```

Replace:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from OpenRouter / OpenAI-style chat completions."""
```

with:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """Stream a turn from OpenRouter / OpenAI-style chat completions."""
```

Replace:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict]]:
    """Stream one turn from Ollama's ``/api/chat`` with tool support.
```

with:

```python
    should_cancel: Callable[[], bool],
    tools: Optional[List[Dict[str, Any]]] = None,
    *,
    on_meta: Optional[Callable[[Dict[str, Any]], None]] = None,
    opts: Optional[LoopOptions] = None,
    tool_mode: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """Stream one turn from Ollama's ``/api/chat`` with tool support.
```

- [ ] **Step 7: Add the error classes**

Replace:

```python
class ClaudeLoopError(RuntimeError):
    pass
```

with:

```python
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
```

- [ ] **Step 8: Extend the constructor**

Replace:

```python
        wiki_store: Optional[WikiStore] = None,
    ):
        self.provider_name = str(provider_name or "mock").lower()
```

with:

```python
        wiki_store: Optional[WikiStore] = None,
        options: Optional[LoopOptions] = None,
    ):
        self.provider_name = str(provider_name or "mock").lower()
```

Replace:

```python
        # rediscovering it from raw docs.
        self.wiki_store = wiki_store
```

with:

```python
        # rediscovering it from raw docs.
        self.wiki_store = wiki_store
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
```

- [ ] **Step 9: Replace `_call` and add `_on_meta` / `_emit`**

Replace the whole `_call` method (from `    def _call(` to the closing `        )` of its `_stream_openrouter(...)` return, just before `    def run(`) with:

```python
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

    def _on_meta(self, item: Dict[str, Any]) -> None:
        """Streamer→loop callback, wired only when ``options`` is set.

        Loop-only kinds (stop_reason, rescued, model_digest) are kept in
        ``self._turn_meta`` for this turn. ``reasoning`` becomes a reasoning
        chunk event; every other item (status, usage) becomes a
        ``system/state`` event carrying the item plus request_id and turn.
        """
        if not isinstance(item, dict):
            return
        kind = str(item.get("kind") or "")
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

```

- [ ] **Step 10: Thread `ctx` through `run`**

Replace:

```python
        prior_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        Run a full multi-turn tool-calling session.
```

with:

```python
        prior_messages: Optional[List[Dict]] = None,
        ctx: Optional[RunContext] = None,
    ) -> str:
        """
        Run a full multi-turn tool-calling session.
```

Replace:

```python
        prior_messages              optional conversation history from a
                                    resumed chat (Anthropic-style format)
```

with:

```python
        prior_messages              optional conversation history from a
                                    resumed chat (Anthropic-style format)
        ctx                         optional RunContext (request identity and
                                    sinks); None keeps today's behaviour
```

Replace:

```python
        self._recorder_start_task(prompt, session_id)
        end_status = "complete"
```

with:

```python
        self._ctx = ctx
        self._turn = 0
        self._turn_meta = {}
        self._recorder_start_task(prompt, session_id)
        end_status = "complete"
```

Replace:

```python
                logger.debug("loop turn %d/%d model=%s",
                             turn + 1, self.MAX_TURNS, self.model)
```

with:

```python
                self._turn = turn + 1
                self._turn_meta = {}
                logger.debug("loop turn %d/%d model=%s",
                             turn + 1, self.MAX_TURNS, self.model)
```

Replace:

```python
        finally:
            self._recorder_end_task(end_status)

        return final_text
```

with:

```python
        finally:
            self._recorder_end_task(end_status)
            self._ctx = None

        return final_text
```

- [ ] **Step 11: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loop_options.py tests/test_claude_loop.py tests/test_ollama_loop.py tests/test_claude_loop_recorder.py -q`
Expected: all passed except the one xfail (`10 passed` in the new module).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed (the adapter builds loops without options, so the golden requests are unchanged).

- [ ] **Step 12: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/helpers/fake_provider.py tests/test_loop_options.py
git commit -m "feat(loop): LoopOptions, RunContext, classified error types

LoopOptions holds every product behaviour flag with today's behaviour as
the default; LoopOptions.product(profile) is the ChatVMD preset (Ollama
num_ctx 32768 when unset, C7). ClaudeToolLoop(options=) and run(ctx=)
are additive: with options=None the streamers get exactly today's
keywords. ClaudeLoopError gains code/hint/http_status and four
subclasses. _on_meta/_emit route streamer meta to ctx.on_event.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 6: P02-T06 — Transport flags in _stream_request

**Files:**
- Create: `tests/test_stream_request_flags.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports (`:17-22`), after `_RETRY_STATUS` (`:472`), `_stream_request` (`:475-530`), the three `with _stream_request(req, timeout) as resp:` lines (`:580`, `:681`, `:1126`), `_stream_ollama`'s `except ClaudeLoopError:` (`:1160`), `run`'s two `except` blocks (`:1770`, `:1877`)

**Interfaces:**
- Consumes: `LoopOptions`, error subclasses (P02-T05); `claude_loop._sleep` (P01-T02)
- Produces:
  - `_stream_request(req, timeout, max_retries=5, *, opts: Optional[LoopOptions] = None, should_cancel: Optional[Callable[[], bool]] = None, on_meta: Optional[Callable[[Dict[str, Any]], None]] = None)`
  - `class RunCancelled(Exception)`
  - `_cancellable_sleep(seconds: float, should_cancel) -> None` (0.1 s slices via `_sleep`)
  - on_meta status item `{kind:'status', phase:'retrying', attempt, max_attempts, wait_s, http_status, message}`
  - `_classify_http_error(code: int, detail: str) -> ClaudeLoopError`
  - (plan additions) `_open_stream(req, timeout, opts, should_cancel, on_meta)` — calls exactly `_stream_request(req, timeout)` when `opts is None`; `_retry_status(on_meta, attempt, max_attempts, wait, http_status)`; `_backoff_sleep(seconds, opts, should_cancel)`; `_status_message(http_status)`; `_HTTP_MAX_RETRIES = 5`; `run()` ends with status `cancelled` when `RunCancelled` reaches it
  - Note: `classify_unreachable` is not acted on here; plan 04 (P04-T01) owns it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_request_flags.py`:

```python
"""P02-T06: transport flags in _stream_request (§2a rows, §5 429/5xx, 401/403, billing, 404)."""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request

import pytest

from helpers.fake_provider import FakeUrlopen, StatusRecorder, http_error, run_loop
from vmd_ai_runtime import claude_loop
from vmd_ai_runtime.claude_loop import (
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    ModelNotFoundError,
    ProviderAuthError,
    ProviderBillingError,
    RunCancelled,
    _classify_http_error,
    _stream_request,
)

URL = "https://api.anthropic.com/v1/messages"


def _req():
    return urllib.request.Request(URL, data=b"{}", method="POST",
                                  headers={"Content-Type": "application/json"})


def _refused():
    return urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


def _serve(monkeypatch, *items):
    fake = FakeUrlopen(list(items))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def test_options_none_identical(monkeypatch, sleep_calls):
    for kwargs in ({}, {"opts": None, "should_cancel": None, "on_meta": None}):
        fake = _serve(monkeypatch, *[_refused() for _ in range(6)])
        del sleep_calls[:]
        with pytest.raises(ClaudeLoopError) as info:
            _stream_request(_req(), 10, **kwargs)
        assert type(info.value) is ClaudeLoopError
        assert str(info.value).startswith("network error:")
        assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 30.0]
        assert [r["timeout"] for r in fake.requests] == [10] * 6


def test_connect_retries_zero_single_attempt(monkeypatch, sleep_calls):
    fake = _serve(monkeypatch, _refused(), _refused())
    with pytest.raises(ClaudeLoopError, match="network error"):
        _stream_request(_req(), 10, opts=LoopOptions(connect_retries=0))
    assert len(fake.requests) == 1
    assert sleep_calls == []
    fake = _serve(monkeypatch, _refused(), _refused(), _refused())
    with pytest.raises(ClaudeLoopError):
        _stream_request(_req(), 10, opts=LoopOptions(connect_retries=1))
    assert len(fake.requests) == 2
    assert sleep_calls == [2.0]


def test_retry_status_meta(monkeypatch, sleep_calls):
    _serve(monkeypatch, http_error(URL, 429, {"error": {"message": "slow down"}}, {"Retry-After": "3"}), b"ok")
    seen = []
    resp = _stream_request(_req(), 10, opts=LoopOptions(), on_meta=seen.append)
    assert resp.read() == b"ok"
    assert seen == [{"kind": "status", "phase": "retrying", "attempt": 1, "max_attempts": 5,
                     "wait_s": 3.0, "http_status": 429, "message": "Rate limited"}]
    assert sleep_calls == [3.0]


def test_cancel_during_backoff_raises_quickly(monkeypatch):
    # Direct: Stop already pressed, a 60 s Retry-After raises at once.
    cancel = threading.Event()
    cancel.set()
    _serve(monkeypatch, http_error(URL, 503, {"error": {"message": "busy"}}, {"Retry-After": "60"}))
    with pytest.raises(RunCancelled):
        _stream_request(_req(), 10, opts=LoopOptions(cancellable_backoff=True),
                        should_cancel=cancel.is_set)

    # Through run(): Stop lands during the backoff; the run ends at once, cancelled.
    cancel = threading.Event()
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        if len(slept) == 3:
            cancel.set()

    monkeypatch.setattr(claude_loop, "_sleep", fake_sleep)
    fake = _serve(monkeypatch, http_error(URL, 429, {"error": {"message": "slow down"}}, {"Retry-After": "60"}))
    recorder = StatusRecorder()
    loop = ClaudeToolLoop("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5",
                          recorder=recorder, options=LoopOptions(cancellable_backoff=True))
    started = time.monotonic()
    assert run_loop(loop, cancel_event=cancel) == ""
    assert time.monotonic() - started < 1.0
    assert recorder.status == "cancelled"
    assert slept == [0.1, 0.1, 0.1]  # 3 slices of a 60 s wait, not 600
    assert len(fake.chat_requests) == 1


def test_classify_401_403_auth(monkeypatch):
    for code in (401, 403):
        _serve(monkeypatch, http_error(URL, code, {"error": {"type": "authentication_error",
                                                            "message": "invalid x-api-key"}}))
        with pytest.raises(ProviderAuthError) as info:
            _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
        assert info.value.code == "auth" and info.value.http_status == code
        assert str(info.value) == f"API error HTTP {code}: invalid x-api-key"
        assert info.value.hint


def test_classify_402_and_credit_balance_billing(monkeypatch):
    cases = [
        (402, {"error": {"message": "Insufficient credits"}}),
        (400, {"error": {"type": "invalid_request_error",
                         "message": "Your credit balance is too low to access the Anthropic API."}}),
    ]
    for code, body in cases:
        _serve(monkeypatch, http_error(URL, code, body))
        with pytest.raises(ProviderBillingError) as info:
            _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
        assert info.value.code == "billing" and info.value.http_status == code


def test_classify_404_model_not_found(monkeypatch):
    _serve(monkeypatch, http_error("http://ollama.test/api/chat", 404, {"error": "model 'qwen9' not found"}))
    with pytest.raises(ModelNotFoundError) as info:
        _stream_request(_req(), 10, opts=LoopOptions(classify_errors=True))
    assert info.value.code == "model_not_found"
    assert str(info.value) == "API error HTTP 404: model 'qwen9' not found"
    other = _classify_http_error(500, "boom")
    assert type(other) is ClaudeLoopError and other.code == "other" and other.http_status == 500


def test_unclassified_without_flag(monkeypatch):
    for opts in (None, LoopOptions()):
        _serve(monkeypatch, http_error(URL, 401, {"error": {"message": "invalid x-api-key"}}))
        with pytest.raises(ClaudeLoopError) as info:
            _stream_request(_req(), 10, opts=opts)
        assert type(info.value) is ClaudeLoopError
        assert info.value.code == "other"
        assert str(info.value) == "API error HTTP 401: invalid x-api-key"


def test_first_byte_timeout_used(monkeypatch):
    fake = _serve(monkeypatch, b"a", b"b", b"c")
    _stream_request(_req(), 90, opts=LoopOptions(first_byte_timeout_s=120.0))
    _stream_request(_req(), 90, opts=LoopOptions())
    _stream_request(_req(), 90)
    assert [r["timeout"] for r in fake.requests] == [120.0, 90, 90]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_stream_request_flags.py -q`
Expected: collection error `ImportError: cannot import name 'RunCancelled' from 'vmd_ai_runtime.claude_loop'`.

- [ ] **Step 3: Add the import and the transport helpers**

Replace:

```python
import logging
import os
```

with:

```python
import logging
import math
import os
```

Replace the line:

```python
_RETRY_STATUS = {429, 500, 502, 503, 529}
```

with:

```python
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
```

- [ ] **Step 4: Replace `_stream_request` and add `_open_stream`**

Replace the whole `_stream_request` function — from `def _stream_request(req: urllib.request.Request, timeout: int, max_retries: int = 5):` through its last line `            raise ClaudeLoopError(f"network error: {exc}") from exc` (after plan 01 its two waits read `_sleep(wait)`) — with:

```python
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
```

- [ ] **Step 5: Open every stream through `_open_stream`**

Use Edit with `replace_all: true`: old `_stream_request(req, timeout) as resp:` new `_open_stream(req, timeout, opts, should_cancel, on_meta) as resp:`.

Run: `grep -c "_open_stream(req, timeout, opts, should_cancel, on_meta) as resp:" runtime/vmd_ai_runtime/claude_loop.py`
Expected: `3` (Anthropic, OpenRouter, Ollama).

In `_stream_ollama` replace:

```python
    except ClaudeLoopError:
        raise
    except urllib.error.HTTPError as exc:
```

with:

```python
    except (ClaudeLoopError, RunCancelled):
        raise
    except urllib.error.HTTPError as exc:
```

- [ ] **Step 6: End the run as cancelled on `RunCancelled`**

In `run` replace:

```python
                except ClaudeLoopError:
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc
```

with:

```python
                except (ClaudeLoopError, RunCancelled):
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc
```

and replace:

```python
        except Exception:
            end_status = "error"
            raise
        finally:
            self._recorder_end_task(end_status)
```

with:

```python
        except RunCancelled:
            end_status = "cancelled"
            logger.info("stopped during a provider backoff")
        except Exception:
            end_status = "error"
            raise
        finally:
            self._recorder_end_task(end_status)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_stream_request_flags.py tests/test_benchmark_retry_pin.py tests/test_claude_loop.py tests/test_ollama_loop.py -q`
Expected: all passed except the one xfail (`9 passed` in the new module; the retry pin still sees `[2,4,8,16,30]`, `[2,4,8,16,32]` and `[7.0]*5`).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed.

- [ ] **Step 8: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/test_stream_request_flags.py
git commit -m "feat(loop): gated transport flags in _stream_request

With options set: connect_retries caps network retries, backoff sleeps in
cancellable 0.1 s slices (RunCancelled -> status cancelled), each retry
emits a status meta item, first_byte_timeout_s bounds the open, and
classify_errors raises the auth/billing/model_not_found subclasses. With
opts=None the streamers call _stream_request(req, timeout) exactly as
before, so the retry pin and the goldens are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: P02-T07 — Loop flags: report_cancelled, turn_retry, raise_stream_errors, guard_truncation, max_turns

**Files:**
- Create: `tests/test_loop_flags.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports, the body of `_stream_anthropic_direct` (`:576-631`), `_stream_openrouter`'s choices loop (`:688-691`), `_stream_ollama`'s `done` check (`:1158-1159`), after `ModelNotFoundError`, the constructor, new methods before `run`, and `run` (whole method)

**Interfaces:**
- Consumes: `_stream_request` opts, `RunCancelled` (P02-T06); `_on_meta`, `_emit` (P02-T05)
- Produces:
  - on_meta `{kind:'stop_reason', value}` from all three streamers (consumed by the loop)
  - `ClaudeToolLoop.last_status` ('complete'|'cancelled'|'error'|'max_turns'|'stuck'), `last_turns`, `last_tool_calls`, `last_final_text_empty`
  - turn.retry event `{kind:'turn.retry', request_id, turn, reason:'stream dropped'}`
  - `TRUNCATED_TOOL_ERROR` text; status phase `'turn_truncated'`
  - (plan additions) `ClaudeToolLoop._call_turn(messages, system_prompt, on_text, cancel_event) -> Tuple[str, List[Dict]]`; `ClaudeToolLoop._turn_truncated() -> bool`; `_is_stream_drop(exc) -> bool`; `_SseOverloaded`; `_anthropic_consume(req, timeout, on_text, should_cancel, on_meta, opts)`. `'stuck'` is set by plan 05's loop guard; this task produces the other four values.

- [ ] **Step 1: Write the failing test**

Create `tests/test_loop_flags.py`:

```python
"""P02-T07: report_cancelled, turn_retry, raise_stream_errors, guard_truncation and max_turns (§2a, §5)."""
from __future__ import annotations

import threading
import urllib.request

import pytest

from helpers.fake_provider import (
    FakeUrlopen,
    SpyBridge,
    StatusRecorder,
    anthropic_error,
    anthropic_text,
    anthropic_tool_use,
    run_loop,
    scripted_call,
    tool_use,
)
from vmd_ai_runtime.claude_loop import (
    TRUNCATED_TOOL_ERROR,
    ClaudeLoopError,
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
)

CHAT_ID = "chat_0123456789ab"


def _loop(opts=None, provider="openrouter"):
    if provider == "anthropic-direct":
        return ClaudeToolLoop("anthropic-direct", "sk-ant-test", "claude-sonnet-4-5", options=opts)
    return ClaudeToolLoop("openrouter", "sk-or-test", "test/model", options=opts)


def _ctx(events):
    return RunContext(request_id="req_flags", chat_id=CHAT_ID, on_event=events.append)


def _of_kind(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def _serve(monkeypatch, *bodies):
    fake = FakeUrlopen(list(bodies))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _stop_while_streaming(cancel, text):
    def _call(messages, system_prompt, on_text, should_cancel):
        on_text(text)
        cancel.set()  # the user pressed Stop while this turn streamed
        return text, []
    return _call


def test_report_cancelled_on():
    cancel = threading.Event()
    loop = _loop(LoopOptions(report_cancelled=True))
    loop._call = _stop_while_streaming(cancel, "partial")
    assert run_loop(loop, cancel_event=cancel) == "partial"
    assert loop.last_status == "cancelled"
    assert loop.last_final_text_empty is False


def test_report_cancelled_off():
    for opts in (None, LoopOptions()):
        cancel = threading.Event()
        loop = _loop(opts)
        loop._call = _stop_while_streaming(cancel, "partial")
        run_loop(loop, cancel_event=cancel)
        assert loop.last_status == "complete"  # today's behaviour


def test_turn_retry_once_after_stream_drop():
    events, seen = [], []
    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call(
        [ConnectionResetError(54, "Connection reset by peer"), ("recovered", [])], seen=seen)
    assert run_loop(loop, ctx=_ctx(events)) == "recovered"
    assert len(seen) == 2 and seen[0] == seen[1]  # the same messages are resent
    assert _of_kind(events, "turn.retry") == [
        {"kind": "turn.retry", "reason": "stream dropped", "request_id": "req_flags", "turn": 1}]
    assert loop.last_status == "complete"
    assert loop.last_turns == 1


def test_turn_retry_not_after_tool_ran():
    """The retry repeats only the model call: a tool that already ran never runs again,
    and one turn gets at most turn_retry retries."""
    bridge = SpyBridge()
    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call([
        ("", [tool_use("tc_0", "run_vmd_command", command="mol new 1hck.pdb")]),
        ConnectionResetError(54, "reset"),
        ("done", []),
    ])
    assert run_loop(loop, bridge=bridge) == "done"
    assert [c["tool_input"]["command"] for c in bridge.calls] == ["mol new 1hck.pdb"]
    assert loop.last_turns == 2

    loop = _loop(LoopOptions(turn_retry=1))
    loop._call = scripted_call([ConnectionResetError(54, "reset"),
                                ConnectionResetError(54, "reset again")])
    with pytest.raises(ClaudeLoopError, match="API call failed on turn 1"):
        run_loop(loop)
    assert loop.last_status == "error"

    loop = _loop(None)  # options=None: no retry at all
    loop._call = scripted_call([ConnectionResetError(54, "reset"), ("never", [])])
    with pytest.raises(ClaudeLoopError, match="API call failed on turn 1"):
        run_loop(loop)


def test_sse_error_event_raises_when_flag_on(monkeypatch):
    _serve(monkeypatch, anthropic_error("api_error", "Internal server error"))
    recorder = StatusRecorder()
    loop = _loop(LoopOptions(raise_stream_errors=True), provider="anthropic-direct")
    loop.recorder = recorder
    with pytest.raises(ClaudeLoopError, match="API stream error: Internal server error"):
        run_loop(loop)
    assert recorder.status == "error"
    assert loop.last_status == "error"


def test_sse_overloaded_retries_as_529(monkeypatch, sleep_calls):
    fake = _serve(monkeypatch, anthropic_error("overloaded_error", "Overloaded"),
                  anthropic_text("Hello"))
    events = []
    loop = _loop(LoopOptions(raise_stream_errors=True), provider="anthropic-direct")
    assert run_loop(loop, ctx=_ctx(events)) == "Hello"
    assert len(fake.chat_requests) == 2
    assert sleep_calls == [2.0]
    assert _of_kind(events, "status") == [{
        "kind": "status", "phase": "retrying", "attempt": 1, "max_attempts": 5,
        "wait_s": 2.0, "http_status": 529, "message": "Overloaded",
        "request_id": "req_flags", "turn": 1,
    }]


def test_sse_error_ignored_when_flag_off(monkeypatch):
    _serve(monkeypatch, anthropic_error("api_error", "Internal server error"))
    loop = _loop(None, provider="anthropic-direct")
    assert run_loop(loop) == ""  # today: an empty answer, status complete
    assert loop.last_status == "complete"
    assert loop.last_final_text_empty is True


def test_guard_truncation_blocks_tool_calls(monkeypatch):
    fake = _serve(
        monkeypatch,
        anthropic_tool_use("toolu_1", "run_vmd_command", '{"command": "mol new', stop_reason="max_tokens"),
        anthropic_text("I will make a shorter call."),
    )
    events, bridge = [], SpyBridge()
    loop = _loop(LoopOptions(guard_truncation=True), provider="anthropic-direct")
    run_loop(loop, bridge=bridge, ctx=_ctx(events))
    assert bridge.calls == []
    result_msg = fake.chat_requests[1]["body"]["messages"][-1]
    block = result_msg["content"][0]
    assert result_msg["role"] == "user"
    assert (block["type"], block["tool_use_id"], block["is_error"]) == ("tool_result", "toolu_1", True)
    assert TRUNCATED_TOOL_ERROR in block["content"]
    assert [m["phase"] for m in _of_kind(events, "status")] == ["turn_truncated"]
    assert loop.last_tool_calls == 1


def test_guard_truncation_off_runs_with_empty_input(monkeypatch):
    _serve(
        monkeypatch,
        anthropic_tool_use("toolu_1", "run_vmd_command", '{"command": "mol new', stop_reason="max_tokens"),
        anthropic_text("ok"),
    )
    bridge = SpyBridge()
    run_loop(_loop(LoopOptions(), provider="anthropic-direct"), bridge=bridge)
    assert bridge.calls == [{"tool_call_id": "toolu_1", "tool_name": "run_vmd_command",
                             "tool_input": {}}]


def test_max_turns_from_options():
    bridge = SpyBridge()
    loop = _loop(LoopOptions(max_turns=3))
    loop._call = scripted_call([
        ("", [tool_use(f"tc_{n}", "run_vmd_command", command=f"puts {n}")]) for n in range(10)])
    run_loop(loop, bridge=bridge)
    assert len(bridge.calls) == 3
    assert loop.last_status == "max_turns"
    assert (loop.last_turns, loop.last_tool_calls) == (3, 3)
    assert loop.last_final_text_empty is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_loop_flags.py -q`
Expected: collection error `ImportError: cannot import name 'TRUNCATED_TOOL_ERROR' from 'vmd_ai_runtime.claude_loop'`.

- [ ] **Step 3: Add the imports**

Replace:

```python
import base64
import dataclasses
import json
```

with:

```python
import base64
import dataclasses
import http.client
import json
```

and replace:

```python
import re
import threading
```

with:

```python
import re
import socket
import threading
```

- [ ] **Step 4: Split the Anthropic stream consumer out and handle SSE `error` and `message_delta`**

In `_stream_anthropic_direct`, replace everything from `    text_parts: List[str] = []` through the function's `    return "".join(text_parts), final_tool_blocks` (the block that follows the `req = urllib.request.Request(...)` construction and ends just before `def _stream_openrouter(`) — that is, this exact text:

```python
    text_parts: List[str] = []
    blocks_in_progress: Dict[int, Dict[str, Any]] = {}
    final_tool_blocks: List[Dict[str, Any]] = []

    with _open_stream(req, timeout, opts, should_cancel, on_meta) as resp:
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
```

— with:

```python
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
    final_tool_blocks: List[Dict[str, Any]] = []
    raise_errors = opts is not None and opts.raise_stream_errors

    with _open_stream(req, timeout, opts, should_cancel, on_meta) as resp:
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

    return "".join(text_parts), final_tool_blocks


def _stream_openrouter(
```

(With `opts=None` the events are handled exactly as before: `message_delta` was already skipped and `error` falls through as before.)

- [ ] **Step 5: Report stop reasons from OpenRouter and Ollama**

In `_stream_openrouter` replace:

```python
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = (choices[0] or {}).get("delta") or {}
```

with:

```python
            choices = event.get("choices") or []
            if not choices:
                continue
            if on_meta is not None:
                finish = (choices[0] or {}).get("finish_reason")
                if finish:
                    on_meta({"kind": "stop_reason", "value": str(finish)})
            delta = (choices[0] or {}).get("delta") or {}
```

In `_stream_ollama` replace:

```python
                if event.get("done"):
                    break
```

with:

```python
                if event.get("done"):
                    if on_meta is not None:
                        on_meta({"kind": "stop_reason",
                                 "value": str(event.get("done_reason") or "stop")})
                    break
```

- [ ] **Step 6: Add the truncation text and the stream-drop test**

Replace:

```python
class ModelNotFoundError(ClaudeLoopError):
    code = "model_not_found"
```

with:

```python
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
```

- [ ] **Step 7: Add the outcome attributes to the constructor**

Replace:

```python
        # 1-based turn number and the loop-only meta items of that turn.
        self._turn = 0
        self._turn_meta: Dict[str, Dict[str, Any]] = {}
```

with:

```python
        # 1-based turn number and the loop-only meta items of that turn.
        self._turn = 0
        self._turn_meta: Dict[str, Dict[str, Any]] = {}
        # Outcome of the last run(); the app builds request.finished from it.
        self.last_status: Optional[str] = None
        self.last_turns = 0
        self.last_tool_calls = 0
        self.last_final_text_empty = False
```

- [ ] **Step 8: Add `_call_turn` and `_turn_truncated`**

Replace:

```python
    def run(
        self,
        prompt: str,
```

with:

```python
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

    def run(
        self,
        prompt: str,
```

- [ ] **Step 9: Replace `run`**

Replace the whole `run` method (from `    def run(` to its `        return final_text`, just before the `# Recorder hooks` banner) with:

```python
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
        ctx                         optional RunContext (request identity and
                                    sinks); None keeps today's behaviour

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

        self._ctx = ctx
        self._turn = 0
        self._turn_meta = {}
        self.last_status = None
        self.last_turns = 0
        self.last_tool_calls = 0
        self.last_final_text_empty = True
        opts = self.options
        max_turns = opts.max_turns if opts is not None else self.MAX_TURNS

        # Open a recorder task for this chat.send. No-op if self.recorder
        # is None. Status is updated below; finalized in the finally block
        # so a cancel / exception still closes the run cleanly on disk.
        self._recorder_start_task(prompt, session_id)
        end_status = "complete"

        try:
            for turn in range(max_turns):
                if cancel_event.is_set():
                    end_status = "cancelled"
                    logger.info("cancelled before turn %d", turn + 1)
                    break

                self._turn = turn + 1
                self._turn_meta = {}
                self.last_turns = turn + 1
                logger.debug("loop turn %d/%d model=%s",
                             turn + 1, max_turns, self.model)

                try:
                    # Real SSE streaming: on_chunk fires for each text delta
                    # as the provider produces it. cancel_event is checked
                    # between SSE events so Stop interrupts mid-generation.
                    text, tool_blocks = self._call_turn(
                        messages, system_prompt, on_chunk, cancel_event,
                    )
                except (ClaudeLoopError, RunCancelled):
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc

                if text:
                    final_text = text

                # report_cancelled: Stop during the stream ends the run as
                # cancelled instead of complete (§2a).
                if opts is not None and opts.report_cancelled and cancel_event.is_set():
                    end_status = "cancelled"
                    self.last_final_text_empty = not text
                    logger.info("stopped during turn %d", turn + 1)
                    break

                # No tool calls → conversation complete
                if not tool_blocks:
                    self.last_final_text_empty = not text
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

                truncated = self._turn_truncated()
                if truncated:
                    self._emit("system", "state", "", {
                        "kind": "status",
                        "phase": "turn_truncated",
                        "message": "The reply was cut off; its tool calls were not run.",
                    })

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
                    if truncated:
                        result = {"ok": False, "output": "",
                                  "error": TRUNCATED_TOOL_ERROR, "executed": "no"}
                    elif tool_name == "search_docs":
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
                    self.last_tool_calls += 1

                    # Mirror the result into the on-disk recorder so this
                    # chat.send produces a replayable transcript.tcl +
                    # snapshots/. Failed tools are counted in the manifest
                    # but never written to transcript.tcl (by design); a
                    # guarded (truncated) call never ran, so it is skipped.
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
                               max_turns)
                end_status = "max_turns"
        except RunCancelled:
            end_status = "cancelled"
            logger.info("stopped during a provider backoff")
        except Exception:
            end_status = "error"
            raise
        finally:
            self.last_status = end_status
            self._recorder_end_task(end_status)
            self._ctx = None

        return final_text
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loop_flags.py tests/test_stream_request_flags.py tests/test_loop_options.py tests/test_claude_loop.py tests/test_claude_loop_recorder.py tests/test_agent_integration.py -q`
Expected: all passed (`10 passed` in `test_loop_flags.py`).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed.

- [ ] **Step 11: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/test_loop_flags.py
git commit -m "feat(loop): report_cancelled, turn_retry, SSE errors, truncation guard, max_turns

All three streamers report the stop reason through on_meta. With options
set: Stop mid-stream ends the run as cancelled; a stream drop retries the
model call once (turn.retry event) without re-running tools; an Anthropic
SSE error raises and overloaded_error retries like HTTP 529; tool calls
from a max_tokens/length turn are not run and get TRUNCATED_TOOL_ERROR;
max_turns comes from options. last_status/turns/tool_calls/
final_text_empty expose the outcome.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 8: P02-T08 — call_key, on_event emission, canonical messages_out

**Files:**
- Create: `tests/test_loop_events.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — imports, `_stream_ollama`'s rescue block (`:1199-1202`), new helpers before the `# The Claude tool loop` banner (`:1354`), new methods before `run`, and `run` (whole method)
- Modify: `tests/test_benchmark_bridge_guard.py` (append at the end)

**Interfaces:**
- Consumes: `RunContext`, `_emit`, `_on_meta` (P02-T05); `LEGACY_KWARGS`, `run_guard` (P01-T06); `_call_turn`, `_turn_truncated`, `TRUNCATED_TOOL_ERROR`, `last_*` (P02-T07)
- Produces:
  - `_mint_call_key() -> str`
  - `execute_tool(..., call_key=, request_id=)` passed only to supports_call_meta bridges
  - loop events: turn.started; assistant chunk; assistant/message {request_id, turn, final}; tool.started {call_key, tool_call_id, tool_name, executor 'tcl'|'runtime', origin 'model'|'rescued', input}; tool.finished {call_key, tool_name, executor, ok, executed, output, error, truncated, duration_ms, statements, blocked, output_path, output_bytes, image, saved_path, late}; usage; status; reasoning chunk
  - on_meta `{kind:'rescued', ids:[...]}`
  - ctx.messages_out receives deep copies with ids rewritten to `'call_<call_key>'`, including the final text-only turn
  - recorder chat_id = ctx.chat_id when ctx is set
  - (plan additions) `_canonical_message(message, call_keys) -> Dict`; `_tool_finished_meta(call_key, tool_name, executor, result, duration_ms) -> Dict`; `_RUNTIME_TOOLS`; methods `_text_sink`, `_out`, `_finish_text_turn`, `_rescued_ids`, `_dispatch_tool`, `_run_tool_block`. `usage` and `reasoning` items are forwarded by `_on_meta` (P02-T05) once plan 04's streamers emit them.

- [ ] **Step 1: Write the failing loop-events test**

Create `tests/test_loop_events.py`:

```python
"""P02-T08: call_key, on_event emission and canonical messages_out (§2a, §2b, §2c)."""
from __future__ import annotations

import re
import urllib.request

from helpers.fake_provider import (
    FakeUrlopen,
    SpyBridge,
    StatusRecorder,
    event_kinds,
    ollama_text,
    run_loop,
    scripted_call,
    tool_use,
)
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, LoopOptions, RunContext

CHAT_ID = "chat_0123456789ab"
LOAD = tool_use("tc_0", "run_vmd_command", command="mol new 1hck.pdb")


def _loop(opts=None):
    return ClaudeToolLoop("openrouter", "sk-or-test", "test/model",
                          options=LoopOptions() if opts is None else opts)


def _meta(events, kind):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == kind]


def test_event_sequence_two_turns():
    events = []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])])
    run_loop(loop, ctx=RunContext("req_1", CHAT_ID, on_event=events.append))
    assert event_kinds(events) == [
        ("system", "state", "turn.started"),
        ("assistant", "chunk", None),
        ("assistant", "message", None),
        ("system", "state", "tool.started"),
        ("system", "state", "tool.finished"),
        ("system", "state", "turn.started"),
        ("assistant", "chunk", None),
        ("assistant", "message", None),
    ]
    sealed = [(e["text"], e["metadata"]["final"], e["metadata"]["turn"])
              for e in events if e["type"] == "message"]
    assert sealed == [("Loading.", False, 1), ("Done.", True, 2)]
    assert all(e["metadata"]["request_id"] == "req_1" for e in events)
    started, = _meta(events, "tool.started")
    finished, = _meta(events, "tool.finished")
    key = started["call_key"]
    assert re.fullmatch(r"[0-9a-f]{12}", key)
    assert started == {"kind": "tool.started", "call_key": key, "tool_call_id": "tc_0",
                       "tool_name": "run_vmd_command", "executor": "tcl", "origin": "model",
                       "input": {"command": "mol new 1hck.pdb"},
                       "request_id": "req_1", "turn": 1}
    assert finished == {"kind": "tool.finished", "call_key": key,
                        "tool_name": "run_vmd_command", "executor": "tcl", "ok": True,
                        "executed": "yes", "output": "ok", "error": "", "truncated": False,
                        "duration_ms": finished["duration_ms"], "statements": None,
                        "blocked": None, "output_path": None, "output_bytes": 2,
                        "image": None, "saved_path": None, "late": False,
                        "request_id": "req_1", "turn": 1}


def test_runtime_tools_emit_pair_with_executor_runtime():
    events, bridge = [], SpyBridge()
    loop = _loop()  # docs_search is None, so search_docs answers with an error
    loop._call = scripted_call([("", [tool_use("tc_0", "search_docs", query="mol new")]),
                                ("ok", [])])
    run_loop(loop, bridge=bridge, ctx=RunContext("req_2", CHAT_ID, on_event=events.append))
    assert bridge.calls == []
    started, = _meta(events, "tool.started")
    finished, = _meta(events, "tool.finished")
    assert (started["executor"], finished["executor"]) == ("runtime", "runtime")
    assert finished["ok"] is False
    assert "search_docs is unavailable" in finished["error"]


def test_rescued_origin(monkeypatch):
    call_json = '{"name": "run_vmd_command", "arguments": {"command": "mol new 1hck.pdb"}}'
    monkeypatch.setattr(urllib.request, "urlopen",
                        FakeUrlopen([ollama_text(call_json), ollama_text("Loaded.")]))
    events, bridge = [], SpyBridge()
    loop = ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b", options=LoopOptions())
    out = run_loop(loop, bridge=bridge, ctx=RunContext("req_r", CHAT_ID, on_event=events.append))
    assert out == "Loaded."
    assert [(s["origin"], s["tool_call_id"]) for s in _meta(events, "tool.started")] == [
        ("rescued", "otc_rescue_1")]
    sealed = [e["text"] for e in events if e["type"] == "message"]
    assert sealed == ["", "Loaded."]  # sealing hides the JSON the rescue consumed
    assert bridge.calls[0]["tool_input"] == {"command": "mol new 1hck.pdb"}


def test_messages_out_canonical_ids():
    events, out, seen = [], [], []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])], seen=seen)
    run_loop(loop, prompt="load it",
             ctx=RunContext("req_3", CHAT_ID, on_event=events.append, messages_out=out))
    key = _meta(events, "tool.started")[0]["call_key"]
    assert out[0] == {"role": "user", "content": "load it"}
    assert out[1]["content"][1]["id"] == "call_" + key
    assert out[2]["content"][0]["tool_use_id"] == "call_" + key
    # The in-run history that turn 2 sent keeps the model's own ids.
    assert seen[1][1]["content"][1]["id"] == "tc_0"
    assert seen[1][2]["content"][0]["tool_use_id"] == "tc_0"


def test_final_turn_only_in_messages_out():
    out, seen = [], []
    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])], seen=seen)
    run_loop(loop, ctx=RunContext("req_4", CHAT_ID, messages_out=out))
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    assert out[3] == {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}
    assert len(seen) == 2 and len(seen[1]) == 3  # no request ever carries the final turn
    assert loop.last_final_text_empty is False

    empty_out = []
    loop = _loop()
    loop._call = scripted_call([("", [LOAD]), ("", [])])
    run_loop(loop, ctx=RunContext("req_5", CHAT_ID, messages_out=empty_out))
    assert [m["role"] for m in empty_out] == ["user", "assistant", "user"]
    assert loop.last_final_text_empty is True


def test_on_event_exception_does_not_break_run():
    class BrokenOut:
        def append(self, message):
            raise OSError("disk full")

    def broken_sink(item):
        raise RuntimeError("sink broke")

    loop = _loop()
    loop._call = scripted_call([("Loading.", [LOAD]), ("Done.", [])])
    ctx = RunContext("req_6", CHAT_ID, on_event=broken_sink, messages_out=BrokenOut())
    assert run_loop(loop, ctx=ctx) == "Done."
    assert loop.last_status == "complete"
    assert loop.last_tool_calls == 1


def test_recorder_chat_id_from_ctx():
    recorder = StatusRecorder()
    loop = ClaudeToolLoop("openrouter", "sk-or-test", "test/model", recorder=recorder)
    loop._call = scripted_call([("hi", [])])
    run_loop(loop, ctx=RunContext("req_7", CHAT_ID))
    assert recorder.chat_id == CHAT_ID
    run_loop(loop)  # ctx=None keeps the benchmark's session_id
    assert recorder.chat_id == "sess_test"
```

- [ ] **Step 2: Add the bridge-guard tests**

Append to `tests/test_benchmark_bridge_guard.py` (it already defines `LEGACY_KWARGS`, `run_guard` and `STRICT_BRIDGES`):

```python


# --- M1 (plan 02, P02-T08): product options and call metadata ---------------

import re as _re
import threading as _threading
from unittest import mock as _mock

from helpers.fake_provider import scripted_call as _scripted_call
from vmd_ai_runtime.claude_loop import ClaudeToolLoop as _Loop
from vmd_ai_runtime.claude_loop import LoopOptions as _LoopOptions
from vmd_ai_runtime.claude_loop import RunContext as _RunContext


def test_product_options_strict_bridges_six_keywords():
    """The product preset changes nothing about how strict bridges are called."""
    for name, factory in STRICT_BRIDGES:
        loop = _Loop(provider_name="openrouter", api_key="sk-or-guard", model="guard/model",
                     options=_LoopOptions.product({"provider": "openrouter", "model": "guard/model"}))
        calls = run_guard(loop, factory())
        assert calls, f"{name}: the scripted run made no tool calls"
        for kwargs in calls:
            assert set(kwargs) == LEGACY_KWARGS, (name, sorted(kwargs))


class _MetaBridge:
    """Opts in on its class, like the product VmdToolBridge will (plan 05)."""

    supports_call_meta = True

    def __init__(self):
        self.calls = []

    def execute_tool(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "output": "ok", "error": ""}


class _Delegating:
    """Forwards attribute access like RetrievalAugmentingBridge/ExploreScaffoldBridge."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _drive_one_call(bridge, *, options=None, ctx=None):
    loop = _Loop("openrouter", "sk-or-guard", "guard/model", options=options)
    loop._call = _scripted_call([
        ("", [{"type": "tool_use", "id": "tc_0", "name": "run_vmd_command",
               "input": {"command": "puts hi"}}]),
        ("done", []),
    ])
    loop.run(prompt="p", system_prompt="", tool_bridge=bridge, session_id="sess_guard",
             session_queue=None, cancel_event=_threading.Event(),
             on_chunk=lambda chunk: None, ctx=ctx)


def test_supports_call_meta_class_attr_gets_call_key():
    bridge = _MetaBridge()
    ctx = _RunContext("req_guard", "chat_0123456789ab")
    _drive_one_call(bridge, ctx=ctx,
                    options=_LoopOptions.product({"provider": "openrouter", "model": "guard/model"}))
    kwargs, = bridge.calls
    assert set(kwargs) == LEGACY_KWARGS | {"call_key", "request_id"}
    assert _re.fullmatch(r"[0-9a-f]{12}", kwargs["call_key"])
    assert kwargs["request_id"] == "req_guard"
    plain = _MetaBridge()
    _drive_one_call(plain)  # options=None and ctx=None: the class still opts in
    assert plain.calls[0]["request_id"] is None


def test_getattr_delegating_wrapper_not_opted_in():
    inner = _MetaBridge()
    wrapper = _Delegating(inner)
    assert wrapper.supports_call_meta is True  # the instance says yes...
    _drive_one_call(wrapper, options=_LoopOptions())
    assert set(inner.calls[0]) == LEGACY_KWARGS  # ...but only the class counts

    class _Plain:
        def __init__(self):
            self.calls = []

        def execute_tool(self, **kwargs):
            self.calls.append(kwargs)
            return {"ok": True, "output": "ok", "error": ""}

    plain = _Plain()
    plain.supports_call_meta = True  # an instance attribute never opts in
    _drive_one_call(plain, options=_LoopOptions())
    assert set(plain.calls[0]) == LEGACY_KWARGS

    mocked = _mock.MagicMock()
    mocked.execute_tool.return_value = {"ok": True, "output": "ok", "error": ""}
    _drive_one_call(mocked, options=_LoopOptions())
    assert set(mocked.execute_tool.call_args.kwargs) == LEGACY_KWARGS
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python -m pytest tests/test_loop_events.py tests/test_benchmark_bridge_guard.py -q`
Expected: 6 of the 7 tests in `test_loop_events.py` fail (`test_event_sequence_two_turns` gets an empty event list, `test_runtime_tools_emit_pair_with_executor_runtime` and `test_rescued_origin` find no `tool.started`, `test_messages_out_canonical_ids` and `test_final_turn_only_in_messages_out` see an empty `messages_out`, `test_recorder_chat_id_from_ctx` sees `'sess_test' == 'chat_0123456789ab'`); `test_on_event_exception_does_not_break_run` already passes. In the bridge guard, `test_supports_call_meta_class_attr_gets_call_key` fails because `call_key` is missing; the P01 guard tests, `test_product_options_strict_bridges_six_keywords` and `test_getattr_delegating_wrapper_not_opted_in` pass already.

- [ ] **Step 4: Add the imports**

In `runtime/vmd_ai_runtime/claude_loop.py` replace:

```python
import base64
import dataclasses
```

with:

```python
import base64
import copy
import dataclasses
```

and replace the line `import urllib.request` with:

```python
import urllib.request
import uuid
```

- [ ] **Step 5: Report rescued call ids from Ollama**

In `_stream_ollama` replace:

```python
            logger.info(
                "ollama: rescued %d tool call(s) from JSON-in-content "
                "(model=%s)", len(rescued), model,
            )
```

with:

```python
            logger.info(
                "ollama: rescued %d tool call(s) from JSON-in-content "
                "(model=%s)", len(rescued), model,
            )
            if on_meta is not None:
                # The loop marks these calls origin "rescued" (§2c).
                on_meta({"kind": "rescued", "ids": [str(b["id"]) for b in rescued]})
```

- [ ] **Step 6: Add the contract helpers**

Replace the banner:

```python
# ---------------------------------------------------------------------------
# The Claude tool loop
# ---------------------------------------------------------------------------
```

with:

```python
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
```

- [ ] **Step 7: Add the per-tool and sink methods**

Replace:

```python
    def run(
        self,
        prompt: str,
```

with:

```python
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
```

- [ ] **Step 8: Replace `run`**

Replace the whole `run` method (from `    def run(` to its `        return final_text`, just before the `# Recorder hooks` banner) with:

```python
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

        self._ctx = ctx
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
                    text, tool_blocks = self._call_turn(
                        messages, system_prompt, on_text, cancel_event,
                    )
                except (ClaudeLoopError, RunCancelled):
                    raise
                except Exception as exc:
                    raise ClaudeLoopError(
                        f"API call failed on turn {turn + 1}: {exc}"
                    ) from exc

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
                        origin="rescued" if tool_id in rescued_ids else "model",
                    )
                    tool_result_blocks.append(
                        _build_tool_result_block(
                            tool_use_id=tool_id,
                            result=result,
                            include_image=self._is_anthropic_direct,
                        )
                    )
                    result_keys.append(call_key)

                # --- Append tool results to conversation ---
                if tool_result_blocks:
                    messages.append(
                        {"role": "user", "content": tool_result_blocks}
                    )
                    self._out(_canonical_message(messages[-1], result_keys))
            else:
                logger.warning("hit max turns (%d) without finishing",
                               max_turns)
                end_status = "max_turns"
        except RunCancelled:
            end_status = "cancelled"
            logger.info("stopped during a provider backoff")
        except Exception:
            end_status = "error"
            raise
        finally:
            self.last_status = end_status
            self._recorder_end_task(end_status)
            self._ctx = None

        return final_text
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loop_events.py tests/test_benchmark_bridge_guard.py tests/test_loop_flags.py tests/test_claude_loop_recorder.py tests/test_recorder_integration.py tests/test_agent_integration.py tests/test_wiki_tools_integration.py -q`
Expected: all passed (`7 passed` in `test_loop_events.py`; the bridge guard gains 3 passing tests).

Run: `SUITE` then `GUARDS`, then `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`.
Expected: `0 failed`, `1 xfailed`; guards all passed; `62 passed` (the explore arm's zero-argument `_tools_for_turn` lambda still works).

- [ ] **Step 10: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/test_loop_events.py tests/test_benchmark_bridge_guard.py
git commit -m "feat(loop): call_key, on_event emission and canonical messages_out

Every tool execution gets a 12-hex call_key; only bridges whose class
declares supports_call_meta receive call_key/request_id. With a ctx the
loop emits turn.started, assistant chunks, per-turn assistant/message,
tool.started/tool.finished (executor tcl|runtime, origin model|rescued)
and appends deep copies with call_<key> ids to messages_out, including
the final text-only turn. The recorder uses ctx.chat_id. The in-run
messages and every request body are unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: P02-T09 — Rescue modes all/json/off (S12)

**Files:**
- Create: `tests/test_rescue_modes.py`
- Modify: `runtime/vmd_ai_runtime/claude_loop.py` — `_rescue_json_tool_calls` signature and docstring end (`:897-936`), pass 2 gate (`:1025-1031`), `_stream_ollama` rescue call (`:1190-1192`)

**Interfaces:**
- Consumes: `LoopOptions.rescue` (P02-T05); tool.started emission (P02-T08)
- Produces:
  - `_rescue_json_tool_calls(text: str, allowed_names: set, mode: str = 'all') -> List[Dict[str, Any]]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rescue_modes.py`:

```python
"""P02-T09: rescue modes all / json / off (§2f Rescue, S12)."""
from __future__ import annotations

import urllib.request

from helpers.fake_provider import FakeUrlopen, SpyBridge, ollama_text, run_loop
from vmd_ai_runtime.claude_loop import (
    ClaudeToolLoop,
    LoopOptions,
    RunContext,
    _rescue_json_tool_calls,
)

CHAT_ID = "chat_0123456789ab"
ALLOWED = {"run_vmd_command", "capture_vmd_snapshot"}
TCL_PROSE = (
    "To load it in VMD you would run:\n\n"
    "```tcl\nmol new 1hck.pdb\nmol modstyle 0 top NewCartoon\n```\n\n"
    "That shows the cartoon."
)
JSON_CALL = '{"name": "run_vmd_command", "arguments": {"command": "mol new 1hck.pdb"}}'


def _product_loop():
    profile = {"provider": "ollama", "model": "qwen3.8:27b", "base_url": "http://ollama.test"}
    return ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b",
                          options=LoopOptions.product(profile))


def _started(events):
    return [e["metadata"] for e in events if e["metadata"].get("kind") == "tool.started"]


def test_json_mode_ignores_fenced_tcl(monkeypatch):
    """S12: a prose answer with a ```tcl block runs nothing in the product."""
    fake = FakeUrlopen([ollama_text(TCL_PROSE)])
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    events, bridge = [], SpyBridge()
    loop = _product_loop()
    assert loop.options.rescue == "json"
    out = run_loop(loop, prompt="how do I load 1hck?", bridge=bridge,
                   ctx=RunContext("req_s12", CHAT_ID, on_event=events.append))
    assert out == TCL_PROSE  # the answer is kept as prose
    assert bridge.calls == []  # nothing reached VMD, so no tool_start was pushed
    assert _started(events) == []
    assert len(fake.chat_requests) == 1
    assert _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="json") == []


def test_json_mode_rescues_offered_tool_json(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        FakeUrlopen([ollama_text(JSON_CALL), ollama_text("Loaded.")]))
    events, bridge = [], SpyBridge()
    out = run_loop(_product_loop(), bridge=bridge,
                   ctx=RunContext("req_json", CHAT_ID, on_event=events.append))
    assert out == "Loaded."
    assert [c["tool_input"] for c in bridge.calls] == [{"command": "mol new 1hck.pdb"}]
    assert [s["origin"] for s in _started(events)] == ["rescued"]
    blocks = _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="json")
    assert [(b["name"], b["input"]) for b in blocks] == [
        ("run_vmd_command", {"command": "mol new 1hck.pdb"})]


def test_json_mode_rejects_unknown_tool():
    unknown = '{"name": "delete_everything", "arguments": {"path": "/"}}'
    assert _rescue_json_tool_calls(unknown, ALLOWED, mode="json") == []
    mixed = "```json\n" + unknown + "\n```\n```tcl\nfile delete -force ~/data\n```"
    assert _rescue_json_tool_calls(mixed, ALLOWED, mode="json") == []
    # The same text in "all" mode would run the Tcl block: that is why the
    # product uses "json".
    assert _rescue_json_tool_calls(mixed, ALLOWED, mode="all")[0]["input"] == {
        "command": "file delete -force ~/data"}


def test_off_mode(monkeypatch):
    assert _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="off") == []
    assert _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="off") == []
    monkeypatch.setattr(urllib.request, "urlopen", FakeUrlopen([ollama_text(JSON_CALL)]))
    bridge = SpyBridge()
    loop = ClaudeToolLoop("ollama", "http://ollama.test", "qwen3.8:27b",
                          options=LoopOptions(rescue="off"))
    assert run_loop(loop, bridge=bridge) == JSON_CALL
    assert bridge.calls == []


def test_all_mode_unchanged():
    default = _rescue_json_tool_calls(TCL_PROSE, ALLOWED)
    assert default == _rescue_json_tool_calls(TCL_PROSE, ALLOWED, mode="all")
    assert default == [{"type": "tool_use", "id": "", "name": "run_vmd_command",
                        "input": {"command": "mol new 1hck.pdb\nmol modstyle 0 top NewCartoon"}}]
    assert (_rescue_json_tool_calls(JSON_CALL, ALLOWED)
            == _rescue_json_tool_calls(JSON_CALL, ALLOWED, mode="all"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_rescue_modes.py -q`
Expected: `5 failed`. The four tests that pass `mode=` fail with `TypeError: _rescue_json_tool_calls() got an unexpected keyword argument 'mode'`, and `test_json_mode_ignores_fenced_tcl` fails with `ClaudeLoopError: Ollama stream failed: unexpected extra request: POST http://ollama.test/api/chat`: the product loop still rescues the ```tcl block, runs it, and asks the model again.

- [ ] **Step 3: Add the mode to `_rescue_json_tool_calls`**

Replace:

```python
def _rescue_json_tool_calls(
    text: str,
    allowed_names: set,
) -> List[Dict[str, Any]]:
```

with:

```python
def _rescue_json_tool_calls(
    text: str,
    allowed_names: set,
    mode: str = "all",
) -> List[Dict[str, Any]]:
```

Replace:

```python
    Returns the list of synthesized tool_use blocks (empty if none).
    Conservative on purpose: we'd rather miss a rescue than fire on
    unrelated content.
    """
    if not text or not allowed_names:
        return []
```

with:

```python
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
```

Replace:

```python
    # ---- Pass 2: ```tcl / ```vmd code blocks ------------------------
    # qwen2.5-coder and similar code-tuned local models often dodge the
    # tool schema entirely and emit "here's the Tcl I'd run" in a
    # fenced ```tcl block. Treat that as an implicit run_vmd_command
    # invocation when the model was offered that tool.
    if "run_vmd_command" not in allowed_names:
        return []
```

with:

```python
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
```

- [ ] **Step 4: Use the profile's mode in `_stream_ollama`**

Replace:

```python
    if not final_tool_blocks and text:
        allowed = {str(t.get("name") or "") for t in tools_list if t.get("name")}
        rescued = _rescue_json_tool_calls(text, allowed)
```

with:

```python
    # Rescue mode (§2f): options=None keeps "all"; the product uses "json".
    rescue_mode = opts.rescue if opts is not None else "all"
    if not final_tool_blocks and text and rescue_mode != "off":
        allowed = {str(t.get("name") or "") for t in tools_list if t.get("name")}
        rescued = _rescue_json_tool_calls(text, allowed, mode=rescue_mode)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_rescue_modes.py tests/test_ollama_loop.py tests/test_loop_events.py -q`
Expected: all passed except the one xfail (`5 passed` in the new module; `RescueJsonToolCallsTests` and `StreamOllamaJsonRescueTests` still pass on the default `all` mode).

Run: `SUITE` then `GUARDS`.
Expected: `0 failed`, `1 xfailed`; guards all passed, including the Ollama rescue golden (`options=None` keeps `all`).

- [ ] **Step 6: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/test_rescue_modes.py
git commit -m "feat(loop): rescue modes all/json/off; prose Tcl never runs in the product (S12)

_rescue_json_tool_calls(text, allowed, mode): 'all' keeps both passes
(options=None), 'json' rescues only tool-call-shaped JSON that names an
offered tool, 'off' rescues nothing. _stream_ollama takes the mode from
LoopOptions.rescue; the product preset uses 'json', so a ```tcl block in
a prose answer emits no tool.started and never reaches VMD.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: P02-T10 — loop_factory: a fresh loop per request, compat setter, real session lock

**Files:**
- Create: `tests/test_loop_factory.py`
- Modify: `runtime/vmd_ai_runtime/app.py` — import (`:19`), constructor signature (after P02-T02), provider/loop block (`:110-128`), `chat.send` (`:230-287`), `settings.get` and `session.start` `agent_loop` lines (`:219`, `:350`), `provider.set` (`:371-409`), `_run_claude_loop_response` (`:557-677`)
- Modify: `runtime/vmd_ai_runtime/sessions.py` (`SessionState`, after the P02-T02 fields)

**Interfaces:**
- Consumes: `ClaudeToolLoop(options=)`, `run(ctx=)`, `RunContext` (P02-T05); `helpers.runtime_fixture` (P02-T02)
- Produces:
  - `RuntimeApp(..., loop_factory: Optional[Callable[[Dict[str, Any]], Optional[ClaudeToolLoop]]] = None)`
  - `RuntimeApp.claude_loop` property; its setter installs a factory that returns the assigned object
  - `RuntimeApp.profile_for_session(state: SessionState) -> Optional[Dict[str, Any]]` (legacy {provider, model})
  - `RuntimeApp.has_agent_loop(state: Optional[SessionState] = None) -> bool`
  - `SessionState.lock: threading.Lock`
  - Factory contract (for every later `loop_factory`, including plan 06's `ScriptedLoopFactory`): the app calls the factory once per `chat.send` for the loop that runs, and also from `has_agent_loop` (for the startup log line, on `session.start` and `settings.get`, and, through `_base_loop_factory`, on `provider.set`) only to learn whether the answer is `None`. A factory must therefore be cheap and side-effect free: building a loop must not consume scripted turns or touch the network; scripted state is consumed when the loop runs.
  - (plan additions) the `claude_loop` getter returns only the loop assigned from outside (or None); `provider.set` drops an assigned loop and restores the base factory; `RuntimeApp._default_loop_factory(profile)`; `RuntimeApp._build_loop(profile)` (raises `PROVIDER_INIT_FAILED`); the worker passes `ctx=RunContext(request_id, chat_id)` so product recorder manifests carry the real chat id. Plan 03 (P03-T04/T08) fills `ctx.messages_out` and makes token sessions read the active profile.

- [ ] **Step 1: Write the failing test**

Create `tests/test_loop_factory.py`:

```python
"""P02-T10: a fresh loop per request, the claude_loop compat setter and a real session lock (§3 app.py)."""
from __future__ import annotations

import threading
import time

from helpers.runtime_fixture import make_app, rpc, start_tokenless_session, wait_idle
from vmd_ai_runtime.claude_loop import ClaudeToolLoop, RunContext

DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"  # DEFAULT_SETTINGS["model"]


class FakeLoop(ClaudeToolLoop):
    """A ClaudeToolLoop whose _call returns one text turn and records what it saw."""

    def __init__(self, release=None):
        super().__init__(provider_name="openrouter", api_key="sk-or-test", model=DEFAULT_MODEL)
        self.release = release
        self.seen_ctx = []
        self.seen_recorders = []

    def run(self, *args, **kwargs):
        self.seen_ctx.append(kwargs.get("ctx"))
        return super().run(*args, **kwargs)

    def _call(self, messages, system_prompt, on_text, should_cancel):
        self.seen_recorders.append(self.recorder)
        if self.release is not None:
            self.release.wait(5)
        on_text("done")
        return "done", []


def _send(app, session, text="hi", **extra):
    return rpc(app, "chat.send", dict(text=text, **extra), session=session)


def _spy_runs(monkeypatch):
    """Record the loop object behind every run() call; _call answers at once."""
    used = []
    original = ClaudeToolLoop.run

    def spy(self, *args, **kwargs):
        used.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ClaudeToolLoop, "run", spy)
    monkeypatch.setattr(ClaudeToolLoop, "_call",
                        lambda self, messages, system_prompt, on_text, should_cancel: ("done", []))
    return used


def test_concurrent_send_conflict(tmp_path):
    release = threading.Event()

    def slow_factory(profile):
        time.sleep(0.1)  # widen the window between the conflict check and the start
        return FakeLoop(release=release)

    app = make_app(tmp_path, loop_factory=slow_factory)
    session = start_tokenless_session(app, cwd=str(tmp_path))
    barrier = threading.Barrier(2)
    results = []

    def worker():
        barrier.wait()
        results.append(_send(app, session))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    release.set()
    wait_idle(app, session["session_id"])
    started = [r for r in results if "result" in r]
    conflicts = [r for r in results if r.get("error", {}).get("code") == "REQUEST_CONFLICT"]
    assert (len(started), len(conflicts)) == (1, 1), results


def test_per_request_loop_gets_wiki_store(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app = make_app(tmp_path, provider_mode="openrouter", enable_wiki=True,
                   wiki_root=str(tmp_path / "wiki"), wiki_raw_root=str(tmp_path / "raw"))
    assert app.wiki_store is not None
    used = _spy_runs(monkeypatch)
    session = start_tokenless_session(app, cwd=str(tmp_path))
    assert "result" in _send(app, session, model="other/model")
    wait_idle(app, session["session_id"])
    assert len(used) == 1
    assert used[0].model == "other/model"
    assert used[0].wiki_store is app.wiki_store  # the old model override dropped it


def test_recorder_not_shared(tmp_path):
    built = []

    def factory(profile):
        loop = FakeLoop()
        built.append(loop)
        return loop

    app = make_app(tmp_path, loop_factory=factory)
    cwd_a, cwd_b = tmp_path / "a", tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    for cwd in (cwd_a, cwd_b):
        session = start_tokenless_session(app, cwd=str(cwd))
        assert "result" in _send(app, session)
        wait_idle(app, session["session_id"])
    ran = [loop for loop in built if loop.seen_recorders]
    assert len(ran) == 2 and ran[0] is not ran[1]
    rec_a, rec_b = ran[0].seen_recorders[0], ran[1].seen_recorders[0]
    assert rec_a is not rec_b
    assert rec_a.runs_root == cwd_a.resolve() / ".vmdai_runs"
    assert rec_b.runs_root == cwd_b.resolve() / ".vmdai_runs"


def test_assigned_claude_loop_used(tmp_path):
    app = make_app(tmp_path)  # mock provider: no loop of its own
    assert app.claude_loop is None
    assert app.has_agent_loop() is False
    fake = FakeLoop()
    app.claude_loop = fake
    assert app.claude_loop is fake
    assert app.has_agent_loop() is True
    session = start_tokenless_session(app, cwd=str(tmp_path))
    assert session["agent_loop"] is True
    sent = _send(app, session)["result"]
    wait_idle(app, session["session_id"])
    ctx, = fake.seen_ctx
    assert isinstance(ctx, RunContext)
    assert (ctx.request_id, ctx.chat_id) == (sent["request_id"], session["chat_id"])
    assert fake.recorder is None  # the shared loop never keeps a request's recorder


def test_provider_set_does_not_assign_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    app = make_app(tmp_path)
    fake = FakeLoop()
    app.claude_loop = fake
    session = start_tokenless_session(app, cwd=str(tmp_path))
    resp = rpc(app, "provider.set", {"provider": "openrouter", "model": DEFAULT_MODEL},
               session=session)
    assert resp["result"]["agent_loop"] is True
    assert app.claude_loop is None  # provider.set never installs a shared loop
    used = _spy_runs(monkeypatch)
    for _ in range(2):
        assert "result" in _send(app, session)
        wait_idle(app, session["session_id"])
    assert len(used) == 2
    assert used[0] is not used[1]
    assert all(loop is not fake for loop in used)
    assert fake.seen_ctx == [] and fake.recorder is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_loop_factory.py -q`
Expected: `5 failed` — `test_concurrent_send_conflict` and `test_recorder_not_shared` with `TypeError: RuntimeApp.__init__() got an unexpected keyword argument 'loop_factory'`, `test_assigned_claude_loop_used` with `AttributeError: 'RuntimeApp' object has no attribute 'has_agent_loop'`, `test_per_request_loop_gets_wiki_store` with `assert None is <...WikiStore...>`, and `test_provider_set_does_not_assign_loop` on `assert app.claude_loop is None`.

- [ ] **Step 3: Give `SessionState` a real lock**

In `runtime/vmd_ai_runtime/sessions.py` replace:

```python
    # Sanitised VMD/Tcl versions from session.start (C6); token sessions only.
    vmd_env: Optional[Dict[str, str]] = None
```

with:

```python
    # Sanitised VMD/Tcl versions from session.start (C6); token sessions only.
    vmd_env: Optional[Dict[str, str]] = None
    # Held by chat.send while it checks for and starts a request (§3).
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
```

- [ ] **Step 4: Import `RunContext` and accept `loop_factory`**

In `runtime/vmd_ai_runtime/app.py` replace:

```python
from .claude_loop import ClaudeToolLoop, ClaudeLoopError, VMD_SYSTEM_PROMPT, build_claude_loop, events_to_messages
```

with:

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

Replace:

```python
        on_shutdown: Optional[Callable[[], None]] = None,
    ):
        self.sessions = SessionManager()
```

with:

```python
        on_shutdown: Optional[Callable[[], None]] = None,
        loop_factory: Optional[Callable[[Dict[str, Any]], Optional[ClaudeToolLoop]]] = None,
    ):
        self.sessions = SessionManager()
```

- [ ] **Step 5: Replace the shared loop with the factory**

Replace:

```python
        self.provider_name, self.provider = build_provider(env_provider)

        # Build the Claude tool loop (None if no key / mock mode). The
        # docs_search instance is wired in here so the agent can call
        # search_docs when an index is available; the wiki_store is wired
        # in so the agent can call wiki_list / wiki_read / wiki_update /
        # wiki_verify_pins as the persistent knowledge base.
        self.claude_loop: ClaudeToolLoop | None = build_claude_loop(
            env_provider,
            docs_search=self.docs_search,
            wiki_store=self.wiki_store,
        )

        if self.logger:
            self.logger.info(
                "provider=%s agent_loop=%s",
                self.provider_name,
                self.claude_loop is not None,
            )
```

with:

```python
        self.provider_name, self.provider = build_provider(env_provider)

        # Every request gets a fresh ClaudeToolLoop from the loop factory
        # (§3), so no loop, recorder or model override is shared between
        # requests. The default factory builds from the legacy profile: the
        # env/--provider choice plus the model picked through provider.set.
        # The docs_search and wiki_store instances are wired into every loop.
        self._loop_provider = env_provider
        self._loop_model: Optional[str] = None
        self._base_loop_factory: Callable[[Optional[Dict[str, Any]]], Optional[ClaudeToolLoop]] = (
            loop_factory if loop_factory is not None else self._default_loop_factory
        )
        self._loop_factory = self._base_loop_factory
        self._assigned_loop: Optional[ClaudeToolLoop] = None

        if self.logger:
            self.logger.info(
                "provider=%s agent_loop=%s",
                self.provider_name,
                self.has_agent_loop(),
            )

    # ------------------------------------------------------------------
    # Loop factory (§3): a fresh ClaudeToolLoop per request
    # ------------------------------------------------------------------

    @property
    def claude_loop(self) -> Optional[ClaudeToolLoop]:
        """The loop assigned from outside (tests), or None.

        The runtime keeps no loop of its own: chat.send builds one per
        request through the loop factory. Assigning a loop installs a
        factory that returns that object, so tests that set
        ``app.claude_loop = FakeLoop(...)`` keep working unchanged.
        """
        return self._assigned_loop

    @claude_loop.setter
    def claude_loop(self, loop: Optional[ClaudeToolLoop]) -> None:
        self._assigned_loop = loop
        self._loop_factory = lambda _profile: loop

    def _default_loop_factory(self, profile: Optional[Dict[str, Any]]) -> Optional[ClaudeToolLoop]:
        """Build a loop for ``profile`` with the app's docs and wiki stores."""
        if not profile:
            return None
        return build_claude_loop(
            str(profile.get("provider") or ""),
            docs_search=self.docs_search,
            wiki_store=self.wiki_store,
            model=profile.get("model") or None,
        )

    def profile_for_session(self, state: Optional[SessionState] = None) -> Optional[Dict[str, Any]]:
        """The profile a request of ``state`` runs with.

        M1 foundation: the legacy profile {provider, model} from the
        env/--provider choice and the last provider.set. Plan 03 makes
        token sessions read the active profile in settings.json.
        """
        return {"provider": self._loop_provider, "model": self._loop_model}

    def has_agent_loop(self, state: Optional[SessionState] = None) -> bool:
        """True when a request of ``state`` would run the agent loop, not mock mode."""
        try:
            return self._loop_factory(self.profile_for_session(state)) is not None
        except Exception:
            if self.logger:
                self.logger.warning("loop factory failed", exc_info=True)
            return False

    def _build_loop(self, profile: Optional[Dict[str, Any]]) -> Optional[ClaudeToolLoop]:
        try:
            return self._loop_factory(profile)
        except Exception as exc:
            raise RpcError(
                "PROVIDER_INIT_FAILED",
                f"failed to build the agent loop: {exc}",
                {"provider": (profile or {}).get("provider")},
            )
```

- [ ] **Step 6: Make `chat.send` atomic and per-request**

Replace the whole `chat.send` branch — from `        if method == "chat.send":` through its `            return {"request_id": request_id}` (just before `        if method == "chat.cancel":`) — with:

```python
        if method == "chat.send":
            state = self._get_session(params["session_id"], session_token)
            if params.get("model"):
                state.settings["model"] = params["model"]
            if params.get("mode"):
                state.settings["mode"] = params["mode"]
            if params.get("conversation_mode"):
                state.settings["conversation_mode"] = params["conversation_mode"]

            # The session lock makes check-then-start atomic: two concurrent
            # chat.send calls on one session can never both start a request.
            with state.lock:
                active = state.active_request
                if active is not None and (active.thread is None or active.thread.is_alive()):
                    raise RpcError("REQUEST_CONFLICT", "an active request is already running")

                # A fresh loop for this request (None → mock mode).
                loop = self._build_loop(self.profile_for_session(state))

                request_id = f"req_{os.urandom(6).hex()}"
                request = RequestState(request_id=request_id)
                state.active_request = request

                user_event = state.queue.push(
                    "user", "message", params["text"], {"request_id": request_id}
                )
                self.store.append_events(state.chat_id, [user_event])

                # Auto-set chat title from the first user message
                manifest = self.store.get_manifest(state.chat_id)
                if manifest and manifest.get("message_count", 0) <= 1:
                    title = params["text"][:60].strip()
                    if len(params["text"]) > 60:
                        title += "..."
                    self.store.update_title(state.chat_id, title)

                # Build prior context when conversation_mode asks for it
                conv_mode = str(state.settings.get("conversation_mode") or "local_first")
                prior_messages = None
                if conv_mode in ("hybrid_resume", "resume_only") and loop is not None:
                    try:
                        raw_events = self.store.read_events(state.chat_id, limit=200)
                        prior_messages = events_to_messages(raw_events)
                    except Exception:
                        prior_messages = None

                # Use the agent loop when there is one; fall back to the simple provider
                if loop is not None:
                    target = self._run_claude_loop_response
                    args = (state.session_id, request_id, params["text"],
                            request.cancel_event, prior_messages, loop)
                else:
                    target = self._run_provider_response
                    args = (state.session_id, request_id, params["text"],
                            request.cancel_event, prior_messages)

                thread = threading.Thread(target=target, args=args, daemon=True)
                request.thread = thread
                thread.start()
            return {"request_id": request_id}
```

- [ ] **Step 7: Stop `provider.set` from installing a shared loop**

Replace the whole `provider.set` branch — from `        if method == "provider.set":` through its closing `            }` (just before `        # ---- Keys ----`) — with:

```python
        if method == "provider.set":
            state = self._get_session(params["session_id"], session_token)
            requested = str(params["provider"] or "").strip().lower()
            if not requested:
                raise RpcError("INVALID_PARAMS", "provider is required")

            picked_model = str(params.get("model") or "").strip() or None
            try:
                provider_name, provider = build_provider(requested)
                agent_loop = self._base_loop_factory(
                    {"provider": requested, "model": picked_model}
                ) is not None
            except Exception as exc:
                raise RpcError(
                    "PROVIDER_INIT_FAILED",
                    f"failed to initialize provider '{requested}': {exc}",
                    {"provider": requested},
                )

            self.provider_name, self.provider = provider_name, provider
            self._loop_provider = requested
            self._loop_model = picked_model
            # Never install a shared loop: drop any loop assigned from
            # outside and go back to a fresh loop per request (§3).
            self._assigned_loop = None
            self._loop_factory = self._base_loop_factory

            if picked_model:
                state.settings["model"] = picked_model

            if self.logger:
                self.logger.info(
                    "provider switched to %s (agent_loop=%s, model=%s)",
                    self.provider_name,
                    agent_loop,
                    state.settings.get("model"),
                )

            return {
                "ok": True,
                "provider": self.provider_name,
                "agent_loop": agent_loop,
                "model": state.settings.get("model"),
            }
```

Then use Edit with `replace_all: true`: old `                "agent_loop": self.claude_loop is not None,` new `                "agent_loop": self.has_agent_loop(state),`.

Run: `grep -n "claude_loop is not None\|self.claude_loop" runtime/vmd_ai_runtime/app.py`
Expected: no output (session.start and settings.get now call `has_agent_loop(state)`).

- [ ] **Step 8: Run the request with the loop chat.send built**

Replace the whole `_run_claude_loop_response` method — from `    def _run_claude_loop_response(` through its last lines

```python
        # Unbind the per-task recorder so the shared loop doesn't carry
        # this run's recorder into the next chat.send.
        if loop is not None:
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
        prior_messages: list | None = None,
        loop: ClaudeToolLoop | None = None,
    ) -> None:
        """
        Full agentic response: the model calls VMD tools as needed until done.
        Runs on a daemon thread with the loop chat.send built for this
        request; pushes chunk/lifecycle events to the queue.
        """
        state = self.sessions.get(session_id)
        if state is None:
            return
        if loop is None:
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            return

        model = str(state.settings.get("model") or DEFAULT_SETTINGS["model"])
        mode = str(state.settings.get("mode") or "work")
        system_prompt = VMD_SYSTEM_PROMPT + f"\n\nMode: {mode}."
        chunk_events = []

        def on_chunk(chunk: str) -> None:
            ev = state.queue.push(
                "assistant", "chunk", chunk, {"request_id": request_id}
            )
            chunk_events.append(ev)

        def on_tool_start(tool_name: str, tool_input: dict) -> None:
            # Tool start events are pushed directly by VmdToolBridge
            pass

        def on_tool_result(tool_id: str, tool_name: str, result: dict) -> None:
            # Transcript entry for tool results is written in tool.command_result handler
            pass

        # The session's model setting overrides the loop's model, as before.
        # A per-request loop is adjusted in place. An assigned loop is shared
        # between requests, so it gets a copy, which now keeps the wiki store.
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

        # Build a per-task RunRecorder for this chat.send. The recorder
        # writes <state.cwd>/.vmdai_runs/<task_id>/transcript.tcl plus
        # snapshots — every successful tool call deposits a replayable
        # artifact on disk, automatically. Set VMD_AI_RECORDER=off to
        # disable. Falls back to ~/.vmdai/runs/ when state.cwd is empty
        # so we never silently drop artifacts.
        recorder = self._build_recorder_for_session(state)
        prev_recorder = loop.recorder
        loop.recorder = recorder
        ctx = RunContext(request_id=request_id, chat_id=state.chat_id)

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
            err_event = state.queue.push(
                "error",
                "message",
                f"Agent error: {exc}",
                {"request_id": request_id, "provider": self.provider_name},
            )
            self.store.append_events(state.chat_id, [err_event])
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            loop.recorder = prev_recorder
            return
        except Exception as exc:
            err_event = state.queue.push(
                "error",
                "message",
                f"Unexpected error: {exc}",
                {"request_id": request_id},
            )
            self.store.append_events(state.chat_id, [err_event])
            if state.active_request and state.active_request.request_id == request_id:
                state.active_request = None
            loop.recorder = prev_recorder
            return

        # Finalize
        events_to_persist = list(chunk_events)
        if cancel_event.is_set():
            cancel_ev = state.queue.push(
                "system", "lifecycle", "cancelled", {"request_id": request_id}
            )
            events_to_persist.append(cancel_ev)
        else:
            final_ev = state.queue.push(
                "assistant", "message", output, {"request_id": request_id}
            )
            events_to_persist.append(final_ev)

        if events_to_persist:
            self.store.append_events(state.chat_id, events_to_persist)

        if state.active_request and state.active_request.request_id == request_id:
            state.active_request = None

        # Unbind the per-task recorder so an assigned (shared) loop doesn't
        # carry this run's recorder into the next chat.send.
        loop.recorder = prev_recorder
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `python -m pytest tests/test_loop_factory.py tests/test_agent_integration.py tests/test_recorder_integration.py tests/test_provider_selection.py tests/test_ollama_app_wiring.py tests/test_runtime_integration.py tests/test_tool_command_result_auth.py tests/test_security_notice.py tests/test_launch_token.py -q`
Expected: all passed (`5 passed` in `test_loop_factory.py`; `test_agent_integration.py:202` and `test_recorder_integration.py:46` still assign `app.claude_loop` and pass unchanged, including `test_recorder_unbound_after_run`).

Run: `SUITE` then `GUARDS`, then `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`.
Expected: `0 failed`, `1 xfailed`; guards all passed; `62 passed`.

- [ ] **Step 10: Commit**

```bash
git add runtime/vmd_ai_runtime/app.py runtime/vmd_ai_runtime/sessions.py tests/test_loop_factory.py
git commit -m "feat(app): fresh loop per request via loop_factory; real session lock

chat.send builds a loop per request from RuntimeApp(loop_factory=) or the
default factory (legacy {provider, model} profile), under a per-session
lock, so two sends can never both start. Model overrides keep the wiki
store, recorders are never shared, and provider.set no longer installs a
shared loop. Assigning app.claude_loop still works for tests. The worker
passes RunContext(request_id, chat_id), so product run manifests carry
the real chat id.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Plan exit check

Run from the repo root on `chatvmd-r1-02-m1-runtime-foundation`:

- [ ] `env -u VMD_AI_PROVIDER python -m pytest tests -q` — `0 failed`, `1 xfailed` (`test_unreachable_host_raises_with_hint`; plan 04 removes the mark), under 60 s; exactly BASELINE + 83 passed (8 + 11 + 4 + 11 + 10 + 9 + 10 + 10 + 5 + 5 new tests in tasks 1–10; 555 + 83 = 638 on the dev Mac), in about 15 s.
- [ ] `python -m pytest tests/test_benchmark_golden_requests.py tests/test_benchmark_retry_pin.py tests/test_benchmark_bridge_guard.py tests/test_benchmark_hashes.py -q` — all passed.
- [ ] `git diff main -- tests/fixtures/golden_requests integrations/scivisagentbench/vmd_ai_agent.py` — empty.
- [ ] `python -m pytest vmdbench/tests -q` — `90 passed`.
- [ ] `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q` — `62 passed`.
- [ ] `python -m pytest tests/test_py39_compat.py -q` — passed on the dev Mac (imports every runtime module, including `vmd_ai_runtime.launch`, under `/usr/bin/python3` 3.9.6, and runs `main.py --help`).
- [ ] Push the branch; the CI 3.9 and 3.12 jobs are green.
- [ ] Exit criteria covered: S4 (`test_sigterm_exits_within_2s`, `test_sigterm_during_active_request_exits_within_2s`, `test_sigterm_during_tool_wait_exits_within_2s`, `test_stdin_eof_exits_within_2s`); S11 (`test_server_security.py`, `test_launch_token.py`); S12 (`test_json_mode_ignores_fenced_tcl`); S7 (goldens unchanged, `test_product_options_strict_bridges_six_keywords`); §2a flag rows connect_retries, classify_errors, cancellable_backoff (`test_stream_request_flags.py`), report_cancelled, turn_retry, raise_stream_errors, guard_truncation, max_turns (`test_loop_flags.py`), rescue (`test_rescue_modes.py`); §3 loop_factory (`test_loop_factory.py`).

## Verification record

Tasks 1–10 were applied step by step, exactly as written, to a scratch clone of `6f5f937` carrying plan 01's conftest, helpers, S7 goldens, bridge guard, hashes and 3.9 check. Every "run it to verify it fails" step failed with the stated error (after the corrections now in Task 1 Step 2 and Task 4 Step 2), and every "run the tests" step passed. The suite went from 518 to 600 passed (1 xfailed) in about 14 s under Python 3.12, and 600 passed under Python 3.9.6 (a `/usr/bin/python3` venv with pytest), including the `main.py` subprocess tests. The 13 S7 golden requests were byte-identical after every task, `vmdbench/tests` stayed at 90 passed and `integrations/` at 62 passed, and `scripts/dev_smoke.sh` ended with `[smoke] ok`. That scratch clone carried only the plan 01 pieces this plan touches, which is why its suite started at 518 rather than plan 01's exit total of 555.

A review pass then added `test_sigterm_during_tool_wait_exits_within_2s`, the fail-fast `_wait_token_file(proc)` and the `VMD_AI_ATTACH` port in both scripts, and re-ran them on the same clone: `tests/test_main_lifecycle.py` gives `11 failed in about 1 s` before Task 4 and `11 passed` after it (also under Python 3.9.6). The full suite gives 601 passed (1 xfailed) under Python 3.12 and under 3.9.6, the four guard files stay green, `integrations/` stays at 62 passed, and both smoke runs in Task 4 Step 5 end with `[smoke] ok`. Making the request worker a non-daemon thread makes both SIGTERM-during-request tests fail, so they do catch a regression.

## Deviations from skeleton

1. **New helper `tests/helpers/fake_provider.py` (P02-T05).** Not in the skeleton's file list. P02-T05..T09 need one shared fake provider; its `FakeUrlopen` answers the Ollama probe paths so the tests survive plan 04's preflight. It also holds `scripted_call`, `SpyBridge`, `StatusRecorder`, `run_loop` and the SSE/NDJSON builders.
2. **`server.py` sets `daemon_threads = True` and `block_on_close = False` (P02-T01), with the extra test `test_request_threads_do_not_block_exit`.** S4 needs request threads that never delay exit. `ThreadingHTTPServer` already defaults `daemon_threads` to True, so that line only records the intent; `block_on_close = False` is the functional change. The change sits in P02-T01 because that task owns `server.py`, so P02-T04 does not have to touch it.
3. **Extra tests beyond the skeleton lists:** `test_require_auth_raises_for_tokenless` (P02-T02), `test_runtime_shutdown_rpc_exits_within_2s` (P02-T04, pins the `on_shutdown` wiring in `main.py`), `test_sigterm_during_tool_wait_exits_within_2s` (P02-T04, the "tool wait" half of the second Review Focus item), `test_on_meta_enriches_and_forwards` (P02-T05).
4. **Extra `helpers.runtime_fixture` functions (P02-T02):** `start_tokenless_session` and `wait_idle`, used by P02-T10 and available to later plans. `start_token_session` defaults `cwd` to the temp HOME so recorder output never lands in the checkout.
5. **`event_protocol` negotiation in M1 (P02-T02).** session.start accepts 1 or 2 (anything else is `INVALID_PARAMS`), but the M1 runtime answers `event_protocol: 1` even when 2 is requested, because the v2 display events land in plan 07 (P07-T01 switches the answer to 2 for token sessions).
6. **`classify_unreachable` is declared but not acted on (P02-T05/T06).** The skeleton puts unreachable classification and its hints in P04-T01; this plan only adds the field. `_is_stream_drop` already refuses to retry any classified error (`code != "other"`), so P04's `ProviderUnreachableError` is never mistaken for a stream drop.
7. **`turn_retry` semantics (P02-T07).** The retry repeats only the model call with the same messages, so a tool that already ran is never run again, and each turn gets at most `turn_retry` retries. `test_turn_retry_not_after_tool_ran` pins exactly that (drop after a tool ran → the tool runs once; two drops in one turn → error; `options=None` → no retry). Note for plan 04: urllib wraps only send-side errors in `URLError`; a reset or a timeout raised by `getresponse()` before the first byte reaches `_is_stream_drop` unwrapped, so it also counts as a drop and is retried once, unless a streamer classifies it first (P04-T01 raises `ProviderUnreachableError` for the Ollama cases, which is never retried).
8. **`first_byte_timeout_s` (P02-T06)** is the `urlopen` timeout until the response opens; afterwards `_set_read_timeout` restores the per-read timeout on a best-effort basis (no-op on fakes).
9. **Anthropic SSE handling moved into `_anthropic_consume` (P02-T07)** so the `overloaded_error` retry can re-issue the request; with `raise_stream_errors` off (and always with `options=None`) the events are handled exactly as before.
10. **`LoopOptions.product` details not fixed by the spec:** `image_max_edge` is 1568 for `openrouter` as well as `anthropic-direct` (openrouter serves Claude by default; §2b groups the two for image limits); `supports_vision` defaults to `"auto"` except `openai-compatible`, which is `False` (§2f manual toggle); the `max_turns` keyword (the settings value) wins over a `max_turns` key in profile options; `tool_overrides` stays `None` (P04-T06 sets it for non-vision profiles); `first_byte_timeout_s` (120 s) is set for Ollama only, like `preflight`, because it bounds a cold model load (§2f, §5 "Cold model load"), so the other providers keep the per-read timeout (a profile can still set it in `options`).
11. **`_LOOP_ONLY_META` (P02-T05)** already lists `model_digest`, so plan 04 reads `self._turn_meta.get("model_digest")` without editing `_on_meta`.
12. **App wiring beyond the skeleton (P02-T10).** The `claude_loop` getter returns only a loop assigned from outside (or None) rather than building one; `provider.set` clears an assigned loop and restores the base factory; the worker passes `RunContext(request_id, chat_id)` with no sinks, so the product recorder already gets the real chat id (plan 03 adds `messages_out`, plan 07 adds `on_event`). `has_agent_loop` builds a loop to answer, which is cheap (no network). Because of that, every `loop_factory` must be side-effect free (Task 10 Interfaces, "Factory contract").
13. **Scripts (P02-T04)** also honour `VMD_AI_PYTHON`, `VMD_AI_PORT` and `VMD_AI_ATTACH` (the port part of `host:port`), as §7 requires, and `dev_smoke.sh` now reaches the runtime on that port instead of a hard-coded 8765.
