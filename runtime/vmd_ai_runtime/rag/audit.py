"""
audit.py — measure the current BM25 baseline.

Usage (as a module):

    from vmd_ai_runtime.rag.audit import audit
    report = audit(
        corpus_root="tests/fixtures/docs",
        golden_path="tests/fixtures/rag_golden.jsonl",
        k=5,
    )
    print(report.to_text())

Usage (as a CLI):

    python -m vmd_ai_runtime.rag.audit \\
        --corpus tests/fixtures/docs \\
        --golden tests/fixtures/rag_golden.jsonl \\
        --out tests/fixtures/rag_baseline.json

The audit is **read-only** and **deterministic**. Same corpus + same
golden set → byte-identical report (timestamps excluded).

It builds an in-memory index from the corpus (same chunker + BM25
that ``docs_search.py`` uses today) so the audit doesn't depend on
``~/.vmdai/docs_index/`` being present. That makes the audit safe to
run in CI, in tests, and on fresh checkouts.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..docs_search import (
    BM25State,
    Chunk,
    chunk_markdown,
    fit_bm25,
    score_bm25,
    tokenize,
)
from .golden import GoldenItem, load_golden, summarize as summarize_golden
from .metrics import mean, mrr_at_k, ndcg_at_k, percentile, recall_at_k


# ----------------------------------------------------------------------
# Corpus loading
# ----------------------------------------------------------------------

def _scope_for(rel_path: Path) -> str:
    """Pick a scope tag from the on-disk layout.

    The fixture corpus mirrors the production tree:
        vmd_ref/*.md      → scope=vmd_ref
        user_guide/*.md   → scope=user_guide
        skills/**/SKILL.md → scope=skills
    """
    parts = rel_path.parts
    if not parts:
        return "all"
    first = parts[0]
    if first in ("vmd_ref", "user_guide", "skills"):
        return first
    return "all"


def load_corpus(corpus_root: str | Path) -> List[Chunk]:
    """Walk ``corpus_root`` and chunk every .md file with the v1 chunker.

    Deterministic order: files are sorted by relative path so the
    chunker output is stable across runs.
    """
    root = Path(corpus_root)
    if not root.exists():
        raise FileNotFoundError(f"corpus root not found: {root}")
    md_files = sorted(p for p in root.rglob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"no .md files under {root}")
    chunks: List[Chunk] = []
    for path in md_files:
        rel = path.relative_to(root)
        scope = _scope_for(rel)
        text = path.read_text(encoding="utf-8")
        # Store the relative path so golden-set suffix matches are
        # consistent regardless of where the repo is checked out.
        chunks.extend(chunk_markdown(str(rel), text, scope))
    return chunks


# ----------------------------------------------------------------------
# Report dataclasses
# ----------------------------------------------------------------------

@dataclass
class CorpusStats:
    chunk_count: int
    avg_tokens: float
    median_tokens: float
    p95_tokens: float
    max_tokens: int
    longest_chunk_id: str
    vocab_size: int
    hapax_fraction: float        # fraction of vocab seen in exactly 1 doc
    top_tokens: List[Tuple[str, int]]  # top-10 by doc frequency
    scope_counts: Dict[str, int]


@dataclass
class QueryResult:
    qid: str
    query: str
    tags: List[str]
    recall_at_k: float
    mrr_at_k: float
    ndcg_at_k: float
    latency_ms: float
    top_hits: List[Tuple[str, str, float]]   # (source, section, score) top-3
    hit_rank: Optional[int]                   # 1-based; None if no hit


@dataclass
class AuditReport:
    corpus_root: str
    golden_path: str
    k: int
    chunker: str
    retriever: str
    bm25_params: Dict[str, float]
    corpus: CorpusStats
    golden_summary: Dict
    queries: List[QueryResult]
    summary: Dict
    elapsed_ms: float

    def to_dict(self) -> Dict:
        return {
            "corpus_root": self.corpus_root,
            "golden_path": self.golden_path,
            "k": self.k,
            "chunker": self.chunker,
            "retriever": self.retriever,
            "bm25_params": self.bm25_params,
            "corpus": asdict(self.corpus),
            "golden_summary": self.golden_summary,
            "queries": [asdict(q) for q in self.queries],
            "summary": self.summary,
            "elapsed_ms": self.elapsed_ms,
        }

    def to_text(self) -> str:
        lines: List[str] = []
        s = self.summary
        c = self.corpus
        lines.append(f"=== RAG audit · {self.retriever} · {self.chunker} ===")
        lines.append(f"corpus_root  : {self.corpus_root}")
        lines.append(f"golden_path  : {self.golden_path}")
        lines.append(f"chunks       : {c.chunk_count}   "
                     f"(avg={c.avg_tokens:.1f} median={c.median_tokens:.0f} "
                     f"p95={c.p95_tokens:.0f} max={c.max_tokens})")
        lines.append(f"vocab        : |V|={c.vocab_size}  "
                     f"hapax={c.hapax_fraction:.0%}")
        lines.append(f"scope counts : {c.scope_counts}")
        lines.append(f"bm25 params  : k1={self.bm25_params['k1']} "
                     f"b={self.bm25_params['b']}")
        lines.append("")
        lines.append(f"--- queries (k={self.k}, n={len(self.queries)}) ---")
        for q in self.queries:
            mark = "✓" if q.hit_rank else "✗"
            lines.append(
                f"  {mark}  {q.qid:<20}  R@k={q.recall_at_k:.2f}  "
                f"MRR={q.mrr_at_k:.2f}  nDCG={q.ndcg_at_k:.2f}  "
                f"lat={q.latency_ms:.1f}ms  rank={q.hit_rank}"
            )
        lines.append("")
        lines.append("--- summary ---")
        lines.append(f"  mean Recall@{self.k}: {s['mean_recall_at_k']:.3f}")
        lines.append(f"  mean MRR@{self.k}   : {s['mean_mrr_at_k']:.3f}")
        lines.append(f"  mean nDCG@{self.k}  : {s['mean_ndcg_at_k']:.3f}")
        lines.append(f"  miss queries     : {s['miss_count']}/{len(self.queries)}")
        lines.append(f"  latency p50      : {s['latency_p50_ms']:.2f} ms")
        lines.append(f"  latency p95      : {s['latency_p95_ms']:.2f} ms")
        lines.append(f"  elapsed total    : {self.elapsed_ms:.1f} ms")
        if s.get("failure_modes"):
            lines.append("")
            lines.append("--- failure-mode samples ---")
            for fm in s["failure_modes"]:
                lines.append(f"  {fm['qid']:<20}  '{fm['query']}'")
                lines.append(f"    tags: {fm['tags']}")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# Audit
# ----------------------------------------------------------------------

def _corpus_stats(chunks: List[Chunk], tokenized: List[List[str]],
                  scope_counts: Dict[str, int]) -> CorpusStats:
    lengths = [len(t) for t in tokenized]
    if not lengths:
        return CorpusStats(
            chunk_count=0, avg_tokens=0.0, median_tokens=0.0,
            p95_tokens=0.0, max_tokens=0, longest_chunk_id="",
            vocab_size=0, hapax_fraction=0.0,
            top_tokens=[], scope_counts={},
        )
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    hapax = sum(1 for n in df.values() if n == 1)
    longest_idx = max(range(len(lengths)), key=lambda i: lengths[i])
    return CorpusStats(
        chunk_count=len(chunks),
        avg_tokens=mean(lengths),
        median_tokens=float(statistics.median(lengths)),
        p95_tokens=percentile(lengths, 95),
        max_tokens=int(max(lengths)),
        longest_chunk_id=chunks[longest_idx].id,
        vocab_size=len(df),
        hapax_fraction=hapax / len(df) if df else 0.0,
        top_tokens=df.most_common(10),
        scope_counts=dict(scope_counts),
    )


def _scope_counts_from_chunks(chunks: List[Chunk]) -> Dict[str, int]:
    out: Counter[str] = Counter()
    for c in chunks:
        out[c.scope] += 1
    return dict(out)


def _run_query(
    item: GoldenItem,
    chunks: List[Chunk],
    bm25: BM25State,
    k: int,
) -> QueryResult:
    q_tokens = tokenize(item.query)
    t0 = time.perf_counter()
    scores = score_bm25(bm25, q_tokens)
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    # Drop zero-score docs to mimic the live DocsSearch behavior.
    ranked = [i for i in ranked if scores[i] > 0]
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    retrieved_dicts = [
        {"source": chunks[i].source, "section": chunks[i].section}
        for i in ranked[:k]
    ]
    r_at_k = recall_at_k(retrieved_dicts, item.matches, k)
    mrr = mrr_at_k(retrieved_dicts, item.matches, k)
    ndcg = ndcg_at_k(retrieved_dicts, item.matches, k)

    hit_rank: Optional[int] = None
    for i, idx in enumerate(ranked[:k], start=1):
        if item.matches({"source": chunks[idx].source,
                         "section": chunks[idx].section}):
            hit_rank = i
            break

    top_hits: List[Tuple[str, str, float]] = []
    for idx in ranked[:3]:
        top_hits.append((
            chunks[idx].source,
            chunks[idx].section,
            round(float(scores[idx]), 4),
        ))

    return QueryResult(
        qid=item.qid,
        query=item.query,
        tags=list(item.tags),
        recall_at_k=r_at_k,
        mrr_at_k=mrr,
        ndcg_at_k=ndcg,
        latency_ms=elapsed_ms,
        top_hits=top_hits,
        hit_rank=hit_rank,
    )


def audit(
    corpus_root: str | Path,
    golden_path: str | Path,
    *,
    k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
) -> AuditReport:
    """Run the full audit. Returns an ``AuditReport``."""
    t_start = time.perf_counter()

    chunks = load_corpus(corpus_root)
    scope_counts = _scope_counts_from_chunks(chunks)
    tokenized = [tokenize(c.text) for c in chunks]
    bm25 = fit_bm25(tokenized, k1=k1, b=b)
    corpus = _corpus_stats(chunks, tokenized, scope_counts)

    golden_items = load_golden(golden_path)
    queries: List[QueryResult] = []
    for item in golden_items:
        queries.append(_run_query(item, chunks, bm25, k))

    latencies = [q.latency_ms for q in queries]
    misses = [q for q in queries if q.hit_rank is None]
    summary = {
        "mean_recall_at_k": mean([q.recall_at_k for q in queries]),
        "mean_mrr_at_k":    mean([q.mrr_at_k    for q in queries]),
        "mean_ndcg_at_k":   mean([q.ndcg_at_k   for q in queries]),
        "miss_count": len(misses),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "failure_modes": [
            {"qid": q.qid, "query": q.query, "tags": list(q.tags)}
            for q in misses
        ],
    }

    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    return AuditReport(
        corpus_root=str(corpus_root),
        golden_path=str(golden_path),
        k=k,
        chunker="v1 (docs_search.chunk_markdown)",
        retriever="BM25 (docs_search.fit_bm25)",
        bm25_params={"k1": k1, "b": b},
        corpus=corpus,
        golden_summary=summarize_golden(golden_items),
        queries=queries,
        summary=summary,
        elapsed_ms=elapsed_ms,
    )


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vmd-ai-rag-audit",
        description="Measure the current BM25 retriever against a golden set.",
    )
    p.add_argument("--corpus", required=True,
                   help="Corpus root (directory of .md files)")
    p.add_argument("--golden", required=True,
                   help="Path to the golden set JSONL")
    p.add_argument("--out", default=None,
                   help="Write report JSON here (default: stdout)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--k1", type=float, default=1.5)
    p.add_argument("--b", type=float, default=0.75)
    p.add_argument("--text", action="store_true",
                   help="Print human-readable text report to stdout")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    report = audit(
        corpus_root=args.corpus,
        golden_path=args.golden,
        k=args.k,
        k1=args.k1,
        b=args.b,
    )
    if args.text or not args.out:
        print(report.to_text())
    if args.out:
        Path(args.out).write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
