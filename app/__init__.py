from flask import Flask, redirect, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_compress import Compress
from werkzeug.middleware.proxy_fix import ProxyFix  # Ensure proxy headers are honored for HTTPS redirects
import os
import redis
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from pathlib import Path
try:  # pragma: no cover - optional dependency guard
    from flask_migrate import Migrate
    _migrate_available = True
except ModuleNotFoundError:  # pragma: no cover - fallback for restricted environments
    _migrate_available = False

    class Migrate:  # type: ignore[override]
        def init_app(self, app, db):
            app.logger.warning(
                "[BOOT] Flask-Migrate not available. Database migrations commands are disabled."
            )

from .routes.main import bp as main_bp
from .routes.experience import bp as experience_bp
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.auth import bp as auth_bp, legacy_bp as legacy_auth_bp
from .routes.api import api_bp
from .routes.status import status_bp
from .routes.billing import bp as billing_bp
from backend.routes.admin_stats import admin_stats_bp
from .models import db
from .utils.csrf import generate_csrf_token
from .services.scheduler_service import SchedulerService
from .utils.logger import configure_logging
from config import Config, get_database_uri_from_env


limiter = None
migrate = Migrate()


def _mask_database_uri(uri: str) -> str:
    try:
        parsed = urlparse(uri)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "***")
            parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)
    except Exception:
        return "<unavailable>"

def create_app(config_overrides: dict | None = None):
    global limiter
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.jinja_env.globals['csrf_token'] = generate_csrf_token

    configure_logging(app.config.get("LOG_DIR"))
    app.logger.info("[BOOT] Logging configured. Writing to %s", Path(app.config.get("LOG_DIR", "logs")) / "app.log")

    secret_key = app.config.get("SECRET_KEY")
    if not secret_key or secret_key in {"dev", "change-me"}:
        raise RuntimeError("SECRET_KEY environment variable must be set to a secure, non-default value.")

    app.config.setdefault("LAST_CSV_READ_AT", None)
    app.config.setdefault("LAST_CSV_LAST_TS", None)
    app.config.setdefault("LAST_CSV_ROW_COUNT", 0)
    app.config.setdefault("LAST_CSV_ERROR", None)
    app.config["START_TIME"] = datetime.utcnow()

    override_database_uri = None
    if config_overrides and "SQLALCHEMY_DATABASE_URI" in config_overrides:
        override_database_uri = config_overrides["SQLALCHEMY_DATABASE_URI"]

    if override_database_uri:
        app.config["SQLALCHEMY_DATABASE_URI"] = override_database_uri
        masked_url = _mask_database_uri(override_database_uri)
        app.logger.info(
            f"[BOOT] SQLALCHEMY_DATABASE_URI configured via overrides: {masked_url}"
        )
    else:
        database_url, database_source = get_database_uri_from_env()
        if database_url:
            app.config["SQLALCHEMY_DATABASE_URI"] = database_url
            if database_source:
                masked_url = _mask_database_uri(database_url)
                app.logger.info(
                    f"[BOOT] SQLALCHEMY_DATABASE_URI resolved from {database_source}: {masked_url}"
                )
        else:
            app.logger.warning(
                "[BOOT] DATABASE_URL not set. Falling back to default SQLALCHEMY_DATABASE_URI from Config."
            )
            app.config["SQLALCHEMY_DATABASE_URI"] = Config.SQLALCHEMY_DATABASE_URI
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["CANONICAL_HOST"] = os.getenv("CANONICAL_HOST", "")

    enable_seo_routes = os.getenv("ENABLE_SEO_ROUTES", "0") == "1"
    enable_ads_routes = os.getenv("ENABLE_ADS_ROUTES", "0") == "1"
    app.config["ENABLE_SEO_ROUTES"] = enable_seo_routes
    app.config["ENABLE_ADS_ROUTES"] = enable_ads_routes

    raw = os.getenv("ADMIN_EMAILS", "")
    admin_set = {e.strip().lower() for e in raw.split(",") if e.strip()}
    app.config["ADMIN_EMAILS_SET"] = admin_set
    app.logger.info(f"[BOOT] ADMIN_EMAILS_SET={admin_set}")

    def get_current_year() -> int:
        return datetime.utcnow().year

    @app.before_request
    def enforce_canonical_host():
        if app.config.get("FLASK_ENV") == "production":
            canonical_host = app.config.get("CANONICAL_HOST")
            if canonical_host:
                incoming_host = request.headers.get("X-Forwarded-Host", request.host)
                if incoming_host and incoming_host != canonical_host:
                    url = request.url.replace(f"//{incoming_host}", f"//{canonical_host}", 1)
                    return redirect(url, code=301)

    @app.context_processor
    def inject_current_year():
        return {
            "current_year": get_current_year(),
            "get_current_year": get_current_year,
        }

    def _canonical_base() -> str:
        canonical_host = app.config.get("CANONICAL_HOST") or request.host
        scheme = request.scheme if request.scheme in {"http", "https"} else "https"
        return f"{scheme}://{canonical_host}"

    @app.context_processor
    def inject_meta_defaults():
        canonical_base = _canonical_base()
        canonical_url = f"{canonical_base}{request.path}"
        default_title = "EtnaMonitor – Monitoraggio Etna in tempo reale"
        default_description = (
            "Monitoraggio in tempo reale del tremore vulcanico dell'Etna con dati INGV, "
            "grafici interattivi e avvisi per gli appassionati."
        )
        default_og_image = url_for(
            "static", filename="icons/icon-512.png", _external=True
        )
        logo_url = url_for("static", filename="icons/apple-touch-icon.png", _external=True)
        structured_base = [
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "EtnaMonitor",
                "url": canonical_base,
                "logo": logo_url,
            },
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "EtnaMonitor",
                "url": canonical_base,
                "potentialAction": {
                    "@type": "SearchAction",
                    "target": f"{canonical_base}/search?q={{search_term_string}}",
                    "query-input": "required name=search_term_string",
                },
            },
        ]

        return {
            "default_page_title": default_title,
            "default_page_description": default_description,
            "default_og_image": default_og_image,
            "canonical_url": canonical_url,
            "canonical_base_url": canonical_base,
            "default_structured_data_base": structured_base,
            "analytics": {
                "plausible_domain": app.config.get("PLAUSIBLE_DOMAIN"),
                "ga_measurement_id": app.config.get("GA_MEASUREMENT_ID"),
            },
            "ads_tracking_enabled": bool(app.config.get("ADS_ROUTES_ENABLED")),
        }

    # Capture the Google redirect URI from the environment so the OAuth flow
    # uses the exact value configured on Google Cloud Console.
    app.config["GOOGLE_REDIRECT_URI"] = os.getenv("GOOGLE_REDIRECT_URI", "")

    # Honor proxy headers inserted by Render (or any reverse proxy) so that
    # url_for(..., _external=True) builds HTTPS links with the correct host.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # type: ignore[attr-defined]
    
    db.init_app(app)
    migrate.init_app(app, db)
    app.config["MIGRATIONS_AVAILABLE"] = _migrate_available

    disable_scheduler = os.getenv("DISABLE_SCHEDULER", "0").lower() in {"1", "true", "yes"}
    if disable_scheduler:
        app.logger.info("[BOOT] Scheduler disabled via DISABLE_SCHEDULER environment variable")
    else:
        try:
            scheduler = SchedulerService()
            scheduler.init_app(app)
            app.logger.info("[BOOT] Scheduler initialized")
        except Exception:
            app.logger.exception("[BOOT] Scheduler initialization failed")

    telegram_mode = (app.config.get("TELEGRAM_BOT_MODE") or "off").lower()
    telegram_status = {
        "enabled": telegram_mode in {"polling", "webhook"},
        "running": False,
        "mode": telegram_mode,
        "last_error": None,
    }
    if telegram_mode == "polling":
        try:
            from .services.telegram_bot_service import TelegramBotService

            telegram_bot = TelegramBotService()
            telegram_bot.init_app(app)
            telegram_status["running"] = True
            app.logger.info("[BOOT] Telegram bot initialized in polling mode")
        except Exception as exc:
            telegram_status["last_error"] = str(exc)
            app.logger.exception("[BOOT] Telegram bot initialization failed")
    elif telegram_mode == "webhook":
        app.logger.info("[BOOT] Telegram bot configured for webhook mode; polling is disabled")
    else:
        app.logger.info("[BOOT] Telegram bot disabled (mode=%s)", telegram_mode)

    app.config["TELEGRAM_BOT_STATUS"] = telegram_status

    with app.app_context():
        try:
            from sqlalchemy import text

            with db.engine.connect() as conn:
                for email in app.config.get("ADMIN_EMAILS_SET", set()):
                    conn.execute(text("UPDATE users SET is_admin=1 WHERE lower(email)=:e"), {"e": email})
                conn.commit()
            app.logger.info("[BOOT] Admin auto-promotion applied to existing users.")
        except Exception as ex:
            app.logger.warning("[BOOT] Admin auto-promotion failed: %s", ex)

    csp = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "https://js.stripe.com",
            "https://plausible.io",
            "https://www.googletagmanager.com",
        ],
        'style-src': [
            "'self'",
            "'unsafe-inline'",
            "https://fonts.googleapis.com",
            "https://cdnjs.cloudflare.com"
        ],
        'font-src': [
            "'self'",
            "https://fonts.gstatic.com",
            "https://cdnjs.cloudflare.com"
        ],
        'img-src': ["'self'", "data:", "https:"],
        'connect-src': [
            "'self'",
            "https://api.stripe.com",
            "https://plausible.io",
            "https://www.google-analytics.com",
        ],
        'frame-src': ["https://js.stripe.com", "https://hooks.stripe.com"]
    }

    Talisman(
        app,
        content_security_policy=csp,
        content_security_policy_nonce_in=['script-src'],
        force_https=os.getenv('FLASK_ENV') == 'production'
    )
    
    Compress(app)
    
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            storage_uri=redis_url,
            default_limits=["200 per day", "50 per hour"],
        )
    else:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            default_limits=["200 per day", "50 per hour"],
        )

    app.extensions["limiter"] = limiter
    
    from .context_processors import inject_user as inject_user_context

    app.context_processor(inject_user_context)

    try:
        from .context_processors import (
            inject_sponsor_banners as inject_sponsor_banners_context,
        )
    except Exception as exc:  # pragma: no cover - optional dependency guard
        app.logger.warning("Sponsor banner context disabled: %s", exc)
    else:
        app.context_processor(inject_sponsor_banners_context)
    
    seo_blueprint = None
    if enable_seo_routes:
        try:
            from .routes.seo import bp as seo_blueprint
        except Exception as exc:  # pragma: no cover - optional dependency guard
            app.logger.warning("SEO routes disabled: %s", exc)
            seo_blueprint = None
        else:
            app.logger.info("SEO routes enabled")

    ads_blueprint = None
    if enable_ads_routes:
        try:
            from .routes.ads import bp as ads_blueprint
        except Exception as exc:  # pragma: no cover - optional dependency guard
            app.logger.warning("Ads routes disabled: %s", exc)
            ads_blueprint = None
        else:
            app.logger.info("Ads routes enabled")

    app.register_blueprint(main_bp)
    app.register_blueprint(experience_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(legacy_auth_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(billing_bp)
    app.register_blueprint(admin_stats_bp, url_prefix="/admin/api")
    app.register_blueprint(api_bp)
    app.register_blueprint(status_bp)

    if seo_blueprint is not None:
        app.register_blueprint(seo_blueprint)
        app.config["SEO_ROUTES_ENABLED"] = True
    else:
        app.config["SEO_ROUTES_ENABLED"] = False

    if ads_blueprint is not None:
        app.register_blueprint(ads_blueprint)
        app.config["ADS_ROUTES_ENABLED"] = True
    else:
        app.config["ADS_ROUTES_ENABLED"] = False

    return app

app = create_app()
