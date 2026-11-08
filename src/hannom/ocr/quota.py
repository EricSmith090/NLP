"""Rolling-window quota ledger for the Kim Hán Nôm API.

The API manual gives 25/minute, 50/hour, 200/day, 600/week. We enforce all
four windows locally and also enforce a minimum delay between requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from ..state import State, iso, utc_now


class QuotaExceeded(RuntimeError):
    def __init__(self, message: str, retry_after: float, snapshot: "QuotaSnapshot"):
        super().__init__(message)
        self.retry_after = retry_after
        self.snapshot = snapshot


@dataclass
class QuotaSnapshot:
    minute: int
    hour: int
    day: int
    week: int
    limits: Mapping[str, int]

    def to_dict(self) -> dict[str, int]:
        return {
            "minute": self.minute,
            "hour": self.hour,
            "day": self.day,
            "week": self.week,
            **{f"limit_{k}": v for k, v in self.limits.items()},
        }


WINDOWS = {
    "minute": 60,
    "hour": 3600,
    "day": 86400,
    "week": 604800,
}


class QuotaLedger:
    def __init__(self, state: State, limits: Mapping[str, int], min_delay_seconds: float = 3.0):
        self.state = state
        self.limits = {
            "minute": int(limits.get("per_minute", limits.get("minute", 25))),
            "hour": int(limits.get("per_hour", limits.get("hour", 50))),
            "day": int(limits.get("per_day", limits.get("day", 200))),
            "week": int(limits.get("per_week", limits.get("week", 600))),
        }
        self.min_delay_seconds = float(min_delay_seconds)

    def snapshot(self, now: datetime | None = None) -> QuotaSnapshot:
        now = now or utc_now()
        counts = {
            name: self.state.count_api_calls(now - timedelta(seconds=seconds))
            for name, seconds in WINDOWS.items()
        }
        return QuotaSnapshot(
            minute=counts["minute"],
            hour=counts["hour"],
            day=counts["day"],
            week=counts["week"],
            limits=self.limits,
        )

    def seconds_until_allowed(self, now: datetime | None = None) -> float:
        now = now or utc_now()
        waits = [0.0]
        last = self.state.last_api_call()
        if last is not None:
            waits.append(max(0.0, (last + timedelta(seconds=self.min_delay_seconds) - now).total_seconds()))
        for name, seconds in WINDOWS.items():
            limit = self.limits[name]
            since = now - timedelta(seconds=seconds)
            rows = self.state.api_calls_since(since)
            if len(rows) >= limit:
                # The oldest call in this window must age out.
                oldest = datetime.fromisoformat(rows[0]["requested_at"])
                waits.append(max(0.0, (oldest + timedelta(seconds=seconds) - now).total_seconds()))
        return max(waits)

    def check(self, now: datetime | None = None) -> QuotaSnapshot:
        now = now or utc_now()
        snap = self.snapshot(now)
        exceeded = [
            name
            for name in WINDOWS
            if getattr(snap, name) >= self.limits[name]
        ]
        if exceeded:
            wait = self.seconds_until_allowed(now)
            raise QuotaExceeded(
                f"Kim Hán Nôm quota reached for: {', '.join(exceeded)}; retry in {wait:.0f}s",
                retry_after=wait,
                snapshot=snap,
            )
        return snap

    def record(
        self,
        endpoint: str,
        image_sha256: str | None,
        status: str,
        response_path: str | None = None,
        note: str | None = None,
        now: datetime | None = None,
    ) -> None:
        self.state.log_api_call(
            endpoint=endpoint,
            image_sha256=image_sha256,
            status=status,
            response_path=response_path,
            note=note,
            requested_at=now or utc_now(),
        )

    def validate_ledger_timestamp(self, dt: datetime) -> str:
        return iso(dt)
