"""Helpers for persisting cron run logs both inside and outside Flask."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from app.models import db
from app.models.cron_run import CronRun
from config import Config, get_database_uri_from_env

_JSON_FIELDS = {"payload", "diagnostic_json", "skipped_by_reason"}


def sanitize_json_value(value: Any) -> Any:
    """
    Recursively sanitize values for JSON serialization.
    
    Converts datetime objects to ISO strings, handles nested structures,
    and ensures all values are JSON-serializable.
    
    Note: Similar logic exists in scripts/csv_updater.serialize_datetimes().
    Both functions are kept separate to avoid cross-module dependencies,
    since csv_updater may run outside the Flask app context.
    """
    if isinstance(value, datetime):
        # Ensure timezone-aware and convert to ISO format
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): sanitize_json_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _sanitize_json_fields(payload: dict) -> dict:
    sanitized = dict(payload)
    for field in _JSON_FIELDS:
        if field in sanitized and sanitized[field] is not None:
            try:
                sanitized[field] = sanitize_json_value(sanitized[field])
            except Exception:
                sanitized[field] = str(sanitized[field])
    return sanitized


def _resolve_database_uri() -> str:
    uri, _ = get_database_uri_from_env(Config.SQLALCHEMY_DATABASE_URI)
    return uri or Config.SQLALCHEMY_DATABASE_URI


def _resolve_retention_days() -> int:
    try:
        from flask import current_app

        if current_app:
            value = current_app.config.get("CRON_RUN_RETENTION_DAYS")
            if value is not None:
                return int(value)
    except Exception:
        pass

    env_value = os.getenv("CRON_RUN_RETENTION_DAYS")
    if env_value:
        try:
            return int(env_value)
        except ValueError:
            return 30
    return getattr(Config, "CRON_RUN_RETENTION_DAYS", 30)


def _purge_old_runs(executor: Connection | Any) -> None:
    retention_days = _resolve_retention_days()
    if retention_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    stmt = CronRun.__table__.delete().where(CronRun.started_at < cutoff)
    executor.execute(stmt)


def log_cron_run(payload: dict, *, commit: bool = True) -> CronRun | None:
    """Persist a cron run using the Flask SQLAlchemy session."""
    if payload.get("started_at") is None:
        payload["started_at"] = datetime.now(timezone.utc)
    if payload.get("finished_at") is None:
        payload["finished_at"] = payload.get("started_at")
    if payload.get("status") is None and payload.get("ok") is not None:
        payload["status"] = "success" if payload.get("ok") else "error"
    if payload.get("diagnostic_json") is None and payload.get("payload") is not None:
        payload["diagnostic_json"] = payload.get("payload")
    payload = _sanitize_json_fields(payload)
    run = CronRun(**payload)
    try:
        db.session.add(run)
        if commit:
            db.session.commit()
            _purge_old_runs(db.session)
            db.session.commit()
        return run
    except Exception:
        db.session.rollback()
        raise


def log_cron_run_external(payload: dict, *, database_uri: str | None = None) -> None:
    """Persist a cron run without needing a Flask app context."""
    if payload.get("started_at") is None:
        payload["started_at"] = datetime.now(timezone.utc)
    if payload.get("finished_at") is None:
        payload["finished_at"] = payload.get("started_at")
    if payload.get("status") is None and payload.get("ok") is not None:
        payload["status"] = "success" if payload.get("ok") else "error"
    if payload.get("diagnostic_json") is None and payload.get("payload") is not None:
        payload["diagnostic_json"] = payload.get("payload")
    payload = _sanitize_json_fields(payload)
    engine = create_engine(database_uri or _resolve_database_uri())
    with engine.begin() as connection:
        connection.execute(CronRun.__table__.insert().values(**payload))
        _purge_old_runs(connection)
