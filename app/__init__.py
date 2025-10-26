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

from .routes.main import bp as main_bp
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.auth import bp as auth_bp
from .routes.api import api_bp
from .routes.status import status_bp
from .routes.billing import bp as billing_bp
from backend.routes.admin_stats import admin_stats_bp
from .models import db
from .utils.csrf import generate_csrf_token
from .services.scheduler_service import SchedulerService
from config import Config, get_database_uri_from_env


limiter = None


def _mask_database_uri(uri: str) -> str:
    try:
        parsed = urlparse(uri)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "***")
            parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)
    except Exception:
        return "<unavailable>"

def create_app():
    global limiter
    app = Flask(__name__)
    app.config.from_object(Config)
    app.jinja_env.globals['csrf_token'] = generate_csrf_token

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
    
    try:
        scheduler = SchedulerService()
        scheduler.init_app(app)
    except Exception as e:
        print(f"⚠️  Scheduler initialization failed: {e}")
        pass
    
    if os.getenv("ENABLE_TELEGRAM_BOT", "false").lower() == "true":
        try:
            from .services.telegram_bot_service import TelegramBotService
            telegram_bot = TelegramBotService()
            telegram_bot.init_app(app)
            print("✅ Telegram bot initialized and polling started")
        except Exception as e:
            print(f"⚠️  Telegram bot initialization failed: {e}")
            pass
    else:
        print("ℹ️  Telegram bot disabled (ENABLE_TELEGRAM_BOT=false)")
    
    with app.app_context():
        from sqlalchemy import inspect, text

        try:
            inspector = inspect(db.engine)
            
            if 'users' in inspector.get_table_names():
                existing_columns = [col['name'] for col in inspector.get_columns('users')]
                existing_indexes = [index['name'] for index in inspector.get_indexes('users')]
                existing_uniques = [constraint['name'] for constraint in inspector.get_unique_constraints('users')]

                billing_columns = [
                    ('stripe_customer_id', 'VARCHAR(100)'),
                    ('subscription_status', 'VARCHAR(20) DEFAULT "free"'),
                    ('subscription_id', 'VARCHAR(100)'),
                    ('current_period_end', 'DATETIME'),
                    ('trial_end', 'DATETIME'),
                    ('billing_email', 'VARCHAR(120)'),
                    ('company_name', 'VARCHAR(200)'),
                    ('vat_id', 'VARCHAR(50)'),
                    ('email_alerts', 'BOOLEAN DEFAULT 0 NOT NULL')
                ]

                columns_added = 0
                for column_name, column_def in billing_columns:
                    if column_name not in existing_columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}'))
                                conn.commit()
                            print(f"✅ Auto-migration: Added column {column_name} to users table")
                            columns_added += 1
                        except Exception as e:
                            print(f"⚠️  Auto-migration: Could not add column {column_name}: {e}")

                if columns_added > 0:
                    print(f"🎉 Auto-migration: Added {columns_added} billing columns to users table")

                premium_donation_columns = [
                    ('is_premium', 'BOOLEAN DEFAULT FALSE NOT NULL'),
                    ('premium_lifetime', 'BOOLEAN DEFAULT FALSE NOT NULL'),
                    ('premium_since', 'TIMESTAMP'),
                    ('donation_tx', 'VARCHAR(255)')
                ]

                for column_name, column_def in premium_donation_columns:
                    if column_name not in existing_columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}'))
                                conn.commit()
                            existing_columns.append(column_name)
                            print(f"✅ Auto-migration: Added column {column_name} to users table")
                        except Exception as e:
                            print(f"⚠️  Auto-migration: Could not add column {column_name}: {e}")

                auth_columns = [
                    ('google_id', 'VARCHAR(255)'),
                    ('name', 'VARCHAR(255)'),
                    ('picture_url', 'VARCHAR(512)')
                ]

                auth_columns_added = 0
                for column_name, column_def in auth_columns:
                    if column_name not in existing_columns:
                        try:
                            with db.engine.connect() as conn:
                                conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_def}'))
                                conn.commit()
                            existing_columns.append(column_name)
                            auth_columns_added += 1
                            print(f"✅ Auto-migration: Added column {column_name} to users table")
                        except Exception as e:
                            print(f"⚠️  Auto-migration: Could not add column {column_name}: {e}")

                if auth_columns_added > 0:
                    print(f"🎉 Auto-migration: Added {auth_columns_added} authentication columns to users table")

                try:
                    dialect = db.engine.dialect.name
                    with db.engine.connect() as conn:
                        if dialect == 'postgresql' and 'uq_users_google_id' not in existing_uniques:
                            conn.execute(text('ALTER TABLE users ADD CONSTRAINT uq_users_google_id UNIQUE (google_id)'))
                            conn.commit()
                            print("✅ Auto-migration: Added unique constraint uq_users_google_id")
                        elif dialect == 'mysql' and 'uq_users_google_id' not in existing_indexes:
                            conn.execute(text('ALTER TABLE users ADD UNIQUE INDEX uq_users_google_id (google_id)'))
                            conn.commit()
                            print("✅ Auto-migration: Added unique index uq_users_google_id")
                        elif dialect == 'sqlite':
                            conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_users_google_id ON users (google_id)'))
                            conn.commit()
                            print("✅ Auto-migration: Ensured unique index uq_users_google_id")
                except Exception as e:
                    print(f"⚠️  Auto-migration: Could not ensure unique constraint on google_id: {e}")

                if 'password_hash' in existing_columns:
                    try:
                        dialect = db.engine.dialect.name
                        with db.engine.connect() as conn:
                            if dialect == 'postgresql':
                                conn.execute(text('ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL'))
                                conn.commit()
                                print('✅ Auto-migration: password_hash set to nullable (PostgreSQL)')
                            elif dialect == 'mysql':
                                conn.execute(text('ALTER TABLE users MODIFY password_hash VARCHAR(128) NULL'))
                                conn.commit()
                                print('✅ Auto-migration: password_hash set to nullable (MySQL)')
                            elif dialect == 'sqlite':
                                print('ℹ️  Auto-migration: Skipping password_hash nullability change on SQLite')
                    except Exception as e:
                        print(f"⚠️  Auto-migration: Could not update password_hash nullability: {e}")

                try:
                    with db.engine.connect() as conn:
                        conn.execute(text("UPDATE users SET password_hash='' WHERE password_hash IS NULL"))
                        conn.commit()
                except Exception as e:
                    print(f"⚠️  Auto-migration: Could not sanitize password_hash values: {e}")

            db.create_all()

        except Exception as e:
            print(f"⚠️  Auto-migration failed: {e}")
            pass

        try:
            with db.engine.connect() as conn:
                for e in app.config.get("ADMIN_EMAILS_SET", set()):
                    conn.execute(text("UPDATE users SET is_admin=1 WHERE lower(email)=:e"), {"e": e})
                conn.commit()
            app.logger.info("[BOOT] Admin auto-promotion applied to existing users.")
        except Exception as ex:
            app.logger.warning(f"[BOOT] Admin auto-promotion failed: {ex}")

    csp = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",  # Required for Plotly.js
            "https://cdn.plot.ly",
            "https://fonts.googleapis.com",
            "https://js.stripe.com"
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
        'connect-src': ["'self'", "https://api.stripe.com"],
        'frame-src': ["https://js.stripe.com", "https://hooks.stripe.com"]
    }
    
    Talisman(app, 
             content_security_policy=csp,
             force_https=os.getenv('FLASK_ENV') == 'production')
    
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
    app.register_blueprint(auth_bp, url_prefix="/auth")
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

    with app.app_context():
        db.create_all()

    return app

app = create_app()
