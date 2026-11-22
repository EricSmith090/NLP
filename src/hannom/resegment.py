"""Re-segmentation from reviewed text, with reviewed rows pinned (2026-11-21).

Problem: ``align`` cut sentences on the cleaned OCR text in ``data/clean`` and
re-applied reviewer text edits row by row afterwards, so a row boundary that
came from broken OCR text (lost or duplicated QN lines) could never move:
the reviewer had to cut sentences to fit it, or retype text that also stayed
in the neighbouring row.

Fix, in two pieces used by ``orchestrator.compute_alignment``:

- ``overlay_label_text`` — Label.txt holds every reviewer text edit (the
  review app writes Label.txt and the CSV together, SYNC-checked). For pages
  whose Label.txt text differs from the cleaned text, segment on the Label
  text instead.
- ``pin_reviewed_rows`` — after re-segmenting, keep the previous rows wherever
  a reviewer already accepted a row. Both row lists partition the same Nôm
  and Quốc ngữ streams; at every boundary they share (same Nôm offset and same
  QN offset) the two segmentations can be swapped. Between two shared
  boundaries the previous rows are kept if one of them is pinned, otherwise
  the new rows are used. Pinned rows therefore keep their exact text, so
  their decisions keep verifying (``review_decisions`` relocates them if the
  sentence_id changes).
"""

from __future__ import annotations

import copy
import os
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Sequence

from .labels import read_label_txt
from .models import AlignmentRow
from .sync_check import norm_nom, norm_vi

PIN_STATUSES = frozenset({"accepted_match", "accepted_difference", "alignment_reviewed"})


class ResegmentError(RuntimeError):
    """Re-segmentation cannot be applied safely (streams differ)."""


def overlay_label_text(cleaned: dict[str, Any], label_root: Path) -> tuple[dict[str, Any], list[str]]:
    """Return (cleaned pages with Label.txt text where it differs, changed image names).

    Comparison ignores whitespace (and hyphens for Quốc ngữ), exactly as the
    SYNC check does, so only pages with real text edits are replaced. Only
    ``text`` (what the charalign segmenter reads) is replaced; the page gets
    the flag ``TEXT_FROM_LABEL``.
    """
    out = dict(cleaned)
    changed: list[str] = []
    # Box texts are joined exactly as clean.py builds page text: Nôm lines
    # without a separator, Quốc ngữ lines with one space. A "\n" here would
    # end up inside CSV cells (official FORM "line break in cell").
    for folder, norm, joiner in (("ch", norm_nom, ""), ("vi", norm_vi, " ")):
        path = Path(label_root) / folder / "Label.txt"
        if not path.exists():
            continue
        for key, boxes in read_label_txt(path).items():
            name = os.path.basename(str(key).replace("\\", "/"))
            page = out.get(name)
            if page is None:
                continue
            text = joiner.join(unicodedata.normalize("NFC", str(b.get("transcription", ""))) for b in boxes)
            if norm(text) != norm(page.text or ""):
                out[name] = replace(page, text=text, flags=sorted(set(page.flags) | {"TEXT_FROM_LABEL"}))
                changed.append(name)
    return out, changed


def _boundaries(rows: Sequence[AlignmentRow]) -> list[tuple[int, int]]:
    out, n, q = [], 0, 0
    for row in rows:
        n += len(norm_nom(row.ch_txt))
        q += len(norm_vi(row.vi_txt))
        out.append((n, q))
    return out


def renumber(rows: Sequence[AlignmentRow]) -> list[AlignmentRow]:
    """sentence_id = <image without .jpg>.<n>, n counted per image in row order (as align._emit_rows)."""
    counters: dict[str, int] = {}
    for row in rows:
        base = row.img_id[:-4] if row.img_id.lower().endswith(".jpg") else row.img_id
        counters[base] = counters.get(base, 0) + 1
        row.sentence_id = f"{base}.{counters[base]}"
    return list(rows)


def pin_reviewed_rows(
    previous: Sequence[AlignmentRow],
    new: Sequence[AlignmentRow],
    pinned: Iterable[int],
) -> tuple[list[AlignmentRow], dict[str, Any]]:
    """Merge two segmentations of the same streams, keeping pinned previous rows.

    ``pinned`` are indices into ``previous``. Raises ``ResegmentError`` when
    the two row lists do not cover identical Nôm and QN streams (then the
    offsets would not mean the same thing and nothing may be merged).
    """
    pinned = set(pinned)
    if "".join(norm_nom(r.ch_txt) for r in previous) != "".join(norm_nom(r.ch_txt) for r in new):
        raise ResegmentError("Nôm stream of the new segmentation differs from the previous CSV")
    if "".join(norm_vi(r.vi_txt) for r in previous) != "".join(norm_vi(r.vi_txt) for r in new):
        raise ResegmentError("Quốc ngữ stream of the new segmentation differs from the previous CSV")
    pb, nb = _boundaries(previous), _boundaries(new)
    shared = set(pb) & set(nb)
    out: list[AlignmentRow] = []
    report = {"windows": 0, "windows_changed": 0, "windows_kept_for_pins": 0, "pinned": len(pinned),
              "rows_previous": len(previous), "rows_new": len(new), "kept_windows": []}
    i = j = 0
    while i < len(previous) or j < len(new):
        pi, nj = i, j
        # advance both sides to the next shared boundary
        while True:
            end_p = pb[pi] if pi < len(pb) else None
            end_n = nb[nj] if nj < len(nb) else None
            if end_p is not None and end_p in shared and end_p == end_n:
                break
            if end_n is None or (end_p is not None and (end_p[0], end_p[1]) < (end_n[0], end_n[1])):
                pi += 1
            else:
                nj += 1
        old_rows, new_rows = previous[i : pi + 1], new[j : nj + 1]
        report["windows"] += 1
        same_cut = _boundaries(old_rows) == _boundaries(new_rows) or len(old_rows) == len(new_rows) == 1
        if not same_cut:
            report["windows_changed"] += 1
        if any(k in pinned for k in range(i, pi + 1)):
            if not same_cut:
                report["windows_kept_for_pins"] += 1
                report["kept_windows"].append([r.sentence_id for r in old_rows])
            out.extend(copy.deepcopy(list(old_rows)))
        else:
            out.extend(new_rows)
        i, j = pi + 1, nj + 1
    renumber(out)
    report["rows_out"] = len(out)
    return out, report


def previous_rows_for_pinning(csv_path: Path, decisions, decision_issues, failures) -> list[AlignmentRow] | None:
    """The previous CSV with decisions applied, or None when there is none yet.

    No previous CSV (a fresh machine running the pipeline from scratch) means
    there is nothing to pin: segmentation still uses the Label.txt text.
    """
    from .review_decisions import apply_decisions
    from .review_metadata import load_rows_with_metadata

    if not Path(csv_path).exists():
        return None
    rows, _issues = load_rows_with_metadata(csv_path)
    rows, _active, _audit = apply_decisions(rows, decisions, decision_issues, failures=failures)
    return rows


def same_cut_rows(previous: Sequence[AlignmentRow], new: Sequence[AlignmentRow]) -> set[int]:
    """Indices of ``previous`` rows whose exact span (start and end in both
    streams, whitespace-insensitive) is also one row of ``new``. Spans, not
    texts: a repeated sentence elsewhere never counts as the same cut."""
    def spans(rows: Sequence[AlignmentRow]) -> list[tuple[int, int, int, int]]:
        out, n, q = [], 0, 0
        for r in rows:
            n2, q2 = n + len(norm_nom(r.ch_txt)), q + len(norm_vi(r.vi_txt))
            out.append((n, q, n2, q2))
            n, q = n2, q2
        return out

    new_spans = set(spans(new))
    return {k for k, s in enumerate(spans(previous)) if s in new_spans}


def release_toc_pins(
    previous: Sequence[AlignmentRow], new: Sequence[AlignmentRow], pinned: Iterable[int], toc_images: set[str]
) -> tuple[list[int], list[str]]:
    """(pins kept, sentence_ids released) for rows on TOC pages.

    A reviewed TOC row is released only where the TOC rule now cuts its text
    differently (e.g. 263.5 once the missing page numbers 33/48 were typed:
    one merged row becomes three entries). Where the new cut yields the very
    same row it stays pinned with its colouring, so a later colouring change
    (name blocks, new rules) cannot void its decision (269.2, 2026-11-22).
    """
    pinned = list(pinned)
    same = same_cut_rows(previous, new) if toc_images else set()
    kept = [k for k in pinned if previous[k].img_id not in toc_images or k in same]
    kept_set = set(kept)
    released = [previous[k].sentence_id for k in pinned if k not in kept_set]
    return kept, released


def toc_nom_images(alignment_config: dict[str, Any] | None, book_id: str, pairs: Sequence[Any]) -> set[str]:
    """Nôm images paired with the book's QN table-of-contents pages
    (``alignment.per_book.<book>.toc_qn_pages``).

    Rows there are cut by the TOC rule (instructor, 2026-11-21); a reviewed
    row is unpinned where the rule cuts differently (``release_toc_pins``):
    reviews made before the rule existed judged rows the rule replaces.
    """
    raw = alignment_config or {}
    cfg = raw.get("alignment", raw) or {}
    pages = {int(p) for p in (((cfg.get("per_book") or {}).get(book_id) or {}).get("toc_qn_pages") or ())}
    if not pages:
        return set()

    def number(name: str) -> int | None:
        try:
            return int(str(name).split(".")[-2])
        except (ValueError, IndexError):
            return None

    return {ch for pair in pairs if any(number(v) in pages for v in pair.vi) for ch in pair.ch}


def pinned_indices(rows: Sequence[AlignmentRow]) -> list[int]:
    """Rows whose review decision verifies with an accepting status."""
    return [
        k for k, r in enumerate(rows)
        if getattr(r, "review_status", None) in PIN_STATUSES and getattr(r, "decision_integrity", None) == "valid"
    ]
