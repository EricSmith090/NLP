"""Stage 9: submission tree, CSV/XLSX, source archive, and ZIP builder.

The CSV is authoritative. XLSX colour spans are derived only from the same
``text_diff`` elements; a mismatch is a blocking validator error.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .align import CSV_COLUMNS, read_alignment_csv, write_alignment_csv
from .clean import MASK, nfc
from .config import BookConfig, ProjectConfig
from .labels import validate_label_txt
from .models import AlignmentRow, DiffElement, PageRecord
from .t1_map import Pair, load_image_map, validate_image_map

RED = "FFFF0000"
YELLOW = "FFFFFF00"
BLACK = "FF000000"
HEADER_FILL = PatternFill("solid", fgColor="FFD9E1F2")
LIGHT_FILL = PatternFill("solid", fgColor="FFF2F2F2")


@dataclass
class PackageIssue:
    code: str
    message: str
    severity: str = "error"
    path: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_jpegs(src_dir: Path, dest_dir: Path, pages: Sequence[PageRecord]) -> list[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for page in pages:
        if not page.image_name.lower().endswith(".jpg"):
            raise ValueError(f"non-JPG image in submission: {page.image_name}")
        source = page.path if page.path.exists() else src_dir / page.image_name
        if not source.exists():
            raise FileNotFoundError(f"missing image for {page.book_id} p{page.page_no}: {source}")
        shutil.copy2(source, dest_dir / page.image_name)
        names.append(page.image_name)
    return names


def _copy_label_files(
    label_dir: Path | None,
    dest_dir: Path,
    image_names: Sequence[str],
    folder: str,
    *,
    require_labels: bool,
) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    label_src = label_dir / folder / "Label.txt" if label_dir else None
    state_src = label_dir / folder / "fileState.txt" if label_dir else None
    if label_src and label_src.exists():
        shutil.copy2(label_src, dest_dir / "Label.txt")
    elif require_labels:
        # An empty but structurally valid label row is safer than a missing
        # row, but the missing OCR is still a blocking completeness issue.
        with (dest_dir / "Label.txt").open("w", encoding="utf-8", newline="\n") as fh:
            for name in image_names:
                fh.write(f"{folder}/{name}\t[]\n")
    if state_src and state_src.exists():
        shutil.copy2(state_src, dest_dir / "fileState.txt")
    else:
        with (dest_dir / "fileState.txt").open("w", encoding="utf-8", newline="\n") as fh:
            for name in image_names:
                fh.write(f"{folder}/{name}\t1\n")


def _elements(row: AlignmentRow) -> list[DiffElement] | None:
    return row.text_diff


def _rich_text(text: str, elements: Sequence[DiffElement] | None, side: str) -> Any:
    if not elements:
        return text
    spans: list[tuple[int, int, str]] = []
    for element in elements:
        color = RED if element.type == "error" else YELLOW
        positions = element.nom_pos if side == "nom" else element.vi_pos
        for start, end in positions:
            if 0 <= start < end <= len(text):
                spans.append((start, end, color))
    if not spans:
        return text
    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for start, end, color in spans:
        if merged and start < merged[-1][1]:
            # Different-type overlaps are a validator error; keep the first
            # colour here and let validation fail the package.
            if color == merged[-1][2]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end), color)
            continue
        merged.append((start, end, color))
    runs: list[Any] = []
    cursor = 0
    for start, end, color in merged:
        if cursor < start:
            runs.append(TextBlock(InlineFont(color=BLACK), text[cursor:start]))
        runs.append(TextBlock(InlineFont(color=color), text[start:end]))
        cursor = end
    if cursor < len(text):
        runs.append(TextBlock(InlineFont(color=BLACK), text[cursor:]))
    return CellRichText(runs)


def write_alignment_xlsx(path: str | Path, rows: Iterable[AlignmentRow]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "alignment"
    ws.append(CSV_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        elements = _elements(row)
        ws.append(
            [
                nfc(row.img_id),
                nfc(row.sentence_id),
                _rich_text(nfc(row.ch_txt), elements, "nom"),
                _rich_text(nfc(row.vi_txt), elements, "vi"),
                row.text_diff_json(),
            ]
        )
    widths = {"A": 24, "B": 24, "C": 52, "D": 52, "E": 42}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
    return path


def _find_label_dir(project: ProjectConfig, book: BookConfig) -> Path | None:
    candidate = project.data_dir / "labels" / book.book_id
    return candidate if candidate.exists() else None


def build_book_folder(
    project: ProjectConfig,
    book: BookConfig,
    pages: Sequence[PageRecord],
    rows: Sequence[AlignmentRow],
    *,
    output_root: Path | None = None,
    image_map_pairs: Sequence[Pair] | None = None,
) -> Path:
    root = output_root or project.output_dir
    book_dir = root / book.book_name
    if book_dir.exists():
        shutil.rmtree(book_dir)
    book_dir.mkdir(parents=True, exist_ok=True)

    by_folder: dict[str, list[PageRecord]] = {}
    for page in pages:
        by_folder.setdefault(str(page.folder), []).append(page)

    labels_root = _find_label_dir(project, book)
    for folder in ("ch", "vi", "intro", "ref", "toc", "blank", "misc"):
        folder_pages = by_folder.get(folder, [])
        if not folder_pages:
            continue
        dest = book_dir / folder
        names = _copy_jpegs(project.data_dir / "pages" / book.book_id / "native", dest, folder_pages)
        if folder in {"ch", "vi", "intro", "ref", "toc"}:
            _copy_label_files(labels_root, dest, names, folder, require_labels=folder in {"ch", "vi"})

    for folder in ("ch", "vi"):
        missing = by_folder.get(f"missing_{folder}", [])
        if missing:
            dest = book_dir / "missing" / folder
            names = _copy_jpegs(
                project.data_dir / "pages" / book.book_id / "native", dest, missing
            )
            _copy_label_files(labels_root, dest, names, f"missing/{folder}", require_labels=False)

    # Source PDF: exactly one original file in the book folder.
    pdf_dest = book_dir / f"{book.book_name}.pdf"
    shutil.copy2(book.pdf, pdf_dest)

    # Image map. Use the exact names present in the final folders.
    if image_map_pairs is None:
        image_map_path = project.data_dir / "layout" / book.book_id / "image_map.json"
        image_map_pairs = load_image_map(image_map_path) if image_map_path.exists() else []
    image_map = {"pairs": [pair.to_dict() for pair in image_map_pairs]}
    (book_dir / f"{book.book_name}_image_map.json").write_text(
        json.dumps(image_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    csv_path = book_dir / f"{book.book_name}.csv"
    write_alignment_csv(csv_path, rows)
    write_alignment_xlsx(book_dir / f"{book.book_name}.xlsx", rows)
    return book_dir


def _is_forbidden(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    parts = set(rel.parts)
    if parts & {"data", "models", "artifacts", ".git", "CV20-24127189", "Doc"}:
        return True
    if path.name in {".env"} or path.name.startswith(".env.") and path.name != ".env.example":
        return True
    if path.suffix.lower() == ".pdf":
        return True
    if "api_cache" in parts or "state.sqlite3" in path.name:
        return True
    return False


def build_source_zip(project: ProjectConfig, output_path: Path | None = None) -> Path:
    output_path = output_path or (project.output_dir / "source.zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    include_dirs = ["src", "configs", "tools", "tests", "docs"]
    include_files = [
        "README.md",
        "USER_GUIDE.md",
        "pyproject.toml",
        "uv.lock",
        ".env.example",
        ".gitignore",
    ]
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in include_files:
            path = project.root / name
            if path.exists() and not _is_forbidden(path, project.root):
                zf.write(path, name)
        for dirname in include_dirs:
            base = project.root / dirname
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                if _is_forbidden(path, project.root):
                    continue
                if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                zf.write(path, path.relative_to(project.root).as_posix())
    return output_path


def build_submission_zip(
    project: ProjectConfig,
    book_dirs: Sequence[Path],
    *,
    report_path: Path | None = None,
    source_zip: Path | None = None,
    extras_zip: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    output_path = output_path or (project.data_dir / "output" / f"{project.zip_stem}.zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for book_dir in book_dirs:
            for path in sorted(book_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(book_dir.parent).as_posix())
        if report_path and report_path.exists():
            zf.write(report_path, report_path.name)
        if source_zip and source_zip.exists():
            zf.write(source_zip, "source.zip")
        if extras_zip and extras_zip.exists():
            zf.write(extras_zip, "extras.zip")
    return output_path


def split_submission_zip(project: ProjectConfig, zip_path: Path, output_dir: Path | None = None) -> list[Path]:
    """Create one ZIP per book from a full submission ZIP (extension support)."""
    output_dir = output_dir or zip_path.parent / "split"
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        top_dirs = sorted({name.split("/", 1)[0] for name in names if "/" in name})
        for top in top_dirs:
            if top in {"source.zip", "extras.zip"} or top.endswith("_report.pdf"):
                continue
            dest = output_dir / f"{project.zip_stem}_{top}.zip"
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
                for name in names:
                    if name == top or name.startswith(top + "/"):
                        out.writestr(name, zf.read(name))
            created.append(dest)
    return created


def read_xlsx_spans(path: str | Path) -> list[dict[str, Any]]:
    """Read rich-text colour spans from the ch/vi columns for validation."""
    from openpyxl import load_workbook

    wb = load_workbook(path, rich_text=True)
    ws = wb.active
    rows: list[dict[str, Any]] = []
    for values in ws.iter_rows(min_row=2, max_col=5):
        record: dict[str, Any] = {}
        for column, cell in zip("ABCDE", values):
            value = cell.value
            if column in {"C", "D"} and isinstance(value, CellRichText):
                spans = []
                cursor = 0
                for block in value:
                    text = block.text if hasattr(block, "text") else str(block)
                    color = None
                    if hasattr(block, "font") and block.font is not None:
                        color = block.font.color
                        if hasattr(color, "rgb"):
                            color = color.rgb
                    if color in {RED, YELLOW, "FFFF0000", "FFFFFF00"}:
                        spans.append([cursor, cursor + len(text), "error" if color in {RED, "FFFF0000"} else "warn"])
                    cursor += len(text)
                record[column] = {"text": str(value), "spans": spans}
            else:
                record[column] = "" if value is None else str(value)
        rows.append(record)
    wb.close()
    return rows


def validate_book_package(
    project: ProjectConfig,
    book: BookConfig,
    book_dir: Path,
    *,
    minimum_similarity: float | None = None,
    require_labels: bool = True,
) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    if not book_dir.exists():
        return [PackageIssue("MISSING_BOOK_DIR", f"missing {book_dir}", path=str(book_dir))]
    expected_pdf = book_dir / f"{book.book_name}.pdf"
    if not expected_pdf.exists():
        issues.append(PackageIssue("MISSING_PDF", "source PDF missing", path=str(expected_pdf)))
    csv_path = book_dir / f"{book.book_name}.csv"
    xlsx_path = book_dir / f"{book.book_name}.xlsx"
    if not csv_path.exists():
        issues.append(PackageIssue("MISSING_CSV", "CSV missing", path=str(csv_path)))
    if not xlsx_path.exists():
        issues.append(PackageIssue("MISSING_XLSX", "XLSX missing", path=str(xlsx_path)))
    if not (book_dir / f"{book.book_name}_image_map.json").exists():
        issues.append(PackageIssue("MISSING_IMAGE_MAP", "image_map.json missing"))

    for folder in ("ch", "vi"):
        folder_dir = book_dir / folder
        if not folder_dir.exists():
            issues.append(PackageIssue("MISSING_FOLDER", f"{folder}/ missing", path=str(folder_dir)))
            continue
        jpgs = sorted(folder_dir.glob("*.jpg"))
        if not jpgs:
            issues.append(PackageIssue("EMPTY_FOLDER", f"{folder}/ has no images", path=str(folder_dir)))
        names = {p.name for p in jpgs}
        if any(not name.startswith(book.book_name + ".") for name in names):
            issues.append(PackageIssue("BAD_IMAGE_NAME", f"{folder}/ contains an image not named after the book"))
        if require_labels:
            result = validate_label_txt(
                folder_dir / "Label.txt",
                folder_dir,
                folder,
                folder_dir / "fileState.txt",
                require_all_images=True,
                strict_points=True,
            )
            for message in result.issues:
                issues.append(PackageIssue("LABEL_INVALID", message, path=str(folder_dir)))
            if not (folder_dir / "Label.txt").exists():
                issues.append(PackageIssue("MISSING_LABELS", f"{folder}/Label.txt missing"))
            if not (folder_dir / "fileState.txt").exists():
                issues.append(PackageIssue("MISSING_FILESTATE", f"{folder}/fileState.txt missing"))

    # CSV must be readable and internally consistent.
    if csv_path.exists():
        try:
            rows = read_alignment_csv(csv_path)
        except Exception as exc:  # noqa: BLE001
            issues.append(PackageIssue("CSV_UNREADABLE", str(exc), path=str(csv_path)))
            rows = []
        seen: set[str] = set()
        for row in rows:
            if row.sentence_id in seen:
                issues.append(PackageIssue("DUPLICATE_SENTENCE_ID", row.sentence_id, path=str(csv_path)))
            seen.add(row.sentence_id)
            if not row.img_id or not row.sentence_id:
                issues.append(PackageIssue("EMPTY_CSV_KEY", "img_id/sentence_id is empty", path=str(csv_path)))
            if "\n" in row.ch_txt or "\n" in row.vi_txt:
                issues.append(PackageIssue("CSV_NEWLINE", row.sentence_id, path=str(csv_path)))
            from .textdiff import validate_text_diff

            for problem in validate_text_diff(row.ch_txt, row.vi_txt, row.text_diff):
                issues.append(PackageIssue("CSV_TEXT_DIFF", f"{row.sentence_id}: {problem}", path=str(csv_path)))
        if minimum_similarity is not None:
            from .evaluate import evaluate_rows

            metrics = evaluate_rows(book.book_id, rows, minimum_similarity=minimum_similarity)
            if not metrics.passed:
                issues.append(
                    PackageIssue(
                        "QUALITY_GATE",
                        f"{book.book_id}: similarity={metrics.similarity} passed={metrics.passed}",
                        path=str(csv_path),
                    )
                )

    # XLSX colours must agree with the CSV text_diff.
    if xlsx_path.exists() and csv_path.exists():
        try:
            xlsx_rows = read_xlsx_spans(xlsx_path)
            csv_rows = read_alignment_csv(csv_path)
            if len(xlsx_rows) != len(csv_rows):
                issues.append(PackageIssue("XLSX_ROW_COUNT", "XLSX and CSV row counts differ", path=str(xlsx_path)))
            for csv_row, xlsx_row in zip(csv_rows, xlsx_rows):
                expected = {
                    "C": csv_row.text_diff,
                    "D": None,
                }
                for column in ("C", "D"):
                    cell = xlsx_row.get(column)
                    spans = cell.get("spans", []) if isinstance(cell, dict) else []
                    csv_spans = []
                    if column == "C" and expected["C"]:
                        for element in expected["C"]:
                            for start, end in element.nom_pos:
                                csv_spans.append([start, end, element.type])
                    if column == "D" and expected["C"]:
                        for element in expected["C"]:
                            for start, end in element.vi_pos:
                                csv_spans.append([start, end, element.type])
                    if sorted(map(tuple, spans)) != sorted(map(tuple, csv_spans)):
                        issues.append(
                            PackageIssue(
                                "XLSX_COLOUR_MISMATCH",
                                f"{csv_row.sentence_id} column {column}",
                                path=str(xlsx_path),
                            )
                        )
        except Exception as exc:  # noqa: BLE001
            issues.append(PackageIssue("XLSX_UNREADABLE", str(exc), path=str(xlsx_path)))

    return issues


def validate_source_zip(path: Path) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    if not path.exists():
        return [PackageIssue("MISSING_SOURCE_ZIP", "source.zip missing")]
    forbidden_names = {
        ".env",
        "state.sqlite3",
    }
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for name in names:
            parts = set(Path(name).parts)
            if parts & {"data", "models", "artifacts", ".git", "CV20-24127189"}:
                issues.append(PackageIssue("SOURCE_CONTAINS_DATA", name, path=str(path)))
            if Path(name).name in forbidden_names:
                issues.append(PackageIssue("SOURCE_CONTAINS_SECRET_OR_STATE", name, path=str(path)))
            if name.lower().endswith(".pdf"):
                issues.append(PackageIssue("SOURCE_CONTAINS_PDF", name, path=str(path)))
        for required in ("README.md", "USER_GUIDE.md", "pyproject.toml"):
            if required not in names:
                issues.append(PackageIssue("SOURCE_MISSING", required, path=str(path)))
        for name in names:
            if not name.lower().endswith((".py", ".md", ".toml", ".yaml", ".yml", ".txt", ".example")):
                continue
            try:
                text = zf.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            if "KIMHANNOM_TOKEN=" in text:
                value = text.split("KIMHANNOM_TOKEN=", 1)[1].splitlines()[0].strip()
                if value:
                    issues.append(PackageIssue("SOURCE_CONTAINS_TOKEN", name, path=str(path)))
    return issues
