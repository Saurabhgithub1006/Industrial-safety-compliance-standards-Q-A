"""Phase 5: final answer assembly.
Combines Judge 1's supported claims with HITL-cleared claims from the review
queue. Pending and rejected claims are held back. See CHG-20260911-07.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from safety_qa.generation.schema import Citation, Claim
from safety_qa.judging.grounding_judge import JudgedAnswer

from .store import ReviewItem, get_item


@dataclass
class FinalAnswer:
    query: str
    claims: list[Claim] = field(default_factory=list)
    pending_count: int = 0
    rejected_count: int = 0
    unsupported_aspects: list[str] = field(default_factory=list)


def assemble_final_answer(
    judged: JudgedAnswer, conn: sqlite3.Connection | None, claim_id_to_item_id: dict[str, int],
    get_item_fn=None,
) -> FinalAnswer:
    """`claim_id_to_item_id` is store.enqueue_all()'s mapping for this judged answer.
    `get_item_fn`, if given, replaces the default sqlite-backed lookup (`conn` can
    then be None) -- lets backend/ reuse this function unchanged."""
    lookup = get_item_fn or (lambda item_id: get_item(conn, item_id))
    claims: list[Claim] = [jc.claim for jc in judged.supported_claims]
    pending = 0
    rejected = 0

    for jc in judged.escalated_claims:
        item_id = claim_id_to_item_id.get(jc.claim.claim_id)
        item = lookup(item_id) if item_id is not None else None

        if item is None or item.status == "pending":
            pending += 1
        elif item.status == "rejected":
            rejected += 1
        elif item.status == "approved":
            claims.append(jc.claim)
        elif item.status == "edited":
            claims.append(_apply_edit(jc.claim, item))

    return FinalAnswer(
        query=judged.query,
        claims=claims,
        pending_count=pending,
        rejected_count=rejected,
        unsupported_aspects=list(judged.unsupported_aspects),
    )


def _apply_edit(claim: Claim, item: ReviewItem) -> Claim:
    """Reviewer-supplied fields override the original; the human edit is the final check."""
    return Claim(
        claim_id=claim.claim_id,
        text=item.edited_text or claim.text,
        citation=Citation(
            standard_id=claim.citation.standard_id,
            clause=item.edited_clause or claim.citation.clause,
            quote=item.edited_quote or claim.citation.quote,
        ),
        status="pending_judge",
    )
