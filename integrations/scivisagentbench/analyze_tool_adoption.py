#!/usr/bin/env python3
"""analyze_tool_adoption.py — measure semantic-tool ADOPTION and taxonomize failures over a
completed atlas-traj run (the "before" number for the tools-arm before/after study).

The trajectory metrics can be answered two ways: call vmd_traj_measure (the tool authors the
correct frame-loop) or hand-write Tcl via run_vmd_command. The transcript makes this legible:
run_task only logs run_vmd_command calls, so a case that used ONLY the tool leaves NO <case>.tcl
file, while a hand-driven case leaves one full of mol/molinfo/measure commands. That asymmetry
is the adoption signal.

  python integrations/scivisagentbench/analyze_tool_adoption.py --run-dir test_results/atlas_traj/tools_v2

Pure classification lives in classify_case() (unit-tested in test_analyze_tool_adoption.py).
"""
import argparse, json, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# measurement done by hand (=> the model drove VMD itself, did not defer to the tool)
_MEASURE_RE = re.compile(r"get\s+numframes|measure\s+(?:rgyr|sasa|rmsd|rmsf|fit|bond)|\bfor\s*\{", re.I)
# a semantic tool's recorded Tcl lives inside a '# >>> via <tool> ... # <<< end <tool>' block;
# strip those before asking "did the model measure BY HAND?", else the tool's own molinfo/measure
# lines would read as hand-written.
_TOOL_BLOCK_RE = re.compile(r"# >>> via .*?# <<< end \S+", re.S)
# the transcript lists failed run_vmd_command attempts as comments under this header; those never
# ran, so they must not be read as the model's actual (hand) computation.
_ERRORED_SECTION_RE = re.compile(r"# --- attempts that errored.*", re.S)
_OVERCORRECT_RE = re.compile(r"numframes\s*\]?\s*-\s*1\b", re.I)          # gratuitous "- 1"
_IMBALANCE_RE = re.compile(r"incomplete Tcl|unclosed", re.I)             # brace-guard rejections
_DOUBT_RE = re.compile(r"proceed with writing|might be an issue|reports?\s+0\s+frames|"
                       r"issue with the trajectory|0 frames", re.I)      # wrote a value it distrusted

ADOPTIONS = ("tool_only", "tool_plus_write", "hand_computed")
REASONS = ("brace_thrash", "over_corrected", "timeout", "knowingly_wrong", "no_answer", "wrong_value")


def classify_case(*, tcl_text, response_text, agent_val, gold_val, ok, harness_error):
    """Return (adoption, failure_reason). adoption in ADOPTIONS; failure_reason is None when
    ok, else one of REASONS. Pure text logic — no VMD, no filesystem."""
    tcl = tcl_text or ""
    resp = response_text or ""
    herr = harness_error or ""

    if not tcl.strip():
        adoption = "tool_only"            # no run_vmd_command calls (pre-marker runs: no .tcl at all)
    else:
        no_tools = _TOOL_BLOCK_RE.sub("", tcl)             # drop the recorded tool blocks
        ok_part = _ERRORED_SECTION_RE.sub("", no_tools)    # drop failed attempts — they never ran
        has_marker = "# >>> via " in tcl
        hand_cmds = any(ln.strip() and not ln.lstrip().startswith("#") for ln in ok_part.splitlines())
        if _MEASURE_RE.search(ok_part):
            adoption = "hand_computed"    # SUCCESSFULLY measured by hand, outside any tool block
        elif not has_marker and _IMBALANCE_RE.search(no_tools):
            # no tool was used and the model thrashed on a hand loop (truncation can hide the
            # measure/for); a brace-imbalance rejection only comes from a hand-written run_vmd_command.
            adoption = "hand_computed"
        elif hand_cmds:
            adoption = "tool_plus_write"  # ran loads / a file-write; the value came from the tool
        else:
            adoption = "tool_only"

    if ok:
        return (adoption, None)

    if len(_IMBALANCE_RE.findall(tcl)) >= 2:
        reason = "brace_thrash"
    elif _OVERCORRECT_RE.search(tcl):
        reason = "over_corrected"
    elif "timed out" in herr.lower():
        reason = "timeout"
    elif agent_val is not None and _DOUBT_RE.search(resp):
        reason = "knowingly_wrong"
    elif agent_val is None:
        reason = "no_answer"
    else:
        reason = "wrong_value"
    return (adoption, reason)


def _read(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _herr_map(run_dir):
    """case_name -> harness_error, from failures.jsonl (keyed by single-underscore case name)."""
    herr = {}
    fjsonl = run_dir / "failures.jsonl"
    if fjsonl.exists():
        for line in fjsonl.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line); herr[r.get("case")] = r.get("harness_error")
                except ValueError:
                    pass
    return herr


def _row(run_dir, name, metric, case_name, gold_val, agent_val, ok, herr):
    adoption, reason = classify_case(
        tcl_text=_read(run_dir / f"{case_name}.tcl"),
        response_text=_read(run_dir / f"{case_name}.response.txt"),
        agent_val=agent_val, gold_val=gold_val, ok=ok, harness_error=herr.get(case_name))
    return {"name": name, "metric": metric, "case": case_name, "gold": gold_val, "agent": agent_val,
            "ok": ok is True, "adoption": adoption, "reason": reason}


def analyze(run_dir, gold_cache=None):
    """Rows of {name, metric, ok, adoption, reason}. Uses summary.json when present; otherwise
    reconstructs from the per-case artifacts on disk + the gold cache (a still-running or
    summary-less run)."""
    run_dir = Path(run_dir)
    if (run_dir / "summary.json").exists():
        return _analyze_from_summary(run_dir)
    return _analyze_from_disk(run_dir, gold_cache)


def _analyze_from_summary(run_dir):
    summary = json.loads((run_dir / "summary.json").read_text())
    herr = _herr_map(run_dir)
    rows = []
    for key, d in summary.items():                       # key: "<name>__<metric>__s<seed>"
        parts = key.split("__")
        if len(parts) != 3:
            continue
        name, metric, _ = parts
        rows.append(_row(run_dir, name, metric, key.replace("__", "_"),
                         d.get("gold"), d.get("agent"), d.get("ok") is True, herr))
    return rows


def _analyze_from_disk(run_dir, gold_cache):
    """No summary.json: enumerate the gold-cache chains x metrics x seeds-seen, keep the cases that
    left an artifact, and recompute (agent, ok) exactly as run_atlas_traj does (nearest float to
    gold, within the metric's tolerance)."""
    gold_path = Path(gold_cache) if gold_cache else (HERE / "gold_cache_atlas_fixtures.json")
    if not gold_path.exists():
        raise SystemExit(f"no summary.json and gold cache not found: {gold_path}\n"
                         "  pass --gold-cache <the run's gold cache json>.")
    gold = json.loads(gold_path.read_text())
    sys.path.insert(0, str(HERE))
    from run_atlas_traj import METRICS, FLOAT              # scoring tolerances + float regex (single source)

    seeds = set()
    for f in run_dir.iterdir():
        m = re.search(r"_s(\d+)(?:\.txt|\.tcl|\.response\.txt)$", f.name)
        if m:
            seeds.add(int(m.group(1)))
    herr = _herr_map(run_dir)

    rows = []
    for name in gold:
        for metric, (_phrase, tol, scored) in METRICS.items():
            g = gold.get(name, {}).get(metric)
            g = float(g) if g is not None else None
            for seed in sorted(seeds):
                case_name = f"{name}_{metric}_s{seed}"
                ans = run_dir / f"{name}__{metric}__s{seed}.txt"
                tcl_f = run_dir / f"{case_name}.tcl"
                resp_f = run_dir / f"{case_name}.response.txt"
                if not (ans.exists() or tcl_f.exists() or resp_f.exists()):
                    continue                              # this (chain,metric,seed) hasn't run
                val = None
                if ans.exists() and g is not None:
                    fs = [float(x) for x in FLOAT.findall(_read(ans) or "")]
                    if fs:
                        val = min(fs, key=lambda x: abs(x - g))
                ok = (val is not None and g is not None and abs(val - g) <= tol) if scored else None
                rows.append(_row(run_dir, name, metric, case_name, g, val, ok, herr))
    return rows


def _pct(a, b):
    return f"{100*a/b:5.1f}%" if b else "   -  "


def report(rows):
    n = len(rows)
    if not n:
        print("no cases found (is --run-dir the tag dir with summary.json?)"); return
    used = lambda r: r["adoption"] != "hand_computed"    # tool_only or tool_plus_write

    print(f"\n=== semantic-tool ADOPTION & failure taxonomy  (n={n} cases) ===\n")

    ad = Counter(r["adoption"] for r in rows)
    print("adoption overall:")
    for a in ADOPTIONS:
        print(f"  {a:16} {ad[a]:4}  {_pct(ad[a], n)}")
    tool_used = sum(1 for r in rows if used(r))
    print(f"  {'-> TOOL USED':16} {tool_used:4}  {_pct(tool_used, n)}   (tool_only + tool_plus_write)\n")

    print(f"per-metric   {'adoption%':>10} {'correct%':>10}   (n per metric)")
    by_metric = defaultdict(list)
    for r in rows:
        by_metric[r["metric"]].append(r)
    for m in sorted(by_metric):
        mr = by_metric[m]
        au = sum(1 for r in mr if used(r)); ok = sum(1 for r in mr if r["ok"])
        print(f"  {m:10} {_pct(au, len(mr)):>10} {_pct(ok, len(mr)):>10}   ({len(mr)})")

    print("\ncorrectness CONDITIONAL on adoption (the key number):")
    for bucket, pred in (("tool used", used), ("hand_computed", lambda r: not used(r))):
        sub = [r for r in rows if pred(r)]
        ok = sum(1 for r in sub if r["ok"])
        print(f"  {bucket:16} {ok:4}/{len(sub):<4} correct  {_pct(ok, len(sub))}")

    fails = [r for r in rows if not r["ok"]]
    tax = Counter(r["reason"] for r in fails)
    print(f"\nfailure taxonomy  ({len(fails)} failures):")
    for reason in REASONS:
        if tax[reason]:
            print(f"  {reason:16} {tax[reason]:4}  {_pct(tax[reason], len(fails))}")


def report_failures(rows):
    """List every failing case, tool-used ones first — those are the surprising failures (a tool
    was used yet the answer was wrong/missing), vs the expected hand-computed ones."""
    fails = [r for r in rows if not r["ok"]]
    if not fails:
        print("\nno failures."); return
    # tool-used failures first (adoption != hand_computed), then by metric/case
    fails.sort(key=lambda r: (r["adoption"] == "hand_computed", r["metric"], r["case"]))
    print(f"\nfailing cases ({len(fails)}) — tool-used first:")
    print(f"  {'case':30}{'adoption':16}{'reason':16}{'gold':>12}{'agent':>12}")
    for r in fails:
        print(f"  {r['case']:30}{r['adoption']:16}{str(r['reason']):16}"
              f"{str(r['gold']):>12}{str(r['agent']):>12}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="the arm's tag dir, e.g. test_results/atlas_traj/tools_v2")
    ap.add_argument("--gold-cache", default=None,
                    help="gold cache json (only needed when the run has no summary.json yet — "
                         "still running or died before the final write). Default: "
                         "gold_cache_atlas_fixtures.json next to this script.")
    ap.add_argument("--show-failures", action="store_true",
                    help="also list every failing case (tool-used ones first) with gold/agent")
    args = ap.parse_args()
    rows = analyze(args.run_dir, gold_cache=args.gold_cache)
    if not (Path(args.run_dir) / "summary.json").exists():
        print(f"[partial] no summary.json — reconstructed {len(rows)} completed case(s) from disk")
    report(rows)
    if args.show_failures:
        report_failures(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
