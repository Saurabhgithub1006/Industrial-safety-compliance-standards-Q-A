"""Core ingestion data model. Standard and Clause, one row each per table."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Standard:
    id: str
    name: str
    edition: str
    license_tier: str
    source_url: str


@dataclass(frozen=True)
class Clause:
    standard_id: str
    citation_key: str
    clause_path: str
    parent_citation_key: str | None
    depth: int
    section_title: str | None
    text: str
    clause_type: str  # requirement | definition | note | appendix
    is_normative: bool  # false for notes/appendix
    order_index: int
