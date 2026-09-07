"""A compact Porter stemmer -- zero dependency (no nltk), pure Python.

Why this exists: exact-token lexical matching missed obvious morphological variants
during Phase 2 tuning against the golden eval set -- a query asking "how often must
it be periodically inspected" shares zero raw tokens with clause text that says
"periodic inspection" ("periodically" != "periodic", "inspected" != "inspection"),
even though they're clearly the same concept. BM25 and TF-IDF both need stemmed
tokens to catch this; the classic Porter (1980) algorithm is what practically every
lightweight IR system reaches for, and it's small enough to implement directly rather
than pull in a dependency for it.
"""

from __future__ import annotations

_VOWELS = "aeiou"


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """Porter's 'm': the number of consonant-vowel-consonant... sequences."""
    n = 0
    i = 0
    length = len(stem)
    while i < length and _is_consonant(stem, i):
        i += 1
    while i < length:
        while i < length and not _is_consonant(stem, i):
            i += 1
        if i >= length:
            break
        while i < length and _is_consonant(stem, i):
            i += 1
        n += 1
    return n


def _contains_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _ends_cvc(word: str) -> bool:
    if len(word) < 3:
        return False
    return (
        _is_consonant(word, len(word) - 3)
        and not _is_consonant(word, len(word) - 2)
        and _is_consonant(word, len(word) - 1)
        and word[-1] not in "wxy"
    )


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        if _measure(word[:-3]) > 0:
            return word[:-1]
        return word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _contains_vowel(stem):
                if stem.endswith(("at", "bl", "iz")):
                    return stem + "e"
                if _ends_double_consonant(stem) and stem[-1] not in "lsz":
                    return stem[:-1]
                if _measure(stem) == 1 and _ends_cvc(stem):
                    return stem + "e"
                return stem
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and _contains_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2_SUFFIXES = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
)


def _step2(word: str) -> str:
    for suffix, replacement in _STEP2_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                return stem + replacement
            return word
    return word


_STEP3_SUFFIXES = (
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
)


def _step3(word: str) -> str:
    for suffix, replacement in _STEP3_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                return stem + replacement
            return word
    return word


_STEP4_SUFFIXES = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
    "ent", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
)


def _step4(word: str) -> str:
    for suffix in _STEP4_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if suffix == "ion" and not (stem.endswith("s") or stem.endswith("t")):
                continue
            if _measure(stem) > 1:
                return stem
            return word
    if word.endswith("ion"):
        stem = word[:-3]
        if stem.endswith(("s", "t")) and _measure(stem) > 1:
            return stem
    return word


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            word = stem
    if word.endswith("ll") and _measure(word[:-1]) > 1:
        word = word[:-1]
    return word


def stem(word: str) -> str:
    """Reduce `word` to its Porter stem, e.g. 'periodically' -> 'period',
    'inspection'/'inspected' -> 'inspect', 'withstanding' -> 'withstand'."""
    word = word.lower()
    if len(word) <= 2:
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _step2(word)
    word = _step3(word)
    word = _step4(word)
    word = _step5(word)
    return word
