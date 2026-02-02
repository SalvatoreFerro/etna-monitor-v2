"""Models supporting the on-site feedback and review system."""

from __future__ import annotations

from datetime import datetime, timezone

from . import db


class UserFeedback(db.Model):
    """Stores qualitative and quantitative feedback submitted by visitors."""

    __tablename__ = "user_feedback"

    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    display_name = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default="new", server_default="new")
    handled_by = db.Column(db.String(120), nullable=True)
    handled_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_user_feedback_rating_range"),
        db.CheckConstraint("status IN ('new', 'reviewed', 'archived')", name="ck_user_feedback_status"),
    )

    def mark_reviewed(self, reviewer: str) -> None:
        self.status = "reviewed"
        self.handled_by = reviewer
        self.handled_at = datetime.now(timezone.utc)

    def archive(self, reviewer: str | None = None) -> None:
        self.status = "archived"
        if reviewer:
            self.handled_by = reviewer
        self.handled_at = datetime.now(timezone.utc)


class FeedbackVote(db.Model):
    """Aggregates community endorsement for feedback notes to drive gamification."""

    __tablename__ = "feedback_votes"

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey("user_feedback.id", ondelete="CASCADE"), nullable=False)
    voter_email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    feedback = db.relationship("UserFeedback", backref=db.backref("votes", lazy="dynamic", cascade="all, delete-orphan"))


def feedback_vote_count(feedback: UserFeedback) -> int:
    """Return cached vote count when relationship is loaded."""

    if hasattr(feedback, "votes") and feedback.votes is not None:
        try:
            return feedback.votes.count()
        except Exception:  # pragma: no cover - fallback when relationship is not query based
            pass
    return 0
