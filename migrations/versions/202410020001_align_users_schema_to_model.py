"""align users schema to model"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "202410020001_align_users_schema_to_model"
down_revision = "202409150001_google_login_normalization"
branch_labels = None
depends_on = None


def _existing_columns(inspector, table_name: str) -> set[str]:
    return {
        column["name"]
        for column in inspector.get_columns(table_name)
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_columns = _existing_columns(inspector, "users")

    def add_column_if_missing(column: sa.Column) -> None:
        if column.name not in existing_columns:
            op.add_column("users", column)

    add_column_if_missing(
        sa.Column(
            "plan_type",
            sa.String(length=20),
            server_default="free",
            nullable=False,
        )
    )
    add_column_if_missing(sa.Column("subscription_status", sa.String(length=32)))
    add_column_if_missing(sa.Column("subscription_id", sa.String(length=64)))
    add_column_if_missing(sa.Column("current_period_end", sa.DateTime()))
    add_column_if_missing(sa.Column("trial_end", sa.DateTime()))
    add_column_if_missing(sa.Column("billing_email", sa.String(length=255)))
    add_column_if_missing(sa.Column("company_name", sa.String(length=255)))
    add_column_if_missing(sa.Column("vat_id", sa.String(length=64)))
    add_column_if_missing(sa.Column("free_alert_event_id", sa.String(length=64)))
    add_column_if_missing(
        sa.Column(
            "free_alert_consumed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        )
    )
    add_column_if_missing(sa.Column("last_alert_sent_at", sa.DateTime()))
    add_column_if_missing(
        sa.Column(
            "alert_count_30d",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        )
    )
    add_column_if_missing(sa.Column("consent_ts", sa.DateTime()))
    add_column_if_missing(sa.Column("privacy_version", sa.String(length=16)))

    existing_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("users")
    }
    if "uq_users_email" not in existing_constraints:
        op.create_unique_constraint("uq_users_email", "users", ["email"])
    if "uq_users_google_id" not in existing_constraints:
        op.create_unique_constraint("uq_users_google_id", "users", ["google_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("users")
    }
    if "uq_users_google_id" in existing_constraints:
        op.drop_constraint("uq_users_google_id", "users", type_="unique")
    if "uq_users_email" in existing_constraints:
        op.drop_constraint("uq_users_email", "users", type_="unique")

    existing_columns = _existing_columns(inspector, "users")
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
        if column in existing_columns:
            op.drop_column("users", column)
