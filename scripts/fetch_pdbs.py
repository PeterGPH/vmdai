#!/usr/bin/env python3
"""
fetch_pdbs.py — download every PDB referenced by a suite JSON.

Reads `pdb` fields from `evals/rag_wiki_suite_v1.json` (or any suite that
follows the same schema) and downloads each unique PDB into a chosen
directory so the replay step (rag_wiki_ab_extract.py → VMD) can resolve
`mol new <id>.pdb` without 404ing.

Usage:
    python scripts/fetch_pdbs.py evals/rag_wiki_suite_v1.json \\
        --out-dir rag_wiki_results/replay

    # also fetch any PDB filename mentioned anywhere in the prompt text
    python scripts/fetch_pdbs.py evals/rag_wiki_suite_v1.json \\
        --out-dir rag_wiki_results/replay --scan-prompts

This is a no-state HTTP fetch — re-running it is safe; files already
present are left alone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List, Set


RCSB_URL = "https://files.rcsb.org/download/{pdb}.pdb"
PDB_ID_RE = re.compile(r"\b([0-9][A-Za-z0-9]{3})\b")


def collect_pdb_ids(
    suite_path: Path,
    scan_prompts: bool,
) -> List[str]:
    raw = json.loads(suite_path.read_text(encoding="utf-8"))
    items = raw.get("prompts") or []
    ids: Set[str] = set()
    for entry in items:
        if not isinstance(entry, dict):
            continue
        pdb = entry.get("pdb")
        if isinstance(pdb, str) and PDB_ID_RE.fullmatch(pdb.strip()):
            ids.add(pdb.strip().upper())
        if scan_prompts:
            text = " ".join(
                str(entry.get(k) or "") for k in ("prompt", "id")
            )
            for m in PDB_ID_RE.findall(text):
                # PDB IDs start with a digit; the regex enforces that.
                # Filter out obvious false positives like 4PIR mid-sentence —
                # actually 4PIR is a valid PDB ID. Trust the regex; this
                # is best-effort.
                ids.add(m.upper())
    return sorted(ids)


def download(pdb_id: str, out_dir: Path) -> str:
    """Download one PDB. Returns "ok" | "exists" | "fail:<reason>"."""
    url = RCSB_URL.format(pdb=pdb_id)
    dst = out_dir / f"{pdb_id.lower()}.pdb"
    if dst.exists() and dst.stat().st_size > 0:
        return "exists"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vmd_ai-fetch_pdbs"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if not data:
            return "fail:empty"
        dst.write_bytes(data)
        return "ok"
    except urllib.error.HTTPError as exc:
        return f"fail:http {exc.code}"
    except urllib.error.URLError as exc:
        return f"fail:url {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return f"fail:{type(exc).__name__} {exc}"


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument(
        "suite",
        help="Path to a suite JSON (e.g. evals/rag_wiki_suite_v1.json).",
    )
    ap.add_argument(
        "--out-dir", default="rag_wiki_results/replay",
        help="Directory to drop downloaded *.pdb files into. "
             "Default: rag_wiki_results/replay (where the extractor "
             "expects them).",
    )
    ap.add_argument(
        "--scan-prompts", action="store_true",
        help="Also extract 4-character PDB IDs from prompt text (in "
             "addition to the dedicated `pdb` field). Useful if a "
             "prompt references multiple structures.",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    suite_path = Path(args.suite).expanduser().resolve()
    if not suite_path.exists():
        print(f"error: suite not found: {suite_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = collect_pdb_ids(suite_path, args.scan_prompts)
    if not ids:
        print(f"[fetch] no PDB ids found in {suite_path}", file=sys.stderr)
        return 1

    print(f"[fetch] {len(ids)} unique PDB ids → {out_dir}")
    n_ok = n_skip = n_fail = 0
    for pid in ids:
        status = download(pid, out_dir)
        if status == "ok":
            n_ok += 1
            tag = "ok"
        elif status == "exists":
            n_skip += 1
            tag = "skip"
        else:
            n_fail += 1
            tag = status
        print(f"  {pid}  {tag}")
    print(f"\n[fetch] done — {n_ok} downloaded, {n_skip} already present, "
          f"{n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
