"""Character-level alignment (charalign) and its v2.1 text_diff output."""

from __future__ import annotations

from hannom.charalign import (
    Matcher,
    align_streams,
    build_nom_stream,
    build_qn_stream,
    build_rows,
    clean_nom_pages,
    clean_qn_text,
    fold,
    similarity,
    validate_text_diff,
)
from hannom.dictionary.readings import Readings

READINGS = Readings(
    {
        "char": {
            "母": ["mẫu"], "聖": ["thánh"], "丕": ["phi"], "離": ["li", "ly"], "批": ["phê"],
            "付": ["phó"], "𡥵": ["con"], "尼": ["này", "nê"], "朱": ["chu", "cho"], "鬼": ["quỷ", "quỉ"],
            "典": ["điển", "đến"], "𣈜": ["ngày"], "𢖖": ["sau"],
        }
    }
)


def _rows(nom_columns: list[str], qn_text: str):
    nom, _ = build_nom_stream([("Book.010.jpg", nom_columns)])
    text, qn, _, _ = build_qn_stream([("Book.001.jpg", qn_text)])
    ops = align_streams(nom, qn, Matcher(READINGS), band=50)
    return build_rows(text, nom, qn, ops, lexicon_is_confirmed=False)


def test_fold_handles_old_spellings_and_ocr_tone_slips():
    assert fold("quỷ") == fold("quỉ") == fold("Quĩ") == "qui"
    assert fold("giấu") == fold("dấu") == "dau"
    assert fold("Đến") == "den"
    assert fold("hay") == "hay"  # y after a vowel is not turned into i


def test_rules_example_gives_the_documented_text_diff():
    rows = _rows(["母聖丕離批"], "cha Thánh Philiphê.")
    assert len(rows) == 1
    row = rows[0]
    assert row.ch_txt == "母聖丕離批"
    assert row.vi_txt == "cha Thánh Philiphê."
    by_type = {e["type"]: e for e in row.text_diff}
    assert by_type["error"] == {
        "nom_pos": [[0, 1]], "nom_sub_text": "母", "vi_pos": [[0, 3]], "vi_sub_text": "cha", "type": "error",
    }
    assert by_type["warn"] == {
        "nom_pos": [[2, 5]], "nom_sub_text": "丕離批", "vi_pos": [[10, 18]], "vi_sub_text": "Philiphê", "type": "warn",
    }
    assert validate_text_diff(row) == []
    # Denominator 5 Nôm chars - 3 yellow = 2; one red char -> 50 %.
    assert similarity(rows)["similarity_percent"] == 50.0


def test_dropped_character_is_a_gap_not_a_shift():
    # OCR dropped 尼 ("này"); everything after it must still match.
    rows = _rows(["付𡥵朱鬼典𣈜𢖖"], "Phó con này cho quỷ, đến ngày sau.")
    (row,) = rows
    assert row.text_diff == [
        {"nom_pos": [], "nom_sub_text": "", "vi_pos": [[8, 11]], "vi_sub_text": "này", "type": "error"}
    ]
    assert validate_text_diff(row) == []


def test_sentences_follow_qn_punctuation_and_ids_count_per_page():
    rows = _rows(["付𡥵尼", "朱鬼"], "Phó con này. Cho quỷ.")
    assert [r.sentence_id for r in rows] == ["Book.010.1", "Book.010.2"]
    assert [r.ch_txt for r in rows] == ["付𡥵尼", "朱鬼"]
    assert all(r.text_diff == [] for r in rows)


def test_cleaning_drops_page_numbers_footnotes_and_reads_page_marker():
    text, marker = clean_qn_text("- 10 - ( 113 ) xuống địa ngục(1) tôi đã thấy")
    assert marker == 113
    assert text == "xuống địa ngục tôi đã thấy"
    body = ["付𡥵尼朱", "鬼典𣈜𢖖", "母聖丕離", "批付𡥵尼"]
    pages = [
        (f"B.{n:03d}.jpg", [{"transcription": body[n]}, {"transcription": "付𡥵"}, {"transcription": "所𥚇卷"}])
        for n in range(4)
    ]
    cleaned, dropped = clean_nom_pages(pages)
    # The margin title goes; a short body phrase repeated mid-page stays.
    assert [cols for _, cols in cleaned] == [[b, "付𡥵"] for b in body]
    assert {(d.text, d.reason) for d in dropped} == {("所𥚇卷", "running_header")}
    # A page number on a single page is caught by the numeral rule.
    cleaned, dropped = clean_nom_pages([("B.001.jpg", [{"transcription": "付𡥵"}, {"transcription": "一百廿三"}])])
    assert cleaned == [("B.001.jpg", ["付𡥵"])]
    assert [d.reason for d in dropped] == ["page_number"]
