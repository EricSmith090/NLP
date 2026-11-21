"""Repair Quốc ngữ spacing in vi/Label.txt that the old review editor broke.

Until 2026-11-21 the review app applied a text edit to Label.txt character by
character on whitespace-free text. SYNC (which ignores whitespace) stayed
green, but words were glued or split in Label.txt, e.g. "vào hơn." stored as
"vàohơ n." The CSV always kept the reviewer's exact text.

This tool rewrites, for every row, the row's spans in vi/Label.txt with the
CSV text (same characters, the CSV's spacing) — see
``hannom.review.edit.respace_vi_rows``. Box points never change.

Dry run by default: prints a summary and writes a report of every row whose
Label text would change. ``--write`` applies it: refuses if Label.txt or the
CSV changed on disk while the tool ran, keeps ``Label.txt.bak-review``, then
re-reads the file and verifies SYNC and the per-box spans.

    python tools/repair_label_spacing.py --book T1_CamPhong_Tap1
    python tools/repair_label_spacing.py --book T1_CamPhong_Tap1 --write

Stop the review app (or at least do not save in it) while ``--write`` runs.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.review.edit import EditError, _row_segments, _stream, atomic_save_labels, respace_vi_rows  # noqa: E402
from hannom.review.patches import read_patches  # noqa: E402
from hannom.review_metadata import load_rows_with_metadata  # noqa: E402
from hannom.sync_check import check_sync, norm_vi, page_orders  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402


def span_mismatches(pairs, vi_labels, rows) -> list[tuple[int, str, str]]:
    """(row index, Label span, CSV slice) for every box span that differs."""
    _ch, vi_order = page_orders(list(pairs))
    stream, origin = _stream(vi_labels, vi_order, norm_vi)
    norms = [norm_vi(r.vi_txt) for r in rows]
    if stream != "".join(norms):
        raise EditError("vi/Label.txt and the CSV are not in SYNC")
    out: list[tuple[int, str, str]] = []
    start = 0
    for i, row in enumerate(rows):
        n = len(norms[i])
        if n:
            segs, seg_of = _row_segments(origin, start, n)
            counted = [k for k, c in enumerate(row.vi_txt) if norm_vi(c)]
            for s, (key, b, first, last) in enumerate(segs):
                js = [j for j, sj in enumerate(seg_of) if sj == s]
                label_span = str(vi_labels[key][b]["transcription"])[first : last + 1]
                csv_slice = row.vi_txt[counted[js[0]] : counted[js[-1]] + 1]
                if label_span != csv_slice:
                    out.append((i, label_span, csv_slice))
        start += n
    return out


def junction_issues(vi_labels) -> dict[str, int]:
    text = [str(bx.get("transcription", "")) for boxes in vi_labels.values() for bx in boxes]
    return {
        "multi_space": sum(len(re.findall(r" {2,}", t)) for t in text),
        "punct_then_letter": sum(len(re.findall(r"[.;:!?,](?=[^\W\d_])", t)) for t in text),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--report", help="report path (default data/diagnostics/label_spacing/<book>.md)")
    ap.add_argument("--write", action="store_true", help="apply the repair to vi/Label.txt")
    args = ap.parse_args()

    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    label_path = project.data_dir / "labels" / book.book_id / "vi" / "Label.txt"
    pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
    stamps = {p: p.stat().st_mtime_ns for p in (csv_path, label_path)}
    rows, _issues = load_rows_with_metadata(csv_path)
    vi_labels = read_label_txt(label_path)
    patch_path = project.data_dir / "review" / f"{book.book_id}.patches.jsonl"
    edited = {p.sentence_id for p in read_patches(patch_path) if p.field == "vi_txt"} if patch_path.exists() else set()

    before = span_mismatches(pairs, vi_labels, rows)
    bad_rows = sorted({i for i, _, _ in before})
    new_labels, changed = respace_vi_rows(pairs, vi_labels, rows, bad_rows)
    after = span_mismatches(pairs, new_labels, rows)
    n_edited = sum(1 for i in changed if rows[i].sentence_id in edited)

    report = Path(args.report) if args.report else project.data_dir / "diagnostics" / "label_spacing" / f"{book.book_id}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# vi/Label.txt spacing repair — {book.book_id}", "",
             f"Rows changed: {len(changed)} (reviewer-edited: {n_edited}, never edited: {len(changed) - n_edited})", ""]
    for i in changed:
        r = rows[i]
        old = " ‖ ".join(lbl for k, lbl, _ in before if k == i)
        new = " ‖ ".join(csv for k, _, csv in before if k == i)
        lines += [f"## {r.sentence_id}{'' if r.sentence_id in edited else '  (never edited)'}", "",
                  f"- Label.txt now: `{old}`", f"- after repair:  `{new}`", ""]
    report.write_text("\n".join(lines), encoding="utf-8")

    print(f"{book.book_id}: rows whose Label span differs from the CSV: {len(bad_rows)}; "
          f"repaired in memory: {len(changed)} (edited {n_edited}, never edited {len(changed) - n_edited}); "
          f"still differing after repair: {len({i for i, _, _ in after})}")
    print(f"  junctions before: {junction_issues(vi_labels)}  after: {junction_issues(new_labels)}")
    print(f"  report: {report}")
    if not args.write or not changed:
        return 0

    for p, t in stamps.items():
        if p.stat().st_mtime_ns != t:
            print(f"ABORT: {p} changed on disk while the tool ran; nothing written.")
            return 2
    atomic_save_labels(new_labels, label_path, "vi")
    reread = read_label_txt(label_path)
    dicts = [{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in rows]
    errors = check_sync(dicts, None, reread, pairs)
    remaining = span_mismatches(pairs, reread, rows)
    print(f"  written {label_path} (backup .bak-review); SYNC errors: {len(errors)}; "
          f"span mismatches left: {len({i for i, _, _ in remaining})}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
