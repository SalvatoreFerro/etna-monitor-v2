from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify

from ..utils.api_keys import require_api_key
from ..utils.attribution import attribution_snippet, powered_by_payload
from backend.utils.time import to_iso_utc

api_v1_bp = Blueprint("api_v1", __name__)


def _error_response(code: str, message: str, status_code: int):
    return (
        jsonify(
            {
                "error": {"code": code, "message": message},
                "powered_by": powered_by_payload(),
            }
        ),
        status_code,
    )


def _load_tremor_dataframe() -> tuple[pd.DataFrame | None, str | None]:
    csv_path_setting = (
        current_app.config.get("CURVA_CSV_PATH")
        or current_app.config.get("CSV_PATH")
        or "/var/tmp/curva.csv"
    )
    csv_path = Path(csv_path_setting)

    if not csv_path.exists() or csv_path.stat().st_size <= 20:
        return None, "missing_data"

    try:
        raw_df = pd.read_csv(csv_path)
    except Exception:
        return None, "read_error"

    if "timestamp" not in raw_df.columns:
        return None, "missing_timestamp"

    df = raw_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if "value" not in df.columns:
        if "value_max" in df.columns:
            df["value"] = df["value_max"]
        elif "value_avg" in df.columns:
            df["value"] = df["value_avg"]

    if "value" not in df.columns:
        return None, "missing_value"

    df = df.dropna(subset=["value"]).sort_values("timestamp")
    if df.empty:
        return None, "empty_data"

    return df, None


def _calculate_trend(df: pd.DataFrame, window_minutes: int = 60) -> dict | None:
    if df.empty:
        return None

    latest_ts = df["timestamp"].max()
    window_start = latest_ts - timedelta(minutes=window_minutes)
    window_df = df[df["timestamp"] >= window_start].copy()

    if window_df.empty:
        return None

    window_df = window_df.sort_values("timestamp")

    sample_size = min(3, len(window_df))
    head_mean = window_df["value"].head(sample_size).mean()
    tail_mean = window_df["value"].tail(sample_size).mean()

    eps = 1e-6
    delta = (tail_mean - head_mean) / max(head_mean, eps)

    if abs(delta) < 0.05:
        status = "STABILE"
        direction = "flat"
        message = "Tremore stabile nell’ultima ora"
    elif delta >= 0.05:
        status = "IN_AUMENTO"
        direction = "up"
        message = "Tremore in aumento nell’ultima ora"
    else:
        status = "IN_CALO"
        direction = "down"
        message = "Tremore in calo nell’ultima ora"

    latest_value = float(window_df["value"].iloc[-1])

    return {
        "ts_utc": to_iso_utc(latest_ts.to_pydatetime()),
        "status": status,
        "direction": direction,
        "value_mv": latest_value,
        "window_min": window_minutes,
        "message": message,
        "source": "INGV",
    }


@api_v1_bp.get("/api/v1/tremor/status")
@require_api_key()
def tremor_status():
    df, reason = _load_tremor_dataframe()
    if reason or df is None:
        return _error_response(
            "data_unavailable",
            "Dati INGV non disponibili al momento.",
            503,
        )

    trend = _calculate_trend(df)
    if trend is None:
        return _error_response(
            "data_unavailable",
            "Dati INGV non disponibili al momento.",
            503,
        )

    trend["powered_by"] = powered_by_payload()
    return jsonify(trend)


@api_v1_bp.get("/api/v1/attribution/snippet")
def attribution_snippet_endpoint():
    payload = attribution_snippet()
    payload["powered_by"] = powered_by_payload()
    return jsonify(payload)
