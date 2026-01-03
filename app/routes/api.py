import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from ..utils.metrics import record_csv_error, record_csv_read, record_csv_update
from ..models.hotspots_cache import HotspotsCache
from ..models.hotspots_record import HotspotsRecord
from backend.utils.extract_png import process_png_to_csv
from backend.utils.time import to_iso_utc
from backend.services.hotspots.config import HotspotsConfig

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


def _normalize_confidence(value: str | None) -> str:
    if not value:
        return "unknown"
    raw = value.strip().lower()
    if raw in {"low", "l"}:
        return "low"
    if raw in {"nominal", "n", "medium", "med"}:
        return "nominal"
    if raw in {"high", "h"}:
        return "high"
    return raw


def _confidence_rank(value: str | None) -> int:
    normalized = _normalize_confidence(value)
    return {"low": 0, "nominal": 1, "high": 2}.get(normalized, -1)


def _is_significant_hotspot(record: HotspotsRecord, config: HotspotsConfig) -> bool:
    if _confidence_rank(record.confidence) < _confidence_rank(config.significant_confidence_min):
        return False
    brightness_ok = record.brightness is not None and record.brightness >= config.significant_brightness_min
    frp_ok = record.frp is not None and record.frp >= config.significant_frp_min
    return brightness_ok or frp_ok


def _prepare_tremor_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Normalise timestamp typing and detect empty datasets."""
    if "timestamp" not in raw_df.columns:
        return pd.DataFrame(columns=["timestamp", "value"]), "missing_timestamp"

    df = raw_df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

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
            "count_all": 0,
            "count_significant": 0,
            "last_nonzero_at": None,
            "items_24h": [],
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
            count_all = (
                HotspotsRecord.query.filter(HotspotsRecord.acq_datetime >= window_start)
                .count()
            )
            items = (
                HotspotsRecord.query.filter(HotspotsRecord.acq_datetime >= window_start)
                .order_by(HotspotsRecord.acq_datetime.desc())
                .limit(500)
                .all()
            )
        except SQLAlchemyError:
            current_app.logger.exception("[API] Hotspots records lookup failed")
            count_all = 0
            items = []

        items_payload = [
            {
                "id": item.fingerprint,
                "time_utc": to_iso_utc(item.acq_datetime),
                "lat": item.lat,
                "lon": item.lon,
                "source": item.source,
                "satellite": item.satellite,
                "confidence": item.confidence,
                "intensity": {
                    "frp": item.frp,
                    "brightness": item.brightness,
                    "unit": item.intensity_unit or "unknown",
                },
                "status": item.status or "unknown",
                "maps_url": f"https://www.google.com/maps?q={item.lat},{item.lon}",
            }
            for item in items
        ]

        if mode == "significant":
            filtered_items = [
                item
                for item in items
                if _is_significant_hotspot(item, config)
            ]
        else:
            filtered_items = items

        filtered_payload = [
            {
                "id": item.fingerprint,
                "time_utc": to_iso_utc(item.acq_datetime),
                "lat": item.lat,
                "lon": item.lon,
                "source": item.source,
                "satellite": item.satellite,
                "confidence": item.confidence,
                "intensity": {
                    "frp": item.frp,
                    "brightness": item.brightness,
                    "unit": item.intensity_unit or "unknown",
                },
                "status": item.status or "unknown",
                "maps_url": f"https://www.google.com/maps?q={item.lat},{item.lon}",
            }
            for item in filtered_items
        ]

        if isinstance(count_significant_cache, int):
            count_significant = count_significant_cache
        else:
            count_significant = len([item for item in items if _is_significant_hotspot(item, config)])

        cache_response = {
            "available": True if config.enabled else False,
            "last_fetch_at": last_fetch_at,
            "last_fetch_count": last_fetch_count,
            "count_24h": count_all,
            "count_all": count_all,
            "count_significant": count_significant,
            "last_nonzero_at": last_nonzero_at,
            "items_24h": items_payload,
            "items": filtered_payload,
            "mode": mode,
        }

    response = jsonify(cache_response)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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
