from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pandas as pd

from backend.utils.time import to_iso_utc

_CURVA_ENV_PATH = os.getenv("CURVA_CSV_PATH")
CURVA_CANONICAL_PATH = Path(_CURVA_ENV_PATH or "data/curva_colored.csv")
# Fallback paths for backward compatibility (deprecated - use canonical path)
_CURVA_FALLBACK_PATHS = [Path("data/curva_colored.csv")]


def get_curva_csv_path() -> Path:
    """
    Return the canonical curva.csv path with fallback logic.
    
    Resolution order:
    1. If CURVA_CSV_PATH env var is set, use that path (no fallback)
    2. Try canonical path: data/curva_colored.csv
    3. Fallback to: data/curva.csv (for backward compatibility)
    4. If nothing exists, return canonical path anyway
    
    The fallback exists for backward compatibility with older deployments.
    New deployments should always use data/curva_colored.csv as the
    single source of truth.
    
    Returns:
        Path: The path to use for reading/writing tremor CSV data
    """
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
    "load_curva_dataframe",
    "warn_if_stale_timestamp",
]
