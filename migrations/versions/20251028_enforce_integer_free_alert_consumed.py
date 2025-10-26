"""ensure free_alert_consumed uses integer counters"""

from alembic import op
import sqlalchemy as sa


revision = "20251028_enforce_integer_free_alert_consumed"
down_revision = "20251027_fix_free_alert_consumed_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            free_alert_type text;
            alert_count_type text;
        BEGIN
            SELECT data_type
              INTO free_alert_type
              FROM information_schema.columns
             WHERE table_name = 'users'
               AND column_name = 'free_alert_consumed';

            IF free_alert_type IS NULL THEN
                ALTER TABLE users ADD COLUMN free_alert_consumed INTEGER;
            ELSIF free_alert_type <> 'integer' THEN
                ALTER TABLE users ALTER COLUMN free_alert_consumed DROP DEFAULT;
                ALTER TABLE users
                    ALTER COLUMN free_alert_consumed TYPE INTEGER
                    USING CASE
                        WHEN free_alert_consumed IS NULL THEN 0
                        WHEN lower(free_alert_consumed::text) IN ('t', 'true', 'y', 'yes', 'on') THEN 1
                        WHEN free_alert_consumed::text ~ '^[0-9]+$' THEN free_alert_consumed::text::INTEGER
                        ELSE 0
                    END;
            END IF;

            UPDATE users
               SET free_alert_consumed = COALESCE(free_alert_consumed, 0);

            ALTER TABLE users ALTER COLUMN free_alert_consumed SET DEFAULT 0;
            ALTER TABLE users ALTER COLUMN free_alert_consumed SET NOT NULL;

            SELECT data_type
              INTO alert_count_type
              FROM information_schema.columns
             WHERE table_name = 'users'
               AND column_name = 'alert_count_30d';

            IF alert_count_type IS NULL THEN
                ALTER TABLE users ADD COLUMN alert_count_30d INTEGER;
            ELSIF alert_count_type <> 'integer' THEN
                ALTER TABLE users ALTER COLUMN alert_count_30d DROP DEFAULT;
                ALTER TABLE users
                    ALTER COLUMN alert_count_30d TYPE INTEGER
                    USING CASE
                        WHEN alert_count_30d IS NULL THEN 0
                        WHEN alert_count_30d::text ~ '^[0-9]+$' THEN alert_count_30d::text::INTEGER
                        ELSE 0
                    END;
            END IF;

            UPDATE users
               SET alert_count_30d = COALESCE(alert_count_30d, 0);

            ALTER TABLE users ALTER COLUMN alert_count_30d SET DEFAULT 0;
            ALTER TABLE users ALTER COLUMN alert_count_30d SET NOT NULL;
        END$$;
        """
    )

    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "free_alert_consumed",
            existing_type=sa.Integer(),
            type_=sa.Integer(),
            nullable=False,
            server_default="0",
        )
        batch.alter_column(
            "alert_count_30d",
            existing_type=sa.Integer(),
            type_=sa.Integer(),
            nullable=False,
            server_default="0",
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "free_alert_consumed",
            existing_type=sa.Integer(),
            server_default=None,
        )
        batch.alter_column(
            "alert_count_30d",
            existing_type=sa.Integer(),
            server_default=None,
        )
