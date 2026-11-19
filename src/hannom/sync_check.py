"""Label.txt ↔ CSV text SYNC with the official checker's normalisation.

Doc/FIX_PLAN_v24.md T1.4. Mirrors ``ocr_nom_align`` v0.2.0
``validate.check_text_sync``: the transcriptions of Label.txt, concatenated
box by box with pages in image_map reading order (pairs that have a Nôm page;
each image once), must equal ``ch_txt`` / ``vi_txt`` concatenated in CSV row
order. Whitespace is ignored on both sides, and ``-`` on the Quốc ngữ side.
Rows whose image is a lost page (``missing``) are left out of the stream.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def norm_nom(text: str) -> str:
    return "".join(text.split())


def norm_vi(text: str) -> str:
    return "".join(c for c in text if not c.isspace() and c != "-")


def page_orders(pairs: Iterable[Any]) -> tuple[list[str], list[str]]:
    """(ch images, vi images) in reading order; a vi page without Nôm page is not aligned."""
    ch_order: list[str] = []
    vi_order: list[str] = []
    for pair in pairs:
        ch = list(pair.ch if hasattr(pair, "ch") else pair.get("ch", []))
        vi = list(pair.vi if hasattr(pair, "vi") else pair.get("vi", []))
        if vi and not ch:
            continue
        ch_order += [x for x in ch if x not in ch_order]
        vi_order += [x for x in vi if x not in vi_order]
    return ch_order, vi_order


def _labels_by_image(labels: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, list[str]]:
    """Label.txt rows keyed by image basename -> transcriptions in box order."""
    return {
        os.path.basename(path.replace("\\", "/")): [str(b.get("transcription", "")) for b in boxes]
        for path, boxes in labels.items()
    }


def _stream(pages: dict[str, list[str]], order: Sequence[str], norm) -> tuple[str, list[tuple[str, int]]]:
    text: list[str] = []
    origin: list[tuple[str, int]] = []
    for image in order:
        for box, transcription in enumerate(pages.get(image, [])):
            t = norm(transcription)
            text.append(t)
            origin += [(image, box)] * len(t)
    return "".join(text), origin


def _first_diff(parts: list[tuple[int, str]], label: str, origin: list[tuple[str, int]], name: str) -> str | None:
    csv_text = "".join(t for _, t in parts)
    if csv_text == label:
        return None
    k = len(os.path.commonprefix([csv_text, label]))
    rowmap = [n for n, t in parts for _ in t]
    row = rowmap[k] if k < len(rowmap) else (rowmap[-1] if rowmap else 0)
    where = f"{origin[k][0]} box {origin[k][1] + 1}" if k < len(origin) else "the end of Label.txt"
    got = csv_text[k : k + 12] or "(end)"
    want = label[k : k + 12] or "(end)"
    return f"row {row}: SYNC: {name} differs from Label.txt at {where} (char {k}): csv {got!r}, Label.txt {want!r}"


def check_sync(
    rows: Sequence[Mapping[str, str]],
    ch_labels: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    vi_labels: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    pairs: Iterable[Any],
    *,
    missing_ch: frozenset[str] = frozenset(),
    missing_vi: frozenset[str] = frozenset(),
) -> list[str]:
    """Errors (empty list = in sync). ``rows`` need ``img_id``, ``ch_txt``, ``vi_txt``."""
    ch_order, vi_order = page_orders(list(pairs))
    errors: list[str] = []
    for labels, order, norm, col, lost in (
        (ch_labels, ch_order, norm_nom, "ch_txt", missing_ch),
        (vi_labels, vi_order, norm_vi, "vi_txt", missing_vi),
    ):
        if labels is None:
            continue
        pages = _labels_by_image(labels)
        label, origin = _stream(pages, [x for x in order if x not in lost], norm)
        parts = [(n, norm(str(r.get(col, "")))) for n, r in enumerate(rows, 1) if r.get("img_id") not in lost]
        msg = _first_diff(parts, label, origin, col)
        if msg:
            errors.append(msg)
    return errors


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def check_book_dir(label_root: Path, csv_path: Path, pairs: Iterable[Any]) -> list[str]:
    """SYNC for a folder holding ``ch/Label.txt`` and ``vi/Label.txt`` (pipeline data or a packaged book)."""
    from .labels import read_label_txt

    label_root = Path(label_root)
    sides = {}
    for folder in ("ch", "vi"):
        path = label_root / folder / "Label.txt"
        sides[folder] = read_label_txt(path) if path.exists() else None
    missing = {
        folder: frozenset(p.name for p in (label_root / "missing" / folder).glob("*.jpg"))
        if (label_root / "missing" / folder).exists() else frozenset()
        for folder in ("ch", "vi")
    }
    return check_sync(
        read_csv_rows(csv_path), sides["ch"], sides["vi"], pairs,
        missing_ch=missing["ch"], missing_vi=missing["vi"],
    )
