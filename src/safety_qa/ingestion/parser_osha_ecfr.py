"""Clause-aware parser for eCFR-style OSHA regulation XML (e.g. 29 CFR 1910.147).

Why this is nontrivial: the source markup does NOT nest clauses as XML elements.
A whole opening chain like "(a) <I>Scope...</I>-(1) <I>Scope.</I> (i) This standard
covers..." lives in a single flat <P> tag; the hierarchy is encoded only as literal
text markers ("(a)", "(1)", "(i)", "(A)", ...) that repeat the same four pattern
classes at every 4th level of nesting. Inline cross-references ("see paragraph (c)(1)
of this section") use the identical bracket syntax and must NOT be mistaken for
structural markers. This module reconstructs the true clause tree from that flat text.

Two building blocks:
  1. `_split_leading_chain` -- pulls the leading run of structural "(marker)[title]"
     openers off the front of one <P>'s text, stopping at the first marker whose
     immediately-following text is NOT itself another marker (that marker's remainder
     is body text, not a title -- and everything after it is body, full stop, so an
     inline reference buried in body prose is never reached by this scan).
  2. `_ClauseStack` -- resolves each opener against the CFR numbering cycle
     (alpha-lower -> digit -> roman-lower -> alpha-upper -> repeat) to decide whether
     it's a new child of the current clause or a sibling that supersedes one or more
     open levels.

Scoping decisions made here (see artifacts/system-arch-and-roadmap.md Sec 1 and the
architect-review notes on this doc):
  - The (b) "Definitions" block is prose, not marker-numbered, in the source -- each
    defined term becomes its own clause with a synthetic citation key
    (`.../definitions/term:<slug>`), since standards get cited by defined term ("the
    OSHA definition of 'authorized employee'") not by a number that doesn't exist.
  - <NOTE> blocks are ingested as separate `is_normative=False` clauses attached to
    the clause they annotate -- a note is explanatory, never itself a citable
    requirement, and must never be presented to a user as one.
  - The non-mandatory Appendix A is stored as a single `is_normative=False` blob
    rather than fully sub-parsed -- it's explicitly non-mandatory guidance, not
    "safety requirements" text, which is this project's actual scope.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .canonical import citation_key, slugify, synthetic_citation_key
from .models import Clause

_MARKER_RE = re.compile(r"^\s*\(([A-Za-z0-9]{1,4})\)\s*")
# A title span may itself contain a parenthetical aside, e.g. "Outside personnel
# (contractors, etc.)." -- allow nested parens as long as their content isn't a bare
# short alnum token (which would make it look like a real structural marker).
_TITLE_RE = re.compile(r"^((?:[^()]|\([^()]*[\s,.;][^()]*\)){1,80}?[.—:])\s*")
_CROSSREF_GUARD_WORDS = ("paragraph", "section", "subpart", "part")

# CFR's nesting convention: depth 1 is always alpha_lower ((a),(b),(c)...) and never
# repeats; depths 2+ cycle through digit -> roman_lower -> alpha_upper and then repeat
# that 3-cycle for arbitrarily deep nesting -- e.g. (c)(5)(ii)(A)(1)(i)(A) is depths
# 1..7. (Not a 4-class cycle that revisits alpha_lower -- that letter is reserved for
# the top level only.)
_DEEP_CYCLE = ["digit", "roman_lower", "alpha_upper"]


def _expected_class(depth: int) -> str:
    if depth == 1:
        return "alpha_lower"
    return _DEEP_CYCLE[(depth - 2) % len(_DEEP_CYCLE)]


_ROMAN_RE = re.compile(r"^(m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3}))$")
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(token: str) -> int:
    total, prev = 0, 0
    for ch in reversed(token.lower()):
        v = _ROMAN_VALUES[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def _is_first_value(token: str, cls: str) -> bool:
    """Does `token` open a class's sequence from scratch? A brand-new nested list
    always starts here -- 'a', '1', 'i', 'A' -- never mid-sequence."""
    return token == {"alpha_lower": "a", "alpha_upper": "A", "digit": "1", "roman_lower": "i"}[cls]


def _is_successor(prev_token: str, token: str, cls: str) -> bool:
    """Is `token` exactly the next value after `prev_token` in `cls`'s sequence?
    This is what actually distinguishes 'continue this list' from 'open a nested
    one' -- punctuation (a trailing '.' vs ':') turns out not to be a reliable
    signal in real CFR text, but strict value succession always is."""
    try:
        if cls in ("alpha_lower", "alpha_upper"):
            return len(prev_token) == 1 and len(token) == 1 and ord(token) - ord(prev_token) == 1
        if cls == "digit":
            return int(token) - int(prev_token) == 1
        if cls == "roman_lower":
            return _roman_to_int(token) - _roman_to_int(prev_token) == 1
    except (ValueError, KeyError):
        return False
    return False


def _possible_classes(token: str) -> set[str]:
    """Which numbering-cycle classes could this literal token belong to? Several
    tokens are genuinely ambiguous out of context (e.g. 'i' is both a valid single
    letter and a valid roman numeral) -- resolution happens against the live stack,
    not here."""
    classes: set[str] = set()
    if len(token) == 1 and token.isalpha():
        classes.add("alpha_lower" if token.islower() else "alpha_upper")
    if token.isdigit():
        classes.add("digit")
    lowered = token.lower()
    if lowered and all(c in "ivxlcdm" for c in lowered) and _ROMAN_RE.match(lowered):
        if token.islower():
            classes.add("roman_lower")
    return classes


def _split_leading_chain(text: str) -> tuple[list[tuple[str, str | None]], str]:
    """Consume the leading '(marker)[title]/(marker)[title].../body' run from the
    start of `text`. Returns (chain, body) where chain is an ordered list of
    (marker_token, title_or_None) and body is the remaining, un-consumed text
    (the payload of the last marker in the chain)."""
    chain: list[tuple[str, str | None]] = []
    remaining = text
    while True:
        m = _MARKER_RE.match(remaining)
        if not m:
            break
        token = m.group(1)
        after_marker = remaining[m.end():]
        title: str | None = None
        tmatch = _TITLE_RE.match(after_marker)
        if tmatch:
            candidate = tmatch.group(1).rstrip(" .—:")
            after_title = after_marker[tmatch.end():]
            looks_like_crossref = any(w in candidate.lower() for w in _CROSSREF_GUARD_WORDS)
            if not looks_like_crossref and _MARKER_RE.match(after_title):
                title = candidate
                after_marker = after_title
        chain.append((token, title))
        remaining = after_marker
        if title is None:
            break
    return chain, remaining


@dataclass
class _StackLevel:
    depth: int
    token: str
    cls: str
    citation_key: str
    segments: tuple[str, ...]


class _ClauseStack:
    """Tracks the currently-open clause path and resolves each new *lone* marker
    (the first token of a fresh <P>, per `resolve()`) against it.

    The key realization this encodes: a lone marker can mean two very different
    things, and pattern class alone can't tell them apart --
      - most of the time, it's a sibling: continuing the current list, or returning
        to a shallower one after a nested list ends ((d)(4)(iii)(B) -> (d)(5));
      - occasionally, it opens a brand-new nested list with no title of its own
        ((e)(3) -> (i), a lone marker one level deeper than anything currently open).
    Trailing punctuation in the source ('.' vs ':') turns out NOT to reliably mark
    which case applies -- real CFR text uses a period before a sub-list just as
    often as a colon. What's actually reliable is the token's *value*: a sibling is
    always the literal successor of the level it continues ('iii' -> 'iv', '4' ->
    '5'); a new nested list always starts at its class's first value ('i', 'A',
    '1'). So successor-match is tried first (deepest matching level down to
    shallowest), then first-of-a-new-class, and only a loose class-only match as a
    last resort.
    """

    def __init__(self, standard_id: str):
        self.standard_id = standard_id
        self._levels: list[_StackLevel] = []

    def top_citation_key(self) -> str | None:
        return self._levels[-1].citation_key if self._levels else None

    def top_segments(self) -> list[str]:
        return list(self._levels[-1].segments) if self._levels else []

    def depth(self) -> int:
        return len(self._levels)

    def _push(self, token: str, depth: int, cls: str) -> _StackLevel:
        new_segments = tuple(self.top_segments()[: depth - 1] + [token])
        level = _StackLevel(
            depth=depth,
            token=token,
            cls=cls,
            citation_key=citation_key(self.standard_id, list(new_segments)),
            segments=new_segments,
        )
        del self._levels[depth - 1:]
        self._levels.append(level)
        return level

    def resolve(self, token: str) -> _StackLevel:
        """Resolve a lone marker (first/only token of a fresh <P>) to its place in
        the tree, mutating the stack, and return the resulting level."""
        classes = _possible_classes(token)
        if not classes:
            raise ValueError(f"unrecognized clause marker token: {token!r}")

        if not self._levels:
            # Bootstrap: the very first clause marker in the whole document.
            expected = _expected_class(1)
            if expected not in classes or not _is_first_value(token, expected):
                raise ValueError(f"first clause marker {token!r} isn't a valid depth-1 label")
            return self._push(token, 1, expected)

        # 1. Sibling continuation: deepest existing level whose class matches AND
        #    whose current token this is the literal successor of.
        for i in range(len(self._levels) - 1, -1, -1):
            lvl = self._levels[i]
            if lvl.cls in classes and _is_successor(lvl.token, token, lvl.cls):
                return self._push(token, i + 1, lvl.cls)

        # 2. New nested list: token is the first value of the class expected one
        #    level deeper than whatever's currently open.
        next_depth = len(self._levels) + 1
        expected_cls = _expected_class(next_depth)
        if expected_cls in classes and _is_first_value(token, expected_cls):
            return self._push(token, next_depth, expected_cls)

        # 3. Last resort: loose class match, ignoring value succession (covers any
        #    numbering irregularity in the source rather than failing outright).
        for i in range(len(self._levels) - 1, -1, -1):
            if self._levels[i].cls in classes:
                return self._push(token, i + 1, self._levels[i].cls)

        raise ValueError(
            f"marker {token!r} (classes={classes}) doesn't fit any open level "
            f"{[(l.token, l.cls) for l in self._levels]}"
        )

    def push_child(self, token: str) -> _StackLevel:
        """Unconditionally push `token` as a new child of the current deepest level.

        Used for every marker AFTER the first in a within-<P> opening chain -- its
        parent relationship is already structurally forced by `_split_leading_chain`
        (a title immediately followed by another marker means "nested", full stop),
        so it must never fall through to the ambiguous sibling-matching in
        `resolve()`. Without this split, a token like 'i' -- valid as both a fresh
        top-level letter *and* a roman numeral -- gets wrongly matched against a
        stale top-level sibling instead of deepening.
        """
        classes = _possible_classes(token)
        next_depth = len(self._levels) + 1
        expected_cls = _expected_class(next_depth)
        if expected_cls not in classes:
            raise ValueError(
                f"chained marker {token!r} (classes={classes}) doesn't match the "
                f"expected class {expected_cls!r} at depth {next_depth}"
            )
        return self._push(token, next_depth, expected_cls)


def _flatten(elem: ET.Element) -> str:
    """All text content of `elem`, ignoring tag structure (italics, emphasis, etc.)
    -- markers split across a plain '(' + italic digit + plain ')' (an eCFR quirk for
    deeply-nested items) still reconstruct correctly since itertext() preserves
    character order regardless of which run each character sits in."""
    return "".join(elem.itertext())


def parse_osha_section(xml_path: str, standard_id: str) -> tuple[str, list[Clause]]:
    """Parse one eCFR <DIV8 TYPE="SECTION"> section into (section_heading, clauses).

    Returns clauses in ingestion order, each independently queryable by its
    `citation_key`. Raises ValueError (rather than silently dropping content) if a
    marker can't be resolved -- for a compliance corpus, failing loud on an unparsed
    clause is the correct behavior; silently skipping one is not.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    if root.tag != "DIV8":
        raise ValueError(f"expected a DIV8 section root, got <{root.tag}>")

    head_elem = root.find("HEAD")
    section_heading = _flatten(head_elem).strip() if head_elem is not None else ""

    clauses: list[Clause] = []
    stack = _ClauseStack(standard_id)
    order = 0
    definitions_mode = False
    note_counters: dict[str, int] = {}

    def next_order() -> int:
        nonlocal order
        order += 1
        return order

    for child in root:
        if child.tag == "HEAD":
            continue

        if child.tag == "P":
            raw_text = _flatten(child).strip()
            if not raw_text:
                continue
            chain, body = _split_leading_chain(raw_text)

            if not chain:
                if definitions_mode and stack.depth() == 1:
                    _emit_definition(clauses, standard_id, stack, raw_text, next_order())
                    continue
                # Fallback: no marker, not a definitions entry -- append as a
                # continuation of the current deepest clause rather than drop it.
                if clauses:
                    last = clauses[-1]
                    merged_text = (last.text + " " + raw_text).strip()
                    clauses[-1] = Clause(
                        standard_id=last.standard_id,
                        citation_key=last.citation_key,
                        clause_path=last.clause_path,
                        parent_citation_key=last.parent_citation_key,
                        depth=last.depth,
                        section_title=last.section_title,
                        text=merged_text,
                        clause_type=last.clause_type,
                        is_normative=last.is_normative,
                        order_index=last.order_index,
                    )
                continue

            level = None
            for idx, (token, title) in enumerate(chain):
                parent_key = stack.top_citation_key()
                level = stack.resolve(token) if idx == 0 else stack.push_child(token)
                is_leaf = idx == len(chain) - 1
                text = body if is_leaf else (title or "")
                clauses.append(
                    Clause(
                        standard_id=standard_id,
                        citation_key=level.citation_key,
                        clause_path="".join(f"({s})" for s in level.segments),
                        parent_citation_key=parent_key,
                        depth=level.depth,
                        section_title=title,
                        text=text.strip(),
                        clause_type="requirement",
                        is_normative=True,
                        order_index=next_order(),
                    )
                )

            if level is not None and level.depth == 1:
                definitions_mode = clauses[-1].text.lower().startswith("definitions")

        elif child.tag == "NOTE":
            note_text = " ".join(
                _flatten(p).strip() for p in child.findall("P") if _flatten(p).strip()
            )
            if not note_text:
                continue
            parent_key = stack.top_citation_key() or ""
            note_counters[parent_key] = note_counters.get(parent_key, 0) + 1
            suffix = "note" if note_counters[parent_key] == 1 else f"note-{note_counters[parent_key]}"
            clauses.append(
                Clause(
                    standard_id=standard_id,
                    citation_key=synthetic_citation_key(standard_id, stack.top_segments(), suffix),
                    clause_path="".join(f"({s})" for s in stack.top_segments()) + f" [{suffix}]",
                    parent_citation_key=parent_key or None,
                    depth=stack.depth(),
                    section_title="Note",
                    text=note_text,
                    clause_type="note",
                    is_normative=False,
                    order_index=next_order(),
                )
            )

        elif child.tag == "EXTRACT":
            hd1 = child.find("HD1")
            title = _flatten(hd1).strip() if hd1 is not None else "Appendix"
            appendix_text = _flatten(child).strip()
            clauses.append(
                Clause(
                    standard_id=standard_id,
                    citation_key=synthetic_citation_key(standard_id, [], "appendix-a"),
                    clause_path="Appendix A",
                    parent_citation_key=None,
                    depth=0,
                    section_title=title,
                    text=appendix_text,
                    clause_type="appendix",
                    is_normative=False,
                    order_index=next_order(),
                )
            )

        # CITA (amendment history) and anything else: not safety-requirement
        # content, deliberately not ingested as a clause.

    return section_heading, clauses


def _emit_definition(
    clauses: list[Clause],
    standard_id: str,
    stack: _ClauseStack,
    raw_text: str,
    order_index: int,
) -> None:
    """One entry in a prose-style '(b) Definitions' block: 'Term. Definition body.'
    with no clause marker of its own. Cited by defined term, not by number."""
    m = re.match(r"^([^.]{1,80})\.\s*(.*)$", raw_text, re.DOTALL)
    term = m.group(1).strip() if m else raw_text
    body = m.group(2).strip() if m else ""
    parent_key = stack.top_citation_key()
    slug = f"term:{slugify(term)}"
    clauses.append(
        Clause(
            standard_id=standard_id,
            citation_key=synthetic_citation_key(standard_id, stack.top_segments(), slug),
            clause_path="".join(f"({s})" for s in stack.top_segments()) + f" [{term}]",
            parent_citation_key=parent_key,
            depth=stack.depth() + 1,
            section_title=term,
            text=body,
            clause_type="definition",
            is_normative=True,
            order_index=order_index,
        )
    )
