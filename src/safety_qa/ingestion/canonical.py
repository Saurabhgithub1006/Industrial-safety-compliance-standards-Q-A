"""Clause identifier canonicalization.
Builds and parses the citation_key format every clause is looked up by.
See artifacts/changelogs.md CHG-20260907-01 for the design rationale.
"""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"\(([A-Za-z0-9]{1,4})\)")


def canonical_path(segments: list[str]) -> str:
    """Join segments like ['c', '4', 'i'] into '(c)(4)(i)'."""
    return "".join(f"({s})" for s in segments)


def citation_key(standard_id: str, segments: list[str]) -> str:
    """Build the lookup key, e.g. 'OSHA-1910.147#(c)(4)(i)'."""
    return f"{standard_id.upper()}#{canonical_path(segments)}"


def synthetic_citation_key(standard_id: str, segments: list[str], suffix: str) -> str:
    """Key for a note or definition attached to a real clause path."""
    base = canonical_path(segments) if segments else ""
    return f"{standard_id.upper()}#{base}/{suffix}"


def parse_clause_ref(ref: str) -> tuple[str, list[str]]:
    """Split 'OSHA-1910.147#(c)(4)(i)' back into (standard_id, segments)."""
    if "#" not in ref:
        raise ValueError(f"not a canonical citation key: {ref!r}")
    standard_id, path = ref.split("#", 1)
    path = path.split("/", 1)[0]  # drop any /suffix for synthetic keys
    segments = _SEGMENT_RE.findall(path)
    return standard_id, segments


def slugify(term: str) -> str:
    """Turn 'Affected employee' into 'affected-employee'."""
    term = term.strip().lower()
    term = re.sub(r"[^a-z0-9]+", "-", term)
    return term.strip("-")
