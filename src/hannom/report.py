"""Report generation and validation.

The PDF is generated locally with PyMuPDF so no document leaves the machine.
Missing member or screenshot data is rendered as a visible blocker rather
than silently omitted.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import pymupdf
from PIL import Image

from .config import ProjectConfig
from .models import BookMetrics

PAGE_W, PAGE_H = 595.0, 842.0  # A4 points
MARGIN_X, MARGIN_Y = 54.0, 54.0
BODY_SIZE = 10.5
LINE_GAP = 14.0


@dataclass
class Member:
    full_name: str = ""
    student_id: str = ""
    email: str = ""

    def complete(self) -> bool:
        return bool(self.full_name.strip() and self.student_id.strip() and self.email.strip())


@dataclass
class Screenshot:
    caption: str
    path: Path
    book_id: str | None = None
    required: bool = True


@dataclass
class ReportData:
    members: list[Member] = field(default_factory=list)
    metrics: list[BookMetrics] = field(default_factory=list)
    book_notes: dict[str, str] = field(default_factory=dict)
    screenshots: list[Screenshot] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    method_notes: list[str] = field(default_factory=list)
    yellow_reasons: dict[str, str] = field(default_factory=dict)
    output_path: Path | None = None


class ReportValidationError(RuntimeError):
    pass


def _font_paths() -> tuple[str, str, str | None]:
    candidates = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/msyh.ttc"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", None),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", None),
    ]
    for body, bold, cjk in candidates:
        if Path(body).exists() and Path(bold).exists():
            return body, bold, cjk if cjk and Path(cjk).exists() else None
    raise ReportValidationError("no usable TTF font found for report generation")


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def _runs(text: str) -> list[tuple[bool, str]]:
    if not text:
        return []
    out: list[tuple[bool, str]] = []
    current_cjk = _is_cjk(text[0])
    current = text[0]
    for ch in text[1:]:
        is_cjk = _is_cjk(ch)
        if is_cjk == current_cjk:
            current += ch
        else:
            out.append((current_cjk, current))
            current_cjk = is_cjk
            current = ch
    out.append((current_cjk, current))
    return out


class _Writer:
    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self.page: pymupdf.Page | None = None
        self.y = MARGIN_Y
        self.body_path, self.bold_path, self.cjk_path = _font_paths()
        self.body_font = pymupdf.Font(fontfile=self.body_path)
        self.bold_font = pymupdf.Font(fontfile=self.bold_path)
        self.cjk_font = pymupdf.Font(fontfile=self.cjk_path) if self.cjk_path else self.body_font
        self.new_page()

    def new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.page.insert_font(fontname="F0", fontfile=self.body_path)
        self.page.insert_font(fontname="F1", fontfile=self.bold_path)
        if self.cjk_path:
            self.page.insert_font(fontname="F2", fontfile=self.cjk_path)
        self.y = MARGIN_Y

    def ensure(self, height: float) -> None:
        if self.y + height > PAGE_H - MARGIN_Y:
            self.new_page()

    def _measure(self, text: str, size: float, bold: bool = False) -> float:
        total = 0.0
        for is_cjk, run in _runs(text):
            font = self.cjk_font if is_cjk and self.cjk_path else (self.bold_font if bold else self.body_font)
            total += font.text_length(run, fontsize=size)
        return total

    def _draw_line(self, text: str, size: float, bold: bool, color: tuple[float, float, float]) -> None:
        x = MARGIN_X
        for is_cjk, run in _runs(text):
            if is_cjk and self.cjk_path:
                fontname = "F2"
                font = self.cjk_font
            else:
                fontname = "F1" if bold else "F0"
                font = self.bold_font if bold else self.body_font
            self.page.insert_text(
                pymupdf.Point(x, self.y),
                run,
                fontname=fontname,
                fontsize=size,
                color=color,
            )
            x += font.text_length(run, fontsize=size)

    def _wrap(self, text: str, size: float, bold: bool = False, width: float | None = None) -> list[str]:
        width = width or (PAGE_W - 2 * MARGIN_X)
        words = text.split(" ")
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if self._measure(candidate, size, bold) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # Hard-break a single word that cannot fit.
                while self._measure(word, size, bold) > width and len(word) > 1:
                    cut = len(word)
                    while cut > 1 and self._measure(word[:cut], size, bold) > width:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    def paragraph(
        self,
        text: str,
        *,
        size: float = BODY_SIZE,
        bold: bool = False,
        color: tuple[float, float, float] = (0, 0, 0),
        before: float = 0.0,
        after: float = 4.0,
    ) -> None:
        self.y += before
        for raw_line in text.split("\n"):
            for line in self._wrap(raw_line, size, bold):
                self.ensure(LINE_GAP)
                self._draw_line(line, size, bold, color)
                self.y += LINE_GAP if size >= 10 else size * 1.35
        self.y += after

    def heading(self, text: str, level: int = 1) -> None:
        sizes = {1: 18, 2: 14, 3: 11.5}
        self.ensure(30)
        self.paragraph(text, size=sizes.get(level, 11.5), bold=True, before=8, after=6)

    def key_values(self, pairs: Sequence[tuple[str, str]]) -> None:
        for key, value in pairs:
            self.paragraph(f"{key}: {value}", size=10, after=1)

    def image(self, path: Path, caption: str, max_height: float = 500.0) -> None:
        if not path.exists():
            self.paragraph(f"[SCREENSHOT MISSING] {caption} — expected at {path}", color=(0.75, 0, 0))
            return
        with Image.open(path) as im:
            width, height = im.size
        max_width = PAGE_W - 2 * MARGIN_X
        scale = min(max_width / max(1, width), max_height / max(1, height), 1.0)
        draw_w, draw_h = width * scale, height * scale
        self.ensure(draw_h + 28)
        rect = pymupdf.Rect(MARGIN_X, self.y, MARGIN_X + draw_w, self.y + draw_h)
        self.page.insert_image(rect, filename=str(path), keep_proportion=True)
        self.y += draw_h + 4
        self.paragraph(caption, size=9, color=(0.2, 0.2, 0.2), after=8)

    def finish_page_numbers(self) -> None:
        total = self.doc.page_count
        for index, page in enumerate(self.doc):
            page.insert_text(
                pymupdf.Point(PAGE_W - MARGIN_X - 28, PAGE_H - 28),
                f"{index + 1}/{total}",
                fontname="F0",
                fontsize=8,
                color=(0.45, 0.45, 0.45),
            )


def build_report_pdf(data: ReportData, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    writer = _Writer(doc)

    writer.heading("Hán Nôm – Quốc ngữ Parallel Corpus", 1)
    writer.paragraph(
        "Báo cáo đồ án T1 — ba sách, 950 trang. Tài liệu này được tạo cục bộ; "
        "không có ảnh scan nào được gửi tới dịch vụ đám mây."
    )
    writer.key_values(
        [
            ("Ngày tạo", dt.date.today().isoformat()),
            ("Hạn nộp", "2026-11-30"),
            ("Số sách", str(len(data.metrics))),
        ]
    )
    writer.heading("Thành viên nhóm", 2)
    if not data.members:
        writer.paragraph("[BLOCKER] Chưa có thông tin thành viên.", color=(0.75, 0, 0))
    for member in data.members:
        status = "OK" if member.complete() else "THIẾU THÔNG TIN"
        writer.paragraph(
            f"- {member.full_name or '[họ tên]'} — MSSV {member.student_id or '[MSSV]'} — "
            f"{member.email or '[email]'} ({status})"
        )
    writer.heading("Tóm tắt phương pháp", 2)
    for note in data.method_notes or [
        "Pipeline cục bộ: trích ảnh gốc, phân loại trang, OCR, PPOCRLabel, làm sạch, "
        "căn hàng, text_diff, đánh giá và đóng gói.",
        "Kim Hán Nôm API chỉ dùng như ý kiến thứ hai có đo lường; không dùng nhiều tài khoản.",
        "Từ điển là tùy chọn; ký tự không có trong từ điển không bị tự động tô đỏ.",
    ]:
        writer.paragraph(f"- {note}")

    writer.heading("Tổng hợp theo sách", 2)
    if data.metrics:
        for metrics in data.metrics:
            writer.key_values(
                [
                    ("Sách", metrics.book_id),
                    (
                        "Similarity",
                        "N/A" if metrics.similarity is None else f"{metrics.similarity:.2f}%",
                    ),
                    (
                        "Yellow ratio",
                        "N/A" if metrics.yellow_ratio is None else f"{metrics.yellow_ratio:.2%}",
                    ),
                    (
                        "Null-row ratio",
                        "N/A" if metrics.null_ratio is None else f"{metrics.null_ratio:.2%}",
                    ),
                    (
                        "Coverage",
                        "N/A" if metrics.coverage_ratio is None else f"{metrics.coverage_ratio:.2%}",
                    ),
                    ("Gate ≥95%", "PASS" if metrics.passed else "FAIL"),
                ]
            )
            if data.yellow_reasons.get(metrics.book_id):
                writer.paragraph(
                    f"  Lý do yellow: {data.yellow_reasons[metrics.book_id]}", size=9.5
                )
    else:
        writer.paragraph("[BLOCKER] Chưa có metrics.", color=(0.75, 0, 0))

    for metrics in data.metrics:
        writer.new_page()
        writer.heading(f"Sách: {metrics.book_id}", 1)
        writer.key_values(
            [
                ("Tổng số dòng", str(metrics.total_rows)),
                ("Dòng có text_diff", str(metrics.scored_rows)),
                ("Dòng null", f"{metrics.null_rows} ({metrics.null_ratio:.2%})" if metrics.null_ratio is not None else str(metrics.null_rows)),
                ("Tổng ký tự Nôm", str(metrics.total_nom_chars)),
                ("Ký tự yellow", f"{metrics.yellow_chars} ({metrics.yellow_ratio:.2%})" if metrics.yellow_ratio is not None else str(metrics.yellow_chars)),
                ("Ký tự red (penalty)", str(metrics.red_mismatch_chars)),
                ("Mẫu số scored", str(metrics.denominator)),
                ("Dòng verified match", str(metrics.verified_match_rows)),
                ("Dòng verified difference", str(metrics.verified_difference_rows)),
                ("Dòng chưa xác minh", str(metrics.unverified_rows)),
                ("Dòng unmatched", str(metrics.unmatched_rows)),
                ("Coverage", "N/A" if metrics.coverage_ratio is None else f"{metrics.coverage_ratio:.2%}"),
                ("Similarity", "N/A" if metrics.similarity is None else f"{metrics.similarity:.4f}%"),
                ("Kết luận", "PASS" if metrics.passed else "FAIL"),
            ]
        )
        if data.yellow_reasons.get(metrics.book_id):
            writer.heading("Yellow ratio và lý do", 3)
            writer.paragraph(data.yellow_reasons[metrics.book_id])
        if data.book_notes.get(metrics.book_id):
            writer.heading("Ghi chú", 3)
            writer.paragraph(data.book_notes[metrics.book_id])
        if metrics.issues:
            writer.heading("Lỗi chặn", 3)
            for issue in metrics.issues[:30]:
                writer.paragraph(f"- {issue}", size=9.5)
        if metrics.warnings:
            writer.heading("Cảnh báo", 3)
            for warning in metrics.warnings[:30]:
                writer.paragraph(f"- {warning}", size=9.5)

    writer.new_page()
    writer.heading("Phụ lục ảnh chụp bắt buộc", 1)
    writer.paragraph(
        "Ảnh chụp phải thể hiện đúng giao diện PPOCRLabel (trang Nôm và trang Quốc ngữ), "
        "file XLSX đang mở và file CSV đang mở không bị lệch cột."
    )
    if not data.screenshots:
        writer.paragraph("[BLOCKER] Chưa cấu hình ảnh chụp nào.", color=(0.75, 0, 0))
    for screenshot in data.screenshots:
        writer.heading(screenshot.caption, 3)
        writer.image(screenshot.path, screenshot.caption)

    writer.new_page()
    writer.heading("Tài liệu tham khảo", 1)
    for citation in data.citations or [
        "Quy_định_đồ_án_v2.1.pdf — quy định đồ án (nguồn chuẩn).",
        "Hướng dẫn sử dụng API Kim Hán Nôm.",
        "Mô tả dữ liệu từ điển Hán Nôm và Quốc ngữ.",
        "PyMuPDF, Vintern-1B-v2, PaddleOCR, PPOCRLabel, Streamlit, openpyxl.",
    ]:
        writer.paragraph(f"- {citation}")

    writer.finish_page_numbers()
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return output_path


def load_report_config(project: ProjectConfig) -> ReportData:
    path = project.root / "configs" / "report.yaml"
    data = ReportData()
    if not path.exists():
        return data
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for item in raw.get("members", []) or []:
        data.members.append(
            Member(
                full_name=str(item.get("full_name", "")),
                student_id=str(item.get("student_id", "")),
                email=str(item.get("email", "")),
            )
        )
    for item in raw.get("screenshots", []) or []:
        data.screenshots.append(
            Screenshot(
                caption=str(item.get("caption", "Screenshot")),
                path=(project.root / str(item.get("path", ""))).resolve(),
                book_id=item.get("book_id"),
                required=bool(item.get("required", True)),
            )
        )
    data.citations = [str(x) for x in raw.get("citations", []) or []]
    data.method_notes = [str(x) for x in raw.get("method_notes", []) or []]
    data.yellow_reasons = {str(k): str(v) for k, v in (raw.get("yellow_reasons", {}) or {}).items()}
    data.book_notes = {str(k): str(v) for k, v in (raw.get("book_notes", {}) or {}).items()}
    return data


def validate_report_data(data: ReportData) -> list[str]:
    issues: list[str] = []
    if not data.members:
        issues.append("REPORT_MEMBERS_MISSING")
    for member in data.members:
        if not member.complete():
            issues.append(f"REPORT_MEMBER_INCOMPLETE:{member.student_id or member.full_name}")
    if not data.metrics:
        issues.append("REPORT_METRICS_MISSING")
    for screenshot in data.screenshots:
        if screenshot.required and not screenshot.path.exists():
            issues.append(f"REPORT_SCREENSHOT_MISSING:{screenshot.caption}:{screenshot.path}")
    required_captions = {"Nôm", "PPOCRLabel", "XLSX", "CSV"}
    captions = " ".join(s.caption for s in data.screenshots)
    for token in required_captions:
        if token not in captions:
            issues.append(f"REPORT_SCREENSHOT_CATEGORY_MISSING:{token}")
    return issues


def report_summary_json(data: ReportData) -> dict[str, Any]:
    return {
        "members": [m.__dict__ for m in data.members],
        "metrics": [m.to_dict() for m in data.metrics],
        "screenshots": [
            {"caption": s.caption, "path": str(s.path), "book_id": s.book_id, "exists": s.path.exists()}
            for s in data.screenshots
        ],
        "validation": validate_report_data(data),
    }
