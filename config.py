import os
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

DATABASE_ENV_PRIORITY = (
    "INTERNAL_DATABASE_URL",
    "DATABASE_URL",
    "EXTERNAL_DATABASE_URL",
)


def normalize_database_uri(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return uri

    if uri.startswith("postgres://"):
        return "postgresql+psycopg2://" + uri[len("postgres://"):]

    if uri.startswith("postgresql://") and not uri.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg2://" + uri[len("postgresql://"):]

    return uri


def get_database_uri_from_env(default: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    for key in DATABASE_ENV_PRIORITY:
        value = os.getenv(key)
        if value:
            return normalize_database_uri(value), key

    if default is not None:
        return normalize_database_uri(default), "default"

    return None, None


DEFAULT_SQLITE_URI = "sqlite:///etna_monitor.db"
RESOLVED_DATABASE_URI, RESOLVED_DATABASE_SOURCE = get_database_uri_from_env(DEFAULT_SQLITE_URI)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = RESOLVED_DATABASE_URI or DEFAULT_SQLITE_URI
    SQLALCHEMY_DATABASE_URI_SOURCE = RESOLVED_DATABASE_SOURCE
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    INGV_URL = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    ALERT_THRESHOLD_DEFAULT = float(os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM", "")

    BUILD_SHA = os.getenv("RENDER_GIT_COMMIT", "")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    PLAUSIBLE_DOMAIN = os.getenv("PLAUSIBLE_DOMAIN", "")
    GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")
    LOG_DIR = os.getenv("LOG_DIR", "logs")
