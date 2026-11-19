"""Per-pair QN quality report and RC10 detection (Doc/FIX_PLAN_v24.md T2.2 / T2.4).

Reads data/clean (both scripts) and the image map; writes
data/diagnostics/qn_quality/<book>.json and .csv (sorted by recall, i.e. the
proofreading queue) and prints the Nôm pages whose box order should be
reversed (candidates for `nom_reversed_pages` in configs/books/<book>.yaml).
No network, no GPU.

    python tools/qn_quality.py [--book T1_CamPhong_Tap2]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.config import load_config  # noqa: E402
from hannom.orchestrator import load_cleaned_pages, load_readings_cache  # noqa: E402
from hannom.qnquality import (  # noqa: E402
    boxes_from_clean,
    classify,
    nom_chars,
    page_quality,
    reading_keys,
    reversed_order_gain,
    summarize,
)
from hannom.t1_map import load_image_map  # noqa: E402


def page_no(image_name: str) -> int:
    return int(image_name.rsplit(".", 2)[-2])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", action="append")
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    readings = load_readings_cache(project)
    if readings is None:
        raise SystemExit("readings cache unavailable (data/dictionary/char_readings.json)")
    keys = reading_keys(readings)
    out_dir = project.data_dir / "diagnostics" / "qn_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    status = 0
    for book in project.books:
        if args.book and book.book_id not in args.book:
            continue
        pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
        cleaned = load_cleaned_pages(project, book)
        listed = set(book.nom_reversed_pages)
        rows = []
        for pair in pairs:
            if not pair.ch or not pair.vi:
                continue
            qn = " ".join(cleaned[v].text for v in pair.vi if v in cleaned)
            nom = [c for ch in pair.ch if ch in cleaned for c in nom_chars(cleaned[ch].text)]
            q = page_quality(qn, nom, keys)
            rev = None
            if len(pair.ch) == 1 and pair.ch[0] in cleaned:
                page = cleaned[pair.ch[0]]
                rev = reversed_order_gain(qn, boxes_from_clean(page.lines, page.line_sources), keys)
            row = {
                "vi": [page_no(v) for v in pair.vi],
                "ch": [page_no(c) for c in pair.ch],
                **q,
                "recall_reversed": round(rev[1], 3) if rev else None,
                "listed_reversed": any(page_no(c) in listed for c in pair.ch),
            }
            row["queue"] = classify(q, rev)
            rows.append(row)
        rows.sort(key=lambda r: (r["recall"] if r["recall"] is not None else -1))
        (out_dir / f"{book.book_id}.json").write_text(
            json.dumps({"summary": summarize(rows), "pairs": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        with (out_dir / f"{book.book_id}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["vi"])
            w.writeheader()
            for r in rows:
                w.writerow({k: (" ".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})
        s = summarize(rows)
        new_rev = sorted(c for r in rows if r["queue"] == "nom_reversed" for c in r["ch"] if c not in listed)
        print(f"{book.book_id}: pairs={s['pairs']} weighted_recall={s['weighted_recall']} queues={s['queues']}")
        if new_rev:
            status = 1
            print(f"  NEW reversed Nôm pages (add to nom_reversed_pages): {new_rev}")
        low = [f"vi{r['vi'][0]}/ch{r['ch'][0]}={r['recall']}" for r in rows if r["queue"] == "manual_qn"]
        if low:
            print(f"  manual_qn ({len(low)}): {', '.join(low[:20])}{' …' if len(low) > 20 else ''}")
    print(f"reports: {out_dir}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
