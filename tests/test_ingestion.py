"""Phase 1 tests: parsing + storage of the OSHA 1910.147 corpus.

Exit criteria (artifacts/system-arch-and-roadmap.md, Phase 1): every ingested
clause is independently queryable by its clause number. These tests exercise
exactly that, plus the structural correctness the parser has to get right for
citations to ever be trustworthy downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from safety_qa.ingestion.canonical import citation_key, parse_clause_ref, slugify
from safety_qa.ingestion.models import Standard
from safety_qa.ingestion.parser_osha_ecfr import parse_osha_section
from safety_qa.ingestion.store import connect, get_clause, list_clauses, replace_clauses, upsert_standard

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RAW_XML = _REPO_ROOT / "data" / "raw" / "osha_1910_147_raw.xml"


# ---------------------------------------------------------------------------
# canonical.py
# ---------------------------------------------------------------------------

def test_citation_key_roundtrip():
    key = citation_key("OSHA-1910.147", ["c", "4", "i"])
    assert key == "OSHA-1910.147#(c)(4)(i)"
    standard_id, segments = parse_clause_ref(key)
    assert standard_id == "OSHA-1910.147"
    assert segments == ["c", "4", "i"]


def test_citation_key_is_case_sensitive_between_depths():
    # (A) at depth 4 and (a) at depth 1 must never collide.
    assert citation_key("OSHA-1910.147", ["a"]) != citation_key("OSHA-1910.147", ["A"])


def test_slugify():
    assert slugify("Affected employee") == "affected-employee"
    assert slugify("Capable of being locked out") == "capable-of-being-locked-out"


# ---------------------------------------------------------------------------
# parser_osha_ecfr.py -- structural correctness
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def parsed():
    heading, clauses = parse_osha_section(str(_RAW_XML), "OSHA-1910.147")
    return heading, clauses


@pytest.fixture(scope="module")
def clause_by_key(parsed):
    _, clauses = parsed
    return {c.citation_key: c for c in clauses}


def test_heading_captured(parsed):
    heading, _ = parsed
    assert "control of hazardous energy" in heading.lower()


def test_no_duplicate_citation_keys(parsed):
    _, clauses = parsed
    keys = [c.citation_key for c in clauses]
    assert len(keys) == len(set(keys)), "every clause must be independently addressable"


def test_top_level_structure(clause_by_key):
    # (a) through (f), each present at depth 1.
    for letter in "abcdef":
        key = f"OSHA-1910.147#({letter})"
        assert key in clause_by_key, f"missing top-level clause {key}"
        assert clause_by_key[key].depth == 1


def test_deep_nesting_resolves_correctly(clause_by_key):
    # (c)(5)(ii)(A)(1) -- depth 5, the digit-class cycling back after alpha_upper.
    key = "OSHA-1910.147#(c)(5)(ii)(A)(1)"
    assert key in clause_by_key
    c = clause_by_key[key]
    assert c.depth == 5
    assert "withstanding the environment" in c.text


def test_sibling_after_nested_return_pops_correctly(clause_by_key):
    # (d)(4)(iii)(B) is depth 4; the very next clause, (d)(5), must pop back to
    # depth 2 rather than being mistaken for a child of (d)(4)(iii)(B).
    assert clause_by_key["OSHA-1910.147#(d)(4)(iii)(B)"].depth == 4
    assert clause_by_key["OSHA-1910.147#(d)(5)"].depth == 2


def test_lone_marker_opens_new_nested_list_without_a_title(clause_by_key):
    # (e)(3)'s body ends mid-sentence with no chained opener, yet (e)(3)(i)/(ii)/(iii)
    # still exist as depth-3 children -- introduced by lone markers alone.
    assert "OSHA-1910.147#(e)(3)(i)" in clause_by_key
    assert "OSHA-1910.147#(e)(3)(ii)" in clause_by_key
    assert "OSHA-1910.147#(e)(3)(iii)" in clause_by_key
    assert clause_by_key["OSHA-1910.147#(e)(3)(i)"].depth == 3


def test_title_containing_parentheses_does_not_break_the_chain(clause_by_key):
    # "(2) Outside personnel (contractors, etc.). (i) Whenever..." -- the title
    # itself has a parenthetical aside; the chain must still continue to (f)(2)(i).
    key = "OSHA-1910.147#(f)(2)"
    assert clause_by_key[key].section_title == "Outside personnel (contractors, etc.)"
    assert "OSHA-1910.147#(f)(2)(i)" in clause_by_key


def test_definitions_are_keyed_by_term_not_number(clause_by_key):
    key = "OSHA-1910.147#(b)/term:authorized-employee"
    assert key in clause_by_key
    c = clause_by_key[key]
    assert c.clause_type == "definition"
    assert c.is_normative is True
    assert "locks out or tags out" in c.text


def test_notes_are_non_normative(clause_by_key):
    notes = [c for c in clause_by_key.values() if c.clause_type == "note"]
    assert notes, "expected at least one Note clause"
    assert all(n.is_normative is False for n in notes)


def test_appendix_is_non_normative_and_separate(clause_by_key):
    key = "OSHA-1910.147#/appendix-a"
    assert key in clause_by_key
    appendix = clause_by_key[key]
    assert appendix.clause_type == "appendix"
    assert appendix.is_normative is False
    assert appendix.depth == 0


# ---------------------------------------------------------------------------
# store.py -- Phase 1 exit criteria: every clause independently queryable
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_conn(tmp_path, parsed):
    _, clauses = parsed
    conn = connect(str(tmp_path / "test_corpus.db"))
    upsert_standard(
        conn,
        Standard(
            id="OSHA-1910.147",
            name="The control of hazardous energy (lockout/tagout)",
            edition="29 CFR 1910.147 (test snapshot)",
            license_tier="public_domain",
            source_url="https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XVII/part-1910/subpart-J/section-1910.147",
        ),
    )
    replace_clauses(conn, "OSHA-1910.147", clauses)
    return conn


def test_every_clause_queryable_by_citation_key(db_conn, parsed):
    _, clauses = parsed
    for c in clauses:
        stored = get_clause(db_conn, c.citation_key)
        assert stored is not None, f"{c.citation_key} not queryable after ingestion"
        assert stored.text == c.text
        assert stored.clause_path == c.clause_path


def test_unknown_citation_returns_none(db_conn):
    assert get_clause(db_conn, "OSHA-1910.147#(z)(99)") is None


def test_list_clauses_preserves_document_order(db_conn):
    clauses = list_clauses(db_conn, "OSHA-1910.147")
    order_indices = [c.order_index for c in clauses]
    assert order_indices == sorted(order_indices)


def test_reingestion_is_idempotent_not_additive(db_conn, parsed):
    _, clauses = parsed
    replace_clauses(db_conn, "OSHA-1910.147", clauses)  # ingest a second time
    stored = list_clauses(db_conn, "OSHA-1910.147")
    assert len(stored) == len(clauses), "re-ingestion must replace, not accumulate"
