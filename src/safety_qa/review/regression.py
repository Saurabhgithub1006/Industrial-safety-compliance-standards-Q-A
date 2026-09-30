"""Phase 6: feedback loop -- review history into a regression suite and a
judge-precision metric. Pure/deterministic; the live replay lives in
run_regression.py. See artifacts/system-arch-and-roadmap.md Sec 4.8 and CHG-20260911-08.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class OverturnedCase:
    """A case where a human overturned Judge 1's flag (approved or edited it)."""

    review_item_id: int
    claim_id: str
    query: str
    claim_text: str
    standard_id: str
    clause: str
    quote: str
    judge1_verdict: str
    judge1_reasoning: str
    judge1_source: str  # "deterministic_check" or "llm_judge"; see run_regression.py
    reviewer_action: str  # "approve" or "edit"
    reviewer_rationale: str


def overturned_cases(conn: sqlite3.Connection) -> list[OverturnedCase]:
    """Every review_item whose latest decision was approve or edit."""
    rows = conn.execute(
        "SELECT * FROM review_item WHERE status IN ('approved', 'edited') ORDER BY id"
    ).fetchall()
    cases = []
    for row in rows:
        decision = conn.execute(
            """SELECT action, rationale FROM review_decision
               WHERE review_item_id = ? ORDER BY id DESC LIMIT 1""",
            (row["id"],),
        ).fetchone()
        cases.append(
            OverturnedCase(
                review_item_id=row["id"], claim_id=row["claim_id"], query=row["query"],
                claim_text=row["claim_text"], standard_id=row["standard_id"], clause=row["clause"],
                quote=row["quote"], judge1_verdict=row["judge1_verdict"],
                judge1_reasoning=row["judge1_reasoning"], judge1_source=row["judge1_source"],
                reviewer_action=decision["action"] if decision else row["status"],
                reviewer_rationale=decision["rationale"] if decision else "",
            )
        )
    return cases


def override_rate(conn: sqlite3.Connection) -> dict:
    """Fraction of decided items where a human overturned Judge 1's verdict."""
    rows = conn.execute(
        "SELECT status FROM review_item WHERE status IN ('approved', 'edited', 'rejected')"
    ).fetchall()
    total = len(rows)
    if total == 0:
        return {"total_decided": 0, "overturned": 0, "confirmed": 0, "override_rate": None}
    overturned = sum(1 for r in rows if r["status"] in ("approved", "edited"))
    confirmed = total - overturned
    return {
        "total_decided": total,
        "overturned": overturned,
        "confirmed": confirmed,
        "override_rate": overturned / total,
    }
