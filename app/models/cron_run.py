"""Database model for cron/automation run logs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db


class CronRun(db.Model):
    __tablename__ = "cron_runs"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    pipeline_id = db.Column(db.String(64), nullable=True, index=True)
    job_type = db.Column(db.String(32), nullable=False, index=True)
    ok = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("false"))
    reason = db.Column(db.String(255), nullable=True)
    duration_ms = db.Column(db.Float, nullable=True)

    csv_path = db.Column(db.String(512), nullable=True)
    csv_mtime = db.Column(db.DateTime(timezone=True), nullable=True)
    csv_size_bytes = db.Column(db.BigInteger, nullable=True)
    last_point_ts = db.Column(db.DateTime(timezone=True), nullable=True)
    moving_avg = db.Column(db.Float, nullable=True)

    users_subscribed_count = db.Column(db.Integer, nullable=True)
    premium_subscribed_count = db.Column(db.Integer, nullable=True)
    sent_count = db.Column(db.Integer, nullable=True)
    skipped_count = db.Column(db.Integer, nullable=True)
    skipped_by_reason = db.Column(db.JSON, nullable=True)

    error_type = db.Column(db.String(120), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    traceback = db.Column(db.Text, nullable=True)

    request_id = db.Column(db.String(128), nullable=True)
    payload = db.Column(db.JSON, nullable=True)

    def serialize(self, *, include_payload: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "pipeline_id": self.pipeline_id,
            "job_type": self.job_type,
            "ok": bool(self.ok),
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "csv_path": self.csv_path,
            "csv_mtime": self.csv_mtime.isoformat() if self.csv_mtime else None,
            "csv_size_bytes": self.csv_size_bytes,
            "last_point_ts": self.last_point_ts.isoformat() if self.last_point_ts else None,
            "moving_avg": self.moving_avg,
            "users_subscribed_count": self.users_subscribed_count,
            "premium_subscribed_count": self.premium_subscribed_count,
            "sent_count": self.sent_count,
            "skipped_count": self.skipped_count,
            "skipped_by_reason": self.skipped_by_reason,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "request_id": self.request_id,
        }
        if include_payload:
            data["payload"] = self.payload
        return data

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CronRun id={self.id} job_type={self.job_type!r} ok={self.ok} "
            f"created_at={self.created_at}>"
        )


__all__ = ["CronRun"]
