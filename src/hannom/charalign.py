"""Character-level Nôm <-> Quốc ngữ alignment for dịch âm (1-1) books.

In a dịch âm book every Nôm character is read as exactly one Quốc ngữ
syllable, in order. So instead of matching whole sentences, this module
aligns the two *streams* (all Nôm characters of the book in reading order,
all QN syllables in reading order) character by character:

1. clean: drop page numbers, running headers and low-confidence noise boxes
   on the Nôm side; footnote markers "(1)" and page headers on the QN side;
2. align: banded dynamic programming (Needleman-Wunsch) where a pair scores
   high when the QN syllable is one of the character's dictionary readings,
   and gaps absorb characters/syllables that OCR dropped. Page starts from
   the image map act as anchors so the band never drifts;
3. learn: characters missing from the dictionary that repeatedly sit in a
   fully matched context opposite the same syllable become *candidate*
   readings (reported for human confirmation, never silently trusted);
4. segment: sentences are cut at QN punctuation (.?!;:) and projected onto
   the Nôm side through the alignment;
5. text_diff: every non-matching run becomes one element in the v2.1 format
   (half-open code point intervals on NFC text, "error"/"warn").

Nothing is invented: a match always comes from a dictionary reading or a
human-confirmed lexicon entry; everything else is reported for review.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .dictionary.readings import Readings, is_ideograph, norm_reading

QN_TOKEN_RE = re.compile(r"[^\W_]+")
SENTENCE_END = frozenset(".?!;:")
FOOTNOTE_RE = re.compile(r"\s*[\(\[]\s*\d{1,3}\s*[\)\]]")
QN_HEADER_RE = re.compile(r"^\s*-\s*\d+\s*-\s*(?:\(\s*(\d+)\s*\))?")
HYPHEN_BREAK_RE = re.compile(r"(\w)-\s+(\w)")
CN_NUMERALS = frozenset("〇零一二三四五六七八九十百千廿卅")
PAGE_NO_RE = re.compile(r"\.(\d+)(?:_\d+)?\.jpg$", re.IGNORECASE)
_Y_AS_I_RE = re.compile(r"(qu|[bcdghklmnprstvx]{0,3})y")

SCORE = {"exact": 3.0, "fold": 2.0, "lex": 2.0, "unknown": 0.0, "diff": -1.0}
GAP = -2.0
BLACK = frozenset({"exact", "fold", "lex"})


def fold(text: str) -> str:
    """Accent/old-spelling-insensitive form used only as a *weak* match.

    quỷ/quỉ/quĩ -> qui, đ -> d, and the old d/gi alternation (dấu = giấu,
    dối = giối) -> d. The text itself is never changed; this only decides
    whether a syllable may be one of the character's readings.
    """
    decomposed = unicodedata.normalize("NFD", text.casefold())
    out = "".join(c for c in decomposed if unicodedata.category(c) != "Mn").replace("đ", "d")
    if _Y_AS_I_RE.fullmatch(out):
        out = out[:-1] + "i"
    if out.startswith("gi") and len(out) > 2:
        out = "d" + out[2:]
    return out


def page_number(image_name: str) -> int:
    match = PAGE_NO_RE.search(image_name)
    return int(match.group(1)) if match else -1


# --------------------------------------------------------------------------
# Streams
# --------------------------------------------------------------------------


@dataclass
class NomChar:
    ch: str
    page: str
    col: int
    trail: str = ""  # punctuation printed right after the character (。、)


@dataclass
class QnToken:
    text: str
    norm: str
    fold: str
    start: int
    end: int
    page: str


@dataclass
class Dropped:
    page: str
    text: str
    reason: str


def clean_nom_pages(pages: Sequence[tuple[str, list[dict[str, Any]]]], strip_texts: Sequence[str] = ()) -> tuple[list[tuple[str, list[str]]], list[Dropped]]:
    """Remove page numbers, running headers and low-confidence noise boxes.

    A running header (the book title printed in the margin, e.g. 所𥚇卷) is a
    short text that recurs on many pages *and* sits at the page edge (first
    or last box) nearly every time; a short phrase of the body text that
    happens to repeat is kept. ``strip_texts`` names exact transcriptions
    that are known margin boxes for this book and are always dropped.
    """
    strip = {unicodedata.normalize("NFC", t).strip() for t in strip_texts}
    occurrences: Counter[str] = Counter()
    at_edge: Counter[str] = Counter()
    for _, boxes in pages:
        texts = [unicodedata.normalize("NFC", str(b.get("transcription", ""))).strip() for b in boxes]
        for index, text in enumerate(texts):
            if 0 < len(text) <= 6:
                occurrences[text] += 1
                if index in (0, len(texts) - 1):
                    at_edge[text] += 1
    running = {
        t for t, c in at_edge.items()
        if c >= max(3, 0.25 * len(pages)) and c >= 0.8 * occurrences[t]
    }
    out: list[tuple[str, list[str]]] = []
    dropped: list[Dropped] = []
    for image, boxes in pages:
        columns: list[str] = []
        for box in boxes:
            text = unicodedata.normalize("NFC", str(box.get("transcription", ""))).strip()
            confidence = box.get("confidence")
            reason = None
            if not text:
                reason = "empty"
            elif strip and text in strip:
                reason = "running_header"
            elif text in running:
                reason = "running_header"
            elif all(c in CN_NUMERALS for c in text):
                reason = "page_number"
            elif confidence is not None and float(confidence) < 0.5 and len(text) <= 3:
                reason = "low_confidence_noise"
            if reason:
                dropped.append(Dropped(image, text, reason))
            else:
                columns.append(text)
        out.append((image, columns))
    return out, dropped


def build_nom_stream(pages: Sequence[tuple[str, list[str]]]) -> tuple[list[NomChar], dict[str, int]]:
    chars: list[NomChar] = []
    starts: dict[str, int] = {}
    for image, columns in pages:
        starts[image] = len(chars)
        for col_index, column in enumerate(columns):
            for ch in unicodedata.normalize("NFC", column):
                if is_ideograph(ch):
                    chars.append(NomChar(ch, image, col_index))
                elif chars and chars[-1].page == image and not ch.isspace():
                    chars[-1].trail += ch
    return chars, starts


def clean_qn_text(raw: str) -> tuple[str, int | None]:
    """(clean text, Nôm page number printed in the header "( N )" if any)."""
    text = unicodedata.normalize("NFC", raw)
    marker = None
    header = QN_HEADER_RE.match(text)
    if header:
        marker = int(header.group(1)) if header.group(1) else None
        text = text[header.end():]
    text = FOOTNOTE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = HYPHEN_BREAK_RE.sub(r"\1-\2", text)
    return text, marker


def build_qn_stream(pages: Sequence[tuple[str, str]]) -> tuple[str, list[QnToken], dict[str, int], dict[str, int]]:
    parts: list[str] = []
    tokens: list[QnToken] = []
    starts: dict[str, int] = {}
    markers: dict[str, int] = {}
    pos = 0
    for image, raw in pages:
        text, marker = clean_qn_text(raw)
        if marker is not None:
            markers[image] = marker
        if parts and text:
            joiner = "" if parts[-1].endswith("-") else " "
            parts.append(joiner)
            pos += len(joiner)
        starts[image] = len(tokens)
        for match in QN_TOKEN_RE.finditer(text):
            word = match.group(0)
            tokens.append(QnToken(word, norm_reading(word), fold(word), pos + match.start(), pos + match.end(), image))
        parts.append(text)
        pos += len(text)
    return "".join(parts), tokens, starts, markers


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------


@dataclass
class Op:
    kind: str  # exact | fold | lex | unknown | diff (pairs) ; N (Nôm only) ; Q (QN only)
    i: int | None
    j: int | None


class Matcher:
    def __init__(self, readings: Readings, lexicon: dict[str, set[str]] | None = None):
        self.readings = readings
        self.lexicon = lexicon or {}
        self._cache: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str]]] = {}

    def sets(self, ch: str) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
        cached = self._cache.get(ch)
        if cached is None:
            exact = self.readings.of(ch)
            folded = frozenset(fold(r) for r in exact)
            lex = frozenset(self.lexicon.get(ch, ()))
            cached = self._cache[ch] = (exact, folded, lex)
        return cached

    def kind(self, ch: str, token: QnToken) -> str:
        exact, folded, lex = self.sets(ch)
        if token.norm in exact:
            return "exact"
        if token.fold in folded:
            return "fold"
        if token.norm in lex:
            return "lex"
        if not exact and not lex:
            return "unknown"
        return "diff"


def _centers(n: int, m: int, anchors: Iterable[tuple[int, int]]) -> list[int]:
    points = sorted({(0, 0), (n, m), *((i, j) for i, j in anchors if 0 <= i <= n and 0 <= j <= m)})
    mono: list[tuple[int, int]] = []
    for i, j in points:
        if mono and (i == mono[-1][0] or j < mono[-1][1]):
            continue
        mono.append((i, j))
    if mono[-1] != (n, m):
        mono.append((n, m))
    centers = [0] * (n + 1)
    for (i0, j0), (i1, j1) in zip(mono, mono[1:]):
        span = max(1, i1 - i0)
        for i in range(i0, i1 + 1):
            centers[i] = round(j0 + (j1 - j0) * (i - i0) / span)
    return centers


def align_streams(
    nom: Sequence[NomChar],
    qn: Sequence[QnToken],
    matcher: Matcher,
    anchors: Iterable[tuple[int, int]] = (),
    band: int = 60,
) -> list[Op]:
    """Banded global alignment; returns ops in reading order."""
    n, m = len(nom), len(qn)
    centers = _centers(n, m, anchors)
    neg = float("-inf")
    backs: list[tuple[int, bytearray]] = []
    prev: list[float] = []
    prev_lo = prev_hi = 0
    for i in range(n + 1):
        lo = max(0, centers[i] - band)
        hi = min(m, centers[i] + band)
        if i == 0:
            lo = 0
        if i == n:
            hi = m
        width = hi - lo + 1
        cur = [neg] * width
        back = bytearray(width)
        ch = nom[i - 1].ch if i > 0 else ""
        for j in range(lo, hi + 1):
            best = 0.0 if (i == 0 and j == 0) else neg
            move = 0
            if i > 0:
                pj = j - 1
                if prev_lo <= pj <= prev_hi:
                    value = prev[pj - prev_lo]
                    if value > neg:
                        score = value + SCORE[matcher.kind(ch, qn[pj])]
                        if score > best:
                            best, move = score, 1
                if prev_lo <= j <= prev_hi:
                    value = prev[j - prev_lo]
                    if value > neg and value + GAP > best:
                        best, move = value + GAP, 2
            if j > lo:
                value = cur[j - 1 - lo]
                if value > neg and value + GAP > best:
                    best, move = value + GAP, 3
            cur[j - lo] = best
            back[j - lo] = move
        backs.append((lo, back))
        prev, prev_lo, prev_hi = cur, lo, hi
    if prev[m - prev_lo] == neg:
        raise ValueError(f"alignment band too narrow (band={band}); increase it")
    ops: list[Op] = []
    i, j = n, m
    while i > 0 or j > 0:
        lo, back = backs[i]
        move = back[j - lo]
        if move == 1:
            ops.append(Op(matcher.kind(nom[i - 1].ch, qn[j - 1]), i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 2:
            ops.append(Op("N", i - 1, None))
            i -= 1
        elif move == 3:
            ops.append(Op("Q", None, j - 1))
            j -= 1
        else:  # pragma: no cover - unreachable when the end cell is finite
            raise RuntimeError(f"broken traceback at ({i}, {j})")
    ops.reverse()
    return ops


def learn_lexicon(
    ops: Sequence[Op],
    nom: Sequence[NomChar],
    qn: Sequence[QnToken],
    matcher: Matcher,
    min_unknown: int = 2,
    min_known: int | None = None,
) -> tuple[dict[str, set[str]], dict[str, Counter[str]]]:
    """Candidate readings from mismatched pairs sitting between two matches.

    Only characters *absent* from the dictionary (Kim Hán Nôm private-use
    codes, rare characters) become candidates by default: on Sửa Lưỡi Quyển
    the dictionary covers 99.7% of characters, and a known character that
    keeps sitting opposite another syllable was an OCR confusion every time
    we checked (極 read where the page has 拯 "chẳng"). Pass ``min_known`` to
    learn for known characters too.
    """
    evidence: dict[str, Counter[str]] = defaultdict(Counter)
    for k in range(1, len(ops) - 1):
        op = ops[k]
        if op.kind not in ("unknown", "diff"):
            continue
        if ops[k - 1].kind in ("exact", "fold") and ops[k + 1].kind in ("exact", "fold"):
            evidence[nom[op.i].ch][qn[op.j].norm] += 1
    learned: dict[str, set[str]] = {}
    for ch, counter in evidence.items():
        need = min_known if matcher.readings.known(ch) else min_unknown
        if need is None:
            continue
        picked = {syl for syl, c in counter.items() if c >= need}
        if picked:
            learned[ch] = picked
    return learned, evidence


# --------------------------------------------------------------------------
# Sentences and text_diff
# --------------------------------------------------------------------------


@dataclass
class Row:
    img_id: str
    sentence_id: str
    ch_txt: str
    vi_txt: str
    text_diff: list[dict[str, Any]] | None
    ops: list[Op] = field(default_factory=list, repr=False)
    flags: list[str] = field(default_factory=list)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for index, ch in enumerate(text):
        if ch in SENTENCE_END and (index + 1 == len(text) or text[index + 1] == " "):
            spans.append((start, index + 1))
            start = index + 1
    if start < len(text) and text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _merge(intervals: list[tuple[int, int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def _is_name_or_number(tokens: Sequence[QnToken], sentence_initial: bool) -> bool:
    """Yellow is only for proper names / numbers whose syllable count differs."""
    if not tokens:
        return False
    if any(t.text.isdigit() for t in tokens):
        return True
    if sentence_initial and len(tokens) == 1:
        return False  # a capital letter at sentence start is not a name
    for t in tokens:
        if t.text.isdigit():
            continue
        if not t.text[:1].isupper():
            return False
    return True


def build_rows(
    stream_text: str,
    nom: Sequence[NomChar],
    qn: Sequence[QnToken],
    ops: Sequence[Op],
    lexicon_is_confirmed: bool,
) -> list[Row]:
    spans = sentence_spans(stream_text)
    token_sentence: list[int] = []
    s = 0
    for token in qn:
        while s + 1 < len(spans) and token.start >= spans[s][1]:
            s += 1
        token_sentence.append(s)
    # Assign every op to a sentence: pairs/Q by their token, N to the current one.
    op_sentence: list[int] = []
    current = 0
    first_token_sentence = token_sentence[0] if token_sentence else 0
    seen_token = False
    for op in ops:
        if op.j is not None:
            current = token_sentence[op.j]
            seen_token = True
        op_sentence.append(current if seen_token else first_token_sentence)
    by_sentence: dict[int, list[Op]] = defaultdict(list)
    for op, sid in zip(ops, op_sentence):
        by_sentence[sid].append(op)

    rows: list[Row] = []
    counters: Counter[str] = Counter()
    last_img = nom[0].page if nom else ""
    for sid, (a, b) in enumerate(spans):
        sentence_ops = by_sentence.get(sid, [])
        raw = stream_text[a:b]
        lead = len(raw) - len(raw.lstrip())
        vi_txt = raw.strip()
        vi_offset = a + lead
        nom_ops = [op for op in sentence_ops if op.i is not None]
        if not nom_ops:
            rows.append(Row(last_img, "", "", vi_txt, None, sentence_ops, ["QN_ONLY_SENTENCE"]))
            continue
        img = nom[nom_ops[0].i].page
        last_img = img
        ch_parts: list[str] = []
        nom_pos: dict[int, int] = {}
        cursor = 0
        for op in nom_ops:
            nom_pos[op.i] = cursor
            piece = nom[op.i].ch + nom[op.i].trail
            ch_parts.append(piece)
            cursor += len(piece)
        ch_txt = "".join(ch_parts)
        diff: list[dict[str, Any]] = []
        run: list[Op] = []

        def flush() -> None:
            if not run:
                return
            nom_iv = [(nom_pos[o.i], nom_pos[o.i] + 1) for o in run if o.i is not None]
            toks = [qn[o.j] for o in run if o.j is not None]
            vi_iv = [(toks[0].start - vi_offset, toks[-1].end - vi_offset)] if toks else []
            n_count = len(nom_iv)
            kind = "error"
            if (
                toks
                and n_count
                and n_count != len(toks)
                and _is_name_or_number(toks, sentence_initial=toks[0].start == vi_offset)
            ):
                kind = "warn"
            nom_ranges = _merge(nom_iv)
            vi_ranges = _merge(vi_iv)
            diff.append(
                {
                    "nom_pos": nom_ranges,
                    "nom_sub_text": "".join(ch_txt[s:e] for s, e in nom_ranges),
                    "vi_pos": vi_ranges,
                    "vi_sub_text": "".join(vi_txt[s:e] for s, e in vi_ranges),
                    "type": kind,
                }
            )
            run.clear()

        for op in sentence_ops:
            black = op.kind in ("exact", "fold") or (op.kind == "lex" and lexicon_is_confirmed)
            if black:
                flush()
            else:
                run.append(op)
        flush()
        counters[img] += 1
        rows.append(Row(img, f"{Path(img).stem}.{counters[img]}", ch_txt, vi_txt, diff, sentence_ops))
    # QN-only sentences take the next free id on the page of the previous row.
    for row in rows:
        if not row.sentence_id:
            counters[row.img_id] += 1
            row.sentence_id = f"{Path(row.img_id).stem}.{counters[row.img_id]}"
    return rows


# --------------------------------------------------------------------------
# Scoring and validation (Quy định v2.1, "Đánh giá dữ liệu")
# --------------------------------------------------------------------------


def _syllables(text: str) -> int:
    return len(QN_TOKEN_RE.findall(text))


def _nom_count(text: str) -> int:
    return sum(1 for ch in text if is_ideograph(ch))


def similarity(rows: Iterable[Row]) -> dict[str, float]:
    denominator = 0
    numerator = 0
    yellow = 0
    total_rows = 0
    null_rows = 0
    for row in rows:
        total_rows += 1
        if row.text_diff is None:
            null_rows += 1
            continue
        nom_chars = _nom_count(row.ch_txt)
        warn_chars = sum(_nom_count(e["nom_sub_text"]) for e in row.text_diff if e["type"] == "warn")
        yellow += warn_chars
        denominator += nom_chars - warn_chars
        for element in row.text_diff:
            if element["type"] == "error":
                numerator += max(_nom_count(element["nom_sub_text"]), _syllables(element["vi_sub_text"]))
    score = 100.0 * (1 - numerator / denominator) if denominator else 0.0
    return {
        "similarity_percent": round(score, 2),
        "red_count": numerator,
        "scored_nom_chars": denominator,
        "yellow_nom_chars": yellow,
        "rows": total_rows,
        "null_rows": null_rows,
    }


def _is_letter(ch: str) -> bool:
    """A 'chữ' for the v2.1 rule: letters/digits, any ideograph, PUA code or 〓."""
    return ch.isalnum() or is_ideograph(ch)


def validate_text_diff(row: Row) -> list[str]:
    """The v2.1 self-check: sub texts equal the sliced cell, no overlaps, letter ends."""
    problems: list[str] = []
    if row.text_diff is None:
        return problems
    for side, text_key, cell in (("nom_pos", "nom_sub_text", row.ch_txt), ("vi_pos", "vi_sub_text", row.vi_txt)):
        covered: list[tuple[int, int]] = []
        for element in row.text_diff:
            ranges = element[side]
            sliced = "".join(cell[s:e] for s, e in ranges)
            if sliced != element[text_key]:
                problems.append(f"{row.sentence_id}: {text_key} != slice")
            for s, e in ranges:
                if not (0 <= s < e <= len(cell)):
                    problems.append(f"{row.sentence_id}: bad range {s},{e}")
                    continue
                if not (_is_letter(cell[s]) and _is_letter(cell[e - 1])):
                    problems.append(f"{row.sentence_id}: range {s},{e} does not start/end on a letter")
                covered.append((s, e))
        covered.sort()
        for (s1, e1), (s2, e2) in zip(covered, covered[1:]):
            if s2 < e1:
                problems.append(f"{row.sentence_id}: overlapping {side}")
    for element in row.text_diff:
        if not element["nom_pos"] and not element["vi_pos"]:
            problems.append(f"{row.sentence_id}: both sides empty")
    return problems


# --------------------------------------------------------------------------
# Book driver and I/O
# --------------------------------------------------------------------------


def read_label_txt(path: Path) -> list[tuple[str, list[dict[str, Any]]]]:
    pages: list[tuple[str, list[dict[str, Any]]]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        name, _, payload = line.partition("\t")
        pages.append((Path(name).name, json.loads(payload) if payload.strip() else []))
    return pages


def read_image_map(path: Path | None) -> list[tuple[list[str], list[str]]]:
    if path is None or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(list(p.get("ch", [])), list(p.get("vi", []))) for p in data.get("pairs", [])]


@dataclass
class BookResult:
    rows: list[Row]
    stats: dict[str, Any]
    review: list[dict[str, Any]]
    qn_spelling: list[dict[str, Any]]
    lexicon_candidates: list[dict[str, Any]]
    dropped: list[Dropped]


def align_book(
    nom_pages: Sequence[tuple[str, list[dict[str, Any]]]],
    qn_pages: Sequence[tuple[str, str]],
    readings: Readings,
    pairs: Sequence[tuple[list[str], list[str]]] = (),
    confirmed_lexicon: dict[str, set[str]] | None = None,
    band: int = 400,
    layout: str = "T1",
    strip_texts: Sequence[str] = (),
) -> BookResult:
    reverse_nom = layout.upper().startswith("T1")
    nom_pages = sorted(nom_pages, key=lambda p: page_number(p[0]), reverse=reverse_nom)
    qn_pages = sorted(qn_pages, key=lambda p: page_number(p[0]))
    cleaned, dropped = clean_nom_pages(nom_pages, strip_texts)
    nom, nom_starts = build_nom_stream(cleaned)
    stream_text, qn, qn_starts, markers = build_qn_stream(qn_pages)
    anchors = []
    for ch_pages, vi_pages in pairs:
        if ch_pages and vi_pages and ch_pages[0] in nom_starts and vi_pages[0] in qn_starts:
            anchors.append((nom_starts[ch_pages[0]], qn_starts[vi_pages[0]]))

    confirmed = {c: set(v) for c, v in (confirmed_lexicon or {}).items()}
    matcher = Matcher(readings, confirmed)
    ops = align_streams(nom, qn, matcher, anchors, band)
    learned, evidence = learn_lexicon(ops, nom, qn, matcher)
    # Second pass: candidate readings help the *alignment* (better sync),
    # but they stay "lex" (not black) unless a human confirmed them.
    combined = {c: set(v) for c, v in confirmed.items()}
    for c, v in learned.items():
        combined.setdefault(c, set()).update(v)
    matcher2 = Matcher(readings, combined)
    ops = align_streams(nom, qn, matcher2, anchors, band)
    for op in ops:
        if op.kind == "lex" and qn[op.j].norm in confirmed.get(nom[op.i].ch, set()):
            op.kind = "exact"  # human-confirmed reading counts as a dictionary match
    rows = build_rows(stream_text, nom, qn, ops, lexicon_is_confirmed=False)

    # For OCR-confusion hints: characters of *this book* that can be read as
    # a given syllable, most frequent first (極 opposite "chẳng" -> 拯?).
    book_freq = Counter(c.ch for c in nom)
    by_syllable: dict[str, list[str]] = defaultdict(list)
    for ch, _count in book_freq.most_common():
        for reading in readings.of(ch) | combined.get(ch, set()):
            by_syllable[reading].append(ch)

    def suggest(element: dict[str, Any]) -> str:
        chars = [c for c in element["nom_sub_text"] if is_ideograph(c)]
        sylls = [norm_reading(t) for t in QN_TOKEN_RE.findall(element["vi_sub_text"])]
        if not chars or len(chars) != len(sylls):
            return ""
        hints = []
        for ch, syl in zip(chars, sylls):
            options = [c for c in by_syllable.get(syl, []) if c != ch][:3]
            if options:
                hints.append(f"{ch}→{'/'.join(options)}? ({syl})")
        return "; ".join(hints)

    review: list[dict[str, Any]] = []
    qn_spelling: list[dict[str, Any]] = []
    for row in rows:
        for op in row.ops:
            if op.kind == "fold":
                token = qn[op.j]
                qn_spelling.append(
                    {
                        "img_id": row.img_id,
                        "sentence_id": row.sentence_id,
                        "nom": nom[op.i].ch,
                        "qn_ocr": token.text,
                        "dictionary": " ".join(sorted(readings.of(nom[op.i].ch))),
                        "qn_page": token.page,
                    }
                )
        if row.text_diff is None:
            review.append({"img_id": row.img_id, "sentence_id": row.sentence_id, "kind": "QN_ONLY_SENTENCE",
                           "nom": "", "qn": row.vi_txt, "where": "", "suggest": "", "dictionary": "",
                           "ch_txt": "", "vi_txt": row.vi_txt})
            continue
        for element in row.text_diff:
            where = sorted({f"{Path(nom[o.i].page).stem} col{nom[o.i].col + 1}" for o in row.ops if o.i is not None
                            and nom[o.i].ch in element["nom_sub_text"]})
            review.append(
                {
                    "img_id": row.img_id,
                    "sentence_id": row.sentence_id,
                    "kind": _element_kind(element, row, nom, qn),
                    "nom": element["nom_sub_text"],
                    "qn": element["vi_sub_text"],
                    "where": "; ".join(where[:3]),
                    "suggest": suggest(element),
                    "dictionary": " | ".join(
                        f"{c}:{'/'.join(sorted(readings.of(c))[:6]) or '-'}" for c in element["nom_sub_text"]
                    ),
                    "ch_txt": row.ch_txt,
                    "vi_txt": row.vi_txt,
                }
            )

    lexicon_candidates = [
        {
            "char": ch,
            "candidate": "/".join(sorted(learned.get(ch, set()))),
            "evidence": "; ".join(f"{syl}×{cnt}" for syl, cnt in counter.most_common(5)),
            "in_dictionary": "/".join(sorted(readings.of(ch))[:8]) or "-",
            "codepoint": f"U+{ord(ch):04X}",
        }
        for ch, counter in sorted(evidence.items(), key=lambda kv: -sum(kv[1].values()))
    ]

    kinds = Counter(op.kind for op in ops)
    stats = {
        "nom_chars": len(nom),
        "qn_syllables": len(qn),
        "pairs": {k: kinds.get(k, 0) for k in ("exact", "fold", "lex", "unknown", "diff")},
        "nom_only": kinds.get("N", 0),
        "qn_only": kinds.get("Q", 0),
        "dictionary_coverage": round(sum(1 for c in nom if readings.known(c.ch)) / max(1, len(nom)), 4),
        "learned_candidates": len(learned),
        "dropped_nom_boxes": Counter(d.reason for d in dropped),
        "qn_page_markers": markers,
        "anchors": len(anchors),
        "score_now": similarity(rows),
    }
    # What the score would be if every learned candidate were confirmed.
    optimistic = build_rows(stream_text, nom, qn, ops, lexicon_is_confirmed=True)
    stats["score_if_candidates_confirmed"] = similarity(optimistic)
    problems = [p for row in rows for p in validate_text_diff(row)]
    stats["text_diff_problems"] = problems[:50]
    stats["text_diff_problem_count"] = len(problems)
    return BookResult(rows, stats, review, qn_spelling, lexicon_candidates, dropped)


def _element_kind(element: dict[str, Any], row: Row, nom: Sequence[NomChar], qn: Sequence[QnToken]) -> str:
    if not element["vi_pos"]:
        return "nom_extra"
    if not element["nom_pos"]:
        return "qn_extra"
    if element["type"] == "warn":
        return "name_or_number"
    return "mismatch"


def write_outputs(result: BookResult, out_dir: Path, book_name: str) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    csv_path = out_dir / f"{book_name}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"])
        for row in result.rows:
            diff = "null" if row.text_diff is None else json.dumps(row.text_diff, ensure_ascii=False, separators=(",", ":"))
            writer.writerow([row.img_id, row.sentence_id, row.ch_txt, row.vi_txt, diff])
    paths["csv"] = csv_path
    for name, records in (
        ("review", result.review),
        ("qn_spelling_review", result.qn_spelling),
        ("lexicon_candidates", result.lexicon_candidates),
    ):
        path = out_dir / f"{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            if records:
                writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
                writer.writeheader()
                writer.writerows(records)
            else:
                handle.write("")
        paths[name] = path
    dropped_path = out_dir / "dropped_nom_boxes.csv"
    with dropped_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["page", "text", "reason"])
        for d in result.dropped:
            writer.writerow([d.page, d.text, d.reason])
    paths["dropped"] = dropped_path
    stats_path = out_dir / "stats.json"
    stats_path.write_text(json.dumps(result.stats, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    paths["stats"] = stats_path
    return paths
