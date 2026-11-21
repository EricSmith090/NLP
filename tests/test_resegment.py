"""Re-segmentation from reviewed text with reviewed rows pinned (2026-11-21)."""

from __future__ import annotations

import json
import random

import pytest

from hannom.clean import CleanedPage
from hannom.models import AlignmentRow
from hannom.resegment import ResegmentError, overlay_label_text, pin_reviewed_rows, renumber
from hannom.sync_check import norm_nom, norm_vi


def R(ch: str, vi: str, page: str = "001") -> AlignmentRow:
    return AlignmentRow(img_id=f"B.{page}.jpg", sentence_id="?", ch_txt=ch, vi_txt=vi)


def texts(rows):
    return [(r.ch_txt, r.vi_txt) for r in rows]


def test_recuts_unreviewed_rows_and_keeps_reviewed_ones():
    prev = [R("天地", "thiên địa."), R("人日月", "nhân nhật. nguyệt"), R("星", "sao tinh."), R("山水", "sơn thủy.")]
    new = [R("天地", "thiên địa."), R("人日", "nhân nhật."), R("月星", "nguyệt sao tinh."), R("山水", "sơn thủy.")]
    renumber(prev)
    out, rep = pin_reviewed_rows(prev, new, pinned={0, 3})
    assert texts(out) == texts(new)  # the unreviewed middle is re-cut; pinned windows were identical anyway
    assert [r.sentence_id for r in out] == ["B.001.1", "B.001.2", "B.001.3", "B.001.4"]
    assert rep["windows_kept_for_pins"] == 0


def test_window_with_a_reviewed_row_is_kept_as_it_was():
    prev = [R("天地人", "thiên địa nhân"), R("日月", "nhật nguyệt.")]
    new = [R("天地", "thiên địa"), R("人日月", "nhân nhật nguyệt.")]
    out, rep = pin_reviewed_rows(prev, new, pinned={0})
    assert texts(out) == texts(prev)
    assert rep["windows_kept_for_pins"] == 1


def test_pinned_row_keeps_its_exact_text_even_when_cut_is_identical():
    prev = [R("天地", "thiên  địa."), R("人", "nhân.")]  # spacing differs only
    new = [R("天地", "thiên địa."), R("人", "nhân.")]
    out, _ = pin_reviewed_rows(prev, new, pinned={0})
    assert out[0].vi_txt == "thiên  địa." and out[1].vi_txt == "nhân."


def test_different_streams_are_refused():
    with pytest.raises(ResegmentError):
        pin_reviewed_rows([R("天地", "thiên địa.")], [R("天", "thiên địa.")], pinned=set())
    with pytest.raises(ResegmentError):
        pin_reviewed_rows([R("天地", "thiên địa.")], [R("天地", "thiên.")], pinned=set())


def test_renumbering_follows_images():
    rows = [R("天", "a.", "010"), R("地", "b.", "010"), R("人", "c.", "009"), R("日", "d.", "009")]
    renumber(rows)
    assert [r.sentence_id for r in rows] == ["B.010.1", "B.010.2", "B.009.1", "B.009.2"]


def _random_partition(stream_n: str, stream_q: list[str], rng) -> list[AlignmentRow]:
    """Random monotone cut of the same two streams into rows (one side may be empty)."""
    rows, i, j = [], 0, 0
    while i < len(stream_n) or j < len(stream_q):
        di = rng.randint(0, 3) if i < len(stream_n) else 0
        dj = rng.randint(0, 3) if j < len(stream_q) else 0
        if di == dj == 0:
            continue
        rows.append(R(stream_n[i : i + di], " ".join(stream_q[j : j + dj])))
        i, j = i + di, j + dj
    return rows


def test_randomised_merge_preserves_streams_and_every_pinned_row():
    rng = random.Random(11)
    for _ in range(2000):
        n = "".join(rng.choice("天地人日月星") for _ in range(rng.randint(1, 14)))
        q = [rng.choice(["a", "bb", "ccc"]) for _ in range(rng.randint(1, 14))]
        prev, new = _random_partition(n, q, rng), _random_partition(n, q, rng)
        pinned = {k for k in range(len(prev)) if rng.random() < 0.3}
        out, _ = pin_reviewed_rows(prev, new, pinned)
        assert "".join(norm_nom(r.ch_txt) for r in out) == n
        assert "".join(norm_vi(r.vi_txt) for r in out) == "".join(q)
        kept = [(r.ch_txt, r.vi_txt) for r in out]
        for k in pinned:  # every pinned row is still there, in order, with its exact text
            assert (prev[k].ch_txt, prev[k].vi_txt) in kept
        assert all(r.ch_txt or r.vi_txt for r in out)


def test_overlay_label_text_only_on_edited_pages(tmp_path):
    def page(name, script, text):
        return CleanedPage(book_id="b", page_no=1, image_name=name, script=script, text=text)

    cleaned = {
        "B.010.jpg": page("B.010.jpg", "nom", "天地人日"),
        "B.001.jpg": page("B.001.jpg", "qn", "Song có ba cửa rộng lớn, nhiều người vào ngục."),
        "B.002.jpg": page("B.002.jpg", "qn", "Câu không sửa."),
    }
    box = lambda t: {"transcription": t, "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}  # noqa: E731
    (tmp_path / "ch").mkdir()
    (tmp_path / "vi").mkdir()
    (tmp_path / "ch" / "Label.txt").write_text(
        "ch/B.010.jpg\t" + json.dumps([box("天地"), box("人日")], ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "vi" / "Label.txt").write_text(
        "vi/B.001.jpg\t" + json.dumps([box("Song có ba cửa rộng lớn, nhiều người vào hơn. Rầy con hãy")], ensure_ascii=False)
        + "\nvi/B.002.jpg\t" + json.dumps([box("Câu  không sửa.")], ensure_ascii=False) + "\n", encoding="utf-8")
    out, changed = overlay_label_text(cleaned, tmp_path)
    assert changed == ["B.001.jpg"]  # B.002 differs only in whitespace, B.010 not at all
    assert out["B.001.jpg"].text.endswith("vào hơn. Rầy con hãy") and "TEXT_FROM_LABEL" in out["B.001.jpg"].flags
    assert out["B.002.jpg"].text == "Câu không sửa." and cleaned["B.001.jpg"].text.endswith("ngục.")


def test_no_previous_csv_means_no_pinning_not_a_failure(tmp_path):
    # A fresh machine (USER_GUIDE "from scratch") has Label.txt but no CSV yet.
    from hannom.resegment import previous_rows_for_pinning

    assert previous_rows_for_pinning(tmp_path / "missing.csv", [], [], []) is None


def test_overlay_joins_boxes_like_clean(tmp_path):
    # clean.py: Nôm page text = "".join(lines), QN page text = " ".join(lines).
    # A "\n" between Nôm column boxes reached the CSV cells (official FORM
    # error "line break in cell", 29 rows in the Tap1 dry run, 2026-11-21).
    cleaned = {"B.010.jpg": CleanedPage(book_id="b", page_no=1, image_name="B.010.jpg", script="nom", text="天地人日"),
               "B.001.jpg": CleanedPage(book_id="b", page_no=1, image_name="B.001.jpg", script="qn", text="a b. c d.")}
    box = lambda t: {"transcription": t, "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}  # noqa: E731
    (tmp_path / "ch").mkdir()
    (tmp_path / "vi").mkdir()
    (tmp_path / "ch" / "Label.txt").write_text(
        "ch/B.010.jpg\t" + json.dumps([box("天下"), box("人日")], ensure_ascii=False) + "\n", encoding="utf-8")
    (tmp_path / "vi" / "Label.txt").write_text(
        "vi/B.001.jpg\t" + json.dumps([box("a b."), box("c e.")], ensure_ascii=False) + "\n", encoding="utf-8")
    out, changed = overlay_label_text(cleaned, tmp_path)
    assert sorted(changed) == ["B.001.jpg", "B.010.jpg"]
    assert out["B.010.jpg"].text == "天下人日"
    assert out["B.001.jpg"].text == "a b. c e."
    assert all("\n" not in p.text for p in out.values())
