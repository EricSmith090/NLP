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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .anchors import find_reading_anchors, gather_readings, token_items
from .clean import is_nom_char, nfc
from .config import BookConfig, ProjectConfig
from .models import PageRecord
from .state import State

PAIR_STATUSES = frozenset({"candidate", "verified", "unresolved", "manual"})


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
    verified_min_coverage: float = 0.5,
    verified_min_anchors: int = 2,
) -> list[Pair]:
    """Attach anchor-evidence confidence/status to heuristic pairs.

    Verified strictly by *unique* local reading anchors: the fraction of
    reading-carrying Nôm characters with a reliable unique anchor must
    reach ``verified_min_coverage`` AND at least ``verified_min_anchors``
    independent anchors must exist. Pairs with reading evidence whose
    anchors do not meet both bars are ``unresolved`` (evidence was found
    but does not confirm the pairing); pairs without reading evidence are
    ``candidate``. Pairs never become ``verified`` via ink mass or dense
    repeated readings.
    """
    scored: list[Pair] = []
    for pair in pairs:
        nom_items: list[list[str]] = []
        toks: list[tuple[int, int, str]] = []
        for name in pair.ch:
            ch_text = str(cleaned_by_name.get(name, "") or "")
            for char in ch_text:
                if is_nom_char(char):
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
    max_group: int = 3,
) -> list[Pair]:
    """Partition two reading-order sequences into page groups.

    ch_pages must already be in Nôm reading order (decreasing PDF page
    numbers for T1). vi_pages must be in QN reading order (increasing).
    """
    config = config or {}
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
                    if a > 1 and b > 1:
                        continue  # guideline allows n-m but prefers smaller units
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

    pairs = align_page_groups(
        ch_pages,
        vi_pages,
        config=(project.alignment_config or {}).get("alignment", {}),
    )
    layout_dir = project.data_dir / "layout" / book.book_id
    dest = layout_dir / "image_map.json"
    manual_path = layout_dir / "image_map.manual.json"
    manual_source = manual_path.exists()
    anchor_source = False
    if manual_source:
        # A manual correction file fully replaces the heuristic mapping;
        # unmatched entries or bad names fail loudly, never silently revert.
        manual_items = json.loads(manual_path.read_text(encoding="utf-8"))
        pairs = parse_manual_pairs(manual_items)
    else:
        texts = _load_cleaned_texts(project, book)
        lexicon = _load_book_lexicon(project, book) if texts else None
        anchor_source = bool(texts) and lexicon is not None
        if anchor_source:
            pairs = score_pairs_with_anchors(pairs, texts, lexicon=lexicon)
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
    )
    if issues:
        raise ImageMapError(f"{book.book_id}: invalid image map: {issues[:5]}")

    mapping_source = (
        "manual"
        if manual_source
        else ("heuristic_mass+anchor_evidence" if anchor_source else "heuristic_mass")
    )
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
            "ch_page_count": len(ch_pages),
            "vi_page_count": len(vi_pages),
        },
    }
    if manual_source:
        data["meta"]["note"] = "image_map.manual.json applied; manual pairs carry status=manual"
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
