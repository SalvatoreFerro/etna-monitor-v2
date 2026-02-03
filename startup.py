#!/usr/bin/env python3
"""Startup script for Render deployment that ensures database migrations run."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from app import create_app
from app.bootstrap import ensure_curva_csv
from app.utils.logger import configure_logging

logger = logging.getLogger(__name__)


def _start_background_updater() -> None:
    """Start a background thread that periodically updates the tremor CSV.

    When ENABLE_BACKGROUND_UPDATER is set to ``true`` (case‑insensitive), this
    function spawns a daemon thread that runs ``scripts.csv_updater.update_with_retries``
    in a loop.  The interval between runs is read from CSV_UPDATE_INTERVAL
    (defaults to 3600 seconds).  Errors are logged but do not terminate
    the thread.
    """
    from pathlib import Path
    from scripts import csv_updater

    enable = os.getenv("ENABLE_BACKGROUND_UPDATER", "false").lower() in {"1", "true", "yes"}
    if not enable:
        logger.info("[BACKGROUND_UPDATER] Disabled (ENABLE_BACKGROUND_UPDATER not set)")
        return
    
    try:
        interval = int(os.getenv("CSV_UPDATE_INTERVAL", "3600"))
    except ValueError:
        interval = 3600
        logger.warning("[BACKGROUND_UPDATER] Invalid CSV_UPDATE_INTERVAL, using default: 3600")

    def _updater_loop() -> None:
        logger.info("[BACKGROUND_UPDATER] Thread started with interval=%s seconds", interval)
        while True:
            try:
                # Read environment variables like the cron job would
                ingv_url = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
                colored_url = (os.getenv("INGV_COLORED_URL") or "").strip() or None
                csv_path = Path(os.getenv("CURVA_CSV_PATH", "data/curva_colored.csv"))
                
                logger.info("[BACKGROUND_UPDATER] Starting CSV update cycle")
                csv_updater.update_with_retries(
                    ingv_url=ingv_url,
                    colored_url=colored_url,
                    csv_path=csv_path,
                )
                logger.info("[BACKGROUND_UPDATER] CSV update cycle completed")
            except Exception:
                logger.exception("[BACKGROUND_UPDATER] CSV updater encountered an error")
            
            time.sleep(interval)

    threading.Thread(target=_updater_loop, daemon=True, name="csv-updater").start()
    logger.info("[BACKGROUND_UPDATER] Background thread launched successfully")


def main() -> None:
    """Entrypoint used by Procfile to run migrations and start Gunicorn.
    
    Performs initial setup such as ensuring the existence of the tremor CSV file
    and optionally starting a background CSV updater thread.  If
    RUN_CSV_UPDATER_ONCE is set in the environment, it will run the CSV updater
    script once before starting the server.
    """

    os.environ.setdefault("ALLOW_AUTO_MIGRATE", "1")
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

    status = app.config.get("ALEMBIC_MIGRATION_STATUS", {})
    logger.info(
        "[STARTUP] Migration status database_online=%s current=%s head=%s up_to_date=%s",
        status.get("database_online"),
        status.get("current_revision"),
        status.get("head_revision"),
        status.get("is_up_to_date"),
    )

    try:
        ensure_curva_csv(app)
    except Exception:
        logger.exception("Failed to bootstrap curva.csv before Gunicorn start")

    # Start the background updater if enabled
    _start_background_updater()

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
