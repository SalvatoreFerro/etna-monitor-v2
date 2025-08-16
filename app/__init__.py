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
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    init_db(app)
    
    csp = {
        'default-src': "'self'",
        'script-src': [
            "'self'",
            "'unsafe-inline'",
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
        'connect-src': ["'self'", "https://api.stripe.com"]
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
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(billing_bp, url_prefix="/billing")
    app.register_blueprint(api_bp)
    app.register_blueprint(status_bp)
    
    return app

app = create_app()
