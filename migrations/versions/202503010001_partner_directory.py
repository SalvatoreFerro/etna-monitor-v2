"""Partner directory tables

Revision ID: 202503010001
Revises: 202502140001_add_post_sanitized_html
Create Date: 2025-03-01 00:01:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "202503010001"
down_revision = "202502140001_add_post_sanitized_html"
branch_labels = None
depends_on = None


partner_status_enum = sa.Enum(
    "draft",
    "pending",
    "approved",
    "rejected",
    "expired",
    "disabled",
    name="partner_status",
)

subscription_status_enum = sa.Enum(
    "paid",
    "expired",
    name="partner_subscription_status",
)

payment_method_enum = sa.Enum(
    "paypal_manual",
    "cash",
    name="partner_payment_method",
)

waitlist_status_enum = sa.Enum(
    "new",
    "contacted",
    "converted",
    name="partner_waitlist_status",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect_name = bind.dialect.name

    json_type = sa.JSON()
    images_server_default = sa.text("'[]'")
    if dialect_name == "postgresql":
        json_type = postgresql.JSONB(astext_type=sa.Text())
        images_server_default = sa.text("'[]'::jsonb")

    if "partners" in inspector.get_table_names():
        op.drop_table("partners")

    partner_status_enum.create(bind, checkfirst=True)
    subscription_status_enum.create(bind, checkfirst=True)
    payment_method_enum.create(bind, checkfirst=True)
    waitlist_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "partner_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_slots", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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

    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("partner_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("short_desc", sa.String(length=280), nullable=True),
        sa.Column("long_desc", sa.Text(), nullable=True),
        sa.Column("website_url", sa.String(length=512), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("whatsapp", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("instagram", sa.String(length=255), nullable=True),
        sa.Column("facebook", sa.String(length=255), nullable=True),
        sa.Column("tiktok", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("logo_path", sa.String(length=255), nullable=True),
        sa.Column("hero_image_path", sa.String(length=255), nullable=True),
        sa.Column(
            "images_json",
            json_type,
            nullable=False,
            server_default=images_server_default,
        ),
        sa.Column("status", partner_status_enum, nullable=False, server_default="draft"),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
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
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_partners_category_status_featured_sort",
        "partners",
        ["category_id", "status", "featured", "sort_order"],
    )

    op.create_table(
        "partner_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "partner_id",
            sa.Integer(),
            sa.ForeignKey("partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("price_eur", sa.Numeric(8, 2), nullable=False),
        sa.Column(
            "status",
            subscription_status_enum,
            nullable=False,
            server_default="paid",
        ),
        sa.Column(
            "payment_method",
            payment_method_enum,
            nullable=False,
        ),
        sa.Column("payment_ref", sa.String(length=120), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("invoice_number", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_unique_constraint(
        "uq_partner_subscriptions_partner_year",
        "partner_subscriptions",
        ["partner_id", "year"],
    )

    op.create_table(
        "partner_waitlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("partner_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            waitlist_status_enum,
            nullable=False,
            server_default="new",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "partner_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "partner_id",
            sa.Integer(),
            sa.ForeignKey("partners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", json_type, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    categories_table = sa.table(
        "partner_categories",
        sa.column("slug", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("max_slots", sa.Integer()),
        sa.column("sort_order", sa.Integer()),
    )

    op.bulk_insert(
        categories_table,
        [
            {
                "slug": "guide",
                "name": "Guide autorizzate",
                "description": "Guide e accompagnatori autorizzati EtnaMonitor.",
                "max_slots": 10,
                "sort_order": 1,
            },
            {
                "slug": "hotel",
                "name": "Hotel",
                "description": "Selezione hotel partner.",
                "max_slots": 10,
                "sort_order": 2,
            },
            {
                "slug": "ristoranti",
                "name": "Ristoranti",
                "description": "Ristoranti consigliati EtnaMonitor.",
                "max_slots": 10,
                "sort_order": 3,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("partner_leads")
    op.drop_table("partner_waitlist")
    op.drop_constraint(
        "uq_partner_subscriptions_partner_year",
        "partner_subscriptions",
        type_="unique",
    )
    op.drop_table("partner_subscriptions")
    op.drop_index("ix_partners_category_status_featured_sort", table_name="partners")
    op.drop_table("partners")
    op.drop_table("partner_categories")

    waitlist_status_enum.drop(op.get_bind(), checkfirst=True)
    payment_method_enum.drop(op.get_bind(), checkfirst=True)
    subscription_status_enum.drop(op.get_bind(), checkfirst=True)
    partner_status_enum.drop(op.get_bind(), checkfirst=True)

    op.create_table(
        "partners",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("name", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("category", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("description", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("website", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("contact", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("image_url", sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column("lat", sa.FLOAT(), autoincrement=False, nullable=True),
        sa.Column("lon", sa.FLOAT(), autoincrement=False, nullable=True),
        sa.Column("verified", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column("visible", sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="partners_pkey"),
    )
