from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.models import db
from app.models.tremor_prediction import TremorPrediction
from app.services.tremor_summary import load_tremor_dataframe
from app.utils.logger import get_logger

logger = get_logger(__name__)

PREDICTION_HORIZON_HOURS = 24
PREDICTION_CHOICES = {"UP", "DOWN", "FLAT"}
TREND_UP_THRESHOLD = 1.10
TREND_DOWN_THRESHOLD = 0.90
NOW_WINDOW_POINTS = 12


def _normalize_reference_time(reference_time: datetime | None) -> datetime | None:
    if reference_time is None:
        return None
    if reference_time.tzinfo is None:
        return reference_time.replace(tzinfo=timezone.utc)
    return reference_time.astimezone(timezone.utc)


def compute_tremor_outcome(
    df: pd.DataFrame,
    reference_time: datetime | None = None,
) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None

    df = df.copy()
    if "timestamp" not in df.columns or "value" not in df.columns:
        return None

    df = df.dropna(subset=["timestamp", "value"]).sort_values("timestamp")
    if df.empty:
        return None

    reference_time = _normalize_reference_time(reference_time)
    if reference_time is None:
        reference_time = df["timestamp"].iloc[-1].to_pydatetime()

    if isinstance(reference_time, pd.Timestamp):
        reference_time = reference_time.to_pydatetime()
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    df_before = df[df["timestamp"] <= reference_time]
    if df_before.empty:
        df_before = df

    now_window = df_before.tail(max(1, NOW_WINDOW_POINTS))
    now_value = float(now_window["value"].max())

    prev_target = reference_time - timedelta(hours=PREDICTION_HORIZON_HOURS)
    prev_idx = (df["timestamp"] - prev_target).abs().idxmin()
    prev_value = float(df.loc[prev_idx, "value"])

    if prev_value <= 0:
        outcome = "FLAT"
    elif now_value > prev_value * TREND_UP_THRESHOLD:
        outcome = "UP"
    elif now_value < prev_value * TREND_DOWN_THRESHOLD:
        outcome = "DOWN"
    else:
        outcome = "FLAT"

    return {
        "outcome": outcome,
        "now_value": now_value,
        "prev_value": prev_value,
        "reference_time": reference_time,
    }


def resolve_expired_predictions(
    *,
    now: datetime | None = None,
) -> int:
    now = _normalize_reference_time(now) or datetime.now(timezone.utc)

    df, reason = load_tremor_dataframe()
    if reason or df is None:
        logger.warning("[PREDICTIONS] Dataset unavailable for resolution: %s", reason)
        return 0

    predictions = (
        TremorPrediction.query.filter(
            TremorPrediction.resolved.is_(False),
            TremorPrediction.resolves_at <= now,
        )
        .order_by(TremorPrediction.resolves_at.asc())
        .all()
    )

    if not predictions:
        return 0

    resolved_count = 0
    for prediction in predictions:
        outcome_payload = compute_tremor_outcome(df, prediction.resolves_at)
        if outcome_payload is None:
            logger.warning(
                "[PREDICTIONS] Unable to resolve prediction id=%s due to missing trend",
                prediction.id,
            )
            continue

        outcome = outcome_payload["outcome"]
        prediction.actual_outcome = outcome
        prediction.points_awarded = 3 if prediction.prediction == outcome else 0
        prediction.resolved = True
        resolved_count += 1

    if resolved_count:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[PREDICTIONS] Failed to commit prediction resolutions")
            return 0

    return resolved_count


__all__ = [
    "compute_tremor_outcome",
    "resolve_expired_predictions",
    "PREDICTION_CHOICES",
    "PREDICTION_HORIZON_HOURS",
]
