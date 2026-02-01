"""Helpers for lightweight badge and level calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..models import db, User
from ..models.event import Event
from ..models.gamification import UserBadge


@dataclass(frozen=True)
class BadgeDefinition:
    code: str
    label: str
    icon: str
    description: str


BADGE_DEFINITIONS = {
    "WATCHER_7D": BadgeDefinition(
        code="WATCHER_7D",
        label="Watcher 7 giorni",
        icon="📆",
        description="Accesso giornaliero per 7 giorni consecutivi",
    ),
    "WATCHER_30D": BadgeDefinition(
        code="WATCHER_30D",
        label="Watcher 30 giorni",
        icon="🗓️",
        description="Accesso giornaliero per 30 giorni consecutivi",
    ),
    "PREMIUM_SUPPORTER": BadgeDefinition(
        code="PREMIUM_SUPPORTER",
        label="Premium supporter",
        icon="💎",
        description="Hai attivato un piano Premium",
    ),
    "ALERT_TRIGGERED": BadgeDefinition(
        code="ALERT_TRIGGERED",
        label="Alert attivato",
        icon="🚨",
        description="Hai ricevuto almeno un alert",
    ),
}

LEVEL_DESCRIPTIONS = {
    1: "Level 1 · Inizio monitoraggio (0-1 badge)",
    2: "Level 2 · Monitoratore attivo (2-3 badge)",
    3: "Level 3 · Super osservatore (4+ badge)",
}


def _distinct_login_days(user_id: int, days: int) -> int:
    start_date = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    start_datetime = datetime.combine(start_date, datetime.min.time())
    count = (
        db.session.query(func.count(func.distinct(func.date(Event.timestamp))))
        .filter(
            Event.user_id == user_id,
            Event.event_type == "login",
            Event.timestamp >= start_datetime,
        )
        .scalar()
    )
    return int(count or 0)


def _has_alert(user_id: int) -> bool:
    return (
        db.session.query(Event.id)
        .filter(Event.user_id == user_id, Event.event_type == "alert")
        .limit(1)
        .first()
        is not None
    )


def _normalize_existing_badges(badges: list[UserBadge]) -> set[str]:
    now = datetime.now(timezone.utc)
    normalized_codes: set[str] = set()
    for badge in badges:
        code = badge.badge_code or badge.code
        if code:
            normalized_codes.add(code)
        if badge.badge_code is None and code in BADGE_DEFINITIONS:
            badge.badge_code = code
        if badge.code is None and badge.badge_code:
            badge.code = badge.badge_code
        if badge.label is None and code in BADGE_DEFINITIONS:
            badge.label = BADGE_DEFINITIONS[code].label
        if badge.earned_at is None:
            badge.earned_at = badge.awarded_at or now
    return normalized_codes


def _level_for_badge_count(count: int) -> int:
    if count <= 1:
        return 1
    if count <= 3:
        return 2
    return 3


def recompute_badges_for_user(user_id: int) -> int | None:
    """Compute badges + level for a user and persist new badges."""

    user = db.session.get(User, user_id)
    if user is None:
        return None

    badges = UserBadge.query.filter_by(user_id=user_id).all()
    unlocked_codes = _normalize_existing_badges(badges)

    should_have = set()
    if _distinct_login_days(user_id, 7) >= 7:
        should_have.add("WATCHER_7D")
    if _distinct_login_days(user_id, 30) >= 30:
        should_have.add("WATCHER_30D")
    if user.has_premium_access:
        should_have.add("PREMIUM_SUPPORTER")
    if _has_alert(user_id):
        should_have.add("ALERT_TRIGGERED")

    now = datetime.now(timezone.utc)
    for code in should_have:
        if code in unlocked_codes:
            continue
        definition = BADGE_DEFINITIONS[code]
        db.session.add(
            UserBadge(
                user_id=user_id,
                code=definition.code,
                badge_code=definition.code,
                label=definition.label,
                awarded_at=now,
                earned_at=now,
            )
        )
        unlocked_codes.add(code)

    badge_count = sum(1 for code in unlocked_codes if code in BADGE_DEFINITIONS)
    user.user_level = _level_for_badge_count(badge_count)
    return user.user_level


def get_user_badges_for_display(user_id: int) -> list[dict[str, str | datetime | None]]:
    badges = (
        UserBadge.query.filter_by(user_id=user_id)
        .order_by(UserBadge.earned_at.asc())
        .all()
    )
    items: list[dict[str, str | datetime | None]] = []
    for badge in badges:
        code = badge.badge_code or badge.code
        if code not in BADGE_DEFINITIONS:
            continue
        definition = BADGE_DEFINITIONS[code]
        items.append(
            {
                "code": code,
                "label": definition.label,
                "icon": definition.icon,
                "description": definition.description,
                "earned_at": badge.earned_at or badge.awarded_at,
            }
        )
    return items
