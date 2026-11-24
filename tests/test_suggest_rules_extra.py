"""alignment.per_book.<book>.text_diff_suggest_rules_extra: book-only rules after a shared table."""

from hannom.textdiff import apply_suggest_rules, suggest_rules_from_config
from hannom.models import DiffElement

SHARED = [{"ocr": "〓", "suggest": "𦉼", "qn": "là"}]
CFG = {"alignment": {"per_book": {
    "A": {"text_diff_suggest_rules": SHARED,
          "text_diff_suggest_rules_extra": [{"ocr": "〓", "suggest": "𫀅", "qn": "xem"},
                                            {"ocr": "〓", "suggest": "〓", "qn": "x"}]},  # ocr == suggest: ignored
    "B": {"text_diff_suggest_rules": SHARED},
}}}


def test_extra_rules_are_appended_for_that_book_only():
    assert suggest_rules_from_config(CFG, "A") == (("〓", "la", "𦉼"), ("〓", "xem", "𫀅"))
    assert suggest_rules_from_config(CFG, "B") == (("〓", "la", "𦉼"),)
    assert suggest_rules_from_config(CFG, "C") == ()


def test_extra_rule_turns_the_red_placeholder_into_a_suggestion():
    el = DiffElement(((2, 3),), "〓", ((4, 7),), "xem", "error")
    out, n = apply_suggest_rules([el], suggest_rules_from_config(CFG, "A"))
    assert n == 1 and (out[0].type, out[0].suggest, out[0].reviewed) == ("warn", "𫀅", 0)
    out_b, n_b = apply_suggest_rules([el], suggest_rules_from_config(CFG, "B"))
    assert n_b == 0 and out_b[0].type == "error"
