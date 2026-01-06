"""Add admin_action_logs table."""

from alembic import op
import sqlalchemy as sa


revision = "20251222_add_admin_action_logs"
down_revision = "20251221_add_alert_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="success",
        ),
        sa.Column("message", sa.String(length=255), nullable=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=True),
        sa.Column(
            "target_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("target_email", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("admin_action_logs")
