"""Reliable local, monotonic Nôm↔Quốc ngữ reading anchors.

An anchor is a (Nôm character, Quốc ngữ token) pair tied together by at
least one shared reading (dictionary or human-reviewed book lexicon).
This module exists so segmentation, page mapping and evaluation can use
the same, conservative notion of evidence:

- **Local uniqueness is mandatory in both directions.** A Nôm character
  anchors only to a QN token when (a) exactly one token position matches
  one of its readings AND (b) no other Nôm position in the window matches
  that token. Repeated occurrences of the same reading and several Nôm
  characters competing for one token are *not* anchors.
- Anchors are monotone: crossed pairs are resolved to a longest
  increasing subsequence, so order is never violated and a token is used
  at most once.
- Ambiguity is exposed, not hidden: ``anchor_diagnostics`` reports how
  many candidates were dropped and why.

No readings are ever invented; everything comes from the lexicon and the
dictionary as load-bearing evidence.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from typing import Any, Sequence

from .clean import is_nom_char
from .dictionary.book_lexicon import strip_diacritics

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
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
    lexicon_readings = (
        list(lexicon.readings(char))
        if lexicon is not None and hasattr(lexicon, "readings")
        else []
    )
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


def _candidate_tables(
    readings_by_position: Sequence[Sequence[str]],
    token_forms: Sequence[str],
) -> tuple[list[frozenset[int]], list[set[int]]]:
    """(item → candidate token indices), (token → candidate item indices)."""
    cand: list[frozenset[int]] = []
    for readings in readings_by_position:
        forms = {normalize_reading(reading) for reading in readings if reading}
        if not forms:
            cand.append(frozenset())
            continue
        cands = {j for j, tf in enumerate(token_forms) if tf in forms}
        cand.append(frozenset(cands))
    token_cand: list[set[int]] = [set() for _ in token_forms]
    for i, cands in enumerate(cand):
        for j in cands:
            token_cand[j].add(i)
    return cand, token_cand


def anchor_diagnostics(
    readings_by_position: Sequence[Sequence[str]],
    tokens: Sequence[tuple[int, int, str]],
) -> dict[str, int]:
    """Expose ambiguity and dropped-anchor statistics."""
    token_forms = [normalize_reading(t[2]) for t in tokens]
    cand, token_cand = _candidate_tables(readings_by_position, token_forms)
    unique_items = sum(1 for cands in cand if len(cands) == 1)
    unique_pairs = 0
    for i, cands in enumerate(cand):
        if len(cands) == 1:
            j = next(iter(cands))
            if len(token_cand[j]) == 1:
                unique_pairs += 1
    anchors = find_reading_anchors(readings_by_position, tokens)
    return {
        "items_total": len(readings_by_position),
        "items_known": sum(1 for readings in readings_by_position if readings),
        "items_with_candidates": sum(1 for cands in cand if cands),
        "unique_item_positions": unique_items,
        "competing_token_positions": sum(1 for items in token_cand if len(items) > 1),
        "unique_unique_pairs": unique_pairs,
        "anchors": len(anchors),
        "dropped_ambiguous_items": sum(1 for cands in cand if len(cands) > 1),
        "dropped_competing_tokens": sum(
            1 for items in token_cand if len(items) > 1
        ),
    }


def find_reading_anchors(
    readings_by_position: Sequence[Sequence[str]],
    tokens: Sequence[tuple[int, int, str]],
) -> list[tuple[int, int]]:
    """Return monotone (nom_index, token_index) anchors.

    A pair is used only when the Nôm position has exactly one candidate
    QN token and the QN token has exactly one candidate Nôm position, and
    the pair survives a longest-increasing-subsequence filter so anchor
    order is monotone in both streams.
    """
    token_forms = [normalize_reading(t[2]) for t in tokens]
    cand, token_cand = _candidate_tables(readings_by_position, token_forms)
    pairs: list[tuple[int, int]] = []
    for i, cands in enumerate(cand):
        if len(cands) != 1:
            continue
        j = next(iter(cands))
        if len(token_cand[j]) != 1:
            continue
        pairs.append((i, j))
    if not pairs:
        return []
    # Longest strictly increasing subsequence over token indices (pairs are
    # ordered by Nôm position already and neither side repeats).
    tails: list[int] = []
    tail_positions: list[int] = []
    parent = [-1] * len(pairs)
    for pos, (_, j) in enumerate(pairs):
        idx = bisect_left(tails, j)
        if idx == len(tails):
            tails.append(j)
            tail_positions.append(pos)
        else:
            tails[idx] = j
            tail_positions[idx] = pos
        parent[pos] = tail_positions[idx - 1] if idx > 0 else -1
    chain: list[int] = []
    current = tail_positions[len(tails) - 1]
    while current != -1:
        chain.append(current)
        current = parent[current]
    chain.reverse()
    return [pairs[k] for k in chain]


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
