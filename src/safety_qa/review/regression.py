"""Phase 6: feedback loop -- turning review history into a regression suite and a
judge-precision metric.

Per artifacts/system-arch-and-roadmap.md Sec 4.8: "build a growing regression
suite ('these exact claims must never again come back unsupported'), measure
Judge 1's precision against human judgment (how often did HITL overturn it?)".

Both functions here are pure/deterministic (read `review_decision` rows, do no
LLM calls themselves) -- the live part, replaying an overturned case through a
fresh Judge 1 call to check it doesn't get wrongly flagged again, lives in
run_regression.py, for the same reason Phase 4's adversarial eval couldn't be a
pure-Python check: verifying an LLM's judgment needs a live model.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class OverturnedCase:
    """A case where a human disagreed with Judge 1 -- approved or edited a claim
    Judge 1 had flagged as contradicted/unsupported. This is exactly what the
    regression suite exists to re-check: Judge 1 was wrong here once: is it still
    wrong the same way?"""

    review_item_id: int
    claim_id: str
    query: str
    claim_text: str
    standard_id: str
    clause: str
    quote: str
    judge1_verdict: str
    judge1_reasoning: str
    judge1_source: str  # "deterministic_check" or "llm_judge" -- see run_regression.py for why this matters for replay
    reviewer_action: str  # "approve" or "edit"
    reviewer_rationale: str


def overturned_cases(conn: sqlite3.Connection) -> list[OverturnedCase]:
    """Every review_item whose most recent decision was approve or edit -- i.e.
    every case where Judge 1 flagged a claim and a human decided it shouldn't
    have been flagged (or flagged it correctly but the *content* was fixable via
    edit, which is still "Judge 1's verdict didn't survive human review")."""
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
    """What fraction of all human decisions disagreed with Judge 1's verdict --
    the judge-precision metric from Sec 4.8. A decided item with status
    'approved'/'edited' means the human overturned the flag; 'rejected' means the
    human agreed Judge 1 was right to flag it."""
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
