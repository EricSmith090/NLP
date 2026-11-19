"""Label.txt <-> CSV SYNC with the official normalisation (FIX_PLAN T1.4)."""

from hannom.sync_check import check_sync, norm_vi, page_orders
from hannom.t1_map import Pair


PAIRS = [Pair(ch=("B.276.jpg",), vi=("B.013.jpg",)), Pair(ch=("B.275.jpg",), vi=("B.014.jpg",))]
CH = {
    "ch/B.276.jpg": [{"transcription": "天主"}, {"transcription": "聖神"}],
    "ch/B.275.jpg": [{"transcription": "阿綿"}],
}
VI = {
    "vi/B.013.jpg": [{"transcription": "Đức Chúa Trời, Chúa Thánh"}],
    "vi/B.014.jpg": [{"transcription": "Thần. A-men."}],
}


def _rows(*cells):
    return [{"img_id": img, "ch_txt": ch, "vi_txt": vi} for img, ch, vi in cells]


def test_in_sync_ignores_whitespace_and_qn_hyphen():
    rows = _rows(
        ("B.276.jpg", "天主聖神", "Đức Chúa Trời, Chúa Thánh Thần."),
        ("B.275.jpg", "阿 綿", "Amen."),
    )
    assert check_sync(rows, CH, VI, PAIRS) == []


def test_reordered_nom_is_reported_with_location():
    rows = _rows(("B.276.jpg", "聖神天主", "Đức Chúa Trời, Chúa Thánh Thần."), ("B.275.jpg", "阿綿", "Amen."))
    errs = check_sync(rows, CH, VI, PAIRS)
    assert len(errs) == 1 and "ch_txt" in errs[0] and "B.276.jpg box 1" in errs[0]


def test_truncated_label_is_reported():
    vi = {"vi/B.013.jpg": [{"transcription": "Đức Chúa Trời,"}], "vi/B.014.jpg": [{"transcription": "Thần. A-men."}]}
    rows = _rows(("B.276.jpg", "天主聖神", "Đức Chúa Trời, Chúa Thánh Thần."), ("B.275.jpg", "阿綿", "Amen."))
    errs = check_sync(rows, CH, vi, PAIRS)
    assert len(errs) == 1 and "vi_txt" in errs[0]


def test_vi_only_pair_is_skipped_and_norm():
    ch, vi = page_orders([Pair(ch=(), vi=("B.001.jpg",)), *PAIRS])
    assert ch == ["B.276.jpg", "B.275.jpg"] and vi == ["B.013.jpg", "B.014.jpg"]
    assert norm_vi("A-men  Giê-su") == "AmenGiêsu"
