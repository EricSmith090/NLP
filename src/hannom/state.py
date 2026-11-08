"""SQLite state and provenance.

The database is the source of truth for resumability, API quota accounting,
and human-review records. It intentionally stores paths, not image blobs.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import PageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    book_id TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    image_name TEXT NOT NULL,
    pdf_page INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    path TEXT NOT NULL,
    script TEXT NOT NULL DEFAULT 'unknown',
    section TEXT NOT NULL DEFAULT 'unknown',
    folder TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'extracted',
    ocr_engine TEXT,
    ocr_confidence REAL,
    review_flags TEXT NOT NULL DEFAULT '[]',
    features_json TEXT NOT NULL DEFAULT '{}',
    extraction_method TEXT NOT NULL DEFAULT '',
    rotation INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (book_id, page_no)
);
CREATE INDEX IF NOT EXISTS idx_pages_book_folder ON pages(book_id, folder);
CREATE INDEX IF NOT EXISTS idx_pages_sha ON pages(sha256);

CREATE TABLE IF NOT EXISTS api_calls (
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
CREATE INDEX IF NOT EXISTS idx_api_calls_time ON api_calls(requested_at);

CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id TEXT NOT NULL,
    page_no INTEGER,
    field TEXT NOT NULL,
    before TEXT,
    after TEXT,
    reviewer TEXT,
    reason TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    git_commit TEXT,
    config_hash TEXT,
    model_versions TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    note TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    book_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    key TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (book_id, stage, key)
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utc_now()).astimezone(timezone.utc).isoformat()


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "State":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_page(self, page: PageRecord) -> None:
        with self.tx() as c:
            c.execute(
                """
                INSERT INTO pages (
                    book_id, page_no, image_name, pdf_page, sha256, width, height,
                    path, script, section, folder, status, ocr_engine,
                    ocr_confidence, review_flags, features_json,
                    extraction_method, rotation, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(book_id, page_no) DO UPDATE SET
                    image_name=excluded.image_name,
                    pdf_page=excluded.pdf_page,
                    sha256=excluded.sha256,
                    width=excluded.width,
                    height=excluded.height,
                    path=excluded.path,
                    script=excluded.script,
                    section=excluded.section,
                    folder=excluded.folder,
                    status=excluded.status,
                    ocr_engine=excluded.ocr_engine,
                    ocr_confidence=excluded.ocr_confidence,
                    review_flags=excluded.review_flags,
                    features_json=excluded.features_json,
                    extraction_method=excluded.extraction_method,
                    rotation=excluded.rotation,
                    updated_at=excluded.updated_at
                """,
                (
                    page.book_id,
                    page.page_no,
                    page.image_name,
                    page.pdf_page,
                    page.sha256,
                    page.width,
                    page.height,
                    str(page.path),
                    page.script,
                    page.section,
                    str(page.folder),
                    page.status,
                    page.ocr_engine,
                    page.ocr_confidence,
                    json.dumps(page.review_flags, ensure_ascii=False),
                    json.dumps(page.features, ensure_ascii=False),
                    page.extraction_method,
                    page.rotation,
                    iso(),
                ),
            )

    def update_page(self, book_id: str, page_no: int, **fields: Any) -> None:
        allowed = {
            "script",
            "section",
            "folder",
            "status",
            "ocr_engine",
            "ocr_confidence",
            "review_flags",
            "features",
            "extraction_method",
            "rotation",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown page fields: {sorted(unknown)}")
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key == "review_flags":
                value = json.dumps(value, ensure_ascii=False)
                col = "review_flags"
            elif key == "features":
                value = json.dumps(value, ensure_ascii=False)
                col = "features_json"
            else:
                col = key
            sets.append(f"{col}=?")
            values.append(value)
        sets.append("updated_at=?")
        values.append(iso())
        values.extend([book_id, page_no])
        with self.tx() as c:
            c.execute(f"UPDATE pages SET {', '.join(sets)} WHERE book_id=? AND page_no=?", values)

    def pages(self, book_id: str) -> list[PageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE book_id=? ORDER BY page_no", (book_id,)
        ).fetchall()
        return [self._row_to_page(r) for r in rows]

    def page(self, book_id: str, page_no: int) -> PageRecord | None:
        row = self._conn.execute(
            "SELECT * FROM pages WHERE book_id=? AND page_no=?", (book_id, page_no)
        ).fetchone()
        return self._row_to_page(row) if row else None

    @staticmethod
    def _row_to_page(row: sqlite3.Row) -> PageRecord:
        return PageRecord(
            book_id=row["book_id"],
            page_no=row["page_no"],
            image_name=row["image_name"],
            pdf_page=row["pdf_page"],
            sha256=row["sha256"],
            width=row["width"],
            height=row["height"],
            path=Path(row["path"]),
            script=row["script"],
            section=row["section"],
            folder=row["folder"],
            status=row["status"],
            ocr_engine=row["ocr_engine"],
            ocr_confidence=row["ocr_confidence"],
            review_flags=json.loads(row["review_flags"] or "[]"),
            features=json.loads(row["features_json"] or "{}"),
            extraction_method=row["extraction_method"],
            rotation=row["rotation"],
        )

    def log_api_call(
        self,
        endpoint: str,
        image_sha256: str | None,
        status: str,
        response_path: str | None = None,
        token_id: str | None = None,
        note: str | None = None,
        requested_at: datetime | None = None,
    ) -> None:
        dt = requested_at or utc_now()
        with self.tx() as c:
            c.execute(
                """INSERT INTO api_calls
                (endpoint, image_sha256, token_id, requested_at, status,
                 response_path, quota_day, quota_week, note)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    endpoint,
                    image_sha256,
                    token_id,
                    iso(dt),
                    status,
                    response_path,
                    dt.date().isoformat(),
                    # SQLite cannot bind a tuple. Store an ISO week label so
                    # weekly quota audits remain readable and sortable.
                    f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}",
                    note,
                ),
            )

    def count_api_calls(self, since: datetime, endpoint: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM api_calls WHERE requested_at >= ?"
        args: list[Any] = [iso(since)]
        if endpoint:
            sql += " AND endpoint=?"
            args.append(endpoint)
        return int(self._conn.execute(sql, args).fetchone()["n"])

    def last_api_call(self, endpoint: str | None = None) -> datetime | None:
        sql = "SELECT requested_at FROM api_calls"
        args: list[Any] = []
        if endpoint:
            sql += " WHERE endpoint=?"
            args.append(endpoint)
        sql += " ORDER BY requested_at DESC LIMIT 1"
        row = self._conn.execute(sql, args).fetchone()
        return datetime.fromisoformat(row["requested_at"]) if row else None

    def api_calls_since(self, since: datetime) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM api_calls WHERE requested_at >= ? ORDER BY requested_at",
            (iso(since),),
        ).fetchall()

    def add_review(
        self,
        book_id: str,
        field: str,
        before: str | None,
        after: str | None,
        reviewer: str | None,
        reason: str | None,
        page_no: int | None = None,
    ) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO reviews
                (book_id, page_no, field, before, after, reviewer, reason, timestamp)
                VALUES (?,?,?,?,?,?,?,?)""",
                (book_id, page_no, field, before, after, reviewer, reason, iso()),
            )

    def set_artifact(
        self,
        book_id: str,
        stage: str,
        key: str,
        path: str | Path,
        sha256: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT INTO artifacts (book_id, stage, key, path, sha256, meta_json, updated_at)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(book_id, stage, key) DO UPDATE SET
                    path=excluded.path, sha256=excluded.sha256,
                    meta_json=excluded.meta_json, updated_at=excluded.updated_at""",
                (
                    book_id,
                    stage,
                    key,
                    str(path),
                    sha256,
                    json.dumps(meta or {}, ensure_ascii=False),
                    iso(),
                ),
            )

    def get_artifact(self, book_id: str, stage: str, key: str) -> Path | None:
        row = self._conn.execute(
            "SELECT path FROM artifacts WHERE book_id=? AND stage=? AND key=?",
            (book_id, stage, key),
        ).fetchone()
        return Path(row["path"]) if row else None

    def start_run(self, run_id: str, git_commit: str | None, config_hash: str | None) -> None:
        with self.tx() as c:
            c.execute(
                """INSERT OR REPLACE INTO runs
                (run_id, git_commit, config_hash, started_at, status)
                VALUES (?,?,?,?, 'running')""",
                (run_id, git_commit, config_hash, iso()),
            )

    def finish_run(self, run_id: str, status: str = "ok", note: str | None = None) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE runs SET finished_at=?, status=?, note=? WHERE run_id=?",
                (iso(), status, note, run_id),
            )


def default_state(project_root: str | Path) -> State:
    return State(Path(project_root) / "data" / "state.sqlite3")


def window_start(now: datetime, seconds: int) -> datetime:
    return now - timedelta(seconds=seconds)
