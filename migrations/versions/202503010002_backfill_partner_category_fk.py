"""Create partners.category_id with online-safe constraints.

Revision ID: 202503010002
Revises: 202503010001
Create Date: 2025-03-01 00:02:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "202503010002"
down_revision = "202503010001"
branch_labels = None
depends_on = None


CATEGORY_ID_INDEX = "ix_partners_category_id"
LEGACY_CATEGORY_INDEX = "ix_partners_category_legacy"
FOREIGN_KEY_NAME = "fk_partners_category"


def _is_postgres(bind: sa.engine.Connection) -> bool:
    return bind.dialect.name == "postgresql"


def _set_timeouts_if_supported(bind: sa.engine.Connection) -> None:
    if _is_postgres(bind):
        op.execute("SET lock_timeout = '5s'")
        op.execute("SET statement_timeout = '5min'")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "partners" not in inspector.get_table_names():
        return

    _set_timeouts_if_supported(bind)

    partner_columns = {column["name"] for column in inspector.get_columns("partners")}

    if "category_id" not in partner_columns:
        op.add_column("partners", sa.Column("category_id", sa.Integer(), nullable=True))

    existing_indexes = {index["name"] for index in inspector.get_indexes("partners")}

    if CATEGORY_ID_INDEX not in existing_indexes:
        if _is_postgres(bind):
            with op.get_context().autocommit_block():
                op.execute(
                    text(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {CATEGORY_ID_INDEX} "
                        "ON partners (category_id)"
                    )
                )
        else:
            op.create_index(CATEGORY_ID_INDEX, "partners", ["category_id"], unique=False)

    if "category" in partner_columns and LEGACY_CATEGORY_INDEX not in existing_indexes:
        if _is_postgres(bind):
            with op.get_context().autocommit_block():
                op.execute(
                    text(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {LEGACY_CATEGORY_INDEX} "
                        "ON partners (category)"
                    )
                )
        else:
            op.create_index(LEGACY_CATEGORY_INDEX, "partners", ["category"], unique=False)

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("partners")}
    if FOREIGN_KEY_NAME not in fk_names and inspector.has_table("partner_categories"):
        if _is_postgres(bind):
            op.execute(
                text(
                    "ALTER TABLE partners ADD CONSTRAINT "
                    f"{FOREIGN_KEY_NAME} FOREIGN KEY (category_id) "
                    "REFERENCES partner_categories(id) ON DELETE RESTRICT NOT VALID"
                )
            )
        else:
            op.create_foreign_key(
                FOREIGN_KEY_NAME,
                "partners",
                "partner_categories",
                ["category_id"],
                ["id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "partners" not in inspector.get_table_names():
        return

    _set_timeouts_if_supported(bind)

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("partners")}
    if FOREIGN_KEY_NAME in fk_names:
        if _is_postgres(bind):
            op.execute(
                text(
                    f"ALTER TABLE partners DROP CONSTRAINT IF EXISTS {FOREIGN_KEY_NAME}"
                )
            )
        else:
            op.drop_constraint(FOREIGN_KEY_NAME, "partners", type_="foreignkey")

    existing_indexes = {index["name"] for index in inspector.get_indexes("partners")}

    if CATEGORY_ID_INDEX in existing_indexes:
        if _is_postgres(bind):
            with op.get_context().autocommit_block():
                op.execute(
                    text(
                        f"DROP INDEX CONCURRENTLY IF EXISTS {CATEGORY_ID_INDEX}"
                    )
                )
        else:
            op.drop_index(CATEGORY_ID_INDEX, table_name="partners")

    if LEGACY_CATEGORY_INDEX in existing_indexes:
        if _is_postgres(bind):
            with op.get_context().autocommit_block():
                op.execute(
                    text(
                        f"DROP INDEX CONCURRENTLY IF EXISTS {LEGACY_CATEGORY_INDEX}"
                    )
                )
        else:
            op.drop_index(LEGACY_CATEGORY_INDEX, table_name="partners")

    partner_columns = {column["name"] for column in inspector.get_columns("partners")}
    if "category_id" in partner_columns:
        op.drop_column("partners", "category_id")
