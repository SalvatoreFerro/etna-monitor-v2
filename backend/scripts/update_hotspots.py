from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.firms_provider import fetch_firms_records
from backend.services.hotspots.normalize import normalize_records
from backend.services.hotspots.scoring import apply_status, deduplicate_items
from backend.services.hotspots.storage import is_cache_valid, unavailable_payload


def _json_type() -> JSON:
    return JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class HotspotsCache(Base):
    __tablename__ = "hotspots_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(_json_type(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def _load_previous_cache(session: Session) -> dict | None:
    record = session.execute(
        select(HotspotsCache).where(HotspotsCache.key == "etna_latest")
    ).scalar_one_or_none()
    if record is None:
        return None
    return record.payload


def _upsert_cache(session: Session, payload: dict, generated_at: datetime) -> None:
    record = session.execute(
        select(HotspotsCache).where(HotspotsCache.key == "etna_latest")
    ).scalar_one_or_none()
    count = int(payload.get("count", 0))
    if record is None:
        record = HotspotsCache(
            key="etna_latest",
            generated_at=generated_at,
            count=count,
            payload=payload,
        )
        session.add(record)
    else:
        record.generated_at = generated_at
        record.count = count
        record.payload = payload


def _normalize_database_url(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+psycopg")
    if url.drivername.startswith("postgresql+psycopg2"):
        return url.set(drivername="postgresql+psycopg")
    return url


def _build_engine() -> Engine:
    raw_url = os.getenv("DATABASE_URL")
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required for hotspots cache updates.")
    url = _normalize_database_url(raw_url)
    return create_engine(url, pool_pre_ping=True)


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

    engine = _build_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    session = SessionLocal()
    try:
        previous_cache = _load_previous_cache(session)
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
            _upsert_cache(session, payload, generated_at_dt)
            session.commit()
            logger.info("[HOTSPOTS] Cache updated with %s items.", len(scored))
            return 0
        except Exception as exc:
            session.rollback()
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
            _upsert_cache(session, payload, generated_at_dt)
            session.commit()
            logger.error(
                "[HOTSPOTS] Update failed and no valid cache is available (%s).",
                error_label,
            )
            return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
