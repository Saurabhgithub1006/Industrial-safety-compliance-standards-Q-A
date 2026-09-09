"""Ask a question and get a grounded, citation-checked answer (Phase 3).

    PYTHONPATH=src python -m safety_qa.generation.ask "what is a lockout device?"

Requires a real LLM API key in .env -- this is the first phase in the project that
actually calls an LLM. Everything before this point (ingestion, retrieval) is
deterministic code with no API dependency; this is where that changes. Provider
defaults to Kimi (set LLM_PROVIDER=anthropic in .env to use Claude instead) -- see
llm_client.build_client().
"""

from __future__ import annotations

import sys
from pathlib import Path

from safety_qa.ingestion.store import connect
from safety_qa.retrieval.eval_set import STANDARD_ID
from safety_qa.retrieval.retriever import Retriever

from .generator import GenerationError, Generator, GenerationResult
from .llm_client import build_client

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "corpus.db")


def _print_result(result: GenerationResult) -> None:
    print(f"\nquery: {result.query}\n")

    if result.valid_claims:
        print(f"claims ({len(result.valid_claims)}):")
        for claim in result.valid_claims:
            print(f"\n  - {claim.text}")
            print(f"    citation: {claim.citation.standard_id} {claim.citation.clause}")
            print(f"    quote: \"{claim.citation.quote}\"")
    else:
        print("claims: (none)")

    if result.rejected_claims:
        print(f"\nREJECTED claims ({len(result.rejected_claims)}) -- failed citation-grounding check, not shown as answers:")
        for rc in result.rejected_claims:
            print(f"\n  - {rc.claim.text}")
            print(f"    reason: {rc.reason}")

    if result.unsupported_aspects:
        print(f"\nunsupported (no clause found in the corpus for):")
        for a in result.unsupported_aspects:
            print(f"  - {a}")


def run(db_path: str = _DEFAULT_DB_PATH) -> None:
    if len(sys.argv) < 2:
        print("usage: python -m safety_qa.generation.ask \"your question\"")
        sys.exit(1)
    query = " ".join(sys.argv[1:])

    conn = connect(db_path)
    retriever = Retriever.from_db(conn, STANDARD_ID)
    generator = Generator(retriever, build_client("generator"))

    try:
        result = generator.answer(query)
    except GenerationError as e:
        print(f"generation failed: {e}")
        sys.exit(1)

    _print_result(result)


if __name__ == "__main__":
    run()
