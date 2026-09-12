"""Phase 5 tests: escalation packet construction, the persistent review queue
(dedup-on-insert, all three decision actions), and final-answer assembly (the four
cases: supported, approved, edited, rejected/pending). Entirely deterministic --
Judge 2 makes no LLM calls (Phase 5 kickoff decision D1) -- so nothing here needs
a fake or real LLM client.
"""

from __future__ import annotations

import pytest

from safety_qa.generation.schema import Citation, Claim
from safety_qa.judging.grounding_judge import JudgedAnswer, JudgedClaim
from safety_qa.review.assembly import assemble_final_answer
from safety_qa.review.cli import apply_decision, resolve_reviewer_id
from safety_qa.review.escalation import build_packets
from safety_qa.review.store import (
    connect, enqueue_all, get_item, list_pending, list_verdict_log, log_verdict, log_verdicts, record_decision,
)


def _claim(claim_id: str, text: str = "some claim", clause: str = "(a)") -> Claim:
    return Claim(claim_id=claim_id, text=text, citation=Citation(standard_id="TEST-1", clause=clause, quote="q"))


def _judged_claim(claim: Claim, verdict: str, reasoning: str = "r") -> JudgedClaim:
    return JudgedClaim(claim=claim, verdict=verdict, reasoning=reasoning, source="llm_judge")


# ---------------------------------------------------------------------------
# escalation.py
# ---------------------------------------------------------------------------

def test_only_non_supported_claims_are_escalated():
    judged = JudgedAnswer(
        query="q",
        judged_claims=[
            _judged_claim(_claim("c1"), "supported"),
            _judged_claim(_claim("c2"), "unsupported"),
        ],
    )
    packets = build_packets(judged)
    assert [p.claim_id for p in packets] == ["c2"]


def test_contradicted_outranks_unsupported():
    judged = JudgedAnswer(
        query="q",
        judged_claims=[
            _judged_claim(_claim("c1"), "unsupported", "u"),
            _judged_claim(_claim("c2"), "contradicted", "c"),
        ],
    )
    packets = build_packets(judged)
    assert [p.claim_id for p in packets] == ["c2", "c1"]  # contradicted first


# ---------------------------------------------------------------------------
# store.py
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    return connect(str(tmp_path / "review.db"))


def test_enqueue_creates_pending_items(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    mapping = enqueue_all(conn, build_packets(judged))

    assert "c1" in mapping
    items = list_pending(conn)
    assert len(items) == 1
    assert items[0].status == "pending"
    assert items[0].claim_id == "c1"


def test_enqueue_dedups_identical_pending_escalation():
    """Same claim text + same citation, escalated again from a later query (a
    different claim_id) -- must merge into the existing pending item, not create
    a near-duplicate."""
    def make(cid):
        return JudgedAnswer(
            query="q2", judged_claims=[_judged_claim(_claim(cid, text="same text", clause="(a)"), "unsupported")]
        )

    conn = connect(":memory:")
    first = enqueue_all(conn, build_packets(make("c1")))
    second = enqueue_all(conn, build_packets(make("c2")))  # different claim_id, same text+clause

    assert len(list_pending(conn)) == 1  # not 2
    assert first["c1"] == second["c2"]  # both map to the same review_item


def test_enqueue_does_not_dedup_against_already_decided_items():
    """An item that's already been approved/rejected shouldn't silently absorb a
    fresh escalation of the same claim -- that's a new instance of the issue
    recurring, worth a human seeing again."""
    conn = connect(":memory:")

    def make(cid):
        return JudgedAnswer(
            query="q", judged_claims=[_judged_claim(_claim(cid, text="same text", clause="(a)"), "unsupported")]
        )

    first_map = enqueue_all(conn, build_packets(make("c1")))
    record_decision(conn, first_map["c1"], "alice", "reject", "not valid")

    second_map = enqueue_all(conn, build_packets(make("c2")))
    assert second_map["c2"] != first_map["c1"]
    assert len(list_pending(conn)) == 1  # the new one


def test_record_decision_approve(conn):
    mapping = enqueue_all(conn, build_packets(
        JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    ))
    record_decision(conn, mapping["c1"], "alice", "approve", "looks fine actually")

    item = get_item(conn, mapping["c1"])
    assert item.status == "approved"
    assert list_pending(conn) == []


def test_record_decision_edit_requires_a_replacement(conn):
    mapping = enqueue_all(conn, build_packets(
        JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    ))
    with pytest.raises(ValueError, match="edit requires"):
        record_decision(conn, mapping["c1"], "alice", "edit", "fixing it")


def test_record_decision_requires_rationale(conn):
    mapping = enqueue_all(conn, build_packets(
        JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    ))
    with pytest.raises(ValueError, match="rationale"):
        record_decision(conn, mapping["c1"], "alice", "approve", "")


def test_record_decision_rejects_invalid_action(conn):
    mapping = enqueue_all(conn, build_packets(
        JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    ))
    with pytest.raises(ValueError, match="action must be one of"):
        record_decision(conn, mapping["c1"], "alice", "delete", "nope")


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------

def test_resolve_reviewer_id_from_command_line_flag():
    assert resolve_reviewer_id(["--reviewer", "alice"]) == "alice"


def test_resolve_reviewer_id_prompts_when_flag_missing(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "bob")
    assert resolve_reviewer_id([]) == "bob"


def test_resolve_reviewer_id_never_silently_defaults_on_empty_input(monkeypatch):
    """Empty input must keep re-prompting, not fall through to some shared
    default identity -- that's the entire point of this hardening item."""
    answers = iter(["", "  ", "carol"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert resolve_reviewer_id([]) == "carol"


def test_apply_decision_edit_stores_corrected_text(conn):
    mapping = enqueue_all(conn, build_packets(
        JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    ))
    item = get_item(conn, mapping["c1"])
    apply_decision(conn, item, "edit", "alice", "fixed the wording", edited_text="corrected claim text")

    updated = get_item(conn, mapping["c1"])
    assert updated.status == "edited"
    assert updated.edited_text == "corrected claim text"


# ---------------------------------------------------------------------------
# assembly.py -- the four cases
# ---------------------------------------------------------------------------

def test_assembly_supported_claim_passes_through_without_review(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1", "a supported claim"), "supported")])
    final = assemble_final_answer(judged, conn, claim_id_to_item_id={})

    assert len(final.claims) == 1
    assert final.claims[0].text == "a supported claim"
    assert final.pending_count == 0


def test_assembly_pending_escalation_excluded_and_counted(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "unsupported")])
    mapping = enqueue_all(conn, build_packets(judged))

    final = assemble_final_answer(judged, conn, mapping)
    assert final.claims == []
    assert final.pending_count == 1


def test_assembly_approved_escalation_included(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1", "flagged claim"), "unsupported")])
    mapping = enqueue_all(conn, build_packets(judged))
    record_decision(conn, mapping["c1"], "alice", "approve", "false positive, it's fine")

    final = assemble_final_answer(judged, conn, mapping)
    assert len(final.claims) == 1
    assert final.claims[0].text == "flagged claim"  # unchanged
    assert final.pending_count == 0


def test_assembly_edited_escalation_uses_corrected_text(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1", "wrong wording"), "contradicted")])
    mapping = enqueue_all(conn, build_packets(judged))
    record_decision(conn, mapping["c1"], "alice", "edit", "fixed it", edited_text="corrected wording")

    final = assemble_final_answer(judged, conn, mapping)
    assert len(final.claims) == 1
    assert final.claims[0].text == "corrected wording"


def test_assembly_rejected_escalation_excluded_and_counted(conn):
    judged = JudgedAnswer(query="q", judged_claims=[_judged_claim(_claim("c1"), "contradicted")])
    mapping = enqueue_all(conn, build_packets(judged))
    record_decision(conn, mapping["c1"], "alice", "reject", "genuinely wrong")

    final = assemble_final_answer(judged, conn, mapping)
    assert final.claims == []
    assert final.rejected_count == 1


def test_pipeline_parse_args_extracts_wait_flag():
    from safety_qa.review.pipeline import _parse_args

    assert _parse_args(["--wait", "what", "is", "a", "lockout", "device"]) == (True, ["what", "is", "a", "lockout", "device"])
    assert _parse_args(["what", "is", "a", "lockout", "device"]) == (False, ["what", "is", "a", "lockout", "device"])


def test_assembly_passes_through_unsupported_aspects(conn):
    judged = JudgedAnswer(query="q", judged_claims=[], unsupported_aspects=["no clause covers X"])
    final = assemble_final_answer(judged, conn, claim_id_to_item_id={})
    assert final.unsupported_aspects == ["no clause covers X"]


# ---------------------------------------------------------------------------
# Phase 7: judge_verdict_log (observability)
# ---------------------------------------------------------------------------

def test_log_verdict_records_supported_claims_too(conn):
    """review_item never held `supported` claims -- the verdict log is the only
    place that verdict gets a permanent record at all."""
    jc = _judged_claim(_claim("c1", "a fine claim"), "supported", "matches the clause")
    jc.model = "some-model"
    jc.prompt_version = "v1"
    log_verdict(conn, jc, query="what is X?")

    [entry] = list_verdict_log(conn)
    assert entry.claim_id == "c1"
    assert entry.verdict == "supported"
    assert entry.model == "some-model"
    assert entry.prompt_version == "v1"


def test_log_verdict_stores_none_model_for_deterministic_source(conn):
    jc = _judged_claim(_claim("c1"), "unsupported", "cited clause does not exist in the corpus")
    jc.source = "deterministic_check"
    jc.model = None
    jc.prompt_version = None
    log_verdict(conn, jc, query="q")

    [entry] = list_verdict_log(conn)
    assert entry.source == "deterministic_check"
    assert entry.model is None


def test_log_verdicts_logs_every_claim_in_a_judged_answer(conn):
    judged = JudgedAnswer(
        query="q",
        judged_claims=[
            _judged_claim(_claim("c1"), "supported"),
            _judged_claim(_claim("c2"), "unsupported"),
        ],
    )
    log_verdicts(conn, judged.judged_claims, judged.query)

    assert len(list_verdict_log(conn)) == 2


def test_list_verdict_log_filters_by_claim_id(conn):
    log_verdict(conn, _judged_claim(_claim("c1"), "supported"), query="q")
    log_verdict(conn, _judged_claim(_claim("c2"), "supported"), query="q")

    entries = list_verdict_log(conn, claim_id="c1")
    assert [e.claim_id for e in entries] == ["c1"]
