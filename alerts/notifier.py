from app.utils.logger import get_logger

logger = get_logger(__name__)

def send_telegram_alert(token: str, chat_id: str, text: str) -> bool:
    """Mock semplice – l'agent sostituirà con chiamata reale o libreria."""
    if not token or not chat_id:
        logger.warning("Token/chat_id mancanti: niente invio")
        return False
    logger.info("[TELEGRAM] → %s: %s", chat_id, text)
    return True
