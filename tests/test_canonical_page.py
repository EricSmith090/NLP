"""order_and_clean_page: one canonical text for Label.txt and data/clean (FIX_PLAN T1.1-T1.3, RC1-RC3, RC10)."""

from pathlib import Path

from hannom.models import OCRLine, PageRecord
from hannom.orchestrator import order_and_clean_page


def _page(script="nom", folder="ch", page_no=67):
    return PageRecord(
        book_id="T1_Test", page_no=page_no, image_name=f"Test.{page_no:03d}.jpg", pdf_page=page_no,
        sha256="0" * 64, width=800, height=1135, path=Path("x.jpg"), script=script, folder=folder,
    )


def _box(text, x0, y0, x1, y1, conf=0.9):
    return OCRLine(text, ((x0, y0), (x1, y0), (x1, y1), (x0, y1)), conf, None)


def test_nom_keeps_api_order_for_split_column():
    # A column split into two boxes: API order is top part then bottom part.
    # The old x-centre sort put the narrower bottom box first (SLQ p.67 `阿綿`).
    lines = [
        _box("天主", 600, 100, 660, 300),
        _box("聖神", 560, 100, 620, 900),
        _box("阿綿", 600, 800, 640, 900),
    ]
    cleaned, boxes = order_and_clean_page("T1_Test", _page(), "nom", lines, None)
    assert [b.text for b in boxes] == ["天主", "聖神", "阿綿"]
    assert "".join(b.text for b in boxes) == cleaned.text
    assert boxes[2].points == lines[2].points


def test_nom_dropped_box_is_not_labelled_and_text_rebuilds():
    lines = [_box("一百十九", 650, 50, 690, 200), _box("天主", 600, 100, 640, 300), _box("", 10, 10, 20, 20)]
    running = {"一百十九"}
    cleaned, boxes = order_and_clean_page("T1_Test", _page(), "nom", lines, running)
    assert [b.text for b in boxes] == ["天主"]
    assert cleaned.text == "天主"
    assert cleaned.line_sources == [1]


def test_nom_reversed_page():
    lines = [_box("甲乙", 600, 100, 640, 900), _box("丙丁", 500, 100, 540, 900)]
    cleaned, boxes = order_and_clean_page("T1_Test", _page(), "nom", lines, None, reverse_nom=True)
    assert [b.text for b in boxes] == ["丙丁", "甲乙"]
    assert cleaned.text == "丙丁甲乙"
    assert "NOM_ORDER_REVERSED" in cleaned.flags


def test_qn_full_page_box_is_not_truncated():
    # RC1: the old label path kept only cleaned.lines[0] of the full-page box.
    text = "- 25 - (260)\nNgày thứ nhất, ban sớm mai ngắm.\nCâu thứ hai cũng phải giữ.\nCâu thứ ba."
    box = _box(text, 0, 0, 800, 1135, None)
    cleaned, boxes = order_and_clean_page("T1_Test", _page("qn", "vi", 13), "qn", [box], None)
    assert len(boxes) == 1
    assert boxes[0].text == cleaned.text
    assert "Câu thứ ba." in boxes[0].text and "Ngày thứ nhất" in boxes[0].text
    assert "\n" not in boxes[0].text
    assert boxes[0].points == box.points


def test_qn_multiple_boxes_become_one_union_box():
    a = _box("Dòng một.", 50, 100, 700, 140)
    b = _box("Dòng hai.", 60, 150, 720, 190)
    cleaned, boxes = order_and_clean_page("T1_Test", _page("qn", "vi", 13), "qn", [b, a], None)
    assert len(boxes) == 1
    assert boxes[0].text == cleaned.text == "Dòng một. Dòng hai."
    assert boxes[0].points == ((50, 100), (720, 100), (720, 190), (50, 190))


def test_qn_empty_page_has_no_box():
    cleaned, boxes = order_and_clean_page("T1_Test", _page("qn", "vi", 13), "qn", [_box("- 3 -", 0, 0, 800, 1135, None)], None)
    assert boxes == [] and cleaned.text == ""
