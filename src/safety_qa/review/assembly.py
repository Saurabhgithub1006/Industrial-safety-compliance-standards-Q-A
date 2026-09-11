"""Phase 5: final answer assembly.

Combines Judge 1's `supported` claims (already trustworthy, no human needed) with
HITL-cleared claims (approved or edited) from the review queue. Rejected and
still-pending claims are held back -- never shipped as if they were a checked
answer, per the arch doc's "never ship an unreviewed claim either way" principle
(Sec 4.7).
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
    judged: JudgedAnswer, conn: sqlite3.Connection, claim_id_to_item_id: dict[str, int]
) -> FinalAnswer:
    """`claim_id_to_item_id` is the mapping returned by `store.enqueue_all()` for
    this same judged answer -- passed explicitly rather than re-derived, since
    dedup-on-insert means a claim's review_item may belong to an earlier query
    (same claim text/citation, different claim_id), and re-deriving that mapping
    later would be ambiguous."""
    claims: list[Claim] = [jc.claim for jc in judged.supported_claims]
    pending = 0
    rejected = 0

    for jc in judged.escalated_claims:
        item_id = claim_id_to_item_id.get(jc.claim.claim_id)
        item = get_item(conn, item_id) if item_id is not None else None

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
    """A human-edited claim: reviewer-supplied text/citation fields override the
    original wherever they provided a replacement, original values carried
    through otherwise. The human review IS the final check for this claim --
    an edited claim is not re-run through Judge 1's automated grounding check."""
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
