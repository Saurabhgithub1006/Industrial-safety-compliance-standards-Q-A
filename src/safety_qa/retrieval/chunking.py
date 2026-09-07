"""Phase 2 chunking: turn stored Clauses into retrievable Chunks.

Per artifacts/system-arch-and-roadmap.md Sec 5, `Chunk` is a distinct retrieval unit
from `Clause` -- decoupled so a clause could later be split into multiple chunks (a
very long clause) or several short clauses merged into one, without touching the
citation model. At this corpus's scale every clause is already a small, well-scoped
unit, so today it's a 1:1 projection; the seam is here for when that stops being true.

Scoping decision: chunks are built from EVERY clause with non-empty text, including
notes and the appendix -- excluding them from retrieval would make the system unable
to answer real questions about exceptions and non-mandatory guidance that a user might
legitimately ask about. `is_normative` rides along as metadata instead, so later
phases (generation, judges) can characterize a note-derived answer correctly ("per a
non-mandatory note...") rather than pretending it's a binding requirement. Filtering
it out of *retrieval* would be answering a citation-labeling problem by making the
system blind, which is the wrong trade.
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
