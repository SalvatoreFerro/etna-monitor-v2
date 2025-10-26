"""add telegram fields to users"""

from alembic import op
import sqlalchemy as sa


revision = "202410020002_add_telegram_fields_to_users"
down_revision = "202410020001_align_users_schema_to_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger()))
    op.add_column(
        "users",
        sa.Column(
            "telegram_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "telegram_opt_in")
    op.drop_column("users", "telegram_chat_id")
