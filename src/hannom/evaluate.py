"""Stage 8: per-book evaluation and quality gates.

Accuracy is computed only over rows with explicit comparison evidence:

    (1 - mismatched_red_characters / scored_nom_characters) * 100

where the denominator only includes Nôm characters in verified rows and
excludes yellow-covered characters and ``[MASK]`` tokens. Coverage is the
fraction of rows that were verified; unverified, unmatched or null rows
never inflate accuracy and are reported separately. Insufficient
coverage, too many unverified rows, too many null rows, or any metadata /
review-decision integrity failure block the gate.

Human review can resolve uncertainty, but only through an explicit,
non-stale review decision recorded in the decision log; a content edit
alone never verifies a row.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .clean import MASK, count_nom_chars, nfc
from .models import AlignmentRow, BookMetrics, DiffElement
from .textdiff import red_penalty, scoreable_nom_chars, validate_text_diff, yellow_spans
from .review_decisions import (
    STATUS_ACCEPTED_DIFFERENCE,
    STATUS_ACCEPTED_MATCH,
    STATUS_ALIGNMENT_REVIEWED,
    STATUS_CONTENT_EDITED,
    STATUS_REJECTED,
    STATUS_UNMATCHED,
    STATUS_UNRESOLVED,
)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _elements(row: Any) -> list[DiffElement] | None:
    value = _row_value(row, "text_diff", None)
    if value is None:
        return None
    if isinstance(value, list):
        out: list[DiffElement] = []
        for item in value:
            if isinstance(item, DiffElement):
                out.append(item)
            elif isinstance(item, dict):
                out.append(
                    DiffElement(
                        nom_pos=tuple(tuple(int(x) for x in p) for p in item.get("nom_pos", [])),
                        nom_sub_text=str(item.get("nom_sub_text", "")),
                        vi_pos=tuple(tuple(int(x) for x in p) for p in item.get("vi_pos", [])),
                        vi_sub_text=str(item.get("vi_sub_text", "")),
                        type=str(item.get("type", "error")),  # type: ignore[arg-type]
                    )
                )
        return out
    raise ValueError(f"text_diff must be a list or null, got {type(value).__name__}")


UNVERIFIED_FLAGS = frozenset(
    {
        "DIFF_UNVERIFIED_NO_BOOK_READINGS",
        "DIFF_UNVERIFIED_DIFFERENT_TEXT",
        "DIFF_AMBIGUOUS_READINGS",
        "REVIEW_METADATA_MISSING",
        "REVIEW_METADATA_MISMATCH",
        "REVIEW_METADATA_UNRESOLVED",
        "TEXT_DIFF_INVALID",
        "ALIGN_EVIDENCE_INSUFFICIENT",
        # Set when --force-recompute re-scores a row whose stored text_diff
        # was null. Re-scored rows are never auto-verified through recompute.
        "ALIGN_FORCE_RECOMPUTED_FROM_NULL",
        "REVIEW_DECISION_STALE",
        "REVIEW_DECISION_MISMATCH",
        "REVIEW_DECISION_INVALID",
        "REVIEW_DECISION_CONFLICT",
    }
)

BLOCKING_PREFIXES = (
    "DUPLICATE_SENTENCE_ID",
    "EMPTY_IMG_ID",
    "TEXT_DIFF",
    "INSUFFICIENT_COVERAGE",
    "UNVERIFIED_RATIO_HIGH",
    "EXCESSIVE_NULL_ROWS",
    "METADATA_",
    "REVIEW_METADATA_",
    "REVIEW_DECISION_",
    "DECISION_",
)

_NON_REVIEWING_DECISION_STATUSES = frozenset(
    {STATUS_UNRESOLVED, STATUS_REJECTED}
)


def _classify_row(
    flags: set[str],
    elements: list[DiffElement] | None,
    review_status: str | None,
    elements_valid: bool,
    decision_integrity: str | None = None,
) -> tuple[str, str | None]:
    """Classify a row; returns (classification, contradiction_issue or None).

    Precedence: explicit, non-stale human decisions first (they may
    resolve an unmatched row), then automatic, flag-based evidence.
    """
    if review_status == STATUS_UNMATCHED:
        if decision_integrity != "valid":
            return "unverified", None
        return "unmatched", None
    if review_status in (
        STATUS_ALIGNMENT_REVIEWED,
        STATUS_ACCEPTED_MATCH,
        STATUS_ACCEPTED_DIFFERENCE,
    ):
        # The decision must come from the sound part of the log (Issue B);
        # a verifying status alone is never enough.
        if decision_integrity != "valid":
            return "unverified", None
        if elements is None:
            return "unverified", "REVIEW_DECISION_MISMATCH"
        if not elements_valid:
            return "unverified", "REVIEW_DECISION_MISMATCH"
        if review_status == STATUS_ACCEPTED_MATCH:
            if elements:
                return "unverified", "REVIEW_DECISION_MISMATCH"
            return "verified_match", None
        if review_status == STATUS_ACCEPTED_DIFFERENCE:
            if not elements:
                return "unverified", "REVIEW_DECISION_MISMATCH"
            return "verified_difference", None
        # alignment_reviewed: correspondence verified explicitly; the
        # validity of the recorded difference elements decides the side.
        return ("verified_match" if not elements else "verified_difference"), None
    if review_status in _NON_REVIEWING_DECISION_STATUSES:
        return "unverified", None
    if review_status == STATUS_CONTENT_EDITED:
        # An edit grants nothing; fall through to automatic evidence.
        pass
    # Automatic classification.
    if "UNMATCHED_NOM" in flags or "UNMATCHED_QN" in flags:
        return "unmatched", None
    if elements is None:
        return "null", None
    if not elements_valid:
        return "unverified", None
    if flags & UNVERIFIED_FLAGS:
        return "unverified", None
    if elements:
        return "verified_difference", None
    return "verified_match", None


def evaluate_rows(
    book_id: str,
    rows: Iterable[Any],
    *,
    minimum_similarity: float = 95.0,
    null_ratio_warn: float = 0.05,
    yellow_ratio_warn: float = 0.05,
    minimum_coverage: float = 0.9,
    max_unverified_ratio: float = 0.05,
    integrity_issues: Iterable[str] | None = None,
    audit_diagnostics: Iterable[str] | None = None,
) -> BookMetrics:
    """Score verified comparisons and report accuracy vs coverage separately.

    Accuracy (``similarity``) is computed only over rows with explicit
    comparison evidence. Coverage is the fraction of rows that were
    verified. Missing evidence never improves the score: unverified rows
    reduce coverage, and insufficient coverage, too many unverified rows
    or too many null rows block the gate. Threshold defaults are project
    policy, configurable via ``configs/project.yaml`` ``quality:``; they
    are deliberately conservative (0.9 coverage, 0.05 unverified/null)
    and may be tuned per book by the instructor.

    ``integrity_issues`` are loader-level integrity failures (metadata
    sidecar or review-decision log) that must block the gate the same as
    row-level issues, whether or not their affected rows can be
    identified.
    """
    rows = list(rows)
    metrics = BookMetrics(book_id=book_id, total_rows=len(rows))
    metrics.decision_audit_diagnostics = [str(item) for item in audit_diagnostics or []]
    for issue in integrity_issues or []:
        text = str(issue)
        if not any(text.startswith(prefix) for prefix in BLOCKING_PREFIXES):
            # Loader issues are defects by definition; normalise so they
            # block the gate.
            text = f"METADATA_{text}" if not text.startswith("REVIEW_") else text
        if text not in metrics.issues:
            metrics.issues.append(text)
    if not rows:
        metrics.issues.append("NO_ROWS")
        metrics.passed = False
        return metrics

    seen_sentence_ids: set[str] = set()
    unverified_different = 0
    invalid = 0
    structural_values: list[float] = []
    semantic_evidence_rows = 0
    evidence_insufficient_rows = 0
    for row in rows:
        img_id = str(_row_value(row, "img_id", ""))
        sentence_id = str(_row_value(row, "sentence_id", ""))
        ch_txt = nfc(str(_row_value(row, "ch_txt", "")))
        vi_txt = nfc(str(_row_value(row, "vi_txt", "")))
        elements = _elements(row)
        flags = {str(flag) for flag in (_row_value(row, "flags", []) or [])}
        review_status = _row_value(row, "review_status", None)
        review_status = str(review_status) if review_status else None
        metrics.total_nom_chars += count_nom_chars(ch_txt)
        confidence = _row_value(row, "confidence", None)
        if confidence is not None:
            try:
                structural_values.append(float(confidence))
            except (TypeError, ValueError):
                pass
        semantic = _row_value(row, "semantic_confidence", None)
        if semantic is not None:
            semantic_evidence_rows += 1
        if "ALIGN_EVIDENCE_INSUFFICIENT" in flags:
            evidence_insufficient_rows += 1
        if sentence_id:
            if sentence_id in seen_sentence_ids:
                metrics.issues.append(f"DUPLICATE_SENTENCE_ID:{sentence_id}")
            seen_sentence_ids.add(sentence_id)
        if not img_id:
            metrics.issues.append(f"EMPTY_IMG_ID:{sentence_id}")
        elements_valid = True
        if elements is not None:
            issues = validate_text_diff(ch_txt, vi_txt, elements)
            if issues:
                invalid += 1
                elements_valid = False
                metrics.issues.extend(f"TEXT_DIFF:{sentence_id}:{issue}" for issue in issues[:3])
        decision_integrity = _row_value(row, "decision_integrity", None)
        decision_integrity = str(decision_integrity) if decision_integrity else None
        classification, contradiction = _classify_row(
            flags, elements, review_status, elements_valid, decision_integrity
        )
        if contradiction:
            metrics.issues.append(f"{contradiction}:{sentence_id}")
        if classification == "unmatched":
            metrics.unmatched_rows += 1
            continue
        if classification == "null":
            metrics.null_rows += 1
            continue
        if classification == "unverified":
            metrics.unverified_rows += 1
            continue
        metrics.scored_rows += 1
        if classification == "verified_match":
            metrics.verified_match_rows += 1
        else:
            metrics.verified_difference_rows += 1
        yellow = sum(
            1
            for element in elements or []
            if element.type == "warn"
            for ch in element.nom_sub_text
            if ch not in MASK and count_nom_chars(ch)
        )
        metrics.yellow_chars += yellow
        metrics.red_mismatch_chars += red_penalty(elements)
        metrics.denominator += scoreable_nom_chars(ch_txt, elements)
        if (
            classification == "verified_match"
            and ch_txt != vi_txt
            and elements is not None
            and not elements
        ):
            unverified_different += 1

    verified = metrics.verified_match_rows + metrics.verified_difference_rows
    if metrics.total_rows:
        metrics.coverage_ratio = verified / metrics.total_rows
        metrics.null_ratio = metrics.null_rows / metrics.total_rows
    if semantic_evidence_rows:
        metrics.semantic_evidence_rows = semantic_evidence_rows
    else:
        metrics.semantic_evidence_rows = 0
    metrics.evidence_insufficient_rows = evidence_insufficient_rows
    if structural_values:
        metrics.structural_confidence_mean = sum(structural_values) / len(structural_values)
    else:
        metrics.structural_confidence_mean = None
    if metrics.total_nom_chars:
        metrics.yellow_ratio = metrics.yellow_chars / metrics.total_nom_chars
    if metrics.denominator > 0:
        metrics.similarity = (
            1.0 - metrics.red_mismatch_chars / metrics.denominator
        ) * 100.0
    else:
        metrics.similarity = None
        metrics.issues.append("EMPTY_DENOMINATOR")

    unverified_ratio = metrics.unverified_rows / metrics.total_rows if metrics.total_rows else 0.0
    coverage = metrics.coverage_ratio if metrics.coverage_ratio is not None else 0.0
    if coverage < minimum_coverage:
        metrics.issues.append(f"INSUFFICIENT_COVERAGE:{coverage:.4f}<{minimum_coverage}")
    if unverified_ratio > max_unverified_ratio:
        metrics.issues.append(f"UNVERIFIED_RATIO_HIGH:{unverified_ratio:.4f}>{max_unverified_ratio}")
    if metrics.null_ratio is not None and metrics.null_ratio > null_ratio_warn:
        metrics.issues.append(f"EXCESSIVE_NULL_ROWS:{metrics.null_ratio:.4f}>{null_ratio_warn}")
        metrics.warnings.append(f"NULL_ROW_RATIO_HIGH:{metrics.null_ratio:.4f}")
    if unverified_different:
        metrics.warnings.append(f"UNVERIFIED_DIFFERENT_ROWS:{unverified_different}")
    if invalid:
        metrics.warnings.append(f"INVALID_TEXT_DIFF_ROWS:{invalid}")
    if metrics.yellow_ratio is not None and metrics.yellow_ratio > yellow_ratio_warn:
        metrics.warnings.append(f"YELLOW_RATIO_HIGH:{metrics.yellow_ratio:.4f}")

    metrics.passed = bool(
        metrics.similarity is not None
        and metrics.similarity >= minimum_similarity
        and metrics.total_nom_chars > 0
        and metrics.scored_rows > 0
        and coverage >= minimum_coverage
        and unverified_ratio <= max_unverified_ratio
        and (metrics.null_ratio is None or metrics.null_ratio <= null_ratio_warn)
        and not any(
            issue.startswith(BLOCKING_PREFIXES) for issue in metrics.issues
        )
    )
    if metrics.similarity is not None and metrics.similarity < minimum_similarity:
        metrics.issues.append(
            f"SIMILARITY_BELOW_GATE:{metrics.similarity:.4f}<{minimum_similarity}"
        )
    return metrics


def metrics_from_dict(data: dict[str, Any]) -> BookMetrics:
    known = {field for field in BookMetrics.__dataclass_fields__}
    return BookMetrics(**{k: v for k, v in data.items() if k in known})


def metrics_to_dict(metrics: BookMetrics) -> dict[str, Any]:
    return asdict(metrics)


def overall_status(book_metrics: Iterable[BookMetrics]) -> dict[str, Any]:
    items = list(book_metrics)
    return {
        "books": [m.to_dict() for m in items],
        "all_passed": bool(items) and all(m.passed for m in items),
        "minimum_similarity": min(
            (m.similarity for m in items if m.similarity is not None),
            default=None,
        ),
    }
