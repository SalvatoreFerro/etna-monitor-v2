"""Startup helpers for database migrations and data bootstrap."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.util import CommandError
from flask import Flask, current_app
from sqlalchemy import inspect, text

from .models import db

try:  # pragma: no cover - optional dependency guard
    from backend.utils.extract_png import process_png_to_csv
except Exception:  # pragma: no cover - backend utilities may be unavailable in tests
    process_png_to_csv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_CURVA_WARNING_FLAG = "_curva_bootstrap_warning_emitted"


def _alembic_config(app: Flask) -> AlembicConfig:
    """Return an Alembic configuration bound to the current Flask app."""

    project_root = Path(app.root_path).parent
    ini_path = project_root / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    cfg.set_main_option("script_location", str(project_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])
    cfg.attributes["configure_logger"] = False
    return cfg


def _ensure_alembic_environment(app: Flask, cfg: AlembicConfig) -> None:
    """Verify that Alembic can run against the current database."""

    script_location = Path(cfg.get_main_option("script_location"))
    if not script_location.exists():
        raise RuntimeError(
            f"Alembic environment missing at {script_location}. Ensure migrations/ exists in the deployment image."
        )

    engine = db.engine
    if engine.dialect.name == "postgresql":
        # Ensure the ``alembic_version`` table exists to avoid permissions issues
        with engine.connect() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("alembic_version"):
                conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
                conn.commit()


def init_db(app: Flask | None = None) -> None:
    """Run database migrations idempotently before serving traffic."""

    app_provided = app is not None
    if app is None:
        from . import create_app  # pylint: disable=import-outside-toplevel

        app = create_app()

    assert app is not None  # pragma: no cover - mypy hint
    log = app.logger if app.logger else logger  # type: ignore[assignment]

    log.info("[BOOT] Running database initialization (Alembic upgrade head)...")

    try:
        with app.app_context():
            cfg = _alembic_config(app)
            _ensure_alembic_environment(app, cfg)
            command.upgrade(cfg, "head")
    except CommandError as exc:
        log.exception("[BOOT] Alembic upgrade failed: %s", exc)
        raise
    except Exception as exc:  # pragma: no cover - defensive catch
        log.exception("[BOOT] Unexpected error during database initialization: %s", exc)
        raise
    else:
        log.info("[BOOT] Database schema is up to date.")
    finally:
        if not app_provided:
            # Drop the application context when we created it just for migrations
            db.session.remove()


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


__all__ = ["ensure_curva_csv", "init_db"]

