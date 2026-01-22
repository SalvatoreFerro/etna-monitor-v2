import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from ..utils.metrics import record_csv_error, record_csv_read, record_csv_update
from ..utils.auth import get_current_user, is_owner_or_admin
from ..utils.config import get_curva_csv_path, warn_if_stale_timestamp
from ..models.hotspots_cache import HotspotsCache
from ..models.hotspots_record import HotspotsRecord
from ..services.copernicus_preview_cache import (
    build_preview_payload,
    load_preview_cache,
    resolve_copernicus_bbox,
    resolve_mode,
    resolve_preview_entry,
    resolve_preview_url,
)
from backend.utils.extract_colored import process_colored_png_to_csv
from backend.utils.time import to_iso_utc
from backend.services.hotspots.config import HotspotsConfig
from backend.services.hotspots.diagnostics import diagnose_firms
from backend.services.hotspots.significance import is_significant_record
from ..services.sentieri_geojson import read_geojson_file, validate_feature_collection

_RANGE_LIMITS: dict[str, int] = {
    "24h": 288,
    "3d": 864,
    "7d": 2016,
    "14d": 4032,
    "all": 4032,
}

_DEFAULT_LIMIT = 2016
_MIN_LIMIT = 1
_MAX_LIMIT = 4032

api_bp = Blueprint("api", __name__)


def _require_admin_user() -> bool:
    user = get_current_user()
    return bool(user and user.is_admin)


def _hotspot_payload(item: HotspotsRecord) -> dict:
    brightness = item.bright_ti4
    if brightness is None:
        brightness = item.brightness
    if brightness is None:
        brightness = item.bright_ti5
    unit = item.intensity_unit
    if not unit:
        if item.frp is not None:
            unit = "MW"
        elif brightness is not None:
            unit = "K"
        else:
            unit = "unknown"
    return {
        "id": item.fingerprint,
        "time_utc": to_iso_utc(item.acq_datetime),
        "lat": item.lat,
        "lon": item.lon,
        "source": item.source,
        "satellite": item.satellite,
        "instrument": item.instrument,
        "confidence": item.confidence,
        "bright_ti4": item.bright_ti4,
        "bright_ti5": item.bright_ti5,
        "frp": item.frp,
        "daynight": item.daynight,
        "version": item.version,
        "intensity": {
            "frp": item.frp,
            "brightness": brightness,
            "unit": unit,
        },
        "status": item.status or "unknown",
        "maps_url": f"https://www.google.com/maps?q={item.lat},{item.lon}",
    }


def _prepare_tremor_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Normalise timestamp typing and detect empty datasets."""
    if "timestamp" not in raw_df.columns:
        return pd.DataFrame(columns=["timestamp", "value"]), "missing_timestamp"

    df = raw_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    if "value" not in df.columns:
        if "value_max" in df.columns:
            df["value"] = df["value_max"]
        elif "value_avg" in df.columns:
            df["value"] = df["value_avg"]

    if df.empty:
        return df, "empty_data"

    return df, None

@api_bp.get("/api/curva")
def get_curva():
    """Return curva.csv data as JSON with no-cache headers"""
    csv_path = get_curva_csv_path()
    include_csv_path = is_owner_or_admin(get_current_user())

    if not csv_path.exists() or csv_path.stat().st_size <= 20:
        try:
            colored_url = os.getenv("INGV_COLORED_URL", "")
            result = process_colored_png_to_csv(colored_url, str(csv_path))
            current_app.logger.info(
                "[API] Auto-generated curva.csv with %s rows", result["rows"]
            )
        except Exception as e:
            current_app.logger.exception("[API] Failed to auto-generate curva.csv")
            record_csv_error(str(e))
            payload = {
                "ok": False,
                "error": "Dati INGV non disponibili al momento",
                "placeholder_reason": "bootstrap_failed",
            }
            if include_csv_path:
                payload["csv_path_used"] = str(csv_path)
            return jsonify(payload), 503

    try:
        raw_df = pd.read_csv(csv_path)
        df, reason = _prepare_tremor_dataframe(raw_df)

        if reason is not None:
            record_csv_error(reason)
            status_code = 200
            payload = {
                "ok": False,
                "reason": reason,
                "rows": 0,
            }
            if include_csv_path:
                payload["csv_path_used"] = str(csv_path)
            return jsonify(payload), status_code

        df = df.sort_values("timestamp")

        limit = request.args.get("limit", type=int)
        if limit is None:
            range_key = request.args.get("range")
            if range_key:
                limit = _RANGE_LIMITS.get(range_key)

        if limit is None:
            limit = _DEFAULT_LIMIT

        if not isinstance(limit, int) or limit < _MIN_LIMIT or limit > _MAX_LIMIT:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "invalid_limit",
                        "reason": "invalid_limit",
                        "rows": 0,
                    }
                ),
                400,
            )

        df = df.tail(limit)

        last_ts = df["timestamp"].iloc[-1]
        warn_if_stale_timestamp(last_ts, current_app.logger, "api_curva")
        record_csv_read(len(df), last_ts.to_pydatetime())

        response_df = df.copy()
        response_df["timestamp"] = response_df["timestamp"].apply(to_iso_utc)

        data = response_df.to_dict(orient="records")

        payload = {
            "ok": True,
            "data": data,
            "last_ts": to_iso_utc(last_ts),
            "rows": len(data),
        }
        if include_csv_path:
            payload["csv_path_used"] = str(csv_path)

        response = jsonify(payload)

        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        if include_csv_path:
            response.headers["X-Csv-Path-Used"] = str(csv_path)
            response.headers["X-Csv-Last-Ts"] = payload.get("last_ts") or ""
        
        return response
        
    except Exception as e:
        current_app.logger.exception("[API] Failed to read curva.csv")
        record_csv_error(str(e))
        payload = {
            "ok": False,
            "error": str(e),
        }
        if include_csv_path:
            payload["csv_path_used"] = str(csv_path)
        return jsonify(payload), 500

@api_bp.route("/api/status")
def get_status():
    """Return current status and metrics"""
    csv_path = get_curva_csv_path()
    threshold = float(os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))
    track_event = request.args.get("track")
    if track_event:
        location = request.args.get("location")
        if location:
            current_app.logger.info("[TRACK] %s | %s", track_event, location)
        else:
            current_app.logger.info("[TRACK] %s", track_event)
    
    try:
        if csv_path.exists():
            raw_df = pd.read_csv(csv_path)
            df, reason = _prepare_tremor_dataframe(raw_df)

            if reason is None:
                df = df.sort_values("timestamp")
                last_ts = df["timestamp"].iloc[-1]
                record_csv_read(len(df), last_ts.to_pydatetime())

                current_value = float(df["value"].iloc[-1])
                above_threshold = current_value > threshold

                return jsonify({
                    "ok": True,
                    "current_value": current_value,
                    "above_threshold": above_threshold,
                    "threshold": threshold,
                    "last_update": to_iso_utc(last_ts),
                    "total_points": len(df)
                })

            record_csv_error(f"status::{reason}")
            status_code = 200
            return jsonify({
                "ok": False,
                "reason": reason,
                "current_value": None,
                "above_threshold": False,
                "threshold": threshold,
                "last_update": None,
                "total_points": 0,
            }), status_code

        return jsonify({
            "ok": True,
            "current_value": 0.0,
            "above_threshold": False,
            "threshold": threshold,
            "last_update": None,
            "total_points": 0
        })
        
    except Exception as e:
        current_app.logger.exception("[API] Status endpoint failed")
        record_csv_error(str(e))
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@api_bp.get("/api/hotspots/latest")
def get_hotspots_latest():
    config = HotspotsConfig.from_env()
    mode = request.args.get("mode", "all").strip().lower()
    if mode not in {"all", "significant"}:
        mode = "all"
    if not config.enabled:
        cache_response = {
            "available": False,
            "last_fetch_at": None,
            "last_fetch_count": 0,
            "count_24h": 0,
            "count_24h_raw": 0,
            "count_24h_significant": 0,
            "count_all": 0,
            "count_significant": 0,
            "last_nonzero_at": None,
            "items_24h": [],
            "items_24h_raw": [],
            "items_24h_significant": [],
            "items": [],
            "mode": mode,
        }
    else:
        try:
            record = HotspotsCache.query.filter_by(key="etna_latest").one_or_none()
        except SQLAlchemyError:
            current_app.logger.exception("[API] Hotspots cache lookup failed")
            record = None

        payload = record.payload if record and isinstance(record.payload, dict) else {}
        last_fetch_at = payload.get("last_fetch_at")
        last_fetch_count = payload.get("last_fetch_count")
        last_nonzero_at = payload.get("last_nonzero_at")
        count_significant_cache = payload.get("count_significant")
        if not isinstance(last_fetch_count, int):
            last_fetch_count = record.count if record else 0
        if not last_fetch_at and record:
            last_fetch_at = to_iso_utc(record.generated_at)
        else:
            last_fetch_at = to_iso_utc(last_fetch_at)
        last_nonzero_at = to_iso_utc(last_nonzero_at)

        window_start = datetime.now(timezone.utc) - timedelta(hours=24)
        try:
            raw_query = HotspotsRecord.query.filter(HotspotsRecord.acq_datetime >= window_start)
            count_raw = raw_query.count()
            items_raw = (
                raw_query.order_by(HotspotsRecord.acq_datetime.desc())
                .limit(500)
                .all()
            )
            records_all = raw_query.all()
        except SQLAlchemyError:
            current_app.logger.exception("[API] Hotspots records lookup failed")
            count_raw = 0
            items_raw = []
            records_all = []

        items_significant = [item for item in items_raw if is_significant_record(item, config)]

        if isinstance(count_significant_cache, int):
            count_significant = count_significant_cache
        else:
            count_significant = len([item for item in records_all if is_significant_record(item, config)])

        items_payload_raw = [_hotspot_payload(item) for item in items_raw]
        items_payload_significant = [_hotspot_payload(item) for item in items_significant]

        if mode == "significant":
            items_payload = items_payload_significant
        else:
            items_payload = items_payload_raw

        cache_response = {
            "available": True if config.enabled else False,
            "last_fetch_at": last_fetch_at,
            "last_fetch_count": last_fetch_count,
            "count_24h": count_raw,
            "count_all": count_raw,
            "count_24h_raw": count_raw,
            "count_24h_significant": count_significant,
            "count_significant": count_significant,
            "last_nonzero_at": last_nonzero_at,
            "items_24h": items_payload,
            "items": items_payload,
            "items_24h_raw": items_payload_raw,
            "items_24h_significant": items_payload_significant,
            "mode": mode,
        }

    response = jsonify(cache_response)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@api_bp.get("/api/hotspots/diagnose")
def get_hotspots_diagnose():
    if not _require_admin_user():
        return jsonify({"ok": False, "error": "Admin access required"}), 403
    config = HotspotsConfig.from_env()
    payload = diagnose_firms(config, current_app.logger)
    payload["ok"] = True
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@api_bp.get("/api/copernicus/latest")
def get_copernicus_latest():
    cache = load_preview_cache()
    default_mode = resolve_mode(cache)
    latest_entry = resolve_preview_entry(cache, "latest")
    best_entry = resolve_preview_entry(cache, "best")

    latest_bbox = resolve_copernicus_bbox(latest_entry)
    best_bbox = resolve_copernicus_bbox(best_entry)
    latest_preview_url = resolve_preview_url(latest_entry)
    best_preview_url = resolve_preview_url(best_entry)

    latest_payload = build_preview_payload(
        latest_entry,
        latest_preview_url,
        "latest",
        latest_bbox,
    )
    best_payload = build_preview_payload(
        best_entry,
        best_preview_url,
        "best",
        best_bbox,
    )

    modes_payload = {"latest": latest_payload, "best": best_payload}
    active_payload = modes_payload.get(default_mode) or best_payload or latest_payload

    status_reason = "ready" if active_payload["available"] else "missing_preview"
    if not active_payload["available"]:
        status_reason = "no_record" if active_payload["status"] == "UNAVAILABLE" else "error"
        current_app.logger.warning(
            "[API] Copernicus missing image mode=%s status=%s reason=%s product_id=%s cloud_cover=%s bbox=%s",
            active_payload["mode"],
            active_payload["status"],
            status_reason,
            active_payload.get("product_id"),
            active_payload.get("cloud_cover"),
            active_payload.get("bbox"),
        )

    current_app.logger.info(
        "[API] Copernicus preview mode=%s status=%s bbox=%s product_id=%s",
        active_payload["mode"],
        active_payload["status"],
        active_payload.get("bbox"),
        active_payload.get("product_id"),
    )

    return jsonify(
        {
            "mode": active_payload["mode"],
            "default_mode": default_mode,
            "available": active_payload["available"],
            "bbox": active_payload.get("bbox"),
            "preview_path": active_payload.get("preview_path"),
            "preview_url": active_payload.get("preview_url"),
            "status": active_payload.get("status"),
            "status_label": active_payload.get("status_label"),
            "status_reason": status_reason,
            "status_detail": active_payload.get("status_detail"),
            "status_badge_class": active_payload.get("status_badge_class"),
            "modes": modes_payload,
        }
    )

def _sentieri_file_paths() -> tuple[Path, Path]:
    data_dir = Path(current_app.root_path) / "static" / "data"
    return data_dir / "trails.geojson", data_dir / "pois.geojson"


def _sentieri_error_response(error: dict[str, object] | None, *, fallback_message: str) -> tuple[object, int]:
    if not error:
        return jsonify({"ok": False, "error": fallback_message}), 400
    message = str(error.get("message") or fallback_message)
    line = error.get("line")
    status = 404 if "mancante" in message else 400
    payload: dict[str, object] = {"ok": False, "error": message}
    if line:
        payload["line"] = line
    return jsonify(payload), status


@api_bp.get("/api/sentieri/trails")
def sentieri_trails():
    """Return the trails GeoJSON payload or an error response."""
    trails_path, _ = _sentieri_file_paths()
    _, data, error = read_geojson_file(trails_path)
    if error:
        return _sentieri_error_response(error, fallback_message="trails.geojson non disponibile")

    report = validate_feature_collection(data, kind="trails")
    if not report["ok"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "trails.geojson non valido",
                    "details": report["errors"],
                }
            ),
            400,
        )
    return jsonify(data)


@api_bp.get("/api/sentieri/pois")
def sentieri_pois():
    """Return the POI GeoJSON payload or an error response."""
    _, pois_path = _sentieri_file_paths()
    _, data, error = read_geojson_file(pois_path)
    if error:
        return _sentieri_error_response(error, fallback_message="pois.geojson non disponibile")

    report = validate_feature_collection(data, kind="pois")
    if not report["ok"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "pois.geojson non valido",
                    "details": report["errors"],
                }
            ),
            400,
        )
    return jsonify(data)


@api_bp.get("/api/sentieri/stats")
def sentieri_stats():
    """Return KPI for sentieri: totals, km sum, and POI count."""
    trails_path, pois_path = _sentieri_file_paths()

    _, trails_data, trails_error = read_geojson_file(trails_path)
    if trails_error:
        return _sentieri_error_response(trails_error, fallback_message="trails.geojson non disponibile")

    _, pois_data, pois_error = read_geojson_file(pois_path)
    if pois_error:
        return _sentieri_error_response(pois_error, fallback_message="pois.geojson non disponibile")

    trails_report = validate_feature_collection(trails_data, kind="trails")
    pois_report = validate_feature_collection(pois_data, kind="pois")
    if not trails_report["ok"] or not pois_report["ok"]:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "GeoJSON non valido",
                    "details": (trails_report["errors"] + pois_report["errors"])[:10],
                }
            ),
            400,
        )

    total_km = 0.0
    for feature in trails_data.get("features", []):
        km_value = feature.get("properties", {}).get("km")
        try:
            total_km += float(km_value)
        except (TypeError, ValueError):
            continue

    return jsonify(
        {
            "ok": True,
            "trails": trails_report["count"],
            "total_km": round(total_km, 2),
            "pois": pois_report["count"],
        }
    )


@api_bp.route("/api/force_update", methods=["GET", "POST"])
def force_update():
    """Force update of tremor data from INGV source"""
    try:
        ingv_url = os.getenv("INGV_COLORED_URL", "")
        csv_path = get_curva_csv_path()

        result = process_colored_png_to_csv(ingv_url, csv_path)
        last_ts_value = None
        if result.get("last_ts"):
            parsed = pd.to_datetime(result["last_ts"], utc=True, errors="coerce")
            if pd.notna(parsed):
                last_ts_value = parsed.to_pydatetime()
        record_csv_read(int(result.get("rows", 0)), last_ts_value)
        record_csv_update(int(result.get("rows", 0)), last_ts_value, error_message=None)
        current_app.logger.info("[API] Force update generated %s rows", result.get("rows"))

        return jsonify({
            "ok": True,
            "rows": result["rows"],
            "last_ts": to_iso_utc(result.get("last_ts")),
            "output_path": result["output_path"]
        }), 200

    except Exception as e:
        current_app.logger.exception("[API] Force update failed")
        record_csv_error(str(e))
        record_csv_update(None, None, error_message=str(e))
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
