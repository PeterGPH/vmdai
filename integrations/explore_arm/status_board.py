#!/usr/bin/env python3
"""status_board.py — one-command progress board for the atlas-traj runs on this machine.

  python3 status_board.py            # board: every run -> COMPLETE (official %) / RUNNING / STALLED
  python3 status_board.py --pulse    # + protocol vitals for unfinished explore cells
  python3 status_board.py --watch    # refresh the board every 60s

COMPLETE  = summary.json exists (written only after the final table) -> official pass rate.
RUNNING   = a live process carries the tag.  STALLED = neither -> investigate before relaunch.
Timeouts are counted per run and must stay 0 (nonzero = lower --concurrency).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.normpath(os.path.join(HERE, "..", "..", "test_results", "atlas_traj"))
PATTERNS = ("explore_*", "*easyfill*", "*easyfix*", "*_claude_*", "*qwen3*")


def live_tags():
    try:
        out = subprocess.run(["pgrep", "-af", "python"], capture_output=True, text=True).stdout
        return set(re.findall(r"--tag (\S+)", out))
    except Exception:  # noqa: BLE001
        return set()


def run_dirs():
    seen = []
    for p in PATTERNS:
        seen += [d for d in glob.glob(os.path.join(RESULTS, p)) if os.path.isdir(d)]
    return sorted(set(seen))


def board():
    live = live_tags()
    done = 0
    rows = []
    for d in run_dirs():
        tag = os.path.basename(d)
        n = len(glob.glob(d + "/*.lab.json")) or len(glob.glob(d + "/*.response.txt"))
        exp = 498 if tag.endswith("_hard") else 465
        tmo = len([f for f in glob.glob(d + "/failures/*.log")
                   if "timed out after" in open(f, errors="replace").read()])
        summ = os.path.join(d, "summary.json")
        if os.path.exists(summ):
            det = json.load(open(summ))
            oks = [v.get("ok") for v in det.values() if isinstance(v, dict)]
            p = sum(1 for o in oks if o is True)
            t = sum(1 for o in oks if o is not None)
            status = f"COMPLETE   pass {p:3}/{t} = {100*p/max(1,t):5.1f}%"
            done += 1
        elif tag in live:
            status = "RUNNING"
        else:
            status = "STALLED?   (no summary.json, no live process)"
        warn = f"  !! {tmo} TIMEOUTS" if tmo else ""
        rows.append(f"{tag:32} {n:4}/{exp:4}  {status}{warn}")
    print(f"== atlas-traj status board  ({done} complete / {len(rows)} tracked) ==")
    print("\n".join(rows) or "(no tracked runs found)")


def pulse():
    keys = ("experiments", "notes", "commits", "commit_rejections",
            "would_reject_commits", "error_recoveries", "loop_nudges")
    print("\n== protocol pulse (unfinished explore cells; per-task averages) ==")
    for d in run_dirs():
        tag = os.path.basename(d)
        if not tag.startswith("explore_") or os.path.exists(os.path.join(d, "summary.json")):
            continue
        fs = glob.glob(d + "/*.lab.json")
        if not fs:
            print(f"{tag:32} (no tasks yet)")
            continue
        agg = dict.fromkeys(keys, 0)
        for f in fs:
            dd = json.load(open(f))
            for k in keys:
                agg[k] += dd.get(k, 0)
        n = len(fs)
        avg = " ".join(f"{k.split('_')[0][:4]}:{v/n:.1f}" for k, v in agg.items())
        print(f"{tag:32} {n:4} tasks  {avg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pulse", action="store_true")
    ap.add_argument("--watch", action="store_true")
    args = ap.parse_args()
    while True:
        board()
        if args.pulse:
            pulse()
        if not args.watch:
            return 0
        sys.stdout.flush()
        time.sleep(60)
        print("\n" + "=" * 72 + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
