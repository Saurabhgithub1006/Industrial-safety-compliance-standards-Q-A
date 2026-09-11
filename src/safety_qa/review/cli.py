"""Phase 5: interactive HITL review queue.

    PYTHONPATH=src python -m safety_qa.review.cli

Per the Phase 5 kickoff decision (D2): a CLI, consistent with the project's
existing ask.py/run_eval.py pattern, rather than a new web-UI dependency. The
decision-applying logic (`apply_decision`) is deliberately separate from the
`input()`-driven loop so it's unit-testable without simulating stdin.
"""

from __future__ import annotations

import sqlite3
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
    """The testable core: validates and records one reviewer decision.
    `store.record_decision` does the actual validation/persistence -- this
    wrapper exists as the CLI's stable entry point, independent of how the
    interactive loop below happens to gather its arguments."""
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


def run(db_path: str = _DEFAULT_DB_PATH, reviewer_id: str = "local-reviewer") -> None:
    conn = connect(db_path)
    items = list_pending(conn)
    if not items:
        print("queue is empty -- nothing pending review")
        return

    print(f"{len(items)} item(s) pending review (worst severity first)")
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


if __name__ == "__main__":
    run()
