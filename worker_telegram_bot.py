"""Minimal Telegram bot worker using polling mode."""

import asyncio
import logging
import os
from typing import Optional

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start with a welcome message."""

    chat_id: Optional[int] = None
    if update.effective_chat:
        chat_id = update.effective_chat.id
    logging.info("Handling /start command chat_id=%s", chat_id)

    if update.message:
        await update.message.reply_text("Ciao! Sono Etna Bot 👋")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /help with a list of supported commands."""

    chat_id: Optional[int] = None
    if update.effective_chat:
        chat_id = update.effective_chat.id
    logging.info("Handling /help command chat_id=%s", chat_id)

    if update.message:
        await update.message.reply_text("Comandi disponibili: /start /help")


async def main() -> None:
    """Start polling the Telegram bot token configured in the environment."""

    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} non impostato")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))

    logging.info("Starting Telegram polling…")
    await app.run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    asyncio.run(main())
