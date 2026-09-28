"""SQLAlchemy Core table definitions for the deployed web app.

Schema mirrors the existing SQLite stores (safety_qa.ingestion.store,
safety_qa.review.store) as closely as possible, so the two systems stay
conceptually interchangeable -- same fields, same meaning -- even though this one
targets PostgreSQL in production. SQLAlchemy Core (not raw psycopg2, not the ORM)
so the exact same table definitions and queries run against SQLite locally
(zero-install testing) and PostgreSQL in production, with no per-dialect branches
in application code -- only the DATABASE_URL differs.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

# ---------------------------------------------------------------------------
# Corpus (mirrors safety_qa.ingestion.store's `standard` / `clause` tables)
# ---------------------------------------------------------------------------

standard = Table(
    "standard",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", Text, nullable=False),
    Column("edition", Text, nullable=False),
    Column("license_tier", Text, nullable=False),
    Column("source_url", Text, nullable=False),
)

clause = Table(
    "clause",
    metadata,
    Column("citation_key", String, primary_key=True),
    Column("standard_id", String, ForeignKey("standard.id"), nullable=False),
    Column("clause_path", Text, nullable=False),
    Column("parent_citation_key", String, ForeignKey("clause.citation_key"), nullable=True),
    Column("depth", Integer, nullable=False),
    Column("section_title", Text, nullable=True),
    Column("text", Text, nullable=False),
    Column("clause_type", String, nullable=False),
    Column("is_normative", Boolean, nullable=False),
    Column("order_index", Integer, nullable=False),
)

# ---------------------------------------------------------------------------
# Review queue (mirrors safety_qa.review.store's tables)
# ---------------------------------------------------------------------------

review_item = Table(
    "review_item",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", String, nullable=False),
    Column("query", Text, nullable=False),
    Column("claim_text", Text, nullable=False),
    Column("standard_id", String, nullable=False),
    Column("clause", String, nullable=False),
    Column("quote", Text, nullable=False),
    Column("judge1_verdict", String, nullable=False),
    Column("judge1_reasoning", Text, nullable=False),
    Column("judge1_source", String, nullable=False, server_default="llm_judge"),
    Column("severity", Integer, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
    Column("edited_text", Text, nullable=True),
    Column("edited_quote", Text, nullable=True),
    Column("edited_clause", Text, nullable=True),
    Column("created_at", String, nullable=False),
)

review_decision = Table(
    "review_decision",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("review_item_id", Integer, ForeignKey("review_item.id"), nullable=False),
    Column("reviewer_id", String, nullable=False),
    Column("action", String, nullable=False),
    Column("edited_text", Text, nullable=True),
    Column("edited_quote", Text, nullable=True),
    Column("rationale", Text, nullable=False),
    Column("decided_at", String, nullable=False),
)

judge_verdict_log = Table(
    "judge_verdict_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", String, nullable=False),
    Column("query", Text, nullable=False),
    Column("verdict", String, nullable=False),
    Column("reasoning", Text, nullable=False),
    Column("source", String, nullable=False),
    Column("model", String, nullable=True),
    Column("prompt_version", String, nullable=True),
    Column("logged_at", String, nullable=False),
)
