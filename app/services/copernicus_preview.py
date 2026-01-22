"""Copernicus Sentinel-2 preview helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_DAYS_LOOKBACK = 7
REQUEST_TIMEOUT = (6, 25)
ASSET_PRIORITY = ("thumbnail", "quicklook", "visual")


@dataclass(frozen=True)
class StacAsset:
    key: str
    href: str
    media_type: str | None
    roles: list[str]


def fetch_latest_copernicus_item(
    bbox: list[float],
    logger,
    *,
    days_lookback: int = DEFAULT_DAYS_LOOKBACK,
) -> dict | None:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_lookback)
    payload = {
        "collections": [DEFAULT_COLLECTION],
        "bbox": bbox,
        "datetime": f"{start.isoformat()}/{now.isoformat()}",
        "limit": 1,
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
        return None

    features = data.get("features") or []
    if not features:
        return None
    return features[0]


def extract_copernicus_assets(item: dict) -> list[StacAsset]:
    assets = item.get("assets") or {}
    extracted: list[StacAsset] = []
    for key, payload in assets.items():
        if not isinstance(payload, dict):
            continue
        href = payload.get("href")
        if not href:
            continue
        media_type = payload.get("type")
        roles = payload.get("roles") or []
        extracted.append(
            StacAsset(
                key=str(key),
                href=str(href),
                media_type=str(media_type) if media_type else None,
                roles=[str(role) for role in roles],
            )
        )
    return extracted


def select_preview_asset(assets: list[StacAsset]) -> StacAsset | None:
    if not assets:
        return None
    by_key = {asset.key: asset for asset in assets}
    for key in ASSET_PRIORITY:
        if key in by_key:
            return by_key[key]
    return assets[0]
