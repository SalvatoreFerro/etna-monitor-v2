from flask import Flask
from .routes.main import bp as main_bp
from .routes.dashboard import bp as dashboard_bp
from .routes.admin import bp as admin_bp
from .routes.auth import bp as auth_bp
from .routes.api import api_bp
from .models import init_db
from .context_processors import inject_user
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    init_db(app)
    
    app.context_processor(inject_user)
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp)
    
    return app

app = create_app()
