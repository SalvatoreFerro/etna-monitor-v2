#!/usr/bin/env python3
"""Generate Copernicus Smart View previews (Sentinel-2 + Sentinel-1)."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import requests

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
STAC_URL = "https://stac.dataspace.copernicus.eu/v1/search"

S2_COLLECTION = "sentinel-2-l2a"
S1_COLLECTION = "sentinel-1-grd"

DEFAULT_BBOX = [14.85, 37.65, 15.15, 37.88]
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
DEFAULT_S2_DAYS = 10
DEFAULT_S1_DAYS = 10
DEFAULT_MAX_CLOUD = 40
REQUEST_TIMEOUT = (8, 60)
RETRY_DELAYS = [1.0, 2.0]


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
    collection: str,
    bbox: list[float],
    start: datetime,
    end: datetime,
    logger: logging.Logger,
    *,
    limit: int = 30,
) -> list[dict]:
    payload = {
        "collections": [collection],
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


def _select_latest(items: list[StacItem]) -> StacItem | None:
    return items[0] if items else None


def _select_s2_candidate(items: list[StacItem], max_cloud: int) -> StacItem | None:
    eligible = [
        item
        for item in items
        if item.cloud_cover is not None and item.cloud_cover <= max_cloud
    ]
    return eligible[0] if eligible else None


def _build_evalscript_s2() -> str:
    return "\n".join(
        [
            "//VERSION=3",
            "function setup() {",
            "  return {",
            "    input: [{ bands: ['B02', 'B03', 'B04'], units: 'REFLECTANCE' }],",
            "    output: { bands: 3, sampleType: 'AUTO' }",
            "  };",
            "}",
            "function clamp(value) {",
            "  return Math.min(1, Math.max(0, value));",
            "}",
            "function evaluatePixel(sample) {",
            "  let r = clamp(sample.B04 * 2.4);",
            "  let g = clamp(sample.B03 * 2.4);",
            "  let b = clamp(sample.B02 * 2.4);",
            "  return [r, g, b];",
            "}",
        ]
    )


def _build_evalscript_s1() -> str:
    return "\n".join(
        [
            "//VERSION=3",
            "function setup() {",
            "  return {",
            "    input: [{ bands: ['VV', 'VH'], units: 'DB' }],",
            "    output: { bands: 3, sampleType: 'AUTO' }",
            "  };",
            "}",
            "function clamp(value) {",
            "  return Math.min(1, Math.max(0, value));",
            "}",
            "function evaluatePixel(sample) {",
            "  let vv = sample.VV;",
            "  let vh = sample.VH;",
            "  let value = (vh !== null && vh !== undefined) ? Math.max(vv, vh) : vv;",
            "  let scaled = clamp((value + 25.0) / 20.0);",
            "  return [scaled, scaled, scaled];",
            "}",
        ]
    )


def _build_process_payload(
    collection: str,
    bbox: list[float],
    width: int,
    height: int,
    time_range: tuple[datetime, datetime],
    evalscript: str,
    *,
    max_cloud: int | None = None,
) -> dict:
    data_filter: dict[str, object] = {
        "timeRange": {
            "from": _isoformat(time_range[0]),
            "to": _isoformat(time_range[1]),
        }
    }
    if max_cloud is not None:
        data_filter["maxCloudCoverage"] = max_cloud
    data_entry: dict[str, object] = {
        "type": collection,
        "dataFilter": data_filter,
    }
    if collection == S1_COLLECTION:
        data_entry["processing"] = {
            "orthorectify": True,
            "backCoeff": "SIGMA0_ELLIPSOID",
        }
    return {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
            },
            "data": [data_entry],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
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


def _write_status(payload: dict, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temp_path.replace(target_path)


def _resolve_paths() -> tuple[Path, Path, Path]:
    base_dir = Path(__file__).resolve().parents[1]
    static_folder = base_dir / "app" / "static" / "copernicus"
    data_dir = Path(os.getenv("DATA_DIR", str(base_dir / "data")))
    log_dir = Path(os.getenv("LOG_DIR", str(base_dir / "logs")))
    status_path = data_dir / "copernicus_status.json"
    log_path = log_dir / "copernicus_preview.log"
    return static_folder, status_path, log_path


def _object_storage_enabled() -> bool:
    flag = (os.getenv("OBJECT_STORAGE") or "").strip().lower()
    return flag in {"1", "true", "yes", "s3", "r2"}


def _load_s3_config(logger: logging.Logger) -> dict | None:
    bucket = (os.getenv("S3_BUCKET") or "").strip()
    access_key = (os.getenv("S3_ACCESS_KEY") or "").strip()
    secret_key = (os.getenv("S3_SECRET_KEY") or "").strip()
    endpoint = (os.getenv("S3_ENDPOINT") or "").strip()
    region = (os.getenv("S3_REGION") or "").strip() or None

    if not (bucket and access_key and secret_key):
        if _object_storage_enabled():
            logger.warning(
                "OBJECT_STORAGE enabled but S3 credentials missing (bucket/access/secret)."
            )
        return None

    return {
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint": endpoint or None,
        "region": region,
    }


def _upload_to_s3(
    client,
    bucket: str,
    key: str,
    path: Path,
    logger: logging.Logger,
) -> None:
    extra_args = {
        "ContentType": "image/png",
        "CacheControl": "public, max-age=3600",
    }
    client.upload_file(str(path), bucket, key, ExtraArgs=extra_args)
    logger.info("Upload S3 completato: %s -> s3://%s/%s", path, bucket, key)


def _resolve_time_range(item: StacItem) -> tuple[datetime, datetime]:
    start = item.acquired_at - timedelta(hours=2)
    end = item.acquired_at + timedelta(hours=2)
    return start, end


def _generate_preview(
    session: requests.Session,
    token: str,
    item: StacItem,
    output_path: Path,
    bbox: list[float],
    logger: logging.Logger,
    *,
    collection: str,
    evalscript: str,
    width: int,
    height: int,
    max_cloud: int | None = None,
) -> None:
    payload = _build_process_payload(
        collection,
        bbox,
        width,
        height,
        _resolve_time_range(item),
        evalscript,
        max_cloud=max_cloud,
    )
    image_bytes = _download_preview(session, token, payload, logger)
    if not image_bytes or len(image_bytes) < 100:
        raise RuntimeError("Preview non valida.")
    _write_image(image_bytes, output_path)


def main() -> int:
    base_logger = logging.getLogger("copernicus-smart-preview")
    base_logger.setLevel(logging.INFO)

    static_folder, status_path, log_path = _resolve_paths()
    static_folder.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not base_logger.handlers:
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        stream_handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        file_handler.setFormatter(formatter)
        stream_handler.setFormatter(formatter)
        base_logger.addHandler(file_handler)
        base_logger.addHandler(stream_handler)

    width = int(os.getenv("COPERNICUS_PREVIEW_WIDTH", str(DEFAULT_WIDTH)))
    height = int(os.getenv("COPERNICUS_PREVIEW_HEIGHT", str(DEFAULT_HEIGHT)))
    max_cloud = int(os.getenv("COPERNICUS_S2_MAX_CLOUD", str(DEFAULT_MAX_CLOUD)))
    s2_days = int(os.getenv("COPERNICUS_S2_DAYS", str(DEFAULT_S2_DAYS)))
    s1_days = int(os.getenv("COPERNICUS_S1_DAYS", str(DEFAULT_S1_DAYS)))

    bbox = DEFAULT_BBOX
    now = datetime.now(timezone.utc)

    base_logger.info("Copernicus Smart View bbox=%s size=%sx%s", bbox, width, height)

    errors: list[str] = []
    s2_item = None
    s2_candidate = None
    s1_item = None
    s2_generated = False
    s1_generated = False

    try:
        s2_raw = _search_stac_items(
            S2_COLLECTION,
            bbox,
            now - timedelta(days=s2_days),
            now,
            base_logger,
            limit=30,
        )
        s2_items = [
            item
            for raw in s2_raw
            if (item := _parse_stac_item(raw, bbox)) is not None
        ]
        s2_item = _select_latest(s2_items)
        s2_candidate = _select_s2_candidate(s2_items, max_cloud)
    except Exception as exc:
        message = f"S2 STAC error: {exc}"
        base_logger.error(message)
        errors.append(message)
        s2_items = []

    try:
        s1_raw = _search_stac_items(
            S1_COLLECTION,
            bbox,
            now - timedelta(days=s1_days),
            now,
            base_logger,
            limit=20,
        )
        s1_items = [
            item
            for raw in s1_raw
            if (item := _parse_stac_item(raw, bbox)) is not None
        ]
        s1_item = _select_latest(s1_items)
    except Exception as exc:
        message = f"S1 STAC error: {exc}"
        base_logger.error(message)
        errors.append(message)
        s1_items = []

    base_logger.info(
        "S2 latest=%s cloud=%s candidate=%s",
        s2_item.product_id if s2_item else None,
        s2_item.cloud_cover if s2_item else None,
        s2_candidate.product_id if s2_candidate else None,
    )
    base_logger.info(
        "S1 latest=%s",
        s1_item.product_id if s1_item else None,
    )

    session = requests.Session()
    token = None
    try:
        token = _fetch_access_token(session, base_logger)
    except Exception as exc:
        message = f"Token error: {exc}"
        base_logger.error(message)
        errors.append(message)

    if token and s2_candidate:
        try:
            _generate_preview(
                session,
                token,
                s2_candidate,
                static_folder / "s2_latest.png",
                bbox,
                base_logger,
                collection=S2_COLLECTION,
                evalscript=_build_evalscript_s2(),
                width=width,
                height=height,
                max_cloud=max_cloud,
            )
            s2_generated = True
            base_logger.info("S2 preview saved: %s", static_folder / "s2_latest.png")
        except Exception as exc:
            message = f"S2 preview error: {exc}"
            base_logger.error(message)
            errors.append(message)

    if token and s1_item:
        try:
            _generate_preview(
                session,
                token,
                s1_item,
                static_folder / "s1_latest.png",
                bbox,
                base_logger,
                collection=S1_COLLECTION,
                evalscript=_build_evalscript_s1(),
                width=width,
                height=height,
            )
            s1_generated = True
            base_logger.info("S1 preview saved: %s", static_folder / "s1_latest.png")
        except Exception as exc:
            message = f"S1 preview error: {exc}"
            base_logger.error(message)
            errors.append(message)

    selected_source = None
    if s2_generated and s2_candidate and s2_candidate.cloud_cover is not None:
        if s2_candidate.cloud_cover <= max_cloud:
            selected_source = "S2"
    if selected_source is None and s1_generated:
        selected_source = "S1"

    storage_mode = "local"
    s3_config = _load_s3_config(base_logger)
    if s3_config:
        s3_client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint"],
            region_name=s3_config["region"],
            aws_access_key_id=s3_config["access_key"],
            aws_secret_access_key=s3_config["secret_key"],
        )
        uploaded = False
        for filename in ("s2_latest.png", "s1_latest.png"):
            path = static_folder / filename
            if not path.exists():
                continue
            try:
                _upload_to_s3(
                    s3_client,
                    s3_config["bucket"],
                    f"copernicus/{filename}",
                    path,
                    base_logger,
                )
                uploaded = True
            except Exception as exc:
                message = f"S3 upload error ({filename}): {exc}"
                base_logger.error(message)
                errors.append(message)
        if uploaded:
            storage_mode = "s3"

    s2_status_item = s2_candidate or s2_item
    last_ok_at = _isoformat(now) if (s1_generated or s2_generated) else None
    last_error = errors[-1] if errors else None
    if not last_ok_at and not last_error:
        last_error = "Preview non disponibile."
    status_payload = {
        "selected_source": selected_source,
        "s2_datetime": _isoformat(s2_status_item.acquired_at) if s2_status_item else None,
        "s2_cloud_cover": s2_status_item.cloud_cover if s2_status_item else None,
        "s2_product_id": s2_status_item.product_id if s2_status_item else None,
        "s1_datetime": _isoformat(s1_item.acquired_at) if s1_item else None,
        "s1_product_id": s1_item.product_id if s1_item else None,
        "generated_at": _isoformat(now),
        "last_ok_at": last_ok_at,
        "last_error": last_error,
        "storage_mode": storage_mode,
        "bbox": bbox,
        "errors": errors,
    }

    _write_status(status_payload, status_path)
    base_logger.info("Copernicus status scritto: %s", status_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
