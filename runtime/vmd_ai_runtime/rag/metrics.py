"""
metrics.py — retrieval metrics. Pure stdlib, deterministic.

A retrieved list is a list of dicts that each carry ``source`` and
``section`` (the same shape ``DocsSearch.search`` returns). Relevance
is decided by a ``GoldenItem.matches(chunk)`` predicate so the metric
implementations stay model-agnostic.

Implementations follow the standard textbook definitions; we avoid
sklearn so the runtime has zero extra deps and behavior is reproducible
across machines.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Sequence


# A predicate type: takes a chunk dict, returns True if it's relevant.
RelevancePredicate = Callable[[Dict], bool]


def recall_at_k(
    retrieved: Sequence[Dict],
    is_relevant: RelevancePredicate,
    k: int,
    *,
    total_relevant: int | None = None,
) -> float:
    """Fraction of relevant items appearing in the top-k.

    By default we compute "hit-rate@k" — 1 if any relevant item is in
    the top-k, else 0 — because for golden sets with multiple valid
    answers, any one of them counts as success. Pass ``total_relevant``
    to compute true recall (matched / total_relevant).
    """
    if k <= 0:
        return 0.0
    matched = sum(1 for c in retrieved[:k] if is_relevant(c))
    if total_relevant is not None and total_relevant > 0:
        return matched / total_relevant
    return 1.0 if matched > 0 else 0.0


def mrr_at_k(
    retrieved: Sequence[Dict],
    is_relevant: RelevancePredicate,
    k: int,
) -> float:
    """Reciprocal rank of the first relevant hit in the top-k, else 0."""
    if k <= 0:
        return 0.0
    for i, c in enumerate(retrieved[:k], start=1):
        if is_relevant(c):
            return 1.0 / i
    return 0.0


def ndcg_at_k(
    retrieved: Sequence[Dict],
    is_relevant: RelevancePredicate,
    k: int,
) -> float:
    """Binary-relevance nDCG@k.

    DCG = Σ rel_i / log2(i + 1),  i ∈ 1..k
    IDCG = DCG of an oracle ranking with all hits at the top.

    Returns 0.0 when there is no relevant item in the corpus (IDCG=0)
    or when k <= 0; never NaN.
    """
    if k <= 0:
        return 0.0
    gains: List[int] = [1 if is_relevant(c) else 0 for c in retrieved[:k]]
    dcg = sum(g / math.log2(i + 1) for i, g in enumerate(gains, start=1))
    total_hits = sum(gains)
    # Ideal DCG places `total_hits` ones at the top.
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, total_hits + 1))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def mean(values: Sequence[float]) -> float:
    """Mean with a 0.0 fallback so empty inputs don't raise."""
    return (sum(values) / len(values)) if values else 0.0


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0..100). Pure stdlib.

    Matches numpy's default (``method='linear'``). Returns 0.0 for empty
    input.
    """
    if not values:
        return 0.0
    if q <= 0:
        return float(min(values))
    if q >= 100:
        return float(max(values))
    s = sorted(values)
    pos = (q / 100.0) * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(s[lo])
    frac = pos - lo
    return float(s[lo] * (1 - frac) + s[hi] * frac)
