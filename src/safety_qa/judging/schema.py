"""Judge 1's structured output contract. Verdict taxonomy per
artifacts/system-arch-and-roadmap.md Sec 4.4:
  - supported    -- quote entails the claim, quote is verbatim from the clause
  - contradicted -- clause says something different from, or opposite of, the claim
  - unsupported  -- clause doesn't address the claim, or the quote isn't verbatim
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["supported", "contradicted", "unsupported"]


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Verdict
    reasoning: str  # short justification; read by Judge 2 / a human reviewer


class GroundingJudgeOutput(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
