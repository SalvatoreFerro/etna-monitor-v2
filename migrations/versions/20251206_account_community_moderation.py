"""Account lifecycle improvements and community moderation tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20251206_account_community_moderation"
down_revision = "20251205_community_hub"
branch_labels = None
depends_on = None


def _column_exists(inspector, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspector.get_columns(table))


def _table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _column_exists(inspector, "users", "role"):
        op.add_column(
            "users",
            sa.Column("role", sa.String(length=20), nullable=False, server_default="free"),
        )
        op.execute(
            text(
                """
                UPDATE users
                SET role = CASE
                    WHEN is_admin THEN 'admin'
                    WHEN COALESCE(plan_type, '') = 'premium'
                        OR COALESCE(subscription_status, '') IN ('active', 'trialing')
                        OR is_premium
                        OR premium
                        OR premium_lifetime THEN 'premium'
                    ELSE 'free'
                END
                """
            )
        )
        op.alter_column("users", "role", server_default=None)

    if not _column_exists(inspector, "users", "deleted_at"):
        op.add_column(
            "users",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(inspector, "users", "erased_at"):
        op.add_column(
            "users",
            sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(inspector, "users", "is_active"):
        op.add_column(
            "users",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
        op.execute(text("UPDATE users SET is_active = TRUE"))
        op.alter_column("users", "is_active", server_default=None)

    if not _table_exists(inspector, "posts"):
        op.create_table(
            "posts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=200), nullable=False),
            sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("moderated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("moderator_reason", sa.Text(), nullable=True),
            sa.Column("anonymous", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.CheckConstraint(
                "status IN ('draft','pending','approved','rejected','hidden')",
                name="ck_posts_valid_status",
            ),
        )
        op.create_index("ix_posts_slug", "posts", ["slug"], unique=True)
        op.create_index("ix_posts_author_id", "posts", ["author_id"])
        op.create_index("ix_posts_moderated_by", "posts", ["moderated_by"])

    if not _table_exists(inspector, "moderation_actions"):
        op.create_table(
            "moderation_actions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("moderator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.CheckConstraint(
                "action IN ('approve','reject','hide','restore')",
                name="ck_moderation_actions_action",
            ),
        )
        op.create_index("ix_moderation_actions_post_id", "moderation_actions", ["post_id"])
        op.create_index("ix_moderation_actions_moderator_id", "moderation_actions", ["moderator_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _table_exists(inspector, "moderation_actions"):
        op.drop_table("moderation_actions")

    if _table_exists(inspector, "posts"):
        op.drop_table("posts")

    if _column_exists(inspector, "users", "is_active"):
        op.drop_column("users", "is_active")

    if _column_exists(inspector, "users", "erased_at"):
        op.drop_column("users", "erased_at")

    if _column_exists(inspector, "users", "deleted_at"):
        op.drop_column("users", "deleted_at")

    if _column_exists(inspector, "users", "role"):
        op.drop_column("users", "role")
