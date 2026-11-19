"""Nôm page furniture removed at clean time (FIX_PLAN T3.1, RC9).

Positions are the measured ones from the T1 books (800x1135 pages unless noted).
"""

from pathlib import Path

from hannom.clean import nom_box_noise, trim_repeat_runs
from hannom.models import OCRLine, PageRecord
from hannom.orchestrator import order_and_clean_page


def _pts(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_folio_in_outer_margin_band_is_removed():
    assert nom_box_noise("一百十九", _pts(115, 758, 145, 870), 0.99, 800, 1135) == "folio"
    assert nom_box_noise("三百八十六", _pts(622, 754, 652, 900), 0.99, 800, 1135) == "folio"
    # 564x800 Tap2 pages: same relative position
    assert nom_box_noise("三百七十六", _pts(432, 533, 452, 640), 0.99, 564, 800) == "folio"
    # upside-down page: the folio sits top-right in the image frame
    assert nom_box_noise("一百十九", _pts(656, 238, 690, 375), 0.99, 800, 1135, mirrored=True) == "folio"


def test_body_text_numerals_stay():
    assert nom_box_noise("五", _pts(142, 145, 160, 190), 0.95, 800, 1135) is None  # Tap2 p.312 top of column
    assert nom_box_noise("五", _pts(108, 823, 128, 870), 0.95, 800, 1135) is None  # Tap1 p.234 y0 = 0.725
    assert nom_box_noise("三", _pts(300, 888, 320, 930), 0.95, 800, 1135) is None  # Tap1 p.263
    assert nom_box_noise("三百十六", _pts(336, 772, 360, 920), 0.99, 800, 1135) is None  # index page, inside body


def test_ornament_needs_corner_low_confidence_and_short_text():
    assert nom_box_noise("熙", _pts(129, 122, 154, 158), 0.47, 800, 1135) == "ornament"
    assert nom_box_noise("熙", _pts(129, 122, 154, 158), 0.95, 800, 1135) is None
    assert nom_box_noise("天主", _pts(400, 122, 430, 158), 0.40, 800, 1135) is None  # not in a corner
    assert nom_box_noise("天主聖", _pts(129, 122, 154, 158), 0.40, 800, 1135) is None  # 3 chars


def test_running_title_from_config_and_repeat_runs():
    assert nom_box_noise("所𥚇卷", _pts(660, 101, 695, 200), 0.99, 800, 1135, strip_texts=frozenset({"所𥚇卷"})) == "running_title"
    assert trim_repeat_runs("相无无无无", 0.63) == ("相", ["无无无无"])
    assert trim_repeat_runs("相无无无无", 0.95) == ("相无无无无", [])
    assert trim_repeat_runs("嘉嘉嘉", 0.40) == ("嘉嘉嘉", [])


def test_page_text_and_labels_drop_the_same_boxes():
    page = PageRecord(book_id="T1_Test", page_no=150, image_name="T.150.jpg", pdf_page=150, sha256="0" * 64,
                      width=800, height=1135, path=Path("x.jpg"), script="nom", folder="ch")
    lines = [
        OCRLine("天主", tuple(map(tuple, _pts(600, 100, 640, 600))), 0.99, None),
        OCRLine("相无无无无", tuple(map(tuple, _pts(560, 100, 600, 600))), 0.60, None),
        OCRLine("一百十九", tuple(map(tuple, _pts(115, 758, 145, 870))), 0.99, None),
    ]
    cleaned, boxes = order_and_clean_page("T1_Test", page, "nom", lines, None)
    assert [b.text for b in boxes] == ["天主", "相"]
    assert cleaned.text == "天主相"
    assert {d["reason"] for d in cleaned.box_drops} == {"folio", "repeat_run"}
    assert "FOLIO_REMOVED" in cleaned.flags and "REPEAT_RUN_REMOVED" in cleaned.flags


def test_inline_parenthesised_footnote_marks_are_removed():
    from hannom.clean import _strip_inline_refs

    assert _strip_inline_refs("chẳng có lấy nanh(5) mà cắn")[0] == "chẳng có lấy nanh mà cắn"
    assert _strip_inline_refs("vì dái lây(7). Đến sau")[0] == "vì dái lây. Đến sau"
    assert _strip_inline_refs("xuống địa ngục (1) tôi")[0] == "xuống địa ngục tôi"
    assert _strip_inline_refs("năm 1571 (A.D.)") == ("năm 1571 (A.D.)", False)


def test_format_chars_and_variation_selectors_are_removed_not_placeholdered():
    from hannom.clean import clean_page_lines, remove_control

    assert remove_control("天︀主‍聖﻿\U000e0101") == "天主聖"
    page = clean_page_lines("B", 1, "B.001.jpg", "nom", ["天︀主​聖"])
    assert page.text == "天主聖" and "〓" not in page.text
    qn = clean_page_lines("B", 2, "B.002.jpg", "qn", ["Thiên​ Chúa­"])
    assert qn.text == "Thiên Chúa"
