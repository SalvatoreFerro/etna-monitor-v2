"""Helpers for Copernicus Smart View previews (S2/S1)."""

from __future__ import annotations

import json
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
    return Path(current_app.root_path).parent / "data" / "copernicus_status.json"


def _log_path() -> Path:
    return Path(current_app.root_path).parent / "data" / "copernicus_preview.log"


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


def _preview_url(filename: str) -> str:
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
    preview_s2 = _preview_url(S2_IMAGE)
    preview_s1 = _preview_url(S1_IMAGE)
    preview_url = preview_s2 if selected_source == "S2" else preview_s1

    return {
        "selected_source": selected_source,
        "badge_label": _badge_label(selected_source),
        "badge_class": _badge_class(selected_source),
        "fallback_note": (
            "Sentinel-2 non disponibile o copertura nuvolosa elevata: "
            "visualizzazione radar (vede attraverso le nubi)."
            if selected_source == "S1"
            else None
        ),
        "preview_url": preview_url,
        "preview_url_s2": preview_s2,
        "preview_url_s1": preview_s1,
        "generated_at": generated_at,
        "generated_at_epoch": generated_epoch,
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
