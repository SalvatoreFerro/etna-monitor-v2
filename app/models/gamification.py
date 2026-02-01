"""Database models to support gamification state for EtnaMonitor users."""

from __future__ import annotations

from datetime import datetime, timezone

from . import db


class UserGamificationProfile(db.Model):
    """Aggregated gamification metrics for authenticated users."""

    __tablename__ = "user_gamification_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    points = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    level = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    streak_days = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    last_interaction_at = db.Column(db.DateTime, nullable=True)
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref=db.backref("gamification", uselist=False, cascade="all, delete-orphan"))

    __table_args__ = (
        db.CheckConstraint("points >= 0", name="ck_gamification_points_non_negative"),
        db.CheckConstraint("level >= 1", name="ck_gamification_level_positive"),
        db.CheckConstraint("streak_days >= 0", name="ck_gamification_streak_non_negative"),
    )

    def add_points(self, amount: int) -> None:
        amount = max(0, int(amount))
        self.points += amount
        self.last_interaction_at = datetime.now(timezone.utc)
        self._normalize_level()

    def register_onboarding(self) -> None:
        self.onboarding_completed_at = datetime.now(timezone.utc)
        self.add_points(25)

    def register_streak(self, today: datetime | None = None) -> None:
        today = today or datetime.now(timezone.utc)
        if self.last_interaction_at is None:
            self.streak_days = 1
        else:
            delta = today.date() - self.last_interaction_at.date()
            if delta.days == 1:
                self.streak_days += 1
            elif delta.days > 1:
                self.streak_days = 1
        self.last_interaction_at = today
        self._normalize_level()

    def _normalize_level(self) -> None:
        base = 100
        if self.points < base:
            self.level = 1
            return
        self.level = min(50, max(1, (self.points // base) + 1))


class UserBadge(db.Model):
    """Catalog of badges unlocked by community activities."""

    __tablename__ = "user_badges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code = db.Column(db.String(60), nullable=False)
    badge_code = db.Column(db.String(60), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False)
    awarded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    earned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("badges", lazy="dynamic", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint("user_id", "code", name="uq_user_badges_user_code"),
        db.UniqueConstraint("user_id", "badge_code", name="uq_user_badges_user_badge_code"),
    )

    def __repr__(self) -> str:  # pragma: no cover - helper
        return f"<UserBadge {self.user_id} {self.code}>"
