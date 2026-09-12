"""Phase 4: Judge 1 -- Grounding & Contradiction Judge.

Two layers, matching the arch doc's design exactly:

  1. An independent, deterministic re-check -- for every claim, re-fetch the cited
     clause straight from the corpus by (standard_id, clause_path) and verify the
     quote is genuinely a verbatim excerpt of THAT freshly-fetched text. This
     duplicates what Phase 3's generator already checked, on purpose: Judge 1 must
     not just trust the generator's framing, so it re-derives the same fact from
     scratch via its own DB lookup rather than reusing Phase 3's chunk objects.
     A claim that fails this is "unsupported" -- no LLM call needed, it's already
     a fact.
  2. For everything that clears step 1, one batched LLM call asks the actual
     semantic question step 1 can't: does the (already-verified-verbatim) quote
     really entail the claim, or does the claim misrepresent/contradict what the
     clause actually says? This is the part no amount of string matching can do.

Cost design (per the arch doc's Sec 4.4 architect note): all of a batch's claims go
in ONE LLM call with an explicit anti-bias instruction, not one call per claim.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from pydantic import ValidationError

from safety_qa.generation.generator import GenerationResult, RejectedClaim
from safety_qa.generation.llm_client import LLMClient
from safety_qa.generation.schema import Claim
from safety_qa.ingestion.store import get_clause_by_path

from .prompt import JUDGE_PROMPT_VERSION, SYSTEM_PROMPT, JudgeItem, build_user_prompt
from .schema import ClaimVerdict, GroundingJudgeOutput, Verdict

_SCHEMA_NAME = "grounding_judge_output"


class JudgeError(Exception):
    """Judge 1 failed to produce a schema-valid, complete response even after one
    retry -- raised rather than silently defaulting every claim to some verdict."""


@dataclass
class JudgedClaim:
    claim: Claim
    verdict: Verdict
    reasoning: str
    source: str  # "deterministic_check" or "llm_judge" -- which layer produced this
    model: str | None = None  # which model made the call; None for deterministic_check (no call made)
    prompt_version: str | None = None  # judging.prompt.JUDGE_PROMPT_VERSION at call time; None likewise


@dataclass
class JudgedAnswer:
    query: str
    judged_claims: list[JudgedClaim] = field(default_factory=list)
    unsupported_aspects: list[str] = field(default_factory=list)

    @property
    def supported_claims(self) -> list[JudgedClaim]:
        return [c for c in self.judged_claims if c.verdict == "supported"]

    @property
    def escalated_claims(self) -> list[JudgedClaim]:
        """Everything Judge 2 (Phase 5) will need to build a review packet for."""
        return [c for c in self.judged_claims if c.verdict != "supported"]


class GroundingJudge:
    def __init__(self, conn: sqlite3.Connection, llm: LLMClient):
        self.conn = conn
        self.llm = llm
        self._schema = GroundingJudgeOutput.model_json_schema()

    def evaluate(self, generation_result: GenerationResult) -> JudgedAnswer:
        """Full pipeline entry point: judges a generator's output end to end,
        folding in Phase 3's already-rejected claims (verdicted unsupported without
        another LLM call -- that fact is already known, re-asking would be waste)
        alongside a fresh judgment of everything that passed Phase 3."""
        judged: list[JudgedClaim] = [
            JudgedClaim(claim=rc.claim, verdict="unsupported", reasoning=rc.reason, source="deterministic_check")
            for rc in generation_result.rejected_claims
        ]
        judged.extend(self.evaluate_claims(generation_result.valid_claims))
        return JudgedAnswer(
            query=generation_result.query,
            judged_claims=judged,
            unsupported_aspects=list(generation_result.unsupported_aspects),
        )

    def evaluate_claims(self, claims: list[Claim]) -> list[JudgedClaim]:
        """Judge a list of claims directly -- the entry point for the adversarial
        eval set (Phase 4 exit criteria), which needs to exercise deliberately
        hallucinated citations and altered quotes that never went through a real
        Generator/retriever pipeline at all."""
        results: list[JudgedClaim | None] = [None] * len(claims)
        to_judge: list[tuple[int, Claim, str]] = []  # (index, claim, actual_clause_text)

        for i, claim in enumerate(claims):
            actual_clause = get_clause_by_path(self.conn, claim.citation.standard_id, claim.citation.clause)
            if actual_clause is None:
                results[i] = JudgedClaim(
                    claim=claim, verdict="unsupported",
                    reasoning="cited clause does not exist in the corpus (unresolvable citation)",
                    source="deterministic_check",
                )
                continue
            if _normalize(claim.citation.quote) not in _normalize(actual_clause.text):
                results[i] = JudgedClaim(
                    claim=claim, verdict="unsupported",
                    reasoning="quoted text is not a verbatim excerpt of the actual clause text in the corpus",
                    source="deterministic_check",
                )
                continue
            to_judge.append((i, claim, actual_clause.text))

        if to_judge:
            items = [
                JudgeItem(
                    claim_id=claim.claim_id, claim_text=claim.text, citation_clause=claim.citation.clause,
                    quoted_excerpt=claim.citation.quote, actual_clause_text=actual_text,
                )
                for _, claim, actual_text in to_judge
            ]
            verdicts_by_id = self._judge_batch(items)
            for i, claim, _ in to_judge:
                v = verdicts_by_id[claim.claim_id]
                results[i] = JudgedClaim(
                    claim=claim, verdict=v.verdict, reasoning=v.reasoning, source="llm_judge",
                    model=self.llm.model, prompt_version=JUDGE_PROMPT_VERSION,
                )

        return [r for r in results if r is not None]

    def _judge_batch(self, items: list[JudgeItem]) -> dict[str, ClaimVerdict]:
        user_prompt = build_user_prompt(items)
        try:
            output = self._call_and_validate(user_prompt, expected_ids={i.claim_id for i in items})
        except (ValidationError, ValueError, KeyError) as first_error:
            retry_prompt = (
                f"{user_prompt}\n\n---\nYour previous response was invalid: {first_error}\n"
                f"Respond again, correcting this -- remember to return exactly one verdict per claim_id."
            )
            try:
                output = self._call_and_validate(retry_prompt, expected_ids={i.claim_id for i in items})
            except Exception as second_error:
                raise JudgeError(
                    f"Judge 1 failed to produce a valid, complete response after retry: {second_error}"
                ) from second_error
        return {v.claim_id: v for v in output.verdicts}

    def _call_and_validate(self, user_prompt: str, expected_ids: set[str]) -> GroundingJudgeOutput:
        raw = self.llm.complete_structured(
            system=SYSTEM_PROMPT, user=user_prompt, schema=self._schema, schema_name=_SCHEMA_NAME
        )
        output = GroundingJudgeOutput.model_validate(raw)
        got_ids = {v.claim_id for v in output.verdicts}
        if got_ids != expected_ids:
            raise ValueError(f"expected verdicts for {expected_ids}, got {got_ids}")
        return output


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
