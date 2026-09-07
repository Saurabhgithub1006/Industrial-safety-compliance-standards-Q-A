"""Reciprocal Rank Fusion -- combines multiple rankers' outputs into one ranking
without needing their raw scores to be on comparable scales (BM25 and cosine
similarity aren't). Per artifacts/system-arch-and-roadmap.md Sec 4.1: "simple
combination (reciprocal rank fusion) is enough; no need for a learned reranker at
this scale."
"""

from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """`rankings`: one ranked list of document indices (best first) per ranker.
    Returns a combined score per document index -- higher is better. `k=60` is the
    standard RRF constant (Cormack et al.); it just damps how much a #1 rank in one
    ranker can dominate over broad agreement across rankers."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores
