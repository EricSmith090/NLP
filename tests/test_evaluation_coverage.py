"""Accuracy vs coverage separation (Issue D)."""

from __future__ import annotations

import pytest

from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow
from hannom.textdiff import make_element


def _row(sentence_id: str, ch: str, vi: str, elements, flags: tuple[str, ...] = ()) -> AlignmentRow:
    return AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=elements,
        flags=list(flags),
    )


def test_empty_diff_without_evidence_is_not_a_verified_match():
    metrics = evaluate_rows(
        "b",
        [_row("Book.001.1", "字字", "khác hẳn hẳn", [], ("DIFF_UNVERIFIED_NO_BOOK_READINGS",))],
    )
    assert metrics.verified_match_rows == 0
    assert metrics.unverified_rows == 1
    assert metrics.coverage_ratio == 0.0
    assert metrics.similarity is None
    assert not metrics.passed
    assert any("INSUFFICIENT_COVERAGE" in issue for issue in metrics.issues)
    assert any("UNVERIFIED_RATIO_HIGH" in issue for issue in metrics.issues)


def test_empty_diff_with_comparison_evidence_is_verified():
    metrics = evaluate_rows(
        "b",
        [_row("Book.001.1", "字字", "khác hẳn hẳn", [], ("DIFF_NO_READING_MISMATCH",))],
    )
    assert metrics.verified_match_rows == 1
    assert metrics.coverage_ratio == 1.0
    assert metrics.similarity == 100.0
    assert metrics.passed


def test_empty_diff_with_identical_texts_is_verified():
    metrics = evaluate_rows("b", [_row("Book.001.1", "字字", "字字", [], ())])
    assert metrics.verified_match_rows == 1
    assert metrics.passed


def test_null_rows_reduce_coverage_and_block_gate():
    rows = [_row(f"Book.001.{i}", "字", "chữ", [], ("DIFF_NO_READING_MISMATCH",)) for i in range(19)]
    rows.append(_row("Book.001.99", "字字", "hai", None))
    metrics = evaluate_rows("b", rows, null_ratio_warn=0.05)
    assert metrics.coverage_ratio == 0.95
    assert metrics.null_ratio == 0.05
    # 19/20 verified = 0.95 coverage; null ratio exactly at the warn
    # threshold, so the gate still passes on similarity alone.
    assert metrics.passed
    rows.append(_row("Book.001.98", "字字", "hai", None))
    metrics = evaluate_rows("b", rows, null_ratio_warn=0.05)
    assert metrics.null_ratio == pytest.approx(2 / 21)
    assert metrics.coverage_ratio == pytest.approx(19 / 21)
    assert any("EXCESSIVE_NULL_ROWS" in issue for issue in metrics.issues)
    assert not metrics.passed


def test_unverified_rows_block_gate_even_with_perfect_accuracy():
    rows = [_row(f"Book.001.{i}", "字", "字換", [], ("DIFF_NO_READING_MISMATCH",)) for i in range(18)]
    rows.append(_row("Book.001.97", "之", "cái khác", [], ("DIFF_UNVERIFIED_DIFFERENT_TEXT",)))
    rows.append(_row("Book.001.98", "其", "cái khác khác", [], ("DIFF_AMBIGUOUS_READINGS",)))
    metrics = evaluate_rows("b", rows, minimum_similarity=50.0)
    assert metrics.similarity == 100.0
    assert metrics.unverified_rows == 2
    assert any("UNVERIFIED_RATIO_HIGH" in issue for issue in metrics.issues)
    assert not metrics.passed


def test_unmatched_rows_are_counted_separately():
    rows = [
        _row("Book.001.1", "字", "chữ", [], ("DIFF_NO_READING_MISMATCH",)),
        _row("Book.001.2", "其其其", "", None, ("UNMATCHED_NOM", "NON_ONE_TO_ONE")),
        _row("Book.001.3", "", "câu tiếng", None, ("UNMATCHED_QN", "NON_ONE_TO_ONE")),
    ]
    metrics = evaluate_rows("b", rows)
    assert metrics.unmatched_rows == 2
    assert metrics.null_rows == 0
    assert metrics.coverage_ratio == 1 / 3


def test_unverified_difference_is_not_scored():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    row = _row("Book.001.1", "字字", "x", [error], ("COSEGMENTED_UNANCHORED",))
    metrics = evaluate_rows("b", [row])
    assert metrics.unverified_rows == 1
    assert metrics.scored_rows == 0
    assert metrics.red_mismatch_chars == 0


def test_coverage_ratio_is_reported():
    rows = [
        _row("Book.001.1", "字", "chữ", [], ("DIFF_NO_READING_MISMATCH",)),
        _row("Book.001.2", "字", "chữ", [], ("DIFF_NO_READING_MISMATCH",)),
        _row("Book.001.3", "字", "chữ", None),
        _row("Book.001.4", "字", "字換", [], ("DIFF_AMBIGUOUS_READINGS",)),
    ]
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 2
    assert metrics.null_rows == 1
    assert metrics.unverified_rows == 1
    assert metrics.coverage_ratio == 0.5


def test_verified_difference_counts_in_accuracy():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    rows = [
        _row("Book.001.1", "字字", "x", [error], ()),
        _row("Book.001.2", "字字", "hai chữ", [], ("DIFF_NO_READING_MISMATCH",)),
    ]
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_difference_rows == 1
    assert metrics.verified_match_rows == 1
    assert metrics.red_mismatch_chars == 2
    assert metrics.denominator == 4
    assert metrics.similarity == 50.0


def test_human_reviewed_rows_verify_even_with_ambiguity():
    rows = [_row("Book.001.1", "之", "thì thế", [], ("HUMAN_REVIEWED", "DIFF_AMBIGUOUS_READINGS"))]
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 1
    assert metrics.unverified_rows == 0
