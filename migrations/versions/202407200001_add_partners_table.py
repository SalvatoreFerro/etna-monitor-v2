"""Add partners table for Etna Experience"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "202407200001"
down_revision = "20240702_add_plan_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "category",
            sa.Text(),
            nullable=False,
            server_default="Altro",
        ),
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
            server_default=sa.text("false"),
        ),
        sa.Column(
            "visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "category IN ('Guide','Hotel','Ristorante','Tour','Altro')",
            name="ck_partners_category",
        ),
    )
    op.create_index("ix_partners_visible", "partners", ["visible"])
    op.create_index("ix_partners_verified", "partners", ["verified"])
    op.create_index("ix_partners_category", "partners", ["category"])


def downgrade() -> None:
    op.drop_index("ix_partners_category", table_name="partners")
    op.drop_index("ix_partners_verified", table_name="partners")
    op.drop_index("ix_partners_visible", table_name="partners")
    op.drop_table("partners")

