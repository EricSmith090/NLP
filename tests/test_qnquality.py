"""Phonetic-recall QN quality metric and RC10 detection (FIX_PLAN T2.2 / T2.4)."""

from hannom.qnquality import (
    boxes_from_clean,
    classify,
    lcs_matches,
    page_quality,
    reversed_order_gain,
    syllable_key,
)

KEYS = {c: frozenset({syllable_key(r)}) for c, r in zip("天主聖神阿綿", ["thiên", "chúa", "thánh", "thần", "a", "men"])}


def test_syllable_key_ignores_tone_placement_not_tone():
    assert syllable_key("hoà") == syllable_key("hòa")
    assert syllable_key("Chúa") == syllable_key("chúa")
    assert syllable_key("chúa") != syllable_key("chua")


def test_lcs_counts_ordered_reading_matches():
    assert lcs_matches(list("天主聖神"), "Thiên Chúa Thánh Thần".split(), KEYS) == 4
    assert lcs_matches(list("天主聖神"), "Thánh Thần Thiên Chúa".split(), KEYS) == 2
    assert lcs_matches(list("天主"), [], KEYS) == 0


def test_page_quality_and_queue():
    q = page_quality("Thiên Chúa Thánh Thần", list("天主聖神"), KEYS)
    assert q["recall"] == 1.0 and q["coverage"] == 1.0 and q["rep8"] == 0
    assert classify(q) == "review"
    assert classify(dict(q, recall=0.3)) == "manual_qn"
    assert classify(dict(q, recall=0.7)) == "priority_review"


def test_reversed_page_detection():
    # Columns returned right-to-left in the image frame of an upside-down page.
    fwd, rev = reversed_order_gain("Thiên Chúa Thánh Thần A men", ["阿綿", "聖神", "天主"], KEYS)
    assert rev == 1.0 and fwd < 0.5
    assert classify({"recall": fwd, "coverage": 1.0, "rep8": 1}, (fwd, rev)) == "nom_reversed"


def test_boxes_from_clean_groups_by_source():
    assert boxes_from_clean(["天", "主", "聖神"], [0, 0, 2]) == ["天主", "聖神"]
    assert boxes_from_clean(["天主"], []) == ["天主"]
