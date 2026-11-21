"""Nôm boxes on the page frame, on the spine, or outside the frame (2026-11-21).

The instructor (reply of 2026-11-21): what is printed on the spine or outside
the frame is not page text and is dropped. On the Cấm Phòng scans the Kim Hán
Nôm API reads the frame's ornaments (corner rosettes, the chain border) as
characters — 照, 熙, 嘉, 无, 念, 心 … — the folio printed above the frame
("- 150 -") as 粥, 紅 …, and the spine label as 目籙. In Tap1 such boxes held
239 characters, 230 of them red in text_diff.

No geometric rule separates them from real text completely: a TOC heading
(排次一, 𣈜次𠃩) or the last short column of a chapter (歇女, 亞綿) can sit
outside the block of long columns as well. Hence three steps:

- ``find_candidates`` lists the short boxes lying outside the page's text
  block (the bounding box of its boxes with >= 4 characters);
- a person checks every candidate on the page image and lists the confirmed
  ones in ``configs/frame_boxes/<book>.tsv`` (image, box corners, OCR text);
- ``drop_listed_boxes`` removes exactly those boxes from ch/Label.txt and the
  same characters, by stream position, from the CSV's ch_txt. Label.txt and
  the CSV stay in SYNC by construction; it is checked before and after.
"""

from __future__ import annotations

import copy
import csv
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import AlignmentRow
from .review.edit import EditError, _stream
from .sync_check import norm_nom, page_orders

NUMERALS = frozenset("〇零一二三四五六七八九十百千廿卄卅")
SHORT_MAX = 3  # a candidate has at most this many characters
LONG_MIN = 4  # boxes with at least this many characters define the text block

Labels = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class FrameBox:
    image: str  # image file name (no folder)
    x0: float
    y0: float
    x1: float
    y1: float
    text: str  # OCR text when the box was checked (information only)


def bounds(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return min(xs), max(xs), min(ys), max(ys)


def _numeral(text: str) -> bool:
    return all(c in NUMERALS for c in text)


def find_candidates(boxes: Sequence[Mapping[str, Any]]) -> list[tuple[int, float]]:
    """(box index, gap in pixels) of short boxes outside the page's text block.

    Short: at most ``SHORT_MAX`` characters and not only numerals (page numbers
    of a table of contents stay). Text block: bounding box of the boxes with at
    least ``LONG_MIN`` characters; a page without such boxes has no candidates.
    """
    texts = [str(b.get("transcription", "")) for b in boxes]
    rects = [bounds(b["points"]) for b in boxes]
    longs = [i for i, t in enumerate(texts) if len(t) >= LONG_MIN and not _numeral(t)]
    if not longs:
        return []
    bx0 = min(rects[i][0] for i in longs)
    bx1 = max(rects[i][1] for i in longs)
    by0 = min(rects[i][2] for i in longs)
    by1 = max(rects[i][3] for i in longs)
    out: list[tuple[int, float]] = []
    for i, t in enumerate(texts):
        if len(t) > SHORT_MAX or _numeral(t):
            continue
        x0, x1, y0, y1 = rects[i]
        gap = max(bx0 - x1, x0 - bx1, by0 - y1, y0 - by1)
        if gap > 0:
            out.append((i, gap))
    return out


# --- the checked list ----------------------------------------------------------

FIELDS = ["image", "x0", "y0", "x1", "y1", "text"]


def read_list(path: str | Path) -> list[FrameBox]:
    """Read ``configs/frame_boxes/<book>.tsv``; lines starting with # are comments."""
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    out: list[FrameBox] = []
    for row in csv.DictReader(lines, delimiter="\t"):
        out.append(FrameBox(row["image"], float(row["x0"]), float(row["y0"]), float(row["x1"]), float(row["y1"]),
                            row.get("text", "")))
    return out


def write_list(path: str | Path, entries: Iterable[FrameBox], comment: str = "") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        for line in comment.splitlines():
            f.write(f"# {line}\n".replace("# \n", "#\n"))
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(FIELDS)
        for e in entries:
            w.writerow([e.image, f"{e.x0:g}", f"{e.y0:g}", f"{e.x1:g}", f"{e.y1:g}", e.text])


def entry_for(image: str, box: Mapping[str, Any]) -> FrameBox:
    x0, x1, y0, y1 = bounds(box["points"])
    return FrameBox(image, x0, y0, x1, y1, str(box.get("transcription", "")))


def match_listed(
    labels: Labels, entries: Sequence[FrameBox], tol: float = 2.0
) -> tuple[dict[tuple[str, int], FrameBox], list[FrameBox]]:
    """Find each listed box in Label.txt by image and corners (± ``tol`` px).

    Matching ignores the text, so a box whose characters were edited in the
    review app is still found. Returns ({(label key, box index): entry},
    entries not found). Raises ``EditError`` if an entry matches two boxes.
    """
    by_base = {os.path.basename(k.replace("\\", "/")): k for k in labels}
    found: dict[tuple[str, int], FrameBox] = {}
    missing: list[FrameBox] = []
    for e in entries:
        key = by_base.get(e.image)
        hits = []
        if key is not None:
            for i, box in enumerate(labels[key]):
                x0, x1, y0, y1 = bounds(box["points"])
                if max(abs(x0 - e.x0), abs(y0 - e.y0), abs(x1 - e.x1), abs(y1 - e.y1)) <= tol:
                    hits.append(i)
        if len(hits) > 1:
            raise EditError(f"{e.image}: listed box {e.text!r} at ({e.x0:g}, {e.y0:g}) matches {len(hits)} boxes")
        if hits:
            found[(key, hits[0])] = e
        else:
            missing.append(e)
    return found, missing


def drop_listed_boxes(
    pairs: Sequence[Any], ch_labels: Labels, rows: Sequence[AlignmentRow], drop: Iterable[tuple[str, int]]
) -> tuple[Labels, list[AlignmentRow], dict[int, str]]:
    """Remove boxes from ch/Label.txt and their characters from ch_txt (inputs untouched).

    Characters are removed by their position in the Label.txt/CSV stream, not
    by searching text, so a junk 心 next to a real 心 removes the right one.
    Returns (new labels, new rows, {row index: removed characters}). Raises
    ``EditError`` if the streams are not in SYNC before or after.
    """
    drop = set(drop)
    ch_order, _vi = page_orders(list(pairs))
    stream, origin = _stream(ch_labels, ch_order, norm_nom)
    norms = [norm_nom(r.ch_txt) for r in rows]
    if stream != "".join(norms):
        raise EditError("ch/Label.txt and the CSV are not in SYNC; nothing removed")

    gone = {g for g, (key, b, _raw) in enumerate(origin) if (key, b) in drop}
    new_rows = copy.deepcopy(list(rows))
    removed: dict[int, str] = {}
    start = 0
    for i, row in enumerate(new_rows):
        n = len(norms[i])
        hit = {g - start for g in gone if start <= g < start + n}
        if hit:
            kept, out, k = [], [], 0
            for c in row.ch_txt:
                if norm_nom(c):
                    if k in hit:
                        out.append(c)
                    else:
                        kept.append(c)
                    k += 1
                else:
                    kept.append(c)
            new_rows[i] = replace(row, ch_txt="".join(kept).strip())
            removed[i] = "".join(out)
        start += n

    new_labels = copy.deepcopy(ch_labels)
    for key in {k for k, _ in drop}:
        if key in new_labels:
            for b in sorted((b for k, b in drop if k == key), reverse=True):
                del new_labels[key][b]

    after, _origin = _stream(new_labels, ch_order, norm_nom)
    if after != "".join(norm_nom(r.ch_txt) for r in new_rows):
        raise EditError("removing the boxes left ch/Label.txt and the CSV out of SYNC")
    return new_labels, new_rows, removed
