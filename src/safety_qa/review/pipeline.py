"""Phase 5: the full loop, end to end.

    PYTHONPATH=src python -m safety_qa.review.pipeline "your question"

generate (Phase 3) -> judge (Phase 4) -> escalate + enqueue (Phase 5, Judge 2) ->
assemble the final answer from what's already trustworthy plus whatever HITL has
already cleared from a PRIOR run of safety_qa.review.cli. This is the concrete
demonstration of the Phase 5 exit criteria: generation -> Judge 1 flag -> Judge 2
packet -> human decision -> correct effect on the final answer.

Needs a real LLM API key (see generation/ask.py) -- this wires together Phases 3
and 4, both of which call an LLM.
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
from .escalation import build_packets
from .store import connect as connect_review
from .store import enqueue_all

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


def run(corpus_db_path: str = _DEFAULT_CORPUS_DB, review_db_path: str = _DEFAULT_REVIEW_DB) -> None:
    if len(sys.argv) < 2:
        print('usage: python -m safety_qa.review.pipeline "your question"')
        sys.exit(1)
    query = " ".join(sys.argv[1:])

    corpus_conn = connect_corpus(corpus_db_path)
    retriever = Retriever.from_db(corpus_conn, STANDARD_ID)
    generator = Generator(retriever, build_client("generator"))
    generation_result = generator.answer(query)

    judge = GroundingJudge(corpus_conn, build_client("judge"))
    judged = judge.evaluate(generation_result)

    review_conn = connect_review(review_db_path)
    packets = build_packets(judged)
    claim_id_to_item_id = enqueue_all(review_conn, packets)
    final = assemble_final_answer(judged, review_conn, claim_id_to_item_id)

    _print_result(final)


if __name__ == "__main__":
    run()
