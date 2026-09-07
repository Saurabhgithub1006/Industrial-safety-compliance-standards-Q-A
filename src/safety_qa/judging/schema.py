"""Judge 1's structured output contract.

Verdict taxonomy is exactly the one defined in
artifacts/system-arch-and-roadmap.md Sec 4.4:
  - supported    -- quote entails the claim, quote is verbatim from the cited clause
  - contradicted -- the cited clause says something different from (or the
                     opposite of) the claim
  - unsupported  -- cited clause exists but doesn't actually address the claim, or
                     quote doesn't match verbatim, or no citation was given at all
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["supported", "contradicted", "unsupported"]


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Verdict
    reasoning: str  # short justification -- this is what Judge 2 / a human reviewer reads


class GroundingJudgeOutput(BaseModel):
    verdicts: list[ClaimVerdict] = Field(default_factory=list)
