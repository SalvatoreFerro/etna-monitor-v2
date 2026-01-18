"""Internal-only health endpoints."""

from __future__ import annotations

import json
import os
import traceback as tb
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import perf_counter

import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import or_, text

from app.models import CronRun, db
from app.models.user import User
from app.services.runlog_service import log_cron_run
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


def _resolve_pipeline_id() -> str | None:
    pipeline_id = (
        request.headers.get("X-Pipeline-Id")
        or request.headers.get("X-PIPELINE-ID")
        or request.args.get("pipeline_id")
        or ""
    ).strip()
    return pipeline_id or None


def _get_client_ip() -> str | None:
    forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def _resolve_cron_key() -> str:
    provided_key = (request.args.get("key") or "").strip()
    if provided_key:
        return provided_key
    return (
        request.headers.get("X-CRON-KEY")
        or request.headers.get("X-Cron-Key")
        or ""
    ).strip()


def _is_authorized_cron() -> bool:
    secret = (current_app.config.get("CRON_SECRET") or "").strip()
    provided_key = _resolve_cron_key()
    return bool(secret and provided_key == secret)


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
        "peak_value": None,
        "moving_avg_real": None,
        "threshold_used": None,
        "threshold_source": None,
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
    window_size = max(1, int(Config.ALERT_MOVING_AVG_WINDOW))
    moving_avg_real = TelegramService().calculate_moving_average(
        recent_data["value"].tolist(), window_size=window_size
    )
    peak_value = float(recent_data["value"].max())
    last_ts = recent_data["timestamp"].iloc[-1]
    diagnostics["last_point_ts"] = (
        last_ts.to_pydatetime().isoformat()
        if hasattr(last_ts, "to_pydatetime")
        else str(last_ts)
    )
    diagnostics["moving_avg"] = float(peak_value)
    diagnostics["peak_value"] = float(peak_value)
    diagnostics["moving_avg_real"] = float(moving_avg_real)
    diagnostics["threshold_used"] = float(Config.ALERT_THRESHOLD_DEFAULT)
    diagnostics["threshold_source"] = "default"

    return diagnostics, df, None


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    pipeline_id = _resolve_pipeline_id()
    client_ip = _get_client_ip()
    query_string = request.query_string.decode("utf-8")
    current_app.logger.info(
        "[CRON] check-alerts started request_id=%s ip=%s path=%s query=%s",
        request_id,
        client_ip,
        request.path,
        query_string,
    )

    authorized = _is_authorized_cron()
    status_code = 200
    sent = 0
    skipped = 0
    cooldown_skipped = 0
    free_candidates_count = 0
    free_trial_sent_count = 0
    skipped_free_already_consumed_count = 0
    skipped_not_premium_count = 0
    reason = "unknown"
    skipped_by_reason: dict[str, int] = {}
    required_reasons = [
        "below_threshold",
        "not_premium",
        "no_chat_id",
        "cooldown",
        "already_sent_hysteresis",
        "error",
    ]
    response_payload: dict | None = None
    diagnostic_snapshot: dict = {}
    premium_samples: list[dict] = []

    error_type = None
    error_message = None
    error_traceback = None

    cron_run = CronRun(
        pipeline_id=pipeline_id,
        job_type="check_alerts",
        started_at=now,
        status=None,
        request_id=request_id,
    )
    try:
        db.session.add(cron_run)
        db.session.commit()
    except Exception:  # pragma: no cover - defensive logging
        db.session.rollback()
        current_app.logger.exception("[CRON] Failed to insert cron run start row")

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
            diagnostic_snapshot["rate_limit_minutes"] = int(
                telegram_service.RATE_LIMIT.total_seconds() // 60
            )
            diagnostic_snapshot["renotify_interval_minutes"] = int(
                telegram_service.RENOTIFY_INTERVAL.total_seconds() // 60
            )
            diagnostic_snapshot["hysteresis_delta"] = float(Config.ALERT_HYSTERESIS_DELTA)

            with _cron_lock:
                if _last_cron_run and now - _last_cron_run < _CRON_COOLDOWN:
                    reason = "cooldown"
                    skipped_by_reason["cooldown"] = 1
                    response_payload = {
                        "ok": True,
                        "sent": sent,
                        "skipped": skipped,
                        "reason": reason,
                        "skipped_by_reason": skipped_by_reason,
                        "ts": now.isoformat(),
                    }
                else:
                    _last_cron_run = now

            if response_payload is None:
                if not telegram_service.is_configured():
                    reason = "no_token_configured"
                    skipped_by_reason["exception"] = 1
                    response_payload = {
                        "ok": True,
                        "skipped": True,
                        "reason": reason,
                        "skipped_by_reason": skipped_by_reason,
                        "ts": now.isoformat(),
                    }

            if response_payload is None and csv_reason:
                reason = csv_reason
                skipped_by_reason["dataset_invalid"] = 1
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "skipped_by_reason": skipped_by_reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None and (dataset is None or dataset.empty):
                reason = "dataset_invalid"
                skipped_by_reason["dataset_invalid"] = 1
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "skipped_by_reason": skipped_by_reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None and not db_ok:
                reason = "db_unavailable"
                skipped_by_reason["exception"] = 1
                response_payload = {
                    "ok": True,
                    "skipped": True,
                    "reason": reason,
                    "skipped_by_reason": skipped_by_reason,
                    "ts": now.isoformat(),
                }

            if response_payload is None:
                result = telegram_service.check_and_send_alerts(
                    raise_on_error=True,
                    allow_free=True,
                )
                sent = int(result.get("sent", 0))
                skipped = int(result.get("skipped", 0))
                cooldown_skipped = int(result.get("cooldown_skipped", 0))
                free_candidates_count = int(result.get("free_candidates_count", 0))
                free_trial_sent_count = int(result.get("free_trial_sent_count", 0))
                skipped_free_already_consumed_count = int(
                    result.get("skipped_free_already_consumed_count", 0)
                )
                skipped_not_premium_count = int(
                    result.get("skipped_not_premium_count", 0)
                )
                skipped_by_reason = result.get("skipped_by_reason") or {}
                premium_samples = result.get("premium_samples") or []
                reason = result.get("reason") or "completed"
                response_payload = {
                    "ok": True,
                    "sent": sent,
                    "skipped": skipped,
                    "reason": reason,
                    "skipped_by_reason": skipped_by_reason,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
    except Exception as exc:  # pragma: no cover - defensive guard
        reason = "exception"
        skipped_by_reason["exception"] = skipped_by_reason.get("exception", 0) + 1
        error_type = type(exc).__name__
        error_message = str(exc)
        error_traceback = tb.format_exc()
        current_app.logger.exception(
            "[CRON] check-alerts failed request_id=%s: %s", request_id, exc
        )
        response_payload = {
            "ok": False,
            "error": "exception",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "skipped_by_reason": skipped_by_reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        duration_ms = (perf_counter() - started_at) * 1000
        if response_payload is not None:
            response_payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
            response_payload["duration_ms"] = round(duration_ms, 1)
            if authorized:
                normalized_reasons = {**(skipped_by_reason or {})}
                if "exception" in normalized_reasons and "error" not in normalized_reasons:
                    normalized_reasons["error"] = normalized_reasons.get("error", 0) + int(
                        normalized_reasons.get("exception", 0)
                    )
                for key in required_reasons:
                    normalized_reasons.setdefault(key, 0)
                response_payload["skipped_by_reason"] = normalized_reasons
                diagnostic_snapshot["sent_count"] = sent
                diagnostic_snapshot["skipped_count"] = skipped
                diagnostic_snapshot["cooldown_skipped_count"] = cooldown_skipped
                diagnostic_snapshot["free_candidates_count"] = free_candidates_count
                diagnostic_snapshot["free_trial_sent_count"] = free_trial_sent_count
                diagnostic_snapshot[
                    "skipped_free_already_consumed_count"
                ] = skipped_free_already_consumed_count
                diagnostic_snapshot["skipped_not_premium_count"] = skipped_not_premium_count
                diagnostic_snapshot["skipped_by_reason"] = normalized_reasons
                diagnostic_snapshot["premium_samples"] = premium_samples
                response_payload["diagnostic"] = diagnostic_snapshot
        if error_message is None and response_payload and not response_payload.get("ok"):
            error_message = response_payload.get("error")
        cron_status = "success" if response_payload and response_payload.get("ok") else "error"
        cron_run_payload = {
            "ok": bool(response_payload and response_payload.get("ok")),
            "reason": reason,
            "duration_ms": round(duration_ms, 1),
            "csv_path": diagnostic_snapshot.get("csv_path"),
            "csv_mtime": _parse_optional_datetime(diagnostic_snapshot.get("csv_mtime")),
            "csv_size_bytes": diagnostic_snapshot.get("csv_size_bytes"),
            "last_point_ts": _parse_optional_datetime(diagnostic_snapshot.get("last_point_ts")),
            "moving_avg": diagnostic_snapshot.get("moving_avg"),
            "users_subscribed_count": diagnostic_snapshot.get("users_subscribed_count"),
            "premium_subscribed_count": diagnostic_snapshot.get("premium_subscribed_count"),
            "sent_count": diagnostic_snapshot.get("sent_count"),
            "skipped_count": diagnostic_snapshot.get("skipped_count"),
            "skipped_by_reason": diagnostic_snapshot.get("skipped_by_reason") or skipped_by_reason,
            "error_type": error_type,
            "error_message": error_message,
            "traceback": error_traceback,
            "payload": response_payload,
            "diagnostic_json": diagnostic_snapshot or None,
            "finished_at": datetime.now(timezone.utc),
            "status": cron_status,
        }
        if cron_run.id:
            try:
                for key, value in cron_run_payload.items():
                    setattr(cron_run, key, value)
                db.session.commit()
            except Exception as exc:  # pragma: no cover - defensive log
                db.session.rollback()
                current_app.logger.exception("[CRON] Failed to update cron run log: %s", exc)
        else:
            cron_run_payload.update(
                {
                    "pipeline_id": pipeline_id,
                    "job_type": "check_alerts",
                    "started_at": now,
                    "request_id": request_id,
                }
            )
            try:
                log_cron_run(cron_run_payload)
            except Exception as exc:  # pragma: no cover - defensive log
                current_app.logger.exception("[CRON] Failed to store cron run log: %s", exc)
        current_app.logger.info(
            "[CRON] check-alerts finished request_id=%s sent=%s skipped=%s reason=%s duration_ms=%.1f",
            request_id,
            sent,
            skipped,
            reason,
            duration_ms,
        )
    return jsonify(response_payload), status_code


@internal_bp.route("/cron/debug-user", methods=["GET"])
def cron_debug_user():
    if not _is_authorized_cron():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    email = (request.args.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "missing_email"}), 400

    user = User.query.filter(User.email == email).first()
    if not user:
        return jsonify({"ok": False, "error": "user_not_found"}), 404

    telegram_service = TelegramService()
    dataset = telegram_service._load_dataset()
    now = datetime.now(timezone.utc)
    last_point_value = None
    last_point_ts = None
    moving_avg_real = None
    peak_value = None
    reason = None
    window_size = max(1, int(Config.ALERT_MOVING_AVG_WINDOW))
    event_id = None

    if dataset is None or dataset.empty:
        reason = "dataset_invalid"
    else:
        recent_data = dataset.tail(10)
        last_point_value = float(recent_data["value"].iloc[-1])
        peak_value = float(recent_data["value"].max())
        moving_avg_real = float(
            telegram_service.calculate_moving_average(
                recent_data["value"].tolist(), window_size=window_size
            )
        )
        timestamp = recent_data["timestamp"].iloc[-1]
        event_ts = timestamp.to_pydatetime() if hasattr(timestamp, "to_pydatetime") else timestamp
        event_ts = telegram_service._utc(event_ts)
        last_point_ts = event_ts.isoformat() if event_ts else str(timestamp)
        event_id = telegram_service._compute_event_id(event_ts, peak_value)

    fallback_threshold = float(Config.ALERT_THRESHOLD_DEFAULT)
    threshold_used, threshold_fallback_used = telegram_service._resolve_threshold(user)
    effective_chat_id = telegram_service._resolve_effective_chat_id(user, allow_update=False)
    last_alert_sent_at = telegram_service._utc(user.last_alert_sent_at)
    cooldown_seconds_remaining = 0
    if last_alert_sent_at:
        cooldown_remaining = telegram_service.RATE_LIMIT - (now - last_alert_sent_at)
        if cooldown_remaining.total_seconds() > 0:
            cooldown_seconds_remaining = int(cooldown_remaining.total_seconds())

    will_send = False
    if reason is None:
        if not user.telegram_opt_in:
            reason = "opt_in_false"
        elif not effective_chat_id:
            reason = "no_chat_id"
        elif peak_value is None or peak_value < threshold_used:
            reason = "below_threshold"
        elif user.has_premium_access:
            if telegram_service._is_rate_limited(user, now):
                reason = "cooldown"
            else:
                last_alert_sent_at = telegram_service._utc(user.last_alert_sent_at)
                if not telegram_service._passed_hysteresis(
                    user,
                    threshold_used,
                    peak_value,
                    last_alert_sent_at,
                ):
                    if last_alert_sent_at and now - last_alert_sent_at >= telegram_service.RENOTIFY_INTERVAL:
                        will_send = True
                        reason = "persistent_above_threshold_renotify"
                    else:
                        reason = "already_sent_hysteresis"
                else:
                    will_send = True
                    reason = "send"
        else:
            if (
                event_id
                and (user.free_alert_consumed or 0) == 0
                and user.free_alert_event_id != event_id
            ):
                will_send = True
                reason = "send_free_trial"
            else:
                reason = "not_premium"

    payload = {
        "email": user.email,
        "user_id": user.id,
        "is_premium": bool(user.is_premium),
        "premium": bool(user.premium),
        "premium_lifetime": bool(user.premium_lifetime),
        "plan_type": user.plan_type,
        "role": user.role,
        "telegram_opt_in": bool(user.telegram_opt_in),
        "chat_id": user.chat_id,
        "telegram_chat_id": user.telegram_chat_id,
        "effective_chat_id": effective_chat_id,
        "threshold": user.threshold,
        "fallback_threshold": fallback_threshold,
        "threshold_used": threshold_used,
        "threshold_fallback_used": threshold_fallback_used,
        "threshold_source": "fallback_default" if threshold_fallback_used else "user",
        "last_alert_sent_at": last_alert_sent_at.isoformat() if last_alert_sent_at else None,
        "now_utc": now.isoformat(),
        "cooldown_seconds_remaining": cooldown_seconds_remaining,
        "moving_avg": peak_value,
        "peak_value": peak_value,
        "moving_avg_real": moving_avg_real,
        "last_point_value": last_point_value,
        "last_point_ts": last_point_ts,
        "will_send": will_send,
        "reason": reason,
    }
    return jsonify(payload)
