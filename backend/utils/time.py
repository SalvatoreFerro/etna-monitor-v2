"""Time-related helpers shared across backend and app layers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def to_iso_utc(ts: Any) -> str | None:
    """Serialize a timestamp-like object to ISO-8601 with a UTC ``Z`` suffix."""
    if ts is None:
        return None

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

    try:
        converted = pd.to_datetime(ts, utc=True, errors="coerce")
    except Exception:
        converted = None

    if converted is None or pd.isna(converted):
        return None

    if converted.tz is None:
        converted = converted.tz_localize("UTC")
    else:
        converted = converted.tz_convert("UTC")

    return converted.isoformat().replace("+00:00", "Z")

__all__ = ["to_iso_utc"]
