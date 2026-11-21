"""tools/harvest_name_rules.py: proper-name detection and click harvesting helpers."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "harvest_name_rules.py"
_spec = importlib.util.spec_from_file_location("harvest_name_rules", _PATH)
hnr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hnr)


def test_is_name_needs_capital_and_hyphen():
    assert hnr.is_name("Giê-su")
    assert hnr.is_name("An-ti-ô-cô")
    assert not hnr.is_name("giê-bi-ô")  # lower-case start
    assert not hnr.is_name("Rôma")  # no hyphen
    assert not hnr.is_name("Giê-")  # empty syllable
    assert not hnr.is_name("1-2")


def test_token_at_strips_outer_punctuation_only():
    text = "thành Giê-ru-gia-lem, tội giết"
    pos = text.index("lem")
    s, e, tok = hnr.token_at(text, pos)
    assert tok == "Giê-ru-gia-lem"
    assert text[s:e] == "Giê-ru-gia-lem,"


def test_single_pair_is_one_char_one_syllable():
    assert hnr.single_pair({"nom_sub_text": "臯", "vi_sub_text": "ti"}) == ("臯", "ti")
    assert hnr.single_pair({"nom_sub_text": "臯烏", "vi_sub_text": "ti"}) is None
    assert hnr.single_pair({"nom_sub_text": "臯", "vi_sub_text": "ti ô"}) is None
    assert hnr.single_pair({"nom_sub_text": "", "vi_sub_text": "ti"}) is None


def test_name_of_finds_the_enclosing_name():
    row = {"vi_txt": "Khi vua An-ti-ô-cô thấy mình"}
    el = {"vi_pos": [[row["vi_txt"].index("ti"), row["vi_txt"].index("ti") + 2]]}
    assert hnr.name_of(row, el)[2] == "An-ti-ô-cô"
    el2 = {"vi_pos": [[row["vi_txt"].index("thấy"), row["vi_txt"].index("thấy") + 4]]}
    assert hnr.name_of(row, el2) is None
