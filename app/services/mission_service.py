"""Mission service for gamification system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.models import db
from app.models.event import Event
from app.models.mission import UserMission
from app.models.tremor_prediction import TremorPrediction
from app.models.user import User
from app.services.badge_service import recompute_badges_for_user
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class MissionDefinition:
    """Definition of a mission type."""

    code: str
    label: str
    description: str
    points: int
    icon: str
    duration_hours: int  # How long the mission is valid


MISSION_DEFINITIONS = {
    "daily_prediction": MissionDefinition(
        code="daily_prediction",
        label="Previsione giornaliera",
        description="Invia almeno una previsione oggi",
        points=5,
        icon="🎯",
        duration_hours=24,
    ),
    "weekly_login_streak": MissionDefinition(
        code="weekly_login_streak",
        label="Presenza settimanale",
        description="Accedi per almeno 5 giorni su 7",
        points=15,
        icon="📅",
        duration_hours=168,  # 7 days
    ),
}


def assign_mission_to_user(
    user_id: int,
    mission_code: str,
    *,
    now: datetime | None = None,
) -> UserMission | None:
    """Assign a new mission to a user.

    Args:
        user_id: User ID
        mission_code: Mission code from MISSION_DEFINITIONS
        now: Current time (for testing)

    Returns:
        UserMission instance or None if failed
    """
    if mission_code not in MISSION_DEFINITIONS:
        logger.warning(
            "[MISSIONS] Unknown mission code: %s for user %s", mission_code, user_id
        )
        return None

    definition = MISSION_DEFINITIONS[mission_code]
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=definition.duration_hours)

    # Check if user already has an active mission of this type
    existing = (
        UserMission.query.filter(
            UserMission.user_id == user_id,
            UserMission.mission_code == mission_code,
            UserMission.expires_at > now,
        )
        .order_by(UserMission.awarded_at.desc())
        .first()
    )

    if existing:
        logger.debug(
            "[MISSIONS] User %s already has active mission %s",
            user_id,
            mission_code,
        )
        return existing

    mission = UserMission(
        user_id=user_id,
        mission_code=mission_code,
        awarded_at=now,
        expires_at=expires_at,
    )
    db.session.add(mission)

    try:
        db.session.commit()
        logger.info(
            "[MISSIONS] Assigned mission %s to user %s (expires: %s)",
            mission_code,
            user_id,
            expires_at,
        )
        return mission
    except Exception:
        db.session.rollback()
        logger.exception(
            "[MISSIONS] Failed to assign mission %s to user %s",
            mission_code,
            user_id,
        )
        return None


def check_and_complete_missions(user_id: int, *, now: datetime | None = None) -> int:
    """Check if any active missions can be completed.

    Args:
        user_id: User ID
        now: Current time (for testing)

    Returns:
        Number of missions completed
    """
    now = now or datetime.now(timezone.utc)

    # Get all active missions for this user
    active_missions = (
        UserMission.query.filter(
            UserMission.user_id == user_id,
            UserMission.completed_at.is_(None),
            UserMission.expires_at > now,
        )
        .order_by(UserMission.awarded_at.asc())
        .all()
    )

    if not active_missions:
        return 0

    completed_count = 0
    for mission in active_missions:
        if _check_mission_completion(mission, now):
            mission.completed_at = now
            completed_count += 1
            logger.info(
                "[MISSIONS] Mission %s completed by user %s",
                mission.mission_code,
                user_id,
            )

    if completed_count > 0:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception(
                "[MISSIONS] Failed to commit mission completions for user %s",
                user_id,
            )
            return 0

    return completed_count


def _check_mission_completion(mission: UserMission, now: datetime) -> bool:
    """Check if a mission should be marked as completed.

    Args:
        mission: UserMission instance
        now: Current time

    Returns:
        True if mission is completed
    """
    if mission.mission_code == "daily_prediction":
        # Check if user has made a prediction in the mission period
        prediction = (
            TremorPrediction.query.filter(
                TremorPrediction.user_id == mission.user_id,
                TremorPrediction.created_at >= mission.awarded_at,
                TremorPrediction.created_at <= now,
            )
            .first()
        )
        return prediction is not None

    elif mission.mission_code == "weekly_login_streak":
        # Check if user has logged in at least 5 days in the past 7 days
        days_since_awarded = (now - mission.awarded_at).days
        if days_since_awarded < 7:
            # Mission not yet completable
            return False

        distinct_days = (
            db.session.query(func.count(func.distinct(func.date(Event.timestamp))))
            .filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= mission.awarded_at,
                Event.timestamp <= mission.expires_at,
            )
            .scalar()
        )
        return int(distinct_days or 0) >= 5

    return False


def claim_mission_reward(mission_id: int, user_id: int) -> dict[str, any]:
    """Claim rewards for a completed mission.

    Args:
        mission_id: Mission ID
        user_id: User ID

    Returns:
        Dict with status and details
    """
    mission = db.session.get(UserMission, mission_id)

    if mission is None:
        return {"ok": False, "error": "mission_not_found"}

    if mission.user_id != user_id:
        return {"ok": False, "error": "unauthorized"}

    if not mission.is_completed:
        return {"ok": False, "error": "mission_not_completed"}

    definition = MISSION_DEFINITIONS.get(mission.mission_code)
    if definition is None:
        return {"ok": False, "error": "invalid_mission_code"}

    # Award points (if we have a points system in User model)
    user = db.session.get(User, user_id)
    if user is None:
        return {"ok": False, "error": "user_not_found"}

    # For now, we'll just recompute badges
    # In the future, you might want to add a points field to User
    recompute_badges_for_user(user_id)

    try:
        db.session.commit()
        logger.info(
            "[MISSIONS] User %s claimed reward for mission %s (%s points)",
            user_id,
            mission.mission_code,
            definition.points,
        )
        return {
            "ok": True,
            "points_awarded": definition.points,
            "mission_code": mission.mission_code,
        }
    except Exception:
        db.session.rollback()
        logger.exception(
            "[MISSIONS] Failed to claim reward for mission %s user %s",
            mission_id,
            user_id,
        )
        return {"ok": False, "error": "database_error"}


def get_user_missions(
    user_id: int, *, include_expired: bool = False, now: datetime | None = None
) -> list[dict]:
    """Get all missions for a user with their status.

    Args:
        user_id: User ID
        include_expired: Include expired missions
        now: Current time (for testing)

    Returns:
        List of mission dictionaries with status
    """
    now = now or datetime.now(timezone.utc)

    query = UserMission.query.filter(UserMission.user_id == user_id)

    if not include_expired:
        query = query.filter(
            db.or_(
                UserMission.completed_at.isnot(None), UserMission.expires_at > now
            )
        )

    missions = query.order_by(UserMission.awarded_at.desc()).all()

    result = []
    for mission in missions:
        definition = MISSION_DEFINITIONS.get(mission.mission_code)
        if definition is None:
            continue

        progress = _get_mission_progress(mission, now)

        result.append(
            {
                "id": mission.id,
                "code": mission.mission_code,
                "label": definition.label,
                "description": definition.description,
                "icon": definition.icon,
                "points": definition.points,
                "awarded_at": mission.awarded_at.isoformat(),
                "expires_at": mission.expires_at.isoformat(),
                "completed_at": (
                    mission.completed_at.isoformat()
                    if mission.completed_at
                    else None
                ),
                "is_completed": mission.is_completed,
                "is_expired": mission.is_expired,
                "is_active": mission.is_active,
                "progress": progress,
            }
        )

    return result


def _get_mission_progress(mission: UserMission, now: datetime) -> dict:
    """Get progress information for a mission.

    Args:
        mission: UserMission instance
        now: Current time

    Returns:
        Dict with current/total progress
    """
    if mission.mission_code == "daily_prediction":
        prediction_count = (
            TremorPrediction.query.filter(
                TremorPrediction.user_id == mission.user_id,
                TremorPrediction.created_at >= mission.awarded_at,
                TremorPrediction.created_at <= now,
            )
            .count()
        )
        return {"current": min(prediction_count, 1), "total": 1}

    elif mission.mission_code == "weekly_login_streak":
        distinct_days = (
            db.session.query(func.count(func.distinct(func.date(Event.timestamp))))
            .filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= mission.awarded_at,
                Event.timestamp <= min(now, mission.expires_at),
            )
            .scalar()
        )
        return {"current": int(distinct_days or 0), "total": 5}

    return {"current": 0, "total": 1}


def cleanup_expired_missions(*, days_old: int = 30) -> int:
    """Remove old expired missions.

    Args:
        days_old: Remove missions expired more than this many days ago

    Returns:
        Number of missions deleted
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    deleted_count = (
        UserMission.query.filter(
            UserMission.completed_at.is_(None), UserMission.expires_at < cutoff_date
        )
        .delete(synchronize_session=False)
    )

    try:
        db.session.commit()
        logger.info("[MISSIONS] Cleaned up %d expired missions", deleted_count)
        return deleted_count
    except Exception:
        db.session.rollback()
        logger.exception("[MISSIONS] Failed to cleanup expired missions")
        return 0


__all__ = [
    "MissionDefinition",
    "MISSION_DEFINITIONS",
    "assign_mission_to_user",
    "check_and_complete_missions",
    "claim_mission_reward",
    "get_user_missions",
    "cleanup_expired_missions",
]
