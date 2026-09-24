#!/usr/bin/env python3
"""audit_answer_parser.py — G-B1 scoring audit: is the benchmark's answer parsing
gold-aware in a way that changes conclusions?

The shipped scorer (run_atlas_traj._parse_answer) accepts up to 4 numeric tokens per
answer file and selects the one NEAREST GOLD — bounded, but gold-aware. This tool
re-scores EXISTING run outputs under two parsers and reports the sensitivity:

  legacy : the shipped parser, delegated verbatim (<=4 tokens, nearest to gold)
  strict : exactly one numeric token in the file, gold-blind

Usage (no VMD, no LLM — pure re-scoring of files on disk):
  python3 audit_answer_parser.py                       # audits test_results/atlas_traj/*
  python3 audit_answer_parser.py --out ../../draft_iclr

Per run dir it reads summary.json (authoritative gold per case) and the raw
<case>.txt answer files; a case whose file never existed (agent gave no answer)
counts as fail under BOTH parsers; a file lost after scoring is excluded and counted.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from run_atlas_traj import FLOAT, METRICS, _parse_answer  # noqa: E402


def _hard_metrics():
    try:
        from hard_metrics import HARD_METRICS
        return HARD_METRICS
    except ImportError:
        return {}


def parse_strict(text):
    """Gold-blind: the answer is the file's single numeric token, else no answer."""
    fs = FLOAT.findall(text or "")
    if len(fs) != 1:
        return None
    return float(fs[0])


def parse_legacy(text, gold):
    """The shipped parser, delegated so the audit can never drift from it."""
    return _parse_answer(text, gold)


def tolerance_for(metric):
    if metric in METRICS:
        return float(METRICS[metric][1])
    hm = _hard_metrics()
    if metric in hm:
        return float(hm[metric][1])
    return None


def audit_entry(text, gold, tol):
    lv = parse_legacy(text, gold)
    sv = parse_strict(text)
    lok = lv is not None and gold is not None and tol is not None and abs(lv - gold) <= tol
    sok = sv is not None and gold is not None and tol is not None and abs(sv - gold) <= tol
    return {"legacy_val": lv, "strict_val": sv,
            "legacy_ok": bool(lok), "strict_ok": bool(sok), "flip": bool(lok != sok)}


def audit_run_dir(run_dir):
    summ = run_dir / "summary.json"
    if not summ.exists():
        return None
    try:
        detail = json.load(open(summ))
    except (ValueError, OSError):
        return None
    rows, lost = [], 0
    for key, d in (detail.items() if isinstance(detail, dict) else []):
        if not isinstance(d, dict) or d.get("ok") is None or d.get("gold") is None:
            continue                       # unscored case
        parts = key.split("__")
        if len(parts) != 3:
            continue
        tol = tolerance_for(parts[1])
        if tol is None:
            continue
        f = run_dir / f"{key}.txt"
        if not f.exists():
            if d.get("agent") is None:     # agent never answered: fail under both
                rows.append({"key": key, "legacy_val": None, "strict_val": None,
                             "legacy_ok": False, "strict_ok": False, "flip": False,
                             "orig_ok": bool(d.get("ok"))})
            else:                          # answer existed at scoring time, file lost since
                lost += 1
            continue
        e = audit_entry(open(f, errors="replace").read(), float(d["gold"]), tol)
        e.update({"key": key, "orig_ok": bool(d.get("ok"))})
        rows.append(e)
    if not rows:
        return None
    n = len(rows)
    return {
        "run": run_dir.name, "entries": n, "lost_files": lost,
        "orig_pass": sum(r["orig_ok"] for r in rows),
        "legacy_pass": sum(r["legacy_ok"] for r in rows),
        "strict_pass": sum(r["strict_ok"] for r in rows),
        "flips": sum(r["flip"] for r in rows),
        "flip_rows": [r for r in rows if r["flip"] or (r["legacy_ok"] != r["orig_ok"])],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results-dir", default=str(HERE.parent.parent / "test_results" / "atlas_traj"))
    ap.add_argument("--out", default=str(HERE.parent.parent / "draft_iclr"))
    args = ap.parse_args()

    root = Path(args.results_dir)
    runs = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        r = audit_run_dir(d)
        if r:
            runs.append(r)

    def pct(a, b):
        return f"{100*a/b:.1f}" if b else "-"

    lines = ["# G-B1 parser-sensitivity audit (legacy nearest-of-<=4 vs strict single-number)",
             "", f"Re-scored from raw answer files under `{root}`.", "",
             "| run | n | lost | orig% | legacy% | strict% | strict-legacy (pp) | flips |",
             "|---|---|---|---|---|---|---|---|"]
    T = {"n": 0, "lost": 0, "o": 0, "l": 0, "s": 0, "f": 0}
    for r in runs:
        n = r["entries"]
        d_pp = (r["strict_pass"] - r["legacy_pass"]) * 100.0 / n if n else 0.0
        lines.append(f"| {r['run']} | {n} | {r['lost_files']} | {pct(r['orig_pass'], n)} | "
                     f"{pct(r['legacy_pass'], n)} | {pct(r['strict_pass'], n)} | "
                     f"{d_pp:+.1f} | {r['flips']} |")
        T["n"] += n; T["lost"] += r["lost_files"]; T["o"] += r["orig_pass"]
        T["l"] += r["legacy_pass"]; T["s"] += r["strict_pass"]; T["f"] += r["flips"]
    if T["n"]:
        lines.append(f"| **TOTAL** | {T['n']} | {T['lost']} | {pct(T['o'], T['n'])} | "
                     f"{pct(T['l'], T['n'])} | {pct(T['s'], T['n'])} | "
                     f"{(T['s']-T['l'])*100.0/T['n']:+.1f} | {T['f']} |")
    lines += ["", "orig% = the score recorded at run time (whatever parser that code had); "
              "legacy%/strict% = today's uniform re-scoring. flips = cases where the two "
              "parsers disagree on pass/fail.", ""]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit_parser_results.md").write_text("\n".join(lines))
    json.dump({"results_dir": str(root), "runs": runs}, open(out / "audit_parser_results.json", "w"), indent=2)
    print("\n".join(lines))
    print(f"\nwrote {out/'audit_parser_results.md'} and .json  ({len(runs)} runs audited)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
