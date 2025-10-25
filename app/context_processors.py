from .utils.auth import get_current_user
from .models.sponsor_banner import SponsorBanner


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
    banners = (
        SponsorBanner.query.filter_by(active=True)
        .order_by(SponsorBanner.created_at.desc())
        .limit(12)
        .all()
    )
    return {"sponsor_banners": banners}
