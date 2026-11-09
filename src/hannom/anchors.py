"""Reliable local, monotonic Nôm↔Quốc ngữ reading anchors.

An anchor is a (Nôm character, Quốc ngữ token) pair tied together by at
least one shared reading (dictionary or human-reviewed book lexicon).
This module exists so segmentation, page mapping and evaluation can use
the same, conservative notion of evidence:

- Assignment is a monotone Needleman-Wunsch optimum over exact reading
  matches. Each QN token anchors at most one Nôm character, so a popular
  token such as ``thì`` can never pin two characters.
- Characters with too many candidate tokens are dropped as ambiguous
  (``MAX_CANDIDATES_PER_CHAR``) and can never anchor.
- Interpolation/migration across a stream is local: callers work on
  small windows, so assignment quality is global only within the window.

No readings are ever invented; everything comes from the lexicon and the
dictionary as load-bearing evidence.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Sequence

from .clean import is_nom_char
from .dictionary.book_lexicon import strip_diacritics

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
MAX_CANDIDATES_PER_CHAR = 3
MAX_ANCHOR_GAP_TOKENS = 120


def normalize_reading(reading: str) -> str:
    return unicodedata.normalize("NFC", reading.strip()).casefold()


def token_items(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in QN_TOKEN_RE.finditer(text)]


def fold(text: str) -> str:
    return strip_diacritics(unicodedata.normalize("NFC", text.casefold()))


def gather_readings(
    char: str,
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
) -> tuple[list[str], str]:
    """Return (readings, source) for one Nôm character.

    ``source`` is ``"lexicon+dictionary"``, ``"lexicon"``, ``"dictionary"``
    or ``"none"``. Readings are NFC/casefold-normalised and de-duplicated.
    """
    lexicon_readings = list(lexicon.readings(char)) if lexicon is not None and hasattr(lexicon, "readings") else []
    dictionary_readings: list[str] = []
    if dictionary is not None and hasattr(dictionary, "lookup"):
        try:
            result = dictionary.lookup(char)
            dictionary_readings = [str(r) for r in getattr(result, "readings", []) or []]
        except Exception:
            dictionary_readings = []
    merged: list[str] = []
    for reading in lexicon_readings + dictionary_readings:
        normalized = normalize_reading(reading)
        if normalized and normalized not in merged:
            merged.append(normalized)
    if lexicon_readings and dictionary_readings:
        source = "lexicon+dictionary"
    elif lexicon_readings:
        source = "lexicon"
    elif dictionary_readings:
        source = "dictionary"
    else:
        source = "none"
    return merged, source


def _nw_anchors(
    readings_by_position: Sequence[Sequence[str]],
    token_forms: Sequence[str],
    *,
    gap_penalty: float = 0.2,
    mismatch_penalty: float = 0.5,
    match_score: float = 1.0,
) -> list[tuple[int, int]]:
    """Monotone optimum over exact reading matches (Needleman-Wunsch)."""
    normalized_items: list[frozenset[str]] = []
    for readings in readings_by_position:
        forms = {normalize_reading(reading) for reading in readings if reading}
        if forms:
            candidates = sum(1 for tf in token_forms if tf in forms)
            if candidates > MAX_CANDIDATES_PER_CHAR:
                forms = set()  # ambiguous character: do not anchor on it
        normalized_items.append(frozenset(forms))

    n, m = len(normalized_items), len(token_forms)
    if n == 0 or m == 0:
        return []
    NEG = -1e9
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] - gap_penalty
        back[i][0] = "up"
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] - gap_penalty
        back[0][j] = "left"
    for i in range(1, n + 1):
        forms = normalized_items[i - 1]
        row, prev_row = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            if not forms:
                score = 0.0
            elif token_forms[j - 1] in forms:
                score = match_score
            else:
                score = -mismatch_penalty
            diag = prev_row[j - 1] + score
            up = prev_row[j] - gap_penalty
            left = row[j - 1] - gap_penalty
            best = max(diag, up, left)
            row[j] = best
            if best == diag:
                back[i][j] = "diag"
            elif best == up:
                back[i][j] = "up"
            else:
                back[i][j] = "left"
    anchors: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step == "diag":
            forms = normalized_items[i - 1]
            if forms and token_forms[j - 1] in forms:
                anchors.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif step == "up":
            i -= 1
        else:
            j -= 1
    anchors.reverse()
    return anchors


def find_reading_anchors(
    readings_by_position: Sequence[Sequence[str]],
    tokens: Sequence[tuple[int, int, str]],
) -> list[tuple[int, int]]:
    """Return monotone (nom_index, token_index) anchors.

    O(n*m) global optimum over exact matches; for stream-scale callers,
    pass a small window of items/tokens instead of the whole book.
    """
    return _nw_anchors(readings_by_position, [normalize_reading(t[2]) for t in tokens])


def anchor_coverage(
    readings_by_position: Sequence[Sequence[str]],
    tokens: Sequence[tuple[int, int, str]],
) -> float:
    """Fraction of reading-carrying Nôm characters with a reliable anchor."""
    known = sum(1 for readings in readings_by_position if readings)
    if known == 0:
        return 0.0
    anchors = find_reading_anchors(readings_by_position, tokens)
    return len(anchors) / known
