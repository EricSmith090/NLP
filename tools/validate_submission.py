"""Validate a submission ZIP or an unpacked submission directory.

This mirrors the acceptance checklist in Doc/PROJECT_PLAN.md §9. Exit code
is non-zero on any blocking issue.

Usage:
    python tools/validate_submission.py path/to/submission.zip
    python tools/validate_submission.py data/output --project configs/project.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hannom.align import read_alignment_csv  # noqa: E402
from hannom.config import load_config  # noqa: E402
from hannom.package import (  # noqa: E402
    PackageIssue,
    validate_book_package,
    validate_source_zip,
)

IMAGE_RE = re.compile(r"^(?P<stem>.+)\.(?P<page>\d{3,})(?:_(?P<index>\d+))?\.jpg$")


def _issues_for_zip_layout(zip_path: Path, book_names: set[str]) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if len(names) != len(set(names)):
            issues.append(PackageIssue("ZIP_DUPLICATE_ENTRY", "ZIP contains duplicate paths"))
        for name in names:
            normalized = Path(name)
            if name.startswith("/") or ".." in normalized.parts:
                issues.append(PackageIssue("ZIP_PATH_TRAVERSAL", name))
            parts = set(normalized.parts)
            if parts & {"data", "models", "artifacts", ".git", "CV20-24127189"}:
                issues.append(PackageIssue("ZIP_CONTAINS_WORKING_DATA", name))
            if normalized.name == ".env" or normalized.suffix.lower() == ".sqlite3":
                issues.append(PackageIssue("ZIP_CONTAINS_SECRET_OR_STATE", name))
        top = {name.split("/", 1)[0] for name in names if "/" in name}
        missing = book_names - top
        if missing:
            issues.append(PackageIssue("ZIP_MISSING_BOOKS", f"missing {sorted(missing)}"))
        if not any(name.endswith("_report.pdf") for name in names):
            issues.append(PackageIssue("ZIP_MISSING_REPORT", "no *_report.pdf at ZIP root"))
        if "source.zip" not in names:
            issues.append(PackageIssue("ZIP_MISSING_SOURCE", "source.zip missing at ZIP root"))
    return issues


def _validate_image_order(book_dir: Path) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    map_path = next(book_dir.glob("*_image_map.json"), None)
    if map_path is None:
        return []
    data = json.loads(map_path.read_text(encoding="utf-8"))
    pairs = data.get("pairs", [])
    ch_names: list[str] = []
    vi_names: list[str] = []
    for pair in pairs:
        ch_names.extend(pair.get("ch", []))
        vi_names.extend(pair.get("vi", []))
    if len(ch_names) != len(set(ch_names)):
        issues.append(PackageIssue("IMAGE_MAP_DUPLICATE_CH", "ch name repeated"))
    if len(vi_names) != len(set(vi_names)):
        issues.append(PackageIssue("IMAGE_MAP_DUPLICATE_VI", "vi name repeated"))
    ch_pages = [int(m.group("page")) for name in ch_names if (m := IMAGE_RE.match(name))]
    vi_pages = [int(m.group("page")) for name in vi_names if (m := IMAGE_RE.match(name))]
    if ch_pages != sorted(ch_pages, reverse=True):
        issues.append(PackageIssue("IMAGE_MAP_CH_ORDER", "ch names are not in decreasing page order"))
    if vi_pages != sorted(vi_pages):
        issues.append(PackageIssue("IMAGE_MAP_VI_ORDER", "vi names are not in increasing page order"))
    for side in ("ch", "vi"):
        folder = book_dir / side
        if not folder.exists():
            continue
        actual = {p.name for p in folder.glob("*.jpg")}
        mapped = set(ch_names if side == "ch" else vi_names)
        if actual - mapped:
            issues.append(PackageIssue("IMAGE_MAP_MISSING", f"{side} images not in image_map: {sorted(actual - mapped)[:3]}"))
        if mapped - actual:
            issues.append(PackageIssue("IMAGE_MAP_UNKNOWN", f"image_map {side} names missing from folder: {sorted(mapped - actual)[:3]}"))
    return issues


def _duplicate_hashes(folder: Path) -> list[str]:
    hashes: dict[str, list[str]] = {}
    for path in sorted(folder.glob("*.jpg")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.setdefault(digest, []).append(path.name)
    return [" / ".join(names) for names in hashes.values() if len(names) > 1]


def _validate_book_dir(project, book, book_dir: Path) -> list[PackageIssue]:
    issues = validate_book_package(project, book, book_dir, minimum_similarity=None)
    issues.extend(_validate_image_order(book_dir))
    for side in ("ch", "vi"):
        folder = book_dir / side
        if folder.exists():
            for duplicate in _duplicate_hashes(folder):
                issues.append(PackageIssue("DUPLICATE_IMAGE", f"{side}: {duplicate}", path=str(folder)))
    pdf = book_dir / f"{book.book_name}.pdf"
    if pdf.exists():
        try:
            import pymupdf

            doc = pymupdf.open(pdf)
            if doc.page_count != book.expected_pages:
                issues.append(
                    PackageIssue(
                        "PDF_PAGE_COUNT",
                        f"{book.book_name}.pdf has {doc.page_count}, expected {book.expected_pages}",
                        path=str(pdf),
                    )
                )
            doc.close()
        except Exception as exc:  # noqa: BLE001
            issues.append(PackageIssue("PDF_UNREADABLE", str(exc), path=str(pdf)))
    csv = book_dir / f"{book.book_name}.csv"
    if csv.exists():
        raw = csv.read_bytes()
        if not raw.startswith(b"\xef\xbb\xbf"):
            issues.append(PackageIssue("CSV_NO_BOM", "CSV should be UTF-8 with BOM", path=str(csv)))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="submission ZIP or directory containing book folders")
    parser.add_argument("--project", default=str(ROOT / "configs" / "project.yaml"))
    parser.add_argument("--keep-extracted", action="store_true")
    args = parser.parse_args(argv)

    project = load_config(args.project)
    target = Path(args.target).resolve()
    if not target.exists():
        print(f"ERROR: target not found: {target}", file=sys.stderr)
        return 2
    issues: list[PackageIssue] = []
    temp_dir: Path | None = None
    try:
        if target.is_file() and target.suffix.lower() == ".zip":
            issues.extend(_issues_for_zip_layout(target, {b.book_name for b in project.books}))
            temp_dir = Path(tempfile.mkdtemp(prefix="hannom_validate_"))
            with zipfile.ZipFile(target) as zf:
                zf.extractall(temp_dir)
            root = temp_dir
            source_zip = root / "source.zip"
            if source_zip.exists():
                issues.extend(validate_source_zip(source_zip))
        else:
            root = target
        for book in project.books:
            book_dir = root / book.book_name
            if not book_dir.exists():
                issues.append(PackageIssue("MISSING_BOOK", book.book_name, path=str(book_dir)))
                continue
            issues.extend(_validate_book_dir(project, book, book_dir))
    finally:
        if temp_dir and not args.keep_extracted:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if issues:
        print(f"FAIL: {len(issues)} blocking issue(s)")
        for issue in issues:
            print(f"  [{issue.code}] {issue.message}" + (f" ({issue.path})" if issue.path else ""))
        return 1
    print("PASS: submission satisfies structural checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
