import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from ..utils.metrics import record_csv_error, record_csv_read, record_csv_update
from ..utils.auth import get_current_user
from ..models.hotspots_cache import HotspotsCache
from ..models.hotspots_record import HotspotsRecord
from ..services.copernicus import (
    fetch_latest_copernicus_items,
    get_latest_copernicus_image,
    is_available_status,
    resolve_copernicus_bbox,
    resolve_copernicus_image_url,
    resolve_latest_and_available_items,
)
from backend.utils.extract_png import process_png_to_csv
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
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH") or "/var/tmp/curva.csv"
    csv_path = Path(csv_path_setting)

    fallback_used = False
    preloaded_df = None
    preloaded_reason: str | None = None

    if not csv_path.exists() or csv_path.stat().st_size <= 20:
        try:
            ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
            result = process_png_to_csv(ingv_url, str(csv_path))
            current_app.logger.info("[API] Auto-generated curva.csv with %s rows", result['rows'])
        except Exception as e:
            current_app.logger.exception("[API] Failed to auto-generate curva.csv")
            record_csv_error(str(e))

            fallback_setting = current_app.config.get("CURVA_FALLBACK_PATH")
            fallback_path = (
                Path(fallback_setting)
                if fallback_setting
                else Path(current_app.root_path).parent / "data" / "curva.csv"
            )

            if fallback_path.exists() and fallback_path.stat().st_size > 20:
                try:
                    raw_fallback_df = pd.read_csv(fallback_path)
                    preloaded_df, preloaded_reason = _prepare_tremor_dataframe(raw_fallback_df)
                    if preloaded_reason is None:
                        fallback_used = True
                        df_to_save = preloaded_df.copy()
                        df_to_save["timestamp"] = df_to_save["timestamp"].apply(to_iso_utc)
                        df_to_save.to_csv(csv_path, index=False)
                        current_app.logger.info(
                            "[API] Served fallback curva.csv from %s", fallback_path
                        )
                    else:
                        record_csv_error(f"fallback::{preloaded_reason}")
                except Exception as fallback_exc:
                    current_app.logger.exception(
                        "[API] Failed to load fallback curva.csv from %s", fallback_path
                    )
                    record_csv_error(f"fallback_error::{fallback_exc}")
                    preloaded_df = None

            if preloaded_df is None:
                return jsonify({
                    "ok": False,
                    "error": "Dati INGV non disponibili al momento",
                    "csv_path": str(csv_path),
                    "placeholder_reason": "bootstrap_failed",
                }), 503

    try:
        if preloaded_df is not None:
            df = preloaded_df.copy()
            reason = preloaded_reason
        else:
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
            if fallback_used:
                payload["source"] = "fallback"
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
        if fallback_used:
            payload["source"] = "fallback"

        response = jsonify(payload)

        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        current_app.logger.exception("[API] Failed to read curva.csv")
        record_csv_error(str(e))
        return jsonify({
            "ok": False,
            "error": str(e),
            "csv_path": str(csv_path)
        }), 500

@api_bp.route("/api/status")
def get_status():
    """Return current status and metrics"""
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH") or "/var/tmp/curva.csv"
    csv_path = Path(csv_path_setting)
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
    record = get_latest_copernicus_image()
    bbox = resolve_copernicus_bbox(record)
    items = fetch_latest_copernicus_items(bbox, current_app.logger)
    latest_item, available_item = resolve_latest_and_available_items(items)
    latest_status = latest_item.status if latest_item else None
    latest_is_available = is_available_status(latest_status)

    image_url = resolve_copernicus_image_url(record)
    has_image = image_url is not None
    available_image_date = (
        to_iso_utc(record.acquired_at)
        if record
        else to_iso_utc(available_item.acquired_at) if available_item else None
    )
    available_image_product_id = (
        record.product_id if record else available_item.product_id if available_item else None
    )

    is_fallback_image = bool(has_image and latest_item and not latest_is_available)
    status = "available" if has_image else "processing"
    status_label = "Immagine disponibile" if has_image else "In elaborazione"
    status_reason = "ready" if has_image else "image_pending"
    status_detail = (
        "Disponibile per la visualizzazione." if has_image else "Miniatura in elaborazione."
    )

    if is_fallback_image:
        status_label = "Ultima immagine disponibile"
        status_reason = "fallback_image"
        status_detail = "L’immagine più recente è in fase di elaborazione Copernicus."

    if not has_image:
        if record is None:
            status = "unavailable"
            status_label = "Non disponibile"
            status_reason = "no_record"
            status_detail = "Dati in aggiornamento."
        elif not record.image_path:
            status_reason = "missing_image_path"
            status_detail = "Percorso immagine mancante."
        else:
            static_folder = current_app.static_folder or ""
            image_path = Path(static_folder) / record.image_path
            if not image_path.exists():
                status_reason = "image_file_missing"
                status_detail = "File immagine non ancora presente."
        current_app.logger.warning(
            "[API] Copernicus missing image status=%s reason=%s product_id=%s cloud_cover=%s bbox=%s",
            status,
            status_reason,
            record.product_id if record else None,
            record.cloud_cover if record else None,
            bbox,
        )
    current_app.logger.info(
        "[API] Copernicus latest status=%s latest_status=%s fallback=%s bbox=%s product_id=%s",
        status,
        latest_status,
        is_fallback_image,
        bbox,
        record.product_id if record else None,
    )
    return jsonify(
        {
            "available": has_image,
            "acquired_at": to_iso_utc(record.acquired_at) if record else None,
            "product_id": record.product_id if record else None,
            "cloud_cover": record.cloud_cover if record else None,
            "cloud_coverage": record.cloud_cover if record else None,
            "bbox": bbox,
            "image_path": record.image_path if record else None,
            "image_url": image_url,
            "created_at": to_iso_utc(record.created_at) if record else None,
            "latest_acquisition_date": (
                to_iso_utc(latest_item.acquired_at) if latest_item else None
            ),
            "latest_acquisition_status": latest_status,
            "available_image_date": available_image_date,
            "available_image_product_id": available_image_product_id,
            "is_fallback_image": is_fallback_image,
            "status": status,
            "status_label": status_label,
            "status_reason": status_reason,
            "status_detail": status_detail,
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
        ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
        csv_path_setting = current_app.config.get('CURVA_CSV_PATH') or current_app.config.get('CSV_PATH') or '/var/tmp/curva.csv'

        result = process_png_to_csv(ingv_url, csv_path_setting)
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
