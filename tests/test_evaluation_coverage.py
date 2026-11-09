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


def test_content_edited_row_without_evidence_does_not_verify():
    # A human edited the row's content but did not verify the alignment:
    # machine evidence decides, and there is none here.
    rows = [
        _row(
            "Book.001.1",
            "之",
            "cái khác hẳn",
            [],
            ("CONTENT_EDITED", "DIFF_UNVERIFIED_NO_BOOK_READINGS"),
        )
    ]
    rows[0].review_status = "content_edited"
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert metrics.verified_match_rows == 0
    assert not metrics.passed


def test_content_edited_row_with_machine_evidence_may_verify():
    rows = [
        _row(
            "Book.001.1",
            "之",
            "cái khác",
            [],
            ("CONTENT_EDITED", "DIFF_NO_READING_MISMATCH"),
        )
    ]
    rows[0].review_status = "content_edited"
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 1


def test_null_row_with_accepted_match_does_not_verify():
    rows = [_row("Book.001.1", "之", "cái", None, ())]
    rows[0].review_status = "accepted_match"
    rows[0].decision_integrity = "valid"  # contradictory: no evidence
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert metrics.verified_match_rows == 0
    assert any("REVIEW_DECISION_MISMATCH" in issue for issue in metrics.issues)
    assert not metrics.passed


def test_unmatched_nom_row_with_content_edit_remains_unmatched():
    rows = [_row("Book.001.1", "其其其", "", None, ("UNMATCHED_NOM", "NON_ONE_TO_ONE", "CONTENT_EDITED"))]
    rows[0].review_status = "content_edited"
    metrics = evaluate_rows("b", rows)
    assert metrics.unmatched_rows == 1
    assert metrics.verified_match_rows == 0


def test_unmatched_qn_row_with_content_edit_remains_unmatched():
    rows = [_row("Book.001.2", "", "một câu hoàn toàn khác", None, ("UNMATCHED_QN", "NON_ONE_TO_ONE", "CONTENT_EDITED"))]
    rows[0].review_status = "content_edited"
    metrics = evaluate_rows("b", rows)
    assert metrics.unmatched_rows == 1


def test_explicit_unmatched_decision_is_unmatched():
    rows = [_row("Book.001.3", "其其", "khác hẳn", None, ())]
    rows[0].review_status = "unmatched"
    rows[0].decision_integrity = "valid"
    metrics = evaluate_rows("b", rows)
    assert metrics.unmatched_rows == 1


def test_accepted_match_with_valid_evidence_is_verified():
    rows = [_row("Book.001.1", "之", "thì", [], ("DIFF_UNVERIFIED_NO_BOOK_READINGS",))]
    rows[0].review_status = "accepted_match"
    rows[0].decision_integrity = "valid"  # consistent: no discrepancy
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 1
    assert metrics.unverified_rows == 0


def test_accepted_difference_with_valid_spans_is_verified():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    rows = [_row("Book.001.1", "字字", "x", [error], ("DIFF_UNVERIFIED_DIFFERENT_TEXT",))]
    rows[0].review_status = "accepted_difference"
    rows[0].decision_integrity = "valid"
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_difference_rows == 1
    assert metrics.denominator == 2


def test_accepted_difference_with_empty_diff_is_mismatch():
    rows = [_row("Book.001.1", "之", "thì", [], ())]
    rows[0].review_status = "accepted_difference"
    rows[0].decision_integrity = "valid"  # says differences exist; there are none
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert any("REVIEW_DECISION_MISMATCH" in issue for issue in metrics.issues)


def test_accepted_match_with_nonempty_diff_is_mismatch():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    rows = [_row("Book.001.1", "字字", "x", [error], ())]
    rows[0].review_status = "accepted_match"
    rows[0].decision_integrity = "valid"  # says no discrepancy; there is one
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert any("REVIEW_DECISION_MISMATCH" in issue for issue in metrics.issues)
    assert not metrics.passed


def test_review_decision_stale_flag_prevents_verification():
    rows = [_row("Book.001.1", "之", "thì", [], ("REVIEW_DECISION_STALE",))]
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1


def test_unresolved_decision_is_unverified():
    rows = [_row("Book.001.1", "之", "thì", [], ())]
    rows[0].review_status = "unresolved"
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1


def test_evidence_insufficient_flag_is_unverified():
    rows = [
        _row("Book.001.1", "之", "về vấn đề này khác hẳn", [], ("ALIGN_EVIDENCE_INSUFFICIENT",))
    ]
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1


def _reload_with_patches(tmp_path, name: str, rows, patches):
    from hannom.align import write_alignment_csv
    from hannom.review_metadata import load_rows_with_metadata
    from hannom.review.patches import apply_patches

    csv_path = tmp_path / f"{name}.csv"
    write_alignment_csv(csv_path, rows)
    restored, _ = load_rows_with_metadata(csv_path)
    return apply_patches(restored, patches)


def test_edit_only_nom_transcription_does_not_accept_alignment(tmp_path):
    from hannom.review.patches import ReviewPatch

    rows = [_row("Book.001.1", "之其", "thì thế", None, ("NON_ONE_TO_ONE",))]
    patches = [
        ReviewPatch(
            book_id="Book",
            sentence_id="Book.001.1",
            field="ch_txt",
            before="之其",
            after="其之",
            reviewer="tester",
            reason="fix scan order",
        )
    ]
    applied = _reload_with_patches(tmp_path, "book_nom_edit", rows, patches)
    (row,) = applied
    assert "CONTENT_EDITED" in row.flags
    assert row.review_status is None  # never auto-accepted
    metrics = evaluate_rows("b", applied)
    assert metrics.verified_match_rows == 0
    assert metrics.verified_difference_rows == 0


def test_edit_only_qn_transcription_does_not_accept_alignment(tmp_path):
    from hannom.review.patches import ReviewPatch

    rows = [_row("Book.001.2", "之其", "thì thế", None, ("NON_ONE_TO_ONE",))]
    patches = [
        ReviewPatch(
            book_id="Book",
            sentence_id="Book.001.2",
            field="vi_txt",
            before="thì thế",
            after="thì thế đó",
            reviewer="tester",
            reason="add missing word",
        )
    ]
    applied = _reload_with_patches(tmp_path, "book_vi_edit", rows, patches)
    (row,) = applied
    assert "CONTENT_EDITED" in row.flags
    assert row.review_status is None
    metrics = evaluate_rows("b", applied)
    assert metrics.verified_match_rows == 0


def test_alignment_reviewed_with_valid_evidence_is_verified():
    rows = [_row("Book.001.1", "之", "thì", [], ("DIFF_UNVERIFIED_NO_BOOK_READINGS",))]
    rows[0].review_status = "alignment_reviewed"
    rows[0].decision_integrity = "valid"
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 1


def test_alignment_reviewed_with_differences_is_verified_difference():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    rows = [_row("Book.001.1", "字字", "x", [error], ())]
    rows[0].review_status = "alignment_reviewed"
    rows[0].decision_integrity = "valid"
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_difference_rows == 1


def test_alignment_reviewed_without_comparison_evidence_stays_unverified():
    rows = [_row("Book.001.1", "之", "thì", None, ())]
    rows[0].review_status = "alignment_reviewed"
    rows[0].decision_integrity = "valid"
    metrics = evaluate_rows("b", rows)
    assert metrics.unverified_rows == 1
    assert any("REVIEW_DECISION_MISMATCH" in issue for issue in metrics.issues)


def test_existing_automatic_verification_still_works():
    rows = [_row("Book.001.1", "字字", "hai chữ", [], ("DIFF_NO_READING_MISMATCH",))]
    metrics = evaluate_rows("b", rows)
    assert metrics.verified_match_rows == 1
    assert metrics.passed
