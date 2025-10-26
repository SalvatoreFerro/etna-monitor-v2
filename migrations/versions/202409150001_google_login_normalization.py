"""Normalize user auth columns for Google login."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202409150001_google_login_normalization"
down_revision = "202409010001_add_google_oauth_fields"
branch_labels = None
depends_on = None


def _has_check_constraint(table: str, name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return name in {constraint["name"] for constraint in inspector.get_check_constraints(table)}


def upgrade() -> None:
    op.execute("UPDATE users SET email = LOWER(TRIM(email)) WHERE email IS NOT NULL")
    op.execute("UPDATE users SET plan_type = 'free' WHERE plan_type IS NULL")
    op.execute(
        "UPDATE users SET created_at = timezone('utc', now()) WHERE created_at IS NULL"
    )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=120),
            type_=sa.String(length=255),
            nullable=False,
        )
        batch_op.alter_column(
            "plan_type",
            existing_type=sa.String(length=20),
            nullable=False,
            server_default=sa.text("'free'"),
        )
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
            postgresql_using="timezone('utc', created_at)",
        )
        if not _has_check_constraint("users", "ck_users_email_lowercase"):
            batch_op.create_check_constraint(
                "ck_users_email_lowercase",
                "email = lower(email)",
            )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        if _has_check_constraint("users", "ck_users_email_lowercase"):
            batch_op.drop_constraint("ck_users_email_lowercase", type_="check")
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            nullable=True,
            server_default=sa.func.now(),
        )
        batch_op.alter_column(
            "plan_type",
            existing_type=sa.String(length=20),
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            type_=sa.String(length=120),
            nullable=False,
        )
