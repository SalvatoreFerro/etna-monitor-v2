"""Add hotspots records table."""

from alembic import op
import sqlalchemy as sa

revision = "20251213_add_hotspots_records"
down_revision = "20251212_add_hotspots_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hotspots_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("satellite", sa.String(length=16), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("acq_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("brightness", sa.Float(), nullable=True),
        sa.Column("frp", sa.Float(), nullable=True),
        sa.Column("intensity_unit", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_hotspots_records_fingerprint",
        "hotspots_records",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "ix_hotspots_records_acq_datetime",
        "hotspots_records",
        ["acq_datetime"],
    )


def downgrade() -> None:
    op.drop_index("ix_hotspots_records_acq_datetime", table_name="hotspots_records")
    op.drop_index("ix_hotspots_records_fingerprint", table_name="hotspots_records")
    op.drop_table("hotspots_records")
