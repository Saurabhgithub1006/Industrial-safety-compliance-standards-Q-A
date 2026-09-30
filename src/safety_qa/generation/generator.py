"""Phase 3: grounded generation.
Orchestrates retrieve -> prompt -> structured LLM call -> validate.
Two checks guard every claim: schema validation, then citation-grounding.
See artifacts/changelogs.md CHG-20260907-03 for the design rationale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from safety_qa.retrieval.retriever import Retriever

from .llm_client import LLMClient
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .schema import Claim, GeneratedAnswer

_SCHEMA_NAME = "generated_answer"


class GenerationError(Exception):
    """Model failed to produce a schema-valid answer after one retry."""


@dataclass
class RejectedClaim:
    claim: Claim
    reason: str


@dataclass
class GenerationResult:
    query: str
    valid_claims: list[Claim] = field(default_factory=list)
    rejected_claims: list[RejectedClaim] = field(default_factory=list)
    unsupported_aspects: list[str] = field(default_factory=list)


class Generator:
    def __init__(self, retriever: Retriever, llm: LLMClient, top_k: int = 5):
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self._schema = GeneratedAnswer.model_json_schema()

    def answer(self, query: str) -> GenerationResult:
        chunks = self.retriever.retrieve(query, top_k=self.top_k)
        if not chunks:
            return GenerationResult(query=query, unsupported_aspects=[query])

        user_prompt = build_user_prompt(query, chunks)
        try:
            parsed = self._call_and_validate(user_prompt)
        except (ValidationError, ValueError, KeyError) as first_error:
            retry_prompt = (
                f"{user_prompt}\n\n---\nYour previous response was invalid: "
                f"{first_error}\nRespond again, correcting this."
            )
            try:
                parsed = self._call_and_validate(retry_prompt)
            except Exception as second_error:
                raise GenerationError(
                    f"model failed to produce a valid structured answer after retry: {second_error}"
                ) from second_error

        chunk_by_ref = {(r.chunk.standard_id, r.chunk.clause_path): r.chunk for r in chunks}
        valid_claims: list[Claim] = []
        rejected: list[RejectedClaim] = []
        for claim in parsed.claims:
            ref = (claim.citation.standard_id, claim.citation.clause)
            chunk = chunk_by_ref.get(ref)
            if chunk is None:
                rejected.append(RejectedClaim(claim, "cited clause was not among the retrieved chunks shown to the model"))
                continue
            if _normalize_whitespace(claim.citation.quote) not in _normalize_whitespace(chunk.text):
                rejected.append(RejectedClaim(claim, "quote is not a verbatim substring of the cited clause's text"))
                continue
            valid_claims.append(claim)

        return GenerationResult(
            query=query,
            valid_claims=valid_claims,
            rejected_claims=rejected,
            unsupported_aspects=parsed.unsupported_aspects,
        )

    def _call_and_validate(self, user_prompt: str) -> GeneratedAnswer:
        raw = self.llm.complete_structured(
            system=SYSTEM_PROMPT, user=user_prompt, schema=self._schema, schema_name=_SCHEMA_NAME
        )
        return GeneratedAnswer.model_validate(raw)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
