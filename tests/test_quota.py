from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hannom.ocr.quota import QuotaExceeded, QuotaLedger
from hannom.state import State


def test_quota_week_is_bound_as_text(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    state.log_api_call("image-ocr", "abc", "http_200", requested_at=now)
    row = state._conn.execute("SELECT quota_day, quota_week FROM api_calls").fetchone()
    assert row["quota_day"] == "2026-11-08"
    assert row["quota_week"] == "2026-W45"
    state.close()


def test_quota_windows_and_retry_after(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    now = datetime.now(timezone.utc)
    state.log_api_call("image-ocr", "a", "http_200", requested_at=now - timedelta(seconds=5))
    state.log_api_call("image-ocr", "b", "http_200", requested_at=now - timedelta(seconds=4))
    ledger = QuotaLedger(state, {"per_minute": 2, "per_hour": 50, "per_day": 200, "per_week": 600}, 0)
    with pytest.raises(QuotaExceeded):
        ledger.check(now)
    assert ledger.snapshot(now).minute == 2
    assert ledger.seconds_until_allowed(now) > 0
    state.close()


def test_quota_allows_below_limit(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    now = datetime.now(timezone.utc)
    state.log_api_call("image-ocr", "a", "http_200", requested_at=now - timedelta(seconds=300))
    ledger = QuotaLedger(state, {"per_minute": 2, "per_hour": 50, "per_day": 200, "per_week": 600}, 0)
    ledger.check(now)
    state.close()
