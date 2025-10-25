from .utils.auth import get_current_user


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
