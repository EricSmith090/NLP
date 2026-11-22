"""Pipeline orchestration and resumable stage helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import warnings
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .align import (
    align_book,
    write_alignment_csv,
)
from .clean import CleanedPage, clean_page_lines, detect_running_lines, validate_clean_text
from .config import BookConfig, ProjectConfig, load_config
from .dictionary.book_lexicon import BookLexicon
from .dictionary.index import build_dictionary_index
from .evaluate import evaluate_rows, overall_status
from .intake import lock_scope, write_json
from .labels import line_to_box, read_label_txt, write_file_state, write_label_txt
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
from .review.patches import apply_patches, apply_patches_checked, read_patches
from .review_decisions import apply_decisions, decision_path, parse_decisions
from .review_metadata import load_rows_with_metadata
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


def _union_points(lines: Sequence[OCRLine]) -> tuple[tuple[float, float], ...]:
    xs = [p[0] for line in lines for p in line.points]
    ys = [p[1] for line in lines for p in line.points]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def order_and_clean_page(
    book_id: str,
    page: PageRecord,
    script: str,
    ocr_lines: Sequence[OCRLine],
    running_lines: set[str] | None,
    *,
    reverse_nom: bool = False,
    strip_texts: frozenset[str] = frozenset(),
) -> tuple[CleanedPage, list[OCRLine]]:
    """One canonical text per page, shared by the labels and clean stages.

    Doc/FIX_PLAN_v24.md T1.1-T1.3 (RC1-RC3): Label.txt, data/clean and the
    CSV must carry the same text. Nôm boxes keep the API reading order
    (reversed for pages scanned upside-down, RC10); the whole page is cleaned
    once and each box's transcription is the concatenation of the cleaned
    lines that came from it. QN pages become one box (the OCR box, or the
    union of the boxes) whose transcription is the whole cleaned page text.
    Invariant: "".join(box texts) == cleaned.text for Nôm, and the single QN
    box text == cleaned.text.
    """
    if script == "nom":
        from .clean import nom_box_noise, trim_repeat_runs

        ordered = []
        box_drops: list[dict] = []
        for line in (reversed(ocr_lines) if reverse_nom else ocr_lines):
            reason = nom_box_noise(
                line.text, line.points, line.confidence, float(page.width or 0), float(page.height or 0),
                mirrored=reverse_nom, strip_texts=strip_texts,
            )
            if reason:
                box_drops.append({"reason": reason, "text": line.text, "confidence": line.confidence})
                continue
            text, runs = trim_repeat_runs(line.text, line.confidence)
            for run in runs:
                box_drops.append({"reason": "repeat_run", "text": run, "confidence": line.confidence})
            if runs and not text.strip():
                continue
            ordered.append(line if not runs else OCRLine(
                text=text, points=line.points, confidence=line.confidence, script=line.script,
                difficult=line.difficult, extra=line.extra,
            ))
        cleaned = clean_page_lines(
            book_id, page.page_no, page.image_name, "nom", [line.text for line in ordered],
            running_lines=running_lines,
        )
        per_box: dict[int, list[str]] = {}
        for text, src in zip(cleaned.lines, cleaned.line_sources):
            per_box.setdefault(src, []).append(text)
        boxes = [
            OCRLine(
                text="".join(per_box[i]),
                points=line.points,
                confidence=line.confidence,
                script=script,
                difficult=line.difficult,
                extra=line.extra,
            )
            for i, line in enumerate(ordered)
            if i in per_box
        ]
        if reverse_nom and "NOM_ORDER_REVERSED" not in cleaned.flags:
            cleaned.flags = sorted(set(cleaned.flags) | {"NOM_ORDER_REVERSED"})
        if box_drops:
            cleaned.box_drops = box_drops
            cleaned.flags = sorted(set(cleaned.flags) | {f"{d['reason'].upper()}_REMOVED" for d in box_drops})
        if "".join(b.text for b in boxes) != cleaned.text:
            raise RuntimeError(f"{book_id} p{page.page_no}: Nôm label boxes do not rebuild the cleaned text")
        return cleaned, boxes
    ordered = _sort_lines(ocr_lines, script)
    cleaned = clean_page_lines(
        book_id, page.page_no, page.image_name, script, [line.text for line in ordered],
        running_lines=running_lines,
    )
    source = [line for line in ordered if line.text.strip()]
    if not cleaned.text or not source:
        return cleaned, []
    single = len(source) == 1
    box = OCRLine(
        text=cleaned.text,
        points=source[0].points if single else _union_points(source),
        confidence=source[0].confidence if single else None,
        script=script,
        difficult=source[0].difficult if single else None,
        extra=source[0].extra if single else {},
    )
    return cleaned, [box]


def _nom_strip_texts(project: ProjectConfig, book: BookConfig) -> frozenset[str]:
    """Exact Nôm box texts that are page furniture (e.g. the SLQ running title
    所𥚇卷), from alignment.per_book.<book>.strip_texts / alignment.strip_texts.
    Applied at clean time so Label.txt and the CSV drop the same boxes."""
    import unicodedata as _ud

    raw = project.alignment_config or {}
    cfg = raw.get("alignment", raw) or {}
    per_book = (cfg.get("per_book") or {}).get(book.book_id, {}) or {}
    texts = list(per_book.get("strip_texts") or cfg.get("strip_texts") or [])
    return frozenset(_ud.normalize("NFC", str(t)).strip() for t in texts if str(t).strip())


def _running_lines(pages: Sequence[PageRecord], router: OCRRouter) -> dict[str, set[str]]:
    """Header/footer lines repeated across pages, keyed by script (nom/qn)."""
    raw = _raw_lines_by_script(pages, router)
    return {
        ("nom" if folder == "ch" else "qn"): detect_running_lines(lines_by_page)
        for folder, lines_by_page in raw.items()
        if lines_by_page
    }


def _reviewed_text_edits(project: ProjectConfig, book: BookConfig) -> int:
    path = project.data_dir / "review" / f"{book.book_id}.patches.jsonl"
    return sum(1 for p in read_patches(path) if p.field in ("ch_txt", "vi_txt")) if path.exists() else 0


def _edited_pages(project: ProjectConfig, book: BookConfig) -> set[int]:
    """PDF pages whose Label.txt text a reviewer edited: the Nôm page of each
    ch_txt patch, the QN page(s) paired with the row's Nôm page for vi_txt."""
    path = project.data_dir / "review" / f"{book.book_id}.patches.jsonl"
    if not path.exists():
        return set()
    map_path = project.data_dir / "layout" / book.book_id / "image_map.json"
    vi_of: dict[str, list[str]] = {}
    if map_path.exists():
        for pair in load_image_map(map_path):
            for ch in pair.ch:
                vi_of.setdefault(ch, []).extend(pair.vi)
    out: set[int] = set()
    for p in read_patches(path):
        if p.field not in ("ch_txt", "vi_txt") or not p.img_id:
            continue
        names = [p.img_id] if p.field == "ch_txt" else vi_of.get(p.img_id, [])
        for name in names:
            try:
                out.add(int(str(name).rsplit(".", 2)[-2]))
            except ValueError:
                pass
    return out


def stage_labels(
    project: ProjectConfig, book: BookConfig, state: State, *, overwrite_reviewed: bool = False,
    only_pages: Iterable[int] | None = None,
) -> dict[str, Any]:
    # Reviewer edits live in Label.txt + CSV (review app). Regenerating
    # Label.txt from OCR would silently discard them while the CSV keeps them
    # (patches are re-applied by align) -> SYNC failure and lost work.
    # ``only_pages``: regenerate just these PDF pages (e.g. QN pages re-read by
    # tools/qn_rescue.py) and keep every other page's boxes as they are in the
    # current Label.txt, reviewer edits included. Refused when one of the
    # selected pages carries a reviewer edit (unless overwrite_reviewed).
    selected = set(int(x) for x in only_pages) if only_pages else None
    if selected is not None:
        touched = sorted(selected & _edited_pages(project, book))
        if touched and not overwrite_reviewed:
            raise PipelineError(
                f"{book.book_id}: page(s) {touched} carry reviewer text edits; regenerating them would discard "
                "the edits. Leave them out of --pages, or pass --overwrite-reviewed if that is intended."
            )
    edits = _reviewed_text_edits(project, book) if selected is None else 0
    if edits and not overwrite_reviewed:
        raise PipelineError(
            f"{book.book_id}: {edits} reviewer text edit(s) exist (data/review/{book.book_id}.patches.jsonl); "
            "re-running labels would discard them from Label.txt. Pass --overwrite-reviewed only if that is intended."
        )
    router = OCRRouter(project, book, state)
    pages = state.pages(book.book_id)
    # Running-line detection needs cross-page evidence; the label path and
    # the clean path share one helper so they drop the same headers/footers.
    running = _running_lines(pages, router)
    reversed_pages = set(book.nom_reversed_pages)
    strip_texts = _nom_strip_texts(project, book)
    by_folder: dict[str, list[PageRecord]] = {}
    for page in pages:
        by_folder.setdefault(str(page.folder), []).append(page)
    # Prune label folders from bins that no longer have pages in the DB
    # (e.g. after the 2026-11-12 re-bin, SLQ's intro/toc went to zero while
    # their stale label files remained on disk). Stages are write-only by
    # design, so pruning stale bins must happen here, explicitly.
    label_root = project.data_dir / "labels" / book.book_id
    for folder in ("ch", "vi", "intro", "ref", "toc", "misc"):
        if selected is not None:
            break  # partial regeneration never prunes folders
        if folder not in by_folder:
            stale = label_root / folder
            if stale.exists():
                shutil.rmtree(stale)
                print(f"[hannom] labels: pruned stale {folder}/ for {book.book_id} (bin has no pages in the DB)")
    counts: dict[str, Any] = {}
    for folder in ("ch", "vi", "intro", "ref", "toc", "misc"):
        folder_pages = sorted(by_folder.get(folder, []), key=lambda p: p.page_no)
        if not folder_pages:
            continue
        image_names = [p.image_name for p in folder_pages]
        boxes_by_image: dict[str, list[dict[str, Any]]] = {}
        empty: list[str] = []
        kept: dict[str, list[dict[str, Any]]] = {}
        if selected is not None:
            if not any(p.page_no in selected for p in folder_pages):
                continue
            current_path = label_root / folder / "Label.txt"
            current = read_label_txt(current_path) if current_path.exists() else {}
            kept = {k.split("/", 1)[-1]: v for k, v in current.items()}
        for page in folder_pages:
            if selected is not None and page.page_no not in selected:
                boxes_by_image[page.image_name] = kept.get(page.image_name, [])
                continue
            result = router.load_result(page)
            if result is None:
                empty.append(page.image_name)
                boxes_by_image[page.image_name] = []
                continue
            script = _label_script(folder)
            _cleaned, cleaned_lines = order_and_clean_page(
                book.book_id, page, script, result.lines, running.get(script),
                reverse_nom=script == "nom" and page.page_no in reversed_pages,
                strip_texts=strip_texts,
            )
            boxes_by_image[page.image_name] = [
                line_to_box(line, page.width, page.height) for line in cleaned_lines
            ]
        label_path = _book_stage(project, book, state, "labels") / folder / "Label.txt"
        state_path = _book_stage(project, book, state, "labels") / folder / "fileState.txt"
        write_label_txt(image_names, boxes_by_image, label_path, folder)
        write_file_state(image_names, state_path, folder, 1)
        no_result = {p.image_name for p in folder_pages if p.image_name in empty}
        with_boxes = {name for name in boxes_by_image if boxes_by_image[name]}
        all_noise = {
            p.image_name
            for p in folder_pages
            if p.image_name not in no_result and p.image_name not in with_boxes
        }
        # Reconcile the label flags on every regenerated page: drop stale
        # empty flags from pages that now carry boxes, and raise exactly one
        # flag for each empty page (LABEL_EMPTY_OCR = OCR missing; OCR_ALL_NOISE
        # = OCR ran but every line was cleaned away). An in-scope page must
        # never leave a regeneration unflagged.
        for page in folder_pages:
            if selected is not None and page.page_no not in selected:
                continue
            image = page.image_name
            before = set(page.review_flags)
            if image in no_result:
                new_flags = (before | {"LABEL_EMPTY_OCR"}) - {"OCR_ALL_NOISE"}
            elif image in all_noise:
                new_flags = (before | {"OCR_ALL_NOISE"}) - {"LABEL_EMPTY_OCR"}
            else:
                new_flags = before - {"LABEL_EMPTY_OCR", "OCR_ALL_NOISE"}
            if new_flags != before:
                state.update_page(book.book_id, page.page_no, review_flags=sorted(new_flags))
        counts[folder] = {"images": len(image_names), "boxes": sum(len(v) for v in boxes_by_image.values()), "empty": empty}
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
    running = _running_lines(pages, router)
    reversed_pages = set(book.nom_reversed_pages)
    strip_texts = _nom_strip_texts(project, book)
    out_dir = _book_stage(project, book, state, "clean")
    dropped_log: list[dict] = []
    count = 0
    flags: dict[str, int] = {}
    for page in pages:
        if page.folder not in {"ch", "vi", "intro", "toc", "ref", "misc"}:
            continue
        result = router.load_result(page)
        if result is None:
            continue
        script = "nom" if page.folder == "ch" else "qn"
        cleaned, _boxes = order_and_clean_page(
            book.book_id, page, script, result.lines, running.get(script),
            reverse_nom=script == "nom" and page.page_no in reversed_pages,
            strip_texts=strip_texts,
        )
        for drop in cleaned.box_drops:
            dropped_log.append({"page_no": page.page_no, "image_name": page.image_name, **drop})
        text_issues = validate_clean_text(cleaned.text, script)
        if text_issues:
            if "CLEAN_TEXT_INVALID" not in cleaned.flags:
                cleaned.flags.append("CLEAN_TEXT_INVALID")
        dest = out_dir / f"{page.page_no:04d}.json"
        dest.write_text(json.dumps(cleaned.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count += 1
        for flag in cleaned.flags:
            flags[flag] = flags.get(flag, 0) + 1
        if cleaned.flags:
            merged = sorted(set(page.review_flags + cleaned.flags))
            state.update_page(book.book_id, page.page_no, review_flags=merged)
    summary = {"pages": count, "flags": dict(sorted(flags.items())), "running_lines": {k: len(v) for k, v in running.items()}}
    summary["box_drops"] = {r: sum(1 for d in dropped_log if d["reason"] == r) for r in sorted({d["reason"] for d in dropped_log})}
    with (out_dir / "dropped.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for item in dropped_log:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
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


def load_readings_cache(project: ProjectConfig) -> Any | None:
    """Load (or rebuild) the compact readings cache once; None when unavailable.

    Honours ``dictionary.skip_sources`` from the dictionary config (default:
    nothing skipped). The cache contributes char ∪ word reading evidence to
    the in-pipeline matchers alongside the JSONL dictionary adapters; absence
    of the drop or the cache simply yields no cache evidence (identical to
    the pre-cache behaviour).
    """
    try:
        from .dictionary.readings import load_readings

        dictionary_cfg = project.dictionary_config or {}
        cfg = (dictionary_cfg or {}).get("dictionary", dictionary_cfg or {})
        entries_dir = project.root / str(cfg.get("entries_dir", "dictionaries/entries"))
        cache = project.data_dir / "dictionary" / "char_readings.json"
        skip = cfg.get("skip_sources") or None
        if isinstance(skip, str):
            skip = [skip]
        return load_readings(entries_dir, cache, skip_sources=skip)
    except Exception as exc:
        # Evidence degradation must never be silent: the pipeline runs with
        # no cache evidence (unlike pre-2026-11-14 consumers) — say so.
        warnings.warn(f"readings cache unavailable ({type(exc).__name__}: {exc}); continuing without cache evidence")
        return None


def learn_for_book(lexicon, rows, dictionary, failures):
    """Fail-closed learning gate shared by ``stage_align`` and tests.

    Log-wide failures (unattributable to any sentence) disable learning
    for the book. Row-specific failures are handled inside
    ``learn_from_rows`` via ``decision_integrity``.
    """
    if any(failure.sentence_id is None for failure in failures or []):
        return {
            "learned_pairs": 0,
            "characters": len(lexicon.data),
            "skipped_log_wide_failure": True,
            "detail": "decision log integrity failure; learning disabled for this run",
            "quarantine": lexicon.quarantine_summary(),
        }
    return lexicon.learn_from_rows(rows, dictionary)


def _rederivable_text_diff_flag(flag: str) -> bool:
    """Return True for flags fully re-derived from the recomputed text_diff.

    ``recompute_text_diff`` re-derives every ``DIFF_*`` flag (and the matching
    ``REVIEW:DIFF_*`` pairs) from the row’s text; keeping the align-time
    originals alongside the recompute-time ones produced contradictory pairs
    like ``DIFF_READING_MISMATCH`` + ``DIFF_NO_READING_MISMATCH`` on the same
    row (verify-F sec.5.A). Re-derived flags are therefore replaced, never
    unioned. Human-facing flags that survive: ``IMAGE_REC_*``, ``OCR_*``,
    ``ALIGN_*``, ``COSEGMENTED_*``, ``SPANS_PAGES``, ``UNMATCHED_*``.
    ``DICT_UNAVAILABLE`` and ``MASK_ONLY_DIFFERENCE`` are also re-derived
    (dictionary empty-flag branch and the [MASK] difference check), so they
    are replaced rather than unioned — the same metadata-hygiene reason.
    """
    if flag.startswith("DIFF_"):
        return True
    if flag == "TEXT_DIFF_INVALID":
        return True
    if flag in {"DICT_UNAVAILABLE", "MASK_ONLY_DIFFERENCE"}:
        return True
    if flag.startswith("REVIEW:"):
        rest = flag[len("REVIEW:"):]
        return rest.startswith("DIFF_") or rest == "DICT_MISS"
    return False


def recompute_text_diff(
    rows: Iterable[AlignmentRow],
    *,
    lexicon: BookLexicon | None = None,
    dictionary: Any | None = None,
    readings_cache: Any | None = None,
    force_recompute: bool = False,
    alignment_config: dict | None = None,
    book_id: str | None = None,
) -> list[AlignmentRow]:
    from .textdiff import (
        auto_text_diff, name_blocks_from_config, name_spellings_from_config, spec_text_diff,
        suggest_rules_from_config, validate_text_diff, variant_fold_from_config, warn_rules_from_config,
    )

    single_fold = variant_fold_from_config(alignment_config)
    _cfg = (alignment_config or {}).get("alignment", alignment_config or {}) or {}
    policy = str(_cfg.get("text_diff_policy", "spec"))
    warn_rules = warn_rules_from_config(alignment_config)
    suggest_rules = suggest_rules_from_config(alignment_config, book_id)
    name_blocks = name_blocks_from_config(alignment_config, book_id)
    rows = list(rows)
    # Spelling table over every row of the book (decided ones included:
    # they are evidence of how a name is written).
    name_spellings = name_spellings_from_config(
        alignment_config, book_id, ((r.ch_txt, r.vi_txt) for r in rows),
        lexicon=lexicon, dictionary=dictionary, readings_cache=readings_cache,
    ) if policy != "legacy" else None
    out: list[AlignmentRow] = []
    for row in rows:
        if getattr(row, "review_status", None) is not None or "CONTENT_EDITED" in row.flags:
            # Rows carrying an explicit review decision (any status) or a
            # human content edit are authoritative; the automatic
            # recomputation must never overwrite them -- except the colouring
            # of a re-applied text edit, which was computed on the old text.
            if "TEXT_DIFF_STALE" in row.flags:
                from .review.edit import recompute_row_diff

                recompute_row_diff(row, lexicon=lexicon, dictionary=dictionary, readings_cache=readings_cache,
                                   warn_rules=warn_rules, suggest_rules=suggest_rules, name_blocks=name_blocks,
                                   name_spellings=name_spellings)
                row.flags = [f for f in row.flags if f != "TEXT_DIFF_STALE"]
            out.append(row)
            continue
        if "NON_ONE_TO_ONE" in row.flags or not row.ch_txt or not row.vi_txt:
            # Non-1-1 rows are forced null FIRST, unconditionally — before any
            # force_recompute is applied. Such rows can never be re-scored.
            row.text_diff = None
            out.append(row)
            continue
        recomputed_from_null = row.text_diff is None
        if recomputed_from_null and not force_recompute:
            # The align stage deliberately left this row unscored
            # (non-1-1 / n-m grouping), and CSV round-trips lose the
            # NON_ONE_TO_ONE flag that marks it. Keep the null unless the
            # caller explicitly force-recomputes (--force-recompute). When it
            # does, the row is re-scored as a 1-1 candidate but is flagged
            # ALIGN_FORCE_RECOMPUTED_FROM_NULL so the evaluator classifies it
            # "unverified", never "verified", regardless of what the re-score
            # finds.
            out.append(row)
            continue
        if policy == "legacy":
            diff = auto_text_diff(
                row.ch_txt,
                row.vi_txt,
                lexicon=lexicon,
                dictionary=dictionary,
                readings_cache=readings_cache,
                strict_reading_mismatch=False,
                # Legacy only: flat (all-diacritic) matching is more lenient
                # than Quy định v2.4, which removes only the 5 tone marks.
                allow_flat_match=True,
                allow_variant_fold=single_fold,
            )
        else:
            # v2.4 / official checker semantics (FIX_PLAN T3.2, RC5/RC7).
            diff = spec_text_diff(
                row.ch_txt, row.vi_txt, lexicon=lexicon, dictionary=dictionary, readings_cache=readings_cache,
                warn_rules=warn_rules,
                suggest_rules=suggest_rules,
                name_blocks=name_blocks,
                name_spellings=name_spellings,
            )
        row.text_diff = diff.elements
        row.flags = sorted(
            {flag for flag in row.flags if not _rederivable_text_diff_flag(flag)}
            | set(diff.flags)
            | {f"REVIEW:{r}" for r in diff.review_reasons}
        )
        if recomputed_from_null:
            row.flags = sorted(set(row.flags + ["ALIGN_FORCE_RECOMPUTED_FROM_NULL"]))
        if diff.elements is not None:
            problems = validate_text_diff(row.ch_txt, row.vi_txt, diff.elements)
            if problems:
                row.flags = sorted(set(row.flags) | {"TEXT_DIFF_INVALID"})
        out.append(row)
    return out


def reconcile_for_book(
    project: ProjectConfig,
    book: BookConfig,
    lexicon: BookLexicon,
    *,
    governance_rows: list[AlignmentRow] | None = None,
    governance_failures: Iterable[Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Fail-closed lexicon reconciliation shared by ``stage_align`` and tests.

    Uses the current governing row state (post patches and decisions) to
    withdraw automated evidence no longer authorized by review. Log-wide
    failure: no revocation, no mutation (documented fail-closed).
    """
    if governance_rows is None or governance_failures is None:
        gov_rows, _blocking, _audit = load_rows_for_evaluation(project, book)
        _d, gov_failures, _issues = parse_decisions(decision_path(project.data_dir, book.book_id))
        governance_rows = gov_rows
        governance_failures = gov_failures
    if any(getattr(f, "sentence_id", "x") is None for f in governance_failures):
        return {"skipped_log_wide_failure": True, "changed": False}
    summary = lexicon.reconcile(governance_rows, dry_run=not persist)
    if summary.get("changed") and persist:
        lexicon.backup()
        lexicon.save()
    return summary


def resegment_enabled(project: ProjectConfig, book: BookConfig) -> bool:
    """``alignment.resegment_from_labels`` (per_book overrides the global value; default off)."""
    raw = project.alignment_config or {}
    cfg = raw.get("alignment", raw) or {}
    per_book = (cfg.get("per_book") or {}).get(book.book_id) or {}
    return bool(per_book.get("resegment_from_labels", cfg.get("resegment_from_labels", False)))


def compute_alignment(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    *,
    persist: bool = True,
    resegment: bool | None = None,
) -> tuple[list[AlignmentRow], dict[str, Any], list[Any]]:
    """Everything ``stage_align`` computes, without writing the CSV or summary.

    ``persist=False`` also leaves the book lexicon on disk untouched, so the
    whole computation can be dry-run on real data. ``resegment`` overrides
    ``alignment.resegment_from_labels`` (``resegment.py``): segment on the
    reviewed Label.txt text and keep the previous rows wherever a reviewer
    accepted one. Returns (rows, summary without sync_errors, pairs).
    """
    from .resegment import (
        overlay_label_text, pin_reviewed_rows, pinned_indices, previous_rows_for_pinning, release_toc_pins,
        toc_nom_images,
    )

    pairs = _load_pairs(project, book, state)
    cleaned = load_cleaned_pages(project, book)
    if not cleaned:
        raise PipelineError(f"{book.book_id}: no cleaned pages; run clean first")
    reseg = resegment_enabled(project, book) if resegment is None else bool(resegment)
    reseg_summary: dict[str, Any] | None = None
    previous_rows: list[AlignmentRow] | None = None
    patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
    decisions, failures, decision_issues = parse_decisions(decision_path(project.data_dir, book.book_id))
    if reseg:
        csv_prev = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
        previous_rows = previous_rows_for_pinning(csv_prev, decisions, decision_issues, failures)
        cleaned, changed_pages = overlay_label_text(cleaned, project.data_dir / "labels" / book.book_id)
        reseg_summary = {"pages_from_label": sorted(changed_pages),
                         "pinning": "on" if previous_rows is not None else "skipped: no previous CSV"}
    dictionary_cfg = project.dictionary_config or {}
    dictionary = build_dictionary_index(project.root, dictionary_cfg, book_id=book.book_id)
    readings_cache = load_readings_cache(project)
    lexicon_path = project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json"
    lexicon = BookLexicon(lexicon_path)
    csv_path_prev = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if csv_path_prev.exists():
        # Automated evidence that is no longer authorized (superseded,
        # invalidated, conflicted, log-wide failure) must not influence
        # this alignment. Reconcile against the *previous* CSV + current
        # decisions before alignment consumes the lexicon.
        revocation = reconcile_for_book(project, book, lexicon, persist=persist)
    else:
        revocation = {"skipped_no_previous_csv": True, "changed": False}
    align_stats: dict[str, Any] = {}
    rows, warnings = align_book(
        book.book_id,
        pairs,
        cleaned,
        config=project.alignment_config,
        lexicon=lexicon,
        dictionary=dictionary,
        readings_cache=readings_cache,
        stats=align_stats,
    )
    if align_stats.get("qn_tokens_stream") is not None:
        # Fail-closed stream-vs-emitted token parity: any sentence the
        # aligner lost must be a hard error, never a silent success.
        stream_tokens = align_stats["qn_tokens_stream"]
        emitted_tokens = align_stats.get("qn_tokens_emitted")
        dropped = align_stats.get("segments_dropped") or 0
        if dropped != 0 or emitted_tokens != stream_tokens:
            raise PipelineError(
                f"{book.book_id}: alignment lost QN content: "
                f"stream_tokens={stream_tokens} emitted_tokens={emitted_tokens} "
                f"sentences_skipped={align_stats.get('sentences_skipped') or []}"
            )
    if reseg and previous_rows is not None:
        pinned = pinned_indices(previous_rows)
        toc_images = toc_nom_images(project.alignment_config, book.book_id, pairs)
        pinned, released = release_toc_pins(previous_rows, rows, pinned, toc_images)
        rows, pin_report = pin_reviewed_rows(previous_rows, rows, pinned)
        reseg_summary.update(pin_report)
        reseg_summary["pins_released_on_toc_pages"] = released
        # Every text edit already sits in the Label.txt text the rows were cut
        # from; replaying text patches on re-cut rows could paste text twice.
        patches = [p for p in patches if p.field not in ("ch_txt", "vi_txt")]
    # Human patches are applied BEFORE learning and BEFORE recomputation so
    # that active learning never consumes unreviewed machine output. Lexicon
    # learning itself is restricted to rows whose decision history is sound
    # (see review_decisions.apply_decisions); a log-wide integrity failure
    # fails the learning step closed for the whole book.
    rows, _first_pass_rejected = apply_patches_checked(rows, patches)
    rows, review_issues, review_audit = apply_decisions(rows, decisions, decision_issues, failures=failures)
    learned = learn_for_book(lexicon, rows, dictionary, failures)
    if persist:
        lexicon.save()
    rows = recompute_text_diff(
        rows,
        lexicon=lexicon,
        dictionary=dictionary,
        readings_cache=readings_cache,
        alignment_config=project.alignment_config,
        book_id=book.book_id,
    )
    # Apply patches and decisions again so human content and review
    # decisions always win over the automatic recomputation. Report what is
    # still rejected after this final pass (a text_diff patch made after a
    # text edit only matches once the colouring has been recomputed).
    rows, rejected_patches = apply_patches_checked(rows, patches)
    if rejected_patches:
        print(
            f"[hannom] align: {book.book_id}: {len(rejected_patches)} review patch(es) no longer match "
            f"their row and were NOT applied (see summary.json review_patches_rejected; "
            f"tools/replay_review_edits.py re-applies text edits by substring)",
            flush=True,
        )
    rows, _, _ = apply_decisions(rows, decisions, decision_issues, failures=failures)
    summary = {
        "book_id": book.book_id,
        "rows": len(rows),
        "warnings": warnings,
        "lexicon": learned,
        "lexicon_quarantine": lexicon.quarantine_summary(),
        "lexicon_revocation": revocation,
        "review_decision_issues": review_issues,
        "review_decision_audit": review_audit,
        "review_patches_rejected": [
            {"sentence_id": r.patch.sentence_id, "field": r.patch.field, "reason": r.reason} for r in rejected_patches
        ],
        "stats": align_stats or None,
        "flags": {
            flag: sum(1 for row in rows if flag in row.flags)
            for flag in sorted({flag for row in rows for flag in row.flags})
        },
    }
    if reseg_summary is not None:
        summary["resegment"] = reseg_summary
    return rows, summary, pairs


def stage_align(project: ProjectConfig, book: BookConfig, state: State) -> tuple[list[AlignmentRow], dict[str, Any]]:
    rows, summary, pairs = compute_alignment(project, book, state)
    csv_path = _book_stage(project, book, state, "align") / f"{book.book_name}.csv"
    write_alignment_csv(csv_path, rows)
    # Label.txt <-> CSV SYNC with the official normalisation (FIX_PLAN T1.4).
    # Reported here for diagnosis; packaging refuses a book that is out of sync.
    from .sync_check import check_book_dir

    label_root = project.data_dir / "labels" / book.book_id
    sync_errors = check_book_dir(label_root, csv_path, pairs) if (label_root / "ch" / "Label.txt").exists() else ["labels missing"]
    summary["sync_errors"] = sync_errors
    write_json(csv_path.parent / "sync_check.json", {"book_id": book.book_id, "errors": sync_errors})
    if sync_errors:
        print(f"[hannom] align: {book.book_id} Label.txt/CSV out of SYNC: {sync_errors[0]}", flush=True)
    write_json(csv_path.parent / "summary.json", summary)
    state.set_artifact(book.book_id, "align", "csv", csv_path, meta={"rows": len(rows)})
    return rows, summary


def load_rows_for_evaluation(
    project: ProjectConfig, book: BookConfig
) -> tuple[list[AlignmentRow], list[str], list[str]]:
    """Load the CSV, restore its metadata sidecar, apply content patches
    and overlay review decisions.

    Returns (rows, blocking_issues, audit_diagnostics):

    - ``blocking_issues`` are current-revision failures that must block the
      evaluation gate (sidecar metadata problems, active decision-integrity
      failures).
    - ``audit_diagnostics`` are historical diagnostics that remain
      inspectable without blocking the current revision.
    """
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    rows, issues = load_rows_with_metadata(csv_path)
    patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
    rows = apply_patches(rows, patches)
    decisions, failures, decision_issues = parse_decisions(decision_path(project.data_dir, book.book_id))
    rows, active, audit = apply_decisions(rows, decisions, decision_issues, failures=failures)
    return rows, issues + active, audit


def _load_rows_patched(project, book) -> tuple[list[AlignmentRow], list[str], list[str]]:
    """Backward-compatible alias for ``load_rows_for_evaluation``."""
    return load_rows_for_evaluation(project, book)


def stage_evaluate(project: ProjectConfig, book: BookConfig, state: State) -> BookMetrics:
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if not csv_path.exists():
        raise PipelineError(f"{book.book_id}: missing CSV {csv_path}")
    rows, blocking_issues, audit = load_rows_for_evaluation(project, book)
    metrics = evaluate_rows(
        book.book_id,
        rows,
        minimum_similarity=float(project.quality.get("minimum_similarity", 95.0)),
        null_ratio_warn=float(project.quality.get("null_ratio_warn", 0.05)),
        yellow_ratio_warn=float(project.quality.get("yellow_ratio_warn", 0.05)),
        minimum_coverage=float(project.quality.get("minimum_coverage", 0.9)),
        max_unverified_ratio=float(project.quality.get("max_unverified_ratio", 0.05)),
        integrity_issues=blocking_issues,
        audit_diagnostics=audit,
    )
    dest = _book_stage(project, book, state, "evaluation") / "metrics.json"
    if dest.exists():
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(dest, dest.with_name(f"metrics.{stamp}.json"))
    write_json(dest, metrics.to_dict())
    state.set_artifact(book.book_id, "evaluation", "metrics", dest, meta=metrics.to_dict())
    return metrics


def stage_package(
    project: ProjectConfig,
    book: BookConfig,
    state: State,
    *,
    strict_gate: bool = True,
    allow_empty_labels: bool = False,
) -> tuple[Path, list]:
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if not csv_path.exists():
        raise PipelineError(f"{book.book_id}: missing CSV {csv_path}")
    rows, _, _ = _load_rows_patched(project, book)
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
        allow_empty_labels=allow_empty_labels,
    )
    blockers = [i for i in issues if i.severity != "warning"]
    if blockers:
        raise PipelineError(
            f"{book.book_id}: package validation failed: "
            + "; ".join(f"{i.code}:{i.message}" for i in blockers[:5])
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
    allow_empty_labels: bool = False,
) -> dict[str, Any]:
    book_dirs: list[Path] = []
    metrics: list[BookMetrics] = []
    for book in project.books:
        book_dir, _ = stage_package(project, book, state, strict_gate=strict_gate, allow_empty_labels=allow_empty_labels)
        book_dirs.append(book_dir)
        metrics.append(stage_evaluate(project, book, state))
    report_path, report_issues, _ = build_report(project, metrics, strict=strict_report)
    source_zip = build_source_zip(project)
    from .package import build_extras_zip

    extras_zip = build_extras_zip(project)
    zip_path = build_submission_zip(
        project,
        book_dirs,
        report_path=report_path,
        source_zip=source_zip,
        extras_zip=extras_zip,
    )
    return {
        "zip": str(zip_path),
        "report": str(report_path),
        "source_zip": str(source_zip),
        "extras_zip": str(extras_zip),
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
