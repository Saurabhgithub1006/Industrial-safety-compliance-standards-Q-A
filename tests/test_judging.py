"""Phase 4 tests: everything about Judge 1 that's testable without a live LLM call --
the deterministic re-check layer (hallucinated citations, altered quotes, both
caught with zero API calls) and the plumbing around the LLM layer (batching into one
call, claim_id-based response mapping, retry-once-then-fail on an incomplete/invalid
response). What is NOT tested here: whether the judge correctly identifies a
"contradicted" claim -- that's a semantic judgment call requiring a real model, and
is instead exercised by run_judge_eval.py against the adversarial set in eval_set.py
(see that module's docstring for why).
"""

from __future__ import annotations

import sqlite3

import pytest

from safety_qa.generation.generator import GenerationResult, RejectedClaim
from safety_qa.generation.llm_client import FakeLLMClient
from safety_qa.generation.schema import Citation, Claim
from safety_qa.ingestion.models import Standard
from safety_qa.ingestion.parser_osha_ecfr import parse_osha_section
from safety_qa.ingestion.store import connect, replace_clauses, upsert_standard
from safety_qa.judging.grounding_judge import GroundingJudge, JudgeError

STANDARD_ID = "TEST-1"


@pytest.fixture()
def conn(tmp_path) -> sqlite3.Connection:
    """A tiny real corpus (via the actual ingestion pipeline, not hand-rolled rows)
    so get_clause_by_path exercises the real lookup path Judge 1 depends on."""
    xml_path = tmp_path / "test.xml"
    xml_path.write_text(
        """<DIV8 N="1"><HEAD>Test standard</HEAD>
<P>(a) Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed.</P>
<P>(b) The employer shall conduct a periodic inspection at least annually.</P>
</DIV8>""",
        encoding="utf-8",
    )
    _, clauses = parse_osha_section(str(xml_path), STANDARD_ID)
    c = connect(str(tmp_path / "test.db"))
    upsert_standard(c, Standard(STANDARD_ID, "Test standard", "test edition", "public_domain", "https://example.test"))
    replace_clauses(c, STANDARD_ID, clauses)
    return c


def _claim(claim_id: str, clause: str, quote: str, text: str = "some claim") -> Claim:
    return Claim(claim_id=claim_id, text=text, citation=Citation(standard_id=STANDARD_ID, clause=clause, quote=quote))


# ---------------------------------------------------------------------------
# deterministic layer -- no LLM call needed
# ---------------------------------------------------------------------------

def test_hallucinated_citation_is_unsupported_without_calling_the_model(conn):
    llm = FakeLLMClient()
    judge = GroundingJudge(conn, llm)

    results = judge.evaluate_claims([_claim("c1", "(z)(99)", "anything")])

    assert results[0].verdict == "unsupported"
    assert results[0].source == "deterministic_check"
    assert "does not exist" in results[0].reasoning
    assert llm.calls == []


def test_altered_quote_is_unsupported_without_calling_the_model(conn):
    llm = FakeLLMClient()
    judge = GroundingJudge(conn, llm)

    results = judge.evaluate_claims([
        _claim("c1", "(a)", "Lockout devices shall be capable of surviving harsh environments")
    ])

    assert results[0].verdict == "unsupported"
    assert results[0].source == "deterministic_check"
    assert "not a verbatim excerpt" in results[0].reasoning
    assert llm.calls == []


def test_verbatim_check_tolerates_whitespace_reformatting(conn):
    llm = FakeLLMClient({"verdicts": [{"claim_id": "c1", "verdict": "supported", "reasoning": "matches"}]})
    judge = GroundingJudge(conn, llm)

    results = judge.evaluate_claims([
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable\nof   withstanding the environment to which they are exposed.")
    ])

    assert results[0].source == "llm_judge"  # passed the deterministic check, went to the model


# ---------------------------------------------------------------------------
# LLM layer -- batching, mapping, retry
# ---------------------------------------------------------------------------

def test_claims_needing_judgment_are_batched_into_one_call(conn):
    llm = FakeLLMClient({
        "verdicts": [
            {"claim_id": "c1", "verdict": "supported", "reasoning": "ok"},
            {"claim_id": "c2", "verdict": "contradicted", "reasoning": "wrong number"},
        ]
    })
    judge = GroundingJudge(conn, llm)
    claims = [
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed."),
        _claim("c2", "(b)", "The employer shall conduct a periodic inspection at least annually."),
    ]

    results = judge.evaluate_claims(claims)

    assert len(llm.calls) == 1  # one call, not two
    by_id = {r.claim.claim_id: r for r in results}
    assert by_id["c1"].verdict == "supported"
    assert by_id["c2"].verdict == "contradicted"
    assert by_id["c2"].reasoning == "wrong number"


def test_verdicts_map_back_correctly_even_out_of_order(conn):
    llm = FakeLLMClient({
        "verdicts": [
            {"claim_id": "c2", "verdict": "contradicted", "reasoning": "r2"},
            {"claim_id": "c1", "verdict": "supported", "reasoning": "r1"},
        ]
    })
    judge = GroundingJudge(conn, llm)
    claims = [
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed."),
        _claim("c2", "(b)", "The employer shall conduct a periodic inspection at least annually."),
    ]

    results = judge.evaluate_claims(claims)

    assert results[0].claim.claim_id == "c1" and results[0].verdict == "supported"
    assert results[1].claim.claim_id == "c2" and results[1].verdict == "contradicted"


def test_incomplete_batch_response_triggers_retry_then_succeeds(conn):
    llm = FakeLLMClient()
    llm.queue({"verdicts": [{"claim_id": "c1", "verdict": "supported", "reasoning": "ok"}]})  # missing c2
    llm.queue({
        "verdicts": [
            {"claim_id": "c1", "verdict": "supported", "reasoning": "ok"},
            {"claim_id": "c2", "verdict": "supported", "reasoning": "ok"},
        ]
    })
    judge = GroundingJudge(conn, llm)
    claims = [
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed."),
        _claim("c2", "(b)", "The employer shall conduct a periodic inspection at least annually."),
    ]

    results = judge.evaluate_claims(claims)

    assert len(llm.calls) == 2
    assert all(r.verdict == "supported" for r in results)


def test_judge_error_after_two_failures(conn):
    llm = FakeLLMClient()
    llm.queue({"verdicts": []})  # missing the required claim_id
    llm.queue({"verdicts": []})  # still missing
    judge = GroundingJudge(conn, llm)

    with pytest.raises(JudgeError):
        judge.evaluate_claims([_claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed.")])

    assert len(llm.calls) == 2


def test_no_claims_needing_judgment_skips_the_model_entirely(conn):
    llm = FakeLLMClient()
    judge = GroundingJudge(conn, llm)

    results = judge.evaluate_claims([_claim("c1", "(z)(99)", "anything")])  # hallucinated -> deterministic only

    assert llm.calls == []
    assert results[0].verdict == "unsupported"


# ---------------------------------------------------------------------------
# evaluate() -- full GenerationResult -> JudgedAnswer pipeline
# ---------------------------------------------------------------------------

def test_evaluate_folds_in_phase3_rejected_claims_without_an_llm_call(conn):
    llm = FakeLLMClient({"verdicts": [{"claim_id": "c1", "verdict": "supported", "reasoning": "ok"}]})
    judge = GroundingJudge(conn, llm)

    valid = [_claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed.")]
    rejected = [RejectedClaim(claim=_claim("c2", "(b)", "wrong quote"), reason="quote is not a verbatim substring of the cited clause's text")]
    gen_result = GenerationResult(query="a question", valid_claims=valid, rejected_claims=rejected, unsupported_aspects=["some gap"])

    judged = judge.evaluate(gen_result)

    assert len(judged.judged_claims) == 2
    by_id = {jc.claim.claim_id: jc for jc in judged.judged_claims}
    assert by_id["c1"].verdict == "supported" and by_id["c1"].source == "llm_judge"
    assert by_id["c2"].verdict == "unsupported" and by_id["c2"].source == "deterministic_check"
    assert judged.unsupported_aspects == ["some gap"]
    assert len(llm.calls) == 1  # only c1 needed the model


def test_supported_and_escalated_claims_properties(conn):
    llm = FakeLLMClient({
        "verdicts": [
            {"claim_id": "c1", "verdict": "supported", "reasoning": "ok"},
            {"claim_id": "c2", "verdict": "contradicted", "reasoning": "wrong"},
        ]
    })
    judge = GroundingJudge(conn, llm)
    claims = [
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed."),
        _claim("c2", "(b)", "The employer shall conduct a periodic inspection at least annually."),
    ]
    gen_result = GenerationResult(query="q", valid_claims=claims)

    judged = judge.evaluate(gen_result)

    assert [c.claim.claim_id for c in judged.supported_claims] == ["c1"]
    assert [c.claim.claim_id for c in judged.escalated_claims] == ["c2"]


def test_llm_judge_verdicts_are_tagged_with_model_and_prompt_version(conn):
    from safety_qa.judging.prompt import JUDGE_PROMPT_VERSION

    llm = FakeLLMClient({"verdicts": [{"claim_id": "c1", "verdict": "supported", "reasoning": "ok"}]}, model="a-specific-model")
    judge = GroundingJudge(conn, llm)

    [result] = judge.evaluate_claims([
        _claim("c1", "(a)", "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed.")
    ])

    assert result.source == "llm_judge"
    assert result.model == "a-specific-model"
    assert result.prompt_version == JUDGE_PROMPT_VERSION


def test_deterministic_check_verdicts_carry_no_model_or_prompt_version(conn):
    llm = FakeLLMClient()
    judge = GroundingJudge(conn, llm)

    [result] = judge.evaluate_claims([_claim("c1", "(z)(99)", "anything")])  # hallucinated citation

    assert result.source == "deterministic_check"
    assert result.model is None
    assert result.prompt_version is None
    assert llm.calls == []  # confirms no model was ever actually called for this one
