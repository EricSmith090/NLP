"""Re-apply reviewer text edits to Label.txt after the pipeline regenerated it.

Reviewer edits (data/review/<book>.patches.jsonl) change Label.txt and the
CSV together. Re-running `labels --overwrite-reviewed` rebuilds Label.txt from
OCR (the edits are gone from it) while `align` re-applies the patches to the
CSV, so the two disagree (SYNC). This tool restores agreement: for every row
whose text equals a patch's `after`, it puts the row back to the patch's
`before` (which matches the regenerated Label.txt), then replays the edit with
the review app's `apply_row_edit`, which edits Label.txt and the row together
and checks SYNC. Patches whose `before` no longer matches the regenerated text
are reported, never forced.

    python -m hannom.cli labels --book X --overwrite-reviewed
    python -m hannom.cli clean --book X
    python -m hannom.cli align --book X
    python tools/replay_review_edits.py --book X
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.review.edit import EditError, apply_row_edit, atomic_save_csv, atomic_save_labels, normalize_cell, recompute_row_diff  # noqa: E402
from hannom.review.patches import read_patches  # noqa: E402
from hannom.review_metadata import load_rows_with_metadata  # noqa: E402
from hannom.sync_check import check_sync  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    label_dir = project.data_dir / "labels" / book.book_id
    pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
    rows, _issues = load_rows_with_metadata(csv_path)
    ch_labels = read_label_txt(label_dir / "ch" / "Label.txt")
    vi_labels = read_label_txt(label_dir / "vi" / "Label.txt")

    try:  # same lexicon / dictionary / readings the align stage uses
        from hannom.dictionary.book_lexicon import BookLexicon
        from hannom.dictionary.index import build_dictionary_index
        from hannom.orchestrator import load_readings_cache

        context = {
            "lexicon": BookLexicon(project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json"),
            "dictionary": build_dictionary_index(project.root, project.dictionary_config or {}, book_id=book.book_id),
            "readings_cache": load_readings_cache(project),
            "warn_rules": __import__("hannom.textdiff", fromlist=["x"]).warn_rules_from_config(project.alignment_config),
            "suggest_rules": __import__("hannom.textdiff", fromlist=["x"]).suggest_rules_from_config(
                project.alignment_config, book.book_id),
            "name_blocks": __import__("hannom.textdiff", fromlist=["x"]).name_blocks_from_config(
                project.alignment_config, book.book_id),
        }
        context["name_spellings"] = __import__("hannom.textdiff", fromlist=["x"]).name_spellings_from_config(
            project.alignment_config, book.book_id, ((r.ch_txt, r.vi_txt) for r in rows),
            lexicon=context["lexicon"], dictionary=context["dictionary"], readings_cache=context["readings_cache"])
    except Exception:  # noqa: BLE001
        context = {}

    def sync_errors(rs):
        return check_sync([{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in rs],
                          ch_labels, vi_labels, pairs)

    if not sync_errors(rows):
        print(f"{book.book_id}: Label.txt and CSV already in SYNC; nothing to replay")
        return 0
    patches = sorted((p for p in read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
                      if p.field in ("ch_txt", "vi_txt") and p.before != p.after), key=lambda p: str(p.timestamp))
    # 1) Undo, newest first, every edit align already put into the CSV, so the
    #    rows match the regenerated Label.txt again (chains like A->B->C unwind).
    for p in reversed(patches):
        for r in rows:
            cur = getattr(r, p.field)
            if p.after and p.after in cur:
                setattr(r, p.field, cur.replace(p.after, p.before, 1))
                break
    if sync_errors(rows):
        print(f"{book.book_id}: still out of SYNC after undoing the edits; not touching anything:")
        print("  " + sync_errors(rows)[0])
        return 1
    # 2) Replay, oldest first, by substring: the row that now contains the
    #    edited span gets it replaced (works when re-segmentation moved the
    #    sentence boundaries around the span). Ambiguous or missing spans are
    #    reported, never guessed.
    replayed = 0
    for p in patches:
        hits = [i for i, r in enumerate(rows) if p.before and p.before in getattr(r, p.field)]
        if len(hits) != 1:
            print(f"  NOT replayed ({'not found' if not hits else 'ambiguous'}): {p.sentence_id} {p.field} "
                  f"{p.before[:40]!r} -> {p.after[:40]!r}")
            continue
        i = hits[0]
        new_text = normalize_cell(getattr(rows[i], p.field).replace(p.before, p.after, 1), p.field)
        try:
            ch_labels, vi_labels, rows = apply_row_edit(
                pairs, ch_labels, vi_labels, rows, i,
                new_ch=new_text if p.field == "ch_txt" else None,
                new_vi=new_text if p.field == "vi_txt" else None,
            )
        except EditError as exc:
            print(f"  replay failed for {p.sentence_id} {p.field}: {exc}")
            return 1
        recompute_row_diff(rows[i], **context)
        replayed += 1
        print(f"  replayed {p.sentence_id} {p.field} into {rows[i].sentence_id}")
    applied = range(replayed)
    atomic_save_labels(ch_labels, label_dir / "ch" / "Label.txt", "ch")
    atomic_save_labels(vi_labels, label_dir / "vi" / "Label.txt", "vi")
    atomic_save_csv(csv_path, rows)
    print(f"{book.book_id}: {len(applied)} edit(s) replayed; SYNC errors now: {len(sync_errors(rows))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
