"""Standalone Telegram bot worker entry-point."""

from __future__ import annotations

import logging
import os
import time

from app import create_app
from app.services.telegram_bot_service import TelegramBotService

logger = logging.getLogger("telegram_worker")

HEARTBEAT_SECONDS = int(os.getenv("TELEGRAM_WORKER_HEARTBEAT", "30"))


def main() -> None:
    app = create_app({"TELEGRAM_BOT_MODE": "polling"})

    with app.app_context():
        bot_service = TelegramBotService()
        bot_service.init_app(app)
        app.logger.info("[BOT] Telegram polling worker initialised")

    try:
        while True:
            time.sleep(max(HEARTBEAT_SECONDS, 5))
    except KeyboardInterrupt:  # pragma: no cover - graceful shutdown
        logger.info("[BOT] Telegram worker shutting down")


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
