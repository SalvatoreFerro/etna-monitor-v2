"""Helpers for Copernicus Sentinel-2 metadata."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, url_for

from app.models.copernicus_image import CopernicusImage

ETNA_BBOX_EPSG4326 = [14.85, 37.65, 15.15, 37.88]


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
    """Return a stable EPSG:4326 bbox for the Etna observatory view."""
    _ = record
    return [float(value) for value in ETNA_BBOX_EPSG4326]
