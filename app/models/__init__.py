from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """Initialize database with app"""
    db.init_app(app)
    with app.app_context():
        db.create_all()

from .user import User
from .event import Event

try:
    from .sponsor_banner import (
        SponsorBanner,
        SponsorBannerClick,
        SponsorBannerImpression,
    )
except Exception:  # pragma: no cover - optional dependency guard
    SponsorBanner = None  # type: ignore
    SponsorBannerClick = None  # type: ignore
    SponsorBannerImpression = None  # type: ignore

__all__ = [
    'db',
    'init_db',
    'User',
    'Event',
]

if SponsorBanner is not None:
    __all__.extend(
        [
            'SponsorBanner',
            'SponsorBannerImpression',
            'SponsorBannerClick',
        ]
    )
