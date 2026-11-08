"""Stage 1: extract one native-resolution JPEG per PDF page.

Two pitfalls are handled explicitly:
1. A PDF page can share an image resource dictionary with every other page
   (Book 3 does this). Taking the first xref from get_images() returns the
   cover for every page. We use get_image_info(), which reports the image
   actually placed on that page. The xrefs=True variant returns the same
   data but re-parses every image resource (~1 s/page on these scans), so
   it is only a fallback when the fast call omits an xref.
2. A page may rotate or composite an image. A single embedded image is
   rotated losslessly from its native pixels; only composite or
   transformed placements are rendered, and rendering is capped at the
   native scan width so nothing is upscaled.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import pymupdf
from PIL import Image

from .config import BookConfig, ProjectConfig
from .intake import sha256_file
from .models import PageRecord
from .state import State


class PageExtractionError(RuntimeError):
    pass


def page_number_str(page_no: int) -> str:
    """At least three digits; no padding once the book exceeds 999 pages."""
    if page_no < 1:
        raise ValueError("page numbers start at 1")
    return f"{page_no:03d}" if page_no <= 999 else str(page_no)


def image_name(book_name: str, page_no: int, image_index: int | None = None) -> str:
    base = f"{book_name}.{page_number_str(page_no)}"
    if image_index is not None:
        if image_index < 1:
            raise ValueError("image index starts at 1")
        base += f"_{image_index}"
    return base + ".jpg"


def _placed_image_info(page: pymupdf.Page) -> list[dict[str, Any]]:
    infos = page.get_image_info()
    if not infos:
        return []
    if all(int(info.get("xref") or 0) > 0 for info in infos):
        return infos
    # Rare PDFs omit xref in the fast result; pay the slow-path cost only
    # for those pages.
    return page.get_image_info(xrefs=True)


def _image_candidates(page: pymupdf.Page) -> list[dict[str, Any]]:
    page_area = abs(page.rect.width * page.rect.height)
    candidates: list[dict[str, Any]] = []
    for info in _placed_image_info(page):
        x0, y0, x1, y1 = info["bbox"]
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        if page_area <= 0:
            continue
        if area / page_area >= 0.45:
            candidates.append(info)
    return candidates


def _matrix_is_rotated(info: dict[str, Any]) -> bool:
    transform = info.get("transform")
    if not transform:
        return False
    try:
        a, b, c, d, _e, _f = transform
    except (TypeError, ValueError):
        return False
    return abs(b) > 1e-3 or abs(c) > 1e-3


def _save_rgb_jpeg(raw: bytes, dest: Path, rotation: int = 0) -> tuple[int, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(raw)) as im:
        width, height = im.size
        # For an unrotated RGB/grayscale JPEG, copy the embedded stream
        # verbatim. Re-encoding would be a silent generation loss and would
        # weaken the claim that submission images preserve the source scan.
        if int(rotation) % 360 == 0 and im.format == "JPEG" and im.mode in {"RGB", "L"}:
            dest.write_bytes(raw)
            return width, height
        im = im.convert("RGB")
        # Applying a display rotation with a 90-degree transpose is exact:
        # no resampling and no change to the underlying scan resolution.
        transpose = {
            90: Image.Transpose.ROTATE_270,   # PDF /Rotate is clockwise
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }.get(int(rotation) % 360)
        if transpose is not None:
            im = im.transpose(transpose)
        width, height = im.size
        im.save(dest, format="JPEG", quality=95, subsampling=0, optimize=False)
        return width, height


def _render_page(page: pymupdf.Page, dest: Path, target_width: float) -> tuple[int, int]:
    # Allow downscaling: rendered pages must not exceed the requested native
    # width, otherwise a rotated scan silently becomes an upscaled 1067 px
    # page although the source image is only 800 px wide.
    zoom = max(0.05, float(target_width) / max(1.0, page.rect.width))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False, colorspace=pymupdf.csRGB)
    with Image.open(io.BytesIO(pix.tobytes("png"))) as im:
        im = im.convert("RGB")
        width, height = im.size
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest, format="JPEG", quality=95, subsampling=0, optimize=False)
    return width, height


def extract_page(
    doc: pymupdf.Document,
    page_no: int,
    dest: Path,
) -> tuple[int, int, str, int]:
    """Extract PDF page *page_no* (1-based) to *dest*.

    Returns (width, height, method, pdf_rotation).
    """
    page = doc[page_no - 1]
    rotation = int(page.rotation or 0)
    candidates = _image_candidates(page)

    if len(candidates) == 1 and not _matrix_is_rotated(candidates[0]):
        info = candidates[0]
        xref = int(info["xref"])
        extracted = doc.extract_image(xref)
        raw = extracted.get("image")
        if raw:
            # Page /Rotate is part of how the scan must be presented. Apply
            # it to the embedded JPEG instead of rendering the whole page,
            # which would upsample an 800 px scan to the PDF's point size.
            w, h = _save_rgb_jpeg(raw, dest, rotation)
            return w, h, f"embedded:xref={xref}", rotation

    # Composite, rotated, or no single full-page image: render the page.
    if candidates:
        target_width = max(int(c.get("width", 0)) for c in candidates) or page.rect.width
    else:
        target_width = max(page.rect.width * 2.0, 1600.0)  # ~144 dpi fallback
    w, h = _render_page(page, dest, target_width)
    return w, h, "rendered", rotation


def _write_pages_jsonl(path: Path, records: Iterable[PageRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            data = asdict(record)
            data["path"] = str(record.path)
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def read_pages_jsonl(path: str | Path) -> list[PageRecord]:
    records: list[PageRecord] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            d["path"] = Path(d["path"])
            records.append(PageRecord(**d))
    return records


def extract_book(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    force: bool = False,
) -> list[PageRecord]:
    if not book.pdf.exists():
        raise PageExtractionError(f"Assigned PDF not found: {book.pdf}")

    out_dir = project.data_dir / "pages" / book.book_id / "native"
    if force and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(book.pdf)
    records: list[PageRecord] = []
    try:
        if doc.page_count != book.expected_pages:
            raise PageExtractionError(
                f"{book.book_id}: expected {book.expected_pages}, got {doc.page_count}"
            )
        for page_no in range(1, doc.page_count + 1):
            dest = out_dir / image_name(book.book_name, page_no)
            if dest.exists() and not force:
                with Image.open(dest) as im:
                    width, height = im.size
                method = "existing"
                rotation = int(doc[page_no - 1].rotation or 0)
            else:
                width, height, method, rotation = extract_page(doc, page_no, dest)
            digest = sha256_file(dest)
            record = PageRecord(
                book_id=book.book_id,
                page_no=page_no,
                image_name=dest.name,
                pdf_page=page_no,
                sha256=digest,
                width=width,
                height=height,
                path=dest,
                extraction_method=method,
                rotation=rotation,
            )
            state.upsert_page(record)
            records.append(record)
    finally:
        doc.close()

    # Duplicate-image detection is a warning, not an automatic deletion:
    # two blank pages can legitimately look identical after compression.
    by_hash: dict[str, list[int]] = {}
    for record in records:
        by_hash.setdefault(record.sha256, []).append(record.page_no)
    duplicates = {h: pages for h, pages in by_hash.items() if len(pages) > 1}
    for pages in duplicates.values():
        for page_no in pages:
            record = records[page_no - 1]
            if "DUPLICATE_IMAGE" not in record.review_flags:
                record.review_flags.append("DUPLICATE_IMAGE")
            state.update_page(book.book_id, page_no, review_flags=record.review_flags)

    manifest_path = project.data_dir / "pages" / book.book_id / "pages.jsonl"
    _write_pages_jsonl(manifest_path, records)
    state.set_artifact(
        book.book_id,
        "pages",
        "native_jsonl",
        manifest_path,
        meta={
            "page_count": len(records),
            "duplicate_hash_groups": len(duplicates),
            "native_size": [records[0].width, records[0].height] if records else None,
        },
    )
    return records


def duplicate_report(records: list[PageRecord]) -> dict[str, list[int]]:
    by_hash: dict[str, list[int]] = {}
    for record in records:
        by_hash.setdefault(record.sha256, []).append(record.page_no)
    return {h: pages for h, pages in by_hash.items() if len(pages) > 1}
