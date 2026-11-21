"""Book-scoped OCR suggestion rules (Quy định v2.4: yellow-by-suggestion working state)."""

from __future__ import annotations

from hannom.models import AlignmentRow, DiffElement
from hannom.review.edit import reject_suggest, suggest_edit_text
from hannom.textdiff import apply_suggest_rules, suggest_rules_from_config, tone_key, validate_text_diff

RAW = {"alignment": {"per_book": {"BookA": {"text_diff_suggest_rules": [
    {"ocr": "𠯇", "suggest": "吧", "qn": "và", "note": "x"},
    {"ocr": "楼", "suggest": "𢖕", "qn": "sau"},
    {"ocr": "楼", "suggest": "婪", "qn": "lam"},
]}}}}


def test_rules_are_book_scoped():
    rules = suggest_rules_from_config(RAW, "BookA")
    assert ("𠯇", tone_key("và"), "吧") in rules and len(rules) == 3
    assert suggest_rules_from_config(RAW, "BookB") == ()
    assert suggest_rules_from_config(RAW, None) == ()


def test_single_char_error_becomes_warn_with_suggest():
    ch, vi = "主𠯇碎", "Chúa và tôi"
    el = DiffElement(((1, 2),), "𠯇", ((5, 7),), "và", "error")
    out, n = apply_suggest_rules([el], suggest_rules_from_config(RAW, "BookA"))
    assert n == 1 and len(out) == 1
    w = out[0]
    assert (w.type, w.suggest, w.suggest_by, w.reviewed) == ("warn", "吧", "similar", 0)
    assert w.to_dict() == {"nom_pos": [[1, 2]], "nom_sub_text": "𠯇", "vi_pos": [[5, 7]], "vi_sub_text": "và",
                           "type": "warn", "reviewed": 0, "suggest": "吧", "suggest_by": "similar"}
    assert validate_text_diff(ch, vi, out) == []


def test_equal_length_run_is_split_and_other_chars_stay_red():
    ch, vi = "秋𠯇楼", "su và sau"
    el = DiffElement(((0, 3),), "秋𠯇楼", ((0, 9),), "su và sau", "error")
    out, n = apply_suggest_rules([el], suggest_rules_from_config(RAW, "BookA"))
    assert n == 2
    assert [(e.nom_sub_text, e.vi_sub_text, e.type, e.suggest) for e in out] == [
        ("秋", "su", "error", None), ("𠯇", "và", "warn", "吧"), ("楼", "sau", "warn", "𢖕")]
    assert validate_text_diff(ch, vi, out) == []


def test_wrong_syllable_or_unequal_run_untouched():
    rules = suggest_rules_from_config(RAW, "BookA")
    a = DiffElement(((0, 1),), "𠯇", ((0, 3),), "rẽ", "error")  # not the expected reading
    b = DiffElement(((0, 2),), "𠯇主", ((0, 2),), "và", "error")  # 2 chars <-> 1 syllable
    out, n = apply_suggest_rules([a, b], rules)
    assert n == 0 and out == [a, b]


def test_accept_and_reject_follow_v24():
    row = AlignmentRow(img_id="x.001.jpg", sentence_id="x.001.1", ch_txt="主𠯇碎", vi_txt="Chúa và tôi")
    row.text_diff = [DiffElement(((1, 2),), "𠯇", ((5, 7),), "và", "warn", reviewed=0, suggest="吧",
                                 suggest_by="similar")]
    assert suggest_edit_text(row, 0) == "主吧碎"  # (b) accept: the suggestion replaces the OCR char
    reject_suggest(row, 0)  # (c) reject: plain red error with exactly the 5 keys
    assert row.text_diff[0].to_dict() == {"nom_pos": [[1, 2]], "nom_sub_text": "𠯇", "vi_pos": [[5, 7]],
                                          "vi_sub_text": "và", "type": "error"}
