"""
vmd_ai_runtime.rag — retrieval upgrade workbench.

This subpackage is a side-by-side prototype that takes the existing
pure-BM25 ``docs_search.py`` and lifts it through the stages laid out
in ``docs/rag_upgrade_plan.html``:

    audit.py   — measure the current BM25 baseline against a golden set
    golden.py  — load & validate the golden Q/relevant-section set
    metrics.py — Recall@k, MRR@k, nDCG@k, deterministic & pure-stdlib

Later steps will land:
    chunker.py — heading-aware, code-fence-preserving v2 chunker
    dense.py   — fastembed-backed dense retriever (lazy, optional)
    fuse.py    — reciprocal rank fusion
    rerank.py  — cross-encoder rescoring (flag-gated)

Nothing in here is wired into the live runtime yet. ``docs_search.py``
is the one and only entrypoint for the ``search_docs`` tool until the
eval gate in step 6 says otherwise.
"""

from .golden import GoldenItem, load_golden  # noqa: F401
from .metrics import mrr_at_k, ndcg_at_k, recall_at_k  # noqa: F401

__all__ = [
    "GoldenItem",
    "load_golden",
    "mrr_at_k",
    "ndcg_at_k",
    "recall_at_k",
]
