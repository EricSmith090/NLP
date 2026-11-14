"""Gate for the guideline-required ``<BookName>_updated.pdf``.

The guideline mandates submitting the orientation-corrected merged PDF when
any image changed (rotated pages). The technical chain exists (extract ->
rebuild -> merge) but nothing enforced it at package time; this module is
the enforcement hook used by ``validate_book_package``.

Checks, given the state rows (page_no, rotation, sha256):
- any page with rotation != 0 -> ``<book_dir>/<BookName>_updated.pdf`` required;
- it must open, have ``expected_pages`` pages, exactly one image per page;
- each embedded image's bytes must hash to the state ``sha256`` for that page;
- the copied file must match the staged build (``output_dir``) and, when a
  manifest exists under ``artifacts/updated_pdf/``, its ``output_pdf_sha256``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

import pymupdf

from .intake import sha256_file
from .package import PackageIssue


def load_pages_readonly(project, book_id: str) -> list[SimpleNamespace] | None:
    """Stage-1 fields straight from the DB, opened read-only.

    Returns None when the DB is missing/unreadable so packaging can warn
    instead of producing false failures.
    """
    db = Path(project.data_dir) / "state.sqlite3"
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT page_no, rotation, sha256 FROM pages WHERE book_id=? ORDER BY page_no",
                (book_id,),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return [SimpleNamespace(page_no=r[0], rotation=r[1], sha256=r[2]) for r in rows]


def rotated_pages_note(rotated: Sequence[SimpleNamespace]) -> str:
    listing = ", ".join(str(p.page_no) for p in rotated[:12])
    if len(rotated) > 12:
        listing += ", …"
    return f"{len(rotated)} rotated pages ({listing})"


def check_updated_pdf(project, book, book_dir: Path, pages) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    rotated = [p for p in pages if int(p.rotation or 0) != 0]
    if not rotated:
        return issues
    staged = (
        project.output_dir / book.book_id / book.book_name / f"{book.book_name}_updated.pdf"
    )
    updated = book_dir / f"{book.book_name}_updated.pdf"
    if not updated.exists():
        issues.append(
            PackageIssue(
                "MISSING_UPDATED_PDF",
                f"{rotated_pages_note(rotated)} require {updated.name} "
                "(rebuild with `python tools/build_updated_pdf.py --all`)",
                path=str(updated),
            )
        )
    else:
        issues.extend(_verify_updated_pdf_bytes(updated, book, pages, rotated))
    if staged.exists() and updated.exists() and sha256_file(staged) != sha256_file(updated):
        issues.append(
            PackageIssue(
                "STALE_UPDATED_PDF",
                "book-folder _updated.pdf differs from the staged build",
                path=str(updated),
            )
        )
    manifest = (
        project.artifacts_dir / "updated_pdf" / f"{book.book_id}_updated_pdf_manifest.json"
    )
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            expected = data.get("output_pdf_sha256")
            for label, candidate in (("staged", staged), ("copied", updated)):
                if candidate.exists() and expected and sha256_file(candidate) != expected:
                    issues.append(
                        PackageIssue(
                            "STALE_UPDATED_PDF",
                            f"{label} _updated.pdf sha256 != manifest output_pdf_sha256",
                            path=str(candidate),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            issues.append(
                PackageIssue(
                    "UPDATED_PDF_MANIFEST_UNREADABLE",
                    str(exc),
                    path=str(manifest),
                    severity="warning",
                )
            )
    else:
        issues.append(
            PackageIssue(
                "UPDATED_PDF_MANIFEST_MISSING",
                "no updated-pdf manifest in artifacts/updated_pdf; "
                "rebuild with `python tools/build_updated_pdf.py --all`",
                severity="warning",
            )
        )
    return issues


def _verify_updated_pdf_bytes(updated: Path, book, pages, rotated) -> list[PackageIssue]:
    issues: list[PackageIssue] = []
    try:
        doc = pymupdf.open(updated)
    except Exception as exc:  # noqa: BLE001
        return [PackageIssue("UPDATED_PDF_UNREADABLE", str(exc), path=str(updated))]
    try:
        if doc.page_count != book.expected_pages:
            issues.append(
                PackageIssue(
                    "STALE_UPDATED_PDF",
                    f"page_count {doc.page_count} != expected {book.expected_pages}",
                    path=str(updated),
                )
            )
        by_page = {p.page_no: p for p in pages}
        for i in range(min(doc.page_count, book.expected_pages)):
            page = doc[i]
            infos = page.get_image_info(xrefs=True)
            if len(infos) != 1:
                issues.append(
                    PackageIssue(
                        "STALE_UPDATED_PDF",
                        f"page {i + 1}: {len(infos)} images (expected exactly 1)",
                        path=str(updated),
                    )
                )
                continue
            xref = int(infos[0].get("xref") or 0)
            if xref <= 0:
                issues.append(
                    PackageIssue(
                        "STALE_UPDATED_PDF",
                        f"page {i + 1}: image xref missing",
                        path=str(updated),
                    )
                )
                continue
            extracted = doc.extract_image(xref) or {}
            raw = extracted.get("image") or b""
            digest = hashlib.sha256(raw).hexdigest()
            expected = by_page.get(i + 1)
            if expected is not None and digest != expected.sha256:
                issues.append(
                    PackageIssue(
                        "STALE_UPDATED_PDF",
                        f"page {i + 1}: embedded image bytes != state sha256",
                        path=str(updated),
                    )
                )
    finally:
        doc.close()
    return issues
