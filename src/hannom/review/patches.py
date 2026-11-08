"""Append-only review patches with provenance.

Automated stages must always regenerate drafts first, then call
``apply_patches``. This preserves human corrections across reruns while
keeping a complete before/after audit trail.
"""

from __future__ import annotations

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
        )
        for item in raw
    ]


def apply_patches(
    rows: Iterable[AlignmentRow],
    patches: Iterable[ReviewPatch],
) -> list[AlignmentRow]:
    """Apply patches in file order; last write wins per row/field."""
    rows = list(rows)
    by_id = {row.sentence_id: row for row in rows}
    for patch in patches:
        row = by_id.get(patch.sentence_id)
        if row is None:
            continue
        if patch.field == "ch_txt":
            row.ch_txt = patch.after
        elif patch.field == "vi_txt":
            row.vi_txt = patch.after
        elif patch.field == "text_diff":
            row.text_diff = _elements_from_json(patch.after)
        if "HUMAN_REVIEWED" not in row.flags:
            row.flags.append("HUMAN_REVIEWED")
    return rows


def patch_log_as_json(rows: Iterable[AlignmentRow], patches: Iterable[ReviewPatch]) -> dict[str, Any]:
    return {
        "rows": len(list(rows)),
        "patches": [patch.to_dict() for patch in patches],
    }
