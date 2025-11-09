"""Community posts and moderation audit trail models."""

from __future__ import annotations

from datetime import datetime, timezone

from slugify import slugify

from . import db
from ..utils.sanitize import find_suspicious_html, sanitize_html

POST_STATUS_CHOICES = ("draft", "pending", "approved", "rejected", "hidden")


class CommunityPost(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(200), unique=True, index=True, nullable=False)
    author_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    body_html_sanitized = db.Column(
        db.Text,
        nullable=False,
        default="",
        server_default="",
    )
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    moderated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    moderated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    moderator_reason = db.Column(db.Text, nullable=True)
    anonymous = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
        server_default=db.text("false"),
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft','pending','approved','rejected','hidden')",
            name="ck_posts_valid_status",
        ),
    )

    author = db.relationship(
        "User",
        back_populates="posts",
        foreign_keys=[author_id],
    )
    moderator = db.relationship(
        "User",
        back_populates="moderated_posts",
        foreign_keys=[moderated_by],
    )
    moderation_actions = db.relationship(
        "ModerationAction",
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="ModerationAction.created_at.desc()",
    )

    def ensure_slug(self) -> None:
        if self.slug:
            return
        base = slugify(self.title or "post")[:180]
        candidate = base or f"post-{self.id or ''}".strip("-")
        suffix = 0
        while True:
            slug_candidate = candidate if suffix == 0 else f"{candidate}-{suffix}"[:190]
            existing = CommunityPost.query.filter(
                CommunityPost.slug == slug_candidate,
                CommunityPost.id != self.id,
            ).first()
            if not existing:
                self.slug = slug_candidate
                return
            suffix += 1

    def sanitize_body(self, raw_body: str) -> str:
        return sanitize_html(raw_body)

    def set_body(self, raw_body: str) -> list[str]:
        content = raw_body or ""
        self.body = content
        self.body_html_sanitized = self.sanitize_body(content)
        return find_suspicious_html(content)

    def has_suspicious_html(self) -> bool:
        return bool(find_suspicious_html(self.body))

    def publish(self, moderator_id: int | None, reason: str | None = None) -> None:
        self.status = "approved"
        now = datetime.now(timezone.utc)
        self.published_at = now
        self.moderated_at = now
        self.moderated_by = moderator_id
        self.moderator_reason = reason
        self.updated_at = now

    def reject(self, moderator_id: int | None, reason: str | None = None) -> None:
        self.status = "rejected"
        now = datetime.now(timezone.utc)
        self.moderated_at = now
        self.moderated_by = moderator_id
        self.moderator_reason = reason
        self.updated_at = now

    def hide(self, moderator_id: int | None, reason: str | None = None) -> None:
        self.status = "hidden"
        now = datetime.now(timezone.utc)
        self.moderated_at = now
        self.moderated_by = moderator_id
        self.moderator_reason = reason
        self.updated_at = now

    def is_visible_to(self, user) -> bool:
        if self.status == "approved":
            return True
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if user.is_moderator():
            return True
        return user.id == self.author_id

    def to_export(self) -> dict[str, object]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "body": self.body,
            "body_html_sanitized": self.body_html_sanitized,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "published_at": (
                self.published_at.isoformat() if self.published_at else None
            ),
            "moderated_at": (
                self.moderated_at.isoformat() if self.moderated_at else None
            ),
            "moderator_reason": self.moderator_reason,
            "anonymous": self.anonymous,
        }

    def __repr__(self) -> str:  # pragma: no cover - helper
        return f"<CommunityPost id={self.id} status={self.status}>"


class ModerationAction(db.Model):
    __tablename__ = "moderation_actions"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(
        db.Integer,
        db.ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    moderator_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.CheckConstraint(
            "action IN ('approve','reject','hide','restore','auto_hide_xss')",
            name="ck_moderation_actions_action",
        ),
    )

    post = db.relationship("CommunityPost", back_populates="moderation_actions")
    moderator = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover - helper
        return f"<ModerationAction id={self.id} action={self.action}>"


def _assign_slug(mapper, connection, target: CommunityPost) -> None:  # pragma: no cover
    target.ensure_slug()


def _apply_sanitization(mapper, connection, target: CommunityPost) -> None:  # pragma: no cover
    target.body_html_sanitized = target.sanitize_body(target.body or "")


db.event.listen(CommunityPost, "before_insert", _assign_slug)
db.event.listen(CommunityPost, "before_update", _assign_slug)
db.event.listen(CommunityPost, "before_insert", _apply_sanitization)
db.event.listen(CommunityPost, "before_update", _apply_sanitization)
