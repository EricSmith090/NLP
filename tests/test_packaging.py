from __future__ import annotations

import zipfile
from pathlib import Path

from hannom.config import ApiSettings, BookConfig, ProjectConfig
from hannom.models import AlignmentRow
from hannom.package import (
    build_source_zip,
    build_submission_zip,
    read_xlsx_spans,
    validate_source_zip,
    write_alignment_xlsx,
)
from hannom.textdiff import make_element


def _project(root: Path) -> ProjectConfig:
    book = BookConfig(
        book_id="b",
        pdf=root / "Book.pdf",
        layout="T1",
        expected_pages=1,
    )
    return ProjectConfig(
        root=root,
        project_name="test",
        deadline="2026-11-30",
        zip_stem="24127189_MSSV2_MSSV3_MSSV4",
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


def test_xlsx_colours_match_text_diff(tmp_path: Path):
    row = AlignmentRow(
        img_id="Book.001.jpg",
        sentence_id="Book.001.1",
        ch_txt="字字",
        vi_txt="hai chữ",
        text_diff=[make_element("字字", "hai chữ", [[0, 1]], [[0, 3]], "error")],
    )
    path = write_alignment_xlsx(tmp_path / "Book.xlsx", [row])
    spans = read_xlsx_spans(path)
    assert len(spans) == 1
    assert spans[0]["C"]["spans"] == [[0, 1, "error"]]
    assert spans[0]["D"]["spans"] == [[0, 3, "error"]]


def test_source_zip_excludes_data_and_forbidden_files(tmp_path: Path):
    project = _project(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("print('x')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")
    (tmp_path / "USER_GUIDE.md").write_text("guide\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "secret.txt").write_text("secret\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    path = build_source_zip(project, tmp_path / "output" / "source.zip")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert "src/x.py" in names
    assert "README.md" in names
    assert "data/secret.txt" not in names
    assert ".env" not in names
    assert not validate_source_zip(path)


def test_submission_zip_contains_books_report_and_source(tmp_path: Path):
    project = _project(tmp_path)
    book_dir = tmp_path / "output" / "Book"
    book_dir.mkdir(parents=True)
    (book_dir / "Book.csv").write_text("img_id,sentence_id,ch_txt,vi_txt,text_diff\n", encoding="utf-8")
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF-1.4\n")
    source = tmp_path / "source.zip"
    source.write_bytes(b"PK")
    path = build_submission_zip(
        project,
        [book_dir],
        report_path=report,
        source_zip=source,
        output_path=tmp_path / "submission.zip",
    )
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
    assert "Book/Book.csv" in names
    assert "report.pdf" in names
    assert "source.zip" in names
