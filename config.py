import os
import subprocess
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()


DEFAULT_GA_MEASUREMENT_ID = "G-Z3ESSERP7W"
DEFAULT_GOOGLE_ADS_ID = "AW-1768143584"


def _resolve_static_asset_version() -> str:
    explicit = os.getenv("STATIC_ASSET_VERSION")
    if explicit:
        return explicit

    render_commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if render_commit:
        return render_commit[:8]

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if git_sha:
            return git_sha
    except Exception:
        pass

    return "dev"

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


def _resolve_telegram_bot_mode() -> str:
    """Return the normalized Telegram bot mode from environment variables."""

    mode = (os.getenv("TELEGRAM_BOT_MODE") or "").strip().lower()
    if mode:
        if mode in {"off", "polling", "webhook"}:
            return mode
        return "off"

    legacy_flag = (os.getenv("ENABLE_TELEGRAM_BOT") or "").strip().lower()
    if legacy_flag in {"1", "true", "yes"}:
        return "polling"
    return "off"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev")
    SQLALCHEMY_DATABASE_URI = RESOLVED_DATABASE_URI or DEFAULT_SQLITE_URI
    SQLALCHEMY_DATABASE_URI_SOURCE = RESOLVED_DATABASE_SOURCE
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Enable SQLAlchemy's connection health checks so that stale or
    # terminated connections are transparently replaced instead of surfacing
    # as ``OperationalError`` exceptions (e.g. ``SSL error: decryption failed``)
    # during OAuth callbacks when the database closes an idle connection.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "280")),
        "pool_size": int(os.getenv("SQLALCHEMY_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "5")),
    }

    INGV_URL = os.getenv("INGV_URL", "https://www.ct.ingv.it/RMS_Etna/2.png")
    ALERT_THRESHOLD_DEFAULT = float(os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))
    PREMIUM_DEFAULT_THRESHOLD = float(
        os.getenv("PREMIUM_DEFAULT_THRESHOLD", os.getenv("ALERT_THRESHOLD_DEFAULT", "2.0"))
    )
    ALERT_HYSTERESIS_DELTA = float(os.getenv("ALERT_HYSTERESIS_DELTA", "0.2"))

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_BOT_MODE = _resolve_telegram_bot_mode()
    PAYPAL_DONATION_LINK = os.getenv("PAYPAL_DONATION_LINK", "")

    PRIVACY_POLICY_VERSION = os.getenv("PRIVACY_POLICY_VERSION", "2024-07")

    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM", "")

    BUILD_SHA = os.getenv("RENDER_GIT_COMMIT", "")

    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    PLAUSIBLE_DOMAIN = os.getenv("PLAUSIBLE_DOMAIN", "")
    GA_MEASUREMENT_ID = (
        os.getenv("GA_MEASUREMENT_ID", DEFAULT_GA_MEASUREMENT_ID).strip()
        or DEFAULT_GA_MEASUREMENT_ID
    )
    ADSENSE_ENABLE = (
        os.getenv("ADSENSE_ENABLE", "").strip().lower() in {"1", "true", "yes"}
    )
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    DATA_DIR = os.getenv("DATA_DIR", "/var/tmp")
    CSV_PATH = os.getenv("CSV_PATH") or os.path.join(DATA_DIR, "curva.csv")
    STATIC_ASSET_VERSION = _resolve_static_asset_version()
    
    # Archive settings
    ARCHIVE_BASE_PATH = os.getenv("ARCHIVE_BASE_PATH", "data/archives")
    ARCHIVE_RETENTION_DAYS = int(os.getenv("ARCHIVE_RETENTION_DAYS", "90"))
