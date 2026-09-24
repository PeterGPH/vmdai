#!/usr/bin/env python3
"""
rag_wiki_ab.py — 2×2 factorial harness over {RAG on/off} × {Wiki on/off}.

Why this exists
---------------
`rag_ab*.py` measures BM25 RAG alone (control vs search_docs). `bench_wiki.py`
measures the LLM-maintained wiki alone (without_wiki vs with_wiki). They use
*different prompt sets* and *different rubrics*, so their numbers do not
compare. This harness runs the SAME prompt set under all four configurations
and scores each one with BOTH rubrics, so the contribution of each retrieval
mechanism can be read off side-by-side along with the interaction term.

Arms
----
    none  : no docs_search, no wiki_store     (baseline)
    rag   : docs_search only
    wiki  : wiki_store only
    both  : docs_search + wiki_store

Within an arm a single WikiStore is shared across prompts so knowledge can
accumulate (mirroring `bench_wiki.run_bench`). Across arms the stores are
independent — the `wiki` arm cannot benefit from pages filed in `both`.

Outputs
-------
    <out-dir>/
        <prompt_id>.<arm>.json   per (prompt, arm) raw trial
        scorecard.csv            wide row per (prompt, arm)
        summary.json             arm means + deltas vs baseline + interaction

Usage
-----
    python scripts/rag_wiki_ab.py \\
        --provider openrouter \\
        --raw-root ~/.vmdai/raw \\
        --out-dir rag_wiki_results/

    # Quick subset
    python scripts/rag_wiki_ab.py --arms none,wiki --only pore,publication

Cost warning
------------
6 prompts × 4 arms = 24 LLM trials. With cloud cooldowns this takes ~30 min
and burns real tokens. Start with `--only <id>` and `--arms none,wiki`
before scaling up.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- path setup so this runs both as `python scripts/rag_wiki_ab.py` and
#     `python -m vmd_ai.scripts.rag_wiki_ab` from the repo root. -------------
HERE = Path(__file__).resolve()
SCRIPTS_DIR = HERE.parent
RUNTIME_DIR = HERE.parents[1] / "runtime"
for _p in (SCRIPTS_DIR, RUNTIME_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rag_ab  # noqa: E402  — reuse _StubBridge + provider resolver
import rag_ab_batch  # noqa: E402  — reuse IDIOM_PATTERNS

from vmd_ai_runtime.claude_loop import (  # noqa: E402
    VMD_SYSTEM_PROMPT,
    build_claude_loop,
)
from vmd_ai_runtime.docs_search import DocsSearch  # noqa: E402
from vmd_ai_runtime.events import EventQueue  # noqa: E402
from vmd_ai_runtime.wiki_store import WikiStore  # noqa: E402


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------

ARMS = ("none", "rag", "wiki", "both")
ARM_HAS_RAG = {"none": False, "rag": True, "wiki": False, "both": True}
ARM_HAS_WIKI = {"none": False, "rag": False, "wiki": True, "both": True}


# ---------------------------------------------------------------------------
# Prompt suite
# ---------------------------------------------------------------------------
# We reuse the wiki_bench prompts as the shared evaluation set because they
# ask broad "how do I…" questions that exercise BOTH retrieval mechanisms.
# Each entry carries `expects` — the idiom categories from
# rag_ab_batch.IDIOM_PATTERNS that a correct Tcl answer SHOULD use. Picked
# conservatively: a hit means the idiom appears, not that the surrounding
# script is fully correct.

@dataclass
class PromptSpec:
    id: str
    prompt: str
    expects: List[str]


DEFAULT_SUITE: List[PromptSpec] = [
    PromptSpec(
        id="pore_hydrophobicity",
        prompt=(
            "I have a membrane protein loaded. How do I select just the "
            "pore-lining residues and color them by hydrophobicity?"
        ),
        expects=["licorice", "color_resname", "within_select"],
    ),
    PromptSpec(
        id="publication_figure",
        prompt=(
            "Walk me through making a publication-quality cartoon-plus-"
            "licorice figure for a protein-ligand complex."
        ),
        expects=[
            "newcartoon", "licorice", "color_structure", "aochalky",
            "orthographic", "ao_on", "tachyon", "white_bg",
        ],
    ),
    PromptSpec(
        id="newcartoon_vs_tube",
        prompt=(
            "What's the difference between NewCartoon and Tube "
            "representations, and when should I use each?"
        ),
        expects=["newcartoon", "color_structure"],
    ),
    PromptSpec(
        id="rmsd_loop",
        prompt=(
            "I want to compute the per-frame RMSD of a binding-site loop "
            "relative to frame 0. Give me the Tcl."
        ),
        expects=["within_select"],   # the canonical idiom is `atomselect`
                                     # over `within ... of`; idiom set is
                                     # sparse here on purpose.
    ),
    PromptSpec(
        id="transparent_surface",
        prompt=(
            "Set up a transparent surface representation that shows the "
            "underlying cartoon clearly. What materials work best?"
        ),
        expects=["newcartoon", "surf", "transparent", "ghost"],
    ),
    PromptSpec(
        id="movie_export",
        prompt=(
            "How do I make a movie of a trajectory with a ligand "
            "highlighted, and export it as MP4?"
        ),
        expects=["newcartoon", "licorice", "rotate", "tachyon",
                 "movie_loop"],
    ),
]


# ---------------------------------------------------------------------------
# Trial result
# ---------------------------------------------------------------------------

@dataclass
class TrialResult:
    prompt_id: str
    prompt: str
    arm: str                                # none | rag | wiki | both
    final_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    sources_cited: List[str] = field(default_factory=list)
    pages_updated: List[str] = field(default_factory=list)
    pages_read: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: Optional[str] = None

    def vmd_tcl(self) -> str:
        out = []
        for c in self.tool_calls:
            if c["tool_name"] == "run_vmd_command":
                cmd = (c.get("tool_input") or {}).get("command", "")
                if cmd:
                    out.append(str(cmd))
        return "\n".join(out)

    def count(self, tool: str) -> int:
        return sum(1 for c in self.tool_calls if c["tool_name"] == tool)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Run one (prompt, arm) trial
# ---------------------------------------------------------------------------

def _run_trial(
    spec: PromptSpec,
    arm: str,
    *,
    provider_mode: str,
    system_prompt: str,
    docs_index_dir: Optional[str],
    wiki_store: Optional[WikiStore],
    timeout: int,
) -> TrialResult:
    res = TrialResult(prompt_id=spec.id, prompt=spec.prompt, arm=arm)

    # Wire docs_search only for RAG-enabled arms. The wiki_store is passed
    # in by the caller — already None for wiki-disabled arms.
    docs_search: Optional[DocsSearch] = None
    if ARM_HAS_RAG[arm]:
        docs_search = DocsSearch(index_dir=docs_index_dir)
        if not docs_search.is_available:
            res.error = (
                "RAG arm: docs_search.is_available=False — index missing "
                "or empty. Run `vmd-ai-index --rebuild` first."
            )
            return res

    loop = build_claude_loop(
        provider_mode,
        docs_search=docs_search,
        wiki_store=wiki_store,
    )
    if loop is None:
        res.error = (
            f"No ClaudeToolLoop available for provider={provider_mode!r}. "
            f"Set the right env vars (OPENROUTER_API_KEY / "
            f"ANTHROPIC_API_KEY / VMD_AI_OLLAMA_MODEL)."
        )
        return res
    # Some providers' constructors take `timeout`, others don't — only set
    # it if the attribute exists, so we don't break older builds.
    if hasattr(loop, "timeout"):
        try:
            loop.timeout = timeout
        except Exception:
            pass

    bridge = rag_ab._StubBridge()
    cancel_event = threading.Event()
    queue = EventQueue()

    # Capture tool calls via the loop's own callbacks rather than monkey-
    # patching dispatchers. This catches every tool (run_vmd_command,
    # capture_vmd_snapshot, search_docs, wiki_*) uniformly.
    in_flight: List[Dict[str, Any]] = []

    def on_tool_start(name: str, tool_input: Dict[str, Any]) -> None:
        rec = {
            "tool_name": name,
            "tool_input": dict(tool_input or {}),
            "ok": None,
            "error": "",
            "output_preview": "",
        }
        res.tool_calls.append(rec)
        in_flight.append(rec)

    def on_tool_result(tool_id: str, tool_name: str,
                       result: Dict[str, Any]) -> None:
        # Find the most recent unresolved record matching the name.
        for rec in reversed(res.tool_calls):
            if rec["tool_name"] == tool_name and rec["ok"] is None:
                rec["ok"] = bool(result.get("ok"))
                rec["error"] = str(result.get("error") or "")
                rec["output_preview"] = str(result.get("output") or "")[:200]
                # Derive wiki signals as they come in. Matches the channels
                # `wiki_bench._derive_wiki_metrics` + bench_wiki.py use:
                #   wiki_read → pins[].path           (citation, read-and-cite)
                #   wiki_update → input.sources[]     (citation, file-and-pin)
                #   wiki_update → input.page          (page filed)
                #   wiki_read → input.page            (page read)
                if tool_name == "wiki_read" and rec["ok"]:
                    page = str(rec["tool_input"].get("page") or "")
                    if page and page not in res.pages_read:
                        res.pages_read.append(page)
                    for pin in result.get("pins") or []:
                        if isinstance(pin, dict):
                            p = pin.get("path")
                            if p and p not in res.sources_cited:
                                res.sources_cited.append(str(p))
                elif tool_name == "wiki_update" and rec["ok"]:
                    page = str(rec["tool_input"].get("page") or "")
                    if page and page not in res.pages_updated:
                        res.pages_updated.append(page)
                    for src in rec["tool_input"].get("sources") or []:
                        if src and src not in res.sources_cited:
                            res.sources_cited.append(str(src))
                return

    t0 = time.perf_counter()
    try:
        res.final_text = loop.run(
            prompt=spec.prompt,
            system_prompt=system_prompt,
            tool_bridge=bridge,
            session_id=f"rag_wiki_ab_{arm}",
            session_queue=queue,
            cancel_event=cancel_event,
            on_chunk=lambda _c: None,
            on_tool_start=on_tool_start,
            on_tool_result=on_tool_result,
        )
    except Exception as exc:  # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        res.elapsed_s = time.perf_counter() - t0

    return res


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class ArmScore:
    arm: str
    error: Optional[str] = None
    # Behavior counters
    vmd_command_count: int = 0
    search_query_count: int = 0
    wiki_read_count: int = 0
    wiki_update_count: int = 0
    snapshot_count: int = 0
    elapsed_s: float = 0.0
    final_chars: int = 0
    # Idiom checklist (rag_ab_batch rubric)
    idiom_hits: Dict[str, bool] = field(default_factory=dict)
    idiom_applicable: int = 0
    idiom_hit_count: int = 0
    # Wiki rubric (wiki_bench)
    pages_filed: int = 0
    pages_read: int = 0
    sources_cited: int = 0
    cited_any: bool = False

    @property
    def idiom_coverage(self) -> float:
        return (
            self.idiom_hit_count / self.idiom_applicable
            if self.idiom_applicable else 0.0
        )


def score_trial(trial: TrialResult, expects: List[str]) -> ArmScore:
    score = ArmScore(arm=trial.arm, error=trial.error)
    score.elapsed_s = trial.elapsed_s
    score.final_chars = len(trial.final_text or "")
    score.vmd_command_count = trial.count("run_vmd_command")
    score.search_query_count = trial.count("search_docs")
    score.wiki_read_count = trial.count("wiki_read")
    score.wiki_update_count = trial.count("wiki_update")
    score.snapshot_count = trial.count("capture_vmd_snapshot")

    all_tcl = trial.vmd_tcl()
    for cat in expects:
        patterns = rag_ab_batch.IDIOM_PATTERNS.get(cat, [])
        hit = any(re.search(p, all_tcl, re.IGNORECASE) for p in patterns)
        score.idiom_hits[cat] = hit
    score.idiom_applicable = len(expects)
    score.idiom_hit_count = sum(1 for v in score.idiom_hits.values() if v)

    score.pages_filed = len(trial.pages_updated)
    score.pages_read = len(trial.pages_read)
    score.sources_cited = len(trial.sources_cited)
    score.cited_any = bool(trial.sources_cited)
    return score


# ---------------------------------------------------------------------------
# CSV + summary
# ---------------------------------------------------------------------------

def write_scorecard_csv(
    rows: List[Tuple[PromptSpec, str, ArmScore]],
    out_path: Path,
) -> None:
    # Use the union of idiom categories that appear anywhere in the suite.
    cats: List[str] = []
    for _spec, _arm, score in rows:
        for c in score.idiom_hits.keys():
            if c not in cats:
                cats.append(c)
    header = [
        "prompt_id", "arm", "error",
        "vmd_commands", "search_queries", "wiki_reads",
        "wiki_updates", "snapshots", "elapsed_s",
        "idiom_applicable", "idiom_hits", "idiom_coverage",
        "pages_filed", "pages_read", "sources_cited", "cited_any",
        "final_chars",
    ] + cats
    with out_path.open("w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        for spec, arm, s in rows:
            row = [
                spec.id, arm, (s.error or "").replace(",", ";"),
                s.vmd_command_count, s.search_query_count, s.wiki_read_count,
                s.wiki_update_count, s.snapshot_count, f"{s.elapsed_s:.1f}",
                s.idiom_applicable, s.idiom_hit_count,
                f"{s.idiom_coverage:.3f}",
                s.pages_filed, s.pages_read, s.sources_cited,
                "1" if s.cited_any else "0",
                s.final_chars,
            ]
            for c in cats:
                row.append("1" if s.idiom_hits.get(c, False) else "0")
            f.write(",".join(str(x) for x in row) + "\n")


def _arm_means(
    rows: List[Tuple[PromptSpec, str, ArmScore]],
    arm: str,
) -> Dict[str, float]:
    arm_scores = [s for _spec, a, s in rows if a == arm and not s.error]
    n = max(len(arm_scores), 1)
    return {
        "n": float(len(arm_scores)),
        "idiom_coverage": sum(s.idiom_coverage for s in arm_scores) / n,
        "citation_rate": sum(1.0 for s in arm_scores if s.cited_any) / n,
        "pages_filed_total": float(sum(s.pages_filed for s in arm_scores)),
        "avg_tool_calls": (
            sum(s.vmd_command_count + s.search_query_count
                + s.wiki_read_count + s.wiki_update_count
                + s.snapshot_count for s in arm_scores) / n
        ),
        "avg_elapsed_s": sum(s.elapsed_s for s in arm_scores) / n,
    }


def write_summary_json(
    rows: List[Tuple[PromptSpec, str, ArmScore]],
    out_path: Path,
    arms: List[str],
) -> Dict[str, Any]:
    per_arm = {a: _arm_means(rows, a) for a in arms}
    # Deltas vs the `none` baseline (if present).
    base = per_arm.get("none")
    deltas: Dict[str, Dict[str, float]] = {}
    if base is not None:
        for a in arms:
            if a == "none":
                continue
            deltas[a] = {
                "Δidiom_coverage":
                    per_arm[a]["idiom_coverage"] - base["idiom_coverage"],
                "Δcitation_rate":
                    per_arm[a]["citation_rate"] - base["citation_rate"],
                "Δavg_tool_calls":
                    per_arm[a]["avg_tool_calls"] - base["avg_tool_calls"],
                "Δavg_elapsed_s":
                    per_arm[a]["avg_elapsed_s"] - base["avg_elapsed_s"],
            }

    # Interaction term: how much of `both` is explained by `rag + wiki`?
    # Δboth − (Δrag + Δwiki) > 0  → synergistic (better together)
    # Δboth − (Δrag + Δwiki) < 0  → redundant (they overlap)
    interaction: Optional[Dict[str, float]] = None
    if all(a in deltas for a in ("rag", "wiki", "both")):
        interaction = {
            "idiom_coverage":
                deltas["both"]["Δidiom_coverage"]
                - (deltas["rag"]["Δidiom_coverage"]
                   + deltas["wiki"]["Δidiom_coverage"]),
            "citation_rate":
                deltas["both"]["Δcitation_rate"]
                - (deltas["rag"]["Δcitation_rate"]
                   + deltas["wiki"]["Δcitation_rate"]),
        }

    # Per-prompt breakdown — useful for spotting which prompts each
    # mechanism actually helps on.
    per_prompt: List[Dict[str, Any]] = []
    by_prompt: Dict[str, Dict[str, ArmScore]] = {}
    for spec, arm, s in rows:
        by_prompt.setdefault(spec.id, {})[arm] = s
    for pid, arm_to_score in by_prompt.items():
        per_prompt.append({
            "prompt_id": pid,
            "idiom_coverage": {a: arm_to_score[a].idiom_coverage
                               for a in arms if a in arm_to_score},
            "citation_rate": {a: (1 if arm_to_score[a].cited_any else 0)
                              for a in arms if a in arm_to_score},
            "errors": {a: arm_to_score[a].error
                       for a in arms if a in arm_to_score
                       and arm_to_score[a].error},
        })

    summary = {
        "arms": arms,
        "per_arm_means": per_arm,
        "deltas_vs_none": deltas,
        "interaction_both_minus_rag_plus_wiki": interaction,
        "per_prompt": per_prompt,
    }
    out_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def render_summary_text(summary: Dict[str, Any]) -> str:
    bar = "─" * 64
    lines = [bar, "RAG × Wiki 2×2 — summary", bar]
    means = summary["per_arm_means"]
    arms = summary["arms"]
    lines.append(
        f"{'arm':<8} {'n':>3}  {'idiom':>7}  {'cite':>5}  "
        f"{'tools':>6}  {'sec':>5}  {'pages':>5}"
    )
    for a in arms:
        m = means.get(a, {})
        lines.append(
            f"{a:<8} {int(m.get('n', 0)):>3}  "
            f"{m.get('idiom_coverage', 0):>7.3f}  "
            f"{m.get('citation_rate', 0):>5.2f}  "
            f"{m.get('avg_tool_calls', 0):>6.1f}  "
            f"{m.get('avg_elapsed_s', 0):>5.1f}  "
            f"{int(m.get('pages_filed_total', 0)):>5}"
        )
    deltas = summary.get("deltas_vs_none") or {}
    if deltas:
        lines.append("")
        lines.append("Δ vs none:")
        for a, d in deltas.items():
            lines.append(
                f"  {a:<6}  Δidiom={d['Δidiom_coverage']:+.3f}  "
                f"Δcite={d['Δcitation_rate']:+.2f}  "
                f"Δtools={d['Δavg_tool_calls']:+.1f}"
            )
    inter = summary.get("interaction_both_minus_rag_plus_wiki")
    if inter:
        lines.append("")
        lines.append(
            "Interaction (Δboth − (Δrag + Δwiki)):  "
            f"idiom={inter['idiom_coverage']:+.3f}  "
            f"cite={inter['citation_rate']:+.2f}"
        )
        lines.append(
            "  positive → synergistic, negative → redundant"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def _default_sleep(provider: str) -> float:
    if provider in ("anthropic-direct", "anthropic_api", "openrouter",
                    "claude", "claude-openrouter"):
        return 30.0
    return 0.0


def _sleep_countdown(seconds: float, why: str) -> None:
    if seconds <= 0:
        return
    print(f"  [cooldown] {seconds:.0f}s — {why}", flush=True)
    time.sleep(seconds)


def run_suite(
    suite: List[PromptSpec],
    arms: List[str],
    *,
    out_dir: Path,
    provider_mode: str,
    system_prompt: str,
    docs_index_dir: Optional[str],
    raw_root: Path,
    wiki_root_for_arm: Dict[str, Path],
    timeout: int,
    sleep_between_arms: float,
    sleep_between_prompts: float,
    skip_existing: bool,
    arm_major: bool = False,
) -> List[Tuple[PromptSpec, str, ArmScore]]:
    """
    Run the (prompt × arm) matrix and score each cell.

    Iteration order is controlled by ``arm_major``:

      * False (default) — prompt-outer, arm-inner. Each prompt runs all arms
        before moving on. Best when arms have similar token cost.

      * True — arm-outer, prompt-inner. All prompts run for one arm before
        switching arms. Recommended on Anthropic tier 1 (30k input
        tokens/min): keeps consecutive trials at similar token sizes and
        isolates the wiki arm's burstiness from the cheaper arms, so a 429
        in one arm doesn't poison adjacent cells of a different arm.

    ``sleep_between_arms`` always pauses when we cross an arm boundary
    (regardless of iteration order); ``sleep_between_prompts`` pauses
    between trials inside the same arm.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # One WikiStore per arm that needs one — shared across prompts within
    # the arm so knowledge accumulates. Independent across arms so the
    # `wiki` arm cannot benefit from pages filed by `both` (or vice versa).
    arm_wiki: Dict[str, Optional[WikiStore]] = {}
    for arm in arms:
        if ARM_HAS_WIKI[arm]:
            ws = WikiStore(wiki_root_for_arm[arm], raw_root=raw_root)
            ws.bootstrap()
            arm_wiki[arm] = ws
        else:
            arm_wiki[arm] = None

    # Build a flat list of (spec, arm) cells in the requested order, plus a
    # tag for whether the *previous* cell was a different arm. The runner
    # below uses that tag to decide which cooldown to apply, so the order
    # logic lives in one place.
    cells: List[Tuple[PromptSpec, str, bool]] = []   # (spec, arm, arm_changed)
    if arm_major:
        for ai, arm in enumerate(arms):
            for pi, spec in enumerate(suite):
                cells.append((spec, arm, pi == 0 and ai > 0))
    else:
        for pi, spec in enumerate(suite):
            for ai, arm in enumerate(arms):
                cells.append((spec, arm, ai > 0))

    rows: List[Tuple[PromptSpec, str, ArmScore]] = []
    total = len(cells)
    for ci, (spec, arm, arm_changed) in enumerate(cells):
        # Sleep BEFORE running the next cell, not after the previous one,
        # so a crash mid-run doesn't leave the harness sleeping.
        if ci > 0:
            if arm_changed:
                _sleep_countdown(sleep_between_arms, "next arm")
            else:
                _sleep_countdown(sleep_between_prompts, "next prompt")

        json_path = out_dir / f"{spec.id}.{arm}.json"
        order_tag = (
            f"arm {arm} | prompt {spec.id}"
            if arm_major else
            f"prompt {spec.id} | arm {arm}"
        )
        print(f"\n[cell {ci+1}/{total}] {order_tag}: "
              f"{spec.prompt[:64]}…")
        if skip_existing and json_path.exists():
            # Skip ONLY if the existing trial finished cleanly. A previous
            # 429 / rate-limit error is treated as "not yet run" so a
            # plain rerun with --skip-existing auto-retries just the
            # failed cells. This is the tier-1 Anthropic recovery loop.
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                trial = _trial_from_dict(data)
            except Exception as exc:
                print(f"  [warn ] couldn't re-read {json_path}: {exc} "
                      "— will re-run")
                trial = None
            if trial is not None:
                err = (trial.error or "").lower()
                transient = ("429" in err or "rate limit" in err
                             or "rate_limit" in err or "timeout" in err)
                if not transient:
                    tag = "skip " if not trial.error else "skip*"
                    print(f"  [{tag}] {json_path.name} "
                          f"(error: {trial.error!r})"
                          if trial.error else
                          f"  [{tag}] {json_path.name} exists")
                    rows.append((spec, arm, score_trial(trial,
                                                         spec.expects)))
                    continue
                print(f"  [retry] {json_path.name} had transient "
                      f"error — rerunning")

        print(f"  [run  ] …", flush=True)
        try:
            trial = _run_trial(
                spec, arm,
                provider_mode=provider_mode,
                system_prompt=system_prompt,
                docs_index_dir=docs_index_dir,
                wiki_store=arm_wiki[arm],
                timeout=timeout,
            )
        except Exception:
            traceback.print_exc()
            trial = TrialResult(
                prompt_id=spec.id, prompt=spec.prompt, arm=arm,
                error="harness exception",
            )
        json_path.write_text(
            json.dumps(trial.to_dict(), indent=2, sort_keys=True,
                       default=str),
            encoding="utf-8",
        )
        rows.append((spec, arm, score_trial(trial, spec.expects)))

    return rows


def load_suite_from_file(path: Path) -> List[PromptSpec]:
    """Load a prompt suite from JSON.

    Schema (see evals/rag_wiki_suite_v1.json):
        { "prompts": [ {"id", "prompt", "expects": [...]}, ... ] }

    Extra fields (e.g. ``bucket``, ``pdb``) are accepted but ignored — the
    harness only needs id / prompt / expects. We warn on unknown idiom
    keys so a typo in `expects` doesn't silently zero out an arm's score.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("prompts")
    if not isinstance(items, list) or not items:
        raise SystemExit(f"--prompts-file {path}: no 'prompts' array")
    known_idioms = set(rag_ab_batch.IDIOM_PATTERNS.keys())
    out: List[PromptSpec] = []
    seen_ids: set = set()
    for i, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise SystemExit(f"--prompts-file {path}: entry #{i} not an object")
        pid = entry.get("id")
        prompt = entry.get("prompt")
        expects = entry.get("expects") or []
        if not pid or not prompt:
            raise SystemExit(
                f"--prompts-file {path}: entry #{i} missing id/prompt"
            )
        if pid in seen_ids:
            raise SystemExit(
                f"--prompts-file {path}: duplicate id {pid!r}"
            )
        seen_ids.add(pid)
        unknown = [e for e in expects if e not in known_idioms]
        if unknown:
            print(f"[warn ] prompt {pid!r}: unknown idiom keys "
                  f"{unknown} (not in IDIOM_PATTERNS) — these will "
                  "never hit. Edit rag_ab_batch.IDIOM_PATTERNS or fix "
                  "the suite.", file=sys.stderr)
        out.append(PromptSpec(id=str(pid), prompt=str(prompt),
                              expects=list(expects)))
    return out


def _trial_from_dict(d: Dict[str, Any]) -> TrialResult:
    return TrialResult(
        prompt_id=d.get("prompt_id") or "",
        prompt=d.get("prompt") or "",
        arm=d.get("arm") or "",
        final_text=d.get("final_text") or "",
        tool_calls=list(d.get("tool_calls") or []),
        sources_cited=list(d.get("sources_cited") or []),
        pages_updated=list(d.get("pages_updated") or []),
        pages_read=list(d.get("pages_read") or []),
        elapsed_s=float(d.get("elapsed_s") or 0.0),
        error=d.get("error"),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rag_wiki_ab",
        description=("2x2 factorial harness over RAG and the LLM wiki, "
                     "scored on a single shared prompt set."),
    )
    p.add_argument("--out-dir", default="./rag_wiki_results",
                   help="Where to write per-trial JSONs + scorecard.")
    p.add_argument("--provider", default=None,
                   help="openrouter | anthropic-direct | ollama | mock "
                        "(default: env)")
    p.add_argument("--docs-index", default=None,
                   help="Override docs index dir (default ~/.vmdai/docs_index)")
    p.add_argument("--raw-root",
                   default=os.path.expanduser("~/.vmdai/raw"),
                   help="Raw-sources dir for wiki pinning.")
    p.add_argument("--wiki-root", default=None,
                   help="Persistent wiki root. Default: fresh tmp dir per "
                        "arm (no carryover between bench runs).")
    p.add_argument("--timeout", type=int, default=120,
                   help="Per-turn LLM timeout in seconds.")
    p.add_argument("--system-prompt", default=None,
                   help="Override system prompt (default VMD_SYSTEM_PROMPT).")
    p.add_argument("--only", default=None,
                   help="Comma-separated prompt_ids to run.")
    p.add_argument("--arms", default=",".join(ARMS),
                   help=f"Comma-separated arms to run. "
                        f"Choices: {','.join(ARMS)}. "
                        f"Default: all four.")
    p.add_argument("--sleep-between-arms", type=float, default=None,
                   help="Seconds to pause between arms within a prompt. "
                        "Default: 30 for cloud, 0 for local.")
    p.add_argument("--sleep-between-prompts", type=float, default=None,
                   help="Seconds to pause between prompts. Default: same "
                        "as --sleep-between-arms.")
    p.add_argument("--skip-existing", action="store_true",
                   help="If <id>.<arm>.json exists, reuse it instead of "
                        "re-running.")
    p.add_argument("--prompts-file", default=None,
                   help="Path to a JSON suite "
                        "(e.g. evals/rag_wiki_suite_v1.json). "
                        "Overrides the built-in DEFAULT_SUITE.")
    p.add_argument("--arm-major", action="store_true",
                   help="Iterate arm-outer, prompt-inner instead of the "
                        "default prompt-outer order. Recommended on "
                        "Anthropic tier 1 (30k input-tok/min): keeps the "
                        "wiki arm's expensive trials clustered so a 429 "
                        "doesn't bleed into adjacent cheap arms.")
    return p


def _validate_arms(spec: str) -> List[str]:
    wanted = [a.strip() for a in spec.split(",") if a.strip()]
    bad = [a for a in wanted if a not in ARMS]
    if bad:
        raise SystemExit(
            f"unknown arm(s): {bad}; valid: {ARMS}"
        )
    # Preserve canonical order so output is deterministic.
    return [a for a in ARMS if a in wanted]


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)

    provider_mode = rag_ab._resolve_provider_mode(args.provider)
    sys_prompt = args.system_prompt or VMD_SYSTEM_PROMPT
    arms = _validate_arms(args.arms)

    if args.prompts_file:
        full_suite = load_suite_from_file(
            Path(args.prompts_file).expanduser().resolve()
        )
    else:
        full_suite = DEFAULT_SUITE
    suite = full_suite
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        suite = [s for s in full_suite if s.id in wanted]
        if not suite:
            print(f"[error] no matching prompts in --only={args.only!r} "
                  f"(suite has {len(full_suite)} prompts: "
                  f"{[s.id for s in full_suite]})",
                  file=sys.stderr)
            return 2

    sleep_arms = (
        args.sleep_between_arms if args.sleep_between_arms is not None
        else _default_sleep(provider_mode)
    )
    sleep_prompts = (
        args.sleep_between_prompts if args.sleep_between_prompts is not None
        else sleep_arms
    )

    raw_root = Path(args.raw_root).expanduser().resolve()
    if not raw_root.exists():
        print(f"[warn ] raw root does not exist: {raw_root} — wiki source "
              "pinning will fail in wiki/both arms.", file=sys.stderr)

    # Wiki roots: one dir per wiki-enabled arm. If --wiki-root is given, the
    # arms are placed as subdirectories under it (so a single --wiki-root
    # value persists both wiki and both across reruns). Otherwise each arm
    # gets a tempdir cleaned up at the end.
    tmp_holders: List[tempfile.TemporaryDirectory] = []
    wiki_root_for_arm: Dict[str, Path] = {}
    base_wiki: Optional[Path] = (
        Path(args.wiki_root).expanduser().resolve()
        if args.wiki_root else None
    )
    if base_wiki:
        base_wiki.mkdir(parents=True, exist_ok=True)
    for arm in arms:
        if not ARM_HAS_WIKI[arm]:
            continue
        if base_wiki:
            wiki_root_for_arm[arm] = base_wiki / arm
            wiki_root_for_arm[arm].mkdir(parents=True, exist_ok=True)
        else:
            holder = tempfile.TemporaryDirectory(
                prefix=f"vmdai-rwab-{arm}-",
            )
            tmp_holders.append(holder)
            wiki_root_for_arm[arm] = Path(holder.name)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[rag_wiki_ab] settings:")
    print(f"  provider             : {provider_mode}")
    print(f"  arms                 : {arms}")
    print(f"  prompts              : {[s.id for s in suite]}")
    print(f"  out dir              : {out_dir}")
    print(f"  raw root             : {raw_root}")
    print(f"  wiki roots           : "
          f"{ {a: str(p) for a, p in wiki_root_for_arm.items()} }")
    print(f"  sleep between arms   : {sleep_arms}s")
    print(f"  sleep between prompts: {sleep_prompts}s")
    print(f"  skip existing        : {args.skip_existing}")
    print(f"  est trials           : {len(suite) * len(arms)}")
    print(f"  iteration order      : "
          f"{'arm-major' if args.arm_major else 'prompt-major'}")
    print()

    try:
        rows = run_suite(
            suite, arms,
            out_dir=out_dir,
            provider_mode=provider_mode,
            system_prompt=sys_prompt,
            docs_index_dir=args.docs_index,
            raw_root=raw_root,
            wiki_root_for_arm=wiki_root_for_arm,
            timeout=args.timeout,
            sleep_between_arms=sleep_arms,
            sleep_between_prompts=sleep_prompts,
            skip_existing=args.skip_existing,
            arm_major=args.arm_major,
        )
    finally:
        for h in tmp_holders:
            try:
                h.cleanup()
            except Exception:
                pass

    if not rows:
        print("[rag_wiki_ab] no trials scored", file=sys.stderr)
        return 1

    csv_path = out_dir / "scorecard.csv"
    summary_path = out_dir / "summary.json"
    write_scorecard_csv(rows, csv_path)
    summary = write_summary_json(rows, summary_path, arms)
    print()
    print(render_summary_text(summary))
    print()
    print(f"[rag_wiki_ab] wrote {csv_path}")
    print(f"[rag_wiki_ab] wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
