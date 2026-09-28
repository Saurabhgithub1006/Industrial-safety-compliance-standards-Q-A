"""Corpus persistence for the web app -- same shape as
safety_qa.ingestion.store, targeting the portable engine from db.py instead of a
raw sqlite3.Connection. Returns the exact same `Clause`/`Standard` dataclasses
the rest of the codebase (Retriever, GroundingJudge, Generator) already knows how
to use, so none of that logic needed to change at all.
"""

from __future__ import annotations

from sqlalchemy import Engine, delete, insert, select

from safety_qa.ingestion.models import Clause, Standard

from .models import clause as clause_table
from .models import standard as standard_table


def upsert_standard(engine: Engine, s: Standard) -> None:
    with engine.begin() as conn:
        conn.execute(delete(standard_table).where(standard_table.c.id == s.id))
        conn.execute(
            insert(standard_table).values(
                id=s.id, name=s.name, edition=s.edition,
                license_tier=s.license_tier, source_url=s.source_url,
            )
        )


def replace_clauses(engine: Engine, standard_id: str, clauses: list[Clause]) -> None:
    """Idempotent, same as the SQLite version: fully replaces this standard's
    clauses rather than accumulating stale rows alongside new ones."""
    with engine.begin() as conn:
        conn.execute(delete(clause_table).where(clause_table.c.standard_id == standard_id))
        if clauses:
            conn.execute(
                insert(clause_table),
                [
                    {
                        "citation_key": c.citation_key, "standard_id": c.standard_id,
                        "clause_path": c.clause_path, "parent_citation_key": c.parent_citation_key,
                        "depth": c.depth, "section_title": c.section_title, "text": c.text,
                        "clause_type": c.clause_type, "is_normative": c.is_normative,
                        "order_index": c.order_index,
                    }
                    for c in clauses
                ],
            )


def list_clauses(engine: Engine, standard_id: str) -> list[Clause]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(clause_table).where(clause_table.c.standard_id == standard_id).order_by(clause_table.c.order_index)
        ).fetchall()
    return [_row_to_clause(r) for r in rows]


def get_clause_by_path(engine: Engine, standard_id: str, clause_path: str) -> Clause | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(clause_table).where(
                clause_table.c.standard_id == standard_id, clause_table.c.clause_path == clause_path
            )
        ).fetchone()
    return _row_to_clause(row) if row else None


def corpus_is_empty(engine: Engine, standard_id: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(select(clause_table.c.citation_key).where(clause_table.c.standard_id == standard_id).limit(1)).fetchone()
    return row is None


def _row_to_clause(row) -> Clause:
    return Clause(
        standard_id=row.standard_id, citation_key=row.citation_key, clause_path=row.clause_path,
        parent_citation_key=row.parent_citation_key, depth=row.depth, section_title=row.section_title,
        text=row.text, clause_type=row.clause_type, is_normative=bool(row.is_normative),
        order_index=row.order_index,
    )
