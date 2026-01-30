"""Utility helpers to keep the gamification system consistent across actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from flask_login import current_user

from ..models import db, User, UserGamificationProfile, UserBadge


@dataclass
class AwardResult:
    profile: UserGamificationProfile
    created: bool


class GamificationService:
    """High level API to track points and achievements."""

    DEFAULT_REWARD_MAP = {
        "feedback:new": 30,
        "forum:thread": 45,
        "forum:reply": 20,
        "blog:read": 5,
        "onboarding:complete": 25,
    }

    BADGE_THRESHOLDS = (
        (100, ("scout", "Esploratore dei dati")),
        (250, ("specialist", "Specialista del tremore")),
        (500, ("mentor", "Mentor della community")),
    )

    def __init__(self, user: User | None = None) -> None:
        self.user = user or getattr(current_user, "_get_current_object", lambda: None)()

    def ensure_profile(self) -> AwardResult | None:
        if not self.user or not getattr(self.user, "is_authenticated", False):
            return None

        profile = UserGamificationProfile.query.filter_by(user_id=self.user.id).first()
        created = False
        if profile is None:
            profile = UserGamificationProfile(user_id=self.user.id)
            db.session.add(profile)
            created = True
        return AwardResult(profile=profile, created=created)

    def award(self, action: str, multiplier: int = 1) -> None:
        context = self.ensure_profile()
        if context is None:
            return

        points = self.DEFAULT_REWARD_MAP.get(action, 0) * max(1, multiplier)
        if points <= 0:
            return

        context.profile.add_points(points)
        self._assign_badges(context.profile)

    def register_onboarding(self) -> None:
        context = self.ensure_profile()
        if context is None:
            return
        context.profile.register_onboarding()
        self._assign_badges(context.profile)

    def record_visit(self) -> None:
        context = self.ensure_profile()
        if context is None:
            return
        context.profile.register_streak()
        self._assign_badges(context.profile)

    def _assign_badges(self, profile: UserGamificationProfile) -> None:
        unlocked_codes = {badge.code for badge in profile.user.badges}
        for threshold, (code, label) in self.BADGE_THRESHOLDS:
            if profile.points >= threshold and code not in unlocked_codes:
                db.session.add(
                    UserBadge(
                        user_id=profile.user_id,
                        code=code,
                        badge_code=code,
                        label=label,
                    )
                )


def ensure_demo_profiles() -> None:
    """Create gamification profiles for all existing users when missing."""

    users_without_profile = (
        User.query.outerjoin(UserGamificationProfile)
        .filter(UserGamificationProfile.id.is_(None))
        .all()
    )

    for user in users_without_profile:
        db.session.add(UserGamificationProfile(user_id=user.id, last_interaction_at=datetime.utcnow()))

    if users_without_profile:
        db.session.commit()
