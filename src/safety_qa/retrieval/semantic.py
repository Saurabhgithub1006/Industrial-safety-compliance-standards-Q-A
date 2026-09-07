"""Semantic leg of hybrid retrieval: TF-IDF + truncated SVD (LSA), not a neural
embedding model.

Why: per the Phase 2 kickoff decision, real neural embeddings (Voyage AI, OpenAI,
a local sentence-transformers model) need either an API key or a heavy install --
neither is a hard requirement to demonstrate hybrid retrieval at this corpus's
scale. TF-IDF+LSA is a legitimate, fully local, explainable "semantic-ish" signal:
it captures term co-occurrence patterns beyond exact keyword overlap (so a query
using different wording than the clause can still match), at lower quality than
neural embeddings on paraphrase-heavy queries.

This is intentionally isolated behind the same `fit`/`score_all` shape as
`BM25Index` so swapping in a real embedding provider later touches only this file,
not `Retriever` or anything upstream of it.
"""

from __future__ import annotations

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer

from .bm25 import tokenize as _stemmed_tokenize


class SemanticIndex:
    def __init__(self, n_components: int = 50, random_state: int = 42):
        self.n_components = n_components
        self.random_state = random_state
        self._vectorizer: TfidfVectorizer | None = None
        self._svd: TruncatedSVD | None = None
        self._doc_vectors: np.ndarray | None = None

    def fit(self, documents: list[str]) -> None:
        # Same stemmed tokenizer as the BM25 leg (see stemming.py) -- otherwise
        # this leg would miss the exact morphological-variant matches it exists
        # to catch, for the same reason BM25 did before stemming was added.
        self._vectorizer = TfidfVectorizer(
            tokenizer=_stemmed_tokenize, token_pattern=None, stop_words=None, min_df=1
        )
        tfidf = self._vectorizer.fit_transform(documents)
        n_comp = max(1, min(self.n_components, tfidf.shape[1] - 1, tfidf.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=n_comp, random_state=self.random_state)
        reduced = self._svd.fit_transform(tfidf)
        self._doc_vectors = _l2_normalize(reduced)

    def score_all(self, query: str) -> list[float]:
        """Cosine similarity between `query` and every indexed document, in index
        order. Returns all zeros for an empty/out-of-vocabulary query rather than
        raising -- callers (the hybrid retriever) just get no signal from this leg."""
        assert self._vectorizer is not None and self._svd is not None and self._doc_vectors is not None, \
            "call fit() before score_all()"
        q_tfidf = self._vectorizer.transform([query])
        q_reduced = self._svd.transform(q_tfidf)
        q_norm = np.linalg.norm(q_reduced[0])
        if q_norm == 0:
            return [0.0] * self._doc_vectors.shape[0]
        q_vec = q_reduced[0] / q_norm
        return (self._doc_vectors @ q_vec).tolist()


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
