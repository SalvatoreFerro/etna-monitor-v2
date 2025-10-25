"""Simple CSRF protection helpers used by HTML forms."""

from __future__ import annotations

import secrets
from typing import Optional

from flask import session

_CSRF_SESSION_KEY = "_csrf_token"


def generate_csrf_token() -> str:
    """Return the CSRF token stored in session, creating one if needed."""
    token: Optional[str] = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(token: Optional[str]) -> bool:
    """Validate a submitted CSRF token against the value stored in session."""
    if not token:
        return False
    session_token: Optional[str] = session.get(_CSRF_SESSION_KEY)
    return bool(session_token and secrets.compare_digest(session_token, token))
