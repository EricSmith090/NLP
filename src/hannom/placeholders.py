"""Where each 〓 in the CSV came from (Quy định v2.4: list every 〓 with its
position and a description of the glyph in the report).

The clean stage records, per Nôm page, the original code point of each 〓 it
writes (``CleanedPage.placeholder_origins``; a Kim Hán Nôm private-use code
such as ``U+F047C``, or ``U+3013`` when the OCR itself returned 〓). Because
Label.txt and the CSV are in SYNC, the k-th 〓 of the Nôm stream (pages in
image-map reading order) is the k-th 〓 of the CSV ``ch_txt`` in row order.
If the counts disagree (e.g. a reviewer added or removed a 〓), the
assignment stops being trusted: every 〓 is reported with code ``unknown``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from .sync_check import page_orders

PLACEHOLDER = "〓"


def stream_origins(pairs: Iterable[Any], cleaned_by_name: Mapping[str, Any]) -> list[tuple[str, str]]:
    """[(Nôm image name, original code)] for every 〓, in reading order."""
    ch_order, _vi = page_orders(list(pairs))
    out: list[tuple[str, str]] = []
    for image in ch_order:
        page = cleaned_by_name.get(image)
        if page is None:
            continue
        origins = list(getattr(page, "placeholder_origins", None) or [])
        count = str(getattr(page, "text", "") or "").count(PLACEHOLDER)
        if len(origins) != count:  # clean JSON older than origin tracking
            origins = ["unknown"] * count
        out.extend((image, code) for code in origins)
    return out


def assign_origins(
    rows: Sequence[Any], origins: Sequence[tuple[str, str]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """One record per 〓 in the CSV: sentence_id, 0-based position, image, code."""
    found = [
        (getattr(r, "sentence_id", ""), getattr(r, "img_id", ""), i)
        for r in rows
        for i, ch in enumerate(getattr(r, "ch_txt", "") or "")
        if ch == PLACEHOLDER
    ]
    problems: list[str] = []
    trusted = len(found) == len(origins)
    if not trusted:
        problems.append(
            f"PLACEHOLDER_ORIGIN_MISMATCH: CSV has {len(found)} 〓, the cleaned Nôm stream {len(origins)}"
        )
    out = []
    for k, (sid, img, pos) in enumerate(found):
        image, code = origins[k] if trusted else (img, "unknown")
        out.append({"sentence_id": sid, "position": pos, "image": image, "code": code})
    return out, problems


def code_counts(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(r["code"] for r in records).most_common())
