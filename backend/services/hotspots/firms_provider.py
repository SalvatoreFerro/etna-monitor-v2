from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from typing import Any

import requests

from .config import HotspotsConfig


def _mask_key(key: str) -> str:
    if len(key) <= 6:
        return "***"
    return f"{key[:3]}***{key[-3:]}"


def build_firms_url(
    config: HotspotsConfig,
    *,
    source: str | None = None,
    bbox: str | None = None,
) -> str:
    if not config.map_key:
        raise ValueError("Missing FIRMS_MAP_KEY")
    final_source = source or config.source
    final_bbox = bbox or config.bbox
    return (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{config.map_key}/{final_source}/{final_bbox}/{config.day_range}"
    )


def build_firms_url_public(
    config: HotspotsConfig,
    *,
    source: str | None = None,
    bbox: str | None = None,
) -> str:
    if not config.map_key:
        raise ValueError("Missing FIRMS_MAP_KEY")
    final_source = source or config.source
    final_bbox = bbox or config.bbox
    return (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"REDACTED/{final_source}/{final_bbox}/{config.day_range}"
    )


@dataclass(frozen=True)
class FirmsFetchResult:
    source: str
    url_public: str
    status_code: int
    body_preview: str
    records: list[dict[str, Any]]


def fetch_firms_records(
    config: HotspotsConfig,
    logger: logging.Logger,
    *,
    source: str | None = None,
    bbox: str | None = None,
) -> FirmsFetchResult:
    final_source = source or config.source
    final_bbox = bbox or config.bbox
    url = build_firms_url(config, source=final_source, bbox=final_bbox)
    masked_key = _mask_key(config.map_key or "")
    logger.info(
        "[HOTSPOTS] Fetching FIRMS data (dataset=%s, bbox=%s, day_range=%s, key=%s)",
        final_source,
        final_bbox,
        config.day_range,
        masked_key,
    )
    response = requests.get(url, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        body_preview = response.text[:500] if response.text else ""
        logger.warning(
            "[HOTSPOTS] FIRMS request failed status=%s body=%s",
            response.status_code,
            body_preview,
        )
        raise

    text = response.content.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        body_preview = text[:500]
        logger.info(
            "[HOTSPOTS] FIRMS response empty status=%s body=%s",
            response.status_code,
            body_preview,
        )
        return FirmsFetchResult(
            source=final_source,
            url_public=build_firms_url_public(config, source=final_source, bbox=final_bbox),
            status_code=response.status_code,
            body_preview=body_preview,
            records=[],
        )

    reader = csv.DictReader(lines)
    records: list[dict[str, Any]] = []
    for row in reader:
        if not row:
            continue
        cleaned: dict[str, Any] = {}
        has_value = False
        for key, value in row.items():
            if key is None:
                continue
            cleaned_key = str(key).strip()
            if value is None:
                cleaned_value = ""
            else:
                cleaned_value = str(value).strip()
            if cleaned_value:
                has_value = True
            cleaned[cleaned_key] = cleaned_value
        if has_value:
            records.append(cleaned)
    return FirmsFetchResult(
        source=final_source,
        url_public=build_firms_url_public(config, source=final_source, bbox=final_bbox),
        status_code=response.status_code,
        body_preview=text[:500],
        records=records,
    )


__all__ = ["fetch_firms_records", "build_firms_url", "build_firms_url_public", "FirmsFetchResult"]
