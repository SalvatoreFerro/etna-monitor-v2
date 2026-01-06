"""Add alert state table for alerting cursor."""

from alembic import op
import sqlalchemy as sa


revision = "20251221_add_alert_state"
down_revision = "20251220_update_cron_runs_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_checked_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("alert_states")
