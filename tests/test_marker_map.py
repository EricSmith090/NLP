"""Tests for the printed cross-reference marker channel:

the T1 books print the Nôm printed page number in parentheses in the
header of every substantive QN page; Nôm PDF = vi_to_nom_offset − vi PDF.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hannom.charalign import build_qn_stream, clean_qn_text, read_image_map
from hannom.clean import clean_quoc_ngu_page
from hannom.config import BookConfig
from hannom.models import PageRecord
from hannom.t1_map import (
    Pair,
    build_marker_map,
    image_name_page_no,
    validate_image_map,
)


def _page(
    book_id: str,
    no: int,
    folder: str,
    prefix: str = "Book",
) -> PageRecord:
    image = f"{prefix}.{no:03d}.jpg"
    return PageRecord(
        book_id=book_id,
        page_no=no,
        image_name=image,
        pdf_page=no,
        sha256="0" * 64,
        width=800,
        height=1135,
        path=Path(image),
        folder=folder,
        status="classified",
        features={"ink_fraction": 0.02},
    )


def _book(offset: int | None = 289) -> BookConfig:
    return BookConfig(
        book_id="b",
        pdf=Path("Book.pdf"),
        layout="T1",
        expected_pages=12,
        vi_to_nom_offset=offset,
    )


def _corpus(offset: int = 289, lo: int = 3, hi: int = 6) -> list[PageRecord]:
    # 4 QN pages (lo..hi by PDF-number) and their 4 Nôm counterparts
    pages = [_page("b", i, "vi") for i in range(lo, hi + 1)]
    pages += [_page("b", offset - i, "ch") for i in range(lo, hi + 1)]
    return pages


def test_marker_map_is_bijection_verified_and_monotone():
    offset = 289
    pages = _corpus(offset, 13, 16)  # vi 13..16 ↔ ch 276..273
    pairs = build_marker_map(_book(offset), pages)
    assert pairs is not None
    assert all(p.status == "verified" and p.source == "printed_marker" for p in pairs)
    assert all(p.confidence == 1.0 for p in pairs)
    seen_ch = [p.ch[0] for p in pairs]
    seen_vi = [p.vi[0] for p in pairs]
    assert seen_vi == [f"Book.{i:03d}.jpg" for i in range(13, 17)]
    assert seen_ch == [f"Book.{offset - i:03d}.jpg" for i in range(13, 17)]
    assert not validate_image_map(
        pairs,
        ch_names={p.image_name for p in pages if p.folder == "ch"},
        vi_names={p.image_name for p in pages if p.folder == "vi"},
        vi_to_nom_offset=offset,
    )


def test_marker_map_offset_missing_falls_back():
    pages = _corpus()
    assert build_marker_map(_book(None), pages) is None


def test_marker_map_blank_nom_side_is_empty_side_pair_not_dropped():
    offset = 289
    pages = _corpus(offset, 13, 16)
    # Remove the Nôm mate of vi 14 and make sure it is not silently dropped.
    ch_name = f"Book.{offset - 14:03d}.jpg"
    pages = [p for p in pages if p.image_name != ch_name]
    pairs = build_marker_map(_book(offset), pages)
    assert pairs is not None
    assert any(p.vi == (f"Book.014.jpg",) and p.ch == () and p.status == "unresolved" for p in pairs)
    assert f"{ch_name}" not in {name for pair in pairs for name in pair.ch}
    # The validator reports the empty side against the marker formula.
    issues = validate_image_map(
        pairs,
        ch_names={p.image_name for p in pages if p.folder == "ch"},
        vi_names={p.image_name for p in pages if p.folder == "vi"},
        vi_to_nom_offset=offset,
    )
    assert any("marker" in issue for issue in issues)


def test_marker_map_inserts_unmatched_nom_at_reading_position():
    offset = 289
    pages = _corpus(offset, 13, 16)
    # Add an extra Nôm page (scan-missing QN): it must appear with empty vi.
    pages.append(_page("b", 275 - 13, "ch"))  # 262: offset − 27 gap between 276 and 273? no: 289-27=262 < 273
    pages = sorted(pages, key=lambda p: (p.folder != "ch", p.page_no))
    pairs = build_marker_map(_book(offset), pages)
    assert pairs is not None
    ours = [p for p in pairs if p.ch == (f"Book.{275 - 13:03d}.jpg",)]
    assert ours and ours[0].vi == () and ours[0].status == "unresolved"


def test_validate_image_map_coverage_unknown_order_marker():
    offset = 289
    pages = _corpus(offset, 13, 14)
    pairs = build_marker_map(_book(offset), pages)
    assert pairs is not None
    # missing one page from coverage
    issues = validate_image_map(pairs, ch_names={"Book.001.jpg"}, vi_names=None, vi_to_nom_offset=offset)
    assert any("coverage" in issue and "Book.001.jpg" in issue for issue in issues)
    # unknown name in a pair
    issues = validate_image_map(
        [Pair(ch=("X.999.jpg",), vi=("Book.013.jpg",))],
        ch_names={p.image_name for p in pages if p.folder == "ch"},
        vi_names={p.image_name for p in pages if p.folder == "vi"},
        vi_to_nom_offset=offset,
    )
    assert any("unknown ch image" in issue for issue in issues)
    # non-1:1 pair violates the marker formula
    issues = validate_image_map(
        [Pair(ch=("Book.276.jpg", "Book.275.jpg"), vi=("Book.013.jpg",))],
        vi_to_nom_offset=offset,
    )
    assert any("not 1:1" in issue for issue in issues)
    # 1:1 pair violating the formula
    issues = validate_image_map(
        [Pair(ch=("Book.270.jpg",), vi=("Book.013.jpg",))],
        vi_to_nom_offset=offset,
    )
    assert any("marker" in issue for issue in issues)


def test_marker_line_regex_via_clean_qn_page():
    page = clean_quoc_ngu_page(
        "b",
        21,
        "Book.021.jpg",
        ["-19\n( 104 )", "Sửa Lưới Quyển"],
    )
    assert page.marker == 104
    assert "104" not in page.text
    assert not any("104" in line for line in page.lines)


def test_clean_qn_page_marker_without_parens_drops_line_no_marker():
    page = clean_quoc_ngu_page(
        "b",
        61,
        "Book.061.jpg",
        ["- 59 -", "Sửa Lưới Quyển"],
    )
    assert page.marker is None


def test_image_name_page_no_handles_unpadded_and_suffixed():
    assert image_name_page_no("Book.001.jpg") == 1
    assert image_name_page_no("Book.1234.jpg") == 1234
    assert image_name_page_no("Book.013_1.jpg") == 13
    assert image_name_page_no("not_a_page.jpg") is None


def test_clean_qn_text_parser_marker():
    text, marker = clean_qn_text("-19\n( 104 )\n- 58 - ( 104 ) lưỡi mà khen")
    assert marker == 104
    assert not text.startswith("-19")
    for raw, expected in [
        ("-20\n(103) body", 103),
        ("-29 - ( 94 ) x", 94),
        ("- 58 - (65) x", 65),
        ("-10 - ( 113 ) x", 113),
        ("-30 - (93) x", 93),
    ]:
        _text, m = clean_qn_text(raw)
        assert m == expected, raw
    for raw in ["- 2010 - (5) x", "front of book", "static ( 104 ) no dash marker"]:
        _text, m = clean_qn_text(raw)
        assert m is None, raw


def test_build_qn_stream_collects_markers():
    stream, _tokens, starts, markers = build_qn_stream(
        [("Book.021.jpg", "-19\n( 104 )\nFirst page text"),
         ("Book.022.jpg", "-20\n(103)\nSecond page text")]
    )
    assert markers == {"Book.021.jpg": 104, "Book.022.jpg": 103}


def test_read_image_map_skips_unresolved_when_honoring_status(tmp_path: Path):
    map_path = tmp_path / "image_map.json"
    map_path.write_text(
        '{"pairs": [{"ch": ["a.jpg"], "vi": ["b.jpg"], "status": "verified"},'
        ' {"ch": ["c.jpg"], "vi": ["d.jpg"], "status": "unresolved"}], "meta": {}}',
        encoding="utf-8",
    )
    pairs = read_image_map(map_path, honor_status=True)
    assert pairs == [(["a.jpg"], ["b.jpg"])]
    pairs = read_image_map(map_path, honor_status=False)
    assert len(pairs) == 2


def test_alignment_yaml_config_honored_in_dp():
    # align_page_groups defaults honor max_group/max_nm_group from the
    # alignment config dict; explicit kwargs take precedence.
    from hannom.models import PageRecord as _PR
    from hannom.t1_map import align_page_groups

    def page(no: int) -> _PR:
        return _PR(
            book_id="b", page_no=no, image_name=f"B.{no:03d}.jpg", pdf_page=no,
            sha256="0" * 64, width=800, height=1135, path=Path(f"B.{no:03d}.jpg"),
            folder="ch" if no > 4 else "vi", features={"ink_fraction": 0.02},
        )

    ch = [page(8 - i) for i in range(4)]
    vi = [page(i + 1) for i in range(3)]
    cfg = {"max_group": 2, "max_nm_group": 1}
    pairs = align_page_groups(ch, vi, cfg)
    sizes = [(len(p.ch), len(p.vi)) for p in pairs]
    assert all(a <= 2 and b <= 2 for a, b in sizes)


@pytest.mark.parametrize("status", ["manual", "candidate", "verified", "unresolved"])
def test_pair_status_roundtrip(status):
    pair = Pair(ch=("a.jpg",), vi=("b.jpg",), status=status)
    assert pair.to_dict()["status"] == status
