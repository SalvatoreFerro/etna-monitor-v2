from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """Initialize database with app"""
    db.init_app(app)

from .user import User
from .event import Event
from .partner import Partner
from .blog import BlogPost
from .forum import ForumThread, ForumReply
from .feedback import UserFeedback, FeedbackVote
from .gamification import UserGamificationProfile, UserBadge

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
    'Partner',
    'BlogPost',
    'ForumThread',
    'ForumReply',
    'UserFeedback',
    'FeedbackVote',
    'UserGamificationProfile',
    'UserBadge',
]

if SponsorBanner is not None:
    __all__.extend(
        [
            'SponsorBanner',
            'SponsorBannerImpression',
            'SponsorBannerClick',
        ]
    )
