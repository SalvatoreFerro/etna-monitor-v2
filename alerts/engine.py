"""Alert evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass
class AlertComputation:
    """Result of an alert evaluation cycle."""

    moving_average: Optional[float]
    latest_value: Optional[float]
    threshold: float
    triggered: bool
    sample_size: int


def _coerce_values(values: Iterable[float]) -> List[float]:
    coerced: List[float] = []
    for value in values:
        try:
            coerced.append(float(value))
        except (TypeError, ValueError):
            continue
    return coerced


def compute_moving_average(values: Sequence[float], window: int) -> Optional[float]:
    """Return the moving average of the last ``window`` samples."""

    if window <= 0:
        raise ValueError("window must be > 0")

    data = _coerce_values(values)
    if not data:
        return None

    if len(data) < window:
        window_values = data
    else:
        window_values = data[-window:]

    if not window_values:
        return None

    return sum(window_values) / len(window_values)


def evaluate_threshold(
    values: Sequence[float],
    window: int,
    threshold: float,
) -> AlertComputation:
    """Evaluate if the moving average exceeds the provided threshold."""

    data = _coerce_values(values)
    if not data:
        return AlertComputation(None, None, float(threshold), False, 0)

    moving_avg = compute_moving_average(data, window)
    latest_value = data[-1] if data else None
    samples_used = min(len(data), window if len(data) >= window else len(data))

    triggered = moving_avg is not None and moving_avg > threshold

    return AlertComputation(moving_avg, latest_value, float(threshold), triggered, samples_used)

