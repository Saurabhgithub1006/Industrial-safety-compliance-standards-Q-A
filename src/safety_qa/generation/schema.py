"""The structured claims contract from artifacts/system-arch-and-roadmap.md Sec 2:
the generator never returns free-text prose. It returns discrete, independently
checkable claims, each with a citation and a verbatim quote -- or an explicit
unsupported marker when nothing in the corpus backs part of the question. This is
what makes automatic grounding-checking (Phase 4's Judge 1) possible at all: you
can't fact-check a paragraph, but you can fact-check a (claim, quote, clause) triple.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    standard_id: str
    clause: str  # display form, e.g. "(c)(4)(i)" -- must match a retrieved chunk's clause_path
    quote: str  # verbatim substring of that chunk's text -- checked, not trusted


class Claim(BaseModel):
    claim_id: str
    text: str
    citation: Citation
    status: Literal["pending_judge"] = "pending_judge"


class GeneratedAnswer(BaseModel):
    query: str
    claims: list[Claim] = Field(default_factory=list)
    # Parts of the question the retrieved chunks don't actually answer -- populated
    # instead of inventing a plausible-sounding citation. An empty list here is a
    # claim in itself ("everything asked was covered"), not just an unfilled default.
    unsupported_aspects: list[str] = Field(default_factory=list)
