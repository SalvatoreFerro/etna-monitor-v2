"""Normalize alert columns on users to match application expectations."""

from alembic import op


revision = "20251027_fix_free_alert_consumed_type"
down_revision = "20251026_add_missing_user_alert_columns"
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
        SELECT data_type
          INTO free_alert_type
          FROM information_schema.columns
         WHERE table_name = 'users' AND column_name = 'free_alert_consumed';

        IF free_alert_type IS NOT NULL AND free_alert_type <> 'boolean' THEN
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

        IF free_alert_event_type IS NOT NULL AND free_alert_event_type <> 'character varying' THEN
            ALTER TABLE users
                ALTER COLUMN free_alert_event_id TYPE VARCHAR(255)
                USING free_alert_event_id::text;
        END IF;
    END$$;
        """
    )


def downgrade() -> None:
    # No downgrade: aligns schema with application model without data loss.
    pass
