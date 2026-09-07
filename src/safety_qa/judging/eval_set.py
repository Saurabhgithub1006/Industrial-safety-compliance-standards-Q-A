"""Phase 4 exit criteria: an adversarial eval set for Judge 1, per the roadmap --
"deliberately wrong citations, subtly altered quotes, contradicted claims" -- with
judge precision/recall measured against it.

Honesty note this eval set forces: unlike Phase 2's recall@k (pure Python, testable
in CI with zero external dependencies), the "contradicted" verdict fundamentally
requires semantic judgment -- there is no deterministic way to verify a judge
correctly identifies that a claim misrepresents a clause without asking a real LLM
whether it caught it. So this eval set is exercised by run_judge_eval.py against a
live model (needs ANTHROPIC_API_KEY), not enforced as a pytest threshold the way
Phase 2's was. tests/test_judging.py still covers the deterministic layer
(hallucinated citations, non-verbatim quotes) and the plumbing (batching, retry,
claim_id mapping) with zero API dependency -- what's untestable without a live
model is specifically the semantic supported-vs-contradicted distinction.

Every case cites a real clause from the ingested OSHA-1910.147 corpus, verified
against the actual stored text (see data/processed/corpus.db).
"""

from __future__ import annotations

from dataclasses import dataclass

from safety_qa.generation.schema import Citation, Claim
from safety_qa.judging.schema import Verdict

STANDARD_ID = "OSHA-1910.147"


@dataclass(frozen=True)
class AdversarialCase:
    description: str
    claim: Claim
    expected_verdict: Verdict


def _claim(claim_id: str, text: str, clause: str, quote: str) -> Claim:
    return Claim(
        claim_id=claim_id, text=text,
        citation=Citation(standard_id=STANDARD_ID, clause=clause, quote=quote),
    )


ADVERSARIAL_SET: list[AdversarialCase] = [
    # -- genuinely correct claims (positive control) --------------------------
    AdversarialCase(
        "correct paraphrase, verbatim quote",
        _claim(
            "s1", "The employer must inspect the energy control procedure at least once a year.",
            "(c)(6)(i)",
            "The employer shall conduct a periodic inspection of the energy control procedure at least annually to ensure that the procedure and the requirements of this standard are being followed.",
        ),
        "supported",
    ),
    AdversarialCase(
        "correct claim, exact requirement restated",
        _claim(
            "s2", "Lockout and tagout devices must be able to withstand the environment they are exposed to.",
            "(c)(5)(ii)(A)(1)",
            "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed for the maximum period of time that exposure is expected.",
        ),
        "supported",
    ),
    AdversarialCase(
        "correct claim about outside contractors",
        _claim(
            "s3", "When outside servicing personnel will be on site, the on-site employer and the outside employer must inform each other of their lockout or tagout procedures.",
            "(f)(2)(i)",
            "Whenever outside servicing personnel are to be engaged in activities covered by the scope and application of this standard, the on-site employer and the outside employer shall inform each other of their respective lockout or tagout procedures.",
        ),
        "supported",
    ),
    # -- contradicted: verbatim quote, but the claim misrepresents it ---------
    AdversarialCase(
        "wrong frequency -- clause says annually, claim says monthly",
        _claim(
            "c1", "The employer must inspect the energy control procedure at least once a month.",
            "(c)(6)(i)",
            "The employer shall conduct a periodic inspection of the energy control procedure at least annually to ensure that the procedure and the requirements of this standard are being followed.",
        ),
        "contradicted",
    ),
    AdversarialCase(
        "inverted requirement -- clause says devices SHALL withstand, claim says need not",
        _claim(
            "c2", "Lockout and tagout devices are not required to withstand the environment they are exposed to.",
            "(c)(5)(ii)(A)(1)",
            "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed for the maximum period of time that exposure is expected.",
        ),
        "contradicted",
    ),
    AdversarialCase(
        "inverted requirement -- clause requires mutual disclosure, claim says it's optional",
        _claim(
            "c3", "It is optional, not required, for the on-site and outside employers to share their lockout/tagout procedures with each other.",
            "(f)(2)(i)",
            "Whenever outside servicing personnel are to be engaged in activities covered by the scope and application of this standard, the on-site employer and the outside employer shall inform each other of their respective lockout or tagout procedures.",
        ),
        "contradicted",
    ),
    # -- unsupported: hallucinated citation (deterministic layer should catch) -
    AdversarialCase(
        "citation to a clause that doesn't exist",
        _claim(
            "u1", "Lockout devices must be inspected by a third party annually.",
            "(z)(99)",
            "Lockout devices must be inspected by a third party annually.",
        ),
        "unsupported",
    ),
    # -- unsupported: altered quote (deterministic layer should catch) --------
    AdversarialCase(
        "quote subtly altered from the actual clause text",
        _claim(
            "u2", "The employer must inspect the energy control procedure at least annually.",
            "(c)(6)(i)",
            "The employer shall conduct a periodic inspection of the energy control procedure at least annually and biannually to ensure compliance.",
        ),
        "unsupported",
    ),
    # -- unsupported: real clause, verbatim quote, but doesn't address the claim
    AdversarialCase(
        "real verbatim quote, but claim asserts something the clause doesn't address",
        _claim(
            "u3", "Lockout devices must be manufactured in the United States.",
            "(c)(5)(ii)(A)(1)",
            "Lockout and tagout devices shall be capable of withstanding the environment to which they are exposed for the maximum period of time that exposure is expected.",
        ),
        "unsupported",
    ),
]


def precision_recall(predicted: list[Verdict], expected: list[Verdict]) -> dict:
    """Per-class precision/recall plus overall accuracy, for the run_judge_eval.py
    report. `predicted`/`expected` must be the same length and order."""
    assert len(predicted) == len(expected)
    labels: list[Verdict] = ["supported", "contradicted", "unsupported"]
    report = {}
    correct = 0
    for label in labels:
        tp = sum(1 for p, e in zip(predicted, expected) if p == label and e == label)
        fp = sum(1 for p, e in zip(predicted, expected) if p == label and e != label)
        fn = sum(1 for p, e in zip(predicted, expected) if p != label and e == label)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        report[label] = {"precision": precision, "recall": recall, "support": sum(1 for e in expected if e == label)}
    correct = sum(1 for p, e in zip(predicted, expected) if p == e)
    report["accuracy"] = correct / len(expected) if expected else 0.0
    return report
