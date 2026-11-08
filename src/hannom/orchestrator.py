"""Pipeline orchestration and resumable stage helpers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .align import (
    align_book,
    read_alignment_csv,
    write_alignment_csv,
)
from .clean import CleanedPage, clean_page_lines, detect_running_lines
from .config import BookConfig, ProjectConfig, load_config
from .dictionary.book_lexicon import BookLexicon
from .dictionary.index import build_dictionary_index
from .evaluate import evaluate_rows, overall_status
from .intake import lock_scope, write_json
from .labels import line_to_box, write_file_state, write_label_txt
from .layout import classify_book
from .models import AlignmentRow, BookMetrics, OCRLine, PageRecord
from .ocr.base import OCRUnavailable
from .ocr.router import OCRRouter
from .package import (
    build_book_folder,
    build_source_zip,
    build_submission_zip,
    validate_book_package,
    validate_source_zip,
)
from .pages import extract_book
from .report import (
    ReportData,
    build_report_pdf,
    load_report_config,
    report_summary_json,
    validate_report_data,
)
from .review.patches import apply_patches, read_patches
from .state import State, iso, utc_now
from .t1_map import Pair, build_image_map, load_image_map


class PipelineError(RuntimeError):
    pass


def load_environment(root: str | Path) -> None:
    """Minimal .env loader; never prints values."""
    path = Path(root) / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def open_state(project: ProjectConfig) -> State:
    return State(project.data_dir / "state.sqlite3")


def config_hash(project: ProjectConfig) -> str:
    digest = hashlib.sha256()
    for path in sorted((project.root / "configs").rglob("*.yaml")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def start_run(project: ProjectConfig, state: State, stage: str) -> str:
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{stage}"
    state.start_run(run_id, None, config_hash(project))
    return run_id


def _book_stage(project: ProjectConfig, book: BookConfig, state: State, stage: str) -> Path:
    path = project.data_dir / stage / book.book_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def stage_intake(project: ProjectConfig, book: BookConfig, state: State) -> dict[str, Any]:
    return lock_scope(project, book, state)


def stage_extract(project: ProjectConfig, book: BookConfig, state: State, *, force: bool = False) -> list[PageRecord]:
    return extract_book(project, book, state, force=force)


def stage_classify(project: ProjectConfig, book: BookConfig, state: State, *, force: bool = False):
    return classify_book(project, book, state, force=force)


def stage_map(project: ProjectConfig, book: BookConfig, state: State, *, force: bool = False) -> dict[str, Any]:
    return build_image_map(project, book, state)


def stage_ocr(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    *,
    engines: list[str] | None = None,
    force: bool = False,
    limit: int | None = None,
    pages: list[PageRecord] | None = None,
) -> list:
    router = OCRRouter(project, book, state)
    return router.run_book(pages=pages, engines=engines, force=force, limit=limit)


def _label_script(folder: str) -> str:
    return "nom" if folder == "ch" else "qn"


def _sort_lines(lines: Sequence[OCRLine], script: str) -> list[OCRLine]:
    def box(line: OCRLine) -> tuple[float, float, float, float]:
        xs = [p[0] for p in line.points]
        ys = [p[1] for p in line.points]
        return min(xs), min(ys), max(xs), max(ys)

    def key(line: OCRLine):
        x0, y0, x1, y1 = box(line)
        if script == "nom" and (y1 - y0) > 1.25 * (x1 - x0):
            return (-((x0 + x1) / 2), y0)
        return (y0, x0)

    return sorted(lines, key=key)


def stage_labels(project: ProjectConfig, book: BookConfig, state: State) -> dict[str, Any]:
    router = OCRRouter(project, book, state)
    pages = state.pages(book.book_id)
    by_folder: dict[str, list[PageRecord]] = {}
    for page in pages:
        by_folder.setdefault(str(page.folder), []).append(page)
    counts: dict[str, Any] = {}
    for folder in ("ch", "vi", "intro", "ref", "toc"):
        folder_pages = sorted(by_folder.get(folder, []), key=lambda p: p.page_no)
        if not folder_pages:
            continue
        image_names = [p.image_name for p in folder_pages]
        boxes_by_image: dict[str, list[dict[str, Any]]] = {}
        empty: list[str] = []
        for page in folder_pages:
            result = router.load_result(page)
            if result is None:
                empty.append(page.image_name)
                boxes_by_image[page.image_name] = []
                continue
            script = _label_script(folder)
            lines = _sort_lines(result.lines, script)
            cleaned_lines: list[OCRLine] = []
            for line in lines:
                if not line.text.strip():
                    continue
                cleaned = clean_page_lines(
                    book.book_id, page.page_no, page.image_name, script, [line.text]
                )
                text = cleaned.lines[0] if cleaned.lines else ""
                if not text:
                    continue
                cleaned_lines.append(
                    OCRLine(
                        text=text,
                        points=line.points,
                        confidence=line.confidence,
                        script=script,
                        difficult=line.difficult,
                        extra=line.extra,
                    )
                )
            boxes_by_image[page.image_name] = [
                line_to_box(line, page.width, page.height) for line in cleaned_lines
            ]
        label_path = _book_stage(project, book, state, "labels") / folder / "Label.txt"
        state_path = _book_stage(project, book, state, "labels") / folder / "fileState.txt"
        write_label_txt(image_names, boxes_by_image, label_path, folder)
        write_file_state(image_names, state_path, folder, 1)
        counts[folder] = {"images": len(image_names), "boxes": sum(len(v) for v in boxes_by_image.values()), "empty": empty}
        if empty:
            for page in folder_pages:
                if page.image_name in empty:
                    flags = sorted(set(page.review_flags + ["LABEL_EMPTY_OCR"]))
                    state.update_page(book.book_id, page.page_no, review_flags=flags)
    return counts


def _raw_lines_by_script(pages: Sequence[PageRecord], router: OCRRouter) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {"ch": [], "vi": []}
    for page in pages:
        if page.folder not in {"ch", "vi"}:
            continue
        result = router.load_result(page)
        out["ch" if page.folder == "ch" else "vi"].append(
            [line.text for line in result.lines if line.text.strip()] if result else []
        )
    return out


def stage_clean(project: ProjectConfig, book: BookConfig, state: State) -> dict[str, Any]:
    router = OCRRouter(project, book, state)
    pages = state.pages(book.book_id)
    raw = _raw_lines_by_script(pages, router)
    running = {
        script: detect_running_lines(lines_by_page)
        for script, lines_by_page in raw.items()
        if lines_by_page
    }
    out_dir = _book_stage(project, book, state, "clean")
    count = 0
    flags: dict[str, int] = {}
    for page in pages:
        if page.folder not in {"ch", "vi", "intro", "toc", "ref"}:
            continue
        result = router.load_result(page)
        if result is None:
            continue
        script = "nom" if page.folder == "ch" else "qn"
        cleaned = clean_page_lines(
            book.book_id,
            page.page_no,
            page.image_name,
            script,
            [line.text for line in result.lines],
            running_lines=running.get("ch" if script == "nom" else "vi"),
        )
        dest = out_dir / f"{page.page_no:04d}.json"
        dest.write_text(json.dumps(cleaned.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count += 1
        for flag in cleaned.flags:
            flags[flag] = flags.get(flag, 0) + 1
        if cleaned.flags:
            merged = sorted(set(page.review_flags + cleaned.flags))
            state.update_page(book.book_id, page.page_no, review_flags=merged)
    summary = {"pages": count, "flags": dict(sorted(flags.items())), "running_lines": {k: len(v) for k, v in running.items()}}
    write_json(out_dir / "summary.json", summary)
    return summary


def load_cleaned_pages(project: ProjectConfig, book: BookConfig) -> dict[str, CleanedPage]:
    out: dict[str, CleanedPage] = {}
    folder = project.data_dir / "clean" / book.book_id
    for path in sorted(folder.glob("*.json")):
        if path.name == "summary.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        known = set(CleanedPage.__dataclass_fields__)
        out[str(data["image_name"])] = CleanedPage(**{k: v for k, v in data.items() if k in known})
    return out


def _load_pairs(project: ProjectConfig, book: BookConfig, state: State) -> list[Pair]:
    path = project.data_dir / "layout" / book.book_id / "image_map.json"
    if not path.exists():
        build_image_map(project, book, state)
    return load_image_map(path)


def recompute_text_diff(
    rows: Iterable[AlignmentRow],
    *,
    lexicon: BookLexicon | None = None,
    dictionary: Any | None = None,
) -> list[AlignmentRow]:
    from .textdiff import auto_text_diff, validate_text_diff

    out: list[AlignmentRow] = []
    for row in rows:
        if "NON_ONE_TO_ONE" in row.flags or not row.ch_txt or not row.vi_txt:
            row.text_diff = None
            out.append(row)
            continue
        diff = auto_text_diff(
            row.ch_txt,
            row.vi_txt,
            lexicon=lexicon,
            dictionary=dictionary,
            strict_reading_mismatch=False,
        )
        row.text_diff = diff.elements
        row.flags = sorted(set(row.flags + diff.flags + [f"REVIEW:{r}" for r in diff.review_reasons]))
        if diff.elements is not None:
            problems = validate_text_diff(row.ch_txt, row.vi_txt, diff.elements)
            if problems:
                row.flags.append("TEXT_DIFF_INVALID")
        out.append(row)
    return out


def stage_align(project: ProjectConfig, book: BookConfig, state: State) -> tuple[list[AlignmentRow], dict[str, Any]]:
    pairs = _load_pairs(project, book, state)
    cleaned = load_cleaned_pages(project, book)
    if not cleaned:
        raise PipelineError(f"{book.book_id}: no cleaned pages; run clean first")
    dictionary_cfg = project.dictionary_config or {}
    dictionary = build_dictionary_index(project.root, dictionary_cfg, book_id=book.book_id)
    lexicon_path = project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json"
    lexicon = BookLexicon(lexicon_path)
    rows, warnings = align_book(
        book.book_id,
        pairs,
        cleaned,
        config=project.alignment_config,
        lexicon=lexicon,
        dictionary=dictionary,
    )
    # Learn from this book's rows, save, then recompute diffs with the new
    # evidence. This is the only pass that changes automatic colours.
    learned = lexicon.learn_from_rows(rows, dictionary)
    lexicon.save()
    rows = recompute_text_diff(rows, lexicon=lexicon, dictionary=dictionary)
    patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
    rows = apply_patches(rows, patches)
    csv_path = _book_stage(project, book, state, "align") / f"{book.book_name}.csv"
    write_alignment_csv(csv_path, rows)
    summary = {
        "book_id": book.book_id,
        "rows": len(rows),
        "warnings": warnings,
        "lexicon": learned,
        "flags": {
            flag: sum(1 for row in rows if flag in row.flags)
            for flag in sorted({flag for row in rows for flag in row.flags})
        },
    }
    write_json(csv_path.parent / "summary.json", summary)
    state.set_artifact(book.book_id, "align", "csv", csv_path, meta={"rows": len(rows)})
    return rows, summary


def stage_evaluate(project: ProjectConfig, book: BookConfig, state: State) -> BookMetrics:
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if not csv_path.exists():
        raise PipelineError(f"{book.book_id}: missing CSV {csv_path}")
    rows = read_alignment_csv(csv_path)
    patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
    rows = apply_patches(rows, patches)
    metrics = evaluate_rows(
        book.book_id,
        rows,
        minimum_similarity=float(project.quality.get("minimum_similarity", 95.0)),
        null_ratio_warn=float(project.quality.get("null_ratio_warn", 0.05)),
        yellow_ratio_warn=float(project.quality.get("yellow_ratio_warn", 0.05)),
    )
    dest = _book_stage(project, book, state, "evaluation") / "metrics.json"
    write_json(dest, metrics.to_dict())
    state.set_artifact(book.book_id, "evaluation", "metrics", dest, meta=metrics.to_dict())
    return metrics


def stage_package(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    *,
    strict_gate: bool = True,
) -> tuple[Path, list]:
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if not csv_path.exists():
        raise PipelineError(f"{book.book_id}: missing CSV {csv_path}")
    rows = read_alignment_csv(csv_path)
    patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
    rows = apply_patches(rows, patches)
    metrics = stage_evaluate(project, book, state)
    if strict_gate and not metrics.passed:
        raise PipelineError(
            f"{book.book_id}: quality gate failed (similarity={metrics.similarity}, "
            f"issues={metrics.issues[:3]}); refusing to package"
        )
    pairs = _load_pairs(project, book, state)
    pages = state.pages(book.book_id)
    book_dir = build_book_folder(project, book, pages, rows, image_map_pairs=pairs)
    issues = validate_book_package(
        project,
        book,
        book_dir,
        minimum_similarity=float(project.quality.get("minimum_similarity", 95.0)),
    )
    if issues:
        raise PipelineError(
            f"{book.book_id}: package validation failed: "
            + "; ".join(f"{i.code}:{i.message}" for i in issues[:5])
        )
    return book_dir, issues


def build_report(
    project: ProjectConfig,
    metrics: Sequence[BookMetrics],
    *,
    output_path: Path | None = None,
    strict: bool = True,
) -> tuple[Path, list[str], ReportData]:
    data = load_report_config(project)
    data.metrics = list(metrics)
    data.output_path = output_path or (project.data_dir / "output" / project.report_name)
    issues = validate_report_data(data)
    if strict and issues:
        raise PipelineError("report data incomplete: " + "; ".join(issues[:8]))
    build_report_pdf(data, data.output_path)
    summary = report_summary_json(data)
    write_json(project.data_dir / "output" / "report_summary.json", summary)
    return data.output_path, issues, data


def stage_package_all(
    project: ProjectConfig,
    state: State,
    *,
    strict_gate: bool = True,
    strict_report: bool = True,
) -> dict[str, Any]:
    book_dirs: list[Path] = []
    metrics: list[BookMetrics] = []
    for book in project.books:
        book_dir, _ = stage_package(project, book, state, strict_gate=strict_gate)
        book_dirs.append(book_dir)
        metrics.append(stage_evaluate(project, book, state))
    report_path, report_issues, _ = build_report(project, metrics, strict=strict_report)
    source_zip = build_source_zip(project)
    zip_path = build_submission_zip(
        project,
        book_dirs,
        report_path=report_path,
        source_zip=source_zip,
    )
    return {
        "zip": str(zip_path),
        "report": str(report_path),
        "source_zip": str(source_zip),
        "books": [str(x) for x in book_dirs],
        "report_issues": report_issues,
    }


def run_pilot(project: ProjectConfig, book_id: str) -> dict[str, Any]:
    """Book 3-style end-to-end run up to the OCR boundary.

    If OCR is unavailable, stop after recording a clear blocked status. The
    earlier version continued into labels/clean/align and failed far from
    the real cause.
    """
    book = project.book(book_id)
    with open_state(project) as state:
        stages: dict[str, Any] = {}
        stages["intake"] = stage_intake(project, book, state)
        stages["extract"] = {"pages": len(stage_extract(project, book, state))}
        _, classification = stage_classify(project, book, state)
        stages["classify"] = classification["counts"]
        stages["map"] = stage_map(project, book, state)["meta"]

        pages = state.pages(book.book_id)
        sample: list[PageRecord] = []
        for folder in ("ch", "vi"):
            candidates = [p for p in pages if p.folder == folder]
            if not candidates:
                continue
            indices = sorted({0, len(candidates) // 2, len(candidates) - 1})
            sample.extend(candidates[i] for i in indices)
        try:
            results = stage_ocr(project, book, state, pages=sample)
            stages["ocr_sample"] = {
                "pages": len(results),
                "page_numbers": [result.page_no for result in results],
            }
        except OCRUnavailable as exc:
            results = []
            stages["ocr_sample"] = {"unavailable": str(exc)}
        if not results:
            stages["status"] = "blocked_ocr"
            stages["next"] = (
                "Install and calibrate a local OCR engine, or set "
                f"{project.api.token_env}, then run `hannom ocr`."
            )
            write_json(project.artifacts_dir / "pilot" / f"{book.book_id}_status.json", stages)
            return stages

        try:
            stages["labels"] = stage_labels(project, book, state)
            stages["clean"] = stage_clean(project, book, state)
            stages["align"] = stage_align(project, book, state)[1]
            stages["evaluation"] = stage_evaluate(project, book, state).to_dict()
            stages["status"] = "partial_ocr_sample" if len(results) < len(
                [p for p in pages if p.folder in {"ch", "vi"}]
            ) else "complete"
        except PipelineError as exc:
            stages["status"] = "blocked_after_ocr"
            stages["error"] = str(exc)
        write_json(project.artifacts_dir / "pilot" / f"{book.book_id}_status.json", stages)
        return stages
