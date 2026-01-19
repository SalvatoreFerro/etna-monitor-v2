from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from ..models import ApiUsageDaily, ApiUsageMinute, db


PLAN_LIMITS = {
    "FREE": {"minute": 60, "day": 5_000},
    "PARTNER": {"minute": 300, "day": 50_000},
    "PRO": {"minute": 1_200, "day": 300_000},
}


@dataclass(frozen=True)
class RateLimitStatus:
    allowed: bool
    minute_count: int
    day_count: int
    minute_limit: int
    day_limit: int


def _plan_limits(plan: str | None) -> dict:
    if not plan:
        return PLAN_LIMITS["FREE"]
    return PLAN_LIMITS.get(plan.upper(), PLAN_LIMITS["FREE"])


def _increment_daily_count(key_id: int, date_value) -> int:
    db.session.execute(
        text(
            """
            INSERT INTO api_usage_daily (key_id, date, requests_count)
            VALUES (:key_id, :date_value, 1)
            ON CONFLICT (key_id, date)
            DO UPDATE SET requests_count = api_usage_daily.requests_count + 1
            """
        ),
        {"key_id": key_id, "date_value": date_value},
    )
    return (
        db.session.query(ApiUsageDaily.requests_count)
        .filter_by(key_id=key_id, date=date_value)
        .scalar()
        or 0
    )


def _increment_minute_count(key_id: int, minute_bucket: datetime) -> int:
    db.session.execute(
        text(
            """
            INSERT INTO api_usage_minute (key_id, minute_bucket, requests_count)
            VALUES (:key_id, :minute_bucket, 1)
            ON CONFLICT (key_id, minute_bucket)
            DO UPDATE SET requests_count = api_usage_minute.requests_count + 1
            """
        ),
        {"key_id": key_id, "minute_bucket": minute_bucket},
    )
    return (
        db.session.query(ApiUsageMinute.requests_count)
        .filter_by(key_id=key_id, minute_bucket=minute_bucket)
        .scalar()
        or 0
    )


def enforce_rate_limits(key_id: int, plan: str | None) -> RateLimitStatus:
    now = datetime.utcnow()
    limits = _plan_limits(plan)
    minute_bucket = now.replace(second=0, microsecond=0)
    day_value = now.date()

    minute_count = _increment_minute_count(key_id, minute_bucket)
    day_count = _increment_daily_count(key_id, day_value)

    allowed = minute_count <= limits["minute"] and day_count <= limits["day"]
    return RateLimitStatus(
        allowed=allowed,
        minute_count=minute_count,
        day_count=day_count,
        minute_limit=limits["minute"],
        day_limit=limits["day"],
    )
