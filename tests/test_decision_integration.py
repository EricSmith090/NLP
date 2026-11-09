"""End-to-end decision flow through the evaluation loader.

Simulates what ``stage_evaluate`` does: build the align CSV + sidecar,
append patches and decisions, then reload and evaluate. Every review
outcome must be honoured exactly once (stale, conflict, edit, accept).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hannom.align import write_alignment_csv
from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow, DiffElement
from hannom.orchestrator import load_rows_for_evaluation
from hannom.review.patches import ReviewPatch, append_patch
from hannom.review_decisions import (
    STATUS_ACCEPTED_MATCH,
    append_decision,
    apply_decisions,
    decision_path,
    make_decision,
    read_decisions,
)
from hannom.review_metadata import sidecar_path


def _project(tmp_path: Path) -> ProjectConfig:
    book = BookConfig(
        book_id="T1_Test",
        pdf=tmp_path / "Data" / "T1_Test.pdf",
        layout="T1",
        expected_pages=1,
        nom_start_hint=1,
        nom_end_hint=1,
        translation_start=2,
        translation_end=1,
        ocr=OCRSettings(nom=("local",), quoc_ngu=("local",)),
    )
    return ProjectConfig(
        root=tmp_path,
        project_name="test",
        deadline="",
        zip_stem="test",
        report_name="test_report.pdf",
        one_zip_for_all_books=True,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
        output_dir=tmp_path / "out",
        dictionaries_dir=tmp_path / "dict",
        models_dir=tmp_path / "models",
        books=(book,),
        api=ApiSettings(
            base_url="https://example.invalid",
            token_env="TOKEN",
            user_agent="test",
            limits={"per_minute": 25, "per_hour": 50, "per_day": 200, "per_week": 600},
        ),
        quality={"minimum_similarity": 95.0},
        ocr_config={"engines": {"local": {"kind": "mock"}}, "routing": {}},
    )


def _row(sentence_id: str, ch: str, vi: str, diff=None, flags=()) -> AlignmentRow:
    return AlignmentRow(
        img_id="Test.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=diff,
        confidence=0.9,
        flags=list(flags),
    )


def _write_book(project: ProjectConfig, rows) -> Path:
    csv_path = project.data_dir / "align" / "T1_Test" / "T1_Test.csv"
    write_alignment_csv(csv_path, rows)
    return csv_path


def test_accepted_match_flow_through_full_loader(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "字字", "hai chữ", [], ("DIFF_UNVERIFIED_NO_BOOK_READINGS",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(
        decisions,
        make_decision(
            book_id="T1_Test",
            sentence_id=row.sentence_id,
            status=STATUS_ACCEPTED_MATCH,
            reviewer="tester",
            reason="đối chiếu hình ảnh",
            ch_txt=row.ch_txt,
            vi_txt=row.vi_txt,
            text_diff_json=row.text_diff_json(),
        ),
    )

    rows, issues = load_rows_for_evaluation(project, book)
    assert issues == []
    (gated,) = rows
    assert gated.review_status == STATUS_ACCEPTED_MATCH
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=issues)
    assert metrics.verified_match_rows == 1
    assert metrics.passed


def test_stale_acceptance_flow_does_not_pass_gate(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_UNVERIFIED_NO_BOOK_READINGS",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(
        decisions,
        make_decision(
            book_id="T1_Test",
            sentence_id=row.sentence_id,
            status=STATUS_ACCEPTED_MATCH,
            reviewer="tester",
            ch_txt=row.ch_txt,
            vi_txt=row.vi_txt,
            text_diff_json=row.text_diff_json(),
        ),
    )
    # Rewrite the CSV with different content (as a re-OCR would).
    row.ch_txt = "其"
    _write_book(project, [row])

    rows, issues = load_rows_for_evaluation(project, book)
    (gated,) = rows
    assert gated.review_status is None
    assert any("REVIEW_DECISION_STALE" in issue for issue in issues)
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=issues)
    assert not metrics.passed


def test_content_edit_is_not_an_acceptance(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "cái khác hoàn toàn", None, ("NON_ONE_TO_ONE",))
    _write_book(project, [row])
    append_patch(
        project.data_dir / "review" / "T1_Test.patches.jsonl",
        ReviewPatch(
            book_id="T1_Test",
            sentence_id=row.sentence_id,
            field="vi_txt",
            before=row.vi_txt,
            after="cái khác hoàn toàn khác",
            reviewer="tester",
        ),
    )
    rows, issues = load_rows_for_evaluation(project, book)
    (gated,) = rows
    assert "CONTENT_EDITED" in gated.flags
    assert gated.review_status is None
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=issues)
    assert metrics.verified_match_rows == 0
    assert metrics.verified_difference_rows == 0
