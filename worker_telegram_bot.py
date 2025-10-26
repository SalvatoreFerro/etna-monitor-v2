#!/usr/bin/env python3
"""Telegram Bot Worker Service."""

from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from app import create_app
from app.services.telegram_bot_service import TelegramBotService
from app.utils.logger import get_logger
from alerts.engine import AlertComputation, evaluate_threshold
from alerts.notifier import send_telegram_alert
from config import Config

logger = get_logger(__name__)

DEFAULT_WINDOW = 5
DEFAULT_INTERVAL = int(os.getenv("ALERT_WORKER_INTERVAL", "300"))
DEFAULT_DATA_FILE = Path(os.getenv("DATA_CURVE_FILE", "data/curva.csv"))
DEFAULT_LOG_FILE = Path(os.getenv("ALERT_WORKER_LOG", "log/alert_events.csv"))


def _load_chat_ids(override: Optional[Sequence[str]] = None) -> List[str]:
    if override is not None:
        return [chat_id for chat_id in override if chat_id]

    chat_ids: List[str] = []
    utenti_file = Path("utenti.csv")
    if utenti_file.exists():
        try:
            with utenti_file.open("r", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    if not row:
                        continue
                    chat_ids.append(row[0].strip())
        except OSError as exc:
            logger.error("Impossibile leggere utenti.csv: %s", exc)

    fallback = Config.TELEGRAM_CHAT_ID
    if fallback and fallback not in chat_ids:
        chat_ids.append(fallback)

    return [chat_id for chat_id in chat_ids if chat_id]


def _load_values(data_file: Path) -> List[float]:
    if not data_file.exists():
        logger.warning("File dati non trovato: %s", data_file)
        return []

    values: List[float] = []
    try:
        with data_file.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    values.append(float(row.get("value", "")))
                except (TypeError, ValueError):
                    continue
    except OSError as exc:
        logger.error("Errore in lettura del file dati %s: %s", data_file, exc)
        return []

    return values


def _write_log_event(
    log_file: Path,
    event_type: str,
    result: AlertComputation,
    chat_id: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_file.exists()
    try:
        with log_file.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(
                    [
                        "timestamp",
                        "event",
                        "chat_id",
                        "moving_average",
                        "latest_value",
                        "threshold",
                        "samples",
                        "message",
                    ]
                )
            writer.writerow(
                [
                    datetime.utcnow().isoformat(),
                    event_type,
                    chat_id or "",
                    "" if result.moving_average is None else f"{result.moving_average:.6f}",
                    "" if result.latest_value is None else f"{result.latest_value:.6f}",
                    f"{result.threshold:.6f}",
                    result.sample_size,
                    message or "",
                ]
            )
    except OSError as exc:
        logger.error("Impossibile scrivere il log degli alert: %s", exc)


def run_alert_cycle(
    *,
    bot_token: Optional[str] = None,
    chat_ids: Optional[Sequence[str]] = None,
    data_file: Optional[Path] = None,
    window: int = DEFAULT_WINDOW,
    threshold: Optional[float] = None,
    log_file: Optional[Path] = None,
    message_template: Optional[str] = None,
) -> bool:
    """Run a single alert evaluation and notification cycle."""

    token = bot_token or Config.TELEGRAM_BOT_TOKEN
    chats = _load_chat_ids(chat_ids)
    data_path = Path(data_file) if data_file is not None else DEFAULT_DATA_FILE
    log_path = Path(log_file) if log_file is not None else DEFAULT_LOG_FILE
    threshold_value = threshold if threshold is not None else Config.ALERT_THRESHOLD_DEFAULT

    values = _load_values(data_path)
    if not values:
        computation = AlertComputation(None, None, float(threshold_value), False, 0)
        _write_log_event(log_path, "no_data", computation)
        return False

    computation = evaluate_threshold(values, window, threshold_value)

    if not chats:
        logger.warning("Nessun chat_id configurato per inviare alert")
        _write_log_event(log_path, "missing_chat_ids", computation)
        return False

    if not computation.triggered:
        _write_log_event(log_path, "no_alert", computation)
        return False

    message = message_template or (
        "\n".join(
            [
                "🌋 ALLERTA ETNA",
                "",
                "Tremore vulcanico oltre soglia.",
                f"Valore attuale: {computation.latest_value:.2f} mV",
                f"Media mobile ({window} campioni): {computation.moving_average:.2f} mV",
                f"Soglia: {computation.threshold:.2f} mV",
            ]
        )
    )

    delivery_success = False
    for chat_id in chats:
        if send_telegram_alert(token, chat_id, message):
            _write_log_event(log_path, "alert_sent", computation, chat_id=chat_id, message=message)
            delivery_success = True
        else:
            _write_log_event(log_path, "alert_failed", computation, chat_id=chat_id, message=message)

    return delivery_success


def main():
    """Initialize and run the Telegram bot worker."""

    logger.info("🤖 Starting Telegram Bot Worker...")

    app = create_app()

    with app.app_context():
        try:
            telegram_bot = TelegramBotService()
            telegram_bot.init_app(app)
            logger.info("✅ Telegram bot initialized and polling started")

            logger.info("🔄 Bot worker running... Press Ctrl+C to stop")
            while True:
                try:
                    run_alert_cycle()
                except Exception:  # pragma: no cover - safety net
                    logger.exception("Errore durante il ciclo di alert")
                time.sleep(max(DEFAULT_INTERVAL, 10))

        except KeyboardInterrupt:
            logger.info("🛑 Bot worker stopped by user")
        except Exception as exc:  # pragma: no cover - startup failure
            logger.exception("❌ Bot worker error: %s", exc)
            raise


if __name__ == "__main__":
    main()
