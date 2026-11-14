"""Sidecar review metadata for alignment CSV rows.

The alignment CSV keeps the stable five-column schema
``img_id, sentence_id, ch_txt, vi_txt, text_diff`` for downstream
compatibility. Flags, confidence and other review-relevant information
therefore live in a sibling JSON Lines file

    <Name>.review_metadata.jsonl

next to the CSV. Each line is a JSON object with::

    {
        "schema": 1,
        "sentence_id": "<stable row id>",
        "img_id": "<image name>",
        "flags": ["..."],
        "confidence": 0.83 | null,
        "semantic_confidence": 1.0 | 0.0 | null,
        "content_sha256": "<sha256 of ch_txt, vi_txt and text_diff>"
    }

Rules enforced here:

- Missing sidecar files are reported, and every row lacking metadata is
  flagged ``REVIEW_METADATA_MISSING``. Absent metadata is never silently
  read as "clean row".
- Duplicated, stale or mismatched entries are reported as ``METADATA_*``
  issues and the affected rows are flagged ``REVIEW_METADATA_MISMATCH``.
- Sidecar writes are atomic (temp file in the destination directory,
  flush+fsync, ``os.replace``); a failed write preserves the previous
  sidecar.
- The sidecar ``schema`` must equal ``1``; confidence values must be
  real numbers (not booleans), finite, and inside ``[0, 1]``. Records
  failing validation are dropped and reported as ``METADATA_*`` issues.
- Restored rows keep any flags set in memory; the sidecar contributes the
  authoritative persisted flags and confidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from pathlib import Path
from typing import Any, Iterable

from .models import AlignmentRow
from .review_decisions import content_sha256

SIDECAR_SUFFIX = ".review_metadata.jsonl"
SCHEMA = 1

MISSING_FLAG = "REVIEW_METADATA_MISSING"
MISMATCH_FLAG = "REVIEW_METADATA_MISMATCH"
UNRESOLVED_FLAG = "REVIEW_METADATA_UNRESOLVED"


def sidecar_path(csv_path: str | Path) -> Path:
    path = Path(csv_path)
    if path.suffix.lower() == ".csv":
        return path.with_suffix(SIDECAR_SUFFIX)
    return path.parent / (path.name + SIDECAR_SUFFIX)


def _content_sha256(row: AlignmentRow) -> str:
    # Single implementation lives in hannom.review_decisions; keep this
    # wrapper for backwards compatibility with callers that used it.
    return content_sha256(row.ch_txt, row.vi_txt, row.text_diff_json())


def _confidence_error(value: Any, field: str = "confidence") -> str | None:
    """Return an error string for invalid confidence-like values, else None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{field} has type {type(value).__name__}"
    number = float(value)
    if not math.isfinite(number):
        return f"{field} is not finite"
    if number < 0.0 or number > 1.0:
        return f"{field} {number} outside [0, 1]"
    return None


def row_metadata_record(row: AlignmentRow) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "sentence_id": row.sentence_id,
        "img_id": row.img_id,
        "flags": sorted(set(row.flags)),
        "confidence": row.confidence,
        # Semantic evidence confidence is persisted separately from the
        # structural ``confidence`` field; ``None`` means "no evidence"
        # and stays distinguishable from a measured 0.0.
        "semantic_confidence": getattr(row, "semantic_confidence", None),
        "content_sha256": _content_sha256(row),
    }


def write_review_metadata(csv_path: str | Path, rows: Iterable[AlignmentRow]) -> Path:
    """Serialize the sidecar atomically.

    A temporary file in the destination directory is flushed and closed,
    then moved onto the destination with ``os.replace``; on any failure
    the temporary file is removed and the previous sidecar is preserved.
    """
    path = sidecar_path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    for row in rows:
        err = _confidence_error(row.confidence)
        if err is not None:
            raise ValueError(f"{row.sentence_id}: invalid confidence for sidecar: {err}")
        sem_err = _confidence_error(getattr(row, "semantic_confidence", None), "semantic_confidence")
        if sem_err is not None:
            raise ValueError(f"{row.sentence_id}: invalid confidence for sidecar: {sem_err}")
    temp = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as fh:
            for row in rows:
                fh.write(json.dumps(row_metadata_record(row), ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def load_review_metadata(path: str | Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Parse the sidecar; duplicates keep the first record and are reported."""
    records: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    sidecar = Path(path)
    if not sidecar.exists():
        issues.append(f"METADATA_SIDECAR_MISSING:{sidecar.name}")
        return records, issues
    for lineno, raw in enumerate(sidecar.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(f"METADATA_JSON_ERROR:{sidecar.name}:{lineno}:{exc.msg}")
            continue
        if not isinstance(record, dict):
            issues.append(f"METADATA_NOT_OBJECT:{sidecar.name}:{lineno}")
            continue
        schema = record.get("schema")
        if schema != SCHEMA:
            issues.append(f"METADATA_SCHEMA_UNSUPPORTED:{sidecar.name}:{lineno}:schema={schema!r}")
            continue
        sentence_id = str(record.get("sentence_id", "")).strip()
        if not sentence_id:
            issues.append(f"METADATA_MISSING_SENTENCE_ID:{sidecar.name}:{lineno}")
            continue
        conf_err = _confidence_error(record.get("confidence"))
        if conf_err is not None:
            issues.append(f"METADATA_BAD_CONFIDENCE:{sidecar.name}:{lineno}:{conf_err}")
            continue
        sem_err = _confidence_error(record.get("semantic_confidence"), "semantic_confidence")
        if sem_err is not None:
            issues.append(f"METADATA_BAD_CONFIDENCE:{sidecar.name}:{lineno}:{sem_err}")
            continue
        if sentence_id in records:
            issues.append(f"METADATA_DUPLICATE:{sentence_id}")
            continue
        records[sentence_id] = record
    return records, issues


def restore_review_metadata(
    csv_path: str | Path,
    rows: list[AlignmentRow],
) -> tuple[list[AlignmentRow], list[str]]:
    """Merge sidecar flags/confidence into CSV-loaded rows.

    Returns the rows (modified in place) and a list of ``METADATA_*``
    issues. Every row missing usable metadata is flagged
    ``REVIEW_METADATA_MISSING`` and therefore can never silently read as
    a clean row.
    """
    path = sidecar_path(csv_path)
    records, issues = load_review_metadata(path)
    known_ids = set()
    for row in rows:
        known_ids.add(row.sentence_id)
        record = records.get(row.sentence_id)
        flags = list(row.flags)
        if record is None:
            issues.append(f"METADATA_MISSING:{row.sentence_id}")
            if MISSING_FLAG not in flags:
                flags.append(MISSING_FLAG)
            row.flags = sorted(set(flags))
            continue
        rec_img = str(record.get("img_id", ""))
        if rec_img != row.img_id:
            issues.append(f"METADATA_MISMATCH_IMG:{row.sentence_id}")
            flags.append(MISMATCH_FLAG)
        rec_sha = str(record.get("content_sha256", ""))
        if not rec_sha and record.get("text_diff_sha256"):
            # Legacy single-field hash (diff only); still validate what we can.
            rec_sha = str(record.get("text_diff_sha256"))
            legacy = True
        else:
            legacy = False
        if rec_sha:
            if legacy:
                # Legacy records hashed the diff JSON alone.
                expected = hashlib.sha256(row.text_diff_json().encode("utf-8")).hexdigest()
            else:
                expected = _content_sha256(row)
            if rec_sha != expected:
                issues.append(f"METADATA_MISMATCH_DIFF:{row.sentence_id}")
                flags.append(MISMATCH_FLAG)
        rec_flags = record.get("flags")
        if isinstance(rec_flags, list):
            flags.extend(str(flag) for flag in rec_flags)
        confidence = record.get("confidence")
        if confidence is not None:
            try:
                row.confidence = float(confidence)
            except (TypeError, ValueError):
                issues.append(f"METADATA_BAD_CONFIDENCE:{row.sentence_id}")
                flags.append(UNRESOLVED_FLAG)
        # Semantic confidence: absent legacy key → untouched (None), never invented.
        if "semantic_confidence" in record:
            sem = record.get("semantic_confidence")
            if sem is None:
                row.semantic_confidence = None
            else:
                sem_err = _confidence_error(sem, "semantic_confidence")
                if sem_err is None:
                    row.semantic_confidence = float(sem)
                else:
                    issues.append(f"METADATA_BAD_CONFIDENCE:{row.sentence_id}:{sem_err}")
                    flags.append(UNRESOLVED_FLAG)
        row.flags = sorted(set(flags))
    for sentence_id in sorted(set(records) - known_ids):
        issues.append(f"METADATA_STALE:{sentence_id}")
    return rows, issues


def load_rows_with_metadata(
    csv_path: str | Path,
) -> tuple[list[AlignmentRow], list[str]]:
    from .align import read_alignment_csv

    rows = read_alignment_csv(csv_path)
    return restore_review_metadata(csv_path, rows)
