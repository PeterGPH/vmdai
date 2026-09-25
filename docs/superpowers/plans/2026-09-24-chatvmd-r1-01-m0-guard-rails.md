# ChatVMD Round 1 — Plan 01: ChatVMD R1 — M0 guard rails and CI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before any behaviour changes: pin today's `options=None` benchmark behaviour (S7), make `tests/` hermetic and under 60 s (S9), add the Tcl harness with VMD's http 2.9.5, record runner provenance, and run CI on Python 3.9 and 3.12 (C9).

**Architecture:** A root `pytest.ini` plus an autouse conftest fixture isolate every test from the owner's shell (env, `HOME`, keyring, backoff sleeps), and a small `tests/helpers/` package holds the shared test machinery: the live-gate snapshot, a keyring stub, the Tcl interpreter/package resolver, a stand-in `evaluation_framework` and the golden-request harness. The benchmark guard tests (golden requests, retry pin, bridge guard, hash pins) drive today's code unchanged; the only `runtime/` edit is the `_sleep` indirection. Runner provenance moves into one stdlib script, and a GitHub Actions workflow runs `tests/` on Ubuntu with Python 3.9 and 3.12.

**Tech Stack:** Python 3.9/3.12 stdlib + pytest (≥ 7, for the `pythonpath` ini key); Tcl 8.6 `tclsh` + `tcltest` 2, VMD 1.9.4a57's http 2.9.5 and json 1.1.2; bash; GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`).

**Spec:** `/Users/pinhaogu/Documents/GitHub/vmdai/docs/superpowers/specs/2026-09-24-chatvmd-round1-design.md` — this plan implements Part A §0 "M0 repository tasks"; §1 success criteria S7 and S9; §2a "`_sleep = time.sleep` hook" and "Guard tests" (golden requests, retry pin, bridge guard with `options=None`, hashes, image bytes, unreachable test); §2c "Thumbnails" (image-byte pin only); §6 "Hermetic base", "Benchmark guard", "tclsh … Interpreter / Packages", "Python 3.9 compatibility"; §7 "Benchmark"; §8 row M0; Part C C9 (CI, stub `keyring`, fake `evaluation_framework`, CI exclusions, "What CI proves", "Tcl and Tk in CI").

**Branch:** `chatvmd-r1-01-m0-guard-rails`, created from `main` (this plan depends on no other plan).

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

**Plan-specific constraints (Plan 01):**

- M0 changes no runtime behaviour. After this plan, `git diff baseline-2026-09-24 -- runtime/` shows only the `_sleep` indirection from P01-T02 (6 lines added, 2 changed). No other file under `runtime/` changes.
- `integrations/scivisagentbench/vmd_ai_agent.py` and `integrations/explore_arm/explore_agent.py` are not edited by this plan.
- `tests/helpers/` is imported as the package `helpers` (via `pythonpath = runtime tests` in `pytest.ini`). Helpers may call `pytest.skip`; they never read the live gates from `os.environ`, only from `helpers.live.LIVE_ENV`, the same snapshot the `live_env` fixture returns.
- `assert_golden` writes a golden file only when that file is missing *and* `CHATVMD_UPDATE_GOLDENS=1`; it never overwrites an existing S7 golden. The 13 golden files must hash to the SHA-256 values listed in P01-T04 and P01-T05; a mismatch means the helper code differs from this plan, and the golden must not be committed.
- Test code must also run on Python 3.9, because CI's 3.9 job runs all of `tests/`: no `X | Y` evaluated at run time, no `match`, no parenthesised multi-item `with (...)`, no `zip(strict=...)`; keep `from __future__ import annotations` and `typing` generics (`List`, `Dict`, `Optional`).
- Pushing the tag, the branch or opening the PR needs the owner's go-ahead; every other step is local.

## Review Focus

These five inputs are the most likely to bite the owner, and the spec implies but does not spell them out. Each is pinned by a test in its owning task.

1. **The owner's real shell.** It exports `VMD_AI_PROVIDER=anthropic-direct` and `ANTHROPIC_API_KEY`, and the suite must still pass with both set (today two `test_provider_selection.py` tests fail). Owner: P01-T01, `tests/test_hermetic_env.py::test_owner_shell_env_does_not_leak`.
2. **The login keychain and the real `~/.vmdai`.** `RuntimeApp()` and `KeyStore()` must never touch either during tests. Owner: P01-T01, `test_keyring_is_isolated` and `test_home_is_tmp`.
3. **Byte identity, not dict equality.** The benchmark's requests depend on `json.dumps` key order and separators, so the goldens compare raw `body_text`, and a mismatch must say *where* and whether only formatting changed. Owner: P01-T04, `tests/test_benchmark_golden_requests.py::test_golden_diff_is_readable`.
4. **An 8.5 `tclsh` first on PATH, or no VMD.app.** Tcl tests must skip with a reason and never error. Owner: P01-T03, `tests/test_tcl_harness.py::test_rejects_85_first_on_path` (plus `test_skip_reason_text` for the missing-VMD.app case).
5. **3.10-only syntax evaluated at run time** in the runtime or in tests breaks 3.9. Owners: P01-T09, `tests/test_py39_compat.py` (`test_runtime_modules_import_on_39`, with the negative control `test_import_check_catches_runtime_union`), and P01-T10, the CI 3.9 job that runs all of `tests/` under 3.9.

---

## File map

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `pytest.ini` | create | T01 | Pin rootdir, `testpaths = tests`, `pythonpath = runtime tests` |
| `tests/conftest.py` | create (T01), modify (T02) | T01, T02 | Autouse `_hermetic`; `live_env`, `fake_keyring_store`, `real_probe_local_ollama`, `sleep_calls` |
| `tests/helpers/__init__.py` | create | T01 | Package marker |
| `tests/helpers/live.py` | create | T01 | `LIVE_GATES`, `LIVE_ENV` snapshot taken at import |
| `tests/helpers/keyring_stub.py` | create | T01 | `make_stub_keyring()` in-memory keyring |
| `tests/test_hermetic_env.py` | create | T01 | Hermetic-base tests |
| `runtime/vmd_ai_runtime/claude_loop.py` | modify | T02 | `_sleep = time.sleep` hook, used at both backoff sites |
| `tests/test_benchmark_retry_pin.py` | create | T02 | Retry pin (URLError, 429, 503, 400) on all three providers |
| `tests/test_ollama_loop.py` | modify | T02 | `xfail(strict=True)` on the known failing test |
| `tests/helpers/tcl.py` | create | T03 | tclsh discovery, package paths, skip reasons, `run_tcl`, `run_tcltest` |
| `tests/tcl/test_harness_smoke.tcl` | create | T03 | Two tcltest cases for the runner |
| `tests/test_tcl_harness.py` | create | T03 | Harness tests |
| `tests/test_recorder.py`, `tests/test_rag_ab_extract.py` | modify | T03 | Use `helpers.tcl` instead of a bare `tclsh` |
| `tests/helpers/fake_evaluation_framework.py` | create | T04 | Stand-in `evaluation_framework` when the real one is missing |
| `tests/helpers/golden.py` | create (T04), modify (T05) | T04, T05 | Golden-request harness |
| `tests/test_benchmark_golden_requests.py` | create (T04), replace (T05) | T04, T05 | S7 golden tests |
| `tests/fixtures/golden_requests/*.json` | create | T04, T05 | 13 S7 request goldens |
| `tests/test_benchmark_bridge_guard.py` | create | T06 | Six-keyword bridge guard (`options=None`) |
| `tests/test_benchmark_hashes.py` | create | T07 | Prompt, tool-schema and PNG-byte hash pins |
| `tests/fixtures/images/pin_8x6.tga` | create | T07 | 8×6 uncompressed 24-bit TGA fixture |
| `integrations/run_provenance.py` | create | T08 | One-line manifest append (module + CLI) |
| 5 runner scripts | modify | T08 | Call `run_provenance` once per run |
| `tests/test_run_provenance.py`, `tests/test_benchmark_wiring.py` | create | T08 | Provenance and config-path wiring tests |
| `tests/test_py39_compat.py` | create | T09 | `/usr/bin/python3` 3.9 import and `--help` check; `RUNTIME_MODULES` |
| `tests/test_keys_no_backend.py` | create | T10 | keys.py "No keychain backend" branch |
| `.github/workflows/tests.yml` | create | T10 | CI on ubuntu-latest, Python 3.9 and 3.12 |

Expected `tests/` totals after each task (dev Mac with anaconda Python 3.12, tclsh 8.6.14 and VMD.app; pytest ≥ 9 also prints `10 subtests passed`): T01 465 passed (known failure deselected), T02 483 passed + 1 xfailed, T03 490, T04 495, T05 505, T06 513, T07 527, T08 550, T09 554, T10 555 passed + 1 xfailed.

---

### Task P01-T01: Baseline tag, pytest.ini, hermetic conftest

**Files:**
- Create: `pytest.ini`
- Create: `tests/conftest.py`
- Create: `tests/helpers/__init__.py`
- Create: `tests/helpers/live.py`
- Create: `tests/helpers/keyring_stub.py`
- Test: `tests/test_hermetic_env.py`
- Tag: `baseline-2026-09-24` → `47539f3`

**Interfaces:**
- Consumes: commit 47539f3
- Produces:
  - git tag baseline-2026-09-24 -> 47539f3
  - pytest.ini: [pytest] testpaths = tests; pythonpath = runtime tests
  - helpers.live.LIVE_GATES (six names); helpers.live.LIVE_ENV: Dict[str, str], captured at import
  - conftest fixture live_env (session scope) -> Dict[str, str]
  - conftest autouse fixture _hermetic: clears the four prefixes; HOME = tmp_path/'home'; keyring patched or stubbed; guarded by find_spec: settings_store.probe_local_ollama -> [] and provider_catalog.clear_caches()
  - conftest fixture real_probe_local_ollama -> the unpatched function (skips if the module is missing)
  - helpers.keyring_stub.make_stub_keyring() -> types.ModuleType; fixture fake_keyring_store -> Dict[Tuple[str, str], str]
  - (also) `_hermetic` yields a `HermeticState` with `.home: Path`, `.keyring: ModuleType`, `.keyring_store: Dict[Tuple[str, str], str]`; the stub module carries `_store` (that dict) and `_vmdai_stub = True`.
  - (contract for later plans) the stub replaces the **module attribute** `vmd_ai_runtime.settings_store.probe_local_ollama`, so runtime code must reach it by attribute access (`settings_store.probe_local_ollama(...)`, as P03-T08 does), never through `from .settings_store import probe_local_ollama`, or tests would probe the real ports 11434/11435. Likewise the keyring patch covers only `get_keyring`/`get_password`/`set_password`/`delete_password` reached through the `keyring` module.

- [ ] **Step 1: Create the branch and the baseline tag**

```bash
git checkout main
git checkout -b chatvmd-r1-01-m0-guard-rails
git tag baseline-2026-09-24 47539f3
git rev-parse 'baseline-2026-09-24^{commit}'
git diff --stat baseline-2026-09-24 HEAD -- runtime/ integrations/ tests/ scripts/ plugin/
```

Expected: `47539f3a363b606067b9189ac07ce3ade858919f`, and the `git diff --stat` prints nothing (6f5f937 only added docs). Push the tag (`git push origin baseline-2026-09-24`) only when the owner says so.

- [ ] **Step 2: Record today's behaviour**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `1 failed, 459 passed, 10 subtests passed in ~66s`; the failure is `tests/test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint` (`AssertionError: 'unreachable' not found in 'network error: <urlopen error connection refused>'`, after 60 s of real backoff sleeps).

Run: `env VMD_AI_PROVIDER=anthropic-direct ANTHROPIC_API_KEY=sk-ant-x python -m pytest tests/test_provider_selection.py -q`
Expected: `2 failed, 3 passed` (`test_default_prefers_openrouter_when_present`, `test_default_uses_auth_token_when_openrouter_like`): the owner-shell leak this task removes.

- [ ] **Step 3: Write the failing test**

Create `tests/test_hermetic_env.py`:

```python
"""The hermetic base (spec §6, S9): env, HOME and keyring are isolated per test."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from helpers.live import LIVE_ENV, LIVE_GATES

REPO = Path(__file__).resolve().parents[1]
PREFIXES = ("VMD_AI_", "ANTHROPIC_", "OPENROUTER_", "OLLAMA_")
PROBE_MODEL = "probe-model-7f3c"


def _child_env(**extra: str) -> dict:
    env = dict(os.environ)
    env.update(extra)
    return env


def _run_child_pytest(*args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=str(REPO),
        env=_child_env(**env),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_env_prefixes_cleared():
    leaked = sorted(k for k in os.environ if k.startswith(PREFIXES))
    assert leaked == []


def test_home_is_tmp(tmp_path):
    from vmd_ai_runtime.app import RuntimeApp

    home = tmp_path / "home"
    assert os.environ["HOME"] == str(home)
    assert Path.home() == home
    app = RuntimeApp()
    assert Path(app.store.root_dir) == home / ".vmdai" / "chats"
    assert app.wiki_store is not None
    assert app.wiki_store.wiki_root.is_relative_to(home.resolve())
    assert app.provider_name == "mock"


def test_keyring_is_isolated(fake_keyring_store):
    import keyring
    from vmd_ai_runtime.keys import KeyStore

    assert type(keyring.get_keyring()).__name__ == "StubBackend"
    assert fake_keyring_store == {}
    result = KeyStore().save("openrouter", "sk-or-hermetic")
    assert result.ok, result.message
    assert fake_keyring_store == {("vmd_ai", "openrouter_api_key"): "sk-or-hermetic"}


def test_live_env_captured_before_clearing():
    proc = _run_child_pytest(
        "tests/test_hermetic_env.py::test_live_env_probe",
        VMD_AI_LIVE_MODEL=PROBE_MODEL,
        CHATVMD_LIVE_PROBE="1",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout


def test_live_env_probe(live_env):
    """Always runs; test_live_env_captured_before_clearing also runs it in a child."""
    assert live_env is LIVE_ENV
    assert set(live_env) <= set(LIVE_GATES)
    for name in LIVE_GATES:
        assert name not in os.environ
    if os.environ.get("CHATVMD_LIVE_PROBE") == "1":
        assert live_env.get("VMD_AI_LIVE_MODEL") == PROBE_MODEL


def test_owner_shell_env_does_not_leak():
    proc = _run_child_pytest(
        "tests/test_provider_selection.py",
        VMD_AI_PROVIDER="anthropic-direct",
        ANTHROPIC_API_KEY="sk-ant-x",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "5 passed" in proc.stdout
```

`test_live_env_probe` runs in the parent run too; there it only checks that the gates were cleared. The child run proves the snapshot was taken before clearing, with the real conftest.

- [ ] **Step 4: Run it to verify it fails**

Run: `python -m pytest tests/test_hermetic_env.py -q`
Expected: collection error, `E   ModuleNotFoundError: No module named 'helpers'`, `1 error`.

- [ ] **Step 5: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = runtime tests
```

- [ ] **Step 6: Create the helper package**

Create `tests/helpers/__init__.py`:

```python
"""Shared helpers for the ChatVMD test suite (importable as ``helpers``)."""
```

Create `tests/helpers/live.py`:

```python
"""Snapshot of the opt-in live-test gates, taken once at import time.

tests/conftest.py imports this module before any fixture runs, so the
values reflect the shell that launched pytest.  The autouse ``_hermetic``
fixture then clears every ``VMD_AI_*`` variable for each test; live tests
read their gates only through the ``live_env`` fixture, which returns
``LIVE_ENV``.
"""
from __future__ import annotations

import os
from typing import Dict, Tuple

LIVE_GATES: Tuple[str, ...] = (
    "VMD_AI_LIVE_OLLAMA",
    "VMD_AI_LIVE_MODEL",
    "VMD_AI_VMD_BIN",
    "VMD_AI_TCLSH",
    "VMD_AI_TCL_TM",
    "VMD_AI_TK_LIB",
)

LIVE_ENV: Dict[str, str] = {
    name: os.environ[name] for name in LIVE_GATES if os.environ.get(name)
}
```

Create `tests/helpers/keyring_stub.py`:

```python
"""In-memory stand-in for the ``keyring`` package.

``make_stub_keyring()`` returns a module object with the four functions
``vmd_ai_runtime.keys`` uses (get_keyring, get_password, set_password,
delete_password).  The backend reports ``priority = 1`` so ``KeyStore``
treats it as a usable keychain; every value lives in the module's
``_store`` dict, which the ``fake_keyring_store`` fixture exposes.
"""
from __future__ import annotations

import types
from typing import Dict, Optional, Tuple


class StubBackend:
    priority = 1

    def __init__(self, store: Dict[Tuple[str, str], str]) -> None:
        self.store = store

    def get_password(self, service: str, account: str) -> Optional[str]:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.store[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.store.pop((service, account), None)


def make_stub_keyring() -> types.ModuleType:
    store: Dict[Tuple[str, str], str] = {}
    backend = StubBackend(store)
    module = types.ModuleType("keyring")
    module.__dict__.update(
        get_keyring=lambda: backend,
        get_password=backend.get_password,
        set_password=backend.set_password,
        delete_password=backend.delete_password,
        _store=store,
        _vmdai_stub=True,
    )
    return module
```

- [ ] **Step 7: Create `tests/conftest.py`**

```python
"""Hermetic base for tests/ (spec §6 "Hermetic base", C9).

Order matters: ``helpers.live`` snapshots the opt-in live gates at import
time, before the autouse ``_hermetic`` fixture clears the environment for
each test.
"""
from __future__ import annotations

import contextlib
import importlib
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
from unittest import mock

import pytest

from helpers.keyring_stub import make_stub_keyring
from helpers.live import LIVE_ENV

CLEARED_PREFIXES: Tuple[str, ...] = ("VMD_AI_", "ANTHROPIC_", "OPENROUTER_", "OLLAMA_")

# Originals of functions the hermetic fixture replaces, for the real_* fixtures.
_ORIGINALS: Dict[str, Callable[..., Any]] = {}


class HermeticState:
    def __init__(self, home: Path, keyring_module: ModuleType) -> None:
        self.home = home
        self.keyring = keyring_module
        self.keyring_store: Dict[Tuple[str, str], str] = keyring_module._store


def _optional_module(name: str) -> Optional[ModuleType]:
    """Import ``name`` only if it exists (modules later plans add)."""
    if importlib.util.find_spec(name) is None:
        return None
    return importlib.import_module(name)


def _install_keyring(stack: contextlib.ExitStack, stub: ModuleType) -> None:
    try:
        import keyring as real  # noqa: F401
    except Exception:
        real = None
    if real is None or getattr(real, "_vmdai_stub", False):
        previous = sys.modules.get("keyring")
        sys.modules["keyring"] = stub

        def _restore() -> None:
            if previous is None:
                sys.modules.pop("keyring", None)
            else:
                sys.modules["keyring"] = previous

        stack.callback(_restore)
        return
    for name in ("get_keyring", "get_password", "set_password", "delete_password"):
        stack.enter_context(mock.patch.object(real, name, getattr(stub, name)))


@pytest.fixture(scope="session")
def live_env() -> Dict[str, str]:
    """The live gates as they were when pytest started (read-only by convention)."""
    return LIVE_ENV


@pytest.fixture(autouse=True)
def _hermetic(tmp_path: Path) -> Iterator[HermeticState]:
    home = tmp_path / "home"
    home.mkdir()
    stub = make_stub_keyring()
    with contextlib.ExitStack() as stack:
        # patch.dict restores os.environ exactly, including keys code under
        # test adds (the adapter exports VMD_AI_OPENAI_BASE_URL, KeyStore.save
        # exports OPENROUTER_API_KEY).
        stack.enter_context(mock.patch.dict(os.environ))
        for key in list(os.environ):
            if key.startswith(CLEARED_PREFIXES):
                del os.environ[key]
        os.environ["HOME"] = str(home)
        _install_keyring(stack, stub)
        state = HermeticState(home, stub)

        settings_store = _optional_module("vmd_ai_runtime.settings_store")
        if settings_store is not None and hasattr(settings_store, "probe_local_ollama"):
            _ORIGINALS.setdefault("probe_local_ollama", settings_store.probe_local_ollama)
            stack.enter_context(
                mock.patch.object(settings_store, "probe_local_ollama", lambda *a, **k: [])
            )
        provider_catalog = _optional_module("vmd_ai_runtime.provider_catalog")
        if provider_catalog is not None and hasattr(provider_catalog, "clear_caches"):
            provider_catalog.clear_caches()

        yield state


@pytest.fixture
def fake_keyring_store(_hermetic: HermeticState) -> Dict[Tuple[str, str], str]:
    """The in-memory keyring for this test: {(service, account): secret}."""
    return _hermetic.keyring_store


@pytest.fixture
def real_probe_local_ollama(_hermetic: HermeticState) -> Callable[..., Any]:
    """The unpatched settings_store.probe_local_ollama (tests that probe sockets)."""
    if "probe_local_ollama" not in _ORIGINALS:
        pytest.skip("vmd_ai_runtime.settings_store.probe_local_ollama does not exist yet")
    return _ORIGINALS["probe_local_ollama"]
```

Do not replace `sys.modules` with `mock.patch.dict(sys.modules, …)`: on exit it clears and refills the whole dict, dropping every module imported during the test.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_hermetic_env.py -q`
Expected: `6 passed`.

Run: `env VMD_AI_PROVIDER=anthropic-direct ANTHROPIC_API_KEY=sk-ant-x python -m pytest tests/test_hermetic_env.py tests/test_provider_selection.py -q`
Expected: `11 passed`.

- [ ] **Step 9: Run the three suites**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q --deselect tests/test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint`
Expected: `465 passed, 1 deselected, 10 subtests passed` in about 8 s (the deselected test still sleeps 60 s until P01-T02).

Run: `python -m pytest vmdbench/tests -q`
Expected: `90 passed` (plus 1 warning and 5 subtests, as today).

Run: `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`
Expected: `62 passed` (plus 3 warnings, as today). The root `pytest.ini` now governs these runs too; `tests/conftest.py` is not loaded for them.

- [ ] **Step 10: Commit**

```bash
git add pytest.ini tests/conftest.py tests/helpers/__init__.py tests/helpers/live.py tests/helpers/keyring_stub.py tests/test_hermetic_env.py
git commit -F - <<'MSG'
test(m0): hermetic conftest, pytest.ini and live-gate snapshot

Every test now runs with VMD_AI_*/ANTHROPIC_*/OPENROUTER_*/OLLAMA_*
cleared, HOME in a temp dir and an in-memory keyring, so the owner's
shell (VMD_AI_PROVIDER, ANTHROPIC_API_KEY) no longer changes results.
Live gates are snapshotted at import and read via the live_env fixture.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T02: _sleep hook, retry pin, strict xfail

**Files:**
- Modify: `runtime/vmd_ai_runtime/claude_loop.py:44` (after `logger = …`), `:497` and `:528` (the two `time.sleep(wait)` calls in `_stream_request`)
- Modify: `tests/conftest.py` (created in P01-T01)
- Modify: `tests/test_ollama_loop.py:23` (imports) and `:442` (`test_unreachable_host_raises_with_hint`)
- Test: `tests/test_benchmark_retry_pin.py`

**Interfaces:**
- Consumes: conftest _hermetic (P01-T01)
- Produces:
  - vmd_ai_runtime.claude_loop._sleep = time.sleep; _stream_request calls _sleep(wait) at both former time.sleep sites
  - conftest autouse patch of claude_loop._sleep; fixture sleep_calls -> List[float]
  - pytest.mark.xfail(strict=True) on test_unreachable_host_raises_with_hint (P04-T01 removes it)
  - (also) `HermeticState.sleep_calls: List[float]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_benchmark_retry_pin.py`:

```python
"""S7 retry pin (spec §2a): with options=None the loop keeps today's retry policy.

Every provider goes through _stream_request.  URLError is retried 5 times with
waits 2, 4, 8, 16, 30 s; HTTP 429/500/502/503/529 are retried 5 times, honouring
Retry-After, else 2, 4, 8, 16, 32 s; any other HTTP status is not retried.
The conftest records the waits instead of sleeping (fixture ``sleep_calls``).
"""
from __future__ import annotations

import email.message
import io
import threading
import urllib.error
from typing import Callable, Optional
from unittest import mock

import pytest

from vmd_ai_runtime.claude_loop import ClaudeLoopError, ClaudeToolLoop

PROVIDERS = {
    "anthropic-direct": ("sk-ant-pin", "claude-sonnet-4-5"),
    "openrouter": ("sk-or-pin", "pin/model"),
    "ollama": ("http://127.0.0.1:9", "llama3.1"),
}


class _NoToolBridge:
    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event):
        raise AssertionError("the pin never reaches a tool call")


class _Raiser:
    """Fake urlopen that raises a fresh exception on every call."""

    def __init__(self, make_exc: Callable[[], Exception]) -> None:
        self.make_exc = make_exc
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        raise self.make_exc()


def _http_error(code: int, retry_after: Optional[str] = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    body = io.BytesIO(b'{"error": {"message": "pinned failure"}}')
    return urllib.error.HTTPError("http://pin.test/", code, "pinned", headers, body)


def _run_loop(provider: str) -> None:
    api_key, model = PROVIDERS[provider]
    loop = ClaudeToolLoop(provider_name=provider, api_key=api_key, model=model)
    loop.run(
        prompt="hi",
        system_prompt="sys",
        tool_bridge=_NoToolBridge(),
        session_id="pin",
        session_queue=None,
        cancel_event=threading.Event(),
        on_chunk=lambda s: None,
    )


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_urlerror_retries_five_times(provider, sleep_calls):
    raiser = _Raiser(lambda: urllib.error.URLError("Connection refused"))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="network error"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 30.0]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_429_backoff_without_retry_after(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(429))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 429: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [2.0, 4.0, 8.0, 16.0, 32.0]


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_503_honours_retry_after(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(503, retry_after="7"))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 503: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == [7.0] * 5


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_http_400_not_retried(provider, sleep_calls):
    raiser = _Raiser(lambda: _http_error(400))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match="HTTP 400: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 1
    assert sleep_calls == []


@pytest.mark.parametrize("provider", sorted(PROVIDERS))
@pytest.mark.parametrize(
    "code,retry_after,waits",
    [(429, "7", [7.0] * 5), (503, None, [2.0, 4.0, 8.0, 16.0, 32.0])],
    ids=["429-retry-after", "503-no-retry-after"],
)
def test_http_retry_after_other_combinations(provider, code, retry_after, waits, sleep_calls):
    """Spec §2a pins 429 *and* 503 with and without Retry-After: the two other cells."""
    raiser = _Raiser(lambda: _http_error(code, retry_after=retry_after))
    with mock.patch("urllib.request.urlopen", raiser):
        with pytest.raises(ClaudeLoopError, match=f"HTTP {code}: pinned failure"):
            _run_loop(provider)
    assert raiser.calls == 6
    assert sleep_calls == waits
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_benchmark_retry_pin.py -q`
Expected: `18 errors`, each `fixture 'sleep_calls' not found`.

- [ ] **Step 3: Add the `_sleep` hook to `runtime/vmd_ai_runtime/claude_loop.py`**

Replace

```python
logger = logging.getLogger("vmdai.claude_loop")

```

with

```python
logger = logging.getLogger("vmdai.claude_loop")

# Backoff sleeps in _stream_request go through this hook (spec §2a). It is
# the only thing tests patch; production behaviour is exactly time.sleep.
_sleep = time.sleep

```

Then, in `_stream_request`, replace both occurrences (lines 497 and 528 before this edit) of

```python
                time.sleep(wait)
```

with

```python
                _sleep(wait)
```

Nothing else in the file changes.

- [ ] **Step 4: Patch `_sleep` in `tests/conftest.py`**

Make four edits.

In the typing import, replace

```python
from typing import Any, Callable, Dict, Iterator, Optional, Tuple
```

with

```python
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
```

In `HermeticState.__init__`, after `self.keyring_store: Dict[Tuple[str, str], str] = keyring_module._store`, add:

```python
        self.sleep_calls: List[float] = []
```

In `_hermetic`, replace

```python
        state = HermeticState(home, stub)

        settings_store = _optional_module("vmd_ai_runtime.settings_store")
```

with

```python
        state = HermeticState(home, stub)

        # Backoff sleeps are recorded, never slept (spec §6: patch only _sleep).
        from vmd_ai_runtime import claude_loop

        stack.enter_context(
            mock.patch.object(claude_loop, "_sleep", state.sleep_calls.append)
        )

        settings_store = _optional_module("vmd_ai_runtime.settings_store")
```

Before the `real_probe_local_ollama` fixture, add:

```python
@pytest.fixture
def sleep_calls(_hermetic: HermeticState) -> List[float]:
    """Every wait passed to claude_loop._sleep during this test, in order."""
    return _hermetic.sleep_calls


```

- [ ] **Step 5: Mark the known Ollama failure as a strict xfail**

In `tests/test_ollama_loop.py`, replace

```python
from unittest import mock

```

(line 23) with

```python
from unittest import mock

import pytest

```

and replace

```python
    def test_unreachable_host_raises_with_hint(self):
```

(line 442) with

```python
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "known Ollama bug (spec §2a 'Unreachable test'): _stream_request retries "
            "URLError and raises a generic 'network error'. P04-T01 passes opts with "
            "connect_retries=0 and removes this mark."
        ),
    )
    def test_unreachable_host_raises_with_hint(self):
```

pytest applies `xfail` to `unittest.TestCase` methods. With `_sleep` patched the test now fails in milliseconds instead of 60 s.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_benchmark_retry_pin.py tests/test_ollama_loop.py -q -rxX`
Expected: `65 passed, 1 xfailed`, with `XFAIL tests/test_ollama_loop.py::StreamOllamaErrorTests::test_unreachable_host_raises_with_hint - known Ollama bug …`.

- [ ] **Step 7: Confirm the runtime diff is only the indirection**

Run: `git diff --stat baseline-2026-09-24 -- runtime/`
Expected: ` runtime/vmd_ai_runtime/claude_loop.py | 8 ++++++--` and ` 1 file changed, 6 insertions(+), 2 deletions(-)`.

Run: `git diff baseline-2026-09-24 -- runtime/ | grep '^[-+][^-+]'`
Expected exactly:

```text
+# Backoff sleeps in _stream_request go through this hook (spec §2a). It is
+# the only thing tests patch; production behaviour is exactly time.sleep.
+_sleep = time.sleep
-                time.sleep(wait)
+                _sleep(wait)
-                time.sleep(wait)
+                _sleep(wait)
```

- [ ] **Step 8: Run the suite (S9 holds from here on)**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `483 passed, 1 xfailed, 10 subtests passed` in about 8 s (under 60 s).

- [ ] **Step 9: Commit**

```bash
git add runtime/vmd_ai_runtime/claude_loop.py tests/conftest.py tests/test_ollama_loop.py tests/test_benchmark_retry_pin.py
git commit -F - <<'MSG'
test(m0): _sleep hook, retry pin, strict xfail for the Ollama unreachable test

claude_loop's two backoff sleeps go through a module-level _sleep hook
(no behaviour change). The conftest records the waits, the retry pin
fixes today's URLError/429/503/400 policy on all three providers, and
the known Ollama failure is xfail(strict=True) until P04-T01.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T03: Tcl test helper and http 2.9.5 harness

**Files:**
- Create: `tests/helpers/tcl.py`
- Create: `tests/tcl/test_harness_smoke.tcl`
- Modify: `tests/test_recorder.py:20-38` (imports and `_tclsh_available`), `:345` and `:415` (class skips), `:363` and `:469` (`["tclsh"]`)
- Modify: `tests/test_rag_ab_extract.py:40-57` (imports and `_tclsh_available`), `:352` (class skip), `:384` (`["tclsh"]`)
- Test: `tests/test_tcl_harness.py`

**Interfaces:**
- Consumes: helpers.live.LIVE_ENV (P01-T01)
- Produces:
  - helpers.tcl.find_tclsh() -> Optional[str]
  - helpers.tcl.tcl_skip_reason(*, needs_http: bool = False, needs_json: bool = False) -> Optional[str]
  - helpers.tcl.http_tm_dir() -> Optional[str]; json_pkg_dir() -> Optional[str] (plugin/lib/json if present, else VMD json1.0)
  - helpers.tcl.tcl_prelude(*, needs_http=False, needs_json=False) -> str
  - helpers.tcl.run_tcl(script: str, *, needs_http=False, needs_json=False, cwd=None, env=None, timeout=60) -> subprocess.CompletedProcess
  - helpers.tcl.run_tcltest(test_file: str, *, needs_http=False, needs_json=False, env=None, timeout=120, prelude: str = '') -> TclTestResult (exports VMDAI_REPO, VMDAI_PLUGIN_DIR, a temp HOME, and a tcltest -outfile)
  - @dataclass helpers.tcl.TclTestResult(passed: int, failed: int, skipped: int, output: str)
  - helpers.tcl.requires_tcl(*, needs_http=False, needs_json=False) -> pytest.mark.skipif
  - (also) `helpers.tcl.tcl_word(value: str) -> str` (one Tcl word, safe for paths with spaces); constants `REPO`, `PLUGIN_DIR`, `PLUGIN_JSON_DIR`, `VMD_TCL_TM_DIR`, `VMD_JSON_DIR`, `HTTP_VERSION = "2.9.5"`, `JSON_VERSION = "1.1.2"`

- [ ] **Step 1: Write the failing tests**

Create `tests/tcl/test_harness_smoke.tcl`:

```tcl
# Smoke test for tests/helpers/tcl.py run_tcltest (P01-T03).
package require tcltest 2
namespace import ::tcltest::*

test harness-1 {the interpreter is Tcl 8.6} -body {
    string match 8.6.* [info patchlevel]
} -result 1

test harness-2 {HOME is a temp dir and VMDAI_REPO is the checkout} -body {
    list [expr {$env(HOME) ne ""}] \
         [file isdirectory $env(HOME)] \
         [file exists [file join $env(VMDAI_REPO) pytest.ini]] \
         [file isdirectory $env(VMDAI_PLUGIN_DIR)]
} -result {1 1 1 1}

cleanupTests
```

Create `tests/test_tcl_harness.py`:

```python
"""tests/helpers/tcl.py: interpreter discovery, package paths, skips, tcltest counts."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

from helpers import tcl

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "tests" / "tcl" / "test_harness_smoke.tcl"


def _fake_tclsh(directory: Path, patchlevel: str) -> Path:
    """A shell script named tclsh that answers `info patchlevel` with ``patchlevel``."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "tclsh"
    path.write_text(f"#!/bin/sh\ncat > /dev/null\necho {patchlevel}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_find_tclsh_prefers_86():
    found = tcl.find_tclsh()
    if found is None:
        pytest.skip(tcl.tcl_skip_reason() or "no tclsh 8.6")
    assert tcl._patchlevel(found).startswith("8.6.")


def test_rejects_85_first_on_path(tmp_path, monkeypatch):
    monkeypatch.delitem(tcl.LIVE_ENV, "VMD_AI_TCLSH", raising=False)
    real = tcl.find_tclsh()
    fake_dir = tmp_path / "old_tcl"
    _fake_tclsh(fake_dir, "8.5.9")

    monkeypatch.setenv("PATH", str(fake_dir) + os.pathsep + os.environ["PATH"])
    assert tcl.find_tclsh() == real

    monkeypatch.setenv("PATH", str(fake_dir))
    assert tcl.find_tclsh() is None
    reason = tcl.tcl_skip_reason()
    assert reason is not None and reason.startswith("no Tcl 8.6 interpreter")
    mark = tcl.requires_tcl().mark
    assert mark.args == (True,) and mark.kwargs["reason"] == reason
    with pytest.raises(pytest.skip.Exception, match="no Tcl 8.6 interpreter"):
        tcl.run_tcl("puts hi")


def test_http_295_loads():
    proc = tcl.run_tcl(
        "puts [package present http]\nputs [info patchlevel]\n", needs_http=True
    )
    assert proc.returncode == 0, proc.stderr
    http_version, patchlevel = proc.stdout.split()
    assert http_version == "2.9.5"
    assert patchlevel.startswith("8.6.")


def test_json_112_loads():
    proc = tcl.run_tcl(
        'puts [package present json]\nputs [json::json2dict {{"a": [1, 2], "b": "x"}}]\n',
        needs_json=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["1.1.2", "a {1 2} b x"]


def test_run_tcltest_counts(tmp_path):
    result = tcl.run_tcltest(str(SMOKE))
    assert (result.passed, result.failed, result.skipped) == (2, 0, 0), result.output

    mixed = tmp_path / "mixed dir" / "t_mixed.tcl"
    mixed.parent.mkdir()
    mixed.write_text(
        "package require tcltest 2\n"
        "namespace import ::tcltest::*\n"
        "test m-1 {passes} -body {expr {1 + 1}} -result 2\n"
        "test m-2 {fails} -body {expr {1 + 1}} -result 3\n"
        "test m-3 {skipped} -constraints noSuchConstraint -body {} -result {}\n"
        "cleanupTests\n"
    )
    result = tcl.run_tcltest(str(mixed))
    assert (result.passed, result.failed, result.skipped) == (1, 1, 1), result.output
    assert "m-2" in result.output

    broken = tmp_path / "t_broken.tcl"
    broken.write_text("error {boom before any test}\n")
    result = tcl.run_tcltest(str(broken))
    assert (result.passed, result.failed) == (0, 1)
    assert "boom before any test" in result.output


def test_skip_reason_text(tmp_path, monkeypatch):
    if tcl.find_tclsh() is None:
        pytest.skip(tcl.tcl_skip_reason() or "no tclsh 8.6")
    monkeypatch.delitem(tcl.LIVE_ENV, "VMD_AI_TCL_TM", raising=False)
    monkeypatch.setattr(tcl, "VMD_TCL_TM_DIR", str(tmp_path / "no_vmd_app"))
    monkeypatch.setattr(tcl, "VMD_JSON_DIR", str(tmp_path / "no_json"))
    monkeypatch.setattr(tcl, "PLUGIN_JSON_DIR", tmp_path / "no_plugin_json")

    assert tcl.tcl_skip_reason() is None
    http_reason = tcl.tcl_skip_reason(needs_http=True)
    assert http_reason is not None and http_reason.startswith("http 2.9.5 not found")
    json_reason = tcl.tcl_skip_reason(needs_json=True)
    assert json_reason is not None and json_reason.startswith("json 1.1.2 not found")
    with pytest.raises(pytest.skip.Exception, match="http 2.9.5 not found"):
        tcl.run_tcl("puts hi", needs_http=True)
    with pytest.raises(pytest.skip.Exception, match="json 1.1.2 not found"):
        tcl.run_tcltest(str(SMOKE), needs_json=True)


def test_no_bare_tclsh_in_tests():
    """C9: every Tcl-running test goes through helpers.tcl, never a bare `tclsh`."""
    offenders = []
    for path in sorted((REPO / "tests").glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""which\(\s*["']tclsh|\[\s*["']tclsh["']""", text):
            offenders.append(path.name)
    assert offenders == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python -m pytest tests/test_tcl_harness.py -q`
Expected: collection error, `E   ModuleNotFoundError: No module named 'helpers.tcl'`, `1 error`.

- [ ] **Step 3: Create `tests/helpers/tcl.py`**

```python
"""One place that decides how Tcl tests run and when they skip (spec §6, C9).

Interpreter: VMD_AI_TCLSH (from the live_env snapshot) if set, else the first
``tclsh8.6``/``tclsh`` on PATH whose ``info patchlevel`` is 8.6.x.  An 8.5
tclsh (macOS /usr/bin) can't load http 2.9 and is rejected.

Packages: http 2.9.5 from VMD.app's Tcl.framework module path (or
VMD_AI_TCL_TM); json 1.1.2 from plugin/lib/json once M1 vendors it, else
from VMD's plugins/noarch/tcl/json1.0.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pytest

from helpers.live import LIVE_ENV

REPO = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO / "plugin"
PLUGIN_JSON_DIR = PLUGIN_DIR / "lib" / "json"
VMD_TCL_TM_DIR = (
    "/Applications/VMD.app/Contents/Frameworks/Tcl.framework/Versions/8.6/Resources/tcl8/8.6"
)
VMD_JSON_DIR = "/Applications/VMD.app/Contents/vmd/plugins/noarch/tcl/json1.0"
HTTP_VERSION = "2.9.5"
JSON_VERSION = "1.1.2"
TCLSH_NAMES = ("tclsh8.6", "tclsh")

_SUMMARY_RE = re.compile(
    r"^\S*:\s+Total\s+(\d+)\s+Passed\s+(\d+)\s+Skipped\s+(\d+)\s+Failed\s+(\d+)",
    re.MULTILINE,
)


@dataclass
class TclTestResult:
    passed: int
    failed: int
    skipped: int
    output: str


@functools.lru_cache(maxsize=None)
def _patchlevel(executable: str) -> Optional[str]:
    """``info patchlevel`` of ``executable``, or None if it can't be run."""
    try:
        proc = subprocess.run(
            [executable],
            input="puts [info patchlevel]\nexit 0\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    level = proc.stdout.strip()
    return level or None


def _is_86(executable: str) -> bool:
    level = _patchlevel(executable)
    return bool(level) and level.startswith("8.6.")


@functools.lru_cache(maxsize=None)
def _has_tcltest(executable: str) -> bool:
    try:
        proc = subprocess.run(
            [executable],
            input="puts [package require tcltest 2]\nexit 0\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip().startswith("2.")


def _path_candidates(path_value: str) -> Iterable[str]:
    for directory in path_value.split(os.pathsep):
        if not directory:
            continue
        for name in TCLSH_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                yield candidate


def find_tclsh() -> Optional[str]:
    override = LIVE_ENV.get("VMD_AI_TCLSH")
    if override:
        return override if _is_86(override) else None
    for candidate in _path_candidates(os.environ.get("PATH", "")):
        if _is_86(candidate):
            return candidate
    return None


def http_tm_dir() -> Optional[str]:
    directory = LIVE_ENV.get("VMD_AI_TCL_TM") or VMD_TCL_TM_DIR
    if Path(directory, f"http-{HTTP_VERSION}.tm").is_file():
        return directory
    return None


def json_pkg_dir() -> Optional[str]:
    for directory in (PLUGIN_JSON_DIR, Path(VMD_JSON_DIR)):
        if (directory / "pkgIndex.tcl").is_file() and (directory / "json.tcl").is_file():
            return str(directory)
    return None


def tcl_skip_reason(*, needs_http: bool = False, needs_json: bool = False) -> Optional[str]:
    if find_tclsh() is None:
        return (
            "no Tcl 8.6 interpreter: set VMD_AI_TCLSH or put tclsh8.6 on PATH "
            "(an 8.5 tclsh such as /usr/bin/tclsh is rejected)"
        )
    if needs_http and http_tm_dir() is None:
        return (
            f"http {HTTP_VERSION} not found: set VMD_AI_TCL_TM to the directory holding "
            f"http-{HTTP_VERSION}.tm (VMD.app: {VMD_TCL_TM_DIR})"
        )
    if needs_json and json_pkg_dir() is None:
        return (
            f"json {JSON_VERSION} not found in {PLUGIN_JSON_DIR} or {VMD_JSON_DIR}"
        )
    return None


def requires_tcl(*, needs_http: bool = False, needs_json: bool = False):
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    return pytest.mark.skipif(reason is not None, reason=reason or "")


def tcl_word(value: str) -> str:
    """Quote ``value`` as one Tcl word (paths may contain spaces)."""
    if value and re.fullmatch(r"[A-Za-z0-9_./:+=@%,-]+", value):
        return value
    if not re.search(r"[{}\\]", value):
        return "{" + value + "}"
    return '"' + re.sub(r'([\\"$\[\]{}])', r"\\\1", value) + '"'


def tcl_prelude(*, needs_http: bool = False, needs_json: bool = False) -> str:
    lines: List[str] = []
    if needs_http:
        tm_dir = http_tm_dir()
        if tm_dir is None:
            raise RuntimeError(tcl_skip_reason(needs_http=True) or "http missing")
        lines.append(f"::tcl::tm::path add {tcl_word(tm_dir)}")
        lines.append(f"package require -exact http {HTTP_VERSION}")
    if needs_json:
        json_dir = json_pkg_dir()
        if json_dir is None:
            raise RuntimeError(tcl_skip_reason(needs_json=True) or "json missing")
        lines.append(f"lappend auto_path {tcl_word(json_dir)}")
        lines.append(f"package require -exact json {JSON_VERSION}")
    return "".join(line + "\n" for line in lines)


def _merged_env(home: str, env: Optional[Dict[str, str]]) -> Dict[str, str]:
    merged = dict(os.environ)
    merged.update(
        HOME=home,
        VMDAI_REPO=str(REPO),
        VMDAI_PLUGIN_DIR=str(PLUGIN_DIR),
    )
    if env:
        merged.update(env)
    return merged


def run_tcl(
    script: str,
    *,
    needs_http: bool = False,
    needs_json: bool = False,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run ``script`` (after the package prelude) as a file under tclsh 8.6.

    Skips the calling test when the interpreter or a package is missing.
    """
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    if reason is not None:
        pytest.skip(reason)
    tclsh = find_tclsh()
    assert tclsh is not None
    with tempfile.TemporaryDirectory(prefix="vmdai_tcl_") as tmp:
        home = os.path.join(tmp, "home")
        os.mkdir(home)
        path = os.path.join(tmp, "script.tcl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(tcl_prelude(needs_http=needs_http, needs_json=needs_json))
            fh.write(script)
        return subprocess.run(
            [tclsh, path],
            cwd=cwd or tmp,
            env=_merged_env(home, env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )


def run_tcltest(
    test_file: str,
    *,
    needs_http: bool = False,
    needs_json: bool = False,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 120,
    prelude: str = "",
) -> TclTestResult:
    """Source a tcltest file under tclsh 8.6 and return its summary counts.

    The file must end with ``::tcltest::cleanupTests``.  It sees
    ``$env(VMDAI_REPO)``, ``$env(VMDAI_PLUGIN_DIR)`` and a temp ``$env(HOME)``.
    A file that dies before printing a summary counts as one failure.
    """
    reason = tcl_skip_reason(needs_http=needs_http, needs_json=needs_json)
    if reason is not None:
        pytest.skip(reason)
    tclsh = find_tclsh()
    assert tclsh is not None
    if not _has_tcltest(tclsh):
        pytest.skip(f"tcltest 2 is not available in {tclsh}")
    test_path = Path(test_file).resolve()
    with tempfile.TemporaryDirectory(prefix="vmdai_tcltest_") as tmp:
        home = os.path.join(tmp, "home")
        os.mkdir(home)
        outfile = os.path.join(tmp, "tcltest.out")
        driver = os.path.join(tmp, "driver.tcl")
        with open(driver, "w", encoding="utf-8") as fh:
            fh.write(tcl_prelude(needs_http=needs_http, needs_json=needs_json))
            fh.write(prelude if prelude.endswith("\n") or not prelude else prelude + "\n")
            fh.write("package require tcltest 2\n")
            fh.write(f"::tcltest::configure -outfile {tcl_word(outfile)} -verbose {{body error}}\n")
            fh.write(f"source {tcl_word(str(test_path))}\n")
        proc = subprocess.run(
            [tclsh, driver],
            cwd=tmp,
            env=_merged_env(home, env),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        report = Path(outfile).read_text(encoding="utf-8") if os.path.exists(outfile) else ""
    output = report + proc.stdout + proc.stderr
    match = _SUMMARY_RE.search(report)
    if match is None:
        return TclTestResult(passed=0, failed=1, skipped=0, output=output)
    _total, passed, skipped, failed = (int(g) for g in match.groups())
    return TclTestResult(passed=passed, failed=failed, skipped=skipped, output=output)
```

`run_tcl` writes the script to a file rather than piping it on stdin: under `tclsh file`, an uncaught error exits non-zero with `errorInfo` on stderr, while stdin mode prints the error and carries on.

- [ ] **Step 4: Run the harness tests**

Run: `python -m pytest tests/test_tcl_harness.py -q`
Expected: `1 failed, 6 passed`; the failure is `test_no_bare_tclsh_in_tests`, whose `offenders` list holds `test_rag_ab_extract.py` and `test_recorder.py` (pytest prints it shortened as `assert ['test_rag_ab..._recorder.py'] == []`).

- [ ] **Step 5: Move `tests/test_recorder.py` onto the helper**

Replace (lines 20-22)

```python
import json
import shutil
import subprocess
```

with

```python
import json
import subprocess
```

Replace (lines 34-38)

```python
from vmd_ai_runtime.recorder import RunRecorder, RunRecorderError  # noqa: E402


def _tclsh_available() -> bool:
    return shutil.which("tclsh") is not None
```

with

```python
from vmd_ai_runtime.recorder import RunRecorder, RunRecorderError  # noqa: E402
from helpers.tcl import find_tclsh, tcl_skip_reason  # noqa: E402

TCLSH = find_tclsh()
_TCL_SKIP = tcl_skip_reason()
```

Replace both occurrences (lines 345 and 415) of

```python
@unittest.skipUnless(_tclsh_available(), "tclsh not installed")
```

with

```python
@unittest.skipIf(_TCL_SKIP is not None, _TCL_SKIP or "")
```

Replace both occurrences (lines 363 and 469) of `["tclsh"],` with `[TCLSH],` (keep each line's indentation).

- [ ] **Step 6: Move `tests/test_rag_ab_extract.py` onto the helper**

Replace (lines 40-42)

```python
import json
import shutil
import subprocess
```

with

```python
import json
import subprocess
```

Replace (lines 53-57)

```python
import rag_ab_extract  # noqa: E402


def _tclsh_available() -> bool:
    return shutil.which("tclsh") is not None
```

with

```python
import rag_ab_extract  # noqa: E402
from helpers.tcl import find_tclsh, tcl_skip_reason  # noqa: E402

TCLSH = find_tclsh()
_TCL_SKIP = tcl_skip_reason()
```

Replace (line 352)

```python
@unittest.skipUnless(_tclsh_available(), "tclsh not installed")
```

with

```python
@unittest.skipIf(_TCL_SKIP is not None, _TCL_SKIP or "")
```

Replace (line 384) `["tclsh"], input=harness, capture_output=True,` with `[TCLSH], input=harness, capture_output=True,`.

- [ ] **Step 7: Run the Tcl tests with 8.6 and with only 8.5**

Run: `python -m pytest tests/test_tcl_harness.py tests/test_recorder.py tests/test_rag_ab_extract.py -q`
Expected: `56 passed`.

Run (only macOS's 8.5.9 `tclsh` left on PATH):

```bash
PY="$(command -v python)"
env PATH=/usr/bin:/bin "$PY" -m pytest tests/test_tcl_harness.py tests/test_recorder.py tests/test_rag_ab_extract.py -q -rs
```

Expected: `45 passed, 11 skipped`; every `SKIPPED` line reads `no Tcl 8.6 interpreter: set VMD_AI_TCLSH or put tclsh8.6 on PATH (an 8.5 tclsh such as /usr/bin/tclsh is rejected)`. No errors.

- [ ] **Step 8: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `490 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 9: Commit**

```bash
git add tests/helpers/tcl.py tests/tcl/test_harness_smoke.tcl tests/test_tcl_harness.py tests/test_recorder.py tests/test_rag_ab_extract.py
git commit -F - <<'MSG'
test(m0): Tcl harness with VMD's http 2.9.5 and one skip policy

helpers.tcl finds an 8.6 tclsh (VMD_AI_TCLSH or PATH; 8.5 rejected),
loads http 2.9.5 from VMD.app's module path and json 1.1.2, runs
tcltest files with a temp HOME and parses their counts. The recorder
and rag_ab_extract Tcl checks now use it instead of a bare `tclsh`.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T04: Fake evaluation_framework and golden requests (none arm)

**Files:**
- Create: `tests/helpers/fake_evaluation_framework.py`
- Create: `tests/helpers/golden.py`
- Create: `tests/fixtures/golden_requests/anthropic_none.json`, `openrouter_vllm_none.json`, `ollama_none.json` (captured by the test, never hand-written)
- Test: `tests/test_benchmark_golden_requests.py`

**Interfaces:**
- Consumes: claude_loop._sleep (P01-T02); vmd_ai_agent.VmdAiAgent, _resolve_provider, _NoopQueue (unchanged)
- Produces:
  - helpers.fake_evaluation_framework.install() -> bool
  - helpers.golden.GOLDEN_DIR
  - helpers.golden.RecordingUrlopen(responses: List[bytes]) with .requests: List[Dict[str, Any]] of {url, method, headers, body_text}
  - helpers.golden.build_benchmark_agent(config: Dict[str, Any]) -> VmdAiAgent (after asyncio.run(setup()), vmd_backend 'vmd_python')
  - helpers.golden.ScriptedBridge (strict six keywords; results in order: ok, error, snapshot with TINY_PNG_B64)
  - helpers.golden.scripted_responses(provider: str, *, rescue: bool = False) -> List[bytes]
  - helpers.golden.drive_benchmark_run(agent, provider: str, *, rescue: bool = False) -> List[Dict[str, Any]]
  - helpers.golden.assert_golden(name: str, requests: List[Dict[str, Any]]) -> None
  - (also) `helpers.fake_evaluation_framework.FAKE_MARKER`, `BaseAgent`, `AgentResult`, `register_agent`, `get_agent`; `helpers.golden.PROVIDER_CONFIGS: Dict[str, Dict[str, Any]]` (keys `anthropic`, `openrouter_vllm`, `ollama`), `COMMON_CONFIG`, `TASK_PROMPT`, `RESCUE_PROMPT`, `TINY_PNG_B64`, `DEFAULT_RESULTS`, `RESCUE_RESULTS`, `UPDATE_ENV = "CHATVMD_UPDATE_GOLDENS"`, `RecordingUrlopen.unconsumed -> int`, `import_adapter() -> module` (installs the fake framework if needed and imports `vmd_ai_agent`)

`provider` in the golden helpers is one of `anthropic` (adapter provider `anthropic` → loop `anthropic-direct`), `openrouter_vllm` (adapter provider `vllm` → loop `openrouter` pointed at `http://localhost:8000/v1` through the adapter's `VMD_AI_OPENAI_BASE_URL` export) and `ollama`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_benchmark_golden_requests.py`:

```python
"""S7 golden requests (spec §2a): options=None requests stay byte-identical.

Each case builds the real benchmark adapter (VmdAiAgent + setup()) and drives
a scripted run: turn 1 plain; turn 2 after two run_vmd_command results (one
ok, one error); turn 3 after a capture_vmd_snapshot result with image_b64.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from helpers import fake_evaluation_framework as fake
from helpers.golden import (
    COMMON_CONFIG,
    GOLDEN_DIR,
    PROVIDER_CONFIGS,
    assert_golden,
    build_benchmark_agent,
    drive_benchmark_run,
)

CASES = [("anthropic", "none"), ("openrouter_vllm", "none"), ("ollama", "none")]
EXPECTED_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openrouter_vllm": "http://localhost:8000/v1/chat/completions",
    "ollama": "http://127.0.0.1:11435/api/chat",
}


@pytest.mark.parametrize("provider,arm", CASES)
def test_golden(provider, arm):
    agent = build_benchmark_agent(dict(COMMON_CONFIG, **PROVIDER_CONFIGS[provider]))
    requests = drive_benchmark_run(agent, provider)
    assert [r["url"] for r in requests] == [EXPECTED_URLS[provider]] * 3
    if provider == "ollama":
        assert all(json.loads(r["body_text"])["options"] == {"num_ctx": 8192}
                   for r in requests)
    assert_golden(f"{provider}_{arm}", requests)


@contextmanager
def _isolated_framework_modules() -> Iterator[None]:
    saved = {name: mod for name, mod in sys.modules.items()
             if name == "evaluation_framework" or name.startswith("evaluation_framework.")}
    for name in saved:
        del sys.modules[name]
    try:
        yield
    finally:
        for name in [n for n in sys.modules
                     if n == "evaluation_framework" or n.startswith("evaluation_framework.")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_fake_framework_only_when_missing(tmp_path, monkeypatch):
    with _isolated_framework_modules():
        assert fake.install() is True
        module = sys.modules["evaluation_framework.base_agent"]
        assert getattr(module, fake.FAKE_MARKER) is True
        from evaluation_framework.agent_registry import register_agent

        class Probe:
            pass

        assert register_agent("probe")(Probe) is Probe
        assert fake.install() is False  # already importable: left alone

    real = tmp_path / "real" / "evaluation_framework"
    real.mkdir(parents=True)
    (real / "__init__.py").write_text("")
    (real / "base_agent.py").write_text(
        "class BaseAgent:\n    pass\n\n\nclass AgentResult:\n    pass\n"
    )
    (real / "agent_registry.py").write_text("def register_agent(name):\n    return lambda c: c\n")
    monkeypatch.syspath_prepend(str(real.parent))
    with _isolated_framework_modules():
        assert fake.install() is False
        module = sys.modules["evaluation_framework.base_agent"]
        assert not hasattr(module, fake.FAKE_MARKER)
        assert Path(module.__file__).parent == real


def test_golden_diff_is_readable():
    golden = json.loads((GOLDEN_DIR / "anthropic_none.json").read_text(encoding="utf-8"))
    requests = golden["requests"]

    reserialised = [dict(r) for r in requests]
    body = json.loads(reserialised[0]["body_text"])
    reserialised[0]["body_text"] = json.dumps(body, separators=(",", ":"))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", reserialised)
    message = str(info.value)
    assert "request 0 body_text: first difference at char" in message
    assert "parse to equal JSON; the bytes differ" in message

    changed = [dict(r) for r in requests]
    body = json.loads(changed[1]["body_text"])
    body["max_tokens"] = 4095
    changed[1]["body_text"] = json.dumps(body)
    changed[2] = dict(changed[2], headers=dict(changed[2]["headers"], **{"X-api-key": "sk-other"}))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", changed)
    message = str(info.value)
    assert '+ "max_tokens": 4095,' in message
    assert '- "max_tokens": 4096,' in message
    assert "request 2 header X-api-key: expected 'sk-ant-golden', got 'sk-other'" in message
```

`test_golden_diff_is_readable` pins Review Focus 3: a body that only changed separators must be reported as a byte difference whose JSON parses equal, and a real value change must show up as a readable `-`/`+` diff line.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: collection error, `E   ModuleNotFoundError: No module named 'helpers.fake_evaluation_framework'`, `1 error`.

- [ ] **Step 3: Create `tests/helpers/fake_evaluation_framework.py`**

```python
"""A minimal stand-in for SciVisAgentBench's ``evaluation_framework`` (C9).

The real package lives in the gitignored ``SciVisAgentBench-main/`` checkout,
so CI can't import it.  ``install()`` registers three modules in
``sys.modules`` -- ``evaluation_framework``, ``.base_agent`` (``BaseAgent``,
``AgentResult``) and ``.agent_registry`` (``register_agent`` as an identity
decorator) -- but only when the real package is not importable.  That is
enough for ``integrations/scivisagentbench/vmd_ai_agent.py`` and
``integrations/explore_arm/explore_agent.py`` to import and run.
"""
from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, Optional

FAKE_MARKER = "_vmdai_fake_evaluation_framework"


class AgentResult:
    def __init__(
        self,
        success: bool,
        response: str = "",
        error: Optional[str] = None,
        output_files: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.success = success
        self.response = response
        self.error = error
        self.output_files = output_files or {}
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "response": self.response,
            "error": self.error,
            "output_files": self.output_files,
            "metadata": self.metadata,
        }


class BaseAgent:
    """The parts of the real BaseAgent that VmdAiAgent uses."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.agent_name = config.get("agent_name", self.__class__.__name__)
        self.eval_mode = config.get("eval_mode", "generic")
        backbone = str(config.get("model", "unknown_model")).replace("/", "-")
        experiment = config.get("experiment_number", "exp_default")
        self.agent_mode = f"{self.agent_name}_{backbone}_{experiment}"

    def count_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.33)

    async def setup(self) -> None:
        return None

    async def teardown(self) -> None:
        return None

    def get_result_directories(self, case_dir: str, case_name: str) -> Dict[str, Path]:
        case_path = Path(case_dir)
        return {
            "results_dir": case_path / "results" / self.agent_mode,
            "test_results_dir": case_path / "test_results" / self.agent_mode,
            "evaluation_dir": case_path / "evaluation_results" / self.agent_mode,
        }


_REGISTRY: Dict[str, type] = {}


def register_agent(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_agent(name: str) -> type:
    return _REGISTRY[name]


def _real_importable() -> bool:
    try:
        importlib.import_module("evaluation_framework.base_agent")
        importlib.import_module("evaluation_framework.agent_registry")
    except ImportError:
        return False
    return True


def install() -> bool:
    """Register the fake modules unless the real package imports.

    Returns True when the fake was installed by this call, False when the
    real package (or an earlier fake) is already importable.
    """
    if _real_importable():
        return False
    for name in list(sys.modules):
        if name == "evaluation_framework" or name.startswith("evaluation_framework."):
            del sys.modules[name]
    package = types.ModuleType("evaluation_framework")
    package.__path__ = []  # a package, so submodule imports resolve via sys.modules
    base_agent = types.ModuleType("evaluation_framework.base_agent")
    base_agent.BaseAgent = BaseAgent
    base_agent.AgentResult = AgentResult
    agent_registry = types.ModuleType("evaluation_framework.agent_registry")
    agent_registry.register_agent = register_agent
    agent_registry.get_agent = get_agent
    agent_registry._AGENT_REGISTRY = _REGISTRY
    for module in (package, base_agent, agent_registry):
        setattr(module, FAKE_MARKER, True)
    package.base_agent = base_agent
    package.agent_registry = agent_registry
    package.BaseAgent = BaseAgent
    package.register_agent = register_agent
    package.get_agent = get_agent
    sys.modules["evaluation_framework"] = package
    sys.modules["evaluation_framework.base_agent"] = base_agent
    sys.modules["evaluation_framework.agent_registry"] = agent_registry
    return True
```

The real package is not on `sys.path` when `tests/` runs (the adapter only adds the repo root and its own directory), so on the dev Mac and in CI alike the fake is what `vmd_ai_agent` imports. The real `register_agent` raises on a duplicate name; the fake does not, so importing the adapter more than once in a session is safe.

- [ ] **Step 4: Create `tests/helpers/golden.py`**

```python
"""S7 golden-request harness (spec §2a "Golden requests", P01-T04/T05).

Builds the benchmark adapter exactly as SciVisAgentBench does
(``VmdAiAgent(config)`` + ``setup()``), swaps in a scripted bridge, and drives
one task through ``run_task`` while a fake ``urlopen`` records every request.
Goldens store each request's url, method, headers and raw ``body_text`` and
are compared byte-for-byte: json.dumps key order and separators are part of
the pinned behaviour, so parsed-dict equality is not enough.
"""
from __future__ import annotations

import asyncio
import copy
import difflib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from helpers.fake_evaluation_framework import install as install_fake_framework

REPO = Path(__file__).resolve().parents[2]
SCIVIS_DIR = REPO / "integrations" / "scivisagentbench"
GOLDEN_DIR = REPO / "tests" / "fixtures" / "golden_requests"
UPDATE_ENV = "CHATVMD_UPDATE_GOLDENS"

TASK_PROMPT = "Load 1ubq.pdb, show it as NewCartoon, and take a snapshot to check the view."
RESCUE_PROMPT = "Load 1ubq.pdb."
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)

# One benchmark config per provider (the "none" arm).
PROVIDER_CONFIGS: Dict[str, Dict[str, Any]] = {
    "anthropic": {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "api_key": "sk-ant-golden",
    },
    "openrouter_vllm": {
        "provider": "vllm",
        "model": "Qwen/Qwen2.5-72B-Instruct-AWQ",
        "base_url": "http://localhost:8000/v1",
        "api_key": "sk-local-anything",
    },
    "ollama": {
        "provider": "ollama",
        "model": "qwen3.8:27b",
        "base_url": "http://127.0.0.1:11435",
    },
}
COMMON_CONFIG: Dict[str, Any] = {
    "agent_name": "vmd_ai",
    "eval_mode": "mcp",
    "experiment_number": "golden",
    "enable_rag": False,
    "enable_wiki": False,
    "loop_timeout": 120,
    "vmd_backend": "vmd_python",
}

# (tool_use id, tool name, input) per scripted turn; ids are ignored by Ollama.
_TURNS: List[Tuple[str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    (
        "I'll load the structure and set the style.",
        [
            ("toolu_golden_1", "run_vmd_command",
             {"command": "mol new 1ubq.pdb", "rationale": "load the structure"}),
            ("toolu_golden_2", "run_vmd_command",
             {"command": "mol modstyle 0 0 NewCartoonX"}),
        ],
    ),
    (
        "The style name was wrong; checking the view.",
        [("toolu_golden_3", "capture_vmd_snapshot", {"purpose": "check the cartoon"})],
    ),
    ("1ubq is loaded and shown as NewCartoon.", []),
]
_RESCUE_TURNS: List[Tuple[str, List[Tuple[str, str, Dict[str, Any]]]]] = [
    (
        'I will run this: {"name": "run_vmd_command", '
        '"arguments": {"command": "mol new 1ubq.pdb"}}',
        [],
    ),
    ("Loaded 1ubq.", []),
]

_OK_RESULT = {"ok": True, "output": "Info) Using plugin pdb for structure file 1ubq.pdb\n0",
              "error": ""}
_ERROR_RESULT = {"ok": False, "output": "",
                 "error": "Unknown representation style 'NewCartoonX'"}
_SNAPSHOT_RESULT = {"ok": True, "output": "Snapshot rendered (check the cartoon).",
                    "error": "", "image_b64": TINY_PNG_B64, "image_mime": "image/png"}
DEFAULT_RESULTS: List[Dict[str, Any]] = [_OK_RESULT, _ERROR_RESULT, _SNAPSHOT_RESULT]
RESCUE_RESULTS: List[Dict[str, Any]] = [_OK_RESULT]


class RecordingUrlopen:
    """Fake ``urllib.request.urlopen``: records each request, serves canned bodies."""

    def __init__(self, responses: List[bytes]) -> None:
        self._responses = list(responses)
        self.requests: List[Dict[str, Any]] = []

    def __call__(self, req: Any, timeout: Optional[float] = None, **_kw: Any) -> io.BytesIO:
        data = req.data or b""
        self.requests.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(sorted(req.header_items())),
            "body_text": data.decode("utf-8"),
        })
        if not self._responses:
            raise AssertionError(
                f"unexpected request #{len(self.requests)} to {req.full_url}"
            )
        return io.BytesIO(self._responses.pop(0))

    @property
    def unconsumed(self) -> int:
        return len(self._responses)


class ScriptedBridge:
    """Strict six-keyword bridge that answers tool calls from a fixed list."""

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None) -> None:
        self._results = copy.deepcopy(DEFAULT_RESULTS if results is None else results)
        self.calls: List[Dict[str, Any]] = []

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None

    def execute_tool(self, *, session_id, tool_call_id, tool_name, tool_input,
                     session_queue, cancel_event) -> Dict[str, Any]:
        self.calls.append({"tool_call_id": tool_call_id, "tool_name": tool_name,
                           "tool_input": dict(tool_input or {})})
        if not self._results:
            raise AssertionError(f"no scripted result left for {tool_name}")
        return self._results.pop(0)


def _sse(events: List[Dict[str, Any]], done: bool = False) -> bytes:
    body = b"".join(b"data: " + json.dumps(e).encode("utf-8") + b"\n\n" for e in events)
    return body + (b"data: [DONE]\n\n" if done else b"")


def _anthropic_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    events: List[Dict[str, Any]] = [
        {"type": "message_start", "message": {"id": "msg_golden", "role": "assistant"}},
    ]
    index = 0
    if text:
        events += [
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": text}},
            {"type": "content_block_stop", "index": 0},
        ]
        index = 1
    for call_id, name, tool_input in calls:
        events += [
            {"type": "content_block_start", "index": index,
             "content_block": {"type": "tool_use", "id": call_id, "name": name, "input": {}}},
            {"type": "content_block_delta", "index": index,
             "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input)}},
            {"type": "content_block_stop", "index": index},
        ]
        index += 1
    events += [
        {"type": "message_delta",
         "delta": {"stop_reason": "tool_use" if calls else "end_turn"}},
        {"type": "message_stop"},
    ]
    return _sse(events)


def _openai_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    chunks: List[Dict[str, Any]] = []
    if text:
        chunks.append({"choices": [{"index": 0,
                                    "delta": {"role": "assistant", "content": text}}]})
    for i, (call_id, name, tool_input) in enumerate(calls):
        chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": i, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(tool_input)},
        }]}}]})
    chunks.append({"choices": [{"index": 0, "delta": {},
                                "finish_reason": "tool_calls" if calls else "stop"}]})
    return _sse(chunks, done=True)


def _ollama_turn(text: str, calls: List[Tuple[str, str, Dict[str, Any]]]) -> bytes:
    lines: List[Dict[str, Any]] = []
    if text:
        lines.append({"model": "golden", "done": False,
                      "message": {"role": "assistant", "content": text}})
    final: Dict[str, Any] = {"role": "assistant", "content": ""}
    if calls:
        final["tool_calls"] = [{"function": {"name": name, "arguments": tool_input}}
                               for _call_id, name, tool_input in calls]
    lines.append({"model": "golden", "done": True, "done_reason": "stop", "message": final})
    return b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines)


_TURN_BUILDERS = {
    "anthropic": _anthropic_turn,
    "openrouter_vllm": _openai_turn,
    "ollama": _ollama_turn,
}


def scripted_responses(provider: str, *, rescue: bool = False) -> List[bytes]:
    """Response bodies for the scripted run (3 turns, or 2 for the rescue run)."""
    if rescue and provider != "ollama":
        raise ValueError("the rescued-turn script is Ollama-only")
    build = _TURN_BUILDERS[provider]
    return [build(text, calls) for text, calls in (_RESCUE_TURNS if rescue else _TURNS)]


def import_adapter() -> Any:
    install_fake_framework()
    if str(SCIVIS_DIR) not in sys.path:
        sys.path.insert(0, str(SCIVIS_DIR))
    import vmd_ai_agent  # registers "vmd_ai" with the (fake) framework

    return vmd_ai_agent


def build_benchmark_agent(config: Dict[str, Any]) -> Any:
    """A VmdAiAgent after ``asyncio.run(agent.setup())`` (vmd_backend 'vmd_python')."""
    adapter = import_adapter()
    cfg = dict(config)
    cfg["vmd_backend"] = "vmd_python"
    agent = adapter.VmdAiAgent(cfg)
    asyncio.run(agent.setup())
    return agent


def drive_benchmark_run(agent: Any, provider: str, *, rescue: bool = False) -> List[Dict[str, Any]]:
    """Run one scripted task through ``agent.run_task``; return the recorded requests."""
    recorder = RecordingUrlopen(scripted_responses(provider, rescue=rescue))
    agent._bridge = ScriptedBridge(RESCUE_RESULTS if rescue else DEFAULT_RESULTS)
    with tempfile.TemporaryDirectory(prefix="vmdai_golden_") as work:
        task = {"working_dir": work, "case_dir": work, "case_name": "golden", "timeout": 60}
        with mock.patch("urllib.request.urlopen", recorder):
            result = asyncio.run(
                agent.run_task(RESCUE_PROMPT if rescue else TASK_PROMPT, task)
            )
    assert result.success, result.error
    assert recorder.unconsumed == 0, f"{recorder.unconsumed} scripted responses unused"
    assert agent._bridge._results == [], "scripted tool results left unused"
    return recorder.requests


def _pretty(body_text: str) -> List[str]:
    try:
        return json.dumps(json.loads(body_text), indent=1, ensure_ascii=False).splitlines()
    except ValueError:
        return body_text.splitlines()


def _first_difference(expected: str, actual: str) -> int:
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            return i
    return min(len(expected), len(actual))


def _diff_request(i: int, expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    for key in ("url", "method"):
        if expected[key] != actual[key]:
            problems.append(f"request {i} {key}: expected {expected[key]!r}, got {actual[key]!r}")
    if expected["headers"] != actual["headers"]:
        keys = sorted(set(expected["headers"]) | set(actual["headers"]))
        for key in keys:
            want, got = expected["headers"].get(key), actual["headers"].get(key)
            if want != got:
                problems.append(f"request {i} header {key}: expected {want!r}, got {got!r}")
    want_body, got_body = expected["body_text"], actual["body_text"]
    if want_body != got_body:
        at = _first_difference(want_body, got_body)
        problems.append(
            f"request {i} body_text: first difference at char {at}: "
            f"expected ...{want_body[max(0, at - 40):at + 40]!r}... "
            f"got ...{got_body[max(0, at - 40):at + 40]!r}..."
        )
        pretty_want, pretty_got = _pretty(want_body), _pretty(got_body)
        if pretty_want == pretty_got:
            problems.append(
                f"request {i} body_text: the bodies parse to equal JSON; the bytes differ "
                "(json.dumps key order or separators changed)"
            )
        else:
            diff = difflib.unified_diff(pretty_want, pretty_got, "golden", "actual",
                                        n=2, lineterm="")
            problems.extend(list(diff)[:60])
    return problems


def assert_golden(name: str, requests: List[Dict[str, Any]]) -> None:
    """Compare ``requests`` with tests/fixtures/golden_requests/<name>.json byte-for-byte.

    A missing golden is written only when CHATVMD_UPDATE_GOLDENS=1; an
    existing one is never rewritten (S7 goldens are captured once, in M0).
    """
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        if os.environ.get(UPDATE_ENV) == "1":
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            payload = {"name": name, "requests": requests}
            path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
            return
        raise AssertionError(
            f"missing S7 golden {path}; capture it once with {UPDATE_ENV}=1 "
            "(existing S7 goldens are never regenerated)"
        )
    expected = json.loads(path.read_text(encoding="utf-8"))["requests"]
    problems: List[str] = []
    if len(expected) != len(requests):
        problems.append(f"request count: expected {len(expected)}, got {len(requests)}")
    for i, (want, got) in enumerate(zip(expected, requests)):
        problems.extend(_diff_request(i, want, got))
    if problems:
        raise AssertionError(f"S7 golden mismatch for {name} ({path}):\n" + "\n".join(problems))
```

Notes for the implementer:
- `run_task` is the benchmark's real entry point: it `chdir`s into the temp working dir, calls `bridge.reset()`, runs `ClaudeToolLoop.run` in an executor thread with `session_id="scivis"` and `_NoopQueue()`, and writes `golden.tcl`/`golden.response.txt` into the temp dir, which is then deleted. `mock.patch("urllib.request.urlopen", …)` is process-global, so the executor thread sees it.
- `vmd_backend` is forced to `vmd_python` so `setup()` builds a `HeadlessVmdBridge` (which imports `vmd` only lazily) instead of spawning VMD; the scripted bridge then replaces it.
- `CHATVMD_UPDATE_GOLDENS` is not one of the cleared prefixes, so it reaches the test.

- [ ] **Step 5: Run the tests to verify the goldens are missing**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: `4 failed, 1 passed`. The three `test_golden[…-none]` cases fail with `AssertionError: missing S7 golden …/tests/fixtures/golden_requests/<provider>_none.json; capture it once with CHATVMD_UPDATE_GOLDENS=1 (existing S7 goldens are never regenerated)`, `test_golden_diff_is_readable` fails with `FileNotFoundError` for `anthropic_none.json`, and `test_fake_framework_only_when_missing` passes.

- [ ] **Step 6: Confirm the code under test is the baseline**

Run: `git diff --stat baseline-2026-09-24 -- runtime/ integrations/`
Expected: only ` runtime/vmd_ai_runtime/claude_loop.py | 8 ++++++--` (the P01-T02 `_sleep` indirection). If anything else is listed, stop: the goldens must be captured from baseline behaviour.

- [ ] **Step 7: Capture the three goldens once**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest "tests/test_benchmark_golden_requests.py::test_golden" -q`
Expected: `3 passed`.

Run: `shasum -a 256 tests/fixtures/golden_requests/*.json`
Expected exactly:

```text
10231c03bd7a487d4d6329f0955a39aa75bb3f4fa7e50094636b465750720f9b  tests/fixtures/golden_requests/anthropic_none.json
4281275674c78b95afc991d14c765ce53f78f67792addb9409a306b9ef2905bf  tests/fixtures/golden_requests/ollama_none.json
ecfaee2bded1d5eb2e8f9b4c272c55cbf86e4e93dd37bd53c9e1e23a68813af1  tests/fixtures/golden_requests/openrouter_vllm_none.json
```

(24 072, 23 714 and 24 294 bytes; byte-identical under Python 3.9 and 3.12.) If a hash differs, delete the three files, compare `tests/helpers/golden.py` and the test with this plan, fix the difference and capture again. Never commit goldens with other hashes.

Sanity-check the content:

```bash
python - <<'PY'
import json
for name in ("anthropic_none", "openrouter_vllm_none", "ollama_none"):
    requests = json.load(open(f"tests/fixtures/golden_requests/{name}.json"))["requests"]
    last = json.loads(requests[-1]["body_text"])
    print(name, len(requests), requests[0]["url"], len(last["messages"]))
PY
```

Expected:

```text
anthropic_none 3 https://api.anthropic.com/v1/messages 5
openrouter_vllm_none 3 http://localhost:8000/v1/chat/completions 7
ollama_none 3 http://127.0.0.1:11435/api/chat 7
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: `5 passed`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `495 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 9: Commit**

```bash
git add tests/helpers/fake_evaluation_framework.py tests/helpers/golden.py tests/test_benchmark_golden_requests.py tests/fixtures/golden_requests/anthropic_none.json tests/fixtures/golden_requests/openrouter_vllm_none.json tests/fixtures/golden_requests/ollama_none.json
git commit -F - <<'MSG'
test(m0): S7 golden requests for the none arm (anthropic, vLLM, Ollama)

The real benchmark adapter is set up (through a stand-in
evaluation_framework when the real one is missing) and drives a scripted
3-turn run; every request's url, headers and raw body_text is compared
byte-for-byte with goldens captured once from baseline behaviour.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T05: Golden requests for rag, wiki, extra_tools and the Ollama rescue turn

**Files:**
- Modify: `tests/helpers/golden.py` (created in P01-T04)
- Modify (replace whole file): `tests/test_benchmark_golden_requests.py`
- Create: `tests/fixtures/golden_requests/anthropic_rag.json`, `anthropic_wiki.json`, `anthropic_extra_tools.json`, `openrouter_vllm_rag.json`, `openrouter_vllm_wiki.json`, `openrouter_vllm_extra_tools.json`, `ollama_rag.json`, `ollama_wiki.json`, `ollama_extra_tools.json`, `ollama_rescue.json` (captured by the test)

**Interfaces:**
- Consumes: helpers.golden.* (P01-T04)
- Produces:
  - helpers.golden.benchmark_config(provider: str, arm: str, tmp_path: Path) -> Dict[str, Any] (provider in anthropic|openrouter_vllm|ollama; arm in none|rag|wiki|extra_tools)
  - (also) `helpers.golden.ARMS = ("none", "rag", "wiki", "extra_tools")`; `helpers.golden.StubDocsSearch` (patched over `vmd_ai_runtime.docs_search.DocsSearch` by `build_benchmark_agent` when `enable_rag` is set)

The arms mirror the adapter's config switches: `rag` = `enable_rag` (a `DocsSearch` stub whose `is_available` is True, so `search_docs` is offered); `wiki` = `enable_wiki` with `wiki_root`/`wiki_raw_root` under `tmp_path` (the adapter bootstraps a `WikiStore` there and the loop appends `WIKI_SYSTEM_PROMPT_ADDENDUM`); `extra_tools` = `enable_semantic_tools` (the adapter sets `extra_tools` to `vmd_measure`, `vmd_traj_measure`, `vmd_represent` and appends `tool_directive(config)`).

- [ ] **Step 1: Write the failing tests**

Replace the whole of `tests/test_benchmark_golden_requests.py` with:

```python
"""S7 golden requests (spec §2a): options=None requests stay byte-identical.

Each case builds the real benchmark adapter (VmdAiAgent + setup()) and drives
a scripted run: turn 1 plain; turn 2 after two run_vmd_command results (one
ok, one error); turn 3 after a capture_vmd_snapshot result with image_b64.
The rescue case is one Ollama turn whose tool call arrives as JSON text.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from helpers import fake_evaluation_framework as fake
from helpers.golden import (
    ARMS,
    GOLDEN_DIR,
    assert_golden,
    benchmark_config,
    build_benchmark_agent,
    drive_benchmark_run,
)

PROVIDERS = ("anthropic", "openrouter_vllm", "ollama")
CASES = [(provider, arm) for provider in PROVIDERS for arm in ARMS]
EXPECTED_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openrouter_vllm": "http://localhost:8000/v1/chat/completions",
    "ollama": "http://127.0.0.1:11435/api/chat",
}
BASE_TOOLS = ["run_vmd_command", "capture_vmd_snapshot"]
ARM_TOOLS = {
    "none": BASE_TOOLS,
    "rag": BASE_TOOLS + ["search_docs"],
    "wiki": BASE_TOOLS + ["wiki_list", "wiki_read", "wiki_update", "wiki_verify_pins"],
    "extra_tools": BASE_TOOLS + ["vmd_measure", "vmd_traj_measure", "vmd_represent"],
}


def _tool_names(body: Dict[str, Any]) -> List[str]:
    return [t.get("name") or t["function"]["name"] for t in body["tools"]]


def _system_prompt(body: Dict[str, Any]) -> str:
    if "system" in body:
        return body["system"]
    return body["messages"][0]["content"]


@pytest.mark.parametrize("provider,arm", CASES)
def test_golden(provider, arm, tmp_path):
    from vmd_ai_runtime.claude_loop import WIKI_SYSTEM_PROMPT_ADDENDUM

    agent = build_benchmark_agent(benchmark_config(provider, arm, tmp_path))
    requests = drive_benchmark_run(agent, provider)
    assert [r["url"] for r in requests] == [EXPECTED_URLS[provider]] * 3
    first = json.loads(requests[0]["body_text"])
    assert _tool_names(first) == ARM_TOOLS[arm]
    assert _system_prompt(first).endswith(WIKI_SYSTEM_PROMPT_ADDENDUM) == (arm == "wiki")
    if provider == "ollama":
        assert all(json.loads(r["body_text"])["options"] == {"num_ctx": 8192}
                   for r in requests)
    assert_golden(f"{provider}_{arm}", requests)


def test_golden_ollama_rescue(tmp_path):
    agent = build_benchmark_agent(benchmark_config("ollama", "none", tmp_path))
    requests = drive_benchmark_run(agent, "ollama", rescue=True)
    assert len(requests) == 2
    replayed = json.loads(requests[1]["body_text"])["messages"]
    assistant = replayed[-2]
    assert assistant["content"] == ""  # rescued JSON text is not kept in history
    assert assistant["tool_calls"][0]["id"] == "otc_rescue_1"
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"command": "mol new 1ubq.pdb"}
    assert replayed[-1] == {"role": "tool", "tool_call_id": "otc_rescue_1",
                            "content": "Info) Using plugin pdb for structure file 1ubq.pdb\n0"}
    assert_golden("ollama_rescue", requests)


@contextmanager
def _isolated_framework_modules() -> Iterator[None]:
    saved = {name: mod for name, mod in sys.modules.items()
             if name == "evaluation_framework" or name.startswith("evaluation_framework.")}
    for name in saved:
        del sys.modules[name]
    try:
        yield
    finally:
        for name in [n for n in sys.modules
                     if n == "evaluation_framework" or n.startswith("evaluation_framework.")]:
            del sys.modules[name]
        sys.modules.update(saved)


def test_fake_framework_only_when_missing(tmp_path, monkeypatch):
    with _isolated_framework_modules():
        assert fake.install() is True
        module = sys.modules["evaluation_framework.base_agent"]
        assert getattr(module, fake.FAKE_MARKER) is True
        from evaluation_framework.agent_registry import register_agent

        class Probe:
            pass

        assert register_agent("probe")(Probe) is Probe
        assert fake.install() is False  # already importable: left alone

    real = tmp_path / "real" / "evaluation_framework"
    real.mkdir(parents=True)
    (real / "__init__.py").write_text("")
    (real / "base_agent.py").write_text(
        "class BaseAgent:\n    pass\n\n\nclass AgentResult:\n    pass\n"
    )
    (real / "agent_registry.py").write_text("def register_agent(name):\n    return lambda c: c\n")
    monkeypatch.syspath_prepend(str(real.parent))
    with _isolated_framework_modules():
        assert fake.install() is False
        module = sys.modules["evaluation_framework.base_agent"]
        assert not hasattr(module, fake.FAKE_MARKER)
        assert Path(module.__file__).parent == real


def test_golden_diff_is_readable():
    golden = json.loads((GOLDEN_DIR / "anthropic_none.json").read_text(encoding="utf-8"))
    requests = golden["requests"]

    reserialised = [dict(r) for r in requests]
    body = json.loads(reserialised[0]["body_text"])
    reserialised[0]["body_text"] = json.dumps(body, separators=(",", ":"))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", reserialised)
    message = str(info.value)
    assert "request 0 body_text: first difference at char" in message
    assert "parse to equal JSON; the bytes differ" in message

    changed = [dict(r) for r in requests]
    body = json.loads(changed[1]["body_text"])
    body["max_tokens"] = 4095
    changed[1]["body_text"] = json.dumps(body)
    changed[2] = dict(changed[2], headers=dict(changed[2]["headers"], **{"X-api-key": "sk-other"}))
    with pytest.raises(AssertionError) as info:
        assert_golden("anthropic_none", changed)
    message = str(info.value)
    assert '+ "max_tokens": 4095,' in message
    assert '- "max_tokens": 4096,' in message
    assert "request 2 header X-api-key: expected 'sk-ant-golden', got 'sk-other'" in message
```

The `none` cases now build their config through `benchmark_config(provider, "none", tmp_path)`, which returns exactly `dict(COMMON_CONFIG, **PROVIDER_CONFIGS[provider])`, so the three committed goldens are compared unchanged.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: collection error, `E   ImportError: cannot import name 'ARMS' from 'helpers.golden'`.

- [ ] **Step 3: Add the arm configs to `tests/helpers/golden.py`**

Replace

```python
import asyncio
import copy
```

with

```python
import asyncio
import contextlib
import copy
```

Insert this block immediately before `def import_adapter() -> Any:`:

```python
ARMS: Tuple[str, ...] = ("none", "rag", "wiki", "extra_tools")


class StubDocsSearch:
    """Replaces vmd_ai_runtime.docs_search.DocsSearch for the rag arm."""

    is_available = True

    def __init__(self, index_dir: Optional[str] = None) -> None:
        self.index_dir = index_dir

    def search(self, query: str, k: int = 5, scope: str = "all") -> Dict[str, Any]:
        raise AssertionError("the golden script never calls search_docs")


def benchmark_config(provider: str, arm: str, tmp_path: Path) -> Dict[str, Any]:
    """The adapter config for one (provider, arm) cell of the S7 matrix."""
    if provider not in PROVIDER_CONFIGS:
        raise ValueError(f"unknown provider {provider!r}")
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    config = dict(COMMON_CONFIG, **PROVIDER_CONFIGS[provider])
    if arm == "rag":
        config["enable_rag"] = True
    elif arm == "wiki":
        config.update(enable_wiki=True,
                      wiki_root=str(tmp_path / "wiki"),
                      wiki_raw_root=str(tmp_path / "raw"))
    elif arm == "extra_tools":
        config["enable_semantic_tools"] = True
    return config


```

In `build_benchmark_agent`, replace

```python
    agent = adapter.VmdAiAgent(cfg)
    asyncio.run(agent.setup())
    return agent
```

with

```python
    agent = adapter.VmdAiAgent(cfg)
    with contextlib.ExitStack() as stack:
        if cfg.get("enable_rag"):
            stack.enter_context(
                mock.patch("vmd_ai_runtime.docs_search.DocsSearch", StubDocsSearch)
            )
        asyncio.run(agent.setup())
    return agent
```

The adapter imports `DocsSearch` inside `setup()` (`from vmd_ai_runtime.docs_search import DocsSearch`), so patching the module attribute for the duration of `setup()` is enough.

- [ ] **Step 4: Run the tests to verify the new goldens are missing**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: `10 failed, 5 passed`. The nine `test_golden[<provider>-rag|wiki|extra_tools]` cases and `test_golden_ollama_rescue` fail with `missing S7 golden …`; the three `-none` cases, `test_fake_framework_only_when_missing` and `test_golden_diff_is_readable` pass.

- [ ] **Step 5: Capture the ten new goldens once**

Run: `CHATVMD_UPDATE_GOLDENS=1 python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: `15 passed`. The three existing `*_none.json` goldens are compared, not rewritten: `git status --short tests/fixtures/golden_requests` lists exactly ten new (`??`) files and no modified ones.

Run: `shasum -a 256 tests/fixtures/golden_requests/*.json`
Expected exactly:

```text
d19ea22cbacf9f103d8c30f7609f37bea9574eb6fe4c1d3954206266e0cb2de3  tests/fixtures/golden_requests/anthropic_extra_tools.json
10231c03bd7a487d4d6329f0955a39aa75bb3f4fa7e50094636b465750720f9b  tests/fixtures/golden_requests/anthropic_none.json
0229f194ccbfe8685919c06bb69bf0a5559fb892b3c1c204957954598d9b86fc  tests/fixtures/golden_requests/anthropic_rag.json
7c46e3fae4117760d67140ec834e70537d098b08c333ad69b389c1e60b7b8135  tests/fixtures/golden_requests/anthropic_wiki.json
68c633a11f6d094263e33250eb38fe34d7163b5d03f5f38ef8614a31af97b3bf  tests/fixtures/golden_requests/ollama_extra_tools.json
4281275674c78b95afc991d14c765ce53f78f67792addb9409a306b9ef2905bf  tests/fixtures/golden_requests/ollama_none.json
dfeef7056c9270c6b0f1ad25c1ec22bc04189c0ab4f9b6c5a061e98afb859365  tests/fixtures/golden_requests/ollama_rag.json
72ee3a874f45fd689dfe3e42816605e51b74f5d24339a88e8223b243b8e7cf39  tests/fixtures/golden_requests/ollama_rescue.json
8e148565149946b9a52d3eadbc42356c24c22a8b971cfe17b329b14c65289c89  tests/fixtures/golden_requests/ollama_wiki.json
451c42066875289ffafeb702b9d7593f4bf0c5a8b7dd72eb8262673192ff851a  tests/fixtures/golden_requests/openrouter_vllm_extra_tools.json
ecfaee2bded1d5eb2e8f9b4c272c55cbf86e4e93dd37bd53c9e1e23a68813af1  tests/fixtures/golden_requests/openrouter_vllm_none.json
da74e77f6ab3c5ee7d1ce5dde258c52e3000ebae8f9e6b44f09d4087cdcaed53  tests/fixtures/golden_requests/openrouter_vllm_rag.json
cc1db9c3dd573c5c4bc8cadbd0019f7af473b51ca82e67d288c66f507fab3e28  tests/fixtures/golden_requests/openrouter_vllm_wiki.json
```

The 13 files total about 388 KB. If any new hash differs, delete only the new files, reconcile the helper and test with this plan, and capture again. The wiki goldens contain no temp paths: the wiki tools are offered but never called.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_benchmark_golden_requests.py -q`
Expected: `15 passed`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `505 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 7: Commit**

```bash
git add tests/helpers/golden.py tests/test_benchmark_golden_requests.py tests/fixtures/golden_requests/anthropic_rag.json tests/fixtures/golden_requests/anthropic_wiki.json tests/fixtures/golden_requests/anthropic_extra_tools.json tests/fixtures/golden_requests/openrouter_vllm_rag.json tests/fixtures/golden_requests/openrouter_vllm_wiki.json tests/fixtures/golden_requests/openrouter_vllm_extra_tools.json tests/fixtures/golden_requests/ollama_rag.json tests/fixtures/golden_requests/ollama_wiki.json tests/fixtures/golden_requests/ollama_extra_tools.json tests/fixtures/golden_requests/ollama_rescue.json
git commit -F - <<'MSG'
test(m0): S7 goldens for the rag, wiki and extra_tools arms and a rescued Ollama turn

Completes the provider x arm matrix (12 goldens) plus one Ollama turn
whose tool call is rescued from JSON text, all captured once from
baseline behaviour and compared byte-for-byte.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T06: Bridge guard (options=None)

**Files:**
- Test: `tests/test_benchmark_bridge_guard.py`

**Interfaces:**
- Consumes: helpers.fake_evaluation_framework.install (P01-T04); helpers.golden.RecordingUrlopen, scripted_responses (P01-T04)
- Produces:
  - LEGACY_KWARGS = frozenset of the six keyword names
  - spy_bridge(bridge) -> Tuple[Any, List[Dict[str, Any]]]
  - run_guard(loop, bridge) -> List[Dict[str, Any]]
  - STRICT_BRIDGES: List[Tuple[str, Callable[[], Any]]]
  - (also) `run_guard(loop, bridge, *, requests_out: Optional[List[Dict[str, Any]]] = None)` appends the recorded requests to `requests_out`; it maps `loop.provider_name` (`anthropic-direct`, `openrouter`, `ollama`) to the matching `scripted_responses` provider. These names live in the test module; P02-T08 imports them with `from test_benchmark_bridge_guard import LEGACY_KWARGS, STRICT_BRIDGES, run_guard, spy_bridge` (tests/ is on `pythonpath`).

The five strict bridges are the call targets named in spec §2a "Constraints": `integrations/scivisagentbench/headless_vmd_bridge.py:68-78`, `scripts/rag_ab.py:86-95` (`_StubBridge`), `scripts/bench_wiki.py:71-74` (`StubToolBridge`), the `_StubBridge` in `tests/test_claude_loop_recorder.py`, and `_stub_bridge_execute` in `tests/test_recorder_integration.py:70-72`. None has `**kwargs`, so one extra keyword from the loop raises `TypeError`.

- [ ] **Step 1: Write the test**

Create `tests/test_benchmark_bridge_guard.py`:

```python
"""S7 bridge guard (spec §2a "Bridge guard"): with options=None every bridge's
execute_tool receives exactly the six legacy keywords, and the adapter never
passes ctx or options.  P02-T08 adds the LoopOptions.product() variant here.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

import pytest

from helpers.fake_evaluation_framework import install as install_fake_framework
from helpers.golden import (
    TASK_PROMPT,
    TINY_PNG_B64,
    RecordingUrlopen,
    benchmark_config,
    scripted_responses,
)
from vmd_ai_runtime.claude_loop import ClaudeToolLoop

REPO = Path(__file__).resolve().parents[1]
SCIVIS_DIR = REPO / "integrations" / "scivisagentbench"
EXPLORE_DIR = REPO / "integrations" / "explore_arm"
SCRIPTS_DIR = REPO / "scripts"

LEGACY_KWARGS = frozenset(
    {"session_id", "tool_call_id", "tool_name", "tool_input", "session_queue", "cancel_event"}
)
SCRIPTED_TOOLS = ["run_vmd_command", "run_vmd_command", "capture_vmd_snapshot"]
_GOLDEN_PROVIDER = {
    "anthropic-direct": "anthropic",
    "openrouter": "openrouter_vllm",
    "ollama": "ollama",
}
_OK = {"ok": True, "output": "ok", "error": ""}
_SNAP = {"ok": True, "output": "snapshot", "error": "", "image_b64": TINY_PNG_B64,
         "image_mime": "image/png"}


def _on_path(*dirs: Path) -> None:
    for directory in dirs:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))


def spy_bridge(bridge: Any) -> Tuple[Any, List[Dict[str, Any]]]:
    """Record the keywords of every execute_tool call, then call the real method.

    The real (strict) signature still runs, so an extra keyword raises TypeError.
    """
    calls: List[Dict[str, Any]] = []
    original = bridge.execute_tool

    def execute_tool(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        assert args == (), f"positional arguments passed: {args!r}"
        calls.append(dict(kwargs))
        return original(**kwargs)

    bridge.execute_tool = execute_tool
    return bridge, calls


def run_guard(loop: ClaudeToolLoop, bridge: Any, *,
              requests_out: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Drive the scripted 3-turn run through ``loop`` against a spied ``bridge``."""
    spied, calls = spy_bridge(bridge)
    recorder = RecordingUrlopen(scripted_responses(_GOLDEN_PROVIDER[loop.provider_name]))
    with mock.patch("urllib.request.urlopen", recorder):
        loop.run(
            prompt=TASK_PROMPT,
            system_prompt="bridge guard",
            tool_bridge=spied,
            session_id="guard",
            session_queue=None,
            cancel_event=threading.Event(),
            on_chunk=lambda text: None,
        )
    assert recorder.unconsumed == 0
    if requests_out is not None:
        requests_out.extend(recorder.requests)
    return calls


def _anthropic_loop() -> ClaudeToolLoop:
    return ClaudeToolLoop(provider_name="anthropic-direct", api_key="sk-ant-guard",
                          model="claude-sonnet-4-5")


def _headless() -> Any:
    _on_path(SCIVIS_DIR)
    from headless_vmd_bridge import HeadlessVmdBridge

    bridge = HeadlessVmdBridge()
    bridge._run_tcl = lambda command: dict(_OK)
    bridge._snapshot = lambda purpose: dict(_SNAP)
    return bridge


def _rag_ab() -> Any:
    _on_path(SCRIPTS_DIR)
    return importlib.import_module("rag_ab")._StubBridge()


def _bench_wiki() -> Any:
    _on_path(SCRIPTS_DIR)
    return importlib.import_module("bench_wiki").StubToolBridge()


def _claude_loop_recorder_stub() -> Any:
    return importlib.import_module("test_claude_loop_recorder")._StubBridge()


def _recorder_integration_stub() -> Any:
    execute = importlib.import_module("test_recorder_integration")._stub_bridge_execute
    return type("RecorderIntegrationStub", (), {"execute_tool": execute})()


STRICT_BRIDGES: List[Tuple[str, Callable[[], Any]]] = [
    ("headless", _headless),
    ("rag_ab", _rag_ab),
    ("bench_wiki", _bench_wiki),
    ("claude_loop_recorder_stub", _claude_loop_recorder_stub),
    ("recorder_integration_stub", _recorder_integration_stub),
]


@pytest.mark.parametrize("name,factory", STRICT_BRIDGES, ids=[n for n, _ in STRICT_BRIDGES])
def test_strict_bridges_receive_six_keywords(name, factory):
    calls = run_guard(_anthropic_loop(), factory())
    assert [c["tool_name"] for c in calls] == SCRIPTED_TOOLS
    for call in calls:
        assert set(call) == LEGACY_KWARGS


def test_benchmark_chain_receives_six_keywords():
    _on_path(EXPLORE_DIR, SCIVIS_DIR)
    import subprocess_vmd_bridge as svb
    from explore_bridge import ExploreScaffoldBridge
    from retrieval_bridge import RetrievalAugmentingBridge
    from scaffold import LabProtocol

    with mock.patch.object(svb, "_resolve_vmd", return_value=("/nonexistent/vmd", None)):
        inner = svb.SubprocessVmdBridge(timeout=5)
    inner._start = lambda: None
    inner._run_tcl = lambda command: dict(_OK)
    inner._snapshot = lambda purpose, save_path=None: dict(_SNAP)
    inner, inner_calls = spy_bridge(inner)
    chain = ExploreScaffoldBridge(RetrievalAugmentingBridge(inner, docs_search=None),
                                  LabProtocol())

    outer_calls = run_guard(_anthropic_loop(), chain)
    assert [c["tool_name"] for c in outer_calls] == SCRIPTED_TOOLS
    assert [c["tool_name"] for c in inner_calls] == SCRIPTED_TOOLS
    for call in outer_calls + inner_calls:
        assert set(call) == LEGACY_KWARGS


def test_explore_tools_for_turn_zero_arg_lambda(tmp_path):
    install_fake_framework()
    _on_path(EXPLORE_DIR, SCIVIS_DIR)
    from explore_agent import ExploreAgent

    agent = ExploreAgent(benchmark_config("openrouter_vllm", "none", tmp_path))
    asyncio.run(agent.setup())
    assert "_tools_for_turn" in vars(agent._loop)  # the instance-level lambda
    lab_tools = ["lab_try", "lab_note", "lab_commit"]
    assert [t["name"] for t in agent._loop._tools_for_turn()] == lab_tools

    headless = agent._bridge.inner
    headless._run_tcl = lambda command: dict(_OK)
    headless._snapshot = lambda purpose: dict(_SNAP)
    requests: List[Dict[str, Any]] = []
    calls = run_guard(agent._loop, agent._bridge, requests_out=requests)
    assert [c["tool_name"] for c in calls] == SCRIPTED_TOOLS
    for request in requests:
        body = json.loads(request["body_text"])
        assert [t["function"]["name"] for t in body["tools"]] == lab_tools


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def test_adapter_never_passes_ctx_or_options():
    for path in (SCIVIS_DIR / "vmd_ai_agent.py", EXPLORE_DIR / "explore_agent.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                names = [kw.arg for kw in node.keywords]
                assert "ctx" not in names and "options" not in names, (
                    f"{path.name}:{node.lineno} passes ctx/options"
                )

    tree = ast.parse((SCIVIS_DIR / "vmd_ai_agent.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    ctor = [c for c in calls if _dotted(c.func) == "ClaudeToolLoop"]
    assert len(ctor) == 1
    assert [kw.arg for kw in ctor[0].keywords] == [
        "provider_name", "api_key", "model", "timeout", "docs_search", "wiki_store",
    ]
    runs = [c for c in calls if _dotted(c.func) == "self._loop.run"]
    assert len(runs) == 1
    assert [kw.arg for kw in runs[0].keywords] == [
        "prompt", "system_prompt", "tool_bridge", "session_id", "session_queue",
        "cancel_event", "on_chunk", "on_tool_start", "on_tool_result", "prior_messages",
    ]
```

How the pieces fit:
- `spy_bridge` shadows `execute_tool` on the instance (a plain attribute set, so `__getattr__`-delegating wrappers are unaffected) and still calls the real bound method with the same keywords.
- The benchmark chain is built as the explore arm builds it (`ExploreScaffoldBridge(RetrievalAugmentingBridge(SubprocessVmdBridge))`). `_resolve_vmd` is patched so no VMD binary is needed; `_start`, `_run_tcl` and `_snapshot` are stubbed on the instance. The explore bridge aliases `run_vmd_command` to `lab_try` and forwards `**kw`, so the innermost bridge must also receive exactly the six keywords.
- `test_explore_tools_for_turn_zero_arg_lambda` pins that `explore_agent.py:57-61` installs `_tools_for_turn` as a zero-argument instance attribute and that `_call` uses it on every turn (all three request bodies offer only the lab tools).

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_benchmark_bridge_guard.py -q`
Expected: `8 passed`. These tests pin today's behaviour, so they pass at once; Step 3 proves they fail when the loop changes.

- [ ] **Step 3: Prove the guard bites (temporary mutation, reverted)**

```bash
python - <<'PY'
from pathlib import Path
path = Path("runtime/vmd_ai_runtime/claude_loop.py")
text = path.read_text()
anchor = "                            cancel_event=cancel_event,\n"
assert text.count(anchor) == 1
path.write_text(text.replace(anchor, anchor + '                            call_key="mutant",\n'))
PY
python -m pytest tests/test_benchmark_bridge_guard.py -q 2>&1 | tail -3
git checkout -- runtime/vmd_ai_runtime/claude_loop.py
git diff --stat -- runtime/
```

Expected: `7 failed, 1 passed` (only the AST test passes). The failures read `TypeError: …execute_tool() got an unexpected keyword argument 'call_key'` (3.9 omits the class name) for all five strict bridges and the two chains. After `git checkout`, `git diff --stat -- runtime/` prints nothing (P01-T02's `_sleep` change is already committed).

- [ ] **Step 4: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `513 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_benchmark_bridge_guard.py
git commit -F - <<'MSG'
test(m0): bridge guard: execute_tool gets exactly six keywords (options=None)

Runs the loop against the five strict bridges and the benchmark's
Subprocess -> Retrieval -> ExploreScaffold chain, checks the explore arm's
zero-argument _tools_for_turn lambda, and AST-pins that the adapter never
passes ctx or options.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T07: Prompt, tool-schema and image-byte hash pins

**Files:**
- Create: `tests/fixtures/images/pin_8x6.tga`
- Test: `tests/test_benchmark_hashes.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - canonical_sha256(obj) -> str (json sort_keys, separators (',',':'))
  - tests/fixtures/images/pin_8x6.tga (8×6 uncompressed 24-bit)

The pinned values were computed from the code at 47539f3 and are identical under Python 3.9.6 (zlib 1.2.12) and 3.12.7 (zlib 1.2.13).

- [ ] **Step 1: Write the test**

Create `tests/test_benchmark_hashes.py`:

```python
"""S7 hash pins (spec §2a "Hashes", "Image bytes"; §2c "Thumbnails").

VMD_SYSTEM_PROMPT, WIKI_SYSTEM_PROMPT_ADDENDUM, the tool schemas and the PNG
bytes image_utils produces are frozen for the benchmark.  A failure here means
a benchmark-visible change: revert it, or put the new behaviour behind a
LoopOptions flag (spec §2a).  Never update these constants to make a test pass.
"""
from __future__ import annotations

import hashlib
import json
import zlib
from pathlib import Path
from typing import Any

import pytest

from vmd_ai_runtime import claude_loop, image_utils

FIXTURE_TGA = Path(__file__).resolve().parent / "fixtures" / "images" / "pin_8x6.tga"
FIXTURE_TGA_SHA256 = "595b1de25339c1c17f8a5acfbdc2dc89de528b080138295e24b3c6bb0e846fd3"
PNG_SHA256 = "bc2e97db09caa57c79d6908fd201836b06ae0c8ea1198a046dbcb717601e0f32"

PROMPT_HASHES = {
    "VMD_SYSTEM_PROMPT": "e6ae7af23836101f82b65c1bcf59f95874af062c7711b8e348b2e9324dafe252",
    "WIKI_SYSTEM_PROMPT_ADDENDUM": "4e17154cc2b74dfcaf5b22b648de1bf2843d1d1d3c819c4872ade177cb18ab63",
}
TOOL_CONSTANT_HASHES = {
    "SEARCH_DOCS_TOOL": "13ad90d9b0c7dfb5fc322f2fa3f41cff6cc2b00b3fb3c4156a60491377ce863d",
    "WIKI_LIST_TOOL": "c7e3c679bb64d9e8fed4106fca8f46e76e46efabbb4fa8170a50b64122b0f19e",
    "WIKI_READ_TOOL": "b8ec993c316b723d7e4912abe7eb62af276b179449ca7ac0dcfa6bb2d2cda9d4",
    "WIKI_UPDATE_TOOL": "0f65b26341194759e83da78ef4b79d65736de2ea51530c0461d185f6595cf094",
    "WIKI_VERIFY_TOOL": "4391a6537b3f263b63bb09de5cf592c0ef2107f47d5f12d9ccb8737b9cbbecbe",
}
VMD_TOOLS_HASH = "64f79dbc1aa851bbaaeb72ee26cefeb43578b8a1cf0c9561a8bc23adb8f19614"
VMD_TOOLS_FN_HASHES = {
    (False, False): "58593769d174dd7dc42a1940ed3696b371b7b1c15751c96c68b4680e670b6210",
    (False, True): "a6d5051ba3c542809537165ff180f048b8feddb525fca5cacd57466e570cafbe",
    (True, False): "64f79dbc1aa851bbaaeb72ee26cefeb43578b8a1cf0c9561a8bc23adb8f19614",
    (True, True): "f28a2ef6444876191d704b54f39c78559303d0a63d61ba768a8913da79c2cb32",
}


def canonical_sha256(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", sorted(PROMPT_HASHES))
def test_prompt_hashes(name):
    assert canonical_sha256(getattr(claude_loop, name)) == PROMPT_HASHES[name]


@pytest.mark.parametrize("name", sorted(TOOL_CONSTANT_HASHES))
def test_tool_constant_hashes(name):
    assert canonical_sha256(getattr(claude_loop, name)) == TOOL_CONSTANT_HASHES[name]


@pytest.mark.parametrize("include_search_docs,include_wiki", sorted(VMD_TOOLS_FN_HASHES))
def test_tool_schema_hashes(include_search_docs, include_wiki):
    tools = claude_loop._vmd_tools(include_search_docs=include_search_docs,
                                   include_wiki=include_wiki)
    assert canonical_sha256(tools) == VMD_TOOLS_FN_HASHES[(include_search_docs, include_wiki)]


def test_vmd_tools_constant_hash():
    assert canonical_sha256(claude_loop.VMD_TOOLS) == VMD_TOOLS_HASH


def test_max_turns_pinned():
    assert claude_loop.ClaudeToolLoop.MAX_TURNS == 28


def test_image_utils_png_bytes():
    assert hashlib.sha256(FIXTURE_TGA.read_bytes()).hexdigest() == FIXTURE_TGA_SHA256
    for convert in (image_utils.read_image_as_png_bytes, image_utils.tga_to_png_bytes):
        png = convert(str(FIXTURE_TGA))
        assert png is not None
        assert hashlib.sha256(png).hexdigest() == PNG_SHA256, (
            f"{convert.__name__} output changed (zlib {zlib.ZLIB_RUNTIME_VERSION})"
        )
```

`canonical_sha256` sorts keys, so the prompt and schema pins catch content changes; key order and separators of the actual request bodies are pinned byte-for-byte by the P01-T04/T05 goldens. `VMD_TOOLS` equals `_vmd_tools(True, False)`, hence the shared hash.

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_benchmark_hashes.py -q`
Expected: `1 failed, 13 passed`; `test_image_utils_png_bytes` fails with `FileNotFoundError: … tests/fixtures/images/pin_8x6.tga`.

- [ ] **Step 3: Create the fixture TGA**

```bash
mkdir -p tests/fixtures/images
python - <<'PY'
import struct
from pathlib import Path

WIDTH, HEIGHT = 8, 6
# 18-byte header: no id, no colour map, type 2 (uncompressed true colour),
# origin (0, 0), 8x6, 24 bpp, descriptor 0 (rows stored bottom-to-top).
header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, WIDTH, HEIGHT, 24, 0)
pixels = bytearray()
for y in range(HEIGHT):
    for x in range(WIDTH):
        blue = (x * 32) % 256
        green = (y * 40) % 256
        red = 200 if (x, y) == (0, 0) else (x * y * 5) % 256
        pixels += bytes((blue, green, red))  # TGA stores BGR
data = header + bytes(pixels)
Path("tests/fixtures/images/pin_8x6.tga").write_bytes(data)
print(len(data))
PY
shasum -a 256 tests/fixtures/images/pin_8x6.tga
```

Expected: `162`, then `595b1de25339c1c17f8a5acfbdc2dc89de528b080138295e24b3c6bb0e846fd3  tests/fixtures/images/pin_8x6.tga`.

The gradient plus one marked pixel make row order (bottom-to-top flip) and channel order (BGR→RGB) both matter to the PNG bytes. `read_image_as_png_bytes` takes the pure-stdlib TGA path for `.tga` files, so Pillow never affects this pin.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_benchmark_hashes.py -q`
Expected: `14 passed`.

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `527 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_benchmark_hashes.py tests/fixtures/images/pin_8x6.tga
git commit -F - <<'MSG'
test(m0): pin prompt, tool-schema and image_utils PNG hashes

VMD_SYSTEM_PROMPT, WIKI_SYSTEM_PROMPT_ADDENDUM, SEARCH_DOCS_TOOL, the
four WIKI_*_TOOL schemas, VMD_TOOLS, _vmd_tools for all four (d, w)
combinations, MAX_TURNS and the PNG bytes image_utils makes from a
fixture TGA are frozen for the benchmark.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T08: Runner provenance and benchmark-wiring test

**Files:**
- Create: `integrations/run_provenance.py`
- Modify: `integrations/scivisagentbench/run_atlas_parallel.sh:49-80` (the provenance block)
- Modify: `integrations/scivisagentbench/run_25cell_retrieval.sh:31` (after the server wait)
- Modify: `integrations/scivisagentbench/run_multistructure.py:262-263` (`main`)
- Modify: `integrations/scivisagentbench/run_heldout.py:138` (`main`)
- Modify: `integrations/explore_arm/run_explore.py:205-206` (`main`)
- Test: `tests/test_run_provenance.py`
- Test: `tests/test_benchmark_wiring.py`

**Interfaces:**
- Consumes: nothing from earlier tasks for the script; `tests/test_benchmark_wiring.py` uses `helpers.golden.import_adapter` (P01-T04)
- Produces:
  - integrations/run_provenance.append_run_manifest(manifest_path: str, repo: str, **fields: str) -> Dict[str, str]
  - CLI: python integrations/run_provenance.py <manifest> key=value ...
  - (also) `integrations/run_provenance.resolve_runtime_path(repo: str, config_path: str = "", configured: str = "") -> str`; every record starts with `ts`, `commit`, `describe`, then the caller's fields, then `vmd_ai_runtime_path`. The CLI exits 2 on a malformed `key=value`.

`vmd_ai_runtime_path` is resolved the way `vmd_ai_agent.setup()` resolves it: the `vmd_ai_runtime_path=` field if given, else the config file's `vmd_ai_runtime_path` (field `config=`), else `$VMD_AI_RUNTIME_PATH`, else `runtime`; a relative value is joined to the repo root, then `realpath`ed. Every runner appends to the tracked `integrations/scivisagentbench/run_manifest.jsonl` and names itself with `runner=`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_provenance.py`:

```python
"""integrations/run_provenance.py: one manifest line per benchmark run (spec §0)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "integrations" / "run_provenance.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_provenance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_append_fields(tmp_path):
    prov = _module()
    manifest = tmp_path / "run_manifest.jsonl"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"vmd_ai_runtime_path": "runtime"}))
    record = prov.append_run_manifest(str(manifest), str(REPO), run="r1", config=str(config))
    lines = manifest.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == record
    assert list(record)[:3] == ["ts", "commit", "describe"]
    assert record["commit"] == _git("rev-parse", "--short", "HEAD")
    assert record["describe"] == _git("describe", "--tags", "--always", "--dirty")
    assert record["vmd_ai_runtime_path"] == os.path.realpath(REPO / "runtime")
    assert record["run"] == "r1"
    assert len(record["ts"]) == 20 and record["ts"].endswith("Z")

    prov.append_run_manifest(str(manifest), str(tmp_path), run="r2",
                             vmd_ai_runtime_path="/abs/runtime")
    second = json.loads(manifest.read_text().splitlines()[1])
    assert second["commit"] == "nogit" and second["describe"] == "-"
    assert second["vmd_ai_runtime_path"] == os.path.realpath("/abs/runtime")


def test_cli_key_value(tmp_path):
    manifest = tmp_path / "m.jsonl"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(manifest), "run=cli", "model=Qwen/x", "arms=none rag"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    record = json.loads(manifest.read_text())
    assert (record["run"], record["model"], record["arms"]) == ("cli", "Qwen/x", "none rag")
    assert record["vmd_ai_runtime_path"] == os.path.realpath(REPO / "runtime")
    assert "== provenance ->" in proc.stdout

    bad = subprocess.run([sys.executable, str(SCRIPT), str(manifest), "no-equals-sign"],
                         capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2
    assert "expected key=value" in bad.stderr
    assert len(manifest.read_text().splitlines()) == 1


RUNNERS = (
    "integrations/scivisagentbench/run_atlas_parallel.sh",
    "integrations/scivisagentbench/run_25cell_retrieval.sh",
    "integrations/scivisagentbench/run_multistructure.py",
    "integrations/scivisagentbench/run_heldout.py",
    "integrations/explore_arm/run_explore.py",
)


def test_every_runner_appends_provenance():
    for rel in RUNNERS:
        path = REPO / rel
        text = path.read_text(encoding="utf-8")
        assert "run_provenance" in text and "runner=" in text, rel
        if rel.endswith(".sh"):
            check = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
            assert check.returncode == 0, check.stderr
        else:
            compile(text, rel, "exec")
```

Create `tests/test_benchmark_wiring.py`:

```python
"""Benchmark wiring (spec §0): repo-relative config paths resolve inside the checkout.

Every integrations/**/config_*.json key in REPO_RELATIVE_KEYS must be a
relative path that vmd_ai_agent._resolve_repo_path maps to an existing path
inside this checkout.  Machine-specific absolute keys (vmd_bin, wiki_root,
wiki_raw_root) are allowed on purpose; any other absolute path is one
machine's layout leaking into a shared config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from helpers.golden import import_adapter

REPO = Path(__file__).resolve().parents[1]
CONFIGS: List[Path] = sorted(REPO.glob("integrations/**/config_*.json"))
REPO_RELATIVE_KEYS = ("vmd_ai_runtime_path", "inject_reference_path")
MACHINE_ABSOLUTE_KEYS = ("vmd_bin", "wiki_root", "wiki_raw_root")


def wiring_problems(data: Dict[str, Any]) -> List[str]:
    adapter = import_adapter()
    problems: List[str] = []
    for key in REPO_RELATIVE_KEYS:
        if key not in data:
            continue
        value = str(data[key])
        if os.path.isabs(os.path.expanduser(value)):
            problems.append(f"{key}={value!r} is absolute; use a repo-relative path")
            continue
        resolved = Path(adapter._resolve_repo_path(value)).resolve()
        if not resolved.is_relative_to(REPO.resolve()):
            problems.append(f"{key}={value!r} resolves outside the checkout ({resolved})")
        elif not resolved.exists():
            problems.append(f"{key}={value!r} resolves to missing {resolved}")
    for key, value in data.items():
        if (isinstance(value, str) and value.startswith(("/", "~"))
                and key not in MACHINE_ABSOLUTE_KEYS and key not in REPO_RELATIVE_KEYS):
            problems.append(f"{key}={value!r} is a machine-specific absolute path")
    return problems


def test_adapter_resolves_against_this_checkout():
    assert Path(import_adapter()._REPO_ROOT) == REPO
    assert len(CONFIGS) >= 18


def test_wiring_rejects_bad_paths():
    assert wiring_problems({"vmd_ai_runtime_path": "/Users/someone/vmdai/runtime"}) == [
        "vmd_ai_runtime_path='/Users/someone/vmdai/runtime' is absolute; "
        "use a repo-relative path",
    ]
    assert wiring_problems({"inject_reference_path": "../elsewhere.md"})[0].startswith(
        "inject_reference_path='../elsewhere.md' resolves outside the checkout"
    )
    assert wiring_problems({"vmd_ai_runtime_path": "no_such_dir"})[0].startswith(
        "vmd_ai_runtime_path='no_such_dir' resolves to missing"
    )
    assert wiring_problems({"docs_index_dir": "/opt/index"}) == [
        "docs_index_dir='/opt/index' is a machine-specific absolute path",
    ]
    assert wiring_problems({"vmd_bin": "/Applications/VMD.app/Contents/vmd/vmd_MACOSXARM64",
                            "wiki_root": "/Users/x/.vmdai/wiki"}) == []


@pytest.mark.parametrize("config", CONFIGS, ids=[c.name for c in CONFIGS])
def test_repo_relative_paths_resolve_inside_checkout(config):
    data = json.loads(config.read_text(encoding="utf-8"))
    assert wiring_problems(data) == []
```

There are 18 configs today (17 under `integrations/scivisagentbench/`, 1 under `integrations/explore_arm/`), so the wiring file collects 20 tests. `test_wiring_rejects_bad_paths` is the negative control that shows the check can fail.

- [ ] **Step 2: Run them to verify the provenance tests fail**

Run: `python -m pytest tests/test_run_provenance.py tests/test_benchmark_wiring.py -q`
Expected: `3 failed, 20 passed`. `test_append_fields` fails with `FileNotFoundError` for `integrations/run_provenance.py`; `test_cli_key_value` fails on `assert proc.returncode == 0` (python: can't open file); `test_every_runner_appends_provenance` fails with `AssertionError: integrations/scivisagentbench/run_atlas_parallel.sh`. The wiring tests pass: today's configs are already repo-relative (commit 47539f3).

- [ ] **Step 3: Commit the wiring test on its own**

The wiring test pins the configs as 47539f3 left them and changes no code, so it is a separate reviewable commit from the provenance change. Leave `tests/test_run_provenance.py` uncommitted (it fails until Step 7).

```bash
git add tests/test_benchmark_wiring.py
git commit -F - <<'MSG'
test(m0): benchmark wiring: config paths resolve inside the checkout

test_benchmark_wiring checks that every integrations/**/config_*.json
repo-relative key (vmd_ai_runtime_path, inject_reference_path) resolves
inside this checkout, and that no other key carries a machine-specific
absolute path (vmd_bin, wiki_root, wiki_raw_root are allowed).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

- [ ] **Step 4: Create `integrations/run_provenance.py`**

```python
#!/usr/bin/env python3
"""run_provenance.py — append one provenance line per benchmark run.

Every runner (run_atlas_parallel.sh, run_25cell_retrieval.sh,
run_multistructure.py, run_heldout.py, explore_arm/run_explore.py) calls
this once per run, so each RUN in run_manifest.jsonl maps back to the code
that produced it (spec §0 "M0 repository tasks").

  python integrations/run_provenance.py <manifest.jsonl> key=value [key=value ...]

Always recorded: ts (UTC), commit, describe, vmd_ai_runtime_path (resolved the
way vmd_ai_agent.py resolves it: the config's value, else $VMD_AI_RUNTIME_PATH,
else "runtime", relative paths against the repo root).  Pass config=<path> to
read vmd_ai_runtime_path from a harness config.  Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(repo: str, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def resolve_runtime_path(repo: str, config_path: str = "", configured: str = "") -> str:
    value = configured
    if not value and config_path and os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as fh:
            value = str(json.load(fh).get("vmd_ai_runtime_path") or "")
    value = os.path.expanduser(value or os.environ.get("VMD_AI_RUNTIME_PATH") or "runtime")
    if not os.path.isabs(value):
        value = os.path.join(repo, value)
    return os.path.realpath(value)


def append_run_manifest(manifest_path: str, repo: str, **fields: str) -> Dict[str, str]:
    """Append one JSON line to ``manifest_path`` and return the record."""
    record: Dict[str, str] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git(repo, "rev-parse", "--short", "HEAD") or "nogit",
        "describe": _git(repo, "describe", "--tags", "--always", "--dirty") or "-",
    }
    record.update({key: str(value) for key, value in fields.items()})
    record["vmd_ai_runtime_path"] = resolve_runtime_path(
        repo, fields.get("config", ""), fields.get("vmd_ai_runtime_path", "")
    )
    parent = os.path.dirname(os.path.abspath(manifest_path))
    os.makedirs(parent, exist_ok=True)
    with open(manifest_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: run_provenance.py <manifest.jsonl> key=value ...", file=sys.stderr)
        return 2
    manifest, pairs = args[0], args[1:]
    fields: Dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            print(f"run_provenance.py: expected key=value, got {pair!r}", file=sys.stderr)
            return 2
        fields[key] = value
    record = append_run_manifest(manifest, REPO, **fields)
    print(f"== provenance -> {manifest}\n   {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable: `chmod +x integrations/run_provenance.py`.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_run_provenance.py -q`
Expected: `1 failed, 2 passed`; only `test_every_runner_appends_provenance` still fails (`run_atlas_parallel.sh`).

- [ ] **Step 6: Give the five runners the one-line append**

`integrations/scivisagentbench/run_atlas_parallel.sh` — replace lines 52-53

```bash
_sha=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo nogit)
_desc=$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo -)
```

with nothing (delete both lines; keep line 54, `_model=$(curl …)`, which the model-mismatch guard uses). Then replace the original lines 69-80 (lines 67-78 once those two lines are gone)

```bash
_tier=$([ -n "${HARD:-}" ] && echo hard || echo easy)
_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo -)
python3 - "$HARNESS/run_manifest.jsonl" "$_ts" "$RUN" "$_sha" "$_desc" "$_model" "$_tier" \
         "$(basename "$FIXDIR")" "$SEEDS" "${CONC:-1}" "${ARMS[*]}" <<'PY'
import sys, json
path = sys.argv[1]
rec = dict(zip(("ts","run","commit","describe","model","tier","fixtures","seeds","conc","arms"),
               sys.argv[2:12]))
with open(path, "a") as f:
    f.write(json.dumps(rec) + "\n")
print(f"== provenance -> {path}\n   {rec}")
PY
```

with

```bash
_tier=$([ -n "${HARD:-}" ] && echo hard || echo easy)
python3 "$REPO/integrations/run_provenance.py" "$HARNESS/run_manifest.jsonl" runner=run_atlas_parallel run="$RUN" model="$_model" tier="$_tier" fixtures="$(basename "$FIXDIR")" seeds="$SEEDS" conc="${CONC:-1}" arms="${ARMS[*]}" config="$HARNESS/config_arm_${ARMS[0]}.json"
```

The record keeps every old key (`ts`, `run`, `commit`, `describe`, `model`, `tier`, `fixtures`, `seeds`, `conc`, `arms`) and adds `runner`, `config` and `vmd_ai_runtime_path`.

`integrations/scivisagentbench/run_25cell_retrieval.sh` — after line 31 (`[ "$up" = "1" ] || { echo "server never came up …"; exit 1; }`) insert:

```bash

# ---- 1a. provenance: one line per run in the tracked manifest (spec §0) ----
python3 "$REPO/integrations/run_provenance.py" "$HARNESS/run_manifest.jsonl" runner=run_25cell_retrieval seeds="$SEEDS" arms="${ARMS[*]}" config="$HARNESS/config_arm_${ARMS[0]}.json"
```

`integrations/scivisagentbench/run_multistructure.py` — in `main()`, replace

```python
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run_arm(args)))
```

with

```python
    args = ap.parse_args()
    sys.path.insert(0, str(HERE.parent))  # integrations/ -> run_provenance
    from run_provenance import append_run_manifest
    append_run_manifest(str(HERE / "run_manifest.jsonl"), str(HERE.parent.parent), runner="run_multistructure", run=args.tag, config=args.config, seeds=str(args.seeds))
    raise SystemExit(asyncio.run(run_arm(args)))
```

`integrations/scivisagentbench/run_heldout.py` — in `main()`, replace

```python
    raise SystemExit(asyncio.run(run_arm(ap.parse_args())))
```

with

```python
    args = ap.parse_args()
    sys.path.insert(0, str(HERE.parent))  # integrations/ -> run_provenance
    from run_provenance import append_run_manifest
    append_run_manifest(str(HERE / "run_manifest.jsonl"), str(HERE.parent.parent), runner="run_heldout", run=args.tag, config=args.config, seeds=str(args.seeds))
    raise SystemExit(asyncio.run(run_arm(args)))
```

`integrations/explore_arm/run_explore.py` — in `main()`, replace

```python
    from run_atlas_traj import run_arm
    raise SystemExit(asyncio.run(run_arm(args)))
```

with

```python
    sys.path.insert(0, str(HERE.parent))  # integrations/ -> run_provenance
    from run_provenance import append_run_manifest
    append_run_manifest(str(SCIVIS / "run_manifest.jsonl"), str(SCIVIS.parent.parent), runner="run_explore", run=args.tag, config=args.config, model=str(cfg.get("model") or ""), seeds=str(args.seeds))
    from run_atlas_traj import run_arm
    raise SystemExit(asyncio.run(run_arm(args)))
```

(`cfg` is the prepared config loaded a few lines above for the served-model check; `args.config` is the prepared temp config, which carries the resolved runtime path.)

When `run_25cell_retrieval.sh` calls `run_multistructure.py` per arm, the manifest gets one `run_25cell_retrieval` line and one `run_multistructure` line per arm; `runner` tells them apart.

- [ ] **Step 7: Check syntax and run the tests**

```bash
bash -n integrations/scivisagentbench/run_atlas_parallel.sh
bash -n integrations/scivisagentbench/run_25cell_retrieval.sh
python -m py_compile integrations/run_provenance.py integrations/scivisagentbench/run_multistructure.py integrations/scivisagentbench/run_heldout.py integrations/explore_arm/run_explore.py
```

Expected: no output.

Run: `python -m pytest tests/test_run_provenance.py tests/test_benchmark_wiring.py -q`
Expected: `23 passed`.

- [ ] **Step 8: Run the suites**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `550 passed, 1 xfailed, 10 subtests passed`.

Run: `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`
Expected: `62 passed`.

- [ ] **Step 9: Commit**

```bash
git add integrations/run_provenance.py integrations/scivisagentbench/run_atlas_parallel.sh integrations/scivisagentbench/run_25cell_retrieval.sh integrations/scivisagentbench/run_multistructure.py integrations/scivisagentbench/run_heldout.py integrations/explore_arm/run_explore.py tests/test_run_provenance.py
git commit -F - <<'MSG'
feat(bench): one provenance line per run from every runner

integrations/run_provenance.py appends ts, commit, describe, the
resolved vmd_ai_runtime_path and the runner's fields to
run_manifest.jsonl; all five runners call it once per run.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T09: Python 3.9 import check

**Files:**
- Test: `tests/test_py39_compat.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - tests/test_py39_compat.py RUNTIME_MODULES: List[str] (later plans append to it)
  - (also) `test_runtime_module_list_is_complete` fails whenever a `runtime/vmd_ai_runtime/**/*.py` module is missing from `RUNTIME_MODULES`, so a later plan that adds a module must append it (P02-T02, P03-T01/T03/T05/T07, P04-T05/T06, P05-T04/T08 already list this file).

- [ ] **Step 1: Write the test**

Create `tests/test_py39_compat.py`:

```python
"""Python 3.9 compatibility (spec §6, §2d): the runtime imports and starts on 3.9.

``py_compile`` misses 3.10-only syntax that is evaluated at run time (for
example ``isinstance(x, int | None)``), so these tests import every runtime
module and run ``runtime/main.py --help`` under ``/usr/bin/python3`` when that
interpreter is 3.9 (the macOS system Python), and skip otherwise.  CI's 3.9
job covers the same ground on Linux by running the whole suite under 3.9.
Later plans append each new runtime module to RUNTIME_MODULES.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
PY39 = "/usr/bin/python3"

RUNTIME_MODULES: List[str] = [
    "vmd_ai_runtime",
    "vmd_ai_runtime.app",
    "vmd_ai_runtime.claude_loop",
    "vmd_ai_runtime.client",
    "vmd_ai_runtime.constants",
    "vmd_ai_runtime.docs_search",
    "vmd_ai_runtime.errors",
    "vmd_ai_runtime.events",
    "vmd_ai_runtime.image_utils",
    "vmd_ai_runtime.keys",
    "vmd_ai_runtime.logging_utils",
    "vmd_ai_runtime.protocol",
    "vmd_ai_runtime.provider",
    "vmd_ai_runtime.rag",
    "vmd_ai_runtime.rag.audit",
    "vmd_ai_runtime.rag.golden",
    "vmd_ai_runtime.rag.metrics",
    "vmd_ai_runtime.recorder",
    "vmd_ai_runtime.recorder.run",
    "vmd_ai_runtime.scripts",
    "vmd_ai_runtime.scripts.build_docs_index",
    "vmd_ai_runtime.server",
    "vmd_ai_runtime.sessions",
    "vmd_ai_runtime.store",
    "vmd_ai_runtime.tool_bridge",
    "vmd_ai_runtime.wiki_bench",
    "vmd_ai_runtime.wiki_store",
]


def _python39() -> Optional[str]:
    if not os.path.exists(PY39):
        return None
    try:
        proc = subprocess.run(
            [PY39, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return PY39 if proc.stdout.strip() == "3.9" else None


requires_py39 = pytest.mark.skipif(_python39() is None,
                                   reason=f"{PY39} is not Python 3.9")


def _import_on_39(path: Path, modules: List[str], cwd: Path) -> subprocess.CompletedProcess:
    code = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(path)!r})\n"
        f"names = {modules!r}\n"
        "for name in names:\n"
        "    importlib.import_module(name)\n"
        "print('imported', len(names))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run([PY39, "-c", code], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=120)


def test_runtime_module_list_is_complete():
    found = set()
    for path in (RUNTIME / "vmd_ai_runtime").rglob("*.py"):
        parts = list(path.relative_to(RUNTIME).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found.add(".".join(parts))
    assert sorted(found - set(RUNTIME_MODULES)) == []


@requires_py39
def test_runtime_modules_import_on_39(tmp_path):
    proc = _import_on_39(RUNTIME, RUNTIME_MODULES, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"imported {len(RUNTIME_MODULES)}"


@requires_py39
def test_import_check_catches_runtime_union(tmp_path):
    (tmp_path / "uses_union.py").write_text(
        "from __future__ import annotations\n"
        "OK = isinstance(1, int | None)\n"
    )
    proc = _import_on_39(tmp_path, ["uses_union"], tmp_path)
    assert proc.returncode != 0
    assert "unsupported operand type(s) for |" in proc.stderr


@requires_py39
def test_main_help_on_39(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run([PY39, str(RUNTIME / "main.py"), "--help"], cwd=str(tmp_path),
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("usage: main.py")
```

`test_import_check_catches_runtime_union` is the negative control for Review Focus 5: it shows the subprocess check fails on exactly the kind of expression `py_compile` accepts. The subprocesses run with the hermetic `HOME` and without `PYTHONPATH`, so no anaconda packages leak into 3.9.

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_py39_compat.py -q -rs`
Expected on the dev Mac: `4 passed` (today's runtime already imports and starts on 3.9.6). Where `/usr/bin/python3` is not 3.9 (CI, Linux): `1 passed, 3 skipped` with `SKIPPED … /usr/bin/python3 is not Python 3.9`.

- [ ] **Step 3: Prove the module-list check bites (temporary file, removed)**

```bash
touch runtime/vmd_ai_runtime/_m0_probe.py
python -m pytest tests/test_py39_compat.py::test_runtime_module_list_is_complete -q 2>&1 | grep -E "^E |failed"
rm runtime/vmd_ai_runtime/_m0_probe.py
git status --short runtime/
```

Expected: `E       AssertionError: assert ['vmd_ai_runtime._m0_probe'] == []` and `1 failed`; after `rm`, `git status --short runtime/` prints nothing.

- [ ] **Step 4: Run the suite**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `554 passed, 1 xfailed, 10 subtests passed`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_py39_compat.py
git commit -F - <<'MSG'
test(m0): runtime imports and main.py --help under /usr/bin/python3 3.9

A subprocess on the macOS system Python 3.9 imports every runtime module
and runs main.py --help (py_compile misses run-time `X | Y`). The module
list must cover every runtime/vmd_ai_runtime module; later plans append.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

---

### Task P01-T10: CI workflow and no-keychain test

**Files:**
- Create: `.github/workflows/tests.yml`
- Test: `tests/test_keys_no_backend.py`

**Interfaces:**
- Consumes: helpers.keyring_stub (P01-T01); helpers.fake_evaluation_framework (P01-T04)
- Produces:
  - .github/workflows/tests.yml: push/pull_request to main; matrix python ['3.9','3.12']; apt-get install tcl8.6; pip install pytest; python -m pytest tests -q

- [ ] **Step 1: Write the test**

Create `tests/test_keys_no_backend.py`:

```python
"""keys.py's "No keychain backend" branch (C9): no keyring module at all."""
from __future__ import annotations

import os
import sys


def test_save_reports_no_keychain_backend(monkeypatch, fake_keyring_store):
    from vmd_ai_runtime.keys import KeyStore, read_keyring_for_provider

    monkeypatch.setitem(sys.modules, "keyring", None)  # `import keyring` now fails
    store = KeyStore()
    result = store.save("openrouter", "sk-or-no-backend")
    assert (result.ok, result.source, result.message) == (
        False, "none", "No keychain backend available",
    )
    assert store.test("openrouter") == {
        "ok": False, "message": "No keychain backend available", "source": "none",
    }
    key, error = read_keyring_for_provider("openrouter")
    assert key == "" and error is not None and error.startswith("keychain read failed")
    assert fake_keyring_store == {}
    assert "OPENROUTER_API_KEY" not in os.environ
```

Setting `sys.modules["keyring"] = None` makes `import keyring` raise `ImportError` whether the conftest installed the stub (CI) or patched the real package (dev Mac); `monkeypatch` restores only that key. Do not use `mock.patch.dict(sys.modules)` (it drops every module imported inside the block).

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_keys_no_backend.py -q`
Expected: `1 passed`. This pins an existing branch of `keys.py` that no other test reaches.

- [ ] **Step 3: Create `.github/workflows/tests.yml`**

```yaml
# CI for the ChatVMD product suite (spec C9): proves tests/ is hermetic and that
# S7 (options=None benchmark behaviour) holds on a clean machine with no
# ~/.vmdai, VMD.app, keychain or tunnel.  vmdbench/ (needs VMD) and
# integrations/ (needs the gitignored SciVisAgentBench checkout) are excluded.
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  pytest:
    runs-on: ubuntu-latest
    env:
      # tclsh sources files in the system encoding; from plan 08 on, plugin Tcl
      # files and op goldens carry UTF-8 literals, so pin a UTF-8 locale.
      LANG: C.UTF-8
      LC_ALL: C.UTF-8
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.9", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install Tcl 8.6
        run: sudo apt-get update && sudo apt-get install -y tcl8.6
      - name: Install pytest (no keyring, no Pillow, so the stdlib paths run)
        run: python -m pip install pytest
      - name: Run tests/
        run: python -m pytest tests -q
```

- [ ] **Step 4: Validate the workflow file**

```bash
python - <<'PY'
import yaml
doc = yaml.safe_load(open(".github/workflows/tests.yml"))
job = doc["jobs"]["pytest"]
print(sorted(doc[True]), job["runs-on"], job["strategy"]["matrix"]["python-version"])
print([step["run"] for step in job["steps"] if "run" in step])
PY
```

Expected (PyYAML reads the `on:` key as `True`):

```text
['pull_request', 'push'] ubuntu-latest ['3.9', '3.12']
['sudo apt-get update && sudo apt-get install -y tcl8.6', 'python -m pip install pytest', 'python -m pytest tests -q']
```

- [ ] **Step 5: Rehearse the CI 3.9 job locally**

```bash
VENV="${TMPDIR:-/tmp}/vmdai-ci39"
/usr/bin/python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q pytest
env -u VMD_AI_PROVIDER "$VENV/bin/python" -m pytest tests -q
rm -rf "$VENV"
```

Expected: `555 passed, 1 xfailed` (pytest 8.4 on 3.9 prints no subtests count). This venv has neither keyring nor Pillow, so the stub-keyring and stdlib image paths run, as in CI.

- [ ] **Step 6: Run the three suites**

Run: `env -u VMD_AI_PROVIDER python -m pytest tests -q`
Expected: `555 passed, 1 xfailed, 10 subtests passed` in about 9 s.

Run: `python -m pytest vmdbench/tests -q`
Expected: `90 passed`.

Run: `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`
Expected: `62 passed`.

- [ ] **Step 7: Commit**

```bash
git add tests/test_keys_no_backend.py .github/workflows/tests.yml
git commit -F - <<'MSG'
ci: run tests/ on ubuntu-latest with Python 3.9 and 3.12

Installs tcl8.6 from apt and only pytest from pip, so the keyring stub,
the fake evaluation_framework and the stdlib image paths run on a clean
machine. Adds the one test of keys.py's "No keychain backend" branch.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
MSG
```

- [ ] **Step 8: Get CI green (needs the owner's go-ahead to push)**

The workflow triggers on pushes to `main` and on pull requests to `main`, so a feature-branch push alone does not run it. With the owner's approval:

```bash
git push -u origin chatvmd-r1-01-m0-guard-rails
git push origin baseline-2026-09-24
gh pr create --draft --base main --head chatvmd-r1-01-m0-guard-rails --title "ChatVMD R1 plan 01: M0 guard rails and CI" --body "M0 guard rails: hermetic tests/, S7 pins (goldens, retry pin, bridge guard, hashes), Tcl harness, runner provenance, CI on 3.9 and 3.12. Plan: docs/superpowers/plans/2026-09-24-chatvmd-r1-01-m0-guard-rails.md"
gh pr checks --watch
```

Expected: both `pytest (3.9)` and `pytest (3.12)` pass. In each job log the summary is `550 passed, 5 skipped, 1 xfailed` (the 3.12 job, on pytest ≥ 9, also prints `10 subtests passed`): `test_http_295_loads` and `test_json_112_loads` skip (no VMD.app), and the three `/usr/bin/python3`-3.9 checks skip (Ubuntu's system Python is not 3.9). If `tcltest` is missing from Ubuntu's Tcl, `test_run_tcltest_counts` also skips with `tcltest 2 is not available in /usr/bin/tclsh8.6`. If `setup-python` cannot provide 3.9 on `ubuntu-latest`, or any test fails only in CI, stop and report to the owner rather than changing the matrix or skipping tests.

---

## M0 exit checklist

| Exit criterion | Evidence |
|---|---|
| Suite green in under 60 s, `test_unreachable_host_raises_with_hint` is `xfail(strict=True)` | P01-T02 Step 8 onwards; P01-T10 Step 6: `555 passed, 1 xfailed` in about 9 s |
| S7: golden requests | P01-T04/T05: 13 goldens with fixed SHA-256 |
| S7: retry pin | P01-T02: `tests/test_benchmark_retry_pin.py` |
| S7: bridge guard (`options=None`) | P01-T06: `tests/test_benchmark_bridge_guard.py`, mutation check |
| S7: prompt and tool-schema hashes, image bytes | P01-T07: `tests/test_benchmark_hashes.py` |
| S9 (hermetic, under 60 s) | P01-T01 hermetic tests; owner-shell child run |
| C9: CI green on ubuntu-latest with 3.9 and 3.12 | P01-T10 Step 8 |
| §0: tag `baseline-2026-09-24`, runner provenance, `test_benchmark_wiring.py` | P01-T01 Step 1, P01-T08 |
| Tcl harness with VMD's http 2.9.5 | P01-T03: `test_http_295_loads` |
| `runtime/` unchanged except `_sleep` | P01-T02 Step 7 (`git diff baseline-2026-09-24 -- runtime/`) |

## Deviations from skeleton

1. **Extra tests beyond the skeleton's lists** (each small, each pins something the spec requires):
   - `test_hermetic_env.py::test_live_env_probe` — the child-run target of `test_live_env_captured_before_clearing`; it also runs in the normal suite (checks the gates are cleared).
   - `test_tcl_harness.py::test_no_bare_tclsh_in_tests` — enforces C9's "one helper decides skips".
   - `test_benchmark_hashes.py::test_tool_constant_hashes` (the spec pins `SEARCH_DOCS_TOOL` and the four `WIKI_*_TOOL` schemas; the skeleton's test names did not cover them) and `::test_max_turns_pinned` (global constraint "MAX_TURNS stays 28").
   - `test_benchmark_wiring.py::test_adapter_resolves_against_this_checkout` and `::test_wiring_rejects_bad_paths` (negative control).
   - `test_run_provenance.py::test_every_runner_appends_provenance` — the only automated check that all five runners were edited.
   - `test_py39_compat.py::test_runtime_module_list_is_complete` (makes "later plans append to it" enforceable) and `::test_import_check_catches_runtime_union` (negative control for Review Focus 5).
2. **Retry pin is parametrized over all three providers** and driven through `ClaudeToolLoop.run` with `options=None`, not through `_stream_request` alone, so the pin still holds after P02-T06 changes `_stream_request`'s signature. Test ids are `test_urlerror_retries_five_times[anthropic-direct]` etc.
3. **Goldens are captured on the plan branch after P01-T02**, not literally "at 47539f3". `runtime/` and `integrations/` then differ from `baseline-2026-09-24` only by the `_sleep` indirection (checked in P01-T04 Step 6), and 6f5f937 changed only docs. Their SHA-256 values are fixed in this plan, and they are byte-identical under Python 3.9 and 3.12.
4. **`RecordingUrlopen` records `headers` as a key-sorted dict of `Request.header_items()`**; urllib capitalises names (`Content-type`, `X-api-key`, `Anthropic-version`, `Http-referer`), and the goldens store them that way.
5. **Additional public names in the helpers** (additive, used by later tasks or plans): `helpers.golden.PROVIDER_CONFIGS`, `COMMON_CONFIG`, `TASK_PROMPT`, `RESCUE_PROMPT`, `TINY_PNG_B64`, `DEFAULT_RESULTS`, `RESCUE_RESULTS`, `UPDATE_ENV`, `RecordingUrlopen.unconsumed`, `import_adapter()` (used by the wiring test), `ARMS` and `StubDocsSearch` (P01-T05); `helpers.tcl.tcl_word` and path/version constants; `helpers.fake_evaluation_framework.FAKE_MARKER`, `get_agent`; the conftest's `HermeticState` and `sleep_calls` on it.
6. **`run_guard` gains an optional keyword** `requests_out` and maps `loop.provider_name` to the scripted provider, so P02-T08 can reuse it with any provider whose product preset does not add preflight requests (`anthropic-direct` or `openrouter`, which P02-T08 uses; not `ollama`, whose product preset sends `/api/version` and `/api/ps` before each `/api/chat`). The bridge-guard names live in the test module and are imported by module name.
7. **`helpers.tcl.run_tcltest` also skips when the interpreter has no `tcltest` 2** (possible on a minimal Linux Tcl). The spec's skip rules cover only a missing 8.6 interpreter, http and json; a missing `tcltest` must also skip, never error.
8. **`helpers.tcl` reads `helpers.live.LIVE_ENV` directly**, not through the `live_env` fixture, because it runs at collection time (skip marks) before fixtures exist. It is the same snapshot object the fixture returns, and nothing reads the gates from `os.environ`.
9. **`integrations/run_provenance.py` adds `resolve_runtime_path(...)` and a `runner=` field**, and replaces `run_atlas_parallel.sh`'s inline Python heredoc (its `_sha`, `_desc` and `_ts` variables go away). The manifest line keeps every old key; key order changes (`ts`, `commit`, `describe` first).
10. **`test_keys_no_backend` sets `sys.modules["keyring"] = None` via `monkeypatch.setitem`** instead of only removing the stub: on the dev Mac the real keyring is installed and would import again after a plain removal.
11. **CI verification goes through a draft PR** (P01-T10 Step 8), because the specified triggers (push and pull_request to `main`) do not fire on a feature-branch push. Pushing the tag, the branch and opening the PR are gated on the owner's approval.
12. **The keyring stub is installed by a single-key `sys.modules["keyring"]` swap, not `patch.dict(sys.modules)`** as C9 words it. `patch.dict` restores by clearing and refilling the whole of `sys.modules`, which drops every module first imported during the test; the swap (restored by the fixture's `ExitStack`) has the same effect on `import keyring` without that side effect.
13. **`test_benchmark_retry_pin.py::test_http_retry_after_other_combinations`** (6 cases) adds the two cells the skeleton's names leave out — 429 *with* Retry-After and 503 *without* — because §2a pins "429 and 503, with and without Retry-After". Every expected `tests/` total from P01-T02 on includes these 6 cases.
14. **P01-T08 makes two commits**: the wiring test (a pure pin of 47539f3's configs, no code change) is committed on its own in Step 3, before the provenance script and runner edits, so each can be reviewed and reverted separately. The task id and scope are unchanged.
15. **CI locale (added by the cross-plan completeness pass).** The workflow pins `LANG`/`LC_ALL` to `C.UTF-8` at the job level. tclsh `source`s files in the system encoding, and from plan 08 on the plugin Tcl files, the view-model tests and the op goldens carry UTF-8 literals (`·`, `—`, `…`, `✓`); ubuntu-latest already defaults to `C.UTF-8`, so this only makes that default explicit. Step 4's validation output is unchanged.
