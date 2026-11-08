from __future__ import annotations

from pathlib import Path

from hannom.models import PageRecord
from hannom.t1_map import Pair, align_page_groups, validate_image_map


def _page(no: int, folder: str, ink: float) -> PageRecord:
    return PageRecord(
        book_id="b",
        page_no=no,
        image_name=f"Book.{no:03d}.jpg",
        pdf_page=no,
        sha256=f"sha{no}",
        width=800,
        height=1135,
        path=Path(f"Book.{no:03d}.jpg"),
        folder=folder,
        features={"ink_fraction": ink},
    )


def test_t1_map_uses_decreasing_ch_and_increasing_vi():
    ch = [_page(n, "ch", 0.03 + n / 1000) for n in range(6, 0, -1)]
    vi = [_page(n, "vi", 0.03 + n / 1000) for n in range(1, 7)]
    pairs = align_page_groups(ch, vi, {"max_group": 2}, max_group=2)
    assert pairs
    assert [p.ch[0] for p in pairs] == [p.ch[0] for p in pairs]
    flat_ch = [name for pair in pairs for name in pair.ch]
    flat_vi = [name for pair in pairs for name in pair.vi]
    assert flat_ch == [p.image_name for p in ch]
    assert flat_vi == [p.image_name for p in vi]
    assert not validate_image_map(pairs)


def test_map_rejects_duplicate_names():
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",))
    issues = validate_image_map([pair, pair])
    assert any("repeated" in issue for issue in issues)


def test_map_allows_one_to_many_and_many_to_one():
    ch = [_page(n, "ch", 0.02) for n in range(4, 0, -1)]
    vi = [_page(n, "vi", 0.02) for n in range(1, 4)]
    pairs = align_page_groups(ch, vi, {"max_group": 3}, max_group=3)
    sizes = {(len(p.ch), len(p.vi)) for p in pairs}
    assert any(a == 1 and b > 1 for a, b in sizes) or any(a > 1 and b == 1 for a, b in sizes)
