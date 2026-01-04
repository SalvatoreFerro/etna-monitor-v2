"""Add cron runs logging table."""

from alembic import op
import sqlalchemy as sa

revision = "20251215_add_cron_runs"
down_revision = "20251214_add_hotspots_record_raw_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cron_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("pipeline_id", sa.String(length=64), nullable=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("csv_path", sa.String(length=512), nullable=True),
        sa.Column("csv_mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("csv_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("last_point_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moving_avg", sa.Float(), nullable=True),
        sa.Column("users_subscribed_count", sa.Integer(), nullable=True),
        sa.Column("premium_subscribed_count", sa.Integer(), nullable=True),
        sa.Column("sent_count", sa.Integer(), nullable=True),
        sa.Column("skipped_count", sa.Integer(), nullable=True),
        sa.Column("skipped_by_reason", sa.JSON(), nullable=True),
        sa.Column("error_type", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_cron_runs_created_at", "cron_runs", ["created_at"])
    op.create_index("ix_cron_runs_job_type", "cron_runs", ["job_type"])
    op.create_index("ix_cron_runs_pipeline_id", "cron_runs", ["pipeline_id"])


def downgrade() -> None:
    op.drop_index("ix_cron_runs_pipeline_id", table_name="cron_runs")
    op.drop_index("ix_cron_runs_job_type", table_name="cron_runs")
    op.drop_index("ix_cron_runs_created_at", table_name="cron_runs")
    op.drop_table("cron_runs")
