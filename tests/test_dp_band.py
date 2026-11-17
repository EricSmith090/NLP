"""Monotonicity band for the align DP: banded runs identical to full DP
when the alignment stays in-band; automatic fallback to the full DP when
the banded grid cannot reach (n, m)."""

from __future__ import annotations

import warnings
from pathlib import Path

from hannom.align import AlignConfig, TextSegment, align_segments


def _seg(text: str, page_no: int = 1, order: int = 0) -> TextSegment:
    return TextSegment(
        text=text,
        image_name=f"Test.{page_no:03d}.jpg",
        page_no=page_no,
        page_numbers=(page_no,),
        image_names=(f"Test.{page_no:03d}.jpg",),
        script="nom" if order % 2 == 0 else "qn",
        order=order,
    )


def _nom(text: str, page_no: int = 1, order: int = 0) -> TextSegment:
    s = _seg(text, page_no, order)
    s.script = "nom"
    return s


def _qn(text: str, page_no: int = 1, order: int = 0) -> TextSegment:
    s = _seg(text, page_no, order)
    s.script = "qn"
    return s


def _rows(nom, qn, **kw):
    cfg = AlignConfig(**kw)
    return align_segments(nom, qn, config=cfg, lexicon=None, dictionary=None, readings_cache=None)


def test_band_matches_full_dp_when_in_band():
    nom = [_nom("経申母福。", 1, 0), _nom("経告命。", 1, 2), _nom("経天主。", 1, 4)]
    qn = [_qn("Kinh Thân Mẫu Phúc.", 1, 1), _qn("Kinh Cáo Mình.", 1, 3), _qn("Kinh Thiên Chúa.", 1, 5)]
    assert _rows(nom, qn, dp_band=None) == _rows(nom, qn, dp_band=3)


def test_band_fallback_reaches_full_dp_when_blocked():
    nom = [_nom("経申母福。", 1, 0)]
    qn = [_qn(f"Câu thứ {i}.", 1, 1 + i) for i in range(10)]
    full = _rows(nom, qn, dp_band=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        banded = _rows(nom, qn, dp_band=1)
    assert banded == full, "infeasible band must fall back to the full DP result"
    assert any("dp_band" in str(w.message) for w in caught), "fallback must emit a warning"
