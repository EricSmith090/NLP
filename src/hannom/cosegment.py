"""Co-segmentation of Nôm ↔ Quốc ngữ for phonetic (dịch âm) 1-1 books.

T1 books are sentence-aligned 1-1 at the reading level. The Quốc ngữ text
carries real sentence punctuation; the Nôm side does not (hoặc rarely does).

``stream_cosegment`` — the primary mode: build one reading stream per
  script, split the QN stream at sentence punctuation and assign the same
  cut points to the Nôm stream. Cuts are derived from reliable local
  reading anchors (see ``hannom.anchors``) when anchor evidence exists,
  interpolated between sufficiently close anchors, and fall back to
  proportional shares only when no anchor evidence brackets a boundary;
  fallback segments carry ``COSEGMENTED_UNANCHORED`` and are never trusted
  as verified evidence. Chunks spanning a page boundary are attributed to
  every page they cover and carry SPANS_PAGES.
  The result is a list of ``Segment`` covering every page exactly once, in
  reading order, with the same boundaries on both scripts. A sentence whose
  co-cut collapses to zero width is never silently dropped: the Nôm side is
  emitted as an empty ``UNMATCHED_QN`` segment (a whole-sentence gap, to be
  resolved by human review) and a token-level parity budget in ``stats``
  makes any loss detectable fail-closed by the caller.

The per-page fallback (``split_nom_page`` / ``split_qn_page`` in Stage 6,
``hannom.align``) is used only when the stream cannot be built (too little
material) — see ``build_segments``.
"""


from __future__ import annotations

import re
from typing import Any

from .anchors import MAX_ANCHOR_GAP_TOKENS, find_reading_anchors, gather_readings, token_items
from .clean import QN_ABBREVIATIONS, VIETNAMESE_UPPER_CLASS, is_nom_char, nfc

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
SENTENCE_STOP_RE = re.compile(r"[.!?;:]")
SENTENCE_UPPER_RE = re.compile("[" + VIETNAMESE_UPPER_CLASS + r"0-9\"“(\[]")

# Abbreviations that end with a full stop but are not sentence boundaries.
# The set lives in ``hannom.clean`` so the stream splitter and the Stage-6
# per-page fallback stay in lockstep.
TRAILING_ABBREV_RE = re.compile(r"([^\W\d_]+)\.$", re.UNICODE)


def is_abbreviation_stop(text: str, stop_end: int) -> bool:
    """True when the stop right before ``stop_end`` closes a known abbreviation."""
    m = TRAILING_ABBREV_RE.search(text[:stop_end])
    return bool(m and m.group(1).casefold() in QN_ABBREVIATIONS)


def qn_sentence_spans(text: str) -> list[tuple[int, int, int]]:
    """Return (char_start, char_end, token_count) per sentence."""
    stops: list[int] = []
    for m in SENTENCE_STOP_RE.finditer(text):
        end = m.end()
        rest = text[end:].lstrip()
        if not rest:
            stops.append(end)
        elif SENTENCE_UPPER_RE.match(rest) and not is_abbreviation_stop(text, end):
            stops.append(end)

    starts = [0] + stops
    ends = stops + [len(text)]
    spans: list[tuple[int, int, int]] = []
    for a, b in zip(starts, ends):
        seg = text[a:b].strip()
        if not seg:
            continue
        tcount = len(QN_TOKEN_RE.findall(seg))
        real_start = a + text[a:b].find(seg)
        spans.append((real_start, real_start + len(seg), tcount))
    return spans


# ---------------------------------------------------------------------------
# Stream mode (primary)
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class PageUnit:
    image_name: str
    text: str


@dataclass
class StreamSegment:
    text: str
    image_names: tuple[str, ...]
    image_name: str
    page_numbers: tuple[int, ...]
    page_no: int
    order_no: int = 0
    flags: list[str] = field(default_factory=lambda: ["COSEGMENTED"])


def _concat_with_offsets(units: Sequence[PageUnit], separator: str = " ") -> tuple[str, list[tuple[str, int, int, int]]]:
    """Concatenate pages in reading order, recording each page's char span.

    Returns the full text and the list of (image_name, page_no, start, end)
    in reading order.
    """
    parts: list[str] = []
    spans: list[tuple[str, int, int, int]] = []
    cursor = 0
    for unit in units:
        if unit.text:
            if parts:
                parts.append(separator)
                cursor += len(separator)
            start = cursor
            parts.append(unit.text)
            end = start + len(unit.text)
            try:
                page_no = int(unit.image_name.split(".")[-2])
            except ValueError:
                page_no = 0
            spans.append((unit.image_name, page_no, start, end))
            cursor = end
    return "".join(parts), spans


def _anchor_cuts(
    *,
    nom_items: list[list[str]],
    qn_tokens: list[tuple[int, int, str]],
    qn_text: str,
    sentences: list[tuple[int, int, int]],
    sentence_token_ranges: list[tuple[int, int]],
    total_nom: int,
    total_tok: int,
    window: int | None,
    max_gap_tokens: int,
    sentence_window_factor: float = 1.5,
) -> tuple[list[tuple[int, int]], set[int]]:
    """Return (per-sentence CJK cuts, boundary indices without anchor evidence).

    Each boundary is estimated from the bracketing reliable anchors inside a
    ±``window`` neighborhood of the proportional estimate. ``window`` may be
    ``None`` for a sentence-relative window of ``max(30, round(factor *
    sentence_tokens))``. When a boundary is not bracketed by at least one
    anchor on each side, it falls back to the proportional cut and its
    index is added to the unanchored set.
    """
    toks_at = [token[0] for token in qn_tokens]
    boundaries: list[int | None] = [0]  # one cut per sentence boundary (0..len(sentences))
    unanchored: set[int] = set()
    for boundary in range(1, len(sentences)):
        est = round(sentence_token_ranges[boundary][0] * total_nom / total_tok)
        tcount = sentences[boundary][2]
        w = window if window is not None else max(30, int(round(sentence_window_factor * tcount)))
        lo = max(0, est - w)
        hi = min(total_nom, est + w)
        tok_mid = sentence_token_ranges[boundary][0]
        k_lo = max(0, tok_mid - w)
        k_hi = min(len(qn_tokens), tok_mid + w)
        sub_anchors = find_reading_anchors(nom_items[lo:hi], qn_tokens[k_lo:k_hi])
        anchors = [(i + lo, k + k_lo) for i, k in sub_anchors]
        boundary_char = sentences[boundary][0]
        left = [a for a in anchors if a[1] < tok_mid]
        right = [a for a in anchors if a[1] >= tok_mid]
        cut: int | None = None
        if left and right:
            left_anchor, right_anchor = left[-1], right[0]
            gap = right_anchor[1] - left_anchor[1]
            if right_anchor[0] > left_anchor[0] and gap <= max_gap_tokens:
                left_char = toks_at[left_anchor[1]]
                right_char = toks_at[right_anchor[1]]
                span = max(1, right_char - left_char)
                fraction = (boundary_char - left_char) / span
                cut = int(round(left_anchor[0] + fraction * (right_anchor[0] - left_anchor[0])))
                cut = max(0, min(total_nom, cut))
        if cut is None:
            cut = est
            unanchored.add(boundary)
        boundaries.append(cut)
    boundaries.append(total_nom)
    # Keep cuts monotone, clamped to the Nôm stream. Every non-empty sentence
    # is guaranteed at least a 1-ideograph span when the stream has enough
    # ideographs for it; only the tail can still collapse (and is emitted as
    # UNMATCHED_QN by the caller instead of being dropped silently).
    cuts: list[tuple[int, int]] = []
    prev_end = 0
    for index in range(len(sentences)):
        start_cut = boundaries[index]
        end_cut = boundaries[index + 1]
        start_cut = max(prev_end, min(total_nom, start_cut))
        end_cut = max(start_cut, min(total_nom, end_cut))
        if end_cut == start_cut and start_cut < total_nom:
            end_cut = start_cut + 1
        cuts.append((start_cut, end_cut))
        prev_end = end_cut
    # Boundary indices are sentence boundaries (1..len(sentences) - 1); the
    # trivially free stream edges never count as unanchored.
    return cuts, unanchored


def stream_cosegment(
    nom_units: Sequence[PageUnit],
    qn_units: Sequence[PageUnit],
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    readings_cache: Any | None = None,
    max_anchor_gap_tokens: int = MAX_ANCHOR_GAP_TOKENS,
    anchor_window: int | None = None,
    sentence_window_factor: float = 1.5,
    stats: dict[str, Any] | None = None,
) -> tuple[list[StreamSegment], list[StreamSegment]] | None:
    """Segment the reading stream of both scripts at QN sentence boundaries.

    Returns two lists (nom_segments, qn_segments) of the same length and
    order. Each segment carries page attribution and one of
    ``COSEGMENTED_ANCHORED`` (both boundary cuts were derived from reliable
    reading anchors) or ``COSEGMENTED_UNANCHORED`` (proportional-fallback
    segmentation; never trusted as verified evidence or scoring). Returns
    None when the stream is too small to split.

    A sentence whose co-cut collapses to zero width is never silently
    dropped: the empty Nôm side is emitted with ``UNMATCHED_QN`` so the gap
    becomes a reviewable row. When ``stats`` is provided it is filled with
    token-level accounting (``stream_sentences``, ``qn_tokens_stream``,
    ``qn_tokens_emitted``, ``segments_dropped``, ``sentence_coverage``,
    ``sentences_isolated``) so the caller can assert parity fail-closed.
    """
    qn_text, qn_spans = _concat_with_offsets(qn_units, separator=" ")
    if not qn_text.strip():
        return None
    sentences = qn_sentence_spans(qn_text)
    total_tok = sum(t for _, _, t in sentences)
    if total_tok == 0:
        return None

    nom_text, nom_spans = _concat_with_offsets(nom_units, separator="")
    if not nom_text.strip():
        return None
    nom_idx = [i for i, ch in enumerate(nom_text) if is_nom_char(ch)]
    total_nom = len(nom_idx)
    if total_nom < 20 or len(sentences) < 2:
        return None

    # ------------------------------------------------------------------
    # Cut positions: windowed anchor interpolation, proportional fallback
    # otherwise. Fallback cuts are flagged COSEGMENTED_UNANCHORED.
    # ------------------------------------------------------------------
    nom_items: list[list[str]] = []
    for pos, index in enumerate(nom_idx):
        readings, _source = gather_readings(
            nom_text[index], lexicon=lexicon, dictionary=dictionary, readings=readings_cache
        )
        nom_items.append(readings)
    qn_tokens = token_items(qn_text)

    # Sentence j occupies tokens [tok_start_j, tok_end_j).
    sentence_token_ranges: list[tuple[int, int]] = []
    cursor = 0
    for _a, _b, tcount in sentences:
        sentence_token_ranges.append((cursor, cursor + tcount))
        cursor += tcount

    nom_cuts, unanchored_cuts = _anchor_cuts(
        nom_items=nom_items,
        qn_tokens=qn_tokens,
        qn_text=qn_text,
        sentences=sentences,
        sentence_token_ranges=sentence_token_ranges,
        total_nom=total_nom,
        total_tok=total_tok,
        window=anchor_window,
        max_gap_tokens=max_anchor_gap_tokens,
        sentence_window_factor=sentence_window_factor,
    )

    # For the QN side, ranges are character-index ranges; for the Nôm side,
    # character ranges directly. Build per-chunk attribution for each script.
    def chunk_pages(prefix_m: list[tuple[str, int, int, int]], start_q: int, end_q: int) -> tuple[str, tuple[int, ...], tuple[str, ...]]:
        pages: list[str] = []
        page_numbers: list[int] = []
        for name, page_no, s, e in prefix_m:
            if s == e:
                continue
            if e <= start_q or s >= end_q:
                continue
            pages.append(name)
            page_numbers.append(page_no)
        return pages[0], tuple(page_numbers), tuple(pages)

    def nom_chunk_pages(start_n: int, end_n: int):
        pages: list[str] = []
        page_numbers: list[int] = []
        for name, page_no, s, e in nom_spans:
            if s == e:
                continue
            lo = next((i for i, pos in enumerate(nom_idx) if pos >= s), len(nom_idx))
            hi = next((i for i, pos in enumerate(nom_idx) if pos >= e), len(nom_idx))
            if hi <= start_n or lo >= end_n:
                continue
            pages.append(name)
            page_numbers.append(page_no)
        return pages[0], tuple(page_numbers), tuple(pages)

    nom_segments: list[StreamSegment] = []
    qn_segments: list[StreamSegment] = []
    sentences_isolated: list[int] = []
    sentences_skipped: list[int] = []
    order = 0
    for idx, (a, b, _tcount) in enumerate(sentences):
        n_start_cum, n_end_cum = nom_cuts[idx]
        # nom text slice from nom_idx positions.
        n0 = nom_idx[n_start_cum] if n_start_cum < total_nom else len(nom_text)
        n1 = nom_idx[n_end_cum - 1] + 1 if n_end_cum > n_start_cum else n0
        nom_chunk = nom_text[n0:n1].strip()
        qn_chunk = qn_text[a:b].strip()
        p_qn, pns_qn, pimgs_qn = chunk_pages(qn_spans, a, b)
        anchored = (idx not in unanchored_cuts) and ((idx + 1) not in unanchored_cuts)
        anchor_flag = "COSEGMENTED_ANCHORED" if anchored else "COSEGMENTED_UNANCHORED"
        if not nom_chunk or not qn_chunk:
            # Never silently drop a sentence: the empty side is emitted as a
            # whole-sentence gap (UNMATCHED_*), to be resolved by human
            # review. The parity accounting in ``stats`` makes any remaining
            # loss fail-closed in the caller.
            if qn_chunk and not nom_chunk:
                sentences_isolated.append(idx)
                nom_segments.append(
                    StreamSegment(
                        text="",
                        image_names=(),
                        image_name=p_qn,
                        page_numbers=(),
                        page_no=pns_qn[0] if pns_qn else 0,
                        order_no=order,
                        flags=["COSEGMENTED", "COSEGMENTED_UNANCHORED", "UNMATCHED_QN"],
                    )
                )
                qn_segments.append(
                    StreamSegment(
                        text=nfc(qn_chunk),
                        image_names=pimgs_qn,
                        image_name=p_qn,
                        page_numbers=pns_qn,
                        page_no=pns_qn[0] if pns_qn else 0,
                        order_no=order,
                        flags=["COSEGMENTED", "COSEGMENTED_UNANCHORED", "UNMATCHED_QN"],
                    )
                )
                order += 1
                continue
            if nom_chunk and not qn_chunk:
                sentences_isolated.append(idx)
                p_nom, pns_nom, pimgs_nom = nom_chunk_pages(n_start_cum, n_end_cum)
                nom_segments.append(
                    StreamSegment(
                        text=nfc(nom_chunk),
                        image_names=pimgs_nom,
                        image_name=p_nom,
                        page_numbers=pns_nom,
                        page_no=pns_nom[0],
                        order_no=order,
                        flags=["COSEGMENTED", "COSEGMENTED_UNANCHORED", "UNMATCHED_NOM"],
                    )
                )
                qn_segments.append(
                    StreamSegment(
                        text="",
                        image_names=(),
                        image_name=p_nom,
                        page_numbers=(),
                        page_no=pns_nom[0],
                        order_no=order,
                        flags=["COSEGMENTED", "COSEGMENTED_UNANCHORED", "UNMATCHED_NOM"],
                    )
                )
                order += 1
                continue
            # Both sides empty — should not happen (spans are non-empty); count it.
            sentences_skipped.append(idx)
            continue
        p_nom, pns_nom, pimgs_nom = nom_chunk_pages(n_start_cum, n_end_cum)
        flags_nom = ["COSEGMENTED", anchor_flag]
        flags_qn = ["COSEGMENTED", anchor_flag]
        if len(pimgs_nom) > 1:
            flags_nom.append("SPANS_PAGES")
        if len(pimgs_qn) > 1:
            flags_qn.append("SPANS_PAGES")
        nom_segments.append(
            StreamSegment(
                text=nfc(nom_chunk),
                image_names=pimgs_nom,
                image_name=p_nom,
                page_numbers=pns_nom,
                page_no=pns_nom[0],
                order_no=order,
                flags=flags_nom,
            )
        )
        qn_segments.append(
            StreamSegment(
                text=nfc(qn_chunk),
                image_names=pimgs_qn,
                image_name=p_qn,
                page_numbers=pns_qn,
                page_no=pns_qn[0],
                order_no=order,
                flags=flags_qn,
            )
        )
        order += 1

    # Reindex order_no sequentially.
    for i, seg in enumerate(nom_segments):
        seg.order_no = i
    for i, seg in enumerate(qn_segments):
        seg.order_no = i
    if stats is not None:
        qn_tokens_emitted = sum(len(QN_TOKEN_RE.findall(seg.text)) for seg in qn_segments)
        stats.update(
            stream_sentences=len(sentences),
            qn_tokens_stream=total_tok,
            qn_tokens_emitted=qn_tokens_emitted,
            segments_dropped=len(sentences_skipped),
            sentence_coverage=(len(qn_segments) / len(sentences)) if sentences else 1.0,
            sentences_isolated=list(sentences_isolated),
            sentences_skipped=list(sentences_skipped),
        )
    return nom_segments, qn_segments
