"""align users schema to model"""

from alembic import op
import sqlalchemy as sa


revision = "202410020001_align_users_schema_to_model"
down_revision = "202409150001_google_login_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "plan_type",
            sa.String(length=20),
            server_default="free",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("subscription_status", sa.String(length=32)),
    )
    op.add_column(
        "users",
        sa.Column("subscription_id", sa.String(length=64)),
    )
    op.add_column(
        "users",
        sa.Column("current_period_end", sa.DateTime()),
    )
    op.add_column(
        "users",
        sa.Column("trial_end", sa.DateTime()),
    )
    op.add_column(
        "users",
        sa.Column("billing_email", sa.String(length=255)),
    )
    op.add_column(
        "users",
        sa.Column("company_name", sa.String(length=255)),
    )
    op.add_column(
        "users",
        sa.Column("vat_id", sa.String(length=64)),
    )
    op.add_column(
        "users",
        sa.Column("free_alert_event_id", sa.String(length=64)),
    )
    op.add_column(
        "users",
        sa.Column(
            "free_alert_consumed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_alert_sent_at", sa.DateTime()),
    )
    op.add_column(
        "users",
        sa.Column(
            "alert_count_30d",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("consent_ts", sa.DateTime()),
    )
    op.add_column(
        "users",
        sa.Column("privacy_version", sa.String(length=16)),
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_google_id", "users", type_="unique")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    for column in [
        "privacy_version",
        "consent_ts",
        "alert_count_30d",
        "last_alert_sent_at",
        "free_alert_consumed",
        "free_alert_event_id",
        "vat_id",
        "company_name",
        "billing_email",
        "trial_end",
        "current_period_end",
        "subscription_id",
        "subscription_status",
        "plan_type",
    ]:
        op.drop_column("users", column)
