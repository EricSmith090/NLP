"""Issue C: lexicon reconciliation revokes revoked/superseded evidence.

Every case exercises persistence + reload end to end:

    build row → decision → learn → save → reload → revoke/replace → persist
    → reload → assert readings / provenance / revoked sections.

Also covers manual restore, idempotency, and the alignment path.
"""

from __future__ import annotations

import json
from pathlib import Path

from hannom.align import write_alignment_csv
from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.dictionary.book_lexicon import BookLexicon
from hannom.evaluate import evaluate_rows
from hannom.models import AlignmentRow
from hannom.review.patches import append_patch, ReviewPatch
from hannom.review_decisions import (
    STATUS_ACCEPTED_MATCH,
    append_decision,
    decision_path,
    make_decision,
    parse_decisions,
    apply_decisions,
)
from hannom.textdiff import auto_text_diff


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


def _row(sentence_id: str, ch: str, vi: str) -> AlignmentRow:
    return AlignmentRow(
        img_id="Test.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=[],
        confidence=0.9,
        flags=[],
        review_status=None,
        review_reviewer=None,
        decision_integrity=None,
        character_token_mappings=[],
    )


def _write_book(project: ProjectConfig, rows) -> Path:
    csv_path = project.data_dir / "align" / "T1_Test" / "T1_Test.csv"
    write_alignment_csv(csv_path, rows)
    return csv_path


def _mapping(char, nom_pos, token, token_pos):
    return {"nom_char": char, "nom_position": nom_pos, "qn_token": token, "qn_token_position": token_pos}


def _learn_from_current(project: ProjectConfig, book, tmp_path: Path):
    """Learn from the currently reviewed rows and persist the lexicon."""
    from hannom.orchestrator import load_rows_for_evaluation, learn_for_book

    rows, blocking, audit = load_rows_for_evaluation(project, book)
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    _, failures, _ = parse_decisions(decision_path(project.data_dir, "T1_Test"))
    learned = learn_for_book(lexicon, rows, None, failures)
    lexicon.save()
    return learned, lexicon


def test_backup_created_and_never_overwritten(tmp_path):
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps({"meta": {}, "readings": {"之": {"thì": 1}}}),
                    encoding="utf-8")
    lexicon = BookLexicon(path)
    first = lexicon.backup()
    second = lexicon.backup()
    assert first is not None and first == second  # byte-identical reused
    # Different content on a subsequent run → new backup; original preserved.
    path.write_text(json.dumps({"meta": {}, "readings": {"之": {"thì": 2}}}),
                    encoding="utf-8")
    third = BookLexicon(path).backup()
    assert third != first
    parsed = json.loads(first.read_text(encoding="utf-8"))
    assert parsed["readings"]["之"]["thì"] == 1
    parsed3 = json.loads(third.read_text(encoding="utf-8"))
    assert parsed3["readings"]["之"]["thì"] == 2


def test_revocation_of_superseded_approval(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之其", "thì thế")
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="reviewer", ch_txt="之其", vi_txt="thì thế",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0), _mapping("其", 1, "thế", 1)],
    ))

    learned, _ = _learn_from_current(project, book, tmp_path)
    assert learned["learned_pairs"] == 2

    # Reviewer withdraws the approval (same revision, rejected semantics).
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="unresolved",
        reviewer="reviewer", ch_txt="之其", vi_txt="thì thế",
        text_diff_json="[]",
    ))

    from hannom.orchestrator import reconcile_for_book

    lexicon = BookLexicon(tmp_path / "lexicon.json")
    summary = reconcile_for_book(project, book, lexicon)
    assert summary.get("automated_revoked", 0) == 2

    reloaded = BookLexicon(tmp_path / "lexicon.json")
    assert reloaded.readings("之") == []
    assert reloaded.readings("其") == []
    # Historical provenance is preserved in the revoked section.
    assert any(r for r in reloaded.revoked.get("之", {}).get("thì", []))
    assert any(r for r in reloaded.revoked.get("其", {}).get("thế", []))
    assert len(decisions.read_text(encoding="utf-8").splitlines()) == 2


def test_mapping_replacement_revokes_only_the_old_reading(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì")
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="reviewer", ch_txt="之", vi_txt="thì",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0)],
    ))
    _learn_from_current(project, book, tmp_path)

    # Newer valid approval mapping the same character to a different token.
    row2 = _row("T1_Test.001.1", "之", "thế")
    _write_book(project, [row2])
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row2.sentence_id, status="accepted_difference",
        reviewer="reviewer", ch_txt="之", vi_txt="thế",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thế", 0)],
    ))
    _learn_from_current(project, book, tmp_path)

    from hannom.orchestrator import reconcile_for_book

    lexicon = BookLexicon(tmp_path / "lexicon.json")
    summary = reconcile_for_book(project, book, lexicon)
    reloaded = BookLexicon(tmp_path / "lexicon.json")
    assert reloaded.readings("之") == ["thế"]
    assert reloaded.readings("thì") == []
    revoked_tokens = [r["qn_token_position"] for r in [
        rec for rec in reloaded.revoked.get("之", {}).get("thì", [])
    ]]
    assert revoked_tokens == [0]


def test_conflict_revocation(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì thế")
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="a", ch_txt="之", vi_txt="thì thế",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0)],
    ))
    _learn_from_current(project, book, tmp_path)

    # Mutually exclusive same-revision verdict arrives later.
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_difference",
        reviewer="b", ch_txt="之", vi_txt="thì thế",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0)],
    ))
    from hannom.orchestrator import reconcile_for_book

    lexicon = BookLexicon(tmp_path / "lexicon.json")
    summary = reconcile_for_book(project, book, lexicon)
    assert summary.get("changed")

    reloaded = BookLexicon(tmp_path / "lexicon.json")
    assert reloaded.readings("之") == []
    assert reloaded.revoked.get("之", {}).get("thì"), "conflicting evidence was destroyed"


def test_independent_rows_are_not_affected(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row_ok = _row("T1_Test.001.1", "之", "thì")
    row_bad = _row("T1_Test.001.2", "其", "thế")
    _write_book(project, [row_ok, row_bad])
    decisions = decision_path(project.data_dir, "T1_Test")
    for row, char, token in ((row_ok, "之", "thì"), (row_bad, "其", "thế")):
        append_decision(decisions, make_decision(
            book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
            reviewer="reviewer", ch_txt=row.ch_txt, vi_txt=row.vi_txt,
            text_diff_json="[]",
            character_token_mappings=[_mapping(char, 0, token, 0)],
        ))
    _learn_from_current(project, book, tmp_path)

    # Revoke only one row.
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row_bad.sentence_id, status="rejected",
        reviewer="reviewer", ch_txt=row_bad.ch_txt, vi_txt=row_bad.vi_txt,
        text_diff_json="[]",
    ))
    from hannom.orchestrator import reconcile_for_book

    lexicon = BookLexicon(tmp_path / "lexicon.json")
    summary = reconcile_for_book(project, book, lexicon)
    reloaded = BookLexicon(tmp_path / "lexicon.json")
    assert reloaded.readings("之") == ["thì"]
    assert reloaded.readings("其") == []


def test_manual_restoration_survives_reconciliation(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì")
    _write_book(project, [row])
    path = tmp_path / "lexicon.json"
    # A legacy (unprovenanced) entry exists in quarantine.
    path.write_text(json.dumps({"meta": {}, "readings": {"之": {"thì": 5}}}), encoding="utf-8")
    lexicon = BookLexicon(path)
    assert lexicon.readings("之") == []
    promoted = lexicon.restore_quarantine(char="之", syllable="thì")
    assert promoted == 1
    lexicon.save()

    # A reviewer explicitly rejects the row afterwards; manual evidence is unaffected.
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="rejected",
        reviewer="reviewer", ch_txt="之", vi_txt="thì",
        text_diff_json="[]",
    ))
    from hannom.orchestrator import reconcile_for_book

    summary = reconcile_for_book(project, book, BookLexicon(path))
    reloaded = BookLexicon(path)
    assert reloaded.readings("之") == ["thì"], "manual restore was revoked"
    manual_records = [
        r for r in reloaded.provenance.get("之", {}).get("thì", [])
        if r.get("evidence") == "human_restore"
    ]
    assert manual_records, "manual provenance was destroyed"
    assert all(r.get("source") == "manual_restore" for r in manual_records)
    assert reloaded.quarantine_summary()["trusted_pairs"] == 5

def test_reconciliation_is_idempotent_and_repeatable(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之其", "thì thế")
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="reviewer", ch_txt="之其", vi_txt="thì thế",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0), _mapping("其", 1, "thế", 1)],
    ))
    _learn_from_current(project, book, tmp_path)

    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="unresolved",
        reviewer="reviewer", ch_txt="之其", vi_txt="thì thế",
        text_diff_json="[]",
    ))
    from hannom.orchestrator import reconcile_for_book

    for _ in range(2):
        lexicon = BookLexicon(tmp_path / "lexicon.json")
        summary = reconcile_for_book(project, book, lexicon)
    reloaded = BookLexicon(tmp_path / "lexicon.json")
    assert reloaded.readings("之") == [] and reloaded.readings("其") == []
    assert reloaded.quarantine_summary()["revoked_records"] == 2
    summary3 = reconcile_for_book(project, book, BookLexicon(tmp_path / "lexicon.json"))
    assert summary3.get("automated_revoked", 0) == 0  # nothing left to revoke


def test_revoked_evidence_does_not_influence_text_comparison(tmp_path):
    project = _project(tmp_path)
    book = project.books[0]
    row = _row("T1_Test.001.1", "之", "thì")
    _write_book(project, [row])
    decisions = decision_path(project.data_dir, "T1_Test")
    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="accepted_match",
        reviewer="reviewer", ch_txt="之", vi_txt="thì",
        text_diff_json="[]",
        character_token_mappings=[_mapping("之", 0, "thì", 0)],
    ))
    _learn_from_current(project, book, tmp_path)

    # Before revocation the reading is available.
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    assert lexicon.readings("之") == ["thì"]
    result = auto_text_diff("之", "thì", lexicon=lexicon, dictionary=None)
    assert result.matched_readings == 1

    append_decision(decisions, make_decision(
        book_id="T1_Test", sentence_id=row.sentence_id, status="unresolved",
        reviewer="reviewer", ch_txt="之", vi_txt="thì",
        text_diff_json="[]",
    ))
    from hannom.orchestrator import reconcile_for_book

    lexicon2 = BookLexicon(tmp_path / "lexicon.json")
    reconcile_for_book(project, book, lexicon2)
    lexicon3 = BookLexicon(tmp_path / "lexicon.json")
    assert lexicon3.readings("之") == []
    after = auto_text_diff("之", "thì", lexicon=lexicon3, dictionary=None)
    assert after.matched_readings == 0
    assert after.known_nom_chars == 0
