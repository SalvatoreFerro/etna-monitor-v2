"""Database model for internal cron run diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db


class CronRunLog(db.Model):
    """Persisted diagnostic snapshot for a cron run."""

    __tablename__ = "cron_run_logs"
    __table_args__ = (
        db.Index("ix_cron_run_logs_created_at_desc", db.desc("created_at")),
        db.Index("ix_cron_run_logs_ok", "ok"),
        db.Index("ix_cron_run_logs_sent", "sent"),
    )

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    duration_ms = db.Column(db.Float, nullable=True)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    sent = db.Column(db.Integer, nullable=False, default=0)
    skipped = db.Column(db.Integer, nullable=False, default=0)
    cooldown_skipped_count = db.Column(db.Integer, nullable=False, default=0)
    users_subscribed_count = db.Column(db.Integer, nullable=True)
    premium_subscribed_count = db.Column(db.Integer, nullable=True)
    moving_avg = db.Column(db.Float, nullable=True)
    threshold_used = db.Column(db.Float, nullable=True)
    last_point_ts = db.Column(db.DateTime(timezone=True), nullable=True)
    error = db.Column(db.String(255), nullable=True)
    exception_type = db.Column(db.String(255), nullable=True)
    message = db.Column(db.Text, nullable=True)
    request_id = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    diagnostic_json = db.Column(db.JSON, nullable=True)
    skipped_by_reason = db.Column(db.JSON, nullable=True)

    def serialize_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "duration_ms": self.duration_ms,
            "ok": bool(self.ok),
            "sent": self.sent,
            "skipped": self.skipped,
            "cooldown_skipped_count": self.cooldown_skipped_count,
            "error": self.error,
            "exception_type": self.exception_type,
        }

    def serialize_detail(self) -> dict[str, Any]:
        return {
            **self.serialize_summary(),
            "users_subscribed_count": self.users_subscribed_count,
            "premium_subscribed_count": self.premium_subscribed_count,
            "moving_avg": self.moving_avg,
            "threshold_used": self.threshold_used,
            "last_point_ts": self.last_point_ts.isoformat() if self.last_point_ts else None,
            "message": self.message,
            "request_id": self.request_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "diagnostic_json": self.diagnostic_json,
            "skipped_by_reason": self.skipped_by_reason,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CronRunLog id={self.id} ok={self.ok} sent={self.sent} skipped={self.skipped}>"
        )


__all__ = ["CronRunLog"]
