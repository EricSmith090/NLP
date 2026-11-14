"""Issue A: superseded row-specific decision failures do not block the gate.

Every case goes through the real path: JSONL decision log → parse_decisions
→ apply_decisions → load_rows_for_evaluation → evaluate_rows.
"""

from __future__ import annotations

from pathlib import Path

from hannom.align import write_alignment_csv
from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow
from hannom.orchestrator import load_rows_for_evaluation
from hannom.review_decisions import (
    STATUS_ACCEPTED_MATCH,
    append_decision,
    decision_path,
    make_decision,
    parse_decisions,
)


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


def _append_raw_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")


def _bogus_line(sentence_id: str, status: str = "bogus_status") -> str:
    return (
        '{"schema": 1, "sentence_id": "%s", "status": "%s", '
        '"reviewer": "intruder", "timestamp": "t", '
        '"content_sha256": "%s"}' % (sentence_id, status, "0" * 64)
    )


def test_superseded_malformed_decision_does_not_block(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    _append_raw_line(decisions, _bogus_line(row.sentence_id))
    # Newer valid approval on the current content supersedes the malformed record.
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status=STATUS_ACCEPTED_MATCH,
        reviewer="reviewer", ch_txt=row.ch_txt, vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    ))

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    (restored,) = rows
    assert restored.decision_integrity == "valid"
    assert restored.review_status == STATUS_ACCEPTED_MATCH
    assert not blocking, f"historical malformed record blocked the gate: {blocking}"
    # The superseded record remains inspectable.
    assert any("DECISION_INVALID" in item or "DECISION_SUPERSEDED" in item for item in audit)
    # Raw history preserved.
    assert len(decisions.read_text(encoding="utf-8").splitlines()) == 2
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=blocking, audit_diagnostics=audit)
    assert metrics.passed


def test_malformed_decision_without_later_decision_blocks(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    _append_raw_line(decision_path(project.data_dir, "T1_Test"), _bogus_line(row.sentence_id))

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    (restored,) = rows
    assert restored.decision_integrity == "invalid"
    assert blocking, "malformed latest record did not block"
    assert restored.review_status is None
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=blocking, audit_diagnostics=audit)
    assert not metrics.passed


def test_malformed_then_stale_latest_blocks(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    _append_raw_line(decisions, _bogus_line(row.sentence_id))
    # Newer decision on a DIFFERENT (stale) revision.
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status=STATUS_ACCEPTED_MATCH,
        reviewer="reviewer", ch_txt="其", vi_txt="thì",
        text_diff_json=row.text_diff_json(),
    ))

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    (restored,) = rows
    assert restored.decision_integrity == "stale"
    assert restored.review_status is None
    assert any("REVIEW_DECISION_STALE" in issue for issue in blocking)
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=blocking, audit_diagnostics=audit)
    assert not metrics.passed


def test_malformed_then_invalid_latest_blocks(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    _append_raw_line(decisions, _bogus_line(row.sentence_id))
    _append_raw_line(decisions, _bogus_line(row.sentence_id, status="still_bogus"))

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    (restored,) = rows
    assert restored.decision_integrity == "invalid"
    assert any("REVIEW_DECISION_INVALID" in issue for issue in blocking)
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=blocking, audit_diagnostics=audit)
    assert not metrics.passed


def test_log_wide_failure_blocks_learning_and_gate(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status=STATUS_ACCEPTED_MATCH,
        reviewer="reviewer", ch_txt=row.ch_txt, vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    ))
    # A standalone corrupted record with no recoverable sentence_id.
    _append_raw_line(decisions, "{ this is not json }")

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    (restored,) = rows
    # The unattributable record cannot block a *row-specific* replay, but
    # the log as a whole is no longer trustworthy: it must remain visible.
    assert any("DECISION_LOG_INVALID" in issue for issue in blocking)
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=blocking, audit_diagnostics=audit)
    assert not metrics.passed
    # Learning is disabled for the whole book.
    from hannom.dictionary.book_lexicon import BookLexicon
    from hannom.orchestrator import learn_for_book

    lexicon = BookLexicon(tmp_path / "lexicon.json")
    _, failures, _ = parse_decisions(decisions)
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert learned.get("skipped_log_wide_failure") is True


def test_historical_diagnostics_remain_inspectable(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì", [], ("DIFF_NO_READING_MISMATCH",))
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    _append_raw_line(decisions, _bogus_line(row.sentence_id))
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status=STATUS_ACCEPTED_MATCH,
        reviewer="reviewer", ch_txt=row.ch_txt, vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    ))
    rows, blocking, audit = load_rows_for_evaluation(project, book)
    assert audit, "audit diagnostics were discarded"
    assert any("DECISION_SUPERSEDED" in item or "DECISION_INVALID" in item for item in audit)
