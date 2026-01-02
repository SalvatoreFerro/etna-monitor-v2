from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .utils_geo import haversine_km


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_same_event(
    item: dict[str, Any],
    other: dict[str, Any],
    max_km: float,
    max_hours: float,
) -> bool:
    if item.get("lat") is None or item.get("lon") is None:
        return False
    if other.get("lat") is None or other.get("lon") is None:
        return False

    time_a = _parse_time(item.get("time_utc"))
    time_b = _parse_time(other.get("time_utc"))
    if time_a is None or time_b is None:
        return False

    distance = haversine_km(float(item["lat"]), float(item["lon"]), float(other["lat"]), float(other["lon"]))
    if distance > max_km:
        return False

    delta_hours = abs((time_a - time_b).total_seconds()) / 3600
    return delta_hours <= max_hours


def deduplicate_items(
    items: list[dict[str, Any]],
    max_km: float,
    max_hours: float,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for item in items:
        if any(_is_same_event(item, existing, max_km, max_hours) for existing in deduped):
            continue
        deduped.append(item)
    return deduped


def apply_status(
    items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    max_km: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    if not previous_items:
        for item in items:
            item["status"] = "new"
        return items

    now = datetime.now(timezone.utc)
    recent_previous = []
    for prev in previous_items:
        prev_time = _parse_time(prev.get("time_utc"))
        if prev_time is None:
            continue
        if (now - prev_time).total_seconds() <= window_hours * 3600:
            recent_previous.append(prev)

    for item in items:
        if any(_is_same_event(item, prev, max_km, window_hours) for prev in recent_previous):
            item["status"] = "persistent"
        else:
            item["status"] = "new"
    return items


__all__ = ["deduplicate_items", "apply_status"]
