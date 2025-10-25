from __future__ import annotations

from datetime import datetime

from . import db


class SponsorBanner(db.Model):
    __tablename__ = "sponsor_banners"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    image_url = db.Column(db.String(512), nullable=False)
    target_url = db.Column(db.String(512), nullable=False)
    description = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<SponsorBanner id={self.id} title={self.title!r} active={self.active}>"
