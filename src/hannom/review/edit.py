"""Pure review-edit logic (no Streamlit): Label.txt + CSV edited together.

SYNC rule (``hannom.sync_check``): the normalised concatenation of Label.txt
transcriptions (pages in image_map order) equals the normalised concatenation
of the CSV column. An edit of ``ch_txt``/``vi_txt`` is therefore applied to
the box transcriptions at mapped positions; box ``points`` never change.
"""

from __future__ import annotations

import copy
import dataclasses
import difflib
import os
from typing import Any, Mapping, Sequence

from ..models import AlignmentRow
from ..sync_check import check_sync, norm_nom, norm_vi, page_orders

Labels = dict[str, list[dict[str, Any]]]


class EditError(ValueError):
    """The edit cannot be applied safely (e.g. stream not in SYNC)."""


def _stream(labels: Mapping[str, Sequence[Mapping[str, Any]]], order: Sequence[str], norm):
    by_base = {os.path.basename(k.replace("\\", "/")): k for k in labels}
    text: list[str] = []
    origin: list[tuple[str, int, int]] = []  # (label key, box index, raw index)
    for image in order:
        key = by_base.get(image)
        if key is None:
            continue
        for b, box in enumerate(labels[key]):
            raw = str(box.get("transcription", ""))
            for r, c in enumerate(raw):
                if norm(c):
                    text.append(c)
                    origin.append((key, b, r))
    return "".join(text), origin


def _edit_side(labels: Labels, order, norm, row_norms: list[str], index: int, new_raw: str) -> None:
    stream, origin = _stream(labels, order, norm)
    if stream != "".join(row_norms):
        raise EditError("Label.txt and CSV are not in SYNC before the edit; refusing to edit")
    start = sum(len(t) for t in row_norms[:index])
    old = row_norms[index]
    new_map = [r for r, c in enumerate(new_raw) if norm(c)]
    new = "".join(new_raw[r] for r in new_map)

    def raw_slice(j1: int, j2: int) -> str:
        if j2 <= j1:
            return ""
        return new_raw[new_map[j1] : new_map[j2 - 1] + 1]

    ops = [o for o in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if o[0] != "equal"]
    for tag, i1, i2, j1, j2 in reversed(ops):
        g1, g2 = start + i1, start + i2
        text = raw_slice(j1, j2)
        if tag == "insert":
            if g1 == start and g1 < len(origin):
                key, b, pos = origin[g1]  # row start: before the following char
            elif g1 > 0:
                key, b, r = origin[g1 - 1]  # after the preceding char
                pos = r + 1
            else:
                raise EditError("no Label.txt box to receive the inserted text")
            t = str(labels[key][b]["transcription"])
            labels[key][b]["transcription"] = t[:pos] + text + t[pos:]
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:  # same length: swap char by char, keep box layout
            for k in range(i2 - i1):
                key, b, r = origin[g1 + k]
                t = str(labels[key][b]["transcription"])
                labels[key][b]["transcription"] = t[:r] + new[j1 + k] + t[r + 1 :]
            continue
        first = origin[g1]
        for g in range(g2 - 1, g1 - 1, -1):  # descending: raw indices stay valid
            key, b, r = origin[g]
            t = str(labels[key][b]["transcription"])
            labels[key][b]["transcription"] = t[:r] + t[r + 1 :]
        if tag == "replace" and text:
            key, b, r = first
            t = str(labels[key][b]["transcription"])
            labels[key][b]["transcription"] = t[:r] + text + t[r:]


def apply_row_edit(
    pairs: Sequence[Any],
    ch_labels: Labels,
    vi_labels: Labels,
    rows: Sequence[AlignmentRow],
    index: int,
    new_ch: str | None = None,
    new_vi: str | None = None,
) -> tuple[Labels, Labels, list[AlignmentRow]]:
    """Edit row ``index`` and the Label.txt dicts together (inputs untouched).

    Returns new (ch_labels, vi_labels, rows) for which ``check_sync`` is [].
    Raises ``EditError`` if the streams were not in SYNC before the edit or
    are not afterwards.
    """
    ch_labels, vi_labels = copy.deepcopy(ch_labels), copy.deepcopy(vi_labels)
    rows = copy.deepcopy(list(rows))
    row = rows[index]
    ch_order, vi_order = page_orders(list(pairs))
    do_ch = new_ch is not None and new_ch != row.ch_txt
    do_vi = new_vi is not None and new_vi != row.vi_txt
    if do_ch:
        _edit_side(ch_labels, ch_order, norm_nom, [norm_nom(r.ch_txt) for r in rows], index, new_ch)
        row.ch_txt = new_ch
    if do_vi:
        _edit_side(vi_labels, vi_order, norm_vi, [norm_vi(r.vi_txt) for r in rows], index, new_vi)
        row.vi_txt = new_vi
    dicts = [{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in rows]
    errors = check_sync(dicts, ch_labels if do_ch else None, vi_labels if do_vi else None, pairs)
    if errors:
        raise EditError("edit left Label.txt out of SYNC: " + errors[0])
    return ch_labels, vi_labels, rows


# --- text_diff after an edit -------------------------------------------------

def recompute_row_diff(
    row: AlignmentRow, *, lexicon=None, dictionary=None, readings_cache=None, mark_edited: bool = True,
    warn_rules=(),
    suggest_rules=(),
) -> AlignmentRow:
    """Spec-policy text_diff for one row; keeps accepted (reviewed=1) warns; flags CONTENT_EDITED."""
    from ..orchestrator import _rederivable_text_diff_flag
    from ..textdiff import spec_text_diff

    kept = {
        (e.nom_pos, e.vi_pos, e.nom_sub_text, e.vi_sub_text)
        for e in (row.text_diff or []) if e.type == "warn" and e.reviewed == 1
    }
    if "NON_ONE_TO_ONE" in row.flags or not row.ch_txt or not row.vi_txt:
        row.text_diff = None
    else:
        diff = spec_text_diff(row.ch_txt, row.vi_txt, lexicon=lexicon, dictionary=dictionary, warn_rules=warn_rules, suggest_rules=suggest_rules,
                              readings_cache=readings_cache)
        row.text_diff = diff.elements
        row.flags = sorted(
            {f for f in row.flags if not _rederivable_text_diff_flag(f)}
            | set(diff.flags) | {f"REVIEW:{r}" for r in diff.review_reasons}
        )
        if row.text_diff:
            row.text_diff = [
                dataclasses.replace(e, reviewed=1)
                if e.type == "warn" and (e.nom_pos, e.vi_pos, e.nom_sub_text, e.vi_sub_text) in kept else e
                for e in row.text_diff
            ]
    if mark_edited and "CONTENT_EDITED" not in row.flags:
        row.flags = sorted(set(row.flags) | {"CONTENT_EDITED"})
    return row


# --- warn / suggest actions --------------------------------------------------

def accept_warn(row: AlignmentRow, element_index: int, reviewed: int = 1) -> AlignmentRow:
    el = (row.text_diff or [])[element_index]
    if el.type != "warn":
        raise EditError("only warn elements can be accepted")
    row.text_diff[element_index] = dataclasses.replace(el, reviewed=1 if reviewed else 0)
    return row


def reject_suggest(row: AlignmentRow, element_index: int) -> AlignmentRow:
    """Quy định v2.4 case (c): keep the OCR char, the element becomes a plain
    red error (suggest, suggest_by and reviewed dropped)."""
    el = (row.text_diff or [])[element_index]
    row.text_diff[element_index] = dataclasses.replace(el, type="error", reviewed=None, suggest=None, suggest_by=None)
    return row


def suggest_edit_text(row: AlignmentRow, element_index: int) -> str:
    """ch_txt with the element's Nôm span replaced by its ``suggest`` (accepting it)."""
    el = (row.text_diff or [])[element_index]
    if el.type != "warn" or not el.suggest or not el.nom_pos:
        raise EditError("element has no suggest to accept")
    s, e = el.nom_pos[0]
    return row.ch_txt[:s] + el.suggest + row.ch_txt[e:]


def suggest_edit_text_all(row: AlignmentRow) -> str:
    """ch_txt with every pending suggestion of the row accepted (one char each)."""
    chars = list(row.ch_txt)
    found = False
    for el in row.text_diff or []:
        if el.type == "warn" and el.suggest and el.nom_pos:
            s, e = el.nom_pos[0]
            if e - s != 1 or len(el.suggest) != 1:
                raise EditError("a suggestion must replace exactly one Nôm char")
            chars[s] = el.suggest
            found = True
    if not found:
        raise EditError("row has no suggestion to accept")
    return "".join(chars)


def nom_stream_index(pairs: Sequence[Any], ch_labels: Labels, rows: Sequence[AlignmentRow]) -> dict[str, Any]:
    """Precomputed Label.txt Nôm stream for ``nom_char_location`` (one pass per page view)."""
    from ..sync_check import _labels_by_image, _stream

    ch_order, _vi_order = page_orders(list(pairs))
    _text, origin = _stream(_labels_by_image(ch_labels), ch_order, norm_nom)
    starts, total = [], 0
    for r in rows:
        starts.append(total)
        total += len(norm_nom(r.ch_txt))
    first: dict[tuple[str, int], int] = {}
    count: dict[tuple[str, int], int] = {}
    for k, key in enumerate(origin):
        first.setdefault(key, k)
        count[key] = count.get(key, 0) + 1
    return {"origin": origin, "starts": starts, "first": first, "count": count}


def nom_char_location(
    pairs: Sequence[Any], ch_labels: Labels, rows: Sequence[AlignmentRow], index: int, pos: int,
    stream: dict[str, Any] | None = None,
) -> tuple[str, int, int, int] | None:
    """(image, box index, char index inside the box, chars in the box) of
    ``rows[index].ch_txt[pos]``, from the Label.txt SYNC stream; None when the
    row is not in SYNC with Label.txt at that point."""
    stream = stream or nom_stream_index(pairs, ch_labels, rows)
    origin = stream["origin"]
    k = stream["starts"][index] + len(norm_nom(rows[index].ch_txt[:pos]))
    if k >= len(origin):
        return None
    key = origin[k]
    return key[0], key[1], k - stream["first"][key], stream["count"][key]


# --- review queue ------------------------------------------------------------

def red_density(row: AlignmentRow) -> float:
    n = len(norm_nom(row.ch_txt))
    if not row.text_diff or not n:
        return 0.0
    red = sum(e - s for el in row.text_diff if el.type == "error" for s, e in el.nom_pos)
    return red / n


def short_row(row: AlignmentRow, minimum: int = 5) -> bool:
    return len(norm_nom(row.ch_txt)) < minimum or len(row.vi_txt.split()) < minimum


def needs_manual(row: AlignmentRow) -> bool:
    """Null text_diff, or fewer than 5 chars/syllables: reviewed by hand (v2.4)."""
    return row.text_diff is None or short_row(row)


def is_reviewed(row: AlignmentRow) -> bool:
    """A reviewer recorded a decision for the row (accept / unresolved / unmatched)."""
    return getattr(row, "review_status", None) is not None


def is_edited(row: AlignmentRow) -> bool:
    return "CONTENT_EDITED" in row.flags


def awaiting_decision(row: AlignmentRow) -> bool:
    """Saved edits but no decision yet: easy to forget, so it has its own queue."""
    return is_edited(row) and not is_reviewed(row)


def pending_suggests(row: AlignmentRow) -> int:
    return sum(1 for e in (row.text_diff or []) if e.type == "warn" and e.suggest)


def review_queue(rows: Sequence[AlignmentRow], mode: str = "red", include_reviewed: bool = True) -> list[int]:
    """Row indices. mode: red (density desc, plus manual rows), manual (null/short), warn (unreviewed warns), all."""
    idx = list(range(len(rows)))
    if not include_reviewed:
        idx = [i for i in idx if not is_reviewed(rows[i])]
    if mode == "pending":
        return [i for i in range(len(rows)) if awaiting_decision(rows[i])]
    if mode == "undecided":
        return [i for i in range(len(rows)) if not is_reviewed(rows[i])]
    if mode == "manual":
        return [i for i in idx if needs_manual(rows[i])]
    if mode == "warn":
        return [i for i in idx if any(e.type == "warn" and e.reviewed != 1 for e in (rows[i].text_diff or []))]
    if mode == "suggest":
        return [i for i in range(len(rows)) if pending_suggests(rows[i])]
    if mode == "red":
        idx = [i for i in idx if red_density(rows[i]) > 0 or needs_manual(rows[i])]
        return sorted(idx, key=lambda i: (-red_density(rows[i]), i))
    return idx


def progress(rows: Sequence[AlignmentRow]) -> tuple[int, int]:
    """(rows with a decision, all rows); saved-but-undecided rows do not count."""
    return sum(1 for r in rows if is_reviewed(r)), len(rows)


def label_paths_save(labels: Labels, path, folder: str) -> None:
    """Write a Label dict back to ``<folder>/Label.txt`` keeping its image order."""
    from ..labels import write_label_txt

    names = [os.path.basename(k.replace("\\", "/")) for k in labels]
    boxes = {os.path.basename(k.replace("\\", "/")): v for k, v in labels.items()}
    write_label_txt(names, boxes, path, folder)


def _backup(path) -> None:
    """Keep the previous version next to the file (<name>.bak-review)."""
    import shutil
    from pathlib import Path

    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak-review"))


def atomic_save_csv(csv_path, rows) -> None:
    """Write the CSV and its review-metadata sidecar atomically (temp dir +
    os.replace), keeping a .bak-review copy of the previous versions."""
    import tempfile
    from pathlib import Path

    from ..align import write_alignment_csv
    from ..review_metadata import sidecar_path as metadata_path

    csv_path = Path(csv_path)
    side = metadata_path(csv_path)
    with tempfile.TemporaryDirectory(dir=csv_path.parent) as tmp:
        tmp_csv = Path(tmp) / csv_path.name
        write_alignment_csv(tmp_csv, rows)
        for target in (csv_path, side):
            _backup(target)
        os.replace(tmp_csv, csv_path)
        tmp_side = metadata_path(tmp_csv)
        if tmp_side.exists():
            os.replace(tmp_side, side)


def atomic_save_labels(labels: Labels, path, folder: str) -> None:
    """label_paths_save, but via a temp file + os.replace with a backup."""
    import tempfile
    from pathlib import Path

    path = Path(path)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        tmp_path = Path(tmp) / path.name
        label_paths_save(labels, tmp_path, folder)
        _backup(path)
        os.replace(tmp_path, path)


def select_row(
    rows: Sequence[AlignmentRow], queue: Sequence[int], row_index: int, pinned_sid: str | None
) -> tuple[int, int | None]:
    """Which row to show: (index into rows, its position in the queue or None).

    The row under review stays pinned by sentence_id across reruns, so saving
    an edit never swaps the displayed row for another one even when the edit
    moves the row in (or removes it from) a red-density queue.
    """
    if pinned_sid is not None:
        for i, r in enumerate(rows):
            if r.sentence_id == pinned_sid:
                return i, (queue.index(i) if i in queue else None)
    pos = max(0, min(int(row_index), len(queue) - 1))
    return queue[pos], pos


def next_position(queue: Sequence[int], current: int, current_pos: int | None, row_index: int) -> int:
    """Queue position after accepting the current row: the following row, or
    (when the current row already left the queue) the row now at its old slot."""
    if current_pos is not None:
        return min(len(queue) - 1, current_pos + 1)
    return max(0, min(int(row_index), len(queue) - 1))


def review_history(patches: Sequence[Any], decisions: Sequence[Any]) -> list[dict[str, str]]:
    """Edits (patches) and decisions, newest first, for the review app."""
    items: list[dict[str, str]] = []
    for p in patches:
        items.append({
            "sentence_id": p.sentence_id, "kind": "edit", "what": f"sửa {p.field}",
            "reviewer": p.reviewer, "timestamp": str(p.timestamp),
            "detail": f"{str(p.before)[:80]} → {str(p.after)[:80]}",
        })
    for d in decisions:
        items.append({
            "sentence_id": d.sentence_id, "kind": "decision", "what": str(d.status),
            "reviewer": d.reviewer, "timestamp": str(d.timestamp), "detail": str(getattr(d, "reason", "") or ""),
        })
    return sorted(items, key=lambda h: h["timestamp"], reverse=True)


def reviewed_order(rows: Sequence[AlignmentRow], history: Sequence[Mapping[str, str]]) -> list[int]:
    """Reviewed/edited rows, most recent activity first (rows without history last, in book order)."""
    latest: dict[str, str] = {}
    for h in history:
        latest.setdefault(h["sentence_id"], h["timestamp"])
    idx = [i for i, r in enumerate(rows) if is_reviewed(r) or is_edited(r) or r.sentence_id in latest]
    return sorted(idx, key=lambda i: (latest.get(rows[i].sentence_id, ""), -i), reverse=True)


def find_rows(rows: Sequence[AlignmentRow], query: str, limit: int = 30) -> list[int]:
    """Rows whose sentence_id ends with the query (e.g. '487.9') or whose text contains it."""
    q = (query or "").strip()
    if not q:
        return []
    by_id = [i for i, r in enumerate(rows) if r.sentence_id.endswith(q) or r.sentence_id.endswith("." + q)]
    if by_id:
        return by_id[:limit]
    ql = q.lower()
    return [i for i, r in enumerate(rows) if q in r.ch_txt or ql in r.vi_txt.lower()][:limit]


def row_locations(
    pairs: Sequence[Any], ch_labels: Labels, vi_labels: Labels, rows: Sequence[AlignmentRow], index: int
) -> dict[str, dict[str, Any]]:
    """Where row ``index`` sits in Label.txt, using the SYNC streams.

    Returns {"ch": {image: sorted box indices}, "vi": {image: (start, end)}}
    where (start, end) is the row's share of that QN page box as fractions
    of its text (the QN page is one full-page box, so on the image this is
    only an estimate of the vertical position).
    """
    from ..sync_check import _labels_by_image, _stream

    out: dict[str, dict[str, Any]] = {"ch": {}, "vi": {}}
    ch_order, vi_order = page_orders(list(pairs))
    for side, labels, order, norm, col in (
        ("ch", ch_labels, ch_order, norm_nom, "ch_txt"),
        ("vi", vi_labels, vi_order, norm_vi, "vi_txt"),
    ):
        pages = _labels_by_image(labels)
        _text, origin = _stream(pages, order, norm)
        start = sum(len(norm(getattr(r, col))) for r in rows[:index])
        end = start + len(norm(getattr(rows[index], col)))
        span = origin[start:end]
        if side == "ch":
            boxes: dict[str, set[int]] = {}
            for image, box in span:
                boxes.setdefault(image, set()).add(box)
            out["ch"] = {img: sorted(b) for img, b in boxes.items()}
        else:
            box_len: dict[tuple[str, int], int] = {}
            first: dict[tuple[str, int], int] = {}
            for pos, key in enumerate(origin):
                box_len[key] = box_len.get(key, 0) + 1
                first.setdefault(key, pos)
            seen: dict[tuple[str, int], list[int]] = {}
            for pos in range(start, min(end, len(origin))):
                key = origin[pos]
                seen.setdefault(key, []).append(pos - first[key])
            for (image, _box), offs in seen.items():
                n = box_len[(image, _box)] or 1
                out["vi"][image] = (min(offs) / n, (max(offs) + 1) / n)
    return out


def normalize_cell(text: str, field: str) -> str:
    """CSV/Label cells never hold line breaks (v2.4 FORM): QN line breaks become
    one space, Nôm whitespace is removed (Nôm is written without spaces)."""
    import re as _re

    if field == "ch_txt":
        return _re.sub(r"\s+", "", text)
    return _re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", text).strip()


def mark_as_warn(row: AlignmentRow, element_index: int) -> AlignmentRow:
    """Reviewer decision (v2.4 yellow): an error element whose Nôm and QN
    differ in length but agree in meaning -- a proper name or a year, e.g.
    阿綿 = "Amen" -- becomes a reviewed warn element."""
    els = list(row.text_diff or [])
    if 0 <= element_index < len(els) and els[element_index].type == "error":
        els[element_index] = dataclasses.replace(els[element_index], type="warn", reviewed=1)
        row.text_diff = els
    return row
