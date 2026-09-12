"""Phase 6 CLI: replay every human-overturned case through a fresh Judge 1 call,
and report the judge-override-rate metric.

    PYTHONPATH=src python -m safety_qa.review.run_regression

Needs a real LLM API key and both databases (data/processed/corpus.db,
data/processed/review_queue.db) -- see regression.py's docstring for why the
replay itself can't be a pure-Python/CI-enforced check the same way Phase 2's
recall@k was: verifying an LLM's judgment needs a live model.
"""

from __future__ import annotations

from pathlib import Path

from safety_qa.generation.llm_client import build_client
from safety_qa.generation.schema import Citation, Claim
from safety_qa.ingestion.store import connect as connect_corpus
from safety_qa.judging.grounding_judge import GroundingJudge

from .regression import overturned_cases, override_rate
from .store import connect as connect_review

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORPUS_DB = str(_REPO_ROOT / "data" / "processed" / "corpus.db")
_DEFAULT_REVIEW_DB = str(_REPO_ROOT / "data" / "processed" / "review_queue.db")


def run(corpus_db_path: str = _DEFAULT_CORPUS_DB, review_db_path: str = _DEFAULT_REVIEW_DB) -> None:
    corpus_conn = connect_corpus(corpus_db_path)
    review_conn = connect_review(review_db_path)

    report = override_rate(review_conn)
    print("judge-override rate (how often a human disagreed with Judge 1):")
    if report["total_decided"] == 0:
        print("  no decided items yet -- nothing to report")
    else:
        print(
            f"  {report['overturned']}/{report['total_decided']} decisions overturned Judge 1 "
            f"({report['override_rate']:.1%}); {report['confirmed']} confirmed Judge 1 was right"
        )

    cases = overturned_cases(review_conn)
    if not cases:
        print("\nno overturned cases to replay -- regression suite is empty until a human overturns a verdict")
        return

    # Only llm_judge-sourced verdicts can drift across prompt/model changes --
    # a deterministic_check catch (hallucinated citation, non-verbatim quote) is a
    # pure string/lookup check that will reproduce identically every time unless
    # the corpus itself changes, so replaying it through the model tests nothing
    # and would just spend an API call for no signal.
    replayable = [c for c in cases if c.judge1_source == "llm_judge"]
    deterministic_only = [c for c in cases if c.judge1_source != "llm_judge"]

    if deterministic_only:
        print(f"\n{len(deterministic_only)} overturned case(s) were originally caught by the deterministic "
              f"check, not Judge 1's own judgment -- not replayed (nothing to drift):")
        for case in deterministic_only:
            print(f"  - {case.claim_text[:70]} (human {_past_tense(case.reviewer_action)} it: \"{case.reviewer_rationale}\")")

    if not replayable:
        print("\nno LLM-judged overturned cases to replay.")
        return

    judge = GroundingJudge(corpus_conn, build_client("judge"))
    print(f"\nreplaying {len(replayable)} LLM-judged overturned case(s) through a fresh Judge 1 call:")
    regressions = 0
    for case in replayable:
        claim = Claim(
            claim_id=case.claim_id, text=case.claim_text,
            citation=Citation(standard_id=case.standard_id, clause=case.clause, quote=case.quote),
        )
        [fresh] = judge.evaluate_claims([claim])
        still_flagged = fresh.verdict != "supported"
        mark = "REGRESSION" if still_flagged else "ok"
        print(f"\n  [{mark}] {case.claim_text[:70]}")
        print(f"    originally: Judge 1 said {case.judge1_verdict!r}, human {_past_tense(case.reviewer_action)} it "
              f"(\"{case.reviewer_rationale}\")")
        print(f"    now: Judge 1 says {fresh.verdict!r} ({fresh.reasoning})")
        if still_flagged:
            regressions += 1

    print(f"\n{regressions}/{len(replayable)} still wrongly flagged on replay.")


def _past_tense(action: str) -> str:
    return {"approve": "approved", "edit": "edited"}.get(action, action)


if __name__ == "__main__":
    run()
