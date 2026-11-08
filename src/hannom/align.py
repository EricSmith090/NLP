"""Stage 6: sentence segmentation and Nôm↔Quốc ngữ alignment.

The aligner produces draft CSV rows. It deliberately does not pretend that
length similarity is semantic understanding: low-confidence rows are flagged
for review, and ``text_diff`` is null for every non-1-1 group.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .clean import MASK, TERMINAL_NOM, count_nom_chars, nfc
from .dictionary.book_lexicon import qn_syllables, strip_diacritics
from .models import AlignmentRow, DiffElement
from .t1_map import Pair
from .textdiff import auto_text_diff, validate_text_diff

QN_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\u2026])\s+(?=[A-ZÀ-Ỹ\"“(\[]|\d)")
NOM_TERMINAL_RE = re.compile(r"(?<=[\u3002\uFF01\uFF1F\uFF1B\uFF1A])")
QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass
class TextSegment:
    text: str
    image_name: str
    page_no: int
    page_numbers: tuple[int, ...]
    image_names: tuple[str, ...]
    script: str
    order: int
    flags: list[str] = field(default_factory=list)

    @property
    def nom_chars(self) -> int:
        return count_nom_chars(self.text)

    @property
    def syllables(self) -> int:
        return len(QN_TOKEN_RE.findall(self.text))


@dataclass
class AlignConfig:
    expected_syllables_per_nom_char: float = 1.0
    max_group: int = 4
    max_nm_group: int = 2
    one_to_many_penalty: float = 0.35
    many_to_one_penalty: float = 0.35
    many_to_many_penalty: float = 0.90
    low_confidence_threshold: float = 0.55
    max_qn_chars: int = 350
    max_nom_chars: int = 80
    join_cross_page: bool = True


def _as_config(raw: dict[str, Any] | None) -> AlignConfig:
    raw = (raw or {}).get("alignment", raw or {})
    defaults = AlignConfig()
    return AlignConfig(
        expected_syllables_per_nom_char=float(
            raw.get("expected_syllables_per_nom_char", defaults.expected_syllables_per_nom_char)
        ),
        max_group=int(raw.get("max_group", defaults.max_group)),
        max_nm_group=int(raw.get("max_nm_group", defaults.max_nm_group)),
        one_to_many_penalty=float(raw.get("one_to_many_penalty", defaults.one_to_many_penalty)),
        many_to_one_penalty=float(raw.get("many_to_one_penalty", defaults.many_to_one_penalty)),
        many_to_many_penalty=float(raw.get("many_to_many_penalty", defaults.many_to_many_penalty)),
        low_confidence_threshold=float(raw.get("low_confidence_threshold", defaults.low_confidence_threshold)),
        max_qn_chars=int(raw.get("max_qn_chars", defaults.max_qn_chars)),
        max_nom_chars=int(raw.get("max_nom_chars", defaults.max_nom_chars)),
        join_cross_page=bool(raw.get("join_cross_page", defaults.join_cross_page)),
    )


def _split_long_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        # Prefer a punctuation or whitespace boundary near the limit.
        cut = max(window.rfind(mark) for mark in (" ", ";", ",", "\u3001", "\uFF1B"))
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [p for p in pieces if p]


def split_nom_page(page: Any, max_chars: int = 80) -> list[str]:
    lines = list(getattr(page, "lines", []) or [])
    text = nfc(str(getattr(page, "text", "") or ""))
    if not lines:
        lines = [text] if text else []
    chunks: list[str] = []
    current = ""
    for line in lines:
        line = nfc(line)
        parts = [p for p in NOM_TERMINAL_RE.split(line) if p]
        if not parts:
            continue
        for part in parts:
            current += part
            if current and (
                current[-1] in TERMINAL_NOM or len(current) >= max_chars
            ):
                chunks.extend(_split_long_text(current, max_chars))
                current = ""
    if current:
        chunks.extend(_split_long_text(current, max_chars))
    return [c for c in chunks if c]


def split_qn_page(page: Any, max_chars: int = 350) -> list[str]:
    text = nfc(str(getattr(page, "text", "") or ""))
    if not text:
        return []
    parts = [p.strip() for p in QN_SENTENCE_SPLIT_RE.split(text) if p.strip()]
    out: list[str] = []
    for part in parts:
        out.extend(_split_long_text(part, max_chars))
    return out


def _may_join_across_pages(previous: str, following: str, script: str) -> bool:
    if not previous or not following:
        return False
    if script == "nom":
        # A page-final colon/comma strongly suggests the sentence continues.
        return previous[-1] not in TERMINAL_NOM and len(previous) < 35 and following[:1] != "〓"
    # QN: only join when the previous page does not end a sentence and the
    # next page starts in lowercase (or the previous ends with a hyphen).
    if previous.endswith("-") and following[:1].islower():
        return True
    return previous[-1] not in ".!?\u2026" and following[:1].islower()


def build_segments(
    pairs: Sequence[Pair],
    cleaned_by_name: dict[str, Any],
    script: str,
    config: AlignConfig,
) -> tuple[list[TextSegment], list[str]]:
    """Build reading-order segments from image-map pairs.

    ``pairs`` is already in reading order. For T1 this means the ch side is
    decreasing page order; the vi side is increasing.
    """
    warnings: list[str] = []
    segments: list[TextSegment] = []
    order = 0
    for pair in pairs:
        names = pair.ch if script == "nom" else pair.vi
        for name in names:
            page = cleaned_by_name.get(name)
            if page is None:
                warnings.append(f"MISSING_CLEAN_PAGE:{name}")
                continue
            pieces = (
                split_nom_page(page, config.max_nom_chars)
                if script == "nom"
                else split_qn_page(page, config.max_qn_chars)
            )
            for piece in pieces:
                segments.append(
                    TextSegment(
                        text=piece,
                        image_name=name,
                        page_no=int(getattr(page, "page_no", 0) or 0),
                        page_numbers=(int(getattr(page, "page_no", 0) or 0),),
                        image_names=(name,),
                        script=script,
                        order=order,
                    )
                )
                order += 1

    if not config.join_cross_page or len(segments) < 2:
        return segments, warnings

    merged: list[TextSegment] = []
    for segment in segments:
        if merged and _may_join_across_pages(merged[-1].text, segment.text, script):
            previous = merged[-1]
            joiner = "" if previous.text.endswith("-") and segment.text[:1].islower() else " "
            text = previous.text + joiner + segment.text
            if previous.text.endswith("-") and segment.text[:1].islower():
                text = previous.text[:-1] + segment.text
            merged[-1] = TextSegment(
                text=text,
                image_name=previous.image_name,
                page_no=previous.page_no,
                page_numbers=previous.page_numbers + segment.page_numbers,
                image_names=previous.image_names + segment.image_names,
                script=script,
                order=previous.order,
                flags=sorted(set(previous.flags + segment.flags + ["CROSS_PAGE_JOIN"])),
            )
        else:
            merged.append(segment)
    return merged, warnings


def _reading_matches(nom_text: str, vi_text: str, lexicon: Any | None) -> tuple[int, int]:
    """Return (matched known characters, known characters) for a group."""
    if lexicon is None:
        return 0, 0
    tokens = {s.casefold() for s in qn_syllables(vi_text)}
    tokens_flat = {strip_diacritics(t) for t in tokens}
    known = matched = 0
    for char in nom_text:
        if not char.strip():
            continue
        readings = lexicon.readings(char) if hasattr(lexicon, "readings") else []
        if not readings:
            continue
        known += 1
        if any(
            r.casefold() in tokens or strip_diacritics(r.casefold()) in tokens_flat
            for r in readings
        ):
            matched += 1
    return matched, known


def _group_cost(
    nom_text: str,
    vi_text: str,
    a: int,
    b: int,
    config: AlignConfig,
    lexicon: Any | None,
) -> float:
    nom_count = max(1, count_nom_chars(nom_text))
    vi_count = max(1, len(QN_TOKEN_RE.findall(vi_text)))
    observed = vi_count / nom_count
    expected = max(0.25, config.expected_syllables_per_nom_char)
    # Log ratio is scale-free and punishes both expansion and omission.
    ratio_cost = abs(math.log(max(0.05, observed) / expected))
    group_cost = 0.0
    if a > 1 and b == 1:
        group_cost = config.many_to_one_penalty * (a - 1)
    elif a == 1 and b > 1:
        group_cost = config.one_to_many_penalty * (b - 1)
    elif a > 1 and b > 1:
        group_cost = config.many_to_many_penalty * (a + b - 2)
    matched, known = _reading_matches(nom_text, vi_text, lexicon)
    reading_bonus = 0.0
    if known:
        reading_bonus = 1.2 * (matched / known)
    return max(0.0, ratio_cost + group_cost - reading_bonus)


def align_segments(
    nom_segments: Sequence[TextSegment],
    qn_segments: Sequence[TextSegment],
    *,
    config: AlignConfig | None = None,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    minimum_confidence: float | None = None,
) -> list[AlignmentRow]:
    config = config or AlignConfig()
    n, m = len(nom_segments), len(qn_segments)
    if n == 0 or m == 0:
        return []
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == inf:
                continue
            for a in range(1, config.max_group + 1):
                if i + a > n:
                    break
                for b in range(1, config.max_group + 1):
                    if j + b > m:
                        break
                    if a > 1 and b > 1 and (a > config.max_nm_group or b > config.max_nm_group):
                        continue
                    nom_text = "".join(s.text for s in nom_segments[i : i + a])
                    vi_text = " ".join(s.text for s in qn_segments[j : j + b])
                    cost = dp[i][j] + _group_cost(nom_text, vi_text, a, b, config, lexicon)
                    if cost < dp[i + a][j + b] - 1e-12:
                        dp[i + a][j + b] = cost
                        back[i + a][j + b] = (a, b)
    if dp[n][m] == inf:
        return []

    groups: list[tuple[int, int, int, int, float]] = []
    i, j = n, m
    while i > 0 and j > 0:
        step = back[i][j]
        if step is None:
            break
        a, b = step
        groups.append((i - a, i, j - b, j, dp[i][j] - dp[i - a][j - b]))
        i -= a
        j -= b
    groups.reverse()

    rows: list[AlignmentRow] = []
    counters: dict[str, int] = {}
    threshold = minimum_confidence if minimum_confidence is not None else config.low_confidence_threshold
    for (i0, i1, j0, j1, cost) in groups:
        nom_group = list(nom_segments[i0:i1])
        qn_group = list(qn_segments[j0:j1])
        if not nom_group or not qn_group:
            continue
        ch_txt = nfc("".join(s.text for s in nom_group))
        vi_txt = nfc(" ".join(s.text for s in qn_group).strip())
        if not ch_txt and not vi_txt:
            continue
        img_id = nom_group[0].image_name
        base = img_id[:-4] if img_id.lower().endswith(".jpg") else img_id
        counters[base] = counters.get(base, 0) + 1
        sentence_id = f"{base}.{counters[base]}"
        confidence = 1.0 / (1.0 + max(0.0, cost))
        flags: list[str] = []
        for segment in nom_group + qn_group:
            flags.extend(segment.flags)
        if len(nom_group) != 1 or len(qn_group) != 1:
            flags.append("NON_ONE_TO_ONE")
        if confidence < threshold:
            flags.append("ALIGN_LOW_CONF")
        if any(len(s.page_numbers) > 1 for s in nom_group + qn_group):
            flags.append("SPANS_PAGES")

        text_diff: list[DiffElement] | None
        if len(nom_group) == 1 and len(qn_group) == 1 and ch_txt and vi_txt:
            diff = auto_text_diff(
                ch_txt,
                vi_txt,
                lexicon=lexicon,
                dictionary=dictionary,
                strict_reading_mismatch=False,
            )
            text_diff = diff.elements
            flags.extend(diff.flags)
            if diff.review_reasons:
                flags.extend(f"REVIEW:{reason}" for reason in diff.review_reasons)
            if text_diff is not None:
                issues = validate_text_diff(ch_txt, vi_txt, text_diff)
                if issues:
                    flags.append("TEXT_DIFF_INVALID")
        else:
            text_diff = None
            flags.append("TEXT_DIFF_NULL_NON_ONE_TO_ONE")

        rows.append(
            AlignmentRow(
                img_id=img_id,
                sentence_id=sentence_id,
                ch_txt=ch_txt,
                vi_txt=vi_txt,
                text_diff=text_diff,
                confidence=confidence,
                flags=sorted(set(flags)),
            )
        )
    return rows


def align_book(
    book_id: str,
    pairs: Sequence[Pair],
    cleaned_by_name: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
) -> tuple[list[AlignmentRow], list[str]]:
    cfg = _as_config(config)
    nom_segments, nom_warnings = build_segments(pairs, cleaned_by_name, "nom", cfg)
    qn_segments, qn_warnings = build_segments(pairs, cleaned_by_name, "qn", cfg)
    if not nom_segments or not qn_segments:
        return [], nom_warnings + qn_warnings + ["NO_SEGMENTS_FOR_ALIGNMENT"]
    rows = align_segments(
        nom_segments,
        qn_segments,
        config=cfg,
        lexicon=lexicon,
        dictionary=dictionary,
    )
    return rows, sorted(set(nom_warnings + qn_warnings))


CSV_COLUMNS = ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]


def row_from_dict(data: dict[str, Any]) -> AlignmentRow:
    raw_diff = data.get("text_diff")
    if raw_diff is None:
        elements = None
    elif isinstance(raw_diff, str):
        value = json.loads(raw_diff) if raw_diff.strip() else []
        elements = None if value is None else [
            DiffElement(
                nom_pos=tuple(tuple(int(x) for x in p) for p in item.get("nom_pos", [])),
                nom_sub_text=str(item.get("nom_sub_text", "")),
                vi_pos=tuple(tuple(int(x) for x in p) for p in item.get("vi_pos", [])),
                vi_sub_text=str(item.get("vi_sub_text", "")),
                type=str(item.get("type", "error")),  # type: ignore[arg-type]
            )
            for item in value
        ]
    else:
        elements = [
            DiffElement(
                nom_pos=tuple(tuple(int(x) for x in p) for p in item.get("nom_pos", [])),
                nom_sub_text=str(item.get("nom_sub_text", "")),
                vi_pos=tuple(tuple(int(x) for x in p) for p in item.get("vi_pos", [])),
                vi_sub_text=str(item.get("vi_sub_text", "")),
                type=str(item.get("type", "error")),  # type: ignore[arg-type]
            )
            for item in raw_diff
        ]
    return AlignmentRow(
        img_id=str(data.get("img_id", "")),
        sentence_id=str(data.get("sentence_id", "")),
        ch_txt=str(data.get("ch_txt", "")),
        vi_txt=str(data.get("vi_txt", "")),
        text_diff=elements,
        confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
        flags=list(data.get("flags", []) or []),
    )


def write_alignment_csv(path: str | Path, rows: Iterable[AlignmentRow]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    nfc(row.img_id),
                    nfc(row.sentence_id),
                    nfc(row.ch_txt),
                    nfc(row.vi_txt),
                    row.text_diff_json(),
                ]
            )
    return path


def read_alignment_csv(path: str | Path) -> list[AlignmentRow]:
    rows: list[AlignmentRow] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError(f"unexpected CSV columns: {reader.fieldnames}")
        for record in reader:
            rows.append(row_from_dict(record))
    return rows
