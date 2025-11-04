"""Ensure the ``theme_preference`` column exists with the expected definition."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251028_theme_pref"
down_revision = "20251029_sync_admin_plan_and_sponsors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("users")}

    column = columns.get("theme_preference")
    desired_type = sa.String(length=50)

    if column is None:
        op.add_column(
            "users",
            sa.Column(
                "theme_preference",
                desired_type,
                nullable=False,
                server_default="volcano_tech",
            ),
        )
    else:
        op.execute(
            sa.text(
                "UPDATE users "
                "SET theme_preference = 'volcano_tech' "
                "WHERE theme_preference IS NULL OR trim(theme_preference) = ''"
            )
        )

        alter_kwargs: dict[str, object] = {
            "existing_type": column["type"],
            "type_": desired_type,
            "nullable": False,
            "existing_nullable": column.get("nullable", True),
            "server_default": "volcano_tech",
        }

        default_clause = column.get("default")
        if default_clause is not None:
            alter_kwargs["existing_server_default"] = default_clause

        op.alter_column("users", "theme_preference", **alter_kwargs)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}

    if "theme_preference" in columns:
        op.drop_column("users", "theme_preference")
