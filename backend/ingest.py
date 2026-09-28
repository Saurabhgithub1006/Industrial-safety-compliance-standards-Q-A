"""Load the OSHA 1910.147 corpus into whatever database DATABASE_URL points at.
Reuses safety_qa.ingestion.parser_osha_ecfr unchanged -- same parser, same source
XML, same clause tree as the SQLite-backed CLI tool; only the storage target
differs. Idempotent (safe to run on every deploy): replace_clauses() fully
replaces the standard's clauses rather than accumulating duplicates.

    PYTHONPATH=src python -m backend.ingest
"""

from __future__ import annotations

from pathlib import Path

from safety_qa.ingestion.models import Standard
from safety_qa.ingestion.parser_osha_ecfr import parse_osha_section

from .corpus_store import replace_clauses, upsert_standard
from .db import init_schema, make_engine

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RAW_XML = _REPO_ROOT / "data" / "raw" / "osha_1910_147_raw.xml"
_STANDARD_ID = "OSHA-1910.147"
_SOURCE_URL = "https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XVII/part-1910/subpart-J/section-1910.147"


def run() -> None:
    engine = make_engine()
    init_schema(engine)

    heading, clauses = parse_osha_section(str(_RAW_XML), _STANDARD_ID)
    standard = Standard(
        id=_STANDARD_ID, name=heading, edition="29 CFR 1910.147 (eCFR snapshot)",
        license_tier="public_domain", source_url=_SOURCE_URL,
    )
    upsert_standard(engine, standard)
    replace_clauses(engine, _STANDARD_ID, clauses)
    print(f"[{_STANDARD_ID}] ingested {len(clauses)} clauses into {engine.url}")


if __name__ == "__main__":
    run()
