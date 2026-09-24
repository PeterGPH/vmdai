#!/usr/bin/env python3
"""
rag_ab.py — workflow-level A/B test for VMD AI's RAG integration.

Runs the same prompt through ClaudeToolLoop twice — once with the
``docs_search`` tool wired in, once without — and reports what the
agent actually emits as VMD Tcl. This is the test that reveals
whether RAG meaningfully changes downstream behavior, not just
retrieval scores.

Usage:

    # uses whatever provider env vars are already set (Claude, Ollama, …)
    python -m vmd_ai_runtime.scripts.rag_ab "your prompt here"

    # explicit provider + model
    VMD_AI_PROVIDER=ollama VMD_AI_OLLAMA_MODEL=llama3.1 \\
        python -m vmd_ai_runtime.scripts.rag_ab \\
        "present CDK2 in academic style focused on ATP binding"

    # save full transcripts as JSON for further analysis
    python -m vmd_ai_runtime.scripts.rag_ab "..." --json out.json

How the A/B works:
    1. Two ClaudeToolLoop instances are built. Both see the same
       run_vmd_command + capture_vmd_snapshot tools. Only the RAG arm
       additionally sees search_docs (and a wired DocsSearch instance).
    2. VmdToolBridge is stubbed: every tool call is recorded and
       answered with a canned success. NO real VMD is required.
       The harness measures what the model WOULD ask VMD to do, not
       whether VMD does it correctly.
    3. After both runs, a side-by-side report is printed: every Tcl
       command emitted, every search_docs query, turn counts, latency.

Caveats:
    * Results depend on the real provider and model — re-running can
      vary turn-to-turn for non-deterministic providers. Run with
      temperature=0 if you need reproducibility.
    * The control arm has no way to recover from bad assumptions
       (since it can't search); the RAG arm can. That asymmetry is
       the whole point.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Make this script runnable both as a module and as a plain file.
# Layout: <repo>/vmd_ai/scripts/rag_ab.py → runtime is at parents[1]/runtime.
HERE = Path(__file__).resolve()
RUNTIME_DIR = HERE.parents[1] / "runtime"
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeToolLoop,
    VMD_SYSTEM_PROMPT,
    build_claude_loop,
)
from vmd_ai_runtime.docs_search import DocsSearch  # noqa: E402


# ----------------------------------------------------------------------
# Stub bridge — captures tool calls, returns canned success
# ----------------------------------------------------------------------

class _StubBridge:
    """Drop-in for VmdToolBridge. Records every tool call; never blocks.

    Each execute_tool returns ``{ok: True, output: <fake>, error: ""}``
    so the agent's loop can proceed past the call as if VMD had
    succeeded. This lets us observe what Tcl the model emits across
    a multi-turn agentic session without spinning up VMD.
    """

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def execute_tool(
        self,
        *,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        session_queue,
        cancel_event,
    ) -> Dict[str, Any]:
        self.calls.append({
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_call_id": tool_call_id,
        })
        # Canned outputs per tool. Keep them short — the agent re-reads
        # them as tool_result text in the next turn.
        if tool_name == "run_vmd_command":
            return {
                "ok": True,
                "output": "[stubbed: command accepted]",
                "error": "",
            }
        if tool_name == "capture_vmd_snapshot":
            return {
                "ok": True,
                "output": "[stubbed: snapshot captured]",
                "error": "",
                # No image_b64 — the model treats this as a text-only result.
            }
        return {"ok": True, "output": "[stubbed: tool ok]", "error": ""}


# ----------------------------------------------------------------------
# Arm result
# ----------------------------------------------------------------------

@dataclass
class ArmResult:
    name: str
    final_text: str = ""
    chunks: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: Optional[str] = None

    def vmd_commands(self) -> List[str]:
        return [
            c["tool_input"].get("command", "")
            for c in self.tool_calls
            if c["tool_name"] == "run_vmd_command"
        ]

    def search_queries(self) -> List[str]:
        return [
            c["tool_input"].get("query", "")
            for c in self.tool_calls
            if c["tool_name"] == "search_docs"
        ]

    def snapshots(self) -> int:
        return sum(1 for c in self.tool_calls
                   if c["tool_name"] == "capture_vmd_snapshot")

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "summary": {
                "vmd_command_count": len(self.vmd_commands()),
                "search_query_count": len(self.search_queries()),
                "snapshot_count": self.snapshots(),
                "total_tool_calls": len(self.tool_calls),
                "final_text_chars": len(self.final_text),
            },
        }


# ----------------------------------------------------------------------
# Run one arm
# ----------------------------------------------------------------------

def _run_arm(
    name: str,
    prompt: str,
    *,
    provider_mode: str,
    enable_rag: bool,
    docs_index_dir: Optional[str],
    system_prompt: str,
) -> ArmResult:
    res = ArmResult(name=name)

    # Build a docs_search if and only if this arm wants RAG.
    docs_search: Optional[DocsSearch] = None
    if enable_rag:
        docs_search = DocsSearch(index_dir=docs_index_dir)
        if not docs_search.is_available:
            res.error = (
                "RAG arm: docs_search.is_available=False — index missing "
                "or empty. Run `vmd-ai-index --rebuild` first."
            )
            return res

    loop = build_claude_loop(provider_mode, docs_search=docs_search)
    if loop is None:
        res.error = (
            f"No ClaudeToolLoop available for provider={provider_mode!r}. "
            f"Set the right env vars (OPENROUTER_API_KEY / "
            f"ANTHROPIC_API_KEY / VMD_AI_OLLAMA_MODEL)."
        )
        return res

    bridge = _StubBridge()
    cancel_event = threading.Event()

    def _on_chunk(text: str) -> None:
        res.chunks.append(text)

    # search_docs doesn't pass through the bridge — capture it from the
    # ClaudeToolLoop's internal _dispatch_search_docs by monkeypatching
    # for the duration of this arm. (We don't synthesize from
    # on_tool_result to avoid double-counting search_docs.)
    original_dispatch = loop._dispatch_search_docs

    def _instrumented_dispatch(tool_input: Dict) -> Dict:
        bridge.calls.append({
            "tool_name": "search_docs",
            "tool_input": dict(tool_input),
            "tool_call_id": f"sd_{len(bridge.calls)}",
        })
        return original_dispatch(tool_input)

    loop._dispatch_search_docs = _instrumented_dispatch

    t0 = time.perf_counter()
    try:
        final = loop.run(
            prompt=prompt,
            system_prompt=system_prompt,
            tool_bridge=bridge,
            session_id="rag_ab",
            session_queue=None,   # bridge is stubbed, so unused
            cancel_event=cancel_event,
            on_chunk=_on_chunk,
        )
        res.final_text = final
    except Exception as exc:  # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        res.elapsed_s = time.perf_counter() - t0
        loop._dispatch_search_docs = original_dispatch
        res.tool_calls = bridge.calls

    return res


# ----------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------

def _trunc(s: str, n: int = 200) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n - 1] + "…"


def render_report(
    prompt: str,
    control: ArmResult,
    rag: ArmResult,
) -> str:
    lines: List[str] = []
    bar = "─" * 72
    lines.append(bar)
    lines.append("VMD AI · workflow A/B (with-RAG vs without-RAG)")
    lines.append(bar)
    lines.append(f"prompt: {_trunc(prompt, 200)}")
    lines.append("")
    for arm in (control, rag):
        lines.append(f"[{arm.name}]")
        if arm.error:
            lines.append(f"  ERROR: {arm.error}")
            lines.append("")
            continue
        lines.append(f"  elapsed         : {arm.elapsed_s:.2f}s")
        lines.append(f"  total tool calls: {len(arm.tool_calls)}")
        lines.append(f"  run_vmd_command : {len(arm.vmd_commands())}")
        lines.append(f"  search_docs     : {len(arm.search_queries())}")
        lines.append(f"  capture_snapshot: {arm.snapshots()}")
        lines.append(f"  final reply chars: {len(arm.final_text)}")
        lines.append("")

    lines.append(bar)
    lines.append("VMD commands emitted")
    lines.append(bar)

    def _dump_commands(arm: ArmResult) -> None:
        lines.append(f"\n--- {arm.name} ---")
        cmds = arm.vmd_commands()
        if not cmds:
            lines.append("  (no run_vmd_command calls)")
            return
        for i, c in enumerate(cmds, 1):
            head = c.split("\n", 1)[0]
            extra = c.count("\n")
            tag = f"  [{i:02d}] {_trunc(head, 110)}"
            if extra:
                tag += f"  (+{extra} more lines)"
            lines.append(tag)

    _dump_commands(control)
    _dump_commands(rag)

    if rag.search_queries():
        lines.append("")
        lines.append(bar)
        lines.append("search_docs queries (RAG arm only)")
        lines.append(bar)
        for i, q in enumerate(rag.search_queries(), 1):
            lines.append(f"  [{i:02d}] {_trunc(q, 120)}")

    lines.append("")
    lines.append(bar)
    lines.append("Final assistant reply")
    lines.append(bar)
    lines.append(f"\n[{control.name}]")
    lines.append(_trunc(control.final_text, 600))
    lines.append(f"\n[{rag.name}]")
    lines.append(_trunc(rag.final_text, 600))
    return "\n".join(lines)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _resolve_provider_mode(arg_mode: Optional[str]) -> str:
    """Pick provider the same way RuntimeApp does — env-first, then keys."""
    if arg_mode:
        return arg_mode.lower()
    env = os.getenv("VMD_AI_PROVIDER")
    if env:
        return env.lower()
    from vmd_ai_runtime.provider import (
        resolve_openrouter_api_key,
        resolve_anthropic_api_key,
        resolve_ollama_model,
    )
    if resolve_openrouter_api_key()[0]:
        return "openrouter"
    if resolve_anthropic_api_key()[0]:
        return "anthropic-direct"
    if resolve_ollama_model()[0]:
        return "ollama"
    return "mock"


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rag_ab",
        description="Workflow-level RAG A/B: same prompt, with and without docs_search.",
    )
    p.add_argument("prompt", help="The user prompt to test.")
    p.add_argument("--provider", default=None,
                   help="Provider mode (overrides VMD_AI_PROVIDER). "
                        "openrouter | anthropic-direct | ollama | mock")
    p.add_argument("--docs-index", default=None,
                   help="Override docs index dir (default ~/.vmdai/docs_index)")
    p.add_argument("--system-prompt", default=None,
                   help="Override system prompt (default VMD_SYSTEM_PROMPT)")
    p.add_argument("--json", default=None,
                   help="Path to write full result as JSON")
    p.add_argument("--sleep", type=float, default=None,
                   help="Seconds to wait between the control and RAG arms "
                        "to dodge per-minute rate limits. Default: 60 for "
                        "cloud providers (anthropic-direct / openrouter), "
                        "0 for ollama / mock. Pass --sleep 0 to disable.")
    return p


def _default_sleep_for(provider_mode: str) -> float:
    """Cloud providers throttle per-minute; local ones don't."""
    if provider_mode in ("anthropic-direct", "anthropic_api",
                         "anthropic-direct-api",
                         "openrouter", "claude", "claude-openrouter"):
        return 60.0
    return 0.0


def _sleep_with_countdown(seconds: float) -> None:
    """Sleep ``seconds`` total, printing a single-line countdown every 5s.

    Stdout-friendly so users see we're waiting on purpose, not hung.
    """
    if seconds <= 0:
        return
    print(f"[rag_ab] cooling down {seconds:.0f}s between arms "
          f"(use --sleep 0 to skip) …", flush=True)
    remaining = float(seconds)
    tick = min(5.0, remaining)
    while remaining > 0:
        time.sleep(min(tick, remaining))
        remaining -= tick
        if remaining > 0:
            print(f"  …{int(remaining)}s left", flush=True)


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    provider_mode = _resolve_provider_mode(args.provider)
    sys_prompt = args.system_prompt or VMD_SYSTEM_PROMPT

    # Smart default for the inter-arm cool-down: 60s for cloud providers
    # whose rate limits are per-minute, 0 for local providers.
    sleep_secs = args.sleep
    if sleep_secs is None:
        sleep_secs = _default_sleep_for(provider_mode)

    print(f"[rag_ab] provider={provider_mode}  inter-arm sleep={sleep_secs:.0f}s")
    print(f"[rag_ab] running CONTROL arm (no RAG) …")
    control = _run_arm(
        "control (no RAG)",
        args.prompt,
        provider_mode=provider_mode,
        enable_rag=False,
        docs_index_dir=args.docs_index,
        system_prompt=sys_prompt,
    )

    _sleep_with_countdown(sleep_secs)

    print(f"[rag_ab] running RAG arm (search_docs available) …")
    rag = _run_arm(
        "rag (search_docs available)",
        args.prompt,
        provider_mode=provider_mode,
        enable_rag=True,
        docs_index_dir=args.docs_index,
        system_prompt=sys_prompt,
    )

    print("")
    print(render_report(args.prompt, control, rag))

    if args.json:
        payload = {
            "prompt": args.prompt,
            "provider_mode": provider_mode,
            "control": control.to_dict(),
            "rag": rag.to_dict(),
        }
        Path(args.json).write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\n[rag_ab] wrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
