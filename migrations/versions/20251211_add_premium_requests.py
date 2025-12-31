"""Add premium requests table."""

from alembic import op
import sqlalchemy as sa

revision = "20251211_add_premium_requests"
down_revision = "20251210_add_partner_short_desc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "premium_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("paypal_tx_id", sa.String(length=255), nullable=True),
        sa.Column("donor_message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="paypal"),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_admin_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes_admin", sa.Text(), nullable=True),
    )
    op.create_index("ix_premium_requests_email", "premium_requests", ["email"])
    op.create_index("ix_premium_requests_status", "premium_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_premium_requests_status", table_name="premium_requests")
    op.drop_index("ix_premium_requests_email", table_name="premium_requests")
    op.drop_table("premium_requests")
