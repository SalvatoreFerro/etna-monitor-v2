"""Backfill partners.category_id using chunked updates and safe FK creation.

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


CHUNK_SIZE = 500
INDEX_NAME = "ix_partners_category_status_featured_sort"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "partners" not in inspector.get_table_names():
        return

    partner_columns = {col["name"] for col in inspector.get_columns("partners")}
    if "category_id" in partner_columns and any(
        constraint["referred_table"] == "partner_categories"
        for constraint in inspector.get_foreign_keys("partners")
    ):
        # The modern schema is already in place, nothing else to do.
        return

    if "category_id" not in partner_columns:
        op.add_column("partners", sa.Column("category_id", sa.Integer(), nullable=True))

    has_categories = inspector.has_table("partner_categories")
    if has_categories:
        category_rows = bind.execute(text("SELECT slug, id FROM partner_categories"))
        slug_to_id = {row["slug"]: row["id"] for row in category_rows.mappings()}

        if slug_to_id:
            while True:
                rows = bind.execute(
                    text(
                        """
                        SELECT id, category
                        FROM partners
                        WHERE category_id IS NULL AND category IS NOT NULL AND category <> ''
                        ORDER BY id
                        LIMIT :limit
                        """
                    ),
                    {"limit": CHUNK_SIZE},
                ).fetchall()

                if not rows:
                    break

                updates = []
                for partner_id, slug in rows:
                    category_id = slug_to_id.get(slug)
                    if category_id is None:
                        continue
                    updates.append({"partner_id": partner_id, "category_id": category_id})

                if updates:
                    bind.execute(
                        text(
                            """
                            UPDATE partners
                            SET category_id = :category_id
                            WHERE id = :partner_id
                            """
                        ),
                        updates,
                    )
    # Create or recreate the index in a safe way.
    existing_indexes = {index["name"] for index in inspector.get_indexes("partners")}
    if INDEX_NAME not in existing_indexes:
        if bind.dialect.name == "postgresql":
            with op.get_context().autocommit_block():
                op.execute(
                    text(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        f"{INDEX_NAME} ON partners (category_id, status, featured, sort_order)"
                    )
                )
        else:
            op.create_index(
                INDEX_NAME,
                "partners",
                ["category_id", "status", "featured", "sort_order"],
                unique=False,
            )

    if has_categories:
        remaining_nulls = 0
        remaining_nulls = bind.execute(
            text("SELECT COUNT(*) FROM partners WHERE category_id IS NULL")
        ).scalar_one()

        fk_names = {fk["name"] for fk in inspector.get_foreign_keys("partners")}
        if "fk_partners_category_id" not in fk_names:
            op.create_foreign_key(
                "fk_partners_category_id",
                "partners",
                "partner_categories",
                ["category_id"],
                ["id"],
                ondelete="RESTRICT",
            )

        if remaining_nulls == 0:
            op.alter_column(
                "partners",
                "category_id",
                existing_type=sa.Integer(),
                nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "partners" not in inspector.get_table_names():
        return

    fk_names = [fk["name"] for fk in inspector.get_foreign_keys("partners")]
    if "fk_partners_category_id" in fk_names:
        op.drop_constraint("fk_partners_category_id", "partners", type_="foreignkey")

    indexes = {index["name"] for index in inspector.get_indexes("partners")}
    if INDEX_NAME in indexes:
        if bind.dialect.name == "postgresql":
            with op.get_context().autocommit_block():
                op.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}"))
        else:
            op.drop_index(INDEX_NAME, table_name="partners")

    partner_columns = {col["name"] for col in inspector.get_columns("partners")}
    if "category_id" in partner_columns:
        op.drop_column("partners", "category_id")
