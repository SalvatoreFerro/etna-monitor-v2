#!/usr/bin/env python3
"""Startup script for Render deployment that ensures database migrations run."""

from __future__ import annotations

import logging
import os
import sys

from app import create_app
from app.bootstrap import ensure_curva_csv, init_db
from app.utils.logger import configure_logging

logger = logging.getLogger(__name__)


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
        app = create_app()
    except Exception:
        logger.exception("Failed to create Flask application during startup")
        sys.exit(1)

    try:
        migrations_ok = init_db(app)
    except Exception:
        logger.exception("[BOOT] init_db raised an unexpected error during startup")
        migrations_ok = False

    if not migrations_ok:
        logger.warning(
            "[BOOT] Proceeding with application startup after schema guard fallback"
        )

    try:
        ensure_curva_csv(app)
    except Exception:
        logger.exception("Failed to bootstrap curva.csv before Gunicorn start")

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
