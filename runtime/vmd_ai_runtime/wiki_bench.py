"""
wiki_bench.py — A/B harness for the LLM Wiki feature.

Question being answered: "Does the wiki actually help?"

The harness runs a fixed set of prompts against two configurations of the
same agent (wiki ON vs wiki OFF), records what each one did, and produces
a structured side-by-side report.

What we measure per trial:
  * tools called (which, in what order, success rate)
  * wiki-specific signals: pages read, pages written, sources cited
  * end-to-end duration
  * final answer text + did it cite anything

What the report compares between arms:
  * tool-call counts and distributions
  * citation rate (answers that mention pinned sources)
  * average duration
  * pages filed (wiki arm only) — knowledge accumulation rate

Design notes
------------
* The harness is **agent-agnostic**: it asks for a ``trial_fn(prompt,
  wiki_store) -> TrialResult`` callable. Unit tests pass a deterministic
  fake that scripts tool calls; the CLI bench passes a real
  ClaudeToolLoop runner. The harness itself never talks to an LLM.
* No threading. Each trial is sequential and self-contained, which
  keeps the report reproducible.
* Reports are JSON-first; rendering markdown is a one-pass formatter
  over the same data so report files round-trip cleanly.
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .wiki_store import WikiStore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ToolCallRecord:
    """One tool call observed during a trial."""
    name: str
    input: Dict[str, Any]
    ok: bool
    duration_ms: float
    output_preview: str = ""   # first ~200 chars of output, for forensics
    error: str = ""


@dataclass
class TrialResult:
    """Outcome of running one prompt against one configuration."""
    prompt: str
    arm: str                    # "with_wiki" | "without_wiki"
    final_answer: str
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str = ""
    # Wiki-specific derived metrics — filled in by the harness, not by
    # the trial function, so trial functions can stay simple.
    pages_read: List[str] = field(default_factory=list)
    pages_updated: List[str] = field(default_factory=list)
    sources_cited: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class ArmSummary:
    """Aggregate stats for one arm of the experiment."""
    arm: str
    n_trials: int
    n_errors: int
    avg_duration_ms: float
    median_duration_ms: float
    avg_tool_calls: float
    tool_call_distribution: Dict[str, int]
    citation_rate: float          # fraction of trials whose answer mentions any source
    pages_filed: int              # unique pages created/updated across trials
    distinct_sources_cited: int


@dataclass
class BenchReport:
    """Side-by-side comparison + per-trial detail."""
    trials: List[TrialResult]
    summaries: Dict[str, ArmSummary]    # arm -> summary
    prompts: List[str]
    config: Dict[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return {
            "config": self.config,
            "prompts": self.prompts,
            "summaries": {k: asdict(v) for k, v in self.summaries.items()},
            "trials": [t.to_json() for t in self.trials],
        }

    def to_markdown(self) -> str:
        lines: List[str] = []
        lines.append("# Wiki A/B Benchmark Report")
        lines.append("")
        lines.append(f"Prompts: {len(self.prompts)}")
        lines.append(f"Config: `{json.dumps(self.config, sort_keys=True)}`")
        lines.append("")

        # Side-by-side summary table.
        lines.append("## Summary")
        lines.append("")
        arms = sorted(self.summaries.keys())
        header = ["metric"] + arms
        rows: List[List[str]] = []

        def push(label: str, fn: Callable[[ArmSummary], Any]) -> None:
            rows.append([label] + [str(fn(self.summaries[a])) for a in arms])

        push("trials", lambda s: s.n_trials)
        push("errors", lambda s: s.n_errors)
        push("avg duration (ms)", lambda s: f"{s.avg_duration_ms:.1f}")
        push("median duration (ms)", lambda s: f"{s.median_duration_ms:.1f}")
        push("avg tool calls", lambda s: f"{s.avg_tool_calls:.2f}")
        push("citation rate", lambda s: f"{s.citation_rate:.2%}")
        push("pages filed", lambda s: s.pages_filed)
        push("distinct sources cited", lambda s: s.distinct_sources_cited)

        # Markdown table.
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Tool call distribution.
        lines.append("## Tool call distribution")
        lines.append("")
        all_tools = sorted({
            name
            for arm in arms
            for name in self.summaries[arm].tool_call_distribution
        })
        if all_tools:
            tool_header = ["tool"] + arms
            lines.append("| " + " | ".join(tool_header) + " |")
            lines.append("| " + " | ".join("---" for _ in tool_header) + " |")
            for tool in all_tools:
                row = [tool] + [
                    str(self.summaries[a].tool_call_distribution.get(tool, 0))
                    for a in arms
                ]
                lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        # Per-trial detail.
        lines.append("## Per-trial detail")
        for i, prompt in enumerate(self.prompts):
            lines.append("")
            lines.append(f"### Trial {i + 1}: {prompt}")
            for arm in arms:
                t = next(
                    (t for t in self.trials if t.prompt == prompt and t.arm == arm),
                    None,
                )
                if t is None:
                    lines.append(f"- **{arm}**: (no trial)")
                    continue
                lines.append(
                    f"- **{arm}**: {len(t.tool_calls)} tool calls, "
                    f"{t.duration_ms:.1f}ms, cited {len(t.sources_cited)} sources"
                )
                if t.error:
                    lines.append(f"  - error: `{t.error}`")
                if t.pages_read:
                    lines.append(f"  - read: {', '.join(t.pages_read)}")
                if t.pages_updated:
                    lines.append(f"  - wrote: {', '.join(t.pages_updated)}")
                if t.sources_cited:
                    lines.append(f"  - sources: {', '.join(t.sources_cited)}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

TrialFn = Callable[[str, Optional[WikiStore]], TrialResult]
"""Signature a trial runner must satisfy.

The harness calls ``trial_fn(prompt, wiki_store)`` once per (prompt, arm).
``wiki_store`` is None for the without-wiki arm, a real WikiStore for the
with-wiki arm. The trial returns a TrialResult populated with at least
``prompt``, ``arm``, ``final_answer``, ``tool_calls``, and ``duration_ms``.
The harness derives wiki-specific metrics from the tool_calls.
"""


def run_bench(
    *,
    prompts: List[str],
    trial_fn: TrialFn,
    with_wiki_store: WikiStore,
    config: Optional[Dict[str, Any]] = None,
) -> BenchReport:
    """Run every prompt against both arms and produce a BenchReport.

    The with-wiki arm receives ``with_wiki_store``; the without-wiki arm
    receives ``None``. We intentionally use the *same* WikiStore across
    trials so the with-wiki arm sees knowledge accumulate — that's the
    central claim of the wiki pattern. If you want each trial isolated,
    bootstrap a fresh store yourself and call ``run_bench`` per prompt.
    """
    config = dict(config or {})
    trials: List[TrialResult] = []
    for prompt in prompts:
        with_t = trial_fn(prompt, with_wiki_store)
        with_t.arm = "with_wiki"
        with_t.prompt = prompt
        _derive_wiki_metrics(with_t)
        trials.append(with_t)

        without_t = trial_fn(prompt, None)
        without_t.arm = "without_wiki"
        without_t.prompt = prompt
        _derive_wiki_metrics(without_t)
        trials.append(without_t)

    summaries = {
        "with_wiki": _summarize("with_wiki", trials),
        "without_wiki": _summarize("without_wiki", trials),
    }
    return BenchReport(
        trials=trials,
        summaries=summaries,
        prompts=list(prompts),
        config=config,
    )


def _derive_wiki_metrics(trial: TrialResult) -> None:
    """Walk tool_calls and fill in wiki-specific derived fields."""
    read_pages: List[str] = []
    updated_pages: List[str] = []
    sources: List[str] = []
    for call in trial.tool_calls:
        if call.name == "wiki_read" and call.ok:
            page = str(call.input.get("page") or "")
            if page:
                read_pages.append(page)
        elif call.name == "wiki_update" and call.ok:
            page = str(call.input.get("page") or "")
            if page:
                updated_pages.append(page)
            for src in call.input.get("sources") or []:
                sources.append(str(src))
    # The agent may also cite sources implicitly via wiki_read output —
    # that's harder to attribute mechanically, but we record any source
    # that appears in the final answer text as a soft signal.
    for src in sources:
        if src and src not in trial.sources_cited:
            trial.sources_cited.append(src)
    trial.pages_read = read_pages
    trial.pages_updated = updated_pages


def _summarize(arm: str, all_trials: List[TrialResult]) -> ArmSummary:
    trials = [t for t in all_trials if t.arm == arm]
    n = len(trials)
    if n == 0:
        return ArmSummary(
            arm=arm, n_trials=0, n_errors=0,
            avg_duration_ms=0.0, median_duration_ms=0.0,
            avg_tool_calls=0.0, tool_call_distribution={},
            citation_rate=0.0, pages_filed=0, distinct_sources_cited=0,
        )
    durations = [t.duration_ms for t in trials]
    tool_counts = [len(t.tool_calls) for t in trials]

    dist: Dict[str, int] = {}
    for t in trials:
        for call in t.tool_calls:
            dist[call.name] = dist.get(call.name, 0) + 1

    cited = sum(1 for t in trials if t.sources_cited)
    pages_filed = len({p for t in trials for p in t.pages_updated})
    distinct_sources = len({s for t in trials for s in t.sources_cited})
    errors = sum(1 for t in trials if t.error)

    return ArmSummary(
        arm=arm,
        n_trials=n,
        n_errors=errors,
        avg_duration_ms=statistics.mean(durations),
        median_duration_ms=statistics.median(durations),
        avg_tool_calls=statistics.mean(tool_counts),
        tool_call_distribution=dist,
        citation_rate=cited / n,
        pages_filed=pages_filed,
        distinct_sources_cited=distinct_sources,
    )


# ---------------------------------------------------------------------------
# Scripted trial runner (for deterministic tests + offline experimentation)
# ---------------------------------------------------------------------------

@dataclass
class ScriptedStep:
    """One scripted tool call in a deterministic agent script."""
    tool: str
    input: Dict[str, Any]


def make_scripted_trial_fn(
    script: List[ScriptedStep],
    final_answer_template: str = "Answer (no sources)",
) -> TrialFn:
    """Build a trial_fn that replays ``script`` against the wiki tools.

    This is the engine the deterministic A/B tests use. It calls the
    same dispatcher methods the real agent loop would call, recording
    each result. When ``wiki_store`` is None, wiki_* calls return the
    same "not configured" errors a real agent would see — that's the
    whole point of the A/B.

    ``final_answer_template`` may reference ``{sources}`` to be
    interpolated with a comma-joined list of cited sources, so the
    citation_rate metric reflects scripted citing behavior.
    """
    from .claude_loop import ClaudeToolLoop

    def trial_fn(prompt: str, wiki_store: Optional[WikiStore]) -> TrialResult:
        # A stripped-down ClaudeToolLoop just for its dispatch methods.
        loop = ClaudeToolLoop(
            provider_name="openrouter",
            api_key="stub",
            model="stub-model",
            wiki_store=wiki_store,
        )
        t0 = time.perf_counter()
        records: List[ToolCallRecord] = []
        cited_sources: List[str] = []
        for step in script:
            call_t0 = time.perf_counter()
            if step.tool == "wiki_list":
                result = loop._dispatch_wiki_list(step.input)
            elif step.tool == "wiki_read":
                result = loop._dispatch_wiki_read(step.input)
            elif step.tool == "wiki_update":
                result = loop._dispatch_wiki_update(step.input)
            elif step.tool == "wiki_verify_pins":
                result = loop._dispatch_wiki_verify_pins(step.input)
            elif step.tool == "search_docs":
                result = loop._dispatch_search_docs(step.input)
            else:
                # Unknown / external tool — record as an unsupported call
                # so the bench still reflects what the agent tried.
                result = {
                    "ok": False, "output": "",
                    "error": f"tool '{step.tool}' not handled by scripted runner",
                }
            call_ms = (time.perf_counter() - call_t0) * 1000.0
            records.append(ToolCallRecord(
                name=step.tool,
                input=step.input,
                ok=bool(result.get("ok")),
                duration_ms=call_ms,
                output_preview=str(result.get("output") or "")[:200],
                error=str(result.get("error") or ""),
            ))
            # Track sources surfaced through wiki_read.
            for pin in result.get("pins", []) or []:
                p = pin.get("path") if isinstance(pin, dict) else None
                if p and p not in cited_sources:
                    cited_sources.append(p)

        duration = (time.perf_counter() - t0) * 1000.0
        answer = final_answer_template.format(
            sources=", ".join(cited_sources) or "(none)",
        )
        return TrialResult(
            prompt=prompt,
            arm="",  # filled in by run_bench
            final_answer=answer,
            tool_calls=records,
            duration_ms=duration,
            sources_cited=cited_sources,
        )

    return trial_fn


# ---------------------------------------------------------------------------
# Report I/O
# ---------------------------------------------------------------------------

def write_report(report: BenchReport, out_dir: Path) -> Tuple[Path, Path]:
    """Write the report as both JSON (machine-readable) and Markdown."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "report.json"
    md_path = out_dir / "report.md"
    json_path.write_text(
        json.dumps(report.to_json(), indent=2, default=str),
        encoding="utf-8",
    )
    md_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, md_path
