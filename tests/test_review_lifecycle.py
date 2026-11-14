"""Full review lifecycle: generate → review → correct → approve → evaluate.

This walks the exact sequence from the third repair pass specification:

    generate row → persist CSV+metadata → unresolved decision →
    content corrected → new approval → reload → latest approval effective,
    history intact, no active blocker → learn from positional mapping →
    re-evaluate → semantic confidence survives serialization.

It also proves repeated execution is stable (no duplicate dictionary
mutation on re-runs).
"""

from __future__ import annotations

import json
from pathlib import Path

from hannom.align import write_alignment_csv
from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.dictionary.book_lexicon import BookLexicon
from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow
from hannom.orchestrator import learn_for_book, load_rows_for_evaluation
from hannom.review.patches import ReviewPatch, append_patch
from hannom.review_decisions import (
    STATUS_ACCEPTED_MATCH,
    append_decision,
    decision_path,
    make_decision,
    parse_decisions,
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


def test_complete_review_lifecycle(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]

    # 1. Generate the alignment row and persist CSV + sidecar metadata.
    row = _row("T1_Test.001.1", "之其", "thì thế", [], ("DIFF_NO_READING_MISMATCH",))
    row.confidence = 0.88
    row.semantic_confidence = 0.5
    csv_path = _write_book(project, [row])
    assert csv_path.exists() and sidecar_path(csv_path).exists()

    # 2. Reviewer examines the row and cannot resolve it.
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="unresolved",
        reviewer="reviewer", ch_txt=row.ch_txt, vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    ))

    # 3. The Nôm transcription is corrected afterwards (the pipeline rewrites
    #    the CSV with the corrected row before decisions are recorded).
    append_patch(
        project.data_dir / "review" / "T1_Test.patches.jsonl",
        ReviewPatch(
            book_id="T1_Test",
            sentence_id=row.sentence_id,
            field="ch_txt",
            before="之其",
            after="之其沛",
            reviewer="reviewer",
            reason="fix after OCR",
        ),
    )
    rows_now, issues, _audit = load_rows_for_evaluation(project, book)
    (current,) = rows_now
    assert current.ch_txt == "之其沛"

    # 4. Reviewer re-examines and accepts the corrected revision.
    patched_row = _row("T1_Test.001.1", "之其沛", "thì thế", [], ("DIFF_NO_READING_MISMATCH",))
    patched_row.semantic_confidence = 0.5
    _write_book(project, [patched_row])  # simulate the align-stage rewrite
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status=STATUS_ACCEPTED_MATCH,
        reviewer="reviewer",
        ch_txt=patched_row.ch_txt, vi_txt=patched_row.vi_txt,
        text_diff_json=patched_row.text_diff_json(),
        character_token_mappings=[
            {"nom_char": "之", "nom_position": 0, "qn_token": "thì", "qn_token_position": 0},
            {"nom_char": "其", "nom_position": 1, "qn_token": "thế", "qn_token_position": 1},
        ],
    ))

    # 5. Reload rows and decisions: the latest approval must be effective,
    #    the stale unresolved decision stays in audit history but no longer
    #    blocks anything.
    rows, issues, _audit = load_rows_for_evaluation(project, book)
    assert issues == []
    (restored,) = rows
    assert restored.review_status == STATUS_ACCEPTED_MATCH
    assert restored.decision_integrity == "valid"
    decision_lines = decisions.read_text(encoding="utf-8").splitlines()
    assert len(decision_lines) == 2  # append-only history preserved
    assert [json.loads(line)["status"] for line in decision_lines] == ["unresolved", "accepted_match"]

    # 6. Semantic confidence survives the serialization boundary.
    assert restored.semantic_confidence == 0.5
    assert restored.confidence == 0.9

    # 7. Evaluation sees the review-resolved row as verified.
    metrics = evaluate_rows("T1_Test", rows, integrity_issues=issues)
    assert metrics.verified_match_rows == 1
    assert metrics.unverified_rows == 0

    # 8. Learn from the reviewed positional mapping.
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    _, failures, _ = parse_decisions(decisions)
    learned = learn_for_book(lexicon, rows, None, failures)
    assert learned["learned_pairs"] == 2

    # 9. Re-running learning is idempotent: no duplicate mutation.
    trusted_before = lexicon.quarantine_summary()["trusted_pairs"]
    _, failures, _ = parse_decisions(decisions)
    learned_again = learn_for_book(lexicon, rows, None, failures)
    assert learned_again["learned_pairs"] == 0
    assert learned_again["skipped_duplicate_evidence"] == 2
    assert lexicon.quarantine_summary()["trusted_pairs"] == trusted_before

    # 10. Evaluation reproducibility: a second loader pass is identical.
    rows2, issues2, _audit = load_rows_for_evaluation(project, book)
    (restored2,) = rows2
    assert issues2 == issues
    assert restored2.review_status == STATUS_ACCEPTED_MATCH
    assert restored2.semantic_confidence == 0.5
    metrics2 = evaluate_rows("T1_Test", rows2, integrity_issues=issues2)
    assert (
        metrics2.similarity,
        metrics2.coverage_ratio,
        metrics2.verified_match_rows,
        metrics2.semantic_evidence_rows,
        metrics2.structural_confidence_mean,
    ) == (
        metrics.similarity,
        metrics.coverage_ratio,
        metrics.verified_match_rows,
        metrics.semantic_evidence_rows,
        metrics.structural_confidence_mean,
    )
