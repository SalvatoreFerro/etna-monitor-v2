from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index

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


class SponsorBannerImpression(db.Model):
    __tablename__ = "sponsor_banner_impressions"
    __table_args__ = (
        Index("ix_banner_impression_session", "banner_id", "session_id", "ts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    banner_id = db.Column(db.Integer, db.ForeignKey("sponsor_banners.id"), nullable=False)
    ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    page = db.Column(db.String(255))
    session_id = db.Column(db.String(64))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    ip_hash = db.Column(db.String(64))

    banner = db.relationship(
        "SponsorBanner",
        backref=db.backref("impressions", lazy="dynamic"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SponsorBannerImpression banner_id={self.banner_id} ts={self.ts.isoformat()} "
            f"page={self.page!r}>"
        )


class SponsorBannerClick(db.Model):
    __tablename__ = "sponsor_banner_clicks"
    __table_args__ = (
        Index("ix_banner_click_session", "banner_id", "session_id", "ts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    banner_id = db.Column(db.Integer, db.ForeignKey("sponsor_banners.id"), nullable=False)
    ts = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    page = db.Column(db.String(255))
    session_id = db.Column(db.String(64))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    ip_hash = db.Column(db.String(64))

    banner = db.relationship(
        "SponsorBanner",
        backref=db.backref("clicks", lazy="dynamic"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<SponsorBannerClick banner_id={self.banner_id} ts={self.ts.isoformat()} "
            f"page={self.page!r}>"
        )
