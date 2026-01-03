"""Add raw FIRMS fields to hotspots records."""

from alembic import op
import sqlalchemy as sa

revision = "20251214_add_hotspots_record_raw_fields"
down_revision = "20251213_add_hotspots_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hotspots_records", sa.Column("instrument", sa.String(length=16), nullable=True))
    op.add_column("hotspots_records", sa.Column("bright_ti4", sa.Float(), nullable=True))
    op.add_column("hotspots_records", sa.Column("bright_ti5", sa.Float(), nullable=True))
    op.add_column("hotspots_records", sa.Column("daynight", sa.String(length=8), nullable=True))
    op.add_column("hotspots_records", sa.Column("version", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("hotspots_records", "version")
    op.drop_column("hotspots_records", "daynight")
    op.drop_column("hotspots_records", "bright_ti5")
    op.drop_column("hotspots_records", "bright_ti4")
    op.drop_column("hotspots_records", "instrument")
