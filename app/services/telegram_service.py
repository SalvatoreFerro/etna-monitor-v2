import requests
import pandas as pd
import os
from datetime import datetime, timedelta

from sqlalchemy import or_

from app.models import db
from app.models.user import User
from app.models.event import Event
from app.utils.logger import get_logger
from config import Config

logger = get_logger(__name__)

class TelegramService:
    def __init__(self):
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    def send_message(self, chat_id: str, text: str) -> bool:
        """Send Telegram message to user"""
        if not self.bot_token or not chat_id:
            logger.warning("Missing bot token or chat_id")
            return False
        
        try:
            response = requests.post(f"{self.api_url}/sendMessage", 
                                   json={"chat_id": chat_id, "text": text}, 
                                   timeout=10)
            response.raise_for_status()
            logger.info(f"Telegram message sent to {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def calculate_moving_average(self, values, window_size=5):
        """Calculate moving average to avoid false positives"""
        if len(values) < window_size:
            return sum(values) / len(values) if values else 0
        return sum(values[-window_size:]) / window_size
    
    def check_and_send_alerts(self):
        """Check tremor levels and send alerts to Premium users"""
        try:
            data_dir = os.getenv("DATA_DIR", "data")
            curva_file = os.path.join(data_dir, "curva.csv")
            
            if not os.path.exists(curva_file):
                logger.warning("No tremor data available for alert checking")
                return
            
            df = pd.read_csv(curva_file, parse_dates=['timestamp'])
            if df.empty:
                logger.warning("Empty tremor data file")
                return
            
            recent_data = df.tail(10)
            current_value = recent_data['value'].iloc[-1]
            moving_avg = self.calculate_moving_average(recent_data['value'].tolist())
            
            premium_users = User.query.filter(
                or_(User.premium.is_(True), User.is_premium.is_(True)),
                User.chat_id.isnot(None),
                User.chat_id != ''
            ).all()
            
            for user in premium_users:
                threshold = user.threshold or Config.ALERT_THRESHOLD_DEFAULT
                
                if moving_avg > threshold:
                    recent_alert = Event.query.filter(
                        Event.user_id == user.id,
                        Event.event_type == 'alert',
                        Event.timestamp > datetime.utcnow() - timedelta(hours=2)
                    ).first()
                    
                    if not recent_alert:
                        message = f"🌋 ETNA ALERT\n\nTremore vulcanico elevato!\n\nValore attuale: {current_value:.2f} mV\nMedia recente: {moving_avg:.2f} mV\nSoglia: {threshold:.2f} mV\n\nVisita etna-monitor-v2.onrender.com per dettagli"
                        
                        if self.send_message(user.chat_id, message):
                            alert_event = Event(
                                user_id=user.id,
                                event_type='alert',
                                value=moving_avg,
                                threshold=threshold,
                                message=f'Telegram alert sent: {moving_avg:.2f} mV > {threshold:.2f} mV'
                            )
                            db.session.add(alert_event)
                            db.session.commit()
                            logger.info(f"Alert sent to user {user.email}")
            
        except Exception as e:
            logger.error(f"Error in alert checking: {e}")
