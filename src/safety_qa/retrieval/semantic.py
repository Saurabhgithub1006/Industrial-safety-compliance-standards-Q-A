"""Semantic leg of hybrid retrieval: e5-base-v2 sentence embeddings + cosine
similarity. Docs get a "passage: " prefix, queries get "query: ", per the
model's asymmetric convention. See artifacts/changelogs.md CHG-20260911-06.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

_MODEL_NAME = "intfloat/e5-base-v2"


@lru_cache(maxsize=None)
def _load_model(model_name: str):
    """Cached process-wide, not per instance, to avoid reloading a 440MB model."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class SemanticIndex:
    def __init__(self, model_name: str = _MODEL_NAME):
        self.model_name = model_name
        self._doc_vectors: np.ndarray | None = None

    def fit(self, documents: list[str]) -> None:
        model = _load_model(self.model_name)
        prefixed = [f"passage: {d}" for d in documents]
        self._doc_vectors = model.encode(
            prefixed, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True
        )

    def score_all(self, query: str) -> list[float]:
        """Cosine similarity between query and each document, in index order."""
        assert self._doc_vectors is not None, "call fit() before score_all()"
        model = _load_model(self.model_name)
        q_vec = model.encode(f"query: {query}", normalize_embeddings=True, show_progress_bar=False)
        return (self._doc_vectors @ q_vec).tolist()
