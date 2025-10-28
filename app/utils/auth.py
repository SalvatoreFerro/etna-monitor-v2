"""Authentication helpers.

This module now primarily serves session-based helpers used by the new OAuth
flow. Legacy password utilities are kept for reference but should be
considered deprecated and unused within the application.
"""

import warnings
from functools import wraps

import bcrypt
from flask import flash, redirect, request, session, url_for
from flask_login import current_user
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import load_only

from ..models import db
from ..models.user import User
from .user_columns import get_login_safe_user_columns

_PASSWORD_DEPRECATION_MSG = (
    "Password hashing utilities are deprecated. Use Google OAuth instead."
)


def hash_password(plain: str) -> str:
    """Deprecated password hashing helper retained for archival purposes."""

    warnings.warn(_PASSWORD_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()


def check_password(plain: str, hashed: str) -> bool:
    """Deprecated password verification helper retained for archival purposes."""

    warnings.warn(_PASSWORD_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            session.pop('user_id', None)
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            session.pop('user_id', None)
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))

        if not user or not user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Return the current session user, caching only successful lookups."""

    if current_user.is_authenticated:
        return current_user

    user_id = session.get('user_id')
    if user_id is None:
        return None

    try:
        user = db.session.get(User, user_id)
    except (ProgrammingError, OperationalError):
        db.session.rollback()
        safe_columns = get_login_safe_user_columns()
        query = db.session.query(User)
        if safe_columns:
            query = query.options(load_only(*safe_columns))
        user = query.filter(User.id == user_id).one_or_none()

    if user is None:
        session.pop('user_id', None)

    return user
