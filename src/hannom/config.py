"""Configuration loading and path resolution.

Filenames are Vietnamese Unicode and may be NFD. YAML is read as UTF-8 and
paths are resolved with pathlib, never by shell string interpolation.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class OCRSettings:
    nom: tuple[str, ...] = ("paddleocr_vl", "kimhannom")
    quoc_ngu: tuple[str, ...] = ("paddleocr_vl",)
    ensemble: bool = True
    api_mode: str = "sample_then_low_confidence"
    sample_pages: int = 12


@dataclass(frozen=True)
class BookConfig:
    book_id: str
    pdf: Path
    layout: str
    expected_pages: int
    scope: str = "all"
    front_matter_end: int = 0
    nom_start_hint: int = 0
    nom_end_hint: int = 0
    translation_start: int = 1
    translation_end: int = 0
    back_matter_is_toc: bool = True
    ocr: OCRSettings = field(default_factory=OCRSettings)
    review_profile: str = "strict"

    @property
    def book_name(self) -> str:
        """Exact assigned filename stem, including Unicode and spaces."""
        return self.pdf.stem

    @property
    def source_pdf(self) -> Path:
        return self.pdf


@dataclass(frozen=True)
class ApiSettings:
    base_url: str
    token_env: str
    user_agent: str
    limits: dict[str, int]
    min_delay_seconds: float = 3.0
    timeout_seconds: float = 120.0
    max_retries: int = 3
    cache_dir: Path = Path("data/ocr/api_cache")


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    project_name: str
    deadline: str
    zip_stem: str
    report_name: str
    one_zip_for_all_books: bool
    data_dir: Path
    artifacts_dir: Path
    output_dir: Path
    dictionaries_dir: Path
    models_dir: Path
    books: tuple[BookConfig, ...]
    api: ApiSettings
    quality: dict[str, float]
    ocr_config: dict[str, Any] = field(default_factory=dict)
    alignment_config: dict[str, Any] = field(default_factory=dict)
    dictionary_config: dict[str, Any] = field(default_factory=dict)
    review_config: dict[str, Any] = field(default_factory=dict)

    def book(self, book_id: str) -> BookConfig:
        for book in self.books:
            if book.book_id == book_id:
                return book
        raise ConfigError(f"Unknown book_id: {book_id}. Known: {[b.book_id for b in self.books]}")

    def selected_books(self, book_id: str | None = None) -> list[BookConfig]:
        if book_id:
            return [self.book(book_id)]
        return list(self.books)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected a mapping in {path}")
    return data


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def load_config(config_path: str | Path = "configs/project.yaml") -> ProjectConfig:
    config_path = Path(config_path).resolve()
    root = config_path.parent.parent
    raw = _read_yaml(config_path)
    project = raw.get("project", {})
    paths = raw.get("paths", {})
    api_raw = raw.get("api", {})
    quality = raw.get("quality", {})

    books: list[BookConfig] = []
    for rel in raw.get("books", []):
        book_path = _resolve(root, rel)
        b = _read_yaml(book_path)
        ocr_raw = b.get("ocr", {}) or {}
        books.append(
            BookConfig(
                book_id=str(b["book_id"]),
                pdf=_resolve(root, str(b["pdf"])),
                layout=str(b.get("layout", "T1")),
                expected_pages=int(b["expected_pages"]),
                scope=str(b.get("scope", "all")),
                front_matter_end=int(b.get("front_matter_end", 0)),
                nom_start_hint=int(b.get("nom_start_hint", 0)),
                nom_end_hint=int(b.get("nom_end_hint", 0)),
                translation_start=int(b.get("translation_start", 1)),
                translation_end=int(b.get("translation_end", 0)),
                back_matter_is_toc=bool(b.get("back_matter_is_toc", True)),
                ocr=OCRSettings(
                    nom=tuple(ocr_raw.get("nom", ["paddleocr_vl", "kimhannom"])),
                    # quoc_ngu is paddle-only since 2026-11-08; vintern_1b_v2 was dropped
    # (uncalibrated, no boxes). The API must stay out of QN.
    quoc_ngu=tuple(ocr_raw.get("quoc_ngu", ["paddleocr_vl"])),
                    ensemble=bool(ocr_raw.get("ensemble", True)),
                    api_mode=str(ocr_raw.get("api_mode", "sample_then_low_confidence")),
                    sample_pages=int(ocr_raw.get("sample_pages", 12)),
                ),
                review_profile=str(b.get("review_profile", "strict")),
            )
        )

    if not books:
        raise ConfigError("No books configured")

    data_dir = _resolve(root, str(paths.get("data", "data")))
    api = ApiSettings(
        base_url=str(api_raw.get("base_url", "https://kimhannom.fit.hcmus.edu.vn")).rstrip("/"),
        token_env=str(api_raw.get("token_env", "KIMHANNOM_TOKEN")),
        user_agent=str(api_raw.get("user_agent", "")),
        limits={k: int(v) for k, v in (api_raw.get("limits", {}) or {}).items()},
        min_delay_seconds=float(api_raw.get("min_delay_seconds", 3.0)),
        timeout_seconds=float(api_raw.get("timeout_seconds", 120.0)),
        max_retries=int(api_raw.get("max_retries", 3)),
        cache_dir=_resolve(root, str(api_raw.get("cache_dir", "data/ocr/api_cache"))),
    )

    return ProjectConfig(
        root=root,
        project_name=str(project.get("name", "Hán Nôm–Quốc ngữ parallel corpus")),
        deadline=str(project.get("deadline", "2026-11-30")),
        zip_stem=str(project.get("zip_stem", "24127189_MSSV2_MSSV3_MSSV4")),
        report_name=str(project.get("report_name", "24127189_MSSV2_MSSV3_MSSV4_report.pdf")),
        one_zip_for_all_books=bool(project.get("one_zip_for_all_books", True)),
        data_dir=data_dir,
        artifacts_dir=_resolve(root, str(paths.get("artifacts", "artifacts"))),
        output_dir=_resolve(root, str(paths.get("output", "data/output"))),
        dictionaries_dir=_resolve(root, str(paths.get("dictionaries", "dictionaries"))),
        models_dir=_resolve(root, str(paths.get("models", "models"))),
        books=tuple(books),
        api=api,
        quality={k: float(v) for k, v in quality.items()},
        ocr_config=_read_yaml(_resolve(root, "configs/ocr.yaml")),
        alignment_config=_read_yaml(_resolve(root, "configs/alignment.yaml")),
        dictionary_config=_read_yaml(_resolve(root, "configs/dictionary.yaml")),
        review_config=_read_yaml(_resolve(root, "configs/review.yaml")),
    )


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def ensure_utf8_env() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
