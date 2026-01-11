from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from sqlalchemy import DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.services.hotspots.config import HotspotsConfig

STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
DEFAULT_COLLECTION = "sentinel-2-l2a"
DEFAULT_SOURCE = "Copernicus Sentinel-2 / CDSE"
DEFAULT_DAYS_LOOKBACK = 5
DEFAULT_MAX_CLOUD = 80
OUTPUT_WIDTH = 1024
OUTPUT_MIN_HEIGHT = 256
OUTPUT_MAX_HEIGHT = 1024
REQUEST_TIMEOUT = (8, 35)
RETRY_DELAYS = [1.0, 2.5]


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
    client_id: str
    client_secret: str
    bbox: list[float]
    days_lookback: int
    max_cloud: int


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
    client_id = os.getenv("CDSE_CLIENT_ID")
    client_secret = os.getenv("CDSE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("CDSE_CLIENT_ID and CDSE_CLIENT_SECRET are required.")

    hotspots_config = HotspotsConfig.from_env()
    bbox = list(hotspots_config.bbox_coords)

    days_lookback = int(os.getenv("CDSE_DAYS_LOOKBACK", str(DEFAULT_DAYS_LOOKBACK)))
    max_cloud = int(os.getenv("CDSE_MAX_CLOUD", str(DEFAULT_MAX_CLOUD)))

    return CopernicusConfig(
        client_id=client_id,
        client_secret=client_secret,
        bbox=bbox,
        days_lookback=days_lookback,
        max_cloud=max_cloud,
    )


def _fetch_stac_items(config: CopernicusConfig, session: requests.Session, logger: logging.Logger) -> list[StacItem]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=config.days_lookback)
    payload = {
        "collections": [DEFAULT_COLLECTION],
        "bbox": config.bbox,
        "datetime": f"{start.isoformat()}/{now.isoformat()}",
        "limit": 25,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }

    response = _request_with_retry(session, "POST", STAC_URL, logger, json=payload)
    data = response.json()
    features = data.get("features") or []
    items: list[StacItem] = []
    for feature in features:
        props = feature.get("properties") or {}
        acquired_at = _parse_dt(props.get("datetime"))
        product_id = feature.get("id")
        if not acquired_at or not product_id:
            continue
        cloud_cover = props.get("eo:cloud_cover")
        if cloud_cover is not None:
            try:
                cloud_cover = float(cloud_cover)
            except (TypeError, ValueError):
                cloud_cover = None
        bbox = feature.get("bbox") or config.bbox
        items.append(
            StacItem(
                product_id=str(product_id),
                acquired_at=acquired_at,
                cloud_cover=cloud_cover,
                bbox=list(bbox),
            )
        )
    return items


def _select_best_item(items: list[StacItem]) -> StacItem | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            -item.acquired_at.timestamp(),
            item.cloud_cover if item.cloud_cover is not None else float("inf"),
        ),
    )[0]


def _fetch_access_token(config: CopernicusConfig, session: requests.Session, logger: logging.Logger) -> str:
    payload = {
        "grant_type": "client_credentials",
        "client_id": config.client_id,
        "client_secret": config.client_secret,
    }
    response = _request_with_retry(session, "POST", TOKEN_URL, logger, data=payload)
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("CDSE token response missing access_token")
    return str(token)


def _compute_output_height(bbox: list[float]) -> int:
    west, south, east, north = bbox
    width_deg = max(east - west, 0.0001)
    height_deg = max(north - south, 0.0001)
    ratio = height_deg / width_deg
    height = int(round(OUTPUT_WIDTH * ratio))
    return max(OUTPUT_MIN_HEIGHT, min(OUTPUT_MAX_HEIGHT, height))


def _build_evalscript() -> str:
    return """//VERSION=3
function setup() {
  return {
    input: ["B04", "B03", "B02"],
    output: { bands: 3 }
  };
}

function evaluatePixel(sample) {
  return [sample.B04, sample.B03, sample.B02];
}
"""


def _download_image(
    item: StacItem,
    config: CopernicusConfig,
    session: requests.Session,
    logger: logging.Logger,
) -> bytes:
    time_from = (item.acquired_at - timedelta(hours=2)).isoformat()
    time_to = (item.acquired_at + timedelta(hours=2)).isoformat()
    payload = {
        "input": {
            "bounds": {
                "bbox": item.bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [
                {
                    "type": DEFAULT_COLLECTION,
                    "dataFilter": {
                        "timeRange": {"from": time_from, "to": time_to},
                        "maxCloudCoverage": config.max_cloud,
                        "mosaickingOrder": "mostRecent",
                    },
                }
            ],
        },
        "output": {
            "width": OUTPUT_WIDTH,
            "height": _compute_output_height(item.bbox),
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": _build_evalscript(),
    }

    token = _fetch_access_token(config, session, logger)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = _request_with_retry(
        session,
        "POST",
        PROCESS_URL,
        logger,
        data=json.dumps(payload),
        headers=headers,
    )
    return response.content


def _write_image(content: bytes, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_bytes(content)
    temp_path.replace(target_path)


def _static_image_path() -> Path:
    base_dir = Path(__file__).resolve().parents[2]
    return base_dir / "app" / "static" / "copernicus" / "last.png"


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

    session = requests.Session()
    try:
        items = _fetch_stac_items(config, session, logger)
    except Exception:
        logger.exception("Copernicus STAC query failed")
        return 1

    item = _select_best_item(items)
    if item is None:
        logger.warning("Copernicus: nessuna acquisizione disponibile")
        return 0

    engine = _build_engine()
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db_session:
        existing = _latest_record(db_session)
        if existing and existing.product_id == item.product_id:
            logger.info("Copernicus: nessun aggiornamento (%s)", item.product_id)
            return 0

    try:
        image_content = _download_image(item, config, session, logger)
    except Exception:
        logger.exception("Copernicus Process API failed")
        return 1

    if not image_content or len(image_content) < 100:
        logger.error("Copernicus: immagine vuota o non valida")
        return 1

    image_path = _static_image_path()
    _write_image(image_content, image_path)

    relative_path = str(Path("copernicus") / image_path.name)

    with session_factory() as db_session:
        record = CopernicusImage(
            acquired_at=item.acquired_at,
            source=DEFAULT_SOURCE,
            product_id=item.product_id,
            cloud_cover=item.cloud_cover,
            bbox=item.bbox,
            image_path=relative_path,
        )
        db_session.add(record)
        db_session.commit()

    logger.info(
        "Copernicus: immagine aggiornata (%s, %s)",
        item.acquired_at.isoformat(),
        item.product_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
