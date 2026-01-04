"""Runtime metrics helpers shared across the application."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import current_app


def _resolve_csv_metrics_path() -> Path:
    if current_app:
        configured = current_app.config.get("CSV_METRICS_PATH")
        if configured:
            return Path(configured)
    data_dir = os.getenv("DATA_DIR", "data")
    return Path(os.getenv("CSV_METRICS_PATH", os.path.join(data_dir, "csv_metrics.json")))


def _read_csv_metrics_file() -> dict:
    path = _resolve_csv_metrics_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_csv_metrics_file(payload: dict) -> None:
    path = _resolve_csv_metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def record_csv_read(rows: int, last_timestamp: Optional[datetime]) -> None:
    """Store metrics about the latest successful CSV read."""

    if not current_app:
        return

    current_app.config["LAST_CSV_READ_AT"] = datetime.now(timezone.utc)
    current_app.config["LAST_CSV_ROW_COUNT"] = rows
    current_app.config["LAST_CSV_LAST_TS"] = last_timestamp
    current_app.config["LAST_CSV_ERROR"] = None


def record_csv_error(error_message: str) -> None:
    """Store information about the last CSV read error."""

    if not current_app:
        return

    current_app.config["LAST_CSV_READ_AT"] = datetime.now(timezone.utc)
    current_app.config["LAST_CSV_ERROR"] = error_message


def record_csv_update(
    rows: int | None,
    last_timestamp: Optional[datetime],
    *,
    error_message: str | None = None,
) -> None:
    payload = {
        "last_update_at": datetime.now(timezone.utc).isoformat(),
        "row_count": rows,
        "last_data_timestamp": last_timestamp.isoformat() if last_timestamp else None,
        "last_error": error_message,
    }
    _write_csv_metrics_file(payload)


def get_csv_metrics() -> dict:
    """Expose aggregated CSV metrics for health reporting."""

    if not current_app:
        return {}

    last_read = current_app.config.get("LAST_CSV_READ_AT")
    last_ts = current_app.config.get("LAST_CSV_LAST_TS")

    update_metrics = _read_csv_metrics_file()

    return {
        "last_read_at": last_read.isoformat() if isinstance(last_read, datetime) else None,
        "last_data_timestamp": last_ts.isoformat() if isinstance(last_ts, datetime) else None,
        "row_count": current_app.config.get("LAST_CSV_ROW_COUNT", 0),
        "last_error": current_app.config.get("LAST_CSV_ERROR"),
        "last_update_at": update_metrics.get("last_update_at"),
        "last_update_row_count": update_metrics.get("row_count"),
        "last_update_data_timestamp": update_metrics.get("last_data_timestamp"),
        "last_update_error": update_metrics.get("last_error"),
    }
