"""Phase 3 tests: grounded generation, entirely against FakeLLMClient -- no network
call, no API key, deterministic. What's under test is the logic Phase 3 actually
adds on top of Phase 2's retrieval: prompt construction, schema validation +
retry-once-then-fail, and the citation-grounding sanity check (hallucinated
citation / non-verbatim quote both get rejected rather than trusted).
"""

from __future__ import annotations

import pytest

from safety_qa.generation.generator import GenerationError, Generator
from safety_qa.generation.llm_client import FakeLLMClient
from safety_qa.retrieval.chunking import Chunk
from safety_qa.retrieval.retriever import Retriever

STANDARD_ID = "TEST-1"


def _chunk(clause_path: str, text: str, title: str | None = None) -> Chunk:
    return Chunk(
        citation_key=f"{STANDARD_ID}#{clause_path}",
        standard_id=STANDARD_ID,
        clause_path=clause_path,
        section_title=title,
        clause_type="requirement",
        is_normative=True,
        text=text,
    )


@pytest.fixture()
def retriever():
    chunks = [
        _chunk("(a)(1)", "Lockout devices shall be capable of withstanding the environment to which they are exposed."),
        _chunk("(a)(2)", "Employees shall receive training on hazardous energy sources at least annually."),
    ]
    return Retriever(chunks)


def _valid_response(query: str) -> dict:
    return {
        "query": query,
        "claims": [
            {
                "claim_id": "c1",
                "text": "Lockout devices must be able to withstand the environment they're exposed to.",
                "citation": {
                    "standard_id": STANDARD_ID,
                    "clause": "(a)(1)",
                    "quote": "Lockout devices shall be capable of withstanding the environment to which they are exposed.",
                },
                "status": "pending_judge",
            }
        ],
        "unsupported_aspects": [],
    }


class _EmptyRetriever:
    def retrieve(self, query: str, top_k: int = 5):
        return []


# ---------------------------------------------------------------------------

def test_valid_grounded_claim_passes_through(retriever):
    llm = FakeLLMClient(_valid_response("what must lockout devices withstand?"))
    gen = Generator(retriever, llm)

    result = gen.answer("what must lockout devices withstand?")

    assert len(result.valid_claims) == 1
    assert result.rejected_claims == []
    assert result.valid_claims[0].citation.clause == "(a)(1)"


def test_prompt_includes_only_retrieved_clause_text(retriever):
    llm = FakeLLMClient(_valid_response("what must lockout devices withstand?"))
    gen = Generator(retriever, llm)
    gen.answer("what must lockout devices withstand?")

    sent_prompt = llm.calls[0]["user"]
    assert "(a)(1)" in sent_prompt
    assert "(a)(2)" in sent_prompt
    assert "withstanding the environment" in sent_prompt


def test_hallucinated_citation_is_rejected_not_trusted(retriever):
    response = _valid_response("what must lockout devices withstand?")
    response["claims"][0]["citation"]["clause"] = "(z)(99)"  # never retrieved
    llm = FakeLLMClient(response)
    gen = Generator(retriever, llm)

    result = gen.answer("what must lockout devices withstand?")

    assert result.valid_claims == []
    assert len(result.rejected_claims) == 1
    assert "not among the retrieved chunks" in result.rejected_claims[0].reason


def test_non_verbatim_quote_is_rejected_not_trusted(retriever):
    response = _valid_response("what must lockout devices withstand?")
    response["claims"][0]["citation"]["quote"] = "Lockout devices must survive harsh conditions."  # paraphrase
    llm = FakeLLMClient(response)
    gen = Generator(retriever, llm)

    result = gen.answer("what must lockout devices withstand?")

    assert result.valid_claims == []
    assert len(result.rejected_claims) == 1
    assert "not a verbatim substring" in result.rejected_claims[0].reason


def test_verbatim_check_tolerates_whitespace_reformatting(retriever):
    response = _valid_response("what must lockout devices withstand?")
    response["claims"][0]["citation"]["quote"] = "Lockout devices shall be capable\nof withstanding   the environment to which they are exposed."
    llm = FakeLLMClient(response)
    gen = Generator(retriever, llm)

    result = gen.answer("what must lockout devices withstand?")

    assert len(result.valid_claims) == 1
    assert result.rejected_claims == []


def test_unsupported_aspects_pass_through(retriever):
    response = _valid_response("what must lockout devices withstand?")
    response["unsupported_aspects"] = ["no clause covers the disposal of lockout devices"]
    llm = FakeLLMClient(response)
    gen = Generator(retriever, llm)

    result = gen.answer("what must lockout devices withstand?")

    assert result.unsupported_aspects == ["no clause covers the disposal of lockout devices"]


def test_malformed_response_triggers_one_retry_then_succeeds(retriever):
    llm = FakeLLMClient()
    llm.queue({"query": "what must lockout devices withstand?"})  # missing required "claims" -> invalid... actually claims defaults to [] so make it truly broken
    llm.queue(_valid_response("what must lockout devices withstand?"))
    # Force the first response to be genuinely unparseable against the schema:
    llm._responses[0] = {"query": "what must lockout devices withstand?", "claims": [{"claim_id": "c1"}]}  # missing required citation/text

    gen = Generator(retriever, llm)
    result = gen.answer("what must lockout devices withstand?")

    assert len(llm.calls) == 2
    assert len(result.valid_claims) == 1


def test_generation_error_after_two_failures(retriever):
    llm = FakeLLMClient()
    llm.queue({"claims": [{"claim_id": "c1"}]})  # invalid: missing required "query"
    llm.queue({"claims": [{"claim_id": "c1"}]})  # invalid again
    gen = Generator(retriever, llm)

    with pytest.raises(GenerationError):
        gen.answer("what must lockout devices withstand?")

    assert len(llm.calls) == 2


def test_empty_retrieval_short_circuits_without_calling_the_model():
    llm = FakeLLMClient()
    gen = Generator(_EmptyRetriever(), llm)

    result = gen.answer("a totally unrelated question")

    assert result.valid_claims == []
    assert result.unsupported_aspects == ["a totally unrelated question"]
    assert llm.calls == []  # never even asked the model -- nothing to ground an answer in
