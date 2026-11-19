"""QN OCR quality against the Nôm partner page, without QN ground truth.

Doc/FIX_PLAN_v24.md T2.2 / T2.4. ``phonetic recall`` = LCS(Nôm chars, QN
syllables) / Nôm chars, where a Nôm char matches a syllable iff the syllable
is one of its dictionary readings (char ∪ word tables of the readings cache),
compared tone-sensitively but independent of tone-mark placement (hoà = hòa).
Ceiling ≈ 0.92-0.97 on these books (Nôm OCR + dictionary gaps). It cannot see
QN errors that are still a valid reading, nor punctuation: it ranks pages for
proofreading, it does not replace it.

The same measure with the Nôm boxes in reversed order detects pages scanned
upside-down (RC10): the API reads the characters but returns the columns in
reverse reading order.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable, Mapping, Sequence

_TONES = frozenset("̣̀́̃̉")
_SYLLABLE_RE = re.compile(r"[^\W\d_]+")
_NOM_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f-〓]")


def syllable_key(s: str) -> str:
    d = unicodedata.normalize("NFD", s.lower())
    tone = "".join(c for c in d if c in _TONES)
    base = unicodedata.normalize("NFC", "".join(c for c in d if c not in _TONES))
    return base + "|" + tone


def reading_keys(readings) -> dict[str, frozenset[str]]:
    """{char: keys} from a hannom.dictionary.readings.Readings (char ∪ word)."""
    out: dict[str, set[str]] = {}
    for table in (readings.char, readings.word):
        for ch, vals in table.items():
            out.setdefault(ch, set()).update(syllable_key(v) for v in vals)
    return {k: frozenset(v) for k, v in out.items()}


def nom_chars(text: str) -> list[str]:
    return _NOM_RE.findall(text or "")


def qn_syllables(text: str) -> list[str]:
    return _SYLLABLE_RE.findall(unicodedata.normalize("NFC", text or ""))


def lcs_matches(nom: Sequence[str], syllables: Sequence[str], keys: Mapping[str, frozenset[str]]) -> int:
    """Bit-parallel LCS length (Hyyrö) with match = syllable is a reading of the char."""
    m = len(syllables)
    if not m or not nom:
        return 0
    pos: dict[str, int] = {}
    for j, s in enumerate(syllables):
        k = syllable_key(s)
        pos[k] = pos.get(k, 0) | (1 << j)
    full = (1 << m) - 1
    v = full
    for c in nom:
        match = 0
        for k in keys.get(c, ()):
            match |= pos.get(k, 0)
        u = v & match
        v = ((v + u) | (v - u)) & full
    return m - bin(v).count("1")


def page_quality(qn_text: str, nom: Sequence[str], keys: Mapping[str, frozenset[str]]) -> dict:
    syl = qn_syllables(qn_text)
    low = [s.lower() for s in syl]
    grams = Counter(tuple(low[i : i + 8]) for i in range(len(low) - 7))
    matched = lcs_matches(nom, syl, keys)
    n = len(nom)
    return {
        "nom_chars": n,
        "qn_syllables": len(syl),
        "coverage": round(len(syl) / n, 3) if n else None,
        "recall": round(matched / n, 3) if n else None,
        "precision": round(matched / len(syl), 3) if syl else None,
        "rep8": max(grams.values()) if grams else 0,
    }


def reversed_order_gain(qn_text: str, nom_boxes: Sequence[str], keys: Mapping[str, frozenset[str]]) -> tuple[float, float]:
    """(recall in the given box order, recall with the box order reversed)."""
    syl = qn_syllables(qn_text)
    fwd = nom_chars("".join(nom_boxes))
    rev = nom_chars("".join(reversed(list(nom_boxes))))
    n = len(fwd) or 1
    return lcs_matches(fwd, syl, keys) / n, lcs_matches(rev, syl, keys) / n


def boxes_from_clean(lines: Sequence[str], sources: Sequence[int] | None) -> list[str]:
    """Group cleaned Nôm lines back into boxes (clean JSON ``lines`` + ``line_sources``)."""
    if not sources or len(sources) != len(lines):
        return list(lines)
    out: list[str] = []
    last = None
    for text, src in zip(lines, sources):
        if src == last:
            out[-1] += text
        else:
            out.append(text)
            last = src
    return out


def classify(q: Mapping, reversed_pair: tuple[float, float] | None = None) -> str:
    """Queue for one pair (T2.2)."""
    if reversed_pair and reversed_pair[1] > reversed_pair[0] + 0.2:
        return "nom_reversed"
    r = q.get("recall")
    if r is None:
        return "no_nom"
    if r < 0.6:
        return "manual_qn"
    cov = q.get("coverage") or 0
    if r < 0.8 or q.get("rep8", 0) >= 4 or not (0.85 <= cov <= 1.2):
        return "priority_review"
    return "review"


def summarize(rows: Iterable[Mapping]) -> dict:
    rows = list(rows)
    n = sum(r["nom_chars"] for r in rows if r.get("recall") is not None)
    w = sum(r["recall"] * r["nom_chars"] for r in rows if r.get("recall") is not None)
    return {
        "pairs": len(rows),
        "weighted_recall": round(w / n, 4) if n else None,
        "queues": dict(Counter(r["queue"] for r in rows)),
    }
