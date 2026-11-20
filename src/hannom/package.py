"""Stage 9: submission tree, CSV/XLSX, source archive, and ZIP builder.

The CSV is authoritative. XLSX colour spans are derived only from the same
``text_diff`` elements; a mismatch is a blocking validator error.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import unicodedata
import warnings
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
    # Back up the state DB before any destructive packaging step
    # (best-effort: warn, never mask the packaging itself).
    db = project.data_dir / "state.sqlite3"
    if db.exists():
        try:
            from .state import State

            with State(db) as st:
                st.backup("package")
        except Exception as exc:  # noqa: BLE001
            warnings.warn(f"state backup before packaging failed: {exc}", stacklevel=2)
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
            _copy_jpegs(
                project.data_dir / "pages" / book.book_id / "native", dest, missing
            )
            # Guidelines: missing/ch image also lives in ch/ (QN missing);
            # missing/vi image lives only in missing/vi (Nom missing).
            if folder == "ch":
                dest_ch = book_dir / "ch"
                dest_ch.mkdir(parents=True, exist_ok=True)
                _copy_jpegs(
                    project.data_dir / "pages" / book.book_id / "native",
                    dest_ch,
                    missing,
                )
        # missing/ never carries Label.txt / fileState.txt.

    # Source PDF: exactly one original file in the book folder.
    pdf_dest = book_dir / f"{book.book_name}.pdf"
    shutil.copy2(book.pdf, pdf_dest)

    # Orientation-corrected merged PDF, required by the guideline when any
    # image changed. Staged by tools/build_updated_pdf.py; absence is normal
    # for books with no rotated pages (e.g. Book 3).
    staged_updated = (
        project.output_dir / book.book_id / book.book_name / f"{book.book_name}_updated.pdf"
    )
    if staged_updated.exists():
        shutil.copy2(staged_updated, book_dir / f"{book.book_name}_updated.pdf")

    # Image map. Copy the maintained artifact verbatim (pairs + full meta:
    # mapping_source, markers_used, vi_page_count, verified/candidate
    # counts) instead of round-tripping through Pair objects (which dropped
    # the whole meta block and silently re-defaulted statuses).
    image_map_path = project.data_dir / "layout" / book.book_id / "image_map.json"
    if image_map_path.exists():
        (book_dir / f"{book.book_name}_image_map.json").write_bytes(image_map_path.read_bytes())
    else:
        if image_map_pairs is None:
            image_map_pairs = []
        fallback = {"pairs": [pair.to_dict() for pair in image_map_pairs]}
        (book_dir / f"{book.book_name}_image_map.json").write_text(
            json.dumps(fallback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    csv_path = book_dir / f"{book.book_name}.csv"
    # The submission folder holds only the files the guideline lists; the
    # review-metadata sidecar stays in data/align (it ships in extras.zip).
    write_alignment_csv(csv_path, rows, metadata=False)
    write_alignment_xlsx(book_dir / f"{book.book_name}.xlsx", rows)

    # Regenerate pages.jsonl from the final in-memory page state so the
    # recorded artifact is no longer the stale Stage-1-time snapshot (the
    # SQLite DB remains authoritative). Best-effort: warn, never fail.
    try:
        from .intake import sha256_file
        from .pages import _write_pages_jsonl
        from .state import State

        manifest_path = project.data_dir / "pages" / book.book_id / "pages.jsonl"
        _write_pages_jsonl(manifest_path, list(pages))
        with State(project.data_dir / "state.sqlite3") as st:
            st.set_artifact(
                book.book_id,
                "pages",
                "native_jsonl",
                manifest_path,
                sha256=sha256_file(manifest_path),
                meta={
                    "page_count": len(pages),
                    "kind": "packaging-snapshot",
                    "native_size": sorted({(p.width, p.height) for p in pages}),
                },
            )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"pages.jsonl regeneration at packaging time failed: {exc}", stacklevel=2)
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
        "requirements-lock.txt",
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


def extras_entries(project: ProjectConfig) -> list[tuple[Path, str]]:
    """(source file, name inside extras.zip) for the review/reproducibility
    artefacts: reviewer patches and decisions, review metadata, SYNC report,
    clean-time drops, the book lexicons, QN quality queues, the 〓 catalogue
    and the official-checker report. No images, no secrets, no state DB."""
    from .review_decisions import decision_path

    data = project.data_dir
    out: list[tuple[Path, str]] = []
    for book in project.books:
        b = book.book_id
        candidates = [
            (data / "review" / f"{b}.patches.jsonl", f"{b}/review/patches.jsonl"),
            (decision_path(data, b), f"{b}/review/review_decisions.jsonl"),
            (data / "align" / b / f"{book.book_name}.review_metadata.jsonl", f"{b}/align/review_metadata.jsonl"),
            (data / "align" / b / "sync_check.json", f"{b}/align/sync_check.json"),
            (data / "align" / b / "summary.json", f"{b}/align/summary.json"),
            (data / "clean" / b / "dropped.jsonl", f"{b}/clean/dropped.jsonl"),
            (data / "clean" / b / "summary.json", f"{b}/clean/summary.json"),
            (data / "dictionary" / "book_lexicons" / f"{b}.json", f"{b}/lexicon/{b}.json"),
            (data / "diagnostics" / "qn_quality" / f"{b}.csv", f"{b}/qn_quality.csv"),
            (data / "evaluation" / b / "metrics.json", f"{b}/metrics.json"),
        ]
        out += [(src, name) for src, name in candidates if src.exists()]
    for src, name in (
        (data / "diagnostics" / "official_check" / "report.json", "official_check_report.json"),
        (data / "diagnostics" / "placeholders" / "catalog.csv", "placeholders/catalog.csv"),
        (data / "diagnostics" / "placeholders" / "placeholder_descriptions.yaml", "placeholders/placeholder_descriptions.yaml"),
    ):
        if src.exists():
            out.append((src, name))
    return out


def build_extras_zip(project: ProjectConfig, output_path: Path | None = None) -> Path:
    output_path = output_path or (project.output_dir / "extras.zip")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, name in extras_entries(project):
            zf.write(src, name)
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


# v2.4 fixed colour sets (either pair is legal): red FF0000 or D32F2F,
# yellow FFFF00 or D99A00, black 000000. Theme/indexed colours are not
# allowed (their RGB depends on the viewer). FIX_PLAN validator item.
_RED_RGB = frozenset({"FF0000", "D32F2F"})
_YELLOW_RGB = frozenset({"FFFF00", "D99A00"})
_BLACK_RGB = frozenset({"000000"})


def _colour_kind(color: Any) -> str:
    """'error' | 'warn' | 'black' | 'invalid' for one rich-text font colour."""
    if color is None:
        return "black"
    rgb = getattr(color, "rgb", color)
    if getattr(color, "type", "rgb") not in (None, "rgb") or not isinstance(rgb, str):
        return "invalid"
    hex6 = rgb[-6:].upper()
    if hex6 in _RED_RGB:
        return "error"
    if hex6 in _YELLOW_RGB:
        return "warn"
    if hex6 in _BLACK_RGB:
        return "black"
    return "invalid"


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
                bad: list[list[int]] = []
                cursor = 0
                for block in value:
                    text = block.text if hasattr(block, "text") else str(block)
                    color = None
                    if hasattr(block, "font") and block.font is not None:
                        color = block.font.color
                    kind = _colour_kind(color)
                    if kind in {"error", "warn"}:
                        spans.append([cursor, cursor + len(text), kind])
                    elif kind == "invalid" and text.strip():
                        bad.append([cursor, cursor + len(text)])
                    cursor += len(text)
                record[column] = {"text": str(value), "spans": spans, "invalid_colours": bad}
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
    allow_empty_labels: bool = False,
) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    if not book_dir.exists():
        return [PackageIssue("MISSING_BOOK_DIR", f"missing {book_dir}", path=str(book_dir))]
    expected_pdf = book_dir / f"{book.book_name}.pdf"
    if not expected_pdf.exists():
        issues.append(PackageIssue("MISSING_PDF", "source PDF missing", path=str(expected_pdf)))
    # The guideline requires <Book>_updated.pdf whenever any image changed
    # (rotated pages). Enforced as an error gate, not a courtesy copy.
    try:
        from .updated_pdf import check_updated_pdf, load_pages_readonly

        pages_ro = load_pages_readonly(project, book.book_id)
        if pages_ro is None:
            issues.append(
                PackageIssue(
                    "STATE_UNAVAILABLE",
                    "state.sqlite3 missing/unreadable; _updated.pdf checks skipped",
                    severity="warning",
                )
            )
        else:
            issues.extend(check_updated_pdf(project, book, book_dir, pages_ro))
    except Exception as exc:  # noqa: BLE001
        issues.append(
            PackageIssue("UPDATED_PDF_CHECK_FAILED", str(exc), severity="warning")
        )
    csv_path = book_dir / f"{book.book_name}.csv"
    xlsx_path = book_dir / f"{book.book_name}.xlsx"
    if not csv_path.exists():
        issues.append(PackageIssue("MISSING_CSV", "CSV missing", path=str(csv_path)))
    if not xlsx_path.exists():
        issues.append(PackageIssue("MISSING_XLSX", "XLSX missing", path=str(xlsx_path)))
    if not (book_dir / f"{book.book_name}_image_map.json").exists():
        # Guideline v2.1: <Tên sách>_image_map.json is optional. Emit a warning
        # only; a missing optional file must not block packaging.
        issues.append(PackageIssue("MISSING_IMAGE_MAP", "image_map.json missing (optional per guideline v2.1)", severity="warning"))
    # Promote present-but-invalid maps to errors up front: coverage, order,
    # duplicate/unknown names and the printed-marker formula are all checked
    # against the actual folder contents, not just the map's internal shape.
    if (book_dir / f"{book.book_name}_image_map.json").exists():
        try:
            from .t1_map import load_image_map as _load_map, validate_image_map as _validate_map

            img_map_pairs = _load_map(book_dir / f"{book.book_name}_image_map.json")
            ch_names = {p.name for p in (book_dir / "ch").glob("*.jpg")} if (book_dir / "ch").exists() else set()
            vi_names = {p.name for p in (book_dir / "vi").glob("*.jpg")} if (book_dir / "vi").exists() else set()
            missing_ch = (
                {p.name for p in (book_dir / "missing" / "ch").glob("*.jpg")}
                if (book_dir / "missing" / "ch").exists()
                else set()
            )
            missing_vi = (
                {p.name for p in (book_dir / "missing" / "vi").glob("*.jpg")}
                if (book_dir / "missing" / "vi").exists()
                else set()
            )
            for msg in _validate_map(
                img_map_pairs,
                ch_names=ch_names | missing_ch,
                vi_names=vi_names | missing_vi,
                vi_to_nom_offset=getattr(book, "vi_to_nom_offset", None),
            ):
                issues.append(PackageIssue("IMAGE_MAP_INVALID", msg, path=str(book_dir)))
            # Label.txt <-> CSV SYNC, official normalisation (FIX_PLAN T1.4): blocking.
            if csv_path.exists() and (book_dir / "ch" / "Label.txt").exists():
                from .sync_check import check_book_dir

                for msg in check_book_dir(book_dir, csv_path, img_map_pairs):
                    issues.append(PackageIssue("SYNC", msg, path=str(book_dir)))
        except Exception as exc:  # noqa: BLE001
            issues.append(PackageIssue("IMAGE_MAP_INVALID", str(exc), path=str(book_dir)))

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
            if not allow_empty_labels and (folder_dir / "Label.txt").exists():
                empty_images = 0
                try:
                    from .labels import read_label_txt

                    rows = read_label_txt(folder_dir / "Label.txt")
                    empty_images = sum(1 for boxes in rows.values() if not boxes)
                except ValueError:
                    # Already reported as LABEL_INVALID above.
                    pass
                if empty_images:
                    issues.append(
                        PackageIssue(
                            "EMPTY_LABELS",
                            f"{folder}/Label.txt: {empty_images} images have no boxes; "
                            "re-run OCR + labels, or pass --allow-empty-labels to ship an "
                            "explicitly incomplete book",
                            path=str(folder_dir / "Label.txt"),
                        )
                    )

    # v2.4: intro/ref/toc are optional, but a shipped folder needs both files.
    for folder in ("intro", "ref", "toc"):
        folder_dir = book_dir / folder
        if folder_dir.exists() and any(folder_dir.glob("*.jpg")):
            for name in ("Label.txt", "fileState.txt"):
                if not (folder_dir / name).exists():
                    issues.append(PackageIssue("OPTIONAL_FOLDER_INCOMPLETE", f"{folder}/{name} missing", path=str(folder_dir)))
    # v2.4 missing/: a Nôm page whose QN page was lost lives in ch/ AND
    # missing/ch; a QN page whose Nôm page was lost lives only in missing/vi;
    # missing/ never carries Label.txt / fileState.txt; every lost image is
    # referenced by the image map.
    missing_dir = book_dir / "missing"
    if missing_dir.exists():
        map_names: set[str] = set()
        map_file = book_dir / f"{book.book_name}_image_map.json"
        if map_file.exists():
            try:
                for pair in json.loads(map_file.read_text(encoding="utf-8")).get("pairs", []):
                    map_names.update(pair.get("ch", []) + pair.get("vi", []))
            except (OSError, ValueError, AttributeError):
                pass
        for side in ("ch", "vi"):
            side_dir = missing_dir / side
            if not side_dir.exists():
                continue
            for name in ("Label.txt", "fileState.txt"):
                if (side_dir / name).exists():
                    issues.append(PackageIssue("MISSING_HAS_LABELS", f"missing/{side}/{name}", path=str(side_dir)))
            for img in sorted(side_dir.glob("*.jpg")):
                in_main = (book_dir / side / img.name).exists()
                if side == "ch" and not in_main:
                    issues.append(PackageIssue("MISSING_CH_NOT_IN_CH", img.name, path=str(side_dir)))
                if side == "vi" and in_main:
                    issues.append(PackageIssue("MISSING_VI_ALSO_IN_VI", img.name, path=str(side_dir)))
                if map_names and img.name not in map_names:
                    issues.append(PackageIssue("MISSING_NOT_IN_IMAGE_MAP", img.name, path=str(side_dir)))

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
            # v2.4 row rules the instructors' checker enforces (FIX_PLAN validator item).
            if bool(row.ch_txt.strip()) != bool(row.vi_txt.strip()):
                issues.append(PackageIssue("CSV_ONE_SIDED_ROW", row.sentence_id, path=str(csv_path)))
            for label, cell in (("ch_txt", row.ch_txt), ("vi_txt", row.vi_txt)):
                if unicodedata.normalize("NFC", cell) != cell:
                    issues.append(PackageIssue("CSV_NOT_NFC", f"{row.sentence_id} {label}", path=str(csv_path)))
                if any(0xFE00 <= ord(c) <= 0xFE0F or 0xE0100 <= ord(c) <= 0xE01EF for c in cell):
                    issues.append(PackageIssue("CSV_VARIATION_SELECTOR", f"{row.sentence_id} {label}", path=str(csv_path)))
            if "TEXT_DIFF_EMPTY_CELL" in row.flags:
                issues.append(PackageIssue("CSV_TEXT_DIFF_EMPTY", row.sentence_id, path=str(csv_path)))
            for element in row.text_diff or []:
                if element.type == "warn" and element.suggest is not None:
                    issues.append(
                        PackageIssue("CSV_SUGGEST_PENDING", f"{row.sentence_id}: {element.nom_sub_text}", path=str(csv_path))
                    )
                if element.type == "warn" and element.reviewed != 1:
                    issues.append(
                        PackageIssue("CSV_WARN_UNREVIEWED", f"{row.sentence_id}: {element.nom_sub_text}",
                                     path=str(csv_path), severity="warning")
                    )
            from .textdiff import validate_text_diff

            for problem in validate_text_diff(row.ch_txt, row.vi_txt, row.text_diff):
                issues.append(PackageIssue("CSV_TEXT_DIFF", f"{row.sentence_id}: {problem}", path=str(csv_path)))
        if minimum_similarity is not None:
            from .evaluate import evaluate_rows
            from .orchestrator import load_rows_for_evaluation

            try:
                gate_rows, gate_issues, _audit = load_rows_for_evaluation(project, book)
            except Exception as exc:  # noqa: BLE001
                gate_rows, gate_issues = [], [f"METADATA_LOAD_ERROR:{exc}"]
            metrics = evaluate_rows(
                book.book_id,
                gate_rows,
                minimum_similarity=minimum_similarity,
                integrity_issues=gate_issues,
            )
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
                    if isinstance(cell, dict) and cell.get("invalid_colours"):
                        issues.append(
                            PackageIssue(
                                "XLSX_COLOUR_INVALID",
                                f"{csv_row.sentence_id} column {column}: colour outside 000000/FF0000/FFFF00 "
                                f"or D32F2F/D99A00 (theme colours are not allowed)",
                                path=str(xlsx_path),
                            )
                        )
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
            base = Path(name).name
            if (
                base in forbidden_names
                or (base.startswith(".env") and base != ".env.example")
                or ".sqlite3" in base  # state.sqlite3 and its .bak-* copies
                or base.lower() == "hannom_api.md"  # plaintext account credentials
            ):
                issues.append(PackageIssue("SOURCE_CONTAINS_SECRET_OR_STATE", name, path=str(path)))
            if name.lower().endswith(".pdf"):
                issues.append(PackageIssue("SOURCE_CONTAINS_PDF", name, path=str(path)))
        for required in ("README.md", "USER_GUIDE.md", "pyproject.toml"):
            if required not in names:
                issues.append(PackageIssue("SOURCE_MISSING", required, path=str(path)))
        for name in names:
            if not name.lower().endswith((".py", ".md", ".toml", ".yaml", ".yml", ".txt", ".example", ".json", ".cfg", ".ini")):
                continue
            try:
                text = zf.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            if "KIMHANNOM_TOKEN=" in text:
                value = text.split("KIMHANNOM_TOKEN=", 1)[1].splitlines()[0].strip()
                # Placeholders (<token>, <...>) and this validator's own
                # source code are not secrets.
                if value and not value.startswith("<") and "package.py" not in name:
                    issues.append(PackageIssue("SOURCE_CONTAINS_TOKEN", name, path=str(path)))
            import re as _re

            if _re.search(r"Bearer\s+[A-Za-z0-9._\-]{20,}", text) and "package.py" not in name:
                issues.append(PackageIssue("SOURCE_CONTAINS_TOKEN", f"{name}: bearer token", path=str(path)))
    return issues
