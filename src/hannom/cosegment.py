"""Co-segmentation of Nôm ↔ Quốc ngữ for phonetic (dịch âm) 1-1 books.

T1 books are sentence-aligned 1-1 at the reading level. The Quốc ngữ text
carries real sentence punctuation; the Nôm side does not (hoặc rarely does).

Two modes:

- ``cosegment_pair`` — pair-wise splitting, used as a fallback when the
  global stream mode cannot be applied.
- ``stream_cosegment`` — the primary mode: build one reading stream per
  script, split the QN stream at sentence punctuation and assign the same
  cut points to the Nôm stream. Cuts are derived from reliable local
  reading anchors (see ``hannom.anchors``) when anchor evidence exists,
  interpolated between sufficiently close anchors, and fall back to
  proportional shares only when no anchor evidence brackets a boundary;
  fallback segments carry ``COSEGMENTED_UNANCHORED`` and are never trusted
  as verified evidence. Chunks spanning a page boundary are attributed to
  every page they cover and carry SPANS_PAGES.
  The result is a list of ``Segment`` covering every page exactly once, in
  reading order, with the same boundaries on both scripts.
"""

from __future__ import annotations

import re
from typing import Any

from .anchors import MAX_ANCHOR_GAP_TOKENS, find_reading_anchors, gather_readings, token_items
from .clean import is_nom_char, nfc

QN_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
SENTENCE_STOP_RE = re.compile(r"[.!?;:]")
SENTENCE_UPPER_RE = re.compile(r"[A-ZÀ-Ỹ0-9\"“(\[]")


def qn_sentence_spans(text: str) -> list[tuple[int, int, int]]:
    """Return (char_start, char_end, token_count) per sentence."""
    stops: list[int] = []
    for m in SENTENCE_STOP_RE.finditer(text):
        end = m.end()
        rest = text[end:].lstrip()
        if not rest or SENTENCE_UPPER_RE.match(rest):
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


def cosegment_pair(
    nom_text: str,
    vi_text: str,
) -> list[tuple[str, str]] | None:
    """Pair Nôm and QN text of the same image-map pair.

    Returns a list of (nom_chunk, vi_chunk) in reading order, or None when
    co-segmentation cannot be applied (too little material, no QN
    sentence boundaries, or wildly mismatched lengths).
    """
    nom_idx = [i for i, c in enumerate(nom_text) if is_nom_char(c)]
    if len(nom_idx) < 8:
        return None
    spans = qn_sentence_spans(vi_text)
    if len(spans) < 2:
        return None

    total_tok = sum(t for _, _, t in spans)
    if total_tok == 0:
        return None
    total_nom = len(nom_idx)

    out: list[tuple[int, int, int, int]] = []
    tok_acc = 0
    for a, b, tcount in spans:
        tok_acc += tcount
        # The translation expands 1 Nôm char into ~1 QN syllable on average;
        # assign the proportional share of Nôm characters to this sentence.
        end_char = round(total_nom * tok_acc / total_tok)
        out.append((a, b, end_char, tcount))

    # Convert cumulative indices into (nom_slice, vi_slice)
    result: list[tuple[str, str]] = []
    prev_nom = 0
    for a, b, end_char, _t in out:
        end_char = max(prev_nom, min(total_nom, end_char))
        # nom slice keeps the raw text span between nom_idx positions
        n0 = nom_idx[prev_nom] if prev_nom < len(nom_idx) else len(nom_text)
        n1 = nom_idx[end_char - 1] + 1 if end_char > prev_nom else n0
        nom_part = nom_text[n0:n1].strip()
        vi_part = vi_text[a:b].strip()
        if nom_part and vi_part:
            result.append((nfc(nom_part), nfc(vi_part)))
        prev_nom = end_char

    # Attach any leftover Nôm chars to the last chunk (never drop content).
    if prev_nom < total_nom and result:
        n0 = nom_idx[prev_nom]
        nom_part, vi_part = result[-1]
        merged = nom_text[n0:].strip()
        if merged:
            result[-1] = (nfc(nom_part + merged), vi_part)

    if len(result) < 2:
        return None
    return result


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
    window: int,
    max_gap_tokens: int,
) -> tuple[list[tuple[int, int]], set[int]]:
    """Return (per-sentence CJK cuts, boundary indices without anchor evidence).

    Each boundary is estimated from the bracketing reliable anchors inside a
    ±``window`` neighborhood of the proportional estimate. When a boundary is
    not bracketed by at least one anchor on each side, it falls back to the
    proportional cut and its index is added to the unanchored set.
    """
    toks_at = [token[0] for token in qn_tokens]
    boundaries: list[int | None] = [0]  # one cut per sentence boundary (0..len(sentences))
    unanchored: set[int] = set()
    for boundary in range(1, len(sentences)):
        est = round(sentence_token_ranges[boundary][0] * total_nom / total_tok)
        lo = max(0, est - window)
        hi = min(total_nom, est + window)
        tok_mid = sentence_token_ranges[boundary][0]
        k_lo = max(0, tok_mid - window)
        k_hi = min(len(qn_tokens), tok_mid + window)
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
    # Keep cuts monotone, clamped to the Nôm stream.
    cuts: list[tuple[int, int]] = []
    prev_end = 0
    for index in range(len(sentences)):
        start_cut = boundaries[index]
        end_cut = boundaries[index + 1]
        start_cut = max(prev_end, min(total_nom, start_cut))
        end_cut = max(start_cut, min(total_nom, end_cut))
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
    max_anchor_gap_tokens: int = MAX_ANCHOR_GAP_TOKENS,
    anchor_window: int = 20,
) -> tuple[list[StreamSegment], list[StreamSegment]] | None:
    """Segment the reading stream of both scripts at QN sentence boundaries.

    Returns two lists (nom_segments, qn_segments) of the same length and
    order. Each segment carries page attribution and one of
    ``COSEGMENTED_ANCHORED`` (both boundary cuts were derived from reliable
    reading anchors) or ``COSEGMENTED_UNANCHORED`` (proportional-fallback
    segmentation; never trusted as verified evidence or scoring). Returns
    None when the stream is too small to split.
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
        readings, _source = gather_readings(nom_text[index], lexicon=lexicon, dictionary=dictionary)
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
    order = 0
    for idx, (a, b, _tcount) in enumerate(sentences):
        n_start_cum, n_end_cum = nom_cuts[idx]
        # nom text slice from nom_idx positions.
        n0 = nom_idx[n_start_cum] if n_start_cum < total_nom else len(nom_text)
        n1 = nom_idx[n_end_cum - 1] + 1 if n_end_cum > n_start_cum else n0
        nom_chunk = nom_text[n0:n1].strip()
        qn_chunk = qn_text[a:b].strip()
        if not nom_chunk or not qn_chunk:
            continue
        p_nom, pns_nom, pimgs_nom = nom_chunk_pages(n_start_cum, n_end_cum)
        p_qn, pns_qn, pimgs_qn = chunk_pages(qn_spans, a, b)
        anchored = (idx not in unanchored_cuts) and ((idx + 1) not in unanchored_cuts)
        anchor_flag = "COSEGMENTED_ANCHORED" if anchored else "COSEGMENTED_UNANCHORED"
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

    # Reindex order_no sequentially (some sentences yield no chunk).
    for i, seg in enumerate(nom_segments):
        seg.order_no = i
    for i, seg in enumerate(qn_segments):
        seg.order_no = i
    return nom_segments, qn_segments
