from flask import current_app

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
