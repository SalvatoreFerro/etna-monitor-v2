"""Persisted state for alert evaluation."""
from __future__ import annotations

from datetime import datetime, timezone

from . import db


class AlertState(db.Model):
    __tablename__ = "alert_states"

    id = db.Column(db.Integer, primary_key=True)
    last_checked_ts = db.Column(db.DateTime(timezone=True), nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


__all__ = ["AlertState"]
