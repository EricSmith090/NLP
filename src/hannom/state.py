"""SQLite state and provenance.

The database is the source of truth for resumability, API quota accounting,
and human-review records. It intentionally stores paths, not image blobs.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import PageRecord

SCHEMA_VERSION = 1


class StateError(RuntimeError):
    """State database is corrupt, unreadable, or from an unsupported version."""


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
        try:
            self._conn = sqlite3.connect(str(self.path))
        except sqlite3.OperationalError as exc:
            raise StateError(
                f"state DB cannot be opened at {self.path} ({exc}); "
                f"create its parent directory or restore from a backup next to it"
            ) from exc
        self._conn.row_factory = sqlite3.Row
        try:
            row = self._conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise StateError(self._corruption_hint(f"PRAGMA quick_check failed ({exc})")) from exc
        if row is None or str(row[0]) != "ok":
            msg = "unknown" if row is None else str(row[0])
            self._conn.close()
            raise StateError(self._corruption_hint(f"PRAGMA quick_check returned {msg!r}"))
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        self._migrate(version)

    def _corruption_hint(self, detail: str) -> str:
        backups = sorted(self.path.parent.glob("state.sqlite3.bak-*")) if self.path.parent.exists() else []
        if backups:
            return (
                f"state DB corrupt at {self.path}: {detail}; "
                f"restore from newest of: {', '.join(str(b) for b in backups)}"
            )
        return f"state DB corrupt at {self.path}: {detail}; no state.sqlite3.bak-* backups found next to it"

    def _migrate(self, version: int) -> None:
        if version > SCHEMA_VERSION:
            self.close()
            raise StateError(
                f"state DB at {self.path} has user_version={version}, newer than "
                f"SCHEMA_VERSION={SCHEMA_VERSION}; upgrade the pipeline instead of opening it"
            )
        # CREATE TABLE IF NOT EXISTS keeps a valid v1 database untouched; a
        # brand-new file (user_version=0) gets the schema stamped with v1.
        with self.tx() as c:
            c.executescript(SCHEMA)
            c.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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

    def backup(self, tag: str | None = None) -> Path:
        """Timestamped copy of the database for pre-destructive-op safety."""
        stamp = utc_now().strftime("%Y%m%d-%H%M%S")
        suffix = f".bak-{stamp}" + (f"-{tag}" if tag else "")
        dest = self.path.with_name(self.path.name + suffix)
        shutil.copy2(self.path, dest)
        return dest

    def stage1_update(
        self,
        book_id: str,
        page_no: int,
        *,
        image_name: str,
        pdf_page: int,
        sha256: str,
        width: int,
        height: int,
        path: str | Path,
        extraction_method: str,
        rotation: int,
    ) -> None:
        """Update only Stage-1 columns; never touch downstream state.

        Used by re-extraction of unchanged files so `status`, `script`,
        `section`, `folder`, OCR results, `review_flags`, and `features_json`
        survive. Raises KeyError if the row is missing.
        """
        with self.tx() as c:
            cur = c.execute(
                """UPDATE pages SET image_name=?, pdf_page=?, sha256=?, width=?,
                   height=?, path=?, extraction_method=?, rotation=?, updated_at=?
                   WHERE book_id=? AND page_no=?""",
                (
                    image_name,
                    pdf_page,
                    sha256,
                    width,
                    height,
                    str(path),
                    extraction_method,
                    rotation,
                    iso(),
                    book_id,
                    page_no,
                ),
            )
            if cur.rowcount != 1:
                raise KeyError(f"no pages row for {book_id}:{page_no}")

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
                if not isinstance(value, list) or not all(isinstance(f, str) for f in value):
                    raise TypeError(f"review_flags must be list[str], got {value!r}")
                value = json.dumps(value, ensure_ascii=False)
                col = "review_flags"
            elif key == "features":
                if not isinstance(value, dict):
                    raise TypeError(f"features must be dict, got {type(value).__name__}")
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
            cur = c.execute(f"UPDATE pages SET {', '.join(sets)} WHERE book_id=? AND page_no=?", values)
            if cur.rowcount != 1:
                raise KeyError(f"no pages row for {book_id}:{page_no}")

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
            cur = c.execute(
                "UPDATE runs SET finished_at=?, status=?, note=? WHERE run_id=?",
                (iso(), status, note, run_id),
            )
            if cur.rowcount != 1:
                raise KeyError(f"no runs row for run_id={run_id!r}")


def window_start(now: datetime, seconds: int) -> datetime:
    return now - timedelta(seconds=seconds)
