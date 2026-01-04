from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_db(app):
    """Initialize database with app"""
    db.init_app(app)

from .user import User
from .event import Event
from .admin_action import AdminActionLog
from .partner import (
    Partner,
    PartnerCategory,
    PartnerLead,
    PartnerSubscription,
    PartnerWaitlist,
)
from .blog import BlogPost
from .forum import ForumThread, ForumReply
from .community_post import CommunityPost, ModerationAction
from .feedback import UserFeedback, FeedbackVote
from .gamification import UserGamificationProfile, UserBadge
from .media_asset import MediaAsset
from .premium_request import PremiumRequest
from .hotspots_cache import HotspotsCache
from .hotspots_record import HotspotsRecord
from .cron_run import CronRun

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
    'AdminActionLog',
    'Partner',
    'PartnerCategory',
    'PartnerSubscription',
    'PartnerWaitlist',
    'PartnerLead',
    'BlogPost',
    'ForumThread',
    'ForumReply',
    'UserFeedback',
    'FeedbackVote',
    'UserGamificationProfile',
    'UserBadge',
    'CommunityPost',
    'ModerationAction',
    'MediaAsset',
    'PremiumRequest',
    'HotspotsCache',
    'HotspotsRecord',
    'CronRun',
]

if SponsorBanner is not None:
    __all__.extend(
        [
            'SponsorBanner',
            'SponsorBannerImpression',
            'SponsorBannerClick',
        ]
    )
