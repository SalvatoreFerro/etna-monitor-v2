import asyncio
import threading
from datetime import datetime

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from app.models import db
from app.models.event import Event
from app.models.user import User
from app.utils.logger import get_logger
from config import Config
from flask import current_app

logger = get_logger(__name__)

class TelegramBotService:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.bot_token = Config.TELEGRAM_BOT_TOKEN
            self.application = None
            self.bot_thread = None
            self.loop = None
            self._initialized = True
        
    def init_app(self, app):
        """Initialize bot with Flask app context"""
        if hasattr(self, 'app') and self.app is not None:
            logger.info("TelegramBotService already initialized, skipping")
            return
            
        self.app = app
        if self.bot_token:
            self._setup_bot()
            self._start_bot_thread()
        else:
            logger.warning("No Telegram bot token configured")
    
    def _setup_bot(self):
        """Setup bot application and handlers"""
        self.application = ApplicationBuilder().token(self.bot_token).build()
        self.application.add_handler(CommandHandler("start", self._handle_start))
        self.application.add_handler(CommandHandler("help", self._handle_help))
        self.application.add_handler(CommandHandler("status", self._handle_status))
        
    def _start_bot_thread(self):
        """Start bot in separate thread"""
        self.bot_thread = threading.Thread(target=self._run_bot, daemon=True)
        self.bot_thread.start()
        logger.info("Telegram bot thread started")
    
    def _run_bot(self):
        """Run bot polling in separate thread"""
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._start_polling())
        except Exception:
            logger.exception("Bot polling error")
    
    async def _start_polling(self):
        """Start bot polling"""
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            logger.info("Telegram bot polling started")
            
            while True:
                await asyncio.sleep(1)
                
        except Exception:
            logger.exception("Bot polling failed")
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""

        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username or update.effective_user.full_name or "Utente"

        with self.app.app_context():
            try:
                user = (
                    User.query.filter(
                        (User.telegram_chat_id == chat_id) | (User.chat_id == chat_id)
                    )
                    .order_by(User.id.asc())
                    .first()
                )

                if user:
                    user.telegram_chat_id = chat_id
                    user.chat_id = chat_id
                    user.telegram_opt_in = True
                    user.consent_ts = user.consent_ts or datetime.utcnow()
                    user.privacy_version = Config.PRIVACY_POLICY_VERSION

                    if user.has_premium_access:
                        plan_line = "✅ Premium attivo: riceverai tutti gli alert."
                    elif not user.free_alert_consumed:
                        plan_line = "⚪ Piano Free: 1 alert gratuito disponibile."
                    else:
                        plan_line = "🔴 Piano Free: alert di prova già utilizzato."

                    message = (
                        f"👋 Ciao {username}!\n\n"
                        f"{plan_line}\n"
                        "Controlla la tua dashboard su etna-monitor-v2.onrender.com per gestire le notifiche."
                    )

                    db.session.add(
                        Event(
                            user_id=user.id,
                            event_type='bot_start',
                            message=f"/start dal bot per chat {chat_id}",
                        )
                    )
                    db.session.commit()
                else:
                    message = (
                        f"👋 Benvenuto su EtnaMonitor, {username}!\n\n"
                        "Per collegare il bot:"
                        "\n1. Accedi su etna-monitor-v2.onrender.com"
                        f"\n2. Inserisci questo Chat ID nella dashboard: {chat_id}"
                        "\n3. Avvia nuovamente /start"
                        "\n\nGli utenti Free ricevono 1 alert gratuito di prova; attiva Premium per notifiche illimitate."
                    )

                await update.message.reply_text(message)

            except Exception:
                logger.exception("Error handling /start command")
                await update.message.reply_text("❌ Errore temporaneo. Riprova più tardi.")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = (
            "🌋 **EtnaMonitor Bot**\n\n"
            "**Comandi disponibili:**\n"
            "/start - Collega il tuo account\n"
            "/help - Mostra questo messaggio\n"
            "/status - Verifica stato collegamento\n\n"
            "**Piani disponibili:**\n"
            "• Free: 1 alert gratuito di prova con soglia standard.\n"
            "• Premium: alert illimitati, soglia personalizzata, log eventi.\n\n"
            "**Supporto:** salvoferro16@gmail.com"
        )

        await update.message.reply_text(help_text)

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        chat_id = str(update.effective_chat.id)

        with self.app.app_context():
            try:
                user = (
                    User.query.filter(
                        (User.telegram_chat_id == chat_id) | (User.chat_id == chat_id)
                    )
                    .order_by(User.id.asc())
                    .first()
                )

                if user:
                    plan = "Premium ✅" if user.has_premium_access else "Free"
                    threshold = user.threshold or Config.ALERT_THRESHOLD_DEFAULT
                    free_state = (
                        "Alert di prova disponibile"
                        if not user.free_alert_consumed
                        else "Alert di prova già utilizzato"
                    )
                    message = (
                        "📊 **Stato Account**\n\n"
                        f"Email: {user.email}\n"
                        f"Piano: {plan}\n"
                        f"Soglia attiva: {threshold:.2f} mV\n"
                        f"Alert gratuiti: {free_state}\n"
                        f"Chat ID: {chat_id}"
                    )
                else:
                    message = (
                        f"❌ Account non collegato\n\nChat ID: {chat_id}\n"
                        "Aggiungi l'ID nella dashboard e avvia nuovamente /start."
                    )

                await update.message.reply_text(message)

            except Exception:
                logger.exception("Error handling /status command")
                await update.message.reply_text("❌ Errore nel recuperare lo stato.")
