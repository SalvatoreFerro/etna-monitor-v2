import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///etna_monitor.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    INGV_URL = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    ALERT_THRESHOLD_DEFAULT = float(os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))
    
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7688152214:AAGJoZFWowVv0aOwNkcsGET6lhmKGoTK1WU")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "000000000")
    
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM", "")

    BUILD_SHA = os.getenv("RENDER_GIT_COMMIT", "")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
