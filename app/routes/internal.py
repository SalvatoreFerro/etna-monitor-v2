"""Internal-only health endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter

from flask import Blueprint, current_app, jsonify, request

from app.services.telegram_service import TelegramService

internal_bp = Blueprint("internal", __name__, url_prefix="/internal")
_CRON_COOLDOWN = timedelta(minutes=5)
_cron_lock = Lock()
_last_cron_run: datetime | None = None


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


@internal_bp.route("/cron/check-alerts", methods=["POST"])
def cron_check_alerts():
    global _last_cron_run
    secret = (current_app.config.get("CRON_SECRET") or "").strip()
    provided_key = (request.args.get("key") or "").strip()
    if not provided_key:
        provided_key = (
            request.headers.get("X-CRON-KEY")
            or request.headers.get("X-Cron-Key")
            or ""
        ).strip()

    if not secret or provided_key != secret:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    started_at = perf_counter()
    sent = 0
    skipped = 0
    reason = "unknown"
    now = datetime.now(timezone.utc)
    current_app.logger.info("[CRON] check-alerts started")
    try:
        with _cron_lock:
            if _last_cron_run and now - _last_cron_run < _CRON_COOLDOWN:
                reason = "cooldown"
                return jsonify(
                    {
                        "ok": True,
                        "sent": sent,
                        "skipped": skipped,
                        "reason": reason,
                        "ts": now.isoformat(),
                    }
                )
            _last_cron_run = now

        telegram_service = TelegramService()
        result = telegram_service.check_and_send_alerts(raise_on_error=True)
        sent = int(result.get("sent", 0))
        skipped = int(result.get("skipped", 0))
        reason = result.get("reason") or "completed"
        payload = {
            "ok": True,
            "sent": sent,
            "skipped": skipped,
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        return jsonify(payload)
    except Exception as exc:  # pragma: no cover - defensive guard
        reason = "internal_error"
        current_app.logger.exception("[CRON] check-alerts failed: %s", exc)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "internal_error",
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        current_app.logger.info(
            "[CRON] check-alerts finished sent=%s skipped=%s reason=%s duration_ms=%.1f",
            sent,
            skipped,
            reason,
            duration_ms,
        )
