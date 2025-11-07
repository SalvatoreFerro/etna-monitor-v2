import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify
import pandas as pd
import time
import hashlib

from backend.utils.time import to_iso_utc
from app.security import serialize_csp

status_bp = Blueprint("status", __name__)

@status_bp.route("/api/status")
def get_status():
    """Extended status endpoint with comprehensive system information"""
    try:
        csv_path = current_app.config.get("CURVA_CSV_PATH") or current_app.config.get("CSV_PATH") or "/var/tmp/curva.csv"
        threshold = float(os.getenv("DEFAULT_THRESHOLD", "2.0"))

        status_data = {
            "ok": True,
            "timestamp": time.time(),
            "uptime_s": int(time.time() - getattr(get_status, '_start_time', time.time())),
            "csv_path": csv_path,
            "threshold": threshold,
            "build_sha": os.getenv("RENDER_GIT_COMMIT", "unknown")[:8],
            "render_region": os.getenv("RENDER_REGION", "unknown")
        }
        
        if Path(csv_path).exists():
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:
                status_data.update({
                    "ok": False,
                    "csv_error": str(exc),
                    "last_ts": None,
                    "rows": 0,
                    "current_value": None,
                    "above_threshold": False
                })
            else:
                if "timestamp" not in df.columns:
                    status_data.update({
                        "ok": False,
                        "reason": "missing_timestamp",
                        "last_ts": None,
                        "rows": 0,
                        "current_value": None,
                        "above_threshold": False,
                        "data_age_minutes": None,
                    })
                else:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                    df = df.dropna(subset=["timestamp"])

                    if df.empty:
                        status_data.update({
                            "ok": False,
                            "reason": "empty_data",
                            "last_ts": None,
                            "rows": 0,
                            "current_value": None,
                            "above_threshold": False,
                            "data_age_minutes": None,
                        })
                    else:
                        df = df.sort_values("timestamp")
                        last_ts = df["timestamp"].iloc[-1]
                        current_value = df["value"].iloc[-1] if len(df) > 0 else None
                        status_data.update({
                            "last_ts": to_iso_utc(last_ts),
                            "rows": len(df),
                            "current_value": float(current_value) if current_value is not None else None,
                            "above_threshold": bool(current_value > threshold) if current_value is not None else False,
                            "data_age_minutes": int((time.time() - last_ts.timestamp()) / 60) if last_ts else None
                        })
        else:
            status_data.update({
                "csv_exists": False,
                "last_ts": None,
                "rows": 0,
                "current_value": None,
                "above_threshold": False
            })
        
        return jsonify(status_data), 200
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "timestamp": time.time()
        }), 500

get_status._start_time = time.time()

@status_bp.route("/readyz")
def readiness_check():
    """Kubernetes-style readiness probe"""
    return jsonify({"ready": True}), 200

@status_bp.route("/livez")
def liveness_check():
    """Kubernetes-style liveness probe"""
    return jsonify({"alive": True}), 200


@status_bp.route("/__csp")
def show_csp_header():
    """Expose the active Content Security Policy header for diagnostics."""

    policy = current_app.config.get("BASE_CONTENT_SECURITY_POLICY")
    if not policy:
        body = "Content-Security-Policy header not configured."
    else:
        body = serialize_csp(policy)

    response = current_app.response_class(f"{body}\n", mimetype="text/plain")
    return response
