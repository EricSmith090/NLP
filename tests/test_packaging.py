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


def test_colour_kinds_accept_both_legal_sets_and_reject_theme():
    from openpyxl.styles.colors import Color

    from hannom.package import _colour_kind

    assert _colour_kind(Color(rgb="FFFF0000")) == "error"
    assert _colour_kind(Color(rgb="FFD32F2F")) == "error"
    assert _colour_kind(Color(rgb="FFFFFF00")) == "warn"
    assert _colour_kind(Color(rgb="00D99A00")) == "warn"
    assert _colour_kind(Color(rgb="FF000000")) == "black"
    assert _colour_kind(None) == "black"
    assert _colour_kind(Color(theme=1)) == "invalid"
    assert _colour_kind(Color(rgb="FF00FF00")) == "invalid"


def test_source_zip_rejects_state_backups_env_variants_and_credentials(tmp_path):
    import zipfile

    from hannom.package import validate_source_zip

    z = tmp_path / "source.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name in ("README.md", "USER_GUIDE.md", "pyproject.toml", ".env.example"):
            zf.writestr(name, "x")
        zf.writestr("data_copy/state.sqlite3.bak-2026-11-08", "x")
        zf.writestr(".env.local", "KIMHANNOM_TOKEN=abc")
        zf.writestr("hannom_API.md", "user/pass")
        zf.writestr("notes/cfg.json", '{"auth": "Bearer abcdefghijklmnopqrstuvwxyz0123"}')
    codes = [(i.code, i.message) for i in validate_source_zip(z)]
    flagged = {m.split(":")[0] for c, m in codes if c.startswith("SOURCE_CONTAINS")}
    assert {"data_copy/state.sqlite3.bak-2026-11-08", ".env.local", "hannom_API.md", "notes/cfg.json"} <= flagged
    assert ".env.example" not in flagged


def test_validator_missing_and_optional_folder_rules(tmp_path):
    import json as _json
    from types import SimpleNamespace

    from hannom.package import validate_book_package

    book = SimpleNamespace(book_id="B", book_name="B", vi_to_nom_offset=None)
    project = SimpleNamespace(data_dir=tmp_path / "data", root=tmp_path, quality={})
    d = tmp_path / "B"
    for sub in ("ch", "vi", "intro", "missing/ch", "missing/vi"):
        (d / sub).mkdir(parents=True)
    (d / "intro" / "B.001.jpg").write_bytes(b"x")
    (d / "missing" / "ch" / "B.276.jpg").write_bytes(b"x")  # not also in ch/
    (d / "missing" / "vi" / "B.013.jpg").write_bytes(b"x")
    (d / "vi" / "B.013.jpg").write_bytes(b"x")  # must not be in vi/
    (d / "missing" / "vi" / "Label.txt").write_text("", encoding="utf-8")
    (d / "B_image_map.json").write_text(_json.dumps({"pairs": [{"ch": ["B.275.jpg"], "vi": ["B.013.jpg"]}]}), encoding="utf-8")
    codes = {i.code for i in validate_book_package(project, book, d, require_labels=False)}
    assert {"OPTIONAL_FOLDER_INCOMPLETE", "MISSING_CH_NOT_IN_CH", "MISSING_VI_ALSO_IN_VI",
            "MISSING_HAS_LABELS", "MISSING_NOT_IN_IMAGE_MAP"} <= codes


def test_extras_zip_collects_review_artefacts(tmp_path):
    import zipfile
    from types import SimpleNamespace

    from hannom.package import build_extras_zip

    data = tmp_path / "data"
    (data / "review").mkdir(parents=True)
    (data / "review" / "B.patches.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "clean" / "B").mkdir(parents=True)
    (data / "clean" / "B" / "dropped.jsonl").write_text("{}\n", encoding="utf-8")
    project = SimpleNamespace(data_dir=data, output_dir=tmp_path / "out",
                              books=[SimpleNamespace(book_id="B", book_name="B")])
    names = zipfile.ZipFile(build_extras_zip(project)).namelist()
    assert names == ["B/review/patches.jsonl", "B/clean/dropped.jsonl"]
