"""Stage 8: per-book evaluation and quality gates.

Accuracy is computed only over rows with explicit comparison evidence:

    (1 - mismatched_red_characters / scored_nom_characters) * 100

where the denominator only includes Nôm characters in verified rows and
excludes yellow-covered characters and ``[MASK]`` tokens. Coverage is the
fraction of rows that were verified; unverified, unmatched or null rows
never inflate accuracy and are reported separately. Insufficient
coverage, too many unverified rows or too many null rows block the gate.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from .clean import MASK, count_nom_chars, nfc
from .models import AlignmentRow, BookMetrics, DiffElement
from .textdiff import red_penalty, scoreable_nom_chars, validate_text_diff, yellow_spans


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
        "COSEGMENTED_UNANCHORED",
        "REVIEW_METADATA_MISSING",
        "REVIEW_METADATA_MISMATCH",
        "TEXT_DIFF_INVALID",
    }
)

BLOCKING_PREFIXES = (
    "DUPLICATE_SENTENCE_ID",
    "EMPTY_IMG_ID",
    "TEXT_DIFF",
    "INSUFFICIENT_COVERAGE",
    "UNVERIFIED_RATIO_HIGH",
    "EXCESSIVE_NULL_ROWS",
)


def _classify_row(flags: set[str], elements: list[DiffElement] | None) -> str:
    if "HUMAN_REVIEWED" in flags:
        # Human sign-off is trusted evidence; it verifies either state.
        return "verified_match" if not elements else "verified_difference"
    if "UNMATCHED_NOM" in flags or "UNMATCHED_QN" in flags:
        return "unmatched"
    if elements is None:
        return "null"
    if flags & UNVERIFIED_FLAGS:
        return "unverified"
    if elements:
        return "verified_difference"
    return "verified_match"


def evaluate_rows(
    book_id: str,
    rows: Iterable[Any],
    *,
    minimum_similarity: float = 95.0,
    null_ratio_warn: float = 0.05,
    yellow_ratio_warn: float = 0.05,
    minimum_coverage: float = 0.9,
    max_unverified_ratio: float = 0.05,
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
    """
    rows = list(rows)
    metrics = BookMetrics(book_id=book_id, total_rows=len(rows))
    if not rows:
        metrics.issues.append("NO_ROWS")
        metrics.passed = False
        return metrics

    seen_sentence_ids: set[str] = set()
    unverified_different = 0
    invalid = 0
    for row in rows:
        img_id = str(_row_value(row, "img_id", ""))
        sentence_id = str(_row_value(row, "sentence_id", ""))
        ch_txt = nfc(str(_row_value(row, "ch_txt", "")))
        vi_txt = nfc(str(_row_value(row, "vi_txt", "")))
        elements = _elements(row)
        flags = {str(flag) for flag in (_row_value(row, "flags", []) or [])}
        metrics.total_nom_chars += count_nom_chars(ch_txt)
        if sentence_id:
            if sentence_id in seen_sentence_ids:
                metrics.issues.append(f"DUPLICATE_SENTENCE_ID:{sentence_id}")
            seen_sentence_ids.add(sentence_id)
        if not img_id:
            metrics.issues.append(f"EMPTY_IMG_ID:{sentence_id}")
        if elements is not None:
            issues = validate_text_diff(ch_txt, vi_txt, elements)
            if issues:
                invalid += 1
                metrics.issues.extend(f"TEXT_DIFF:{sentence_id}:{issue}" for issue in issues[:3])
        classification = _classify_row(flags, elements)
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
