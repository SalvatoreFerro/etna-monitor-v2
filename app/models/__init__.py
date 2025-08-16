from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """Initialize database with app"""
    db.init_app(app)
    with app.app_context():
        db.create_all()

from .user import User
from .event import Event

__all__ = ['db', 'init_db', 'User', 'Event']
