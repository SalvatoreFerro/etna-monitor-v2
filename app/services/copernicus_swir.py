"""Fetch and cache Sentinel Hub SWIR preview for the observatory page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

import requests
from flask import current_app

from app.services.copernicus import ETNA_BBOX_EPSG4326

INSTANCE_ID = "bdceb943-164b-475a-aa72-8011ec5500ab"
LAYER_NAME = "SWIR"
WMS_URL = f"https://services.sentinel-hub.com/ogc/wms/{INSTANCE_ID}"
REQUEST_TIMEOUT = (6, 30)
RETRY_DELAYS = [0.0, 1.0, 2.0]
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
MAX_CACHE_AGE = timedelta(minutes=30)


@dataclass(frozen=True)
class SwirRefreshResult:
    ok: bool
    updated: bool
    used_cache: bool
    error: str | None
    updated_at: datetime | None


def _swir_image_path() -> Path:
    return Path(current_app.static_folder) / "copernicus" / "s2_latest.png"


def _build_wms_params(bbox: list[float], width: int, height: int) -> dict[str, str]:
    lon_min, lat_min, lon_max, lat_max = bbox
    bbox_value = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    return {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": LAYER_NAME,
        "FORMAT": "image/png",
        "TRANSPARENT": "true",
        "CRS": "EPSG:4326",
        "BBOX": bbox_value,
        "WIDTH": str(width),
        "HEIGHT": str(height),
    }


def _request_with_retry(session: requests.Session, url: str, params: dict[str, str]) -> bytes:
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_exc = exc
            current_app.logger.warning(
                "[OBSERVATORY] SWIR download failed (attempt %s/%s): %s",
                attempt,
                len(RETRY_DELAYS),
                exc,
            )
    if last_exc:
        raise last_exc
    raise RuntimeError("SWIR download failed")


def _is_stale(path: Path) -> bool:
    if not path.exists():
        return True
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - mtime > MAX_CACHE_AGE


def refresh_swir_image(*, force: bool = False, bypass_owner: bool = False) -> SwirRefreshResult:
    target_path = _swir_image_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    cached_exists = target_path.exists()
    _ = bypass_owner

    if not force and cached_exists and not _is_stale(target_path):
        updated_at = datetime.fromtimestamp(target_path.stat().st_mtime, tz=timezone.utc)
        return SwirRefreshResult(
            ok=True,
            updated=False,
            used_cache=True,
            error=None,
            updated_at=updated_at,
        )

    try:
        params = _build_wms_params(ETNA_BBOX_EPSG4326, DEFAULT_WIDTH, DEFAULT_HEIGHT)
        session = requests.Session()
        content = _request_with_retry(session, WMS_URL, params)
        temp_path = target_path.with_suffix(".tmp")
        temp_path.write_bytes(content)
        temp_path.replace(target_path)
        current_app.logger.info("[SWIR] image written to %s", target_path.resolve())
        updated_at = datetime.fromtimestamp(target_path.stat().st_mtime, tz=timezone.utc)
        return SwirRefreshResult(
            ok=True,
            updated=True,
            used_cache=False,
            error=None,
            updated_at=updated_at,
        )
    except Exception as exc:  # noqa: BLE001 - return status to frontend
        updated_at = None
        if cached_exists:
            updated_at = datetime.fromtimestamp(target_path.stat().st_mtime, tz=timezone.utc)
        return SwirRefreshResult(
            ok=False,
            updated=False,
            used_cache=cached_exists,
            error=str(exc),
            updated_at=updated_at,
        )
