"""Append-only review patches with provenance.

Automated stages must always regenerate drafts first, then call
``apply_patches``. This preserves human corrections across reruns while
keeping a complete before/after audit trail.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import AlignmentRow, DiffElement


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReviewPatch:
    book_id: str
    sentence_id: str
    field: str  # ch_txt | vi_txt | text_diff
    before: str
    after: str
    reviewer: str
    reason: str = ""
    page_no: int | None = None
    timestamp: str = field(default_factory=utc_now)
    # Identity (T4.1): content hash of the row the patch was made against
    # (img_id + ch_txt + vi_txt *before* the edit) and its Nôm image.
    # ``sentence_id`` is only a positional hint. Empty row_hash = legacy line.
    row_hash: str = ""
    img_id: str = ""
    after_hash: str = ""  # row hash once this patch is applied (ch/vi fields)

    def validate(self) -> list[str]:
        issues: list[str] = []
        if self.field not in {"ch_txt", "vi_txt", "text_diff"}:
            issues.append(f"invalid field {self.field!r}")
        if not self.sentence_id:
            issues.append("sentence_id is empty")
        if not self.reviewer.strip():
            issues.append("reviewer is empty")
        if self.field == "text_diff":
            try:
                json.loads(self.after)
            except json.JSONDecodeError:
                issues.append("text_diff patch is not valid JSON")
        return issues

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def row_content_hash(img_id: str, ch_txt: str, vi_txt: str) -> str:
    """Stable identity of a row's content (independent of its position)."""
    payload = "".join((img_id or "", ch_txt or "", vi_txt or ""))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def make_patch(row: AlignmentRow, *, book_id: str, field: str, after: str, reviewer: str,
               reason: str = "") -> ReviewPatch:
    """Patch bound to ``row``'s current content (call BEFORE mutating the row)."""
    before = {"ch_txt": row.ch_txt, "vi_txt": row.vi_txt}.get(field)
    if before is None:
        before = row.text_diff_json()
    after_hash = ""
    if field in ("ch_txt", "vi_txt"):
        ch, vi = (after, row.vi_txt) if field == "ch_txt" else (row.ch_txt, after)
        after_hash = row_content_hash(row.img_id, ch, vi)
    return ReviewPatch(
        after_hash=after_hash, book_id=book_id, sentence_id=row.sentence_id, field=field, before=before, after=after,
        reviewer=reviewer, reason=reason, row_hash=row_content_hash(row.img_id, row.ch_txt, row.vi_txt),
        img_id=row.img_id,
    )


@dataclass
class RejectedPatch:
    patch: ReviewPatch
    reason: str


def append_patch(path: str | Path, patch: ReviewPatch) -> Path:
    issues = patch.validate()
    if issues:
        raise ValueError("; ".join(issues))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(patch.to_dict(), ensure_ascii=False) + "\n")
    return path


def read_patches(path: str | Path) -> list[ReviewPatch]:
    path = Path(path)
    if not path.exists():
        return []
    out: list[ReviewPatch] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid patch JSON") from exc
            known = set(ReviewPatch.__dataclass_fields__)
            out.append(ReviewPatch(**{k: v for k, v in data.items() if k in known}))
    return out


def _elements_from_json(value: str) -> list[DiffElement] | None:
    raw = json.loads(value)
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("text_diff patch must be null or a JSON array")
    return [
        DiffElement(
            nom_pos=tuple(tuple(int(x) for x in span) for span in item.get("nom_pos", [])),
            nom_sub_text=str(item.get("nom_sub_text", "")),
            vi_pos=tuple(tuple(int(x) for x in span) for span in item.get("vi_pos", [])),
            vi_sub_text=str(item.get("vi_sub_text", "")),
            type=str(item.get("type", "error")),  # type: ignore[arg-type]
            reviewed=item.get("reviewed"),
            suggest=item.get("suggest"),
            suggest_by=item.get("suggest_by"),
        )
        for item in raw
    ]


def _current(row: AlignmentRow, field_name: str) -> str:
    if field_name == "ch_txt":
        return row.ch_txt
    if field_name == "vi_txt":
        return row.vi_txt
    return row.text_diff_json()


def apply_patches_checked(
    rows: Iterable[AlignmentRow],
    patches: Iterable[ReviewPatch],
) -> tuple[list[AlignmentRow], list[RejectedPatch]]:
    """Apply patches by content hash; never overwrite a row that changed.

    A patch is located by ``row_hash`` (+ ``img_id``); ``sentence_id`` only
    breaks ties. It is applied only when the row's current value still equals
    the patch's ``before``. A patch whose ``after`` is already in place is a
    no-op (the edit was persisted to the CSV). Anything else is returned in
    the rejected list with a reason. Legacy patches (no ``row_hash``) are
    located by ``sentence_id`` but get the same ``before`` check.
    Applied rows are flagged ``CONTENT_EDITED``.
    """
    rows = list(rows)
    index: dict[str, list[AlignmentRow]] = {}
    by_sid: dict[str, AlignmentRow] = {}

    def register(key: str, row: AlignmentRow) -> None:
        bucket = index.setdefault(key, [])
        if not any(r is row for r in bucket):
            bucket.append(row)

    for row in rows:
        register(row_content_hash(row.img_id, row.ch_txt, row.vi_txt), row)
        by_sid.setdefault(row.sentence_id, row)
    rejected: list[RejectedPatch] = []
    for patch in patches:
        if patch.row_hash:
            cands = [r for r in index.get(patch.row_hash, []) if not patch.img_id or r.img_id == patch.img_id]
            if not cands and patch.after_hash:
                done = [r for r in index.get(patch.after_hash, [])
                        if (not patch.img_id or r.img_id == patch.img_id) and _current(r, patch.field) == patch.after]
                if done:
                    continue  # already applied (persisted to the CSV)
            if not cands:
                rejected.append(RejectedPatch(patch, "stale: no row has the content this patch was made against"))
                continue
            if len(cands) > 1:
                hinted = [r for r in cands if r.sentence_id == patch.sentence_id]
                if len(hinted) != 1:
                    rejected.append(RejectedPatch(patch, "ambiguous: several rows share this content"))
                    continue
                cands = hinted
            row = cands[0]
        else:
            row = by_sid.get(patch.sentence_id)
            if row is None:
                rejected.append(RejectedPatch(patch, "legacy patch: sentence_id not found"))
                continue
        current = _current(row, patch.field)
        if current == patch.after:
            continue
        if current != patch.before:
            rejected.append(RejectedPatch(patch, f"stale: {patch.field} changed since the patch was made"))
            continue
        if patch.field == "ch_txt":
            row.ch_txt = patch.after
        elif patch.field == "vi_txt":
            row.vi_txt = patch.after
        else:
            try:
                row.text_diff = _elements_from_json(patch.after)
            except (ValueError, TypeError) as exc:
                rejected.append(RejectedPatch(patch, f"invalid text_diff: {exc}"))
                continue
        if "CONTENT_EDITED" not in row.flags:
            row.flags.append("CONTENT_EDITED")
        register(row_content_hash(row.img_id, row.ch_txt, row.vi_txt), row)
    return rows, rejected


def apply_patches(
    rows: Iterable[AlignmentRow],
    patches: Iterable[ReviewPatch],
) -> list[AlignmentRow]:
    """Apply patches (see ``apply_patches_checked``), dropping the rejected list.

    Every patched row is flagged ``CONTENT_EDITED``; that grants no
    alignment verification. Review *decisions* live in
    ``hannom.review_decisions``. Use ``apply_patches_checked`` to see
    stale/rejected patches.
    """
    return apply_patches_checked(rows, patches)[0]


def patch_log_as_json(rows: Iterable[AlignmentRow], patches: Iterable[ReviewPatch]) -> dict[str, Any]:
    return {
        "rows": len(list(rows)),
        "patches": [patch.to_dict() for patch in patches],
    }
