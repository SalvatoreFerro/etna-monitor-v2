"""Helpers for Copernicus Smart View previews (S2/S1)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, url_for

from app.services.copernicus import ETNA_BBOX_EPSG4326

S2_IMAGE = "copernicus/s2_latest.png"
S1_IMAGE = "copernicus/s1_latest.png"


def _parse_datetime(value: str | None) -> datetime | None:
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


def _status_path() -> Path:
    data_dir = current_app.config.get("DATA_DIR") or Path(current_app.root_path).parent / "data"
    return Path(data_dir) / "copernicus_status.json"


def _log_path() -> Path:
    log_dir = current_app.config.get("LOG_DIR") or Path(current_app.root_path).parent / "logs"
    return Path(log_dir) / "copernicus_preview.log"


def _copernicus_static_dir() -> Path:
    return Path(current_app.static_folder) / "copernicus"


def load_copernicus_status() -> dict:
    path = _status_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def load_copernicus_log() -> str | None:
    path = _log_path()
    if not path.exists():
        return None
    return path.read_text(errors="replace")


def _resolve_bbox(status: dict) -> list[float]:
    bbox = status.get("bbox") if isinstance(status, dict) else None
    if isinstance(bbox, list) and len(bbox) == 4:
        return [float(value) for value in bbox]
    return [float(value) for value in ETNA_BBOX_EPSG4326]


def _resolve_source(status: dict) -> str:
    source = status.get("selected_source") if isinstance(status, dict) else None
    if source in {"S1", "S2"}:
        return source
    return "S1"


def _preview_url(filename: str, storage_mode: str | None) -> str | None:
    if storage_mode == "s3":
        base_url = (os.getenv("S3_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if base_url:
            return f"{base_url}/{filename}"
        return None
    return url_for("static", filename=filename)


def _badge_label(source: str) -> str:
    return "Sentinel-2 (Ottico)" if source == "S2" else "Sentinel-1 (Radar)"


def _badge_class(source: str) -> str:
    return "observatory-badge--success" if source == "S2" else "observatory-badge--fallback"


def build_copernicus_view_payload() -> dict:
    status = load_copernicus_status()
    selected_source = _resolve_source(status)
    bbox = _resolve_bbox(status)
    generated_at = status.get("generated_at")
    generated_dt = _parse_datetime(generated_at)
    generated_epoch = int(generated_dt.timestamp()) if generated_dt else None
    storage_mode = status.get("storage_mode") if isinstance(status, dict) else None
    last_error = status.get("last_error") if isinstance(status, dict) else None
    last_ok_at = status.get("last_ok_at") if isinstance(status, dict) else None

    static_dir = _copernicus_static_dir()
    local_available = any(
        (static_dir / name).exists() for name in ("s1_latest.png", "s2_latest.png")
    )
    s3_available = storage_mode == "s3" and bool(last_ok_at)
    preview_available = local_available or s3_available

    preview_s2 = (
        _preview_url(S2_IMAGE, storage_mode if s3_available else None)
        if preview_available
        else None
    )
    preview_s1 = (
        _preview_url(S1_IMAGE, storage_mode if s3_available else None)
        if preview_available
        else None
    )
    if s3_available and not (preview_s1 and preview_s2):
        preview_available = False
        preview_s1 = None
        preview_s2 = None
    preview_url = None
    if preview_available:
        preview_url = preview_s2 if selected_source == "S2" else preview_s1

    if not preview_available:
        selected_source = None

    badge_label = (
        "Preview non generata" if not preview_available else _badge_label(selected_source)
    )
    badge_class = (
        "observatory-badge--warning"
        if not preview_available
        else _badge_class(selected_source)
    )
    fallback_note = None
    if not preview_available:
        fallback_note = (
            f"Preview non generata: {last_error}" if last_error else "Preview non generata."
        )
    elif selected_source == "S1":
        fallback_note = (
            "Sentinel-2 non disponibile o copertura nuvolosa elevata: "
            "visualizzazione radar (vede attraverso le nubi)."
        )

    return {
        "selected_source": selected_source,
        "badge_label": badge_label,
        "badge_class": badge_class,
        "fallback_note": fallback_note,
        "preview_url": preview_url,
        "preview_url_s2": preview_s2,
        "preview_url_s1": preview_s1,
        "generated_at": generated_at,
        "generated_at_epoch": generated_epoch,
        "storage_mode": storage_mode,
        "last_error": last_error,
        "last_ok_at": last_ok_at,
        "bbox": bbox,
        "s2": {
            "datetime": status.get("s2_datetime"),
            "cloud_cover": status.get("s2_cloud_cover"),
            "product_id": status.get("s2_product_id"),
        },
        "s1": {
            "datetime": status.get("s1_datetime"),
            "product_id": status.get("s1_product_id"),
        },
        "errors": status.get("errors") if isinstance(status.get("errors"), list) else [],
    }
