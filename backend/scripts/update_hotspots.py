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
from backend.services.hotspots.firms_provider import FirmsFetchResult, fetch_firms_records
from backend.services.hotspots.normalize import normalize_records
from backend.services.hotspots.scoring import apply_status, deduplicate_items
from backend.services.hotspots.significance import is_significant_item
from backend.services.hotspots.storage import is_cache_valid
from backend.services.hotspots.sources import build_sources


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
    instrument: Mapped[str | None] = mapped_column(String(16))
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    acq_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16))
    brightness: Mapped[float | None] = mapped_column(Float)
    bright_ti4: Mapped[float | None] = mapped_column(Float)
    bright_ti5: Mapped[float | None] = mapped_column(Float)
    frp: Mapped[float | None] = mapped_column(Float)
    intensity_unit: Mapped[str | None] = mapped_column(String(8))
    daynight: Mapped[str | None] = mapped_column(String(8))
    version: Mapped[str | None] = mapped_column(String(16))
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


def _records_from_items(
    items: list[dict],
    status_by_id: dict[str, str | None] | None = None,
) -> list[dict]:
    records: list[dict] = []
    for item in items:
        fingerprint = item.get("id")
        if not fingerprint:
            continue
        acq_time = _parse_time_utc(item.get("time_utc"))
        if acq_time is None:
            continue
        intensity = item.get("intensity") or {}
        status = None
        if status_by_id is not None:
            status = status_by_id.get(fingerprint)
        records.append(
            {
                "fingerprint": fingerprint,
                "source": item.get("source") or "UNKNOWN",
                "satellite": item.get("satellite") or "UNKNOWN",
                "instrument": item.get("instrument"),
                "lat": float(item.get("lat")),
                "lon": float(item.get("lon")),
                "acq_datetime": acq_time,
                "confidence": item.get("confidence"),
                "brightness": intensity.get("brightness"),
                "bright_ti4": item.get("bright_ti4"),
                "bright_ti5": item.get("bright_ti5"),
                "frp": intensity.get("frp"),
                "intensity_unit": intensity.get("unit"),
                "daynight": item.get("daynight"),
                "version": item.get("version"),
                "status": status or item.get("status"),
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


def _is_in_bbox(
    lat: float,
    lon: float,
    bbox_coords: tuple[float, float, float, float],
) -> bool:
    west, south, east, north = bbox_coords
    return west <= lon <= east and south <= lat <= north


def _filter_geo(items: list[dict], bbox_coords: tuple[float, float, float, float]) -> list[dict]:
    return [
        item
        for item in items
        if item.get("lat") is not None
        and item.get("lon") is not None
        and _is_in_bbox(float(item["lat"]), float(item["lon"]), bbox_coords)
    ]


def _filter_recent(items: list[dict], now_utc: datetime, window_hours: float) -> list[dict]:
    window_start = now_utc - timedelta(hours=window_hours)
    filtered: list[dict] = []
    for item in items:
        acq_time = _parse_time_utc(item.get("time_utc"))
        if acq_time is None:
            continue
        if window_start <= acq_time <= now_utc:
            filtered.append(item)
    return filtered


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


def _log_fetch_summary(
    logger: logging.Logger,
    dataset: str,
    platforms: list[str],
    downloaded: int,
    inserted: int,
) -> None:
    logger.info(
        "FIRMS ingest: dataset=%s platforms=%s downloaded=%s inserted=%s",
        dataset,
        platforms,
        downloaded,
        inserted,
    )


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
            sources, platforms = build_sources(config)
            logger.info(
                "[HOTSPOTS] FIRMS ingest datasets=%s platforms=%s include_modis=%s",
                sources,
                platforms,
                config.include_modis,
            )

            results: list[FirmsFetchResult] = []
            for source in sources:
                results.append(
                    fetch_firms_records(
                        config,
                        logger,
                        source=source,
                        bbox=config.fetch_bbox,
                    )
                )

            raw_count = 0
            for result in results:
                if not result.records:
                    logger.info(
                        "[HOTSPOTS] FIRMS zero records status=%s body=%s dataset=%s platforms=%s url=%s",
                        result.status_code,
                        result.body_preview,
                        config.dataset,
                        platforms,
                        result.url_public,
                    )
                    continue
                logger.info(
                    "[HOTSPOTS] FIRMS request url=%s",
                    result.url_public,
                )
                raw_count += len(result.records)
            normalized: list[dict] = []
            for result in results:
                if not result.records:
                    continue
                normalized.extend(
                    normalize_records(result.records, result.source, config)
                )

            generated_at_dt = datetime.now(timezone.utc)
            recent_filtered = _filter_recent(normalized, generated_at_dt, 24.0)
            geo_filtered = _filter_geo(recent_filtered, config.bbox_coords)
            scored = apply_status(
                geo_filtered,
                previous_items,
                config.dedup_km,
                config.new_window_hours,
            )
            significant_items = [item for item in scored if is_significant_item(item, config)]
            deduped_significant = deduplicate_items(
                significant_items,
                config.dedup_km,
                config.dedup_hours,
            )
            raw_24h_count = len(scored)
            significant_count = len(deduped_significant)
            if raw_24h_count > 0:
                last_nonzero_at = generated_at_dt.isoformat().replace("+00:00", "Z")

            acq_times = [
                _parse_time_utc(item.get("time_utc")) for item in normalized
            ]
            acq_times = [t for t in acq_times if t is not None]
            if acq_times:
                logger.info(
                    "[HOTSPOTS] FIRMS acquisition range min=%s max=%s",
                    min(acq_times).isoformat().replace("+00:00", "Z"),
                    max(acq_times).isoformat().replace("+00:00", "Z"),
                )

            window_start = generated_at_dt - timedelta(hours=24)
            logger.info(
                "[HOTSPOTS] FIRMS window now_utc=%s window_start_utc=%s",
                generated_at_dt.isoformat().replace("+00:00", "Z"),
                window_start.isoformat().replace("+00:00", "Z"),
            )

            status_by_id = {
                item.get("id"): item.get("status")
                for item in scored
                if item.get("id")
            }
            records = _records_from_items(normalized, status_by_id)
            inserted_count = _insert_records(session, engine, records)
            cleanup_cutoff = generated_at_dt - timedelta(hours=48)
            _cleanup_records(session, cleanup_cutoff)
            payload = {
                "available": True,
                "generated_at": generated_at_dt.isoformat().replace("+00:00", "Z"),
                "last_fetch_at": generated_at_dt.isoformat().replace("+00:00", "Z"),
                "last_fetch_count": raw_count,
                "last_nonzero_at": last_nonzero_at,
                "source": {
                    "provider": "NASA_FIRMS",
                    "mode": config.mode,
                    "dataset": config.dataset,
                    "sources": sources,
                    "platforms": platforms,
                    "bbox": config.bbox,
                    "bbox_raw": config.bbox_raw,
                    "bbox_padding_deg": config.bbox_padding_deg,
                    "fetch_bbox": config.fetch_bbox,
                    "day_range": config.day_range,
                    "products": list(config.products),
                },
                "count": raw_24h_count,
                "count_24h_raw": raw_24h_count,
                "count_24h_significant": significant_count,
                "count_significant": significant_count,
                "items": scored,
                "items_24h_raw": scored,
                "items_24h_significant": deduped_significant,
            }
            _upsert_cache(session, payload, generated_at_dt)
            session.commit()
            logger.info(
                "[HOTSPOTS] FIRMS fetch bbox=%s (raw=%s, pad=%.3f, fetch=%s) sources=%s raw_count=%s geo_count=%s all_count=%s significant_count=%s inserted_count=%s",
                config.bbox,
                config.bbox_raw,
                config.bbox_padding_deg,
                config.fetch_bbox,
                sources,
                raw_count,
                len(geo_filtered),
                raw_24h_count,
                significant_count,
                inserted_count,
            )
            _log_fetch_summary(
                logger,
                config.dataset,
                platforms,
                raw_count,
                inserted_count,
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
