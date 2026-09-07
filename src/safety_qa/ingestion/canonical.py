"""Clause identifier canonicalization.

Per artifacts/system-arch-and-roadmap.md Sec 4.1: every clause gets a normalized
`citation_key` (standard_id + canonical_path) at ingest time. Citations are matched
against this key everywhere downstream (generator output, Judge 1's clause lookup) --
never by fuzzy string similarity. Getting this right at ingest is cheap; retrofitting
it after claims/verdicts have accumulated against inconsistent keys is not.
"""

from __future__ import annotations

import re

_SEGMENT_RE = re.compile(r"\(([A-Za-z0-9]{1,4})\)")


def canonical_path(segments: list[str]) -> str:
    """Join ordered clause-path segments (e.g. ['c', '4', 'i']) into the canonical
    display/lookup form '(c)(4)(i)'."""
    return "".join(f"({s})" for s in segments)


def citation_key(standard_id: str, segments: list[str]) -> str:
    """Build the canonical key used to resolve a citation to exactly one clause.

    Format: '<STANDARD_ID>#<canonical_path>', e.g. 'OSHA-1910.147#(c)(4)(i)'.
    The standard id is upper-cased for consistency; path segments keep their written
    case as-is, since case is significant in this numbering scheme -- (a) and (A) are
    different clauses at different depths.
    """
    return f"{standard_id.upper()}#{canonical_path(segments)}"


def synthetic_citation_key(standard_id: str, segments: list[str], suffix: str) -> str:
    """Citation key for a non-numbered record attached to a real clause path --
    a Note, or a defined term inside a definitions block. `suffix` disambiguates it
    from the clause it's attached to (e.g. 'note', 'term:affected-employee')."""
    base = canonical_path(segments) if segments else ""
    return f"{standard_id.upper()}#{base}/{suffix}"


def parse_clause_ref(ref: str) -> tuple[str, list[str]]:
    """Split a citation string like 'OSHA-1910.147#(c)(4)(i)' back into
    (standard_id, segments) -- inverse of citation_key. Used to validate a
    generator/judge-supplied citation against the store instead of trusting it as-is."""
    if "#" not in ref:
        raise ValueError(f"not a canonical citation key: {ref!r}")
    standard_id, path = ref.split("#", 1)
    path = path.split("/", 1)[0]  # drop any /suffix for synthetic keys
    segments = _SEGMENT_RE.findall(path)
    return standard_id, segments


def slugify(term: str) -> str:
    """Lowercase, hyphenated slug for a defined term, e.g. 'Affected employee' ->
    'affected-employee'. Used to build synthetic citation keys for definition-list
    entries, which OSHA/IEC-style standards number as prose, not by clause marker."""
    term = term.strip().lower()
    term = re.sub(r"[^a-z0-9]+", "-", term)
    return term.strip("-")
