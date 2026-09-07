"""Hybrid retriever: BM25 (lexical) + TF-IDF/LSA (semantic) fused with RRF.

The index is built in-memory from the Chunk store at construction time -- at this
corpus's scale (hundreds of clauses, not millions) there's no reason to persist
vectors to disk; `Retriever.from_db(...)` rebuilds the whole index in well under a
second. Persisting/caching becomes worth doing once ingestion covers enough
standards that rebuild time actually matters (Phase 7 territory, not now).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from safety_qa.ingestion.store import list_clauses

from .bm25 import BM25Index
from .chunking import Chunk, build_chunks
from .hybrid import reciprocal_rank_fusion
from .semantic import SemanticIndex


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    rrf_score: float
    bm25_rank: int | None  # 0-based; None if the chunk scored 0 on this leg
    semantic_rank: int | None


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("cannot build a retriever over zero chunks")
        self.chunks = chunks
        texts = [c.index_text for c in chunks]
        self._bm25 = BM25Index()
        self._bm25.fit(texts)
        self._semantic = SemanticIndex()
        self._semantic.fit(texts)

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, standard_id: str) -> "Retriever":
        clauses = list_clauses(conn, standard_id)
        return cls(build_chunks(clauses))

    def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        bm25_scores = self._bm25.score_all(query)
        sem_scores = self._semantic.score_all(query)

        bm25_ranking = _rank_nonzero(bm25_scores)
        sem_ranking = _rank_nonzero(sem_scores)
        bm25_rank_of = {idx: r for r, idx in enumerate(bm25_ranking)}
        sem_rank_of = {idx: r for r, idx in enumerate(sem_ranking)}

        fused = reciprocal_rank_fusion([bm25_ranking, sem_ranking])
        ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

        return [
            RetrievedChunk(
                chunk=self.chunks[idx],
                rrf_score=score,
                bm25_rank=bm25_rank_of.get(idx),
                semantic_rank=sem_rank_of.get(idx),
            )
            for idx, score in ordered
        ]


def _rank_nonzero(scores: list[float]) -> list[int]:
    """Indices sorted best-first, excluding zero-score entries -- a chunk with no
    signal at all from a given leg shouldn't get credit in that leg's ranking just
    because everything left over is tied at zero."""
    return [i for i, s in sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True) if s > 0]
