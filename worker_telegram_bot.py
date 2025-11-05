"""Standalone Telegram bot worker for EtnaMonitor."""

import logging
import os
import sys
from typing import Final

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN_ENV: Final[str] = "TELEGRAM_BOT_TOKEN"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is not None:
        logging.info("Handling /start command chat_id=%s", chat_id)
    if update.message:
        greeting = "Ciao, sono Etna Bot! 🔥"
        if chat_id is not None:
            greeting = f"{greeting}\nIl tuo chat ID è: {chat_id}"
        await update.message.reply_text(greeting)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""

    if update.effective_chat:
        logging.info("Handling /help command chat_id=%s", update.effective_chat.id)
    if update.message:
        await update.message.reply_text(
            "Comandi disponibili:\n"
            "• /start - Presentazione del bot\n"
            "• /help - Mostra questo messaggio"
        )


def configure_logging() -> None:
    """Configure logging for the worker."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def get_token() -> str:
    """Retrieve the Telegram bot token from the environment."""

    token = os.environ.get(TOKEN_ENV)
    if not token:
        logging.error("Environment variable %s is not set. Exiting.", TOKEN_ENV)
        sys.exit(1)
    return token


def main() -> None:
    """Entry point for the Telegram bot worker."""

    configure_logging()
    token = get_token()

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    logging.info("Bot is ready!")
    logging.info("Starting Telegram polling...")

    application.run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    main()
