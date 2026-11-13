"""Regression tests for the Verify-D fix set (2026-11-13)."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from PIL import Image

from hannom.clean import (
    MASK,
    _FULLPAGE_LEADING_MARK,
    _join_hyphenated_lines,
    _strip_trailing_title,
    clean_nom_page,
    clean_quoc_ngu_page,
    validate_clean_text,
)
from hannom.labels import clamp_quad, read_label_txt, validate_label_txt, write_file_state, write_label_txt

PUA = "\U000F047C"  # U+F047C, a Plane-15 PUA codepoint emitted by Kim Hán Nôm


def test_nom_sanitizer_result_is_applied():
    page = clean_nom_page("b", 1, "Book.001.jpg", [f"付{PUA}𡥵", "第二。"])  # U+F047C emitted by Kim Hán Nôm
    assert PUA not in page.text
    assert "\\u3013" not in page.text  # raw escape must not appear
    assert "〓" in page.text
    assert page.text.count("〓") == 1
    assert page.replacements == {PUA: 1}
    assert "NOM_UNENCODABLE_REPLACED" in page.flags
    assert "".join(page.lines) == page.text
    assert validate_clean_text(page.text, "nom") == []


def test_validate_clean_text_rejects_unsafe_codepoints():
    assert any("U+F047C" in issue for issue in validate_clean_text(PUA, "nom"))
    assert any("U+F047C" in issue for issue in validate_clean_text(PUA, "qn"))
    assert validate_clean_text("〓", "nom") == []
    assert validate_clean_text("字", "nom") == []
    # Not a bracketed mask token at all — no complaints.
    assert validate_clean_text("abc[ MAASK ]def", "qn") == []
    assert any(
        "invalid mask token" in issue for issue in validate_clean_text("[MASKx]y", "nom")
    )


def test_fullpage_leading_mark_does_not_split_bare_years():
    never_match = [
        "1802, vua Gia Long lên ngôi",
        "1802 Gia Long lên ngôi",
        "1913 Lời mở đầu",
        "1975 30 tháng 4 giải phóng",
        "15 20 25 là các số",
    ]
    for case in never_match:
        assert _FULLPAGE_LEADING_MARK.match(case) is None
    always_match = [
        ("-11 - (274) CẤM PHÒNG", "-11 - (274)"),
        ("- 12 - (273)", "- 12 - (273)"),
        ("-10 ( 113 )", "-10 ( 113 )"),
        ("-276 -", "-276 -"),
        ("-14\n(271)", "-14\n(271)"),
    ]
    for case, expected in always_match:
        m = _FULLPAGE_LEADING_MARK.match(case)
        assert m is not None, case
        assert m.group(0).strip() == expected.strip(), case


def test_fullpage_leading_mark_requires_terminator():
    # A bare '-7 text' heading must not be over-stripped.
    assert _FULLPAGE_LEADING_MARK.match("-7 BẢN QUỐC NGỮ SỬA LƯỚI QUYỀN") is None
    assert _FULLPAGE_LEADING_MARK.match("-197530 x") is None
    assert _FULLPAGE_LEADING_MARK.match("-1 SỬA LƯỚI QUYỀN") is None


def test_strip_trailing_title_dispositions():
    line, disposition, dropped = _strip_trailing_title("hãy sửa lưới")
    assert disposition == "suspect"
    assert line == "hãy sửa lưới"
    line, disposition, dropped = _strip_trailing_title("-15- Sửa Lưới")
    assert disposition == "removed"
    assert line == "-15-"
    assert dropped == "Sửa Lưới"
    line, disposition, dropped = _strip_trailing_title("SỬA LƯỚI QUYỀN")
    assert disposition == "removed"
    assert line == ""
    line, disposition, _ = _strip_trailing_title("không có tiêu đề")
    assert disposition == "none"
    assert line == "không có tiêu đề"


def test_join_hyphenated_lines_rules():
    out, joined = _join_hyphenated_lines(["tin-", "tưởng"])
    assert out == ["tin tưởng"]
    assert joined == 1
    out, joined = _join_hyphenated_lines(["A-", "ve"])
    assert out == ["A-ve"]
    assert joined == 1
    out, joined = _join_hyphenated_lines(["Nam-", "Việt"])
    assert out == ["Nam Việt"]
    assert joined == 1
    out, joined = _join_hyphenated_lines(["tint-", "Việt"])
    assert out == ["tint Việt"]
    assert joined == 1


def test_qn_giant_page_split_markers_and_page_number():
    page = clean_quoc_ngu_page(
        "b", 1, "Book.001.jpg", ["-14\n(271)\nDòng một.\nDòng hai.\n- 271 -"]
    )
    assert page.marker == 271
    assert "- 271 -" not in page.text
    assert "PAGE_MARK_REMOVED" in page.flags
    assert "PAGE_NUMBER_REMOVED" in page.flags
    assert page.text == "Dòng một. Dòng hai."


def test_qn_slq_0003_like_case_is_flagged_empty():
    page = clean_quoc_ngu_page("b", 3, "T1_Sửa Lưỡi Quyển.003.jpg", ["-1\nSỬA LƯỚI QUYỀN"])
    assert page.text == ""
    assert "EMPTY_AFTER_CLEAN" in page.flags
    assert "FOOTER_TITLE_REMOVED" in page.flags


def test_nom_marker_only_page_becomes_empty_after_clean():
    page = clean_nom_page("b", 83, "Book.083.jpg", ["- 81 - (204)"])
    # The Nôm path strips full-page markers symmetrically and flags the page.
    assert page.text == ""
    assert "PAGE_MARK_REMOVED" in page.flags
    assert "EMPTY_AFTER_CLEAN" in page.flags
    assert page.marker == 204


def test_nom_margin_noise_page_number_is_flagged():
    page = clean_nom_page("b", 9, "Book.009.jpg", ["- 7 -"])
    assert page.text == ""
    assert "PAGE_NUMBER_REMOVED" in page.flags
    assert "EMPTY_AFTER_CLEAN" in page.flags


def test_clamp_quad_caps_at_dimensions():
    quad = clamp_quad(((0.0, 0.0), (800.0, 0.0), (800.0, 1135.0), (0.0, 1135.0)), 800, 1135)
    assert quad[1][0] == 800.0
    assert quad[2][1] == 1135.0


def _make_package_fixture(root: Path):
    from hannom.config import ApiSettings, BookConfig, ProjectConfig

    book = BookConfig(book_id="b", pdf=root / "Book.pdf", layout="T1", expected_pages=1)
    project = ProjectConfig(
        root=root,
        project_name="test",
        deadline="2026-11-30",
        zip_stem="s",
        report_name="report.pdf",
        one_zip_for_all_books=True,
        data_dir=root / "data",
        artifacts_dir=root / "artifacts",
        output_dir=root / "output",
        dictionaries_dir=root / "dictionaries",
        models_dir=root / "models",
        books=(book,),
        api=ApiSettings(base_url="https://example.invalid", token_env="T", user_agent="UA", limits={}),
        quality={"minimum_similarity": 95.0},
    )
    return project, book


def test_validate_book_package_blocks_empty_labels(tmp_path: Path):
    from hannom.package import validate_book_package

    project, book = _make_package_fixture(tmp_path)
    book_dir = tmp_path / "output" / "Book"
    ch_dir = book_dir / "ch"
    ch_dir.mkdir(parents=True)
    (book_dir / "Book.pdf").write_bytes(b"%PDF-1.4\n")
    Image.new("RGB", (100, 200), "white").save(ch_dir / "Book.001.jpg", "JPEG")
    write_label_txt(
        ["Book.001.jpg"],
        {"Book.001.jpg": []},  # one image, zero boxes
        ch_dir / "Label.txt",
        "ch",
    )
    write_file_state(["Book.001.jpg"], ch_dir / "fileState.txt", "ch", 1)

    issues = validate_book_package(project, book, book_dir)
    assert any(i.code == "EMPTY_LABELS" for i in issues)

    issues = validate_book_package(project, book, book_dir, allow_empty_labels=True)
    assert not any(i.code == "EMPTY_LABELS" for i in issues)


def test_mask_kept_and_lines_match_text():
    page = clean_nom_page("b", 2, "Book.002.jpg", ["字[MASK]字"])
    assert MASK in page.text
    assert "".join(page.lines) == page.text
