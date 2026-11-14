"""Tests for the Area A (verify-A) hardening changes.

Covers: state Stage-1 preservation (M1), update_page validation (n2),
corrupt-DB handling (M6), and the image/accounting preflight gates (M5).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from hannom.config import ApiSettings, BookConfig, ProjectConfig
from hannom.models import PageRecord
from hannom.pages import _matrix_is_rotated
from hannom.preflight import check_book_images
from hannom.state import SCHEMA_VERSION, State, StateError
from hannom.updated_pdf import check_updated_pdf


def _page(book_id: str, page_no: int, **overrides) -> PageRecord:
    base = dict(
        book_id=book_id,
        page_no=page_no,
        image_name=f"Book.{page_no:03d}.jpg",
        pdf_page=page_no,
        sha256=f"{page_no:064x}",
        width=10,
        height=10,
        path=Path(f"Book.{page_no:03d}.jpg"),
        status="extracted",
        script="unknown",
        section="unknown",
        folder="",
        extraction_method="embedded:xref=1",
        rotation=0,
    )
    base.update(overrides)
    return PageRecord(**base)


def _project(root: Path, book_id: str = "b", book_name: str = "Book", expected: int = 3) -> ProjectConfig:
    book = BookConfig(
        book_id=book_id,
        pdf=root / f"{book_name}.pdf",
        layout="T1",
        expected_pages=expected,
    )
    return ProjectConfig(
        root=root,
        project_name="test",
        deadline="2026-11-30",
        zip_stem="zip",
        report_name="report.pdf",
        one_zip_for_all_books=True,
        data_dir=root / "data",
        artifacts_dir=root / "artifacts",
        output_dir=root / "output",
        dictionaries_dir=root / "dictionaries",
        models_dir=root / "models",
        books=(book,),
        api=ApiSettings(base_url="https://example.invalid", token_env="TOKEN", user_agent="UA", limits={}),
        quality={"minimum_similarity": 95.0},
    )


def test_stage1_update_preserves_downstream_columns(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    try:
        state.upsert_page(_page("b", 1))
        state.update_page(
            "b",
            1,
            status="ocr_done",
            script="nom",
            folder="ch",
            review_flags=["LABEL_EMPTY_OCR"],
            features={"conf": 0.9},
        )
        state.stage1_update(
            "b",
            1,
            image_name="Book.001.jpg",
            pdf_page=1,
            sha256="f" * 64,
            width=123,
            height=456,
            path="x.jpg",
            extraction_method="existing",
            rotation=0,
        )
        page = state.page("b", 1)
        assert page.status == "ocr_done"
        assert page.script == "nom"
        assert page.folder == "ch"
        assert page.review_flags == ["LABEL_EMPTY_OCR"]
        assert page.features == {"conf": 0.9}
        assert page.extraction_method == "existing"
        assert (page.width, page.height, page.sha256) == (123, 456, "f" * 64)
    finally:
        state.close()


def test_stage1_update_raises_on_missing_row(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    try:
        with pytest.raises(KeyError):
            state.stage1_update(
                "b",
                99,
                image_name="Book.099.jpg",
                pdf_page=99,
                sha256="0" * 64,
                width=1,
                height=1,
                path="x.jpg",
                extraction_method="existing",
                rotation=0,
            )
    finally:
        state.close()


def test_update_page_rejects_bad_types_and_missing_rows(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    try:
        state.upsert_page(_page("b", 1))
        with pytest.raises(TypeError):
            state.update_page("b", 1, review_flags="DUPLICATE_IMAGE")
        with pytest.raises(TypeError):
            state.update_page("b", 1, review_flags=[1])
        with pytest.raises(TypeError):
            state.update_page("b", 1, features=5)
        with pytest.raises(KeyError):
            state.update_page("b", 77, status="classified")
        # good path still works
        state.update_page("b", 1, review_flags=["X"], features={"k": "v"})
        page = state.page("b", 1)
        assert page.review_flags == ["X"] and page.features == {"k": "v"}
    finally:
        state.close()


def test_state_corrupt_db_raises_state_error_with_backups(tmp_path: Path):
    (tmp_path / "state.sqlite3.bak-2099-01-01").write_bytes(b"backup")
    bad = tmp_path / "state.sqlite3"
    bad.write_bytes(b"this is not a sqlite database")
    with pytest.raises(StateError) as excinfo:
        State(bad)
    assert "bak-2099-01-01" in str(excinfo.value)


def test_state_fresh_db_gets_user_version_and_reopens(tmp_path: Path):
    db = tmp_path / "state.sqlite3"
    state = State(db)
    state.upsert_page(_page("b", 1))
    state.close()
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
    State(db).close()  # reopening an existing v1 DB works


def test_matrix_is_rotated_detects_flip_placements():
    assert _matrix_is_rotated({"transform": (1, 0, 0, 1, 0, 0)}) is False
    assert _matrix_is_rotated({"transform": (0, 1, -1, 0, 0, 0)}) is True
    assert _matrix_is_rotated({"transform": (-1, 0, 0, -1, 0, 0)}) is True
    assert _matrix_is_rotated({"transform": (-1, 0, 0, 1, 0, 0)}) is True


def _make_image(path: Path, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), color).save(path, "JPEG")


def test_preflight_sweep_passes_clean_packaged_book(tmp_path: Path):
    book_dir = tmp_path / "Book"
    for folder in ("ch", "vi"):
        for page in (1, 2, 3):
            _make_image(book_dir / folder / f"Book.{page:03d}.jpg", "red" if page == 1 else "blue")
    issues = check_book_images(book_dir, "Book", 3)
    assert [i for i in issues if i.severity == "error"] == []


def test_preflight_sweep_failures(tmp_path: Path):
    book_dir = tmp_path / "Book"
    _make_image(book_dir / "ch" / "Book.001.jpg")
    _make_image(book_dir / "ch" / "Book.002.jpg")
    _make_image(book_dir / "vi" / "Book.001.jpg")
    # missing page 3 entirely, stray png, vi/missing-vi overlap
    (book_dir / "ch" / "notes.png").write_bytes(b"png")
    _make_image(book_dir / "missing" / "vi" / "Book.001.jpg")
    issues = check_book_images(book_dir, "Book", 3)
    codes = {i.code for i in issues}
    assert "IMAGES_MISSING_PAGES" in codes
    assert "NON_JPG_FILE" in codes
    assert "VI_AND_MISSING_VI" in codes


def test_updated_pdf_gate_requires_file_when_rotated(tmp_path: Path):
    project = _project(tmp_path)
    book_dir = tmp_path / "out" / "Book"
    book_dir.mkdir(parents=True)
    pages = [SimpleNamespace(page_no=1, rotation=180, sha256="0" * 64)]
    issues = check_updated_pdf(project, project.books[0], book_dir, pages)
    codes = {i.code for i in issues}
    assert "MISSING_UPDATED_PDF" in codes
    # no rotated pages -> no gate
    issues = check_updated_pdf(
        project, project.books[0], book_dir, [SimpleNamespace(page_no=1, rotation=0, sha256="0" * 64)]
    )
    assert issues == []
