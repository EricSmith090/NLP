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

    rows, issues, _audit = load_rows_for_evaluation(project, book)
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

    rows, issues, _audit = load_rows_for_evaluation(project, book)
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
    rows, issues, _audit = load_rows_for_evaluation(project, book)
    (gated,) = rows
    assert "CONTENT_EDITED" in gated.flags
    assert gated.review_status is None
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=issues)
    assert metrics.verified_match_rows == 0
    assert metrics.verified_difference_rows == 0


# ---------------------------------------------------------------------------
# Issue B: learning must fail closed under decision-integrity failures
# ---------------------------------------------------------------------------

def _book_with_decision(tmp_path, *, ch="之", vi="thì", mappings=None, status="accepted_match"):
    project = _project(tmp_path)
    row = _row("T1_Test.001.1", ch, vi, [], ())
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    decision_kwargs = dict(
        book_id="T1_Test",
        sentence_id=row.sentence_id,
        status=status,
        reviewer="tester",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    )
    if mappings is not None:
        decision_kwargs["character_token_mappings"] = mappings
    append_decision(decisions, make_decision(**decision_kwargs))
    return project, row


def _lexicon(tmp_path):
    from hannom.dictionary.book_lexicon import BookLexicon

    return BookLexicon(tmp_path / "lexicon.json")


def test_valid_decision_and_mapping_learns(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project, row = _book_with_decision(
        tmp_path,
        ch="之其",
        vi="thì mà thế",
        mappings=[
            {"nom_char": "之", "nom_position": 0, "qn_token": "thì", "qn_token_position": 0},
            {"nom_char": "其", "nom_position": 1, "qn_token": "thế", "qn_token_position": 2},
        ],
        status="accepted_difference",
    )
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    assert issues == []
    lexicon = _lexicon(tmp_path)
    before = lexicon.quarantine_summary()["trusted_pairs"]
    _, failures, _ = parse_decisions(decision_path(project.data_dir, "T1_Test"))
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 2
    after = lexicon.quarantine_summary()["trusted_pairs"]
    assert after == before + 2
    assert lexicon.readings("之") == ["thì"]
    assert lexicon.readings("其") == ["thế"]


def test_conflicted_decisions_do_not_modify_lexicon(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    # same-revision match vs difference, both valid → conflict
    project = _project(tmp_path)
    row = _row("T1_Test.001.1", "之", "thì", [], ())
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="a", ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json(),
    ))
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_difference",
        reviewer="b", ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json(),
    ))
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    assert any("REVIEW_DECISION_CONFLICT" in issue for issue in issues)
    _, failures, _ = parse_decisions(decisions)
    lexicon = _lexicon(tmp_path)
    snapshot = lexicon.quarantine_summary()["trusted_pairs"]
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert lexicon.quarantine_summary()["trusted_pairs"] == snapshot


def test_invalid_latest_decision_does_not_modify_lexicon(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project = _project(tmp_path)
    row = _row("T1_Test.001.1", "之", "thì", [], ())
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="a", ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json(),
    ))
    with decisions.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"schema": 1, "sentence_id": "T1_Test.001.1", "status": "bogus_status", '
                 '"reviewer": "b", "timestamp": "t", "content_sha256": "' + "0" * 64 + '"}\n')
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    _, failures, _ = parse_decisions(decisions)
    lexicon = _lexicon(tmp_path)
    before = lexicon.quarantine_summary()["trusted_pairs"]
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert lexicon.readings("之") == []
    assert lexicon.quarantine_summary()["trusted_pairs"] == before


def test_stale_decision_does_not_modify_lexicon(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project, row = _book_with_decision(tmp_path, ch="之", vi="thì")
    # Row content changes after the decision → stale.
    _write_book(project, [_row("T1_Test.001.1", "其", "thì", [], ())])
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    assert any("REVIEW_DECISION_STALE" in issue for issue in issues)
    _, failures, _ = parse_decisions(decision_path(project.data_dir, "T1_Test"))
    lexicon = _lexicon(tmp_path)
    before = lexicon.quarantine_summary()["trusted_pairs"]
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert lexicon.quarantine_summary()["trusted_pairs"] == before


def test_malformed_decision_log_disables_learning_for_book(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project, row = _book_with_decision(tmp_path, ch="之", vi="thì")
    decisions = decision_path(project.data_dir, "T1_Test")
    with decisions.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"not a decision": true}\n')
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    _, failures, _ = parse_decisions(decisions)
    lexicon = _lexicon(tmp_path)
    before = lexicon.quarantine_summary()["trusted_pairs"]
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert learned.get("skipped_log_wide_failure") is True
    assert lexicon.quarantine_summary()["trusted_pairs"] == before


def test_valid_row_learns_when_separate_row_has_row_specific_problem(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project = _project(tmp_path)
    row_ok = _row("T1_Test.001.1", "之", "thì", [], ())
    row_bad = _row("T1_Test.001.2", "其", "thế", None, ())
    _write_book(project, [row_ok, row_bad])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row_ok.sentence_id, status="accepted_match",
        reviewer="a", ch_txt=row_ok.ch_txt, vi_txt=row_ok.vi_txt,
        text_diff_json=row_ok.text_diff_json(),
    ))
    with decisions.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"schema": 1, "sentence_id": "T1_Test.001.2", "status": "bogus_status", '
                 '"reviewer": "b", "timestamp": "t", "content_sha256": "ab"}\n')
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    _, failures, _ = parse_decisions(decisions)
    lexicon = _lexicon(tmp_path)
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 1
    assert lexicon.readings("之") == ["thì"]
    assert lexicon.readings("其") == []


def test_approval_cannot_resurrect_after_invalid_supersedes(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project = _project(tmp_path)
    row = _row("T1_Test.001.1", "之", "thì", [], ())
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="a", ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json(),
    ))
    with decisions.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"schema": 1, "sentence_id": "T1_Test.001.1", "status": "bogus_status", '
                 '"reviewer": "b", "timestamp": "t", "content_sha256": "zz"}\n')
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    _, failures, _ = parse_decisions(decisions)
    lexicon = _lexicon(tmp_path)
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    assert lexicon.readings("之") == []


def test_quarantined_entries_stay_excluded(tmp_path):
    import json as _json

    from hannom.dictionary.book_lexicon import BookLexicon
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project, row = _book_with_decision(tmp_path)
    path = tmp_path / "lexicon.json"
    path.write_text(
        _json.dumps({"meta": {}, "readings": {"之": {"thì": 7}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    lexicon = BookLexicon(path)
    assert lexicon.readings("之") == []  # quarantine: never trusted
    _, failures, _ = parse_decisions(decision_path(project.data_dir, "T1_Test"))
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    learn_for_book(lexicon, rows, None, failures)
    assert lexicon.readings("之") == ["thì"]  # only the new reviewed entry is trusted
    assert lexicon.quarantine_summary()["legacy_without_provenance_pairs"] == 7


def test_later_valid_decision_restores_learning_eligibility(tmp_path):
    from hannom.orchestrator import learn_for_book
    from hannom.review_decisions import parse_decisions

    project, row = _book_with_decision(tmp_path, ch="之", vi="thì")
    # First, the decision goes stale (row edited by someone).
    _write_book(project, [_row("T1_Test.001.1", "其", "thì", [], ())])
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    _, failures, _ = parse_decisions(decision_path(project.data_dir, "T1_Test"))
    lexicon = _lexicon(tmp_path)
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 0
    # Then the reviewer re-verifies the CURRENT content; eligibility returns.
    current = _row("T1_Test.001.1", "其", "thì", [], ())
    append_decision(decision_path(project.data_dir, "T1_Test"), make_decision(
        book_id="T1_Test", sentence_id=current.sentence_id, status="accepted_match",
        reviewer="tester", ch_txt=current.ch_txt, vi_txt=current.vi_txt,
        text_diff_json=current.text_diff_json(),
    ))
    rows, issues, _audit = load_rows_for_evaluation(project, project.books[0])
    learned = learn_for_book(
        lexicon, rows, None, parse_decisions(decision_path(project.data_dir, "T1_Test"))[1]
    )
    assert learned["learned_pairs"] == 1
    assert lexicon.readings("其") == ["thì"]
