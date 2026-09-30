"""Turns stored Clauses into retrievable Chunks (currently a 1:1 projection).
Includes notes and appendix text; is_normative flags them for later phases.
Scoping rationale: artifacts/changelogs.md CHG-20260907-02.
"""

from __future__ import annotations

from dataclasses import dataclass

from safety_qa.ingestion.models import Clause


@dataclass(frozen=True)
class Chunk:
    citation_key: str
    standard_id: str
    clause_path: str
    section_title: str | None
    clause_type: str
    is_normative: bool
    text: str  # exact clause text -- what gets quoted/cited; never altered for search

    @property
    def index_text(self) -> str:
        """Text actually handed to the retrieval indexes. A defined term's own body
        often never repeats the term itself ("Lockout device." -> "A device that
        utilizes a positive means...") -- prepending the title/term means a query
        like "what is a lockout device?" can lexically anchor on it. `text` (the
        citable/quotable form) stays untouched; this exists only for search."""
        if self.section_title:
            return f"{self.section_title}. {self.text}"
        return self.text


def build_chunks(clauses: list[Clause]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for c in clauses:
        text = c.text.strip()
        if not text:
            continue
        chunks.append(
            Chunk(
                citation_key=c.citation_key,
                standard_id=c.standard_id,
                clause_path=c.clause_path,
                section_title=c.section_title,
                clause_type=c.clause_type,
                is_normative=c.is_normative,
                text=text,
            )
        )
    return chunks
