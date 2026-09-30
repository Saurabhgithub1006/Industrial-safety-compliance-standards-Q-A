"""Hand-rolled Okapi BM25, zero dependency. The lexical/keyword leg of hybrid
retrieval: catches exact term and clause-number matches."""

from __future__ import annotations

import math
import re
from collections import Counter

from .stemming import stem

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, stemmed tokens."""
    return [stem(t) for t in _TOKEN_RE.findall(text.lower())]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._doc_freqs: list[Counter[str]] = []
        self._doc_lens: list[int] = []
        self._avgdl = 0.0
        self._df: Counter[str] = Counter()
        self._n = 0

    def fit(self, documents: list[str]) -> None:
        doc_tokens = [tokenize(d) for d in documents]
        self._doc_freqs = [Counter(toks) for toks in doc_tokens]
        self._doc_lens = [len(toks) for toks in doc_tokens]
        self._n = len(documents)
        self._avgdl = sum(self._doc_lens) / self._n if self._n else 0.0
        self._df = Counter()
        for freqs in self._doc_freqs:
            for term in freqs:
                self._df[term] += 1

    def _idf(self, term: str) -> float:
        n_qi = self._df.get(term, 0)
        # +1 smoothing keeps idf non-negative (Okapi BM25+ convention).
        return math.log((self._n - n_qi + 0.5) / (n_qi + 0.5) + 1)

    def score_all(self, query: str) -> list[float]:
        """BM25 score per document, in index order."""
        scores = [0.0] * self._n
        if self._n == 0:
            return scores
        for term in tokenize(query):
            idf = self._idf(term)
            if idf <= 0:
                continue
            for i in range(self._n):
                f = self._doc_freqs[i].get(term, 0)
                if f == 0:
                    continue
                dl = self._doc_lens[i]
                norm = (1 - self.b + self.b * dl / self._avgdl) if self._avgdl else 1.0
                denom = f + self.k1 * norm
                scores[i] += idf * (f * (self.k1 + 1)) / denom
        return scores
