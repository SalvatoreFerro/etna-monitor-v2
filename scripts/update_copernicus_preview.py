#!/usr/bin/env python3
"""Generate Copernicus Sentinel-2 previews via Sentinel Hub Process API."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"

DEFAULT_BBOX = [14.85, 37.65, 15.15, 37.88]
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_BEST_DAYS = 7
DEFAULT_LATEST_DAYS = 14
DEFAULT_MAX_CLOUD = 80
REQUEST_TIMEOUT = (8, 60)
RETRY_DELAYS = [1.0, 2.5]
TMP_BASE_DIR = Path("/tmp/etnamonitor")


@dataclass(frozen=True)
class StacItem:
    product_id: str
    acquired_at: datetime
    cloud_cover: float | None
    bbox: list[float]


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    cleaned = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
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


def _fetch_access_token(session: requests.Session, logger: logging.Logger) -> str:
    client_id = (os.getenv("CDSE_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("CDSE_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("CDSE_CLIENT_ID e CDSE_CLIENT_SECRET sono obbligatori.")
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = _request_with_retry(session, "POST", TOKEN_URL, logger, data=payload)
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Token CDSE non disponibile.")
    return str(token)


def _search_stac_items(
    bbox: list[float],
    start: datetime,
    end: datetime,
    logger: logging.Logger,
    *,
    limit: int = 30,
) -> list[dict]:
    payload = {
        "collections": ["sentinel-2-l2a"],
        "bbox": bbox,
        "datetime": f"{_isoformat(start)}/{_isoformat(end)}",
        "limit": limit,
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    response = _request_with_retry(
        requests.Session(),
        "POST",
        STAC_URL,
        logger,
        json=payload,
    )
    data = response.json()
    return data.get("features") or []


def _parse_stac_item(item: dict, fallback_bbox: list[float]) -> StacItem | None:
    props = item.get("properties") or {}
    acquired_at = _parse_datetime(props.get("datetime"))
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
        bbox=[float(value) for value in bbox],
    )


def _select_best_item(items: list[StacItem]) -> StacItem | None:
    if not items:
        return None
    with_cloud = [item for item in items if item.cloud_cover is not None]
    if with_cloud:
        return min(with_cloud, key=lambda item: (item.cloud_cover, item.acquired_at))
    return max(items, key=lambda item: item.acquired_at)


def _build_evalscript() -> str:
    return "\n".join(
        [
            "//VERSION=3",
            "function setup() {",
            "  return {",
            "    input: [{ bands: ['B02', 'B03', 'B04'], units: 'REFLECTANCE' }],",
            "    output: { bands: 3, sampleType: 'AUTO' }",
            "  };",
            "}",
            "function evaluatePixel(sample) {",
            "  return [sample.B04, sample.B03, sample.B02];",
            "}",
        ]
    )


def _build_process_payload(
    bbox: list[float],
    width: int,
    height: int,
    time_range: tuple[datetime, datetime],
    mosaicking_order: str,
    max_cloud: int,
) -> dict:
    return {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {
                    "crs": "http://www.opengis.net/def/crs/EPSG/0/4326",
                },
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": _isoformat(time_range[0]),
                            "to": _isoformat(time_range[1]),
                        },
                        "maxCloudCoverage": max_cloud,
                    },
                    "processing": {"mosaickingOrder": mosaicking_order},
                }
            ],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": _build_evalscript(),
    }


def _download_preview(
    session: requests.Session,
    token: str,
    payload: dict,
    logger: logging.Logger,
) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    response = _request_with_retry(
        session,
        "POST",
        PROCESS_URL,
        logger,
        json=payload,
        headers=headers,
    )
    return response.content


def _write_image(content: bytes, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_bytes(content)
    temp_path.replace(target_path)


def _write_cache(payload: dict, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp_path.replace(target_path)


def _resolve_output_paths() -> tuple[Path, Path]:
    base_dir = TMP_BASE_DIR
    folder = base_dir / "copernicus"
    return folder, folder / "preview.json"


def _resolve_archive_path(folder: Path, when: datetime) -> Path:
    archive_dir = folder / "archive"
    return archive_dir / f"{when:%Y%m%d}.png"


def _build_mode_record(
    mode: str,
    status: str,
    bbox: list[float],
    preview_path: str | None,
    generated_at: datetime,
    *,
    item: StacItem | None,
) -> dict:
    return {
        "mode": mode,
        "status": status,
        "bbox": bbox,
        "preview_path": preview_path,
        "generated_at": _isoformat(generated_at),
        "product_id": item.product_id if item else None,
        "cloud_cover": item.cloud_cover if item else None,
        "acquired_at": _isoformat(item.acquired_at) if item else None,
        "sensing_time": _isoformat(item.acquired_at) if item else None,
    }


def _resolve_time_range(
    item: StacItem | None,
    fallback_range: tuple[datetime, datetime],
) -> tuple[datetime, datetime]:
    if not item:
        return fallback_range
    start = item.acquired_at - timedelta(hours=2)
    end = item.acquired_at + timedelta(hours=2)
    return start, end


def _generate_preview(
    session: requests.Session,
    token: str,
    mode: str,
    bbox: list[float],
    output_path: Path,
    archive_path: Path | None,
    time_range: tuple[datetime, datetime],
    logger: logging.Logger,
    *,
    mosaicking_order: str,
    max_cloud: int,
    width: int,
    height: int,
) -> str:
    payload = _build_process_payload(
        bbox,
        width,
        height,
        time_range,
        mosaicking_order,
        max_cloud,
    )
    image_bytes = _download_preview(session, token, payload, logger)
    if not image_bytes or len(image_bytes) < 100:
        raise RuntimeError(f"Preview {mode} non valida.")
    _write_image(image_bytes, output_path)
    if archive_path:
        _write_image(image_bytes, archive_path)
    return str(Path("copernicus") / output_path.name)


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("copernicus-preview")

    width = int(os.getenv("COPERNICUS_PREVIEW_WIDTH", str(DEFAULT_WIDTH)))
    height = int(os.getenv("COPERNICUS_PREVIEW_HEIGHT", str(DEFAULT_HEIGHT)))
    max_cloud = int(os.getenv("CDSE_MAX_CLOUD", str(DEFAULT_MAX_CLOUD)))
    best_days = int(os.getenv("COPERNICUS_BEST_DAYS", str(DEFAULT_BEST_DAYS)))
    latest_days = int(os.getenv("COPERNICUS_LATEST_DAYS", str(DEFAULT_LATEST_DAYS)))

    bbox = DEFAULT_BBOX
    folder, cache_path = _resolve_output_paths()
    now = datetime.now(timezone.utc)

    logger.info("Copernicus preview bbox=%s size=%sx%s", bbox, width, height)

    best_range = (now - timedelta(days=best_days), now)
    latest_range = (now - timedelta(days=latest_days), now)

    stac_best_raw = _search_stac_items(bbox, *best_range, logger, limit=30)
    stac_latest_raw = _search_stac_items(bbox, *latest_range, logger, limit=10)

    best_items = [
        item for raw in stac_best_raw if (item := _parse_stac_item(raw, bbox)) is not None
    ]
    latest_items = [
        item for raw in stac_latest_raw if (item := _parse_stac_item(raw, bbox)) is not None
    ]

    best_item = _select_best_item(best_items)
    latest_item = latest_items[0] if latest_items else None

    logger.info(
        "Copernicus best candidate=%s cloud=%s",
        best_item.product_id if best_item else None,
        best_item.cloud_cover if best_item else None,
    )
    logger.info(
        "Copernicus latest candidate=%s cloud=%s",
        latest_item.product_id if latest_item else None,
        latest_item.cloud_cover if latest_item else None,
    )

    session = requests.Session()
    token = _fetch_access_token(session, logger)

    payload = {
        "generated_at": _isoformat(now),
        "bbox": bbox,
        "default_mode": "best",
        "modes": {},
    }

    for mode, item, time_range, mosaicking_order, output_name in (
        (
            "best",
            best_item,
            _resolve_time_range(best_item, best_range),
            "leastCC",
            "best.png",
        ),
        (
            "latest",
            latest_item,
            _resolve_time_range(latest_item, latest_range),
            "mostRecent",
            "latest.png",
        ),
    ):
        status = "ERROR"
        preview_path = None
        archive_path = None
        if item:
            archive_path = _resolve_archive_path(folder, item.acquired_at)
        try:
            preview_path = _generate_preview(
                session,
                token,
                mode,
                bbox,
                folder / output_name,
                archive_path,
                time_range,
                logger,
                mosaicking_order=mosaicking_order,
                max_cloud=max_cloud,
                width=width,
                height=height,
            )
            status = "AVAILABLE"
        except Exception as exc:
            logger.error("Copernicus preview %s failed: %s", mode, exc)
            if item is None:
                status = "NO_DATA"
        payload["modes"][mode] = _build_mode_record(
            mode,
            status,
            bbox,
            preview_path,
            now,
            item=item,
        )

    _write_cache(payload, cache_path)
    logger.info("Copernicus preview cache scritto: %s", cache_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
