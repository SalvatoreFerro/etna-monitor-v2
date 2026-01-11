"""Add copernicus_images table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20251226_add_copernicus_images"
down_revision = "20251224_add_telegram_link_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "copernicus_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.String(length=128), nullable=False),
        sa.Column("cloud_cover", sa.Float(), nullable=True),
        sa.Column(
            "bbox",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("image_path", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_copernicus_images_acquired_at",
        "copernicus_images",
        ["acquired_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_copernicus_images_acquired_at", table_name="copernicus_images")
    op.drop_table("copernicus_images")
