"""Review queue persistence for the web app -- same behavior as
safety_qa.review.store (dedup-on-insert against pending items only, append-only
decision audit trail, verdict logging), targeting the portable engine from db.py.
Reuses the existing `ReviewItem` / `VerdictLogEntry` dataclasses so
`safety_qa.review.assembly.assemble_final_answer()` and `safety_qa.review.cli`'s
decision-printing code work against either storage backend unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Engine, insert, select, update

from safety_qa.review.escalation import EscalationPacket
from safety_qa.review.store import ReviewItem, VerdictLogEntry

from .models import judge_verdict_log as verdict_log_table
from .models import review_decision as decision_table
from .models import review_item as item_table

_VALID_ACTIONS = ("approve", "edit", "reject")


def enqueue_all(engine: Engine, packets: list[EscalationPacket]) -> dict[str, int]:
    result: dict[str, int] = {}
    with engine.begin() as conn:
        for packet in packets:
            existing = conn.execute(
                select(item_table.c.id).where(
                    item_table.c.standard_id == packet.standard_id,
                    item_table.c.clause == packet.clause,
                    item_table.c.claim_text == packet.claim_text,
                    item_table.c.status == "pending",
                )
            ).fetchone()
            if existing:
                result[packet.claim_id] = existing.id
                continue
            inserted = conn.execute(
                insert(item_table).values(
                    claim_id=packet.claim_id, query=packet.query, claim_text=packet.claim_text,
                    standard_id=packet.standard_id, clause=packet.clause, quote=packet.quote,
                    judge1_verdict=packet.judge1_verdict, judge1_reasoning=packet.judge1_reasoning,
                    judge1_source=packet.judge1_source, severity=packet.severity,
                    status="pending", created_at=_now(),
                )
            )
            result[packet.claim_id] = inserted.inserted_primary_key[0]
    return result


def list_pending(engine: Engine) -> list[ReviewItem]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(item_table).where(item_table.c.status == "pending")
            .order_by(item_table.c.severity.desc(), item_table.c.created_at.asc())
        ).fetchall()
    return [_row_to_item(r) for r in rows]


def get_item(engine: Engine, item_id: int) -> ReviewItem | None:
    with engine.connect() as conn:
        row = conn.execute(select(item_table).where(item_table.c.id == item_id)).fetchone()
    return _row_to_item(row) if row else None


def record_decision(
    engine: Engine, item_id: int, reviewer_id: str, action: str, rationale: str,
    edited_text: str | None = None, edited_quote: str | None = None, edited_clause: str | None = None,
) -> None:
    if action not in _VALID_ACTIONS:
        raise ValueError(f"action must be one of {_VALID_ACTIONS}, got {action!r}")
    if action == "edit" and not (edited_text or edited_quote or edited_clause):
        raise ValueError("edit requires at least one of edited_text/edited_quote/edited_clause")
    if not rationale.strip():
        raise ValueError("rationale is required for every review decision")

    status = "approved" if action == "approve" else "edited" if action == "edit" else "rejected"
    with engine.begin() as conn:
        conn.execute(
            insert(decision_table).values(
                review_item_id=item_id, reviewer_id=reviewer_id, action=action,
                edited_text=edited_text, edited_quote=edited_quote, rationale=rationale, decided_at=_now(),
            )
        )
        conn.execute(
            update(item_table).where(item_table.c.id == item_id).values(
                status=status, edited_text=edited_text, edited_quote=edited_quote, edited_clause=edited_clause,
            )
        )


def log_verdicts(engine: Engine, judged_claims, query: str) -> None:
    if not judged_claims:
        return
    with engine.begin() as conn:
        conn.execute(
            insert(verdict_log_table),
            [
                {
                    "claim_id": jc.claim.claim_id, "query": query, "verdict": jc.verdict,
                    "reasoning": jc.reasoning, "source": jc.source, "model": jc.model,
                    "prompt_version": jc.prompt_version, "logged_at": _now(),
                }
                for jc in judged_claims
            ],
        )


def list_verdict_log(engine: Engine, claim_id: str | None = None) -> list[VerdictLogEntry]:
    query = select(verdict_log_table)
    if claim_id is not None:
        query = query.where(verdict_log_table.c.claim_id == claim_id)
    with engine.connect() as conn:
        rows = conn.execute(query.order_by(verdict_log_table.c.id)).fetchall()
    return [
        VerdictLogEntry(
            id=r.id, claim_id=r.claim_id, query=r.query, verdict=r.verdict, reasoning=r.reasoning,
            source=r.source, model=r.model, prompt_version=r.prompt_version, logged_at=r.logged_at,
        )
        for r in rows
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_item(row) -> ReviewItem:
    return ReviewItem(
        id=row.id, claim_id=row.claim_id, query=row.query, claim_text=row.claim_text,
        standard_id=row.standard_id, clause=row.clause, quote=row.quote,
        judge1_verdict=row.judge1_verdict, judge1_reasoning=row.judge1_reasoning,
        judge1_source=row.judge1_source, severity=row.severity, status=row.status,
        edited_text=row.edited_text, edited_quote=row.edited_quote, edited_clause=row.edited_clause,
        created_at=row.created_at,
    )
