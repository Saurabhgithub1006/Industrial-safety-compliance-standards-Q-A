"""Phase 5+7: the full loop, end to end.

    PYTHONPATH=src python -m safety_qa.review.pipeline "your question"
    PYTHONPATH=src python -m safety_qa.review.pipeline --wait --reviewer alice "your question"

generate -> judge -> log verdicts -> escalate/enqueue -> assemble. --wait reviews
inline in this run instead of leaving items for a later cli.py pass.
Needs an LLM API key. See artifacts/changelogs.md CHG-20260911-07 and CHG-20260912-09.
"""

from __future__ import annotations

import sys
from pathlib import Path

from safety_qa.generation.generator import Generator
from safety_qa.generation.llm_client import build_client
from safety_qa.ingestion.store import connect as connect_corpus
from safety_qa.judging.grounding_judge import GroundingJudge
from safety_qa.retrieval.eval_set import STANDARD_ID
from safety_qa.retrieval.retriever import Retriever

from .assembly import FinalAnswer, assemble_final_answer
from .cli import resolve_reviewer_id, review_items_interactively
from .escalation import build_packets
from .store import connect as connect_review
from .store import enqueue_all, get_item, log_verdicts

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CORPUS_DB = str(_REPO_ROOT / "data" / "processed" / "corpus.db")
_DEFAULT_REVIEW_DB = str(_REPO_ROOT / "data" / "processed" / "review_queue.db")


def _print_result(final: FinalAnswer) -> None:
    print(f"\nquery: {final.query}\n")
    if final.claims:
        print(f"claims ({len(final.claims)}):")
        for c in final.claims:
            print(f"\n  - {c.text}")
            print(f"    citation: {c.citation.standard_id} {c.citation.clause}")
    else:
        print("claims: (none yet -- see pending/rejected below)")

    if final.pending_count:
        print(f"\n{final.pending_count} point(s) pending human review -- not shown above yet.")
        print("Run `python -m safety_qa.review.cli` to review the queue.")
    if final.rejected_count:
        print(f"{final.rejected_count} point(s) were reviewed and rejected -- excluded.")
    if final.unsupported_aspects:
        print("\nunsupported (no clause found in the corpus for):")
        for a in final.unsupported_aspects:
            print(f"  - {a}")


def _parse_args(argv: list[str]) -> tuple[bool, list[str]]:
    """Pulls --wait out of argv; --reviewer is only required in --wait mode."""
    wait = "--wait" in argv
    remaining = [a for a in argv if a != "--wait"]
    return wait, remaining


def run(corpus_db_path: str = _DEFAULT_CORPUS_DB, review_db_path: str = _DEFAULT_REVIEW_DB) -> None:
    wait_for_review, remaining_argv = _parse_args(sys.argv[1:])
    reviewer_id = None
    if wait_for_review:
        reviewer_id = resolve_reviewer_id(remaining_argv)
        if "--reviewer" in remaining_argv:
            idx = remaining_argv.index("--reviewer")
            remaining_argv = remaining_argv[:idx] + remaining_argv[idx + 2:]
    if not remaining_argv:
        print('usage: python -m safety_qa.review.pipeline [--wait --reviewer NAME] "your question"')
        sys.exit(1)
    query = " ".join(remaining_argv)

    corpus_conn = connect_corpus(corpus_db_path)
    retriever = Retriever.from_db(corpus_conn, STANDARD_ID)
    generator = Generator(retriever, build_client("generator"))
    generation_result = generator.answer(query)

    judge = GroundingJudge(corpus_conn, build_client("judge"))
    judged = judge.evaluate(generation_result)

    review_conn = connect_review(review_db_path)
    log_verdicts(review_conn, judged.judged_claims, judged.query)  # logs every verdict, not just escalated ones

    packets = build_packets(judged)
    claim_id_to_item_id = enqueue_all(review_conn, packets)

    if wait_for_review:
        newly_pending = [
            item for item_id in set(claim_id_to_item_id.values())
            if (item := get_item(review_conn, item_id)) and item.status == "pending"
        ]
        if newly_pending:
            print(f"\n{len(newly_pending)} claim(s) need review before a final answer -- reviewing now:")
            review_items_interactively(review_conn, newly_pending, reviewer_id)

    final = assemble_final_answer(judged, review_conn, claim_id_to_item_id)
    _print_result(final)


if __name__ == "__main__":
    run()
