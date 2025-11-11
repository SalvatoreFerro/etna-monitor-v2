"""Ensure missing partner description columns exist"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251210_add_partner_short_desc"
down_revision = "20251209_merge_partner_validation_branch"
branch_labels = None
depends_on = None


def _column_missing(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    columns = {col["name"] for col in inspector.get_columns(table)}
    return column not in columns


def upgrade() -> None:
    if _column_missing("partners", "short_desc"):
        op.add_column(
            "partners",
            sa.Column("short_desc", sa.String(length=280), nullable=True),
        )
    if _column_missing("partners", "long_desc"):
        op.add_column(
            "partners",
            sa.Column("long_desc", sa.Text(), nullable=True),
        )


def downgrade() -> None:  # pragma: no cover - destructive downgrade intentionally omitted
    """Downgrade intentionally left empty to avoid accidental data loss."""
    pass
