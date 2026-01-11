"""Standalone Telegram bot worker for EtnaMonitor."""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Final

from flask import Flask
from sqlalchemy import or_
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.models import TelegramLinkToken, User, db, init_db
from app.models.event import Event
from config import Config

TOKEN_ENV: Final[str] = "TELEGRAM_BOT_TOKEN"
LINK_PREFIX: Final[str] = "LINK_"
RATE_LIMIT_SECONDS: Final[int] = 2
_LAST_START_AT: dict[int, float] = {}
_FLASK_APP = None


def _create_worker_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    init_db(app)
    return app


def _get_flask_app():
    global _FLASK_APP
    if _FLASK_APP is None:
        _FLASK_APP = _create_worker_app()
    return _FLASK_APP


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is not None:
        logging.info("Handling /start command chat_id=%s", chat_id)
        now = time.monotonic()
        last_start_at = _LAST_START_AT.get(chat_id)
        if last_start_at and now - last_start_at < RATE_LIMIT_SECONDS:
            return
        _LAST_START_AT[chat_id] = now

    if not update.message:
        return

    args = context.args or []
    payload = args[0] if args else ""
    if payload.startswith(LINK_PREFIX):
        token_value = payload[len(LINK_PREFIX):].strip()
        if not token_value or chat_id is None:
            await update.message.reply_text(
                "Token non valido. Riprova dal pulsante sul sito."
            )
            return

        app = _get_flask_app()
        with app.app_context():
            now = datetime.now(timezone.utc)
            try:
                token_record = TelegramLinkToken.query.filter_by(token=token_value).first()
                if not token_record:
                    await update.message.reply_text(
                        "Token non valido o scaduto. Rigenera il link dal sito."
                    )
                    return
                if token_record.used_at:
                    await update.message.reply_text(
                        "Questo link è già stato usato. Rigenera il link dal sito."
                    )
                    return
                if token_record.expires_at < now:
                    await update.message.reply_text(
                        "Il link è scaduto. Rigenera il link dal sito."
                    )
                    return

                user = User.query.get(token_record.user_id)
                if not user:
                    await update.message.reply_text(
                        "Impossibile completare il collegamento. Riprova dal sito."
                    )
                    return

                if user.telegram_chat_id and user.telegram_chat_id != chat_id:
                    await update.message.reply_text(
                        "Il tuo account è già collegato a un altro Telegram."
                    )
                    return

                existing_user = User.query.filter(
                    User.id != user.id,
                    or_(User.telegram_chat_id == chat_id, User.chat_id == chat_id),
                ).first()
                if existing_user:
                    await update.message.reply_text(
                        "Questo account Telegram è già collegato a un altro profilo."
                    )
                    return

                user.telegram_chat_id = chat_id
                user.chat_id = chat_id
                user.telegram_opt_in = True
                user.consent_ts = user.consent_ts or datetime.utcnow()
                user.privacy_version = Config.PRIVACY_POLICY_VERSION
                token_record.used_at = now
                db.session.add(
                    Event(
                        user_id=user.id,
                        event_type="telegram_connected",
                        message="Telegram connected via deep link",
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
                logging.exception("Failed to link Telegram account for chat_id=%s", chat_id)
                await update.message.reply_text(
                    "Errore durante il collegamento. Riprova dal sito."
                )
                return

        await update.message.reply_text(
            "✅ Collegato! Ora riceverai gli alert quando superi la soglia."
        )
        return

    greeting = (
        "Ciao, sono Etna Bot! 🔥\n"
        "Per collegare il tuo account, usa il pulsante su EtnaMonitor."
    )
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


def _resolve_polling_mode() -> str:
    mode = (os.getenv("TELEGRAM_BOT_MODE") or Config.TELEGRAM_BOT_MODE or "").strip().lower()
    if mode and mode != "polling":
        logging.warning(
            "TELEGRAM_BOT_MODE=%s is not supported for the worker; forcing polling.", mode
        )
    return "polling"


def main() -> None:
    """Entry point for the Telegram bot worker."""

    configure_logging()
    token = get_token()
    mode = _resolve_polling_mode()

    logging.info("Worker booting with Python=%s", sys.version.replace("\n", " "))
    logging.info("Telegram token present: %s", "yes" if token else "no")
    logging.info("Telegram mode: %s", mode)

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    logging.info("Bot handlers registered: /start, /help")
    logging.info("Starting Telegram polling...")

    application.run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    main()
