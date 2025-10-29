import os
from pathlib import Path

import pandas as pd
from flask import Blueprint, current_app, jsonify, request

from ..utils.metrics import record_csv_error, record_csv_read
from backend.utils.extract_png import process_png_to_csv

api_bp = Blueprint("api", __name__)

@api_bp.get("/api/curva")
def get_curva():
    """Return curva.csv data as JSON with no-cache headers"""
    csv_path_setting = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH") or "/var/tmp/curva.csv"
    csv_path = Path(csv_path_setting)

    fallback_used = False
    preloaded_df = None

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
                    preloaded_df = pd.read_csv(fallback_path, parse_dates=["timestamp"])
                    preloaded_df.to_csv(csv_path, index=False)
                    fallback_used = True
                    current_app.logger.info(
                        "[API] Served fallback curva.csv from %s", fallback_path
                    )
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
        df = (
            preloaded_df
            if preloaded_df is not None
            else pd.read_csv(csv_path, parse_dates=["timestamp"])
        )
        last_ts = df["timestamp"].max() if not df.empty else None
        record_csv_read(len(df), last_ts)

        if df.empty:
            return jsonify({
                "ok": True,
                "data": [],
                "last_ts": None,
                "rows": 0
            })

        df = df.sort_values("timestamp")
        data = df.to_dict(orient="records")

        payload = {
            "ok": True,
            "data": data,
            "last_ts": last_ts.isoformat() if pd.notna(last_ts) else None,
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
            df = pd.read_csv(csv_path, parse_dates=["timestamp"])
            last_ts = df["timestamp"].max() if not df.empty else None
            record_csv_read(len(df), last_ts)
            if not df.empty:
                current_value = float(df["value"].iloc[-1])
                above_threshold = current_value > threshold
                last_update = last_ts.isoformat() if pd.notna(last_ts) else None

                return jsonify({
                    "ok": True,
                    "current_value": current_value,
                    "above_threshold": above_threshold,
                    "threshold": threshold,
                    "last_update": last_update,
                    "total_points": len(df)
                })

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

@api_bp.route("/api/force_update", methods=["GET", "POST"])
def force_update():
    """Force update of tremor data from INGV source"""
    try:
        ingv_url = os.getenv('INGV_URL', 'https://www.ct.ingv.it/RMS_Etna/2.png')
        csv_path_setting = current_app.config.get('CURVA_CSV_PATH') or current_app.config.get('CSV_PATH') or '/var/tmp/curva.csv'

        result = process_png_to_csv(ingv_url, csv_path_setting)
        last_ts_value = None
        if result.get("last_ts"):
            try:
                parsed = pd.to_datetime(result["last_ts"])
                last_ts_value = parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed
            except Exception:
                last_ts_value = None
        record_csv_read(int(result.get("rows", 0)), last_ts_value)
        current_app.logger.info("[API] Force update generated %s rows", result.get("rows"))

        return jsonify({
            "ok": True,
            "rows": result["rows"],
            "last_ts": result["last_ts"],
            "output_path": result["output_path"]
        }), 200

    except Exception as e:
        current_app.logger.exception("[API] Force update failed")
        record_csv_error(str(e))
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500
