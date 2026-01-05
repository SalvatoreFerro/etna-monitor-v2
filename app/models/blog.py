"""Blog post models used for the EtnaMonitor community hub."""

from __future__ import annotations

from datetime import datetime
import re

from slugify import slugify

from . import db


class BlogPost(db.Model):
    """Content entity for the blog section managed from the admin panel."""

    __tablename__ = "blog_posts"
    DEFAULT_AUTHOR_NAME = "Salvatore Ferro"
    DEFAULT_AUTHOR_SLUG = "salvatore-ferro"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
    summary = db.Column(db.String(280), nullable=True)
    content = db.Column(db.Text, nullable=False)
    hero_image = db.Column(db.String(512), nullable=True)  # legacy storage
    hero_image_url = db.Column(db.String(512), nullable=True)
    meta_title = db.Column(db.String(190), nullable=True)
    meta_description = db.Column(db.String(300), nullable=True)
    seo_title = db.Column(db.String(190), nullable=True)
    seo_description = db.Column(db.String(300), nullable=True)
    seo_keywords = db.Column(db.String(300), nullable=True)
    seo_score = db.Column(db.Integer, nullable=False, default=0)
    author_name = db.Column(db.String(120), nullable=True, default=DEFAULT_AUTHOR_NAME)
    author_slug = db.Column(db.String(140), nullable=True, default=DEFAULT_AUTHOR_SLUG)
    sources = db.Column(db.JSON, nullable=True)
    published = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("true"))
    published_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.CheckConstraint("seo_score >= 0", name="ck_blog_posts_seo_score_non_negative"),
    )

    def __repr__(self) -> str:  # pragma: no cover - string helper
        return f"<BlogPost {self.slug}>"

    @staticmethod
    def build_slug(title: str) -> str:
        """Return a normalized slug for the provided title."""

        base = slugify(title or "post")
        return base[:190]

    def ensure_slug(self) -> None:
        """Populate the slug when missing and keep it unique."""

        if not self.slug:
            candidate = self.build_slug(self.title)
            suffix = 1
            unique_candidate = candidate
            while BlogPost.query.filter(BlogPost.slug == unique_candidate, BlogPost.id != self.id).first():
                suffix += 1
                unique_candidate = f"{candidate}-{suffix}"[:190]
            self.slug = unique_candidate

    def apply_seo_boost(self) -> None:
        """Generate SEO metadata heuristically and store an indicative score."""

        title = (self.title or "").strip()
        summary = (self.summary or "").strip()
        content_preview = (self.content or "").strip()

        if not summary and content_preview:
            summary = content_preview.split("\n", 1)[0][:260]

        keyword_candidates = []
        for chunk in (title, summary, content_preview):
            if not chunk:
                continue
            for word in chunk.replace(",", " ").replace(".", " ").split():
                normalized = word.lower().strip()
                if len(normalized) > 4 and normalized not in keyword_candidates:
                    keyword_candidates.append(normalized)
            if len(keyword_candidates) >= 12:
                break

        keywords = ", ".join(keyword_candidates[:12]) or None

        self.meta_title = title[:180] if title else self.meta_title or None
        self.meta_description = summary[:280] if summary else self.meta_description or None
        # Keep legacy SEO fields in sync for backwards compatibility.
        self.seo_title = self.meta_title
        self.seo_description = self.meta_description
        self.seo_keywords = keywords

        score = 0
        if self.meta_title:
            score += 30
        if self.meta_description and len(self.meta_description) >= 120:
            score += 30
        if self.seo_keywords:
            score += 20
        if self.hero_image_url or self.hero_image:
            score += 20

        self.seo_score = min(score, 100)

    @property
    def abstract(self) -> str | None:
        """Expose ``summary`` as ``abstract`` for template ergonomics."""

        return self.summary

    @abstract.setter
    def abstract(self, value: str | None) -> None:
        self.summary = value

    @property
    def author_display_name(self) -> str:
        return (self.author_name or "").strip() or self.DEFAULT_AUTHOR_NAME

    @property
    def author_display_slug(self) -> str:
        fallback = self.author_display_name
        if self.author_slug:
            return self.author_slug
        return BlogPost.build_slug(fallback) or self.DEFAULT_AUTHOR_SLUG

    @property
    def reading_time_minutes(self) -> int:
        content = (self.content or "").strip()
        if not content:
            return 1
        words = re.findall(r"\\w+", content)
        minutes = max(1, round(len(words) / 200))
        return minutes


def track_blog_update(mapper, connection, target: BlogPost) -> None:  # pragma: no cover - hook side effect
    """Ensure slug and updated timestamp are applied before commit."""

    target.ensure_slug()


db.event.listen(BlogPost, "before_insert", track_blog_update)
db.event.listen(BlogPost, "before_update", track_blog_update)
