"""SQLite persistence for the ingestion data model (Phase 1).

Mirrors `Standard` / `Clause` from artifacts/system-arch-and-roadmap.md Sec 5.
SQLite, not Postgres, per the tech-stack choice for local dev (Sec 6) -- Phase 1
has no concurrent-write or scale requirement that would justify anything heavier.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Clause, Standard

_SCHEMA = """
CREATE TABLE IF NOT EXISTS standard (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    edition       TEXT NOT NULL,
    license_tier  TEXT NOT NULL,
    source_url    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clause (
    citation_key         TEXT PRIMARY KEY,
    standard_id           TEXT NOT NULL REFERENCES standard(id),
    clause_path           TEXT NOT NULL,
    parent_citation_key   TEXT REFERENCES clause(citation_key),
    depth                 INTEGER NOT NULL,
    section_title         TEXT,
    text                  TEXT NOT NULL,
    clause_type           TEXT NOT NULL,
    is_normative           INTEGER NOT NULL,
    order_index            INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clause_standard ON clause(standard_id);
CREATE INDEX IF NOT EXISTS idx_clause_parent ON clause(parent_citation_key);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def upsert_standard(conn: sqlite3.Connection, standard: Standard) -> None:
    conn.execute(
        """INSERT INTO standard (id, name, edition, license_tier, source_url)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, edition=excluded.edition,
             license_tier=excluded.license_tier, source_url=excluded.source_url""",
        (standard.id, standard.name, standard.edition, standard.license_tier, standard.source_url),
    )
    conn.commit()


def replace_clauses(conn: sqlite3.Connection, standard_id: str, clauses: list[Clause]) -> None:
    """Replace all clauses for `standard_id` with `clauses` -- ingestion is
    idempotent: re-running it against an updated source fully replaces the prior
    snapshot rather than accumulating stale rows alongside new ones."""
    conn.execute("DELETE FROM clause WHERE standard_id = ?", (standard_id,))
    conn.executemany(
        """INSERT INTO clause
             (citation_key, standard_id, clause_path, parent_citation_key, depth,
              section_title, text, clause_type, is_normative, order_index)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                c.citation_key, c.standard_id, c.clause_path, c.parent_citation_key,
                c.depth, c.section_title, c.text, c.clause_type,
                int(c.is_normative), c.order_index,
            )
            for c in clauses
        ],
    )
    conn.commit()


def get_clause(conn: sqlite3.Connection, citation_key: str) -> Clause | None:
    """The Phase 1 exit-criteria operation: resolve any citation key to its exact
    clause, independent of ingestion order or file layout."""
    row = conn.execute("SELECT * FROM clause WHERE citation_key = ?", (citation_key,)).fetchone()
    return _row_to_clause(row) if row else None


def get_clause_by_path(conn: sqlite3.Connection, standard_id: str, clause_path: str) -> Clause | None:
    """Resolve a clause by its (standard_id, clause_path) pair -- the form a
    generated claim's citation actually carries (display path, not the internal
    citation_key). Used by Judge 1 (Phase 4) to independently re-fetch a cited
    clause straight from the corpus, deliberately not reusing whatever chunk object
    the generator already had -- an independent lookup is the whole point of a
    grounding check that "must not just trust the generator's framing."""
    row = conn.execute(
        "SELECT * FROM clause WHERE standard_id = ? AND clause_path = ?", (standard_id, clause_path)
    ).fetchone()
    return _row_to_clause(row) if row else None


def list_clauses(conn: sqlite3.Connection, standard_id: str) -> list[Clause]:
    rows = conn.execute(
        "SELECT * FROM clause WHERE standard_id = ? ORDER BY order_index", (standard_id,)
    ).fetchall()
    return [_row_to_clause(r) for r in rows]


def _row_to_clause(row: sqlite3.Row) -> Clause:
    return Clause(
        standard_id=row["standard_id"],
        citation_key=row["citation_key"],
        clause_path=row["clause_path"],
        parent_citation_key=row["parent_citation_key"],
        depth=row["depth"],
        section_title=row["section_title"],
        text=row["text"],
        clause_type=row["clause_type"],
        is_normative=bool(row["is_normative"]),
        order_index=row["order_index"],
    )
