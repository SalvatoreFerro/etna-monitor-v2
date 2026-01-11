"""Helpers for Copernicus Sentinel-2 metadata."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, url_for

from app.models.copernicus_image import CopernicusImage

DEFAULT_ETNA_CENTER = (37.751, 14.993)
DEFAULT_BBOX_DELTA_DEG = 0.06


def get_latest_copernicus_image() -> CopernicusImage | None:
    return (
        CopernicusImage.query.order_by(CopernicusImage.acquired_at.desc()).first()
    )


def resolve_copernicus_image_url(record: CopernicusImage | None) -> str | None:
    if record is None or not record.image_path:
        return None
    static_folder = current_app.static_folder or ""
    image_path = Path(static_folder) / record.image_path
    if not image_path.exists():
        return None
    return url_for("static", filename=record.image_path)


def resolve_copernicus_bbox(record: CopernicusImage | None) -> list[float]:
    bbox = record.bbox if record else None
    if isinstance(bbox, dict):
        if all(key in bbox for key in ("west", "south", "east", "north")):
            return [
                float(bbox["west"]),
                float(bbox["south"]),
                float(bbox["east"]),
                float(bbox["north"]),
            ]
        if isinstance(bbox.get("bbox"), (list, tuple)) and len(bbox["bbox"]) == 4:
            return [float(value) for value in bbox["bbox"]]
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return [float(value) for value in bbox]
    lat_center, lon_center = DEFAULT_ETNA_CENTER
    return [
        lon_center - DEFAULT_BBOX_DELTA_DEG,
        lat_center - DEFAULT_BBOX_DELTA_DEG,
        lon_center + DEFAULT_BBOX_DELTA_DEG,
        lat_center + DEFAULT_BBOX_DELTA_DEG,
    ]
