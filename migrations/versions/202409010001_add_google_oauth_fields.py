"""Add Google OAuth fields to the users table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202409010001_add_google_oauth_fields"
down_revision = "202409010000_extend_alembic_len"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {col["name"] for col in inspector.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in {index["name"] for index in inspector.get_indexes(table)}


def _has_unique_constraint(table: str, name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in {constraint["name"] for constraint in inspector.get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    new_columns: list[sa.Column] = []
    if not _has_column("users", "google_id"):
        new_columns.append(sa.Column("google_id", sa.String(length=255), nullable=True))
    if not _has_column("users", "name"):
        new_columns.append(sa.Column("name", sa.String(length=255), nullable=True))
    if not _has_column("users", "picture_url"):
        new_columns.append(sa.Column("picture_url", sa.String(length=512), nullable=True))

    if new_columns:
        with op.batch_alter_table("users", schema=None) as batch_op:
            for column in new_columns:
                batch_op.add_column(column)

    if dialect == "postgresql":
        if not _has_unique_constraint("users", "uq_users_google_id"):
            op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])
    else:
        if not _has_index("users", "ix_users_google_id_unique"):
            op.create_index(
                "ix_users_google_id_unique",
                "users",
                ["google_id"],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        if _has_unique_constraint("users", "uq_users_google_id"):
            op.drop_constraint("uq_users_google_id", "users", type_="unique")
    else:
        if _has_index("users", "ix_users_google_id_unique"):
            op.drop_index("ix_users_google_id_unique", table_name="users")

    drop_columns = [
        ("picture_url", sa.String(length=512)),
        ("name", sa.String(length=255)),
        ("google_id", sa.String(length=255)),
    ]

    columns_to_drop = [name for name, _ in drop_columns if _has_column("users", name)]

    if columns_to_drop:
        with op.batch_alter_table("users", schema=None) as batch_op:
            for column_name, _ in drop_columns:
                if column_name in columns_to_drop:
                    batch_op.drop_column(column_name)
