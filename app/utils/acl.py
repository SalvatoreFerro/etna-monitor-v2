"""Access control utilities for role-based authorization."""

from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import abort
from flask_login import current_user


def role_required(*roles: str) -> Callable:
    """Restrict a view to the provided roles.

    Admin users automatically bypass role checks. Views should combine this
    decorator with :func:`flask_login.login_required` when authentication is
    mandatory.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if not roles:
                if current_user.is_admin:
                    return func(*args, **kwargs)
                abort(403)
            if not current_user.has_role(*roles):
                abort(403)
            return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = ["role_required"]
