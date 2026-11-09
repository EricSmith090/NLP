"""Build ``<BookName>_updated.pdf`` from the extracted, orientation-corrected images.

The extraction stage rotates 90°/180°/270° scans losslessly (transpose, no
resampling) but keeps the source JPEG bytes for everything else. The
Hán Nôm guideline requires that any image change is accompanied by a merged
``<BookName>_updated.pdf`` (one image per page, page order and count of the
assigned PDF) plus a report note and a notification to the handout person.

This tool embeds each extracted JPEG at its native resolution, stretched to
the source page's *displayed* rect (rotation already applied by the PDF), so
the merged file is upright with no upscaling, no duplicates, and one image
per page. Books whose pages were all extracted with rotation == 0 get no
``_updated.pdf`` at all.

The file is staged at ``data/output/<book_id>/<BookName>/<BookName>_updated.pdf``;
``hannom package`` copies it into the final book folder (as the guideline
requires alongside the original PDF); the staging copy is never deleted.

Usage:
    python tools/build_updated_pdf.py --all
    python tools/build_updated_pdf.py --book T1_CamPhong_Tap1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hannom.config import load_config  # noqa: E402
from hannom.state import State  # noqa: E402

TOOL = "tools/build_updated_pdf.py"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_for_book(book_id: str, args) -> int:
    project = load_config(args.project)
    book = project.book(book_id)
    state = State(project.data_dir / "state.sqlite3")
    try:
        pages = sorted(state.pages(book_id), key=lambda p: p.page_no)
        rotations = {p.page_no: int(p.rotation or 0) for p in pages}
    finally:
        state.close()

    changed = {n: r for n, r in rotations.items() if r % 360 != 0}
    book_name = book.book_name
    if not changed:
        print(f"[{book_id}] no page was rotated; no _updated.pdf is required")
        return 0

    source_pdf = book.source_pdf
    if not source_pdf.exists():
        print(f"[{book_id}] ERROR: assigned PDF not found: {source_pdf}", file=sys.stderr)
        return 1

    problems: list[str] = []
    images = [Path(p.path) for p in pages]
    for image in images:
        if not image.exists():
            problems.append(f"missing extracted image: {image}")
    if problems:
        for problem in problems:
            print(f"[{book_id}] ERROR: {problem}", file=sys.stderr)
        return 1

    out_dir = Path(args.output_dir) / book_id / book_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{book_name}_updated.pdf"

    with pymupdf.open(str(source_pdf)) as source:
        if source.page_count != len(pages):
            print(
                f"[{book_id}] ERROR: source PDF has {source.page_count} pages but state has {len(pages)}",
                file=sys.stderr,
            )
            return 1
        document = pymupdf.open()
        for index, page in enumerate(source):
            rect = page.rect  # displayed orientation, /Rotate applied
            new_page = document.new_page(width=rect.width, height=rect.height)
            new_page.insert_image(new_page.rect, filename=str(images[index]))
        document.set_metadata(
            {
                "title": f"{book_name}_updated.pdf",
                "creator": TOOL,
                "producer": f"PyMuPDF {pymupdf.__version__}",
                "creationDate": datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ"),
            }
        )
        document.save(str(out_pdf), deflate=True, garbage=4)
        document.close()

    # Verify the merged file before declaring success.
    with pymupdf.open(str(out_pdf)) as check:
        if check.page_count != len(pages):
            print(f"[{book_id}] ERROR: merged PDF has {check.page_count} pages, expected {len(pages)}", file=sys.stderr)
            return 1
        bad_pages = [n + 1 for n, page in enumerate(check) if len(page.get_images(full=True)) != 1]
        if bad_pages:
            print(f"[{book_id}] ERROR: pages without exactly one image: {bad_pages}", file=sys.stderr)
            return 1

    manifest = {
        "book_id": book_id,
        "book_name": book_name,
        "tool": TOOL,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_pdf": str(source_pdf),
        "source_pdf_sha256": _sha256_file(source_pdf),
        "output_pdf": str(out_pdf),
        "output_pdf_sha256": _sha256_file(out_pdf),
        "page_count": len(pages),
        "pages_rotated": sorted(changed),
        "rotation_values_deg": {str(n): rotations[n] for n in sorted(changed)},
        "notes": (
            "Images embedded at native resolution, stretched to each source page's "
            "displayed rect; one image per page; no resampling; JPEG streams embedded as-is."
        ),
    }
    manifest_dir = Path(args.manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{book_id}_updated_pdf_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[{book_id}] wrote {out_pdf} ({out_pdf.stat().st_size/1024/1024:.1f} MB, "
        f"{len(pages)} pages, rotated {sorted(changed)})"
    )
    print(f"[{book_id}] manifest {manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", action="append", default=None, help="Book config id; repeatable. Default: all books with rotated pages.")
    parser.add_argument("--all", action="store_true", help="Process every book that has rotated pages.")
    parser.add_argument("--project", default=str(ROOT / "configs" / "project.yaml"))
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "output"))
    parser.add_argument("--manifest-dir", default=str(ROOT / "artifacts" / "updated_pdf"))
    args = parser.parse_args(argv)

    project = load_config(args.project)
    candidates = args.book if args.book else [b.book_id for b in project.books]
    status = 0
    for book_id in candidates:
        status |= build_for_book(book_id, args)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
