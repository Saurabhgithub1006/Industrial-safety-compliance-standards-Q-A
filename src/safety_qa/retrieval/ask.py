"""Ad-hoc query CLI -- type a question, see what Phase 2 retrieval finds for it.

    PYTHONPATH=src python -m safety_qa.retrieval.ask "what is a lockout device?"

Or with no argument, drops into an interactive loop (type 'quit' to exit). This is
NOT the final answering system -- there's no generation/LLM step yet (that's
Phase 3). It just shows you, honestly, what the retriever hands to that future step:
the top-k clause chunks and their citation keys, nothing synthesized on top.
"""

from __future__ import annotations

import sys
from pathlib import Path

from safety_qa.ingestion.store import connect

from .eval_set import STANDARD_ID
from .retriever import Retriever

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "corpus.db")


def _print_results(retriever: Retriever, query: str, top_k: int = 5) -> None:
    results = retriever.retrieve(query, top_k=top_k)
    if not results:
        print("  (no results)")
        return
    for rank, r in enumerate(results, start=1):
        c = r.chunk
        flag = "" if c.is_normative else "  [NON-NORMATIVE: note/appendix, not a binding requirement]"
        print(f"\n  #{rank}  {c.citation_key}{flag}")
        if c.section_title:
            print(f"      title: {c.section_title}")
        print(f"      rrf={r.rrf_score:.4f}  bm25_rank={r.bm25_rank}  semantic_rank={r.semantic_rank}")
        snippet = c.text if len(c.text) <= 300 else c.text[:300] + "..."
        print(f"      text: {snippet}")


def run(db_path: str = _DEFAULT_DB_PATH) -> None:
    conn = connect(db_path)
    retriever = Retriever.from_db(conn, STANDARD_ID)
    print(f"indexed {len(retriever.chunks)} chunks from {STANDARD_ID}\n")

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"query: {query}")
        _print_results(retriever, query)
        return

    print("interactive mode -- type a question, or 'quit' to exit")
    while True:
        try:
            query = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in ("quit", "exit"):
            break
        _print_results(retriever, query)


if __name__ == "__main__":
    run()
