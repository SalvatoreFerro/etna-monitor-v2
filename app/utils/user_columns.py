"""Helpers for determining safe user column selections during login flows."""

from __future__ import annotations

from flask import current_app
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from ..models import db
from ..models.user import User

_LOGIN_COLUMN_CACHE: tuple | None = None


def get_login_safe_user_columns() -> tuple:
    """Return the minimal set of ``User`` columns safe for login queries."""

    global _LOGIN_COLUMN_CACHE
    if _LOGIN_COLUMN_CACHE is not None:
        return _LOGIN_COLUMN_CACHE

    safe_defaults = (
        User.id,
        User.email,
        User.google_id,
        User.name,
        User.picture_url,
        User.password_hash,
        User.is_premium,
        User.premium,
        User.premium_lifetime,
        User.telegram_opt_in,
    )

    try:
        inspector = inspect(db.engine)
        available = {
            column.get("name")
            for column in inspector.get_columns(User.__tablename__)
        }
    except SQLAlchemyError as exc:  # pragma: no cover - best-effort path
        current_app.logger.warning(
            "[LOGIN] Could not inspect users table columns: %s", exc
        )
        _LOGIN_COLUMN_CACHE = safe_defaults
        return _LOGIN_COLUMN_CACHE

    preferred = safe_defaults + (
        User.plan_type,
        User.is_admin,
        User.subscription_status,
        User.subscription_id,
        User.current_period_end,
        User.trial_end,
        User.billing_email,
        User.company_name,
        User.vat_id,
        User.free_alert_event_id,
        User.free_alert_consumed,
        User.last_alert_sent_at,
        User.alert_count_30d,
        User.consent_ts,
        User.privacy_version,
        User.theme_preference,
    )

    selected = []
    for attr in preferred:
        if attr.key in available:
            selected.append(attr)

    if not selected:
        selected = list(safe_defaults)

    deduped: list = []
    seen = set()
    for attr in selected:
        if attr.key in seen:
            continue
        seen.add(attr.key)
        deduped.append(attr)

    _LOGIN_COLUMN_CACHE = tuple(deduped)
    return _LOGIN_COLUMN_CACHE


def reset_login_safe_user_columns_cache() -> None:
    """Clear the cached login column selection (useful for tests)."""

    global _LOGIN_COLUMN_CACHE
    _LOGIN_COLUMN_CACHE = None
