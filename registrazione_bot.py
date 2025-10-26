import csv
import logging
import os

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app.utils.logger import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required to run the registration bot.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    username = update.effective_user.username

    # Controlla se l'utente è già registrato
    file_path = "utenti.csv"
    utenti = []
    if os.path.exists(file_path):
        with open(file_path, "r", newline='') as file:
            reader = csv.reader(file)
            utenti = list(reader)

    già_iscritto = any(str(chat_id) == row[0] for row in utenti)

    if not già_iscritto:
        with open(file_path, "a", newline='') as file:
            writer = csv.writer(file)
            writer.writerow([chat_id, f"@{username}" if username else ""])
        await update.message.reply_text("✅ Sei iscritto agli avvisi dell'Etna!")
    else:
        await update.message.reply_text("🔄 Sei già iscritto al sistema di notifiche.")

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))

logger.info("Telegram registration bot running")
app.run_polling()
