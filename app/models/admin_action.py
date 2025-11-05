"""Database model for auditing administrator actions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db


class AdminActionLog(db.Model):
    """Persisted record describing an action executed by an administrator."""

    __tablename__ = "admin_action_logs"

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="success")
    message = db.Column(db.String(255), nullable=True)

    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    admin_email = db.Column(db.String(255), nullable=True)

    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    target_email = db.Column(db.String(255), nullable=True)

    ip_address = db.Column(db.String(64), nullable=True)
    context = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    admin = db.relationship("User", foreign_keys=[admin_id], backref="admin_actions", lazy="joined")
    target_user = db.relationship(
        "User",
        foreign_keys=[target_user_id],
        backref=db.backref("admin_action_events", lazy="dynamic"),
        lazy="joined",
    )

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "status": self.status,
            "message": self.message,
            "admin_id": self.admin_id,
            "admin_email": self.admin_email,
            "target_user_id": self.target_user_id,
            "target_email": self.target_email,
            "ip_address": self.ip_address,
            "context": self.context,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<AdminActionLog action={self.action!r} admin={self.admin_email!r} "
            f"target={self.target_email!r} status={self.status!r}>"
        )


__all__ = ["AdminActionLog"]
