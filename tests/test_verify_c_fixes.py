"""Verify-C 2026-11-13 fixes: D1, D5, D6, D7, D16-D21, N3/N4/N5."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hannom.config import ApiSettings, BookConfig, OCRSettings, ProjectConfig
from hannom.models import PageRecord
from hannom.ocr.kimhannom import KimHanNomClient, _success_code, scrub_server_payload
from hannom.ocr.quota import QuotaLedger
from hannom.ocr.router import OCRRouter, PROPAGATED_WARNING_CODES
from hannom.state import FUTURE_TOLERANCE, SCHEMA_VERSION, State, StateError


def _project(tmp_path: Path, api_limits=(25, 50, 200, 600)) -> ProjectConfig:
    ocr = OCRSettings(nom=("local",), quoc_ngu=("local",), api_mode="local_only")
    book = BookConfig(
        book_id="T1_Test",
        pdf=tmp_path / "Test.pdf",
        layout="T1",
        expected_pages=1,
        nom_start_hint=1,
        nom_end_hint=1,
        translation_start=2,
        translation_end=1,
        ocr=ocr,
    )
    return ProjectConfig(
        root=tmp_path,
        project_name="test",
        deadline="",
        zip_stem="test",
        report_name="test_report.pdf",
        one_zip_for_all_books=True,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
        output_dir=tmp_path / "out",
        dictionaries_dir=tmp_path / "dict",
        models_dir=tmp_path / "models",
        books=(book,),
        api=ApiSettings(
            base_url="https://example.invalid",
            token_env="HANNOM_TEST_TOKEN_ABSENT",
            user_agent="test",
            limits={
                "per_minute": api_limits[0],
                "per_hour": api_limits[1],
                "per_day": api_limits[2],
                "per_week": api_limits[3],
            },
        ),
        quality={"minimum_similarity": 95.0},
        ocr_config={"engines": {"local": {"kind": "mock"}}, "routing": {}},
    )


def _page(tmp_path: Path, sha256: str = "a" * 64, page_no: int = 1) -> PageRecord:
    return PageRecord(
        book_id="T1_Test",
        page_no=page_no,
        image_name=f"Test.{page_no:03d}.jpg",
        pdf_page=page_no,
        sha256=sha256,
        width=800,
        height=1135,
        path=Path(tmp_path / f"Test.{page_no:03d}.jpg"),
        script="qn",
        folder="vi",
    )


# ---------------------------------------------------------------- D1
def test_d1_success_code_is_strict():
    assert _success_code("000000") is True
    for bad in (0, 0.0, 1, False, True, "0", "000001", "", None, "000000 "):
        assert _success_code(bad) is False


# ---------------------------------------------------------------- D5
def test_d5_fresh_schema_has_business_code_column(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    cols = {row[1] for row in state._conn.execute("PRAGMA table_info(api_calls)")}
    assert "business_code" in cols
    assert int(state._conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
    state.close()


def test_d5_v1_database_is_migrated_to_v2(tmp_path: Path):
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE api_calls (
            call_id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT NOT NULL,
            image_sha256 TEXT,
            token_id TEXT,
            requested_at TEXT NOT NULL,
            status TEXT NOT NULL,
            response_path TEXT,
            quota_day TEXT,
            quota_week TEXT,
            note TEXT
        );
        CREATE TABLE pages (
            book_id TEXT NOT NULL, page_no INTEGER NOT NULL,
            image_name TEXT NOT NULL, pdf_page INTEGER NOT NULL,
            sha256 TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            path TEXT NOT NULL, script TEXT NOT NULL DEFAULT 'unknown',
            section TEXT NOT NULL DEFAULT 'unknown', folder TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'extracted', ocr_engine TEXT,
            ocr_confidence REAL, review_flags TEXT NOT NULL DEFAULT '[]',
            features_json TEXT NOT NULL DEFAULT '{}', extraction_method TEXT NOT NULL DEFAULT '',
            rotation INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
            PRIMARY KEY (book_id, page_no)
        );
        PRAGMA user_version = 1;
        """
    )
    conn.close()
    state = State(db)
    cols = {row[1] for row in state._conn.execute("PRAGMA table_info(api_calls)")}
    assert "business_code" in cols
    assert int(state._conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
    state.close()


def test_d5_business_code_roundtrip(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    state.log_api_call("image-ocr", "abc", "http_200", business_code="000108")
    state.log_api_call("image-upload", "abc", "http_500", note="non_retryable")
    rows = state._conn.execute(
        "SELECT endpoint, business_code FROM api_calls ORDER BY call_id"
    ).fetchall()
    assert [(r["endpoint"], r["business_code"]) for r in rows] == [
        ("image-ocr", "000108"),
        ("image-upload", None),
    ]
    state.close()


# ---------------------------------------------------------------- D6
def test_d6_future_row_insert_is_rejected(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    future = datetime.now(timezone.utc) + FUTURE_TOLERANCE + timedelta(hours=1)
    with pytest.raises(StateError):
        state.log_api_call("image-ocr", "abc", "http_200", requested_at=future)
    state.close()


def test_d6_windows_ignore_skewed_future_rows(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    now = datetime.now(timezone.utc)
    state.log_api_call("image-ocr", "a", "http_200", requested_at=now - timedelta(seconds=10))
    # Simulate a row recorded by a clock-skewed host: insert it directly.
    future = now + timedelta(hours=3)
    state._conn.execute(
        "INSERT INTO api_calls (endpoint, requested_at, status, quota_day, quota_week, note)"
        " VALUES (?,?,?,?,?,?)",
        ("image-ocr", future.isoformat(), "http_200", "2999-01-01", "2999-W01", None),
    )
    since = now - timedelta(seconds=60)
    assert state.count_api_calls(since, until=now) == 1
    assert all(r["requested_at"] <= now.isoformat() for r in state.api_calls_since(since, until=now))
    assert state.last_api_call(until=now) is not None
    ledger = QuotaLedger(state, {"per_minute": 25, "per_hour": 50, "per_day": 200, "per_week": 600}, 0)
    snapshot = ledger.check(now)
    assert snapshot.minute == 1 and snapshot.week == 1
    state.close()


# ---------------------------------------------------------------- D7/D20
def test_d7_new_codes_are_propagated():
    assert {
        "ENGINE_UNAVAILABLE",
        "IMAGE_REC_FALLBACK",
        "API_CLASSIFIED_NOT_SINO_NOM",
        "OCR_ROUTING_UNKNOWN_MODE",
        "OCR_LINE_WITHOUT_BBOX",
    } <= PROPAGATED_WARNING_CODES


def test_d7_cache_hit_promotes_flags(tmp_path: Path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    page = _page(tmp_path, sha256="b" * 64)
    path = tmp_path / "data" / "ocr" / "T1_Test" / "0001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "book_id": "T1_Test",
                "page_no": 1,
                "image_name": page.image_name,
                "image_sha256": page.sha256,
                "engine": "kimhannom",
                "lines": [
                    {
                        "text": "測試",
                        "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                        "confidence": 0.9,
                        "script": "qn",
                        "difficult": False,
                        "extra": {},
                    }
                ],
                "raw": {},
                "warnings": ["ENGINE_UNAVAILABLE:kimhannom:no_token", "UNRELATED:x"],
                "cached": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    state.upsert_page(page)
    assert state.page("T1_Test", 1).review_flags == []
    router = OCRRouter(project, project.books[0], state)
    result = router.load_result(page)
    assert result is not None and result.cached is True
    assert "ENGINE_UNAVAILABLE" in state.page("T1_Test", 1).review_flags
    assert "UNRELATED" not in state.page("T1_Test", 1).review_flags
    # Idempotent: a second cache hit must not duplicate the flag.
    router.load_result(state.page("T1_Test", 1))
    assert state.page("T1_Test", 1).review_flags.count("ENGINE_UNAVAILABLE") == 1
    state.close()


# ---------------------------------------------------------------- D16/D17
def test_d16_stale_result_is_ignored(tmp_path: Path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    page = _page(tmp_path, sha256="c" * 64)
    path = tmp_path / "data" / "ocr" / "T1_Test" / "0001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "book_id": "T1_Test",
                "page_no": 1,
                "image_name": page.image_name,
                "image_sha256": "d" * 64,  # different image -> stale
                "engine": "kimhannom",
                "lines": [],
                "raw": {},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    state.upsert_page(page)
    router = OCRRouter(project, project.books[0], state)
    assert router.load_result(page) is None
    state.close()


def test_d17_corrupt_result_file_is_ignored(tmp_path: Path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    page = _page(tmp_path, sha256="e" * 64)
    path = tmp_path / "data" / "ocr" / "T1_Test" / "0001.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    state.upsert_page(page)
    router = OCRRouter(project, project.books[0], state)
    assert router.load_result(page) is None
    state.close()


def test_d17_corrupt_api_cache_file_is_ignored(tmp_path: Path):
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    client = KimHanNomClient(project, state)
    key = "zz" * 32
    cache_file = client._cache_path(key)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("not json at all", encoding="utf-8")
    assert client._load_cache(key) is None
    state.close()


# ---------------------------------------------------------------- D21
def test_d21_scrub_server_payload_strips_base64_anywhere():
    obj = {
        "data": {"result": {"result_ocr_text": ["x"], "result_image_base64": "AAA"}},
        "raw": {"is_success": True, "nested": [{"result_image_base64": "BBB"}, {"keep": 1}]},
        "list": [["result_image_base64", "CCC"], "ok"],
    }
    scrubbed = scrub_server_payload(obj)

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for item in node:
                yield from keys(item)

    assert "result_image_base64" not in set(keys(scrubbed))
    assert scrubbed["data"]["result"]["result_ocr_text"] == ["x"]
    assert scrubbed["raw"]["nested"] == [{}, {"keep": 1}]


# ---------------------------------------------------------------- D20
def test_d20_unavailability_reason_without_token(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HANNOM_TEST_TOKEN_ABSENT", raising=False)
    project = _project(tmp_path)
    state = State(tmp_path / "state.sqlite3")
    client = KimHanNomClient(project, state)
    assert client.unavailability_reason() == "no_token"
    assert client.is_available() is False
    state.close()
