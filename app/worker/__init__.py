"""Background worker entry-point for scheduler and Telegram bot."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import create_app
from app.bootstrap import ensure_curva_csv, init_db
from app.models import db
from app.services.scheduler_service import SchedulerService
from app.services.telegram_bot_service import TelegramBotService
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)

_HEARTBEAT_FILE_NAME = "worker-heartbeat.json"
_LOCK_ID = int(os.getenv("WORKER_ADVISORY_LOCK_ID", "862421"))
_HEARTBEAT_INTERVAL = int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "30"))


def _heartbeat_path(app) -> Path:
    data_dir = Path(app.config.get("DATA_DIR", "/var/tmp"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / _HEARTBEAT_FILE_NAME


def _write_heartbeat(app) -> None:
    path = _heartbeat_path(app)
    payload = {
        "pid": os.getpid(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("[WORKER] Unable to persist heartbeat at %s", path)


@contextmanager
def _advisory_lock(app):
    engine = db.engine
    if engine.dialect.name != "postgresql":
        logger.info(
            "[WORKER] Advisory lock skipped for dialect %s", engine.dialect.name
        )
        yield True
        return

    acquired = False
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": _LOCK_ID})
            acquired = bool(result.scalar())
            conn.commit()
        except SQLAlchemyError:
            logger.exception("[WORKER] Failed to acquire advisory lock")

    if not acquired:
        logger.error(
            "[WORKER] Another worker instance is active (lock_id=%s). Exiting.",
            _LOCK_ID,
        )
        yield False
        return

    logger.info("[WORKER] Advisory lock %s acquired", _LOCK_ID)
    try:
        yield True
    finally:
        with engine.connect() as conn:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": _LOCK_ID})
                conn.commit()
            except SQLAlchemyError:
                logger.exception("[WORKER] Failed to release advisory lock")


def _start_heartbeat_thread(app):
    stop_event = threading.Event()

    def _beat():
        while not stop_event.is_set():
            _write_heartbeat(app)
            stop_event.wait(max(_HEARTBEAT_INTERVAL, 10))

    thread = threading.Thread(target=_beat, daemon=True, name="worker-heartbeat")
    thread.start()
    return stop_event


def main() -> None:
    configure_logging(os.getenv("LOG_DIR", "logs"))
    logger.info("[WORKER] Bootstrapping EtnaMonitor worker...")

    app = create_app()

    init_db(app)
    ensure_curva_csv(app)

    with app.app_context():
        with _advisory_lock(app) as acquired:
            if not acquired:
                sys.exit(0)

            heartbeat_stop = _start_heartbeat_thread(app)

            scheduler = SchedulerService()
            scheduler.init_app(app)
            logger.info("[WORKER] Scheduler ready")

            telegram_service = TelegramBotService()
            telegram_service.init_app(app)
            logger.info("[WORKER] Telegram bot initialization requested")

            def _graceful_exit(*_args):
                logger.info("[WORKER] Shutdown signal received")
                heartbeat_stop.set()
                sys.exit(0)

            signal.signal(signal.SIGTERM, _graceful_exit)
            signal.signal(signal.SIGINT, _graceful_exit)

            logger.info("[WORKER] Entering heartbeat loop")
            while True:
                time.sleep(60)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()

