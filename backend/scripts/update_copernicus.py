from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from sqlalchemy import DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.services.copernicus_preview import (
    extract_copernicus_assets,
    fetch_latest_copernicus_item,
    select_preview_asset,
)

DEFAULT_SOURCE = "Copernicus Sentinel-2 / CDSE"
DEFAULT_DAYS_LOOKBACK = 5
DEFAULT_BBOX_DELTA_DEG = 0.06
REQUEST_TIMEOUT = (8, 35)
RETRY_DELAYS = [1.0, 2.5]
ETNA_CENTER = (37.751, 14.993)


class Base(DeclarativeBase):
    pass


def _json_type():
    from sqlalchemy import JSON

    return JSON().with_variant(JSONB, "postgresql")


class CopernicusImage(Base):
    __tablename__ = "copernicus_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    cloud_cover: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[dict | list | None] = mapped_column(_json_type())
    image_path: Mapped[str | None] = mapped_column(String(256))
    preview_path: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


@dataclass(frozen=True)
class StacItem:
    product_id: str
    acquired_at: datetime
    cloud_cover: float | None
    bbox: list[float]


@dataclass(frozen=True)
class CopernicusConfig:
    bbox: list[float]
    days_lookback: int


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
        raise RuntimeError("DATABASE_URL is required for Copernicus updates.")
    url = _normalize_database_url(raw_url)
    return create_engine(url, pool_pre_ping=True)


def _parse_dt(value: str | None) -> datetime | None:
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


def _request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    logger: logging.Logger,
    **kwargs,
) -> requests.Response:
    for attempt, delay in enumerate([0.0] + RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            if attempt > len(RETRY_DELAYS):
                logger.error("Copernicus request failed: %s", exc)
                raise
            logger.warning("Copernicus request failed (attempt %s), retrying...", attempt)
    raise RuntimeError("Unreachable")


def _load_config() -> CopernicusConfig:
    bbox = _resolve_bbox()

    days_lookback = int(os.getenv("CDSE_DAYS_LOOKBACK", str(DEFAULT_DAYS_LOOKBACK)))

    return CopernicusConfig(
        bbox=bbox,
        days_lookback=days_lookback,
    )


def _resolve_bbox() -> list[float]:
    bbox_km = os.getenv("CDSE_BBOX_KM")
    bbox_delta = os.getenv("CDSE_BBOX_DELTA_DEG")

    lat_center, lon_center = ETNA_CENTER
    if bbox_km:
        try:
            km_value = float(bbox_km)
        except ValueError:
            km_value = DEFAULT_BBOX_DELTA_DEG * 111
        lat_delta = km_value / 111
        lon_delta = km_value / (111 * max(0.1, abs(math.cos(math.radians(lat_center)))))
    else:
        try:
            delta_deg = float(bbox_delta) if bbox_delta else DEFAULT_BBOX_DELTA_DEG
        except ValueError:
            delta_deg = DEFAULT_BBOX_DELTA_DEG
        lat_delta = delta_deg
        lon_delta = delta_deg

    return [
        lon_center - lon_delta,
        lat_center - lat_delta,
        lon_center + lon_delta,
        lat_center + lat_delta,
    ]


def _parse_stac_item(item: dict, fallback_bbox: list[float]) -> StacItem | None:
    props = item.get("properties") or {}
    acquired_at = _parse_dt(props.get("datetime"))
    product_id = item.get("id")
    if not acquired_at or not product_id:
        return None
    cloud_cover = props.get("eo:cloud_cover")
    if cloud_cover is not None:
        try:
            cloud_cover = float(cloud_cover)
        except (TypeError, ValueError):
            cloud_cover = None
    bbox = item.get("bbox") or fallback_bbox
    if not isinstance(bbox, list) or len(bbox) != 4:
        bbox = fallback_bbox
    return StacItem(
        product_id=str(product_id),
        acquired_at=acquired_at,
        cloud_cover=cloud_cover,
        bbox=list(bbox),
    )


def _download_asset(
    href: str,
    session: requests.Session,
    logger: logging.Logger,
) -> bytes:
    response = _request_with_retry(session, "GET", href, logger)
    return response.content


def _write_image(content: bytes, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_bytes(content)
    temp_path.replace(target_path)


def _static_image_paths(acquired_at: datetime) -> tuple[Path, Path]:
    base_dir = Path(__file__).resolve().parents[2]
    folder = base_dir / "app" / "static" / "copernicus"
    latest_path = folder / "latest.png"
    dated_path = folder / f"{acquired_at:%Y%m%d}.png"
    return latest_path, dated_path


def _latest_record(session: Session) -> CopernicusImage | None:
    return session.execute(
        select(CopernicusImage).order_by(CopernicusImage.acquired_at.desc())
    ).scalar_one_or_none()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("copernicus")

    try:
        config = _load_config()
    except RuntimeError as exc:
        logger.error(str(exc))
        return 2

    logger.info("Copernicus bbox used: %s", config.bbox)

    session = requests.Session()
    item_payload = fetch_latest_copernicus_item(
        config.bbox,
        logger,
        days_lookback=config.days_lookback,
    )
    if not item_payload:
        logger.warning("Copernicus: nessuna acquisizione disponibile")
        return 0

    item = _parse_stac_item(item_payload, config.bbox)
    if item is None:
        logger.error("Copernicus: item STAC non valido")
        return 1

    logger.info(
        "Copernicus: selezionato prodotto %s (cloud cover: %s)",
        item.product_id,
        f"{item.cloud_cover:.1f}%" if item.cloud_cover is not None else "n/a",
    )

    engine = _build_engine()
    session_factory = sessionmaker(bind=engine)

    assets = extract_copernicus_assets(item_payload)
    preview_asset = select_preview_asset(assets)

    preview_path: str | None = None
    status = "NO_ASSET"
    if preview_asset is None:
        logger.warning("Copernicus: nessun asset immagine disponibile (%s)", item.product_id)
    else:
        logger.info("Copernicus: preview asset selezionato=%s", preview_asset.key)
        try:
            image_content = _download_asset(preview_asset.href, session, logger)
        except Exception:
            logger.exception("Copernicus preview download failed")
            status = "ERROR"
        else:
            if not image_content or len(image_content) < 100:
                logger.error("Copernicus: immagine vuota o non valida")
                status = "ERROR"
            else:
                latest_path, dated_path = _static_image_paths(item.acquired_at)
                _write_image(image_content, latest_path)
                _write_image(image_content, dated_path)
                preview_path = str(Path("copernicus") / latest_path.name)
                status = "AVAILABLE"

    with session_factory() as db_session:
        existing = _latest_record(db_session)
        if (
            existing
            and existing.product_id == item.product_id
            and existing.status == "AVAILABLE"
            and status == "AVAILABLE"
        ):
            logger.info("Copernicus: nessun aggiornamento (%s)", item.product_id)
            return 0

        target = None
        if existing and existing.product_id == item.product_id:
            target = existing
        else:
            target = CopernicusImage()
            db_session.add(target)

        target.acquired_at = item.acquired_at
        target.source = DEFAULT_SOURCE
        target.product_id = item.product_id
        target.cloud_cover = item.cloud_cover
        target.bbox = item.bbox
        target.image_path = preview_path
        target.preview_path = preview_path
        target.status = status
        target.created_at = datetime.now(timezone.utc)
        db_session.commit()

    logger.info("Copernicus: status=%s preview_path=%s", status, preview_path)
    logger.info(
        "Copernicus: record aggiornato (%s, %s)",
        item.acquired_at.isoformat(),
        item.product_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
