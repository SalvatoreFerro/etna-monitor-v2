"""Ensure the plan_type column exists as VARCHAR with a default."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202408010001_sync_plan_type"
down_revision = "202407200001"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    has_plan_type = _has_column("users", "plan_type")

    if not has_plan_type:
        if dialect == "postgresql":
            op.execute(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20)
                DEFAULT 'free'
                NOT NULL
                """
            )
        else:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "plan_type",
                        sa.String(length=20),
                        nullable=False,
                        server_default="free",
                    )
                )
    else:
        if dialect == "postgresql":
            op.execute(
                """
                ALTER TABLE users
                ALTER COLUMN plan_type TYPE VARCHAR(20)
                USING plan_type::text
                """
            )
            op.execute(
                """
                UPDATE users
                SET plan_type = 'free'
                WHERE plan_type IS NULL OR plan_type = ''
                """
            )
            op.execute(
                """ALTER TABLE users ALTER COLUMN plan_type SET DEFAULT 'free'"""
            )
            op.execute(
                """ALTER TABLE users ALTER COLUMN plan_type SET NOT NULL"""
            )
        else:
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.alter_column(
                    "plan_type",
                    existing_type=sa.String(length=20),
                    type_=sa.String(length=20),
                    nullable=False,
                    server_default="free",
                )
            op.execute(
                """
                UPDATE users
                SET plan_type = 'free'
                WHERE plan_type IS NULL OR plan_type = ''
                """
            )

    if dialect == "postgresql":
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'plan_type_enum'
                ) THEN
                    DROP TYPE plan_type_enum;
                END IF;
            END$$;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("ALTER TABLE users DROP COLUMN IF EXISTS plan_type")
        op.execute("DROP TYPE IF EXISTS plan_type_enum")
    else:
        if _has_column("users", "plan_type"):
            with op.batch_alter_table("users", schema=None) as batch_op:
                batch_op.drop_column("plan_type")
