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
from .anchors import gather_readings
from .charalign import fold as variant_fold
from .models import DiffElement

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
MASK_RE = re.compile(re.escape(MASK))


def variant_fold_from_config(raw_config: Any | None) -> bool:
    """Read the ``text_diff.variant_fold`` key from a loaded alignment config.

    The key lives next to ``text_diff.unknown_policy`` in
    ``configs/alignment.yaml``; if it is missing the weak variant fold stays
    enabled (the documented default), matching the historical behaviour.
    Returns ``True`` unless the key is explicitly set to a falsy value.
    """
    cfg = raw_config or {}
    text_diff = cfg.get("text_diff") if isinstance(cfg, dict) else None
    if not isinstance(text_diff, dict):
        return True
    return bool(text_diff.get("variant_fold", True))


@dataclass
class DiffResult:
    elements: list[DiffElement] | None
    flags: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    matched_readings: int = 0
    known_nom_chars: int = 0
    unknown_nom_chars: int = 0
    lexicon_matched_readings: int = 0
    dictionary_matched_readings: int = 0
    dictionary_known_nom_chars: int = 0
    ambiguous_nom_chars: int = 0
    # NW anchor composition for auditability (exact=2.0, flat=1.0, fold=1.0).
    matched_exact_readings: int = 0
    matched_flat_readings: int = 0
    matched_fold_readings: int = 0

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
            "matched_exact_readings": self.matched_exact_readings,
            "matched_flat_readings": self.matched_flat_readings,
            "matched_fold_readings": self.matched_fold_readings,
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


def _is_letter(ch: str) -> bool:
    """A character allowed at the edge of a span (v2.4, official `EDGE`):
    a letter of either script, a digit, or the placeholder 〓."""
    return is_nom_char(ch) or ch == "\u3013" or ch.isalpha() or ch.isdigit()


def validate_element(nom: str, vi: str, element: DiffElement) -> list[str]:
    issues: list[str] = []
    nom = nfc(nom)
    vi = nfc(vi)
    if element.type not in {"warn", "error"}:
        issues.append(f"invalid type {element.type!r}")
    if not element.nom_pos and not element.vi_pos:
        issues.append("both sides are empty")
    for label, text, spans in (("nom", nom, element.nom_pos), ("vi", vi, element.vi_pos)):
        ordered = sorted(spans)
        if list(spans) != ordered:
            issues.append(f"{label} spans must be sorted ascending")
        for start, end in spans:
            if not (0 <= start < end <= len(text)):
                continue
            if not _is_letter(text[start]):
                issues.append(f"{label} span {start, end} must start with a letter")
            if not _is_letter(text[end - 1]):
                issues.append(f"{label} span {start, end} must end with a letter")
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
            for other, _kind in occupied_nom:
                if spans_overlap(span, other):
                    issues.append(f"element {index}: overlapping nom positions")
            occupied_nom.append((span, element.type))
        for span in element.vi_pos:
            for other, _kind in occupied_vi:
                if spans_overlap(span, other):
                    issues.append(f"element {index}: overlapping vi positions")
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


def auto_text_diff(
    nom: str,
    vi: str,
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    readings_cache: Any | None = None,
    strict_reading_mismatch: bool = False,
    proper_name: bool = False,
    allow_flat_match: bool = False,
    allow_variant_fold: bool = True,
) -> DiffResult:
    """Conservative automatic diff.

    Only characters with a learned per-book reading can become red, and only
    when that reading cannot be matched anywhere in the QN sentence. Unknown
    characters never become red solely because a dictionary is incomplete.
    Yellow is never generated automatically.

    Matching is exact (NFC, casefold) first; a weak variant fold
    (quỷ/quỉ/quĩ -> qui, d/gi and đ/d alternation) is accepted as a weak
    reading match (score 1.0, like the flat tone-folded match), never as a
    stronger signal. The fold applies to comparisons only, never to stored
    text. When the fold anchors at least one character the row carries the
    non-blocking flag ``DIFF_VARIANT_FOLD_APPLIED`` so fold coverage can be
    audited in ``summary.json`` / CSV flags; ``matched_fold_readings``
    counts the anchored characters.
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
    abs_pos = [abs_index for abs_index, _ in chars]
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
    sources: dict[int, str] = {}
    for index, char in chars:
        readings, source = gather_readings(
            char, lexicon=lexicon, dictionary=dictionary, readings=readings_cache
        )
        if readings:
            readings_by_index[index] = readings
            sources[index] = source
    known = len(readings_by_index)
    dictionary_known = sum(1 for source in sources.values() if "dictionary" in source)
    if known:
        token_set = {t[2] for t in tokens}
        ambiguous = sum(
            1 for readings in readings_by_index.values()
            if sum(1 for reading in readings if reading in token_set) >= 2
        )
    else:
        ambiguous = 0
    if ambiguous:
        flags.append("DIFF_AMBIGUOUS_READINGS")

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

    # Global 1-1 phonetic alignment (Needleman-Wunsch, O(n·m)) — far more
    # robust than a greedy cursor for this text class. Require an
    # exact, flat or (default-on) fold reading match to count as anchorable.
    # Evidence lookups are keyed by the ABSOLUTE position of the character in
    # the Nôm string (`abs_pos[list_index]`); the NW iteration indexes the
    # filtered ideograph list, so list index and absolute position diverge the
    # moment any non-ideograph (PUA, punctuation, [MASK]) precedes one.
    GAP = -1.2

    def _match_tier(list_index: int, token_index: int) -> str:
        rs = readings_by_index.get(abs_pos[list_index])
        if not rs:
            return "absent"  # neutral; matches are never made on this cell
        tok = tokens[token_index][2]
        exact = {r.strip().casefold() for r in rs if r.strip()}
        if tok in exact:
            return "exact"
        if allow_flat_match:
            flat = {
                "".join(c for c in unicodedata.normalize("NFD", r) if unicodedata.category(c) != "Mn")
                for r in exact
            }
            tok_flat = "".join(c for c in unicodedata.normalize("NFD", tok) if unicodedata.category(c) != "Mn")
            if tok_flat in flat:
                return "flat"
        if allow_variant_fold:
            fold_variants = {variant_fold(r) for r in exact}
            if variant_fold(tok) in fold_variants:
                return "fold"
        return "mismatch"

    def _score(list_index: int, token_index: int) -> float:
        tier = _match_tier(list_index, token_index)
        if tier in {"exact", "flat", "fold"}:
            return 2.0 if tier == "exact" else 1.0
        if tier == "mismatch":
            return -1.0
        return 0.0  # "absent"

    n, m_ = len(chars), len(tokens)
    NEG = -1e9
    dp = [[NEG] * (m_ + 1) for _ in range(n + 1)]
    back = [[None] * (m_ + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP
        back[i][0] = 'up'
    for j in range(1, m_ + 1):
        dp[0][j] = dp[0][j - 1] + GAP
        back[0][j] = 'left'
    for i in range(1, n + 1):
        for j in range(1, m_ + 1):
            s_ij = _score(i - 1, j - 1)
            diag = dp[i - 1][j - 1] + s_ij
            up = dp[i - 1][j] + GAP
            left = dp[i][j - 1] + GAP
            best = max(diag, up, left)
            dp[i][j] = best
            if best == diag:
                back[i][j] = 'diag'
            elif best == up:
                back[i][j] = 'up'
            else:
                back[i][j] = 'left'

    matched: set[int] = set()
    char_matches: dict[int, int] = {}
    lexicon_matched = 0
    dictionary_matched = 0
    tier_counters = {"exact": 0, "flat": 0, "fold": 0}
    i, j = n, m_
    while i > 0 or j > 0:
        step = back[i][j]
        if step == 'diag':
            tier = _match_tier(i - 1, j - 1)
            if tier in tier_counters:
                abs_index = abs_pos[i - 1]
                matched.add(abs_index)
                char_matches[abs_index] = j - 1
                tier_counters[tier] += 1
                source = sources.get(abs_index, "")
                if "lexicon" in source:
                    lexicon_matched += 1
                if "dictionary" in source:
                    dictionary_matched += 1
            i -= 1
            j -= 1
        elif step == 'up':
            i -= 1
        else:
            j -= 1

    unknown = len(chars) - known
    if unknown:
        flags.append("DIFF_UNKNOWN_NOM_CHARS")
        review.append("DICT_MISS")

    # Build disjoint runs of unmatched characters between matched anchors.
    elements: list[DiffElement] = []
    unmatched_run: list[tuple[int, str]] = []
    last_matched_token = -1
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

    if dictionary_matched:
        flags.append("DIFF_READINGS_FROM_DICTIONARY")
    if tier_counters["fold"]:
        flags.append("DIFF_VARIANT_FOLD_APPLIED")
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
        lexicon_matched_readings=lexicon_matched,
        dictionary_matched_readings=dictionary_matched,
        dictionary_known_nom_chars=dictionary_known,
        ambiguous_nom_chars=ambiguous,
        matched_exact_readings=tier_counters["exact"],
        matched_flat_readings=tier_counters["flat"],
        matched_fold_readings=tier_counters["fold"],
    )


# --- v2.4 / official-checker text_diff (FIX_PLAN T3.2, RC5/RC7) ----------
#
# Same semantics as ocr-nom-align v0.2.0 `diff.text_diff` with its defaults
# (independent implementation over this repo's readings): a weighted
# Levenshtein between Nôm characters and QN tokens (syllables and numbers);
# a character matches a syllable when the syllable, with the five tone marks
# removed, equals one of the character's readings with the tone marks removed
# (breve, circumflex, horn and đ still count); 〓 and characters with no known
# reading are red; every maximal run of unmatched characters, unmatched
# syllables and extra tokens on either side becomes one element; a run that
# holds a number is yellow (`warn`, reviewed 0), everything else is red.

SPEC_TONE_MARKS = frozenset("\u0300\u0301\u0303\u0309\u0323")
_SPEC_VI_TOKEN_RE = re.compile(r"\d+|[^\W\d_]+")
_SPEC_HAN = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF),
             (0xE000, 0xF8FF), (0xF0000, 0xFFFFD))
_SPEC_COST = {"match": 0.0, "mismatch": 1.0, "placeholder": 1.0, "unknown": 0.5, "num": 0.5}
_SPEC_GAP = 1.0
_EPS = 1e-9


def tone_key(syllable: str) -> str:
    """NFC, lower-case, the five tone marks removed (keeps ă â ê ô ơ ư đ)."""
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFC", syllable).lower())
    return unicodedata.normalize("NFC", "".join(c for c in s if c not in SPEC_TONE_MARKS))


def spec_is_nom_char(ch: str) -> bool:
    cp = ord(ch)
    return ch == "\u3013" or any(a <= cp <= b for a, b in _SPEC_HAN)


def _spec_segments(nom: str, vi: str) -> list[tuple[list[tuple[int, int, str, str]], list[tuple[int, int, str, str]]]]:
    def nom_tokens(a: int, b: int):
        return [(i, i + 1, nom[i], "han") for i in range(a, b) if spec_is_nom_char(nom[i])]

    def vi_tokens(a: int, b: int):
        return [(m.start(), m.end(), m.group(), "num" if m.group()[0].isdigit() else "syl")
                for m in _SPEC_VI_TOKEN_RE.finditer(vi, a, b)]

    cs, vs = mask_spans_official(nom), mask_spans_official(vi)
    if len(cs) != len(vs):  # masks do not pair up: align the cells jointly
        return [([t for a, b in cs for t in nom_tokens(a, b)], [t for a, b in vs for t in vi_tokens(a, b)])]
    return [(nom_tokens(a, b), vi_tokens(c, d)) for (a, b), (c, d) in zip(cs, vs)]


def mask_spans_official(text: str) -> list[tuple[int, int]]:
    """Text between [MASK] markers (empty spans kept, so both cells pair by index)."""
    out, pos = [], 0
    while True:
        k = text.find(MASK, pos)
        if k < 0:
            out.append((pos, len(text)))
            return out
        out.append((pos, k))
        pos = k + len(MASK)


def spec_text_diff(
    nom: str,
    vi: str,
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    readings_cache: Any | None = None,
    warn_numbers: bool = True,
) -> DiffResult:
    nom = nfc(nom)
    vi = nfc(vi)
    keys_cache: dict[str, frozenset[str]] = {}
    sources: dict[str, str] = {}

    def keys(ch: str) -> frozenset[str]:
        if ch not in keys_cache:
            readings, source = gather_readings(ch, lexicon=lexicon, dictionary=dictionary, readings=readings_cache)
            keys_cache[ch] = frozenset(tone_key(r) for r in readings if r and r.strip())
            sources[ch] = source
        return keys_cache[ch]

    def classify(c: tuple, t: tuple) -> str:
        if c[2] == "\u3013":
            return "placeholder"
        if t[3] == "num":
            return "num"
        ks = keys(c[2])
        if not ks:
            return "unknown"
        return "match" if tone_key(t[2]) in ks else "mismatch"

    elements: list[DiffElement] = []
    flags: list[str] = []
    review: list[str] = []
    n_nom = matched = unknown_chars = placeholders = 0
    for nt, vt in _spec_segments(nom, vi):
        n_nom += len(nt)
        n, m = len(nt), len(vt)
        d = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            d[i][0] = i * _SPEC_GAP
        for j in range(1, m + 1):
            d[0][j] = j * _SPEC_GAP
        kinds: dict[tuple[int, int], str] = {}
        for i in range(1, n + 1):
            prev, row = d[i - 1], d[i]
            for j in range(1, m + 1):
                kind = classify(nt[i - 1], vt[j - 1])
                kinds[(i - 1, j - 1)] = kind
                row[j] = min(prev[j - 1] + _SPEC_COST[kind], prev[j] + _SPEC_GAP, row[j - 1] + _SPEC_GAP)
        ops: list[tuple[str, int | None, int | None]] = []
        i, j = n, m
        while i > 0 or j > 0:  # ties prefer a gap (surplus tokens land last)
            if i > 0 and abs(d[i][j] - (d[i - 1][j] + _SPEC_GAP)) < _EPS:
                ops.append(("d", i - 1, None))
                i -= 1
            elif j > 0 and abs(d[i][j] - (d[i][j - 1] + _SPEC_GAP)) < _EPS:
                ops.append(("i", None, j - 1))
                j -= 1
            else:
                ops.append(("s", i - 1, j - 1))
                i, j = i - 1, j - 1
        ops.reverse()
        run_n: list[tuple] = []
        run_v: list[tuple] = []

        def flush() -> None:
            if not run_n and not run_v:
                return
            if any(t[2] == "\u3013" for t in run_n):
                kind = "error"
            elif warn_numbers and run_n and any(t[3] == "num" for t in run_v):
                kind = "warn"
            else:
                kind = "error"
            nom_spans = [[run_n[0][0], run_n[-1][1]]] if run_n else []
            vi_spans = [[run_v[0][0], run_v[-1][1]]] if run_v else []
            el = make_element(nom, vi, nom_spans, vi_spans, kind)
            if kind == "warn":
                el = DiffElement(el.nom_pos, el.nom_sub_text, el.vi_pos, el.vi_sub_text, "warn", reviewed=0)
            elements.append(el)
            run_n.clear()
            run_v.clear()

        for op, a, b in ops:
            if op == "s":
                kind = kinds[(a, b)]
                if kind == "unknown":
                    unknown_chars += 1
                if kind == "placeholder":
                    placeholders += 1
                if kind == "match":
                    matched += 1
                    flush()
                    continue
                run_n.append(nt[a])
                run_v.append(vt[b])
            elif op == "d":
                run_n.append(nt[a])
            else:
                run_v.append(vt[b])
        flush()
    if unknown_chars:
        flags.append("DIFF_UNKNOWN_NOM_CHARS")
        review.append("DICT_MISS")
    if placeholders:
        flags.append("DIFF_PLACEHOLDER_RED")
    if any(e.type == "error" for e in elements):
        flags.append("DIFF_READING_MISMATCH")
        review.append("DIFF_SEMANTIC")
    if any(e.type == "warn" for e in elements):
        flags.append("DIFF_NUMBER_WARN")
    flags.append("DIFF_POLICY_SPEC_V24")
    known = sum(1 for c, ks in keys_cache.items() if ks)
    return DiffResult(
        elements=elements,
        flags=sorted(set(flags)),
        review_reasons=sorted(set(review)),
        matched_readings=matched,
        known_nom_chars=known,
        unknown_nom_chars=len(keys_cache) - known,
        dictionary_matched_readings=0,
        dictionary_known_nom_chars=sum(1 for c in keys_cache if "dictionary" in sources.get(c, "")),
        matched_exact_readings=matched,
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


def spec_count_nom(text: str) -> int:
    """Nôm characters as the official checker counts them (Han, PUA, 〓)."""
    return sum(1 for ch in text if spec_is_nom_char(ch))


def spec_count_vi(text: str) -> int:
    """QN tokens as the official checker counts them (syllables and numbers)."""
    return len(_SPEC_VI_TOKEN_RE.findall(text))


def scoreable_nom_chars(text: str, elements: Sequence[DiffElement] | None = None) -> int:
    """Denominator (v2.4): Nôm characters (〓 and PUA included) minus yellow
    ones; punctuation and [MASK] are not Nôm characters."""
    total = spec_count_nom(text)
    if elements:
        for element in elements:
            if element.type != "warn":
                continue
            for start, end in element.nom_pos:
                total -= spec_count_nom(text[start:end])
    return max(0, total)


def red_penalty(elements: Sequence[DiffElement] | None) -> int:
    """Guideline numerator: max(Nôm chars, QN syllables) per error span."""
    if not elements:
        return 0
    penalty = 0
    for element in elements:
        if element.type != "error":
            continue
        penalty += max(spec_count_nom(element.nom_sub_text), spec_count_vi(element.vi_sub_text))
    return penalty
