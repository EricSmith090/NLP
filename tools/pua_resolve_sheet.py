"""Sheet for resolving 〓 (Kim Hán Nôm private-use codes) by eye.

The API returns a private-use code for some glyphs; the pipeline writes 〓
and the pair stays red. A suggestion rule needs the real character, which
only the page image shows. For every red 〓 <-> one syllable this tool
groups the occurrences by (original code, syllable) and writes a local HTML
page: print crops of up to N occurrences next to the characters the
dictionaries read as that syllable (most used in the book first). The
reviewer picks the candidate whose shape is the printed glyph (or "none"),
and downloads the choices as JSON; a human-checked choice becomes a
text_diff_suggest_rules entry, each occurrence still accepted on its crop.

Read-only on the data; writes only data/diagnostics/pua_resolve/<book>/.
The page and crops are book scans: keep them on this machine.

    python tools/pua_resolve_sheet.py --book T1_CamPhong_Tap2 [--min 2] [--crops 8]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hannom.align import read_alignment_csv  # noqa: E402
from hannom.config import load_config  # noqa: E402
from hannom.dictionary.readings import norm_reading  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.orchestrator import load_cleaned_pages, load_readings_cache  # noqa: E402
from hannom.placeholders import PLACEHOLDER, assign_origins, stream_origins  # noqa: E402
from hannom.review.edit import nom_char_location, nom_stream_index  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402
from hannom.textdiff import tone_key  # noqa: E402

NOM_FONTS = ("'Nom Na Tong','HAN NOM A','HAN NOM B','Han-Nom Gothic','Han-Nom Ming','HanaMinA','HanaMinB',"
             "'SimSun-ExtB','SimSun-ExtG','MingLiU-ExtB',serif")


def reverse_readings(readings) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(reading -> chars, tone-insensitive key -> chars) from a Readings object."""
    exact: dict[str, set[str]] = defaultdict(set)
    loose: dict[str, set[str]] = defaultdict(set)
    for table in (readings.char, readings.word):
        for ch, values in table.items():
            if len(ch) != 1:
                continue
            for r in values:
                exact[r].add(ch)
                loose[tone_key(r)].add(ch)
    return exact, loose


def candidates_for(syllable: str, exact, loose, freq: Counter, limit: int = 24, loose_limit: int = 12):
    """[(char, 'exact'|'tone')] reading as ``syllable``; chars used most in the book first."""
    s = norm_reading(syllable)
    first = sorted(exact.get(s, set()), key=lambda c: (-freq[c], c))[:limit]
    rest = sorted(loose.get(tone_key(s), set()) - set(first) - exact.get(s, set()), key=lambda c: (-freq[c], c))
    return [(c, "exact") for c in first] + [(c, "tone") for c in rest[:loose_limit]]


def glyph_crop(image_path: Path, labels: dict, image_name: str, box: int, idx: int, count: int):
    """Same cell estimate as the review app (box split evenly), one cell of context each side."""
    from PIL import Image, ImageDraw

    boxes = labels.get(f"ch/{image_name}") or []
    if box >= len(boxes) or not image_path.exists() or count <= 0:
        return None
    pts = [tuple(float(v) for v in p) for p in (boxes[box].get("points") or [])]
    if len(pts) != 4:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (y1 - y0) >= (x1 - x0):
        step = (y1 - y0) / count
        cell = (x0, y0 + step * idx, x1, y0 + step * (idx + 1))
        region = (x0 - step * 0.4, cell[1] - step * 1.1, x1 + step * 0.4, cell[3] + step * 1.1)
    else:
        step = (x1 - x0) / count
        cell = (x0 + step * idx, y0, x0 + step * (idx + 1), y1)
        region = (cell[0] - step * 1.1, y0 - step * 0.4, cell[2] + step * 1.1, y1 + step * 0.4)
    image = Image.open(image_path).convert("RGB")
    ImageDraw.Draw(image).rectangle(cell, outline=(230, 0, 0), width=3)
    crop = image.crop(tuple(int(v) for v in region))
    scale = 200 / max(1, crop.height)
    return crop.resize((max(1, int(crop.width * scale)), 200))


def short_id(sentence_id: str) -> str:
    head, _, sent = sentence_id.rpartition(".")
    return f"{head.rpartition('.')[2]}.{sent}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--min", type=int, default=2, dest="minimum", help="smallest group shown (occurrences)")
    ap.add_argument("--crops", type=int, default=8, help="crops per group")
    args = ap.parse_args()

    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    data = project.data_dir
    rows = read_alignment_csv(data / "align" / book.book_id / f"{book.book_name}.csv")
    pairs = load_image_map(data / "layout" / book.book_id / "image_map.json")
    ch_labels = read_label_txt(data / "labels" / book.book_id / "ch" / "Label.txt")
    origins = stream_origins(pairs, load_cleaned_pages(project, book), ch_labels)
    records, problems = assign_origins(rows, origins)
    code_of = {(r["sentence_id"], r["position"]): r["code"] for r in records}
    for p in problems:
        print(f"warning: {p}")

    groups: dict[tuple[str, str], list[tuple[int, int, str]]] = defaultdict(list)
    shown_syllable: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for i, row in enumerate(rows):
        for el in row.text_diff or []:
            vi = (el.vi_sub_text or "").strip()
            if el.type != "error" or el.nom_sub_text != PLACEHOLDER or not vi.isalpha() or not el.nom_pos:
                continue
            pos = el.nom_pos[0][0]
            key = (code_of.get((row.sentence_id, pos), "unknown"), tone_key(vi))
            groups[key].append((i, pos, vi))
            shown_syllable[key][vi.lower()] += 1

    ordered = sorted(((k, v) for k, v in groups.items() if len(v) >= args.minimum), key=lambda kv: -len(kv[1]))
    print(f"{book.book_id}: red 〓 <-> syllable: {sum(len(v) for v in groups.values())} in {len(groups)} groups; "
          f"shown (>= {args.minimum}): {len(ordered)} groups, {sum(len(v) for _, v in ordered)} occurrences")

    readings = load_readings_cache(project)
    if readings is None:
        raise SystemExit("readings cache unavailable")
    exact, loose = reverse_readings(readings)
    freq = Counter(ch for r in rows for ch in (r.ch_txt or ""))
    out = data / "diagnostics" / "pua_resolve" / book.book_id
    (out / "crops").mkdir(parents=True, exist_ok=True)
    native = data / "pages" / book.book_id / "native"
    stream = nom_stream_index(pairs, ch_labels, rows)

    sections = []
    for g, ((code, key), occ) in enumerate(ordered):
        syl = shown_syllable[(code, key)].most_common(1)[0][0]
        crops_html = []
        step = max(1, len(occ) // args.crops)
        for n, (i, pos, vi) in enumerate(occ[::step][: args.crops]):
            loc = nom_char_location(pairs, ch_labels, rows, i, pos, stream=stream)
            img = glyph_crop(native / loc[0], ch_labels, loc[0], loc[1], loc[2], loc[3]) if loc else None
            qn = rows[i].vi_txt or ""
            k = qn.lower().find(vi.lower())
            ctx = qn[max(0, k - 18): k + len(vi) + 18] if k >= 0 else ""
            if img is None:
                crops_html.append(f"<figure><div class='nocrop'>?</div><figcaption>{short_id(rows[i].sentence_id)}"
                                  f"</figcaption></figure>")
                continue
            name = f"g{g:03d}_{n}.png"
            img.save(out / "crops" / name)
            crops_html.append(f"<figure><img src='crops/{name}' alt=''><figcaption>{short_id(rows[i].sentence_id)}"
                              f"<br><span class='ctx'>…{html.escape(ctx)}…</span></figcaption></figure>")
        cands = candidates_for(syl, exact, loose, freq)
        cand_html = []
        for c, kind in cands:
            reads = ", ".join(sorted(readings.of(c)))[:60]
            cand_html.append(
                f"<label class='cand {kind}'><input type='radio' name='g{g}' value='{html.escape(c)}'>"
                f"<span class='glyph'>{html.escape(c)}</span><span class='meta'>U+{ord(c):04X} · ×{freq[c]} trong sách"
                f"<br>{html.escape(reads)}</span></label>")
        cand_html.append(f"<label class='cand opt'><input type='radio' name='g{g}' value='none'>"
                         f"<span class='glyph small'>∅</span><span class='meta'>Không chữ nào giống</span></label>")
        cand_html.append(f"<label class='cand opt'><input type='radio' name='g{g}' value='' checked>"
                         f"<span class='glyph small'>?</span><span class='meta'>Chưa chắc / bỏ qua</span></label>")
        sections.append(
            f"<section data-g='{g}' data-code='{html.escape(code)}' data-syl='{html.escape(syl)}' data-n='{len(occ)}'>"
            f"<h2><span class='ph'>〓</span> {html.escape(code)} ↔ «{html.escape(syl)}» "
            f"<small>{len(occ)} chỗ đỏ</small></h2>"
            f"<div class='crops'>{''.join(crops_html)}</div>"
            f"<p class='hint'>Chọn chữ có <b>hình giống chữ trong ô đỏ</b> của ảnh in. Ứng viên viền xanh đọc đúng "
            f"«{html.escape(syl)}»; viền xám chỉ khác dấu thanh.</p>"
            f"<div class='cands'>{''.join(cand_html)}</div></section>")

    page = PAGE.replace("{{BOOK}}", html.escape(book.book_id)).replace("{{FONTS}}", NOM_FONTS) \
               .replace("{{SECTIONS}}", "\n".join(sections))
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"open: {out / 'index.html'}")
    return 0


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chọn chữ cho 〓</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#d9d9d4;--ok:#1f7a3a;--sel:#fff4c2}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ececea;--muted:#9b9b95;--card:#1f1f1d;--line:#3a3a37;--ok:#5cc07a;--sel:#4a4220}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px;z-index:2}
main{padding:0 16px 80px;max-width:1200px;margin:auto}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:16px 0}
h2{font-size:18px;margin:4px 0 10px}h2 small{color:var(--muted);font-weight:400}
.ph{font-size:22px}.crops{display:flex;flex-wrap:wrap;gap:10px}
figure{margin:0;text-align:center;font-size:12px;color:var(--muted);max-width:150px}
figure img{height:200px;border:1px solid var(--line);border-radius:6px;background:#fff}
.nocrop{height:200px;width:80px;display:grid;place-items:center;border:1px dashed var(--line)}
.ctx{color:var(--fg)}.hint{color:var(--muted);margin:10px 0 6px}
.cands{display:flex;flex-wrap:wrap;gap:8px}
.cand{display:flex;align-items:center;gap:8px;border:2px solid var(--line);border-radius:8px;padding:6px 10px;cursor:pointer;min-width:150px}
.cand.exact{border-color:var(--ok)}.cand input{margin:0}
.cand:has(input:checked){background:var(--sel);outline:3px solid var(--ok)}
.glyph{font-family:{{FONTS}};font-size:46px;line-height:1}.glyph.small{font-size:30px}
.meta{font-size:12px;color:var(--muted)}
textarea{width:100%;height:90px;font:12px monospace}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
</style></head><body>
<header><b>Chọn chữ cho 〓 — {{BOOK}}</b> · <span id="done">0</span> nhóm đã chọn ·
<button id="dl">Tải file kết quả</button> <button id="cp">Sao chép</button>
<details><summary>Kết quả (JSON)</summary><textarea id="out" readonly></textarea></details></header>
<main>{{SECTIONS}}</main>
<script>
const KEY='pua_resolve_{{BOOK}}';
function collect(){const out=[];document.querySelectorAll('section').forEach(s=>{const c=s.querySelector('input:checked');
 if(c&&c.value)out.push({code:s.dataset.code,qn:s.dataset.syl,count:+s.dataset.n,choice:c.value});});return out;}
function refresh(){const r=collect();document.getElementById('out').value=JSON.stringify(r,null,1);
 document.getElementById('done').textContent=r.length;
 try{localStorage.setItem(KEY,JSON.stringify(r));}catch(e){}}
try{const saved=JSON.parse(localStorage.getItem(KEY)||'[]');saved.forEach(x=>{document.querySelectorAll('section').forEach(s=>{
 if(s.dataset.code===x.code&&s.dataset.syl===x.qn){const i=[...s.querySelectorAll('input')].find(i=>i.value===x.choice);if(i)i.checked=true;}});});}catch(e){}
document.addEventListener('change',refresh);refresh();
document.getElementById('dl').onclick=()=>{const b=new Blob([document.getElementById('out').value],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='pua_choices_{{BOOK}}.json';a.click();};
document.getElementById('cp').onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('out').value);};
</script></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
