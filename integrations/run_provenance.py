#!/usr/bin/env python3
"""run_provenance.py — append one provenance line per benchmark run.

Every runner (run_atlas_parallel.sh, run_25cell_retrieval.sh,
run_multistructure.py, run_heldout.py, explore_arm/run_explore.py) calls
this once per run, so each RUN in run_manifest.jsonl maps back to the code
that produced it (spec §0 "M0 repository tasks").

  python integrations/run_provenance.py <manifest.jsonl> key=value [key=value ...]

Always recorded: ts (UTC), commit, describe, vmd_ai_runtime_path (resolved the
way vmd_ai_agent.py resolves it: the config's value, else $VMD_AI_RUNTIME_PATH,
else "runtime", relative paths against the repo root).  Pass config=<path> to
read vmd_ai_runtime_path from a harness config.  Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(repo: str, *args: str) -> Optional[str]:
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def resolve_runtime_path(repo: str, config_path: str = "", configured: str = "") -> str:
    value = configured
    if not value and config_path and os.path.isfile(config_path):
        with open(config_path, encoding="utf-8") as fh:
            value = str(json.load(fh).get("vmd_ai_runtime_path") or "")
    value = os.path.expanduser(value or os.environ.get("VMD_AI_RUNTIME_PATH") or "runtime")
    if not os.path.isabs(value):
        value = os.path.join(repo, value)
    return os.path.realpath(value)


def append_run_manifest(manifest_path: str, repo: str, **fields: str) -> Dict[str, str]:
    """Append one JSON line to ``manifest_path`` and return the record."""
    record: Dict[str, str] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git(repo, "rev-parse", "--short", "HEAD") or "nogit",
        "describe": _git(repo, "describe", "--tags", "--always", "--dirty") or "-",
    }
    record.update({key: str(value) for key, value in fields.items()})
    record["vmd_ai_runtime_path"] = resolve_runtime_path(
        repo, fields.get("config", ""), fields.get("vmd_ai_runtime_path", "")
    )
    parent = os.path.dirname(os.path.abspath(manifest_path))
    os.makedirs(parent, exist_ok=True)
    with open(manifest_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: run_provenance.py <manifest.jsonl> key=value ...", file=sys.stderr)
        return 2
    manifest, pairs = args[0], args[1:]
    fields: Dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            print(f"run_provenance.py: expected key=value, got {pair!r}", file=sys.stderr)
            return 2
        fields[key] = value
    record = append_run_manifest(manifest, REPO, **fields)
    print(f"== provenance -> {manifest}\n   {record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
