"""Original glyph of every 〓 (Quy định v2.4: report position + glyph description)."""

from types import SimpleNamespace

from hannom.clean import clean_page_lines
from hannom.placeholders import assign_origins, code_counts, stream_origins
from hannom.report import ReportData, compute_book_report_stats, validate_report_data
from hannom.t1_map import Pair


def _row(sid, img, ch):
    return SimpleNamespace(sentence_id=sid, img_id=img, ch_txt=ch, vi_txt="x", text_diff=[])


def test_clean_records_origins_in_order():
    page = clean_page_lines("B", 1, "B.001.jpg", "nom", ["天\U000F047C主", "〓聖\U000F07EF"])
    assert page.text == "天〓主〓聖〓"
    assert page.placeholder_origins == ["U+F047C", "U+3013", "U+F07EF"]


def test_origins_follow_reading_order_into_csv_rows():
    p276 = clean_page_lines("B", 276, "B.276.jpg", "nom", ["天\U000F047C主"])
    p275 = clean_page_lines("B", 275, "B.275.jpg", "nom", ["\U000F07EF聖"])
    pairs = [Pair(ch=("B.276.jpg",), vi=("B.013.jpg",)), Pair(ch=("B.275.jpg",), vi=("B.014.jpg",))]
    origins = stream_origins(pairs, {"B.276.jpg": p276, "B.275.jpg": p275})
    rows = [_row("B.276.1", "B.276.jpg", "天〓"), _row("B.276.2", "B.276.jpg", "主〓聖")]
    recs, problems = assign_origins(rows, origins)
    assert problems == []
    assert [(r["sentence_id"], r["position"], r["code"], r["image"]) for r in recs] == [
        ("B.276.1", 1, "U+F047C", "B.276.jpg"),
        ("B.276.2", 1, "U+F07EF", "B.275.jpg"),
    ]
    assert code_counts(recs) == {"U+F047C": 1, "U+F07EF": 1}


def test_count_mismatch_is_reported_not_guessed():
    recs, problems = assign_origins([_row("B.1", "B.1.jpg", "〓〓")], [("B.1.jpg", "U+F047C")])
    assert problems and all(r["code"] == "unknown" for r in recs)


def test_report_requires_a_description_per_code():
    st = compute_book_report_stats([_row("B.1", "B.1.jpg", "天〓")], None, "", [("B.1.jpg", "U+F047C")])
    assert st["placeholder_codes"] == {"U+F047C": 1}
    data = ReportData()
    data.book_stats = {"B": st}
    assert any(i.startswith("REPORT_PLACEHOLDER_DESCRIPTION_MISSING:B:U+F047C") for i in validate_report_data(data))
    data.placeholder_descriptions = {"U+F047C": "mô tả mẫu (test)"}
    assert not any("PLACEHOLDER_DESCRIPTION" in i for i in validate_report_data(data))


def test_origins_survive_a_reviewer_replacing_one_placeholder():
    p276 = clean_page_lines("B", 276, "B.276.jpg", "nom", ["天\U000F047C主\U000F07EF聖"])
    pairs = [Pair(ch=("B.276.jpg",), vi=("B.013.jpg",))]
    # the reviewer found the first glyph in Unicode and typed it in place of 〓
    labels = {"ch/B.276.jpg": [{"transcription": "天羅主"}, {"transcription": "〓聖"}]}
    origins = stream_origins(pairs, {"B.276.jpg": p276}, labels)
    assert origins == [("B.276.jpg", "U+F07EF")]
    recs, problems = assign_origins([_row("B.276.1", "B.276.jpg", "天羅主〓聖")], origins)
    assert problems == [] and recs[0]["code"] == "U+F07EF"
