from flask import Flask, g, redirect, request, render_template, url_for, current_app
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix  # Ensure proxy headers are honored for HTTPS redirects
import os
import sys
import redis
import warnings
from datetime import datetime, timedelta
from time import perf_counter
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from sqlalchemy import text

# Alembic può non essere disponibile: gestiscilo in modo sicuro
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

from sqlalchemy.orm import load_only
from sqlalchemy.pool import QueuePool, StaticPool

from .routes.main import bp as main_bp
from .routes.experience import bp as experience_bp
from .routes.community import bp as community_bp
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.auth import bp as auth_bp, legacy_bp as legacy_auth_bp
from .routes.api import api_bp
from .routes.status import status_bp
from .routes.billing import bp as billing_bp
from .routes.internal import internal_bp
from backend.routes.admin_stats import admin_stats_bp
from .bootstrap import (
    ensure_curva_csv,
    ensure_schema_current,
    ensure_user_schema_guard,
)
from .models import db
from .filters import md
from .utils.csrf import generate_csrf_token
from .utils.logger import configure_logging
from config import Config, get_database_uri_from_env
from .extensions import cache
from .security import build_csp, talisman

login_manager = LoginManager()
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


SLOW_REQUEST_THRESHOLD_MS = 300


def _is_truthy_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def _ensure_partners_table(app: Flask) -> None:
    """Ensure the partners table exists with the expected schema."""

    create_sql = text(
        """
        CREATE TABLE IF NOT EXISTS partners (
            id SERIAL PRIMARY KEY,
            name TEXT,
            category TEXT,
            description TEXT,
            website TEXT,
            contact TEXT,
            image_url TEXT,
            lat DOUBLE PRECISION,
            lon DOUBLE PRECISION,
            verified BOOLEAN DEFAULT FALSE,
            visible BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
    )

    try:
        with db.engine.connect() as conn:
            conn.execute(create_sql)
            conn.commit()
        app.logger.info("[BOOT] partners table ensured ✅")
    except Exception as ex:  # pragma: no cover - defensive fallback
        app.logger.warning("[BOOT] partners table ensure failed: %s", ex)


def _ensure_sponsor_tables(app: Flask) -> None:
    """Ensure sponsor banner tables exist to avoid runtime failures."""

    dialect = db.engine.dialect.name
    if dialect == "sqlite":
        statements = [
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    description TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banner_impressions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    banner_id INTEGER NOT NULL,
                    ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    page TEXT,
                    session_id TEXT,
                    user_id INTEGER,
                    ip_hash TEXT,
                    FOREIGN KEY(banner_id) REFERENCES sponsor_banners(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banner_clicks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    banner_id INTEGER NOT NULL,
                    ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    page TEXT,
                    session_id TEXT,
                    user_id INTEGER,
                    ip_hash TEXT,
                    FOREIGN KEY(banner_id) REFERENCES sponsor_banners(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_banner_impression_session
                ON sponsor_banner_impressions (banner_id, session_id, ts)
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_banner_click_session
                ON sponsor_banner_clicks (banner_id, session_id, ts)
                """
            ),
        ]
    else:
        statements = [
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banners (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR(120) NOT NULL,
                    image_url VARCHAR(512) NOT NULL,
                    target_url VARCHAR(512) NOT NULL,
                    description VARCHAR(255),
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banner_impressions (
                    id SERIAL PRIMARY KEY,
                    banner_id INTEGER NOT NULL REFERENCES sponsor_banners(id) ON DELETE CASCADE,
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    page VARCHAR(255),
                    session_id VARCHAR(64),
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    ip_hash VARCHAR(64)
                )
                """
            ),
            text(
                """
                CREATE TABLE IF NOT EXISTS sponsor_banner_clicks (
                    id SERIAL PRIMARY KEY,
                    banner_id INTEGER NOT NULL REFERENCES sponsor_banners(id) ON DELETE CASCADE,
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    page VARCHAR(255),
                    session_id VARCHAR(64),
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    ip_hash VARCHAR(64)
                )
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_banner_impression_session
                ON sponsor_banner_impressions (banner_id, session_id, ts)
                """
            ),
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_banner_click_session
                ON sponsor_banner_clicks (banner_id, session_id, ts)
                """
            ),
        ]

    try:
        with db.engine.connect() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.commit()
        app.logger.info("[BOOT] Sponsor banner tables ensured ✅")
    except Exception:
        app.logger.exception("[BOOT] Sponsor banner table ensure failed")


def create_app(config_overrides: dict | None = None):
    global limiter
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.config.setdefault("DATA_DIR", Config.DATA_DIR)
    app.config.setdefault("CSV_PATH", Config.CSV_PATH)
    app.config.setdefault("STATIC_ASSET_VERSION", Config.STATIC_ASSET_VERSION)
    app.config.setdefault("SEND_FILE_MAX_AGE_DEFAULT", 60 * 60 * 24 * 7)
    app.config.setdefault(
        "WORKER_HEARTBEAT_INTERVAL", int(os.getenv("WORKER_HEARTBEAT_INTERVAL", "30"))
    )
    app.jinja_env.filters["md"] = md
    app.jinja_env.globals["csrf_token"] = generate_csrf_token
    app.jinja_env.globals["static_asset_version"] = app.config["STATIC_ASSET_VERSION"]
    app.jinja_env.globals["STATIC_ASSET_VERSION"] = app.config["STATIC_ASSET_VERSION"]

    configure_logging(app.config.get("LOG_DIR"))
    app.logger.info(
        "[BOOT] Logging configured. Writing to %s",
        Path(app.config.get("LOG_DIR", "logs")) / "app.log",
    )

    warnings.filterwarnings("ignore", message="Using the in-memory storage")

    app_env = (
        os.getenv("APP_ENV")
        or app.config.get("APP_ENV")
        or os.getenv("FLASK_ENV")
        or "development"
    ).lower()
    app.config["APP_ENV"] = app_env

    alembic_running = _is_truthy_env(os.getenv("ALEMBIC_RUNNING"))
    app.config["ALEMBIC_RUNNING"] = alembic_running
    if alembic_running:
        app.logger.info(
            "[BOOT] ALEMBIC_RUNNING detected – skipping startup side-effects"
        )

    secret_from_env = os.getenv("SECRET_KEY")
    if secret_from_env:
        app.config["SECRET_KEY"] = secret_from_env

    secret_key = app.config.get("SECRET_KEY")

    if app.config.get("TESTING"):
        if not secret_key or secret_key in {"dev", "change-me"}:
            app.config["SECRET_KEY"] = "test-secret-key"
    elif app_env == "production":
        normalized_secret = secret_key if isinstance(secret_key, str) else str(secret_key or "")
        if not normalized_secret:
            app.logger.critical(
                "[BOOT] SECRET_KEY environment variable missing. Set a strong value (>=32 characters) before starting."
            )
            sys.exit(1)
        if len(normalized_secret) < 32:
            app.logger.critical(
                "[BOOT] SECRET_KEY is too short. Provide a value with at least 32 characters."
            )
            sys.exit(1)
    else:
        if not secret_key or secret_key in {"dev", "change-me", ""}:
            app.config["SECRET_KEY"] = "dev-secret-key"
            app.logger.warning(
                "[BOOT] SECRET_KEY not provided; using development fallback. Do not use in production."
            )

    app.config.setdefault("SESSION_COOKIE_SECURE", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("COMPRESS_ALGORITHM", ["br", "gzip"])

    app.config.setdefault("LAST_CSV_READ_AT", None)
    app.config.setdefault("LAST_CSV_LAST_TS", None)
    app.config.setdefault("LAST_CSV_ROW_COUNT", 0)
    app.config.setdefault("LAST_CSV_ERROR", None)
    app.config["START_TIME"] = datetime.utcnow()
    app.send_file_max_age_default = timedelta(hours=6)

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
    engine_defaults = {
        "pool_size": 5,
        "max_overflow": 5,
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }
    existing_engine_options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}))
    engine_defaults.update(existing_engine_options)

    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "") or ""

    if database_uri.startswith("sqlite"):
        # SQLite (especially :memory:) does not accept pool sizing parameters.
        for key in ("pool_size", "max_overflow", "pool_recycle"):
            engine_defaults.pop(key, None)

    poolclass = engine_defaults.get("poolclass")
    if poolclass:
        try:
            is_static_pool = issubclass(poolclass, StaticPool)
            is_queue_pool = issubclass(poolclass, QueuePool)
        except TypeError:
            is_static_pool = False
            is_queue_pool = False

        if is_static_pool:
            # StaticPool does not accept queue sizing parameters.
            for key in ("pool_size", "max_overflow", "pool_recycle"):
                engine_defaults.pop(key, None)
        elif not is_queue_pool:
            # For custom pools drop sizing knobs that may not be supported.
            engine_defaults.pop("pool_size", None)
            engine_defaults.pop("max_overflow", None)

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_defaults
    configured_canonical = os.getenv("CANONICAL_HOST")
    if not configured_canonical and os.getenv("FLASK_ENV") == "production":
        configured_canonical = "etnamonitor.it"

    app.config["CANONICAL_HOST"] = configured_canonical or ""

    enable_seo_routes = os.getenv("ENABLE_SEO_ROUTES", "1").lower() not in {
        "0",
        "false",
        "no",
    }
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
                    url = request.url.replace(
                        f"//{incoming_host}", f"//{canonical_host}", 1
                    )
                    return redirect(url, code=301)

    @app.before_request
    def start_request_timer():  # pragma: no cover - tiny helper
        g._request_started_at = perf_counter()

    @app.context_processor
    def inject_current_year():
        return {"current_year": get_current_year(), "get_current_year": get_current_year}

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
        default_og_image = url_for("static", filename="icons/icon-512.png", _external=True)
        logo_url = url_for(
            "static", filename="icons/apple-touch-icon.png", _external=True
        )
        structured_base = [
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "EtnaMonitor",
                "url": canonical_base,
                "logo": logo_url,
                "sameAs": [
                    "https://www.linkedin.com/in/ferrosalvatore",
                    "https://www.ct.ingv.it",
                ],
                "contactPoint": [
                    {
                        "@type": "ContactPoint",
                        "contactType": "customer support",
                        "email": "salvoferro16@gmail.com",
                        "availableLanguage": ["it", "en"],
                    }
                ],
            },
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": "EtnaMonitor",
                "url": canonical_base,
                "inLanguage": "it-IT",
                "isAccessibleForFree": True,
            },
        ]

        return {
            "default_page_title": default_title,
            "default_page_description": default_description,
            "default_og_image": default_og_image,
            "canonical_url": canonical_url,
            "canonical_base_url": canonical_base,
            "default_structured_data_base": structured_base,
            "ads_tracking_enabled": bool(app.config.get("ADS_ROUTES_ENABLED")),
        }

    @app.context_processor
    def inject_analytics_settings():
        return {
            "analytics": {
                "ga_measurement_id": os.getenv("GA_MEASUREMENT_ID", "").strip(),
                "google_ads_id": os.getenv("GOOGLE_ADS_ID", "").strip(),
                "plausible_domain": os.getenv("PLAUSIBLE_DOMAIN", "").strip(),
            }
        }

    # Google OAuth redirect URI (deve combaciare con quello su Google Cloud Console)
    app.config["GOOGLE_REDIRECT_URI"] = os.getenv("GOOGLE_REDIRECT_URI", "")

    # Rispetta gli header del proxy (Render) per URL esterni corretti
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # type: ignore[attr-defined]

    db.init_app(app)
    migrate.init_app(app, db)

    skip_schema_validation_env = _is_truthy_env(os.getenv("SKIP_SCHEMA_VALIDATION"))

    if alembic_running:
        migration_status = {
            "head_revision": None,
            "current_revision": None,
            "database_online": False,
            "is_up_to_date": False,
            "error": "Schema validation skipped via ALEMBIC_RUNNING",
            "skipped": True,
        }
    elif skip_schema_validation_env:
        migration_status = {
            "head_revision": None,
            "current_revision": None,
            "database_online": False,
            "is_up_to_date": False,
            "error": "Schema validation skipped via SKIP_SCHEMA_VALIDATION",
            "skipped": True,
        }
    else:
        with app.app_context():
            migration_status = ensure_schema_current(app)

    app.config["ALEMBIC_MIGRATION_STATUS"] = migration_status

    if not alembic_running:
        if not migration_status.get("database_online") and not skip_schema_validation_env:
            app.logger.warning("[BOOT] Database connection unavailable during startup checks")
        elif migration_status.get("is_up_to_date"):
            app.logger.info(
                "[BOOT] Database schema verified current (revision=%s)",
                migration_status.get("current_revision"),
            )

        if app_env == "production" and not skip_schema_validation_env and not migration_status.get(
            "is_up_to_date"
        ):
            app.logger.critical(
                "[BOOT] Database schema not up to date (current=%s head=%s). "
                "Run 'alembic upgrade head' before starting or set ALLOW_AUTO_MIGRATE=1.",
                migration_status.get("current_revision"),
                migration_status.get("head_revision"),
            )
            sys.exit(2)

    if skip_schema_validation_env and not alembic_running:
        app.logger.info("[BOOT] Schema validation skipped due to SKIP_SCHEMA_VALIDATION=1")

    if not alembic_running:
        curva_path = ensure_curva_csv(app)
        app.config["CURVA_CSV_PATH"] = str(curva_path)
    else:
        app.config["CURVA_CSV_PATH"] = None

    # Auto-migrazione opzionale (DISABILITATA di default). Richiede app context.
    if (
        not alembic_running
        and _migrate_available
        and os.getenv("AUTO_MIGRATE", "0").lower() in {"1", "true", "yes"}
    ):
        try:  # pragma: no cover - integration with alembic CLI
            from flask_migrate import upgrade as alembic_upgrade
            with app.app_context():
                alembic_upgrade()
            app.logger.info("[BOOT] Alembic auto-migrate: upgrade head OK.")
        except Exception as ex:  # pragma: no cover - defensive logging
            app.logger.warning("[BOOT] Alembic auto-migrate failed: %s", ex)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.session_protection = "strong"

    from .models.user import User  # imported lazily to avoid circular imports

    @login_manager.user_loader
    def load_user(user_id: str):  # pragma: no cover - thin integration wrapper
        try:
            return (
                db.session.query(User)
                .options(
                    load_only(
                        User.id,
                        User.email,
                        User.google_id,
                        User.name,
                        User.picture_url,
                        User.is_admin,
                        User.is_premium,
                    )
                )
                .filter(User.id == int(user_id))
                .first()
            )
        except Exception as e:  # pragma: no cover - defensive guard
            current_app.logger.error("[LOGIN] user_loader failed: %s", e, exc_info=True)
            return None

    app.config["MIGRATIONS_AVAILABLE"] = _migrate_available

    disable_scheduler = os.getenv("DISABLE_SCHEDULER", "0").lower() in {"1", "true", "yes"}
    if not alembic_running:
        if disable_scheduler:
            app.logger.info(
                "[BOOT] Scheduler disabled via DISABLE_SCHEDULER environment variable"
            )
        else:
            app.logger.info(
                "[BOOT] Scheduler execution delegated to worker process (python -m app.worker)"
            )

    telegram_mode = (app.config.get("TELEGRAM_BOT_MODE") or "off").lower()
    telegram_status = {
        "enabled": telegram_mode in {"polling", "webhook"},
        "running": False,
        "mode": telegram_mode,
        "last_error": None,
        "managed_by": "worker" if telegram_mode == "polling" else "app",
    }
    if not alembic_running:
        if telegram_mode == "webhook":
            app.logger.info(
                "[BOOT] Telegram bot configured for webhook mode; polling is disabled"
            )
        elif telegram_mode == "polling":
            app.logger.info("[BOOT] Telegram bot polling managed by background worker ✅")
        else:
            app.logger.info("[BOOT] Telegram bot disabled (mode=%s)", telegram_mode)

    app.config["TELEGRAM_BOT_STATUS"] = telegram_status

    if not alembic_running:
        with app.app_context():
            ensure_user_schema_guard(app)
            _ensure_partners_table(app)
            _ensure_sponsor_tables(app)

            # Auto-promozione admin
            try:
                with db.engine.connect() as conn:
                    for email in app.config.get("ADMIN_EMAILS_SET", set()):
                        normalized_email = (email or "").strip().lower()
                        if not normalized_email:
                            continue
                        conn.execute(
                            text(
                                "UPDATE users SET is_admin = TRUE WHERE lower(email) = :e"
                            ),
                            {"e": normalized_email},
                        )
                    conn.commit()
                app.logger.info("[BOOT] Admin auto-promotion applied to existing users.")
            except Exception:
                app.logger.exception("[BOOT] Admin auto-promotion failed")

    csp = build_csp()
    app.config["BASE_CONTENT_SECURITY_POLICY"] = build_csp()

    talisman.init_app(
        app,
        content_security_policy=csp,
        content_security_policy_nonce_in=["script-src"],
        force_https=os.getenv("FLASK_ENV") == "production",
        frame_options="SAMEORIGIN",
    )

    redis_url = os.getenv("REDIS_URL")
    cache_config = {"CACHE_DEFAULT_TIMEOUT": 90}
    if redis_url:
        cache_config.update(
            {"CACHE_TYPE": "RedisCache", "CACHE_REDIS_URL": redis_url}
        )
    else:
        cache_config["CACHE_TYPE"] = "SimpleCache"
    cache.init_app(app, config=cache_config)

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

    try:
        from .context_processors import inject_user_theme as inject_user_theme_context
    except Exception as exc:
        app.logger.warning("User theme context disabled: %s", exc)
    else:
        app.context_processor(inject_user_theme_context)

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
    app.register_blueprint(community_bp)
    app.register_blueprint(admin_stats_bp, url_prefix="/admin/api")
    app.register_blueprint(api_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(internal_bp)

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

    @app.after_request
    def finalize_response(response):  # pragma: no cover - thin instrumentation
        started_at = getattr(g, "_request_started_at", None)
        if started_at is not None:
            elapsed_ms = (perf_counter() - started_at) * 1000
            if elapsed_ms > SLOW_REQUEST_THRESHOLD_MS:
                app.logger.warning(
                    "[SLOW] %s %s took %.1f ms", request.method, request.path, elapsed_ms
                )
        if request.path.startswith("/static/"):
            response.headers.setdefault(
                "Cache-Control", "public, max-age=604800, immutable"
            )
        return response

    @app.errorhandler(500)
    def render_internal_error(error):  # pragma: no cover - presentation only
        app.logger.exception("[500] Internal server error")
        return (
            render_template(
                "errors/500.html",
                page_title="Qualcosa è andato storto",
                page_description="Si è verificato un errore inaspettato. Riprova fra poco.",
            ),
            500,
        )

    return app


app = create_app()
