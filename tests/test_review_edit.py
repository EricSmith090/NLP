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


# --- QN spacing: Label.txt must hold exactly what the reviewer typed ----------
# SYNC ignores whitespace, so these tests compare Label.txt text directly.
# Regression for the 2026-11-21 finding: "vào ngục." -> "vào hơn." was stored
# in Label.txt as "vàohơ n." while the CSV and SYNC looked fine.

QN_PAIRS = [{"ch": ["c1.jpg"], "vi": ["v1.jpg"]}]


def build_qn(*row_texts):
    nom = {"ch/c1.jpg": [box("天" * sum(len(t.split()) for t in row_texts))]}
    vi = {"vi/v1.jpg": [box(" ".join(row_texts))]}
    rows = [AlignmentRow("c1.jpg", f"s{i}", "天" * len(t.split()), t) for i, t in enumerate(row_texts)]
    return nom, vi, rows


def vi_text(vi, key="vi/v1.jpg"):
    return " | ".join(b["transcription"] for b in vi[key])


def test_qn_insert_keeps_typed_spacing():
    ch, vi, rows = build_qn("Song có ba cửa rộng lớn, nhiều người vào ngục.", "Song có ba cửa")
    typed = "Song có ba cửa rộng lớn, nhiều người vào hơn. Rầy con hãy"
    _, v2, r2 = apply_row_edit(QN_PAIRS, ch, vi, rows, 0, new_vi=typed)
    assert vi_text(v2) == typed + " Song có ba cửa"
    assert r2[0].vi_txt == typed


def test_qn_delete_words_leaves_single_spaces():
    ch, vi, rows = build_qn("Một hai ba bốn.", "Năm sáu.")
    _, v2, _ = apply_row_edit(QN_PAIRS, ch, vi, rows, 0, new_vi="Một bốn.")
    assert vi_text(v2) == "Một bốn. Năm sáu."
    _, v3, _ = apply_row_edit(QN_PAIRS, ch, vi, rows, 1, new_vi="Năm.")
    assert vi_text(v3) == "Một hai ba bốn. Năm."


def test_qn_edit_middle_row_keeps_neighbours():
    ch, vi, rows = build_qn("Một hai.", "ba bốn năm.", "sáu bảy.")
    _, v2, _ = apply_row_edit(QN_PAIRS, ch, vi, rows, 1, new_vi="ba, bốn và năm.")
    assert vi_text(v2) == "Một hai. ba, bốn và năm. sáu bảy."
    _, v3, _ = apply_row_edit(QN_PAIRS, ch, vi, rows, 1, new_vi="lẽ ấy, nếu con lấy tội mọn")
    assert vi_text(v3) == "Một hai. lẽ ấy, nếu con lấy tội mọn sáu bảy."


def test_qn_edit_row_spanning_two_pages():
    pairs = [{"ch": ["c1.jpg"], "vi": ["v1.jpg"]}, {"ch": ["c2.jpg"], "vi": ["v2.jpg"]}]
    vi = {"vi/v1.jpg": [box("Câu một. Câu hai bắt")], "vi/v2.jpg": [box("đầu ở trang trước. Câu ba.")]}
    ch = {"ch/c1.jpg": [box("天天天天天")], "ch/c2.jpg": [box("天天天天天天天")]}
    rows = [
        AlignmentRow("c1.jpg", "s1", "天天", "Câu một."),
        AlignmentRow("c1.jpg", "s2", "天天天天天天天天", "Câu hai bắt đầu ở trang trước."),
        AlignmentRow("c2.jpg", "s3", "天天", "Câu ba."),
    ]
    _, v2, _ = apply_row_edit(pairs, ch, vi, rows, 1, new_vi="Câu hai thật sự bắt đầu ở trang trước.")
    assert vi_text(v2, "vi/v1.jpg") == "Câu một. Câu hai thật sự bắt"
    assert vi_text(v2, "vi/v2.jpg") == "đầu ở trang trước. Câu ba."
    _, v3, _ = apply_row_edit(pairs, ch, vi, rows, 1, new_vi="Câu hai bắt đầu ở trang sau này.")
    assert vi_text(v3, "vi/v1.jpg") == "Câu một. Câu hai bắt"
    assert vi_text(v3, "vi/v2.jpg") == "đầu ở trang sau này. Câu ba."


def test_respace_repairs_label_damaged_by_old_edits():
    from hannom.review.edit import respace_vi_rows

    ch, vi, rows = build_qn("Song có ba cửa rộng lớn, nhiều người vào hơn. Rầy con hãy", "Song có ba cửa")
    vi["vi/v1.jpg"][0]["transcription"] = "Song có ba cửa rộng lớn, nhiều người vàohơ n. Rầyc onhãy   Song có ba cửa"
    assert sync(ch, vi, rows) == []  # SYNC cannot see the damage
    v2, changed = respace_vi_rows(QN_PAIRS, vi, rows, [0, 1])
    assert vi_text(v2) == "Song có ba cửa rộng lớn, nhiều người vào hơn. Rầy con hãy Song có ba cửa"
    assert changed == [0]
    assert vi["vi/v1.jpg"][0]["transcription"].startswith("Song có ba cửa rộng lớn, nhiều người vàohơ n.")  # input untouched


def test_same_length_substitution_stays_in_its_column():
    # Suggestion grid: 〓 -> 没 when 没 already follows. A diff can match the
    # existing 没 against the first new one and move characters across boxes.
    ch = {"ch/c1.jpg": [box("天〓〓"), box("没地")]}
    vi = {"vi/v1.jpg": [box("thiên một một một địa")]}
    rows = [AlignmentRow("c1.jpg", "s1", "天〓〓没地", "thiên một một một địa")]
    c2, v2, r2 = apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="天没没没地")
    assert [b["transcription"] for b in c2["ch/c1.jpg"]] == ["天没没", "没地"]
    assert sync(c2, v2, r2) == []
    # Found by a randomised check (243/5000 cases moved a char, old and new
    # diff-based code alike): the diff matched the existing 没 too early.
    ch = {"ch/c1.jpg": [box("地天〓"), box("没〓地")]}
    rows = [AlignmentRow("c1.jpg", "s1", "地天〓没〓地", "thiên một một một địa")]
    c3, v3, r3 = apply_row_edit(PAIRS, ch, vi, rows, 0, new_ch="地天没没没地")
    assert [b["transcription"] for b in c3["ch/c1.jpg"]] == ["地天没", "没没地"]
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
    # a saved edit without a decision is NOT counted as reviewed; it waits in its own queue
    assert progress([lo, row]) == (0, 2)
    assert review_queue([lo, row], "pending") == [1]
    row.review_status = "accepted_difference"
    assert progress([lo, row]) == (1, 2) and review_queue([lo, row], "pending") == []


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


def test_select_row_keeps_the_edited_row_pinned():
    from types import SimpleNamespace

    from hannom.review.edit import next_position, select_row

    rows = [SimpleNamespace(sentence_id=f"B.1.{i}") for i in range(5)]
    queue = [3, 1, 4]  # red-density order
    assert select_row(rows, queue, 1, None) == (1, 1)
    # after an edit the pinned row moved in the queue: still shown, new position reported
    assert select_row(rows, [3, 4, 1], 1, "B.1.1") == (1, 2)
    # after an edit removed all its red it left the queue: still shown, position None
    assert select_row(rows, [3, 4], 1, "B.1.1") == (1, None)
    # accepting: next row in the queue, or the row now in the old slot when it left
    assert next_position([3, 1, 4], 1, 1, 1) == 2
    assert next_position([3, 4], 1, None, 1) == 1


def test_history_search_and_reviewed_order():
    from types import SimpleNamespace

    from hannom.review.edit import find_rows, review_history, reviewed_order

    rows = [SimpleNamespace(sentence_id=f"B (T).487.{i}", ch_txt="天主" if i == 2 else "x", vi_txt=f"câu {i}",
                            flags=["CONTENT_EDITED"] if i == 9 else [], review_status=None) for i in range(1, 11)]
    patches = [SimpleNamespace(sentence_id="B (T).487.9", field="vi_txt", before="a", after="b", reviewer="r",
                               timestamp="2026-11-20T01:20:22")]
    decisions = [SimpleNamespace(sentence_id="B (T).487.3", status="unresolved", reviewer="r",
                                 timestamp="2026-11-20T01:30:00", reason="")]
    hist = review_history(patches, decisions)
    assert [h["sentence_id"] for h in hist] == ["B (T).487.3", "B (T).487.9"]
    assert [rows[i].sentence_id for i in reviewed_order(rows, hist)] == ["B (T).487.3", "B (T).487.9"]
    assert [rows[i].sentence_id for i in find_rows(rows, "487.9")] == ["B (T).487.9"]
    assert [rows[i].sentence_id for i in find_rows(rows, "天主")] == ["B (T).487.2"]
    assert find_rows(rows, "CÂU 5") == [4]


def test_reapplied_text_patch_gets_its_text_diff_recomputed():
    from hannom.models import AlignmentRow, DiffElement
    from hannom.orchestrator import recompute_text_diff
    from hannom.review.patches import apply_patches_checked, make_patch
    from hannom.textdiff import validate_text_diff

    class Lex:
        def readings(self, ch):
            return {"天": ["thiên"], "主": ["chúa"]}.get(ch, [])

    stale = [DiffElement(((1, 2),), "主", ((6, 7),), "x", "error")]
    row = AlignmentRow("B.001.jpg", "B.001.1", "天主", "Thiên x", stale)
    p = make_patch(row, book_id="B", field="vi_txt", after="Thiên Chúa", reviewer="r", reason="ocr")
    fresh = AlignmentRow("B.001.jpg", "B.001.1", "天主", "Thiên x", list(stale))
    rows, rejected = apply_patches_checked([fresh], [p])
    assert not rejected and "TEXT_DIFF_STALE" in rows[0].flags
    out = recompute_text_diff(rows, lexicon=Lex(), dictionary=None)[0]
    assert out.text_diff == [] and validate_text_diff(out.ch_txt, out.vi_txt, out.text_diff) == []
    assert "TEXT_DIFF_STALE" not in out.flags and "CONTENT_EDITED" in out.flags


def test_row_locations_point_to_boxes_and_page_share():
    from types import SimpleNamespace

    from hannom.review.edit import row_locations
    from hannom.t1_map import Pair

    pairs = [Pair(ch=("B.276.jpg",), vi=("B.013.jpg",))]
    ch = {"ch/B.276.jpg": [{"transcription": "天主"}, {"transcription": "聖神"}, {"transcription": "阿綿"}]}
    vi = {"vi/B.013.jpg": [{"transcription": "Thiên Chúa Thánh Thần A-men"}]}
    rows = [SimpleNamespace(ch_txt="天主聖", vi_txt="Thiên Chúa Thánh"), SimpleNamespace(ch_txt="神阿綿", vi_txt="Thần A-men")]
    loc = row_locations(pairs, ch, vi, rows, 1)
    assert loc["ch"] == {"B.276.jpg": [1, 2]}
    a, b = loc["vi"]["B.013.jpg"]
    assert 0.5 < a < 0.7 and b == 1.0


def test_mark_as_warn_and_text_diff_patch_survives_realignment():
    import copy

    from hannom.models import AlignmentRow, DiffElement
    from hannom.review.edit import mark_as_warn
    from hannom.review.patches import apply_patches_checked, make_patch

    err = DiffElement(((0, 2),), "阿綿", ((0, 4),), "Amen", "error")
    row = AlignmentRow("B.067.jpg", "B.067.1", "阿綿", "Amen.", [err])
    snap = copy.deepcopy(row)
    mark_as_warn(row, 0)
    assert row.text_diff[0].type == "warn" and row.text_diff[0].reviewed == 1
    p = make_patch(snap, book_id="B", field="text_diff", after=row.text_diff_json(), reviewer="r")
    fresh = AlignmentRow("B.067.jpg", "B.067.1", "阿綿", "Amen.", [err])  # what a re-alignment produces
    out, rejected = apply_patches_checked([fresh], [p])
    assert not rejected and out[0].text_diff[0].type == "warn" and out[0].text_diff[0].reviewed == 1


def test_any_red_queue_keeps_reading_order_and_qn_only_red():
    black = AlignmentRow("i", "a", "天地人日月", "a b c d e", text_diff=[])
    nom_red = AlignmentRow("i", "b", "天地人日月", "a b c d e", text_diff=[
        DiffElement(((0, 1),), "天", ((0, 1),), "a", "error")])
    qn_only = AlignmentRow("i", "c", "天地人日月", "a b c d e x y", text_diff=[
        DiffElement((), "", ((10, 13),), "x y", "error")])  # extra QN words: 0 % Nôm red
    yellow = AlignmentRow("i", "d", "天地人日月", "a b c d e", text_diff=[
        DiffElement(((0, 1),), "天", ((0, 1),), "a", "warn", reviewed=0)])
    short = AlignmentRow("i", "e", "天地", "a b", text_diff=[])
    rows = [nom_red, black, qn_only, yellow, short]
    assert red_density(qn_only) == 0.0 and review_queue(rows, "red") == [0, 4]  # the QN-only row is missed there
    assert review_queue(rows, "any_red") == [0, 2, 4]
    nom_red.review_status = "accepted_difference"
    assert review_queue(rows, "any_red", include_reviewed=False) == [2, 4]


class _NameLex:
    """Readings for the manual-yellow tests (Tap2 539.8: 臯 has no reading "ti")."""
    READ = {"安": ["an"], "臯": ["cao"], "烏": ["ô"], "姑": ["cô"], "死": ["tử"], "𣩂": ["chết"], "皐": ["cao"]}

    def readings(self, ch):
        return self.READ.get(ch, [])


def _yellow_ti(row):
    from hannom.review.edit import mark_as_warn

    k = next(i for i, e in enumerate(row.text_diff) if e.nom_sub_text == "臯")
    mark_as_warn(row, k)
    assert row.text_diff[k].type == "warn" and row.text_diff[k].reviewed == 1


def test_manual_yellow_survives_an_edit_elsewhere_in_the_row():
    # Tap2 539.8 (2026-11-21): the reviewer turned 臯 <-> ti yellow, then accepted
    # a suggestion on another char; the recompute dropped the yellow and 臯 <-> ti
    # had to be clicked again.
    row = AlignmentRow("c.jpg", "c.1", "安臯烏姑死", "An-ti-ô-cô chết.")
    recompute_row_diff(row, lexicon=_NameLex())
    _yellow_ti(row)
    row.ch_txt = "安臯烏姑𣩂"  # another char changes (an accepted suggestion)
    recompute_row_diff(row, lexicon=_NameLex())
    ti = [e for e in row.text_diff if e.nom_sub_text == "臯"]
    assert [(e.type, e.vi_sub_text, e.reviewed) for e in ti] == [("warn", "ti", 1)]


def test_manual_yellow_is_dropped_when_its_own_char_changes():
    row = AlignmentRow("c.jpg", "c.1", "安臯烏姑死", "An-ti-ô-cô chết.")
    recompute_row_diff(row, lexicon=_NameLex())
    _yellow_ti(row)
    row.ch_txt = "安皐烏姑死"  # the yellow char itself was edited: review it again
    recompute_row_diff(row, lexicon=_NameLex())
    assert [(e.type, e.nom_sub_text) for e in row.text_diff if e.vi_sub_text == "ti"] == [("error", "皐")]


def _tap2_5398():
    """Tap2 539.8 (2026-11-21): yellow click, suggestion accepted (〓 -> 𦉼), yellow click again."""
    import copy

    from hannom.review.edit import mark_as_warn
    from hannom.review.patches import make_patch

    err = DiffElement(((3, 4),), "臯", ((11, 13),), "ti", "error")
    sug = DiffElement(((7, 8),), "〓", ((24, 26),), "là", "warn", reviewed=0, suggest="𦉼", suggest_by="similar")
    row = AlignmentRow("B.539.jpg", "B.539.8", "丕𤤰安臯烏姑𣩂〓", "Vậy vua An-ti-ô-cô chết là", [err, sug])
    snap = copy.deepcopy(row)
    mark_as_warn(row, 0)
    p1 = make_patch(snap, book_id="B", field="text_diff", after=row.text_diff_json(), reviewer="r")
    p_ch = make_patch(row, book_id="B", field="ch_txt", after="丕𤤰安臯烏姑𣩂𦉼", reviewer="r")
    row.ch_txt, row.text_diff = "丕𤤰安臯烏姑𣩂𦉼", [err]  # the recompute dropped the click
    snap2 = copy.deepcopy(row)
    mark_as_warn(row, 0)
    p2 = make_patch(snap2, book_id="B", field="text_diff", after=row.text_diff_json(), reviewer="r")
    return row, p1, p_ch, p2


def test_text_diff_patch_superseded_by_a_later_one_is_not_reported_stale():
    from hannom.review.patches import apply_patches_checked

    row, p1, p_ch, p2 = _tap2_5398()
    out, rejected = apply_patches_checked([row], [p1, p_ch, p2])
    assert rejected == []
    assert [(e.type, e.reviewed) for e in out[0].text_diff] == [("warn", 1)]


def test_text_diff_patch_without_a_later_one_is_still_reported_stale():
    import dataclasses

    from hannom.review.patches import apply_patches_checked

    row, p1, _p_ch, _p2 = _tap2_5398()
    other = dataclasses.replace(row, sentence_id="B.539.9")  # p1 has no successor for this sentence
    p1b = dataclasses.replace(p1, sentence_id="B.539.9")
    _out, rejected = apply_patches_checked([other], [p1b])
    assert [r.reason for r in rejected] == ["stale: no row has the content this patch was made against"]


def test_superseded_and_in_place_patches_are_not_reported_stale():
    from hannom.models import AlignmentRow
    from hannom.review.patches import ReviewPatch, apply_patches_checked

    row = AlignmentRow("B.067.jpg", "B.067.1", "綿", "Men.", [])
    p1 = ReviewPatch(book_id="B", sentence_id="B.067.1", field="vi_txt", before="Amen.", after="Lưỡi.", reviewer="r", timestamp="2026-11-20T01:38:27")
    p2 = ReviewPatch(book_id="B", sentence_id="B.067.1", field="vi_txt", before="Lưỡi.", after="Men.", reviewer="r", timestamp="2026-11-20T01:42:58")
    _rows, rejected = apply_patches_checked([row], [p1, p2])
    assert rejected == []


def test_patch_chain_replays_on_a_regenerated_row():
    """Two successive edits of one field (A -> B -> C) must both apply, in order,
    when re-alignment regenerated the row from OCR (value A again)."""
    from hannom.models import AlignmentRow
    from hannom.review.patches import ReviewPatch, apply_patches_checked

    fresh = AlignmentRow("B.067.jpg", "B.067.1", "綿", "Amen.", [])
    p1 = ReviewPatch(book_id="B", sentence_id="B.067.1", field="vi_txt", before="Amen.", after="Lưỡi.", reviewer="r", timestamp="2026-11-20T01:38:27")
    p2 = ReviewPatch(book_id="B", sentence_id="B.067.1", field="vi_txt", before="Lưỡi.", after="Men.", reviewer="r", timestamp="2026-11-20T01:42:58")
    out, rejected = apply_patches_checked([fresh], [p1, p2])
    assert rejected == [] and out[0].vi_txt == "Men."


def test_colour_patch_already_in_csv_survives_recompute():
    """A reviewer's text_diff change saved to the CSV (patch already in place)
    marks the row as human-edited, so the automatic recompute keeps it."""
    import copy

    from hannom.models import AlignmentRow, DiffElement
    from hannom.orchestrator import recompute_text_diff
    from hannom.review.edit import accept_warn
    from hannom.review.patches import apply_patches_checked, make_patch

    w = DiffElement(((0, 2),), "卢搓", ((0, 5),), "Lu-si", "warn", reviewed=0)
    row = AlignmentRow("B.200.jpg", "B.200.1", "卢搓", "Lu-si", [w])
    snap = copy.deepcopy(row)
    accept_warn(row, 0)
    patch = make_patch(snap, book_id="B", field="text_diff", after=row.text_diff_json(), reviewer="r")
    saved = copy.deepcopy(row)  # what the app wrote to the CSV
    saved.flags = []
    out, rejected = apply_patches_checked([saved], [patch])
    assert not rejected and "CONTENT_EDITED" in out[0].flags
    out = recompute_text_diff(out)
    assert out[0].text_diff[0].reviewed == 1


def test_cells_never_keep_line_breaks():
    from hannom.review.edit import normalize_cell

    assert normalize_cell("Cho nên,\nkẻ có đạo\r\n đã biết", "vi_txt") == "Cho nên, kẻ có đạo đã biết"
    assert normalize_cell("天主\n聖 神", "ch_txt") == "天主聖神"


def test_warn_rules_turn_single_name_syllables_yellow():
    from hannom.textdiff import spec_text_diff

    class Lex:
        def readings(self, ch):
            return {"支": ["giê"], "秋": ["thu"], "髀": ["vế"]}.get(ch, [])

    rules = (("秋", "su"),)
    els = spec_text_diff("支秋", "Giê-su", lexicon=Lex(), warn_rules=rules).elements
    assert [(e.type, e.reviewed) for e in els] == [("warn", 1)]
    mixed = spec_text_diff("支秋髀", "Giê-su ra", lexicon=Lex(), warn_rules=rules).elements
    assert [e.type for e in mixed] == ["error"]
