"""Authentication helpers.

This module now primarily serves session-based helpers used by the new OAuth
flow. Legacy password utilities are kept for reference but should be
considered deprecated and unused within the application.
"""

import warnings
from functools import wraps

import bcrypt
from flask import current_app, flash, redirect, request, session, url_for
from flask_login import current_user
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
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
            current_app.logger.info(
                "[AUTH] login_required redirect. endpoint=%s path=%s user_id=%s flask_user_id=%s",
                request.endpoint,
                request.path,
                session.get("user_id"),
                session.get("_user_id"),
            )
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
    """Return the current session user, recovering gracefully from DB failures."""

    try:
        if current_user.is_authenticated:
            return current_user
    except SQLAlchemyError as exc:
        current_app.logger.warning(
            "[AUTH] current_user authentication check failed: %s", exc
        )
        db.session.rollback()
        db.session.remove()
        return None

    user_id = session.get('user_id')
    if user_id is None:
        return None

    user = None

    try:
        user = db.session.get(User, user_id)
    except (ProgrammingError, OperationalError, SQLAlchemyError) as exc:
        current_app.logger.warning(
            "[AUTH] Primary user lookup failed, attempting safe reload: %s", exc
        )
        db.session.rollback()
        safe_columns = get_login_safe_user_columns()
        query = db.session.query(User)
        if safe_columns:
            query = query.options(load_only(*safe_columns))
        try:
            user = query.filter(User.id == user_id).one_or_none()
        except SQLAlchemyError as fallback_exc:
            current_app.logger.error(
                "[AUTH] Fallback user lookup failed, clearing session: %s",
                fallback_exc,
            )
            db.session.rollback()
            db.session.remove()
            session.pop('user_id', None)
            return None

    if user is None:
        session.pop('user_id', None)

    return user
