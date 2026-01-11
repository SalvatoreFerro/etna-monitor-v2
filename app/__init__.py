from flask import Flask, g, redirect, request, render_template, url_for, current_app, session
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix  # Ensure proxy headers are honored for HTTPS redirects
import os
import sys
import redis
import warnings
import copy
import click
from datetime import datetime, timedelta
from time import perf_counter
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from sqlalchemy import inspect, text

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

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import load_only
from sqlalchemy.pool import QueuePool, StaticPool

from .routes.main import bp as main_bp
from .routes.partners import bp as partners_bp
from .routes.community import bp as community_bp
from .routes.category import bp as category_bp
from .routes.account import bp as account_bp, register_rate_limits as account_rate_limits
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.admin_moderation import (
    bp as moderation_bp,
    register_rate_limits as moderation_rate_limits,
)
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
from .assets.social_preview import ensure_social_preview_image
from .models import db
from .models.partner import PartnerCategory
from .filters import md
from .utils.csrf import generate_csrf_token
from .utils.user_columns import get_login_safe_user_columns
from .utils.logger import configure_logging
from config import (
    Config,
    DEFAULT_GA_MEASUREMENT_ID,
    get_database_uri_from_env,
)
from .extensions import cache
from .security import BASE_CSP, apply_csp_headers, talisman

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
    """Ensure the partners table exists with the expected schema.

    This function will:
    - create the partners table with the modern schema if missing,
    - or, if the table exists, add any missing columns and try to migrate
      data from legacy columns to the new ones (non-destructive).
    """
    engine = db.engine
    dialect = engine.dialect.name

    # Expected modern columns based on app/models/partner.py and migrations
    expected_columns = {
        "id",
        "category_id",
        "slug",
        "name",
        "short_desc",
        "long_desc",
        "website_url",
        "phone",
        "whatsapp",
        "email",
        "instagram",
        "facebook",
        "tiktok",
        "address",
        "city",
        "geo_lat",
        "geo_lng",
        "logo_path",
        "hero_image_path",
        "extra_data",
        "images_json",
        "status",
        "featured",
        "sort_order",
        "created_at",
        "updated_at",
        "approved_at",
    }

    try:
        inspector = inspect(engine)
    except SQLAlchemyError as exc:
        app.logger.warning("[BOOT] Unable to inspect DB engine for partners table: %s", exc)
        return

    has_table = inspector.has_table("partners")

    try:
        if not has_table:
            app.logger.info("[BOOT] partners table missing; creating with modern schema")
            if dialect == "sqlite":
                create_sql = text(
                    """
                    CREATE TABLE IF NOT EXISTS partners (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category_id INTEGER,
                        slug TEXT UNIQUE,
                        name VARCHAR(180) NOT NULL,
                        short_desc VARCHAR(280),
                        long_desc TEXT,
                        website_url VARCHAR(512),
                        phone VARCHAR(64),
                        whatsapp VARCHAR(64),
                        email VARCHAR(255),
                        instagram VARCHAR(255),
                        facebook VARCHAR(255),
                        tiktok VARCHAR(255),
                        address VARCHAR(255),
                        city VARCHAR(120),
                        geo_lat NUMERIC,
                        geo_lng NUMERIC,
                        logo_path VARCHAR(255),
                        hero_image_path VARCHAR(255),
                        extra_data TEXT NOT NULL DEFAULT '{}',
                        images_json TEXT NOT NULL DEFAULT '[]',
                        status VARCHAR(32) NOT NULL DEFAULT 'draft',
                        featured INTEGER NOT NULL DEFAULT 0,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        approved_at DATETIME
                    );
                    """
                )
            else:
                # PostgreSQL schema
                create_sql = text(
                    """
                    CREATE TABLE IF NOT EXISTS partners (
                        id SERIAL PRIMARY KEY,
                        category_id INTEGER,
                        slug VARCHAR(120) UNIQUE,
                        name VARCHAR(180) NOT NULL,
                        short_desc VARCHAR(280),
                        long_desc TEXT,
                        website_url VARCHAR(512),
                        phone VARCHAR(64),
                        whatsapp VARCHAR(64),
                        email VARCHAR(255),
                        instagram VARCHAR(255),
                        facebook VARCHAR(255),
                        tiktok VARCHAR(255),
                        address VARCHAR(255),
                        city VARCHAR(120),
                        geo_lat NUMERIC(9,6),
                        geo_lng NUMERIC(9,6),
                        logo_path VARCHAR(255),
                        hero_image_path VARCHAR(255),
                        extra_data JSONB NOT NULL DEFAULT '{}'::jsonb,
                        images_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                        status VARCHAR(32) NOT NULL DEFAULT 'draft',
                        featured BOOLEAN NOT NULL DEFAULT FALSE,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        approved_at TIMESTAMPTZ
                    );
                    """
                )

            with engine.begin() as conn:
                conn.execute(create_sql)
            app.logger.info("[BOOT] partners table created or confirmed")
            return

        # Table exists -> check missing columns
        partner_columns = {c["name"] for c in inspector.get_columns("partners")}
        missing = expected_columns - partner_columns
        if not missing:
            app.logger.info("[BOOT] partners table present and appears up-to-date")
            return

        app.logger.warning("[BOOT] partners table exists but missing columns: %s", ", ".join(sorted(missing)))

        # Prepare ALTER statements for missing columns.
        alter_statements = []
        for col in sorted(missing):
            if col == "category_id":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN category_id INTEGER"))
            elif col == "slug":
                # add the column only; unique constraint/index handled separately
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN slug VARCHAR(120)"))
            elif col == "short_desc":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN short_desc VARCHAR(280)"))
            elif col == "long_desc":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN long_desc TEXT"))
            elif col == "website_url":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN website_url VARCHAR(512)"))
            elif col == "phone":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN phone VARCHAR(64)"))
            elif col == "whatsapp":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN whatsapp VARCHAR(64)"))
            elif col == "email":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN email VARCHAR(255)"))
            elif col == "instagram":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN instagram VARCHAR(255)"))
            elif col == "facebook":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN facebook VARCHAR(255)"))
            elif col == "tiktok":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN tiktok VARCHAR(255)"))
            elif col == "address":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN address VARCHAR(255)"))
            elif col == "city":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN city VARCHAR(120)"))
            elif col == "geo_lat":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN geo_lat NUMERIC"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN geo_lat NUMERIC(9,6)"))
            elif col == "geo_lng":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN geo_lng NUMERIC"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN geo_lng NUMERIC(9,6)"))
            elif col == "logo_path":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN logo_path VARCHAR(255)"))
            elif col == "hero_image_path":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN hero_image_path VARCHAR(255)"))
            elif col == "extra_data":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN extra_data TEXT NOT NULL DEFAULT '{}'"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN extra_data JSONB NOT NULL DEFAULT '{}'::jsonb"))
            elif col == "images_json":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN images_json TEXT NOT NULL DEFAULT '[]'"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN images_json JSONB NOT NULL DEFAULT '[]'::jsonb"))
            elif col == "status":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'draft'"))
            elif col == "featured":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN featured INTEGER NOT NULL DEFAULT 0"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN featured BOOLEAN NOT NULL DEFAULT FALSE"))
            elif col == "sort_order":
                alter_statements.append(text("ALTER TABLE partners ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"))
            elif col == "created_at":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN created_at DATETIME"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN created_at TIMESTAMPTZ"))
            elif col == "updated_at":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN updated_at DATETIME"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN updated_at TIMESTAMPTZ"))
            elif col == "approved_at":
                if dialect == "sqlite":
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN approved_at DATETIME"))
                else:
                    alter_statements.append(text("ALTER TABLE partners ADD COLUMN approved_at TIMESTAMPTZ"))
            else:
                # Generic fallback: add as TEXT
                alter_statements.append(text(f"ALTER TABLE partners ADD COLUMN {col} TEXT"))

        # Execute ALTERs in a single transaction
        try:
            with engine.begin() as conn:
                for stmt in alter_statements:
                    conn.execute(stmt)
            app.logger.info("[BOOT] Added missing partners columns: %s", ", ".join(sorted(missing)))
        except SQLAlchemyError as exc:
            app.logger.error("[BOOT] Failed to add missing partners columns automatically: %s", exc, exc_info=True)

        # If legacy columns exist, try to copy data to new columns non-destructively
        legacy_to_new = [
            ("description", "long_desc"),
            ("website", "website_url"),
            ("image_url", "logo_path"),
            ("lat", "geo_lat"),
            ("lon", "geo_lng"),
            ("contact", "phone"),
        ]

        try:
            with engine.begin() as conn:
                existing_cols = {c["name"] for c in inspector.get_columns("partners")}
                for old, new in legacy_to_new:
                    if old in existing_cols and new in existing_cols:
                        # copy where new is NULL or empty
                        copy_sql = text(
                            f"UPDATE partners SET {new} = {old} WHERE ({new} IS NULL OR {new} = '') AND ({old} IS NOT NULL AND {old} != '')"
                        )
                        conn.execute(copy_sql)
            app.logger.info("[BOOT] Attempted to migrate legacy partners columns to new names where possible")
        except SQLAlchemyError:
            app.logger.exception("[BOOT] Legacy -> new column data copy failed (non-fatal)")

        # Try to create unique index on slug (separate statement; may fail if duplicates exist)
        if "slug" in missing and dialect != "sqlite":
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_partners_slug ON partners (slug)"))
            except Exception:
                app.logger.warning("[BOOT] Creating unique index on partners.slug failed (possible duplicates) — leaving slug column in place")

        # Re-inspect to confirm
        try:
            inspector = inspect(engine)
            partner_columns = {c["name"] for c in inspector.get_columns("partners")}
            missing_after = expected_columns - partner_columns
            if missing_after:
                app.logger.warning("[BOOT] After automatic adjustments, still missing partners columns: %s", ", ".join(sorted(missing_after)))
            else:
                app.logger.info("[BOOT] partners table schema aligned with expectations after automatic adjustments")
        except SQLAlchemyError:
            app.logger.warning("[BOOT] Unable to re-inspect partners table after adjustments")

    except Exception as exc:  # pragma: no cover - defensive fallback
        app.logger.exception("[BOOT] Unexpected error while ensuring partners table: %s", exc)
        
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
    ga_from_env = (os.getenv("GA_MEASUREMENT_ID") or "").strip()
    if ga_from_env:
        app.config["GA_MEASUREMENT_ID"] = ga_from_env
    else:
        app.config.setdefault("GA_MEASUREMENT_ID", DEFAULT_GA_MEASUREMENT_ID)
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
    app.jinja_env.globals["os"] = os

    configure_logging(app.config.get("LOG_DIR"))
    app.logger.info(
        "[BOOT] Logging configured. Writing to %s",
        Path(app.config.get("LOG_DIR", "logs")) / "app.log",
    )
    app.logger.info(
        "[GA4] GA_MEASUREMENT_ID present? %s",
        bool(os.getenv("GA_MEASUREMENT_ID")),
    )

    try:
        ensure_social_preview_image(app.static_folder, logger=app.logger)
    except Exception as exc:  # pragma: no cover - should only happen on IO failures
        app.logger.error("[SEO] Failed to ensure og-image.png: %s", exc, exc_info=True)
        raise

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

    app.config.setdefault("SESSION_COOKIE_SECURE", app_env == "production")
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=30))
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
        default_title = "Monitoraggio Etna in tempo reale – Grafico INGV"
        default_description = (
            "Consulta il grafico del tremore vulcanico dell'Etna in tempo reale con serie storiche INGV, "
            "analisi contestuali e avvisi per appassionati, tecnici e operatori sul territorio."
        )
        computed_og_image = url_for(
            "static",
            filename="images/og-image.png",
            _external=True,
        )
        default_og_image = computed_og_image
        logo_url = computed_og_image
        structured_base = [
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "EtnaMonitor",
                "url": canonical_base,
                "logo": logo_url,
                "sameAs": [
                    "https://www.instagram.com/etna_monitor_official?igsh=Mm9oeXlmOWZsNHNm",
                    "https://www.facebook.com/share/17jhakJdrv/?mibextid=wwXIfr",
                    "https://t.me/etna_turi_bot",
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
            "ads_tracking_enabled": bool(app.config.get("ADS_ROUTES_ENABLED")),
            "ADSENSE_ENABLE": bool(app.config.get("ADSENSE_ENABLE")),
        }

    @app.context_processor
    def inject_analytics_settings():
        ga_measurement_id = (
            current_app.config.get("GA_MEASUREMENT_ID", "").strip()
            or DEFAULT_GA_MEASUREMENT_ID
        )
        ga_debug_enabled = _is_truthy_env(os.getenv("GA_DEBUG"))
        return {
            "analytics": {
                "ga_measurement_id": ga_measurement_id,
                "ga_debug_enabled": ga_debug_enabled,
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
    login_manager.session_protection = "basic"

    @login_manager.unauthorized_handler
    def handle_unauthorized():  # pragma: no cover - glue for diagnostics
        current_app.logger.info(
            "[AUTH] Unauthorized access, redirecting to login. endpoint=%s path=%s user_id=%s flask_user_id=%s",
            request.endpoint,
            request.path,
            session.get("user_id"),
            session.get("_user_id"),
        )
        return redirect(url_for("auth.login", next=request.url))

    from .models.user import User  # imported lazily to avoid circular imports

    @login_manager.user_loader
    def load_user(user_id: str):  # pragma: no cover - thin integration wrapper
        if not user_id:
            return None

        try:
            user_pk = int(user_id)
        except (TypeError, ValueError):
            current_app.logger.warning(
                "[LOGIN] user_loader received invalid user id %r", user_id
            )
            return None

        def _query_with_columns(columns: tuple) -> User | None:
            query = db.session.query(User)
            if columns:
                query = query.options(load_only(*columns))
            return query.filter(User.id == user_pk).first()

        try:
            return _query_with_columns(
                (
                    User.id,
                    User.email,
                    User.google_id,
                    User.name,
                    User.picture_url,
                    User.is_admin,
                    User.is_premium,
                    User._is_active,
                )
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.warning(
                "[LOGIN] user_loader primary query failed for user_id=%s: %s",
                user_pk,
                exc,
            )
            try:
                safe_columns = get_login_safe_user_columns()
                return _query_with_columns(safe_columns)
            except SQLAlchemyError as fallback_exc:
                db.session.rollback()
                current_app.logger.error(
                    "[LOGIN] user_loader fallback failed for user_id=%s: %s",
                    user_pk,
                    fallback_exc,
                    exc_info=fallback_exc,
                )
                return None
        except Exception as exc:  # pragma: no cover - defensive guard
            db.session.rollback()
            current_app.logger.error(
                "[LOGIN] user_loader unexpected failure for user_id=%s: %s",
                user_pk,
                exc,
                exc_info=True,
            )
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

    app.config["BASE_CONTENT_SECURITY_POLICY"] = copy.deepcopy(BASE_CSP)

    talisman.init_app(
        app,
        content_security_policy=copy.deepcopy(BASE_CSP),
        content_security_policy_nonce_in=["script-src", "script-src-elem"],
        force_https=os.getenv("FLASK_ENV") == "production",
        frame_options="DENY",
        referrer_policy="no-referrer-when-downgrade",
    )

    @app.after_request
    def _apply_csp(response):
        return apply_csp_headers(response)

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
    app.register_blueprint(partners_bp)
    app.register_blueprint(category_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(legacy_auth_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(moderation_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(community_bp)
    app.register_blueprint(account_bp)
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

    account_rate_limits(app)
    moderation_rate_limits(app)

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
        else:
            cache_exempt_prefixes = ("/auth", "/dashboard", "/api")
            if any(request.path.startswith(prefix) for prefix in cache_exempt_prefixes):
                response.headers.pop("Cache-Control", None)
                response.headers.setdefault(
                    "Cache-Control", "no-store, private, max-age=0"
                )
            elif (
                request.method == "GET"
                and response.status_code == 200
                and request.blueprint not in {"auth", "dashboard", "api"}
            ):
                response.headers.setdefault("Cache-Control", "public, max-age=300")
        return response

    @app.errorhandler(404)
    def render_not_found(error):  # pragma: no cover - presentation only
        current_app.logger.info("[404] Not found: %s", request.path)
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def render_internal_error(error):  # pragma: no cover - presentation only
        try:
            db.session.rollback()
        except SQLAlchemyError as exc:
            app.logger.error("[500] Failed to rollback session: %s", exc)
        finally:
            db.session.remove()
        app.logger.exception("[500] Internal server error")
        return (
            render_template(
                "errors/500.html",
                page_title="Qualcosa è andato storto",
                page_description="Si è verificato un errore inaspettato. Riprova fra poco.",
            ),
            500,
        )

    @app.teardown_request
    def cleanup_session(exception):  # pragma: no cover - defensive cleanup
        try:
            if exception is not None:
                app.logger.debug(
                    "[SESSION] Rolling back transaction because of exception: %s",
                    exception,
                )
                try:
                    db.session.rollback()
                except SQLAlchemyError as exc:
                    app.logger.error(
                        "[SESSION] Failed to rollback session during teardown: %s", exc
                    )
        finally:
            db.session.remove()

    if _is_truthy_env(os.getenv("FLASK_RUN_FROM_CLI")) or _is_truthy_env(
        os.getenv("FLASK_CLI")
    ):
        from .cli import register_cli_commands

        register_cli_commands(app)

    @app.cli.command("categories-ensure-seed")
    def categories_ensure_seed() -> None:
        """Ensure default partner categories exist."""

        db.session.remove()
        session = db.session

        seeds = [
            {"slug": "guide", "name": "Guide autorizzate", "sort_order": 0},
            {"slug": "hotel", "name": "Hotel", "sort_order": 1},
            {"slug": "ristoranti", "name": "Ristoranti", "sort_order": 2},
        ]

        created = 0
        updated = 0

        for payload in seeds:
            category = session.query(PartnerCategory).filter_by(slug=payload["slug"]).first()
            if category is None:
                category = PartnerCategory(**payload, is_active=True, max_slots=10)
                session.add(category)
                created += 1
            else:
                changed = False
                for key, value in (
                    ("name", payload["name"]),
                    ("sort_order", payload["sort_order"]),
                ):
                    if getattr(category, key) != value:
                        setattr(category, key, value)
                        changed = True
                if not category.is_active:
                    category.is_active = True
                    changed = True
                if category.max_slots != 10:
                    category.max_slots = 10
                    changed = True
                if changed:
                    updated += 1

        session.commit()
        click.echo(
            f"Seed completed: {created} created, {updated} updated."
        )

    return app


app = create_app()
