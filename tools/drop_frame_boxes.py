"""Drop Nôm boxes printed on the page frame, on the spine or outside the frame.

The instructor (2026-11-21): what is on the spine or outside the frame is not
page text. The OCR read the frame ornaments, the folio numbers above the frame
and the spine label as characters; they are listed, after a check of every
candidate on the page image, in ``configs/frame_boxes/<book>.tsv`` (see
``hannom.frame_boxes``).

For every listed box found in ch/Label.txt (same image, same corners ± 2 px;
the text is not compared, so edited boxes are still found) the tool removes
the box from Label.txt and the same characters, by stream position, from the
CSV's ch_txt, then recomputes text_diff of the rows that changed. Reviewer
decisions on those rows stop verifying (their content changed): the report
lists them.

Dry run by default: prints a summary and writes a report. ``--write`` applies
it: refuses if Label.txt or the CSV changed on disk while the tool ran, keeps
``.bak-review`` copies, then re-reads both and checks SYNC. Run ``align`` for
the book afterwards (rows with removed characters are cut again).

    python tools/drop_frame_boxes.py --book T1_CamPhong_Tap1
    python tools/drop_frame_boxes.py --book T1_CamPhong_Tap1 --write
    python tools/drop_frame_boxes.py --book T1_CamPhong_Tap1 --find   # candidates for a new check

Stop the review app while ``--write`` runs.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.frame_boxes import drop_listed_boxes, entry_for, find_candidates, match_listed, read_list, write_list  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.review.edit import atomic_save_csv, atomic_save_labels, recompute_row_diff  # noqa: E402
from hannom.review_decisions import apply_decisions, decision_path, parse_decisions  # noqa: E402
from hannom.review_metadata import load_rows_with_metadata, sidecar_path  # noqa: E402
from hannom.sync_check import check_sync  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402


def diff_context(project, book, rows) -> dict:
    """Lexicon / dictionary / readings / rules / name blocks exactly as the review app recomputes a row."""
    from hannom.dictionary.book_lexicon import BookLexicon
    from hannom.dictionary.index import build_dictionary_index
    from hannom.orchestrator import load_readings_cache
    from hannom.textdiff import (
        name_blocks_from_config, name_spellings_from_config, suggest_rules_from_config, warn_rules_from_config,
    )

    ctx = {
        "lexicon": BookLexicon(project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json"),
        "dictionary": build_dictionary_index(project.root, project.dictionary_config or {}, book_id=book.book_id),
        "readings_cache": load_readings_cache(project),
        "warn_rules": warn_rules_from_config(project.alignment_config),
        "suggest_rules": suggest_rules_from_config(project.alignment_config, book.book_id),
        "name_blocks": name_blocks_from_config(project.alignment_config, book.book_id),
    }
    ctx["name_spellings"] = name_spellings_from_config(
        project.alignment_config, book.book_id, ((r.ch_txt, r.vi_txt) for r in rows),
        lexicon=ctx["lexicon"], dictionary=ctx["dictionary"], readings_cache=ctx["readings_cache"])
    return ctx


def colours(row) -> Counter:
    out: Counter = Counter()
    for el in row.text_diff or []:
        out[el.type] += sum(e - s for s, e in el.nom_pos)
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--list", help="checked box list (default configs/frame_boxes/<book>.tsv)")
    ap.add_argument("--report", help="report path (default data/diagnostics/frame_boxes/<book>.md)")
    ap.add_argument("--find", action="store_true", help="only write the current candidates (for a new check)")
    ap.add_argument("--write", action="store_true", help="apply to ch/Label.txt and the CSV")
    ap.add_argument("--data", help="another data directory (e.g. a copy for a trial run)")
    args = ap.parse_args()

    project = load_config(ROOT / args.config)
    if args.data:
        project = dataclasses.replace(project, data_dir=Path(args.data).resolve())
    book = next(b for b in project.books if b.book_id == args.book)
    data = project.data_dir
    csv_path = data / "align" / book.book_id / f"{book.book_name}.csv"
    label_path = data / "labels" / book.book_id / "ch" / "Label.txt"
    vi_path = data / "labels" / book.book_id / "vi" / "Label.txt"
    out_dir = data / "diagnostics" / "frame_boxes"
    ch_labels = read_label_txt(label_path)

    if args.find:
        entries = [entry_for(os.path.basename(k.replace("\\", "/")), boxes[i])
                   for k, boxes in ch_labels.items() for i, _gap in find_candidates(boxes)]
        path = out_dir / f"{book.book_id}_candidates.tsv"
        write_list(path, entries, "candidates only: check each one on the page image before listing it")
        print(f"{book.book_id}: {len(entries)} candidates -> {path}")
        return 0

    list_path = Path(args.list) if args.list else ROOT / "configs" / "frame_boxes" / f"{book.book_id}.tsv"
    entries = read_list(list_path)
    pairs = load_image_map(data / "layout" / book.book_id / "image_map.json")
    side = sidecar_path(csv_path)
    stamps = {p: p.stat().st_mtime_ns for p in (csv_path, side, label_path) if p.exists()}
    rows, _issues = load_rows_with_metadata(csv_path)

    found, missing = match_listed(ch_labels, entries)
    new_labels, new_rows, removed = drop_listed_boxes(pairs, ch_labels, rows, set(found))
    ctx = diff_context(project, book, new_rows)
    before = {i: colours(rows[i]) for i in removed}
    for i in removed:
        recompute_row_diff(new_rows[i], **ctx, mark_edited=False)
    after = {i: colours(new_rows[i]) for i in removed}

    decisions, failures, issues = parse_decisions(decision_path(data, book.book_id))
    reviewed, _a, _b = apply_decisions(rows, decisions, issues, failures=failures)
    status = {i: reviewed[i].review_status for i in removed if reviewed[i].review_status}
    emptied = [i for i in removed if not new_rows[i].ch_txt]
    red_before = sum(before[i]["error"] for i in removed)
    red_after = sum(after[i]["error"] for i in removed)

    report = Path(args.report) if args.report else out_dir / f"{book.book_id}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Frame / spine boxes removed — {book.book_id}", "",
             f"List: `{list_path.relative_to(ROOT) if list_path.is_relative_to(ROOT) else list_path}` "
             f"({len(entries)} boxes; found in Label.txt: {len(found)}; not found: {len(missing)})", "",
             f"Rows changed: {len(removed)}; red Nôm chars in them {red_before} -> {red_after}; "
             f"rows left without Nôm text: {len(emptied)}; rows with a review decision: {len(status)}", ""]
    if status:
        lines += ["## Rows whose decision stops verifying (review again after align)", ""]
        lines += [f"- {rows[i].sentence_id} ({s})" for i, s in status.items()] + [""]
    lines += ["## Rows", ""]
    for i in removed:
        lines += [f"- {rows[i].sentence_id}: removed `{removed[i]}` — `{rows[i].ch_txt}` -> `{new_rows[i].ch_txt}`"
                  f" (red {before[i]['error']} -> {after[i]['error']})"]
    if missing:
        lines += ["", "## Listed boxes not found (already removed, or the box moved)", ""]
        lines += [f"- {e.image} ({e.x0:g}, {e.y0:g}) `{e.text}`" for e in missing]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{book.book_id}: listed {len(entries)}, found {len(found)}, not found {len(missing)}; "
          f"rows changed {len(removed)} (with a decision: {len(status)}, left without Nôm: {len(emptied)}); "
          f"red Nôm chars in those rows {red_before} -> {red_after}")
    print(f"  report: {report}")
    if not args.write or not found:
        return 0

    for p, t in stamps.items():
        if p.stat().st_mtime_ns != t:
            print(f"ABORT: {p} changed on disk while the tool ran; nothing written.")
            return 2
    atomic_save_labels(new_labels, label_path, "ch")
    atomic_save_csv(csv_path, new_rows)
    reread_rows, _ = load_rows_with_metadata(csv_path)
    dicts = [{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in reread_rows]
    errors = check_sync(dicts, read_label_txt(label_path), read_label_txt(vi_path), pairs)
    left, _ = match_listed(read_label_txt(label_path), entries)
    print(f"  written {label_path} and {csv_path} (backups .bak-review); SYNC errors: {len(errors)}; "
          f"listed boxes still present: {len(left)}")
    print(f"  next: python -m hannom.cli align --book {book.book_id}")
    return 0 if not errors and not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
