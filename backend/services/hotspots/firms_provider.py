from __future__ import annotations

import csv
import logging
from typing import Any

import requests

from .config import HotspotsConfig


def _mask_key(key: str) -> str:
    if len(key) <= 6:
        return "***"
    return f"{key[:3]}***{key[-3:]}"


def build_firms_url(config: HotspotsConfig) -> str:
    if not config.map_key:
        raise ValueError("Missing FIRMS_MAP_KEY")
    return (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{config.map_key}/{config.source}/{config.bbox}/{config.day_range}"
    )


def fetch_firms_records(config: HotspotsConfig, logger: logging.Logger) -> list[dict[str, Any]]:
    url = build_firms_url(config)
    masked_key = _mask_key(config.map_key or "")
    logger.info(
        "[HOTSPOTS] Fetching FIRMS data (dataset=%s, bbox=%s, day_range=%s, key=%s)",
        config.source,
        config.bbox,
        config.day_range,
        masked_key,
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    text = response.content.decode("utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

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
    return records


__all__ = ["fetch_firms_records", "build_firms_url"]
