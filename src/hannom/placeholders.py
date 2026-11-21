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


def stream_origins(
    pairs: Iterable[Any],
    cleaned_by_name: Mapping[str, Any],
    ch_labels: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[tuple[str, str]]:
    """[(Nôm image name, original code)] for every 〓, in reading order.

    With ``ch_labels`` (the current ch/Label.txt), each page's cleaned text is
    aligned to the page's current Label text, so reviewer edits do not shift
    the codes: a 〓 the reviewer replaced by a real character drops out, and a
    〓 the reviewer typed in gets ``U+3013`` (no OCR origin).
    """
    import difflib

    from .sync_check import _labels_by_image, norm_nom

    ch_order, _vi = page_orders(list(pairs))
    current = _labels_by_image(ch_labels) if ch_labels is not None else {}
    out: list[tuple[str, str]] = []
    for image in ch_order:
        page = cleaned_by_name.get(image)
        clean_text = norm_nom(str(getattr(page, "text", "") or "")) if page is not None else ""
        origins = list(getattr(page, "placeholder_origins", None) or []) if page is not None else []
        if len(origins) != clean_text.count(PLACEHOLDER):  # clean JSON older than origin tracking
            origins = ["unknown"] * clean_text.count(PLACEHOLDER)
        if ch_labels is None:
            out.extend((image, code) for code in origins)
            continue
        label_text = "".join(norm_nom(t) for t in current.get(image, []))
        clean_codes = {}
        k = 0
        for pos, ch in enumerate(clean_text):
            if ch == PLACEHOLDER:
                clean_codes[pos] = origins[k]
                k += 1
        mapped: dict[int, str] = {}
        sm = difflib.SequenceMatcher(None, clean_text, label_text, autojunk=False)
        for tag, a0, a1, b0, _b1 in sm.get_opcodes():
            if tag == "equal":
                for off in range(a1 - a0):
                    if (a0 + off) in clean_codes:
                        mapped[b0 + off] = clean_codes[a0 + off]
        for pos, ch in enumerate(label_text):
            if ch == PLACEHOLDER:
                out.append((image, mapped.get(pos, "U+3013")))
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
