"""Durable, append-only review decisions (Issues 2 and 3)."""

from __future__ import annotations

import json

import pytest

from hannom.models import AlignmentRow
from hannom.review_decisions import (
    DECISION_STATUSES,
    STATUS_ACCEPTED_MATCH,
    STATUS_ACCEPTED_DIFFERENCE,
    STATUS_CONTENT_EDITED,
    STATUS_UNMATCHED,
    STATUS_UNRESOLVED,
    apply_decisions,
    decision_path,
    make_decision,
    append_decision,
    read_decisions,
)


def _row(sentence_id: str, ch: str = "字字", vi: str = "hai chữ", diff=None, flags=()) -> AlignmentRow:
    return AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id=sentence_id,
        ch_txt=ch,
        vi_txt=vi,
        text_diff=diff,
        confidence=0.9,
        flags=list(flags),
    )


def _content_hash(row: AlignmentRow) -> str:
    from hannom.review_decisions import content_sha256

    return content_sha256(row.ch_txt, row.vi_txt, row.text_diff_json())


def test_no_change_acceptance_creates_persistent_record(tmp_path):
    row = _row("Book.001.1")
    decision = make_decision(
        book_id="b",
        sentence_id=row.sentence_id,
        status=STATUS_ACCEPTED_MATCH,
        reviewer="tester",
        reason="đối chiếu hình ảnh",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    )
    path = decision_path(tmp_path, "b")
    append_decision(path, decision)

    decisions, issues = read_decisions(path)
    assert issues == []
    assert len(decisions) == 1
    loaded = decisions[0]
    assert loaded.status == STATUS_ACCEPTED_MATCH
    assert loaded.reviewer == "tester"
    assert loaded.timestamp and loaded.schema == 1
    assert loaded.content_sha256 == _content_hash(row)


def test_decision_survives_serialization_and_reload(tmp_path):
    row = _row("Book.001.1", ch="之", vi="thì")
    path = tmp_path / "decisions.jsonl"
    decision = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status=STATUS_ACCEPTED_MATCH,
        reviewer="tester",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
        character_token_mappings=[
            {"nom_char": "之", "nom_position": 0, "qn_token": "thì", "qn_token_position": 0}
        ],
    )
    append_decision(path, decision)
    decisions, issues = read_decisions(path)
    assert issues == []
    (loaded,) = decisions
    assert loaded.character_token_mappings[0].nom_char == "之"
    assert loaded.character_token_mappings[0].qn_token_position == 0


def test_explicit_reviewer_mapping_survives_reload(tmp_path):
    from hannom.review_decisions import CharacterTokenMapping

    row = _row("Book.001.1", ch="之", vi="thì mà")
    path = tmp_path / "decisions.jsonl"
    decision = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status="accepted_difference",
        reviewer="tester",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
        character_token_mappings=[CharacterTokenMapping("之", 0, "thì", 0)],
    )
    append_decision(path, decision)
    rows, issues = apply_decisions([row], read_decisions(path)[0])
    assert issues == []
    (applied,) = rows
    assert applied.review_status == STATUS_ACCEPTED_DIFFERENCE
    assert applied.review_reviewer == "tester"
    assert applied.character_token_mappings[0]["qn_token_position"] == 0


def test_content_change_invalidates_stale_approval(tmp_path):
    row = _row("Book.001.1", ch="之", vi="thì")
    path = tmp_path / "decisions.jsonl"
    decision = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status=STATUS_ACCEPTED_MATCH,
        reviewer="tester",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    )
    append_decision(path, decision)
    # Someone edits the Nôm text afterwards (e.g. re-OCR).
    row.ch_txt = "其"
    rows, issues = apply_decisions([row], read_decisions(path)[0])
    (applied,) = rows
    assert applied.review_status is None
    assert "REVIEW_DECISION_STALE" in applied.flags
    assert any("REVIEW_DECISION_STALE" in issue for issue in issues)


def test_editing_nom_only_does_not_accept_alignment():
    row = _row("Book.001.1")
    # Editorial edit recorded as a decision: grants no verification.
    from hannom.review_decisions import apply_decisions, make_decision

    decisions = [
        make_decision(
            book_id="b",
            sentence_id="Book.001.1",
            status=STATUS_CONTENT_EDITED,
            reviewer="tester",
            ch_txt=row.ch_txt,
            vi_txt=row.vi_txt,
            text_diff_json=row.text_diff_json(),
        )
    ]
    rows, issues = apply_decisions([row], decisions)
    (applied,) = rows
    assert applied.review_status == STATUS_CONTENT_EDITED


def test_unmatched_decision_persists(tmp_path):
    row = _row("Book.001.1", ch="其其", vi="", diff=None, flags=("UNMATCHED_NOM",))
    path = tmp_path / "decisions.jsonl"
    decision = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status=STATUS_UNMATCHED,
        reviewer="tester",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
    )
    append_decision(path, decision)
    rows, issues = apply_decisions([row], read_decisions(path)[0])
    assert issues == []
    assert rows[0].review_status == STATUS_UNMATCHED


def test_latest_decision_wins_and_conflict_is_reported():
    row = _row("Book.001.1")
    first = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status="unresolved",
        reviewer="a",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
        timestamp="2026-11-09T00:00:00+00:00",
    )
    second = make_decision(
        book_id="b",
        sentence_id="Book.001.1",
        status=STATUS_ACCEPTED_MATCH,
        reviewer="b",
        ch_txt=row.ch_txt,
        vi_txt=row.vi_txt,
        text_diff_json=row.text_diff_json(),
        timestamp="2026-11-09T01:00:00+00:00",
    )
    rows, issues = apply_decisions([row], [first, second])
    (applied,) = rows
    assert applied.review_status == STATUS_ACCEPTED_MATCH
    assert any("REVIEW_DECISION_CONFLICT" in issue for issue in issues)


def test_invalid_decision_is_rejected(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        json.dumps({"schema": 1, "sentence_id": "X", "status": "bogus_status",
                    "reviewer": "a", "timestamp": "t", "content_sha256": "0" * 64})
        + "\nnot-json\n",
        encoding="utf-8",
    )
    decisions, issues = read_decisions(path)
    assert decisions == []
    assert any("DECISION_JSON_ERROR" in i for i in issues)
    assert any("DECISION_INVALID" in i for i in issues)


def test_unsupported_schema_is_rejected(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text(
        json.dumps({"schema": 99, "sentence_id": "X", "status": "accepted_match",
                    "reviewer": "a", "timestamp": "t", "content_sha256": "0" * 64})
        + "\n",
        encoding="utf-8",
    )
    decisions, issues = read_decisions(path)
    assert decisions == []
    assert any("unsupported schema" in i for i in issues)


def test_all_statuses_are_known_constants():
    assert DECISION_STATUSES >= {
        "content_edited",
        "alignment_reviewed",
        "accepted_match",
        "accepted_difference",
        "unresolved",
        "unmatched",
        "rejected",
    }
