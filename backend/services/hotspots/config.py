from __future__ import annotations

from dataclasses import dataclass
import os


SUPPORTED_SOURCES = {
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
}


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _parse_bbox(value: str | None) -> tuple[str, tuple[float, float, float, float]]:
    default_bbox = "14.85,37.55,15.25,37.90"
    raw = value or default_bbox
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 4:
        raw = default_bbox
        parts = [p.strip() for p in raw.split(",")]
    try:
        coords = tuple(float(p) for p in parts)
    except ValueError:
        raw = default_bbox
        coords = tuple(float(p) for p in raw.split(","))
    return raw, coords  # type: ignore[return-value]


@dataclass(frozen=True)
class HotspotsConfig:
    enabled: bool
    map_key: str | None
    source: str
    bbox: str
    bbox_coords: tuple[float, float, float, float]
    day_range: int
    cache_ttl_min: int
    dedup_km: float
    dedup_hours: float
    new_window_hours: float
    data_dir: str
    cache_path: str

    @classmethod
    def from_env(cls) -> "HotspotsConfig":
        enabled = _parse_bool(os.getenv("HOTSPOTS_ENABLED"), default=False)
        map_key = os.getenv("FIRMS_API_KEY") or os.getenv("FIRMS_MAP_KEY")
        source = os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT").strip()
        if source not in SUPPORTED_SOURCES:
            source = "VIIRS_SNPP_NRT"

        bbox_raw, bbox_coords = _parse_bbox(
            os.getenv("HOTSPOTS_BBOX") or os.getenv("ETNA_BBOX")
        )
        day_range = _parse_int(os.getenv("HOTSPOTS_DAY_RANGE"), 1)
        cache_ttl_min = _parse_int(os.getenv("HOTSPOTS_CACHE_TTL_MIN"), 180)
        dedup_km = _parse_float(os.getenv("HOTSPOTS_DEDUP_KM"), 1.0)
        dedup_hours = _parse_float(os.getenv("HOTSPOTS_DEDUP_HOURS"), 2.0)
        new_window_hours = _parse_float(os.getenv("HOTSPOTS_NEW_WINDOW_HOURS"), 12.0)
        data_dir = os.getenv("DATA_DIR", "data")
        cache_path = os.path.join(data_dir, "hotspots_latest.json")

        return cls(
            enabled=enabled,
            map_key=map_key,
            source=source,
            bbox=bbox_raw,
            bbox_coords=bbox_coords,
            day_range=day_range,
            cache_ttl_min=cache_ttl_min,
            dedup_km=dedup_km,
            dedup_hours=dedup_hours,
            new_window_hours=new_window_hours,
            data_dir=data_dir,
            cache_path=cache_path,
        )


__all__ = ["HotspotsConfig", "SUPPORTED_SOURCES"]
