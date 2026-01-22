"""Add Copernicus preview status fields."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20251231_add_copernicus_preview_fields"
down_revision = "20251230_add_api_access_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("copernicus_images") as batch_op:
        batch_op.add_column(sa.Column("preview_path", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("status", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("copernicus_images") as batch_op:
        batch_op.drop_column("status")
        batch_op.drop_column("preview_path")
