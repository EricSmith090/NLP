"""tools/pua_resolve_sheet.py: candidate lookup for a 〓 facing a syllable."""

import importlib.util
from collections import Counter
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "pua_resolve_sheet.py"
_spec = importlib.util.spec_from_file_location("pua_resolve_sheet", _PATH)
prs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prs)


class _Readings:
    char = {"䀡": {"xem"}, "占": {"chiêm", "xem"}, "𥆾": {"xem"}, "沾": {"chiêm"}, "閻": {"diêm"}, "兼": {"kiêm", "xém"}}
    word = {"眨": {"xẻm"}, "䀡䀡": {"xem xem"}}  # multi-char words are ignored


def test_reverse_readings_keeps_single_chars_and_tone_keys():
    exact, loose = prs.reverse_readings(_Readings())
    assert exact["xem"] == {"䀡", "占", "𥆾"}
    assert loose["xem"] == {"䀡", "占", "𥆾", "兼", "眨"}  # xém / xẻm differ only by tone
    assert "xem xem" not in exact


def test_candidates_exact_first_most_used_in_the_book_first():
    exact, loose = prs.reverse_readings(_Readings())
    freq = Counter({"占": 40, "䀡": 3})
    out = prs.candidates_for("Xem", exact, loose, freq)
    assert out[:3] == [("占", "exact"), ("䀡", "exact"), ("𥆾", "exact")]
    assert {c for c, k in out if k == "tone"} == {"兼", "眨"}


def test_candidates_unknown_syllable_is_empty():
    exact, loose = prs.reverse_readings(_Readings())
    assert prs.candidates_for("qwz", exact, loose, Counter()) == []
