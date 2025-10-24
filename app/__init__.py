from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_compress import Compress
import os
import redis

from .routes.main import bp as main_bp
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.auth import bp as auth_bp
from .routes.api import api_bp
from .routes.status import status_bp
from .routes.billing import bp as billing_bp
from .models import init_db
from .context_processors import inject_user
from .services.scheduler_service import SchedulerService
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    init_db(app)
    
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
        try:
            from sqlalchemy import inspect, text
            from .models import db
            inspector = inspect(db.engine)
            
            if 'users' in inspector.get_table_names():
                existing_columns = [col['name'] for col in inspector.get_columns('users')]
                
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
            
            db.create_all()
            
        except Exception as e:
            print(f"⚠️  Auto-migration failed: {e}")
            pass
    
    csp = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",
            "'unsafe-eval'",  # Required for Chart.js
            "https://cdn.jsdelivr.net",
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
            default_limits=["200 per day", "50 per hour"]
        )
    else:
        limiter = Limiter(
            key_func=get_remote_address,
            app=app,
            default_limits=["200 per day", "50 per hour"]
        )
    
    app.context_processor(inject_user)
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(api_bp)
    app.register_blueprint(status_bp)
    
    return app

app = create_app()
