"""Add admin cron monitoring fields."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20251220_update_cron_runs_monitoring"
down_revision = "20251215_add_cron_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cron_runs",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "cron_runs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "cron_runs",
        sa.Column("status", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "cron_runs",
        sa.Column(
            "diagnostic_json",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.execute("UPDATE cron_runs SET started_at = created_at WHERE started_at IS NULL")
    op.execute("UPDATE cron_runs SET finished_at = created_at WHERE finished_at IS NULL")
    op.execute(
        "UPDATE cron_runs SET status = CASE WHEN ok THEN 'success' ELSE 'error' END WHERE status IS NULL"
    )
    op.create_index("ix_cron_runs_started_at", "cron_runs", ["started_at"])
    op.create_index("ix_cron_runs_status", "cron_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cron_runs_status", table_name="cron_runs")
    op.drop_index("ix_cron_runs_started_at", table_name="cron_runs")
    op.drop_column("cron_runs", "diagnostic_json")
    op.drop_column("cron_runs", "status")
    op.drop_column("cron_runs", "finished_at")
    op.drop_column("cron_runs", "started_at")
