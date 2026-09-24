#!/usr/bin/env python3
"""
rag_ab_batch.py — run the RAG A/B harness across a suite of prompts and
score each arm against an idiom checklist. Produces:

    <out-dir>/
        <prompt_id>.json        ← raw rag_ab output, one per prompt
        scorecard.csv           ← per-prompt, per-arm idiom hits
        summary.json            ← aggregate win/loss/tie counts

The default suite covers six prompts that exercise different parts of
the indexed corpus (kinase SKILL, docking SKILL, TCBG tutorial
sections on representations / rendering / animation, pore SKILL). Each
prompt pins a specific PDB ID so neither arm gets unfair "the model
picked the wrong structure" credit.

Each prompt is scored on a binary idiom checklist:

    Did the captured Tcl contain `NewCartoon`?  ✓ or ✗
    Did it use `mol color Structure`?           ✓ or ✗
    Did it pick the correct ligand selector?    ✓ or ✗
    …

The score per arm is hits / applicable_idioms (each prompt declares
which idioms apply). RAG wins a prompt when its score > control's;
ties and losses are counted separately so a 5-of-6 RAG win is visible
without averaging it away.

Usage:

    python scripts/rag_ab_batch.py                           # full default suite
    python scripts/rag_ab_batch.py --only cdk2_atp,abl_imatinib  # subset
    python scripts/rag_ab_batch.py --provider ollama --sleep 0
    python scripts/rag_ab_batch.py --out-dir results/ --skip-existing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

HERE = Path(__file__).resolve()
SCRIPTS_DIR = HERE.parent
RUNTIME_DIR = HERE.parents[1] / "runtime"
for p in (SCRIPTS_DIR, RUNTIME_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import rag_ab  # noqa: E402


# ----------------------------------------------------------------------
# Idiom checklist — what patterns count as a hit per category.
# ----------------------------------------------------------------------
# Each category is a list of regex patterns. A category counts as a hit
# if ANY of its patterns match anywhere in the concatenated Tcl of an
# arm. Patterns are case-insensitive (re.IGNORECASE applied below).

IDIOM_PATTERNS: Dict[str, List[str]] = {
    "newcartoon":       [r"\bNewCartoon\b"],
    "licorice":         [r"\bLicorice\b"],
    "vdw":              [r"\bVDW\b"],
    "surf":             [r"\bSurf\b", r"\bQuickSurf\b"],
    "color_structure":  [r"mol color Structure"],
    "color_resname":    [r"mol color (?:ResName|ResType|Type)"],
    "aochalky":         [r"\bAOChalky\b"],
    "glossy":           [r"\bGlossy\b"],
    "ghost":            [r"material Ghost", r"mol material Ghost"],
    "transparent":      [r"material Transparent", r"mol material Transparent"],
    "orthographic":     [r"display projection Orthographic"],
    "ao_on":            [r"display ambientocclusion on"],
    "shadows_on":       [r"display shadows on"],
    "tachyon":          [r"render TachyonInternal", r"render Tachyon\b"],
    "render_snapshot":  [r"render snapshot\b"],
    "white_bg":         [r"display backgroundcolor white",
                         r"color Display Background white"],
    "axes_off":         [r"axes location Off"],
    "rotate":           [r"rotate [xyz] by", r"display resetview"],
    # Ligand selectors — different per prompt.
    "atp_selector":     [r"resname ATP", r"resname ANP",
                         r"resname AMP", r"resname ADP"],
    "imatinib_sel":     [r"resname STI", r"resname IMA"],
    "capsaicin_sel":    [r"resname CPS", r"resname CAP"],
    "pdbqt_load":       [r"mol new\s+\"?[^\"]*\.pdbqt", r"type pdbqt"],
    "user_column":      [r"mol color User", r"\$\w+ set user\b",
                         r"mol scaleminmax"],
    "within_select":    [r"within\s+\d+(?:\.\d+)?\s+of"],
    "measure_contacts": [r"measure contacts"],
    "movie_loop":       [r"\bfor\s*\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*rotate",
                         r"\bplay\b",
                         r"render TachyonInternal[^\n]*\$(?:f|i|n|frame)"],
}


# ----------------------------------------------------------------------
# Prompt suite — id, prompt text, applicable idioms
# ----------------------------------------------------------------------

@dataclass
class PromptSpec:
    id: str
    prompt: str
    expects: List[str]                # idiom categories that apply
    notes: str = ""                   # what we expect to differ between arms


DEFAULT_SUITE: List[PromptSpec] = [
    PromptSpec(
        id="cdk2_atp",
        prompt=(
            "Load 1HCK (CDK2 with AMPPNP) and present it in academic "
            "style focused on the ATP-pocket binding interactions"
        ),
        expects=[
            "newcartoon", "licorice", "color_structure", "aochalky",
            "ghost", "orthographic", "ao_on", "shadows_on", "tachyon",
            "white_bg", "atp_selector", "within_select",
        ],
        notes="kinase SKILL — RAG should know ANP resname + 6-layer recipe",
    ),
    PromptSpec(
        id="abl_imatinib",
        prompt=(
            "Load 1IEP (ABL kinase bound to imatinib) and show it in "
            "publication style with the DFG-out conformation highlighted"
        ),
        expects=[
            "newcartoon", "licorice", "color_structure", "aochalky",
            "orthographic", "ao_on", "tachyon", "imatinib_sel",
            "within_select",
        ],
        notes="kinase SKILL on inhibitor — RAG should know STI resname",
    ),
    PromptSpec(
        id="vina_docking",
        prompt=(
            "Load the Vina docking output from a PDBQT file "
            "(receptor.pdbqt + vina_out.pdbqt) and color the poses by "
            "binding affinity"
        ),
        expects=[
            "licorice", "user_column", "pdbqt_load",
            "measure_contacts", "within_select",
        ],
        notes="docking SKILL — RAG should know to parse REMARK + use User column",
    ),
    PromptSpec(
        id="ubq_secondary",
        prompt=(
            "Show 1UBQ in NewCartoon colored by secondary structure "
            "and render with ambient occlusion and shadows"
        ),
        expects=[
            "newcartoon", "color_structure", "orthographic",
            "ao_on", "shadows_on", "tachyon", "white_bg", "aochalky",
        ],
        notes="TCBG tutorial — rendering section. Both should get this; "
              "RAG should be slightly more thorough.",
    ),
    PromptSpec(
        id="ubq_movie",
        prompt=(
            "Make a 360° rotation animation of 1UBQ and save the frames "
            "as ray-traced images"
        ),
        expects=[
            "newcartoon", "rotate", "tachyon", "movie_loop",
        ],
        notes="TCBG IMGMOV tutorial — animation section",
    ),
    PromptSpec(
        id="trpv1_pore",
        prompt=(
            "Visualize a TRPV1 channel with its agonist capsaicin in "
            "the pore; show the channel as a transparent surface and "
            "the ligand as Licorice"
        ),
        expects=[
            "licorice", "transparent", "color_resname",
            "within_select", "capsaicin_sel",
        ],
        notes="pore SKILL — RAG should know channel-vs-pocket selection",
    ),
]


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------

@dataclass
class ArmScore:
    name: str
    error: Optional[str] = None
    vmd_command_count: int = 0
    search_query_count: int = 0
    snapshot_count: int = 0
    elapsed_s: float = 0.0
    hits: Dict[str, bool] = field(default_factory=dict)
    applicable: int = 0
    hit_count: int = 0

    @property
    def coverage(self) -> float:
        return self.hit_count / self.applicable if self.applicable else 0.0


@dataclass
class PromptResult:
    prompt_id: str
    prompt: str
    control: ArmScore
    rag: ArmScore
    json_path: str

    @property
    def winner(self) -> str:
        if self.control.error and self.rag.error:
            return "both_failed"
        if self.control.error:
            return "rag"
        if self.rag.error:
            return "control"
        if self.rag.coverage > self.control.coverage:
            return "rag"
        if self.control.coverage > self.rag.coverage:
            return "control"
        return "tie"


def _concatenate_vmd_tcl(arm_json: Dict) -> str:
    """Concat all run_vmd_command Tcl from an arm's tool_calls."""
    out = []
    for c in arm_json.get("tool_calls") or []:
        if c.get("tool_name") == "run_vmd_command":
            cmd = (c.get("tool_input") or {}).get("command", "")
            if cmd:
                out.append(str(cmd))
    return "\n".join(out)


def _count_tool_calls(arm_json: Dict, tool_name: str) -> int:
    return sum(
        1 for c in (arm_json.get("tool_calls") or [])
        if c.get("tool_name") == tool_name
    )


def score_arm(arm_json: Dict, expects: List[str], arm_label: str) -> ArmScore:
    score = ArmScore(name=arm_label)
    err = arm_json.get("error")
    if err:
        score.error = str(err)
    score.elapsed_s = float(arm_json.get("elapsed_s", 0) or 0)
    score.vmd_command_count = _count_tool_calls(arm_json, "run_vmd_command")
    score.search_query_count = _count_tool_calls(arm_json, "search_docs")
    score.snapshot_count = _count_tool_calls(arm_json, "capture_vmd_snapshot")

    all_tcl = _concatenate_vmd_tcl(arm_json)
    for cat in expects:
        patterns = IDIOM_PATTERNS.get(cat, [])
        hit = any(re.search(p, all_tcl, re.IGNORECASE) for p in patterns)
        score.hits[cat] = hit

    score.applicable = len(expects)
    score.hit_count = sum(1 for v in score.hits.values() if v)
    return score


def score_prompt_json(json_path: Path, spec: PromptSpec) -> PromptResult:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return PromptResult(
        prompt_id=spec.id,
        prompt=spec.prompt,
        control=score_arm(data.get("control") or {}, spec.expects, "control"),
        rag=score_arm(data.get("rag") or {}, spec.expects, "rag"),
        json_path=str(json_path),
    )


# ----------------------------------------------------------------------
# CSV + summary emission
# ----------------------------------------------------------------------

def write_scorecard_csv(results: List[PromptResult], out_path: Path) -> None:
    # Determine the union of idiom categories actually used so the
    # header is stable and informative.
    cats: List[str] = []
    for r in results:
        for c in r.control.hits.keys():
            if c not in cats:
                cats.append(c)
    header = (
        ["prompt_id", "arm", "error", "vmd_commands",
         "search_queries", "snapshots", "elapsed_s",
         "applicable", "hit_count", "coverage"]
        + cats
    )
    rows = []
    for r in results:
        for arm in (r.control, r.rag):
            row = [
                r.prompt_id, arm.name, arm.error or "",
                arm.vmd_command_count, arm.search_query_count,
                arm.snapshot_count, f"{arm.elapsed_s:.1f}",
                arm.applicable, arm.hit_count, f"{arm.coverage:.3f}",
            ]
            for c in cats:
                row.append("1" if arm.hits.get(c, False) else "0")
            rows.append(row)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(str(x) for x in row) + "\n")


def write_summary_json(results: List[PromptResult], out_path: Path) -> Dict:
    wins = {"control": 0, "rag": 0, "tie": 0, "both_failed": 0}
    for r in results:
        wins[r.winner] += 1
    summary = {
        "n_prompts": len(results),
        "wins": wins,
        "control_mean_coverage": (
            sum(r.control.coverage for r in results) / len(results)
            if results else 0.0
        ),
        "rag_mean_coverage": (
            sum(r.rag.coverage for r in results) / len(results)
            if results else 0.0
        ),
        "per_prompt": [
            {
                "prompt_id": r.prompt_id,
                "winner": r.winner,
                "control_coverage": r.control.coverage,
                "rag_coverage": r.rag.coverage,
                "control_hit_count": r.control.hit_count,
                "rag_hit_count": r.rag.hit_count,
                "applicable": r.control.applicable,
                "control_error": r.control.error,
                "rag_error": r.rag.error,
            }
            for r in results
        ],
    }
    out_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8",
    )
    return summary


def render_summary_text(summary: Dict) -> str:
    bar = "─" * 60
    lines = [bar, "RAG A/B batch — summary", bar]
    w = summary["wins"]
    n = summary["n_prompts"]
    lines.append(f"prompts run     : {n}")
    lines.append(f"  RAG wins      : {w['rag']}")
    lines.append(f"  control wins  : {w['control']}")
    lines.append(f"  ties          : {w['tie']}")
    lines.append(f"  both failed   : {w['both_failed']}")
    lines.append("")
    lines.append(f"control mean coverage : {summary['control_mean_coverage']:.3f}")
    lines.append(f"rag     mean coverage : {summary['rag_mean_coverage']:.3f}")
    lines.append("")
    lines.append("per-prompt breakdown:")
    for r in summary["per_prompt"]:
        mark = {"rag": "★", "control": "·", "tie": "=", "both_failed": "X"}[r["winner"]]
        lines.append(
            f"  {mark} {r['prompt_id']:<20}  "
            f"control={r['control_coverage']:.2f} "
            f"rag={r['rag_coverage']:.2f}  "
            f"winner={r['winner']}"
        )
        if r["control_error"]:
            lines.append(f"      control error: {r['control_error'][:80]}…")
        if r["rag_error"]:
            lines.append(f"      rag error    : {r['rag_error'][:80]}…")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------

def run_one_prompt(
    spec: PromptSpec,
    *,
    out_dir: Path,
    provider: Optional[str],
    sleep: Optional[float],
    skip_existing: bool,
) -> Path:
    """Run rag_ab.main() for one prompt. Returns the JSON path."""
    json_path = out_dir / f"{spec.id}.json"
    if skip_existing and json_path.exists():
        print(f"  [skip] {spec.id} — {json_path} already exists")
        return json_path

    print(f"  [run]  {spec.id}: {spec.prompt[:60]}…")
    argv = [spec.prompt, "--json", str(json_path)]
    if provider:
        argv += ["--provider", provider]
    if sleep is not None:
        argv += ["--sleep", str(sleep)]
    try:
        rc = rag_ab.main(argv)
        if rc != 0:
            print(f"  [warn] {spec.id} exited rc={rc}")
    except SystemExit as e:
        if int(getattr(e, "code", 0) or 0) != 0:
            print(f"  [warn] {spec.id} SystemExit code={e.code}")
    except Exception:
        # Don't let one bad prompt kill the batch. Record the failure
        # by writing a stub JSON the scorer can read.
        print(f"  [error] {spec.id} crashed:")
        traceback.print_exc()
        if not json_path.exists():
            json_path.write_text(json.dumps({
                "prompt": spec.prompt,
                "control": {"error": "batch runner exception",
                            "tool_calls": []},
                "rag":     {"error": "batch runner exception",
                            "tool_calls": []},
            }), encoding="utf-8")
    return json_path


def run_batch(
    suite: List[PromptSpec],
    *,
    out_dir: Path,
    provider: Optional[str],
    sleep: Optional[float],
    sleep_between_prompts: float,
    skip_existing: bool,
) -> List[PromptResult]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[PromptResult] = []
    for i, spec in enumerate(suite):
        json_path = run_one_prompt(
            spec,
            out_dir=out_dir,
            provider=provider,
            sleep=sleep,
            skip_existing=skip_existing,
        )
        try:
            results.append(score_prompt_json(json_path, spec))
        except Exception as exc:
            print(f"  [error] scoring {spec.id} failed: {exc}")
        # Cool down before the next prompt to spread out the token spend.
        if sleep_between_prompts > 0 and i < len(suite) - 1:
            print(f"  [cooldown] {sleep_between_prompts:.0f}s before next prompt …")
            time.sleep(sleep_between_prompts)
    return results


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rag_ab_batch",
        description=(
            "Run the RAG A/B harness across a suite of prompts and "
            "score each arm against an idiom checklist."
        ),
    )
    p.add_argument("--out-dir", default="./rag_ab_results",
                   help="Directory to write per-prompt JSONs + scorecard")
    p.add_argument("--provider", default=None,
                   help="Provider for rag_ab (overrides VMD_AI_PROVIDER)")
    p.add_argument("--sleep", type=float, default=None,
                   help="Pause between control & RAG arms within a "
                        "single prompt (rag_ab --sleep). Default: 90 "
                        "for cloud, 0 for local.")
    p.add_argument("--sleep-between-prompts", type=float, default=None,
                   help="Pause between successive prompts. Default: "
                        "60 for cloud, 0 for local.")
    p.add_argument("--only", default=None,
                   help="Comma-separated prompt_ids to run "
                        "(default: full suite)")
    p.add_argument("--skip-existing", action="store_true",
                   help="If <out-dir>/<id>.json already exists, skip "
                        "the run and just score it")
    p.add_argument("--summary-only", action="store_true",
                   help="Skip running; just score whatever JSONs are "
                        "already in --out-dir")
    return p


def _default_sleep(provider: Optional[str]) -> float:
    if (provider or "").lower() in ("anthropic-direct", "anthropic_api",
                                     "openrouter", "claude"):
        return 90.0
    return 0.0


def _default_between_prompts(provider: Optional[str]) -> float:
    if (provider or "").lower() in ("anthropic-direct", "anthropic_api",
                                     "openrouter", "claude"):
        return 60.0
    return 0.0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    suite = DEFAULT_SUITE
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        suite = [s for s in DEFAULT_SUITE if s.id in wanted]
        if not suite:
            print(f"[error] no matching prompts in --only={args.only!r}")
            return 2

    sleep = (
        args.sleep if args.sleep is not None
        else _default_sleep(args.provider)
    )
    sleep_between = (
        args.sleep_between_prompts if args.sleep_between_prompts is not None
        else _default_between_prompts(args.provider)
    )

    print("[batch] settings:")
    print(f"  provider           : {args.provider or '(env)'}")
    print(f"  arm sleep          : {sleep}s")
    print(f"  prompt cooldown    : {sleep_between}s")
    print(f"  out dir            : {out_dir}")
    print(f"  prompts            : {[s.id for s in suite]}")
    print(f"  skip existing      : {args.skip_existing}")
    print(f"  summary only       : {args.summary_only}")
    print()

    if args.summary_only:
        results: List[PromptResult] = []
        for spec in suite:
            json_path = out_dir / f"{spec.id}.json"
            if not json_path.exists():
                print(f"  [skip] {spec.id} — no JSON at {json_path}")
                continue
            results.append(score_prompt_json(json_path, spec))
    else:
        results = run_batch(
            suite,
            out_dir=out_dir,
            provider=args.provider,
            sleep=sleep,
            sleep_between_prompts=sleep_between,
            skip_existing=args.skip_existing,
        )

    if not results:
        print("[batch] no results to score")
        return 1

    csv_path = out_dir / "scorecard.csv"
    summary_path = out_dir / "summary.json"
    write_scorecard_csv(results, csv_path)
    summary = write_summary_json(results, summary_path)
    print()
    print(render_summary_text(summary))
    print()
    print(f"[batch] wrote {csv_path}")
    print(f"[batch] wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
