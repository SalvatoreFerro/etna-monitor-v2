"""Ensure admin/plan columns and sponsor tables exist"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20251029_sync_admin_plan_and_sponsors"
down_revision = (
    "20251028_enforce_integer_free_alert_consumed",
    "202410020002_add_telegram_fields_to_users",
)
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()


def _column_details(table_name: str, column_name: str) -> dict | None:
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(table_name):
        if column.get("name") == column_name:
            return column
    return None


def _index_exists(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _boolean_default(dialect: str, value: bool) -> sa.sql.elements.TextClause:
    if dialect == "sqlite":
        return sa.text("1" if value else "0")
    return sa.text("true" if value else "false")


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Normalize users.is_admin to be a proper BOOLEAN column with defaults.
    is_admin_details = _column_details("users", "is_admin")
    if is_admin_details is not None:
        if dialect == "postgresql":
            if not isinstance(is_admin_details["type"], sa.Boolean):
                op.execute(
                    """
                    ALTER TABLE users
                    ALTER COLUMN is_admin DROP DEFAULT;
                    """
                )
                op.execute(
                    """
                    ALTER TABLE users
                    ALTER COLUMN is_admin TYPE BOOLEAN
                    USING CASE
                        WHEN is_admin IS NULL THEN FALSE
                        WHEN is_admin IN ('t','true','y','yes','on') THEN TRUE
                        WHEN is_admin::text ~ '^[0-9]+$' THEN (is_admin::int <> 0)
                        ELSE FALSE
                    END
                    """
                )
            op.execute("UPDATE users SET is_admin = FALSE WHERE is_admin IS NULL")
            op.execute("ALTER TABLE users ALTER COLUMN is_admin SET DEFAULT FALSE")
            op.execute("ALTER TABLE users ALTER COLUMN is_admin SET NOT NULL")
        else:
            with op.batch_alter_table("users", schema=None) as batch:
                batch.alter_column(
                    "is_admin",
                    existing_type=is_admin_details["type"],
                    type_=sa.Boolean(),
                    nullable=False,
                    server_default=_boolean_default(dialect, False),
                )
            op.execute(
                "UPDATE users SET is_admin = 0 WHERE is_admin IS NULL"
                if dialect == "sqlite"
                else "UPDATE users SET is_admin = FALSE WHERE is_admin IS NULL"
            )

    # Ensure users.plan_type exists with NOT NULL DEFAULT 'free'.
    plan_details = _column_details("users", "plan_type")
    if plan_details is None:
        with op.batch_alter_table("users", schema=None) as batch:
            batch.add_column(
                sa.Column(
                    "plan_type",
                    sa.String(length=20),
                    nullable=False,
                    server_default="free",
                )
            )
    else:
        with op.batch_alter_table("users", schema=None) as batch:
            batch.alter_column(
                "plan_type",
                existing_type=plan_details["type"],
                type_=sa.String(length=20),
                nullable=False,
                server_default="free",
            )
        op.execute(
            """
            UPDATE users
            SET plan_type = 'free'
            WHERE plan_type IS NULL OR trim(plan_type) = ''
            """
        )

    # Ensure partners table exists for experience directory.
    if not _table_exists("partners"):
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
                server_default=_boolean_default(dialect, False),
            ),
            sa.Column(
                "visible",
                sa.Boolean(),
                nullable=False,
                server_default=_boolean_default(dialect, True),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    # Create sponsor banner tables when missing.
    if not _table_exists("sponsor_banners"):
        op.create_table(
            "sponsor_banners",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("image_url", sa.String(length=512), nullable=False),
            sa.Column("target_url", sa.String(length=512), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=_boolean_default(dialect, True),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    if not _table_exists("sponsor_banner_impressions"):
        op.create_table(
            "sponsor_banner_impressions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "banner_id",
                sa.Integer(),
                sa.ForeignKey("sponsor_banners.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "ts",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("page", sa.String(length=255), nullable=True),
            sa.Column("session_id", sa.String(length=64), nullable=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ip_hash", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_banner_impression_session",
            "sponsor_banner_impressions",
            ["banner_id", "session_id", "ts"],
        )
    elif not _index_exists("sponsor_banner_impressions", "ix_banner_impression_session"):
        op.create_index(
            "ix_banner_impression_session",
            "sponsor_banner_impressions",
            ["banner_id", "session_id", "ts"],
        )

    if not _table_exists("sponsor_banner_clicks"):
        op.create_table(
            "sponsor_banner_clicks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "banner_id",
                sa.Integer(),
                sa.ForeignKey("sponsor_banners.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "ts",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("page", sa.String(length=255), nullable=True),
            sa.Column("session_id", sa.String(length=64), nullable=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ip_hash", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_banner_click_session",
            "sponsor_banner_clicks",
            ["banner_id", "session_id", "ts"],
        )
    elif not _index_exists("sponsor_banner_clicks", "ix_banner_click_session"):
        op.create_index(
            "ix_banner_click_session",
            "sponsor_banner_clicks",
            ["banner_id", "session_id", "ts"],
        )


def downgrade() -> None:
    if _table_exists("sponsor_banner_clicks"):
        if _index_exists("sponsor_banner_clicks", "ix_banner_click_session"):
            op.drop_index(
                "ix_banner_click_session", table_name="sponsor_banner_clicks"
            )
        op.drop_table("sponsor_banner_clicks")

    if _table_exists("sponsor_banner_impressions"):
        if _index_exists(
            "sponsor_banner_impressions", "ix_banner_impression_session"
        ):
            op.drop_index(
                "ix_banner_impression_session",
                table_name="sponsor_banner_impressions",
            )
        op.drop_table("sponsor_banner_impressions")

    if _table_exists("sponsor_banners"):
        op.drop_table("sponsor_banners")

    if _table_exists("partners"):
        op.drop_table("partners")

    with op.batch_alter_table("users", schema=None) as batch:
        batch.alter_column("plan_type", server_default=None)
        batch.alter_column("is_admin", server_default=None)
