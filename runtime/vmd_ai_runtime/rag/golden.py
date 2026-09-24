"""
golden.py — load and validate the RAG golden set.

The golden set is a JSONL file. One line per query:

    {
      "qid": "para-tachyon",
      "query": "how do I take a high quality ray traced picture",
      "relevant": [["vmd_ref/render.md", "render TachyonInternal"]],
      "tags": ["paraphrase", "expected-bm25-fail"],
      "note": "free-form explanation"
    }

Why match on (source_suffix, section) rather than chunk id:
    Chunk ids are an artifact of whichever chunker built the index.
    We're about to ship a v2 chunker, so id-based pinning would break
    on day one. (source_suffix, section) survives chunker churn as
    long as the heading text stays the same.

    ``source_suffix`` is a suffix-match (chunk.source endswith suffix)
    so the same golden set works against fixtures and the real
    ~/.vmdai/docs_index/ corpus without rewriting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class GoldenItem:
    qid: str
    query: str
    relevant: Tuple[Tuple[str, str], ...]   # ((source_suffix, section), ...)
    tags: Tuple[str, ...] = ()
    note: str = ""

    def matches(self, chunk: Dict) -> bool:
        """True iff ``chunk`` (a dict with 'source' and 'section') is
        one of this item's relevant chunks.
        """
        src = str(chunk.get("source", ""))
        sec = str(chunk.get("section", ""))
        for rel_src, rel_sec in self.relevant:
            if src.endswith(rel_src) and sec == rel_sec:
                return True
        return False


class GoldenSetError(ValueError):
    """Raised when the golden set file is malformed."""


def load_golden(path: str | Path) -> List[GoldenItem]:
    """Load and validate a JSONL golden set.

    Raises ``GoldenSetError`` with a 1-based line number on the first
    malformed entry, so authors don't have to grep for which line they
    fat-fingered.
    """
    p = Path(path)
    if not p.exists():
        raise GoldenSetError(f"golden set not found: {p}")
    items: List[GoldenItem] = []
    seen_qids: set[str] = set()
    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise GoldenSetError(f"line {lineno}: invalid JSON: {e}") from e
            item = _to_item(obj, lineno)
            if item.qid in seen_qids:
                raise GoldenSetError(f"line {lineno}: duplicate qid {item.qid!r}")
            seen_qids.add(item.qid)
            items.append(item)
    if not items:
        raise GoldenSetError(f"golden set {p} is empty")
    return items


def _to_item(obj: Dict, lineno: int) -> GoldenItem:
    for key in ("qid", "query", "relevant"):
        if key not in obj:
            raise GoldenSetError(f"line {lineno}: missing required field {key!r}")
    qid = str(obj["qid"]).strip()
    if not qid:
        raise GoldenSetError(f"line {lineno}: empty qid")
    query = str(obj["query"]).strip()
    if not query:
        raise GoldenSetError(f"line {lineno}: empty query")
    rel_raw = obj["relevant"]
    if not isinstance(rel_raw, list) or not rel_raw:
        raise GoldenSetError(f"line {lineno}: 'relevant' must be a non-empty list")
    relevant: List[Tuple[str, str]] = []
    for i, pair in enumerate(rel_raw):
        if (not isinstance(pair, (list, tuple))) or len(pair) != 2:
            raise GoldenSetError(
                f"line {lineno}: relevant[{i}] must be [source_suffix, section]"
            )
        src, sec = pair
        if not isinstance(src, str) or not isinstance(sec, str):
            raise GoldenSetError(
                f"line {lineno}: relevant[{i}] entries must be strings"
            )
        if not src or not sec:
            raise GoldenSetError(
                f"line {lineno}: relevant[{i}] has empty source or section"
            )
        relevant.append((src, sec))
    tags = tuple(str(t) for t in obj.get("tags", ()) or ())
    note = str(obj.get("note", "") or "")
    return GoldenItem(
        qid=qid,
        query=query,
        relevant=tuple(relevant),
        tags=tags,
        note=note,
    )


def summarize(items: Iterable[GoldenItem]) -> Dict:
    """Return a small dict suitable for printing or asserting on."""
    items = list(items)
    tag_counts: Dict[str, int] = {}
    for it in items:
        for t in it.tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    return {
        "total": len(items),
        "tag_counts": dict(sorted(tag_counts.items())),
        "avg_relevant_per_query": (
            sum(len(it.relevant) for it in items) / len(items)
            if items else 0.0
        ),
    }
