"""Semantic leg of hybrid retrieval: e5-base-v2 neural sentence embeddings +
cosine similarity.

Supersedes the original TF-IDF + truncated SVD (LSA) implementation (see git
history / CHG-20260907-02 in artifacts/changelogs.md for why that was the initial
choice -- no API key and an assumed-heavy local-model install at the time). That
reasoning no longer held once torch/transformers turned out to already be present
in this environment with GPU (CUDA) support, making a real embedding model a small
incremental cost instead of a heavy one -- see CHG-20260911-06 in
artifacts/changelogs.md for the switch itself.

e5 models use an asymmetric retrieval convention: indexed documents get a
"passage: " prefix, queries get a "query: " prefix (per the model card;
mismatching these measurably hurts retrieval quality). Embeddings are
L2-normalized at encode time, so cosine similarity is just a dot product.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

_MODEL_NAME = "intfloat/e5-base-v2"


@lru_cache(maxsize=None)
def _load_model(model_name: str):
    """Model load is cached process-wide (not per SemanticIndex instance) -- the
    model itself is stateless and reusable across every corpus/Retriever built in
    the same process, and reloading a ~440MB model per instance would be wasteful
    (and would make the test suite painfully slow)."""
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
        """Cosine similarity between `query` and every indexed document, in index
        order."""
        assert self._doc_vectors is not None, "call fit() before score_all()"
        model = _load_model(self.model_name)
        q_vec = model.encode(f"query: {query}", normalize_embeddings=True, show_progress_bar=False)
        return (self._doc_vectors @ q_vec).tolist()
