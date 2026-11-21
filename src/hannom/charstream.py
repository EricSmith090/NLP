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

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Collection, Sequence

from .charalign import Matcher, Op, QnToken, NomChar, align_streams, fold
from .anchors import gather_readings
from .clean import is_nom_char, nfc
from .cosegment import QN_TOKEN_RE, qn_sentence_spans
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


# A page number in a table of contents: digits not inside a word or "(267)".
TOC_NUMBER_RE = re.compile(r"(?<![\w(])\d{1,4}(?![\w)])")
TOC_MIN_TOKENS = 3  # a shorter TOC piece ("Tựa 1") is part of the line before it


def toc_sentence_spans(
    text: str, spans: Sequence[tuple[int, int, int]], ranges: Sequence[tuple[int, int]]
) -> list[tuple[int, int, int]]:
    """Re-cut QN sentences inside table-of-contents pages (instructor, 2026-11-21).

    One row per entry, the page number with its title ("Ban sớm mai[...]. 206"):
    the QN prints the number after the title ("… mà ra. 58 - Ban chiều hôm …"),
    the Nôm at the foot of the title's column. Inside ``ranges`` (offsets of the
    TOC pages in ``text``):

    - a cut goes right after every page number (a number followed by the end,
      a bullet/dash or a capital: not "đủ 10 ngày", not "(267)");
    - the sentence stop just before a page number is dropped (the number
      belongs to the sentence it follows), and so is a stop after ":" ("Bài
      thứ tám: Phải xưng …" is one title);
    - a piece with fewer than ``TOC_MIN_TOKENS`` words joins the piece before it
      ("Cấm phòng cho bổn đạo đủ 10 ngày. Tựa 1" is one printed line).
    Cuts outside the ranges are untouched.
    """
    if not ranges or not spans:
        return list(spans)

    def in_toc(pos: int) -> bool:
        return any(a <= pos < b for a, b in ranges)

    page_number_ends: set[int] = set()
    for m in TOC_NUMBER_RE.finditer(text):
        if not in_toc(m.start()):
            continue
        rest = text[m.end():].lstrip()
        if not rest or rest[0] in "-–+•✣" or rest[0].isupper() or rest[0].isdigit():
            page_number_ends.add(m.end())

    cuts: set[int] = set()
    for _start, end, _n in spans[:-1]:
        if not in_toc(end - 1):
            cuts.add(end)
            continue
        if text[:end].rstrip().endswith(":"):
            continue
        after = text[end:]
        nxt = TOC_NUMBER_RE.match(text, end + len(after) - len(after.lstrip()))
        if nxt and nxt.end() in page_number_ends:
            continue
        cuts.add(end)
    cuts |= page_number_ends
    # The table of contents starts a row of its own (e.g. after a title page
    # whose last line has no sentence stop).
    for a, _b in ranges:
        before = text[:a].rstrip()
        if before and not in_toc(len(before) - 1):
            cuts.add(a)

    def build(points: list[int]) -> list[tuple[int, int, int]]:
        out = []
        for a, b in zip([0] + points, points + [len(text)]):
            seg = text[a:b].strip()
            if seg:
                real = a + text[a:b].find(seg)
                out.append((real, real + len(seg), len(QN_TOKEN_RE.findall(seg))))
        return out

    out = build(sorted(cuts))
    merged: list[tuple[int, int, int]] = []
    for span in out:
        if merged and span[2] < TOC_MIN_TOKENS and in_toc(span[0]) and in_toc(merged[-1][1] - 1):
            a, _b, n = merged.pop()
            merged.append((a, span[1], n + span[2]))
        else:
            merged.append(span)
    return merged


TOC_NUMERALS = frozenset("〇零一二三四五六七八九十百千廿卄卅")


def keep_numeral_runs_together(nom_chars: Sequence[Any], ops: Sequence[Any], op_sentence: list[int],
                               pages: Collection[str]) -> list[int]:
    """On TOC Nôm pages a page number (二百六十四) is never cut in two.

    A run of consecutive Nôm numerals whose ops fall in different sentences
    goes whole to the earliest one: in a table of contents the number ends
    its entry. Returns the new sentence index per op.
    """
    out = list(op_sentence)
    if not pages:
        return out
    by_i = {op.i: k for k, op in enumerate(ops) if op.i is not None}
    i = 0
    n = len(nom_chars)
    while i < n:
        if nom_chars[i].ch in TOC_NUMERALS and nom_chars[i].page in pages and i in by_i:
            j = i
            while j + 1 < n and nom_chars[j + 1].ch in TOC_NUMERALS and nom_chars[j + 1].page in pages and j + 1 in by_i:
                j += 1
            ks = [by_i[x] for x in range(i, j + 1)]
            first = min(out[k] for k in ks)
            if max(out[k] for k in ks) != first:
                for k in ks:
                    out[k] = first
            i = j + 1
        else:
            i += 1
    return out


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
    toc_qn_pages: Collection[int] = (),
) -> tuple[list[Any], list[Any], list[str]] | None:
    """Align the Nôm and Quốc ngữ reading streams, then cut at QN punctuation.

    Returns ``(nom_segments, qn_segments, warnings)`` with ``TextSegment``
    entries; index i of each list is one aligned sentence pair. Returns None
    when the streams are too small to align. ``toc_qn_pages``: PDF page
    numbers of QN table-of-contents pages, cut by ``toc_sentence_spans``.
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
    if toc_qn_pages:
        toc = {int(p) for p in toc_qn_pages}
        ranges = [(start, end) for name, _no, start, end in qn_spans if _page_number(name) in toc]
        sentences = toc_sentence_spans(qn_text, sentences, ranges)
    if len(sentences) < 2:
        return None

    # Nôm stream: positions of ideographs in reading order.
    nom_positions = nom_ideograph_positions(nom_text)
    if len(nom_positions) < 20:
        return None

    # QN tokens with global offsets (page-joined text shares one coordinate system).
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
    # Nôm-only chars sitting between two sentences go with the FOLLOWING
    # sentence when that sentence opens with an unmatched token: e.g. 阿綿 =
    # "Amen." after "...chẳng cùng." -- 阿 has no partner of its own and
    # belongs to the transliterated word that starts the next sentence
    # (SLQ 067.1, 2026-11-20). Runs longer than 3 chars stay put.
    k = 0
    while k < len(ops):
        if ops[k].j is not None:
            k += 1
            continue
        start = k
        while k < len(ops) and ops[k].j is None:
            k += 1
        if k < len(ops) and start > 0 and k - start <= 3:
            nxt = ops[k]
            # "lex" = a reading learned from this unreviewed stream, not evidence
            if op_sentence[k] > op_sentence[start - 1] and nxt.kind not in {"exact", "fold"}:
                for m in range(start, k):
                    op_sentence[m] = op_sentence[k]
    if toc_qn_pages:
        toc_nom = {name for pair in pairs if any(_page_number(v) in toc for v in pair.vi) for name in pair.ch}
        op_sentence = keep_numeral_runs_together(nom_chars, ops, op_sentence, toc_nom)
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
