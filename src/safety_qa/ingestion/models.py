"""Core ingestion data model (Phase 1).

Mirrors the `Standard` / `Clause` tables sketched in
artifacts/system-arch-and-roadmap.md Sec 5, scoped to what ingestion needs.
Retrieval/embedding fields (the `Chunk` table) land in Phase 2 -- Phase 1's job is
just to get every clause into the store, correctly identified and independently
queryable, with nothing lost or mis-attributed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Standard:
    id: str  # canonical standard id, e.g. "OSHA-1910.147"
    name: str  # e.g. "The control of hazardous energy (lockout/tagout)"
    edition: str  # e.g. "29 CFR 1910.147 (eCFR, retrieved 2026-09-07)"
    license_tier: str  # e.g. "public_domain"
    source_url: str


@dataclass(frozen=True)
class Clause:
    standard_id: str
    citation_key: str  # canonical, e.g. "OSHA-1910.147#(c)(4)(i)"
    clause_path: str  # display form, e.g. "(c)(4)(i)"
    parent_citation_key: str | None
    depth: int  # 1 = top-level (a)/(b)/(c)..., deeper = nested
    section_title: str | None  # short heading text this clause carries, if any
    text: str  # this clause's own text only, not its children's
    clause_type: str  # "requirement" | "definition" | "note" | "appendix"
    is_normative: bool  # False for notes/appendix -- explanatory, not a citable requirement
    order_index: int  # ingestion order, for stable display ordering
