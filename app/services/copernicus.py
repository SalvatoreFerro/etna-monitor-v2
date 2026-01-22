"""Helpers for Copernicus Sentinel-2 metadata."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, url_for

from app.models.copernicus_image import CopernicusImage

ETNA_BBOX_EPSG4326 = [14.85, 37.65, 15.15, 37.88]
AVAILABLE_STATUS = "AVAILABLE"


def get_latest_copernicus_image() -> CopernicusImage | None:
    return (
        CopernicusImage.query.order_by(CopernicusImage.acquired_at.desc()).first()
    )


def resolve_copernicus_preview_url(record: CopernicusImage | None) -> str | None:
    if record is None:
        return None
    preview_path = record.preview_path or record.image_path
    if not preview_path:
        return None
    static_folder = current_app.static_folder or ""
    image_path = Path(static_folder) / preview_path
    if not image_path.exists():
        return None
    return url_for("static", filename=preview_path)


def resolve_copernicus_bbox(record: CopernicusImage | None) -> list[float]:
    """Return a stable EPSG:4326 bbox for the Etna observatory view."""
    _ = record
    return [float(value) for value in ETNA_BBOX_EPSG4326]


def is_available_status(status: str | None, preview_url: str | None) -> bool:
    if not status or not preview_url:
        return False
    return status.upper() == AVAILABLE_STATUS


def build_copernicus_status(
    record: CopernicusImage | None,
    preview_url: str | None,
) -> dict[str, str | bool]:
    if not record:
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

    status = (record.status or "").upper() or "UNKNOWN"
    available = is_available_status(status, preview_url)
    if available:
        return {
            "status": status,
            "available": True,
            "label": "✅ Immagine disponibile",
            "message": "Immagine pronta per la visualizzazione.",
            "badge_class": "observatory-badge--success",
        }
    if status == "NO_ASSET":
        return {
            "status": status,
            "available": False,
            "label": "🟡 Nessuna anteprima disponibile",
            "message": (
                "L’ultimo item Sentinel-2 non fornisce asset immagine (thumbnail/quicklook/visual)."
            ),
            "badge_class": "observatory-badge--warning",
        }
    if status == "ERROR":
        return {
            "status": status,
            "available": False,
            "label": "⚠️ Errore Copernicus",
            "message": "Errore durante il download della preview. Riprovare più tardi.",
            "badge_class": "observatory-badge--danger",
        }
    if status == "AVAILABLE" and not preview_url:
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
