"""Partner-aware QN rescue (Doc/FIX_PLAN_v24.md T2.1 retry policy, step 2).

For the listed QN pages (default: every pair in the `manual_qn` queue of
data/diagnostics/qn_quality/<book>.json), re-read the page with Vintern-1B-v3.5
on two 15 %-overlapping halves and keep the halves text only if its phonetic
recall against the Nôm partner page is higher by at least --min-gain. The new
result is written as the page's OCR JSON (warning QN_RESCUED_HALVES, both
candidates' scores in raw). Local GPU only; never calls the Kim Hán Nôm API.
Re-run labels -> clean -> align afterwards.

    python tools/qn_rescue.py --book T1_CamPhong_Tap1 [--pages 15 69] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from hannom.config import load_config  # noqa: E402
from hannom.ocr.local_vintern import Vintern35Engine, qn_text_quality, stitch_overlapping  # noqa: E402
from hannom.ocr.router import OCRRouter  # noqa: E402
from hannom.orchestrator import load_cleaned_pages, load_readings_cache, open_state  # noqa: E402
from hannom.qnquality import nom_chars, page_quality, reading_keys  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402


def page_no(image_name: str) -> int:
    return int(image_name.rsplit(".", 2)[-2])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", type=int, nargs="*", help="QN PDF page numbers (default: manual_qn queue)")
    ap.add_argument("--min-gain", type=float, default=0.10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    keys = reading_keys(load_readings_cache(project))
    cleaned = load_cleaned_pages(project, book)
    pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
    partner = {page_no(v): pair.ch for pair in pairs for v in pair.vi if pair.ch}
    targets = args.pages
    if not targets:
        report = json.loads((project.data_dir / "diagnostics" / "qn_quality" / f"{book.book_id}.json").read_text(encoding="utf-8"))
        targets = [r["vi"][0] for r in report["pairs"] if r["queue"] == "manual_qn" and len(r["vi"]) == 1]
    engine = Vintern35Engine()
    with open_state(project) as state:
        router = OCRRouter(project, book, state)
        pages = {p.page_no: p for p in state.pages(book.book_id)}
        for n in targets:
            page = pages.get(n)
            if page is None or n not in partner:
                print(f"p{n}: no QN page or no Nôm partner; skipped")
                continue
            current = router.load_result(page)
            if current is None:
                print(f"p{n}: no cached OCR; skipped")
                continue
            nom = [c for ch in partner[n] if ch in cleaned for c in nom_chars(cleaned[ch].text)]
            old_text = "\n".join(line.text for line in current.lines)
            old_q = page_quality(old_text, nom, keys)
            parts, infos = engine._halves(page)
            new_text = stitch_overlapping(parts)
            new_q = page_quality(new_text, nom, keys)
            gain = (new_q["recall"] or 0) - (old_q["recall"] or 0)
            keep = gain >= args.min_gain
            print(f"p{n}: recall {old_q['recall']} -> {new_q['recall']} (coverage {old_q['coverage']} -> "
                  f"{new_q['coverage']}) {'KEEP' if keep else 'no change'}")
            if keep and not args.dry_run:
                line = replace(current.lines[0], text=new_text) if current.lines else None
                result = replace(
                    current,
                    lines=[line] if line else [],
                    warnings=sorted(set(current.warnings) | {"QN_RESCUED_HALVES"}),
                    raw=dict(current.raw or {}, rescue={
                        "method": "halves_by_partner_recall", "old": old_q, "new": new_q,
                        "halves": [qn_text_quality(p) for p in parts], "part_info": infos,
                    }),
                    cached=False,
                )
                router.save_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
