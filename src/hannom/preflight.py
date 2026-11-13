"""Pre-hand-in image preflight: decode, names, and per-book accounting.

Implements the blocking gate from Doc/PROJECT_PLAN.md §9 that previously
existed only on paper: every PDF page accounted for exactly once, every
image decodable, no non-.jpg files in image folders, and (when a state
SHA map is supplied) bytes matching the state layer.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image

from .intake import sha256_file
from .package import PackageIssue

IMAGE_RE = re.compile(r"^(?P<stem>.+)\.(?P<page>\d{3,})(?:_(?P<index>\d+))?\.jpg$")
FOLDER_NAMES = ("ch", "vi", "intro", "ref", "toc", "blank", "misc")
# Label files that legitimately live inside ch/vi image folders (guideline).
ALLOWED_LABEL_FILES = {"label.txt", "filestate.txt", "label_char.txt", "filestate_char.txt"}


def image_folders(book_dir: Path) -> list[Path]:
    folders = [book_dir / name for name in FOLDER_NAMES]
    folders.append(book_dir / "missing" / "ch")
    folders.append(book_dir / "missing" / "vi")
    return [f for f in folders]


def folder_kind(folder: Path) -> str:
    parent = folder.parent.name
    if parent == "missing":
        return f"missing_{folder.name}"
    return folder.name


def page_no_from_name(name: str) -> int | None:
    m = IMAGE_RE.match(name)
    return int(m.group("page")) if m else None


def check_book_images(
    book_dir: Path,
    book_name: str,
    expected_pages: int,
    *,
    sha_by_image: dict[str, str] | None = None,
    dims_by_image: dict[str, tuple[int, int]] | None = None,
    flat: bool = False,
) -> list[PackageIssue]:
    """Sweep a packaged (or native) book folder for image-layer defects.

    - every file in image folders decodes as JPEG and is named per the
      guideline regex;
    - no non-.jpg files anywhere in image folders;
    - union of page numbers across all image folders covers 1..expected
      exactly (ch/ + missing/ch/ double placement is allowed and expected;
      missing/vi pages must not also appear in vi/);
    - optional sha256/dimension match against the state layer.
    """
    issues: list[PackageIssue] = []
    stem = re.escape(book_name)
    name_re = re.compile(rf"^{stem}\.\d{{3,}}(_\d+)?\.jpg$")
    union: set[int] = set()
    ch_pages: set[int] = set()
    missing_ch_pages: set[int] = set()
    vi_pages: set[int] = set()
    missing_vi_pages: set[int] = set()

    folders = [("all" if flat else None, book_dir)] if flat else [(folder_kind(f), f) for f in image_folders(book_dir)]
    for kind, folder in folders:
        if kind is None:
            kind = folder_kind(folder)
        if not folder.exists():
            continue
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() != ".jpg":
                # missing/ folders must not carry Label.txt/fileState.txt;
                # flat (native) dirs carry no labels either; elsewhere those
                # (and only those) label files are allowed.
                if not flat and not kind.startswith("missing") and p.name.lower() in ALLOWED_LABEL_FILES:
                    continue
                issues.append(
                    PackageIssue(
                        "NON_JPG_FILE",
                        f"{p} is not a .jpg file (images must be JPEG only)",
                        path=str(p),
                    )
                )
                continue
            try:
                with Image.open(p) as im:
                    im.verify()
                with Image.open(p) as im:
                    im.load()
                    size = (im.width, im.height)
            except Exception as exc:  # noqa: BLE001
                issues.append(PackageIssue("JPEG_UNDECODABLE", f"{p.name}: {exc}", path=str(p)))
                continue
            page = page_no_from_name(p.name)
            if page is None or not name_re.match(p.name):
                issues.append(
                    PackageIssue(
                        "BAD_IMAGE_NAME",
                        f"{p.name} does not match <Tên sách>.NNN[_i].jpg",
                        path=str(p),
                    )
                )
                continue
            if sha_by_image is not None:
                expected_sha = sha_by_image.get(p.name)
                if expected_sha is None:
                    issues.append(
                        PackageIssue(
                            "IMAGE_NOT_IN_STATE",
                            f"{p.name} has no matching row in the state DB",
                            path=str(p),
                        )
                    )
                elif sha256_file(p) != expected_sha:
                    issues.append(
                        PackageIssue(
                            "IMAGE_SHA_MISMATCH",
                            f"{p.name} sha256 differs from state",
                            path=str(p),
                        )
                    )
            if dims_by_image is not None:
                expected_dims = dims_by_image.get(p.name)
                if expected_dims is not None and tuple(expected_dims) != size:
                    issues.append(
                        PackageIssue(
                            "IMAGE_DIMS_MISMATCH",
                            f"{p.name} is {size[0]}x{size[1]}, state says "
                            f"{expected_dims[0]}x{expected_dims[1]}",
                            path=str(p),
                        )
                    )
            union.add(page)
            if kind == "ch":
                ch_pages.add(page)
            elif kind == "missing_ch":
                missing_ch_pages.add(page)
            elif kind == "vi":
                vi_pages.add(page)
            elif kind == "missing_vi":
                missing_vi_pages.add(page)

    expected = set(range(1, expected_pages + 1))
    missing = sorted(expected - union)
    extra = sorted(union - expected)
    if missing:
        issues.append(
            PackageIssue(
                "IMAGES_MISSING_PAGES",
                f"no image for PDF pages: {missing[:20]}{'…' if len(missing) > 20 else ''}",
                path=str(book_dir),
            )
        )
    if extra:
        issues.append(
            PackageIssue(
                "IMAGES_EXTRA_PAGES",
                f"images for out-of-range pages: {extra[:20]}{'…' if len(extra) > 20 else ''}",
                path=str(book_dir),
            )
        )
    for page in sorted(missing_ch_pages - ch_pages):
        issues.append(
            PackageIssue(
                "MISSING_CH_NOT_IN_CH",
                f"missing/ch page {page} is not also present in ch/ "
                "(guideline: Nôm pages lost on the QN side are kept in both)",
                path=str(book_dir),
            )
        )
    overlap = vi_pages & missing_vi_pages
    if overlap:
        issues.append(
            PackageIssue(
                "VI_AND_MISSING_VI",
                f"pages in both vi/ and missing/vi/: {sorted(overlap)[:20]}",
                path=str(book_dir),
            )
        )
    return issues
