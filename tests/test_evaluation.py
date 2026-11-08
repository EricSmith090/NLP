from __future__ import annotations

from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow
from hannom.textdiff import make_element


def row(sentence_id: str, ch: str, vi: str, elements=None) -> AlignmentRow:
    return AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=elements,
    )


def test_identical_row_scores_full_marks():
    metrics = evaluate_rows("b", [row("Book.001.1", "字字", "hai chữ", [])])
    assert metrics.similarity == 100.0
    assert metrics.passed


def test_red_penalty_uses_max_of_nom_chars_and_qn_syllables():
    error = make_element("字字", "x", [[0, 2]], [[0, 1]], "error")
    metrics = evaluate_rows("b", [row("Book.001.1", "字字", "x", [error])])
    assert metrics.red_mismatch_chars == 2
    assert metrics.denominator == 2
    assert metrics.similarity == 0.0
    assert not metrics.passed


def test_yellow_is_excluded_from_denominator_and_reported():
    warn = make_element("字字", "x", [[0, 1]], [], "warn")
    metrics = evaluate_rows("b", [row("Book.001.1", "字字", "x", [warn])])
    assert metrics.total_nom_chars == 2
    assert metrics.yellow_chars == 1
    assert metrics.denominator == 1
    assert metrics.yellow_ratio == 0.5
    assert metrics.similarity == 100.0


def test_null_rows_are_reported_but_not_scored():
    metrics = evaluate_rows(
        "b",
        [
            row("Book.001.1", "字", "chữ", []),
            row("Book.001.2", "字字", "hai", None),
        ],
    )
    assert metrics.total_rows == 2
    assert metrics.null_rows == 1
    assert metrics.null_ratio == 0.5
    assert metrics.scored_rows == 1
    assert metrics.denominator == 1


def test_duplicate_sentence_ids_fail_gate():
    metrics = evaluate_rows(
        "b",
        [
            row("Book.001.1", "字", "chữ", []),
            row("Book.001.1", "字", "chữ", []),
        ],
    )
    assert any("DUPLICATE_SENTENCE_ID" in issue for issue in metrics.issues)
    assert not metrics.passed


def test_gate_is_per_book_not_aggregate():
    metrics = evaluate_rows("b", [row("Book.001.1", "字", "x", [])], minimum_similarity=95.0)
    assert metrics.passed
