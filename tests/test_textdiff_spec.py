"""text_diff per Quy định v2.4 / ocr-nom-align v0.2.0 defaults (FIX_PLAN T3.2, RC5/RC7).

Expected outputs were cross-checked against the official `diff.text_diff`
(2026-11-19, identical on every case below).
"""

import json

from hannom.align import row_from_dict, write_alignment_csv, read_alignment_csv
from hannom.models import AlignmentRow, DiffElement
from hannom.textdiff import red_penalty, scoreable_nom_chars, spec_text_diff, tone_key, validate_text_diff

READ = {"天": ["thiên"], "主": ["chúa"], "聖": ["thánh"], "神": ["thần"], "母": ["mẫu"], "年": ["niên"]}


class _Lex:
    def readings(self, ch):
        return READ.get(ch, [])


def _diff(nom, vi):
    out = spec_text_diff(nom, vi, lexicon=_Lex())
    assert validate_text_diff(nom, vi, out.elements) == []
    return [e.to_dict() for e in out.elements]


def test_tone_key_removes_only_the_five_tones():
    assert tone_key("Thiền") == tone_key("thiên") == "thiên"
    assert tone_key("mẫu") == "mâu" != tone_key("mau")
    assert tone_key("đến") == "đên" != tone_key("dến")


def test_exact_and_tone_only_differences_are_black():
    assert _diff("天主聖神", "Thiên Chúa Thánh Thần") == []
    assert _diff("天主", "Thiền Chúa") == []


def test_vowel_quality_difference_is_red():
    assert _diff("母", "mau") == [
        {"nom_pos": [[0, 1]], "nom_sub_text": "母", "vi_pos": [[0, 3]], "vi_sub_text": "mau", "type": "error"}
    ]


def test_missing_syllable_and_extra_syllables_are_red():
    assert _diff("天主聖神", "Thiền Chúa Thánh") == [
        {"nom_pos": [[3, 4]], "nom_sub_text": "神", "vi_pos": [], "vi_sub_text": "", "type": "error"}
    ]
    assert _diff("天主", "Thiên Chúa Ba Ngôi") == [
        {"nom_pos": [], "nom_sub_text": "", "vi_pos": [[11, 18]], "vi_sub_text": "Ba Ngôi", "type": "error"}
    ]


def test_placeholder_and_unknown_char_are_red():
    assert _diff("母〓", "mẫu xx")[0]["nom_sub_text"] == "〓"
    assert _diff("天主𡨸", "Thiên Chúa chữ") == [
        {"nom_pos": [[2, 3]], "nom_sub_text": "𡨸", "vi_pos": [[11, 14]], "vi_sub_text": "chữ", "type": "error"}
    ]


def test_number_run_is_yellow_with_reviewed_key():
    (el,) = _diff("年", "năm 1571")
    assert el["type"] == "warn" and el["reviewed"] == 0 and el["vi_sub_text"] == "năm 1571"
    assert list(el) == ["nom_pos", "nom_sub_text", "vi_pos", "vi_sub_text", "type", "reviewed"]


def test_mask_segments_pair_up():
    assert _diff("天[MASK]主", "Thiên [MASK] Chúa") == []


def test_score_counts_like_the_official_formula():
    nom, vi = "天主〓神", "Thiên Chúa x y Thần 3"
    els = spec_text_diff(nom, vi, lexicon=_Lex()).elements
    assert scoreable_nom_chars(nom, els) == 4  # 〓 is in the denominator
    assert red_penalty(els) == 2 + 1  # 〓 against "x y" (2) + the extra trailing number "3" (1)
    warn = DiffElement(((0, 1),), "年", ((0, 4),), "1571", "warn", reviewed=1)
    assert scoreable_nom_chars("年", [warn]) == 0


def test_warn_keys_round_trip_and_error_keeps_five_keys(tmp_path):
    warn = DiffElement(((0, 1),), "年", ((4, 8),), "1571", "warn", reviewed=1, suggest="念", suggest_by="similar")
    err = DiffElement(((1, 2),), "母", ((9, 12),), "mau", "error", reviewed=1)
    assert len(err.to_dict()) == 5
    row = AlignmentRow("B.001.jpg", "B.001.1", "年母", "năm 1571 mau", [warn, err])
    path = write_alignment_csv(tmp_path / "b.csv", [row])
    (back,) = read_alignment_csv(path)
    assert back.text_diff[0].to_dict() == warn.to_dict()
    assert back.text_diff[1].to_dict() == err.to_dict()


def test_empty_text_diff_cell_is_not_read_as_fully_matching():
    row = row_from_dict({"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": "天", "vi_txt": "thiên", "text_diff": ""})
    assert row.text_diff is None and "TEXT_DIFF_EMPTY_CELL" in row.flags
    ok = row_from_dict({"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": "天", "vi_txt": "thiên", "text_diff": json.dumps([])})
    assert ok.text_diff == []


def test_missing_type_is_invalid_not_silently_red():
    row = row_from_dict({"img_id": "B.001.jpg", "sentence_id": "B.001.1", "ch_txt": "天", "vi_txt": "x",
                         "text_diff": json.dumps([{"nom_pos": [[0, 1]], "nom_sub_text": "天", "vi_pos": [[0, 1]], "vi_sub_text": "x"}])})
    assert row.text_diff[0].type == ""
    assert validate_text_diff("天", "x", row.text_diff)  # reported as invalid
    assert red_penalty(row.text_diff) == 0
