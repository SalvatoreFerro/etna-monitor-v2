from __future__ import annotations

from datetime import datetime, timezone

from . import db


class PremiumRequest(db.Model):
    __tablename__ = "premium_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=True)
    currency = db.Column(db.String(3), nullable=True)
    paypal_tx_id = db.Column(db.String(255), nullable=True)
    donor_message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    source = db.Column(db.String(32), nullable=False, default="paypal")
    raw_payload = db.Column(db.JSON, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    notes_admin = db.Column(db.Text, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_admin_id], lazy="joined")

    def mark_reviewed(self, status: str, admin_id: int | None, notes: str | None) -> None:
        self.status = status
        self.reviewed_at = datetime.now(timezone.utc)
        self.reviewed_by_admin_id = admin_id
        self.notes_admin = notes


__all__ = ["PremiumRequest"]
