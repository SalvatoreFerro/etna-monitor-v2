"""Add tremor predictions table."""

from alembic import op
import sqlalchemy as sa

revision = "20260205_add_tremor_predictions"
down_revision = "20260110_add_badges_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tremor_predictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "horizon_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
        ),
        sa.Column("prediction", sa.String(length=8), nullable=False),
        sa.Column("resolves_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "resolved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("actual_outcome", sa.String(length=8), nullable=True),
        sa.Column(
            "points_awarded",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "prediction IN ('UP', 'DOWN', 'FLAT')",
            name="ck_tremor_predictions_prediction",
        ),
        sa.CheckConstraint("horizon_hours > 0", name="ck_tremor_predictions_horizon"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_tremor_predictions_user_id",
        "tremor_predictions",
        ["user_id"],
    )
    op.create_index(
        "ix_tremor_predictions_resolved",
        "tremor_predictions",
        ["resolved"],
    )
    op.create_index(
        "ix_tremor_predictions_resolves_at",
        "tremor_predictions",
        ["resolves_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tremor_predictions_resolves_at", table_name="tremor_predictions")
    op.drop_index("ix_tremor_predictions_resolved", table_name="tremor_predictions")
    op.drop_index("ix_tremor_predictions_user_id", table_name="tremor_predictions")
    op.drop_table("tremor_predictions")
