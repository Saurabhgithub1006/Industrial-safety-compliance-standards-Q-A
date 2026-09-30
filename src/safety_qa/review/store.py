"""Phase 5+7: persistent review queue and verdict log.
Separate database file from corpus.db -- the corpus is regenerable, this queue
holds real human-decision history that must never be wiped.

  review_item        -- one row per escalated claim and its current status.
  review_decision     -- append-only audit trail of every decision ever made.
  judge_verdict_log   -- every Judge 1 verdict, supported or not (Phase 7).

Dedup on insert: a pending item for the same (standard_id, clause, claim_text)
absorbs a new escalation instead of duplicating it.
See artifacts/changelogs.md CHG-20260911-07 and CHG-20260912-09.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .escalation import EscalationPacket

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_item (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id          TEXT NOT NULL,
    query             TEXT NOT NULL,
    claim_text        TEXT NOT NULL,
    standard_id       TEXT NOT NULL,
    clause            TEXT NOT NULL,
    quote             TEXT NOT NULL,
    judge1_verdict    TEXT NOT NULL,
    judge1_reasoning  TEXT NOT NULL,
    judge1_source     TEXT NOT NULL DEFAULT 'llm_judge',
    severity          INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    edited_text       TEXT,
    edited_quote      TEXT,
    edited_clause     TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_decision (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    review_item_id    INTEGER NOT NULL REFERENCES review_item(id),
    reviewer_id       TEXT NOT NULL,
    action            TEXT NOT NULL,
    edited_text       TEXT,
    edited_quote      TEXT,
    rationale         TEXT NOT NULL,
    decided_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judge_verdict_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id          TEXT NOT NULL,
    query             TEXT NOT NULL,
    verdict           TEXT NOT NULL,
    reasoning         TEXT NOT NULL,
    source            TEXT NOT NULL,
    model             TEXT,
    prompt_version    TEXT,
    logged_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_item_status ON review_item(status);
"""

_VALID_ACTIONS = ("approve", "edit", "reject")


@dataclass(frozen=True)
class ReviewItem:
    id: int
    claim_id: str
    query: str
    claim_text: str
    standard_id: str
    clause: str
    quote: str
    judge1_verdict: str
    judge1_reasoning: str
    judge1_source: str
    severity: int
    status: str
    edited_text: str | None
    edited_quote: str | None
    edited_clause: str | None
    created_at: str


@dataclass(frozen=True)
class VerdictLogEntry:
    id: int
    claim_id: str
    query: str
    verdict: str
    reasoning: str
    source: str
    model: str | None
    prompt_version: str | None
    logged_at: str


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Adds columns missing from an older schema version, without touching existing rows."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(review_item)")}
    if "judge1_source" not in existing:
        conn.execute("ALTER TABLE review_item ADD COLUMN judge1_source TEXT NOT NULL DEFAULT 'llm_judge'")
        conn.commit()


def enqueue_all(conn: sqlite3.Connection, packets: list[EscalationPacket]) -> dict[str, int]:
    """Insert each packet as pending, or merge into a matching pending item.
    Returns claim_id -> review_item.id for every packet passed in."""
    result: dict[str, int] = {}
    for packet in packets:
        existing = conn.execute(
            """SELECT id FROM review_item
               WHERE standard_id = ? AND clause = ? AND claim_text = ? AND status = 'pending'""",
            (packet.standard_id, packet.clause, packet.claim_text),
        ).fetchone()
        if existing:
            result[packet.claim_id] = existing["id"]
            continue
        cur = conn.execute(
            """INSERT INTO review_item
                 (claim_id, query, claim_text, standard_id, clause, quote,
                  judge1_verdict, judge1_reasoning, judge1_source, severity, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                packet.claim_id, packet.query, packet.claim_text, packet.standard_id,
                packet.clause, packet.quote, packet.judge1_verdict, packet.judge1_reasoning,
                packet.judge1_source, packet.severity, _now(),
            ),
        )
        result[packet.claim_id] = cur.lastrowid
    conn.commit()
    return result


def list_pending(conn: sqlite3.Connection) -> list[ReviewItem]:
    rows = conn.execute(
        "SELECT * FROM review_item WHERE status = 'pending' ORDER BY severity DESC, created_at ASC"
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> ReviewItem | None:
    row = conn.execute("SELECT * FROM review_item WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row) if row else None


def record_decision(
    conn: sqlite3.Connection,
    item_id: int,
    reviewer_id: str,
    action: str,
    rationale: str,
    edited_text: str | None = None,
    edited_quote: str | None = None,
    edited_clause: str | None = None,
) -> None:
    if action not in _VALID_ACTIONS:
        raise ValueError(f"action must be one of {_VALID_ACTIONS}, got {action!r}")
    if action == "edit" and not (edited_text or edited_quote or edited_clause):
        raise ValueError("edit requires at least one of edited_text/edited_quote/edited_clause")
    if not rationale.strip():
        raise ValueError("rationale is required for every review decision")

    now = _now()
    conn.execute(
        """INSERT INTO review_decision
             (review_item_id, reviewer_id, action, edited_text, edited_quote, rationale, decided_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (item_id, reviewer_id, action, edited_text, edited_quote, rationale, now),
    )
    status = "approved" if action == "approve" else "edited" if action == "edit" else "rejected"
    conn.execute(
        """UPDATE review_item
           SET status = ?, edited_text = ?, edited_quote = ?, edited_clause = ?
           WHERE id = ?""",
        (status, edited_text, edited_quote, edited_clause, item_id),
    )
    conn.commit()


def log_verdict(conn: sqlite3.Connection, judged_claim, query: str) -> None:
    """Records one Judge 1 verdict, supported included, as a JudgedClaim by duck typing."""
    conn.execute(
        """INSERT INTO judge_verdict_log
             (claim_id, query, verdict, reasoning, source, model, prompt_version, logged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            judged_claim.claim.claim_id, query, judged_claim.verdict, judged_claim.reasoning,
            judged_claim.source, judged_claim.model, judged_claim.prompt_version, _now(),
        ),
    )
    conn.commit()


def log_verdicts(conn: sqlite3.Connection, judged_claims, query: str) -> None:
    for jc in judged_claims:
        log_verdict(conn, jc, query)


def list_verdict_log(conn: sqlite3.Connection, claim_id: str | None = None) -> list[VerdictLogEntry]:
    if claim_id is not None:
        rows = conn.execute(
            "SELECT * FROM judge_verdict_log WHERE claim_id = ? ORDER BY id", (claim_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM judge_verdict_log ORDER BY id").fetchall()
    return [
        VerdictLogEntry(
            id=r["id"], claim_id=r["claim_id"], query=r["query"], verdict=r["verdict"],
            reasoning=r["reasoning"], source=r["source"], model=r["model"],
            prompt_version=r["prompt_version"], logged_at=r["logged_at"],
        )
        for r in rows
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_item(row: sqlite3.Row) -> ReviewItem:
    return ReviewItem(
        id=row["id"], claim_id=row["claim_id"], query=row["query"], claim_text=row["claim_text"],
        standard_id=row["standard_id"], clause=row["clause"], quote=row["quote"],
        judge1_verdict=row["judge1_verdict"], judge1_reasoning=row["judge1_reasoning"],
        judge1_source=row["judge1_source"],
        severity=row["severity"], status=row["status"], edited_text=row["edited_text"],
        edited_quote=row["edited_quote"], edited_clause=row["edited_clause"], created_at=row["created_at"],
    )
