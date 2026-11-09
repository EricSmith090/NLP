"""Positional mapping-set validation (Issue D)."""

from __future__ import annotations

import pytest

from hannom.dictionary.book_lexicon import BookLexicon
from hannom.models import AlignmentRow
from hannom.review_decisions import (
    CharacterTokenMapping,
    make_decision,
    validate_mapping_set,
    validate_mappings_against_text,
    apply_decisions,
    read_decisions,
)

CH = "之其沛"
VI = "thì thế bóng"


def _m(char: str, nom_pos: int, token: str, token_pos: int) -> CharacterTokenMapping:
    return CharacterTokenMapping(char, nom_pos, token, token_pos)


def test_mappings_sharing_nom_position_are_rejected():
    mappings = [_m("之", 0, "thì", 0), _m("其", 0, "thế", 1)]
    issues = validate_mapping_set(mappings)
    assert any("duplicate Nôm position" in issue for issue in issues)


def test_mappings_sharing_qn_token_position_are_rejected():
    mappings = [_m("之", 0, "thì", 0), _m("其", 1, "thế", 0)]
    issues = validate_mapping_set(mappings)
    assert any("duplicate QN token position" in issue for issue in issues)


def test_duplicate_mapping_entries_are_rejected():
    mappings = [_m("之", 0, "thì", 0), _m("之", 0, "thì", 0)]
    issues = validate_mapping_set(mappings)
    assert any("duplicate" in issue for issue in issues)


def test_char_must_match_declared_position():
    issues = validate_mappings_against_text([_m("其", 0, "thì", 0)], CH, VI)
    assert any("does not match" in issue for issue in issues)


def test_token_must_match_declared_position():
    issues = validate_mappings_against_text([_m("之", 0, "thế", 0)], CH, VI)
    assert any("does not match" in issue for issue in issues)


def test_out_of_bounds_positions_are_rejected():
    issues = validate_mappings_against_text([_m("之", 5, "thì", 0)], CH, VI)
    assert any("out of bounds" in issue for issue in issues)
    issues = validate_mappings_against_text([_m("之", 0, "thì", 9)], CH, VI)
    assert any("out of bounds" in issue for issue in issues)


def test_repeated_char_at_distinct_positions_is_accepted():
    ch = "之沛之"
    vi = "thì bóng mà"
    mappings = [_m("之", 0, "thì", 0), _m("之", 2, "mà", 2)]
    # Same spelling, distinct positions — sequential monotone order.
    assert validate_mappings_against_text(mappings, ch, vi) == []


def test_repeated_token_spelling_at_distinct_positions_is_accepted():
    ch = "之其渝"
    vi = "thì bóng thì"
    mappings = [_m("之", 0, "thì", 0), _m("渝", 2, "thì", 2)]
    assert validate_mappings_against_text(mappings, ch, vi) == []


def test_non_monotone_mapping_set_is_rejected():
    mappings = [_m("其", 2, "thế", 1), _m("之", 0, "thì", 0)]
    issues = validate_mapping_set(mappings)
    assert any("monotone" in issue for issue in issues)


def test_negative_positions_are_rejected():
    issues = validate_mapping_set([_m("之", -1, "thì", 0)])
    assert any("nom_position" in issue for issue in issues)


def test_valid_multi_char_mapping_learns_every_entry(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    row = AlignmentRow(
        img_id="B.001.jpg",
        sentence_id="B.001.1",
        ch_txt=CH,
        vi_txt=VI,
        text_diff=None,
        flags=[],
        review_status="accepted_difference",
        review_reviewer="r",
        decision_integrity="valid",
        character_token_mappings=[
            _m("之", 0, "thì", 0).to_dict(),
            _m("其", 1, "thế", 1).to_dict(),
        ],
    )
    stats = lexicon.learn_from_rows([row])
    assert stats["learned_pairs"] == 2
    assert lexicon.readings("之") == ["thì"]
    assert lexicon.readings("其") == ["thế"]


def test_one_invalid_mapping_rejects_entire_set(tmp_path):
    lexicon = BookLexicon(tmp_path / "lexicon.json")
    row = AlignmentRow(
        img_id="B.001.jpg",
        sentence_id="B.001.1",
        ch_txt=CH,
        vi_txt=VI,
        text_diff=None,
        flags=[],
        review_status="accepted_difference",
        review_reviewer="r",
        decision_integrity="valid",
        character_token_mappings=[
            _m("之", 0, "thì", 0).to_dict(),
            _m("其", 1, "bóng", 1).to_dict(),  # token mismatch — whole set rejected
        ],
    )
    stats = lexicon.learn_from_rows([row])
    assert stats["learned_pairs"] == 0
    assert lexicon.readings("之") == []
    assert lexicon.readings("其") == []


def test_set_validation_used_in_decision_validation(tmp_path):
    # make_decision itself must reject a non-unique set atomically.
    with pytest.raises(ValueError):
        make_decision(
            book_id="b",
            sentence_id="B.001.1",
            status="accepted_match",
            reviewer="r",
            ch_txt=CH,
            vi_txt=VI,
            text_diff_json="[]",
            character_token_mappings=[_m("之", 0, "thì", 0), _m("其", 0, "thế", 0)],
        )

