"""Runtime metrics helpers shared across the application."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from flask import current_app


def record_csv_read(rows: int, last_timestamp: Optional[datetime]) -> None:
    """Store metrics about the latest successful CSV read."""

    if not current_app:
        return

    current_app.config["LAST_CSV_READ_AT"] = datetime.utcnow()
    current_app.config["LAST_CSV_ROW_COUNT"] = rows
    current_app.config["LAST_CSV_LAST_TS"] = last_timestamp
    current_app.config["LAST_CSV_ERROR"] = None


def record_csv_error(error_message: str) -> None:
    """Store information about the last CSV read error."""

    if not current_app:
        return

    current_app.config["LAST_CSV_READ_AT"] = datetime.utcnow()
    current_app.config["LAST_CSV_ERROR"] = error_message


def get_csv_metrics() -> dict:
    """Expose aggregated CSV metrics for health reporting."""

    if not current_app:
        return {}

    last_read = current_app.config.get("LAST_CSV_READ_AT")
    last_ts = current_app.config.get("LAST_CSV_LAST_TS")

    return {
        "last_read_at": last_read.isoformat() if isinstance(last_read, datetime) else None,
        "last_data_timestamp": last_ts.isoformat() if isinstance(last_ts, datetime) else None,
        "row_count": current_app.config.get("LAST_CSV_ROW_COUNT", 0),
        "last_error": current_app.config.get("LAST_CSV_ERROR"),
    }
