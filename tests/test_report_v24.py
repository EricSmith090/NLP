from __future__ import annotations

from pathlib import Path

import pymupdf

from hannom.models import AlignmentRow, BookMetrics
from hannom.report import (
    Member,
    ReportData,
    Screenshot,
    build_report_pdf,
    compute_book_report_stats,
    report_summary_json,
    validate_report_data,
)


def _warn(nom, **kw):
    from hannom.models import DiffElement

    return DiffElement(nom_pos=((0, 1),), nom_sub_text=nom, vi_pos=(), vi_sub_text="", type="warn", **kw)


def _rows():
    from hannom.models import DiffElement

    err = DiffElement(nom_pos=((0, 1),), nom_sub_text="x", vi_pos=(), vi_sub_text="", type="error")
    return [
        AlignmentRow("0001", "0001.1", "天〓地", "a b", [err, _warn("天", reviewed=1, suggest="天", suggest_by="fallback")]),
        AlignmentRow("0001", "0001.2", "人人", "c", [_warn("人", reviewed=0, suggest="仁", suggest_by="similar")]),
        AlignmentRow("0002", "0002.1", "〓", "d", None),
        AlignmentRow("0002", "0002.2", "木", "e", []),
    ]


def test_stats_counts():
    st = compute_book_report_stats(_rows(), [{"type": "phonetic"}, {"sentence_ids": ["0002.1", "0002.2"], "type": "meaning"}], "ok")
    assert st["total_rows"] == 4
    assert st["yellow_elements"] == 2 and st["yellow_reviewed"] == 1 and st["yellow_unreviewed"] == 1
    assert st["suggestions"]["fallback"]["accepted"] == 1
    assert st["suggestions"]["similar"]["pending"] == 1
    assert st["suggestions_pending"] == 1
    assert st["meaning_rows"] == 2 and st["meaning_ratio"] == 0.5
    assert st["null_rows"] == 1 and st["null_ratio"] == 0.25
    assert [(p["sentence_id"], p["position"], p["code"]) for p in st["placeholders"]] == [
        ("0001.1", 1, "unknown"),
        ("0002.1", 0, "unknown"),
    ]
    assert st["translation_declared"]


def test_undeclared_default_phonetic_and_validation():
    st = compute_book_report_stats(_rows())
    assert not st["translation_declared"] and st["meaning_rows"] == 0
    data = ReportData(members=[Member("", "1", "")], book_stats={"b": st})
    issues = validate_report_data(data)
    assert "REPORT_TRANSLATION_TYPE_MISSING:b" in issues
    assert "REPORT_NULL_JUSTIFICATION_MISSING:b" in issues
    assert any(i.startswith("REPORT_MEMBER_NAME_MISSING") for i in issues)
    assert any(i.startswith("REPORT_MEMBER_EMAIL_MISSING") for i in issues)


def test_pdf_builds_with_missing_screenshot(tmp_path: Path):
    st = compute_book_report_stats(_rows(), "phonetic", "rows are page headers")
    data = ReportData(
        members=[Member("A", "1", "a@x")],
        metrics=[BookMetrics(book_id="b")],
        book_stats={"b": st},
        screenshots=[Screenshot("PPOCRLabel Nôm", tmp_path / "nope.png")],
    )
    out = build_report_pdf(data, tmp_path / "r.pdf")
    doc = pymupdf.open(out)
    text = "".join(p.get_text() for p in doc).replace("\xa0", " ").replace(" ", " ")
    assert "SCREENSHOT MISSING" in text
    assert "confidence" in text
    assert "0001.1" in text
    summ = report_summary_json(data)
    assert summ["book_stats"]["b"]["null_rows"] == 1
