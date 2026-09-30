"""Pydantic request/response models for the HTTP API; separate from
safety_qa.generation.schema's internal pipeline contract.
"""

from __future__ import annotations

from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class ClaimOut(BaseModel):
    text: str
    standard_id: str
    clause: str
    quote: str


class AskResponse(BaseModel):
    query: str
    claims: list[ClaimOut]
    pending_count: int
    rejected_count: int
    unsupported_aspects: list[str]


class ReviewItemOut(BaseModel):
    id: int
    query: str
    claim_text: str
    standard_id: str
    clause: str
    quote: str
    judge1_verdict: str
    judge1_reasoning: str
    severity: int
    created_at: str


class DecisionRequest(BaseModel):
    reviewer_id: str
    action: str  # approve | edit | reject
    rationale: str
    edited_text: str | None = None
    edited_quote: str | None = None


class HealthResponse(BaseModel):
    status: str
    corpus_loaded: bool
    clause_count: int
