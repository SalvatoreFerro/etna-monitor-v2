from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_AGGREGATED_PRODUCTS = [
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
    "MODIS_TERRA",
    "MODIS_AQUA",
]

SUPPORTED_SOURCES = {
    "VIIRS_SNPP_NRT",
    "MODIS_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "VIIRS_SNPP",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
    "MODIS_TERRA",
    "MODIS_AQUA",
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


def _parse_list(value: str | None) -> list[str]:
    if not value:
        return []
    items: list[str] = []
    for raw in value.replace(";", ",").split(","):
        cleaned = raw.strip()
        if cleaned:
            items.append(cleaned)
    return items


def _dataset_from_source(source: str) -> str:
    upper = source.upper()
    if "MODIS" in upper:
        return "MODIS"
    if "VIIRS" in upper:
        return "VIIRS"
    return "UNKNOWN"


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


def _pad_bbox(
    coords: tuple[float, float, float, float],
    padding: float,
) -> tuple[float, float, float, float]:
    west, south, east, north = coords
    if padding <= 0:
        return coords
    return (
        max(-180.0, west - padding),
        max(-90.0, south - padding),
        min(180.0, east + padding),
        min(90.0, north + padding),
    )


def _bbox_to_string(coords: tuple[float, float, float, float]) -> str:
    west, south, east, north = coords
    return f"{west:.5f},{south:.5f},{east:.5f},{north:.5f}"


@dataclass(frozen=True)
class HotspotsConfig:
    enabled: bool
    map_key: str | None
    mode: str
    source: str
    dataset: str
    products: tuple[str, ...]
    include_platforms: tuple[str, ...]
    include_modis: bool
    bbox: str
    bbox_coords: tuple[float, float, float, float]
    bbox_raw: str
    bbox_coords_raw: tuple[float, float, float, float]
    bbox_padding_deg: float
    fetch_bbox: str
    fetch_bbox_coords: tuple[float, float, float, float]
    day_range: int
    cache_ttl_min: int
    dedup_km: float
    dedup_hours: float
    new_window_hours: float
    significant_confidence_min: str
    significant_brightness_min: float
    significant_frp_min: float
    data_dir: str
    cache_path: str

    @classmethod
    def from_env(cls) -> "HotspotsConfig":
        enabled = _parse_bool(os.getenv("HOTSPOTS_ENABLED"), default=False)
        map_key = os.getenv("FIRMS_API_KEY") or os.getenv("FIRMS_MAP_KEY")
        mode = os.getenv("FIRMS_MODE", "STANDARD").strip().upper()
        source = os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT").strip()
        if source not in SUPPORTED_SOURCES:
            source = "VIIRS_SNPP_NRT"
        dataset = "FIRMS_AGGREGATED_24H" if mode == "FIRMS_AGGREGATED_24H" else _dataset_from_source(source)
        products_raw = _parse_list(os.getenv("FIRMS_PRODUCTS"))
        if products_raw:
            products = [product.strip().upper() for product in products_raw if product.strip()]
        elif mode == "FIRMS_AGGREGATED_24H":
            products = DEFAULT_AGGREGATED_PRODUCTS.copy()
        else:
            products = []
        products = [product for product in products if product in SUPPORTED_SOURCES]
        include_platforms_raw = _parse_list(os.getenv("HOTSPOTS_INCLUDE_PLATFORMS"))
        include_platforms = (
            [p.upper() for p in include_platforms_raw]
            if include_platforms_raw
            else (["SNPP", "NOAA20", "NOAA21"] if dataset == "VIIRS" else [])
        )
        include_modis = _parse_bool(os.getenv("HOTSPOTS_INCLUDE_MODIS"), default=False)

        bbox_raw, bbox_coords_raw = _parse_bbox(
            os.getenv("HOTSPOTS_BBOX") or os.getenv("ETNA_BBOX")
        )
        bbox_padding_deg = _parse_float(
            os.getenv("HOTSPOTS_BBOX_PADDING_DEG") or os.getenv("ETNA_BBOX_PADDING_DEG"),
            0.02,
        )
        bbox_coords = _pad_bbox(bbox_coords_raw, bbox_padding_deg)
        bbox = _bbox_to_string(bbox_coords)
        fetch_bbox_raw = os.getenv("HOTSPOTS_FETCH_BBOX") or os.getenv("FIRMS_FETCH_BBOX")
        if not fetch_bbox_raw and mode == "FIRMS_AGGREGATED_24H":
            fetch_bbox_raw = "-180,-90,180,90"
        fetch_bbox_raw, fetch_bbox_coords = _parse_bbox(fetch_bbox_raw)
        fetch_bbox = _bbox_to_string(fetch_bbox_coords)
        day_range = _parse_int(os.getenv("HOTSPOTS_DAY_RANGE"), 1)
        cache_ttl_min = _parse_int(os.getenv("HOTSPOTS_CACHE_TTL_MIN"), 180)
        dedup_km = _parse_float(os.getenv("HOTSPOTS_DEDUP_KM"), 1.0)
        dedup_hours = _parse_float(os.getenv("HOTSPOTS_DEDUP_HOURS"), 2.0)
        new_window_hours = _parse_float(os.getenv("HOTSPOTS_NEW_WINDOW_HOURS"), 12.0)
        significant_confidence_min = (
            os.getenv("HOTSPOTS_SIGNIFICANT_CONFIDENCE_MIN", "nominal").strip().lower()
        )
        significant_brightness_min = _parse_float(
            os.getenv("HOTSPOTS_SIGNIFICANT_BRIGHTNESS_MIN"),
            325.0,
        )
        significant_frp_min = _parse_float(
            os.getenv("HOTSPOTS_SIGNIFICANT_FRP_MIN"),
            10.0,
        )
        data_dir = os.getenv("DATA_DIR", "data")
        cache_path = os.path.join(data_dir, "hotspots_latest.json")

        return cls(
            enabled=enabled,
            map_key=map_key,
            mode=mode,
            source=source,
            dataset=dataset,
            products=tuple(products),
            include_platforms=tuple(include_platforms),
            include_modis=include_modis,
            bbox=bbox,
            bbox_coords=bbox_coords,
            bbox_raw=bbox_raw,
            bbox_coords_raw=bbox_coords_raw,
            bbox_padding_deg=bbox_padding_deg,
            fetch_bbox=fetch_bbox,
            fetch_bbox_coords=fetch_bbox_coords,
            day_range=day_range,
            cache_ttl_min=cache_ttl_min,
            dedup_km=dedup_km,
            dedup_hours=dedup_hours,
            new_window_hours=new_window_hours,
            significant_confidence_min=significant_confidence_min,
            significant_brightness_min=significant_brightness_min,
            significant_frp_min=significant_frp_min,
            data_dir=data_dir,
            cache_path=cache_path,
        )


__all__ = ["HotspotsConfig", "SUPPORTED_SOURCES"]
