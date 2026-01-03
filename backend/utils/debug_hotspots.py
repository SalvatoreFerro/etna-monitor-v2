from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.scripts.update_hotspots import HotspotRecord, HotspotsCache, _build_engine
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.significance import is_significant_record


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("hotspots.debug")

    config = HotspotsConfig.from_env()
    engine = _build_engine()
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    west, south, east, north = config.bbox_coords

    with Session(engine) as session:
        cache = session.execute(
            select(HotspotsCache).where(HotspotsCache.key == "etna_latest")
        ).scalar_one_or_none()
        payload = cache.payload if cache and isinstance(cache.payload, dict) else {}
        logger.info(
            "[HOTSPOTS] cache last_fetch_at=%s last_fetch_count=%s count_significant=%s bbox=%s (raw=%s, pad=%.3f)",
            payload.get("last_fetch_at"),
            payload.get("last_fetch_count"),
            payload.get("count_significant"),
            config.bbox,
            config.bbox_raw,
            config.bbox_padding_deg,
        )

        total_24h = session.execute(
            select(HotspotRecord).where(HotspotRecord.acq_datetime >= window_start)
        ).scalars()
        total_records = list(total_24h)
        logger.info("[HOTSPOTS] records in 24h window: %s", len(total_records))

        geo_records = session.execute(
            select(HotspotRecord).where(
                and_(
                    HotspotRecord.acq_datetime >= window_start,
                    HotspotRecord.lon >= west,
                    HotspotRecord.lon <= east,
                    HotspotRecord.lat >= south,
                    HotspotRecord.lat <= north,
                )
            )
        ).scalars()
        geo_records_list = list(geo_records)
        logger.info("[HOTSPOTS] records in bbox: %s", len(geo_records_list))

        significant_records = [
            record for record in geo_records_list if is_significant_record(record, config)
        ]
        logger.info(
            "[HOTSPOTS] significant records (confidence>=%s, brightness>=%s, frp>=%s): %s",
            config.significant_confidence_min,
            config.significant_brightness_min,
            config.significant_frp_min,
            len(significant_records),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
