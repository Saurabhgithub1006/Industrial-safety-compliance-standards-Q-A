"""Phase 6 tests: overturned_cases() and override_rate() against synthetic
review_decision data -- deterministic, zero LLM dependency. The live replay
(run_regression.py, which re-runs an overturned case through a fresh Judge 1 call)
is validated manually against the real queue, same as Phase 4's adversarial eval --
see regression.py's docstring for why.
"""

from __future__ import annotations

import pytest

from safety_qa.review.regression import overturned_cases, override_rate
from safety_qa.review.store import connect, enqueue_all, record_decision
from safety_qa.judging.grounding_judge import JudgedAnswer, JudgedClaim
from safety_qa.generation.schema import Citation, Claim
from safety_qa.review.escalation import build_packets


def _claim(claim_id: str, text: str | None = None, clause: str | None = None) -> Claim:
    # Each claim_id gets a distinct default text/clause -- store.enqueue_all()
    # deliberately dedups identical (clause, claim_text) pairs (that's the whole
    # point of dedup-on-insert), so tests exercising multiple *distinct* escalated
    # items must not accidentally collide on the same defaults.
    return Claim(
        claim_id=claim_id, text=text or f"claim text for {claim_id}",
        citation=Citation(standard_id="TEST-1", clause=clause or f"({claim_id})", quote="q"),
    )


def _escalate(conn, claim_id: str, verdict: str, reasoning: str = "r") -> int:
    judged = JudgedAnswer(
        query="q", judged_claims=[JudgedClaim(claim=_claim(claim_id), verdict=verdict, reasoning=reasoning, source="llm_judge")]
    )
    mapping = enqueue_all(conn, build_packets(judged))
    return mapping[claim_id]


@pytest.fixture()
def conn(tmp_path):
    return connect(str(tmp_path / "review.db"))


def test_override_rate_with_no_decisions_yet(conn):
    report = override_rate(conn)
    assert report == {"total_decided": 0, "overturned": 0, "confirmed": 0, "override_rate": None}


def test_override_rate_counts_approve_and_edit_as_overturned(conn):
    id1 = _escalate(conn, "c1", "unsupported")
    id2 = _escalate(conn, "c2", "contradicted")
    id3 = _escalate(conn, "c3", "unsupported")
    record_decision(conn, id1, "alice", "approve", "false positive")
    record_decision(conn, id2, "alice", "edit", "fixed wording", edited_text="corrected")
    record_decision(conn, id3, "alice", "reject", "genuinely wrong")

    report = override_rate(conn)
    assert report == {"total_decided": 3, "overturned": 2, "confirmed": 1, "override_rate": pytest.approx(2 / 3)}


def test_override_rate_ignores_pending_items(conn):
    _escalate(conn, "c1", "unsupported")  # never decided
    report = override_rate(conn)
    assert report["total_decided"] == 0


def test_overturned_cases_excludes_rejected_and_pending(conn):
    id1 = _escalate(conn, "c1", "unsupported")
    _escalate(conn, "c2", "unsupported")  # left pending
    id3 = _escalate(conn, "c3", "contradicted")
    record_decision(conn, id1, "alice", "approve", "false positive")
    record_decision(conn, id3, "alice", "reject", "genuinely wrong")

    cases = overturned_cases(conn)
    assert [c.claim_id for c in cases] == ["c1"]


def test_overturned_cases_carries_the_rationale_and_original_verdict(conn):
    item_id = _escalate(conn, "c1", "contradicted", reasoning="clause says annually not monthly")
    record_decision(conn, item_id, "alice", "approve", "actually the claim was about a different clause, my mistake")

    [case] = overturned_cases(conn)
    assert case.judge1_verdict == "contradicted"
    assert case.judge1_reasoning == "clause says annually not monthly"
    assert case.reviewer_action == "approve"
    assert "my mistake" in case.reviewer_rationale


def test_overturned_cases_reflects_edited_replacement_text(conn):
    item_id = _escalate(conn, "c1", "unsupported")
    record_decision(conn, item_id, "alice", "edit", "wording was imprecise", edited_text="the corrected claim text")

    [case] = overturned_cases(conn)
    assert case.reviewer_action == "edit"
    # the case still carries the ORIGINAL claim text (what Judge 1 actually
    # evaluated) -- the point of replaying is to re-check Judge 1's original call,
    # not the human's corrected version.
    assert case.claim_text == "claim text for c1"
