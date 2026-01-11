"""Helpers for Copernicus Sentinel-2 metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from flask import current_app, url_for

from app.models.copernicus_image import CopernicusImage

ETNA_BBOX_EPSG4326 = [14.85, 37.65, 15.15, 37.88]
STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_DAYS_LOOKBACK = 7
STAC_LIMIT = 30
REQUEST_TIMEOUT = (6, 25)
AVAILABLE_STATUSES = {"AVAILABLE", "READY"}


@dataclass(frozen=True)
class StacItem:
    product_id: str
    acquired_at: datetime
    status: str | None
    cloud_cover: float | None
    bbox: list[float]


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


def is_available_status(status: str | None) -> bool:
    if not status:
        return False
    return status.upper() in AVAILABLE_STATUSES


def fetch_latest_copernicus_items(
    bbox: list[float],
    logger,
    *,
    days_lookback: int = DEFAULT_DAYS_LOOKBACK,
) -> list[StacItem]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_lookback)
    payload = {
        "collections": [DEFAULT_COLLECTION],
        "bbox": bbox,
        "datetime": f"{start.isoformat()}/{now.isoformat()}",
        "limit": STAC_LIMIT,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    try:
        response = requests.post(
            STAC_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        logger.exception("[Copernicus] STAC search failed")
        return []

    items: list[StacItem] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        acquired_at = _parse_datetime(props.get("datetime"))
        product_id = feature.get("id")
        if not acquired_at or not product_id:
            continue
        status = _extract_status(props)
        cloud_cover = _parse_cloud_cover(props.get("eo:cloud_cover"))
        items.append(
            StacItem(
                product_id=str(product_id),
                acquired_at=acquired_at,
                status=status,
                cloud_cover=cloud_cover,
                bbox=list(bbox),
            )
        )
    return items


def resolve_latest_and_available_items(
    items: list[StacItem],
) -> tuple[StacItem | None, StacItem | None]:
    if not items:
        return None, None
    ordered = sorted(items, key=lambda item: item.acquired_at, reverse=True)
    latest = ordered[0]
    available = next(
        (item for item in ordered if is_available_status(item.status)),
        None,
    )
    return latest, available


def _parse_datetime(value: str | None) -> datetime | None:
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


def _parse_cloud_cover(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_status(props: dict) -> str | None:
    for key in ("status", "processing:status", "sci:status"):
        value = props.get(key)
        if value:
            return str(value)
    return None
