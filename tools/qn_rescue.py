"""Partner-aware QN rescue (Doc/FIX_PLAN_v24.md T2.1 retry policy, step 2).

For each selected QN page, build candidate transcriptions and keep the one
whose phonetic recall against the Nôm partner page is highest (precision
breaks ties), if it beats the current text:
  * current text with adjacent repeated spans removed (loop / seam artefacts),
  * (GPU) a fresh Vintern-1B-v3.5 reading on two 15 %-overlapping halves,
    and the same with adjacent repeats removed.
The kept result is written as the page's OCR JSON (warning QN_RESCUED_*, all
candidates' scores in raw). Local only; never calls the Kim Hán Nôm API.
Re-run labels -> clean -> align afterwards.

    python tools/qn_rescue.py --book T1_CamPhong_Tap1                 # manual_qn queue, with GPU
    python tools/qn_rescue.py --book T1_CamPhong_Tap2 --repeats       # pages with a repeated 12-word span
    python tools/qn_rescue.py --book T1_CamPhong_Tap2 --repeats --no-gpu
    python tools/qn_rescue.py --book T1_CamPhong_Tap2 --pages 152 154 --dry-run
    python tools/qn_rescue.py --book T1_CamPhong_Tap1 --restitch            # re-join kept halves (no GPU)

--restitch re-joins the two halves of pages already rescued with "halves"
using the current stitch_overlapping (the seam read twice slightly
differently used to be kept twice). The halves are taken from raw.rescue.parts
or, for older results, split back by the first half's syllable count.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from hannom.config import load_config  # noqa: E402
from hannom.ocr.local_vintern import dedupe_adjacent_repeats, qn_text_quality, stitch_overlapping  # noqa: E402
from hannom.ocr.router import OCRRouter  # noqa: E402
from hannom.orchestrator import load_cleaned_pages, load_readings_cache, open_state  # noqa: E402
from hannom.qnquality import nom_chars, page_quality, reading_keys  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402

SYL = re.compile(r"[^\W\d_]+")


def page_no(image_name: str) -> int:
    return int(image_name.rsplit(".", 2)[-2])


def max_repeat(text: str, n: int = 12) -> int:
    w = [x.lower() for x in SYL.findall(text or "")]
    c = collections.Counter(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    return max(c.values()) if c else 0


def better(cand: dict, best: dict) -> bool:
    if cand["recall"] is None:
        return False
    if best["recall"] is None or cand["recall"] > best["recall"] + 0.005:
        return True
    return abs(cand["recall"] - best["recall"]) <= 0.005 and (cand["precision"] or 0) > (best["precision"] or 0) + 0.01


def _split_halves(text: str, info: list) -> list[str] | None:
    """The two halves of a stitched text in which nothing was removed at the
    seam (syllable counts of the parts add up), split after the first part."""
    from hannom.ocr.local_vintern import _SYLLABLE_RE

    if not info or len(info) != 2:
        return None
    n0, n1 = int(info[0].get("syllables") or 0), int(info[1].get("syllables") or 0)
    matches = list(_SYLLABLE_RE.finditer(text))
    if not n0 or len(matches) != n0 + n1:
        return None
    end = matches[n0 - 1].end()
    ws = re.search(r"\s", text[end:])
    cut = end + ws.start() if ws else len(text)
    return [text[:cut], text[cut:]]


def restitch(args, pages, partner, cleaned, keys, router) -> int:
    targets = sorted(set(args.pages or [])) or sorted(pages)
    kept = 0
    for n in targets:
        page = pages.get(n)
        current = router.load_result(page) if page is not None and n in partner else None
        rescue = (current.raw or {}).get("rescue") if current is not None else None
        if not rescue or rescue.get("method") != "halves" or not current.lines:
            continue
        text = current.lines[0].text
        parts = rescue.get("parts") or _split_halves(text, rescue.get("part_info"))
        if not parts:
            print(f"p{n}: halves cannot be recovered (seam already joined); skipped")
            continue
        new_text = stitch_overlapping(parts)
        if new_text == text:
            print(f"p{n}: seam already clean")
            continue
        nom = [c for ch in partner[n] if ch in cleaned for c in nom_chars(cleaned[ch].text)]
        before = rescue.get("candidates", {}).get("current") or {}
        old_q, new_q = page_quality(text, nom, keys), page_quality(new_text, nom, keys)
        verdict = "KEEP restitched" if better(new_q, before) or (new_q["recall"] or 0) >= (before.get("recall") or 0) else             "WORSE than the pre-rescue text"
        print(f"p{n}: pre-rescue {before.get('recall')}/{before.get('precision')}, halves {old_q['recall']}/"
              f"{old_q['precision']}, restitched {new_q['recall']}/{new_q['precision']} "
              f"({len(text.split())} -> {len(new_text.split())} words) -> {verdict}")
        if args.dry_run or not verdict.startswith("KEEP"):
            continue
        line = replace(current.lines[0], text=new_text)
        router.save_result(replace(
            current, lines=[line],
            warnings=sorted(set(current.warnings) | {"QN_RESCUED_HALVES_RESTITCHED"}),
            raw=dict(current.raw or {}, rescue=dict(rescue, parts=parts, restitched=new_q,
                                                    quality=qn_text_quality(new_text))),
            cached=False,
        ))
        kept += 1
    print(f"{args.book}: {kept} page(s) re-stitched")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", type=int, nargs="*", help="QN PDF page numbers")
    ap.add_argument("--repeats", action="store_true", help="select pages with a repeated 12-word span")
    ap.add_argument("--no-gpu", action="store_true", help="only try removing adjacent repeats")
    ap.add_argument("--gpu-below", type=float, default=0.86,
                    help="with --repeats: read halves on the GPU only when recall is below this")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--restitch", action="store_true", help="re-join already rescued halves pages (no GPU)")
    args = ap.parse_args()
    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    keys = reading_keys(load_readings_cache(project))
    cleaned = load_cleaned_pages(project, book)
    pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
    partner = {page_no(v): pair.ch for pair in pairs for v in pair.vi if pair.ch}
    engine = None
    with open_state(project) as state:
        router = OCRRouter(project, book, state)
        pages = {p.page_no: p for p in state.pages(book.book_id)}
        targets = list(args.pages or [])
        if args.repeats:
            for n, page in sorted(pages.items()):
                res = router.load_result(page) if str(page.folder) in {"vi", "intro", "toc", "ref"} else None
                if res and res.lines and max_repeat(res.lines[0].text) >= 2:
                    targets.append(n)
        if not targets:
            report = json.loads((project.data_dir / "diagnostics" / "qn_quality" / f"{book.book_id}.json").read_text(encoding="utf-8"))
            targets = [r["vi"][0] for r in report["pairs"] if r["queue"] == "manual_qn" and len(r["vi"]) == 1]
        if args.restitch:
            return restitch(args, pages, partner, cleaned, keys, router)
        kept = 0
        for n in sorted(set(targets)):
            page = pages.get(n)
            if page is None or n not in partner:
                print(f"p{n}: no QN page or no Nôm partner; skipped")
                continue
            current = router.load_result(page)
            if current is None or not current.lines:
                print(f"p{n}: no cached OCR; skipped")
                continue
            nom = [c for ch in partner[n] if ch in cleaned for c in nom_chars(cleaned[ch].text)]
            old_text = current.lines[0].text
            scored = {"current": (old_text, page_quality(old_text, nom, keys))}
            dedup, k = dedupe_adjacent_repeats(old_text)
            if k:
                scored["current_dedup"] = (dedup, page_quality(dedup, nom, keys))
            use_gpu = not args.no_gpu and (not args.repeats or (scored["current"][1]["recall"] or 0) < args.gpu_below)
            infos = None
            if use_gpu:
                if engine is None:
                    from hannom.ocr.local_vintern import Vintern35Engine

                    engine = Vintern35Engine()
                parts, infos = engine._halves(page)
                halves = stitch_overlapping(parts)
                scored["halves"] = (halves, page_quality(halves, nom, keys))
                hd, hk = dedupe_adjacent_repeats(halves)
                if hk:
                    scored["halves_dedup"] = (hd, page_quality(hd, nom, keys))
            best_name = "current"
            for name, (_t, q) in scored.items():
                if name != "current" and better(q, scored[best_name][1]):
                    best_name = name
            summary = ", ".join(f"{name} {q['recall']}/{q['precision']}" for name, (_t, q) in scored.items())
            print(f"p{n}: {summary} -> {'KEEP ' + best_name if best_name != 'current' else 'no change'}")
            if best_name == "current" or args.dry_run:
                continue
            new_text = scored[best_name][0]
            line = replace(current.lines[0], text=new_text)
            result = replace(
                current,
                lines=[line],
                warnings=sorted(set(current.warnings) | {f"QN_RESCUED_{best_name.upper()}"}),
                raw=dict(current.raw or {}, rescue={
                    "method": best_name,
                    "candidates": {name: q for name, (_t, q) in scored.items()},
                    "quality": qn_text_quality(new_text),
                    "part_info": infos,
                    "parts": parts if best_name.startswith("halves") else None,
                }),
                cached=False,
            )
            router.save_result(result)
            kept += 1
        print(f"{book.book_id}: {kept} page(s) updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
