"""Tests for backend/ -- the new SQLAlchemy-based storage layer that replaces
SQLite with a portable engine (SQLite here, PostgreSQL in production; same code
either way). Doesn't re-test what safety_qa's own suite already covers (parsing,
retrieval, judging, escalation logic) -- only this package's new glue: does the
corpus/review data round-trip correctly through SQLAlchemy, and does the
dependency-injection wiring into GroundingJudge/assemble_final_answer actually work.
"""

from __future__ import annotations

import pytest

from backend import corpus_store, review_store
from backend.db import init_schema, make_engine
from safety_qa.generation.schema import Citation, Claim
from safety_qa.ingestion.models import Clause, Standard
from safety_qa.judging.grounding_judge import GroundingJudge, JudgedAnswer, JudgedClaim
from safety_qa.generation.llm_client import FakeLLMClient
from safety_qa.review.escalation import build_packets
from safety_qa.review.assembly import assemble_final_answer


@pytest.fixture()
def engine(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path}/test.db")
    init_schema(e)
    return e


def _clause(citation_key="TEST#(a)", clause_path="(a)", text="Some clause text.") -> Clause:
    return Clause(
        standard_id="TEST", citation_key=citation_key, clause_path=clause_path,
        parent_citation_key=None, depth=1, section_title=None, text=text,
        clause_type="requirement", is_normative=True, order_index=1,
    )


# ---------------------------------------------------------------------------
# corpus_store
# ---------------------------------------------------------------------------

def test_corpus_round_trip(engine):
    corpus_store.upsert_standard(engine, Standard("TEST", "Test Standard", "ed1", "public_domain", "https://example.test"))
    corpus_store.replace_clauses(engine, "TEST", [_clause(citation_key="TEST#(a)", clause_path="(a)")])

    clauses = corpus_store.list_clauses(engine, "TEST")
    assert len(clauses) == 1
    assert clauses[0].clause_path == "(a)"

    fetched = corpus_store.get_clause_by_path(engine, "TEST", "(a)")
    assert fetched is not None
    assert fetched.text == "Some clause text."


def test_corpus_is_empty_before_and_after_ingest(engine):
    assert corpus_store.corpus_is_empty(engine, "TEST") is True
    corpus_store.replace_clauses(engine, "TEST", [_clause()])
    assert corpus_store.corpus_is_empty(engine, "TEST") is False


def test_replace_clauses_is_idempotent(engine):
    corpus_store.replace_clauses(engine, "TEST", [_clause(citation_key="TEST#(a)", clause_path="(a)")])
    corpus_store.replace_clauses(engine, "TEST", [_clause(citation_key="TEST#(a)", clause_path="(a)")])
    assert len(corpus_store.list_clauses(engine, "TEST")) == 1  # not 2


# ---------------------------------------------------------------------------
# review_store
# ---------------------------------------------------------------------------

def _judged(claim_id, verdict="unsupported", clause="(a)", text="claim text"):
    claim = Claim(claim_id=claim_id, text=text, citation=Citation(standard_id="TEST", clause=clause, quote="q"))
    return JudgedAnswer(query="q", judged_claims=[JudgedClaim(claim=claim, verdict=verdict, reasoning="r", source="llm_judge")])


def test_review_enqueue_and_decision_round_trip(engine):
    judged = _judged("c1")
    mapping = review_store.enqueue_all(engine, build_packets(judged))

    pending = review_store.list_pending(engine)
    assert len(pending) == 1
    assert pending[0].claim_id == "c1"

    review_store.record_decision(engine, mapping["c1"], "alice", "approve", "looks fine")
    item = review_store.get_item(engine, mapping["c1"])
    assert item.status == "approved"
    assert review_store.list_pending(engine) == []


def test_review_dedup_on_insert(engine):
    j1 = _judged("c1", clause="(a)", text="same text")
    j2 = _judged("c2", clause="(a)", text="same text")
    m1 = review_store.enqueue_all(engine, build_packets(j1))
    m2 = review_store.enqueue_all(engine, build_packets(j2))
    assert m1["c1"] == m2["c2"]
    assert len(review_store.list_pending(engine)) == 1


def test_verdict_log_round_trip(engine):
    judged = _judged("c1", verdict="supported")
    review_store.log_verdicts(engine, judged.judged_claims, judged.query)
    entries = review_store.list_verdict_log(engine)
    assert len(entries) == 1
    assert entries[0].verdict == "supported"


# ---------------------------------------------------------------------------
# dependency-injection wiring: GroundingJudge / assemble_final_answer against
# the Postgres-shaped store instead of sqlite3.Connection
# ---------------------------------------------------------------------------

def test_grounding_judge_works_against_backend_store(engine):
    corpus_store.upsert_standard(engine, Standard("TEST", "Test", "ed1", "public_domain", "https://example.test"))
    corpus_store.replace_clauses(engine, "TEST", [
        _clause(citation_key="TEST#(a)", clause_path="(a)", text="Lockout devices shall be durable.")
    ])
    llm = FakeLLMClient({"verdicts": [{"claim_id": "c1", "verdict": "supported", "reasoning": "matches"}]})
    judge = GroundingJudge(None, llm, clause_lookup=lambda sid, path: corpus_store.get_clause_by_path(engine, sid, path))

    claim = Claim(claim_id="c1", text="claim", citation=Citation(standard_id="TEST", clause="(a)", quote="Lockout devices shall be durable."))
    [result] = judge.evaluate_claims([claim])
    assert result.verdict == "supported"


def test_assemble_final_answer_works_against_backend_store(engine):
    judged = _judged("c1", verdict="unsupported")
    mapping = review_store.enqueue_all(engine, build_packets(judged))
    review_store.record_decision(engine, mapping["c1"], "alice", "approve", "false positive")

    final = assemble_final_answer(
        judged, None, mapping, get_item_fn=lambda item_id: review_store.get_item(engine, item_id)
    )
    assert len(final.claims) == 1
    assert final.pending_count == 0
