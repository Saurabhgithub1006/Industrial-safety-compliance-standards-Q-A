"""Clause-aware parser for eCFR-style OSHA regulation XML (e.g. 29 CFR 1910.147).
Rebuilds the clause tree from flat, unnested markup: "(a)", "(1)", "(i)" markers
appear as plain text inside one <P> tag, not as nested XML elements.
Design decisions and the bugs found fixing this are logged in
artifacts/changelogs.md CHG-20260907-01.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .canonical import citation_key, slugify, synthetic_citation_key
from .models import Clause

_MARKER_RE = re.compile(r"^\s*\(([A-Za-z0-9]{1,4})\)\s*")
# Title span may contain a parenthetical aside, e.g. "(contractors, etc.)".
# Nested parens allowed as long as their content isn't a bare short token.
_TITLE_RE = re.compile(r"^((?:[^()]|\([^()]*[\s,.;][^()]*\)){1,80}?[.—:])\s*")
_CROSSREF_GUARD_WORDS = ("paragraph", "section", "subpart", "part")

# depth 1 is alpha_lower, depths 2+ cycle digit -> roman_lower -> alpha_upper.
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
    """True if token is the first value of its class: 'a', '1', 'i', 'A'."""
    return token == {"alpha_lower": "a", "alpha_upper": "A", "digit": "1", "roman_lower": "i"}[cls]


def _is_successor(prev_token: str, token: str, cls: str) -> bool:
    """True if token is exactly the next value after prev_token."""
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
    """Which numbering classes could this token belong to (can be ambiguous)."""
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
    """Split leading '(marker)[title]...' openers off text. Returns (chain, body)."""
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
    """Tracks the open clause path. Resolves each lone marker as either a
    sibling (successor of the current value) or a new nested level (first
    value of its class) -- see resolve()."""

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

        # 1. Sibling: deepest level whose class matches and is a successor.
        for i in range(len(self._levels) - 1, -1, -1):
            lvl = self._levels[i]
            if lvl.cls in classes and _is_successor(lvl.token, token, lvl.cls):
                return self._push(token, i + 1, lvl.cls)

        # 2. New nested list: first value of the class one level deeper.
        next_depth = len(self._levels) + 1
        expected_cls = _expected_class(next_depth)
        if expected_cls in classes and _is_first_value(token, expected_cls):
            return self._push(token, next_depth, expected_cls)

        # 3. Fallback: loose class match, ignoring value succession.
        for i in range(len(self._levels) - 1, -1, -1):
            if self._levels[i].cls in classes:
                return self._push(token, i + 1, self._levels[i].cls)

        raise ValueError(
            f"marker {token!r} (classes={classes}) doesn't fit any open level "
            f"{[(l.token, l.cls) for l in self._levels]}"
        )

    def push_child(self, token: str) -> _StackLevel:
        """Push token as a child. Used for markers after the first in a chain,
        where nesting is already structurally forced, so it skips resolve()'s
        ambiguous sibling matching."""
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
    """All text content of elem, ignoring tag structure like <I> italics."""
    return "".join(elem.itertext())


def parse_osha_section(xml_path: str, standard_id: str) -> tuple[str, list[Clause]]:
    """Parse one eCFR <DIV8> section into (section_heading, clauses).
    Raises ValueError on an unresolvable marker rather than skipping it."""
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
                # No marker, not a definition: append to the current clause.
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

        # CITA (amendment history) and anything else: not a clause, skipped.

    return section_heading, clauses


def _emit_definition(
    clauses: list[Clause],
    standard_id: str,
    stack: _ClauseStack,
    raw_text: str,
    order_index: int,
) -> None:
    """One 'Term. Body.' entry in a Definitions block, cited by term not number."""
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
