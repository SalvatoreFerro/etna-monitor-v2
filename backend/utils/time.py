"""Time-related helpers shared across backend and app layers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import importlib.util

_PANDAS_SPEC = importlib.util.find_spec("pandas")
if _PANDAS_SPEC is not None:  # pragma: no cover - optional dependency
    import pandas as pd
else:  # pragma: no cover - pandas not installed in cron environment
    pd = None  # type: ignore[assignment]


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    if hasattr(value, "to_pydatetime"):
        try:
            converted = value.to_pydatetime()
            if isinstance(converted, datetime):
                return converted
        except Exception:
            return None

    return None


def to_iso_utc(ts: Any) -> str | None:
    """Serialize a timestamp-like object to ISO-8601 with a UTC ``Z`` suffix."""
    if ts is None:
        return None

    if pd is not None:
        if hasattr(ts, "tzinfo") and pd.isna(ts):  # Handles pandas NaT and friends.
            return None

        if isinstance(ts, str):
            ts = pd.to_datetime(ts, utc=True, errors="coerce")
            if ts is None or pd.isna(ts):
                return None

        if isinstance(ts, pd.Series):  # defensive guard
            raise TypeError("to_iso_utc does not accept pandas Series objects")

        if isinstance(ts, pd.Timestamp):
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            return ts.isoformat().replace("+00:00", "Z")

    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return ts.isoformat().replace("+00:00", "Z")

    if hasattr(ts, "tz_convert"):
        tz_value = getattr(ts, "tz", None)
        ts = ts.tz_convert("UTC") if tz_value is not None else ts.tz_localize("UTC")
        return ts.isoformat().replace("+00:00", "Z")

    converted = _coerce_datetime(ts)
    if converted is None:
        return None

    if converted.tzinfo is None:
        converted = converted.replace(tzinfo=timezone.utc)
    else:
        converted = converted.astimezone(timezone.utc)

    return converted.isoformat().replace("+00:00", "Z")

__all__ = ["to_iso_utc"]
