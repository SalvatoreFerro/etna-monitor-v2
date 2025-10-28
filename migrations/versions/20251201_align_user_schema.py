"""Align users table schema with application model."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251201_align_user_schema"
down_revision = "20251101_fix_telegram_chat_ids"
branch_labels = None
depends_on = None


_USER_COLUMNS = {
    "password_hash": sa.Column("password_hash", sa.String(length=128), nullable=True, server_default=""),
    "premium": sa.Column("premium", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "is_premium": sa.Column("is_premium", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "premium_lifetime": sa.Column("premium_lifetime", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "premium_since": sa.Column("premium_since", sa.DateTime(), nullable=True),
    "donation_tx": sa.Column("donation_tx", sa.String(length=255), nullable=True),
    "chat_id": sa.Column("chat_id", sa.BigInteger(), nullable=True),
    "plan_type": sa.Column("plan_type", sa.String(length=20), nullable=False, server_default="free"),
    "is_admin": sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "telegram_chat_id": sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
    "telegram_opt_in": sa.Column("telegram_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "free_alert_consumed": sa.Column("free_alert_consumed", sa.Integer(), nullable=False, server_default="0"),
    "free_alert_event_id": sa.Column("free_alert_event_id", sa.String(length=255), nullable=True),
    "last_alert_sent_at": sa.Column("last_alert_sent_at", sa.DateTime(), nullable=True),
    "alert_count_30d": sa.Column("alert_count_30d", sa.Integer(), nullable=False, server_default="0"),
    "consent_ts": sa.Column("consent_ts", sa.DateTime(), nullable=True),
    "privacy_version": sa.Column("privacy_version", sa.String(length=32), nullable=True),
    "threshold": sa.Column("threshold", sa.Float(), nullable=True),
    "email_alerts": sa.Column("email_alerts", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    "stripe_customer_id": sa.Column("stripe_customer_id", sa.String(length=100), nullable=True),
    "subscription_status": sa.Column("subscription_status", sa.String(length=20), nullable=False, server_default="free"),
    "subscription_id": sa.Column("subscription_id", sa.String(length=100), nullable=True),
    "current_period_end": sa.Column("current_period_end", sa.DateTime(), nullable=True),
    "trial_end": sa.Column("trial_end", sa.DateTime(), nullable=True),
    "billing_email": sa.Column("billing_email", sa.String(length=120), nullable=True),
    "company_name": sa.Column("company_name", sa.String(length=200), nullable=True),
    "vat_id": sa.Column("vat_id", sa.String(length=50), nullable=True),
    "google_id": sa.Column("google_id", sa.String(length=255), nullable=True),
    "name": sa.Column("name", sa.String(length=255), nullable=True),
    "picture_url": sa.Column("picture_url", sa.String(length=512), nullable=True),
    "theme_preference": sa.Column("theme_preference", sa.String(length=16), nullable=True, server_default="system"),
}


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    for column_name, column in _USER_COLUMNS.items():
        if not _column_exists(inspector, "users", column_name):
            op.add_column("users", column.copy())

    if _column_exists(inspector, "users", "theme_preference"):
        op.alter_column(
            "users",
            "theme_preference",
            existing_type=sa.String(),
            type_=sa.String(length=16),
            existing_nullable=False,
            nullable=True,
            server_default="system",
            existing_server_default="volcano_tech",
        )
        op.execute(
            sa.text(
                "UPDATE users SET theme_preference = 'system' WHERE theme_preference IS NULL OR trim(theme_preference) = ''"
            )
        )

    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_google_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_email"))
    op.alter_column(
        "users",
        "theme_preference",
        existing_type=sa.String(),
        type_=sa.String(length=50),
        existing_nullable=True,
        nullable=False,
        server_default="volcano_tech",
        existing_server_default="system",
    )
