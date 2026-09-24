# VMD AI (`vmd_ai`)

Claude-powered AI assistant for VMD (Visual Molecular Dynamics). Drives live molecular
visualization through an agentic tool-calling loop: Claude issues Tcl commands directly
into VMD, captures viewport screenshots to verify results, and iterates until the task
is complete — all from a natural-language prompt in the Tcl/Tk panel.

## Security model

Read this before installing.

VMD AI lets the model drive a real VMD session by sending **Tcl commands**
that are evaluated at the global scope of your running VMD interpreter.
Tcl is not sandboxed: it includes `exec` (run shell commands), `file
delete`, `open` (file/pipe IO), `socket`, and the ability to redefine any
existing proc. The agent therefore has, in effect, **shell-equivalent
access** to your machine while the plugin is loaded.

Operational guidance:

- Treat the assistant like a trusted shell user. If you wouldn't let a
  collaborator run arbitrary commands in your terminal, don't run VMD AI.
- Don't load datasets containing secrets, credentials, or material from
  untrusted sources while the plugin is active — prompt-injection in
  loaded files (e.g. PDB REMARK lines, trajectory metadata) can steer the
  model into running commands you didn't ask for.
- API keys are kept in your OS keychain; the runtime listens only on
  127.0.0.1 and authenticates each RPC with a per-session token, so the
  network surface is small. The remaining trust boundary is the Tcl tool
  call itself.
- A locked-down Tcl `safe interpreter` mode is on the roadmap. Until
  it lands, the warning above applies.

## Architecture

```
User → Tcl/Tk panel (plugin/)
         ↓  JSON-RPC  (HTTP 127.0.0.1)
       Python runtime (runtime/)
         ↓  ClaudeToolLoop
       Anthropic / OpenRouter API
         ↓  tool_use blocks
       VmdToolBridge  →  tool_start EventQueue event
         ↓  poll_once picks it up
       Tcl bridge  →  eval VMD command  →  render snapshot
         ↓  tool.command_result RPC
       VmdToolBridge.resolve()  →  ClaudeToolLoop continues
```

- Tcl/Tk plugin shell (`plugin/`)
- External Python JSON-RPC runtime (`runtime/`)
- Protocol documentation (`docs/`)
- Unit/integration tests (`tests/`)
- Local developer scripts (`scripts/`)

## Feature Matrix

| Capability | Status |
|---|---|
| Tcl/Tk chat panel in VMD | Included |
| OpenRouter model access (claude-sonnet-4.6 default) | Included |
| Direct Anthropic API | Included |
| Agentic tool loop — Claude drives tool calls | **Included** |
| `run_vmd_command` tool (real VMD Tcl execution) | **Included** |
| `capture_vmd_snapshot` tool (TGA→PNG, vision feedback) | **Included** |
| Persistent chat history under `~/.vmdai/chats/` | Included |
| Per-task reproducible runs under `<workdir>/.vmdai_runs/` | **Included** |
| Local-provider support via Ollama (full agentic) | **Included** |
| OS keychain for API keys | Optional (`keyring`) |
| Better image conversion | Optional (`Pillow`) |
| Mock mode (no API key needed) | Included |

## JSON-RPC Methods

- `session.start` / `session.stop`
- `chat.send` / `chat.cancel` / `chat.events.poll` / `chat.history.list`
- `settings.get` / `settings.set`
- `keys.save` / `keys.test`
- `tool.command_result` ← **posted by Tcl bridge after VMD execution**

## Reproducible runs

Every successful `chat.send` deposits an on-disk artifact under
`<workdir>/.vmdai_runs/<task_id>/` so any session can be replayed,
shared, or pasted into a methods section:

```
<workdir>/.vmdai_runs/<timestamp>-<hash>_<slug>/
├── manifest.json     — prompt, model, status, turn / success / fail counts
├── transcript.tcl    — annotated, REPLAYABLE Tcl (only successful commands)
└── snapshots/
    └── turn_NN.png   — decoded images from capture_vmd_snapshot
```

The transcript is real Tcl. To reproduce the session in a fresh VMD:

```bash
vmd -e <workdir>/.vmdai_runs/<task_id>/transcript.tcl
vmd -dispdev text -e <task>/transcript.tcl    # headless replay
```

Only commands that returned `ok=true` are written to `transcript.tcl`; failed
attempts are counted in the manifest but never persist to the replayable
artifact, so re-running always works.

The Tk panel surfaces this dir: the header shows `(N runs)` next to the
folder path, and the **Runs…** button opens the directory in your file
manager.

**Where the runs end up:**

| `state.cwd` (from `session.start` / panel Choose…) | runs land at |
|---|---|
| a real directory | `<that dir>/.vmdai_runs/` |
| empty / unset | `~/.vmdai/runs/` (fallback so no data is lost) |

Opt out with `VMD_AI_RECORDER=off` if you don't want disk artifacts.

## Quick Start

### 1) Run runtime standalone

```bash
cd vmd_ai
./scripts/run_runtime.sh
```

### 2) Load plugin in VMD

In VMD Tcl console:

```tcl
source /absolute/path/to/PyMolAI/vmd_ai/plugin/init.tcl
::vmdai::start
```

Then use `Extensions -> VMD AI` (if VMD extension registration is available).

### 3) Verify handshake and events

- Type `hi` in the VMD AI panel and press Send.
- You should see user message + streamed mock assistant chunks.
- Press Stop mid-stream to trigger cancel lifecycle event.

## Wire Claude (OpenRouter)

The runtime can use Claude models through OpenRouter.

1. Set your key in the shell that launches VMD:

```bash
export OPENROUTER_API_KEY="your_openrouter_key"
```

2. Force provider mode (optional, but explicit):

```bash
export VMD_AI_PROVIDER="openrouter"
```

3. Start VMD from that same shell and load plugin:

```tcl
source /absolute/path/to/PyMolAI/vmd_ai/plugin/init.tcl
::vmdai::start
```

Notes:
- Default model is `anthropic/claude-sonnet-4.6`.
- If no key is present, runtime falls back to mock mode.

## Wire Claude (Direct Anthropic API)

Use this path when you want runtime calls to go directly to Anthropic:

```bash
export ANTHROPIC_API_KEY="your_anthropic_api_key"
export VMD_AI_PROVIDER="anthropic-direct"
# optional override
export ANTHROPIC_MODEL="claude-sonnet-4-5"
```

Then start VMD from the same shell and load:

```tcl
source /absolute/path/to/PyMolAI/vmd_ai/plugin/init.tcl
::vmdai::start
```

Provider selection behavior:
- `VMD_AI_PROVIDER=anthropic-direct` -> direct Anthropic API.
- `VMD_AI_PROVIDER=openrouter` -> OpenRouter.
- no provider set:
1. OpenRouter if `OPENROUTER_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set.
2. otherwise Anthropic direct if `ANTHROPIC_API_KEY` is set.
3. otherwise mock provider.

## Development Scripts

- `scripts/run_runtime.sh`: launch runtime server.
- `scripts/print_env_checks.sh`: print Python/runtime health and port checks.
- `scripts/dev_smoke.sh`: automated local handshake/send/poll smoke.

## Test

Run from repo root:

```bash
.venv/bin/python -m unittest discover -s vmd_ai/tests -p 'test_*.py' -v
```

## Notes

- Key save/test uses OS keychain via `keyring` when available.
- File fallback for keys is intentionally disabled in this skeleton.
- Tool execution is intentionally stubbed in this phase.
