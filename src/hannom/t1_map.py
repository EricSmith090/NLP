"""Stage 2b: T1 Nôm↔Quốc ngữ page mapping.

T1 books read QN front-to-back and Nôm back-to-front. The page map is a
partition of both reading-order sequences into 1-1, 1-n, or n-1 groups,
using text mass as a cheap alignment prior. OCR/alignment must refine it,
but the map is valid JSON and every image occurs at most once per side.

Honesty rule: a pair is only ``verified`` through *unique* reading
anchors (see ``hannom.anchors``) — at least ``verified_min_anchors`` of
them with ``verified_min_coverage`` coverage. Ink mass never verifies a
mapping. Pairs without word-level evidence stay ``candidate``; pairs
whose evidence does not confirm them stay ``unresolved``;
``image_map.manual.json`` applies explicit corrections (``manual``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .anchors import find_reading_anchors, gather_readings, token_items
from .clean import is_nom_char, nfc
from .config import BookConfig, ProjectConfig
from .models import PageRecord
from .state import State

PAIR_STATUSES = frozenset({"candidate", "verified", "unresolved", "manual"})

_NAME_PAGE_RE = re.compile(r"\.(\d{3,})(?:_\d+)?\.jpg$", re.IGNORECASE)


def image_name_page_no(name: str) -> int | None:
    """Extract the ≥3-digit page number from a submitted image name."""
    match = _NAME_PAGE_RE.search(str(name))
    return int(match.group(1)) if match else None


class ImageMapError(RuntimeError):
    pass


@dataclass(frozen=True)
class Pair:
    ch: tuple[str, ...]
    vi: tuple[str, ...]
    note: str | None = None
    confidence: float | None = None
    source: str | None = None
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"ch": list(self.ch), "vi": list(self.vi)}
        if self.note:
            d["note"] = self.note
        if self.confidence is not None:
            d["confidence"] = float(self.confidence)
        if self.source:
            d["source"] = self.source
        d["status"] = self.status
        return d


def _mass(page: PageRecord) -> float:
    # A page's text mass is its ink density, not its pixel count. Some pages
    # are native 564x800 rotated scans while the rest are 800x1135; using
    # width*height would silently give the rotated pages half the weight.
    f = page.features or {}
    ink = float(f.get("ink_fraction", 0.01) or 0.01)
    return max(1e-6, ink)


def _cumulative(values: list[float]) -> list[float]:
    out: list[float] = []
    total = 0.0
    for v in values:
        total += v
        out.append(total)
    return out


def _group_cost(
    ch_mass: float,
    vi_mass: float,
    total_ch: float,
    total_vi: float,
    a: int,
    b: int,
    config: dict[str, Any],
) -> float:
    expected = config.get("expected_syllables_per_nom_char", 1.0)
    # Both sides are normalised to [0,1], so a group's mass fraction is a
    # coarse proxy for how much text it contains.
    ratio = abs((ch_mass / total_ch) - (vi_mass / total_vi))
    penalty_1n = float(config.get("one_to_many_penalty", 0.35))
    penalty_n1 = float(config.get("many_to_one_penalty", 0.35))
    penalty_nm = float(config.get("many_to_many_penalty", 0.90))
    penalty = 0.0
    if a > 1 and b == 1:
        penalty = penalty_n1 * (a - 1)
    elif a == 1 and b > 1:
        penalty = penalty_1n * (b - 1)
    elif a > 1 and b > 1:
        penalty = penalty_nm * (a + b - 2)
    # The expected ratio is mostly a guardrail; mass fractions already
    # normalise book length, so do not let it dominate.
    ratio_guard = abs(expected - 1.0) * 0.05
    return ratio + penalty + ratio_guard


def score_pairs_with_anchors(
    pairs: list[Pair],
    cleaned_by_name: dict[str, str],
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    verified_min_coverage: float = 0.08,
    verified_min_anchors: int = 2,
) -> list[Pair]:
    """Attach anchor-evidence confidence/status to heuristic pairs.

    Verified strictly by *unique* local reading anchors: at least
    ``verified_min_anchors`` independent anchors AND fraction of
    reading-carrying Nôm characters with a reliable unique anchor must
    reach ``verified_min_coverage`` (recalibrated 0.5 → 0.08 — correct
    Tap1/Tap3 pairs measured min 0.061 / median 0.201). Pairs with reading
    evidence whose anchors do not meet both bars are ``unresolved``;
    pairs without reading evidence stay ``candidate``. Pairs never become
    ``verified`` via ink mass. (In the assigned books the marker formula
    supersedes this path: pairs are verified against the printed marker.)
    """
    scored: list[Pair] = []
    for pair in pairs:
        nom_items: list[list[str]] = []
        toks: list[tuple[int, int, str]] = []
        for name in pair.ch:
            ch_text = str(cleaned_by_name.get(name, "") or "")
            for char in ch_text:
                if is_nom_char(char):
                    # Deliberately no readings_cache kwarg: this is the
                    # superseded heuristic mass-DP scorer (the marker formula
                    # in build_marker_map is authoritative for the assigned
                    # books); keeping its evidence set unchanged avoids
                    # reshuffling any fallback pairing.
                    readings, _source = gather_readings(char, lexicon=lexicon, dictionary=dictionary)
                    nom_items.append(readings)
        for name in pair.vi:
            toks.extend(token_items(str(cleaned_by_name.get(name, "") or "")))
        known = sum(1 for readings in nom_items if readings)
        source = "heuristic_mass"
        if known == 0:
            scored.append(
                Pair(ch=pair.ch, vi=pair.vi, note=pair.note,
                     confidence=None, source=source, status="candidate")
            )
            continue
        anchors = find_reading_anchors(nom_items, toks)
        confidence = len(anchors) / known
        status = (
            "verified"
            if len(anchors) >= verified_min_anchors and confidence >= verified_min_coverage
            else "unresolved"
        )
        scored.append(
            Pair(ch=pair.ch, vi=pair.vi, note=pair.note,
                 confidence=round(confidence, 4), source=source + "+anchors", status=status)
        )
    return scored


def parse_manual_pairs(data: Any) -> list[Pair]:
    """Parse ``image_map.manual.json`` into explicit Pair objects."""
    items = data if isinstance(data, list) else data.get("pairs", [])
    if not isinstance(items, list) or not items:
        raise ImageMapError("image_map.manual.json: expected a non-empty list of pairs")
    out: list[Pair] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ImageMapError(f"manual pair {index}: expected an object")
        ch = tuple(str(name) for name in item.get("ch", []))
        vi = tuple(str(name) for name in item.get("vi", []))
        if not ch and not vi:
            raise ImageMapError(f"manual pair {index}: both sides empty")
        note = str(item.get("note") or "manual correction")
        out.append(Pair(ch=ch, vi=vi, note=note, confidence=1.0, source="manual", status="manual"))
    return out


def mapping_summary(pairs: list[Pair]) -> dict[str, int]:
    summary: dict[str, int] = {"pairs": len(pairs), "verified": 0, "candidate": 0,
                               "unresolved": 0, "manual": 0}
    for pair in pairs:
        summary[pair.status] = summary.get(pair.status, 0) + 1
    return summary


def build_marker_map(
    book: BookConfig,
    pages: list[PageRecord],
) -> list[Pair] | None:
    """Deterministic image map from the printed cross-reference markers.

    The T1 books print the Nôm *printed* page number in parentheses in the
    header of every substantive QN page (``- 58 - ( 65 )``). Print is produced
    as ``marker = (vi_to_nom_offset − 2) − vi_pdf``; the Nôm PDF page is then
    ``vi_to_nom_offset − vi_pdf`` (verified on image evidence on every page
    class sampled across all three books — no exceptions). When the book
    config carries ``vi_to_nom_offset``, the map is a bijection over the
    ``ch/`` ∪ ``vi/`` inventories: every QN page pairs 1:1 with the Nôm page
    the publisher paired it with. Pages without a marker (blanks, endnotes,
    dividers) never enter the map (they live outside the ``vi`` folder).

    Returns ``None`` when ``vi_to_nom_offset`` is not configured (books that
    do not carry markers fall back to the heuristic DP).
    """
    offset = getattr(book, "vi_to_nom_offset", None)
    if not offset:
        return None
    ch_by_page = {p.page_no: p for p in pages if p.folder == "ch"}
    vi_pages = sorted([p for p in pages if p.folder == "vi"], key=lambda p: p.page_no)
    pairs: list[Pair] = []
    used_ch: set[int] = set()
    for page in vi_pages:
        ch_no = offset - page.page_no
        nom_page = ch_by_page.get(ch_no)
        if nom_page is None:
            pairs.append(
                Pair(ch=(), vi=(page.image_name,),
                     note=f"printed marker maps to Nôm PDF {ch_no}, not in ch/",
                     source="printed_marker", status="unresolved")
            )
            continue
        used_ch.add(ch_no)
        pairs.append(
            Pair(ch=(nom_page.image_name,), vi=(page.image_name,),
                 note=f"printed marker: Nôm PDF = {offset} − vi PDF",
                 confidence=1.0, source="printed_marker", status="verified")
        )
    # Nôm pages whose mate is not in the vi folder (the QN page is blank or
    # scan-missing): insert them at their reading position with an empty vi
    # side — never silently dropped.
    leftover = sorted((no for no in ch_by_page if no not in used_ch), reverse=True)
    for ch_no in leftover:
        nom_page = ch_by_page[ch_no]
        marker_pair = Pair(
            ch=(nom_page.image_name,), vi=(),
            note="no Quốc ngữ counterpart (blank or scan-missing Quốc ngữ)",
            source="printed_marker", status="unresolved",
        )
        insert_at = len(pairs)
        for idx, pair in enumerate(pairs):
            if pair.ch:
                pair_ch = image_name_page_no(pair.ch[0])
                if pair_ch is not None and pair_ch < ch_no:
                    insert_at = idx
                    break
        pairs.insert(insert_at, marker_pair)
    return pairs


def _load_cleaned_texts(project: ProjectConfig, book: BookConfig) -> dict[str, str]:
    folder = project.data_dir / "clean" / book.book_id
    if not folder.exists():
        return {}
    texts: dict[str, str] = {}
    for path in folder.glob("*.json"):
        if path.name == "summary.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = data.get("image_name")
        if name:
            texts[str(name)] = str(data.get("text", "") or "")
    return texts


class _LookupResult:
    """Minimal lookup result shape expected by ``gather_readings``."""

    def __init__(self, readings):
        self.readings = list(readings)


class _HvdicCacheAdapter:
    """Adapter over the merged offline reading cache (hvdic/unihan/etc.).

    The cache (``data/dictionary/char_readings.json``) is the only dictionary
    available in long runs; wrapping it in the ``.lookup`` shape the anchor
    scorer consumes lets the pre-existing path verify pairs from real data.
    """

    def __init__(self, payload: dict):
        self.char = {str(c): list(v) for c, v in (payload.get("char") or {}).items()}

    def lookup(self, char):
        return _LookupResult(self.char.get(char, []))


def _load_hvdic_cache(project: ProjectConfig):
    cache_path = project.data_dir / "dictionary" / "char_readings.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return _HvdicCacheAdapter(payload)
    except Exception:
        return None


def _load_book_lexicon(project: ProjectConfig, book: BookConfig):
    path = project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json"
    if not path.exists():
        return None
    try:
        from .dictionary.book_lexicon import BookLexicon

        return BookLexicon(path)
    except Exception:
        return None


def align_page_groups(
    ch_pages: list[PageRecord],
    vi_pages: list[PageRecord],
    config: dict[str, Any] | None = None,
    max_group: int | None = None,
) -> list[Pair]:
    """Partition two reading-order sequences into page groups.

    ch_pages must already be in Nôm reading order (decreasing PDF page
    numbers for T1). vi_pages must be in QN reading order (increasing).
    Group limits honour ``max_group``/``max_nm_group`` from the alignment
    config (``configs/alignment.yaml``: ``max_group: 4``,
    ``max_nm_group: 2``) when not passed explicitly.
    """
    config = config or {}
    max_group = int(max_group if max_group is not None else config.get("max_group", 4))
    max_nm = int(config.get("max_nm_group", 2))
    n, m = len(ch_pages), len(vi_pages)
    if n == 0 or m == 0:
        raise ImageMapError("Both sides need at least one page for an image map")
    ch_mass = [_mass(p) for p in ch_pages]
    vi_mass = [_mass(p) for p in vi_pages]
    total_ch = sum(ch_mass)
    total_vi = sum(vi_mass)
    if total_ch <= 0 or total_vi <= 0:
        raise ImageMapError("Page mass must be positive")

    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == inf:
                continue
            for a in range(1, max_group + 1):
                if i + a > n:
                    break
                for b in range(1, max_group + 1):
                    if j + b > m:
                        break
                    if a > 1 and b > 1 and (a > max_nm or b > max_nm):
                        continue  # guideline: n-m only when translation is restructured, up to max_nm_group
                    cost = dp[i][j] + _group_cost(
                        sum(ch_mass[i : i + a]),
                        sum(vi_mass[j : j + b]),
                        total_ch,
                        total_vi,
                        a,
                        b,
                        config,
                    )
                    if cost < dp[i + a][j + b]:
                        dp[i + a][j + b] = cost
                        back[i + a][j + b] = (a, b)

    if dp[n][m] == inf:
        raise ImageMapError("Could not partition page sequences")
    pairs: list[Pair] = []
    i, j = n, m
    while i > 0 and j > 0:
        step = back[i][j]
        if step is None:
            raise ImageMapError("Broken backpointer in page mapping")
        a, b = step
        ch_group = tuple(p.image_name for p in ch_pages[i - a : i])
        vi_group = tuple(p.image_name for p in vi_pages[j - b : j])
        pairs.append(Pair(ch=ch_group, vi=vi_group, note="heuristic mass mapping",
                          source="heuristic_mass", status="candidate"))
        i -= a
        j -= b
    pairs.reverse()
    return pairs


def validate_image_map(
    pairs: list[Pair],
    ch_names: set[str] | None = None,
    vi_names: set[str] | None = None,
    *,
    vi_to_nom_offset: int | None = None,
) -> list[str]:
    issues: list[str] = []
    seen_ch: set[str] = set()
    seen_vi: set[str] = set()
    for idx, pair in enumerate(pairs):
        if not pair.ch and not pair.vi:
            issues.append(f"pair {idx}: both sides empty")
        if len(set(pair.ch)) != len(pair.ch):
            issues.append(f"pair {idx}: duplicate ch name within pair")
        if len(set(pair.vi)) != len(pair.vi):
            issues.append(f"pair {idx}: duplicate vi name within pair")
        for name in pair.ch:
            if name in seen_ch:
                issues.append(f"pair {idx}: ch name repeated across pairs: {name}")
            seen_ch.add(name)
            if ch_names is not None and name not in ch_names:
                issues.append(f"pair {idx}: unknown ch image {name}")
        for name in pair.vi:
            if name in seen_vi:
                issues.append(f"pair {idx}: vi name repeated across pairs: {name}")
            seen_vi.add(name)
            if vi_names is not None and name not in vi_names:
                issues.append(f"pair {idx}: unknown vi image {name}")
    # Coverage: every page of the relevant inventory must appear in exactly
    # one pair (or nowhere, with an empty-side pair recorded — both sides of
    # a pair may not be empty, but an empty side is allowed and counts as
    # coverage of the other side's scan-missing counterpart).
    all_ch = {name for p in pairs for name in p.ch}
    all_vi = {name for p in pairs for name in p.vi}
    if ch_names is not None:
        for name in sorted(ch_names - all_ch):
            issues.append(f"coverage: ch image {name} not in any pair")
    if vi_names is not None:
        for name in sorted(vi_names - all_vi):
            issues.append(f"coverage: vi image {name} not in any pair")
    # Monotonicity of pairs in book reading order (vi ascending, ch
    # descending). Empty-side pairs anchor at their non-empty side's rank;
    # an absent side is never asserted.
    def _vi_rank(pair: Pair) -> int | None:
        pages = [image_name_page_no(n) for n in pair.vi]
        return min(p for p in pages if p is not None) if any(pages) else None

    def _ch_rank(pair: Pair) -> int | None:
        pages = [image_name_page_no(n) for n in pair.ch]
        return max(p for p in pages if p is not None) if any(pages) else None

    vi_ranks = [_vi_rank(pair) for pair in pairs]
    ch_ranks = [_ch_rank(pair) for pair in pairs]
    for idx in range(len(pairs) - 1):
        if vi_ranks[idx] is not None and vi_ranks[idx + 1] is not None:
            if vi_ranks[idx] >= vi_ranks[idx + 1]:
                issues.append(f"order: pairs {idx} and {idx + 1} are not vi-ascending")
        if ch_ranks[idx] is not None and ch_ranks[idx + 1] is not None:
            if ch_ranks[idx] <= ch_ranks[idx + 1]:
                issues.append(f"order: pairs {idx} and {idx + 1} are not ch-descending")
    # Marker check: when the book carries a printed cross-reference marker
    # formula, every pair must satisfy Nôm PDF = vi_to_nom_offset − vi PDF
    # (1:1 by construction in this corpus).
    if vi_to_nom_offset:
        for idx, pair in enumerate(pairs):
            if len(pair.ch) == 1 and len(pair.vi) == 1:
                ch_page = image_name_page_no(pair.ch[0])
                vi_page = image_name_page_no(pair.vi[0])
                if ch_page is not None and vi_page is not None:
                    if ch_page != vi_to_nom_offset - vi_page:
                        issues.append(
                            f"marker: pair {idx} ({pair.vi[0]} ↔ {pair.ch[0]}) violates "
                            f"Nôm PDF = {vi_to_nom_offset} − vi PDF"
                        )
            else:
                issues.append(
                    f"marker: pair {idx} is not 1:1 ({len(pair.ch)} ch ↔ {len(pair.vi)} vi); "
                    f"markers prove 1:1 for this corpus"
                )
    return issues


def build_image_map(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    pages: list[PageRecord] | None = None,
) -> dict[str, Any]:
    pages = pages or state.pages(book.book_id)
    ch_pages = sorted([p for p in pages if p.folder == "ch"], key=lambda p: p.page_no, reverse=True)
    vi_pages = sorted([p for p in pages if p.folder == "vi"], key=lambda p: p.page_no)
    if not ch_pages:
        raise ImageMapError(f"{book.book_id}: no ch pages")
    if not vi_pages:
        raise ImageMapError(f"{book.book_id}: no vi pages")

    layout_dir = project.data_dir / "layout" / book.book_id
    dest = layout_dir / "image_map.json"
    manual_path = layout_dir / "image_map.manual.json"
    manual_source = manual_path.exists()
    marker_source = False
    anchor_source = False
    # Printed cross-reference markers are the deterministic ground truth for
    # these books (Nôm printed = PDF − 2; see verify-B §3). The formula map
    # replaces the heuristics whenever the book config carries the offset;
    # the heuristic DP remains the fallback for books without markers; the
    # manual correction file always wins.
    marker_map = build_marker_map(book, pages) if not manual_source else None
    if marker_map is not None:
        pairs = marker_map
        marker_source = True
    else:
        pairs = align_page_groups(
            ch_pages,
            vi_pages,
            config=(project.alignment_config or {}).get("alignment", {}),
        )
    if manual_source:
        # A manual correction file fully replaces the heuristic mapping;
        # unmatched entries or bad names fail loudly, never silently revert.
        manual_items = json.loads(manual_path.read_text(encoding="utf-8"))
        pairs = parse_manual_pairs(manual_items)
    elif not marker_source:
        # Marker-formula pairs are already verified by print; only the
        # heuristic DP fallback gets anchor-scored here.
        texts = _load_cleaned_texts(project, book)
        lexicon = _load_book_lexicon(project, book) if texts else None
        hvdic = _load_hvdic_cache(project)
        anchor_source = bool(texts)
        if anchor_source:
            pairs = score_pairs_with_anchors(
                pairs, texts, lexicon=lexicon, dictionary=hvdic,
            )
    # Scan-missing pages (guideline §Quy định chung về file ánh xạ hình ảnh):
    # missing_ch ⇔ vi empty, missing_vi ⇒ ch empty. These may not already
    # appear in the partitioned ch/vi lists (layout marks them separately).
    seen_ch = {name for p in pairs for name in p.ch}
    seen_vi = {name for p in pairs for name in p.vi}
    for p in sorted(
        [p for p in pages if p.folder == "missing_ch"],
        key=lambda p: p.page_no,
        reverse=True,
    ):
        if p.image_name not in seen_ch:
            pairs.append(
                Pair(
                    ch=(p.image_name,),
                    vi=(),
                    note="Trang Quốc ngữ tương ứng bị mất khi scan",
                )
            )
    for p in sorted(
        [p for p in pages if p.folder == "missing_vi"],
        key=lambda p: p.page_no,
    ):
        if p.image_name not in seen_vi:
            pairs.append(
                Pair(
                    ch=(),
                    vi=(p.image_name,),
                    note="Trang Nôm tương ứng bị mất khi scan",
                )
            )
    # Keep pairs sorted by QN reading order; empty-vi pairs key by Nom position.
    pair_order = {name: i for i, p in enumerate(vi_pages + sorted(
        [p for p in pages if p.folder == "missing_vi"],
        key=lambda p: p.page_no,
    )) for name in (p.image_name,)}
    nom_order = {p.image_name: p.page_no for p in pages}
    pairs.sort(
        key=lambda pair: (
            min((pair_order.get(name, 10**9) for name in pair.vi), default=10**9),
            max((nom_order.get(name, 0) for name in pair.ch), default=0),
        )
    )
    issues = validate_image_map(
        pairs,
        ch_names={p.image_name for p in pages if p.folder in {"ch", "missing_ch"}},
        vi_names={p.image_name for p in pages if p.folder in {"vi", "missing_vi"}},
        vi_to_nom_offset=getattr(book, "vi_to_nom_offset", None),
    )
    if issues:
        raise ImageMapError(f"{book.book_id}: invalid image map: {issues[:5]}")

    if manual_source:
        mapping_source = "manual"
    elif marker_source:
        mapping_source = "printed_marker"
    else:
        mapping_source = "heuristic_mass+anchor_evidence" if anchor_source else "heuristic_mass"
    summary = mapping_summary(pairs)
    data = {
        "pairs": [p.to_dict() for p in pairs],
        "meta": {
            "book_id": book.book_id,
            "layout": book.layout,
            "reading_order": {"ch": "decreasing page number", "vi": "increasing page number"},
            "mapping_source": mapping_source,
            "verified_pairs": summary.get("verified", 0),
            "candidate_pairs": summary.get("candidate", 0),
            "unresolved_pairs": summary.get("unresolved", 0),
            "manual_pairs": summary.get("manual", 0),
            "markers_used": sum(1 for p in pairs if p.source == "printed_marker"),
            "marker_issues": [
                p.note for p in pairs if p.status == "unresolved" and p.note
            ],
            "ch_page_count": len(ch_pages),
            "vi_page_count": len(vi_pages),
        },
    }
    if manual_source:
        data["meta"]["note"] = "image_map.manual.json applied; manual pairs carry status=manual"
    elif marker_source:
        data["meta"]["note"] = (
            "image map built from the printed cross-reference marker formula "
            "(Nôm printed = PDF − 2); every pair verified against print"
        )
        if getattr(book, "vi_to_nom_offset", None):
            data["meta"]["vi_to_nom_offset"] = book.vi_to_nom_offset
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    state.set_artifact(
        book.book_id,
        "layout",
        "image_map",
        dest,
        meta={"pairs": len(pairs), "ch_pages": len(ch_pages), "vi_pages": len(vi_pages)},
    )
    return data


def load_image_map(path: str | Path) -> list[Pair]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    pairs: list[Pair] = []
    for item in data.get("pairs", []):
        note = item.get("note")
        confidence = item.get("confidence")
        status = str(item.get("status") or "candidate")
        if status not in PAIR_STATUSES:
            status = "unresolved"  # unknown status: explicit, never silently verified
        pairs.append(
            Pair(
                ch=tuple(item.get("ch", [])),
                vi=tuple(item.get("vi", [])),
                note=note,
                confidence=float(confidence) if confidence is not None else None,
                source=item.get("source"),
                status=status,
            )
        )
    return pairs
