"""Content-based image_map repair for T1 books.

``t1_map.align_page_groups`` pairs pages by ink density only; it never
looks at text. This module re-pairs the reading-order sequences by
maximising the number of Nôm characters whose readings appear in the
paired Quốc ngữ page's token set, using a monotone dynamic program over
group shapes (1-1, 1-2, 2-1) with optional skips for pages that have no
counterpart (e.g. translator apparatus with no Nôm source).

Outputs a proposal ``image_map`` plus per-pair recall evidence so a human
can triage every changed pair before it is applied. The repaired map is
written only by ``tools/repair_image_map.py --apply``; the heuristic
map is archived by the caller.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .charalign import fold
from .clean import count_nom_chars
from .dictionary.readings import load_readings, norm_reading

QN_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def qn_token_sets(text: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return (exact token set, fold token set) for a QN page."""
    norms = {norm_reading(t) for t in QN_TOKEN_RE.findall(text)}
    folds = {fold(t) for t in QN_TOKEN_RE.findall(text)}
    return frozenset(norms), frozenset(folds)


def _is_ideograph_char(ch: str) -> bool:
    if ch == "〓":
        return True
    code = ord(ch)
    if 0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0x10FFFD:
        return True  # PUA (Kim Hán Nôm private-use glyphs)
    return any(
        lo <= code <= hi
        for lo, hi in (
            (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
            (0x20000, 0x2A6DF), (0x2A700, 0x2B73F), (0x2B740, 0x2B81F),
            (0x2B820, 0x2CEAF), (0x2CEB0, 0x2EBEF), (0x2EBF0, 0x2EE5F),
            (0x30000, 0x3134F),
        )
    )


def ideographs(text: str) -> list[str]:
    return [ch for ch in text if _is_ideograph_char(ch)]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def pair_score(
    ch_chars: Sequence[str],
    vi_sets: tuple[frozenset[str], frozenset[str]],
    readings: Any,
    *,
    exact_weight: float = 1.0,
    fold_weight: float = 0.6,
) -> float:
    """Total weighted reading matches of the Nôm chars against the QN token set."""
    exact_set, fold_set = vi_sets
    total = 0.0
    for ch in ch_chars:
        rs = readings.of(ch)
        if not rs:
            continue
        if any(norm_reading(r) in exact_set for r in rs):
            total += exact_weight
            continue
        if any(fold(r) in fold_set for r in rs):
            total += fold_weight
    return total


def match_recall(ch_chars: Sequence[str], vi_sets: tuple[frozenset[str], frozenset[str]], readings: Any) -> float:
    if not ch_chars:
        return 0.0
    exact_set, fold_set = vi_sets
    hits = 0
    for ch in ch_chars:
        rs = readings.of(ch)
        if not rs:
            continue
        if any(norm_reading(r) in exact_set or fold(r) in fold_set for r in rs):
            hits += 1
    return hits / len(ch_chars)


# ---------------------------------------------------------------------------
# DP
# ---------------------------------------------------------------------------


@dataclass
class MapRepairResult:
    pairs: list[dict[str, Any]]
    skipped_ch: list[str]
    skipped_vi: list[str]
    per_pair: list[dict[str, Any]] = field(default_factory=list)
    anchor_issues: list[str] = field(default_factory=list)


def _solve_segment(
    i0: int,
    i1: int,
    j0: int,
    j1: int,
    ch_pages: Sequence[str],
    ch_chars: Sequence[Sequence[str]],
    vi_pages: Sequence[str],
    vi_sets: Sequence[tuple[frozenset[str], frozenset[str]]],
    readings: Any,
    *,
    skip_penalty: float,
    fold_weight: float,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """DP re-pairing of a sub-sequence without anchors. Same shapes as solve()."""
    seg_ch_pages = ch_pages[i0:i1]
    seg_vi_pages = vi_pages[j0:j1]
    seg = solve(
        seg_ch_pages,
        ch_chars[i0:i1],
        seg_vi_pages,
        vi_sets[j0:j1],
        readings,
        skip_penalty=skip_penalty,
        fold_weight=fold_weight,
    )
    return seg.pairs, seg.skipped_ch, seg.skipped_vi


def _dp_solve(
    ch_pages: Sequence[str],
    ch_chars: Sequence[Sequence[str]],
    vi_pages: Sequence[str],
    vi_sets: Sequence[tuple[frozenset[str], frozenset[str]]],
    readings: Any,
    *,
    skip_penalty: float = 25.0,
    fold_weight: float = 0.6,
) -> MapRepairResult:
    """Monotone DP re-pairing ch (reading order) with vi (reading order).

    Maximises total weighted reading matches; groups (1-1), (1-2), (2-1)
    allowed. Pages whose matches are too weak to beat the skip penalty
    are left unpaired (reported as skipped).
    """
    n, m = len(ch_pages), len(vi_pages)
    neg = float("-inf")
    dp = [[neg] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    # Cache of page-range scores keyed by (i0, i1, j0, j1).
    score_cache: dict[tuple[int, int, int, int], float] = {}

    def group_score(i0: int, i1: int, j0: int, j1: int) -> float:
        key = (i0, i1, j0, j1)
        if key not in score_cache:
            chars = [c for seg in ch_chars[i0:i1] for c in seg]
            exact = frozenset().union(*(vi_sets[j][0] for j in range(j0, j1)))
            folds = frozenset().union(*(vi_sets[j][1] for j in range(j0, j1)))
            score_cache[key] = pair_score(
                chars, (exact, folds), readings, fold_weight=fold_weight
            )
        return score_cache[key]

    for i in range(n + 1):
        for j in range(m + 1):
            base = dp[i][j]
            if base == neg:
                continue
            # (1-1) | (2-1) | (1-2)
            if i + 1 <= n and j + 1 <= m:
                cand = base + group_score(i, i + 1, j, j + 1)
                if cand > dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = cand
                    back[i + 1][j + 1] = ("pair", 1, 1)
            if i + 2 <= n and j + 1 <= m:
                cand = base + group_score(i, i + 2, j, j + 1)
                if cand > dp[i + 2][j + 1]:
                    dp[i + 2][j + 1] = cand
                    back[i + 2][j + 1] = ("pair", 2, 1)
            if i + 1 <= n and j + 2 <= m:
                cand = base + group_score(i, i + 1, j, j + 2)
                if cand > dp[i + 1][j + 2]:
                    dp[i + 1][j + 2] = cand
                    back[i + 1][j + 2] = ("pair", 1, 2)
            # skip a QN page (translator apparatus or surplus translation page)
            if j + 1 <= m:
                cand = base - skip_penalty
                if cand > dp[i][j + 1]:
                    dp[i][j + 1] = cand
                    back[i][j + 1] = ("skip_vi", 0, 1)
            # skip a Nôm page (no counterpart, e.g. unencodable title page)
            if i + 1 <= n:
                cand = base - skip_penalty
                if cand > dp[i + 1][j]:
                    dp[i + 1][j] = cand
                    back[i + 1][j] = ("skip_ch", 1, 0)

    groups: list[tuple[int, int, int, int]] = []
    skipped_ch: list[str] = []
    skipped_vi: list[str] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            raise RuntimeError("unreachable: back pointer missing")
        kind, a, b = step
        if kind == "pair":
            groups.append((i - a, i, j - b, j))
        elif kind == "skip_vi":
            skipped_vi.append(vi_pages[j - 1])
        else:
            skipped_ch.append(ch_pages[i - 1])
        i -= a
        j -= b
    groups.reverse()
    skipped_ch.reverse()
    skipped_vi.reverse()

    pairs = []
    for i0, i1, j0, j1 in groups:
        pairs.append({
            "ch": list(ch_pages[i0:i1]),
            "vi": list(vi_pages[j0:j1]),
        })
    return MapRepairResult(pairs=pairs, skipped_ch=skipped_ch, skipped_vi=skipped_vi)


def solve(
    ch_pages: Sequence[str],
    ch_chars: Sequence[Sequence[str]],
    vi_pages: Sequence[str],
    vi_sets: Sequence[tuple[frozenset[str], frozenset[str]]],
    readings: Any,
    *,
    skip_penalty: float = 25.0,
    fold_weight: float = 0.6,
    anchors: Sequence[tuple[str, str]] = (),
) -> MapRepairResult:
    """Anchor-aware re-pairing.

    ``anchors`` are (ch_name, vi_name) pairs pinned by evidence the book
    itself carries (e.g. the parenthetical Nôm page number printed in the
    QN header). Anchored pairs are exact 1-1 matches; the sequences between
    consecutive anchors are re-paired by the reading-match DP. Anchors that
    reference pages outside the inventory (e.g. excluded apparatus) or that
    break monotonicity are dropped and reported in ``anchor_issues`` —
    never trusted silently.
    """
    issues: list[str] = []
    ch_index = {name: i for i, name in enumerate(ch_pages)}
    vi_index = {name: j for j, name in enumerate(vi_pages)}

    pinned: list[tuple[int, int, str, str]] = []
    for ch_name, vi_name in anchors:
        ci = ch_index.get(ch_name)
        vj = vi_index.get(vi_name)
        if ci is None or vj is None:
            issues.append(f"anchor not in inventory: {ch_name} <-> {vi_name}")
            continue
        pinned.append((ci, vj, ch_name, vi_name))

    pinned.sort(key=lambda item: item[0])

    # Monotonicity and uniqueness of both sides.
    last_vi = -1
    ok: list[tuple[int, int, str, str]] = []
    for ci, vj, ch_name, vi_name in pinned:
        if vj <= last_vi:
            issues.append(f"anchor out of order: {ch_name} <-> {vi_name}")
            continue
        ok.append((ci, vj, ch_name, vi_name))
        last_vi = vj
    seen_ch: set[int] = set()
    seen_vi: set[int] = set()
    final_pinned: list[tuple[int, int, str, str]] = []
    for ci, vj, ch_name, vi_name in ok:
        if ci in seen_ch or vj in seen_vi:
            issues.append(f"duplicate anchor: {ch_name} <-> {vi_name}")
            continue
        seen_ch.add(ci)
        seen_vi.add(vj)
        final_pinned.append((ci, vj, ch_name, vi_name))

    if not final_pinned:
        seg = _dp_solve(
            ch_pages, ch_chars, vi_pages, vi_sets, readings,
            skip_penalty=skip_penalty, fold_weight=fold_weight,
        )
        seg.anchor_issues = issues
        return seg

    pairs: list[dict[str, Any]] = []
    skipped_ch: list[str] = []
    skipped_vi: list[str] = []

    def extend(seg: MapRepairResult) -> None:
        pairs.extend(seg.pairs)
        skipped_ch.extend(seg.skipped_ch)
        skipped_vi.extend(seg.skipped_vi)

    i = 0
    j = 0
    for ci, vj, ch_name, vi_name in final_pinned:
        if i < ci or j < vj:
            extend(_dp_solve(
                ch_pages[i:ci], ch_chars[i:ci],
                vi_pages[j:vj], vi_sets[j:vj],
                readings, skip_penalty=skip_penalty, fold_weight=fold_weight,
            ))
        pairs.append({"ch": [ch_name], "vi": [vi_name]})
        i = ci + 1
        j = vj + 1
    if i < len(ch_pages) or j < len(vi_pages):
        extend(_dp_solve(
            ch_pages[i:], ch_chars[i:],
            vi_pages[j:], vi_sets[j:],
            readings, skip_penalty=skip_penalty, fold_weight=fold_weight,
        ))

    return MapRepairResult(
        pairs=pairs,
        skipped_ch=skipped_ch,
        skipped_vi=skipped_vi,
        anchor_issues=issues,
    )


# ---------------------------------------------------------------------------
# Triage evidence
# ---------------------------------------------------------------------------


def recall_for(ch_chars: Sequence[str], vi_sets: Sequence[tuple[frozenset[str], frozenset[str]]], readings: Any) -> float:
    exact: set[str] = set()
    folds: set[str] = set()
    for e, f in vi_sets:
        exact |= e
        folds |= f
    return match_recall(ch_chars, (frozenset(exact), frozenset(folds)), readings)


def triage_rows(
    old_pairs: Sequence[dict[str, Any]],
    new_pairs: Sequence[dict[str, Any]],
    ch_chars_by_name: dict[str, list[str]],
    vi_sets_by_name: dict[str, tuple[frozenset[str], frozenset[str]]],
    readings: Any,
) -> list[dict[str, str]]:
    """Old → new pair assignment with recall evidence, one row per ch page."""
    def index(pairs):
        out: dict[str, list[str]] = {}
        for pair in pairs:
            for name in pair.get("ch", []):
                out.setdefault(name, [])
            for name in pair.get("ch", []):
                out[name] = list(pair.get("vi", []))
        return out

    old_map = index(old_pairs)
    new_map = index(new_pairs)

    def old_vi(ch: str) -> list[str]:
        return old_map.get(ch, [])

    def new_vi(ch: str) -> list[str]:
        return new_map.get(ch, [])

    all_ch = list(dict.fromkeys([*old_map, *new_map]))

    def union_sets(names):
        return [vi_sets_by_name[n] for n in names if n in vi_sets_by_name]

    rows: list[dict[str, str]] = []
    for ch in all_ch:
        o, n_ = old_vi(ch), new_vi(ch)
        chars = ch_chars_by_name.get(ch, [])
        old_r = recall_for(chars, union_sets(o), readings) if o else 0.0
        new_r = recall_for(chars, union_sets(n_), readings) if n_ else 0.0
        if o != n_:
            rows.append(
                {
                    "ch_page": ch,
                    "old_vi": "+".join(o) or "(unpaired)",
                    "new_vi": "+".join(n_) or "(skipped)",
                    "old_recall": f"{old_r:.3f}",
                    "new_recall": f"{new_r:.3f}",
                    "delta": f"{new_r - old_r:+.3f}",
                }
            )
    return rows


def write_triage_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ch_page", "old_vi", "new_vi", "old_recall", "new_recall", "delta"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_readings_for(entries_dir: Path, cache_path: Path, skip_sources: Iterable[str] | None = None) -> Any:
    return load_readings(str(entries_dir), str(cache_path), skip_sources=skip_sources)


def read_clean_text(clean_dir: Path, page_number: int) -> str:
    path = clean_dir / f"{page_number:04d}.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data.get("text", "") or "")


def image_page_number(name: str) -> int:
    match = re.search(r"\.(\d+)(?:_\d+)?\.jpg$", name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", name)
    return int(match.group(1)) if match else -1
