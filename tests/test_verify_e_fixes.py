"""Regression tests for the verify-E remediation.

Covers: C1 (silent sentence drops in cosegment), H1 (UNVERIFIED_FLAGS hygiene),
H2 (force-recompute loophole), M1 (sentence splitter), M8 (LONG_SEGMENT),
and the fail-closed token parity contract between stream and emission.
"""

from __future__ import annotations

from types import SimpleNamespace

from hannom.cosegment import (
    PageUnit,
    SENTENCE_UPPER_RE,
    VIETNAMESE_UPPER_CLASS,
    qn_sentence_spans,
    stream_cosegment,
)
from hannom.align import AlignConfig, _emit_rows, TextSegment
from hannom.clean import count_nom_chars
from hannom.models import AlignmentRow
from hannom.orchestrator import recompute_text_diff
from hannom.evaluate import UNVERIFIED_FLAGS, _classify_row


# ---------------------------------------------------------------- M1 splitter

def test_uppercase_class_excludes_lowercase_and_non_latin_scripts():
    assert "Ệ" in VIETNAMESE_UPPER_CLASS
    assert "Đ" in VIETNAMESE_UPPER_CLASS
    assert "Ơ" in VIETNAMESE_UPPER_CLASS
    assert "ệ" not in VIETNAMESE_UPPER_CLASS
    assert "đ" not in VIETNAMESE_UPPER_CLASS
    for ch in "ΑΩЩЯאבشԱ":
        assert ch not in VIETNAMESE_UPPER_CLASS


def test_uppercase_re_matches_vietnamese_boundaries_only():
    assert SENTENCE_UPPER_RE.match("Ệnh")
    assert SENTENCE_UPPER_RE.match("Đây")
    assert not SENTENCE_UPPER_RE.match("ệnh")
    assert not SENTENCE_UPPER_RE.match("Ωμέγα")
    assert not SENTENCE_UPPER_RE.match("Якесь")


def test_spans_handle_abbreviations_and_major_scripts():
    assert len(qn_sentence_spans("Mr. Smith đến. Ông ấy đi.")) == 2
    assert len(qn_sentence_spans("Tp. Hồ Chí Minh đẹp. Mai mưa.")) == 2
    assert len(qn_sentence_spans("Kết thúc. Đây là câu tiếp.")) == 2
    assert len(qn_sentence_spans("Bình thường!!!Ω συνηθισμένο. Βλαβερό.")) == 1


def test_terminal_set_includes_semicolon_and_colon():
    assert len(qn_sentence_spans("Sơ lược; Cái này khác.")) == 2
    assert len(qn_sentence_spans("Sơ lược: Cái này khác.")) == 2


# ------------------------------------------------------------- C1 min span

def _nom(chars: str) -> PageUnit:
    return PageUnit("T.002.jpg", chars)


def _qn(text: str) -> PageUnit:
    return PageUnit("T.001.jpg", text)


def test_min_ideograph_span_prevents_total_collapse():
    nom = "一" * 30
    vi = "Một hai. Ba bốn. Năm sáu. Bảy tám."
    stream = stream_cosegment([_nom(nom)], [_qn(vi)])
    assert stream is not None
    nom_segs, qn_segs = stream
    assert len(nom_segs) == len(qn_segs) == 4
    assert all(s.text for s in nom_segs)


def test_collapsed_sentences_are_emitted_unmatched_not_dropped():
    # 24 one-token sentences but only 21 ideographs: three cannot get a span.
    nom = "一二三四五六七八九十一二三四五六七八九十甲"  # 21 CJK ideographs
    assert count_nom_chars(nom) == 21
    words = [f"Từ{i}" for i in range(24)]
    vi = " ".join(f"{w}." if i < 23 else w for i, w in enumerate(words))
    stats: dict = {}
    stream = stream_cosegment([_nom(nom)], [_qn(vi)], stats=stats)
    assert stream is not None
    nom_segs, qn_segs = stream
    assert len(nom_segs) == len(qn_segs) == 24
    assert sum(1 for s in nom_segs if not s.text) == 3
    assert stats["segments_dropped"] == 0
    assert stats["stream_sentences"] == 24
    assert stats["qn_tokens_emitted"] == stats["qn_tokens_stream"]
    assert stats["sentence_coverage"] == 1.0
    isolated = stats["sentences_isolated"]
    assert isolated == [21, 22, 23]
    assert stats["sentences_skipped"] == []
    for idx in isolated:
        assert "UNMATCHED_QN" in nom_segs[idx].flags
        assert qn_segs[idx].text


def test_stream_stats_parity_on_balanced_input():
    nom = "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸"  # 20 ideographs
    vi = "Một hai ba bốn. Năm sáu bảy tám. Chín mười mười một mườiHai."
    stats: dict = {}
    stream = stream_cosegment([_nom(nom)], [_qn(vi)], stats=stats)
    assert stream is not None
    assert stats["segments_dropped"] == 0
    assert stats["qn_tokens_emitted"] == stats["qn_tokens_stream"] > 0


# -------------------------------------------------------------- H1 / H2

def test_unverified_flags_hygiene():
    assert "COSEGMENTED_UNANCHORED" not in UNVERIFIED_FLAGS
    assert "ALIGN_FORCE_RECOMPUTED_FROM_NULL" in UNVERIFIED_FLAGS
    # Machine-evidence boundary unchanged: verified rows still verify.
    assert _classify_row({"P"}, [], None, True)[0] == "verified_match"
    # Evidence-insufficient still blocks verification.
    assert _classify_row({"ALIGN_EVIDENCE_INSUFFICIENT"}, [], None, True)[0] == "unverified"


def _row(*, text_diff, flags):
    return AlignmentRow(
        img_id="T.001.jpg",
        sentence_id="T.001.1",
        ch_txt="一",
        vi_txt="Một",
        text_diff=text_diff,
        confidence=0.9,
        flags=list(flags),
        semantic_confidence=0.9,
    )


def test_force_recompute_flags_rows_formerly_null_unverified():
    row = _row(text_diff=None, flags=["TEXT_DIFF_NULL_NON_ONE_TO_ONE"])
    out = recompute_text_diff([row], force_recompute=True)
    assert out[0].text_diff is not None
    assert "ALIGN_FORCE_RECOMPUTED_FROM_NULL" in out[0].flags
    classification, _ = _classify_row(set(out[0].flags), out[0].text_diff, None, True)
    assert classification == "unverified"


def test_recompute_keeps_null_for_flagged_non_one_to_one_even_forced():
    row = _row(text_diff=None, flags=["NON_ONE_TO_ONE"])
    out = recompute_text_diff([row], force_recompute=True)
    assert out[0].text_diff is None


def test_recompute_keeps_null_without_force_by_default():
    row = _row(text_diff=None, flags=())
    out = recompute_text_diff([row])
    assert out[0].text_diff is None
    assert "ALIGN_FORCE_RECOMPUTED_FROM_NULL" not in out[0].flags


# ------------------------------------------- empty-side & long-segment rows

def _text_segment(text: str, image_name: str, script: str = "nom") -> TextSegment:
    return TextSegment(
        text=text,
        image_name=image_name,
        page_no=1,
        page_numbers=(1,),
        image_names=(image_name,),
        script=script,
        order=0,
        flags=[],
    )


def test_group_with_empty_nom_side_normalizes_to_unmatched_qn():
    nom = _text_segment("", "T.001.jpg", "nom")
    qn = _text_segment("Một hai ba bốn năm sáu bảy tám chín mười.", "T.001.jpg", "qn")
    rows = _emit_rows(
        [(0, 1, 0, 1, 0.0, "group", 1, 1)],
        [nom],
        [qn],
        config=AlignConfig(),
    )
    assert len(rows) == 1
    flags = rows[0].flags
    assert "UNMATCHED_QN" in flags and "NON_ONE_TO_ONE" in flags
    assert "TEXT_DIFF_NULL_NON_ONE_TO_ONE" in flags
    assert rows[0].text_diff is None
    assert rows[0].ch_txt == ""


def test_long_segment_flag_fires_above_160_chars():
    nom_text = "一" * 170
    qn_text = "Một hai ba bốn năm sáu bảy tám chín mười mườiMột mườiHai mườiBa mườiBốn mườiNăm mườiSáu mườiBảy tám chín."
    nom = _text_segment(nom_text, "T.001.jpg")
    qn = _text_segment(qn_text, "T.001.jpg", "qn")
    rows = _emit_rows(
        [(0, 1, 0, 1, 0.0, "group", 1, 1)],
        [nom],
        [qn],
        config=AlignConfig(),
    )
    assert "LONG_SEGMENT" in rows[0].flags


def test_long_segment_flag_silent_for_normal_rows():
    nom = _text_segment("一二三", "T.001.jpg")
    qn = _text_segment("Một hai ba.", "T.001.jpg", "qn")
    rows = _emit_rows(
        [(0, 1, 0, 1, 0.0, "group", 1, 1)],
        [nom],
        [qn],
        config=AlignConfig(),
    )
    assert "LONG_SEGMENT" not in rows[0].flags


def test_align_book_marks_missing_clean_pages():
    from hannom import align as m
    from hannom.t1_map import Pair

    nom_text = "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸子丑"  # 22 ideographs
    qn_text = "Một hai ba bốn năm sáu. Bảy tám chín mười mười một. MườiHai mườiBa mườiBốn."
    cleaned = {
        "T.002.jpg": SimpleNamespace(text=nom_text, lines=[], script="nom", image_name="T.002.jpg", page_no=2),
        "T.001.jpg": SimpleNamespace(text=qn_text, lines=[], script="qn", image_name="T.001.jpg", page_no=1),
        # T.004.jpg (nom) and T.003.jpg (qn) of pair 2 are deliberately absent.
    }
    stats: dict = {}
    rows, warnings = m.align_book(
        "ZZ_MISSING",
        [Pair(ch=("T.002.jpg", "T.004.jpg"), vi=("T.001.jpg", "T.003.jpg"))],
        cleaned,
        config={"alignment": {"segmentation": "cosegment"}},
        stats=stats,
    )
    assert "MISSING_CLEAN_PAGE:T.004.jpg" in warnings
    assert "MISSING_CLEAN_PAGE:T.003.jpg" in warnings
    assert sorted(stats.get("missing_clean_pages") or []) == ["T.003.jpg", "T.004.jpg"]


def test_align_book_marks_missing_clean_pages_charstream():
    from hannom import align as m
    from hannom.t1_map import Pair

    nom_text = "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸子丑"  # 22 ideographs
    qn_text = "Một hai ba bốn năm sáu. Bảy tám chín mười mười một. MườiHai mườiBa mườiBốn."
    cleaned = {
        "T.002.jpg": SimpleNamespace(text=nom_text, lines=[], script="nom", image_name="T.002.jpg", page_no=2),
        "T.001.jpg": SimpleNamespace(text=qn_text, lines=[], script="qn", image_name="T.001.jpg", page_no=1),
    }
    stats: dict = {}
    rows, warnings = m.align_book(
        "ZZ_MISSING_CA",
        [Pair(ch=("T.002.jpg", "T.004.jpg"), vi=("T.001.jpg", "T.003.jpg"))],
        cleaned,
        config={"alignment": {"segmentation": "charalign", "strip_texts": [],
                               "per_book": {"ZZ_MISSING_CA": {"segmentation": "charalign"}}}},
        stats=stats,
    )
    assert "MISSING_CLEAN_PAGE:T.004.jpg" in warnings
    assert "MISSING_CLEAN_PAGE:T.003.jpg" in warnings


# --------------------------------------------------- align_book integration

def test_align_book_stats_parity_on_tiny_book():
    from hannom import align as m
    from hannom.t1_map import Pair

    nom_text = "一二三四五六七八九十甲乙丙丁戊己庚辛壬癸子丑"  # 22 ideographs
    qn_text = "Một hai ba bốn năm sáu. Bảy tám chín mười mười một. MườiHai mườiBa mườiBốn."
    cleaned = {
        "T.002.jpg": SimpleNamespace(text=nom_text, lines=[], script="nom", image_name="T.002.jpg", page_no=2),
        "T.001.jpg": SimpleNamespace(text=qn_text, lines=[], script="qn", image_name="T.001.jpg", page_no=1),
    }
    stats: dict = {}
    rows, warnings = m.align_book(
        "ZZ_TEST_BOOK",
        [Pair(ch=("T.002.jpg",), vi=("T.001.jpg",))],
        cleaned,
        config={"alignment": {"segmentation": "cosegment"}},
        stats=stats,
    )
    assert stats.get("qn_tokens_stream") is not None
    assert stats["qn_tokens_emitted"] == stats["qn_tokens_stream"]
    assert stats["segments_dropped"] == 0
    assert isinstance(rows, list)
    assert isinstance(warnings, list)
