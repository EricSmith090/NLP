"""Table-of-contents rows: one entry with its page number (instructor, 2026-11-21)."""

from hannom.charstream import toc_sentence_spans
from hannom.cosegment import qn_sentence_spans

# QN text of Cấm Phòng Tập 1 PDF 15 (page numbers as printed), 16, 20, then the body.
P15 = ("MỤC LỤC - Cấm phòng cho bổn đạo đủ 10 ngày. Tựa 1 PHẦN THỨ NHẤT 3 Tóm lại các bài ngắm. "
       "Cắt nghĩa thứ tự cùng ý tứ các bài ngắm trong tuần cấm phòng. Ngày thứ nhất ✣ Ban sớm mai, ngắm về "
       "sự cấm phòng là thế nào. 7 ✣ Ban chiều hôm, ngắm về sự Đức Chúa Trời có ý nào mà dựng nên loài người ta. 19")
P16 = ("- Ngày thứ ba - Ban sớm mai, ngắm về những sự dữ và những sự thiệt hại bởi tội trọng mà ra. 58 "
       "- Ban chiều hôm, ngắm về sự Đức Chúa Trời phạt tội trọng là thế nào. 68 - Ngày thứ tư - Ban sớm mai, "
       "ngắm về đôi ba tội trọng quen gọi là cửa địa ngục. 77")
P20 = ("- Bài thứ chín: Về tội dâm dục. 326 - Bài thứ mười: Về sự đền của người ta. 337 "
       "- Bài thứ mười ba: Về sự giữ ơn Đức Chúa Trời cho vững vàng. 374")
BODY = "CẤM PHÒNG CHO BỔN ĐẠO ĐỦ 10 NGÀY Tựa Ta làm sách này. Bài thứ nhất: Ai nấy phải lo. 12 người đến."


def pieces(*pages, toc=None):
    text, ranges, pos = "", [], 0
    for k, page in enumerate(pages):
        if k:
            text += " "
            pos += 1
        if toc is None or k in toc:
            ranges.append((pos, pos + len(page)))
        text += page
        pos += len(page)
    spans = toc_sentence_spans(text, qn_sentence_spans(text), ranges)
    return [text[a:b] for a, b, _n in spans]


def test_entries_end_after_their_page_number():
    assert pieces(P16) == [
        "- Ngày thứ ba - Ban sớm mai, ngắm về những sự dữ và những sự thiệt hại bởi tội trọng mà ra. 58",
        "- Ban chiều hôm, ngắm về sự Đức Chúa Trời phạt tội trọng là thế nào. 68",
        "- Ngày thứ tư - Ban sớm mai, ngắm về đôi ba tội trọng quen gọi là cửa địa ngục. 77",
    ]


def test_title_line_headings_and_short_pieces():
    assert pieces(P15) == [
        "MỤC LỤC - Cấm phòng cho bổn đạo đủ 10 ngày. Tựa 1",  # "đủ 10 ngày" is no page number; "Tựa 1" joins its line
        "PHẦN THỨ NHẤT 3",
        "Tóm lại các bài ngắm.",
        "Cắt nghĩa thứ tự cùng ý tứ các bài ngắm trong tuần cấm phòng.",
        "Ngày thứ nhất ✣ Ban sớm mai, ngắm về sự cấm phòng là thế nào. 7",
        "✣ Ban chiều hôm, ngắm về sự Đức Chúa Trời có ý nào mà dựng nên loài người ta. 19",
    ]


def test_no_cut_after_colon_and_the_body_after_the_toc_is_untouched():
    out = pieces(P20, BODY, toc={0})
    assert out[:3] == [
        "- Bài thứ chín: Về tội dâm dục. 326",
        "- Bài thứ mười: Về sự đền của người ta. 337",
        "- Bài thứ mười ba: Về sự giữ ơn Đức Chúa Trời cho vững vàng. 374",
    ]
    # outside the TOC the ordinary cuts stay, ":" and a leading number included
    body = [text for text in out[3:]]
    assert body == [p for p in pieces(BODY, toc=set())]


def test_the_toc_starts_its_own_row():
    title = "CẤM PHÒNG CHO BỔN ĐẠO Giám mục Phê-rô Ma-ri-a Đông truyền tử"  # title page, no stop
    out = pieces(title, P15, toc={1})
    assert out[0] == title
    assert out[1] == "MỤC LỤC - Cấm phòng cho bổn đạo đủ 10 ngày. Tựa 1"


def test_page_numbers_are_not_cut_in_two_on_toc_pages():
    from types import SimpleNamespace as NS

    from hannom.charstream import keep_numeral_runs_together

    chars = [NS(ch=c, page="p270") for c in "信二百六十四排"] + [NS(ch=c, page="p100") for c in "二百"]
    ops = [NS(i=k) for k in range(len(chars))]
    sent = [0, 0, 0, 1, 1, 1, 1, 2, 3]
    assert keep_numeral_runs_together(chars, ops, sent, {"p270"}) == [0, 0, 0, 0, 0, 0, 1, 2, 3]
    assert keep_numeral_runs_together(chars, ops, sent, set()) == sent  # no TOC pages: untouched


def test_without_toc_pages_nothing_changes():
    text = P16
    spans = qn_sentence_spans(text)
    assert toc_sentence_spans(text, spans, []) == spans
