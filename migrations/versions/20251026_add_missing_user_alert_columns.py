"""Ensure Telegram and alert columns exist on users (idempotent)."""

from alembic import op

revision = "20251026_add_missing_user_alert_columns"
down_revision = "202410020001_align_users_schema_to_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
    DO $$
    DECLARE
        free_alert_type text;
        free_alert_event_type text;
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='users' AND column_name='telegram_chat_id'
        ) THEN
            ALTER TABLE users ADD COLUMN telegram_chat_id BIGINT;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='users' AND column_name='telegram_opt_in'
        ) THEN
            ALTER TABLE users ADD COLUMN telegram_opt_in BOOLEAN NOT NULL DEFAULT FALSE;
        END IF;

        SELECT data_type
          INTO free_alert_type
          FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'free_alert_consumed';

        IF free_alert_type IS NULL THEN
            ALTER TABLE users ADD COLUMN free_alert_consumed BOOLEAN NOT NULL DEFAULT FALSE;
        ELSIF free_alert_type <> 'boolean' THEN
            ALTER TABLE users ALTER COLUMN free_alert_consumed DROP DEFAULT;
            ALTER TABLE users
                ALTER COLUMN free_alert_consumed TYPE BOOLEAN
                USING COALESCE(free_alert_consumed, 0) <> 0;
            ALTER TABLE users ALTER COLUMN free_alert_consumed SET DEFAULT FALSE;
            ALTER TABLE users ALTER COLUMN free_alert_consumed SET NOT NULL;
        END IF;

        SELECT data_type
          INTO free_alert_event_type
          FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'free_alert_event_id';

        IF free_alert_event_type IS NULL THEN
            ALTER TABLE users ADD COLUMN free_alert_event_id VARCHAR(255);
        ELSIF free_alert_event_type <> 'character varying' THEN
            ALTER TABLE users
                ALTER COLUMN free_alert_event_id TYPE VARCHAR(255)
                USING free_alert_event_id::text;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='users' AND column_name='last_alert_sent_at'
        ) THEN
            ALTER TABLE users ADD COLUMN last_alert_sent_at TIMESTAMPTZ;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='users' AND column_name='alert_count_30d'
        ) THEN
            ALTER TABLE users ADD COLUMN alert_count_30d INTEGER NOT NULL DEFAULT 0;
        END IF;
    END$$;
        """
    )


def downgrade() -> None:
    # Intentionally left blank: the schema guard migration is idempotent and non-destructive.
    pass
