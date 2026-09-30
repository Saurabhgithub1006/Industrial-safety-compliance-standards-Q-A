"""Structured claims contract (Pydantic). The generator returns discrete,
checkable claims with citations, never free-text prose.
See artifacts/system-arch-and-roadmap.md Sec 2.
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
    # Parts of the question the corpus doesn't answer; empty list means "fully covered".
    unsupported_aspects: list[str] = Field(default_factory=list)
