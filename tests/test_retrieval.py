"""Phase 2 tests: BM25, the semantic (TF-IDF+LSA) leg, RRF fusion, and the exit
criterion itself -- recall@k on the golden eval set meeting the threshold set in
artifacts/system-arch-and-roadmap.md Phase 2 ("recall@k ... >= 0.9 @ k=5"). That last
test is the important one: it turns the roadmap's exit criteria into something CI
actually enforces, not just a claim in a doc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from safety_qa.ingestion.store import connect
from safety_qa.retrieval.bm25 import BM25Index, tokenize
from safety_qa.retrieval.chunking import Chunk, build_chunks
from safety_qa.retrieval.eval_set import GOLDEN_SET, STANDARD_ID, recall_at_k
from safety_qa.retrieval.hybrid import reciprocal_rank_fusion
from safety_qa.retrieval.retriever import Retriever
from safety_qa.retrieval.semantic import SemanticIndex
from safety_qa.retrieval.stemming import stem

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _REPO_ROOT / "data" / "processed" / "corpus.db"


# ---------------------------------------------------------------------------
# stemming.py
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "word,expected_stem",
    [
        ("periodically", "period"),
        ("periodic", "period"),
        ("inspection", "inspect"),
        ("inspected", "inspect"),
        ("withstanding", "withstand"),
        ("devices", "devic"),
        ("device", "devic"),
    ],
)
def test_stem_unifies_morphological_variants(word, expected_stem):
    assert stem(word) == expected_stem


def test_tokenize_applies_stemming():
    assert tokenize("Periodically Inspected Devices") == ["period", "inspect", "devic"]


# ---------------------------------------------------------------------------
# bm25.py
# ---------------------------------------------------------------------------

def test_bm25_ranks_exact_term_match_first():
    docs = [
        "lockout devices shall be durable",
        "employees must receive training on hazardous energy",
        "tagout devices shall indicate hazardous conditions",
    ]
    idx = BM25Index()
    idx.fit(docs)
    scores = idx.score_all("training")
    assert scores[1] > scores[0]
    assert scores[1] > scores[2]


def test_bm25_matches_stemmed_variant():
    idx = BM25Index()
    idx.fit(["periodic inspection is required annually", "training records must be kept"])
    scores = idx.score_all("periodically inspected")
    assert scores[0] > scores[1]


def test_bm25_empty_corpus_does_not_crash():
    idx = BM25Index()
    idx.fit([])
    assert idx.score_all("anything") == []


# ---------------------------------------------------------------------------
# semantic.py
# ---------------------------------------------------------------------------

def test_semantic_index_scores_are_finite_and_bounded():
    idx = SemanticIndex(n_components=2)
    idx.fit(["lockout devices must be durable", "employees receive training", "tagout warns of hazards"])
    scores = idx.score_all("durable lockout devices")
    assert len(scores) == 3
    assert all(-1.0001 <= s <= 1.0001 for s in scores)  # cosine similarity range


# ---------------------------------------------------------------------------
# hybrid.py
# ---------------------------------------------------------------------------

def test_rrf_rewards_agreement_across_rankers():
    # doc 0 is top of both rankers; doc 1 is only ever second.
    scores = reciprocal_rank_fusion([[0, 1, 2], [0, 2, 1]])
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_rrf_combines_rankers_that_disagree():
    scores = reciprocal_rank_fusion([[0, 1], [1, 0]])
    assert scores[0] == pytest.approx(scores[1])


# ---------------------------------------------------------------------------
# chunking.py
# ---------------------------------------------------------------------------

def test_index_text_prepends_title_without_mutating_citable_text():
    chunk = Chunk(
        citation_key="X#(b)/term:foo", standard_id="X", clause_path="(b)",
        section_title="Foo", clause_type="definition", is_normative=True,
        text="A thing that does foo-ing.",
    )
    assert chunk.index_text == "Foo. A thing that does foo-ing."
    assert chunk.text == "A thing that does foo-ing."  # untouched -- still verbatim-quotable


def test_build_chunks_skips_empty_text():
    from safety_qa.ingestion.models import Clause

    clauses = [
        Clause("X", "X#(a)", "(a)", None, 1, None, "", "requirement", True, 1),
        Clause("X", "X#(b)", "(b)", None, 1, None, "real text", "requirement", True, 2),
    ]
    chunks = build_chunks(clauses)
    assert [c.citation_key for c in chunks] == ["X#(b)"]


# ---------------------------------------------------------------------------
# retriever.py + eval_set.py -- end-to-end, against the real ingested corpus
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def retriever():
    if not _DB_PATH.exists():
        pytest.skip("corpus.db not built -- run `python -m safety_qa.ingestion.run_ingest` first")
    conn = connect(str(_DB_PATH))
    return Retriever.from_db(conn, STANDARD_ID)


def test_retriever_finds_exact_definition(retriever):
    results = retriever.retrieve("What is a tagout device?", top_k=5)
    keys = [r.chunk.citation_key for r in results]
    assert f"{STANDARD_ID}#(b)/term:tagout-device" in keys


def test_retriever_top_k_respected(retriever):
    assert len(retriever.retrieve("lockout", top_k=3)) <= 3


def test_recall_at_5_meets_phase_2_exit_criteria(retriever):
    """The roadmap's Phase 2 exit criterion, enforced: recall@5 >= 0.9 on the
    golden eval set. A drop below this on future changes (re-chunking, swapping
    the semantic leg, re-ingesting a changed source) should fail CI, not go
    unnoticed."""
    recall, details = recall_at_k(retriever, GOLDEN_SET, k=5)
    misses = [d["question"] for d in details if not d["hit"]]
    assert recall >= 0.9, f"recall@5 = {recall:.2%}, misses: {misses}"
