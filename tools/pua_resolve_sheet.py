"""Sheet for picking the real character of a red Nôm char by eye.

Two kinds of red 1 Nôm char <-> 1 syllable elements:

* 〓 (default): the Kim Hán Nôm API returned a private-use code; occurrences
  are grouped by (original code, syllable).
* ``--pairs FILE``: pairs the reviewer noted while reviewing, one per line
  ``<Nôm char>; <syllable>`` (e.g. data/review/note_tap2.txt); occurrences are
  grouped by (OCR char, syllable).

For every group the tool writes print crops of up to N occurrences next to
the characters the dictionaries read as that syllable: look-alikes of the
OCR char (instructor's SinoNom_Similar_Dic_v2.csv) first, then the ones used
most in the book. The reviewer picks the candidate whose shape is the printed
glyph, "none" (no candidate fits), "nochange" (the OCR char is right; the
pair was misdiagnosed), or leaves it undecided, then downloads the choices
as JSON. A picked char becomes a suggestion rule; each occurrence is still
accepted on its crop in the review grid.

Read-only on the data; writes only data/diagnostics/pua_resolve/<book>/.
The page and crops are book scans: keep them on this machine.

    python tools/pua_resolve_sheet.py --book T1_CamPhong_Tap2 [--min 2] [--crops 8]
    python tools/pua_resolve_sheet.py --book T1_CamPhong_Tap2 --pairs data/review/note_tap2.txt
"""

from __future__ import annotations

import argparse
import ast
import csv
import html
import re
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


def candidates_for(syllable: str, exact, loose, freq: Counter, limit: int = 24, loose_limit: int = 12,
                   similar: list[str] | None = None):
    """[(char, 'exact'|'tone')] reading as ``syllable``.

    Look-alikes of the OCR char (``similar``, in their rank order) first, then
    the chars used most in the book."""
    rank = {c: k for k, c in enumerate(similar or [])}

    def key(c):
        return (rank.get(c, len(rank)), -freq[c], c)

    s = norm_reading(syllable)
    first = sorted(exact.get(s, set()), key=key)[:limit]
    rest = sorted(loose.get(tone_key(s), set()) - set(first) - exact.get(s, set()), key=key)
    return [(c, "exact") for c in first] + [(c, "tone") for c in rest[:loose_limit]]


def read_pairs(path: Path) -> list[tuple[str, str]]:
    """``<Nôm char>; <syllable>`` lines -> unique (char, syllable) in file order; other lines ignored."""
    out: list[tuple[str, str]] = []
    seen = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if ";" not in line:
            continue
        nom, _, syl = (x.strip() for x in line.partition(";"))
        nom = unicodedata.normalize("NFC", nom)
        syl = unicodedata.normalize("NFC", syl).lower()
        if len(nom) != 1 or not syl or not syl.replace("-", "").isalpha():
            continue
        if (nom, tone_key(syl)) not in seen:
            seen.add((nom, tone_key(syl)))
            out.append((nom, syl))
    return out


def load_similar(root: Path) -> dict[str, list[str]]:
    path = root / "dictionaries-04-11-2026" / "SinoNom_Similar_Dic_v2.csv"
    if not path.exists():
        return {}
    csv.field_size_limit(10**8)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return {r["Input Character"]: ast.literal_eval(r["Top 20 Similar Characters"]) for r in csv.DictReader(fh)}


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


def red_single(row):
    """(element, syllable) for every red 1 Nôm char <-> 1 syllable element of the row."""
    for el in row.text_diff or []:
        vi = (el.vi_sub_text or "").strip()
        if el.type == "error" and len(el.nom_sub_text or "") == 1 and vi.isalpha() and el.nom_pos:
            yield el, vi


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/project.yaml")
    ap.add_argument("--book", required=True)
    ap.add_argument("--pairs", help="file of '<Nôm char>; <syllable>' lines (reviewer notes) instead of 〓")
    ap.add_argument("--min", type=int, default=2, dest="minimum", help="smallest 〓 group shown (occurrences)")
    ap.add_argument("--crops", type=int, default=8, help="crops per group")
    args = ap.parse_args()

    project = load_config(ROOT / args.config)
    book = next(b for b in project.books if b.book_id == args.book)
    data = project.data_dir
    rows = read_alignment_csv(data / "align" / book.book_id / f"{book.book_name}.csv")
    pairs = load_image_map(data / "layout" / book.book_id / "image_map.json")
    ch_labels = read_label_txt(data / "labels" / book.book_id / "ch" / "Label.txt")

    # groups: (ocr char, code or "", tone key) -> [(row index, pos, syllable)]
    groups: dict[tuple[str, str, str], list[tuple[int, int, str]]] = defaultdict(list)
    missing: list[tuple[str, str]] = []
    if args.pairs:
        wanted = read_pairs(Path(args.pairs))
        keys = {(n, tone_key(s)) for n, s in wanted}
        for i, row in enumerate(rows):
            for el, vi in red_single(row):
                k = (el.nom_sub_text, tone_key(vi.lower()))
                if k in keys and el.nom_sub_text != PLACEHOLDER:
                    groups[(k[0], "", k[1])].append((i, el.nom_pos[0][0], vi))
        order = [(n, "", tone_key(s)) for n, s in wanted if n != PLACEHOLDER]
        missing = [(n, s) for n, s in wanted if n != PLACEHOLDER and not groups.get((n, "", tone_key(s)))]
        ordered = [(k, groups[k]) for k in order if groups.get(k)]
        kind = "red_pairs"
    else:
        origins = stream_origins(pairs, load_cleaned_pages(project, book), ch_labels)
        records, problems = assign_origins(rows, origins)
        code_of = {(r["sentence_id"], r["position"]): r["code"] for r in records}
        for p in problems:
            print(f"warning: {p}")
        for i, row in enumerate(rows):
            for el, vi in red_single(row):
                if el.nom_sub_text == PLACEHOLDER:
                    pos = el.nom_pos[0][0]
                    groups[(PLACEHOLDER, code_of.get((row.sentence_id, pos), "unknown"), tone_key(vi))].append(
                        (i, pos, vi))
        ordered = sorted(((k, v) for k, v in groups.items() if len(v) >= args.minimum), key=lambda kv: -len(kv[1]))
        kind = "pua"
    print(f"{book.book_id} [{kind}]: groups shown {len(ordered)}, occurrences {sum(len(v) for _, v in ordered)}"
          + (f"; noted pairs with no red occurrence left: {len(missing)}" if args.pairs else ""))

    readings = load_readings_cache(project)
    if readings is None:
        raise SystemExit("readings cache unavailable")
    exact, loose = reverse_readings(readings)
    similar = load_similar(project.root)
    freq = Counter(ch for r in rows for ch in (r.ch_txt or ""))
    out = data / "diagnostics" / "pua_resolve" / book.book_id
    crop_dir = out / ("crops" if kind == "pua" else "crops_pairs")
    crop_dir.mkdir(parents=True, exist_ok=True)
    native = data / "pages" / book.book_id / "native"
    stream = nom_stream_index(pairs, ch_labels, rows)

    sections = []
    for g, ((ocr, code, _key), occ) in enumerate(ordered):
        syl = Counter(v.lower() for _i, _p, v in occ).most_common(1)[0][0]
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
            img.save(crop_dir / name)
            crops_html.append(f"<figure><img src='{crop_dir.name}/{name}' alt=''><figcaption>"
                              f"{short_id(rows[i].sentence_id)}<br><span class='ctx'>…{html.escape(ctx)}…</span>"
                              f"</figcaption></figure>")
        sims = similar.get(ocr, []) if ocr != PLACEHOLDER else []
        cand_html = []
        for c, cls in candidates_for(syl, exact, loose, freq, similar=sims):
            reads = ", ".join(sorted(readings.of(c)))[:60]
            badge = " · <b>giống hình</b>" if c in sims else ""
            cand_html.append(
                f"<label class='cand {cls}'><input type='radio' name='g{g}' value='{html.escape(c)}'>"
                f"<span class='glyph'>{html.escape(c)}</span><span class='meta'>U+{ord(c):04X} · ×{freq[c]} trong sách"
                f"{badge}<br>{html.escape(reads)}</span></label>")
        if ocr != PLACEHOLDER:
            cand_html.append(f"<label class='cand opt'><input type='radio' name='g{g}' value='nochange'>"
                             f"<span class='glyph small'>{html.escape(ocr)}</span><span class='meta'><b>No-change</b>: "
                             f"chữ OCR đúng, cặp này không sai</span></label>")
        cand_html.append(f"<label class='cand opt'><input type='radio' name='g{g}' value='none'>"
                         f"<span class='glyph small'>∅</span><span class='meta'>Không chữ nào giống</span></label>")
        cand_html.append(f"<label class='cand opt'><input type='radio' name='g{g}' value='' checked>"
                         f"<span class='glyph small'>?</span><span class='meta'>Chưa chắc / bỏ qua</span></label>")
        title = (f"<span class='ph'>〓</span> {html.escape(code)}" if ocr == PLACEHOLDER
                 else f"OCR <span class='glyph inline'>{html.escape(ocr)}</span>")
        sections.append(
            f"<section data-g='{g}' data-ocr='{html.escape(ocr)}' data-code='{html.escape(code)}' "
            f"data-syl='{html.escape(syl)}' data-n='{len(occ)}'>"
            f"<h2>{title} ↔ «{html.escape(syl)}» <small>{len(occ)} chỗ đỏ</small></h2>"
            f"<div class='crops'>{''.join(crops_html)}</div>"
            f"<p class='hint'>Chọn chữ có <b>hình giống chữ trong ô đỏ</b> của ảnh in. Viền xanh: đọc đúng "
            f"«{html.escape(syl)}»; viền xám: chỉ khác dấu thanh; nhãn <b>giống hình</b>: trông giống chữ OCR.</p>"
            f"<div class='cands'>{''.join(cand_html)}</div></section>")
    if missing:
        sections.append("<section><h2>Cặp trong ghi chú không còn chỗ đỏ 1↔1</h2><p class='hint'>Đã sửa, đã có gợi ý, "
                        "hoặc nằm trong khối lệch số chữ: " + ", ".join(f"{html.escape(n)}↔{html.escape(s)}"
                                                                         for n, s in missing) + "</p></section>")

    page = (PAGE.replace("{{BOOK}}", html.escape(book.book_id)).replace("{{KIND}}", kind)
            .replace("{{TITLE}}", "Chọn chữ cho 〓" if kind == "pua" else "Chọn chữ cho các cặp đỏ đã ghi chú")
            .replace("{{FONTS}}", NOM_FONTS).replace("{{SECTIONS}}", "\n".join(sections)))
    target = out / ("index.html" if kind == "pua" else "red_pairs.html")
    target.write_text(page, encoding="utf-8")
    print(f"open: {target}")
    return 0


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
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
.glyph{font-family:{{FONTS}};font-size:46px;line-height:1}.glyph.small{font-size:30px}.glyph.inline{font-size:30px}
.meta{font-size:12px;color:var(--muted)}
textarea{width:100%;height:90px;font:12px monospace}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
</style></head><body>
<header><b>{{TITLE}} — {{BOOK}}</b> · <span id="done">0</span> nhóm đã chọn ·
<button id="dl">Tải file kết quả</button> <button id="cp">Sao chép</button>
<details><summary>Kết quả (JSON)</summary><textarea id="out" readonly></textarea></details></header>
<main>{{SECTIONS}}</main>
<script>
const KEY='pua_resolve_{{KIND}}_{{BOOK}}';
const secs=()=>[...document.querySelectorAll('section[data-g]')];
function collect(){const out=[];secs().forEach(s=>{const c=s.querySelector('input:checked');
 if(c&&c.value)out.push({ocr:s.dataset.ocr,code:s.dataset.code,qn:s.dataset.syl,count:+s.dataset.n,choice:c.value});});return out;}
function refresh(){const r=collect();document.getElementById('out').value=JSON.stringify(r,null,1);
 document.getElementById('done').textContent=r.length;
 try{localStorage.setItem(KEY,JSON.stringify(r));}catch(e){}}
try{const saved=JSON.parse(localStorage.getItem(KEY)||'[]');saved.forEach(x=>{secs().forEach(s=>{
 if(s.dataset.ocr===x.ocr&&s.dataset.code===x.code&&s.dataset.syl===x.qn){const i=[...s.querySelectorAll('input')].find(i=>i.value===x.choice);if(i)i.checked=true;}});});}catch(e){}
document.addEventListener('change',refresh);refresh();
document.getElementById('dl').onclick=()=>{const b=new Blob([document.getElementById('out').value],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='{{KIND}}_choices_{{BOOK}}.json';a.click();};
document.getElementById('cp').onclick=()=>{navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('out').value);};
</script></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
