"""Mission service for gamification system."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func

from app.models import db
from app.models.event import Event
from app.models.mission import UserMission
from app.models.tremor_prediction import TremorPrediction
from app.models.gamification import UserGamificationProfile
from app.models.user import User
from app.services.badge_service import recompute_badges_for_user
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_datetime(dt: datetime) -> datetime:
    """Normalize datetime to timezone-aware UTC.
    
    Args:
        dt: Datetime to normalize
        
    Returns:
        Timezone-aware datetime in UTC
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class MissionDefinition:
    """Definition of a mission type."""

    code: str
    label: str
    description: str
    points: int
    icon: str
    duration_hours: int  # How long the mission is valid
    auto_claim: bool = False


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


PREDICTION_WAIT_POINTS = _env_int("PREDICTION_WAIT_POINTS", 20)


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
    "daily_login": MissionDefinition(
        code="daily_login",
        label="Accesso giornaliero",
        description="Effettua almeno un accesso oggi",
        points=3,
        icon="✅",
        duration_hours=24,
    ),
    "daily_leaderboard": MissionDefinition(
        code="daily_leaderboard",
        label="Apri la classifica",
        description="Visita la classifica del Prediction Game",
        points=4,
        icon="🏁",
        duration_hours=24,
    ),
    "daily_graph_view": MissionDefinition(
        code="daily_graph_view",
        label="Visualizza il grafico",
        description="Apri il grafico del tremore di oggi",
        points=4,
        icon="📈",
        duration_hours=24,
    ),
    "prediction_wait": MissionDefinition(
        code="prediction_wait",
        label="Attendi l'esito della previsione",
        description="La previsione si risolverà automaticamente",
        points=PREDICTION_WAIT_POINTS,
        icon="⏳",
        duration_hours=24,
        auto_claim=True,
    ),
}

AUTO_CLAIM_MISSIONS = {"prediction_wait"}


def _start_of_day(now: datetime) -> datetime:
    now = _normalize_datetime(now)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(now: datetime) -> datetime:
    return _start_of_day(now) + timedelta(days=1)


def _format_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m"
    return "meno di 1m"


def assign_mission_to_user(
    user_id: int,
    mission_code: str,
    *,
    now: datetime | None = None,
    awarded_at: datetime | None = None,
    expires_at: datetime | None = None,
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
    awarded_at = _normalize_datetime(awarded_at or now)
    expires_at = _normalize_datetime(
        expires_at or (awarded_at + timedelta(hours=definition.duration_hours))
    )

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
        awarded_at=awarded_at,
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


def ensure_daily_missions(user_id: int, *, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    day_start = _start_of_day(now)
    day_end = _end_of_day(now)
    for mission_code in ("daily_login", "daily_leaderboard", "daily_graph_view"):
        assign_mission_to_user(
            user_id,
            mission_code,
            now=now,
            awarded_at=day_start,
            expires_at=day_end,
        )


def ensure_prediction_wait_mission(
    user_id: int,
    prediction: TremorPrediction | None,
    *,
    now: datetime | None = None,
) -> None:
    if prediction is None or prediction.resolved:
        return
    now = now or datetime.now(timezone.utc)
    expires_at = _normalize_datetime(prediction.resolves_at)
    awarded_at = _normalize_datetime(prediction.created_at)
    existing = (
        UserMission.query.filter(
            UserMission.user_id == user_id,
            UserMission.mission_code == "prediction_wait",
            UserMission.expires_at >= now,
        )
        .order_by(UserMission.awarded_at.desc())
        .first()
    )
    if existing:
        return
    assign_mission_to_user(
        user_id,
        "prediction_wait",
        now=now,
        awarded_at=awarded_at,
        expires_at=expires_at,
    )


def record_daily_event(
    user_id: int,
    event_type: str,
    *,
    now: datetime | None = None,
    message: str | None = None,
) -> bool:
    now = now or datetime.now(timezone.utc)
    day_start = _start_of_day(now)
    existing = (
        Event.query.filter(
            Event.user_id == user_id,
            Event.event_type == event_type,
            Event.timestamp >= day_start,
        )
        .order_by(Event.timestamp.desc())
        .first()
    )
    if existing:
        return False
    db.session.add(Event(user_id=user_id, event_type=event_type, message=message))
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        logger.exception("[MISSIONS] Failed to record daily event %s", event_type)
        return False


def sync_user_missions(
    user_id: int,
    *,
    now: datetime | None = None,
    active_prediction: TremorPrediction | None = None,
) -> None:
    now = now or datetime.now(timezone.utc)
    ensure_daily_missions(user_id, now=now)
    ensure_prediction_wait_mission(user_id, active_prediction, now=now)
    check_and_complete_missions(user_id, now=now)


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
            if mission.mission_code in AUTO_CLAIM_MISSIONS:
                definition = MISSION_DEFINITIONS.get(mission.mission_code)
                if definition:
                    _award_mission_points(
                        mission,
                        definition.points,
                        now=now,
                        claim_source="auto",
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
                TremorPrediction.created_at >= _normalize_datetime(mission.awarded_at),
                TremorPrediction.created_at <= now,
            )
            .first()
        )
        return prediction is not None

    elif mission.mission_code == "daily_login":
        login_event = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= _normalize_datetime(mission.awarded_at),
                Event.timestamp <= now,
            )
            .first()
        )
        return login_event is not None

    elif mission.mission_code == "daily_leaderboard":
        leaderboard_event = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "leaderboard_view",
                Event.timestamp >= _normalize_datetime(mission.awarded_at),
                Event.timestamp <= now,
            )
            .first()
        )
        return leaderboard_event is not None

    elif mission.mission_code == "daily_graph_view":
        graph_event = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "graph_view",
                Event.timestamp >= _normalize_datetime(mission.awarded_at),
                Event.timestamp <= now,
            )
            .first()
        )
        return graph_event is not None

    elif mission.mission_code == "weekly_login_streak":
        # Check if user has logged in at least 5 distinct days within the mission period
        # Normalize timestamps for consistent comparison
        awarded_at = _normalize_datetime(mission.awarded_at)
        expires_at = _normalize_datetime(mission.expires_at)
        now_normalized = _normalize_datetime(now)
        
        # Count distinct days where user has logged in during the mission period
        distinct_days = (
            db.session.query(func.count(func.distinct(func.date(Event.timestamp))))
            .filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= awarded_at,
                Event.timestamp <= min(now_normalized, expires_at),
            )
            .scalar()
        )
        return int(distinct_days or 0) >= 5

    elif mission.mission_code == "prediction_wait":
        resolves_at = _normalize_datetime(mission.expires_at)
        prediction = (
            TremorPrediction.query.filter(
                TremorPrediction.user_id == mission.user_id,
                TremorPrediction.resolved.is_(True),
                TremorPrediction.resolves_at == resolves_at,
            )
            .first()
        )
        return prediction is not None

    return False


def _award_mission_points(
    mission: UserMission,
    points: int,
    *,
    now: datetime | None = None,
    claim_source: str = "manual",
) -> None:
    now = now or datetime.now(timezone.utc)
    message = f"mission:{mission.id}"
    already_claimed = (
        Event.query.filter(
            Event.user_id == mission.user_id,
            Event.event_type == "mission_claimed",
            Event.message == message,
        )
        .limit(1)
        .first()
        is not None
    )
    if already_claimed:
        return

    profile = UserGamificationProfile.query.filter_by(user_id=mission.user_id).first()
    if profile is None:
        profile = UserGamificationProfile(user_id=mission.user_id)
        db.session.add(profile)
    profile.add_points(points)
    db.session.add(
        Event(
            user_id=mission.user_id,
            event_type="mission_claimed",
            message=message,
        )
    )
    recompute_badges_for_user(mission.user_id)
    logger.info(
        "[MISSIONS] Mission %s points awarded to user %s (source=%s)",
        mission.mission_code,
        mission.user_id,
        claim_source,
    )


def claim_mission_reward(mission_id: int, user_id: int) -> dict[str, Any]:
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

    message = f"mission:{mission.id}"
    already_claimed = (
        Event.query.filter(
            Event.user_id == user_id,
            Event.event_type == "mission_claimed",
            Event.message == message,
        )
        .limit(1)
        .first()
        is not None
    )
    if already_claimed:
        return {"ok": False, "error": "mission_already_claimed"}

    # Award points (if we have a points system in User model)
    user = db.session.get(User, user_id)
    if user is None:
        return {"ok": False, "error": "user_not_found"}

    _award_mission_points(mission, definition.points, claim_source="manual")

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
        # Normalize now for comparison
        now_normalized = _normalize_datetime(now)
        
        query = query.filter(
            db.or_(
                UserMission.completed_at.isnot(None),
                UserMission.expires_at > now_normalized
            )
        )

    missions = query.order_by(UserMission.awarded_at.desc()).all()
    claim_messages = [f"mission:{mission.id}" for mission in missions]
    claimed_messages = set()
    if claim_messages:
        claimed_messages = {
            event.message
            for event in Event.query.filter(
                Event.user_id == user_id,
                Event.event_type == "mission_claimed",
                Event.message.in_(claim_messages),
            ).all()
        }

    result = []
    for mission in missions:
        definition = MISSION_DEFINITIONS.get(mission.mission_code)
        if definition is None:
            continue
        if mission.mission_code == "prediction_wait" and mission.is_completed:
            continue

        progress = _get_mission_progress(mission, now)
        hint = _get_mission_hint(mission.mission_code, mission)

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
                "progress_label": progress.get("label"),
                "hint": hint,
                "auto_claim": definition.auto_claim,
                "is_claimed": f"mission:{mission.id}" in claimed_messages,
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
    # Normalize now for comparisons
    now = _normalize_datetime(now)
    awarded_at = _normalize_datetime(mission.awarded_at)
        
    if mission.mission_code == "daily_prediction":
        prediction_count = (
            TremorPrediction.query.filter(
                TremorPrediction.user_id == mission.user_id,
                TremorPrediction.created_at >= awarded_at,
                TremorPrediction.created_at <= now,
            )
            .count()
        )
        return {"current": min(prediction_count, 1), "total": 1}

    elif mission.mission_code == "daily_login":
        login_count = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= awarded_at,
                Event.timestamp <= now,
            )
            .count()
        )
        return {"current": min(login_count, 1), "total": 1}

    elif mission.mission_code == "daily_leaderboard":
        leaderboard_count = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "leaderboard_view",
                Event.timestamp >= awarded_at,
                Event.timestamp <= now,
            )
            .count()
        )
        return {"current": min(leaderboard_count, 1), "total": 1}

    elif mission.mission_code == "daily_graph_view":
        graph_count = (
            Event.query.filter(
                Event.user_id == mission.user_id,
                Event.event_type == "graph_view",
                Event.timestamp >= awarded_at,
                Event.timestamp <= now,
            )
            .count()
        )
        return {"current": min(graph_count, 1), "total": 1}

    elif mission.mission_code == "weekly_login_streak":
        expires_at = _normalize_datetime(mission.expires_at)
        
        distinct_days = (
            db.session.query(func.count(func.distinct(func.date(Event.timestamp))))
            .filter(
                Event.user_id == mission.user_id,
                Event.event_type == "login",
                Event.timestamp >= awarded_at,
                Event.timestamp <= min(now, expires_at),
            )
            .scalar()
        )
        return {"current": int(distinct_days or 0), "total": 5}

    elif mission.mission_code == "prediction_wait":
        expires_at = _normalize_datetime(mission.expires_at)
        total_seconds = max(int((expires_at - awarded_at).total_seconds()), 1)
        elapsed_seconds = max(int((now - awarded_at).total_seconds()), 0)
        elapsed_seconds = min(elapsed_seconds, total_seconds)
        remaining_seconds = max(total_seconds - elapsed_seconds, 0)
        return {
            "current": elapsed_seconds,
            "total": total_seconds,
            "label": f"Manca {_format_remaining(remaining_seconds)}",
        }

    return {"current": 0, "total": 1}


def _get_mission_hint(mission_code: str, mission: UserMission) -> str | None:
    if mission_code == "prediction_wait":
        return "Attiva perché hai una previsione in corso."
    if mission_code == "daily_login":
        return "Missione giornaliera: basta un accesso oggi."
    if mission_code == "daily_leaderboard":
        return "Missione giornaliera: apri la classifica oggi."
    if mission_code == "daily_graph_view":
        return "Missione giornaliera: visita il grafico oggi."
    if mission_code == "weekly_login_streak":
        return "Conta i giorni distinti di accesso negli ultimi 7 giorni."
    if mission_code == "daily_prediction":
        return "Completa inviando una previsione oggi."
    return None


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
    "ensure_daily_missions",
    "ensure_prediction_wait_mission",
    "get_user_missions",
    "record_daily_event",
    "sync_user_missions",
    "cleanup_expired_missions",
]
