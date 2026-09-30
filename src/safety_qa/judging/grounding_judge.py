"""Phase 4: Judge 1 -- Grounding & Contradiction Judge.
Two layers: a deterministic re-check against the corpus, then one batched LLM
call per answer for claims that clear it. See artifacts/changelogs.md CHG-20260907-04.
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
    """Judge 1 failed to produce a valid response even after one retry."""


@dataclass
class JudgedClaim:
    claim: Claim
    verdict: Verdict
    reasoning: str
    source: str  # "deterministic_check" or "llm_judge"
    model: str | None = None  # model that made the call; None for deterministic_check
    prompt_version: str | None = None  # JUDGE_PROMPT_VERSION at call time; None likewise


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
    def __init__(self, conn: sqlite3.Connection | None, llm: LLMClient, clause_lookup=None):
        """`clause_lookup`, if given, replaces the default sqlite-backed lookup
        (`conn` can then be None) -- lets backend/ reuse this class unchanged."""
        self.conn = conn
        self.llm = llm
        self._clause_lookup = clause_lookup or (lambda standard_id, path: get_clause_by_path(self.conn, standard_id, path))
        self._schema = GroundingJudgeOutput.model_json_schema()

    def evaluate(self, generation_result: GenerationResult) -> JudgedAnswer:
        """Judges a generator's output end to end; folds in Phase 3's already-rejected claims."""
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
        """Judge a list of claims directly; entry point for the adversarial eval set."""
        results: list[JudgedClaim | None] = [None] * len(claims)
        to_judge: list[tuple[int, Claim, str]] = []  # (index, claim, actual_clause_text)

        for i, claim in enumerate(claims):
            actual_clause = self._clause_lookup(claim.citation.standard_id, claim.citation.clause)
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
