"""Stage 0: intake and scope lock.

No mass OCR is allowed before the book identity, page count, layout, and
source paths are recorded. The source PDF is never modified.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from .config import BookConfig, ProjectConfig
from .state import State


class IntakeError(RuntimeError):
    pass


@dataclass
class PdfInspection:
    path: Path
    sha256: str
    size_bytes: int
    page_count: int
    text_chars: list[int]
    image_counts: list[int]
    page_sizes: list[tuple[float, float]]
    image_only: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "page_count": self.page_count,
            "text_chars_total": sum(self.text_chars),
            "image_only": self.image_only,
            "text_chars_by_page": self.text_chars,
            "image_counts_by_page": self.image_counts,
            "page_sizes": [list(x) for x in self.page_sizes],
        }


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_pdf(path: str | Path) -> PdfInspection:
    path = Path(path)
    if not path.exists():
        raise IntakeError(f"Assigned PDF not found: {path}")
    doc = pymupdf.open(path)
    try:
        text_chars = [len(page.get_text("text").strip()) for page in doc]
        # xrefs=False reads placed-image info from the display list and is
        # effectively instant. xrefs=True re-parses every image resource
        # and costs ~1 s/page on scanned books (minutes across a book).
        image_counts = [len(page.get_image_info()) for page in doc]
        page_sizes = [(float(page.rect.width), float(page.rect.height)) for page in doc]
        return PdfInspection(
            path=path,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            page_count=doc.page_count,
            text_chars=text_chars,
            image_counts=image_counts,
            page_sizes=page_sizes,
            image_only=sum(text_chars) == 0,
        )
    finally:
        doc.close()


def _link_or_copy(src: Path, dst: Path, *, expected_sha: str | None = None) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if not dst.is_file():
            raise IntakeError(f"raw copy path is not a regular file: {dst}")
        if expected_sha is not None and sha256_file(dst) != expected_sha:
            raise IntakeError(
                f"raw copy diverged from the assigned PDF: {dst} "
                f"(sha256 mismatch; assigned sha256 {expected_sha}); "
                "refusing to proceed — reconcile or replace the raw archive manually"
            )
        return "existing"
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def lock_scope(project: ProjectConfig, book: BookConfig, state: State) -> dict[str, Any]:
    """Record the immutable intake facts and refuse mismatched scope."""
    inspection = inspect_pdf(book.pdf)
    if inspection.page_count != book.expected_pages:
        raise IntakeError(
            f"{book.book_id}: expected {book.expected_pages} pages, found {inspection.page_count}"
        )
    if not inspection.image_only:
        raise IntakeError(
            f"{book.book_id}: expected image-only PDF; text layer found "
            f"({sum(inspection.text_chars)} chars)"
        )
    if book.layout.upper() != "T1":
        raise IntakeError(f"{book.book_id}: this harness is configured for T1, got {book.layout}")
    if book.scope != "all":
        raise IntakeError(
            f"{book.book_id}: partial scope '{book.scope}' is not supported by this runner; "
            "the assigned scope is all pages"
        )

    raw_dir = project.data_dir / "raw" / book.book_id
    raw_pdf = raw_dir / "original.pdf"
    link_kind = _link_or_copy(book.pdf, raw_pdf, expected_sha=inspection.sha256)
    # Preserve first-run link semantics across re-runs: a re-run must not
    # overwrite "hardlink"/"copy" with "existing" (the archive semantics are
    # the audit trail for how the ground-truth raw copy was produced).
    manifest_path = raw_dir / "manifest.json"
    previous_raw_link = None
    if manifest_path.exists():
        try:
            previous_raw_link = (read_json(manifest_path) or {}).get("raw_link")
        except Exception:  # noqa: BLE001 - a corrupt manifest must not block intake
            previous_raw_link = None
    first_run_link = (
        previous_raw_link if previous_raw_link in {"hardlink", "copy"} else link_kind
    )
    raw_link = (
        first_run_link
        if link_kind == "existing" and previous_raw_link in {"hardlink", "copy"}
        else link_kind
    )
    manifest = {
        "book_id": book.book_id,
        "book_name": book.book_name,
        "assigned_pdf": str(book.pdf),
        "assigned_pdf_name": book.pdf.name,
        "raw_pdf": str(raw_pdf),
        "raw_link": raw_link,
        "raw_link_first_seen": first_run_link,
        "inspection": inspection.to_dict(),
        "layout": book.layout,
        "scope": book.scope,
        "front_matter_end": book.front_matter_end,
        "translation_start": book.translation_start,
        "translation_end": book.translation_end,
        "nom_start_hint": book.nom_start_hint,
        "nom_end_hint": book.nom_end_hint,
    }
    dest = manifest_path
    write_json(dest, manifest)
    state.set_artifact(
        book.book_id,
        "intake",
        "manifest",
        dest,
        sha256=inspection.sha256,
        meta={"page_count": inspection.page_count, "image_only": inspection.image_only},
    )
    return manifest


def write_json(path: str | Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)
