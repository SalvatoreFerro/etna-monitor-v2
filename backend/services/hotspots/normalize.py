from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from backend.utils.time import to_iso_utc

from .config import HotspotsConfig


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(record: dict[str, Any]) -> datetime | None:
    timestamp = (record.get("timestamp") or "").strip()
    if timestamp:
        normalized = timestamp.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            parsed = None
        if parsed:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

    acq_date = (record.get("acq_date") or "").strip()
    acq_time = (record.get("acq_time") or "").strip()
    if not acq_date:
        return None
    time_str = acq_time.zfill(4) if acq_time else "0000"
    try:
        parsed = datetime.strptime(f"{acq_date} {time_str}", "%Y-%m-%d %H%M")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _normalize_confidence(raw: str | None) -> str:
    if raw is None:
        return "unknown"
    value = raw.strip().lower()
    if not value:
        return "unknown"
    if value in {"l", "low"}:
        return "low"
    if value in {"n", "nominal", "medium", "med"}:
        return "nominal"
    if value in {"h", "high"}:
        return "high"
    try:
        numeric = float(value)
    except ValueError:
        return "unknown"
    if numeric < 30:
        return "low"
    if numeric < 80:
        return "nominal"
    return "high"


def _satellite_from_source(source: str) -> str:
    if "MODIS" in source:
        return "MODIS"
    if "VIIRS" in source:
        return "VIIRS"
    return "UNKNOWN"


def _build_stable_id(lat: float, lon: float, time_utc: datetime, satellite: str, source: str) -> str:
    lat_round = round(lat, 3)
    lon_round = round(lon, 3)
    time_bucket = time_utc.strftime("%Y%m%d%H")
    raw = f"{lat_round}|{lon_round}|{time_bucket}|{satellite}|{source}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def normalize_records(
    raw_records: list[dict[str, Any]],
    source: str,
    config: HotspotsConfig,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in raw_records:
        lat = _parse_float(record.get("latitude"))
        lon = _parse_float(record.get("longitude"))
        if lat is None or lon is None:
            continue

        timestamp = _parse_time(record)
        if timestamp is None:
            continue

        satellite = (record.get("satellite") or "").strip().upper()
        if not satellite:
            satellite = _satellite_from_source(source)

        confidence = _normalize_confidence(record.get("confidence"))

        instrument = (record.get("instrument") or "").strip().upper() or None
        daynight = (record.get("daynight") or "").strip().upper() or None
        version = (record.get("version") or "").strip() or None

        frp = _parse_float(record.get("frp"))
        bright_ti4 = _parse_float(record.get("bright_ti4"))
        bright_ti5 = _parse_float(record.get("bright_ti5"))
        brightness = _parse_float(record.get("brightness"))
        if bright_ti4 is not None:
            brightness = bright_ti4
        elif brightness is None:
            brightness = bright_ti5
        if frp is not None:
            unit = "MW"
        elif brightness is not None:
            unit = "K"
        else:
            unit = "unknown"

        item = {
            "id": _build_stable_id(lat, lon, timestamp, satellite, source),
            "time_utc": to_iso_utc(timestamp),
            "lat": lat,
            "lon": lon,
            "satellite": satellite if satellite else "UNKNOWN",
            "instrument": instrument,
            "source": source,
            "confidence": confidence,
            "intensity": {
                "frp": frp,
                "brightness": brightness,
                "unit": unit,
            },
            "bright_ti4": bright_ti4,
            "bright_ti5": bright_ti5,
            "daynight": daynight,
            "version": version,
            "status": "new",
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
        }
        items.append(item)
    return items


__all__ = ["normalize_records"]
