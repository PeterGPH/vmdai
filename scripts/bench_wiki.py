#!/usr/bin/env python3
"""
bench_wiki.py — run the wiki A/B benchmark against a real LLM provider.

The deterministic tests in tests/test_wiki_ab.py prove the wiring is
correct. This script answers the quality question: when a real LLM is
in the loop, does the wiki actually help?

Usage:
    # From the repo root, with an OPENROUTER_API_KEY (or ANTHROPIC_API_KEY)
    # exported in your environment:
    python scripts/bench_wiki.py \\
        --prompts evals/wiki_bench_prompts.json \\
        --raw-root ~/.vmdai/raw \\
        --out bench-out/

Outputs report.json + report.md in --out.

What the script does:
  1. Loads a prompts JSON file ({"prompts": [...] }).
  2. Builds two ClaudeToolLoop instances — one with WikiStore, one without —
     sharing the same provider + model so the LLM variable is held fixed.
  3. For each prompt, runs ONE turn against each arm using a stub
     VmdToolBridge that returns success for VMD tool calls (we're
     measuring agent behavior, not VMD execution).
  4. Records tool calls + final text into TrialResult, derives wiki
     metrics, writes report.json + report.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from anywhere — make the runtime package importable.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "runtime"))

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    ClaudeToolLoop, VMD_SYSTEM_PROMPT, build_claude_loop,
)
from vmd_ai_runtime.events import EventQueue  # noqa: E402
from vmd_ai_runtime.wiki_bench import (  # noqa: E402
    BenchReport, ToolCallRecord, TrialResult, run_bench, write_report,
)
from vmd_ai_runtime.wiki_store import WikiStore  # noqa: E402


# ---------------------------------------------------------------------------
# Stub VMD tool bridge — agent thinks it's running commands; we lie.
# ---------------------------------------------------------------------------

class StubToolBridge:
    """Pretends every VMD command and snapshot succeeded.

    The bench is about agent *reasoning* with vs. without the wiki —
    actually running VMD would conflate provider quality with VMD's
    rendering pipeline and add minutes of latency. The stub returns
    plausible success payloads so the agent loop keeps progressing.
    """
    def get_pending_session(self, tool_call_id: str) -> Optional[str]:
        return None

    def execute_tool(
        self, *, session_id, tool_call_id, tool_name, tool_input,
        session_queue, cancel_event, timeout=30,
    ) -> Dict[str, Any]:
        if tool_name == "capture_vmd_snapshot":
            return {
                "ok": True,
                "output": "[stub] snapshot OK",
                "error": "",
                # No image — the bench doesn't need vision feedback.
            }
        # run_vmd_command and anything else: ack success.
        return {
            "ok": True,
            "output": f"[stub] {tool_name} OK",
            "error": "",
        }


# ---------------------------------------------------------------------------
# Real-LLM trial function
# ---------------------------------------------------------------------------

def make_live_trial_fn(
    provider_name: str,
    api_key: str,
    model: str,
    timeout: int,
) -> Any:
    """Return a trial_fn that runs ONE turn against the real provider.

    Uses ``ClaudeToolLoop`` directly. The Loop's ``run`` callback signature
    is rich — we wire dummy callbacks that just capture what we need:
    tool starts (for tool_calls), final text (for final_answer).
    """
    def trial_fn(prompt: str, wiki_store: Optional[WikiStore]) -> TrialResult:
        loop = ClaudeToolLoop(
            provider_name=provider_name,
            api_key=api_key,
            model=model,
            timeout=timeout,
            wiki_store=wiki_store,
        )
        tool_calls: List[ToolCallRecord] = []
        # Sources surfaced through wiki_read results — distinct from
        # sources cited via wiki_update.input. Both count as citations
        # for the bench, but they come through different channels.
        read_sources: List[str] = []
        # In-flight tool tracking so we can compute durations.
        tool_t0_by_id: Dict[str, float] = {}

        def on_tool_start(name: str, tool_input: Dict[str, Any]) -> None:
            # The loop doesn't pass us a tool_id here — keep the record
            # simple and pair start/result by order of appearance.
            tool_calls.append(ToolCallRecord(
                name=name, input=dict(tool_input or {}),
                ok=False, duration_ms=0.0,
            ))
            tool_t0_by_id[name + str(len(tool_calls))] = time.perf_counter()

        def on_tool_result(tool_id: str, tool_name: str, result: Dict[str, Any]) -> None:
            # Find the most recent unresolved record matching the name.
            for rec in reversed(tool_calls):
                if rec.name == tool_name and rec.duration_ms == 0.0:
                    rec.ok = bool(result.get("ok"))
                    rec.error = str(result.get("error") or "")
                    rec.output_preview = str(result.get("output") or "")[:200]
                    # Approximate duration; the loop measures it precisely
                    # but doesn't pass it here. Good enough for A/B.
                    key = tool_name + str(tool_calls.index(rec) + 1)
                    t0 = tool_t0_by_id.get(key, time.perf_counter())
                    rec.duration_ms = (time.perf_counter() - t0) * 1000.0
                    # Pull pinned sources out of wiki_read results so
                    # citation_rate reflects "read-and-cite" turns, not
                    # only "filed-a-new-page" turns. Without this, a
                    # well-behaved agent that READS the wiki but never
                    # writes scores 0% — undercounting the wiki's value.
                    if tool_name == "wiki_read" and bool(result.get("ok")):
                        for pin in result.get("pins") or []:
                            if isinstance(pin, dict):
                                p = pin.get("path")
                                if p and p not in read_sources:
                                    read_sources.append(str(p))
                    return

        # Stub bridge + dummy session queue for the agent loop's plumbing.
        bridge = StubToolBridge()
        queue = EventQueue()
        cancel_event = threading.Event()
        chunks: List[str] = []

        t0 = time.perf_counter()
        error_msg = ""
        try:
            final_text = loop.run(
                prompt=prompt,
                system_prompt=VMD_SYSTEM_PROMPT,
                tool_bridge=bridge,
                session_id="bench",
                session_queue=queue,
                cancel_event=cancel_event,
                on_chunk=lambda c: chunks.append(c),
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
            )
        except Exception as exc:  # noqa: BLE001
            final_text = ""
            error_msg = f"{type(exc).__name__}: {exc}"
        duration_ms = (time.perf_counter() - t0) * 1000.0

        return TrialResult(
            prompt=prompt,
            arm="",
            final_answer=final_text or "".join(chunks),
            tool_calls=tool_calls,
            duration_ms=duration_ms,
            error=error_msg,
            # Seed sources_cited with wiki_read pins. _derive_wiki_metrics
            # will add wiki_update.input.sources on top — both channels
            # contribute to the final citation_rate.
            sources_cited=read_sources,
        )

    return trial_fn


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    p.add_argument(
        "--prompts", required=True,
        help="JSON file with {\"prompts\": [\"...\", \"...\"]}.",
    )
    p.add_argument(
        "--out", default="bench-out",
        help="Directory to write report.json + report.md (default: bench-out/).",
    )
    p.add_argument(
        "--provider", default=None,
        help="Override provider: openrouter | anthropic-direct | ollama. "
             "Defaults to whatever env vars are set.",
    )
    p.add_argument("--model", default=None, help="Override model string.")
    p.add_argument(
        "--raw-root", default=os.path.expanduser("~/.vmdai/raw"),
        help="Directory containing raw sources for wiki pinning.",
    )
    p.add_argument(
        "--wiki-root", default=None,
        help="Wiki directory. Default: a fresh tmp dir per run.",
    )
    p.add_argument(
        "--timeout", type=int, default=120,
        help="Per-turn LLM timeout in seconds.",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    prompts_path = Path(args.prompts).expanduser().resolve()
    if not prompts_path.exists():
        print(f"error: prompts file not found: {prompts_path}", file=sys.stderr)
        return 2
    prompts_data = json.loads(prompts_path.read_text(encoding="utf-8"))
    prompts: List[str] = list(prompts_data.get("prompts") or [])
    if not prompts:
        print("error: prompts JSON has no 'prompts' array", file=sys.stderr)
        return 2

    # Resolve provider + key + model from env unless overridden.
    provider = (args.provider or os.getenv("VMD_AI_PROVIDER") or "openrouter").lower()
    if provider in ("openrouter", "claude", "claude-openrouter"):
        from vmd_ai_runtime.provider import resolve_openrouter_api_key
        api_key, _src = resolve_openrouter_api_key()
        default_model = "anthropic/claude-sonnet-4.6"
    elif provider in ("anthropic-direct", "anthropic_api"):
        from vmd_ai_runtime.provider import resolve_anthropic_api_key
        api_key, _src = resolve_anthropic_api_key()
        default_model = "claude-sonnet-4-5"
    elif provider in ("ollama", "local-ollama"):
        from vmd_ai_runtime.provider import resolve_ollama_host, resolve_ollama_model
        api_key, _src = resolve_ollama_host()
        ollama_model, _ms = resolve_ollama_model()
        default_model = ollama_model or "llama3.1:8b"
    else:
        print(f"error: unknown provider {provider!r}", file=sys.stderr)
        return 2
    if not api_key:
        print(f"error: no credentials for provider={provider}. "
              "Set OPENROUTER_API_KEY / ANTHROPIC_API_KEY / OLLAMA_HOST.",
              file=sys.stderr)
        return 2
    model = args.model or default_model

    # Wiki + raw roots. Use a tmp wiki by default so successive bench
    # runs aren't contaminated by accumulated state — set --wiki-root to
    # share a persistent wiki across runs.
    raw_root = Path(args.raw_root).expanduser().resolve()
    if not raw_root.exists():
        print(f"warning: raw root does not exist: {raw_root}. "
              "Source pinning will fail in the wiki arm.", file=sys.stderr)

    if args.wiki_root:
        wiki_root = Path(args.wiki_root).expanduser().resolve()
        tmp_holder = None
    else:
        tmp_holder = tempfile.TemporaryDirectory(prefix="vmdai-bench-wiki-")
        wiki_root = Path(tmp_holder.name)

    try:
        wiki = WikiStore(wiki_root, raw_root=raw_root)
        wiki.bootstrap()

        trial_fn = make_live_trial_fn(
            provider_name=provider,
            api_key=api_key,
            model=model,
            timeout=args.timeout,
        )

        config = {
            "provider": provider,
            "model": model,
            "wiki_root": str(wiki_root),
            "raw_root": str(raw_root),
        }
        print(f"Running {len(prompts)} prompts × 2 arms = "
              f"{len(prompts) * 2} trials against {provider}/{model}...")
        report = run_bench(
            prompts=prompts,
            trial_fn=trial_fn,
            with_wiki_store=wiki,
            config=config,
        )

        out_dir = Path(args.out).expanduser().resolve()
        json_path, md_path = write_report(report, out_dir)
        print(f"wrote {json_path}")
        print(f"wrote {md_path}")
        # Headline numbers to stdout so CI logs are useful.
        with_arm = report.summaries["with_wiki"]
        without_arm = report.summaries["without_wiki"]
        print()
        print("== headline ==")
        print(f"  citation rate      with={with_arm.citation_rate:.2%}  "
              f"without={without_arm.citation_rate:.2%}")
        print(f"  pages filed        with={with_arm.pages_filed:<3}  "
              f"without={without_arm.pages_filed}")
        print(f"  avg duration (ms)  with={with_arm.avg_duration_ms:.0f}  "
              f"without={without_arm.avg_duration_ms:.0f}")
        return 0
    finally:
        if tmp_holder is not None:
            tmp_holder.cleanup()


if __name__ == "__main__":
    sys.exit(main())
