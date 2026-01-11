from __future__ import annotations

from datetime import datetime, timezone

from . import db


class TelegramLinkToken(db.Model):
    __tablename__ = "telegram_link_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("telegram_link_tokens", lazy="dynamic"))

    def __repr__(self) -> str:
        return f"<TelegramLinkToken user_id={self.user_id} expires_at={self.expires_at}>"
