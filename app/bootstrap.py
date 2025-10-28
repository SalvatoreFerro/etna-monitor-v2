"""Startup helpers for database migrations and data bootstrap."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, current_app
from flask_migrate import init as migrate_init
from flask_migrate import stamp as migrate_stamp
from flask_migrate import upgrade as migrate_upgrade
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .models import db

try:  # pragma: no cover - optional dependency guard
    from backend.utils.extract_png import process_png_to_csv
except Exception:  # pragma: no cover - backend utilities may be unavailable in tests
    process_png_to_csv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CURVA_WARNING_FLAG = "_curva_bootstrap_warning_emitted"
_MIGRATIONS_DIRNAME = "migrations"

_USER_SCHEMA_GUARD_COLUMNS = {
    "telegram_chat_id": "BIGINT",
    "telegram_opt_in": "BOOLEAN NOT NULL DEFAULT FALSE",
    "free_alert_consumed": "INTEGER NOT NULL DEFAULT 0",
    "free_alert_event_id": "VARCHAR(255)",
    "last_alert_sent_at": "TIMESTAMP",
    "alert_count_30d": "INTEGER NOT NULL DEFAULT 0",
    "consent_ts": "TIMESTAMP",
    "privacy_version": "VARCHAR(32)",
    "threshold": "DOUBLE PRECISION",
    "email_alerts": "BOOLEAN NOT NULL DEFAULT FALSE",
    "stripe_customer_id": "VARCHAR(100)",
    "subscription_status": "VARCHAR(20) NOT NULL DEFAULT 'free'",
    "subscription_id": "VARCHAR(100)",
    "current_period_end": "TIMESTAMP",
    "trial_end": "TIMESTAMP",
    "billing_email": "VARCHAR(120)",
    "company_name": "VARCHAR(200)",
    "vat_id": "VARCHAR(50)",
    "google_id": "VARCHAR(255)",
    "name": "VARCHAR(255)",
    "picture_url": "VARCHAR(512)",
    "premium": "BOOLEAN NOT NULL DEFAULT FALSE",
    "is_premium": "BOOLEAN NOT NULL DEFAULT FALSE",
    "premium_lifetime": "BOOLEAN NOT NULL DEFAULT FALSE",
    "premium_since": "TIMESTAMP",
    "donation_tx": "VARCHAR(255)",
    "chat_id": "BIGINT",
    "plan_type": "VARCHAR(20) NOT NULL DEFAULT 'free'",
    "theme_preference": "VARCHAR(16) DEFAULT 'system'",
}


def _migrations_directory(app: Flask) -> Path:
    return Path(app.root_path).parent / _MIGRATIONS_DIRNAME


def _ensure_migrations_initialized(app: Flask, migrations_dir: Path, log: logging.Logger) -> None:
    """Initialise a Flask-Migrate environment when running on a fresh image."""

    env_py = migrations_dir / "env.py"
    if env_py.exists():
        return

    log.warning(
        "[BOOT] migrations environment missing at %s – initialising via Flask-Migrate", migrations_dir
    )
    try:
        migrate_init(directory=str(migrations_dir))
    except Exception as exc:  # pragma: no cover - defensive guard
        log.error("[BOOT] Flask-Migrate init failed: %s", exc)
        raise

    try:
        migrate_stamp(directory=str(migrations_dir), revision="head")
    except Exception as exc:  # pragma: no cover - defensive guard
        log.warning("[BOOT] Unable to stamp migrations to head after init: %s", exc)


def ensure_user_schema_guard(app: Flask, log: logging.Logger | None = None) -> None:
    """Fallback guard that ensures critical ``users`` columns exist."""

    guard_statements = []
    for column_name, ddl in _USER_SCHEMA_GUARD_COLUMNS.items():
        guard_statements.append(
            f"""
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='users' AND column_name='{column_name}'
            ) THEN
                ALTER TABLE users ADD COLUMN {column_name} {ddl};
            END IF;
            """.strip()
        )

    guard_sql = "\n".join(guard_statements)
    logger_to_use = log or getattr(app, "logger", logger)

    try:
        engine = db.engine
        if engine.dialect.name == "sqlite":
            with engine.connect() as conn:
                table_exists = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
                    )
                ).fetchone()
                if table_exists is None:
                    logger_to_use.debug("[BOOT] Schema guard skipped; users table missing (sqlite)")
                    return
                existing_columns = {
                    row._mapping["name"]
                    for row in conn.execute(text("PRAGMA table_info(users)"))
                }
                for column_name, ddl in _USER_SCHEMA_GUARD_COLUMNS.items():
                    if column_name in existing_columns:
                        continue
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {ddl}"))
                conn.commit()
        else:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        f"""
                        DO $$
                        BEGIN
                        {guard_sql}
                        END$$;
                        """
                    )
                )
                conn.commit()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive fallback
        logger_to_use.warning("[BOOT] Schema guard failed: %s", exc)
    else:
        logger_to_use.info("[BOOT] Schema guard completed")


def init_db(app: Flask) -> bool:
    """Run database migrations idempotently before serving traffic."""

    if app is None:  # pragma: no cover - sanity check
        raise ValueError("init_db requires a Flask application instance")

    log = app.logger if app.logger else logger  # type: ignore[assignment]
    log.info("[BOOT] Running database initialization (Flask-Migrate upgrade head)...")

    migrations_dir = _migrations_directory(app)

    try:
        with app.app_context():
            migrations_dir.mkdir(parents=True, exist_ok=True)
            _ensure_migrations_initialized(app, migrations_dir, log)
            migrate_upgrade(directory=str(migrations_dir))
    except Exception as exc:  # pragma: no cover - defensive guard
        log.exception("[BOOT] Database migration failed: %s", exc)
        log.warning("[BOOT] Falling back to schema guard for critical columns")
        ensure_user_schema_guard(app, log)
        return False
    else:
        log.info("[BOOT] Alembic upgrade head OK")
        return True


def ensure_curva_csv(app: Flask | None = None) -> Path:
    """Ensure the tremor CSV exists, generating a placeholder when necessary."""

    app = app or current_app
    data_dir = Path(app.config.get("DATA_DIR", "/var/tmp"))
    csv_path = Path(app.config.get("CSV_PATH", data_dir / "curva.csv"))

    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if csv_path.exists() and csv_path.stat().st_size > 0:
        return csv_path

    skip_bootstrap = os.getenv("SKIP_CURVA_BOOTSTRAP", "0").lower() in {"1", "true", "yes"}
    if process_png_to_csv and not skip_bootstrap:
        try:
            result = process_png_to_csv(output_path=str(csv_path))
        except Exception as exc:  # pragma: no cover - external dependency failures
            app.logger.warning(
                "[BOOT] Failed to bootstrap curva.csv from INGV source: %s", exc
            )
        else:
            rows = result.get("rows", 0)
            app.logger.info(
                "[BOOT] curva.csv bootstrap complete path=%s rows=%s", csv_path, rows
            )
            if rows:
                return csv_path

    if not csv_path.exists() or csv_path.stat().st_size == 0:
        csv_path.write_text("timestamp,value\n", encoding="utf-8")

    if not app.config.get(_CURVA_WARNING_FLAG):
        app.logger.warning(
            "[BOOT] curva.csv unavailable; created placeholder at %s", csv_path
        )
        app.config[_CURVA_WARNING_FLAG] = True

    return csv_path


__all__ = ["ensure_curva_csv", "ensure_user_schema_guard", "init_db"]

