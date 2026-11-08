from __future__ import annotations

from hannom.clean import (
    MASK,
    clean_nom_page,
    clean_quoc_ngu_page,
    detect_running_lines,
    nfc,
    validate_clean_text,
)


def test_nom_cleaning_removes_page_numbers_and_spaces():
    page = clean_nom_page("b", 1, "Book.001.jpg", ["字 字", "123", "第二。", "第二。"])
    assert page.text == "字字第二。"
    assert "123" in page.dropped_lines
    assert not validate_clean_text(page.text, "nom")


def test_nom_punctuation_is_normalized_without_inventing():
    page = clean_nom_page("b", 1, "Book.001.jpg", ["字,字.字?"])
    assert page.text == "字、字。字？"


def test_mask_remains_exactly_six_characters():
    page = clean_nom_page("b", 1, "Book.001.jpg", ["字[MASK]字"])
    assert MASK in page.text
    assert len(MASK) == 6
    assert not validate_clean_text(page.text, "nom")


def test_nfc_normalization():
    page = clean_quoc_ngu_page("b", 1, "Book.001.jpg", ["e\u0301"])
    assert page.text == "é"
    assert nfc(page.text) == page.text


def test_qn_keeps_spaces_and_joins_hyphenated_line_break():
    page = clean_quoc_ngu_page("b", 1, "Book.001.jpg", ["A-", "ve", "đi"])
    assert page.text == "A-ve đi"


def test_running_header_detection():
    pages = [["SÁCH MẪU", "dòng nội dung", "1"] for _ in range(6)]
    lines = detect_running_lines(pages, min_pages=5)
    assert "sách mẫu" in lines
