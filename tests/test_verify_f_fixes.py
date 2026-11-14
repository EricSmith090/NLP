"""Regression tests for the verify-F remediation.

Covers: §3 (miskeyed evidence lookup — absolute positions), §3A/R11 (variant
fold wired to config; anchor tier counters; ``DIFF_VARIANT_FOLD_APPLIED``),
§5.A/R3 (replace — never union — re-derivable recompute flags), and R7 (the
guideline "Đánh giá dữ liệu" formula reported alongside the gate number).
"""

from __future__ import annotations

from hannom.align import AlignConfig, _as_config
from hannom.models import AlignmentRow, DiffElement
from hannom.orchestrator import recompute_text_diff
from hannom.evaluate import evaluate_rows
from hannom.textdiff import auto_text_diff, variant_fold_from_config


class _FakeLexicon:
    def __init__(self, table):
        self._table = table

    def readings(self, ch):
        return list(self._table.get(ch, []))


# ---------------------------------------------------------------- §3 miskeying

def test_miskeying_punctuation_gap_no_spurious_element():
    lex = _FakeLexicon({"一": ["một"], "二": ["hai"]})
    res = auto_text_diff("一，二", "một hai", lexicon=lex)
    assert res.elements == []
    assert res.known_nom_chars == 2
    assert res.matched_readings == 2
    assert "DIFF_NO_READING_MISMATCH" in res.flags


def test_miskeying_mask_gap_no_spurious_element():
    lex = _FakeLexicon({"一": ["một"], "二": ["hai"]})
    res = auto_text_diff("一[MASK]二", "một hai", lexicon=lex)
    assert res.elements == []


def test_miskeying_gap_inside_four_char_run():
    lex = _FakeLexicon({"一": ["một"], "二": ["hai"], "三": ["ba"], "四": ["bốn"]})
    res = auto_text_diff("一二，三四", "một hai ba bốn", lexicon=lex)
    assert res.elements == []
    assert res.known_nom_chars == 4
    assert res.matched_readings == 4


def test_miskeying_pua_gap_anchors_both_sides():
    lex = _FakeLexicon({"𧵑": ["của"], "兜": ["đâu"]})
    res = auto_text_diff("\uF0152𧵑兜", "của đâu", lexicon=lex)
    assert res.elements == []


def test_genuine_mismatch_still_flagged():
    lex = _FakeLexicon({"一": ["một"]})
    res = auto_text_diff("一", "hai", lexicon=lex)
    assert res.elements is not None and len(res.elements) == 1
    assert res.elements[0].type == "error"
    assert res.elements[0].nom_sub_text == "一"
    assert "DIFF_READING_MISMATCH" in res.flags


# ----------------------------------------------------------- §3A/R11 variant fold

def test_variant_fold_anchors_by_default():
    lex = _FakeLexicon({"鬼": ["quỷ"]})
    res = auto_text_diff("鬼", "qui", lexicon=lex)
    assert res.elements == []
    assert res.matched_fold_readings == 1
    assert res.matched_exact_readings == 0
    assert "DIFF_VARIANT_FOLD_APPLIED" in res.flags


def test_variant_fold_disabled_restores_error():
    lex = _FakeLexicon({"鬼": ["quỷ"]})
    res = auto_text_diff("鬼", "qui", lexicon=lex, allow_variant_fold=False)
    assert res.elements and res.elements[0].type == "error"
    assert res.matched_fold_readings == 0
    assert "DIFF_VARIANT_FOLD_APPLIED" not in res.flags


def test_variant_fold_gi_prefix_alternation():
    lex = _FakeLexicon({"範": ["giấu"]})
    res = auto_text_diff("範", "dấu", lexicon=lex)
    assert res.elements == []
    assert res.matched_fold_readings == 1


def test_variant_fold_old_spelling_match():
    lex = _FakeLexicon({"紀": ["kỷ"]})
    res = auto_text_diff("紀", "ki", lexicon=lex)
    assert res.elements == []


def test_exact_match_not_counted_as_fold():
    lex = _FakeLexicon({"鬼": ["quỷ"]})
    res = auto_text_diff("鬼", "quỷ", lexicon=lex)
    assert res.matched_exact_readings == 1
    assert res.matched_fold_readings == 0
    assert "DIFF_VARIANT_FOLD_APPLIED" not in res.flags


def test_fold_anchor_collapses_would_be_error_run():
    lex = _FakeLexicon({"鬼": ["quỷ"], "甲": ["sai"]})
    res_on = auto_text_diff("鬼甲", "qui khi", lexicon=lex)
    res_off = auto_text_diff("鬼甲", "qui khi", lexicon=lex, allow_variant_fold=False)
    assert [e.nom_sub_text for e in res_on.elements or []] == ["甲"]
    assert [e.nom_sub_text for e in res_off.elements or []] == ["鬼甲"]


def test_variant_fold_from_config_default_and_override():
    assert variant_fold_from_config(None) is True
    assert variant_fold_from_config({}) is True
    assert variant_fold_from_config({"text_diff": {}}) is True
    assert variant_fold_from_config({"text_diff": {"variant_fold": True}}) is True
    assert variant_fold_from_config({"text_diff": {"variant_fold": False}}) is False


def test_alignment_config_plumbs_variant_fold():
    assert _as_config({"alignment": {}, "text_diff": {"variant_fold": False}}).variant_fold is False
    # Legacy single-section config (no "alignment" wrapper) still honours it.
    assert _as_config({"text_diff": {"variant_fold": False}}).variant_fold is False
    assert _as_config({"alignment": {}}).variant_fold is True
    assert _as_config(None).variant_fold is True
    assert AlignConfig().variant_fold is True


# ----------------------------------- §5.A/R3 replace-not-union recompute flags

def _row(flags, ch="一", vi="một", text_diff=[]):
    return AlignmentRow(
        img_id="T.001.jpg",
        sentence_id="T.001.1",
        ch_txt=ch,
        vi_txt=vi,
        text_diff=text_diff,
        flags=list(flags),
    )


def test_recompute_replaces_stale_diff_flags():
    lex = _FakeLexicon({"一": ["một"]})
    row = _row(
        [
            "DIFF_READING_MISMATCH",
            "REVIEW:DIFF_SEMANTIC",
            "REVIEW:DICT_MISS",
            "TEXT_DIFF_INVALID",
            "IMAGE_REC_FALLBACK",
            "ALIGN_EVIDENCE_INSUFFICIENT",
            "ALIGNED",
        ]
    )
    out = recompute_text_diff([row], lexicon=lex, dictionary=None)[0]
    flags = set(out.flags)
    # Stale re-derivable flags are gone.
    assert "DIFF_READING_MISMATCH" not in flags
    assert "REVIEW:DIFF_SEMANTIC" not in flags
    assert "REVIEW:DICT_MISS" not in flags
    assert "TEXT_DIFF_INVALID" not in flags
    # Fresh flags reflect the new derivation (one matches exactly).
    assert "DIFF_NO_READING_MISMATCH" in flags
    # Human-facing / align-level flags survive untouched.
    assert "IMAGE_REC_FALLBACK" in flags
    assert "ALIGN_EVIDENCE_INSUFFICIENT" in flags
    assert "ALIGNED" in flags


def test_recompute_clears_stale_textdiff_invalid_when_recomputed_clean():
    lex = _FakeLexicon({})  # no evidence -> valid empty diff
    row = _row(["TEXT_DIFF_INVALID", "IMAGE_REC_FALLBACK"])
    out = recompute_text_diff([row], lexicon=lex, dictionary=None)[0]
    assert "TEXT_DIFF_INVALID" not in out.flags
    assert "IMAGE_REC_FALLBACK" in out.flags
    assert "DIFF_UNVERIFIED_NO_BOOK_READINGS" in out.flags


def test_recompute_keeps_non_one_to_one_null_row():
    row = _row(["NON_ONE_TO_ONE", "TEXT_DIFF_NULL_NON_ONE_TO_ONE"], text_diff=None)
    out = recompute_text_diff([row], lexicon=_FakeLexicon({}), dictionary=None)[0]
    assert out.text_diff is None
    assert "NON_ONE_TO_ONE" in out.flags
    assert "DIFF_READING_MISMATCH" not in out.flags


# ------------------------------------------------- R7 spec-formula accounting

def _error(nom_range=(0, 1), vi_range=(0, 5), nom_sub="四", vi_sub="ba sì"):
    return DiffElement(
        nom_pos=(nom_range,),
        nom_sub_text=nom_sub,
        vi_pos=(vi_range,),
        vi_sub_text=vi_sub,
        type="error",
    )


def test_spec_formula_fields_report_all_compared_rows():
    rows = [
        AlignmentRow(
            img_id="T.001.jpg", sentence_id="T.001.1",
            ch_txt="一", vi_txt="một",
            text_diff=[], flags=["DIFF_NO_READING_MISMATCH"],
        ),
        AlignmentRow(
            img_id="T.002.jpg", sentence_id="T.002.1",
            ch_txt="三", vi_txt="hai",
            text_diff=None, flags=["NON_ONE_TO_ONE"],
        ),
        AlignmentRow(
            img_id="T.003.jpg", sentence_id="T.003.1",
            ch_txt="四", vi_txt="ba sì",
            text_diff=[_error()], flags=["DIFF_READING_MISMATCH"],
        ),
    ]
    m = evaluate_rows("Book", rows)
    # Null (non-1-1) row excluded from the spec formula entirely.
    assert m.spec_formula_scored_rows == 2
    assert m.spec_formula_denominator == 2
    assert m.spec_formula_red_chars == 2  # max(#Nôm 四 = 1, two QN syllables)
    assert m.spec_formula_similarity == 0.0
    # The gate remains on the covered/verified rows only.
    assert m.null_rows == 1
    assert m.passed is False


def test_spec_formula_similarity_none_when_no_comparable_rows():
    rows = [
        AlignmentRow(
            img_id="T.001.jpg", sentence_id="T.001.1",
            ch_txt="", vi_txt="",
            text_diff=None, flags=["NON_ONE_TO_ONE"],
        )
    ]
    m = evaluate_rows("Book", rows)
    assert m.spec_formula_scored_rows == 0
    assert m.spec_formula_similarity is None
