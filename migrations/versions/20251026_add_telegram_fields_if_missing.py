"""add telegram fields to users (IF NOT EXISTS)"""

from alembic import op
from sqlalchemy import text

revision = "20251026_add_telegram_fields_if_missing"
down_revision = "202410020001_align_users_schema_to_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
    DO $$
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
    END$$;
            """
        )
    )


def downgrade() -> None:
    # Intentionally left blank: the schema guard migration is idempotent and non-destructive.
    pass
