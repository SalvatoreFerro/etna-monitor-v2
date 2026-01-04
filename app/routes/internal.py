"""Internal-only health endpoints."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import or_, text

from app.models import db
from app.models.user import User
from app.services.telegram_service import TelegramService
from config import Config

internal_bp = Blueprint("internal", __name__, url_prefix="/internal")
_CRON_COOLDOWN = timedelta(minutes=5)
_cron_lock = Lock()
_last_cron_run: datetime | None = None


def _get_request_id() -> str | None:
    for header in ("X-Request-Id", "X-Request-ID", "X-Amzn-Trace-Id", "X-Cloud-Trace-Context"):
        value = (request.headers.get(header) or "").strip()
        if value:
            return value
    return None


def _get_client_ip() -> str | None:
    forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _collect_csv_diagnostics() -> tuple[dict, pd.DataFrame | None, str | None]:
    data_dir = os.getenv("DATA_DIR", "data")
    csv_path = Path(data_dir) / "curva.csv"
    diagnostics: dict = {
        "csv_path": str(csv_path),
        "csv_exists": csv_path.exists(),
        "csv_size_bytes": None,
        "csv_mtime": None,
        "last_point_ts": None,
        "moving_avg": None,
        "threshold_used": None,
    }

    if not csv_path.exists():
        return diagnostics, None, "csv_missing"

    try:
        stat = csv_path.stat()
        diagnostics["csv_size_bytes"] = stat.st_size
        diagnostics["csv_mtime"] = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        diagnostics["csv_size_bytes"] = None
        diagnostics["csv_mtime"] = None

    if diagnostics["csv_size_bytes"] == 0:
        return diagnostics, None, "csv_empty"

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("[CRON] Failed reading CSV for diagnostics: %s", exc)
        return diagnostics, None, "dataset_invalid"

    if "timestamp" not in df.columns or "value" not in df.columns:
        return diagnostics, None, "dataset_invalid"

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if df.empty:
        return diagnostics, None, "csv_empty"

    recent_data = df.tail(10)
    window_size = 5
    moving_avg = TelegramService().calculate_moving_average(
        recent_data["value"].tolist(), window_size=window_size
    )
    last_ts = recent_data["timestamp"].iloc[-1]
    diagnostics["last_point_ts"] = (
        last_ts.to_pydatetime().isoformat()
        if hasattr(last_ts, "to_pydatetime")
        else str(last_ts)
    )
    diagnostics["moving_avg"] = float(moving_avg)
    diagnostics["threshold_used"] = float(Config.ALERT_THRESHOLD_DEFAULT)

    return diagnostics, df, None


def _collect_db_diagnostics() -> tuple[dict, bool]:
    diagnostics = {
        "users_subscribed_count": None,
        "premium_subscribed_count": None,
        "db_error": None,
    }
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("[CRON] Database unavailable: %s", exc)
        diagnostics["db_error"] = str(exc)
        return diagnostics, False

    try:
        users_count = (
            User.query.filter(
                User.telegram_opt_in.is_(True),
                or_(
                    User.telegram_chat_id.isnot(None),
                    User.chat_id.isnot(None),
                ),
            )
            .count()
        )
        premium_count = (
            User.query.filter(
                User.telegram_opt_in.is_(True),
                or_(
                    User.telegram_chat_id.isnot(None),
                    User.chat_id.isnot(None),
                ),
                User.premium_status_clause(),
            )
            .count()
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("[CRON] Database diagnostics failed: %s", exc)
        diagnostics["db_error"] = str(exc)
        return diagnostics, False

    diagnostics["users_subscribed_count"] = int(users_count or 0)
    diagnostics["premium_subscribed_count"] = int(premium_count or 0)
    return diagnostics, True


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
    started_at = perf_counter()
    now = datetime.now(timezone.utc)
    request_id = _get_request_id()
    client_ip = _get_client_ip()
    query_string = request.query_string.decode("utf-8")
    current_app.logger.info(
        "[CRON] check-alerts started request_id=%s ip=%s path=%s query=%s",
        request_id,
        client_ip,
        request.path,
        query_string,
    )

    secret = (current_app.config.get("CRON_SECRET") or "").strip()
    provided_key = (request.args.get("key") or "").strip()
    if not provided_key:
        provided_key = (
            request.headers.get("X-CRON-KEY")
            or request.headers.get("X-Cron-Key")
            or ""
        ).strip()

    authorized = bool(secret and provided_key == secret)
    status_code = 200
    sent = 0
    skipped = 0
    cooldown_skipped = 0
    reason = "unknown"
    response_payload: dict | None = None
    diagnostic_snapshot: dict = {}

    try:
        if not authorized:
            status_code = 401
            reason = "unauthorized"
            response_payload = {"ok": False, "error": "unauthorized"}
        if response_payload is None:
            telegram_service = TelegramService()

            csv_diagnostics, dataset, csv_reason = _collect_csv_diagnostics()
            db_diagnostics, db_ok = _collect_db_diagnostics()
            diagnostic_snapshot.update(csv_diagnostics)
            diagnostic_snapshot.update(db_diagnostics)

            with _cron_lock:
                if _last_cron_run and now - _last_cron_run < _CRON_COOLDOWN:
                    reason = "cooldown"
                    response_payload = {
                        "ok": True,
                        "sent": sent,
                        "skipped": skipped,
                        "reason": reason,
                        "ts": now.isoformat(),
                    }
                else:
                    _last_cron_run = now

            if response_payload is None:
                if not telegram_service.is_configured():
                    reason = "no_token_configured"
                    response_payload = {
                        "ok": True,
                        "skipped": True,
                        "reason": reason,
                        "ts": now.isoformat(),
                    }

            if response_payload is None and csv_reason:
                reason = csv_reason
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None and (dataset is None or dataset.empty):
                reason = "dataset_invalid"
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None and not db_ok:
                reason = "db_unavailable"
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None:
                result = telegram_service.check_and_send_alerts(raise_on_error=True)
                sent = int(result.get("sent", 0))
                skipped = int(result.get("skipped", 0))
                cooldown_skipped = int(result.get("cooldown_skipped", 0))
                reason = result.get("reason") or "completed"
                response_payload = {
                    "ok": True,
                    "sent": sent,
                    "skipped": skipped,
                    "reason": reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
    except Exception as exc:  # pragma: no cover - defensive guard
        reason = "exception"
        current_app.logger.exception(
            "[CRON] check-alerts failed request_id=%s: %s", request_id, exc
        )
        response_payload = {
            "ok": False,
            "error": "exception",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        if response_payload is not None:
            response_payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
            response_payload["duration_ms"] = round(duration_ms, 1)
            if authorized:
                diagnostic_snapshot["sent_count"] = sent
                diagnostic_snapshot["skipped_count"] = skipped
                diagnostic_snapshot["cooldown_skipped_count"] = cooldown_skipped
                response_payload["diagnostic"] = diagnostic_snapshot
        current_app.logger.info(
            "[CRON] check-alerts finished request_id=%s sent=%s skipped=%s reason=%s duration_ms=%.1f",
            request_id,
            sent,
            skipped,
            reason,
            duration_ms,
        )
    return jsonify(response_payload), status_code
