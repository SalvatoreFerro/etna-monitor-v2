"""Forum/Q&A models supporting the community features."""

from __future__ import annotations

from datetime import datetime

from slugify import slugify

from . import db


class ForumThread(db.Model):
    """Top level question or discussion entry."""

    __tablename__ = "forum_threads"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), nullable=False, unique=True, index=True)
    body = db.Column(db.Text, nullable=False)
    author_name = db.Column(db.String(120), nullable=True)
    author_email = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open", server_default="open")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    replies = db.relationship(
        "ForumReply",
        backref="thread",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="ForumReply.created_at.asc()",
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('open', 'resolved', 'archived')", name="ck_forum_threads_status_valid"),
    )

    @staticmethod
    def build_slug(title: str) -> str:
        base = slugify(title or "thread")
        return base[:170]

    def ensure_slug(self) -> None:
        if not self.slug:
            candidate = self.build_slug(self.title)
            suffix = 1
            unique_candidate = candidate
            while ForumThread.query.filter(ForumThread.slug == unique_candidate, ForumThread.id != self.id).first():
                suffix += 1
                unique_candidate = f"{candidate}-{suffix}"[:170]
            self.slug = unique_candidate

    def __repr__(self) -> str:  # pragma: no cover - helper
        return f"<ForumThread {self.slug}>"


class ForumReply(db.Model):
    """Reply entity for a given thread."""

    __tablename__ = "forum_replies"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("forum_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    author_name = db.Column(db.String(120), nullable=True)
    author_email = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover - helper
        return f"<ForumReply {self.id} thread={self.thread_id}>"


def track_thread_slug(mapper, connection, target: ForumThread) -> None:  # pragma: no cover - hook
    target.ensure_slug()


db.event.listen(ForumThread, "before_insert", track_thread_slug)
db.event.listen(ForumThread, "before_update", track_thread_slug)
