"""Add light badges, levels, and login indexes."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260110_add_badges_levels"
down_revision = "20251231_add_copernicus_preview_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("user_level", sa.Integer(), nullable=False, server_default="1")
        )

    with op.batch_alter_table("user_badges") as batch_op:
        batch_op.add_column(sa.Column("badge_code", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("earned_at", sa.DateTime(), nullable=True))

    op.execute("UPDATE user_badges SET badge_code = code WHERE badge_code IS NULL")
    op.execute(
        "UPDATE user_badges SET earned_at = awarded_at WHERE earned_at IS NULL"
    )

    with op.batch_alter_table("user_badges") as batch_op:
        batch_op.alter_column(
            "badge_code", existing_type=sa.String(length=60), nullable=False
        )
        batch_op.alter_column(
            "earned_at", existing_type=sa.DateTime(), nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_user_badges_user_badge_code", ["user_id", "badge_code"]
        )

    op.create_index(
        "ix_events_user_id_timestamp", "events", ["user_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_events_user_id_timestamp", table_name="events")

    with op.batch_alter_table("user_badges") as batch_op:
        batch_op.drop_constraint(
            "uq_user_badges_user_badge_code", type_="unique"
        )
        batch_op.drop_column("earned_at")
        batch_op.drop_column("badge_code")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("user_level")
