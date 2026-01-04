"""Add cron run logs table."""

from alembic import op
import sqlalchemy as sa

revision = "20251215_add_cron_run_logs"
down_revision = "20251214_add_hotspots_record_raw_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cron_run_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("sent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "cooldown_skipped_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("users_subscribed_count", sa.Integer(), nullable=True),
        sa.Column("premium_subscribed_count", sa.Integer(), nullable=True),
        sa.Column("moving_avg", sa.Float(), nullable=True),
        sa.Column("threshold_used", sa.Float(), nullable=True),
        sa.Column("last_point_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("exception_type", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("diagnostic_json", sa.JSON(), nullable=True),
        sa.Column("skipped_by_reason", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_cron_run_logs_created_at_desc",
        "cron_run_logs",
        [sa.text("created_at DESC")],
    )
    op.create_index("ix_cron_run_logs_ok", "cron_run_logs", ["ok"])
    op.create_index("ix_cron_run_logs_sent", "cron_run_logs", ["sent"])


def downgrade() -> None:
    op.drop_index("ix_cron_run_logs_sent", table_name="cron_run_logs")
    op.drop_index("ix_cron_run_logs_ok", table_name="cron_run_logs")
    op.drop_index("ix_cron_run_logs_created_at_desc", table_name="cron_run_logs")
    op.drop_table("cron_run_logs")
