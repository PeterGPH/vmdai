#!/usr/bin/env python3
"""
inspect_bench.py — read a bench-out/report.json and tell you exactly
what each trial did. Handy for debugging surprising headline numbers
("citation_rate=0%? what did the agent actually do?").

Usage:
    python3 scripts/inspect_bench.py bench-out/report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path, help="Path to report.json")
    p.add_argument(
        "--show-output", action="store_true",
        help="Print the truncated tool output preview for each call.",
    )
    p.add_argument(
        "--show-answer", action="store_true",
        help="Print each trial's final answer text.",
    )
    p.add_argument(
        "--show-wiki-inputs", action="store_true",
        help="Dump every wiki_update / wiki_read call's full input dict — "
             "useful when citation_rate is 0 and you need to see whether "
             "the model is passing the 'sources' field at all.",
    )
    args = p.parse_args(argv)

    if not args.report.exists():
        print(f"error: {args.report} does not exist", file=sys.stderr)
        return 2
    data = json.loads(args.report.read_text(encoding="utf-8"))

    print("== config ==")
    for k, v in sorted(data.get("config", {}).items()):
        print(f"  {k}: {v}")
    print()

    for arm in ("with_wiki", "without_wiki"):
        trials = [t for t in data["trials"] if t["arm"] == arm]
        print(f"== arm: {arm}  ({len(trials)} trials) ==")
        for i, t in enumerate(trials, 1):
            print(f"  [{i}] {t['prompt'][:80]}")
            print(f"      duration: {t['duration_ms']:.0f}ms, "
                  f"error: {t.get('error') or '(none)'}")
            tool_counts = Counter(c["name"] for c in t["tool_calls"])
            tool_str = ", ".join(f"{n}×{c}" for n, c in sorted(tool_counts.items()))
            print(f"      tools: {tool_str or '(none)'}")
            if t.get("pages_read"):
                print(f"      read:  {', '.join(t['pages_read'])}")
            if t.get("pages_updated"):
                print(f"      wrote: {', '.join(t['pages_updated'])}")
            if t.get("sources_cited"):
                print(f"      cited: {', '.join(t['sources_cited'])}")
            if args.show_answer:
                ans = (t.get("final_answer") or "").strip().replace("\n", " ")
                print(f"      answer: {ans[:240]}{'...' if len(ans) > 240 else ''}")
            if args.show_output:
                for j, call in enumerate(t["tool_calls"], 1):
                    preview = (call.get("output_preview") or "")[:120].replace("\n", " ")
                    err = call.get("error") or ""
                    ok = "✓" if call.get("ok") else "✗"
                    print(f"        [{j}] {ok} {call['name']}  {preview}"
                          f"{' ERR: ' + err if err else ''}")
            if args.show_wiki_inputs:
                for j, call in enumerate(t["tool_calls"], 1):
                    if call["name"] not in ("wiki_update", "wiki_read"):
                        continue
                    inp = call.get("input") or {}
                    src = inp.get("sources")
                    # Surface the smoking gun: did the model pass sources?
                    if call["name"] == "wiki_update":
                        page = inp.get("page", "?")
                        reason = (inp.get("reason") or "")[:60]
                        if src is None:
                            srcs = "<sources field OMITTED>"
                        elif not src:
                            srcs = "<sources=[]>"
                        else:
                            srcs = ", ".join(src)
                        print(f"        wiki_update [{j}] page={page}")
                        print(f"            reason: {reason}")
                        print(f"            sources: {srcs}")
                    elif call["name"] == "wiki_read":
                        print(f"        wiki_read [{j}] page={inp.get('page', '?')}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
