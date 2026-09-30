"""Phase 5: interactive HITL review queue.

    PYTHONPATH=src python -m safety_qa.review.cli --reviewer alice

Reviewer identity is required, never silently defaulted.
See artifacts/changelogs.md CHG-20260911-07 and CHG-20260912-09.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from .store import ReviewItem, connect, list_pending, record_decision

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "review_queue.db")


def apply_decision(
    conn: sqlite3.Connection,
    item: ReviewItem,
    action: str,
    reviewer_id: str,
    rationale: str,
    edited_text: str | None = None,
    edited_quote: str | None = None,
) -> None:
    """Testable core: validates and records one reviewer decision."""
    record_decision(
        conn, item.id, reviewer_id, action, rationale,
        edited_text=edited_text, edited_quote=edited_quote,
    )


def _print_item(item: ReviewItem) -> None:
    print(f"\n--- review item #{item.id} [{item.judge1_verdict}] ---")
    print(f"query: {item.query}")
    print(f"claim: {item.claim_text}")
    print(f"citation: {item.standard_id} {item.clause}")
    print(f'quote: "{item.quote}"')
    print(f"Judge 1 reasoning: {item.judge1_reasoning}")


def resolve_reviewer_id(argv: list[str]) -> str:
    """Never defaults silently: --reviewer NAME, or keeps prompting until non-empty."""
    if "--reviewer" in argv:
        idx = argv.index("--reviewer")
        if idx + 1 < len(argv) and argv[idx + 1].strip():
            return argv[idx + 1].strip()
    reviewer_id = ""
    while not reviewer_id:
        reviewer_id = input("reviewer identity (required -- who is making these decisions?): ").strip()
    return reviewer_id


def review_items_interactively(conn: sqlite3.Connection, items: list[ReviewItem], reviewer_id: str) -> None:
    """Interactive decision loop over a list of items; reused by pipeline.py's --wait mode."""
    for item in items:
        _print_item(item)
        while True:
            action = input("action [approve/edit/reject/skip]: ").strip().lower()
            if action == "skip":
                break
            if action not in ("approve", "edit", "reject"):
                print("  enter approve, edit, reject, or skip")
                continue
            rationale = input("rationale (required): ").strip()
            if not rationale:
                print("  rationale is required")
                continue
            edited_text = edited_quote = None
            if action == "edit":
                edited_text = input(f"corrected claim text [blank = keep \"{item.claim_text}\"]: ").strip() or None
                edited_quote = input(f"corrected quote [blank = keep as-is]: ").strip() or None
                if not edited_text and not edited_quote:
                    print("  edit requires a corrected claim text and/or quote")
                    continue
            apply_decision(conn, item, action, reviewer_id, rationale, edited_text, edited_quote)
            print(f"  recorded: {action}")
            break


def run(db_path: str = _DEFAULT_DB_PATH, reviewer_id: str | None = None) -> None:
    if reviewer_id is None:
        reviewer_id = resolve_reviewer_id(sys.argv[1:])
    conn = connect(db_path)
    items = list_pending(conn)
    if not items:
        print("queue is empty -- nothing pending review")
        return

    print(f"{len(items)} item(s) pending review (worst severity first)")
    review_items_interactively(conn, items, reviewer_id)


if __name__ == "__main__":
    run()
