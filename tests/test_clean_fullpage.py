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


def test_model_talk_glued_to_page_text_is_removed():
    # Dẫn Đàng Phần 1 PDF 224 (halves stitched into one line) and PDF 461.
    page = clean_quoc_ngu_page("B", 224, "B.224.jpg", [
        "-222- (229) mà con chẳng có ra trắng cùng tốt lành sạch sẽ mọi đàng thì làm sao? "
        "Tôi không thể trích xuất toàn bộ văn bản tiếng Việt từ ảnh. Ảnh chỉ hiển thị một phần "
        "văn bản mờ nhạt, không đủ để đọc được toàn bộ nội dung."
    ])
    assert page.text == "mà con chẳng có ra trắng cùng tốt lành sạch sẽ mọi đàng thì làm sao?"
    assert "QN_MODEL_TALK_REMOVED" in page.flags
    page = clean_quoc_ngu_page("B", 461, "B.461.jpg", [
        "Đoạn thứ 21: Giảng về sự dọn mình chịu lễ ...234 * Mục lục chung ...443 "
        "Không có bất kỳ văn bản tiếng Việt nào trong ảnh."
    ])
    assert page.text == "Đoạn thứ 21: Giảng về sự dọn mình chịu lễ ...234 * Mục lục chung ...443"
    echo = clean_quoc_ngu_page("B", 11, "B.011.jpg", [
        "Trích xuất toàn bộ văn bản tiếng Việt có trong ảnh. Chỉ trả về phần văn bản, mỗi dòng "
        "một dòng, theo đúng thứ tự từ trên xuống dưới.", "(không có nội dung)"
    ])
    assert echo.text == ""


def test_printed_anh_is_not_model_talk():
    text = "Ví dù con đã có ảnh Đức Chúa Giê-su thì phải hôn ảnh ấy. Không ai được phá ảnh tượng ấy."
    page = clean_quoc_ngu_page("B", 169, "B.169.jpg", [text])
    assert page.text == text and "QN_MODEL_TALK_REMOVED" not in page.flags
