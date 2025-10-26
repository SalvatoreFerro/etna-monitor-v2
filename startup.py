#!/usr/bin/env python3
"""Startup script for Render deployment that ensures database migrations run."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager

from alembic import command
from alembic.config import Config as AlembicConfig

from app import create_app
from app.utils.logger import configure_logging

logger = logging.getLogger(__name__)


@contextmanager
def _app_context():
    """Yield a Flask application context for Alembic operations."""

    app = create_app()
    with app.app_context():
        yield app


def _alembic_config(database_uri: str) -> AlembicConfig:
    """Build a minimal Alembic configuration object."""

    config = AlembicConfig()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", database_uri)
    config.attributes["configure_logger"] = False
    return config


def run_migration() -> None:
    """Run ``alembic upgrade head`` and abort on failure."""

    logger.info("Running database migrations via Alembic...")

    with _app_context() as app:
        alembic_cfg = _alembic_config(app.config["SQLALCHEMY_DATABASE_URI"])

        try:
            command.upgrade(alembic_cfg, "head")
        except Exception:
            logger.exception("Alembic upgrade failed")
            raise

    logger.info("Database migration completed successfully")


def main() -> None:
    """Entrypoint used by Procfile to run migrations and start Gunicorn."""

    configure_logging(os.getenv("LOG_DIR", "logs"))
    logger.info("Starting EtnaMonitor deployment...")

    data_dir = os.getenv("DATA_DIR", "/var/tmp")
    log_dir = os.getenv("LOG_DIR", "/var/tmp/log")

    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    logger.info("Data directories ready data_dir=%s log_dir=%s", data_dir, log_dir)

    try:
        run_migration()
    except Exception:
        logger.critical("Aborting startup because database migrations failed")
        sys.exit(1)

    port = os.environ.get("PORT", "5000")
    workers = os.environ.get("WEB_CONCURRENCY", "2")

    cmd = [
        "gunicorn",
        "-w",
        str(workers),
        "-k",
        "gthread",
        "-b",
        f"0.0.0.0:{port}",
        "app:app",
    ]

    logger.info("Starting gunicorn with command: %s", " ".join(cmd))
    os.execvp("gunicorn", cmd)


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
