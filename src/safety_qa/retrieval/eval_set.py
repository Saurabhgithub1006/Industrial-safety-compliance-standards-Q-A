"""Phase 2 exit criteria: recall@k on a golden question -> clause set.

Every question below was written against verified clause text pulled directly from
the ingested corpus.db (not guessed) -- see the parser output for exact wording.
Most map to exactly one clause; a few legitimately admit more than one correct
citation (e.g. a question a human could reasonably answer from either of two
adjacent clauses), so `expected_citation_keys` is a tuple and a hit counts if ANY of
them appears in the top-k.
"""

from __future__ import annotations

from dataclasses import dataclass

from .retriever import Retriever

STANDARD_ID = "OSHA-1910.147"


@dataclass(frozen=True)
class EvalCase:
    question: str
    expected_citation_keys: tuple[str, ...]


GOLDEN_SET: list[EvalCase] = [
    EvalCase(
        "How often must the energy control procedure be periodically inspected?",
        (f"{STANDARD_ID}#(c)(6)(i)",),
    ),
    EvalCase(
        "What is the definition of an authorized employee?",
        (f"{STANDARD_ID}#(b)/term:authorized-employee",),
    ),
    EvalCase(
        "What is a lockout device?",
        (f"{STANDARD_ID}#(b)/term:lockout-device",),
    ),
    EvalCase(
        "What must lockout and tagout devices be able to withstand?",
        (f"{STANDARD_ID}#(c)(5)(ii)(A)(1)",),
    ),
    EvalCase(
        "What training must an authorized employee receive about hazardous energy sources?",
        (f"{STANDARD_ID}#(c)(7)(i)(A)",),
    ),
    EvalCase(
        "What must happen when outside contractors will be servicing equipment covered by this standard?",
        (f"{STANDARD_ID}#(f)(2)(i)",),
    ),
    EvalCase(
        "What counts as an energy isolating device?",
        (f"{STANDARD_ID}#(b)/term:energy-isolating-device",),
    ),
    EvalCase(
        "What is required for group lockout or tagout when a crew is servicing equipment?",
        (f"{STANDARD_ID}#(f)(3)(i)",),
    ),
    EvalCase(
        "What must be verified before starting work on equipment that has been locked out?",
        (f"{STANDARD_ID}#(d)(6)",),
    ),
    EvalCase(
        "What must the employer do if an energy isolating device cannot be locked out?",
        (f"{STANDARD_ID}#(c)(2)(i)",),
    ),
    EvalCase(
        "What is a tagout device?",
        (f"{STANDARD_ID}#(b)/term:tagout-device",),
    ),
    EvalCase(
        "What must be done during shift or personnel changes to maintain lockout protection?",
        (f"{STANDARD_ID}#(f)(4)",),
    ),
    EvalCase(
        "Is there an exception for minor tool changes during normal production operations?",
        (f"{STANDARD_ID}#(a)(2)(ii)(B)/note",),
    ),
    EvalCase(
        "Does an employer always have to document the energy control procedure for every machine?",
        (f"{STANDARD_ID}#(c)(4)(i)/note",),
    ),
    EvalCase(
        "Who must be notified when lockout or tagout devices are applied or removed?",
        (f"{STANDARD_ID}#(c)(9)",),
    ),
]


def recall_at_k(retriever: Retriever, cases: list[EvalCase], k: int) -> tuple[float, list[dict]]:
    """Fraction of `cases` where at least one expected citation key appears in the
    top-k retrieved chunks, plus a per-case breakdown for debugging misses."""
    hits = 0
    details = []
    for case in cases:
        results = retriever.retrieve(case.question, top_k=k)
        retrieved_keys = [r.chunk.citation_key for r in results]
        hit = bool(set(retrieved_keys) & set(case.expected_citation_keys))
        hits += int(hit)
        details.append(
            {
                "question": case.question,
                "expected": case.expected_citation_keys,
                "retrieved": retrieved_keys,
                "hit": hit,
            }
        )
    recall = hits / len(cases) if cases else 0.0
    return recall, details
