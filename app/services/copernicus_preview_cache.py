"""Helpers for Copernicus Sentinel-2 preview cache."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, url_for

from app.services.copernicus import ETNA_BBOX_EPSG4326

DEFAULT_MODE = "best"
AVAILABLE_STATUS = "AVAILABLE"


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


def load_preview_cache() -> dict:
    static_folder = Path(current_app.static_folder or "static")
    cache_path = static_folder / "copernicus" / "preview.json"
    if not cache_path.exists():
        return {}
    try:
        return json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        return {}


def resolve_preview_entry(cache: dict, mode: str) -> dict | None:
    modes = cache.get("modes") if isinstance(cache, dict) else None
    if isinstance(modes, dict) and mode in modes:
        entry = modes.get(mode)
    else:
        entry = cache.get(mode) if isinstance(cache, dict) else None
    return entry if isinstance(entry, dict) else None


def resolve_preview_url(entry: dict | None) -> str | None:
    if not entry:
        return None
    preview_path = entry.get("preview_path")
    if not preview_path:
        return None
    static_folder = current_app.static_folder or ""
    image_path = Path(static_folder) / preview_path
    if not image_path.exists():
        return None
    return url_for("static", filename=preview_path)


def resolve_copernicus_bbox(entry: dict | None) -> list[float]:
    if entry and entry.get("bbox"):
        bbox = entry.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            return [float(value) for value in bbox]
    return [float(value) for value in ETNA_BBOX_EPSG4326]


def build_copernicus_status(
    entry: dict | None,
    preview_url: str | None,
) -> dict[str, str | bool]:
    if not entry:
        return {
            "status": "UNAVAILABLE",
            "available": False,
            "label": "❌ Nessun prodotto recente",
            "message": (
                "Nessun prodotto recente disponibile per l’area dell’Etna. "
                "La mappa mostra il footprint di riferimento."
            ),
            "badge_class": "observatory-badge--danger",
        }

    status = str(entry.get("status") or "").upper() or "UNKNOWN"
    available = status == AVAILABLE_STATUS and bool(preview_url)
    if available:
        return {
            "status": status,
            "available": True,
            "label": "✅ Immagine disponibile",
            "message": "Immagine pronta per la visualizzazione.",
            "badge_class": "observatory-badge--success",
        }
    if status == "NO_DATA":
        return {
            "status": status,
            "available": False,
            "label": "🟡 Nessuna acquisizione recente",
            "message": "Nessun prodotto recente disponibile per l’area dell’Etna.",
            "badge_class": "observatory-badge--warning",
        }
    if status == "ERROR":
        return {
            "status": status,
            "available": False,
            "label": "⚠️ Errore Copernicus",
            "message": "Errore durante la generazione della preview. Riprovare più tardi.",
            "badge_class": "observatory-badge--danger",
        }
    if status == AVAILABLE_STATUS and not preview_url:
        return {
            "status": status,
            "available": False,
            "label": "⚠️ Anteprima mancante",
            "message": "La preview risulta disponibile ma il file non è presente nello storage.",
            "badge_class": "observatory-badge--warning",
        }
    return {
        "status": status,
        "available": False,
        "label": "⏳ Anteprima in aggiornamento",
        "message": "Anteprima non ancora disponibile per l’ultima acquisizione.",
        "badge_class": "observatory-badge--info",
    }


def resolve_mode(cache: dict) -> str:
    default_mode = cache.get("default_mode") if isinstance(cache, dict) else None
    return str(default_mode) if default_mode else DEFAULT_MODE


def build_preview_payload(
    entry: dict | None,
    preview_url: str | None,
    mode: str,
    bbox: list[float],
) -> dict:
    sensing_time = entry.get("sensing_time") if entry else None
    acquired_at = entry.get("acquired_at") if entry else None
    created_at = entry.get("generated_at") if entry else None
    timestamp = _parse_datetime(sensing_time or acquired_at)
    status_payload = build_copernicus_status(entry, preview_url)
    return {
        "mode": mode,
        "available": bool(status_payload["available"]),
        "status": status_payload["status"],
        "status_label": status_payload["label"],
        "status_detail": status_payload["message"],
        "status_badge_class": status_payload["badge_class"],
        "preview_path": preview_url,
        "preview_url": preview_url,
        "product_id": entry.get("product_id") if entry else None,
        "cloud_cover": entry.get("cloud_cover") if entry else None,
        "cloud_coverage": entry.get("cloud_cover") if entry else None,
        "acquired_at": sensing_time or acquired_at,
        "sensing_time": sensing_time,
        "created_at": created_at,
        "datetime_epoch": int(timestamp.timestamp()) if timestamp else None,
        "bbox": bbox,
    }
