from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.firms_provider import fetch_firms_records
from backend.services.hotspots.normalize import normalize_records
from backend.services.hotspots.scoring import apply_status, deduplicate_items
from backend.services.hotspots.storage import is_cache_valid


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


class HotspotRecord(Base):
    __tablename__ = "hotspots_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    satellite: Mapped[str] = mapped_column(String(16), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    acq_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16))
    brightness: Mapped[float | None] = mapped_column(Float)
    frp: Mapped[float | None] = mapped_column(Float)
    intensity_unit: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def _parse_time_utc(value: str | None) -> datetime | None:
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


def _records_from_items(items: list[dict], source: str) -> list[dict]:
    records: list[dict] = []
    for item in items:
        fingerprint = item.get("id")
        if not fingerprint:
            continue
        acq_time = _parse_time_utc(item.get("time_utc"))
        if acq_time is None:
            continue
        intensity = item.get("intensity") or {}
        records.append(
            {
                "fingerprint": fingerprint,
                "source": source,
                "satellite": item.get("satellite") or "UNKNOWN",
                "lat": float(item.get("lat")),
                "lon": float(item.get("lon")),
                "acq_datetime": acq_time,
                "confidence": item.get("confidence"),
                "brightness": intensity.get("brightness"),
                "frp": intensity.get("frp"),
                "intensity_unit": intensity.get("unit"),
                "status": item.get("status"),
            }
        )
    return records


def _insert_records(session: Session, engine: Engine, records: list[dict]) -> int:
    if not records:
        return 0

    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(HotspotRecord).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["fingerprint"])
        result = session.execute(stmt)
        return result.rowcount or 0

    if engine.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        stmt = sqlite_insert(HotspotRecord).values(records)
        stmt = stmt.on_conflict_do_nothing(index_elements=["fingerprint"])
        result = session.execute(stmt)
        return result.rowcount or 0

    inserted = 0
    for record in records:
        try:
            with session.begin_nested():
                session.add(HotspotRecord(**record))
            inserted += 1
        except IntegrityError:
            continue
    return inserted


def _cleanup_records(session: Session, cutoff: datetime) -> int:
    result = session.execute(
        delete(HotspotRecord).where(HotspotRecord.acq_datetime < cutoff)
    )
    return result.rowcount or 0


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
        logger.warning(
            "[HOTSPOTS] FIRMS_API_KEY/FIRMS_MAP_KEY missing, skipping update."
        )
        return 0

    engine = _build_engine()
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    session = SessionLocal()
    try:
        previous_cache = _load_previous_cache(session)
        previous_items = previous_cache.get("items", []) if previous_cache else []
        last_nonzero_at = previous_cache.get("last_nonzero_at") if previous_cache else None

        try:
            raw_records = fetch_firms_records(config, logger)
            raw_count = len(raw_records)
            normalized = normalize_records(raw_records, config)
            deduped = deduplicate_items(normalized, config.dedup_km, config.dedup_hours)
            scored = apply_status(
                deduped,
                previous_items,
                config.dedup_km,
                config.new_window_hours,
            )
            generated_at_dt = datetime.now(timezone.utc)
            filtered_count = len(scored)
            if filtered_count > 0:
                last_nonzero_at = generated_at_dt.isoformat().replace("+00:00", "Z")
            records = _records_from_items(scored, config.source)
            inserted_count = _insert_records(session, engine, records)
            cleanup_cutoff = generated_at_dt - timedelta(hours=48)
            _cleanup_records(session, cleanup_cutoff)
            payload = {
                "available": True,
                "generated_at": generated_at_dt.isoformat().replace("+00:00", "Z"),
                "last_fetch_at": generated_at_dt.isoformat().replace("+00:00", "Z"),
                "last_fetch_count": filtered_count,
                "last_nonzero_at": last_nonzero_at,
                "source": {
                    "provider": "NASA_FIRMS",
                    "dataset": config.source,
                    "bbox": config.bbox,
                    "day_range": config.day_range,
                },
                "count": filtered_count,
                "items": scored,
            }
            _upsert_cache(session, payload, generated_at_dt)
            session.commit()
            logger.info(
                "[HOTSPOTS] FIRMS fetch bbox=%s source=%s raw_count=%s filtered_count=%s inserted_count=%s last_fetch_at=%s",
                config.bbox,
                config.source,
                raw_count,
                filtered_count,
                inserted_count,
                generated_at_dt.isoformat().replace("+00:00", "Z"),
            )
            return 0
        except Exception as exc:
            session.rollback()
            error_label = exc.__class__.__name__
            if previous_cache and is_cache_valid(previous_cache, config.cache_ttl_min):
                logger.warning(
                    "[HOTSPOTS] FIRMS unavailable, keeping cached data (%s).",
                    error_label,
                )
                return 0

            logger.error(
                "[HOTSPOTS] Update failed, leaving existing data untouched (%s).",
                error_label,
            )
            return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
