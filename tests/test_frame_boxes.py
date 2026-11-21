"""Frame / spine / outside-frame Nôm boxes (instructor, 2026-11-21)."""

import pytest

from hannom.frame_boxes import (
    FrameBox, drop_listed_boxes, entry_for, find_candidates, match_listed, read_list, write_list,
)
from hannom.models import AlignmentRow
from hannom.review.edit import EditError
from hannom.sync_check import check_sync


def box(t, x0, y0, x1, y1):
    return {"transcription": t, "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "difficult": False}


PAIRS = [{"ch": ["p1.jpg", "p2.jpg"], "vi": ["v1.jpg"]}]


def sync(ch, rows):
    d = [{"img_id": r.img_id, "ch_txt": r.ch_txt, "vi_txt": r.vi_txt} for r in rows]
    return check_sync(d, ch, None, PAIRS)


def test_candidates_are_short_boxes_outside_the_text_block():
    # Long columns x 200-500, y 150-900 (like a Cấm Phòng page).
    page = [
        box("照", 590, 95, 615, 135),            # corner rosette: above and right of the block
        box("天地人日月星", 460, 150, 495, 900),
        box("排次一", 520, 470, 555, 590),        # TOC heading just right of the block: still a candidate
        box("二百六", 520, 770, 555, 880),        # only numerals (a TOC page number): never a candidate
        box("山水", 300, 400, 330, 470),          # short but inside the block: not a candidate
        box("目籙", 105, 640, 142, 722),          # spine label left of the frame
        box("江河海湖", 200, 160, 235, 880),
        box("無無無無無", 120, 100, 135, 990),    # long box: part of the block, never a candidate
    ]
    got = {i for i, _gap in find_candidates(page)}
    assert got == {0, 2}  # the 5-char chain box widens the block, so 目籙 is inside it
    page.pop()  # without the long chain box the spine label is outside again
    assert {i for i, _ in find_candidates(page)} == {0, 2, 5}
    assert find_candidates([box("山", 0, 0, 10, 10)]) == []  # no long box: no block, no candidate


def test_list_round_trip_and_matching_ignores_text(tmp_path):
    ch = {"ch/p1.jpg": [box("天地", 400, 150, 430, 230), box("熙", 600, 960, 630, 995)]}
    entries = [entry_for("p1.jpg", ch["ch/p1.jpg"][1]), FrameBox("p9.jpg", 1, 1, 2, 2, "照")]
    path = tmp_path / "frame.tsv"
    write_list(path, entries, comment="checked on the page images\nsecond line")
    assert path.read_text(encoding="utf-8").startswith("# checked on the page images\n# second line\n")
    back = read_list(path)
    assert back == entries
    ch["ch/p1.jpg"][1]["transcription"] = "非"  # edited in the review app: same box
    found, missing = match_listed(ch, back)
    assert list(found) == [("ch/p1.jpg", 1)] and missing == [entries[1]]
    for pt in ch["ch/p1.jpg"][1]["points"]:  # moved more than the tolerance: not the same box
        pt[0] += 5
    found, _ = match_listed(ch, back)
    assert found == {}


def test_drop_removes_boxes_and_the_same_stream_positions():
    # p1: 心(junk) 心心天 | p2: 地 熙(junk) 人 — rows cross the page break.
    ch = {
        "ch/p1.jpg": [box("心", 600, 100, 620, 130), box("心心天", 400, 150, 430, 600)],
        "ch/p2.jpg": [box("地", 400, 150, 430, 200), box("熙", 600, 960, 620, 990), box("人", 380, 150, 395, 200)],
    }
    rows = [
        AlignmentRow("p1.jpg", "p1.1", "心心", "tâm tâm"),
        AlignmentRow("p1.jpg", "p1.2", "心天地熙", "tâm thiên địa"),
        AlignmentRow("p2.jpg", "p2.1", "人", "nhân"),
    ]
    assert sync(ch, rows) == []
    new_ch, new_rows, removed = drop_listed_boxes(PAIRS, ch, rows, {("ch/p1.jpg", 0), ("ch/p2.jpg", 1)})
    assert [r.ch_txt for r in new_rows] == ["心", "心天地", "人"]  # the first 心 (the junk box) went
    assert removed == {0: "心", 1: "熙"}
    assert [b["transcription"] for b in new_ch["ch/p1.jpg"]] == ["心心天"]
    assert [b["transcription"] for b in new_ch["ch/p2.jpg"]] == ["地", "人"]
    assert sync(new_ch, new_rows) == []
    assert rows[0].ch_txt == "心心" and len(ch["ch/p1.jpg"]) == 2  # inputs untouched
    # a second run finds nothing left to drop
    again = drop_listed_boxes(PAIRS, new_ch, new_rows, set())
    assert again[2] == {}


def test_drop_refuses_when_not_in_sync():
    ch = {"ch/p1.jpg": [box("天地", 0, 0, 10, 10)], "ch/p2.jpg": []}
    rows = [AlignmentRow("p1.jpg", "p1.1", "天", "thiên")]
    with pytest.raises(EditError):
        drop_listed_boxes(PAIRS, ch, rows, {("ch/p1.jpg", 0)})
