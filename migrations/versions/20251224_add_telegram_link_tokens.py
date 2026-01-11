"""Add telegram_link_tokens table for deep-linking."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20251224_add_telegram_link_tokens"
down_revision = "20251223_merge_admin_action_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_telegram_link_tokens_token",
        "telegram_link_tokens",
        ["token"],
        unique=True,
    )
    op.create_index(
        "ix_telegram_link_tokens_user_id",
        "telegram_link_tokens",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_link_tokens_user_id", table_name="telegram_link_tokens")
    op.drop_index("ix_telegram_link_tokens_token", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")
