"""Phase 5: Judge 2 -- escalation packet construction.

Deterministic by design (Phase 5 kickoff decision D1): severity ranking and
deduping are mechanical, not judgment calls, so this makes zero LLM calls. An
LLM-written packet summary was considered and explicitly deferred as an optional
later enhancement -- not needed for the queue to function.

Severity ordering matches artifacts/system-arch-and-roadmap.md Sec 4.5:
"contradicted outranks unsupported". (The arch doc's third tier, "no_citation",
isn't a separate Judge 1 verdict in this implementation -- it's folded into
"unsupported", see judging/schema.py's Verdict taxonomy.)
"""

from __future__ import annotations

from dataclasses import dataclass

from safety_qa.judging.grounding_judge import JudgedAnswer

_SEVERITY_RANK = {"contradicted": 2, "unsupported": 1}


@dataclass(frozen=True)
class EscalationPacket:
    claim_id: str
    query: str
    claim_text: str
    standard_id: str
    clause: str
    quote: str
    judge1_verdict: str
    judge1_reasoning: str
    severity: int


def build_packets(judged: JudgedAnswer) -> list[EscalationPacket]:
    """One packet per escalated claim -- everything Judge 1 didn't mark
    `supported` -- sorted worst-first. `supported` claims never appear here; they
    already passed and go straight to answer assembly without a human."""
    packets = [
        EscalationPacket(
            claim_id=jc.claim.claim_id,
            query=judged.query,
            claim_text=jc.claim.text,
            standard_id=jc.claim.citation.standard_id,
            clause=jc.claim.citation.clause,
            quote=jc.claim.citation.quote,
            judge1_verdict=jc.verdict,
            judge1_reasoning=jc.reasoning,
            severity=_SEVERITY_RANK.get(jc.verdict, 0),
        )
        for jc in judged.escalated_claims
    ]
    return sorted(packets, key=lambda p: p.severity, reverse=True)
