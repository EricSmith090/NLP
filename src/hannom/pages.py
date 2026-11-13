"""Stage 1: extract one native-resolution JPEG per PDF page.

Two pitfalls are handled explicitly:
1. A PDF page can share an image resource dictionary with every other page
   (Book 3 does this). Taking the first xref from get_images() returns the
   cover for every page. We use get_image_info(), which reports the image
   actually placed on that page. The fast xrefs=False variant carries no
   xref for the scans in this project (verified 0/950 pages), so the
   xref-aware variant is called unconditionally; for these books it is the
   mandatory path, not a rare fallback.
2. A page may rotate or composite an image. A single embedded image is
   rotated geometrically at native resolution (90-degree transpose, JPEG
   re-encode q95, no resampling; not a DCT-domain lossless transform);
   only composite or transformed placements are rendered, and rendering is
   capped at the native scan size so nothing is upscaled.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from dataclasses import asdict, replace
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
    # The fast get_image_info() never carries an xref for the scanned books
    # in this project (0/950 pages), so the xref-aware variant is always
    # used; it costs ~1 s/page but is the only path that resolves the
    # placed image to an extractable stream.
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
    # Sign-flipped scale encodes a flip (e.g. a<0/d<0 for 180-degree flips
    # with b == c == 0); those pages must not be served from the verbatim
    # path, otherwise the submitted image displays upside-down.
    return abs(b) > 1e-3 or abs(c) > 1e-3 or a < -1e-3 or d < -1e-3


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
        if im.mode not in {"RGB", "L"}:
            im = im.convert("RGB")
        # A geometric 90-degree transpose re-quantizes the JPEG (q95,
        # 4:4:4, no resampling, native resolution kept). It is not a
        # DCT-domain lossless transform.
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
        # No full-page candidate: cap the render at the largest placed
        # image's pixel width so a small placed image is never upscaled.
        # Falls back to the ~144 dpi floor only when no image exists.
        infos = _placed_image_info(page)
        largest = max((int(i.get("width") or 0) for i in infos), default=0)
        fallback = max(page.rect.width * 2.0, 1600.0)
        target_width = min(fallback, float(largest)) if largest > 0 else fallback
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

    # Validate the PDF *before* any destructive step: open it, check the
    # page count, and touch page 1 before --force deletes anything.
    try:
        doc = pymupdf.open(book.pdf)
    except Exception as exc:  # noqa: BLE001 - pymupdf raises many exception types
        raise PageExtractionError(f"Cannot open assigned PDF {book.pdf}: {exc}") from exc

    out_dir = project.data_dir / "pages" / book.book_id / "native"
    records: list[PageRecord] = []
    try:
        if doc.page_count != book.expected_pages:
            raise PageExtractionError(
                f"{book.book_id}: expected {book.expected_pages}, got {doc.page_count}"
            )
        _ = doc[0]  # first page must decode before any deletion
        if force and out_dir.exists():
            # Back up the state database before destroying native images.
            if state.path.exists():
                state.backup("extract-force")
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for page_no in range(1, doc.page_count + 1):
            dest = out_dir / image_name(book.book_name, page_no)
            digest: str | None = None
            if dest.exists() and not force:
                with Image.open(dest) as im:
                    width, height = im.size
                rotation = int(doc[page_no - 1].rotation or 0)
                digest = sha256_file(dest)
                old = state.page(book.book_id, page_no)
                if old is not None and old.sha256 == digest:
                    # The file is unchanged: refresh only Stage-1 columns
                    # so downstream state (status/OCR/flags/features) is
                    # preserved instead of being reset to Stage-1 defaults.
                    method = old.extraction_method or "existing"
                    state.stage1_update(
                        book.book_id,
                        page_no,
                        image_name=dest.name,
                        pdf_page=page_no,
                        sha256=digest,
                        width=width,
                        height=height,
                        path=dest,
                        extraction_method=method,
                        rotation=rotation,
                    )
                    records.append(
                        replace(
                            old,
                            width=width,
                            height=height,
                            path=dest,
                            extraction_method=method,
                            rotation=rotation,
                            sha256=digest,
                            image_name=dest.name,
                        )
                    )
                    continue
                method = "existing"
            else:
                width, height, method, rotation = extract_page(doc, page_no, dest)
            if digest is None:
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
    # Content-hash the decoded pixels so an identical scan extracted
    # verbatim on one page and re-encoded after a 90-degree transpose on
    # another is still flagged.
    by_hash: dict[str, list[int]] = {}
    for record in records:
        with Image.open(record.path) as im:
            content = hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()
        by_hash.setdefault(content, []).append(record.page_no)
    duplicates = {h: pages for h, pages in by_hash.items() if len(pages) > 1}
    by_page = {r.page_no: r for r in records}
    for pages in duplicates.values():
        for page_no in pages:
            record = by_page[page_no]
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
        sha256=sha256_file(manifest_path),
        meta={
            "page_count": len(records),
            "duplicate_hash_groups": len(duplicates),
            "native_size": sorted({(r.width, r.height) for r in records}),
        },
    )
    return records
