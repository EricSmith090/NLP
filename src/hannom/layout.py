"""Stage 2: page script/layout classification and T1 section boundaries.

This is deliberately evidence-based and conservative. The classifier uses
projection profiles, column separators, ink density, and page position. It
does not pretend to read the script. Anything ambiguous is flagged for
review rather than silently forced into ch/ or vi/.

Known T1 complication (verified on the assigned books): QN back-matter
tables of contents can appear *after* the Nôm block. Those pages must not be
mapped to Nôm pages or aligned.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import BookConfig, ProjectConfig
from .models import PageRecord
from .state import State


class LayoutError(RuntimeError):
    pass


@dataclass
class PageFeatures:
    width: int
    height: int
    ink_fraction: float
    vertical_lines: int
    horizontal_lines: int
    row_peaks: int
    row_std: float
    column_peaks: int
    column_std: float
    bbox: tuple[float, float, float, float]
    otsu_threshold: int
    nom_likely: bool
    blank_likely: bool
    toc_likely: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "ink_fraction": round(self.ink_fraction, 6),
            "vertical_lines": self.vertical_lines,
            "horizontal_lines": self.horizontal_lines,
            "row_peaks": self.row_peaks,
            "row_std": round(self.row_std, 6),
            "column_peaks": self.column_peaks,
            "column_std": round(self.column_std, 6),
            "bbox": [round(x, 4) for x in self.bbox],
            "otsu_threshold": self.otsu_threshold,
            "nom_likely": self.nom_likely,
            "blank_likely": self.blank_likely,
            "toc_likely": self.toc_likely,
        }


def _otsu(gray: np.ndarray) -> int:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    hist = hist.astype(float)
    total = hist.sum()
    if total <= 0:
        return 127
    sum_all = float(np.dot(np.arange(256), hist))
    sum_b = 0.0
    w_b = 0.0
    best = 0.0
    threshold = 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best:
            best = var
            threshold = i
    return int(threshold)


def _runs(mask: np.ndarray, max_gap: int = 1) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    groups: list[tuple[int, int]] = []
    start = int(idx[0])
    prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev <= max_gap + 1:
            prev = i
        else:
            groups.append((start, prev))
            start = i
            prev = i
    groups.append((start, prev))
    return groups


def _peak_count(profile: np.ndarray, min_distance: int = 6) -> int:
    if profile.size < 5 or float(profile.std()) < 1e-6:
        return 0
    threshold = float(profile.mean() + 0.5 * profile.std())
    candidates: list[int] = []
    for i in range(2, len(profile) - 2):
        if profile[i] >= threshold and profile[i] == profile[i - 2 : i + 3].max():
            if not candidates or i - candidates[-1] >= min_distance:
                candidates.append(i)
            elif profile[i] > profile[candidates[-1]]:
                candidates[-1] = i
    return len(candidates)


def analyze_image(path: str | Path, max_side: int = 900) -> PageFeatures:
    with Image.open(path) as im:
        gray = im.convert("L")
        w, h = gray.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            gray = gray.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        arr = np.asarray(gray, dtype=np.uint8)

    height, width = arr.shape
    threshold = _otsu(arr)
    ink = arr < max(80, threshold)

    # Crop margins so scanner borders and stamps do not dominate projections.
    mh = int(height * 0.06)
    mw = int(width * 0.06)
    core = ink[mh : height - mh, mw : width - mw]
    if core.size == 0:
        core = ink
    core_h, core_w = core.shape
    ink_fraction = float(core.mean())

    column = core.sum(axis=0) / max(1, core_h)
    row = core.sum(axis=1) / max(1, core_w)

    # Thin, long vertical/horizontal strokes are column/rule lines, not text.
    vlines = [
        r
        for r in _runs(column > 0.45, 1)
        if (r[1] - r[0] + 1) <= 10 and r[1] > core_w * 0.05 and r[0] < core_w * 0.95
    ]
    hlines = [
        r
        for r in _runs(row > 0.45, 1)
        if (r[1] - r[0] + 1) <= 10 and r[1] > core_h * 0.05 and r[0] < core_h * 0.95
    ]

    row_clean = row.copy()
    column_clean = column.copy()
    for start, end in hlines:
        row_clean[start : end + 1] = 0
    for start, end in vlines:
        column_clean[start : end + 1] = 0

    row_peaks = _peak_count(row_clean)
    column_peaks = _peak_count(column_clean)
    row_std = float(row_clean.std())
    column_std = float(column_clean.std())

    ys, xs = np.where(core)
    if len(xs):
        bbox = (
            float(xs.min() / max(1, core_w)),
            float(ys.min() / max(1, core_h)),
            float(xs.max() / max(1, core_w)),
            float(ys.max() / max(1, core_h)),
        )
    else:
        bbox = (0.0, 0.0, 0.0, 0.0)

    # Nôm pages in these books are dense vertical-column blocks. The column
    # profile is the strongest separator from QN horizontal prose. The
    # toc_likely flag catches dense QN tables with dotted leaders, which can
    # otherwise look column-dense.
    nom_likely = bool(column_std >= 0.065 and ink_fraction >= 0.020 and column_peaks >= 8)
    blank_likely = bool(ink_fraction < 0.006 or (ink_fraction < 0.010 and row_peaks <= 8))
    toc_likely = bool(
        (not nom_likely)
        and ink_fraction >= 0.015
        and row_peaks >= 18
        and column_std < 0.070
        and column_peaks >= 12
    )

    return PageFeatures(
        width=width,
        height=height,
        ink_fraction=ink_fraction,
        vertical_lines=len(vlines),
        horizontal_lines=len(hlines),
        row_peaks=row_peaks,
        row_std=row_std,
        column_peaks=column_peaks,
        column_std=column_std,
        bbox=bbox,
        otsu_threshold=threshold,
        nom_likely=nom_likely,
        blank_likely=blank_likely,
        toc_likely=toc_likely,
    )


def _longest_nom_run(
    pages: list[PageRecord],
    features: dict[int, PageFeatures],
    min_length: int = 15,
) -> tuple[int, int] | None:
    """Find the longest contiguous Nôm-like block, allowing blank gaps.

    QN text is never allowed as a gap, because that would merge the QN TOC
    after the Nôm block into the block.
    """
    n = len(pages)
    candidates = [features[p.page_no].nom_likely for p in pages]
    best: tuple[float, int, int] | None = None

    for start in range(n):
        if not candidates[start]:
            continue
        end = start
        gaps = 0
        i = start + 1
        while i < n:
            if candidates[i]:
                end = i
                gaps = 0
                i += 1
                continue
            # Allow a short blank/divider gap, but never a QN text page.
            if features[pages[i].page_no].blank_likely and (i - end) <= 3:
                i += 1
                continue
            break
        length = end - start + 1
        if length < min_length:
            continue
        density = sum(candidates[start : end + 1]) / max(1, length)
        if density < 0.75:
            continue
        score = length + 3.0 * density - 0.5 * gaps
        if best is None or score > best[0]:
            best = (score, start, end)

    if best is None:
        return None
    return best[1], best[2]


def classify_book(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    force: bool = False,
) -> tuple[list[PageRecord], dict[str, Any]]:
    pages = state.pages(book.book_id)
    if not pages:
        raise LayoutError(f"{book.book_id}: no extracted pages; run extract first")
    if len(pages) != book.expected_pages:
        raise LayoutError(
            f"{book.book_id}: expected {book.expected_pages} pages, state has {len(pages)}"
        )

    features: dict[int, PageFeatures] = {}
    for i, page in enumerate(pages, 1):
        if not page.path.exists():
            raise LayoutError(f"Missing page image: {page.path}")
        features[page.page_no] = analyze_image(page.path)

    run = _longest_nom_run(pages, features)
    run_source = "image_evidence"
    if run is None:
        if not (book.nom_start_hint and book.nom_end_hint):
            raise LayoutError(
                f"{book.book_id}: could not find a Nôm block and no nom_start_hint/nom_end_hint"
            )
        run = (book.nom_start_hint - 1, book.nom_end_hint - 1)
        run_source = "config_hint_fallback"

    start_idx, end_idx = run
    nom_pages = set(range(start_idx + 1, end_idx + 2))
    back_start = end_idx + 2

    for page in pages:
        f = features[page.page_no]
        flags: list[str] = []
        page.features = f.to_dict()

        if page.page_no == 1:
            section, folder, script = "cover", "misc", "qn"
            flags.append("COVER_PAGE")
        elif f.blank_likely:
            section, folder, script = "blank", "blank", "blank"
        elif page.page_no in nom_pages:
            section, folder, script = "nom", "ch", "nom"
            if page.page_no == book.nom_start_hint:
                flags.append("NOM_BLOCK_START")
            if page.page_no == book.nom_end_hint:
                flags.append("NOM_BLOCK_END")
        elif page.page_no < book.translation_start:
            section, folder, script = "front_matter", "intro", "qn"
            if f.toc_likely:
                section, folder = "toc", "toc"
                flags.append("TOC_LIKELY_FRONT")
        elif page.page_no <= book.translation_end:
            section, folder, script = "translation", "vi", "qn"
            if f.nom_likely:
                flags.append("MIXED_PAGE_SUSPECT")
        elif page.page_no >= back_start and book.back_matter_is_toc:
            section, folder, script = "back_matter_toc", "toc", "qn"
        else:
            section, folder, script = "other", "misc", "qn"

        # QN back-matter pages can be dense tables and satisfy the Nôm
        # heuristic; location after the Nôm block wins.
        if page.page_no >= back_start and book.back_matter_is_toc:
            section, folder, script = "back_matter_toc", "toc", "qn"

        if f.nom_likely and folder == "vi" and 0.055 <= f.column_std < 0.075:
            flags.append("MIXED_PAGE_SUSPECT")

        page.section = section
        page.folder = folder
        page.script = script
        page.review_flags = sorted(set(page.review_flags + flags))
        page.status = "classified"
        state.update_page(
            book.book_id,
            page.page_no,
            script=page.script,
            section=page.section,
            folder=page.folder,
            status=page.status,
            review_flags=page.review_flags,
            features=page.features,
        )

    summary = {
        "book_id": book.book_id,
        "page_count": len(pages),
        "nom_run": [start_idx + 1, end_idx + 1],
        "nom_run_source": run_source,
        "counts": _counts(pages),
        "features": {str(p.page_no): p.features for p in pages},
        "thresholds": {
            "nom_column_std": 0.065,
            "nom_ink_fraction": 0.020,
            "blank_ink_fraction": 0.006,
        },
    }
    dest = project.data_dir / "layout" / book.book_id / "classification.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    state.set_artifact(book.book_id, "layout", "classification", dest, meta=summary["counts"])
    return pages, summary


def _counts(pages: list[PageRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in pages:
        counts[p.folder] = counts.get(p.folder, 0) + 1
    return dict(sorted(counts.items()))


def read_classification(project: ProjectConfig, book: BookConfig) -> dict[str, Any]:
    path = project.data_dir / "layout" / book.book_id / "classification.json"
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
