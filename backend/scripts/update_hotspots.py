from __future__ import annotations

import logging
from datetime import datetime, timezone

from app import create_app
from app.models import db
from app.models.hotspots_cache import HotspotsCache
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.firms_provider import fetch_firms_records
from backend.services.hotspots.normalize import normalize_records
from backend.services.hotspots.scoring import apply_status, deduplicate_items
from backend.services.hotspots.storage import is_cache_valid, unavailable_payload


def _load_previous_cache() -> dict | None:
    record = HotspotsCache.query.filter_by(key="etna_latest").one_or_none()
    if record is None:
        return None
    return record.payload


def _upsert_cache(payload: dict, generated_at: datetime) -> None:
    record = HotspotsCache.query.filter_by(key="etna_latest").one_or_none()
    count = int(payload.get("count", 0))
    if record is None:
        record = HotspotsCache(
            key="etna_latest",
            generated_at=generated_at,
            count=count,
            payload=payload,
        )
        db.session.add(record)
    else:
        record.generated_at = generated_at
        record.count = count
        record.payload = payload
    db.session.commit()


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

    app = create_app()
    with app.app_context():
        previous_cache = _load_previous_cache()
        previous_items = previous_cache.get("items", []) if previous_cache else []

        try:
            raw_records = fetch_firms_records(config, logger)
            normalized = normalize_records(raw_records, config)
            deduped = deduplicate_items(normalized, config.dedup_km, config.dedup_hours)
            scored = apply_status(
                deduped,
                previous_items,
                config.dedup_km,
                config.new_window_hours,
            )
            generated_at_dt = datetime.now(timezone.utc)
            payload = {
                "available": True,
                "generated_at": generated_at_dt.isoformat().replace("+00:00", "Z"),
                "source": {
                    "provider": "NASA_FIRMS",
                    "dataset": config.source,
                    "bbox": config.bbox,
                    "day_range": config.day_range,
                },
                "count": len(scored),
                "items": scored,
            }
            _upsert_cache(payload, generated_at_dt)
            logger.info("[HOTSPOTS] Cache updated with %s items.", len(scored))
            return 0
        except Exception as exc:
            error_label = exc.__class__.__name__
            if previous_cache and is_cache_valid(previous_cache, config.cache_ttl_min):
                logger.warning(
                    "[HOTSPOTS] FIRMS unavailable, using cached data (%s).",
                    error_label,
                )
                return 0

            generated_at_dt = datetime.now(timezone.utc)
            payload = unavailable_payload("Dati non disponibili")
            payload["generated_at"] = generated_at_dt.isoformat().replace("+00:00", "Z")
            payload["source"] = {
                "provider": "NASA_FIRMS",
                "dataset": config.source,
                "bbox": config.bbox,
                "day_range": config.day_range,
            }
            payload["count"] = 0
            payload["items"] = []
            _upsert_cache(payload, generated_at_dt)
            logger.error(
                "[HOTSPOTS] Update failed and no valid cache is available (%s).",
                error_label,
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
