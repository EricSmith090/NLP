"""Review-metadata sidecar round trip (Issue A)."""

from __future__ import annotations

import csv
import json

from hannom.align import read_alignment_csv, write_alignment_csv
from hannom.models import AlignmentRow, DiffElement
from hannom.review_metadata import (
    MISSING_FLAG,
    MISMATCH_FLAG,
    load_rows_with_metadata,
    row_metadata_record,
    sidecar_path,
    write_review_metadata,
)


def _rows() -> list[AlignmentRow]:
    element = DiffElement(
        nom_pos=((0, 2),), nom_sub_text="字字", vi_pos=((0, 3),), vi_sub_text="chữ", type="error"
    )
    return [
        AlignmentRow(
            img_id="Book.001.jpg",
            sentence_id="Book.001.1",
            ch_txt="字字",
            vi_txt="chữ",
            text_diff=[element],
            confidence=0.42,
            flags=["ALIGN_LOW_CONF", "REVIEW:DIFF_SEMANTIC"],
        ),
        AlignmentRow(
            img_id="Book.001.jpg",
            sentence_id="Book.001.2",
            ch_txt="字",
            vi_txt="chữ",
            text_diff=None,
            confidence=None,
            flags=["NON_ONE_TO_ONE"],
        ),
    ]


def test_round_trip_preserves_flags_and_confidence(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())

    rows = read_alignment_csv(csv_path)
    assert [row.sentence_id for row in rows] == ["Book.001.1", "Book.001.2"]
    # CSV itself stays five-column.
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == ["img_id", "sentence_id", "ch_txt", "vi_txt", "text_diff"]

    restored, issues = load_rows_with_metadata(csv_path)
    assert issues == []
    assert restored[0].confidence == 0.42
    assert restored[0].flags == sorted({"ALIGN_LOW_CONF", "REVIEW:DIFF_SEMANTIC"})
    assert restored[1].flags == ["NON_ONE_TO_ONE"]


def test_missing_sidecar_flags_rows(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    sidecar_path(csv_path).unlink()

    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_SIDECAR_MISSING") for issue in issues)
    assert all(MISSING_FLAG in row.flags for row in restored)


def test_duplicate_metadata_is_detected(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    record = json.loads(json.dumps(row_metadata_record(_rows()[0])))
    with sidecar_path(csv_path).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    restored, issues = load_rows_with_metadata(csv_path)
    assert f"METADATA_DUPLICATE:{record['sentence_id']}" in issues


def test_mismatched_metadata_is_detected(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    sidecar = sidecar_path(csv_path)
    records = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    records[0]["img_id"] = "Book.999.jpg"
    sidecar.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")

    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_MISMATCH_IMG:") for issue in issues)
    assert MISMATCH_FLAG in restored[0].flags


def test_mismatched_text_diff_hash_is_detected(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        content = fh.read().replace("字字", "字字字", 1)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write(content)

    _, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_MISMATCH_DIFF:") for issue in issues)


def test_stale_metadata_entries_are_reported(tmp_path):
    csv_path = tmp_path / "Book.csv"
    rows = _rows()
    write_alignment_csv(csv_path, rows)
    write_review_metadata(csv_path, rows + [
        AlignmentRow("Book.002.jpg", "Book.002.1", "字", "chữ", None, None, ["X"]),
    ])

    _, issues = load_rows_with_metadata(csv_path)
    assert "METADATA_STALE:Book.002.1" in issues


# ---------------------------------------------------------------------------
# Issue 6: metadata integrity failures must block unsafe evaluation
# ---------------------------------------------------------------------------

def test_unsupported_schema_is_reported_and_blocks(tmp_path):
    from hannom.review_metadata import SCHEMA

    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    sidecar = sidecar_path(csv_path)
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["schema"] = SCHEMA + 5
    lines[0] = json.dumps(record, ensure_ascii=False)
    sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")

    restored, issues = load_rows_with_metadata(csv_path)
    assert any("METADATA_SCHEMA_UNSUPPORTED" in issue for issue in issues)
    row = next(r for r in restored if r.sentence_id == "Book.001.1")
    assert "REVIEW_METADATA_MISSING" in row.flags


def test_invalid_confidence_values_are_rejected(tmp_path):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    sidecar = sidecar_path(csv_path)
    records = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    for bad in (True, "high", 1.5, float("inf"), float("nan")):
        for record in records:
            record["confidence"] = bad
        sidecar.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        _, issues = load_rows_with_metadata(csv_path)
        assert any("METADATA_BAD_CONFIDENCE" in issue for issue in issues), f"bad={bad!r} not rejected"


def test_atomic_write_failure_preserves_previous_sidecar(tmp_path, monkeypatch):
    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _rows())
    sidecar = sidecar_path(csv_path)
    before = sidecar.read_text(encoding="utf-8")

    import hannom.review_metadata as rm

    def boom(src, dst):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(rm.os, "replace", boom)
    try:
        write_review_metadata(csv_path, _rows())
        assert False, "expected the write to fail"
    except OSError:
        pass
    assert sidecar.read_text(encoding="utf-8") == before
    leftovers = list(tmp_path.glob("*.tmp-*"))
    assert leftovers == []


def _good_rows():
    element = DiffElement(
        nom_pos=((0, 2),), nom_sub_text="字", vi_pos=((0, 3),), vi_sub_text="một", type="error"
    )
    return [
        AlignmentRow(
            img_id="Book.001.jpg",
            sentence_id="Book.001.1",
            ch_txt="字",
            vi_txt="một",
            text_diff=[element],
            flags=[],
        ),
    ]


def test_duplicate_metadata_blocks_evaluation(tmp_path):
    from hannom.evaluate import evaluate_rows

    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _good_rows())
    with sidecar_path(csv_path).open("a", encoding="utf-8", newline="\n") as fh:
        record = json.loads(sidecar_path(csv_path).read_text(encoding="utf-8").splitlines()[0])
        fh.write(json.dumps(record) + "\n")
    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_DUPLICATE") for issue in issues)
    metrics = evaluate_rows("b", restored, integrity_issues=issues, minimum_coverage=0.0, max_unverified_ratio=1.0)
    assert not metrics.passed


def test_stale_metadata_blocks_evaluation(tmp_path):
    from hannom.evaluate import evaluate_rows

    csv_path = tmp_path / "Book.csv"
    rows = _good_rows()
    write_alignment_csv(csv_path, rows)
    write_review_metadata(
        csv_path,
        rows
        + [
            AlignmentRow("Book.002.jpg", "Book.002.1", "字", "chữ", None, None, ["X"]),
        ],
    )
    restored, issues = load_rows_with_metadata(csv_path)
    assert "METADATA_STALE:Book.002.1" in issues
    metrics = evaluate_rows("b", restored, integrity_issues=issues, minimum_coverage=0.0, max_unverified_ratio=1.0)
    assert not metrics.passed


def test_malformed_json_blocks_evaluation(tmp_path):
    from hannom.evaluate import evaluate_rows

    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _good_rows())
    sidecar_path(csv_path).write_text("{not json}\n", encoding="utf-8")
    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_JSON_ERROR") for issue in issues)
    metrics = evaluate_rows("b", restored, integrity_issues=issues, minimum_coverage=0.0, max_unverified_ratio=1.0)
    assert not metrics.passed


def test_missing_sidecar_blocks_evaluation(tmp_path):
    from hannom.evaluate import evaluate_rows

    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _good_rows())
    sidecar_path(csv_path).unlink()
    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_SIDECAR_MISSING") for issue in issues)
    metrics = evaluate_rows("b", restored, integrity_issues=issues, minimum_coverage=0.0, max_unverified_ratio=1.0)
    assert not metrics.passed


def test_hash_mismatch_blocks_evaluation(tmp_path):
    from hannom.evaluate import evaluate_rows

    csv_path = tmp_path / "Book.csv"
    write_alignment_csv(csv_path, _good_rows())
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        content = fh.read().replace("字", "字字", 1)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        fh.write(content)
    restored, issues = load_rows_with_metadata(csv_path)
    assert any(issue.startswith("METADATA_MISMATCH_DIFF") for issue in issues)
    metrics = evaluate_rows("b", restored, integrity_issues=issues, minimum_coverage=0.0, max_unverified_ratio=1.0)
    assert not metrics.passed


def test_loader_integrity_issues_block_even_with_perfect_rows():
    from hannom.evaluate import evaluate_rows

    rows = [
        AlignmentRow(
            img_id="Book.001.jpg",
            sentence_id="Book.001.1",
            ch_txt="字字",
            vi_txt="hai chữ",
            text_diff=[],
            flags=["DIFF_NO_READING_MISMATCH"],
        )
    ]
    metrics = evaluate_rows("b", rows, integrity_issues=["METADATA_DUPLICATE:Book.001.1"])
    assert metrics.similarity == 100.0
    assert not metrics.passed
    assert any("METADATA_DUPLICATE" in issue for issue in metrics.issues)


def test_decision_integrity_issues_block_even_with_perfect_rows():
    from hannom.evaluate import evaluate_rows

    rows = [
        AlignmentRow(
            img_id="Book.001.jpg",
            sentence_id="Book.001.1",
            ch_txt="字字",
            vi_txt="hai chữ",
            text_diff=[],
            flags=["DIFF_NO_READING_MISMATCH"],
        )
    ]
    metrics = evaluate_rows("b", rows, integrity_issues=["DECISION_JSON_ERROR:book.jsonl:3:Expecting value"])
    assert not metrics.passed
