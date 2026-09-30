"""Reciprocal Rank Fusion: combines rankers' outputs without needing scores
on a common scale (BM25 and cosine similarity aren't)."""

from __future__ import annotations


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> dict[int, float]:
    """Combine ranked index lists into one score per index. k=60 is the
    standard RRF constant."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return scores
