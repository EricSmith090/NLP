"""Local Streamlit review app for alignment and text_diff.

Run from the repository root:

    streamlit run src/hannom/review/app.py

The app reads the draft CSV, displays the exact submitted image and boxes,
and appends provenance-preserving patches. It never edits automated JSON
files in place.
"""

from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

# Streamlit executes this file directly, so make ``src`` importable.
SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from hannom.config import load_config  # noqa: E402
from hannom.labels import read_label_txt  # noqa: E402
from hannom.review.patches import ReviewPatch, append_patch, apply_patches, read_patches  # noqa: E402
from hannom.review_metadata import load_rows_with_metadata  # noqa: E402
from hannom.state import State  # noqa: E402
from hannom.textdiff import diff_summary, make_element  # noqa: E402


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


def _overlay(image_path: Path, label_path: Path, image_name: str) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    if not label_path.exists():
        return image
    try:
        labels = read_label_txt(label_path)
    except Exception:
        return image
    boxes = labels.get(f"ch/{image_name}") or labels.get(f"vi/{image_name}") or []
    draw = ImageDraw.Draw(image)
    for box in boxes:
        points = box.get("points") or []
        if len(points) == 4:
            draw.polygon([tuple(float(v) for v in point) for point in points], outline=(0, 160, 0), width=2)
    return image


def main() -> None:
    st.set_page_config(page_title="Hán Nôm review", layout="wide")
    st.title("Hán Nôm–Quốc ngữ review")
    st.caption("Phím tắt gợi ý: j = câu sau, k = câu trước, a = chấp nhận, f = đánh dấu. "
               "Các nút bên dưới thực hiện cùng thao tác khi dùng chuột.")

    project_root = Path(os.environ.get("HANNOM_PROJECT", ".")).resolve()
    try:
        project = load_config(project_root / "configs" / "project.yaml")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Không đọc được cấu hình: {exc}")
        return
    book_ids = [book.book_id for book in project.books]
    book_id = st.sidebar.selectbox("Sách", book_ids)
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
    rows = apply_patches(rows, read_patches(patch_path))

    st.sidebar.metric("Số dòng", len(rows))
    only_flagged = st.sidebar.checkbox("Chỉ dòng cần review", value=True)
    indexed = list(enumerate(rows))
    if only_flagged:
        indexed = [
            (i, row)
            for i, row in indexed
            if any(
                flag.startswith(("ALIGN_LOW_CONF", "DIFF_", "REVIEW:", "OCR_", "BBOX_", "REVIEW_METADATA_", "UNMATCHED_"))
                for flag in row.flags
            )
        ]
    if not indexed:
        st.success("Không còn dòng bị đánh dấu.")
        return
    if "row_index" not in st.session_state:
        st.session_state.row_index = 0
    st.session_state.row_index = max(0, min(st.session_state.row_index, len(indexed) - 1))
    position = st.sidebar.number_input(
        "Vị trí", min_value=1, max_value=len(indexed),
        value=st.session_state.row_index + 1, step=1,
    ) - 1
    st.session_state.row_index = int(position)
    original_index, row = indexed[st.session_state.row_index]
    st.sidebar.write(f"`{row.sentence_id}`")
    if st.sidebar.button("← Câu trước (k)"):
        st.session_state.row_index = max(0, st.session_state.row_index - 1)
        st.rerun()
    if st.sidebar.button("Câu sau → (j)"):
        st.session_state.row_index = min(len(indexed) - 1, st.session_state.row_index + 1)
        st.rerun()

    nom_spans = [
        (start, end, element.type)
        for element in (row.text_diff or [])
        for start, end in element.nom_pos
    ]
    vi_spans = [
        (start, end, element.type)
        for element in (row.text_diff or [])
        for start, end in element.vi_pos
    ]
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Ảnh")
        image_path = project.data_dir / "pages" / book.book_id / "native" / row.img_id
        if image_path.exists():
            label_dir = project.data_dir / "labels" / book.book_id
            folder = "ch" if row.img_id else "vi"
            overlay = _overlay(image_path, label_dir / folder / "Label.txt", row.img_id)
            st.image(overlay, caption=row.img_id, use_container_width=True)
        else:
            st.warning(f"Không thấy ảnh: {image_path}")
        st.write(f"Confidence: {row.confidence if row.confidence is not None else 'N/A'}")
        st.code(", ".join(row.flags) or "(none)")
    with right:
        st.subheader("Căn hàng")
        st.markdown("**Nôm**", unsafe_allow_html=True)
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

    with st.form("edit_row"):
        ch_txt = st.text_area("Nôm", value=row.ch_txt, height=120)
        vi_txt = st.text_area("Quốc ngữ", value=row.vi_txt, height=100)
        diff_json = st.text_area(
            "text_diff JSON (null hoặc mảng; sửa thủ công nếu cần)",
            value=row.text_diff_json(),
            height=150,
        )
        reviewer = st.text_input("Người review", value=os.environ.get("USERNAME", ""))
        reason = st.text_input("Lý do", value="")
        c1, c2, c3 = st.columns(3)
        with c1:
            add_span = st.form_submit_button("Thêm span màu")
        with c2:
            save = st.form_submit_button("Lưu patch")
        with c3:
            accept = st.form_submit_button("Chấp nhận (không đổi)")

        # The span builder is intentionally explicit: the reviewer supplies
        # exact half-open code-point positions and the type.
        s1, s2, s3, s4 = st.columns(4)
        with s1:
            nom_start = st.number_input("nom start", min_value=0, value=0, step=1)
        with s2:
            nom_end = st.number_input("nom end", min_value=0, value=0, step=1)
        with s3:
            vi_start = st.number_input("vi start", min_value=0, value=0, step=1)
        with s4:
            vi_end = st.number_input("vi end", min_value=0, value=0, step=1)
        span_type = st.selectbox("Loại", ["error", "warn"])

    if add_span:
        try:
            element = make_element(
                ch_txt,
                vi_txt,
                [[int(nom_start), int(nom_end)]] if nom_end > nom_start else [],
                [[int(vi_start), int(vi_end)]] if vi_end > vi_start else [],
                span_type,
            )
            existing = json.loads(diff_json) if diff_json.strip() not in {"", "null"} else []
            existing.append(element.to_dict())
            st.session_state["pending_diff"] = json.dumps(existing, ensure_ascii=False)
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Span không hợp lệ: {exc}")

    if save or accept:
        if accept:
            ch_txt, vi_txt, diff_json = row.ch_txt, row.vi_txt, row.text_diff_json()
        if not reviewer.strip():
            st.error("Cần nhập người review.")
        else:
            state = State(project.data_dir / "state.sqlite3")
            try:
                for field, before, after in (
                    ("ch_txt", row.ch_txt, ch_txt),
                    ("vi_txt", row.vi_txt, vi_txt),
                    ("text_diff", row.text_diff_json(), diff_json),
                ):
                    if before != after:
                        patch = ReviewPatch(
                            book_id=book.book_id,
                            sentence_id=row.sentence_id,
                            field=field,
                            before=before,
                            after=after,
                            reviewer=reviewer.strip(),
                            reason=reason.strip(),
                        )
                        append_patch(patch_path, patch)
                        state.add_review(
                            book.book_id, field, before, after,
                            reviewer.strip(), reason.strip() or None,
                        )
                st.success("Đã ghi patch. Chạy lại bước align/text_diff để áp dụng.")
            finally:
                state.close()
            st.rerun()

    if st.session_state.get("pending_diff"):
        st.info("Có span đang chờ. Dán JSON này vào ô text_diff nếu muốn giữ:")
        st.code(st.session_state["pending_diff"])


if __name__ == "__main__":
    main()
