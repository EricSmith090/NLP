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

Event order and supersession
----------------------------

The log is append-only and **file order is the authoritative event
order** (timestamps may be duplicated, manually supplied or reordered, so
they are never used for selection). For each ``sentence_id`` the
*effective decision* is the latest event in append order, and it alone
determines the row's review state after hash validation:

- The effective decision whose ``content_sha256`` matches the current row
  is applied normally.
- An effective decision that is stale never verifies anything, even if an
  earlier, now-superseded decision was valid: history is preserved for
  audit, never silently reused.
- An invalid effective decision behaves the same way; the system never
  falls back to an older approval.
- Earlier, superseded decisions never create active blockers — a newer
  valid decision legitimately replaces them.
- Two *valid* decisions on the same revision that make mutually exclusive
  claims (``accepted_match`` vs ``accepted_difference``) or assign the
  same Nôm position to different tokens are a genuine contradiction and
  are reported as ``REVIEW_DECISION_CONFLICT``.
- Ordinary status transitions (e.g. ``unresolved`` → ``accepted_match``,
  ``content_edited`` → ``rejected``) are legitimate and are never
  classified as conflicts.

Invalid records never verify a row, never trigger a fallback to an older
approval, and always surface as log-integrity issues. Integrity failures
attributable to a specific ``sentence_id`` block that row; log-wide
failures (unparseable JSON, unsupported schema, unreadable file) disable
learning for the whole book.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import unicodedata
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


def _nom_char_positions(text: str) -> list[int]:
    from .clean import is_nom_char

    return [i for i, ch in enumerate(text) if is_nom_char(ch)]


def _qn_token_items(text: str) -> list[tuple[int, int, str]]:
    import re

    return [m for m in re.finditer(r"[^\W\d_]+", unicodedata.normalize("NFC", text).casefold())]


def normalize_token(token: str) -> str:
    return unicodedata.normalize("NFC", token.strip()).casefold()


def validate_mapping_set(mappings: Iterable[CharacterTokenMapping]) -> list[str]:
    """Validate a *set* of positional mappings as a whole (Issue D).

    Position assignment uniqueness and monotonic order are enforced across
    the complete set — never mapping-by-mapping in isolation:

    - exactly one Nôm code point per mapping;
    - positions are integers >= 0;
    - no duplicate entries (identical char/positions pair);
    - each Nôm position appears at most once;
    - each QN token position appears at most once;
    - the set is monotone in both coordinates (sequential 1-1
      correspondence must remain sequential);
    - ``nom_char``/``qn_token`` are single code points / non-empty
      normalized syllables respectively.
    """
    issues: list[str] = []
    items = list(mappings)
    if not items:
        return issues
    positions_nom: list[int] = []
    positions_qn: list[int] = []
    seen_exact: set[tuple[str, int, str, int]] = set()
    for index, mapping in enumerate(items):
        if len(mapping.nom_char) != 1:
            issues.append(f"mapping {index}: nom_char must be exactly one code point")
        if mapping.nom_position < 0:
            issues.append(f"mapping {index}: nom_position must be >= 0")
        if mapping.qn_token_position < 0:
            issues.append(f"mapping {index}: qn_token_position must be >= 0")
        token = normalize_token(mapping.qn_token)
        if not token:
            issues.append(f"mapping {index}: qn_token is empty")
        key = (
            unicodedata.normalize("NFC", mapping.nom_char),
            mapping.nom_position,
            token,
            mapping.qn_token_position,
        )
        if key in seen_exact:
            issues.append(f"mapping {index}: duplicate mapping entry")
        seen_exact.add(key)
        positions_nom.append(mapping.nom_position)
        positions_qn.append(mapping.qn_token_position)
    if any(pos < 0 for pos in positions_nom + positions_qn):
        # Negative positions make set-level order checks meaningless.
        return issues
    if len(set(positions_nom)) != len(positions_nom):
        dupes = sorted({p for p in positions_nom if positions_nom.count(p) > 1})
        issues.append(f"duplicate Nôm positions in mapping set: {dupes}")
    if len(set(positions_qn)) != len(positions_qn):
        dupes = sorted({p for p in positions_qn if positions_qn.count(p) > 1})
        issues.append(f"duplicate QN token positions in mapping set: {dupes}")
    if positions_nom != sorted(positions_nom):
        issues.append("mapping set is not monotone in Nôm positions")
    if positions_qn != sorted(positions_qn):
        issues.append("mapping set is not monotone in QN token positions")
    return issues


def validate_mappings_against_text(
    mappings: Iterable[CharacterTokenMapping], ch_txt: str, vi_txt: str
) -> list[str]:
    """Validate a mapping set against a specific row (Issue D, row-bound).

    Every mapping must bind the character standing at its declared Nôm
    position and the token standing at its declared QN token position.
    All errors from both levels (set and row-bound) are returned so
    callers can report them; the all-or-nothing guarantee lives in the
    learning path, which checks *all* errors before applying any change.
    """
    items = list(mappings)
    issues = validate_mapping_set(items)
    nom_positions = _nom_char_positions(ch_txt)
    tokens = _qn_token_items(vi_txt)
    for index, mapping in enumerate(items):
        try:
            if mapping.nom_position >= 0 and mapping.nom_position < len(nom_positions):
                ch_at = unicodedata.normalize("NFC", ch_txt[nom_positions[mapping.nom_position]])
                if ch_at != unicodedata.normalize("NFC", mapping.nom_char):
                    issues.append(
                        f"mapping {index}: nom_char {mapping.nom_char!r} does not match "
                        f"the Nôm character at position {mapping.nom_position}"
                    )
            elif mapping.nom_position >= len(nom_positions):
                issues.append(f"mapping {index}: nom_position out of bounds")
            token_position = mapping.qn_token_position
            if token_position >= 0 and token_position < len(tokens):
                token_text = normalize_token(tokens[token_position].group(0))
                if token_text != normalize_token(mapping.qn_token):
                    issues.append(
                        f"mapping {index}: qn_token {mapping.qn_token!r} does not match "
                        f"the QN token at position {mapping.qn_token_position}"
                    )
            elif token_position >= len(tokens):
                issues.append(f"mapping {index}: qn_token_position out of bounds")
        except (TypeError, AttributeError, ValueError):
            issues.append(f"mapping {index}: malformed mapping entry")
    return issues


def validate_mapping_evidence(
    mappings: Iterable[CharacterTokenMapping],
    ch_txt: str | None = None,
    vi_txt: str | None = None,
) -> list[str]:
    """Single validation entry point used everywhere (Issue D)."""
    items = list(mappings)
    if ch_txt is None or vi_txt is None:
        return validate_mapping_set(items)
    return validate_mappings_against_text(items, ch_txt, vi_txt)


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
    # Set-level positional validation (Issue D): duplicate positions and
    # non-monotone sets are structural errors even without row content.
    issues.extend(validate_mapping_set(decision.character_token_mappings))
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
    # Row-bound evidence validation (Issue D): the whole mapping set must
    # agree with the row content before the decision may be persisted.
    if not issues:
        issues = validate_mappings_against_text(items, ch_txt, vi_txt)
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


def read_decisions(
    path: str | Path,
) -> tuple[list[ReviewDecision], list[str]]:
    """Parse the decision log.

    Returns (valid decisions, issues). Malformed records are never
    silently skipped; ``parse_decisions`` exposes the structured failure
    detail used by callers that must attribute failures to rows.
    """
    decisions, _failures, issues = parse_decisions(path)
    return decisions, issues


@dataclass
class DecisionFailure:
    """A record that could not be used, tagged for attribution."""

    line: int
    sentence_id: str | None
    error: str


def parse_decisions(
    path: str | Path,
) -> tuple[list[ReviewDecision], list[DecisionFailure], list[str]]:
    """Parse the log into (valid decisions, failures, human-readable issues).

    ``failures`` preserves the positional context needed to route
    row-specific integrity failures: failures whose ``sentence_id`` is
    known affect only that row; failures with ``sentence_id is None`` are
    log-wide and disable use of the log for safety.
    """
    path = Path(path)
    decisions: list[ReviewDecision] = []
    failures: list[DecisionFailure] = []
    issues: list[str] = []

    def _failure(line: int, sentence_id: str | None, code: str, error: str) -> None:
        failures.append(DecisionFailure(line=line, sentence_id=sentence_id, error=f"{code}: {error}"))
        issues.append(f"{code}:{path.name}:{line}:{error}")

    if not path.exists():
        # No decisions yet is a normal state, not an integrity failure.
        return decisions, failures, issues
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            _failure(lineno, None, "DECISION_JSON_ERROR", exc.msg)
            continue
        if not isinstance(data, dict):
            _failure(lineno, None, "DECISION_NOT_OBJECT", "record is not a JSON object")
            continue
        try:
            decision = ReviewDecision.from_dict(data)
        except (TypeError, ValueError) as exc:
            sid = str(data.get("sentence_id", "")).strip() or None
            _failure(lineno, sid, "DECISION_SCHEMA_ERROR", str(exc))
            continue
        errs = validate_decision(decision)
        if errs:
            sid = decision.sentence_id.strip() or None
            _failure(lineno, sid, "DECISION_INVALID", "|".join(errs))
            continue
        # Track the append position so valid and invalid records can be
        # replayed in true file order by apply_decisions. Not serialized.
        setattr(decision, "log_line", lineno)
        decisions.append(decision)
    return decisions, failures, issues


def _row_hash(row: AlignmentRow) -> str:
    return content_sha256(row.ch_txt, row.vi_txt, row.text_diff_json())


def _incompatible_transition(
    prev: ReviewDecision, effective: ReviewDecision
) -> str | None:
    """Genuine same-content contradiction, or None for legitimate transitions.

    Ordinary chronological transitions (unresolved → accepted_match,
    content_edited → unmatched, ...) are legitimate. Two valid decisions on
    the same content revision are incompatible when either:

    - they are ``accepted_match`` vs ``accepted_difference`` — the texts
      either differ or do not, the assertions are mutually exclusive; or
    - their mapping sets assign the same Nôm position to different
      (QN token, position) pairs.
    """
    pair = {prev.status, effective.status}
    if pair == {STATUS_ACCEPTED_MATCH, STATUS_ACCEPTED_DIFFERENCE}:
        return f"{prev.status}->{effective.status} (mutually exclusive same-revision verdicts)"
    prev_map = {
        m.nom_position: (normalize_token(m.qn_token), m.qn_token_position)
        for m in prev.character_token_mappings
    }
    eff_map = {
        m.nom_position: (normalize_token(m.qn_token), m.qn_token_position)
        for m in effective.character_token_mappings
    }
    for position in sorted(set(prev_map) & set(eff_map)):
        if prev_map[position] != eff_map[position]:
            return (
                f"same Nôm position {position} mapped to "
                f"{prev_map[position]} then {eff_map[position]}"
            )
    return None


def apply_decisions(
    rows: list[AlignmentRow],
    decisions: Iterable[ReviewDecision],
    decision_issues: Iterable[str] | None = None,
    *,
    failures: Iterable[DecisionFailure] | None = None,
) -> tuple[list[AlignmentRow], list[str]]:
    """Overlay review decisions onto rows.

    Returns the rows (modified in place) and a list of integrity issues.

    Selection: for each ``sentence_id`` every record (valid or not) is
    replayed in true append (file) order; the **state after the latest
    event** determines the row::

        latest event valid + hash matches row → ``valid``   (row verified as decided)
        latest event stale                  → ``stale``   (row not verified)
        latest event invalid                → ``invalid`` (row not verified, NO fallback)
        latest valid event conflicts with an earlier
        same-revision valid decision        → ``conflict`` (row not verified)

    Superseded historical records never produce active issues — a newer
    decision legitimately replaces them while the history is kept in the
    log for audit. ``log_line`` injected by ``parse_decisions`` is used
    to order events; records lacking provenance sort first.
    """
    issues: list[str] = list(decision_issues or [])
    failure_by_sid: dict[str, list[DecisionFailure]] = {}
    for failure in failures or []:
        if failure.sentence_id:
            failure_by_sid.setdefault(failure.sentence_id, []).append(failure)
    groups: dict[str, list[ReviewDecision]] = {}
    for decision in decisions:
        groups.setdefault(decision.sentence_id, []).append(decision)
    for row in rows:
        sid = row.sentence_id
        group = groups.get(sid, [])
        row_failures = failure_by_sid.get(sid, [])
        row.review_status = None
        row.review_reviewer = None
        row.character_token_mappings = []
        row.decision_integrity = None  # type: ignore[attr-defined]
        # Drop flags previously produced by decision application; this run
        # recomputes them from the log.
        row.flags = sorted(
            flag
            for flag in set(row.flags)
            if not flag.startswith("REVIEW_STATUS_")
            and not flag.startswith("REVIEW_DECISION_")
        )
        if not group and not row_failures:
            continue
        # Replay every event in its true file order. A later record may
        # supersede an earlier one, regardless of whether either record
        # parsed correctly; the final state is what matters.
        events: list[tuple[int, str, Any]] = []
        for decision in group:
            events.append((int(getattr(decision, "log_line", 0)), "valid-record", decision))
        for failure in row_failures:
            events.append((failure.line, "failure", failure))
        events.sort(key=lambda item: item[0])
        row_hash = _row_hash(row)
        state: str | None = None
        status: str | None = None
        reviewer: str | None = None
        mappings: list[dict[str, Any]] = []
        applied_valid: list[ReviewDecision] = []
        for _line, kind, event in events:
            if kind == "failure":
                state, status, reviewer, mappings = "invalid", None, None, []
                continue
            errs = validate_decision(event)
            if errs:
                state, status, reviewer, mappings = "invalid", None, None, []
                continue
            if event.content_sha256 != row_hash:
                state, status, reviewer, mappings = "stale", None, None, []
                continue
            conflict = None
            for prev in reversed(applied_valid):
                if prev.content_sha256 != event.content_sha256:
                    continue
                conflict = _incompatible_transition(prev, event)
                if conflict:
                    break
            applied_valid.append(event)
            if conflict:
                state, status, reviewer, mappings = "conflict", None, None, []
            else:
                state = "valid"
                status = event.status
                reviewer = event.reviewer
                mappings = [m.to_dict() for m in event.character_token_mappings]
        if state is None:
            continue
        if state == "valid":
            row.review_status = status
            row.review_reviewer = reviewer
            row.character_token_mappings = mappings
            row.flags = sorted(set(row.flags) | {f"REVIEW_STATUS_{(status or '').upper()}"})
            row.decision_integrity = "valid"  # type: ignore[attr-defined]
            continue
        # Superseded history never raises an issue: only the latest state
        # is reported/active.
        flag = {
            "stale": REVIEW_DECISION_STALE_FLAG,
            "invalid": "REVIEW_DECISION_INVALID",
            "conflict": "REVIEW_DECISION_CONFLICT",
        }[state]
        row.flags = sorted(set(row.flags) | {flag})
        if state == "stale":
            issues.append(f"REVIEW_DECISION_STALE:{sid}")
        elif state == "invalid":
            detail = "; ".join(f.error for f in row_failures) or "invalid decision record"
            issues.append(f"REVIEW_DECISION_INVALID:{sid}:{detail}")
        else:
            issues.append(f"REVIEW_DECISION_CONFLICT:{sid}:{conflict or 'same-revision contradiction'}")
        row.decision_integrity = state  # type: ignore[attr-defined]
    return rows, issues
