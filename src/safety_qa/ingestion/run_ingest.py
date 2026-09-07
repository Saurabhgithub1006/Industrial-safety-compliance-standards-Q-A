"""Phase 1 ingestion CLI: parse a source file and load it into the clause store.

    python -m safety_qa.ingestion.run_ingest

Currently wires up the one Phase 1 corpus source (OSHA 1910.147). Adding a second
source means adding a `_INGEST_JOBS` entry with its own parser -- the store and
canonicalization layers are already source-agnostic.
"""

from __future__ import annotations

from pathlib import Path

from .models import Standard
from .parser_osha_ecfr import parse_osha_section
from .store import connect, list_clauses, replace_clauses, upsert_standard

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "corpus.db")

_INGEST_JOBS = [
    {
        "standard_id": "OSHA-1910.147",
        "source_path": str(_REPO_ROOT / "data" / "raw" / "osha_1910_147_raw.xml"),
        "source_url": "https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XVII/part-1910/subpart-J/section-1910.147",
        "license_tier": "public_domain",
    },
]


def run(db_path: str = _DEFAULT_DB_PATH) -> None:
    conn = connect(db_path)
    for job in _INGEST_JOBS:
        heading, clauses = parse_osha_section(job["source_path"], job["standard_id"])
        standard = Standard(
            id=job["standard_id"],
            name=heading,
            edition="29 CFR " + job["standard_id"].split("-", 1)[1] + " (eCFR snapshot)",
            license_tier=job["license_tier"],
            source_url=job["source_url"],
        )
        upsert_standard(conn, standard)
        replace_clauses(conn, job["standard_id"], clauses)
        print(f"[{job['standard_id']}] ingested {len(clauses)} clauses -> {db_path}")

    total = sum(len(list_clauses(conn, job["standard_id"])) for job in _INGEST_JOBS)
    print(f"done. {total} clauses total across {len(_INGEST_JOBS)} standard(s).")


if __name__ == "__main__":
    run()
