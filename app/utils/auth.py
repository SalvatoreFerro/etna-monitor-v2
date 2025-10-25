"""Authentication helpers.

This module now primarily serves session-based helpers used by the new OAuth
flow. Legacy password utilities are kept for reference but should be
considered deprecated and unused within the application.
"""

import warnings
from functools import wraps

import bcrypt
from flask import flash, redirect, request, session, url_for

from ..models.user import User

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
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('auth.login'))
        
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None
