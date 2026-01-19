"""Add API access management tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20251230_add_api_access_tables"
down_revision = "20251226_add_copernicus_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("plan", sa.String(length=20), nullable=False, server_default="FREE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_api_clients_name"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("api_clients.id"), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=8), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_hash"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
    )
    op.create_index("ix_api_usage_ts", "api_usage", ["ts"])

    op.create_table(
        "api_usage_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("requests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("key_id", "date", name="uq_api_usage_daily_key_date"),
    )
    op.create_index("ix_api_usage_daily_date", "api_usage_daily", ["date"])

    op.create_table(
        "api_usage_minute",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("minute_bucket", sa.DateTime(), nullable=False),
        sa.Column("requests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "key_id",
            "minute_bucket",
            name="uq_api_usage_minute_key_bucket",
        ),
    )
    op.create_index(
        "ix_api_usage_minute_bucket",
        "api_usage_minute",
        ["minute_bucket"],
    )


def downgrade() -> None:
    op.drop_index("ix_api_usage_minute_bucket", table_name="api_usage_minute")
    op.drop_table("api_usage_minute")

    op.drop_index("ix_api_usage_daily_date", table_name="api_usage_daily")
    op.drop_table("api_usage_daily")

    op.drop_index("ix_api_usage_ts", table_name="api_usage")
    op.drop_table("api_usage")

    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_table("api_clients")
