"""Catalogue of the glyphs written as 〓 (Quy định v2.4: report every 〓 with
its position and a description of the glyph's composition).

For every original code point that the clean stage turns into 〓 (mostly Kim
Hán Nôm private-use codes such as U+F047C) this writes, under
data/diagnostics/placeholders/:
  * catalog.csv / catalog.html: per code — occurrences per book, the QN
    syllables most often facing it in the CSV, dictionary readings recorded
    for the code, dictionary entries listing it as a form of a standard
    character (candidate Unicode equivalent for configs/khn_pua_map.yaml),
    example contexts, and glyph crops;
  * <code>/<book>_<page>_<k>.png: approximate crops of the glyph from the
    page scan (position estimated inside the OCR box; check visually);
  * placeholder_descriptions.yaml: a skeleton to copy into
    configs/report.yaml once a reviewer has described each glyph.
Reads data/ and the dictionary entries only; no network, no GPU.

    python tools/placeholder_catalog.py [--book ID] [--crops 6]
"""

from __future__ import annotations

import argparse
import collections
import csv
import html
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.align import read_alignment_csv  # noqa: E402
from hannom.clean import is_safe_codepoint, nfc, pua_map  # noqa: E402
from hannom.config import load_config  # noqa: E402
from hannom.orchestrator import load_cleaned_pages  # noqa: E402
from hannom.placeholders import assign_origins, stream_origins  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402

PLACEHOLDER = "〓"


def code_of(ch: str) -> str:
    return f"U+{ord(ch):04X}"


def char_of(code: str) -> str:
    try:
        return chr(int(code[2:], 16)) if code.startswith("U+") else ""
    except ValueError:
        return ""


def becomes_placeholder(ch: str) -> bool:
    if ch == PLACEHOLDER:
        return True
    if pua_map.is_enabled() and pua_map.mapped_pua(ch) is not None:
        return False
    return not is_safe_codepoint(ch)


def page_no(image_name: str) -> int:
    return int(image_name.rsplit(".", 2)[-2])


def glyph_box(points, index: int, count: int, reversed_page: bool):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    vertical = (y1 - y0) >= (x1 - x0)
    if reversed_page:  # upside-down scan: reading order runs bottom -> top
        index = count - 1 - index
    if vertical:
        step = (y1 - y0) / max(1, count)
        a, b = y0 + step * index, y0 + step * (index + 1)
        pad = step * 0.15
        return x0 - pad, a - pad, x1 + pad, b + pad
    step = (x1 - x0) / max(1, count)
    a, b = x0 + step * index, x0 + step * (index + 1)
    pad = step * 0.15
    return a - pad, y0 - pad, b + pad, y1 + pad


def dictionary_hits(entries_dir: Path, codes: set[str]) -> dict[str, list[str]]:
    """Dictionary records whose text mentions a code: '<file>: head=<head> reading=<r>'."""
    chars = {char_of(c): c for c in codes if char_of(c) and c != "U+3013"}
    hits: dict[str, list[str]] = collections.defaultdict(list)
    if not entries_dir.exists():
        return hits
    for f in sorted(entries_dir.glob("*.jsonl")):
        if "catusf" in f.name:
            continue
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                found = [c for c in chars if c in line]
                if not found:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                head = str(rec.get("head") or "")
                reading = rec.get("readings") or rec.get("qn") or ""
                for c in found:
                    if len(hits[chars[c]]) < 8:
                        hits[chars[c]].append(f"{f.stem}: head={head} reading={reading}"[:160])
    return hits


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", action="append")
    ap.add_argument("--crops", type=int, default=6, help="example crops per code and book")
    args = ap.parse_args()
    from PIL import Image

    project = load_config(ROOT / args.config)
    out_dir = project.data_dir / "diagnostics" / "placeholders"
    out_dir.mkdir(parents=True, exist_ok=True)
    readings = json.loads((project.data_dir / "dictionary" / "char_readings.json").read_text(encoding="utf-8"))
    rtab = {**readings.get("word", {}), **readings.get("char", {})}
    stats: dict[str, dict] = collections.defaultdict(lambda: {
        "books": collections.Counter(), "facing": collections.Counter(), "contexts": [], "crops": []})
    for book in project.books:
        if args.book and book.book_id not in args.book:
            continue
        pairs = load_image_map(project.data_dir / "layout" / book.book_id / "image_map.json")
        cleaned = load_cleaned_pages(project, book)
        reversed_pages = set(book.nom_reversed_pages)
        # 1) occurrences + crops from the raw OCR boxes
        crops_done: collections.Counter = collections.Counter()
        for pair in pairs:
            for image in pair.ch:
                n = page_no(image)
                ocr = project.data_dir / "ocr" / book.book_id / f"{n:04d}.json"
                if not ocr.exists():
                    continue
                data = json.loads(ocr.read_text(encoding="utf-8"))
                img = None
                for line in data.get("lines", []):
                    chars = [c for c in nfc(line.get("text", "")) if not c.isspace()]
                    for i, ch in enumerate(chars):
                        if not becomes_placeholder(ch):
                            continue
                        code = code_of(ch)
                        st = stats[code]
                        st["books"][book.book_id] += 1
                        if len(st["contexts"]) < 6:
                            ctx = "".join(chars[max(0, i - 4):i]) + "[〓]" + "".join(chars[i + 1:i + 5])
                            st["contexts"].append(f"{book.book_id} p{n}: {ctx}")
                        if crops_done[(book.book_id, code)] >= args.crops:
                            continue
                        if img is None:
                            src = next((project.data_dir / "pages" / book.book_id / "native").glob(f"*.{n:03d}.jpg"), None)
                            if src is None:
                                break
                            img = Image.open(src).convert("RGB")
                        box = glyph_box(line["points"], i, len(chars), n in reversed_pages)
                        crop = img.crop(tuple(int(v) for v in box))
                        if n in reversed_pages:
                            crop = crop.rotate(180)
                        crop = crop.resize((max(1, crop.width * 3), max(1, crop.height * 3)))
                        dest = out_dir / code / f"{book.book_id}_{n}_{crops_done[(book.book_id, code)]}.png"
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        crop.save(dest)
                        st["crops"].append(dest.relative_to(out_dir).as_posix())
                        crops_done[(book.book_id, code)] += 1
        # 2) QN syllables facing each code in the current CSV
        csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
        if csv_path.exists():
            rows = read_alignment_csv(csv_path)
            recs, _problems = assign_origins(rows, stream_origins(pairs, cleaned))
            by_sid = {r.sentence_id: r for r in rows}
            for rec in recs:
                row = by_sid.get(rec["sentence_id"])
                for el in (row.text_diff or []) if row else []:
                    if any(a <= rec["position"] < b for a, b in el.nom_pos):
                        stats[rec["code"]]["facing"][el.vi_sub_text.lower() or "(none)"] += 1
    dcfg = (project.dictionary_config or {}).get("dictionary", project.dictionary_config or {}) or {}
    hits = dictionary_hits(ROOT / str(dcfg.get("entries_dir", "dictionaries/entries")), set(stats))
    order = sorted(stats, key=lambda c: -sum(stats[c]["books"].values()))
    with (out_dir / "catalog.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "total", "per_book", "dict_readings", "facing_qn_top", "dictionary_entries", "contexts", "crops"])
        for code in order:
            st = stats[code]
            ch = char_of(code)
            w.writerow([
                code, sum(st["books"].values()), json.dumps(dict(st["books"]), ensure_ascii=False),
                " ".join(rtab.get(ch, [])[:6]), "; ".join(f"{k}×{v}" for k, v in st["facing"].most_common(5)),
                " | ".join(hits.get(code, [])), " | ".join(st["contexts"]), " ".join(st["crops"]),
            ])
    parts = ["<!doctype html><meta charset='utf-8'><title>〓 catalog</title>",
             "<style>body{font-family:sans-serif;margin:16px}td,th{border:1px solid #ccc;padding:4px;vertical-align:top}"
             "table{border-collapse:collapse}img{height:72px;margin:2px;border:1px solid #999}</style>",
             "<h1>Glyphs written as 〓</h1><p>Crops are estimated from the OCR box; confirm on the scan.</p>",
             "<table><tr><th>code</th><th>count</th><th>facing QN</th><th>dictionary</th><th>contexts</th><th>crops</th></tr>"]
    for code in order:
        st = stats[code]
        ch = char_of(code)
        parts.append(
            f"<tr><td>{code}</td><td>{sum(st['books'].values())}<br>{html.escape(json.dumps(dict(st['books'])))}</td>"
            f"<td>{html.escape('; '.join(f'{k}×{v}' for k, v in st['facing'].most_common(5)))}</td>"
            f"<td>{html.escape(' '.join(rtab.get(ch, [])[:6]))}<br>{'<br>'.join(html.escape(h) for h in hits.get(code, []))}</td>"
            f"<td>{'<br>'.join(html.escape(c) for c in st['contexts'])}</td>"
            f"<td>{''.join(f'<img src={chr(34)}{c}{chr(34)}>' for c in st['crops'])}</td></tr>"
        )
    parts.append("</table>")
    (out_dir / "catalog.html").write_text("\n".join(parts), encoding="utf-8")
    skeleton = ["placeholder_descriptions:"] + [
        f'  "{code}": ""   # {sum(stats[code]["books"].values())}× ; facing: '
        + ", ".join(k for k, _ in stats[code]["facing"].most_common(3))
        for code in order
    ]
    (out_dir / "placeholder_descriptions.yaml").write_text("\n".join(skeleton) + "\n", encoding="utf-8")
    print(f"{len(order)} codes, {sum(sum(s['books'].values()) for s in stats.values())} occurrences")
    for code in order[:12]:
        st = stats[code]
        print(f"  {code} ×{sum(st['books'].values())} facing {st['facing'].most_common(3)} dict={rtab.get(char_of(code), [])[:3]} entries={len(hits.get(code, []))}")
    print(f"catalog: {out_dir / 'catalog.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
