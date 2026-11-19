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
from .models import AlignmentRow, BookMetrics

PLACEHOLDER = "〓"
PHONETIC, MEANING = "phonetic", "meaning"
TYPE_LABELS = {PHONETIC: "dịch âm", MEANING: "dịch nghĩa"}

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
    # v2.4 additions
    translation_types: dict[str, Any] = field(default_factory=dict)
    null_row_justification: dict[str, str] = field(default_factory=dict)
    confidence_note: str = ""
    missing_pages: dict[str, list[str]] = field(default_factory=dict)
    book_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    # configs/report.yaml placeholder_descriptions: {"U+F047C": "cấu tạo …"}
    placeholder_descriptions: dict[str, str] = field(default_factory=dict)


class ReportValidationError(RuntimeError):
    pass


def _default_confidence_note() -> str:
    return (
        "Label.txt có thêm trường `confidence` trong mỗi box: đây là giá trị truyền nguyên từ "
        "API Kim Hán Nôm (độ tin cậy nhận dạng của dịch vụ), không phải nhãn do nhóm gán "
        "và không tham gia vào text_diff hay công thức chấm điểm."
    )


def _norm_type(value: Any) -> str:
    v = str(value or "").strip().lower()
    if v in {"meaning", "nghia", "nghĩa", "dich nghia", "dịch nghĩa"}:
        return MEANING
    return PHONETIC


def _expand_types(rows: Sequence[AlignmentRow], spec: Any) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Per-row translation type. ``spec`` is a list of items
    {images|sentence_ids: [first, last] | range: all, type} (ranges in row order,
    inclusive) or a plain type string. Undeclared rows default to phonetic."""
    types = [PHONETIC] * len(rows)
    problems: list[str] = []
    declared: list[dict[str, Any]] = []
    if isinstance(spec, str):
        spec = [{"range": "all", "type": spec}]
    for item in spec or []:
        if not isinstance(item, dict):
            continue
        t = _norm_type(item.get("type"))
        by_img = "images" in item
        rng = item.get("images", item.get("sentence_ids"))
        if rng is None:
            lo, hi, label = 0, len(rows) - 1, "all"
        else:
            if isinstance(rng, str):
                parts = [x.strip() for x in rng.replace("..", "-").split("-", 1)]
            else:
                parts = [str(x) for x in rng]
            if len(parts) == 1:
                parts = parts * 2
            if len(parts) != 2:
                problems.append(f"bad range {rng!r}")
                continue
            ids = [r.img_id if by_img else r.sentence_id for r in rows]
            if parts[0] not in ids or parts[1] not in ids:
                problems.append(f"range endpoint not found {parts}")
                continue
            lo = ids.index(parts[0])
            hi = len(ids) - 1 - ids[::-1].index(parts[1])
            label = f"{parts[0]}..{parts[1]}"
        for i in range(lo, hi + 1):
            types[i] = t
        declared.append({"range": label, "type": t, "rows": max(0, hi - lo + 1)})
    return types, problems, declared


def compute_book_report_stats(
    rows: Sequence[AlignmentRow],
    translation_spec: Any = None,
    null_justification: str = "",
    placeholder_origins: Sequence[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Pure v2.4 report statistics for one book from its CSV rows."""
    total = len(rows)
    types, problems, declared = _expand_types(rows, translation_spec)
    meaning_rows = sum(1 for t in types if t == MEANING)
    null_rows = sum(1 for r in rows if r.text_diff is None)
    warn_total = warn_reviewed = 0
    yellow_chars = nom_chars = 0
    sugg: dict[str, dict[str, int]] = {}
    pending = 0
    for r in rows:
        nom_chars += len(r.ch_txt or "")
        for el in r.text_diff or []:
            if el.type != "warn":
                continue
            warn_total += 1
            yellow_chars += len(el.nom_sub_text or "")
            if el.reviewed == 1:
                warn_reviewed += 1
            if el.suggest is not None:
                b = sugg.setdefault(el.suggest_by or "unknown", {"accepted": 0, "rejected": 0, "pending": 0})
                if el.reviewed == 1:
                    b["accepted" if el.nom_sub_text == el.suggest else "rejected"] += 1
                else:
                    b["pending"] += 1
                    pending += 1
    # Every 〓 with its position and, when the clean stage recorded it, the
    # original glyph code (v2.4: list position + glyph description).
    from .placeholders import assign_origins, code_counts

    placeholders, placeholder_problems = assign_origins(rows, list(placeholder_origins or []))
    if placeholder_origins is None:
        placeholder_problems = []
    return {
        "total_rows": total,
        "translation_declared": bool(declared),
        "translation_types": declared,
        "translation_problems": problems,
        "meaning_rows": meaning_rows,
        "meaning_ratio": (meaning_rows / total) if total else None,
        "yellow_elements": warn_total,
        "yellow_reviewed": warn_reviewed,
        "yellow_unreviewed": warn_total - warn_reviewed,
        "yellow_chars": yellow_chars,
        "yellow_ratio": (yellow_chars / nom_chars) if nom_chars else None,
        "suggestions": sugg,
        "suggestions_pending": pending,
        "placeholder_count": len(placeholders),
        "placeholders": placeholders,
        "placeholder_codes": code_counts(placeholders),
        "placeholder_problems": placeholder_problems,
        "null_rows": null_rows,
        "null_ratio": (null_rows / total) if total else None,
        "null_justification": null_justification,
    }


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
        "text_diff theo Quy định v2.4 (cùng ngữ nghĩa với công cụ chấm ocr-nom-align v0.2.0): so âm đọc bỏ 5 dấu thanh; chữ 〓 và chữ không có âm đọc trong từ điển bị tô đỏ; âm tiết thừa bị tô đỏ; đoạn có số được tô vàng.",
    ]:
        writer.paragraph(f"- {note}")

    writer.heading("Tổng hợp theo sách", 2)
    if data.metrics:
        for metrics in data.metrics:
            writer.key_values(
                [
                    ("Sách", metrics.book_id),
                    (
                        "Similarity (công thức Quy định v2.4, mọi dòng không null)",
                        "N/A" if metrics.spec_formula_similarity is None
                        else f"{metrics.spec_formula_similarity:.2f}%",
                    ),
                    (
                        "Similarity nội bộ (chỉ dòng đã xác minh; tham khảo)",
                        "N/A" if metrics.similarity is None else f"{metrics.similarity:.2f}%",
                    ),
                    (
                        "Spec formula red/denom",
                        f"{metrics.spec_formula_red_chars} / {metrics.spec_formula_denominator}",
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
                    (
                        "Structural confidence (grouping)",
                        "N/A" if metrics.structural_confidence_mean is None else f"{metrics.structural_confidence_mean:.2f}",
                    ),
                    ("Semantic evidence rows", str(metrics.semantic_evidence_rows)),
                    ("Evidence-insufficient rows", str(metrics.evidence_insufficient_rows)),
                    ("Decision diagnostics (superseded)", str(len(metrics.decision_audit_diagnostics))),
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
                ("Structural confidence (grouping)", "N/A" if metrics.structural_confidence_mean is None else f"{metrics.structural_confidence_mean:.4f}"),
                ("Semantic evidence rows", str(metrics.semantic_evidence_rows)),
                ("Evidence-insufficient rows", str(metrics.evidence_insufficient_rows)),
                ("Decision diagnostics (superseded)", str(len(metrics.decision_audit_diagnostics))),
                ("Similarity (Quy định v2.4)", "N/A" if metrics.spec_formula_similarity is None else f"{metrics.spec_formula_similarity:.4f}%"),
                ("Similarity nội bộ (chỉ dòng đã xác minh)", "N/A" if metrics.similarity is None else f"{metrics.similarity:.4f}%"),
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
    writer.heading("Các mục theo Quy định v2.4", 1)
    for book_id, st in data.book_stats.items():
        writer.heading(f"Sách {book_id}", 2)
        if st.get("translation_declared"):
            for t in st.get("translation_types", []):
                writer.paragraph(f"- Loại dịch [{t['range']}]: {TYPE_LABELS[t['type']]} ({t['rows']} dòng)")
        else:
            writer.paragraph("[BLOCKER] Chưa khai báo loại dịch (dịch âm / dịch nghĩa).", color=(0.75, 0, 0))
        ratio = st.get("meaning_ratio")
        writer.paragraph(
            f"Cặp dịch nghĩa: {st['meaning_rows']} / {st['total_rows']}"
            + ("" if ratio is None else f" ({ratio:.2%})")
        )
        writer.paragraph(
            f"Ký tự Nôm vàng (warn): {st['yellow_elements']} phần tử; đã review {st['yellow_reviewed']}, "
            f"chưa review {st['yellow_unreviewed']}; tỷ lệ yellow "
            + ("N/A" if st["yellow_ratio"] is None else f"{st['yellow_ratio']:.2%}")
        )
        for src, b in sorted(st["suggestions"].items()):
            writer.paragraph(
                f"Gợi ý nguồn '{src}': chấp nhận {b['accepted']}, từ chối {b['rejected']}, chưa xử lý {b['pending']}"
            )
        if not st["suggestions"]:
            writer.paragraph("Gợi ý: không có.")
        nr = st["null_ratio"]
        writer.paragraph(
            f"Dòng null (text_diff = null): {st['null_rows']} / {st['total_rows']}"
            + ("" if nr is None else f" ({nr:.2%})")
        )
        writer.paragraph(f"Lý do dòng null: {st['null_justification'] or '[CHƯA GHI LÝ DO]'}")
        writer.paragraph(f"Ký tự 〓: {st['placeholder_count']} lần xuất hiện")
        for code, count in st.get("placeholder_codes", {}).items():
            desc = data.placeholder_descriptions.get(code, "").strip() or "[CHƯA MÔ TẢ CẤU TẠO]"
            writer.paragraph(f"  {code} × {count}: {desc}", size=9, after=0)
        for ph in st["placeholders"][:200]:
            writer.paragraph(
                f"  {ph['sentence_id']} @ {ph['position']} ({ph.get('code', 'unknown')})", size=9, after=0
            )
        if len(st["placeholders"]) > 200:
            writer.paragraph(
                f"  ... và {len(st['placeholders']) - 200} vị trí khác (đầy đủ trong report_summary.json).", size=9
            )
        lost = data.missing_pages.get(book_id)
        writer.paragraph(
            "Trang bị mất khi scan: " + ("; ".join(lost) if lost else "không có (không có thư mục missing/).")
        )
    writer.heading("Trường confidence trong Label.txt", 2)
    writer.paragraph(data.confidence_note or _default_confidence_note())

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
    data.translation_types = dict(raw.get("translation_types", {}) or {})
    data.null_row_justification = {
        str(k): str(v) for k, v in (raw.get("null_row_justification", {}) or {}).items()
    }
    data.confidence_note = str(raw.get("confidence_note", "") or "")
    data.placeholder_descriptions = {
        str(k).upper().replace("U+", "U+"): str(v) for k, v in (raw.get("placeholder_descriptions", {}) or {}).items()
    }
    for book in project.books:
        csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
        if csv_path.exists():
            try:
                from .align import read_alignment_csv

                rows = read_alignment_csv(csv_path)
            except Exception:
                rows = None
            if rows is not None:
                origins = None
                try:
                    from .orchestrator import load_cleaned_pages
                    from .placeholders import stream_origins
                    from .t1_map import load_image_map

                    map_path = project.data_dir / "layout" / book.book_id / "image_map.json"
                    if map_path.exists():
                        origins = stream_origins(load_image_map(map_path), load_cleaned_pages(project, book))
                except Exception:  # noqa: BLE001 - the report still lists positions
                    origins = None
                data.book_stats[book.book_id] = compute_book_report_stats(
                    rows,
                    data.translation_types.get(book.book_id, data.translation_types.get("default")),
                    data.null_row_justification.get(book.book_id, ""),
                    origins,
                )
        lost = sorted(
            str(p.relative_to(project.data_dir))
            for base in (project.data_dir / "labels" / book.book_id, project.data_dir / "pages" / book.book_id)
            if base.exists()
            for p in base.rglob("missing")
            if p.is_dir()
        )
        if lost:
            data.missing_pages[book.book_id] = lost
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
    for member in data.members:
        if not member.full_name.strip():
            issues.append(f"REPORT_MEMBER_NAME_MISSING:{member.student_id or '?'}")
        if not member.student_id.strip():
            issues.append(f"REPORT_MEMBER_ID_MISSING:{member.full_name or '?'}")
        if not member.email.strip():
            issues.append(f"REPORT_MEMBER_EMAIL_MISSING:{member.student_id or member.full_name or '?'}")
    book_ids = list(data.book_stats) or [m.book_id for m in data.metrics]
    for book_id in book_ids:
        st = data.book_stats.get(book_id)
        declared = st["translation_declared"] if st else bool(
            data.translation_types.get(book_id, data.translation_types.get("default"))
        )
        if not declared:
            issues.append(f"REPORT_TRANSLATION_TYPE_MISSING:{book_id}")
        if st and st["null_rows"] and not st["null_justification"].strip():
            issues.append(f"REPORT_NULL_JUSTIFICATION_MISSING:{book_id}")
        if st:
            for problem in st.get("placeholder_problems", []):
                issues.append(f"REPORT_{problem.split(':', 1)[0]}:{book_id}")
            for code in st.get("placeholder_codes", {}):
                if code != "unknown" and not data.placeholder_descriptions.get(code, "").strip():
                    issues.append(f"REPORT_PLACEHOLDER_DESCRIPTION_MISSING:{book_id}:{code}")
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
        "book_stats": data.book_stats,
        "translation_types": data.translation_types,
        "missing_pages": data.missing_pages,
        "confidence_note": data.confidence_note or _default_confidence_note(),
        "validation": validate_report_data(data),
    }
