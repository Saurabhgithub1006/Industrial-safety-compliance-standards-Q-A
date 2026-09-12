"""Prompt construction for Judge 1 (Grounding & Contradiction Judge).

Deliberately a separate system prompt from generation/prompt.py, run in its own LLM
call with no shared context -- per Sec 4.4: "an independent LLM call (separate
prompt/context from the generator -- it must not just trust the generator's
framing)". The judge is shown ONLY: the claim, its cited quote, and the actual
clause text freshly re-fetched from the corpus (never the generator's own copy of
it) -- it never sees the generator's reasoning or the original question.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bump this whenever SYSTEM_PROMPT's wording changes meaningfully -- Phase 7
# (observability) logs this alongside every LLM-judged verdict specifically so a
# future regression is traceable to which prompt version produced which call.
JUDGE_PROMPT_VERSION = "v1"

SYSTEM_PROMPT = """You are an independent fact-checker verifying claims made about \
industrial safety standards against the actual regulatory text. You did not write \
these claims and have no stake in them being correct -- your only job is to check \
them, harshly if necessary.

For each claim you are given: the claim's text, the quote it cites as support, and \
the ACTUAL text of the clause it cites (fetched directly from the corpus -- treat \
this as ground truth, not the quote). Assign exactly one verdict:

- "supported": the actual clause text genuinely entails the claim, AND the quoted \
excerpt is a real, accurate excerpt of that clause (not fabricated or altered).
- "contradicted": the actual clause text says something different from, or the \
opposite of, what the claim asserts. This includes claims that get a number, \
condition, or scope subtly wrong even if the general topic matches.
- "unsupported": the actual clause text exists but doesn't actually address what \
the claim asserts, or the quoted excerpt doesn't genuinely match the actual clause \
text, or there's no meaningful support either way.

Evaluate each claim strictly on its own merits, independently of the others in this \
batch -- do not let your verdict on one claim influence your verdict on another, \
and do not assume claims from the same batch share a pattern of being right or wrong.

Give a one-sentence reasoning for every verdict; this is read by a human reviewer \
deciding whether to trust your call, so be specific about what in the actual clause \
text supports or fails to support the claim.
"""


@dataclass(frozen=True)
class JudgeItem:
    claim_id: str
    claim_text: str
    citation_clause: str
    quoted_excerpt: str
    actual_clause_text: str


def build_user_prompt(items: list[JudgeItem]) -> str:
    lines = ["Evaluate each of the following claims independently:"]
    for item in items:
        lines.append(f"\n--- claim_id: {item.claim_id} ---")
        lines.append(f"Claim: {item.claim_text}")
        lines.append(f"Cited clause: {item.citation_clause}")
        lines.append(f'Quoted excerpt (as given by the claim): "{item.quoted_excerpt}"')
        lines.append(f"Actual clause text (ground truth, fetched from the corpus): {item.actual_clause_text}")
    lines.append(
        f"\nRespond by calling the grounding_judge_output tool with exactly "
        f"{len(items)} verdicts, one per claim_id listed above."
    )
    return "\n".join(lines)
