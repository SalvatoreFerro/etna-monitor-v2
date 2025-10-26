"""Ensure the partners table exists with required indexes."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202408010002_sync_partners"
down_revision = "202408010001_sync_plan_type"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    inspector = sa.inspect(bind)

    if not _table_exists("partners"):
        if dialect == "postgresql":
            op.execute(
                """
                CREATE TABLE IF NOT EXISTS partners (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT,
                    description TEXT,
                    website TEXT,
                    contact TEXT,
                    image_url TEXT,
                    lat DOUBLE PRECISION,
                    lon DOUBLE PRECISION,
                    verified BOOLEAN NOT NULL DEFAULT FALSE,
                    visible  BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        else:
            op.create_table(
                "partners",
                sa.Column("id", sa.Integer(), primary_key=True),
                sa.Column("name", sa.Text(), nullable=False),
                sa.Column("category", sa.Text(), nullable=True),
                sa.Column("description", sa.Text(), nullable=True),
                sa.Column("website", sa.Text(), nullable=True),
                sa.Column("contact", sa.Text(), nullable=True),
                sa.Column("image_url", sa.Text(), nullable=True),
                sa.Column("lat", sa.Float(), nullable=True),
                sa.Column("lon", sa.Float(), nullable=True),
                sa.Column(
                    "verified",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0" if dialect == "sqlite" else "false"),
                ),
                sa.Column(
                    "visible",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1" if dialect == "sqlite" else "true"),
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.func.now(),
                ),
            )
    else:
        if dialect == "postgresql":
            op.execute(
                "ALTER TABLE partners DROP CONSTRAINT IF EXISTS ck_partners_category"
            )
            op.execute(
                "ALTER TABLE partners ALTER COLUMN category DROP NOT NULL"
            )
            op.execute("ALTER TABLE partners ALTER COLUMN category DROP DEFAULT")
            op.execute(
                "ALTER TABLE partners ALTER COLUMN verified SET DEFAULT FALSE"
            )
            op.execute(
                "ALTER TABLE partners ALTER COLUMN visible SET DEFAULT TRUE"
            )

            columns = {col["name"]: col for col in inspector.get_columns("partners")}
            created_col = columns.get("created_at")
            if created_col and not getattr(created_col["type"], "timezone", False):
                op.execute(
                    """
                    ALTER TABLE partners
                    ALTER COLUMN created_at TYPE TIMESTAMPTZ
                    USING COALESCE(created_at, NOW()) AT TIME ZONE 'UTC'
                    """
                )

        indexes = {idx["name"] for idx in inspector.get_indexes("partners")}
        if "ix_partners_visible" in indexes and dialect == "postgresql":
            op.execute("DROP INDEX IF EXISTS ix_partners_visible")
        if "ix_partners_verified" in indexes and dialect == "postgresql":
            op.execute("DROP INDEX IF EXISTS ix_partners_verified")
        if "ix_partners_category" in indexes and dialect == "postgresql":
            op.execute("DROP INDEX IF EXISTS ix_partners_category")

    if dialect == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_partners_visible ON partners(visible)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_partners_verified_created ON partners(verified DESC, created_at DESC)"
        )
    else:
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_partners_visible ON partners(visible)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_partners_verified_created ON partners(verified DESC, created_at DESC)"
        )


def downgrade() -> None:
    if _table_exists("partners"):
        op.execute("DROP INDEX IF EXISTS idx_partners_visible")
        op.execute("DROP INDEX IF EXISTS idx_partners_verified_created")
        op.drop_table("partners")
