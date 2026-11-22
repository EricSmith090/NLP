"""T1_DanDangNhanDuc_Phan1: Nôm run grown to the configured hints, and the
printed-marker map across the two blank leaves inserted in the Nôm block."""

from __future__ import annotations

from pathlib import Path

from hannom.config import load_config
from hannom.layout import extend_run_to_hints
from hannom.models import PageRecord
from hannom.t1_map import build_marker_map, image_name_page_no, validate_image_map

ROOT = Path(__file__).resolve().parents[1]


def test_hint_adds_the_short_last_nom_page():
    # PDF 231 (a few columns) misses nom_likely; the image run is 232-446.
    run, added = extend_run_to_hints((231, 445), 231, 446, 462)
    assert run == (230, 445)
    assert added == [231]


def test_hint_equal_to_run_changes_nothing():
    # Tap1 147-276, Tap2 277-540, SLQ 67-116: hints equal the image runs.
    for lo, hi, n in ((147, 276, 282), (277, 540, 550), (67, 116, 118)):
        assert extend_run_to_hints((lo - 1, hi - 1), lo, hi, n) == ((lo - 1, hi - 1), [])


def test_hint_never_shrinks_or_bridges_a_gap():
    assert extend_run_to_hints((100, 200), 120, 180, 300) == ((100, 200), [])
    # hint range does not touch the run: ignored
    assert extend_run_to_hints((100, 200), 210, 250, 300) == ((100, 200), [])
    assert extend_run_to_hints((100, 200), 0, 0, 300) == ((100, 200), [])
    # touching on the right, clamped to the book
    assert extend_run_to_hints((100, 200), 150, 400, 300) == ((100, 299), list(range(202, 301)))


def _page(book, no: int, folder: str) -> PageRecord:
    name = f"{book.book_name}.{no:03d}.jpg"
    return PageRecord(book_id=book.book_id, page_no=no, image_name=name, pdf_page=no,
                      sha256="0" * 64, width=800, height=1135, path=Path(name), folder=folder)


def test_config_maps_every_qn_page_to_its_printed_nom_page():
    project = load_config(ROOT / "configs" / "project.yaml")
    book = next(b for b in project.books if b.book_id == "T1_DanDangNhanDuc_Phan1")
    vi = list(range(11, 225))
    ch = list(range(231, 427)) + list(range(429, 447))
    pages = [_page(book, n, "vi") for n in vi] + [_page(book, n, "ch") for n in ch]
    pages += [_page(book, n, "blank") for n in (427, 428)]
    pairs = build_marker_map(book, pages)
    got = {image_name_page_no(p.vi[0]): image_name_page_no(p.ch[0]) for p in pairs}
    assert len(pairs) == 214 and all(p.status == "verified" for p in pairs)
    # Read off the scans: QN header "( ) = 453 − vi PDF"; Nôm printed = PDF − 2
    # up to PDF 426, PDF − 4 from PDF 429 (blank leaves 427, 428).
    for v in vi:
        printed = 453 - v
        assert got[v] == (printed + 2 if printed <= 424 else printed + 4), v
    assert got[11] == 446 and got[12] == 445 and got[28] == 429 and got[29] == 426 and got[224] == 231
    names = dict(ch_names={p.image_name for p in pages if p.folder == "ch"},
                 vi_names={p.image_name for p in pages if p.folder == "vi"})
    assert validate_image_map(pairs, **names, vi_to_nom_offset=book.vi_to_nom_offset,
                              marker_overrides=book.marker_overrides) == []
