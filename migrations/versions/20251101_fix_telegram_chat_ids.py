"""Normalize Telegram chat identifiers to BIGINT and enforce positivity."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20251101_fix_telegram_chat_ids"
down_revision = "20251029_sync_admin_plan_and_sponsors"
branch_labels = None
depends_on = None


def _constraint_exists(table_name: str, constraint_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_check_constraints(table_name):
        if constraint.get("name") == constraint_name:
            return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE users
              ALTER COLUMN telegram_chat_id TYPE BIGINT
              USING NULLIF(trim(telegram_chat_id::text), '')::bigint;
            """
        )
        op.execute(
            """
            ALTER TABLE users
              ALTER COLUMN chat_id TYPE BIGINT
              USING NULLIF(trim(chat_id::text), '')::bigint;
            """
        )
        op.execute("UPDATE users SET telegram_chat_id = NULL WHERE telegram_chat_id = 0;")
        op.execute("UPDATE users SET chat_id = NULL WHERE chat_id = 0;")
        op.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_telegram_chat_id_positive'
              ) THEN
                ALTER TABLE users ADD CONSTRAINT ck_users_telegram_chat_id_positive
                  CHECK (telegram_chat_id IS NULL OR telegram_chat_id > 0);
              END IF;
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_chat_id_positive'
              ) THEN
                ALTER TABLE users ADD CONSTRAINT ck_users_chat_id_positive
                  CHECK (chat_id IS NULL OR chat_id > 0);
              END IF;
            END$$;
            """
        )
        return

    op.execute(sa.text("UPDATE users SET telegram_chat_id = NULL WHERE telegram_chat_id IS NULL"))
    op.execute(sa.text("UPDATE users SET chat_id = NULL WHERE chat_id IS NULL"))
    op.execute(sa.text("UPDATE users SET telegram_chat_id = NULL WHERE trim(CAST(telegram_chat_id AS TEXT)) = ''"))
    op.execute(sa.text("UPDATE users SET chat_id = NULL WHERE trim(CAST(chat_id AS TEXT)) = ''"))
    op.execute(sa.text("UPDATE users SET telegram_chat_id = NULL WHERE telegram_chat_id = 0"))
    op.execute(sa.text("UPDATE users SET chat_id = NULL WHERE chat_id = 0"))
    op.execute(
        sa.text(
            "UPDATE users SET telegram_chat_id = CAST(telegram_chat_id AS INTEGER) "
            "WHERE telegram_chat_id IS NOT NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE users SET chat_id = CAST(chat_id AS INTEGER) "
            "WHERE chat_id IS NOT NULL"
        )
    )

    with op.batch_alter_table("users", schema=None) as batch:
        batch.alter_column(
            "telegram_chat_id",
            existing_type=sa.String(length=64),
            type_=sa.BigInteger(),
            nullable=True,
        )
        batch.alter_column(
            "chat_id",
            existing_type=sa.String(length=50),
            type_=sa.BigInteger(),
            nullable=True,
        )
        if not _constraint_exists("users", "ck_users_telegram_chat_id_positive"):
            batch.create_check_constraint(
                "ck_users_telegram_chat_id_positive",
                "telegram_chat_id IS NULL OR telegram_chat_id > 0",
            )
        if not _constraint_exists("users", "ck_users_chat_id_positive"):
            batch.create_check_constraint(
                "ck_users_chat_id_positive",
                "chat_id IS NULL OR chat_id > 0",
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        if _constraint_exists("users", "ck_users_telegram_chat_id_positive"):
            op.drop_constraint("ck_users_telegram_chat_id_positive", "users", type_="check")
        if _constraint_exists("users", "ck_users_chat_id_positive"):
            op.drop_constraint("ck_users_chat_id_positive", "users", type_="check")
        op.execute(
            """
            ALTER TABLE users
              ALTER COLUMN telegram_chat_id TYPE VARCHAR(64)
              USING telegram_chat_id::text;
            """
        )
        op.execute(
            """
            ALTER TABLE users
              ALTER COLUMN chat_id TYPE VARCHAR(50)
              USING chat_id::text;
            """
        )
        return

    with op.batch_alter_table("users", schema=None) as batch:
        if _constraint_exists("users", "ck_users_telegram_chat_id_positive"):
            batch.drop_constraint("ck_users_telegram_chat_id_positive", type_="check")
        if _constraint_exists("users", "ck_users_chat_id_positive"):
            batch.drop_constraint("ck_users_chat_id_positive", type_="check")
        batch.alter_column(
            "telegram_chat_id",
            existing_type=sa.BigInteger(),
            type_=sa.String(length=64),
            nullable=True,
        )
        batch.alter_column(
            "chat_id",
            existing_type=sa.BigInteger(),
            type_=sa.String(length=50),
            nullable=True,
        )
