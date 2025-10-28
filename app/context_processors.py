from flask import current_app, request
from sqlalchemy import inspect

from .models import db
from .utils.auth import get_current_user

try:
    from .models.sponsor_banner import SponsorBanner
except Exception:  # pragma: no cover - optional dependency guard
    SponsorBanner = None  # type: ignore


def inject_user():
    user = get_current_user()
    user_name = None
    user_avatar = None

    if user:
        user_name = user.name or user.email
        user_avatar = user.picture_url

    return dict(
        current_user=user,
        current_user_name=user_name,
        current_user_avatar_url=user_avatar,
    )


def inject_sponsor_banners():
    if SponsorBanner is None:
        return {"sponsor_banners": []}

    try:
        banners = (
            SponsorBanner.query.filter_by(active=True)
            .order_by(SponsorBanner.created_at.desc())
            .limit(12)
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        current_app.logger.warning(
            "Unable to load sponsor banners: %s", exc,
        )
        db.session.rollback()
        banners = []

    return {"sponsor_banners": banners}


def inject_user_theme():
    """
    Safely inject user theme preference into template context.
    
    This context processor checks if the theme_preference column exists
    in the users table before attempting to access it. This prevents
    crashes during migrations when the column doesn't exist yet.
    
    Returns:
        dict: Contains 'user_theme' key with the theme name
    """
    default_theme = 'volcano_tech'
    
    preview_theme = request.args.get('preview')
    if preview_theme in ['maintenance', 'volcano_tech', 'apple_minimal']:
        return {'user_theme': preview_theme}
    
    try:
        user = get_current_user()
        
        if not user or not user.is_authenticated:
            return {'user_theme': default_theme}
        
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'theme_preference' not in columns:
            current_app.logger.debug(
                "theme_preference column not found in users table, using default theme"
            )
            return {'user_theme': default_theme}
        
        theme = getattr(user, 'theme_preference', default_theme)
        return {'user_theme': theme or default_theme}
        
    except Exception as exc:
        current_app.logger.warning(
            "Error getting user theme preference: %s, using default", exc
        )
        return {'user_theme': default_theme}
