"""Ensure theme_preference column exists with server default."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "20251203_add_theme_preference_column"
down_revision = "20251202_merge_user_theme_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "theme_preference" not in columns:
        op.add_column(
            "users",
            sa.Column(
                "theme_preference",
                sa.String(length=16),
                nullable=True,
                server_default=sa.text("'system'"),
            ),
        )
    else:
        op.alter_column(
            "users",
            "theme_preference",
            existing_type=sa.String(),
            type_=sa.String(length=16),
            existing_nullable=True,
            nullable=True,
            server_default=sa.text("'system'"),
            existing_server_default=None,
        )

    op.execute(
        text(
            "UPDATE users SET theme_preference = 'system' "
            "WHERE theme_preference IS NULL OR trim(theme_preference) = ''"
        )
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "theme_preference",
        existing_type=sa.String(length=16),
        type_=sa.String(length=16),
        existing_nullable=True,
        nullable=True,
        server_default=None,
    )
