"""REST endpoints that expose administrative activity insights."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request
from sqlalchemy import func
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

    now = datetime.utcnow()
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
        "generated_at": _serialize_timestamp(datetime.utcnow()),
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
            "generated_at": _serialize_timestamp(datetime.utcnow()),
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

    now = datetime.utcnow()
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
            "generated_at": _serialize_timestamp(datetime.utcnow()),
            "metrics": {
                "total_users": int(total_users),
                "premium_users": int(premium_users),
                "free_users": int(free_users),
                "alerts_last_24h": int(alerts_last_24h),
            },
        }
    )
