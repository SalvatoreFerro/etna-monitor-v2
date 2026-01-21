"""Startup helpers for database migrations and data bootstrap."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask, current_app
from flask_migrate import init as migrate_init
from flask_migrate import stamp as migrate_stamp
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .models import db

try:  # pragma: no cover - optional dependency guard
    from backend.utils.extract_colored import process_colored_png_to_csv
    from app.utils.config import get_curva_csv_path
except Exception:  # pragma: no cover - backend utilities may be unavailable in tests
    process_colored_png_to_csv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CURVA_WARNING_FLAG = "_curva_bootstrap_warning_emitted"
_MIGRATIONS_DIRNAME = "migrations"
_AUTO_MIGRATE_LOCK = "alembic-autoupgrade.lock"

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


def _repository_root(app: Flask) -> Path:
    return Path(app.root_path).parent


def _migrations_directory(app: Flask) -> Path:
    return _repository_root(app) / _MIGRATIONS_DIRNAME


def _alembic_config(app: Flask) -> AlembicConfig:
    repo_root = _repository_root(app)
    ini_path = repo_root / "alembic.ini"
    config = AlembicConfig(str(ini_path))
    script_location = config.get_main_option("script_location")
    migrations_path = repo_root / _MIGRATIONS_DIRNAME
    if not script_location or script_location == _MIGRATIONS_DIRNAME:
        config.set_main_option("script_location", str(migrations_path))
    sqlalchemy_url = app.config.get("SQLALCHEMY_DATABASE_URI")
    if sqlalchemy_url:
        config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return config


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


def _run_auto_migrate(app: Flask, config: AlembicConfig, log: logging.Logger) -> bool:
    """Execute ``alembic upgrade head`` while holding a filesystem lock."""

    allow = os.getenv("ALLOW_AUTO_MIGRATE", "0").lower() in {"1", "true", "yes"}
    if not allow:
        return False

    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)
    lock_path = instance_path / _AUTO_MIGRATE_LOCK

    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        log.info("[MIGRATE] Auto-migrate lock present at %s; skipping", lock_path)
        return False

    skip_var = "SKIP_SCHEMA_VALIDATION"
    previous_skip = os.environ.get(skip_var)

    try:
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
        os.environ[skip_var] = "1"

        try:
            script = ScriptDirectory.from_config(config)
            heads = script.get_heads()
        except Exception as exc:  # pragma: no cover - defensive guard
            log.warning("[MIGRATE] Unable to inspect Alembic heads: %s", exc)
            heads = None

        if heads and len(heads) > 1:
            target = "heads"
            log.warning(
                "[MIGRATE] Multiple Alembic heads detected (%s); upgrading all heads",
                ", ".join(heads),
            )
        else:
            target = "head"
            log.info("[MIGRATE] Running alembic upgrade head (auto-migrate enabled)")

        command.upgrade(config, target)
        log.info("[MIGRATE] Alembic upgrade %s completed", target)
        return True
    except Exception:
        log.exception("[MIGRATE] Alembic auto-migrate failed")
        raise
    finally:
        if previous_skip is None:
            os.environ.pop(skip_var, None)
        else:
            os.environ[skip_var] = previous_skip
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def get_alembic_status(app: Flask, log: logging.Logger | None = None) -> dict[str, Optional[str] | bool]:
    """Return the expected and applied Alembic revisions together with health info."""

    logger_to_use = log or getattr(app, "logger", logger)

    expected_revision: Optional[str] = None
    current_revision: Optional[str] = None
    error: Optional[str] = None
    database_online = False

    config = _alembic_config(app)

    try:
        script = ScriptDirectory.from_config(config)
        expected_revision = script.get_current_head()
    except Exception as exc:  # pragma: no cover - defensive guard
        error = f"Unable to determine Alembic head: {exc}"
        logger_to_use.warning("[MIGRATE] %s", error)

    try:
        engine = db.engine
    except Exception as exc:  # pragma: no cover - defensive guard
        error = f"Unable to access database engine: {exc}"
        logger_to_use.warning("[MIGRATE] %s", error)
    else:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                database_online = True
                try:
                    result = conn.execute(text("SELECT version_num FROM alembic_version"))
                except SQLAlchemyError as exc:  # pragma: no cover - fallback for missing table
                    if error is None:
                        error = f"Unable to read alembic_version table: {exc}"
                    logger_to_use.warning("[MIGRATE] %s", error)
                else:
                    row = result.first()
                    if row is not None:
                        current_revision = row[0]
        except SQLAlchemyError as exc:  # pragma: no cover - database offline
            error = f"Database connectivity check failed: {exc}"
            logger_to_use.warning("[MIGRATE] %s", error)

    is_up_to_date = (
        database_online
        and expected_revision is not None
        and current_revision is not None
        and current_revision == expected_revision
    )

    return {
        "head_revision": expected_revision,
        "current_revision": current_revision,
        "database_online": database_online,
        "is_up_to_date": is_up_to_date,
        "error": error,
    }


def ensure_schema_current(app: Flask, log: logging.Logger | None = None) -> dict[str, Optional[str] | bool]:
    """Ensure the runtime database schema matches the Alembic head revision."""

    logger_to_use = log or getattr(app, "logger", logger)
    config = _alembic_config(app)
    status = get_alembic_status(app, logger_to_use)

    if status["is_up_to_date"]:
        return status

    if not status["database_online"]:
        return status

    try:
        ran = _run_auto_migrate(app, config, logger_to_use)
    except Exception:
        return status

    if ran:
        status = get_alembic_status(app, logger_to_use)

    return status


def init_db(app: Flask) -> bool:
    """Run Alembic migrations when ``ALLOW_AUTO_MIGRATE`` is enabled."""

    if app is None:  # pragma: no cover - sanity check
        raise ValueError("init_db requires a Flask application instance")

    log = app.logger if app.logger else logger  # type: ignore[assignment]
    log.info("[BOOT] Checking database schema state...")

    migrations_dir = _migrations_directory(app)

    with app.app_context():
        migrations_dir.mkdir(parents=True, exist_ok=True)
        _ensure_migrations_initialized(app, migrations_dir, log)
        status = ensure_schema_current(app, log)

    if status["is_up_to_date"]:
        log.info("[BOOT] Database schema matches Alembic head (%s)", status["head_revision"])
        return True

    log.warning(
        "[BOOT] Database schema not up to date (current=%s head=%s)",
        status["current_revision"],
        status["head_revision"],
    )
    return False


def ensure_curva_csv(app: Flask | None = None) -> Path:
    """Ensure the tremor CSV exists, generating a placeholder when necessary."""

    app = app or current_app
    csv_path = get_curva_csv_path()

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    if csv_path.exists() and csv_path.stat().st_size > 0:
        return csv_path

    skip_bootstrap = os.getenv("SKIP_CURVA_BOOTSTRAP", "0").lower() in {"1", "true", "yes"}
    if process_colored_png_to_csv and not skip_bootstrap:
        try:
            colored_url = os.getenv("INGV_COLORED_URL", "")
            result = process_colored_png_to_csv(colored_url, output_path=str(csv_path))
        except Exception as exc:  # pragma: no cover - external dependency failures
            app.logger.warning(
                "[BOOT] Failed to bootstrap curva.csv from INGV colored source: %s", exc
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


__all__ = [
    "ensure_curva_csv",
    "ensure_user_schema_guard",
    "ensure_schema_current",
    "get_alembic_status",
    "init_db",
]
