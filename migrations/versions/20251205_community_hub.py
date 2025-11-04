"""Introduce community hub tables (blog, forum, feedback, gamification)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251205_community_hub"
down_revision = "20251203_add_theme_preference_column"
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _table_exists(inspector, "blog_posts"):
        op.create_table(
            "blog_posts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=180), nullable=False),
            sa.Column("slug", sa.String(length=200), nullable=False),
            sa.Column("summary", sa.String(length=280), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("hero_image", sa.String(length=512), nullable=True),
            sa.Column("seo_title", sa.String(length=190), nullable=True),
            sa.Column("seo_description", sa.String(length=300), nullable=True),
            sa.Column("seo_keywords", sa.String(length=300), nullable=True),
            sa.Column("seo_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.CheckConstraint("seo_score >= 0", name="ck_blog_posts_seo_score_non_negative"),
        )
        op.create_index("ix_blog_posts_slug", "blog_posts", ["slug"], unique=True)

    if not _table_exists(inspector, "forum_threads"):
        op.create_table(
            "forum_threads",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("slug", sa.String(length=180), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author_name", sa.String(length=120), nullable=True),
            sa.Column("author_email", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.CheckConstraint("status IN ('open', 'resolved', 'archived')", name="ck_forum_threads_status_valid"),
        )
        op.create_index("ix_forum_threads_slug", "forum_threads", ["slug"], unique=True)

    if not _table_exists(inspector, "forum_replies"):
        op.create_table(
            "forum_replies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("thread_id", sa.Integer(), sa.ForeignKey("forum_threads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author_name", sa.String(length=120), nullable=True),
            sa.Column("author_email", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_forum_replies_thread_id", "forum_replies", ["thread_id"])

    if not _table_exists(inspector, "user_feedback"):
        op.create_table(
            "user_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False),
            sa.Column("category", sa.String(length=80), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("display_name", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
            sa.Column("handled_by", sa.String(length=120), nullable=True),
            sa.Column("handled_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_user_feedback_rating_range"),
            sa.CheckConstraint("status IN ('new', 'reviewed', 'archived')", name="ck_user_feedback_status"),
        )

    if not _table_exists(inspector, "feedback_votes"):
        op.create_table(
            "feedback_votes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("feedback_id", sa.Integer(), sa.ForeignKey("user_feedback.id", ondelete="CASCADE"), nullable=False),
            sa.Column("voter_email", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_feedback_votes_feedback_id", "feedback_votes", ["feedback_id"])

    if not _table_exists(inspector, "user_gamification_profiles"):
        op.create_table(
            "user_gamification_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_interaction_at", sa.DateTime(), nullable=True),
            sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True),
            sa.CheckConstraint("points >= 0", name="ck_gamification_points_non_negative"),
            sa.CheckConstraint("level >= 1", name="ck_gamification_level_positive"),
            sa.CheckConstraint("streak_days >= 0", name="ck_gamification_streak_non_negative"),
        )

    if not _table_exists(inspector, "user_badges"):
        op.create_table(
            "user_badges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code", sa.String(length=60), nullable=False),
            sa.Column("label", sa.String(length=120), nullable=False),
            sa.Column("awarded_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("user_id", "code", name="uq_user_badges_user_code"),
        )
        op.create_index("ix_user_badges_user_id", "user_badges", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for table_name in (
        "user_badges",
        "user_gamification_profiles",
        "feedback_votes",
        "user_feedback",
        "forum_replies",
        "forum_threads",
        "blog_posts",
    ):
        if _table_exists(inspector, table_name):
            op.drop_table(table_name)
