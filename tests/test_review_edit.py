from hannom.align import read_alignment_csv, write_alignment_csv
from hannom.models import AlignmentRow, DiffElement
from hannom.review.edit import (
    EditError, accept_warn, apply_row_edit, progress, recompute_row_diff, red_density, review_queue,
)
from hannom.review.patches import (
    ReviewPatch, append_patch, apply_patches, apply_patches_checked, make_patch, read_patches,
)
from hannom.sync_check import check_sync
import pytest


def box(t):
    return {"transcription": t, "points": [[0, 0], [1, 0], [1, 1], [0, 1]], "difficult": False}


PAIRS = [{"ch": ["c1.jpg"], "vi": ["v1.jpg"]}]


def build():
    ch = {"ch/c1.jpg": [box("天地人"), box("日月星")]}
    vi = {"vi/v1.jpg": [box("Thiên địa nhân nhật-nguyệt tinh")]}
    rows = [
        AlignmentRow("c1.jpg", "s1", "天地", "Thiên địa"),
        AlignmentRow("c1.jpg", "s2", "人日", "nhân nhật-"),
        AlignmentRow("c1.jpg", "s3", "月星", "nguyệt tinh"),
    ]
    return ch, vi, rows


def sync(ch, vi, rows):
    d = [{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in rows]
    return check_sync(d, ch, vi, PAIRS)


def test_fixture_in_sync():
    assert sync(*build()) == []


def test_nom_edit_inside_one_box():
    ch, vi, rows = build()
    c2, v2, r2 = apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="天下")
    assert c2["ch/c1.jpg"][0]["transcription"] == "天下人"
    assert c2["ch/c1.jpg"][0]["points"] == ch["ch/c1.jpg"][0]["points"]
    assert sync(c2, v2, r2) == []
    assert ch["ch/c1.jpg"][0]["transcription"] == "天地人"  # input untouched


def test_nom_edit_spanning_two_boxes():
    ch, vi, rows = build()
    c2, v2, r2 = apply_row_edit(PAIRS, ch, vi, rows, 1, new_ch="仁月")
    assert [b["transcription"] for b in c2["ch/c1.jpg"]] == ["天地仁", "月月星"]
    assert sync(c2, v2, r2) == []


def test_qn_edit_with_hyphen():
    ch, vi, rows = build()
    c2, v2, r2 = apply_row_edit(PAIRS, ch, vi, rows, 1, new_vi="nhơn nhựt-")
    assert sync(c2, v2, r2) == []
    assert "nhơn nhựt-nguyệt" in v2["vi/v1.jpg"][0]["transcription"]
    c3, v3, r3 = apply_row_edit(PAIRS, ch, vi, rows, 2, new_vi="nguyệt-tinh")
    assert sync(c3, v3, r3) == []


def test_insertion_at_row_boundary():
    ch, vi, rows = build()
    c2, v2, r2 = apply_row_edit(PAIRS, ch, vi, rows, 1, new_ch="大人日")  # row start
    assert sync(c2, v2, r2) == []
    c3, v3, r3 = apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="天地大")  # row end
    assert sync(c3, v3, r3) == []
    c4, v4, r4 = apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="大天地")
    assert c4["ch/c1.jpg"][0]["transcription"].startswith("大天地")
    assert sync(c4, v4, r4) == []


def test_refuses_when_not_in_sync():
    ch, vi, rows = build()
    ch["ch/c1.jpg"][0]["transcription"] = "天地X"
    with pytest.raises(EditError):
        apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="天下")


def test_patch_survives_resegmentation_and_stale_rejected(tmp_path):
    _, _, rows = build()
    patch = make_patch(rows[1], book_id="b", field="vi_txt", after="nhơn nhật-", reviewer="r")
    log = tmp_path / "p.jsonl"
    append_patch(log, patch)
    # legacy line (no row_hash) must still be readable
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"book_id":"b","sentence_id":"s1","field":"vi_txt","before":"x","after":"y","reviewer":"r"}\n')
    patches = read_patches(log)
    assert len(patches) == 2
    # re-segmentation: the row moves and its sentence_id now names another sentence
    moved = [AlignmentRow("c1.jpg", "s1", "新", "mới"), AlignmentRow("c1.jpg", "s9", "人日", "nhân nhật-")]
    out, rejected = apply_patches_checked(moved, patches)
    assert out[1].vi_txt == "nhơn nhật-" and "CONTENT_EDITED" in out[1].flags
    assert out[0].vi_txt == "mới"
    assert len(rejected) == 1 and "stale" in rejected[0].reason or "legacy" in rejected[0].reason
    # content changed: stale, nothing overwritten
    changed = [AlignmentRow("c1.jpg", "s2", "人日", "khác")]
    out, rejected = apply_patches_checked(changed, patches[:1])
    assert out[0].vi_txt == "khác" and rejected and "stale" in rejected[0].reason
    # already applied (persisted to CSV) is a no-op, not a rejection
    done = [AlignmentRow("c1.jpg", "s2", "人日", "nhơn nhật-")]
    assert apply_patches_checked(done, patches[:1])[1] == []
    assert apply_patches(changed, patches[:1])[0].vi_txt == "khác"


def test_accept_warn_roundtrips_csv(tmp_path):
    warn = DiffElement(((0, 1),), "天", ((0, 1),), "x", "warn", reviewed=0, suggest="夫", suggest_by="m")
    err = DiffElement(((1, 2),), "地", ((1, 2),), "y", "error")
    row = AlignmentRow("c1.jpg", "s1", "天地", "x y", text_diff=[warn, err])
    accept_warn(row, 0)
    assert row.text_diff[0].reviewed == 1
    path = tmp_path / "a.csv"
    write_alignment_csv(path, [row])
    back = read_alignment_csv(path)[0]
    assert back.text_diff[0].reviewed == 1 and back.text_diff[0].suggest == "夫"
    with pytest.raises(EditError):
        accept_warn(row, 1)


def test_recompute_marks_edited_and_queue():
    row = AlignmentRow("c1.jpg", "s1", "天地人日月", "thiên địa nhân nhật nguyệt")
    recompute_row_diff(row)
    assert "CONTENT_EDITED" in row.flags and row.text_diff is not None
    hi = AlignmentRow("i", "a", "天地人日月", "a b c d e", text_diff=[
        DiffElement(((0, 3),), "天地人", ((0, 1),), "a", "error")])
    lo = AlignmentRow("i", "b", "天地人日月", "a b c d e", text_diff=[
        DiffElement(((0, 1),), "天", ((0, 1),), "a", "error")])
    assert red_density(hi) > red_density(lo)
    assert review_queue([lo, hi], "red") == [1, 0]
    assert progress([lo, row]) == (1, 2)


def test_atomic_saves_keep_a_backup_and_sidecar(tmp_path):
    from hannom.align import read_alignment_csv, write_alignment_csv
    from hannom.models import AlignmentRow
    from hannom.review.edit import atomic_save_csv, atomic_save_labels
    from hannom.review_metadata import sidecar_path

    csv_path = tmp_path / "B.csv"
    rows = [AlignmentRow("B.276.jpg", "B.276.1", "天主", "Thiên Chúa", [])]
    write_alignment_csv(csv_path, rows)
    rows[0].vi_txt = "Thiên Chúa Trời"
    atomic_save_csv(csv_path, rows)
    assert read_alignment_csv(csv_path)[0].vi_txt == "Thiên Chúa Trời"
    assert (tmp_path / "B.csv.bak-review").exists() and sidecar_path(csv_path).exists()
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == []  # temp dir cleaned up
    lab = tmp_path / "ch" / "Label.txt"
    lab.parent.mkdir()
    atomic_save_labels({"ch/B.276.jpg": [{"transcription": "天主", "points": [[0, 0], [1, 0], [1, 1], [0, 1]], "difficult": False}]}, lab, "ch")
    assert "天主" in lab.read_text(encoding="utf-8")


def test_labels_stage_refuses_to_discard_reviewer_edits(tmp_path):
    import pytest

    from hannom.orchestrator import PipelineError, stage_labels
    from hannom.review.patches import ReviewPatch, append_patch
    from test_ocr_warning_propagation import _project

    project = _project(tmp_path)
    book = project.books[0]
    import dataclasses
    fields = {f.name for f in dataclasses.fields(ReviewPatch)}
    kw = {"book_id": book.book_id, "sentence_id": "T.001.1", "field": "ch_txt", "before": "天", "after": "主", "reviewer": "r", "reason": "ocr"}
    append_patch(project.data_dir / "review" / f"{book.book_id}.patches.jsonl", ReviewPatch(**{k: v for k, v in kw.items() if k in fields}))
    with pytest.raises(PipelineError, match="overwrite-reviewed"):
        stage_labels(project, book, state=None)
