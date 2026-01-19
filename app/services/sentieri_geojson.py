"""Helpers for reading and validating sentieri GeoJSON data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALLOWED_POI_CATEGORIES = {"point", "cave", "mount", "hut"}


def _normalize_required(value: Any) -> bool:
    """Return True when a required property value is present."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def parse_geojson_text(text: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Parse GeoJSON from text, returning error metadata when invalid."""
    if not text or not text.strip():
        return None, {"message": "JSON vuoto", "line": None}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, {"message": f"JSON non valido: {exc.msg}", "line": exc.lineno}
    if not isinstance(data, dict):
        return None, {"message": "JSON non valido: il payload deve essere un oggetto", "line": None}
    return data, None


def validate_feature_collection(
    data: dict[str, Any] | None,
    *,
    kind: str,
) -> dict[str, Any]:
    """Validate GeoJSON FeatureCollection for trails/pois and return a report."""
    errors: list[dict[str, Any]] = []
    count = 0

    if not data:
        return {
            "ok": False,
            "count": 0,
            "errors": [{"message": "GeoJSON mancante", "line": None}],
        }

    if data.get("type") != "FeatureCollection":
        errors.append({"message": "type deve essere FeatureCollection", "line": None})

    features = data.get("features", [])
    if not isinstance(features, list):
        errors.append({"message": "features deve essere una lista", "line": None})
        features = []

    count = len(features)

    required_props = {
        "trails": [
            "slug",
            "name",
            "difficulty",
            "km",
            "start_lat",
            "start_lng",
            "description",
        ],
        "pois": ["trail_slug", "category", "name", "description"],
    }
    expected_geom = {"trails": "LineString", "pois": "Point"}

    for index, feature in enumerate(features, start=1):
        if len(errors) >= 10:
            break
        if not isinstance(feature, dict):
            errors.append({"message": "feature non valida", "line": f"feature #{index}"})
            continue

        properties = feature.get("properties")
        geometry = feature.get("geometry")

        if not isinstance(properties, dict):
            errors.append({"message": "properties deve essere un oggetto", "line": f"feature #{index}"})
            properties = {}
        if not isinstance(geometry, dict):
            errors.append({"message": "geometry deve essere un oggetto", "line": f"feature #{index}"})
            geometry = {}

        missing = [
            key
            for key in required_props.get(kind, [])
            if key not in properties or not _normalize_required(properties.get(key))
        ]
        if missing:
            errors.append(
                {
                    "message": f"properties mancanti: {', '.join(missing)}",
                    "line": f"feature #{index}",
                }
            )

        geom_type = geometry.get("type") if isinstance(geometry, dict) else None
        if geom_type != expected_geom.get(kind):
            errors.append(
                {
                    "message": f"geometry.type deve essere {expected_geom.get(kind)}",
                    "line": f"feature #{index}",
                }
            )

        if kind == "pois" and properties:
            category = properties.get("category")
            if category not in ALLOWED_POI_CATEGORIES:
                errors.append(
                    {
                        "message": (
                            "category non valida (usa: point, cave, mount, hut)"
                        ),
                        "line": f"feature #{index}",
                    }
                )

    return {"ok": len(errors) == 0, "count": count, "errors": errors}


def read_geojson_file(path: Path) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Read a GeoJSON file from disk returning raw text and parsed JSON."""
    if not path.exists():
        return None, None, {"message": "file mancante", "line": None}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, {"message": f"errore lettura file: {exc}", "line": None}
    data, error = parse_geojson_text(raw)
    return raw, data, error
