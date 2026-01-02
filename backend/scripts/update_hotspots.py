from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.firms_provider import fetch_firms_records
from backend.services.hotspots.normalize import normalize_records
from backend.services.hotspots.scoring import apply_status, deduplicate_items
from backend.services.hotspots.storage import (
    is_cache_valid,
    read_cache,
    unavailable_payload,
    write_cache,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("hotspots")

    config = HotspotsConfig.from_env()
    if not config.enabled:
        logger.info("[HOTSPOTS] HOTSPOTS_ENABLED=false, skipping.")
        return 0

    if not config.map_key:
        logger.warning("[HOTSPOTS] FIRMS_MAP_KEY missing, skipping update.")
        return 0

    previous_cache = read_cache(config.cache_path)
    previous_items = previous_cache.get("items", []) if previous_cache else []

    try:
        raw_records = fetch_firms_records(config, logger)
        normalized = normalize_records(raw_records, config)
        deduped = deduplicate_items(normalized, config.dedup_km, config.dedup_hours)
        scored = apply_status(deduped, previous_items, config.dedup_km, config.new_window_hours)
        payload = {
            "available": True,
            "generated_at": _iso_now(),
            "source": {
                "provider": "NASA_FIRMS",
                "dataset": config.source,
                "bbox": config.bbox,
                "day_range": config.day_range,
            },
            "count": len(scored),
            "items": scored,
        }
        write_cache(config.cache_path, payload)
        logger.info("[HOTSPOTS] Cache updated with %s items.", len(scored))
        return 0
    except Exception as exc:
        error_label = exc.__class__.__name__
        if previous_cache and is_cache_valid(previous_cache, config.cache_ttl_min):
            logger.warning("[HOTSPOTS] FIRMS unavailable, using cached data (%s).", error_label)
            return 0

        payload = unavailable_payload("Dati non disponibili")
        payload["generated_at"] = _iso_now()
        payload["source"] = {
            "provider": "NASA_FIRMS",
            "dataset": config.source,
            "bbox": config.bbox,
            "day_range": config.day_range,
        }
        payload["count"] = 0
        payload["items"] = []
        write_cache(config.cache_path, payload)
        logger.error("[HOTSPOTS] Update failed and no valid cache is available (%s).", error_label)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
