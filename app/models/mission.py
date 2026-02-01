"""User missions model for gamification."""

from datetime import datetime, timezone

from . import db


class UserMission(db.Model):
    """Tracks user missions (daily/weekly challenges)."""

    __tablename__ = "user_missions"
    __table_args__ = (
        db.Index("ix_user_missions_user_id", "user_id"),
        db.Index("ix_user_missions_mission_code", "mission_code"),
        db.Index("ix_user_missions_expires_at", "expires_at"),
        db.Index("ix_user_missions_completed_at", "completed_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    mission_code = db.Column(db.String(64), nullable=False)
    awarded_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", backref="missions")

    def __repr__(self) -> str:
        return (
            f"<UserMission id={self.id} user_id={self.user_id} "
            f"code={self.mission_code} completed={self.completed_at is not None}>"
        )

    @property
    def is_completed(self) -> bool:
        """Check if mission is completed."""
        return self.completed_at is not None

    @property
    def is_expired(self) -> bool:
        """Check if mission is expired and not completed."""
        if self.is_completed:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_active(self) -> bool:
        """Check if mission is active (not expired and not completed)."""
        return not self.is_expired and not self.is_completed


__all__ = ["UserMission"]
