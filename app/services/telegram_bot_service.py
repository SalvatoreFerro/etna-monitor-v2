import asyncio
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from app.models import db
from app.models.user import User
from app.models.event import Event
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
        """Handle /start command"""
        chat_id = str(update.effective_chat.id)
        username = update.effective_user.username or "Unknown"
        
        with self.app.app_context():
            try:
                user = User.query.filter_by(chat_id=chat_id).first()
                
                if user:
                    if user.has_premium_access:
                        message = f"✅ Ciao {username}! Il tuo account Premium è già collegato.\n\nRiceverai notifiche quando il tremore supera la tua soglia personalizzata ({user.threshold or 2.0} mV)."
                    else:
                        message = f"👋 Ciao {username}! Il tuo account è collegato ma non è Premium.\n\nPer ricevere notifiche personalizzate, attiva Premium su etna-monitor-v2.onrender.com"
                else:
                    message = f"👋 Benvenuto su EtnaMonitor, {username}!\n\n🔗 Per collegare il tuo account:\n1. Accedi su etna-monitor-v2.onrender.com\n2. Vai nel Dashboard\n3. Inserisci questo Chat ID: {chat_id}\n\n⚠️ Solo gli utenti Premium possono ricevere notifiche personalizzate."
                
                await update.message.reply_text(message)
                
                event = Event(
                    user_id=user.id if user else None,
                    event_type='bot_interaction',
                    value=0,
                    threshold=0,
                    message=f'Bot /start command from {username} (chat_id: {chat_id})'
                )
                db.session.add(event)
                db.session.commit()
                
            except Exception:
                logger.exception("Error handling /start command")
                await update.message.reply_text("❌ Errore temporaneo. Riprova più tardi.")
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """🌋 **EtnaMonitor Bot**

**Comandi disponibili:**
/start - Collega il tuo account
/help - Mostra questo messaggio
/status - Verifica stato collegamento

**Come funziona:**
1. Registrati su etna-monitor-v2.onrender.com
2. Attiva Premium per notifiche personalizzate
3. Collega il bot dal Dashboard
4. Ricevi avvisi quando il tremore supera la tua soglia

**Supporto:** salvoferro16@gmail.com"""
        
        await update.message.reply_text(help_text)
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        chat_id = str(update.effective_chat.id)
        
        with self.app.app_context():
            try:
                user = User.query.filter_by(chat_id=chat_id).first()
                
                if user:
                    status = "Premium ✅" if user.has_premium_access else "Free"
                    threshold = user.threshold or 2.0
                    message = f"📊 **Stato Account**\n\nEmail: {user.email}\nTipo: {status}\nSoglia: {threshold} mV\nChat ID: {chat_id}"
                else:
                    message = f"❌ Account non collegato\n\nChat ID: {chat_id}\nCollega il tuo account su etna-monitor-v2.onrender.com"
                
                await update.message.reply_text(message)
                
            except Exception:
                logger.exception("Error handling /status command")
                await update.message.reply_text("❌ Errore nel recuperare lo stato.")
