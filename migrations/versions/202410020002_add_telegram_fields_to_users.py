"""add telegram fields to users"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "202410020002_add_telegram_fields_to_users"
down_revision = "202410020001_align_users_schema_to_model"
branch_labels = None
depends_on = None


def _is_boolean(column: dict) -> bool:
    """Return True when the inspected column already reports a Boolean type."""

    return isinstance(column.get("type"), sa.Boolean)


def _is_bigint(column: dict) -> bool:
    """Return True when the inspected column already reports a BigInteger type."""

    return isinstance(column.get("type"), sa.BigInteger)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    dialect = bind.dialect.name

    columns = {column["name"]: column for column in inspector.get_columns("users")}

    telegram_chat_id = columns.get("telegram_chat_id")
    if telegram_chat_id is None:
        op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    elif dialect == "postgresql" and not _is_bigint(telegram_chat_id):
        op.alter_column("users", "telegram_chat_id", type_=sa.BigInteger())

    telegram_opt_in = columns.get("telegram_opt_in")
    if telegram_opt_in is None:
        op.add_column(
            "users",
            sa.Column(
                "telegram_opt_in",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    else:
        if dialect == "postgresql" and not _is_boolean(telegram_opt_in):
            op.alter_column("users", "telegram_opt_in", type_=sa.Boolean())

        op.execute(sa.text("UPDATE users SET telegram_opt_in = FALSE WHERE telegram_opt_in IS NULL"))

        alter_kwargs = {
            "existing_type": sa.Boolean(),
            "nullable": False,
            "server_default": sa.text("false"),
        }
        if dialect == "sqlite":
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.alter_column("telegram_opt_in", **alter_kwargs)
        else:
            op.alter_column("users", "telegram_opt_in", **alter_kwargs)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = {column["name"] for column in inspector.get_columns("users")}

    if "telegram_opt_in" in existing_columns:
        op.drop_column("users", "telegram_opt_in")
    if "telegram_chat_id" in existing_columns:
        op.drop_column("users", "telegram_chat_id")
