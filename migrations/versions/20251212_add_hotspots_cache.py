"""Add hotspots cache table."""

from alembic import op
import sqlalchemy as sa

try:  # pragma: no cover - optional dependency guard
    from sqlalchemy.dialects import postgresql

    _PAYLOAD_TYPE = sa.JSON().with_variant(postgresql.JSONB, "postgresql")
except ModuleNotFoundError:  # pragma: no cover - fallback for limited envs
    _PAYLOAD_TYPE = sa.JSON()

revision = "20251212_add_hotspots_cache"
down_revision = "20251211_add_premium_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hotspots_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", _PAYLOAD_TYPE, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_hotspots_cache_key", "hotspots_cache", ["key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_hotspots_cache_key", table_name="hotspots_cache")
    op.drop_table("hotspots_cache")
