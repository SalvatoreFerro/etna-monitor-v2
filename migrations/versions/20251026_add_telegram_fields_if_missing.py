"""Ensure Telegram, alert and privacy columns exist on users (idempotent)."""

from alembic import op

revision = "20251026_add_telegram_fields_if_missing"
down_revision = "202410020001_align_users_schema_to_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT,
            ADD COLUMN IF NOT EXISTS telegram_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS free_alert_consumed INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS free_alert_event_id INTEGER,
            ADD COLUMN IF NOT EXISTS last_alert_sent_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS alert_count_30d INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS consent_ts TIMESTAMP,
            ADD COLUMN IF NOT EXISTS privacy_version INTEGER NOT NULL DEFAULT 1;
        """
    )


def downgrade() -> None:
    # Intentionally left blank: the schema guard migration is idempotent and non-destructive.
    pass
