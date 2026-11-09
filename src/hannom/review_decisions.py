"""Durable, append-only review decisions (Stage "human review").

A *content edit* is not an approval of the alignment, and accepting a row
is a first-class, durable event. This module stores one JSON object per
review decision in ``data/review/<book_id>.review_decisions.jsonl``::

    {
        "schema": 1,
        "book_id": "T1_Book",
        "sentence_id": "T1_Book.001.1",
        "status": "accepted_match",
        "reviewer": "reviewer",
        "reason": "đối chiếu hình ảnh",
        "timestamp": "2026-11-09T12:00:00+00:00",
        "content_sha256": "<sha256 of ch_txt, vi_txt, text_diff>",
        "character_token_mappings": [
            {"nom_char": "之", "nom_position": 0,
             "qn_token": "thì", "qn_token_position": 2}
        ]
    }

Decision semantics
------------------

- ``content_edited``       a reviewer changed transcription/comparison
                           content. Establishes nothing about the
                           alignment. Any edit is also mirrored by a
                           content patch in ``*.patches.jsonl``.
- ``alignment_reviewed``   a reviewer explicitly verified the Nôm↔QN
                           correspondence without asserting whether
                           differences exist.
- ``accepted_match``       a reviewer explicitly confirmed the texts
                           correspond with no discrepancy.
- ``accepted_difference``  a reviewer explicitly confirmed the
                           correspondence and accepted the recorded
                           difference elements.
- ``unresolved``           a reviewer could not resolve the row.
- ``unmatched``            a reviewer determined no reliable counterpart
                           exists.
- ``rejected``             a reviewer rejected the current row content.

Rules enforced here:

- The newest record for a ``sentence_id`` wins; the log is append-only so
  the full history is preserved.
- A decision whose ``content_sha256`` does not match the *current* row
  content is **stale**: it never verifies anything, and it is reported as
  a blocking issue.
- A decision whose ``status`` is not a known constant is **invalid**:
  reported and ignored.
- A valid verifying decision whose content contradicts it (e.g.
  ``accepted_match`` with a non-empty ``text_diff``) is treated as
  unverified and reported.
- Machine-generated evidence and human-confirmed evidence stay
  distinguishable at every stage.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import AlignmentRow

SCHEMA = 1

STATUS_CONTENT_EDITED = "content_edited"
STATUS_ALIGNMENT_REVIEWED = "alignment_reviewed"
STATUS_ACCEPTED_MATCH = "accepted_match"
STATUS_ACCEPTED_DIFFERENCE = "accepted_difference"
STATUS_UNRESOLVED = "unresolved"
STATUS_UNMATCHED = "unmatched"
STATUS_REJECTED = "rejected"

DECISION_STATUSES = frozenset(
    {
        STATUS_CONTENT_EDITED,
        STATUS_ALIGNMENT_REVIEWED,
        STATUS_ACCEPTED_MATCH,
        STATUS_ACCEPTED_DIFFERENCE,
        STATUS_UNRESOLVED,
        STATUS_UNMATCHED,
        STATUS_REJECTED,
    }
)

# Decisions that explicitly verify the correspondence. ``content_edited``
# deliberately grants nothing.
VERIFYING_STATUSES = frozenset(
    {STATUS_ALIGNMENT_REVIEWED, STATUS_ACCEPTED_MATCH, STATUS_ACCEPTED_DIFFERENCE}
)

REVIEW_DECISION_STALE_FLAG = "REVIEW_DECISION_STALE"
REVIEW_DECISION_MISMATCH_FLAG = "REVIEW_DECISION_MISMATCH"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_sha256(ch_txt: str, vi_txt: str, diff_json: str) -> str:
    payload = "\x1f".join(
        [
            unicodedata.normalize("NFC", ch_txt),
            unicodedata.normalize("NFC", vi_txt),
            diff_json,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CharacterTokenMapping:
    nom_char: str
    nom_position: int
    qn_token: str
    qn_token_position: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterTokenMapping":
        return cls(
            nom_char=str(data.get("nom_char", "")),
            nom_position=int(data.get("nom_position", -1)),
            qn_token=str(data.get("qn_token", "")),
            qn_token_position=int(data.get("qn_token_position", -1)),
        )


@dataclass
class ReviewDecision:
    book_id: str
    sentence_id: str
    status: str
    reviewer: str
    reason: str = ""
    timestamp: str = field(default_factory=utc_now)
    content_sha256: str = ""
    character_token_mappings: list[CharacterTokenMapping] = field(default_factory=list)
    schema: int = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["character_token_mappings"] = [m.to_dict() for m in self.character_token_mappings]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewDecision":
        try:
            schema_value = int(data.get("schema", SCHEMA))
        except (TypeError, ValueError):
            schema_value = -1  # invalid schema: validate_decision will flag it
        mappings = [
            CharacterTokenMapping.from_dict(item)
            for item in data.get("character_token_mappings", [])
            if isinstance(item, dict)
        ]
        return cls(
            book_id=str(data.get("book_id", "")),
            sentence_id=str(data.get("sentence_id", "")),
            status=str(data.get("status", "")),
            reviewer=str(data.get("reviewer", "")),
            reason=str(data.get("reason", "")),
            timestamp=str(data.get("timestamp", "")),
            content_sha256=str(data.get("content_sha256", "")),
            character_token_mappings=mappings,
            schema=schema_value,
        )


def decision_path(data_dir: str | Path, book_id: str) -> Path:
    return Path(data_dir) / "review" / f"{book_id}.review_decisions.jsonl"


def validate_decision(decision: ReviewDecision) -> list[str]:
    issues: list[str] = []
    if decision.schema != SCHEMA:
        issues.append(f"unsupported schema {decision.schema!r}")
    if not decision.sentence_id.strip():
        issues.append("sentence_id is empty")
    if decision.status not in DECISION_STATUSES:
        issues.append(f"invalid status {decision.status!r}")
    if not decision.reviewer.strip():
        issues.append("reviewer is empty")
    sha = decision.content_sha256.strip()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower()):
        issues.append("content_sha256 is not a sha256 hex digest")
    if not decision.timestamp.strip():
        issues.append("timestamp is empty")
    seen_mapping = False
    for mapping in decision.character_token_mappings:
        if len(mapping.nom_char) != 1:
            issues.append("character_token_mappings: nom_char must be exactly one code point")
        if mapping.nom_position < 0 or mapping.qn_token_position < 0:
            issues.append("character_token_mappings: positions must be >= 0")
        if not mapping.qn_token.strip():
            issues.append("character_token_mappings: qn_token is empty")
        seen_mapping = True
    return issues


def make_decision(
    *,
    book_id: str,
    sentence_id: str,
    status: str,
    reviewer: str,
    reason: str = "",
    ch_txt: str,
    vi_txt: str,
    text_diff_json: str,
    character_token_mappings: Iterable[Any] | None = None,
    timestamp: str | None = None,
) -> ReviewDecision:
    if status not in DECISION_STATUSES:
        raise ValueError(f"invalid review status {status!r}")
    items = []
    for item in character_token_mappings or []:
        if isinstance(item, CharacterTokenMapping):
            items.append(item)
        elif isinstance(item, dict):
            items.append(CharacterTokenMapping.from_dict(item))
        else:
            raise ValueError(f"character_token_mappings: unsupported item {item!r}")
    decision = ReviewDecision(
        book_id=book_id,
        sentence_id=sentence_id,
        status=status,
        reviewer=reviewer.strip(),
        reason=reason.strip(),
        timestamp=timestamp or utc_now(),
        content_sha256=content_sha256(ch_txt, vi_txt, text_diff_json),
        character_token_mappings=items,
    )
    issues = validate_decision(decision)
    if issues:
        raise ValueError("; ".join(issues))
    return decision


def append_decision(path: str | Path, decision: ReviewDecision) -> Path:
    issues = validate_decision(decision)
    if issues:
        raise ValueError("; ".join(issues))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
    return path


def read_decisions(path: str | Path) -> tuple[list[ReviewDecision], list[str]]:
    """Parse the decision log; malformed lines are reported, never skipped."""
    path = Path(path)
    decisions: list[ReviewDecision] = []
    issues: list[str] = []
    if not path.exists():
        # No decisions yet is a normal state, not an integrity failure.
        return decisions, issues
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(f"DECISION_JSON_ERROR:{path.name}:{lineno}:{exc.msg}")
            continue
        if not isinstance(data, dict):
            issues.append(f"DECISION_NOT_OBJECT:{path.name}:{lineno}")
            continue
        try:
            decision = ReviewDecision.from_dict(data)
        except (TypeError, ValueError) as exc:
            issues.append(f"DECISION_SCHEMA_ERROR:{path.name}:{lineno}:{exc}")
            continue
        errs = validate_decision(decision)
        if errs:
            issues.append(f"DECISION_INVALID:{path.name}:{lineno}:{'|'.join(errs)}")
            continue
        decisions.append(decision)
    return decisions, issues


def _row_hash(row: AlignmentRow) -> str:
    return content_sha256(row.ch_txt, row.vi_txt, row.text_diff_json())


def apply_decisions(
    rows: list[AlignmentRow],
    decisions: Iterable[ReviewDecision],
    decision_issues: Iterable[str] | None = None,
) -> tuple[list[AlignmentRow], list[str]]:
    """Overlay review decisions onto rows.

    Returns the rows (modified in place) and a list of
    ``REVIEW_DECISION_*``/``DECISION_*`` integrity issues. A decision
    whose hash does not match the current row content is stale and is
    discarded: it never verifies a row.
    """
    issues: list[str] = list(decision_issues or [])
    by_id: dict[str, list[ReviewDecision]] = {}
    for decision in decisions:
        by_id.setdefault(decision.sentence_id, []).append(decision)
    for row in rows:
        candidates = by_id.get(row.sentence_id, [])
        row.review_status = None
        row.review_reviewer = None
        row.character_token_mappings = []
        if not candidates:
            continue
        effective: ReviewDecision | None = None
        saw_stale = False
        for decision in candidates:
            errs = validate_decision(decision)
            if errs:
                issues.append(f"REVIEW_DECISION_INVALID:{row.sentence_id}:{'|'.join(errs)}")
                continue
            if decision.content_sha256 != _row_hash(row):
                issues.append(f"REVIEW_DECISION_STALE:{row.sentence_id}")
                saw_stale = True
                continue
            if effective is not None and effective.status != decision.status:
                issues.append(
                    f"REVIEW_DECISION_CONFLICT:{row.sentence_id}:{effective.status}->{decision.status}"
                )
            effective = decision
        if effective is None:
            row.flags = sorted(set(row.flags) | ({REVIEW_DECISION_STALE_FLAG} if saw_stale else {"REVIEW_DECISION_INVALID"}))
            continue
        row.review_status = effective.status
        row.review_reviewer = effective.reviewer
        row.character_token_mappings = [m.to_dict() for m in effective.character_token_mappings]
        row.flags = sorted(set(row.flags) | {f"REVIEW_STATUS_{effective.status.upper()}"})
    return rows, issues
