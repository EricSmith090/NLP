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
    progress,
    recompute_row_diff,
    red_density,
    reject_suggest,
    review_queue,
    suggest_edit_text,
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


def _overlay(image_path: Path, labels: dict, folder: str, image_name: str) -> Image.Image:
    """Draw the boxes of ``<folder>/<image_name>`` from an already-read Label dict."""
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in labels.get(f"{folder}/{image_name}") or []:
        points = box.get("points") or []
        if len(points) == 4:
            draw.polygon([tuple(float(v) for v in point) for point in points], outline=(0, 160, 0), width=2)
    return image


def _read_labels(path: Path) -> dict:
    try:
        return read_label_txt(path) if path.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _recompute_context(project, book) -> dict:
    """Lexicon / dictionary / readings cache as ``stage_align`` builds them (empty on failure)."""
    try:
        from hannom.dictionary.book_lexicon import BookLexicon
        from hannom.dictionary.index import build_dictionary_index
        from hannom.orchestrator import load_readings_cache

        lexicon = BookLexicon(project.data_dir / "dictionary" / "book_lexicons" / f"{book.book_id}.json")
        dictionary = build_dictionary_index(project.root, project.dictionary_config or {}, book_id=book.book_id)
        return {"lexicon": lexicon, "dictionary": dictionary, "readings_cache": load_readings_cache(project)}
    except Exception:  # noqa: BLE001
        return {}


def main() -> None:
    st.set_page_config(page_title="Hán Nôm review", layout="wide")
    st.title("Hán Nôm–Quốc ngữ review")

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
    st.sidebar.progress(done / total if total else 0.0, text=f"Đã review {done}/{total}")
    mode = st.sidebar.selectbox(
        "Hàng đợi",
        ["red", "manual", "warn", "all"],
        format_func={
            "red": "Mật độ đỏ giảm dần",
            "manual": "Null / <5 ký tự (thủ công)",
            "warn": "Còn vàng chưa duyệt",
            "all": "Tất cả",
        }.get,
    )
    hide_done = st.sidebar.checkbox("Ẩn dòng đã review", value=False)
    queue = review_queue(rows, mode, include_reviewed=not hide_done)
    if not queue:
        st.success("Hàng đợi trống.")
        return
    if "row_index" not in st.session_state:
        st.session_state.row_index = 0
    st.session_state.row_index = max(0, min(st.session_state.row_index, len(queue) - 1))
    position = st.sidebar.number_input(
        "Vị trí", min_value=1, max_value=len(queue), value=st.session_state.row_index + 1, step=1
    ) - 1
    st.session_state.row_index = int(position)
    row = rows[queue[st.session_state.row_index]]
    st.sidebar.write(f"`{row.sentence_id}` · đỏ {red_density(row):.0%}")
    if st.sidebar.button("← Câu trước"):
        st.session_state.row_index = max(0, st.session_state.row_index - 1)
        st.rerun()
    if st.sidebar.button("Câu sau →"):
        st.session_state.row_index = min(len(queue) - 1, st.session_state.row_index + 1)
        st.rerun()
    reviewer = st.sidebar.text_input("Người review", value=os.environ.get("USERNAME", ""))
    reason = st.sidebar.text_input("Lý do", value="")

    nom_spans = [(s0, e0, el.type) for el in (row.text_diff or []) for s0, e0 in el.nom_pos]
    vi_spans = [(s0, e0, el.type) for el in (row.text_diff or []) for s0, e0 in el.vi_pos]
    native = project.data_dir / "pages" / book.book_id / "native"
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Ảnh")
        if (native / row.img_id).exists():
            # Folder-specific Label.txt: Nôm boxes come from ch/, QN boxes from vi/.
            st.image(_overlay(native / row.img_id, ch_labels, "ch", row.img_id), caption=row.img_id,
                     use_container_width=True)
        else:
            st.warning(f"Không thấy ảnh: {native / row.img_id}")
        for pair in pairs:
            if row.img_id in pair.ch:
                for vi_img in pair.vi:
                    if (native / vi_img).exists():
                        st.image(_overlay(native / vi_img, vi_labels, "vi", vi_img), caption=vi_img,
                                 use_container_width=True)
                break
        st.write(f"Confidence: {row.confidence if row.confidence is not None else 'N/A'}")
        st.code(", ".join(row.flags) or "(none)")
    with right:
        st.subheader("Căn hàng")
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
        st.caption(f"text_diff: {diff_summary(row.text_diff)}")

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
            mutate(raw[idx])
        atomic_save_csv(csv_path, raw)
        for patch in patches:  # audit trail; re-applying is a no-op thanks to after/hash checks
            append_patch(patch_path, patch)
        return True

    st.markdown("**Cảnh báo vàng**")
    for k, el in enumerate(row.text_diff or []):
        if el.type != "warn":
            continue
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        c1.write(
            f"{el.nom_sub_text} ↔ {el.vi_sub_text} · reviewed={el.reviewed or 0}"
            + (f" · gợi ý {el.suggest} ({el.suggest_by})" if el.suggest else "")
        )
        if c2.button("Duyệt", key=f"w{k}") and _persist(mutate=lambda r, k=k: accept_warn(r, k)):
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
            st.success(f"Đã ghi quyết định '{status}' cho {row.sentence_id}.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Không ghi được quyết định: {exc}")

    if save:
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
            # The decision hash binds the approval to the persisted content.
            _record_decision(status, row.ch_txt, row.vi_txt, row.text_diff_json())
            if accept_next:
                st.session_state.row_index = min(len(queue) - 1, st.session_state.row_index + 1)
            st.rerun()


if __name__ == "__main__":
    main()
