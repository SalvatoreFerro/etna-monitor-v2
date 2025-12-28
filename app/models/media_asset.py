"""Models for media assets stored in the admin media library."""

from __future__ import annotations

from datetime import datetime

from . import db


class MediaAsset(db.Model):
    """Represents an uploaded media asset stored on Cloudinary."""

    __tablename__ = "media_assets"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(1024), nullable=False)
    public_id = db.Column(db.String(255), nullable=False, unique=True)
    original_filename = db.Column(db.String(255), nullable=True)
    bytes = db.Column(db.Integer, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - string helper
        return f"<MediaAsset {self.public_id}>"
