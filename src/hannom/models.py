"""Shared data models. Keep these free of third-party imports so tests and
validators can use them without loading OCR or GUI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Script = Literal["nom", "qn", "mixed", "blank", "unknown"]
Folder = Literal["ch", "vi", "intro", "ref", "toc", "blank", "misc", "missing_ch", "missing_vi"]


@dataclass
class PageRecord:
    book_id: str
    page_no: int
    image_name: str
    pdf_page: int
    sha256: str
    width: int
    height: int
    path: Path
    script: Script = "unknown"
    section: str = "unknown"
    folder: Folder | str = ""
    status: str = "extracted"
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    review_flags: list[str] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    extraction_method: str = ""
    rotation: int = 0

    @property
    def page_id(self) -> str:
        return f"{self.book_id}:{self.page_no:04d}"


@dataclass
class OCRLine:
    text: str
    points: tuple[tuple[float, float], ...]
    confidence: float | None = None
    script: str | None = None
    difficult: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_ppocr(self) -> dict[str, Any]:
        box: dict[str, Any] = {
            "transcription": self.text,
            "points": [[float(x), float(y)] for x, y in self.points],
        }
        if self.difficult is not None:
            box["difficult"] = bool(self.difficult)
        if self.confidence is not None:
            box["confidence"] = float(self.confidence)
        return box


@dataclass
class OCRResult:
    book_id: str
    page_no: int
    image_name: str
    image_sha256: str
    engine: str
    lines: list[OCRLine] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    cached: bool = False


@dataclass(frozen=True)
class DiffElement:
    nom_pos: tuple[tuple[int, int], ...]
    nom_sub_text: str
    vi_pos: tuple[tuple[int, int], ...]
    vi_sub_text: str
    type: Literal["warn", "error"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nom_pos": [list(p) for p in self.nom_pos],
            "nom_sub_text": self.nom_sub_text,
            "vi_pos": [list(p) for p in self.vi_pos],
            "vi_sub_text": self.vi_sub_text,
            "type": self.type,
        }


@dataclass
class AlignmentRow:
    img_id: str
    sentence_id: str
    ch_txt: str
    vi_txt: str
    text_diff: list[DiffElement] | None = None
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)

    def text_diff_json(self) -> str:
        if self.text_diff is None:
            return "null"
        import json

        return json.dumps([d.to_dict() for d in self.text_diff], ensure_ascii=False)


@dataclass
class BookMetrics:
    book_id: str
    total_rows: int = 0
    null_rows: int = 0
    scored_rows: int = 0
    total_nom_chars: int = 0
    yellow_chars: int = 0
    red_mismatch_chars: int = 0
    denominator: int = 0
    similarity: float | None = None
    yellow_ratio: float | None = None
    null_ratio: float | None = None
    passed: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


@dataclass
class Issue:
    code: str
    message: str
    severity: Literal["info", "warning", "error", "blocker"] = "error"
    path: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
