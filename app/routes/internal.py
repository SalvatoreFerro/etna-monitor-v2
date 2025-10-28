"""Internal-only health endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify


internal_bp = Blueprint("internal", __name__, url_prefix="/internal")


@internal_bp.route("/worker/health", methods=["GET"])
def worker_health():
    data_dir = Path(current_app.config.get("DATA_DIR", "/var/tmp"))
    heartbeat_path = data_dir / "worker-heartbeat.json"

    if not heartbeat_path.exists():
        return jsonify({"ok": False, "error": "missing_heartbeat"}), 503

    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        current_app.logger.warning("[WORKER] Invalid heartbeat payload: %s", exc)
        return jsonify({"ok": False, "error": "invalid_payload"}), 500

    timestamp_raw = payload.get("timestamp")
    if not timestamp_raw:
        return jsonify({"ok": False, "error": "missing_timestamp"}), 500

    try:
        beat_ts = datetime.fromisoformat(timestamp_raw)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_timestamp"}), 500

    if beat_ts.tzinfo is None:
        beat_ts = beat_ts.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - beat_ts).total_seconds()
    tolerance = int(current_app.config.get("WORKER_HEARTBEAT_INTERVAL", 30)) * 3
    healthy = age_seconds <= tolerance

    status_code = 200 if healthy else 503
    return (
        jsonify(
            {
                "ok": healthy,
                "age_seconds": age_seconds,
                "heartbeat_timestamp": beat_ts.isoformat(),
                "pid": payload.get("pid"),
            }
        ),
        status_code,
    )

