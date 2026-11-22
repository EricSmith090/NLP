"""Yellow for transliterated names (config key text_diff_name_blocks), 2026-11-22.

TA (asked about 秋 <-> "su" in Giê-su: "tên riêng phiên âm có cùng số chữ
nhưng từ điển không ghi âm"): "Bạn đánh vàng nhé". Inside a hyphenated QN
name the differing chars turn yellow; chars whose reading matches stay black.
Never when it would hide what the spec colours red: 〓, a char without
readings, a pending suggestion, a duplicated/missing/swallowed char (not
1-1), or a minority spelling of the name in the book (an OCR misreading).
"""

from collections import Counter

from hannom.textdiff import name_key, name_spelling_table, spec_text_diff, validate_text_diff

READ = {
    "翁": ["ông"], "卢": ["lô"], "搓": ["sai"], "批": ["phê"], "樣": ["dạng"], "髀": ["bễ"],
    "支": ["chi", "giê"], "秋": ["thu"], "主": ["chúa"], "亞": ["á"], "離": ["li"], "德": ["đức"], "妑": ["bà"],
    "衣": ["y"], "計": ["kế"], "移": ["di"], "加": ["gia"],
}


class _Lex:
    def readings(self, ch):
        return READ.get(ch, [])


def diff(nom, vi, **kw):
    out = spec_text_diff(nom, vi, lexicon=_Lex(), **{"name_blocks": True, **kw})
    assert validate_text_diff(nom, vi, out.elements) == []
    return out


def els(out):
    return [(e.type, e.nom_sub_text, e.vi_sub_text, e.reviewed) for e in out.elements]


def test_only_the_differing_chars_of_a_name_turn_yellow():
    # 支 reads "giê": black. 秋 has no reading "su": yellow (the TA's case).
    out = diff("德主支秋", "Đức Chúa Giê-su")
    assert els(out) == [("warn", "秋", "su", 0)] and "DIFF_NAME_WARN" in out.flags  # 德主支 black
    # consecutive differing chars form one element, the matching 加 stays black
    assert els(diff("衣計移加", "I-ghê-rê-gia")) == [("warn", "衣計移", "I-ghê-rê", 0)]
    # a matching char in the middle splits the yellow in two
    assert els(diff("卢離批", "Lu-li-phe")) == [("warn", "卢", "Lu", 0), ("warn", "批", "phe", 0)]
    assert els(diff("離亞", "Li-a")) == []  # every syllable matches: black, as spec example 027.3


def test_off_by_default_the_name_stays_red():
    out = spec_text_diff("卢離批", "Lu-li-phe", lexicon=_Lex())
    assert [e.type for e in out.elements] == ["error", "error"] and "DIFF_NAME_WARN" not in out.flags


def test_reviewed_only_for_elements_made_of_ta_rule_pairs():
    assert els(diff("支秋", "Giê-su", warn_rules=[("秋", "su")])) == [("warn", "秋", "su", 1)]
    assert els(diff("支秋", "Giê-su")) == [("warn", "秋", "su", 0)]
    # a run mixing a rule pair and another pair is not reviewed
    assert els(diff("衣計移加", "I-ghê-rê-gia", warn_rules=[("移", "rê")])) == [("warn", "衣計移", "I-ghê-rê", 0)]


def test_no_yellow_when_nom_and_syllables_are_not_one_to_one():
    dup = diff("卢搓搓批", "Lu-si-phe")  # OCR duplicated a char: the spec says red
    assert "DIFF_NAME_WARN" not in dup.flags and all(e.type == "error" for e in dup.elements)
    missing = diff("亞", "A-ve")  # 蟡 missing from the Nôm
    assert "DIFF_NAME_WARN" not in missing.flags and ("error", "", "ve", None) in els(missing)
    edge = diff("翁卢搓批", "Lu-si-phe")  # 翁 unpaired next to the name: extent uncertain
    assert "DIFF_NAME_WARN" not in edge.flags


def test_no_yellow_over_a_placeholder():
    out = diff("卢〓批", "Lu-si-phe")
    assert "DIFF_NAME_WARN" not in out.flags
    assert any(e.type == "error" and "〓" in e.nom_sub_text for e in out.elements)


def test_minority_spelling_of_a_name_stays_red():
    table = {name_key("Lu-si-phe"): Counter({"卢搓批": 3, "卢樣批": 1})}
    assert els(diff("卢搓批", "Lu-si-phe", name_spellings=table)) == [("warn", "卢搓批", "Lu-si-phe", 0)]
    minority = diff("卢樣批", "Lu-xi-phe", name_spellings=table)  # Lu-xi-phe is the same name
    assert "DIFF_NAME_WARN" not in minority.flags
    assert any(e.type == "error" and "樣" in e.nom_sub_text for e in minority.elements)
    giesu = {name_key("Giê-su"): Counter({"支秋": 267, "德妑": 1})}
    assert "DIFF_NAME_WARN" not in diff("德妑", "Giê-su", name_spellings=giesu).flags
    tie = {name_key("Lu-si-phe"): Counter({"卢搓批": 1, "卢樣批": 1})}
    assert "DIFF_NAME_WARN" not in diff("卢搓批", "Lu-si-phe", name_spellings=tie).flags


def test_spelling_table_counts_one_to_one_occurrences_only():
    texts = [("卢搓批", "Lu-si-phe")] * 3 + [("卢樣批", "Lu-xi-phe"), ("卢搓搓批", "Lu-si-phe"),
                                             ("卢〓批", "Lu-si-phe"), ("離亞", "Li-a"), ("天", "")]
    table = name_spelling_table(texts, lexicon=_Lex())
    assert table == {"lu-si-phe": Counter({"卢搓批": 3, "卢樣批": 1}), "li-a": Counter({"離亞": 1})}


def test_name_key_merges_qn_spelling_variants():
    assert name_key("Lu-xi-phe") == name_key("Lu-si-phe") and name_key("Giu-đa") == name_key("Giu-da")
    assert name_key("Giê-su") != name_key("Giu-se")


def test_ta_rule_applies_after_the_suggestion_split():
    # Tap2 510.2: "秋髀 <-> su ra" is one 2:2 red run; the suggestion table
    # puts 髀 (OCR for 𪡔 "ra") on its own element, then 秋 <-> su is 1:1 and
    # the TA rule must make it yellow (it stayed red before 2026-11-22).
    out = spec_text_diff("支秋髀", "Giê-su ra", lexicon=_Lex(), warn_rules=[("秋", "su")],
                         suggest_rules=[("髀", "ra", "𪡔")])
    assert validate_text_diff("支秋髀", "Giê-su ra", out.elements) == []
    got = [(e.type, e.nom_sub_text, e.vi_sub_text, e.reviewed, e.suggest) for e in out.elements]
    assert got == [("warn", "秋", "su", 1, None), ("warn", "髀", "ra", 0, "𪡔")]
