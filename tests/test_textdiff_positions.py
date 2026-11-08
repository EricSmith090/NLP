from __future__ import annotations

import pytest

from hannom.models import AlignmentRow, DiffElement
from hannom.textdiff import (
    auto_text_diff,
    diff_from_decisions,
    make_element,
    mask_spans,
    scoreable_nom_chars,
    validate_text_diff,
)


class Lexicon:
    def __init__(self, data: dict[str, list[str]]):
        self.data = data

    def readings(self, char: str) -> list[str]:
        return self.data.get(char, [])


def test_positions_are_code_points_and_half_open():
    element = make_element("é字", "x", [[1, 2]], [], "error")
    assert element.nom_pos == ((1, 2),)
    assert element.nom_sub_text == "字"
    assert element.vi_pos == ()
    assert element.vi_sub_text == ""
    assert validate_text_diff("é字", "x", [element]) == []


def test_nfc_is_normalized_before_position_computation():
    raw = "e\u0301字"  # e + combining acute + 字
    element = make_element(raw, "x", [[1, 2]], [], "error")
    assert element.nom_sub_text == "字"
    assert validate_text_diff(raw, "x", [element]) == []


def test_astral_nom_character_counts_as_one_code_point():
    char = "\U00021638"  # 𡘸, outside the BMP
    element = make_element(char, "x", [[0, 1]], [], "error")
    assert element.nom_sub_text == char
    assert len(char) == 1


def test_mask_is_six_chars_and_cannot_be_inside_a_position():
    assert len("[MASK]") == 6
    text = "[MASK]字"
    assert mask_spans(text) == [(0, 6)]
    with pytest.raises(ValueError, match="MASK"):
        make_element(text, "x", [[0, 6]], [], "error")
    # A span after the mask is valid and the mask itself stays outside.
    element = make_element(text, "x", [[6, 7]], [], "error")
    assert element.nom_sub_text == "字"


def test_substrings_must_match_exactly():
    element = DiffElement(
        nom_pos=((0, 1),),
        nom_sub_text="wrong",
        vi_pos=(),
        vi_sub_text="",
        type="error",
    )
    issues = validate_text_diff("字", "", [element])
    assert any("does not match" in issue for issue in issues)


def test_different_types_cannot_overlap():
    a = make_element("字字", "x", [[0, 2]], [], "error")
    b = make_element("字字", "x", [[1, 2]], [], "warn")
    issues = validate_text_diff("字字", "x", [a, b])
    assert any("overlapping" in issue for issue in issues)


def test_decisions_build_exact_elements():
    elements = diff_from_decisions(
        "字字",
        "hai chữ",
        [{"nom_pos": [0, 1], "vi_pos": [0, 3], "type": "warn"}],
    )
    assert len(elements) == 1
    assert elements[0].nom_sub_text == "字"
    assert elements[0].vi_sub_text == "hai"
    assert elements[0].type == "warn"


def test_auto_diff_matches_known_reading():
    result = auto_text_diff("字", "chữ", lexicon=Lexicon({"字": ["chữ"]}))
    assert result.elements == []
    assert "DIFF_NO_READING_MISMATCH" in result.flags


def test_auto_diff_red_for_known_reading_mismatch():
    result = auto_text_diff("字", "khác", lexicon=Lexicon({"字": ["chữ"]}))
    assert result.elements is not None
    assert result.elements and result.elements[0].type == "error"
    assert "DIFF_READING_MISMATCH" in result.flags


def test_auto_diff_never_red_for_unknown_dictionary_char():
    result = auto_text_diff("字", "khác", lexicon=None, dictionary=None)
    assert result.elements == []
    assert "DIFF_UNVERIFIED_NO_BOOK_READINGS" in result.flags


def test_mask_only_difference_is_black_and_excluded():
    result = auto_text_diff("[MASK]字", "字", lexicon=Lexicon({"字": ["tự"]}))
    assert result.elements == []
    assert "MASK_ONLY_DIFFERENCE" in result.flags
    assert scoreable_nom_chars("[MASK]字") == 1


def test_yellow_spans_are_excluded_from_denominator():
    yellow = make_element("字字", "x", [[0, 1]], [], "warn")
    assert scoreable_nom_chars("字字", [yellow]) == 1
