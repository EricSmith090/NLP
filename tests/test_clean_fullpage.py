from __future__ import annotations

from hannom.clean import clean_quoc_ngu_page


def test_full_page_leading_mark_is_stripped():
    page = clean_quoc_ngu_page("b", 12, "Book.012.jpg", ["-10 ( 113 ) khốn nạn gốm ghiếc lắm, song"])
    assert page.text == "khốn nạn gốm ghiếc lắm, song"
    assert "PAGE_MARK_REMOVED" in page.flags


def test_full_page_leading_mark_dash_only():
    page = clean_quoc_ngu_page("b", 16, "Book.016.jpg", ["-14- ( 109 )"])
    assert page.text == ""
    assert "PAGE_MARK_REMOVED" in page.flags


def test_full_page_leading_mark_dash_only():
    page = clean_quoc_ngu_page("b", 16, "Book.016.jpg", ["-14- ( 109 )"])
    assert page.text == ""
    assert "PAGE_MARK_REMOVED" in page.flags


def test_full_page_leading_mark_dash_with_parens():
    # v2.1 fix set: the lone title colophon after a page marker is removed
    # line-by-line (verify-D fix #5/#8; the whole page is flagged empty).
    page = clean_quoc_ngu_page("b", 32, "Book.032.jpg", ["-30 - (93) Sửa Lưới"])
    assert page.text == ""
    assert "PAGE_MARK_REMOVED" in page.flags
    assert "FOOTER_TITLE_REMOVED" in page.flags
    assert "EMPTY_AFTER_CLEAN" in page.flags


def test_full_page_trailing_title_footer_is_suspect():
    # v2.1 fix set: a body line ending in the book's theme words is kept and
    # flagged for review, never silently deleted (verify-D fix #5).
    page = clean_quoc_ngu_page(
        "b", 12, "Book.012.jpg",
        ["ho nó trả của ta thì nên hay là Sửa Lứỡi"],
    )
    assert page.text == "ho nó trả của ta thì nên hay là Sửa Lứỡi"
    assert "FOOTER_TITLE_SUSPECT" in page.flags
    assert "FOOTER_TITLE_REMOVED" not in page.flags


def test_full_page_trailing_title_uppercase_qui():
    page = clean_quoc_ngu_page(
        "b", 9, "Book.009.jpg",
        ["-7 BẢN QUỐC NGỮ SỬA LƯỚI QUYỀN"],
    )
    # The remainder is body text ending in a letter: kept, flagged suspect.
    assert page.text == "-7 BẢN QUỐC NGỮ SỬA LƯỚI QUYỀN"
    assert "FOOTER_TITLE_SUSPECT" in page.flags


def test_full_page_title_like_content_is_removed():
    # A page whose only line is the colophon itself is removed and flagged
    # empty (verify-D §6 fix #5/#8: page never blanked is no longer a rule;
    # an apparatus-only page must be reported as EMPTY_AFTER_CLEAN).
    page = clean_quoc_ngu_page("b", 2, "Book.002.jpg", ["SỬA LUỘI QUYỀN"])
    assert page.text == ""
    assert "FOOTER_TITLE_REMOVED" in page.flags
    assert "EMPTY_AFTER_CLEAN" in page.flags


def test_full_page_lowercase_title_is_kept():
    # Lowercase 'sửa lưới' inside prose is legitimate content.
    page = clean_quoc_ngu_page("b", 5, "Book.005.jpg", ["xin sửa lưới cho đẹp"])
    assert page.text == "xin sửa lưới cho đẹp"


def test_full_page_mid_sentence_content_is_kept():
    page = clean_quoc_ngu_page("b", 17, "Book.017.jpg", ["một người nói là Sửa Lứỡi là ai đó"])
    assert page.text == "một người nói là Sửa Lứỡi là ai đó"
