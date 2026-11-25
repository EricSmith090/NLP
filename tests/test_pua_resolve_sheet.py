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


def test_candidates_look_alikes_of_the_ocr_char_come_first():
    exact, loose = prs.reverse_readings(_Readings())
    freq = Counter({"占": 40, "䀡": 3})
    out = prs.candidates_for("xem", exact, loose, freq, similar=["𥆾", "某"])
    assert out[0] == ("𥆾", "exact")  # rank 0 look-alike, even though unused in the book
    assert out[1:3] == [("占", "exact"), ("䀡", "exact")]


def test_read_pairs_skips_headers_and_duplicates(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("Nôm; Việt\n\n諫; khiêm\n了;tréo\n了; tréo\n〓; Vì\n參; TÓM\nbad line\n二三; x\n", encoding="utf-8")
    assert prs.read_pairs(p) == [("諫", "khiêm"), ("了", "tréo"), ("〓", "vì"), ("參", "tóm")]


def test_no_limit_by_default_and_limits_when_asked():
    exact = {"xem": {chr(0x4E00 + k) for k in range(30)}}
    loose = {"xem": set(exact["xem"]) | {chr(0x5000 + k) for k in range(20)}}
    assert len(prs.candidates_for("xem", exact, loose, Counter())) == 50
    out = prs.candidates_for("xem", exact, loose, Counter(), limit=24, loose_limit=12)
    assert [k for _c, k in out].count("exact") == 24 and [k for _c, k in out].count("tone") == 12


def test_tonghop3_rows_join_the_candidates(tmp_path):
    d = tmp_path / "dictionaries-04-11-2026"
    d.mkdir()
    (d / "QuocNgu_SinoNom_TongHop3.csv").write_text(
        '"QuocNgu","SinoNom"\n"xem","𫀅"\n"xém","䁤"\n"xem","𧡊𧡊"\n', encoding="utf-8")
    th3 = prs.load_tonghop3(tmp_path)
    assert th3[0]["xem"] == {"𫀅"} and th3[1]["xem"] == {"𫀅", "䁤"}  # multi-char SinoNom skipped
    exact, loose = prs.merge_reverse(prs.reverse_readings(_Readings()), th3)
    assert exact["xem"] == {"䀡", "占", "𥆾", "𫀅"}
    assert "䁤" in loose["xem"] and "䁤" not in exact["xem"]


def test_candidates_unknown_syllable_is_empty():
    exact, loose = prs.reverse_readings(_Readings())
    assert prs.candidates_for("qwz", exact, loose, Counter()) == []
