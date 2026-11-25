"""Local Streamlit review app for alignment and text_diff.

Run from the repository root (``python -m hannom.cli review --book <id>`` sets
``HANNOM_BOOK``):

    streamlit run src/hannom/review/app.py

Text edits go through ``hannom.review.edit.apply_row_edit``: Label.txt (ch/ and
vi/) and the CSV are changed together so the SYNC check keeps passing, the
row's text_diff is recomputed with the v2.4 spec policy and the row is flagged
CONTENT_EDITED. Patches are keyed by row content hash (never by position).
"""

from __future__ import annotations

import html
import os
import sys
from pathlib import Path

# Streamlit executes this file directly, so make ``src`` importable.
SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from hannom.align import read_alignment_csv, write_alignment_csv  # noqa: E402
from hannom.config import load_config  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.review.edit import (  # noqa: E402
    EditError,
    accept_warn,
    apply_row_edit,
    atomic_save_csv,
    atomic_save_labels,
    label_paths_save,
    is_reviewed,
    progress,
    recompute_row_diff,
    red_density,
    reject_suggest,
    awaiting_decision,
    find_rows,
    mark_as_warn,
    normalize_cell,
    review_history,
    review_queue,
    reviewed_order,
    row_locations,
    select_row,
    next_position,
    suggest_edit_text,
    suggest_edit_text_all,
    nom_char_location,
    nom_stream_index,
    pending_suggests,
)
from hannom.review.patches import (  # noqa: E402
    append_patch,
    apply_patches_checked,
    make_patch,
    read_patches,
    row_content_hash,
)
from hannom.review_decisions import (  # noqa: E402
    append_decision,
    decision_path,
    parse_decisions,
)
from hannom.review_metadata import load_rows_with_metadata  # noqa: E402
from hannom.t1_map import load_image_map  # noqa: E402
from hannom.textdiff import diff_summary  # noqa: E402


def _spans_html(text: str, spans: list[tuple[int, int, str]]) -> str:
    if not spans:
        return html.escape(text)
    spans = sorted(spans)
    out: list[str] = []
    cursor = 0
    for start, end, kind in spans:
        if start < cursor:
            continue
        out.append(html.escape(text[cursor:start]))
        color = "#ffd6d6" if kind == "error" else "#fff2a8"
        out.append(f"<span style='background-color:{color}'>{html.escape(text[start:end])}</span>")
        cursor = end
    out.append(html.escape(text[cursor:]))
    return "".join(out)


def _overlay(image_path: Path, labels: dict, folder: str, image_name: str,
             highlight_boxes=(), band=None) -> Image.Image:
    """Draw the boxes of ``<folder>/<image_name>``; the boxes holding the row
    under review in thick red; for a QN page, a translucent band over the
    estimated vertical position of the row (``band`` = (start, end) fractions)."""
    image = Image.open(image_path).convert("RGB")
    boxes = labels.get(f"{folder}/{image_name}") or []
    if band is not None and boxes:
        pts = [tuple(float(v) for v in p) for p in (boxes[0].get("points") or [])]
        if len(pts) == 4:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            h = max(ys) - min(ys)
            top = min(ys) + h * max(0.0, band[0] - 0.03)
            bottom = min(ys) + h * min(1.0, band[1] + 0.03)
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).rectangle([min(xs), top, max(xs), bottom], fill=(255, 200, 0, 70), outline=(230, 120, 0, 255), width=3)
            image = Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
    draw = ImageDraw.Draw(image)
    marked = set(highlight_boxes)
    for k, box in enumerate(boxes):
        points = box.get("points") or []
        if len(points) == 4:
            poly = [tuple(float(v) for v in point) for point in points]
            if k in marked:
                draw.polygon(poly, outline=(0, 90, 255), width=5)
            else:
                draw.polygon(poly, outline=(0, 160, 0), width=1)
    return image


NOM_FONTS = ("'Nom Na Tong','HAN NOM A','HAN NOM B','Han-Nom Gothic','Han-Nom Ming','HanaMinA','HanaMinB',"
             "'SimSun-ExtB','SimSun-ExtG','MingLiU-ExtB',serif")


def _glyph_crop(image_path: Path, labels: dict, image_name: str, box: int, idx: int, count: int) -> Image.Image | None:
    """The glyph cell ``idx`` of Nôm box ``box`` (cells estimated by dividing the
    box evenly), with one cell of context on each side, outlined in red."""
    boxes = labels.get(f"ch/{image_name}") or []
    if box >= len(boxes) or not image_path.exists():
        return None
    pts = [tuple(float(v) for v in p) for p in (boxes[box].get("points") or [])]
    if len(pts) != 4 or count <= 0:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if (y1 - y0) >= (x1 - x0):  # vertical column
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
    scale = 260 / max(1, crop.height)
    return crop.resize((max(1, int(crop.width * scale)), 260))


def _apply_suggestions(project, book, csv_path: Path, label_dir: Path, patch_path: Path, pairs, ch_labels, vi_labels,
                       ops, reviewer: str, reason: str) -> tuple[int, list[str]]:
    """Resolve suggestions on several rows at once (Quy định v2.4 states b/c).

    ``ops``: [(sentence_id, content hash, accept positions, reject positions)].
    Per row: accepted chars replace the OCR chars in Label.txt and ch_txt
    together (SYNC kept, ch_txt patch logged, colouring recomputed); then the
    rejected ones become plain red errors (text_diff patch logged). Rows whose
    content changed on disk since the page was drawn are skipped."""
    import copy as _copy

    raw = read_alignment_csv(csv_path)
    meta_rows, _ = load_rows_with_metadata(csv_path)
    for r, m in zip(raw, meta_rows):
        r.flags, r.confidence = list(m.flags), m.confidence
    ctx = _recompute_context(project, book)
    ch_now, vi_now, labels_changed = ch_labels, vi_labels, False
    patches, done, skipped = [], 0, []
    for sid, content_hash, accept, reject in ops:
        idx = next((i for i, r in enumerate(raw)
                    if r.sentence_id == sid and row_content_hash(r.img_id, r.ch_txt, r.vi_txt) == content_hash), None)
        if idx is None:
            skipped.append(sid)
            continue
        if accept:
            chars = list(raw[idx].ch_txt)
            for el in raw[idx].text_diff or []:
                if el.type == "warn" and el.suggest and el.nom_pos and el.nom_pos[0][0] in accept:
                    chars[el.nom_pos[0][0]] = el.suggest
            new_text = "".join(chars)
            if new_text != raw[idx].ch_txt:
                try:
                    ch_now, vi_now, new_rows = apply_row_edit(pairs, ch_now, vi_now, raw, idx, new_text, None)
                except EditError:
                    skipped.append(sid)
                    continue
                patches.append(make_patch(raw[idx], book_id=book.book_id, field="ch_txt", after=new_text,
                                          reviewer=reviewer, reason=reason or "nhận gợi ý thay chữ (đã đối chiếu ảnh)"))
                recompute_row_diff(new_rows[idx], **ctx)
                raw, labels_changed = new_rows, True
        if reject:
            snapshot = _copy.deepcopy(raw[idx])
            for k, el in enumerate(raw[idx].text_diff or []):
                if el.type == "warn" and el.suggest and el.nom_pos and el.nom_pos[0][0] in reject:
                    reject_suggest(raw[idx], k)
            if raw[idx].text_diff_json() != snapshot.text_diff_json():
                patches.append(make_patch(snapshot, book_id=book.book_id, field="text_diff",
                                          after=raw[idx].text_diff_json(), reviewer=reviewer,
                                          reason=reason or "bỏ gợi ý thay chữ (đã đối chiếu ảnh)"))
        done += 1
    if labels_changed:
        atomic_save_labels(ch_now, label_dir / "ch" / "Label.txt", "ch")
    atomic_save_csv(csv_path, raw)
    for p in patches:
        append_patch(patch_path, p)
    return done, skipped


def _review_everywhere(project, book, csv_path: Path, patch_path: Path, nom_text: str, vi_text: str,
                       reviewer: str) -> tuple[int, int]:
    """Set reviewed 1 on every yellow element of the book with exactly this
    Nôm and QN text (e.g. one transliterated name block). Rows carrying a
    review decision are left alone (changing their text_diff would void the
    decision); returns (elements reviewed, decided rows skipped)."""
    import copy as _copy

    raw = read_alignment_csv(csv_path)
    meta_rows, _ = load_rows_with_metadata(csv_path)
    from hannom.review_decisions import parse_decisions as _parse_decisions

    decided = {d.sentence_id for d in _parse_decisions(decision_path(project.data_dir, book.book_id))[0]}
    for r, m in zip(raw, meta_rows):
        r.flags, r.confidence = list(m.flags), m.confidence
    n_done = n_skipped = 0
    patches = []
    for row in raw:
        hits = [k for k, el in enumerate(row.text_diff or [])
                if el.type == "warn" and not el.suggest and el.reviewed != 1
                and el.nom_sub_text == nom_text and el.vi_sub_text == vi_text]
        if not hits:
            continue
        if row.sentence_id in decided:
            n_skipped += 1
            continue
        snapshot = _copy.deepcopy(row)
        for k in hits:
            accept_warn(row, k)
        patches.append(make_patch(snapshot, book_id=book.book_id, field="text_diff", after=row.text_diff_json(),
                                  reviewer=reviewer, reason=f"duyệt vàng hàng loạt: {nom_text} ↔ {vi_text}"))
        n_done += len(hits)
    if patches:
        atomic_save_csv(csv_path, raw)
        for p in patches:
            append_patch(patch_path, p)
    return n_done, n_skipped


def _suggest_grid(project, book, rows, pairs, ch_labels, vi_labels, csv_path, label_dir, patch_path) -> None:
    """All pending suggestions of one kind as a grid of print crops: the
    reviewer looks at every glyph, unticks the wrong ones, applies the page."""
    import collections
    import math

    st.subheader("Duyệt gợi ý thay chữ Nôm theo lưới")
    st.caption("Mỗi ô: ảnh in (khung đỏ = chữ được gợi ý thay). Giữ dấu ✓ nếu chữ in ĐÚNG là chữ gợi ý; "
               "bỏ dấu nếu khác. Áp dụng: ô có dấu → nhận (thay vào Label.txt và CSV, thành đen); "
               "ô không dấu → bỏ (giữ chữ OCR, tô đỏ). Quy định v2.4: mọi gợi ý phải được nhận hoặc bỏ trước khi nộp.")
    reviewer = st.text_input("Người review", value=os.environ.get("USERNAME", ""), key="grid_reviewer")
    items = [(i, el) for i, r in enumerate(rows) for el in (r.text_diff or []) if el.type == "warn" and el.suggest]
    if not items:
        st.success("Không còn gợi ý nào chưa xử lý.")
        return
    kinds = collections.Counter((el.nom_sub_text, el.suggest) for _i, el in items)
    kind = st.selectbox("Loại gợi ý", sorted(kinds, key=lambda k: -kinds[k]),
                        format_func=lambda k: f"{k[0]} → {k[1]}  ({kinds[k]} ô)")
    sel = [(i, el) for i, el in items if (el.nom_sub_text, el.suggest) == kind]
    per_page = 30
    pages = max(1, math.ceil(len(sel) / per_page))
    page = int(st.number_input(f"Trang lưới (1–{pages})", min_value=1, max_value=pages, value=1, step=1))
    chunk = sel[(page - 1) * per_page: page * per_page]
    st.markdown(
        f"<div style=\"font-family:{NOM_FONTS};font-size:40px\">{html.escape(kind[0])} → "
        f"<span style='color:#0a7d2c'>{html.escape(kind[1])}</span></div>", unsafe_allow_html=True)
    native = project.data_dir / "pages" / book.book_id / "native"
    stream = nom_stream_index(pairs, ch_labels, rows)
    cols = st.columns(6)
    choice = {}
    for j, (i, el) in enumerate(chunk):
        pos = el.nom_pos[0][0]
        with cols[j % 6]:
            loc = nom_char_location(pairs, ch_labels, rows, i, pos, stream=stream)
            crop = _glyph_crop(native / loc[0], ch_labels, loc[0], loc[1], loc[2], loc[3]) if loc else None
            if crop is not None:
                st.image(crop.resize((max(1, crop.width * 180 // crop.height), 180)))
            else:
                st.caption("(không định vị được)")
            st.caption(f"{rows[i].sentence_id.rsplit('.', 2)[-2]}.{rows[i].sentence_id.rsplit('.', 1)[-1]} · "
                       f"{el.vi_sub_text}")
            choice[(i, pos)] = st.checkbox("đúng chữ gợi ý", value=True, key=f"g|{rows[i].sentence_id}|{pos}")
    n_yes = sum(choice.values())
    if st.button(f"Áp dụng trang này: nhận {n_yes}, bỏ {len(choice) - n_yes}", type="primary"):
        if not reviewer.strip():
            st.error("Cần nhập người review.")
            return
        by_row: dict[int, tuple[set, set]] = {}
        for (i, pos), yes in choice.items():
            by_row.setdefault(i, (set(), set()))[0 if yes else 1].add(pos)
        ops = [(rows[i].sentence_id, row_content_hash(rows[i].img_id, rows[i].ch_txt, rows[i].vi_txt), acc, rej)
               for i, (acc, rej) in by_row.items()]
        done, skipped = _apply_suggestions(project, book, csv_path, label_dir, patch_path, pairs, ch_labels,
                                           vi_labels, ops, reviewer.strip(), "")
        st.session_state.flash = (f"Đã xử lý {len(choice)} gợi ý trên {done} câu (nhận {n_yes}, bỏ {len(choice) - n_yes})."
                                  + (f" Bỏ qua {len(skipped)} câu đã đổi trên đĩa." if skipped else ""))
        st.rerun()


def _read_labels(path: Path) -> dict:
    try:
        return read_label_txt(path) if path.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _dictionary_cfg(project) -> dict:
    return (project.dictionary_config or {}).get("dictionary", project.dictionary_config or {}) or {}


def _stamp(paths) -> tuple:
    return tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in paths)


def _dictionary_stamp(project) -> tuple:
    """The dictionary files the shared adapters are read from (a new or
    changed file, or a dictionary.yaml edit, reloads them)."""
    root, cfg = project.root, _dictionary_cfg(project)
    return _stamp([root / "configs" / "dictionary.yaml", root / str(cfg.get("entries_dir", "dictionaries/entries"))]
                  + [root / str(cfg[k]) for k in ("unihan_dir", "cedict_path", "makemeahanzi_path",
                                                   "cjkvi_ids_path", "cjkvi_variants_path") if cfg.get(k)])


def _resource_stamp(project, book) -> tuple:
    """What one book's diff resources were built from: its lexicon (a
    re-align rewrites it), the readings cache, the configs, the dictionaries."""
    return _dictionary_stamp(project) + _stamp((
        project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json",
        project.data_dir / "dictionary" / "char_readings.json",
        project.root / "configs" / "alignment.yaml",
    ))


@st.cache_resource(max_entries=1, show_spinner="Đang nạp từ điển (một lần cho cả phiên, khoảng 30–40 giây)…")
def _shared_dictionary(_project, stamp: tuple) -> tuple[list, list]:
    """The dictionary adapters (official JSONL drop, Unihan, CC-CEDICT, …),
    loaded once for every book: about 2.6 GB once read. Built on every save,
    a fresh index re-read the files and the save took 33-37 s (Tap1,
    2026-11-22); on loaded adapters it takes 1.5-1.7 s. Only the book lexicon
    differs between books (``_diff_resources``)."""
    import gc

    from hannom.dictionary.index import build_dictionary_index

    index = build_dictionary_index(_project.root, _project.dictionary_config or {}, book_id=None)
    index.lookup("天", use_cache=False)  # adapters read their files on the first lookup: do it under the spinner
    # Streamlit runs gc.collect(2) after every script run (runner.postScriptGC):
    # over the ~5.1 M objects of the loaded dictionaries that is ~0.9 s per
    # click on an idle machine and far more when RAM is short (py-spy on the
    # live app, 2026-11-22: 54 of 65 s CPU in _on_script_finished). Frozen
    # objects are skipped by the collector; they live as long as this cache.
    gc.collect()
    gc.freeze()
    return index.adapters, index.configured_sources


@st.cache_resource(max_entries=4, show_spinner=False)
def _diff_resources(_project, book_id: str, stamp: tuple) -> dict:
    """One book's lexicon, dictionary index (shared adapters + this book's
    lexicon, as ``build_dictionary_index`` assembles it) and readings cache,
    kept across reruns. ``name_memo`` holds the per-row name spellings
    (textdiff.name_spelling_table)."""
    from hannom.dictionary.book_lexicon import BookLexicon
    from hannom.dictionary.index import DictionaryIndex
    from hannom.orchestrator import load_readings_cache

    adapters, configured = _shared_dictionary(_project, _dictionary_stamp(_project))
    lexicons_dir = _project.root / str(_dictionary_cfg(_project).get("book_lexicons_dir", "data/dictionary/book_lexicons"))
    return {
        "lexicon": BookLexicon(_project.data_dir / "dictionary" / "book_lexicons" / f"{book_id}.json"),
        "dictionary": DictionaryIndex(adapters, BookLexicon(lexicons_dir / f"{book_id}.json"),
                                      configured_sources=configured),
        "readings_cache": load_readings_cache(_project),
        "name_memo": {},
    }


def _recompute_context(project, book) -> dict:
    """Lexicon / dictionary / readings cache as ``stage_align`` builds them.

    Raises on failure (shown by Streamlit; the callers have not written
    anything yet): an empty context would recolour the edited row without
    any dictionary and save that."""
    import inspect

    from hannom import textdiff
    from hannom.textdiff import (
        name_blocks_from_config, name_spellings_from_config, suggest_rules_from_config, warn_rules_from_config,
    )

    res = _diff_resources(project, book.book_id, _resource_stamp(project, book))
    ctx = {"lexicon": res["lexicon"], "dictionary": res["dictionary"], "readings_cache": res["readings_cache"],
           "warn_rules": warn_rules_from_config(project.alignment_config),
           "suggest_rules": suggest_rules_from_config(project.alignment_config, book.book_id),
           "name_blocks": name_blocks_from_config(project.alignment_config, book.book_id)}
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if ctx["name_blocks"] and csv_path.exists():
        # Same whole-book spelling table as `align` / `textdiff`, so an
        # edited row gets the colouring a full recompute would give it.
        extra = {}
        # Streamlit reloads this script on change, not hannom.textdiff: an app
        # started before the memo existed keeps the old signature.
        if "memo" in inspect.signature(textdiff.name_spelling_table).parameters:
            extra["memo"] = res["name_memo"]
        ctx["name_spellings"] = name_spellings_from_config(
            project.alignment_config, book.book_id, ((r.ch_txt, r.vi_txt) for r in read_alignment_csv(csv_path)),
            lexicon=ctx["lexicon"], dictionary=ctx["dictionary"], readings_cache=ctx["readings_cache"], **extra)
    return ctx


def main() -> None:
    st.set_page_config(page_title="Hán Nôm review", layout="wide")
    st.title("Hán Nôm–Quốc ngữ review")
    # Confirmation of the last action survives the rerun that follows it.
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)

    project_root = Path(os.environ.get("HANNOM_PROJECT", ".")).resolve()
    try:
        project = load_config(project_root / "configs" / "project.yaml")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Không đọc được cấu hình: {exc}")
        return
    book_ids = [book.book_id for book in project.books]
    wanted = os.environ.get("HANNOM_BOOK")
    default = book_ids.index(wanted) if wanted in book_ids else 0
    book_id = st.sidebar.selectbox("Sách", book_ids, index=default)
    book = project.book(book_id)
    csv_path = project.data_dir / "align" / book.book_id / f"{book.book_name}.csv"
    if not csv_path.exists():
        st.warning(f"Chưa có CSV nháp: {csv_path}")
        return
    rows, metadata_issues = load_rows_with_metadata(csv_path)
    if metadata_issues:
        st.warning(
            "Metadata review không đầy đủ hoặc không khớp: "
            + ", ".join(metadata_issues[:5])
            + (" …" if len(metadata_issues) > 5 else "")
            + ". Các dòng thiếu metadata không được coi là sạch."
        )
    patch_path = project.data_dir / "review" / f"{book.book_id}.patches.jsonl"
    rows, rejected = apply_patches_checked(rows, read_patches(patch_path))
    if rejected:
        st.warning(
            f"{len(rejected)} patch cũ/không khớp nội dung, KHÔNG áp dụng: "
            + "; ".join(f"{r.patch.sentence_id}: {r.reason}" for r in rejected[:3])
        )
    decisions_file = decision_path(project.data_dir, book.book_id)
    from hannom.review_decisions import apply_decisions  # noqa: E402

    decisions, failures, decision_issues = parse_decisions(decisions_file)
    history = review_history(read_patches(patch_path), decisions)
    rows, decision_issues, _audit = apply_decisions(rows, decisions, decision_issues, failures=failures)
    if decision_issues:
        st.warning(
            "Quyết định review không hợp lệ/đã cũ: "
            + ", ".join(decision_issues[:5])
            + (" …" if len(decision_issues) > 5 else "")
            + ". Quyết định cũ không được dùng để xác minh."
        )

    label_dir = project.data_dir / "labels" / book.book_id
    ch_labels = _read_labels(label_dir / "ch" / "Label.txt")
    vi_labels = _read_labels(label_dir / "vi" / "Label.txt")
    map_path = project.data_dir / "layout" / book.book_id / "image_map.json"
    pairs = load_image_map(map_path) if map_path.exists() else []

    done, total = progress(rows)
    st.sidebar.progress(done / total if total else 0.0, text=f"Đã chấp nhận/quyết định {done}/{total}")
    undecided_black = sum(1 for r in rows if not getattr(r, "review_status", None) and red_density(r) == 0
                          and not any(e.type == "warn" for e in (r.text_diff or [])))
    if undecided_black:
        st.sidebar.info(f"{undecided_black} câu không đỏ chưa có quyết định — chúng không nằm trong hàng đợi đỏ; "
                        "xem hàng đợi \"Chưa quyết định\" (vẫn cần đối chiếu dấu thanh Quốc ngữ với ảnh).")
    n_suggest = sum(pending_suggests(r) for r in rows)
    if n_suggest:
        st.sidebar.warning(f"{n_suggest} gợi ý thay chữ Nôm chưa xử lý ({sum(1 for r in rows if pending_suggests(r))} câu) "
                           "— mỗi gợi ý phải Nhận hoặc Bỏ trước khi nộp (v2.4); xem hàng đợi \"Gợi ý thay chữ Nôm\".")
    pending = sum(1 for r in rows if awaiting_decision(r))
    if pending:
        st.sidebar.warning(f"{pending} câu đã lưu sửa nhưng CHƯA chấp nhận — xem hàng đợi \"Đã sửa, chưa chấp nhận\".")
    mode = st.sidebar.selectbox(
        "Hàng đợi",
        ["red", "any_red", "no_red", "suggest", "suggest_grid", "undecided", "pending", "manual", "warn", "reviewed",
         "all"],
        format_func={
            "red": "Mật độ đỏ giảm dần",
            "any_red": "Có đỏ (Nôm hoặc Quốc ngữ) — thứ tự đọc",
            "no_red": "Không đỏ (0 %) — thứ tự đọc",
            "suggest": "Gợi ý thay chữ Nôm — từng câu",
            "suggest_grid": "Gợi ý thay chữ Nôm — lưới duyệt nhanh",
            "undecided": "Chưa quyết định (mọi câu, kể cả không đỏ)",
            "pending": "Đã sửa, chưa chấp nhận",
            "manual": "Null / <5 ký tự (thủ công)",
            "warn": "Còn vàng chưa duyệt",
            "reviewed": "Đã review / đã sửa (mới nhất trước)",
            "all": "Tất cả",
        }.get,
    )
    hide_done = st.sidebar.checkbox("Ẩn dòng đã chấp nhận/quyết định", value=False)
    if mode == "suggest_grid":
        _suggest_grid(project, book, rows, pairs, ch_labels, vi_labels, csv_path, label_dir, patch_path)
        return
    if mode == "reviewed":
        queue = reviewed_order(rows, history)
    else:
        queue = review_queue(rows, mode, include_reviewed=not hide_done)

    # Jump to any sentence: by id (e.g. 487.9) or by a piece of its text.
    query = st.sidebar.text_input("Tìm câu (mã câu, vd 487.9, hoặc đoạn chữ)", value="")
    if query.strip():
        hits = find_rows(rows, query)
        if hits:
            choice = st.sidebar.selectbox(
                f"Kết quả ({len(hits)})", hits,
                format_func=lambda i: f"{rows[i].sentence_id.rsplit(')', 1)[-1]} · {rows[i].vi_txt[:40]}",
            )
            if st.sidebar.button("Mở câu này"):
                st.session_state.pinned_sid = rows[choice].sentence_id
                st.rerun()
        else:
            st.sidebar.info("Không tìm thấy câu nào.")
    if history:
        with st.sidebar.expander("Sửa / quyết định gần đây", expanded=False):
            for k, h in enumerate(history[:10]):
                label = f"{h['sentence_id'].rsplit(')', 1)[-1]} · {h['what']} · {h['timestamp'][11:16]}"
                if st.button(label, key=f"hist{k}"):
                    st.session_state.pinned_sid = h["sentence_id"]
                    st.rerun()
    if st.session_state.get("queue_key") != (book_id, mode, hide_done):
        # A different book/queue: forget the pinned row (before the empty-queue check).
        st.session_state.queue_key = (book_id, mode, hide_done)
        st.session_state.pinned_sid = None
    if not queue:
        if done == total:
            st.success(f"Hàng đợi trống — đã quyết định đủ {done}/{total} câu của sách này.")
        else:
            st.success(f"Hàng đợi này trống. Còn {total - done} câu chưa quyết định: "
                       "chọn hàng đợi \"Chưa quyết định\".")
        if not st.session_state.get("pinned_sid"):
            return
        queue = list(range(len(rows)))  # a pinned row outside an empty queue
    if "row_index" not in st.session_state:
        st.session_state.row_index = 0
    st.session_state.row_index = max(0, min(st.session_state.row_index, len(queue) - 1))
    position = st.sidebar.number_input(
        "Vị trí", min_value=1, max_value=len(queue), value=st.session_state.row_index + 1, step=1
    ) - 1
    if int(position) != st.session_state.row_index:  # the reviewer typed a position
        st.session_state.row_index = int(position)
        st.session_state.pinned_sid = None
    # The row under review stays pinned by sentence_id: saving an edit that
    # removes its red must not swap the displayed row for another one.
    row_i, queue_pos = select_row(rows, queue, st.session_state.row_index, st.session_state.get("pinned_sid"))
    row = rows[row_i]
    st.session_state.pinned_sid = row.sentence_id
    if queue_pos is not None:
        st.session_state.row_index = queue_pos
    st.sidebar.write(f"`{row.sentence_id}` · đỏ {red_density(row):.0%}")
    if queue_pos is None:
        st.sidebar.info("Câu này đã rời hàng đợi sau khi sửa (vd. hết đỏ); vẫn giữ để bạn xem lại và chấp nhận.")
    if st.sidebar.button("← Câu trước"):
        st.session_state.row_index = max(0, (queue_pos if queue_pos is not None else st.session_state.row_index) - 1)
        st.session_state.pinned_sid = None
        st.rerun()
    if st.sidebar.button("Câu sau →"):
        st.session_state.row_index = next_position(queue, row_i, queue_pos, st.session_state.row_index)
        st.session_state.pinned_sid = None
        st.rerun()
    reviewer = st.sidebar.text_input("Người review", value=os.environ.get("USERNAME", ""))
    reason = st.sidebar.text_input("Lý do", value="")

    nom_spans = [(s0, e0, el.type) for el in (row.text_diff or []) for s0, e0 in el.nom_pos]
    vi_spans = [(s0, e0, el.type) for el in (row.text_diff or []) for s0, e0 in el.vi_pos]
    native = project.data_dir / "pages" / book.book_id / "native"
    try:
        where = row_locations(pairs, ch_labels, vi_labels, rows, row_i)
    except Exception:  # noqa: BLE001 - locating is a convenience, never a blocker
        where = {"ch": {}, "vi": {}}
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Ảnh")
        if (native / row.img_id).exists():
            # Folder-specific Label.txt: Nôm boxes come from ch/, QN boxes from vi/.
            st.image(_overlay(native / row.img_id, ch_labels, "ch", row.img_id,
                              highlight_boxes=where["ch"].get(row.img_id, ())),
                     caption=f"{row.img_id} — cột viền XANH DƯƠNG chứa câu đang xem (không phải lỗi)", width="stretch")
            for other, other_boxes in where["ch"].items():  # the sentence continues on another Nôm page
                if other != row.img_id and (native / other).exists():
                    st.image(_overlay(native / other, ch_labels, "ch", other, highlight_boxes=other_boxes),
                             caption=f"{other} — phần tiếp của câu", width="stretch")
        else:
            st.warning(f"Không thấy ảnh: {native / row.img_id}")
        vi_images = list(where["vi"]) or next((list(p.vi) for p in pairs if row.img_id in p.ch), [])
        for vi_img in vi_images:
            if (native / vi_img).exists():
                st.image(_overlay(native / vi_img, vi_labels, "vi", vi_img, band=where["vi"].get(vi_img)),
                         caption=f"{vi_img} — dải vàng: vị trí ƯỚC LƯỢNG của câu (theo tỉ lệ chữ trên trang)",
                         width="stretch")
        st.write(f"Confidence: {row.confidence if row.confidence is not None else 'N/A'}")
        st.code(", ".join(row.flags) or "(none)")
    with right:
        st.subheader("Căn hàng")
        if row_i > 0:
            st.caption(f"Câu trước: {rows[row_i - 1].vi_txt[-120:]}")
        st.markdown("**Nôm**")
        st.markdown(
            f"<div style='font-size:20px;line-height:1.8'>{_spans_html(row.ch_txt, nom_spans)}</div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Quốc ngữ**")
        st.markdown(
            f"<div style='font-size:16px;line-height:1.8'>{_spans_html(row.vi_txt, vi_spans)}</div>",
            unsafe_allow_html=True,
        )
        if row_i + 1 < len(rows):
            st.caption(f"Câu sau: {rows[row_i + 1].vi_txt[:120]}")
        st.caption(f"text_diff: {diff_summary(row.text_diff)}")
        mine = [h for h in history if h["sentence_id"] == row.sentence_id]
        with st.expander(f"Lịch sử câu này ({len(mine)})", expanded=bool(mine)):
            if not mine:
                st.write("Chưa có sửa hay quyết định nào.")
            for h in mine:
                st.write(f"{h['timestamp'][:16].replace('T', ' ')} · {h['reviewer']} · **{h['what']}** · {h['detail']}")

    def _persist(edit_ch=None, edit_vi=None, mutate=None) -> bool:
        """Apply a text edit (Label.txt + CSV together) and/or a text_diff change to the row."""
        if not reviewer.strip():
            st.error("Cần nhập người review.")
            return False
        raw = read_alignment_csv(csv_path)
        meta_rows, _ = load_rows_with_metadata(csv_path)
        for r, m in zip(raw, meta_rows):  # keep flags/confidence from the sidecar
            r.flags, r.confidence = list(m.flags), m.confidence
        h = row_content_hash(row.img_id, row.ch_txt, row.vi_txt)
        idx = next(
            (i for i, r in enumerate(raw)
             if r.sentence_id == row.sentence_id and row_content_hash(r.img_id, r.ch_txt, r.vi_txt) == h),
            None,
        )
        if idx is None:
            st.error("Dòng này đã thay đổi trên đĩa (hoặc có patch chưa áp dụng); tải lại trang.")
            return False
        patches = []
        if edit_ch is not None or edit_vi is not None:
            try:
                new_ch, new_vi, new_rows = apply_row_edit(pairs, ch_labels, vi_labels, raw, idx, edit_ch, edit_vi)
            except EditError as exc:
                st.error(f"Không sửa được: {exc}")
                return False
            for name, new_val, old_val in (("ch_txt", edit_ch, raw[idx].ch_txt), ("vi_txt", edit_vi, raw[idx].vi_txt)):
                if new_val is not None and new_val != old_val:
                    patches.append(make_patch(raw[idx], book_id=book.book_id, field=name, after=new_val,
                                              reviewer=reviewer.strip(), reason=reason.strip()))
            recompute_row_diff(new_rows[idx], **_recompute_context(project, book))
            raw = new_rows
            if edit_ch is not None:
                atomic_save_labels(new_ch, label_dir / "ch" / "Label.txt", "ch")
            if edit_vi is not None:
                atomic_save_labels(new_vi, label_dir / "vi" / "Label.txt", "vi")
        if mutate is not None:
            import copy as _copy

            snapshot = _copy.deepcopy(raw[idx])
            mutate(raw[idx])
            after_diff = raw[idx].text_diff_json()
            if after_diff != snapshot.text_diff_json():  # logged so the choice survives a re-alignment
                patches.append(make_patch(snapshot, book_id=book.book_id, field="text_diff", after=after_diff,
                                          reviewer=reviewer.strip(), reason=reason.strip() or "text_diff review"))
        atomic_save_csv(csv_path, raw)
        for patch in patches:  # audit trail; re-applying is a no-op thanks to after/hash checks
            append_patch(patch_path, patch)
        return True

    reds = [(k, el) for k, el in enumerate(row.text_diff or []) if el.type == "error"]
    if reds:
        st.markdown("**Phần tử đỏ** — chỉ chuyển sang vàng khi khác số chữ nhưng đúng nghĩa (tên riêng, năm), theo v2.4")
        for k, el in reds:
            c1, c2 = st.columns([4, 1])
            c1.write(f"{el.nom_sub_text or '∅'} ↔ {el.vi_sub_text or '∅'}")
            if c2.button("→ Vàng (tên riêng/năm)", key=f"y{k}") and _persist(mutate=lambda r, k=k: mark_as_warn(r, k)):
                st.rerun()

    st.markdown("**Cảnh báo vàng**")
    suggestions = [(k, el) for k, el in enumerate(row.text_diff or []) if el.type == "warn" and el.suggest]
    if suggestions:
        st.markdown("**Gợi ý thay chữ Nôm** — so ô đỏ trên ảnh với chữ gợi ý; *Nhận* thay chữ vào Label.txt và CSV "
                    "(thành đen), *Bỏ* giữ chữ OCR và tô đỏ (v2.4).")
        cols = st.columns(min(4, len(suggestions)))
        for j, (k, el) in enumerate(suggestions):
            with cols[j % len(cols)]:
                loc = None
                try:
                    loc = nom_char_location(pairs, ch_labels, rows, row_i, el.nom_pos[0][0])
                except Exception:  # noqa: BLE001 - the crop is a convenience
                    loc = None
                crop = _glyph_crop(native / loc[0], ch_labels, loc[0], loc[1], loc[2], loc[3]) if loc else None
                if crop is not None:
                    st.image(crop, caption=f"ảnh in · {loc[0].rsplit('.', 2)[-2]} cột {loc[1] + 1}")
                else:
                    st.caption("(không định vị được chữ trên ảnh)")
                st.markdown(
                    f"<div style=\"font-family:{NOM_FONTS};font-size:34px\">"
                    f"<span title='chữ OCR'>{html.escape(el.nom_sub_text)}</span> → "
                    f"<span title='chữ gợi ý' style='color:#0a7d2c'>{html.escape(el.suggest)}</span></div>"
                    f"<div>{html.escape(el.vi_sub_text)}</div>",
                    unsafe_allow_html=True,
                )
                keep = st.checkbox("đúng chữ gợi ý", value=True, key=f"rowsug|{row.sentence_id}|{el.nom_pos[0][0]}")
                st.session_state.setdefault("_rowsug", {})[(row.sentence_id, el.nom_pos[0][0])] = keep
        picks = {pos: st.session_state["_rowsug"].get((row.sentence_id, pos), True)
                 for pos in (el.nom_pos[0][0] for _k, el in suggestions)}
        n_yes = sum(picks.values())
        if st.button(f"Áp dụng gợi ý của câu này: nhận {n_yes}, bỏ {len(picks) - n_yes}"):
            if not reviewer.strip():
                st.error("Cần nhập người review.")
            else:
                op = (row.sentence_id, row_content_hash(row.img_id, row.ch_txt, row.vi_txt),
                      {p for p, y in picks.items() if y}, {p for p, y in picks.items() if not y})
                done, skipped = _apply_suggestions(project, book, csv_path, label_dir, patch_path, pairs, ch_labels,
                                                   vi_labels, [op], reviewer.strip(), reason.strip())
                if skipped:
                    st.error("Dòng này đã thay đổi trên đĩa; tải lại trang.")
                else:
                    st.session_state.flash = f"Đã xử lý {len(picks)} gợi ý (nhận {n_yes}, bỏ {len(picks) - n_yes})."
                    st.rerun()
    for k, el in enumerate(row.text_diff or []):
        if el.type != "warn" or el.suggest:  # suggestions are resolved above (accept/reject), never "Duyệt"
            continue
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        c1.write(
            f"{el.nom_sub_text} ↔ {el.vi_sub_text} · reviewed={el.reviewed or 0}"
            + (f" · gợi ý {el.suggest} ({el.suggest_by})" if el.suggest else "")
        )
        if c2.button("Duyệt", key=f"w{k}") and _persist(mutate=lambda r, k=k: accept_warn(r, k)):
            st.rerun()
        same = sum(1 for r in rows for e in (r.text_diff or [])
                   if e.type == "warn" and not e.suggest and e.reviewed != 1
                   and e.nom_sub_text == el.nom_sub_text and e.vi_sub_text == el.vi_sub_text)
        if same > 1 and c3.button(f"Duyệt cả {same} lần", key=f"wa{k}",
                                  help="Mọi phần tử vàng chưa duyệt có CÙNG chữ Nôm và CÙNG chữ Quốc ngữ trong sách"):
            if not reviewer.strip():
                st.error("Cần nhập người review.")
            else:
                n_done, n_skip = _review_everywhere(project, book, csv_path, patch_path, el.nom_sub_text,
                                                    el.vi_sub_text, reviewer.strip())
                st.session_state.flash = (f"Đã duyệt {n_done} phần tử “{el.nom_sub_text} ↔ {el.vi_sub_text}”."
                                          + (f" Bỏ qua {n_skip} câu đã có quyết định." if n_skip else ""))
                st.rerun()
        if el.suggest:
            if c3.button("Nhận gợi ý", key=f"s{k}") and _persist(edit_ch=suggest_edit_text(row, k)):
                st.rerun()
            if c4.button("Bỏ gợi ý", key=f"r{k}") and _persist(mutate=lambda r, k=k: reject_suggest(r, k)):
                st.rerun()

    with st.form("edit_row"):
        ch_txt = st.text_area("Nôm", value=row.ch_txt, height=120)
        vi_txt = st.text_area("Quốc ngữ", value=row.vi_txt, height=100)
        mappings_json = st.text_area(
            "Positional mappings (JSON list, optional) — e.g. "
            '[{"nom_char":"之","nom_position":0,"qn_token":"thì","qn_token_position":2}]',
            value="",
            height=60,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            save = st.form_submit_button("Lưu sửa (Label.txt + CSV)")
        with c2:
            accept_match = st.form_submit_button("✓ Chấp nhận match")
        with c3:
            accept_diff = st.form_submit_button("≈ Chấp nhận khác biệt")
        c4, c5, c6 = st.columns(3)
        with c4:
            unresolved = st.form_submit_button("? Chưa rõ (unresolved)")
        with c5:
            unmatched = st.form_submit_button("∅ Unmatched")
        with c6:
            accept_next = st.form_submit_button("✓ Chấp nhận & câu sau")

    def _parse_mappings(ch_content, vi_content):
        """Validate the complete mapping set; returns (mappings, errors)."""
        if not mappings_json.strip():
            return [], []
        import json

        try:
            raw_items = json.loads(mappings_json)
        except json.JSONDecodeError as exc:
            return None, [f"Positional mappings JSON sai: {exc}"]
        if not isinstance(raw_items, list):
            return None, ["Positional mappings phải là một danh sách JSON."]
        from hannom.review_decisions import CharacterTokenMapping, validate_mappings_against_text

        try:
            items = [CharacterTokenMapping.from_dict(item) for item in raw_items]
        except Exception as exc:  # noqa: BLE001
            return None, [f"Positional mappings không hợp lệ: {exc}"]
        errors = validate_mappings_against_text(items, ch_content, vi_content)
        if errors:
            return None, errors
        return items, []

    def _record_decision(status, decision_ch, decision_vi, decision_diff):
        from hannom.review_decisions import make_decision as _make

        mappings, mapping_errors = _parse_mappings(decision_ch, decision_vi)
        if mapping_errors:
            for error in mapping_errors:
                st.error(error)
            st.warning("Quyết định KHÔNG được ghi: tập mapping không hợp lệ.")
            return
        try:
            decision = _make(
                book_id=book.book_id,
                sentence_id=row.sentence_id,
                status=status,
                reviewer=reviewer.strip(),
                reason=reason.strip(),
                ch_txt=decision_ch,
                vi_txt=decision_vi,
                text_diff_json=decision_diff,
                character_token_mappings=mappings,
            )
            append_decision(decision_path(project.data_dir, book.book_id), decision)
            label = {"accepted_match": "Chấp nhận match", "accepted_difference": "Chấp nhận khác biệt",
                     "unresolved": "Chưa rõ", "unmatched": "Unmatched"}.get(status, status)
            st.session_state.flash = f"Đã ghi “{label}” cho {row.sentence_id.rsplit(')', 1)[-1]}."
        except Exception as exc:  # noqa: BLE001
            st.error(f"Không ghi được quyết định: {exc}")

    if save:
        ch_txt, vi_txt = normalize_cell(ch_txt, "ch_txt"), normalize_cell(vi_txt, "vi_txt")
        edit_ch = ch_txt if ch_txt != row.ch_txt else None
        edit_vi = vi_txt if vi_txt != row.vi_txt else None
        if edit_ch is None and edit_vi is None:
            st.info("Không có thay đổi nào để ghi.")
        elif _persist(edit_ch=edit_ch, edit_vi=edit_vi):
            # A saved correction is a content edit, NOT an approval of the alignment.
            st.rerun()

    if accept_match or accept_diff or unresolved or unmatched or accept_next:
        if not reviewer.strip():
            st.error("Cần nhập người review.")
        else:
            has_red = any(el.type == "error" for el in (row.text_diff or []))
            status = (
                "accepted_match" if accept_match or (accept_next and not has_red)
                else "accepted_difference" if accept_diff or accept_next
                else "unresolved" if unresolved
                else "unmatched"
            )
            if status == "accepted_match" and has_red:
                st.error("Câu còn chữ đỏ nên không thể 'match': sửa chữ, chuyển vàng (tên riêng/năm) "
                         "hoặc dùng 'Chấp nhận khác biệt'.")
                st.stop()
            already = (getattr(row, "review_status", None) == status
                       and getattr(row, "decision_integrity", None) == "valid")
            was_done = is_reviewed(row)
            if not already:  # the same verdict on the same content is not logged twice
                # The decision hash binds the approval to the persisted content.
                _record_decision(status, row.ch_txt, row.vi_txt, row.text_diff_json())
            else:
                st.session_state.flash = (f"{row.sentence_id} đã có quyết định này trên đúng nội dung hiện tại "
                                          "— không cần ghi lại.")
            if st.session_state.get("flash"):
                n_done = done + (0 if was_done or already else 1)
                st.session_state.flash += f" Đã quyết định {n_done}/{total} câu."
                if n_done == total:
                    st.session_state.flash += " Sách này đã quyết định đủ."
            if accept_next and queue_pos is not None and queue_pos >= len(queue) - 1 and not hide_done:
                st.session_state.flash = (st.session_state.get("flash") or "") + \
                    " Đây là câu cuối của hàng đợi nên app không chuyển tiếp."
            if accept_next:
                nxt = next_position(queue, row_i, queue_pos, st.session_state.row_index)
                if hide_done and queue_pos is not None:
                    nxt = queue_pos  # the accepted row leaves the queue; the next one takes its slot
                st.session_state.row_index = nxt
                st.session_state.pinned_sid = None
            st.rerun()


if __name__ == "__main__":
    main()
