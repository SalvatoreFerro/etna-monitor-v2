from datetime import datetime, timezone

from . import db


class TremorPrediction(db.Model):
    __tablename__ = "tremor_predictions"
    __table_args__ = (
        db.Index("ix_tremor_predictions_user_id", "user_id"),
        db.Index("ix_tremor_predictions_resolved", "resolved"),
        db.Index("ix_tremor_predictions_resolves_at", "resolves_at"),
        db.CheckConstraint(
            "prediction IN ('UP', 'DOWN', 'FLAT')",
            name="ck_tremor_predictions_prediction",
        ),
        db.CheckConstraint("horizon_hours > 0", name="ck_tremor_predictions_horizon"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    horizon_hours = db.Column(
        db.Integer,
        nullable=False,
        default=24,
        server_default="24",
    )
    prediction = db.Column(db.String(8), nullable=False)
    resolves_at = db.Column(db.DateTime(timezone=True), nullable=False)
    resolved = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )
    actual_outcome = db.Column(db.String(8), nullable=True)
    points_awarded = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    user = db.relationship("User", backref="tremor_predictions")

    def __repr__(self) -> str:
        return (
            "<TremorPrediction id=%s user_id=%s prediction=%s resolved=%s>"
            % (self.id, self.user_id, self.prediction, self.resolved)
        )


__all__ = ["TremorPrediction"]
