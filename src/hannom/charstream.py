"""Charalign-projected sentence segmentation for dịch-âm (phonetic 1-1) books.

QN carries real sentence punctuation; the Nôm side does not. Instead of
splitting the two streams independently, this module aligns the two reading
streams globally (banded Needleman–Wunsch with page-start anchors, the same
alignment ``hannom.charalign`` uses) and then **projects QN sentence cut
points back onto the Nôm stream** through the alignment.

Cut points are therefore evidence-derived, not guessed: a cut lands right
after the last Nôm character that matched a Quốc ngữ syllable before the
sentence-final punctuation. Segments carry ``COSEGMENTED_STREAM_ALIGNED`` and
are produced in matching order (index i ↔ index i), one segment per QN
sentence. A QN sentence whose alignment had no Nôm ops at all yields an empty
Nôm segment and is flagged ``UNMATCHED_QN`` by the aligner.

This module is a *segmentation provider*: it only decides where rows are cut.
``text_diff``, flags, review sidecar and evaluation all remain in
``hannom.textdiff``/``hannom.evaluate``.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Sequence

from .charalign import Matcher, Op, QnToken, NomChar, align_streams, fold
from .anchors import gather_readings
from .clean import is_nom_char, nfc
from .cosegment import qn_sentence_spans
from .dictionary.readings import norm_reading


@dataclass
class PageImage:
    image_name: str
    page_no: int
    text: str


def _page_number(image_name: str) -> int:
    try:
        return int(image_name.split(".")[-2])
    except (ValueError, IndexError):
        return 0


def _concat(pages: Sequence[PageImage], separator: str) -> tuple[str, list[tuple[str, int, int, int]]]:
    """Concatenate pages in reading order; return (text, page spans)."""
    parts: list[str] = []
    spans: list[tuple[str, int, int, int]] = []
    cursor = 0
    for page in pages:
        text = page.text
        if not text:
            continue
        if parts:
            parts.append(separator)
            cursor += len(separator)
        start = cursor
        parts.append(text)
        cursor += len(text)
        spans.append((page.image_name, page.page_no, start, cursor))
    return "".join(parts), spans


class _EntryReadingsAdapter:
    """Adapts (lexicon, dictionary[, readings_cache]) to the ``Matcher`` readings interface."""

    def __init__(self, lexicon: Any | None, dictionary: Any | None, readings_cache: Any | None = None):
        self.lexicon = lexicon
        self.dictionary = dictionary
        self.readings_cache = readings_cache
        self._cache: dict[str, frozenset[str]] = {}

    def of(self, ch: str) -> frozenset[str]:
        cached = self._cache.get(ch)
        if cached is None:
            readings, _source = gather_readings(
                ch, lexicon=self.lexicon, dictionary=self.dictionary, readings=self.readings_cache
            )
            cached = frozenset(norm_reading(r) for r in readings)
            self._cache[ch] = cached
        return cached

    def known(self, ch: str) -> bool:
        return bool(self.of(ch))

    def __len__(self) -> int:
        return len(self._cache)


def nom_ideograph_positions(text: str) -> list[int]:
    """Global offsets of ideographs (incl. Kim Hán Nôm PUA + 〓) in the Nôm stream."""
    out: list[int] = []
    for i, ch in enumerate(text):
        if is_nom_char(ch) or "\U000f0000" <= ch <= "\U0010fffd" or "\ue000" <= ch <= "\uf8ff" or ch == "〓":
            out.append(i)
    return out


def stream_segments_by_charalign(
    pairs: Sequence[Any],
    cleaned_by_name: dict[str, Any],
    *,
    lexicon: Any | None = None,
    dictionary: Any | None = None,
    readings_cache: Any | None = None,
    strip_texts: Sequence[str] = (),
    band: int = 400,
) -> tuple[list[Any], list[Any], list[str]] | None:
    """Align the Nôm and Quốc ngữ reading streams, then cut at QN punctuation.

    Returns ``(nom_segments, qn_segments, warnings)`` with ``TextSegment``
    entries; index i of each list is one aligned sentence pair. Returns None
    when the streams are too small to align.
    """
    from hannom.align import TextSegment  # lazy import to avoid a module cycle

    ch_pages: list[PageImage] = []
    vi_pages: list[PageImage] = []
    strips = {unicodedata.normalize("NFC", t).strip() for t in strip_texts if t}

    def cleaned_text(page: Any) -> str:
        text = nfc(str(getattr(page, "text", "") or ""))
        if strips:
            lines = [l for l in text.splitlines() if unicodedata.normalize("NFC", l).strip() not in strips]
            text = "\n".join(lines)
        return text

    missing_pages: list[str] = []
    for pair in pairs:
        for name in pair.ch:
            page = cleaned_by_name.get(name)
            if page is None:
                missing_pages.append(name)
                continue
            ch_pages.append(PageImage(name, _page_number(name), cleaned_text(page)))
        for name in pair.vi:
            page = cleaned_by_name.get(name)
            if page is None:
                missing_pages.append(name)
                continue
            vi_pages.append(PageImage(name, _page_number(name), cleaned_text(page)))

    nom_text, nom_spans = _concat(ch_pages, separator="")
    qn_text, qn_spans = _concat(vi_pages, separator=" ")
    if not nom_text.strip() or not qn_text.strip():
        return None

    # QN sentence spans from the shared sentence splitter (hannom.cosegment.qn_sentence_spans).
    sentences = qn_sentence_spans(qn_text)
    if len(sentences) < 2:
        return None

    # Nôm stream: positions of ideographs in reading order.
    nom_positions = nom_ideograph_positions(nom_text)
    if len(nom_positions) < 20:
        return None

    # QN tokens with global offsets (page-joined text shares one coordinate system).
    import re
    token_re = re.compile(r"[^\W_]+", re.UNICODE)
    qn_tokens = [
        QnToken(match.group(0), norm_reading(match.group(0)), fold(match.group(0)), match.start(), match.end(), "")
        for match in token_re.finditer(qn_text)
    ]
    for token in qn_tokens:  # fill page names
        for name, _page_no, start, end in qn_spans:
            if start <= token.start < end:
                token.page = name
                break

    # Page-start anchors (one per image-map pair), like the diagnostic CLI.
    page_first_index: dict[str, int] = {}
    for index, pos in enumerate(nom_positions):
        for name, _page_no, start, end in nom_spans:
            if start <= pos < end and name not in page_first_index:
                page_first_index[name] = index
                break
    qn_starts: dict[str, int] = {}
    for index, token in enumerate(qn_tokens):
        qn_starts.setdefault(token.page, index)

    # Confirmed lexicon entries (human-verified readings only).
    confirmed: dict[str, set[str]] = {}
    if lexicon is not None and hasattr(lexicon, "readings"):
        seen: set[str] = set()
        for pos in nom_positions:
            ch = nom_text[pos]
            if ch in seen:
                continue
            seen.add(ch)
            readings = lexicon.readings(ch)
            if readings:
                confirmed[ch] = {norm_reading(str(r)) for r in readings}

    adapter = _EntryReadingsAdapter(lexicon, dictionary, readings_cache)
    matcher = Matcher(adapter, {c: set(v) for c, v in confirmed.items()})
    nom_chars = [NomChar(nom_text[pos], "", 0) for pos in nom_positions]
    # Fill page attribution for review rendering.
    for index, ch in enumerate(nom_chars):
        pos = nom_positions[index]
        for name, _page_no, start, end in nom_spans:
            if start <= pos < end:
                ch.page = name
                break

    anchors = []
    for pair in pairs:
        ch_first = pair.ch[0] if pair.ch else None
        vi_first = pair.vi[0] if pair.vi else None
        if ch_first and vi_first and ch_first in page_first_index and vi_first in qn_starts:
            anchors.append((page_first_index[ch_first], qn_starts[vi_first]))

    ops = align_streams(nom_chars, qn_tokens, matcher, anchors, band)

    from .charalign import learn_lexicon
    learned, _evidence = learn_lexicon(ops, nom_chars, qn_tokens, matcher, min_unknown=2)
    combined = {c: set(v) for c, v in confirmed.items()}
    for ch, readings in learned.items():
        combined.setdefault(ch, set()).update(readings)
    matcher2 = Matcher(adapter, combined)
    ops = align_streams(nom_chars, qn_tokens, matcher2, anchors, band)

    # Assign every op to a sentence (QN punctuation cuts).
    token_sentence: list[int] = []
    s = 0
    for token in qn_tokens:
        while s + 1 < len(sentences) and token.start >= sentences[s][1]:
            s += 1
        token_sentence.append(s)
    op_sentence: list[int] = []
    current = 0
    first_token_sentence = token_sentence[0] if token_sentence else 0
    seen_token = False
    for op in ops:
        if op.j is not None:
            current = token_sentence[op.j]
            seen_token = True
        op_sentence.append(current if seen_token else first_token_sentence)
    by_sentence: dict[int, list[Op]] = {}
    for op, sidx in zip(ops, op_sentence):
        by_sentence.setdefault(sidx, []).append(op)

    def pages_for_range(spans_list, start_i, end_i):
        return [name for name, _no, s0, e0 in spans_list
                if not (e0 <= start_i or s0 >= end_i) and (e0 != s0)]

    nom_segments: list[Any] = []
    qn_segments: list[Any] = []
    warnings: list[str] = [f"MISSING_CLEAN_PAGE:{name}" for name in missing_pages]
    order = 0
    for sidx, (a, b, _tok) in enumerate(sentences):
        sentence_ops = by_sentence.get(sidx, [])
        vi_chunk = nfc(qn_text[a:b].strip())
        vi_page_names = pages_for_range(qn_spans, a, b)
        vi_page_numbers = [_page_number(n) for n in vi_page_names]
        vi_image = vi_page_names[0] if vi_page_names else ""

        # Nôm chars of this sentence, in reading order.
        sel = [op.i for op in sentence_ops if op.i is not None]
        if not sel:
            nom_chunk = ""
            seg_pages = []
            seg_page_numbers = []
            ch_image = vi_image
        else:
            uniq_pages = []
            for pos_index in sel:
                page = nom_chars[pos_index].page
                if page not in uniq_pages:
                    uniq_pages.append(page)
            seg_pages = uniq_pages
            seg_page_numbers = [_page_number(n) for n in uniq_pages]
            ch_image = uniq_pages[0]
            start_pos = nom_positions[sel[0]]
            end_pos = nom_positions[sel[-1]] + 1
            nom_chunk = nfc(nom_text[start_pos:end_pos].strip())

        nom_flags = ["COSEGMENTED", "COSEGMENTED_STREAM_ALIGNED"] + (["SPANS_PAGES"] if len(seg_pages) > 1 else [])
        qn_flags = ["COSEGMENTED", "COSEGMENTED_STREAM_ALIGNED"] + (["SPANS_PAGES"] if len(vi_page_names) > 1 else [])
        if not nom_chunk:
            warnings.append(f"QN_SENTENCE_NO_NOM:{sidx}")

        nom_segments.append(
            TextSegment(
                text=nom_chunk,
                image_name=ch_image,
                page_no=_page_number(ch_image) if ch_image else 0,
                page_numbers=tuple(seg_page_numbers),
                image_names=tuple(seg_pages),
                script="nom",
                order=order,
                flags=nom_flags + (["UNMATCHED_QN"] if not nom_chunk else []),
            )
        )
        qn_segments.append(
            TextSegment(
                text=vi_chunk,
                image_name=vi_page_names[0] if vi_page_names else "",
                page_no=vi_page_numbers[0] if vi_page_numbers else 0,
                page_numbers=tuple(vi_page_numbers),
                image_names=tuple(vi_page_names),
                script="qn",
                order=order,
                flags=qn_flags + (["UNMATCHED_QN"] if not nom_chunk else []),
            )
        )
        order += 1
    return nom_segments, qn_segments, warnings
