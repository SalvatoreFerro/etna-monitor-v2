"""REST endpoints that expose administrative activity insights."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from app.models import AdminActionLog, Event, User, db
from app.utils.auth import get_current_user

admin_stats_bp = Blueprint("admin_stats", __name__)


def _serialize_timestamp(value: Optional[datetime]) -> Optional[str]:
    """Return an ISO-8601 string with UTC designator for a datetime value."""
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(microsecond=0).isoformat() + "Z"

    utc_value = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc_value.isoformat().replace("+00:00", "Z")


def _coerce_limit(raw: Optional[str], *, default: int, maximum: int) -> int:
    try:
        limit = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default

    return max(1, min(limit, maximum))


def _coerce_period_days(raw: Optional[str], *, fallback: int = 30) -> int:
    try:
        value = int(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback
    if value not in {7, 30, 90}:
        return fallback
    return value


def _coerce_filter(raw: Optional[str], allowed: set[str], *, default: str) -> str:
    if not raw:
        return default
    normalized = raw.strip().lower()
    return normalized if normalized in allowed else default


def _serialize_event(event: Event) -> Dict[str, Any]:
    user_email = None
    if event.user is not None:
        user_email = event.user.email

    payload: Dict[str, Any] = {
        "id": event.id,
        "user_id": event.user_id,
        "user_email": user_email,
        "event_type": event.event_type,
        "timestamp": _serialize_timestamp(event.timestamp),
        "message": event.message,
    }

    if event.value is not None:
        try:
            payload["value"] = float(event.value)
        except (TypeError, ValueError):
            payload["value"] = event.value

    if event.threshold is not None:
        try:
            payload["threshold"] = float(event.threshold)
        except (TypeError, ValueError):
            payload["threshold"] = event.threshold

    return payload


def _serialize_admin_action(entry: AdminActionLog) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "action": entry.action,
        "status": entry.status,
        "message": entry.message,
        "admin_id": entry.admin_id,
        "admin_email": entry.admin_email,
        "target_user_id": entry.target_user_id,
        "target_email": entry.target_email,
        "ip_address": entry.ip_address,
        "context": entry.context,
        "created_at": _serialize_timestamp(entry.created_at),
    }


def _require_admin_user() -> Optional[User]:
    user = get_current_user()
    if not user or not user.is_admin:
        return None
    return user


@admin_stats_bp.get("/audit")
def get_audit_feed():
    """Return recent audit trail events for the administration dashboard."""
    if _require_admin_user() is None:
        return (
            jsonify({"ok": False, "error": "Admin access required"}),
            403,
        )

    events_limit = _coerce_limit(request.args.get("limit"), default=15, maximum=100)
    alerts_limit = _coerce_limit(request.args.get("alerts_limit"), default=10, maximum=50)

    events = (
        Event.query.options(selectinload(Event.user))
        .order_by(Event.timestamp.desc())
        .limit(events_limit)
        .all()
    )

    alert_events = (
        Event.query.options(selectinload(Event.user))
        .filter(Event.event_type == "alert")
        .order_by(Event.timestamp.desc())
        .limit(alerts_limit)
        .all()
    )

    now = datetime.now(timezone.utc)
    alerts_last_24h = (
        Event.query.filter(
            Event.event_type == "alert",
            Event.timestamp >= now - timedelta(hours=24),
        )
        .with_entities(func.count(Event.id))
        .scalar()
        or 0
    )

    total_events = db.session.query(func.count(Event.id)).scalar() or 0

    payload = {
        "ok": True,
        "generated_at": _serialize_timestamp(datetime.now(timezone.utc)),
        "events": [_serialize_event(event) for event in events],
        "alerts": [_serialize_event(event) for event in alert_events],
        "metrics": {
            "alerts_last_24h": int(alerts_last_24h),
            "total_events": int(total_events),
            "events_limit": events_limit,
            "alerts_limit": alerts_limit,
        },
    }

    return jsonify(payload)


@admin_stats_bp.get("/admin-actions")
def get_admin_actions():
    if _require_admin_user() is None:
        return (
            jsonify({"ok": False, "error": "Admin access required"}),
            403,
        )

    entries_limit = _coerce_limit(request.args.get("limit"), default=25, maximum=100)
    entries = (
        AdminActionLog.query.order_by(AdminActionLog.created_at.desc())
        .limit(entries_limit)
        .all()
    )

    total_entries = db.session.query(func.count(AdminActionLog.id)).scalar() or 0

    return jsonify(
        {
            "ok": True,
            "generated_at": _serialize_timestamp(datetime.now(timezone.utc)),
            "limit": entries_limit,
            "total": int(total_entries),
            "entries": [_serialize_admin_action(entry) for entry in entries],
        }
    )


@admin_stats_bp.get("/analytics")
def get_admin_analytics():
    if _require_admin_user() is None:
        return (
            jsonify({"ok": False, "error": "Admin access required"}),
            403,
        )

    total_users = db.session.query(func.count(User.id)).scalar() or 0
    premium_users = (
        db.session.query(func.count(User.id))
        .select_from(User)
        .filter(User.premium_status_clause())
        .scalar()
        or 0
    )
    free_users = max(0, int(total_users) - int(premium_users))

    now = datetime.now(timezone.utc)
    alerts_last_24h = (
        Event.query.filter(
            Event.event_type == "alert",
            Event.timestamp >= now - timedelta(hours=24),
        )
        .with_entities(func.count(Event.id))
        .scalar()
        or 0
    )

    return jsonify(
        {
            "ok": True,
            "generated_at": _serialize_timestamp(datetime.now(timezone.utc)),
            "metrics": {
                "total_users": int(total_users),
                "premium_users": int(premium_users),
                "free_users": int(free_users),
                "alerts_last_24h": int(alerts_last_24h),
            },
        }
    )


@admin_stats_bp.get("/user-analytics")
def get_user_analytics():
    if _require_admin_user() is None:
        return (
            jsonify({"ok": False, "error": "Admin access required"}),
            403,
        )

    period_days = _coerce_period_days(request.args.get("period"), fallback=30)
    telegram_filter = _coerce_filter(
        request.args.get("telegram"),
        {"all", "yes", "no"},
        default="all",
    )
    premium_filter = _coerce_filter(
        request.args.get("premium"),
        {"all", "yes", "no"},
        default="all",
    )
    limit = _coerce_limit(request.args.get("limit"), default=100, maximum=300)

    try:
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=period_days)

        telegram_clause = or_(
            User.telegram_chat_id.isnot(None),
            User.chat_id.isnot(None),
        )
        premium_clause = User.premium_status_clause()

        total_users = db.session.query(func.count(User.id)).scalar() or 0
        premium_users = (
            db.session.query(func.count(User.id))
            .select_from(User)
            .filter(premium_clause)
            .scalar()
            or 0
        )
        free_users = max(0, int(total_users) - int(premium_users))

        new_users_24h = (
            db.session.query(func.count(User.id))
            .filter(User.created_at >= now - timedelta(hours=24))
            .scalar()
            or 0
        )
        new_users_7d = (
            db.session.query(func.count(User.id))
            .filter(User.created_at >= now - timedelta(days=7))
            .scalar()
            or 0
        )
        new_users_30d = (
            db.session.query(func.count(User.id))
            .filter(User.created_at >= now - timedelta(days=30))
            .scalar()
            or 0
        )

        telegram_connected = (
            db.session.query(func.count(User.id))
            .filter(telegram_clause)
            .scalar()
            or 0
        )
        telegram_connected_pct = (
            (telegram_connected / total_users) * 100 if total_users else 0.0
        )

        recent_users_query = User.query.filter(User.created_at >= now - timedelta(days=7))
        recent_total = (
            recent_users_query.with_entities(func.count(User.id)).scalar() or 0
        )
        recent_telegram = (
            recent_users_query.filter(telegram_clause)
            .with_entities(func.count(User.id))
            .scalar()
            or 0
        )
        recent_telegram_pct = (
            (recent_telegram / recent_total) * 100 if recent_total else 0.0
        )

        trend_start = now - timedelta(days=29)
        trend_rows = (
            db.session.query(func.date(User.created_at), func.count(User.id))
            .filter(User.created_at >= trend_start)
            .group_by(func.date(User.created_at))
            .order_by(func.date(User.created_at))
            .all()
        )
        trend_map = {
            (row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])): int(
                row[1]
            )
            for row in trend_rows
        }
        trend = []
        for offset in range(30):
            day = (trend_start.date() + timedelta(days=offset)).isoformat()
            trend.append({"date": day, "count": int(trend_map.get(day, 0))})

        filtered_query = User.query.filter(User.created_at >= period_start)
        if telegram_filter == "yes":
            filtered_query = filtered_query.filter(telegram_clause)
        elif telegram_filter == "no":
            filtered_query = filtered_query.filter(~telegram_clause)

        if premium_filter == "yes":
            filtered_query = filtered_query.filter(premium_clause)
        elif premium_filter == "no":
            filtered_query = filtered_query.filter(~premium_clause)

        filtered_total = filtered_query.with_entities(func.count(User.id)).scalar() or 0

        last_login_subquery = (
            db.session.query(
                Event.user_id.label("user_id"),
                func.max(Event.timestamp).label("last_login"),
            )
            .filter(Event.event_type == "login")
            .group_by(Event.user_id)
            .subquery()
        )

        filtered_users = (
            db.session.query(User, last_login_subquery.c.last_login)
            .outerjoin(
                last_login_subquery, User.id == last_login_subquery.c.user_id
            )
            .filter(User.created_at >= period_start)
            .order_by(User.created_at.desc())
        )
        if telegram_filter == "yes":
            filtered_users = filtered_users.filter(telegram_clause)
        elif telegram_filter == "no":
            filtered_users = filtered_users.filter(~telegram_clause)
        if premium_filter == "yes":
            filtered_users = filtered_users.filter(premium_clause)
        elif premium_filter == "no":
            filtered_users = filtered_users.filter(~premium_clause)

        user_items = []
        for user, last_login in filtered_users.limit(limit).all():
            user_items.append(
                {
                    "id": user.id,
                    "email": user.email,
                    "created_at": _serialize_timestamp(user.created_at),
                    "has_premium": bool(user.has_premium_access),
                    "plan": user.current_plan,
                    "telegram_connected": bool(
                        user.telegram_chat_id or user.chat_id
                    ),
                    "threshold": user.threshold,
                    "last_access": _serialize_timestamp(last_login),
                }
            )

        payload = {
            "ok": True,
            "generated_at": _serialize_timestamp(datetime.now(timezone.utc)),
            "filters": {
                "period_days": period_days,
                "telegram": telegram_filter,
                "premium": premium_filter,
                "limit": limit,
            },
            "metrics": {
                "total_users": int(total_users),
                "premium_users": int(premium_users),
                "free_users": int(free_users),
                "new_users_24h": int(new_users_24h),
                "new_users_7d": int(new_users_7d),
                "new_users_30d": int(new_users_30d),
                "telegram_connected": int(telegram_connected),
                "telegram_connected_pct": round(telegram_connected_pct, 2),
                "telegram_recent_pct": round(recent_telegram_pct, 2),
            },
            "trend": trend,
            "filtered": {"total": int(filtered_total)},
            "users": user_items,
        }

        return jsonify(payload)
    except Exception:  # pragma: no cover - defensive logging
        current_app.logger.exception("Failed to load admin user analytics")
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Analytics temporaneamente non disponibili.",
                }
            ),
            500,
        )
