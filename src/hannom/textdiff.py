"""Stage 7: exact, code-point-based ``text_diff`` generation and validation.

Rules enforced here:
- strings are NFC before positions are computed;
- positions are 0-based half-open ranges over Unicode code points;
- ``[MASK]`` is exactly six code points, is never covered by a position,
  and is excluded from scoring;
- ``[]`` means compared with no asserted difference; ``None`` means the row
  is not a 1-1 comparison;
- uncertain semantics produce review flags, not invented red/yellow spans.

Automatic colouring is deliberately conservative. A known reading that
cannot be matched is a red candidate; a character with no evidence at all is
routed to review. Yellow is never generated automatically because the
guideline restricts it to specific human-confirmed cases.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .clean import MASK, count_nom_chars, is_nom_char, nfc
from .models import DiffElement

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
MASK_RE = re.compile(re.escape(MASK))


@dataclass
class DiffResult:
    elements: list[DiffElement] | None
    flags: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    matched_readings: int = 0
    known_nom_chars: int = 0
    unknown_nom_chars: int = 0

    @property
    def text_diff(self) -> list[DiffElement] | None:
        return self.elements

    def to_dict(self) -> dict[str, Any]:
        return {
            "text_diff": None
            if self.elements is None
            else [e.to_dict() for e in self.elements],
            "flags": self.flags,
            "review_reasons": self.review_reasons,
            "matched_readings": self.matched_readings,
            "known_nom_chars": self.known_nom_chars,
            "unknown_nom_chars": self.unknown_nom_chars,
        }


def mask_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in MASK_RE.finditer(text)]


def spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _covered_by_mask(span: tuple[int, int], masks: Sequence[tuple[int, int]]) -> bool:
    return any(spans_overlap(span, mask) for mask in masks)


def _char_positions(text: str) -> list[tuple[int, str]]:
    return [(i, ch) for i, ch in enumerate(text) if is_nom_char(ch)]


def _qn_tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0).casefold()) for m in QN_TOKEN_RE.finditer(text)]


def _span_text(text: str, spans: Sequence[Sequence[int]]) -> str:
    return "".join(text[int(start) : int(end)] for start, end in spans)


def _normalize_spans(value: Any) -> list[tuple[int, int]]:
    if value in (None, []):
        return []
    spans: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"position must be [start,end], got {item!r}")
        start, end = int(item[0]), int(item[1])
        spans.append((start, end))
    return spans


def make_element(
    nom: str,
    vi: str,
    nom_spans: Sequence[Sequence[int]] | None,
    vi_spans: Sequence[Sequence[int]] | None,
    kind: str,
    *,
    nom_sub_text: str | None = None,
    vi_sub_text: str | None = None,
) -> DiffElement:
    nom = nfc(nom)
    vi = nfc(vi)
    nspans = _normalize_spans(nom_spans)
    vspans = _normalize_spans(vi_spans)
    if kind not in {"warn", "error"}:
        raise ValueError("type must be 'warn' or 'error'")
    if not nspans and not vspans:
        raise ValueError("both sides of a diff element cannot be empty")
    for text, spans, label in ((nom, nspans, "nom"), (vi, vspans, "vi")):
        for start, end in spans:
            if not (0 <= start < end <= len(text)):
                raise ValueError(f"{label} span {start, end} outside text length {len(text)}")
    if nom_sub_text is None:
        nom_sub_text = _span_text(nom, nspans)
    if vi_sub_text is None:
        vi_sub_text = _span_text(vi, vspans)
    element = DiffElement(
        nom_pos=tuple(nspans),
        nom_sub_text=nom_sub_text,
        vi_pos=tuple(vspans),
        vi_sub_text=vi_sub_text,
        type=kind,  # type: ignore[arg-type]
    )
    issues = validate_element(nom, vi, element)
    if issues:
        raise ValueError("; ".join(issues))
    return element


def validate_element(nom: str, vi: str, element: DiffElement) -> list[str]:
    issues: list[str] = []
    nom = nfc(nom)
    vi = nfc(vi)
    if element.type not in {"warn", "error"}:
        issues.append(f"invalid type {element.type!r}")
    if not element.nom_pos and not element.vi_pos:
        issues.append("both sides are empty")
    if element.nom_pos:
        actual = _span_text(nom, element.nom_pos)
        if actual != element.nom_sub_text:
            issues.append(f"nom_sub_text does not match document text: {actual!r} != {element.nom_sub_text!r}")
    elif element.nom_sub_text:
        issues.append("nom_sub_text is non-empty but nom_pos is empty")
    if element.vi_pos:
        actual = _span_text(vi, element.vi_pos)
        if actual != element.vi_sub_text:
            issues.append(f"vi_sub_text does not match document text: {actual!r} != {element.vi_sub_text!r}")
    elif element.vi_sub_text:
        issues.append("vi_sub_text is non-empty but vi_pos is empty")
    masks = mask_spans(nom)
    for start, end in element.nom_pos:
        if not (0 <= start < end <= len(nom)):
            issues.append(f"nom span {start, end} outside length {len(nom)}")
        elif _covered_by_mask((start, end), masks):
            issues.append(f"nom span {start, end} overlaps [MASK]")
    for start, end in element.vi_pos:
        if not (0 <= start < end <= len(vi)):
            issues.append(f"vi span {start, end} outside length {len(vi)}")
    if len(set(element.nom_pos)) != len(element.nom_pos):
        issues.append("duplicate nom span")
    if len(set(element.vi_pos)) != len(element.vi_pos):
        issues.append("duplicate vi span")
    return issues


def validate_text_diff(
    nom: str,
    vi: str,
    elements: Sequence[DiffElement] | None,
    *,
    strict_identical: bool = False,
) -> list[str]:
    """Validate all structural invariants of one CSV row.

    ``None`` is valid only when the caller marks the row non-1-1; this
    function cannot see that flag, so it only reports whether the text pair
    is identical and a non-null empty list is plausible.
    """
    nom = nfc(nom)
    vi = nfc(vi)
    if elements is None:
        return []
    issues: list[str] = []
    if not isinstance(elements, (list, tuple)):
        return ["text_diff is not an array or null"]
    if strict_identical and not elements and nom != vi:
        issues.append("empty text_diff but texts are not identical")
    occupied_nom: list[tuple[tuple[int, int], str]] = []
    occupied_vi: list[tuple[tuple[int, int], str]] = []
    for index, element in enumerate(elements):
        if not isinstance(element, DiffElement):
            issues.append(f"element {index} is not a DiffElement")
            continue
        for issue in validate_element(nom, vi, element):
            issues.append(f"element {index}: {issue}")
        for span in element.nom_pos:
            for other, kind in occupied_nom:
                if spans_overlap(span, other) and kind != element.type:
                    issues.append(f"element {index}: overlapping nom positions of different types")
            occupied_nom.append((span, element.type))
        for span in element.vi_pos:
            for other, kind in occupied_vi:
                if spans_overlap(span, other) and kind != element.type:
                    issues.append(f"element {index}: overlapping vi positions of different types")
            occupied_vi.append((span, element.type))
    return issues


def diff_from_decisions(
    nom: str,
    vi: str,
    decisions: Iterable[dict[str, Any]],
) -> list[DiffElement]:
    """Build a diff from explicit human decisions.

    Each decision may use ``nom_pos``/``vi_pos`` and the corresponding
    ``*_sub_text`` fields, or simple ``nom_span``/``vi_span`` pairs.
    """
    nom = nfc(nom)
    vi = nfc(vi)
    elements: list[DiffElement] = []
    for decision in decisions:
        nspans = decision.get("nom_pos", decision.get("nom_span"))
        vspans = decision.get("vi_pos", decision.get("vi_span"))
        if isinstance(nspans, (list, tuple)) and len(nspans) == 2 and all(
            isinstance(x, int) for x in nspans
        ):
            nspans = [nspans]
        if isinstance(vspans, (list, tuple)) and len(vspans) == 2 and all(
            isinstance(x, int) for x in vspans
        ):
            vspans = [vspans]
        elements.append(
            make_element(
                nom,
                vi,
                nspans,
                vspans,
                str(decision.get("type", "error")),
                nom_sub_text=decision.get("nom_sub_text"),
                vi_sub_text=decision.get("vi_sub_text"),
            )
        )
    issues = validate_text_diff(nom, vi, elements, strict_identical=True)
    if issues:
        raise ValueError("; ".join(issues))
    return elements


def _reading_match(
    char: str,
    readings: Sequence[str],
    tokens: Sequence[tuple[int, int, str]],
    start_index: int,
) -> int | None:
    if not readings:
        return None
    flat_readings = set()
    for reading in readings:
        value = reading.strip().casefold()
        if not value:
            continue
        flat_readings.add(value)
        decomposed = unicodedata.normalize("NFD", value)
        flat_readings.add("".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn"))
    for index in range(start_index, len(tokens)):
        token = tokens[index][2]
        token_flat = "".join(
            ch
            for ch in unicodedata.normalize("NFD", token)
            if unicodedata.category(ch) != "Mn"
        )
        if token in flat_readings or token_flat in flat_readings:
            return index
    return None


def auto_text_diff(
    nom: str,
    vi: str,
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    strict_reading_mismatch: bool = False,
    proper_name: bool = False,
) -> DiffResult:
    """Conservative automatic diff.

    Only characters with a learned per-book reading can become red, and only
    when that reading cannot be matched anywhere in the QN sentence. Unknown
    characters never become red solely because a dictionary is incomplete.
    Yellow is never generated automatically.
    """
    nom = nfc(nom)
    vi = nfc(vi)
    flags: list[str] = []
    review: list[str] = []

    if nom == vi:
        return DiffResult(elements=[], flags=flags)
    # Mask differences are black and excluded from the denominator.
    if nom.replace(MASK, "") == vi.replace(MASK, ""):
        return DiffResult(elements=[], flags=["MASK_ONLY_DIFFERENCE"])

    chars = _char_positions(nom)
    tokens = _qn_tokens(vi)
    if not chars:
        return DiffResult(
            elements=None,
            flags=["DIFF_NO_NOM_CHARS"],
            review_reasons=["DIFF_NO_NOM_CHARS"],
        )
    if not tokens:
        return DiffResult(
            elements=None,
            flags=["DIFF_NO_QN_TOKENS"],
            review_reasons=["DIFF_NO_QN_TOKENS"],
        )

    readings_by_index: dict[int, list[str]] = {}
    known = 0
    for index, char in chars:
        readings: list[str] = []
        if lexicon is not None and hasattr(lexicon, "readings"):
            readings = list(lexicon.readings(char))
        if readings:
            readings_by_index[index] = readings
            known += 1

    if not known:
        # No positive evidence. Do not invent red spans and do not claim the
        # strings are identical; route the row to review.
        reason = "DIFF_UNVERIFIED_NO_BOOK_READINGS"
        flags.append(reason)
        review.append(reason)
        if dictionary is not None and hasattr(dictionary, "source_names") and not dictionary.source_names:
            flags.append("DICT_UNAVAILABLE")
        if proper_name:
            flags.append("PROPER_NAME_CANDIDATE")
        return DiffResult(
            elements=[],
            flags=sorted(set(flags)),
            review_reasons=sorted(set(review)),
            known_nom_chars=0,
            unknown_nom_chars=len(chars),
        )

    # Greedy reading alignment. QN expansions are allowed; unmatched known
    # Nôm characters are candidates for red.
    matched: set[int] = set()
    token_cursor = 0
    char_matches: dict[int, int] = {}
    for index, char in chars:
        readings = readings_by_index.get(index)
        if not readings:
            continue
        token_index = _reading_match(char, readings, tokens, token_cursor)
        if token_index is not None:
            matched.add(index)
            char_matches[index] = token_index
            token_cursor = token_index + 1

    unknown = len(chars) - known
    if unknown:
        flags.append("DIFF_UNKNOWN_NOM_CHARS")
        review.append("DICT_MISS")

    # Build disjoint runs of unmatched characters between matched anchors.
    elements: list[DiffElement] = []
    unmatched_run: list[tuple[int, str]] = []
    last_matched_token = -1
    anchors = sorted(char_matches.items(), key=lambda kv: kv[0])
    anchor_index = 0
    all_positions = [idx for idx, _ in chars]

    def flush_run(next_token_start: int | None) -> None:
        nonlocal unmatched_run
        if not unmatched_run:
            return
        known_run = [(idx, ch) for idx, ch in unmatched_run if idx in readings_by_index]
        if not known_run:
            review.append("DIFF_UNKNOWN_RUN")
            unmatched_run = []
            return
        # QN material between the previous matched token and the next one.
        start_token = last_matched_token + 1
        end_token = next_token_start if next_token_start is not None else len(tokens)
        qn_slice = tokens[start_token:end_token] if start_token < end_token else []
        if qn_slice:
            vi_start = qn_slice[0][0]
            vi_end = qn_slice[-1][1]
            vi_spans = [[vi_start, vi_end]]
            vi_text = vi[vi_start:vi_end]
        else:
            vi_spans = []
            vi_text = ""
        nom_start = known_run[0][0]
        nom_end = known_run[-1][0] + 1
        # Include only the known run in the Nôm span. If the run contains
        # unknown characters between known ones, expand to keep the span
        # contiguous and flag the uncertainty.
        nom_text = nom[nom_start:nom_end]
        try:
            elements.append(
                make_element(
                    nom,
                    vi,
                    [[nom_start, nom_end]],
                    vi_spans,
                    "error",
                    nom_sub_text=nom_text,
                    vi_sub_text=vi_text,
                )
            )
        except ValueError:
            review.append("DIFF_SPAN_BUILD_FAILED")
        unmatched_run = []

    for char_index, char in chars:
        if char_index in char_matches:
            # Flush immediately before this anchor; its token index bounds
            # the preceding QN material.
            flush_run(char_matches[char_index])
            last_matched_token = char_matches[char_index]
            anchor_index += 1
        else:
            unmatched_run.append((char_index, char))
    flush_run(None)

    if elements:
        flags.append("DIFF_READING_MISMATCH")
        review.append("DIFF_SEMANTIC")
    else:
        flags.append("DIFF_NO_READING_MISMATCH")
        if nom != vi:
            review.append("DIFF_UNVERIFIED_DIFFERENT_TEXT")

    if proper_name:
        flags.append("PROPER_NAME_CANDIDATE")
    if not strict_reading_mismatch and elements:
        # Keep the elements: they are based on positive reading evidence.
        # This branch documents that strictness is a caller policy, not a
        # semantic truth.
        flags.append("DIFF_REVIEW_RECOMMENDED")

    return DiffResult(
        elements=elements,
        flags=sorted(set(flags)),
        review_reasons=sorted(set(review)),
        matched_readings=len(matched),
        known_nom_chars=known,
        unknown_nom_chars=unknown,
    )


def diff_summary(elements: Sequence[DiffElement] | None) -> dict[str, int]:
    if elements is None:
        return {"null": 1}
    summary = {"warn": 0, "error": 0, "elements": len(elements)}
    for element in elements:
        summary[element.type] = summary.get(element.type, 0) + 1
    return summary


def yellow_spans(elements: Sequence[DiffElement] | None) -> list[tuple[int, int]]:
    if not elements:
        return []
    return [span for element in elements if element.type == "warn" for span in element.nom_pos]


def red_spans(elements: Sequence[DiffElement] | None) -> list[tuple[int, int]]:
    if not elements:
        return []
    return [span for element in elements if element.type == "error" for span in element.nom_pos]


def mask_character_count(text: str) -> int:
    return text.count(MASK)


def scoreable_nom_chars(text: str, elements: Sequence[DiffElement] | None = None) -> int:
    """Count Nôm characters excluding masks and yellow-covered chars."""
    total = count_nom_chars(text)
    if elements:
        for element in elements:
            if element.type != "warn":
                continue
            for start, end in element.nom_pos:
                total -= sum(1 for ch in text[start:end] if is_nom_char(ch))
    return max(0, total)


def red_penalty(elements: Sequence[DiffElement] | None) -> int:
    """Guideline numerator: max(Nôm chars, QN syllables) per error span."""
    if not elements:
        return 0
    penalty = 0
    for element in elements:
        if element.type != "error":
            continue
        nom_chars = count_nom_chars(element.nom_sub_text)
        qn_syllables = len(QN_TOKEN_RE.findall(element.vi_sub_text))
        penalty += max(nom_chars, qn_syllables)
    return penalty
