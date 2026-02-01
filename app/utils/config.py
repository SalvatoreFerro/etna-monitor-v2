from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pandas as pd

from backend.utils.time import to_iso_utc

_DEFAULT_STALE_HOURS = int(os.getenv("CURVA_STALE_HOURS", "6"))

_CURVA_ENV_PATH = os.getenv("CURVA_CSV_PATH")
CURVA_CANONICAL_PATH = Path(_CURVA_ENV_PATH or "data/curva_colored.csv")
_CURVA_FALLBACK_PATHS = [Path("data/curva_colored.csv"), Path("data/curva.csv")]


def get_curva_csv_path() -> Path:
    """Return the canonical curva.csv path."""
    if _CURVA_ENV_PATH:
        return CURVA_CANONICAL_PATH
    if CURVA_CANONICAL_PATH.exists():
        return CURVA_CANONICAL_PATH
    for fallback in _CURVA_FALLBACK_PATHS:
        if fallback.exists():
            return fallback
    return CURVA_CANONICAL_PATH


def _prepare_curva_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    if "timestamp" not in df.columns:
        return pd.DataFrame(columns=["timestamp", "value"]), "missing_timestamp"

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if "value" not in df.columns:
        if "value_max" in df.columns:
            df["value"] = df["value_max"]
        elif "value_avg" in df.columns:
            df["value"] = df["value_avg"]

    if "value" not in df.columns:
        return pd.DataFrame(columns=["timestamp", "value"]), "missing_value"

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])

    if df.empty:
        return df, "empty"

    return df, None


def _normalize_timestamp_utc(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        if value.tz is None:
            return value.tz_localize("UTC").to_pydatetime()
        return value.tz_convert("UTC").to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def get_temporal_status_from_timestamp(
    last_ts: pd.Timestamp | datetime | None,
    *,
    stale_hours: int | None = None,
) -> dict:
    updated_at = _normalize_timestamp_utc(last_ts)
    updated_at_iso = to_iso_utc(updated_at) if updated_at else None
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(hours=stale_hours or _DEFAULT_STALE_HOURS)
    age_hours = None
    is_stale = False
    detected_today = False
    if updated_at:
        age_delta = now - updated_at
        age_hours = round(age_delta.total_seconds() / 3600, 2)
        is_stale = age_delta > stale_threshold
        detected_today = updated_at.date() == now.date()
        if is_stale:
            detected_today = False
    return {
        "updated_at": updated_at,
        "updated_at_iso": updated_at_iso,
        "detected_today": detected_today,
        "is_stale": is_stale,
        "age_hours": age_hours,
        "stale_threshold_hours": stale_threshold.total_seconds() / 3600,
    }


def load_curva_dataframe(path: Path) -> tuple[pd.DataFrame | None, str | None]:
    if not path.exists():
        return None, "csv_missing"

    try:
        raw_df = pd.read_csv(path)
    except Exception as exc:
        return None, f"read_error::{exc}"

    df, reason = _prepare_curva_dataframe(raw_df)
    if reason:
        return None, reason

    return df, None


def get_curva_csv_status(path: Path, df: pd.DataFrame | None = None) -> dict:
    status = {
        "csv_path_used": str(path),
        "file_exists": path.exists(),
        "mtime_utc": None,
        "rowcount": 0,
        "first_ts": None,
        "last_ts": None,
        "last_value_mv": None,
        "error": None,
    }

    if not status["file_exists"]:
        return status

    try:
        stat = path.stat()
        status["mtime_utc"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    except OSError as exc:
        status["error"] = f"stat_error::{exc}"
        return status

    if df is None:
        df, reason = load_curva_dataframe(path)
        if reason:
            status["error"] = reason
            return status

    df = df.sort_values("timestamp")
    status["rowcount"] = int(len(df))
    if len(df):
        first_ts = df["timestamp"].iloc[0]
        last_ts = df["timestamp"].iloc[-1]
        status["first_ts"] = to_iso_utc(first_ts)
        status["last_ts"] = to_iso_utc(last_ts)
        try:
            status["last_value_mv"] = float(df["value"].iloc[-1])
        except (TypeError, ValueError):
            status["last_value_mv"] = None

    return status


def get_curva_csv_temporal_status(path: Path, df: pd.DataFrame | None = None) -> dict:
    if df is None:
        df, reason = load_curva_dataframe(path)
        if reason or df is None or df.empty:
            return get_temporal_status_from_timestamp(None)

    df = df.sort_values("timestamp")
    last_ts = df["timestamp"].iloc[-1] if len(df) else None
    return get_temporal_status_from_timestamp(last_ts)


def warn_if_stale_timestamp(
    last_ts: pd.Timestamp | datetime | None,
    logger,
    context: str,
) -> None:
    if last_ts is None:
        return
    if isinstance(last_ts, pd.Timestamp):
        if last_ts.tz is None:
            last_ts = last_ts.tz_localize("UTC")
        else:
            last_ts = last_ts.tz_convert("UTC")
    elif isinstance(last_ts, datetime):
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)
        else:
            last_ts = last_ts.astimezone(timezone.utc)
    else:
        return

    now = datetime.now(timezone.utc)
    if now - last_ts > timedelta(hours=2):
        logger.warning(
            "[CSV] Stale dataset detected context=%s last_ts=%s now=%s",
            context,
            last_ts.isoformat(),
            now.isoformat(),
        )


__all__ = [
    "CURVA_CANONICAL_PATH",
    "get_curva_csv_path",
    "get_curva_csv_status",
    "get_curva_csv_temporal_status",
    "get_temporal_status_from_timestamp",
    "load_curva_dataframe",
    "warn_if_stale_timestamp",
]
