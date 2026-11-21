"""Apply alignment.text_diff_warn_rules to the CSVs that already exist, and
carry the reviewers' decisions over to the new colouring.

A rule (e.g. 秋 <-> "su" in 支秋 = Giê-su, agreed with the teaching assistant)
turns a one-char / one-syllable red element into a reviewed yellow one. The
align stage applies the rules itself from now on; this tool updates the
current CSV + review metadata without re-aligning, and for every row that
already had a valid decision it appends a new decision on the new content
(same reviewer; accepted_match when no red is left, otherwise the previous
verdict), with the reason naming the rule. Rows whose text_diff was edited by
a reviewer are reported, never changed.

    python tools/apply_warn_rules.py [--book ID] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.models import DiffElement  # noqa: E402
from hannom.review.edit import atomic_save_csv  # noqa: E402
from hannom.review.patches import apply_patches_checked, read_patches  # noqa: E402
from hannom.review_decisions import (  # noqa: E402
    append_decision, apply_decisions, decision_path, make_decision, parse_decisions,
)
from hannom.review_metadata import load_rows_with_metadata  # noqa: E402
from hannom.textdiff import _SPEC_VI_TOKEN_RE, tone_key, warn_rules_from_config  # noqa: E402

REASON = "Quy tắc vàng của trợ giảng (alignment.text_diff_warn_rules), áp dụng hàng loạt"


def convert(elements, rules):
    out, changed = [], 0
    for el in elements or []:
        toks = _SPEC_VI_TOKEN_RE.findall(el.vi_sub_text)
        if (el.type == "error" and len(el.nom_sub_text) == 1 and len(toks) == 1
                and (el.nom_sub_text, tone_key(toks[0])) in rules):
            el = DiffElement(el.nom_pos, el.nom_sub_text, el.vi_pos, el.vi_sub_text, "warn", reviewed=1)
            changed += 1
        out.append(el)
    return out, changed


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", action="append")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    rules = set(warn_rules_from_config(project.alignment_config))
    if not rules:
        print("no alignment.text_diff_warn_rules configured")
        return 1
    for book in project.books:
        if args.book and book.book_id not in args.book:
            continue
        csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
        rows, _issues = load_rows_with_metadata(csv_path)
        patches = read_patches(project.data_dir / "review" / f"{book.book_id}.patches.jsonl")
        rows, _rej = apply_patches_checked(rows, patches)
        dpath = decision_path(project.data_dir, book.book_id)
        decisions, failures, dissues = parse_decisions(dpath)
        rows, _di, _audit = apply_decisions(rows, decisions, dissues, failures=failures)
        last_reviewer = {d.sentence_id: d.reviewer for d in decisions}
        diff_edited = {p.sentence_id for p in patches if p.field == "text_diff"}
        n_el = n_rows = n_dec = 0
        skipped = []
        new_decisions = []
        for row in rows:
            new_diff, k = convert(row.text_diff, rules)
            if not k:
                continue
            if row.sentence_id in diff_edited:
                skipped.append(row.sentence_id)
                continue
            status = getattr(row, "review_status", None)
            valid = getattr(row, "decision_integrity", None) == "valid"
            row.text_diff = new_diff
            row.flags = sorted(set(row.flags) | {"DIFF_WARN_RULE"})
            n_el += k
            n_rows += 1
            if status and valid:
                has_red = any(e.type == "error" for e in new_diff)
                new_status = "accepted_match" if (status in ("accepted_match", "accepted_difference") and not has_red) else status
                new_decisions.append(make_decision(
                    book_id=book.book_id, sentence_id=row.sentence_id, status=new_status,
                    reviewer=last_reviewer.get(row.sentence_id, "rule"), reason=REASON,
                    ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json(),
                ))
                n_dec += 1
        print(f"{book.book_id}: {n_el} element(s) -> yellow in {n_rows} row(s); "
              f"{n_dec} decision(s) carried over; skipped (reviewer-edited text_diff): {skipped[:10]}")
        if args.dry_run or not n_rows:
            continue
        atomic_save_csv(csv_path, rows)
        for d in new_decisions:
            append_decision(dpath, d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
