"""Decisions follow their content when re-segmentation renumbers rows.

sentence_id is positional (<image>.<n>): splitting or merging one row
renumbers every later row of the page. Before 2026-11-21 that made all of
their decisions stale although their content was unchanged (measured on SLQ
page 085: one split lost 17 decisions instead of 1).
"""

from __future__ import annotations

from hannom.models import AlignmentRow
from hannom.review_decisions import (
    STATUS_ACCEPTED_DIFFERENCE,
    STATUS_ACCEPTED_MATCH,
    append_decision,
    apply_decisions,
    decision_path,
    make_decision,
    parse_decisions,
)


def _row(n: int, ch: str, vi: str, page: str = "001") -> AlignmentRow:
    return AlignmentRow(img_id=f"Book.{page}.jpg", sentence_id=f"Book.{page}.{n}", ch_txt=ch, vi_txt=vi)


def _decide(row: AlignmentRow, status: str = STATUS_ACCEPTED_MATCH, sid: str | None = None, reviewer: str = "r"):
    return make_decision(book_id="b", sentence_id=sid or row.sentence_id, status=status, reviewer=reviewer,
                         ch_txt=row.ch_txt, vi_txt=row.vi_txt, text_diff_json=row.text_diff_json())


def _verified(rows):
    return [r.sentence_id for r in rows if r.review_status is not None]


def test_split_of_one_row_loses_only_that_rows_decision():
    a, b, c = _row(1, "天地人日", "thiên địa nhân nhật"), _row(2, "月星", "nguyệt tinh"), _row(3, "山水", "sơn thủy")
    decisions = [_decide(a), _decide(b, STATUS_ACCEPTED_DIFFERENCE), _decide(c)]
    # re-segmentation splits row 1: every later row of the page is renumbered
    after = [_row(1, "天地", "thiên địa"), _row(2, "人日", "nhân nhật"), _row(3, "月星", "nguyệt tinh"),
             _row(4, "山水", "sơn thủy")]
    rows, active, audit = apply_decisions(after, decisions)
    assert _verified(rows) == ["Book.001.3", "Book.001.4"]
    assert rows[2].review_status == STATUS_ACCEPTED_DIFFERENCE and rows[3].review_status == STATUS_ACCEPTED_MATCH
    # only the row that really changed is stale; the renumbered ones are not flagged
    assert [r.sentence_id for r in rows if "REVIEW_DECISION_STALE" in r.flags] == ["Book.001.1"]
    assert active == ["REVIEW_DECISION_STALE:Book.001.1"]
    assert sum(1 for x in audit if x.startswith("DECISION_RELOCATED:")) == 2


def test_orphaned_decision_follows_its_content():
    row = _row(5, "山水", "sơn thủy")
    decisions = [_decide(row, sid="Book.001.9")]  # that sentence_id no longer exists
    rows, active, _audit = apply_decisions([row], decisions)
    assert _verified(rows) == ["Book.001.5"] and active == []


def test_no_relocation_when_content_is_not_unique():
    refrain = ("吧𥛉主碎", "và lạy Chúa tôi")
    rows_now = [_row(1, *refrain), _row(2, "月星", "nguyệt tinh"), _row(3, *refrain)]
    decisions = [_decide(_row(7, *refrain))]  # old position, content now appears twice
    rows, _active, _audit = apply_decisions(rows_now, decisions)
    assert _verified(rows) == []


def test_own_valid_decision_is_never_replaced():
    row = _row(1, "月星", "nguyệt tinh")
    own = _decide(row, STATUS_ACCEPTED_DIFFERENCE, reviewer="a")
    stray = _decide(row, STATUS_ACCEPTED_MATCH, sid="Book.001.8", reviewer="b")
    rows, _active, audit = apply_decisions([row], [own, stray])
    assert rows[0].review_status == STATUS_ACCEPTED_DIFFERENCE
    assert not any(x.startswith("DECISION_RELOCATED:") for x in audit)


def test_two_decisions_competing_for_one_row_are_not_relocated():
    row = _row(1, "月星", "nguyệt tinh")
    first, second = _decide(row, sid="Book.001.7"), _decide(row, sid="Book.001.8")
    rows, _active, _audit = apply_decisions([row], [first, second])
    assert _verified(rows) == []


def test_invalid_latest_record_blocks_relocation(tmp_path):
    row = _row(1, "月星", "nguyécat")
    path = decision_path(tmp_path, "b")
    append_decision(path, _decide(row, sid="Book.001.9"))
    with path.open("a", encoding="utf-8") as fh:  # a later, malformed record for the same sentence_id
        fh.write('{"book_id": "b", "sentence_id": "Book.001.9", "status": "nonsense"}\n')
    decisions, failures, issues = parse_decisions(path)
    rows, _active, _audit = apply_decisions([row], decisions, issues, failures=failures)
    assert _verified(rows) == []


def test_changed_content_still_goes_stale_without_relocation():
    row = _row(1, "之", "thì")
    decisions = [_decide(row)]
    row.ch_txt = "其"
    rows, active, audit = apply_decisions([row], decisions)
    assert _verified(rows) == [] and "REVIEW_DECISION_STALE" in rows[0].flags
    assert not any(x.startswith("DECISION_RELOCATED:") for x in audit)
