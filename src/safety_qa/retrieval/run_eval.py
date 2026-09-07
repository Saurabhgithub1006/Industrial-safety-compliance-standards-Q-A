"""Phase 2 CLI: build the retriever from the ingested corpus and report recall@k
against the golden eval set.

    PYTHONPATH=src python -m safety_qa.retrieval.run_eval
"""

from __future__ import annotations

from pathlib import Path

from safety_qa.ingestion.store import connect

from .eval_set import GOLDEN_SET, STANDARD_ID, recall_at_k
from .retriever import Retriever

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "corpus.db")


def run(db_path: str = _DEFAULT_DB_PATH, k: int = 5) -> None:
    conn = connect(db_path)
    retriever = Retriever.from_db(conn, STANDARD_ID)
    print(f"indexed {len(retriever.chunks)} chunks from {STANDARD_ID}")

    recall, details = recall_at_k(retriever, GOLDEN_SET, k)
    print(f"\nrecall@{k}: {recall:.2%} ({sum(d['hit'] for d in details)}/{len(details)})\n")

    for d in details:
        mark = "OK " if d["hit"] else "MISS"
        print(f"[{mark}] {d['question']}")
        print(f"        expected:  {list(d['expected'])}")
        print(f"        retrieved: {d['retrieved']}")


if __name__ == "__main__":
    run()
